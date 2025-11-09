#!/usr/bin/env python3
import os, time, json, math, sys
import requests
from urllib.parse import quote

INOREADER_BASE = "https://www.inoreader.com"
STREAM_LABEL   = os.getenv("STREAM_LABEL", "significance_todo")
STREAM_ID      = f"user/-/label/{STREAM_LABEL}"
HIGH_TAG       = "user/-/label/significant"  # or "user/-/state/com.google/starred" to mark as read later
MEDIUM_TAG     = "user/-/label/medium"
READ_STATE     = "user/-/state/com.google/read"

POLL_EVERY_HOURS = float(os.getenv("POLL_EVERY_HOURS", "4"))
HIGH_BORDER      = float(os.getenv("HIGH_BORDER", "6.5"))
MEDIUM_BORDER    = float(os.getenv("MEDIUM_BORDER", "5.0"))
MAX_FETCH        = int(os.getenv("MAX_FETCH", "100"))
BATCH_SIZE       = int(os.getenv("BATCH_SIZE", "50"))
OPENAI_MODEL     = os.getenv("OPENAI_MODEL", "gpt-5-nano")
REFRESH_TOKEN_FILE = os.getenv("REFRESH_TOKEN_FILE", "last_refresh_token.txt")

PREF_PROMPT = os.getenv("PREF_PROMPT", """
Score the article's significance to me on the scale 0.0-10.0. The goal is to find news that would be considered important for me based either on global scale criteria or local keywords, so I either have to hear about them or want to hear about them.  
Articles rated below 3 usually cover sports, entertainment, and small local news. Articles with rating 5+ cover significant world events that shape the world.  
  
Use the next global scale criteria to determine if I have to hear about the article:  
1. **Scale:** how broadly the event affects humanity;  
2. **Impact:** how strong the immediate effect is;  
3. **Novelty:** how unique and unexpected is the event;  
4. **Potential:** how likely it is to shape the future;  
5. **Legacy:** how likely it is to be considered a turning point in history or a major milestone;  
6. **Positivity:** how positive is the event;  
7. **Credibility:** how trustworthy and reliable is the source.
""").strip()


def refresh_token_path():
    path = REFRESH_TOKEN_FILE
    if os.path.isabs(path):
        return path
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, path)


def save_refresh_token(token):
    # Persist the most recent refresh token so restarts reuse the correct value.
    if not token:
        return
    token = token.strip()
    path = refresh_token_path()
    try:
        with open(path, "w", encoding="ascii") as handle:
            handle.write(token)
    except Exception as exc:
        print(f"[auth] failed to persist refresh token: {exc}", file=sys.stderr)


def load_refresh_token():
    """Fetch the refresh token from disk or fall back to the environment."""
    path = refresh_token_path()
    if os.path.exists(path):
        with open(path, "r", encoding="ascii") as handle:
            token = handle.read().strip()
            if token:
                return token

    token = os.environ.get("INOREADER_REFRESH_TOKEN", "").strip()
    if token:
        save_refresh_token(token)
        return token

    raise RuntimeError(
        "Refresh token not found. Set INOREADER_REFRESH_TOKEN or create "
        f"a token file at {path}."
    )

# ---- OAuth2: refresh token -> access token
def refresh_inoreader_token():
    refresh_token = load_refresh_token()
    data = {
        "grant_type": "refresh_token",
        "client_id": os.environ["INOREADER_CLIENT_ID"],
        "client_secret": os.environ["INOREADER_CLIENT_SECRET"],
        "refresh_token": refresh_token,
    }
    r = requests.post(f"{INOREADER_BASE}/oauth2/token", data=data, timeout=30)
    r.raise_for_status()
    payload = r.json()
    tok = payload["access_token"]
    new_refresh = payload.get("refresh_token")
    save_refresh_token(new_refresh if new_refresh else refresh_token)
    return tok

def ino_headers():
    h = {
        "Authorization": f"Bearer {refresh_inoreader_token()}",
    }
    # App headers (recommended by Inoreader)
    app_id  = os.getenv("INOREADER_APP_ID")
    app_key = os.getenv("INOREADER_APP_KEY")
    if app_id and app_key:
        h["AppId"]  = app_id
        h["AppKey"] = app_key
    return h

# ---- Fetch unread items with the specific label
def fetch_unread_labeled_items(max_fetch=MAX_FETCH):
    url = f"{INOREADER_BASE}/reader/api/0/stream/contents/{quote(STREAM_ID, safe='')}"
    items = []
    params = {
        "n": max_fetch,
        # # exclude read items:
        # "xt": READ_STATE,
        # order: newest first by default; that's fine
    }
    headers = ino_headers()
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 401:
            headers = ino_headers()  # refresh and retry once
            r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items.extend(data.get("items", []))
        cont = data.get("continuation")
        if not cont:
            break
        params["c"] = cont
    return items

