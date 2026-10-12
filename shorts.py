"""Vertical Shorts (1080x1920) that promote the long video.

Timeline of each Short (about 25 seconds):
  0.0 - 3.0   hook: big text + a friendly voice ("Hey guys, listen to this song") over the quiet start of the chorus
  3.0 - end-4 the song plays at full volume with animated lyrics, equalizer and sparkles
  last 4 s    call to action: full song on our channel, like, subscribe, share
"""
import asyncio
import os
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter

import fx
import media

W, H = 1080, 1920
HOOK_S, OUTRO_S = 3.0, 4.0
VOICE = os.getenv("SHORTS_VOICE", "en-US-AriaNeural")
OUTROS = ["The full song is on our channel. Tap my name, then like, subscribe, and share!",
          "Want the full song? It's on our channel. Tap my name, and like, subscribe, and share!",
          "Full song is on our channel. Tap my name, and don't forget to like, subscribe, and share!"]


def log(m):
    print(m, flush=True)


# ----------------------------- picture ---------------------------------------
def vertical_image(landscape, portrait, out):
    """1080x1920 hero picture: the real vertical picture if we have it, else a crop of the wide one."""
    if portrait and Path(portrait).exists():
        media.cover(portrait, out, (W, H))
        return str(out)
    img = Image.open(landscape).convert("RGB")
    cw = int(img.height * 9 / 16)
    x0 = max(0, min(img.width - cw, int(img.width * 0.66) - cw // 2))
    img = img.crop((x0, 0, x0 + cw, img.height)).resize((W, H), Image.LANCZOS)
    img.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2)).save(out, quality=95)
    return str(out)


# ----------------------------- which part of the song ------------------------
def section_runs(lyrics):
    """[(kind, first_line_index, last_line_index)] in the order of lyric_lines."""
    runs, idx, kind = [], 0, "verse"
    cur = None
    for raw in lyrics.splitlines():
        t = raw.strip()
        if not t:
            continue
        if t.startswith("["):
            low = t.lower()
            kind = "chorus" if "chorus" in low or "hook" in low else ("bridge" if "bridge" in low else "verse")
            cur = None
            continue
        if cur is None:
            cur = [kind, idx, idx]
            runs.append(cur)
        cur[2] = idx
        idx += 1
    return [tuple(r) for r in runs]


