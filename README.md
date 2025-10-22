# Inoreader triager

docker build -t inoreader-triager .

docker run -d \  
  -e INOREADER_CLIENT_ID=xxxxx \  
  -e INOREADER_CLIENT_SECRET=xxxxx \  
  -e INOREADER_REFRESH_TOKEN=xxxxx \  
  -e INOREADER_APP_ID=your_app_id \        # the same as INOREADER_CLIENT_ID for oauth2  
  -e INOREADER_APP_KEY=your_app_key \      # the same as INOREADER_CLIENT_SECRET for oauth2  
  -e OPENAI_API_KEY=sk-xxxx \  
  -e POLL_EVERY_HOURS=6 \  
  -e HIGH_BORDER=6.5 \  
  -e MEDIUM_BORDER=5.0 \  
  -e PREF_PROMPT="$(cat prefs.txt)" \      # custom criteria  
  inoreader-triager  

or 

docker run -d --env-file .env -e PREF_PROMPT="$(cat prefs.txt)" inoreader-triager
