# Auto Song Channel (US audience)
Learns from past videos, writes an original song with a fictional AI singer, makes a lyric video, and uploads it.

Secrets needed (Settings > Secrets and variables > Actions):
YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, GEMINI_API_KEY, KAGGLE_USERNAME, KAGGLE_KEY
Optional backup text AI: GROQ_API_KEY

Set your channel name in .github/workflows/daily.yml (CHANNEL_NAME).
Test: Actions > Make and upload song video > Run workflow (leave dry_run ticked).
Go live: untick dry_run once, then enable the schedule lines in daily.yml.
