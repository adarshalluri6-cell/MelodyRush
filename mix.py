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


def loop_xf(song, want=1.5):
    """Cross-fade length that makes the repeat period an exact number of video frames (so lyrics never drift)."""
    d = media.probe_duration(song)
    return d - round((d - want) * FPS) / FPS


def build_loop_audio(song, out_mp3, target_s, xf=1.5):
    """Repeat one song until about target_s seconds, joined with smooth cross-fades. Returns (song_len, offsets, total)."""
    d = media.probe_duration(song)
    n = max(3, round((target_s - xf) / (d - xf)))
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for _ in range(n):
        cmd += ["-i", str(song)]
    chain, prev = "", "[0:a]"
    for i in range(1, n):
        chain += f"{prev}[{i}:a]acrossfade=d={xf}:c1=tri:c2=tri[a{i}];"
        prev = f"[a{i}]"
    total = n * d - (n - 1) * xf
    chain += f"{prev}loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:st=0:d=1.2,afade=t=out:st={total - 3:.2f}:d=3[aout]"
    run(cmd + ["-filter_complex", chain, "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", str(out_mp3)])
    offsets = [k * (d - xf) for k in range(n)]
    log(f"Audio OK: the song x{n}, {total / 60:.1f} minutes")
    return d, offsets, total


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def chapters(titles, offsets):
    return [f"{stamp(o)} {i + 1:02d}. {t}" for i, (t, o) in enumerate(zip(titles, offsets))]


# ----------------------------- text on screen --------------------------------
def _bgr(rgb):
    return "&H00%02X%02X%02X" % (rgb[2], rgb[1], rgb[0])


def write_mix_ass(path, songs, segs_per_song, durs, offsets, total, cta_question, pal, brand, lyric_rgb=(255, 120, 190), loop=False):
    font = "Anton" if media.ANTON.exists() else "DejaVu Sans"
    bold = 0 if media.ANTON.exists() else -1
    acc, sung = _bgr(pal["rgb"]), _bgr(lyric_rgb)
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
            "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Lyric,{font},104,{sung},&H00FFFFFF,&H00180C10,&H78000000,{bold},0,0,0,100,100,1,0,1,6,3,2,100,100,150,1\n"
            f"Style: Glow,{font},104,{sung},{sung},{sung},&H00000000,{bold},0,0,0,100,100,1,0,1,14,0,2,100,100,150,1\n"
            f"Style: Now,{font},64,&H00FFFFFF,&H00FFFFFF,&H00180C10,&H78000000,{bold},0,0,0,100,100,3,0,1,5,2,7,60,60,60,1\n"
            f"Style: NowSmall,{font},40,{acc},{acc},&H00180C10,&H78000000,{bold},0,0,0,100,100,5,0,1,4,1,7,60,60,60,1\n"
            f"Style: Cta,{font},62,&H00FFFFFF,&H00FFFFFF,&H00180C10,&H78000000,{bold},0,0,0,100,100,2,0,1,6,2,8,100,100,60,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev, ts = [], media._ts
    segs_cache = {}
    for i, s in enumerate(songs):
        off, dur = offsets[i], durs[i]
        if not loop or i % 4 == 0:
            c0 = max(off + 0.6, INTRO_S + 0.3)
            label = "NOW PLAYING" if loop else f"NOW PLAYING  {i + 1:02d}"
            ev.append(f"Dialogue: 2,{ts(c0)},{ts(c0 + 5.9)},NowSmall,,0,0,0,,{{\\fad(250,400)\\move(-500,150,60,150,0,350)}}{label}")
            ev.append(f"Dialogue: 2,{ts(c0)},{ts(c0 + 5.9)},Now,,0,0,0,,{{\\fad(250,400)\\move(-500,200,60,200,0,420)}}{media._clean(s['song_title'].upper())}")
        key = id(segs_per_song[i])
        if key not in segs_cache:
            segs_cache[key] = media.align(s["lyric_lines"], segs_per_song[i], dur)
        for text, a, b in segs_cache[key]:
            if off + a < INTRO_S + 0.2:
                continue
            slide = "\\an2\\move(960,975,960,930,0,230)\\fad(110,190)\\fscx90\\fscy90\\t(0,230,\\fscx100\\fscy100)"
            ev.append(f"Dialogue: 0,{ts(off + a)},{ts(off + b)},Glow,,0,0,0,,{{{slide}\\blur14\\1a&HFF&\\3a&H60&}}{media._wrap_line(text)}")
            ev.append(f"Dialogue: 1,{ts(off + a)},{ts(off + b)},Lyric,,0,0,0,,{{{slide}\\blur1.2}}{media._karaoke(text, b - a)}")
    marks = [(25, "LIKE if this song hits you"), (70, "SUBSCRIBE for a new song every day")]
    t = 540
    while t < total - 60:
        marks.append((t, random.choice([media._clean(cta_question), "LIKE and SUBSCRIBE for more songs", "COMMENT your favorite line"])))
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
    fx.light_band(workdir / "band.png", pal)
    fc = (f"[0:v]scale=3072:1728:flags=lanczos,zoompan=z='1.06+0.04*sin(6.2832*on/{frames})':"
          f"x='iw/2-(iw/zoom/2)+70*sin(6.2832*on/{frames})':y='ih/2-(ih/zoom/2)+36*sin(2*6.2832*on/{frames})'"
          f":d={frames}:s=1920x1080:fps={FPS},format=gbrp[bg];"
          "[1:v]scale=1920:1080,format=gbrp[p];[bg][p]blend=all_mode=screen:shortest=1,format=rgba[m];"
          "[m][3:v]overlay=x='-760+(W+760)*mod(t,15)/15':y=0:format=auto[m2];"
          "[m2][2:v]overlay=0:0:format=auto,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", hero, "-stream_loop", "-1", "-i", str(part), "-i", str(workdir / "watermark.png"),
         "-loop", "1", "-framerate", str(FPS), "-i", str(workdir / "band.png"),
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
         "-filter_complex", fc2, "-map", "[v]", "-map", "[aout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-maxrate", "2200k", "-bufsize", "4400k",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{total:.2f}",
         "-movflags", "+faststart", out], cwd=str(Path(ass).parent))
    for f in (loop, intro, head, part, lst, workdir / "watermark.png", workdir / "band.png"):
        Path(f).unlink(missing_ok=True)
    log(f"Video OK ({Path(out).stat().st_size / 1e6:.0f} MB), final pass {time.time() - T1:.0f}s for {total:.0f}s of video")
    return total


