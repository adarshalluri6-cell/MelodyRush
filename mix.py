"""Long mix videos (10-90 minutes): many songs, chapters, synced lyrics, intro, fast render."""
import math
import random
import subprocess
import time
from pathlib import Path

import fx
import media

FPS = 24
LOOP_S = 30
XFADE_S = 1.0
INTRO_S = 4.0


def log(m):
    print(m, flush=True)


def run(cmd, cwd=None):
    subprocess.run(cmd, check=True, cwd=cwd)


# ----------------------------- audio -----------------------------------------
def build_audio(song_files, workdir, out_mp3):
    """Fade every song in/out softly, join them, return (durations, start_offsets)."""
    workdir = Path(workdir)
    wavs, durs = [], []
    for i, f in enumerate(song_files):
        d = media.probe_duration(f)
        w = workdir / f"mixpart_{i:02d}.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(f), "-af",
             f"afade=t=in:d=1.2,afade=t=out:st={max(d - 2.2, 0.5):.2f}:d=2.2", "-ar", "44100", "-ac", "2", str(w)])
        wavs.append(w)
        durs.append(media.probe_duration(w))
    lst = workdir / "mixparts.txt"
    lst.write_text("".join(f"file '{Path(w).resolve()}'\n" for w in wavs))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame",
         "-b:a", "192k", str(out_mp3)])
    for w in wavs:
        w.unlink(missing_ok=True)
    offsets, t = [], 0.0
    for d in durs:
        offsets.append(t)
        t += d
    log(f"Mix audio OK: {len(durs)} songs, {t / 60:.1f} minutes")
    return durs, offsets


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def chapters(titles, offsets):
    return [f"{stamp(o)} {i + 1:02d}. {t}" for i, (t, o) in enumerate(zip(titles, offsets))]


# ----------------------------- text on screen --------------------------------
def write_mix_ass(path, songs, segs_per_song, durs, offsets, total, cta_question, pal, brand):
    font = "Anton" if media.ANTON.exists() else "DejaVu Sans"
    bold = 0 if media.ANTON.exists() else -1
    acc = "&H00%02X%02X%02X" % (pal["rgb"][2], pal["rgb"][1], pal["rgb"][0])
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
            "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Lyric,{font},100,{acc},&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,1,0,1,7,3,2,100,100,150,1\n"
            f"Style: Now,{font},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,3,0,1,5,2,7,60,60,60,1\n"
            f"Style: NowSmall,{font},40,{acc},{acc},&H00000000,&H78000000,{bold},0,0,0,100,100,5,0,1,4,1,7,60,60,60,1\n"
            f"Style: Cta,{font},62,{acc},{acc},&H00000000,&H78000000,{bold},0,0,0,100,100,2,0,1,6,2,8,100,100,60,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev, ts = [], media._ts
    for i, s in enumerate(songs):
        off, dur = offsets[i], durs[i]
        # "Now playing" card slides in at the start of every song
        card = "{\\fad(250,400)\\move(-500,150,60,150,0,350)}"
        c0 = max(off + 0.6, INTRO_S + 0.3)
        ev.append(f"Dialogue: 2,{ts(c0)},{ts(c0 + 5.9)},NowSmall,,0,0,0,,{card}NOW PLAYING  {i + 1:02d}")
        ev.append(f"Dialogue: 2,{ts(c0)},{ts(c0 + 5.9)},Now,,0,0,0,,{{\\fad(250,400)\\move(-500,200,60,200,0,420)}}{media._clean(s['song_title'].upper())}")
        timed = media.align(s["lyric_lines"], segs_per_song[i], dur)
        for text, a, b in timed:
            if off + a < INTRO_S + 0.2:
                continue
            pop = "{\\an2\\fad(110,170)\\fscx88\\fscy88\\blur1.4\\t(0,200,\\fscx100\\fscy100)}"
            ev.append(f"Dialogue: 0,{ts(off + a)},{ts(off + b)},Lyric,,0,0,0,,{pop}{media._karaoke(text, b - a)}")
    # engagement prompts: early, then every ~9 minutes, and near the end
    marks = [(25, "LIKE if this vibe is for you"), (70, "SUBSCRIBE for a new mix every day")]
    t = 540
    while t < total - 60:
        marks.append((t, random.choice([media._clean(cta_question), "LIKE and SUBSCRIBE for more songs", "COMMENT your favorite track number"])))
        t += 540
    marks.append((max(total - 40, 90), media._clean(cta_question)))
    for t0, text in marks:
        ev.append(f"Dialogue: 3,{ts(t0)},{ts(t0 + 6)},Cta,,0,0,0,,{{\\fad(300,400)\\move(960,-80,960,60,0,380)}}{text}")
    Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ----------------------------- video render ----------------------------------
