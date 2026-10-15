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
import mix
import shorts

OUT = Path(os.getenv("WORK_DIR", "output"))
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() == "true"
FAKE = os.getenv("FAKE_RUN", "false").strip().lower() == "true"  # offline test: no APIs, fake song


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def fake_song(path, seconds=75):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"anoisesrc=color=pink:amplitude=0.4:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={seconds}", "-filter_complex",
                    "[0:a]lowpass=f=3000,tremolo=f=2:d=0.8[a];[a][1:a]amix=inputs=2", str(path)], check=True)


def build_shorts(plan, persona, pal, audio, timed, duration, landscape, portrait):
    """Two vertical Shorts cut from the song. Returns [(file, short_plan)]."""
    log("Making 2 Shorts...")
    vimg = shorts.vertical_image(landscape, portrait, OUT / "short_image.jpg")
    particles = OUT / "particles_v.mp4"
    fx.make_particles(particles, pal, w=1080, h=1920, n=70, seed=21)
    wins = shorts.pick_windows(plan["lyrics"], timed, duration, 2)
    files = []
    for i, (win, sp) in enumerate(zip(wins, plan["shorts"]), 1):
        out = OUT / f"short{i}.mp4"
        shorts.make_short(audio, timed, win, sp, persona, pal, vimg, particles, OUT, out, brain.CHANNEL_NAME)
        files.append((out, sp))
    particles.unlink(missing_ok=True)
    return files


def publish_time(hours):
    if hours <= 0:
        return None
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_shorts(api, files, plan, persona, long_id):
    delays = [float(x) for x in os.getenv("SHORTS_DELAY_HOURS", "3,9").split(",") if x.strip()]
    done = []
    for i, (f, sp) in enumerate(files):
        title = f"{sp['title']} #shorts"[:100]
        desc = shorts.short_description(sp, f"https://youtu.be/{long_id}")
        tags = ["shorts", "new song", "original song", persona["name"]] + plan["tags"][:8]
        when = publish_time(delays[i] if i < len(delays) else 0)
        try:
            try:
                sid = api.upload(f, title, desc, tags, publish_at=when)
            except Exception as e:
                log(f"Scheduled upload failed ({str(e)[:120]}), uploading right away")
                sid = api.upload(f, title, desc, tags)
            done.append({"id": sid, "title": sp["title"]})
        except Exception as e:
            log(f"Short {i + 1} failed to upload: {str(e)[:200]}")
    return done


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hist = brain.load_history()
    api = None
    if not FAKE:
        import ytapi
        api = ytapi.YT()
        log("Learning from past videos...")
        brain.update_metrics(hist, api)
    persona, genre, hook, short_hook = brain.choose(hist)
    context = "No data (test run)." if FAKE else brain.learning_context(hist, api)
    plan = brain.make_plan(persona, genre, hook, context, short_hook)
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
                                          "portrait_prompt": brain.portrait_prompt_for(persona, plan),
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
    short_files = []
    if os.getenv("MAKE_SHORTS", "true").strip().lower() == "true":
        try:
            short_files = build_shorts(plan, persona, pal, audio, timed, duration, bg, res.get("portrait") if not FAKE else None)
        except Exception as e:
            log(f"Shorts skipped: {type(e).__name__}: {str(e)[:300]}")

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
    if short_files:
        hist["videos"][-1]["short_hook"] = short_hook
        hist["videos"][-1]["shorts"] = upload_shorts(api, short_files, plan, persona, vid)
        brain.save_history(hist)
    log("Saved to history. Done.")


def fake_songs(n, seconds=22):
    import subprocess
    res = []
    for i in range(n):
        p = OUT / f"fake_song_{i}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"anoisesrc=color=pink:amplitude=0.4:duration={seconds}", "-f", "lavfi", "-i",
                        f"sine=frequency={200 + 40 * i}:duration={seconds}", "-filter_complex",
                        "[0:a]lowpass=f=3000,tremolo=f=2:d=0.8[a];[a][1:a]amix=inputs=2", str(p)], check=True)
        res.append({"i": i, "audio": str(p), "segments": []})
    return res


