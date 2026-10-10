#!/usr/bin/env python3
"""Daily pipeline: learn from past videos -> plan -> sing -> animate -> upload -> save."""
import datetime as dt
import json
import os
import sys
import time
import uuid
from pathlib import Path

import brain
import fx
import media

OUT = Path(os.getenv("WORK_DIR", "output"))
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() == "true"
FAKE = os.getenv("FAKE_RUN", "false").strip().lower() == "true"  # offline test: no APIs, fake song


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def fake_song(path, seconds=40):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"anoisesrc=color=pink:amplitude=0.4:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={seconds}", "-filter_complex",
                    "[0:a]lowpass=f=3000,tremolo=f=2:d=0.8[a];[a][1:a]amix=inputs=2", str(path)], check=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hist = brain.load_history()
    api = None
    if not FAKE:
        import ytapi
        api = ytapi.YT()
        log("Learning from past videos...")
        brain.update_metrics(hist, api)
    persona, genre, hook = brain.choose(hist)
    context = "No data (test run)." if FAKE else brain.learning_context(hist, api)
    plan = brain.make_plan(persona, genre, hook, context)
    log(f"Title: {plan['title']}")
    (OUT / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    segments, res = [], {}
    if FAKE:
        audio = str(OUT / "song.mp3")
        fake_song(audio)
    else:
        import kaggle_music
        log("Making the song on Kaggle's free GPU (this takes a while)...")
        res = kaggle_music.generate_song({"run_id": uuid.uuid4().hex, "caption": plan["caption"],
                                          "lyrics": plan["lyrics"], "bpm": plan["bpm"],
                                          "duration": plan["duration"],
                                          "image_prompt": brain.image_prompt_for(persona, plan),
                                          "seed": persona["seed"]}, OUT)
        audio, segments = res["audio"], res["segments"]
    log(f"Song ready ({len(segments)} vocal segments detected)")

    kaggle_img = res.get("image") if not FAKE else None
    bg = media.get_singer_image(persona, plan["image_prompt"], kaggle_img, OUT / "singer.jpg")
    pal = fx.palette_for(persona["id"])
    thumb = media.make_thumbnail(bg, plan["thumbnail_hook"], persona["name"], OUT / "thumbnail.jpg", brain.CHANNEL_NAME, pal)
    duration = media.probe_duration(audio)
    timed = media.align(plan["lyric_lines"], segments, duration)
    video = OUT / "video.mp4"
    media.build_video(bg, audio, timed, plan["cta_question"], OUT, video, plan["thumbnail_hook"], persona["name"],
                      plan["song_title"], brain.CHANNEL_NAME, pal)
    description = brain.build_description(plan, persona)
    (OUT / "description.txt").write_text(description, encoding="utf-8")

    if DRY_RUN or FAKE:
        log("Dry run: not uploading. Download the 'test-output' artifact and check video.mp4 + thumbnail.jpg")
        return
    vid = api.upload(video, plan["title"], description, plan["tags"])
    api.set_thumbnail(vid, thumb)
    api.comment(vid, plan["cta_question"])
    api.add_to_playlist(hist, persona["id"], f"{persona['name']} - Songs", vid)
    hist["videos"].append({"id": vid, "date": dt.datetime.now(dt.timezone.utc).isoformat(), "persona": persona["id"],
                           "genre": genre, "hook": hook, "title": plan["title"], "duration": round(duration)})
    brain.save_history(hist)
    log("Saved to history. Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FAILED: {type(e).__name__}: {e}")
        sys.exit(1)
