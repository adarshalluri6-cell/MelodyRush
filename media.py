"""Images, thumbnail, lyric timing, and video rendering (1080p, one hero image, animated lyrics)."""
import difflib
import math
import random
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests

import fx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

FONTS = Path("fonts")
W, H = 1280, 720
ANTON = FONTS / "Anton-Regular.ttf"


def log(m):
    print(m, flush=True)


# ----------------------------- images ----------------------------------------
def cover(src, dst, size, sharpen=True):
    img = Image.open(src).convert("RGB")
    ratio = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((math.ceil(img.width * ratio), math.ceil(img.height * ratio)), Image.LANCZOS)
    l, t = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    img = img.crop((l, t, l + size[0], t + size[1]))
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))
    img.save(dst, quality=95)
    return str(dst)


def gradient(path, tint):
    t = np.linspace(0, 1, 1080, dtype=np.float32)[:, None, None]
    c1, c2 = np.array(tint, dtype=np.float32) * 0.35, np.array(tint, dtype=np.float32)
    img = (c1 * (1 - t) + c2 * t) * np.ones((1080, 1920, 3), dtype=np.float32)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)).save(path, quality=92)


def pollinations(prompt, path):
    """Backup image source (lower quality, free). Returns True on success."""
    for attempt in range(4):
        try:
            time.sleep(6 if attempt else 0)
            r = requests.get("https://image.pollinations.ai/prompt/" + quote(prompt + ", no text, no watermark"),
                             params={"width": 1920, "height": 1080, "nologo": "true", "seed": random.randint(1, 10**6)},
                             timeout=180)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image"):
                raise ValueError("not an image")
            raw = Path(path).with_suffix(".raw")
            raw.write_bytes(r.content)
            img = Image.open(raw).convert("RGB")
            raw.unlink()
            img.crop((0, 0, img.width, int(img.height * 0.92))).save(path, quality=95)  # drops watermark strip
            return True
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", "")
            log(f"  backup image attempt {attempt + 1} failed: {type(e).__name__} {code}")
            time.sleep(8 * (attempt + 1))
    return False


def get_singer_image(persona, image_prompt, kaggle_img, out):
    """The one hero picture used for the whole video (and the thumbnail). 1920x1080."""
    out = Path(out)
    if kaggle_img and Path(kaggle_img).exists():
        log("Using the high-quality singer image from the Kaggle GPU")
        cover(kaggle_img, out, (1920, 1080))
        return str(out)
    log("Kaggle image missing, using the backup image service (lower quality)")
    prompt = (f"professional photo of {persona['look']}, {image_prompt}, singing into a microphone, subject on the "
              "right third of the frame, empty dark space on the left, cinematic lighting, sharp focus")
    raw = out.with_name("backup_src.jpg")
    if not pollinations(prompt, raw):
        gradient(raw, [random.randint(80, 220) for _ in range(3)])
    cover(raw, out, (1920, 1080))
    return str(out)


# ----------------------------- thumbnail -------------------------------------
def _font(size):
    for f in [ANTON, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]:
        if f.exists():
            return ImageFont.truetype(str(f), size)
    return ImageFont.load_default()


def make_thumbnail(src, hook, persona_name, out, brand="MELODYRUSH", pal=None):
    pal = pal or fx.PALETTES["gold"]
    img = Image.open(src).convert("RGB")
    ratio = max(W / img.width, H / img.height)
    img = img.resize((math.ceil(img.width * ratio), math.ceil(img.height * ratio)), Image.LANCZOS)
    l, t = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((l, t, l + W, t + H))
    img = ImageEnhance.Color(img).enhance(1.22)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Sharpness(img).enhance(1.35)
    shade = np.zeros((H, W, 4), dtype=np.uint8)
    xx = np.clip(0.80 - np.linspace(0, 0.80 / 0.60, W)[None, :], 0, 0.80)
    yy = np.linspace(0, 1, H)[:, None] ** 2.4 * 0.5
    shade[:, :, 3] = (np.clip(xx + yy, 0, 0.86) * 255).astype(np.uint8)
    shade[:, :, 0], shade[:, :, 1], shade[:, :, 2] = 6, 5, 14
    img = Image.alpha_composite(img.convert("RGBA"), Image.fromarray(shade, "RGBA"))
    img = Image.alpha_composite(img, fx.sparkle_layer(W, H, pal))
    img = Image.alpha_composite(img, fx.eq_decor(W, H, pal))
    img = Image.alpha_composite(img, fx.title_layer(W, H, hook, persona_name, brand, pal))
    img = img.convert("RGB")
    for q in (95, 90, 82):
        img.save(out, "JPEG", quality=q, optimize=True)
        if Path(out).stat().st_size < 1_900_000:
            break
    log("Thumbnail OK")
    return out