def main_mix():
    """Daily long video: a mix of many songs by one singer, with chapters, synced lyrics and a channel intro."""
    OUT.mkdir(parents=True, exist_ok=True)
    hist = brain.load_history()
    api = None
    if not FAKE:
        import ytapi
        api = ytapi.YT()
        log("Learning from past videos...")
        brain.update_metrics(hist, api)
    persona, genre, hook, _ = brain.choose(hist)
    bucket, minutes = brain.choose_length(hist)
    context = "No data (test run)." if FAKE else brain.learning_context(hist, api)
    plan = brain.make_mix_plan(persona, genre, hook, context, minutes)
    if FAKE:
        plan["songs"] = plan["songs"][:3]
    (OUT / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    log(f"Title: {plan['title']}")

    kaggle_res = None
    if FAKE:
        got = fake_songs(len(plan["songs"]))
    else:
        import kaggle_music
        log(f"Making {len(plan['songs'])} songs and the singer picture on Kaggle's free GPU (this takes a while)...")
        kaggle_res = kaggle_music.generate_song({
            "run_id": uuid.uuid4().hex, "budget_min": 200,
            "songs": [{k: s[k] for k in ("caption", "lyrics", "bpm", "duration")} for s in plan["songs"]],
            "image_prompt": brain.image_prompt_for(persona, plan), "seed": persona["seed"]}, OUT)
        got = kaggle_res["songs"]
    if len(got) < min(3, len(plan["songs"])):
        raise RuntimeError(f"Only {len(got)} songs were made, not enough for a mix")
    songs = [plan["songs"][g["i"]] for g in got]
    log(f"Songs ready: {len(songs)} of {len(plan['songs'])}")

    pal = fx.palette_for(persona["id"])
    hero = media.get_singer_image(persona, plan["image_prompt"], kaggle_res.get("image") if kaggle_res else None, OUT / "singer.jpg")
    audio = OUT / "mix_audio.mp3"
    durs, offsets = mix.build_audio([g["audio"] for g in got], OUT, audio)
    total = sum(durs)
    actual_min = max(1, round(total / 60))
    if brain.duration_label(minutes) in plan["title"]:
        plan["title"] = plan["title"].replace(brain.duration_label(minutes), brain.duration_label(actual_min))
    thumb = media.make_mix_thumbnail(hero, plan, persona["name"], OUT / "thumbnail.jpg", brain.CHANNEL_NAME, pal,
                                     brain.badge_label(actual_min))
    ass = OUT / "mix_lyrics.ass"
    mix.write_mix_ass(ass, songs, [g["segments"] for g in got], durs, offsets, total, plan["cta_question"], pal, brain.CHANNEL_NAME)
    video = OUT / "video.mp4"
    mix.render(hero, audio, ass, OUT, video, pal, brain.CHANNEL_NAME)
    chap = mix.chapters([s["song_title"] for s in songs], offsets)
    description = brain.build_mix_description(plan, persona, chap)
    (OUT / "description.txt").write_text(description, encoding="utf-8")

    if DRY_RUN or FAKE:
        log("Dry run: not uploading. Download the 'test-output' artifact and check video.mp4 + thumbnail.jpg")
        return
    try:
        vid = api.upload(video, plan["title"], description, plan["tags"])
    except Exception as e:
        log("UPLOAD FAILED. The finished video is saved in this run's Artifacts (test-output): download it and upload it "
            "in YouTube Studio with description.txt and thumbnail.jpg.")
        raise
    api.set_thumbnail(vid, thumb)
    api.comment(vid, plan["first_comment"])
    api.add_to_playlist(hist, persona["id"], f"{persona['name']} - Songs", vid)
    hist["videos"].append({"id": vid, "date": dt.datetime.now(dt.timezone.utc).isoformat(), "persona": persona["id"],
                           "genre": genre, "hook": hook, "len_bucket": bucket, "title": plan["title"],
                           "duration": round(total), "songs": len(songs)})
    brain.save_history(hist)
    log("Saved to history. Done.")


def _safe(label, fn, *a, **k):
    """Run a non-essential step; a failure is logged and never stops the run."""
    try:
        return fn(*a, **k)
    except Exception as e:
        log(f"(skipped: {label} failed: {type(e).__name__}: {str(e)[:200]})")
        return None


def main_loop():
    """Daily video: ONE song played for about an hour, with the channel intro, synced lyrics and lots of motion."""
    import seo
    OUT.mkdir(parents=True, exist_ok=True)
    hist = brain.load_history()
    api = None
    if not FAKE:
        import ytapi
        api = ytapi.YT()
        log("Learning from past videos...")
        _safe("learning", brain.update_metrics, hist, api)
    persona, genre, hook, _ = brain.choose(hist)
    target_min = int(os.getenv("LOOP_MINUTES", "60"))
    context = "No data (test run)." if FAKE else (_safe("learning context", brain.learning_context, hist, api) or "No data yet.")
    research = {} if FAKE else (_safe("keyword research", seo.research, api, genre, [hook]) or {})
    plan = brain.make_loop_plan(persona, genre, hook, context, research)
    (OUT / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    song = plan["song"]
    log(f"Song: {plan['song_title']} | {persona['name']} | {genre} | keyword: {plan.get('primary_keyword')}")

    kaggle_res = None
    if FAKE:
        got = fake_songs(1, seconds=int(os.getenv("FAKE_SONG_SECONDS", "20")))
    else:
        import kaggle_music
        for attempt in (1, 2, 3):
            try:
                log("Making the song and the singer picture on Kaggle's free GPU...")
                kaggle_res = kaggle_music.generate_song({
                    "run_id": uuid.uuid4().hex, "budget_min": 60,
                    "songs": [{k: song[k] for k in ("caption", "lyrics", "bpm", "duration")}],
                    "image_prompt": brain.image_prompt_for(persona, plan), "seed": persona["seed"]}, OUT)
                break
            except Exception as e:
                log(f"Kaggle attempt {attempt} failed: {str(e)[:300]}")
                if attempt == 3:
                    raise
                time.sleep(90)
        got = kaggle_res["songs"]
    segs = got[0]["segments"]
    log(f"Song ready ({len(segs)} sung phrases detected for lyric timing)")

    pal = fx.palette_for(persona["id"])
    hero = media.get_singer_image(persona, plan["image_prompt"], kaggle_res.get("image") if kaggle_res else None, OUT / "singer.jpg",
                                  bank=brain.DATA / "heroes" / f"{persona['id']}.jpg")
    audio = OUT / "loop_audio.mp3"
    xf = mix.loop_xf(got[0]["audio"], want=3.0)
    d, offsets, total = mix.build_loop_audio(got[0]["audio"], audio, target_min * 60, xf=xf)
    actual_min = max(1, round(total / 60))
    title = plan["title"].replace("[DURATION]", brain.duration_label(actual_min))[:100]

    # three simple thumbnail versions: A is uploaded; B and C are saved so you can run YouTube's Test & compare
    thumb = None
    for v in "ABC":
        r = _safe(f"thumbnail {v}", media.make_simple_thumbnail, hero, plan, OUT / f"thumbnail_{v}.jpg", persona["id"], v)
        if v == "A":
            thumb = r
    if thumb is None:
        thumb = OUT / "thumbnail_A.jpg"
        media.gradient(OUT / "thumbnail_A.jpg", [60, 60, 90])
    (OUT / "thumbnail.jpg").write_bytes(Path(thumb).read_bytes())

    # the video is just the character picture + one small sound wave + the channel intro
    media.make_art(hero, 1920, 1080, "V").convert("RGB").save(OUT / "art.png")
    video = OUT / "video.mp4"
    mix.render_still_safe(OUT / "art.png", audio, d, xf, pal, OUT, video, brain.CHANNEL_NAME)
    (OUT / "art.png").unlink(missing_ok=True)
    description = brain.build_loop_description(plan, persona)
    (OUT / "description.txt").write_text(f"{title}\n\n{description}\n\nTAGS: {', '.join(plan['tags'])}", encoding="utf-8")
    log(f"Title: {title}")

    if DRY_RUN or FAKE:
        log("Dry run: not uploading. Download the 'test-output' artifact and check video.mp4 + thumbnail files")
        return
    if (OUT / "uploaded.txt").exists():
        log("This video was already uploaded in an earlier try. Nothing more to do.")
        return
    try:
        vid = api.upload(video, title, description, plan["tags"])
    except Exception:
        log("UPLOAD FAILED. The finished video is saved in this run's Artifacts (test-output): download it and upload it "
            "in YouTube Studio with description.txt and thumbnail.jpg.")
        raise
    (OUT / "uploaded.txt").write_text(vid)
    log(f"UPLOADED: https://youtu.be/{vid}")
    _safe("thumbnail", api.set_thumbnail, vid, thumb)
    _safe("first comment", api.comment, vid, plan["first_comment"])
    _safe("playlist", api.add_to_playlist, hist, persona["id"], f"{persona['name']} - Songs", vid)
    hist["videos"].append({"id": vid, "date": dt.datetime.now(dt.timezone.utc).isoformat(), "persona": persona["id"],
                           "genre": genre, "hook": hook, "title": title, "duration": round(total), "songs": 1,
                           "keyword": plan.get("primary_keyword"), "thumb": "A"})
    _safe("history", brain.save_history, hist)
    log("Saved to history. Done.")


if __name__ == "__main__":
    try:
        {"song": main, "mix": main_mix}.get(os.getenv("MODE", "loop").strip().lower(), main_loop)()
    except Exception as e:
        log(f"FAILED: {type(e).__name__}: {e}")
        sys.exit(1)