# =====================================================================================================
# ONE-SONG LOOP VIDEO: render ONE cycle (one pass of the song) with everything on it, then repeat it.
# Premium look = the thumbnail artwork in motion: slow zoom, sparkles, light sweep, bar equalizer, synced lyrics.
# =====================================================================================================
EQ_W, EQ_H, EQ_X, EQ_Y = 780, 170, 1040, 705


def write_cycle_ass(path, song, segs, d, cycle_len, cta_question, pal, lyric_rgb, skip_before=0.0):
    font_n = "Anton" if media.ANTON.exists() else "DejaVu Sans"
    bold = 0 if media.ANTON.exists() else -1
    acc, sung = _bgr(pal["rgb"]), _bgr(lyric_rgb)
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
            "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Lyric,{font_n},74,{sung},&H00FFFFFF,&H00180C10,&H78000000,{bold},0,0,0,100,100,1,0,1,5,3,2,700,30,46,1\n"
            f"Style: Glow,{font_n},74,{sung},{sung},{sung},&H00000000,{bold},0,0,0,100,100,1,0,1,12,0,2,700,30,46,1\n"
            f"Style: Cta,{font_n},50,&H00FFFFFF,&H00FFFFFF,{acc},&H78000000,{bold},0,0,0,100,100,2,0,1,5,2,9,60,60,50,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev, ts = [], media._ts
    for text, a, b in media.align(song["lyric_lines"], segs, d):
        if a < skip_before or a >= cycle_len - 0.5:
            continue
        b = min(b, cycle_len - 0.05)
        slide = "\\an2\\move(1310,1030,1310,1004,0,230)\\fad(110,190)\\fscx92\\fscy92\\t(0,230,\\fscx100\\fscy100)"
        ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Glow,,0,0,0,,{{{slide}\\blur12\\1a&HFF&\\3a&H60&}}{media._wrap_line(text)}")
        ev.append(f"Dialogue: 1,{ts(a)},{ts(b)},Lyric,,0,0,0,,{{{slide}\\blur1.2}}{media._karaoke(text, b - a)}")
    for t0, text in ((cycle_len * 0.33, "LIKE & SUBSCRIBE  \u2665"), (cycle_len * 0.70, media._clean(cta_question).upper())):
        if t0 >= skip_before:
            ev.append(f"Dialogue: 3,{ts(t0)},{ts(t0 + 4.5)},Cta,,0,0,0,,{{\\fad(300,500)\\move(1860,-60,1860,50,0,380)}}{text}")
    Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def _cycle_encode(extra=None):
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-maxrate", "1900k", "-bufsize", "3800k", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0"] + (extra or [])


