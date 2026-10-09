"""YouTube API helpers: stats, analytics, upload, thumbnail, comment, playlist."""
import datetime as dt
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


def log(m):
    print(m, flush=True)


class YT:
    def __init__(self):
        creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"].strip(),
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=os.environ["YT_CLIENT_ID"].strip(),
                            client_secret=os.environ["YT_CLIENT_SECRET"].strip())
        try:
            creds.refresh(Request())
        except Exception as e:
            raise RuntimeError("Google login failed. Re-check YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN "
                               f"(run get_token.py again). Details: {e}")
        self.yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        try:
            self.ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        except Exception:
            self.ya = None
        try:
            ch = self.yt.channels().list(part="snippet", mine=True).execute()
            log("Channel: " + ", ".join(c["snippet"]["title"] for c in ch.get("items", [])))
        except Exception:
            log("Could not read channel name")

    # ---------------- learning data ----------------
    def fetch_stats(self, ids):
        out = {}
        try:
            for i in range(0, len(ids), 50):
                r = self.yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
                for it in r.get("items", []):
                    s = it["statistics"]
                    out[it["id"]] = {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                                     "comments": int(s.get("commentCount", 0))}
        except Exception as e:
            log(f"[stats] failed: {type(e).__name__}")
        return out

    def fetch_analytics(self, ids, start_date):
        out = {}
        if not self.ya:
            return out
        try:
            r = self.ya.reports().query(
                ids="channel==MINE", startDate=start_date, endDate=dt.date.today().isoformat(),
                metrics="views,subscribersGained,averageViewPercentage,estimatedMinutesWatched",
                dimensions="video", filters="video==" + ",".join(ids[:200]), maxResults=200).execute()
            for row in r.get("rows", []):
                out[row[0]] = {"subs": row[2], "avg_view_pct": row[3], "minutes": row[4]}
        except Exception as e:
            log(f"[analytics] unavailable ({type(e).__name__}); using basic stats only. "
                "Enable 'YouTube Analytics API' in Google Cloud and re-run get_token.py to unlock retention data.")
        return out

    def top_comments(self, video_id):
        r = self.yt.commentThreads().list(part="snippet", videoId=video_id, order="relevance", maxResults=10).execute()
        return [it["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for it in r.get("items", [])]

    # ---------------- publishing ----------------
    def upload(self, video_path, title, description, tags):
        def body(synthetic):
            st = {"privacyStatus": os.getenv("UPLOAD_PRIVACY", "public"), "selfDeclaredMadeForKids": False}
            if synthetic:
                st["containsSyntheticMedia"] = True
            return {"snippet": {"title": title, "description": description, "tags": tags, "categoryId": "10",
                                "defaultLanguage": "en", "defaultAudioLanguage": "en"}, "status": st}

        def go(b):
            media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
            req = self.yt.videos().insert(part="snippet,status", body=b, media_body=media)
            resp = None
            while resp is None:
                status, resp = req.next_chunk()
                if status:
                    log(f"  uploaded {int(status.progress() * 100)}%")
            return resp
        try:
            try:
                resp = go(body(True))
            except HttpError as e:
                if e.resp.status != 400:
                    raise
                log("YouTube rejected the AI-label field, retrying without it")
                resp = go(body(False))
        except HttpError as e:
            raise RuntimeError(f"YouTube upload failed: HTTP {e.resp.status} {e.content[:400]}")
        vid = resp["id"]
        log(f"UPLOADED: https://youtu.be/{vid} (privacy: {resp.get('status', {}).get('privacyStatus')})")
        return vid

    def set_thumbnail(self, vid, path):
        try:
            self.yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(path))).execute()
            log("Thumbnail set OK")
        except Exception as e:
            log(f"Thumbnail not set (verify your channel at youtube.com/verify): {type(e).__name__}")

    def comment(self, vid, text):
        try:
            self.yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": vid, "topLevelComment": {
                "snippet": {"textOriginal": text}}}}).execute()
            log("First comment posted (pin it in YouTube Studio for best effect)")
        except Exception as e:
            log(f"Comment not posted: {type(e).__name__}")

    def add_to_playlist(self, hist, key, title, vid):
        try:
            pid = hist["playlists"].get(key)
            if not pid:
                r = self.yt.playlists().insert(part="snippet,status", body={
                    "snippet": {"title": title, "description": f"All songs: {title}"},
                    "status": {"privacyStatus": "public"}}).execute()
                pid = r["id"]
                hist["playlists"][key] = pid
            self.yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            log(f"Added to playlist: {title}")
        except Exception as e:
            log(f"Playlist step failed: {type(e).__name__}")