# ----------------------------- lyric timing ----------------------------------
def proportional(lines, segs, duration):
    """Spread lines over the parts of the song where someone is actually singing."""
    segs = [s for s in segs if s["end"] > s["start"]]
    total_voc = sum(s["end"] - s["start"] for s in segs)
    total_chars = sum(len(x) + 8 for x in lines)

    def at(offset):
        for s in segs:
            d = s["end"] - s["start"]
            if offset <= d:
                return s["start"] + offset
            offset -= d
        return segs[-1]["end"]
    out, c = [], 0
    for x in lines:
        c0, c1 = c, c + len(x) + 8
        c = c1
        a = at(total_voc * c0 / total_chars)
        b = at(total_voc * c1 / total_chars)
        out.append((x, a, min(max(a + 1.0, b - 0.1), a + 7.0)))
    return out


def align(lines, segs, duration):
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())
    n = len(lines)
    times = [None] * n
    j = 0
    for s in segs:
        if j >= n:
            break
        best, bi = 0, None
        for i in range(j, min(j + 4, n)):
            r = difflib.SequenceMatcher(None, norm(lines[i]), norm(s["text"])).ratio()
            if r > best:
                best, bi = r, i
        if bi is not None and best >= 0.4:
            times[bi] = (s["start"], s["end"])
            j = bi + 1
    known = sum(t is not None for t in times)
    if known < max(3, n // 4) and len(segs) >= 3:
        log(f"Lyric timing: matched {known}/{n}; mapping lines onto the {len(segs)} vocal segments")
        return proportional(lines, segs, duration)
    if known < max(3, n // 4):
        log(f"Lyric timing: only {known}/{n} lines matched, spreading evenly")
        a, b = duration * 0.07, duration * 0.93
        step = (b - a) / n
        return [(lines[i], a + i * step, a + (i + 1) * step - 0.15) for i in range(n)]
    i = 0
    while i < n:
        if times[i] is None:
            k = i
            while k < n and times[k] is None:
                k += 1
            left = times[i - 1][1] if i > 0 else duration * 0.06
            right = times[k][0] if k < n else min(duration * 0.97, left + 3.2 * (k - i))
            step = max((right - left) / (k - i), 0.8)
            for m in range(i, k):
                times[m] = (left + (m - i) * step, left + (m - i + 1) * step - 0.1)
            i = k
        else:
            i += 1
    out = []
    for idx, (a, b) in enumerate(times):
        nxt = times[idx + 1][0] if idx + 1 < n else duration
        out.append((lines[idx], a, max(a + 0.8, min(b + 0.4, nxt - 0.05))))
    log(f"Lyric timing OK ({known}/{n} lines matched to the singing)")
    return out


# ----------------------------- animated lyrics (ASS) -------------------------
def _ts(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _clean(s):
    return s.replace("{", "(").replace("}", ")").replace("\\", "")


def _karaoke(text, dur):
    words = _clean(text).split()
    if not words:
        return ""
    brk = len(words) // 2 if len(text) > 26 and len(words) > 3 else -1
    total_cs = max(int(dur * 100 * 0.85), 30 * len(words) // 3)
    weights = [len(w) + 1 for w in words]
    ws = sum(weights)
    out = ""
    for i, w in enumerate(words):
        cs = max(8, int(total_cs * weights[i] / ws))
        out += "{\\kf%d}%s" % (cs, w)
        if i == brk - 1:
            out += "\\N"
        elif i < len(words) - 1:
            out += " "
    return out


def write_ass(timed, duration, cta_question, path):
    font = "Anton" if ANTON.exists() else "DejaVu Sans"
    bold = 0 if ANTON.exists() else -1
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
            "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Lyric,{font},100,&H0014E1FF,&H00FFFFFF,&H00000000,&H78000000,{bold},0,0,0,100,100,1,0,1,7,3,2,100,100,110,1\n"
            f"Style: Cta,{font},60,&H0014E1FF,&H0014E1FF,&H00000000,&H78000000,{bold},0,0,0,100,100,1,0,1,6,2,8,100,100,50,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev = []
    for text, a, b in timed:
        pop = "{\\an2\\fad(120,180)\\fscx88\\fscy88\\blur1.5\\t(0,220,\\fscx100\\fscy100)}"
        ev.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Lyric,,0,0,0,,{pop}{_karaoke(text, b - a)}")
    ctas = [(3, 9, "LIKE if this song hits you"),
            (duration * 0.45, duration * 0.45 + 6, "SUBSCRIBE for a new song every day"),
            (max(duration - 14, 10), duration - 2, _clean(cta_question))]
    for a, b, t in ctas:
        ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cta,,0,0,0,,{{\\an8\\fad(250,300)\\move(960,-90,960,55,0,350)}}{t}")
    Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ----------------------------- video -----------------------------------------
def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def build_video(bg, audio, timed, cta_question, workdir, out, hook="NEW SONG", singer="", song="",
                brand="MELODYRUSH", pal=None):
    pal = pal or fx.PALETTES["gold"]
    workdir = Path(workdir).resolve()
    bg, audio, out = str(Path(bg).resolve()), str(Path(audio).resolve()), str(Path(out).resolve())
    duration = probe_duration(audio)
    frames = int(duration * 30)
    ass = workdir / "lyrics.ass"
    write_ass(timed, duration, cta_question, ass)
    fx.title_layer(1920, 1080, hook, singer, brand, pal).save(workdir / "title.png")
    fx.nowplaying_layer(1920, 1080, brand, singer, song[:42], pal).save(workdir / "nowplaying.png")
    particles = workdir / "particles.mp4"
    log("Making sparkle loop...")
    fx.make_particles(particles, pal)
    fontsdir = str(FONTS.resolve()) if FONTS.exists() else "/usr/share/fonts"
    log(f"Rendering 1080p video with equalizer and sparkles, {duration:.0f}s...")
    fc = (
        f"[0:v]scale=2880:1620:flags=lanczos,zoompan=z='1+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s=1920x1080:fps=30,eq=saturation=1.06:contrast=1.04,format=gbrp[bg];"
        "[2:v]scale=1920:1080,format=gbrp[part];"
        "[bg][part]blend=all_mode=screen:shortest=1[b1];"
        "[1:a]asplit=2[aout][aeq];"
        f"[aeq]showfreqs=s=96x26:mode=bar:ascale=sqrt:fscale=log:win_size=2048:rate=30:averaging=3:colors={pal['hex']},"
        "format=gbrp,scale=1920:260:flags=neighbor,drawgrid=width=20:height=10:thickness=3:color=black,"
        "lutrgb=r=val*0.85:g=val*0.85:b=val*0.85,pad=1920:1080:0:820:black[eq];"
        "[b1][eq]blend=all_mode=screen:shortest=1[b2];"
        "[3:v]format=rgba,fade=t=in:st=0.4:d=0.9:alpha=1,fade=t=out:st=11.2:d=1:alpha=1[title];"
        "[4:v]format=rgba,fade=t=in:st=12:d=1.5:alpha=1[np];"
        "[b2]format=rgba[b2r];[b2r][title]overlay=0:0:eof_action=pass[b3];[b3][np]overlay=0:0[b4];"
        f"[b4]subtitles={ass.name}:fontsdir={fontsdir},format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", bg, "-i", audio,
                    "-stream_loop", "-1", "-i", str(particles),
                    "-loop", "1", "-framerate", "30", "-t", "13", "-i", str(workdir / "title.png"),
                    "-loop", "1", "-framerate", "30", "-i", str(workdir / "nowplaying.png"),
                    "-filter_complex", fc, "-map", "[v]", "-map", "[aout]",
                    "-c:v", "libx264", "-preset", "faster", "-crf", "19", "-r", "30",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{duration:.2f}",
                    "-movflags", "+faststart", out], check=True, cwd=str(workdir))
    for f in ("title.png", "nowplaying.png", "particles.mp4"):
        (workdir / f).unlink(missing_ok=True)
    log(f"Video OK ({Path(out).stat().st_size / 1e6:.0f} MB)")
    return duration