def pick_windows(lyrics, timed, duration, n=2):
    """Choose n parts of the song (first chorus, then last chorus or the bridge)."""
    runs = [r for r in section_runs(lyrics) if r[2] < len(timed)]
    choruses = [r for r in runs if r[0] == "chorus"]
    others = [r for r in runs if r[0] == "bridge"] or [r for r in runs if r[0] == "verse"][1:2]
    chosen = []
    if choruses:
        chosen.append(choruses[0])
    if len(choruses) > 1:
        chosen.append(choruses[-1])
    elif others:
        chosen.append(others[0])
    while len(chosen) < n and runs:
        chosen.append(runs[min(len(runs) - 1, len(chosen) * max(1, len(runs) // 2))])
    wins = []
    for kind, i0, i1 in chosen[:n]:
        a, b = timed[i0][1], timed[i1][2]
        body = min(max(b - a + 1.0, 15.0), 22.0)
        total = HOOK_S + body + OUTRO_S
        s = max(0.0, a - HOOK_S)
        total = min(total, duration - s - 0.2)
        wins.append({"start": s, "total": total, "kind": kind})
    while len(wins) < n:
        s = duration * (0.3 + 0.2 * len(wins))
        wins.append({"start": s, "total": min(HOOK_S + 18 + OUTRO_S, duration - s - 0.2), "kind": "verse"})
    return wins


# ----------------------------- voice -----------------------------------------
def tts(text, path):
    """Free text-to-speech. Returns the file path, or None if the service is unavailable."""
    try:
        import edge_tts

        async def run():
            await edge_tts.Communicate(text, VOICE, rate="+8%").save(str(path))
        asyncio.run(run())
        if Path(path).exists() and Path(path).stat().st_size > 1500:
            return str(path)
    except Exception as e:
        log(f"  voice unavailable ({type(e).__name__}); using on-screen text only")
    return None


# ----------------------------- text overlays (ASS) ---------------------------
def _bgr(rgb):
    return "&H00%02X%02X%02X" % (rgb[2], rgb[1], rgb[0])


def _mid_break(text):
    words = text.split()
    if len(words) < 4:
        return text
    m = len(words) // 2
    return " ".join(words[:m]) + "\\N" + " ".join(words[m:])


def write_short_ass(path, T, timed, win_start, hook_text, brand, singer, pal):
    font = "Anton" if media.ANTON.exists() else "DejaVu Sans"
    bold = 0 if media.ANTON.exists() else -1
    acc = _bgr(pal["rgb"])
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
            "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Hook,{font},185,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,2,0,1,10,3,8,60,60,300,1\n"
            f"Style: Lyric,{font},108,{acc},&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,1,0,1,8,3,2,70,70,590,1\n"
            f"Style: Cta,{font},128,{acc},{acc},&H00000000,&H78000000,{bold},0,0,0,100,100,2,0,1,9,3,5,60,60,0,1\n"
            f"Style: White,{font},128,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,2,0,1,9,3,5,60,60,0,1\n"
            f"Style: Small,{font},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,3,0,1,6,2,5,60,60,0,1\n"
            f"Style: Brand,{font},46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,4,0,1,4,1,7,50,50,60,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev = []
    ts = media._ts
    ev.append(f"Dialogue: 2,{ts(0)},{ts(T)},Brand,,0,0,0,,{{\\an7}}{media._clean(brand.upper())}  \\u2022  {media._clean(singer.upper())}".replace("\\u2022", "\u2022"))
    pop = "{\\an8\\fad(60,250)\\fscx55\\fscy55\\t(0,180,\\fscx112\\fscy112)\\t(180,320,\\fscx100\\fscy100)}"
    ev.append(f"Dialogue: 2,{ts(0.05)},{ts(HOOK_S + 0.2)},Hook,,0,0,0,,{pop}{_mid_break(media._clean(hook_text))}")
    for text, a, b in timed:
        a2, b2 = a - win_start, b - win_start
        if a2 < HOOK_S - 0.1 or a2 > T - OUTRO_S - 0.6:
            continue
        b2 = min(b2, T - OUTRO_S + 0.2)
        if b2 - a2 < 0.8:
            b2 = a2 + 0.8
        pop2 = "{\\an2\\fad(100,160)\\fscx88\\fscy88\\blur1.2\\t(0,200,\\fscx100\\fscy100)}"
        ev.append(f"Dialogue: 1,{ts(a2)},{ts(b2)},Lyric,,0,0,0,,{pop2}{media._karaoke(text, b2 - a2)}")
    t0 = T - OUTRO_S
    pulse = "\\t(0,260,\\fscx115\\fscy115)\\t(260,460,\\fscx100\\fscy100)"
    ev.append(f"Dialogue: 3,{ts(t0)},{ts(T)},White,,0,0,0,,{{\\an5\\pos(540,780)\\fad(120,0)\\fscx70\\fscy70{pulse}}}FULL SONG")
    ev.append(f"Dialogue: 3,{ts(t0 + 0.25)},{ts(T)},Cta,,0,0,0,,{{\\an5\\pos(540,930)\\fad(120,0)\\fscx70\\fscy70{pulse}}}ON OUR CHANNEL")
    ev.append(f"Dialogue: 3,{ts(t0 + 0.7)},{ts(T)},White,,0,0,0,,{{\\an5\\pos(540,1110)\\fad(120,0)\\fscx70\\fscy70{pulse}}}TAP MY NAME")
    ev.append(f"Dialogue: 3,{ts(t0 + 1.3)},{ts(T)},Small,,0,0,0,,{{\\an5\\pos(540,1260)\\fad(150,0)}}LIKE   \u2022   SUBSCRIBE   \u2022   SHARE")
    Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ----------------------------- render ----------------------------------------
def make_short(song, timed, win, sp, persona, pal, image, particles, workdir, out, brand):
    workdir = Path(workdir).resolve()
    song, image, particles, out = (str(Path(p).resolve()) for p in (song, image, particles, out))
    s, T = win["start"], win["total"]
    frames = int(T * 30)
    ass = workdir / f"short_{Path(out).stem}.ass"
    write_short_ass(ass, T, timed, s, sp["hook_text"], brand, persona["name"], pal)
    v1 = tts(sp["spoken_hook"], workdir / f"{Path(out).stem}_v1.mp3")
    v2 = tts(random.choice(OUTROS), workdir / f"{Path(out).stem}_v2.mp3") if v1 else None
    voices = bool(v1 and v2)
    a, b = T - OUTRO_S - 0.3, T - OUTRO_S + 0.3
    duck = (f"volume='if(lt(t,2.3),0.30,if(lt(t,3.1),0.30+(t-2.3)*0.875,if(lt(t,{a:.2f}),1,"
            f"if(lt(t,{b:.2f}),1-(t-{a:.2f})*1.13,0.32))))':eval=frame," if voices else "")
    fontsdir = str(media.FONTS.resolve()) if media.FONTS.exists() else "/usr/share/fonts"
    inputs = ["-i", image, "-ss", f"{s:.2f}", "-t", f"{T:.2f}", "-i", song, "-stream_loop", "-1", "-i", particles,
              "-f", "lavfi", "-i", f"color=c={pal['hex']}:s=1080x16:r=30"]
    if voices:
        inputs += ["-i", v1, "-i", v2]
    fc = (
        f"[0:v]scale=1620:2880:flags=lanczos,zoompan=z='1+0.08*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s=1080x1920:fps=30,eq=saturation=1.08:contrast=1.05,format=gbrp[bg];"
        "[2:v]scale=1080:1920,format=gbrp[part];"
        "[bg][part]blend=all_mode=screen:shortest=1[b1];"
        "[1:a]asplit=2[sa][se];"
        f"[se]showfreqs=s=54x30:mode=bar:ascale=sqrt:fscale=log:win_size=2048:rate=30:averaging=3:colors={pal['hex']},"
        "format=gbrp,scale=1080:300:flags=neighbor,drawgrid=width=20:height=10:thickness=3:color=black,"
        "lutrgb=r=val*0.9:g=val*0.9:b=val*0.9,pad=1080:1920:0:1380:black[eq];"
        "[b1][eq]blend=all_mode=screen:shortest=1[b2];"
        "[3:v]format=gbrp[bar];"
        f"[b2][bar]overlay=x='-1080+1080*t/{T:.2f}':y=0:format=gbrp:shortest=1[b3];"
        f"[b3]drawbox=x=0:y=640:w=1080:h=720:color=black@0.5:t=fill:enable='between(t,{T - OUTRO_S:.2f},{T:.2f})'[b4];"
        f"[b4]subtitles={ass.name}:fontsdir={fontsdir},format=yuv420p[v];"
        f"[sa]{duck}afade=t=out:st={T - 0.7:.2f}:d=0.7[song]")
    if voices:
        ms = int((T - OUTRO_S + 0.2) * 1000)
        fc += (";[4:a]adelay=350|350,volume=1.7[va];"
               f"[5:a]adelay={ms}|{ms},volume=1.7[vb];"
               "[song][va][vb]amix=inputs=3:normalize=0:duration=first,alimiter=limit=0.95[aout]")
    else:
        fc += ";[song]anull[aout]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "faster", "-crf", "18", "-r", "30", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "44100", "-t", f"{T:.2f}", "-movflags", "+faststart", out], check=True, cwd=str(workdir))
    log(f"  Short OK: {Path(out).name} ({T:.0f}s, voice={'yes' if voices else 'no'})")
    return out


def short_description(sp, long_url, plan_hashtags=None):
    tags = " ".join(sp["hashtags"])
    return (f"{sp['description_hook']}\n\n\U0001F3A7 FULL SONG: {long_url}\n"
            "(Tap my name or the Related video link, then like, subscribe, and share!)\n\n"
            f"{tags}\n\nMusic and vocals are AI-generated. All characters are fictional.")[:4800]
