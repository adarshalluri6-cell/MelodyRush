"""Friendly replies to new comments on our videos. Runs a few times a day, small limit, skips spam."""
import json
import os
import random
import re
import time
from pathlib import Path

import brain
import ytapi

STATE = brain.DATA / "replies.json"
MAX_PER_RUN = int(os.getenv("MAX_REPLIES", "8"))


def log(m):
    print(m, flush=True)


def main():
    api = ytapi.YT()
    yt = api.yt
    hist = brain.load_history()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"done": []}
    done = set(state["done"])
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    posted = 0
    for v in reversed(hist["videos"][-15:]):
        if posted >= MAX_PER_RUN:
            break
        try:
            threads = yt.commentThreads().list(part="snippet", videoId=v["id"], order="time", maxResults=25).execute()
        except Exception as e:
            log(f"could not read comments for {v['id']}: {type(e).__name__}")
            continue
        for it in threads.get("items", []):
            top = it["snippet"]["topLevelComment"]
            cid, sn = top["id"], top["snippet"]
            author = (sn.get("authorChannelId") or {}).get("value")
            if cid in done or author == me or it["snippet"].get("totalReplyCount", 0) > 0:
                continue
            text = re.sub(r"<[^>]+>", " ", sn.get("textDisplay", "")).strip()
            if not text or len(text) > 500 or re.search(r"https?://|www\.|\.com", text, re.I):
                done.add(cid)
                continue
            prompt = (f'You manage the YouTube comments for the music channel "{brain.CHANNEL_NAME}". A viewer wrote under the video '
                      f'"{v["title"]}":\n"{text}"\n\nWrite ONE short reply (1 or 2 sentences, under 220 characters) in warm, casual American English. '
                      "Thank them or react to what they said, answer any question, and when it fits end with a short friendly question "
                      "that keeps the chat going. Speak as the channel (use 'we'). At most one emoji, no hashtags, no links. "
                      "If they ask whether the music, voices or singers are AI, answer honestly that yes, the songs and singers are AI-generated. "
                      "If the comment is spam, rude, hateful, or asks for personal info, output exactly SKIP. Output only the reply text.")
            reply = brain.llm_text(prompt)
            done.add(cid)
            if not reply or reply.strip().upper().startswith("SKIP") or len(reply) > 400:
                continue
            try:
                yt.comments().insert(part="snippet", body={"snippet": {"parentId": cid, "textOriginal": reply.strip('"')}}).execute()
                posted += 1
                log(f"replied to: {text[:60]!r}")
            except Exception as e:
                log(f"reply failed: {type(e).__name__}")
            if posted >= MAX_PER_RUN:
                break
            time.sleep(random.randint(25, 70))
    state["done"] = list(done)[-3000:]
    brain.DATA.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))
    log(f"Done. Replies posted: {posted}")


if __name__ == "__main__":
    main()
