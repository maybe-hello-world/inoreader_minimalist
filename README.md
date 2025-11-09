# Inoreader triager

docker build -t inoreader-triager .

docker run -d \  
  -v /path/on/host/last_refresh_token.txt:/app/last_refresh_token.txt \  # persist the refresh token file
  -e INOREADER_CLIENT_ID=xxxxx \  
  -e INOREADER_CLIENT_SECRET=xxxxx \  
  -e INOREADER_REFRESH_TOKEN=xxxxx \  
  -e REFRESH_TOKEN_FILE=/app/last_refresh_token.txt \   # optional override for the persisted refresh token path
  -e INOREADER_APP_ID=your_app_id \        # the same as INOREADER_CLIENT_ID for oauth2  
  -e INOREADER_APP_KEY=your_app_key \      # the same as INOREADER_CLIENT_SECRET for oauth2  
  -e OPENAI_API_KEY=sk-xxxx \  
  -e POLL_EVERY_HOURS=6 \  
  -e HIGH_BORDER=6.5 \  
  -e MEDIUM_BORDER=5.0 \  
  -e PREF_PROMPT="$(cat prefs.txt)" \      # custom criteria  
  inoreader-triager  

or (example)

docker run -d --name inoreader --rm \
  -v /home/ubuntu/inoreader_minimalist/last_refresh_token.txt:/app/last_refresh_token.txt \
  --env-file .env \
  -e PREF_PROMPT="$(cat prefs.txt)" \
  inoreader-triager

## Refresh token persistence

The app now persists the most recent Inoreader refresh token to a file so container restarts reuse the latest value returned by the OAuth endpoint.

- By default the file is created next to `app.py` as `last_refresh_token.txt`. Bind-mount a host file to `/app/last_refresh_token.txt` (or update `REFRESH_TOKEN_FILE` accordingly) so the token survives container recreation.
- On first run the value from `INOREADER_REFRESH_TOKEN` seeds the file. Afterwards the app overwrites it whenever the API issues a replacement token.
- If neither the file nor the environment variable is present, the app exits with a clear error message.