def _enc(extra=None):
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)] + (extra or [])


def render(hero, audio, ass, workdir, out, pal, brand):
    workdir = Path(workdir).resolve()
    hero, audio, out = str(Path(hero).resolve()), str(Path(audio).resolve()), str(Path(out).resolve())
    total = media.probe_duration(audio)
    T0 = time.time()
    # 1) 30-second seamless loop: hero picture, gentle breathing zoom, sparkles, corner emblem
    log("Making the looping background...")
    part = workdir / "loop_particles.mp4"
    fx.make_particles(part, pal, w=1920, h=1080, seconds=10, fps=FPS, n=70, seed=7)
    fx.watermark(1920, 1080, pal).save(workdir / "watermark.png")
    frames = LOOP_S * FPS
    loop = workdir / "loop.mp4"
    fc = (f"[0:v]scale=2880:1620:flags=lanczos,zoompan=z='1.05+0.035*sin(6.2832*on/{frames})':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d={frames}:s=1920x1080:fps={FPS},eq=saturation=1.05:contrast=1.04,format=gbrp[bg];"
          "[1:v]scale=1920:1080,format=gbrp[p];[bg][p]blend=all_mode=screen:shortest=1,format=rgba[m];"
          "[m][2:v]overlay=0:0:format=auto,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", hero, "-stream_loop", "-1", "-i", str(part), "-i", str(workdir / "watermark.png"),
         "-filter_complex", fc, "-map", "[v]", "-t", str(LOOP_S), *_enc(), str(loop)])
    # 2) intro, cross-faded into the first loop, so it disappears smoothly
    log("Making the intro...")
    intro = workdir / "intro.mp4"
    fx.make_intro(intro, brand, pal, seconds=INTRO_S, fps=FPS)
    head = workdir / "head.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(intro), "-i", str(loop), "-filter_complex",
         f"[0:v][1:v]xfade=transition=fade:duration={XFADE_S}:offset={INTRO_S - XFADE_S},format=yuv420p[v]",
         "-map", "[v]", *_enc(), str(head)])
    head_len = INTRO_S + LOOP_S - XFADE_S            # = exactly one loop later, so the loop continues seamlessly
    reps = max(1, math.ceil((total - head_len) / LOOP_S) + 1)
    lst = workdir / "loops.txt"
    lst.write_text(f"file '{head}'\n" + "".join(f"file '{loop}'\n" for _ in range(reps)))
    # 3) one final pass: equalizer + synced lyrics + audio
    log(f"Background ready ({time.time() - T0:.0f}s). Rendering the final video ({total / 60:.0f} minutes)...")
    T1 = time.time()
    fontsdir = str(media.FONTS.resolve()) if media.FONTS.exists() else "/usr/share/fonts"
    fc2 = ("[1:a]asplit=2[aout][aeq];"
           f"[aeq]showfreqs=s=96x26:mode=bar:ascale=sqrt:fscale=log:win_size=2048:rate={FPS}:averaging=3:colors={pal['hex']},"
           "format=rgba,scale=1920:260:flags=neighbor,drawgrid=width=20:height=10:thickness=3:color=black,"
           "colorkey=0x000000:0.30:0.12[eq];"
           "[0:v][eq]overlay=0:820:format=auto:enable='gte(t,3.2)'[v1];"
           f"[v1]subtitles={Path(ass).name}:fontsdir={fontsdir},format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", audio,
         "-filter_complex", fc2, "-map", "[v]", "-map", "[aout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{total:.2f}",
         "-movflags", "+faststart", out], cwd=str(Path(ass).parent))
    for f in (loop, intro, head, part, lst, workdir / "watermark.png"):
        Path(f).unlink(missing_ok=True)
    log(f"Video OK ({Path(out).stat().st_size / 1e6:.0f} MB), final pass {time.time() - T1:.0f}s for {total:.0f}s of video")
    return total