# ---- OpenAI scoring
def score_titles_openai(pairs):
    """
    pairs: list of dicts {id: <inoreader_item_id>, content: <content>}
    returns dict {id: score_float}
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type": "application/json",
    }

    # We send a compact JSON payload of IDs and content.
    articles = [{"id": p["id"], "content": p["content"]} for p in pairs]
    user_payload = {
        "preferences": PREF_PROMPT,
        "instruction": (
            "For each article, return a score from 0.0 to 10.0 based ONLY on the provided content. "
            "Higher = more relevant for my stated preferences. If unclear, give 0.0. "
            "Return JSON object: {\"scores\":[{\"id\":\"...\",\"score\":7.3}...]}. "
            "Use one decimal place."
        ),
        "articles": articles,
    }

    body = {
        "model": OPENAI_MODEL,
        "temperature": 1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful scorer. "
                    "Output strictly valid JSON with the key 'scores'. "
                    "No prose, no extra keys."
                ),
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }

    r = requests.post(url, headers=headers, json=body, timeout=90)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
        results = {}
        for row in parsed.get("scores", []):
            _id = row.get("id")
            sc = row.get("score")
            if _id is None or sc is None:
                continue
            # clamp & coerce
            try:
                sc = float(sc)
            except Exception:
                continue
            if math.isnan(sc) or math.isinf(sc):
                continue
            if sc < 0.0: sc = 0.0
            if sc > 10.0: sc = 10.0
            results[_id] = round(sc, 1)
        return results
    except Exception as e:
        print("OpenAI parse error. Raw content:", content, file=sys.stderr)
        raise

# ---- Edit-tag in a single request for multiple IDs (add star + remove label)
def edit_tag_batch(item_ids, add_tags=None, remove_tags=None):
    if not item_ids:
        return
    url = f"{INOREADER_BASE}/reader/api/0/edit-tag"
    headers = ino_headers()
    form = []
    for t in (add_tags or []):
        form.append(("a", t))
    for t in (remove_tags or []):
        form.append(("r", t))
    form += [("i", iid) for iid in item_ids]
    r = requests.post(url, headers=headers, data=form, timeout=30)
    if r.status_code == 401:
        headers = ino_headers()
        r = requests.post(url, headers=headers, data=form, timeout=30)
    r.raise_for_status()

def add_high_tag(item_ids):
    edit_tag_batch(item_ids, add_tags=[HIGH_TAG], remove_tags=[READ_STATE])

def add_medium_tag(item_ids):
    edit_tag_batch(item_ids, add_tags=[MEDIUM_TAG], remove_tags=[READ_STATE])

def remove_todo(item_ids):
    # remove the label for ALL processed items, regardless of score
    edit_tag_batch(item_ids, remove_tags=[STREAM_ID])

def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def run_once():
    print(f"[poll] fetching unread items tagged '{STREAM_LABEL}'…")
    items = fetch_unread_labeled_items()
    if not items:
        print("[poll] no items found.")
        return

    # convert IDs from base 16 to base 10
    for item in items:
        if not item["id"]:
            continue
        item_id = item["id"].split("/")[-1]
        item["id"] = str(int(item_id, base=16))

    # all fetched IDs (we'll remove the tag from ALL of these)
    all_ids = [it.get("id") for it in items if it.get("id")]

    # score only items that have content
    pairs = [{"id": it["id"], "content": (it.get("summary", {}).get("content") or "").strip()}
             for it in items if it.get("id") and (it.get("summary", {}).get("content") or "").strip()]

    high_ids = []
    medium_ids = []
    if pairs:
        for batch in chunked(pairs, BATCH_SIZE):
            print(f"[score] sending {len(batch)} contents to {OPENAI_MODEL}…")
            scores = score_titles_openai(batch)
            for p in batch:
                s = scores.get(p["id"], 0.0)
                if s >= HIGH_BORDER:
                    high_ids.append(p["id"])
                elif s >= MEDIUM_BORDER:
                    medium_ids.append(p["id"])
        print(f"[score] total ≥ {HIGH_BORDER}: {len(high_ids)}")
        print(f"[score] total ≥ {MEDIUM_BORDER}: {len(medium_ids)}")
    else:
        print("[score] no items to score.")

    # 1) star only the high ones (in chunks)
    if high_ids:
        for b in chunked(high_ids, BATCH_SIZE):
            add_high_tag(b)
    if medium_ids:
        for b in chunked(medium_ids, BATCH_SIZE):
            add_medium_tag(b)

    # 2) ALWAYS remove the todo label from ALL processed items
    if all_ids:
        print(f"[tag] removing '{STREAM_LABEL}' from {len(all_ids)} items…")
        for b in chunked(all_ids, BATCH_SIZE):
            remove_todo(b)
        print("[tag] removal done.")


def main():
    interval = max(POLL_EVERY_HOURS, 0.01)  # avoid zero
    print(f"Starting triager. Poll every {interval}h. High border ≥ {HIGH_BORDER}, medium border ≥ {MEDIUM_BORDER}. Stream: {STREAM_ID}")
    while True:
        try:
            run_once()
        except Exception as e:
            print("[error]", repr(e), file=sys.stderr)

        time.sleep(int(interval * 3600))

if __name__ == "__main__":
    main()