def _compose_cycle(wd, art, title, particles, band, eq, ass, cyc, pal, out, use_eq, use_subs, intro=None, limit=None):
    frames = int(round(cyc * FPS))
    kz = max(1, round(cyc / 30))                       # zoom/drift cycles per pass: seamless when the pass repeats
    P = cyc / max(2, math.ceil(cyc / 15))              # light sweep period (divides the pass exactly)
    fontsdir = str(media.FONTS.resolve()) if media.FONTS.exists() else "/usr/share/fonts"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(art), "-stream_loop", "-1", "-i", str(particles),
           "-loop", "1", "-framerate", str(FPS), "-t", f"{cyc:.3f}", "-i", str(band),
           "-loop", "1", "-framerate", str(FPS), "-t", f"{cyc:.3f}", "-i", str(title)]
    n_in = 4
    if use_eq:
        cmd += ["-i", str(eq)]
        eq_i, n_in = n_in, n_in + 1
    if intro:
        cmd += ["-i", str(intro)]
        in_i, n_in = n_in, n_in + 1
    fc = (f"[0:v]scale=3072:1728:flags=lanczos,zoompan=z='1.06+0.04*sin(6.2832*{kz}*on/{frames})':"
          f"x='iw/2-(iw/zoom/2)+70*sin(6.2832*{kz}*on/{frames})':y='ih/2-(ih/zoom/2)+36*sin(2*6.2832*{kz}*on/{frames})'"
          f":d={frames}:s=1920x1080:fps={FPS},format=gbrp[bg];"
          "[1:v]scale=1920:1080,format=gbrp[p];[bg][p]blend=all_mode=screen:shortest=1,format=rgba[m];"
          f"[m][2:v]overlay=x='-760+(W+760)*mod(t,{P:.4f})/{P:.4f}':y=0:format=auto:shortest=1[m2];"
          "[m2][3:v]overlay=0:0:format=auto:shortest=1[m3]")
    last = "m3"
    if use_eq:
        fc += (f";[{last}]split[a][b];[b]crop={EQ_W}:{EQ_H}:{EQ_X}:{EQ_Y},format=gbrp[c];[{eq_i}:v]format=gbrp[e];"
               f"[c][e]blend=all_mode=screen:shortest=1[d];[a][d]overlay={EQ_X}:{EQ_Y}:format=auto:shortest=1[v1]")
        last = "v1"
    if use_subs:
        fc += f";[{last}]subtitles={Path(ass).name}:fontsdir={fontsdir}[v2]"
        last = "v2"
    if intro:
        fc += (f";[{in_i}:v]format=yuva420p,fade=t=out:st=2.6:d=1.4:alpha=1[ii];"
               f"[{last}][ii]overlay=0:0:enable='lt(t,4.0)':format=auto[v3]")
        last = "v3"
    fc += f";[{last}]format=yuv420p[v]"
    run(cmd + ["-filter_complex", fc, "-map", "[v]", "-t", f"{(limit or cyc):.3f}", *_cycle_encode(), str(out)], cwd=str(Path(ass).parent))


