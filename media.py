"""Images, thumbnail, lyric timing, and video rendering."""
import difflib
import math
import os
import random
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

FONTS = Path("fonts")
W, H = 1280, 720


def log(m):
    print(m, flush=True)


# ----------------------------- images ----------------------------------------
def gradient(path, tint):
    t = np.linspace(0, 1, 1080, dtype=np.float32)[:, None, None]
    c1 = np.array(tint, dtype=np.float32) * 0.4
    c2 = np.array(tint, dtype=np.float32)
    img = (c1 * (1 - t) + c2 * t) * np.ones((1080, 1920, 3), dtype=np.float32)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)).save(path, quality=92)


def make_images(persona, scenes, outdir):
    paths = []
    base_seed = random.randint(1, 10**6)
    for i, scene in enumerate(scenes):
        p = Path(outdir) / f"scene{i}.jpg"
        prompt = (f"{persona['look']}, {scene}, cinematic lighting, vibrant saturated colors, sharp focus, "
                  "ultra detailed illustration photo, no text, no watermark, no logo")
        ok = False
        for attempt in range(3):
            try:
                r = requests.get("https://image.pollinations.ai/prompt/" + quote(prompt),
                                 params={"width": 1920, "height": 1080, "nologo": "true",
                                         "seed": base_seed + i * 13}, timeout=180)
                r.raise_for_status()
                if not r.headers.get("content-type", "").startswith("image"):
                    raise ValueError("not an image")
                tmp = p.with_suffix(".raw")
                tmp.write_bytes(r.content)
                img = Image.open(tmp).convert("RGB")
                tmp.unlink()
                img = img.crop((0, 0, img.width, int(img.height * 0.92)))  # removes watermark strip
                ratio = max(1920 / img.width, 1080 / img.height)
                img = img.resize((math.ceil(img.width * ratio), math.ceil(img.height * ratio)), Image.LANCZOS)
                l, t = (img.width - 1920) // 2, (img.height - 1080) // 2
                img.crop((l, t, l + 1920, t + 1080)).save(p, quality=92)
                ok = True
                break
            except Exception as e:
                log(f"  image {i + 1} attempt {attempt + 1} failed: {type(e).__name__}")
                time.sleep(4)
        if not ok:
            gradient(p, [random.randint(80, 220) for _ in range(3)])
        paths.append(str(p))
    log(f"Images OK ({len(paths)})")
    return paths


# ----------------------------- thumbnail -------------------------------------
def _font(size):
    for f in [FONTS / "Anton-Regular.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
              Path("C:/Windows/Fonts/arialbd.ttf")]:
        if f.exists():
            return ImageFont.truetype(str(f), size)
    return ImageFont.load_default()


def make_thumbnail(img_path, hook, persona_name, out):
    img = Image.open(img_path).convert("RGB").resize((W, H), Image.LANCZOS)
    img = ImageEnhance.Color(img).enhance(1.35)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    # dark gradient bottom + left for readable text
    shade = np.zeros((H, W, 4), dtype=np.uint8)
    yy = np.linspace(0, 1, H)[:, None] ** 1.6
    xx = np.clip(1.1 - np.linspace(0, 1.4, W)[None, :], 0, 1)
    shade[:, :, 3] = (np.clip(yy * 0.75 + xx * 0.45, 0, 0.88) * 255).astype(np.uint8)
    img = Image.alpha_composite(img.convert("RGBA"), Image.fromarray(shade, "RGBA")).convert("RGB")
    d = ImageDraw.Draw(img)
    words = hook.split()
    size = 170
    while size > 60:
        font = _font(size)
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=font) <= 800:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        lines = [x for x in lines if x]
        if len(lines) <= 3 and len(lines) * size * 1.05 <= 470:
            break
        size -= 8
    y = H - 60 - int(len(lines) * size * 1.05)
    colors = [(255, 225, 20), (255, 255, 255), (255, 225, 20)]
    for i, line in enumerate(lines):
        d.text((50, y), line, font=font, fill=colors[i % 3], stroke_width=max(6, size // 14), stroke_fill=(0, 0, 0))
        y += int(size * 1.05)
    bf = _font(40)
    d.rounded_rectangle((40, 36, 40 + d.textlength("NEW SONG", font=bf) + 40, 100), 14, fill=(225, 20, 40))
    d.text((60, 42), "NEW SONG", font=bf, fill=(255, 255, 255))
    nf = _font(36)
    tw = d.textlength(persona_name.upper(), font=nf)
    d.text((W - tw - 40, H - 70), persona_name.upper(), font=nf, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    img.save(out, "JPEG", quality=90)
    log("Thumbnail OK")
    return out


# ----------------------------- lyric timing ----------------------------------
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


def _ts(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _wrap(text, width=34):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    return "\\N".join(lines)


def write_ass(timed, duration, cta_question, path):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
            "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            "Style: Lyric,DejaVu Sans,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,70,1\n"
            "Style: Cta,DejaVu Sans,38,&H0014E1FF,&H0014E1FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,8,60,60,40,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    ev = []
    for text, a, b in timed:
        ev.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Lyric,,0,0,0,,{{\\fad(150,150)}}{_wrap(text)}")
    ctas = [(3, 9, "LIKE if this song hits you"),
            (duration * 0.45, duration * 0.45 + 6, "SUBSCRIBE for a new song every day"),
            (max(duration - 14, 10), duration - 2, _wrap(cta_question, 44))]
    for a, b, t in ctas:
        ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},Cta,,0,0,0,,{{\\fad(300,300)}}{t}")
    Path(path).write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ----------------------------- video -----------------------------------------
def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def build_video(images, audio, timed, cta_question, workdir, out):
    workdir = Path(workdir)
    duration = probe_duration(audio)
    n = len(images)
    seg = duration / n
    frames = int(seg * 25)
    clips = []
    log(f"Rendering {n} animated scenes for {duration:.0f}s...")
    for i, img in enumerate(images):
        z = "min(zoom+0.0007,1.3)" if i % 2 == 0 else "if(eq(on,0),1.3,max(zoom-0.0007,1.0))"
        vf = (f"scale=2560:1440,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=25,"
              f"fade=t=in:st=0:d=0.6,fade=t=out:st={max(seg - 0.6, 0.1):.2f}:d=0.6,format=yuv420p")
        clip = workdir / f"clip{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", img, "-vf", vf, "-frames:v", str(frames),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(clip)], check=True)
        clips.append(clip)
    lst = workdir / "clips.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    joined = workdir / "joined.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(joined)], check=True)
    ass = workdir / "lyrics.ass"
    write_ass(timed, duration, cta_question, ass)
    fontsdir = str(FONTS.resolve()) if FONTS.exists() else "/usr/share/fonts"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-i", audio,
                    "-vf", f"subtitles={ass.name}:fontsdir={fontsdir}", "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest", "-movflags", "+faststart",
                    str(out)], check=True, cwd=str(workdir))
    for c in clips + [joined]:
        c.unlink(missing_ok=True)
    log(f"Video OK ({Path(out).stat().st_size / 1e6:.0f} MB)")
    return duration
