import requests
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
r = requests.get("https://www.googleapis.com/youtube/v3/channels",
                 params={"part": "snippet", "mine": "true"},
                 headers={"Authorization": f"Bearer {creds.token}"})
print("\n" + "=" * 60)
print("Videos will be uploaded to this channel:")
for c in r.json().get("items", []):
    print("  ->", c["snippet"]["title"])
print("\nREFRESH TOKEN (copy into GitHub secret YT_REFRESH_TOKEN):\n")
print(creds.refresh_token)
print("=" * 60)