def render_loop(art_png, title_png, audio, d, xf, song, segs, plan, pal, lyric_rgb, workdir, out, brand):
    workdir = Path(workdir).resolve()
    art_png, title_png, audio, out = (str(Path(x).resolve()) for x in (art_png, title_png, audio, out))
    total = media.probe_duration(audio)
    cyc = d - xf
    T0 = time.time()
    log(f"Making one {cyc:.0f}s cycle (the whole video is this cycle repeated)...")
    particles, band, eq, intro = workdir / "particles.mp4", workdir / "band.png", workdir / "eq.mp4", workdir / "intro.mp4"
    fx.make_particles(particles, pal, w=1920, h=1080, seconds=10, fps=FPS, n=64, seed=7)
    fx.light_band(band, pal)
    have_eq = True
    try:
        fx.render_eq(audio, cyc, cyc, eq, pal, w=EQ_W, h=EQ_H, fps=FPS)
    except Exception as e:
        log(f"Equalizer failed ({str(e)[:120]}); continuing without it")
        have_eq = False
    have_intro = True
    try:
        fx.make_intro(intro, brand, pal, seconds=INTRO_S, fps=FPS)
    except Exception as e:
        log(f"Intro failed ({str(e)[:120]}); continuing without it")
        have_intro = False
    ass_full, ass_intro = workdir / "cycle.ass", workdir / "cycle_intro.ass"
    write_cycle_ass(ass_full, song, segs, d, cyc, plan["cta_question"], pal, lyric_rgb)
    write_cycle_ass(ass_intro, song, segs, d, cyc, plan["cta_question"], pal, lyric_rgb, skip_before=INTRO_S + 0.3)
    cycle, head, rest = workdir / "cycle.mp4", workdir / "head.mp4", workdir / "rest.mp4"
    HEAD_S = 6.0                                       # keyframes every 2 s, so 6.0 is an exact cut point
    ok = False
    for use_eq, use_subs in ((have_eq, True), (have_eq, False), (False, False)):
        try:
            _compose_cycle(workdir, art_png, title_png, particles, band, eq, ass_full, cyc, pal, cycle, use_eq, use_subs)
            _compose_cycle(workdir, art_png, title_png, particles, band, eq, ass_intro, cyc, pal, head, use_eq, use_subs,
                           intro=intro if have_intro else None, limit=HEAD_S)
            ok = True
            break
        except Exception as e:
            log(f"Cycle render variant (eq={use_eq}, lyrics={use_subs}) failed: {str(e)[:160]}")
    if not ok:
        raise RuntimeError("cycle render failed")
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{HEAD_S}", "-i", str(cycle), "-c", "copy", str(rest)])
    reps = max(1, math.ceil(total / cyc))
    lst = workdir / "cycles.txt"
    lst.write_text(f"file '{head}'\nfile '{rest}'\n" + "".join(f"file '{cycle}'\n" for _ in range(reps - 1)))
    log(f"Cycle ready ({time.time() - T0:.0f}s). Joining {reps} repeats with the audio...")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", audio, "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{total:.2f}", "-movflags", "+faststart", out])
    for f in (particles, band, eq, intro, cycle, head, rest, lst, ass_full, ass_intro):
        Path(f).unlink(missing_ok=True)
    log(f"Video OK ({Path(out).stat().st_size / 1e6:.0f} MB) in {time.time() - T0:.0f}s")
    return total


def render_simple(art_png, title_png, audio, out):
    """Last-resort video: the finished artwork as a still picture + the music. Always works."""
    from PIL import Image
    flat = Path(out).with_name("flat.png")
    base = Image.open(art_png).convert("RGBA")
    if title_png:
        base = Image.alpha_composite(base, Image.open(title_png).convert("RGBA"))
    base.convert("RGB").save(flat)
    total = media.probe_duration(audio)
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "6", "-i", str(flat), "-i", str(audio),
         "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-r", "6",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)])
    flat.unlink(missing_ok=True)
    log("Video OK (simple version)")
    return total


def render_safe(art_png, title_png, audio, d, xf, song, segs, plan, pal, lyric_rgb, workdir, out, brand):
    for attempt in (1, 2):
        try:
            return render_loop(art_png, title_png, audio, d, xf, song, segs, plan, pal, lyric_rgb, workdir, out, brand)
        except Exception as e:
            log(f"Full render attempt {attempt} failed: {str(e)[:200]}")
    log("Using the simple video so the upload still happens")
    return render_simple(art_png, title_png, audio, out)


# =====================================================================================================
# STILL VIDEO (current look): the character picture, nothing else, plus ONE small sound wave and the intro.
# One cycle = one pass of the song; the whole video repeats it, so the wave always matches the music.
# =====================================================================================================
SW_W, SW_H, SW_X, SW_Y = 440, 110, 110, 860          # small wave, bottom-left (the empty side of the picture)


def _still_cycle(art, eq, cyc, out, use_eq, intro=None, limit=None):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{cyc:.3f}", "-i", str(art)]
    n = 1
    if use_eq:
        cmd += ["-i", str(eq)]
        eq_i, n = n, n + 1
    if intro:
        cmd += ["-i", str(intro)]
        in_i, n = n, n + 1
    fc, last = "[0:v]format=rgba[base]", "base"
    if use_eq:
        fc += (f";[{last}]split[a][b];[b]crop={SW_W}:{SW_H}:{SW_X}:{SW_Y},format=gbrp[c];[{eq_i}:v]format=gbrp[e];"
               f"[c][e]blend=all_mode=screen:shortest=1[d];[a][d]overlay={SW_X}:{SW_Y}:format=auto:shortest=1[v1]")
        last = "v1"
    if intro:
        fc += (f";[{in_i}:v]format=yuva420p,fade=t=out:st=2.6:d=1.4:alpha=1[ii];"
               f"[{last}][ii]overlay=0:0:enable='lt(t,4.0)':format=auto[v3]")
        last = "v3"
    fc += f";[{last}]format=yuv420p[v]"
    run(cmd + ["-filter_complex", fc, "-map", "[v]", "-t", f"{(limit or cyc):.3f}", *_cycle_encode(), str(out)])


def render_still(art_png, audio, d, xf, pal, workdir, out, brand):
    workdir = Path(workdir).resolve()
    art_png, audio, out = (str(Path(x).resolve()) for x in (art_png, audio, out))
    total = media.probe_duration(audio)
    cyc = d - xf
    T0 = time.time()
    log(f"Making one {cyc:.0f}s cycle (still picture + small sound wave)...")
    eq, intro = workdir / "eq.mp4", workdir / "intro.mp4"
    have_eq = True
    try:
        fx.render_eq(audio, cyc, cyc, eq, pal, w=SW_W, h=SW_H, fps=FPS, bars=20)
    except Exception as e:
        log(f"Sound wave failed ({str(e)[:120]}); continuing without it")
        have_eq = False
    have_intro = True
    try:
        fx.make_intro(intro, brand, pal, seconds=INTRO_S, fps=FPS)
    except Exception as e:
        log(f"Intro failed ({str(e)[:120]}); continuing without it")
        have_intro = False
    cycle, head, rest = workdir / "cycle.mp4", workdir / "head.mp4", workdir / "rest.mp4"
    HEAD_S = 6.0
    ok = False
    for use_eq in ((True, False) if have_eq else (False,)):
        try:
            _still_cycle(art_png, eq, cyc, cycle, use_eq)
            _still_cycle(art_png, eq, cyc, head, use_eq, intro=intro if have_intro else None, limit=HEAD_S)
            ok = True
            break
        except Exception as e:
            log(f"Cycle render (wave={use_eq}) failed: {str(e)[:160]}")
    if not ok:
        raise RuntimeError("cycle render failed")
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{HEAD_S}", "-i", str(cycle), "-c", "copy", str(rest)])
    reps = max(1, math.ceil(total / cyc))
    lst = workdir / "cycles.txt"
    lst.write_text(f"file '{head}'\nfile '{rest}'\n" + "".join(f"file '{cycle}'\n" for _ in range(reps - 1)))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", audio, "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{total:.2f}", "-movflags", "+faststart", out])
    for f in (eq, intro, cycle, head, rest, lst):
        Path(f).unlink(missing_ok=True)
    log(f"Video OK ({Path(out).stat().st_size / 1e6:.0f} MB) in {time.time() - T0:.0f}s")
    return total


def render_still_safe(art_png, audio, d, xf, pal, workdir, out, brand):
    for attempt in (1, 2):
        try:
            return render_still(art_png, audio, d, xf, pal, workdir, out, brand)
        except Exception as e:
            log(f"Video render attempt {attempt} failed: {str(e)[:200]}")
    log("Using the plain picture + music video so the upload still happens")
    return render_simple(art_png, None, audio, out)
