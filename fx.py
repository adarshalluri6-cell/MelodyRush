"""Visual effects: title graphic, sparkles, equalizer look. Shared by the thumbnail and the video."""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path("fonts")
PALETTES = {
    "rose": {"light": (255, 196, 218), "dark": (226, 62, 122), "hex": "0xFF69A0", "rgb": (255, 105, 160)},
    "cyan": {"light": (176, 242, 255), "dark": (0, 150, 232), "hex": "0x40E0FF", "rgb": (64, 224, 255)},
    "violet": {"light": (228, 196, 255), "dark": (132, 72, 232), "hex": "0xBE78FF", "rgb": (190, 120, 255)},
    "ember": {"light": (255, 208, 156), "dark": (232, 92, 32), "hex": "0xFF8C42", "rgb": (255, 140, 66)},
    "mint": {"light": (176, 255, 228), "dark": (22, 182, 142), "hex": "0x50FFC8", "rgb": (80, 255, 200)},
}
PERSONA_PALETTE = {"mira": "rose", "kai": "cyan", "luna": "violet", "jax": "ember", "nova": "mint"}


def palette_for(persona_id):
    return PALETTES[PERSONA_PALETTE.get(persona_id, "rose")]


def lyric_rgb(persona_id):
    """Colour of the lyric words once sung (white before). Taken from the singer's palette, never yellow."""
    return palette_for(persona_id)["rgb"]


def light_band(path, pal, w=760, h=1080):
    """Soft diagonal light streak that sweeps across the picture every 15 seconds."""
    xs = np.linspace(-1, 1, w, dtype=np.float32)
    prof = np.exp(-(xs / 0.28) ** 2)
    a = np.broadcast_to(prof[None, :], (h, w)) * 0.20
    img = np.zeros((h, w, 4), np.uint8)
    col = np.array(pal["light"], np.float32) * 0.6 + 255 * 0.4
    img[:, :, :3] = col.astype(np.uint8)
    img[:, :, 3] = (a * 255).astype(np.uint8)
    Image.fromarray(img, "RGBA").transform((w, h), Image.AFFINE, (1, 0.45, -0.22 * h, 0, 1, 0), Image.BICUBIC).save(path)


def font(kind, size):
    """kind: heavy | medium | bold | script. Uses nicer fonts if they were downloaded and are valid, else safe fallbacks."""
    order = {
        "heavy": [FONTS / "Anton-Regular.ttf", FONTS / "Poppins-ExtraBold.ttf"],
        "bold": [FONTS / "Poppins-Bold.ttf", FONTS / "Anton-Regular.ttf"],
        "medium": [FONTS / "Poppins-Medium.ttf"],
        "script": [FONTS / "KaushanScript-Regular.ttf", FONTS / "GreatVibes-Regular.ttf"],
        "serif": [FONTS / "DMSerifDisplay-Regular.ttf", FONTS / "PlayfairDisplay-SemiBold.ttf",
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")],
    }[kind] + [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]
    if kind == "script":
        order += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf")]
    for f in order:
        try:
            if f.exists() and f.stat().st_size > 5000:      # a failed download leaves a tiny text file
                return ImageFont.truetype(str(f), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _spaced(d, x, y, text, fnt, fill, spacing):
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + spacing
    return x


def _spaced_width(d, text, fnt, spacing):
    return sum(d.textlength(c, font=fnt) + spacing for c in text) - spacing


def _gradient_text(layer, x, y, text, fnt, top, bottom, s):
    bbox = fnt.getbbox(text)
    w, h = bbox[2] - bbox[0] + 40, bbox[3] - bbox[1] + 40
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((20 - bbox[0], 20 - bbox[1]), text, font=fnt, fill=255)
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    col = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    grad = Image.fromarray(np.broadcast_to(col, (h, w, 3)).astype(np.uint8), "RGB")
    px, py = x - 20, y - 20  # (x, y) is the top-left corner of the letters
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(10 * s)).point(lambda v: int(v * 0.85)))
    layer.alpha_composite(shadow, (int(px + 5 * s), int(py + 8 * s)))
    edge = mask.filter(ImageFilter.MaxFilter(3 if s < 1.3 else 5))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dark.putalpha(edge.point(lambda v: int(v * 0.9)))
    layer.alpha_composite(dark, (int(px), int(py)))
    layer.paste(grad, (int(px), int(py)), mask)


def title_layer(W, H, hook, singer, brand, pal, subtitle="NEW SONG   \u2022   OFFICIAL LYRIC VIDEO"):
    """Transparent graphic: brand, big hook text, boxed subtitle, singer tag. Designed on a 1280x720 grid."""
    s = H / 720.0
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = pal["rgb"]
    # brand (top-left): play badge + spaced name + thin line
    r = int(24 * s)
    d.ellipse((46 * s, 38 * s, 46 * s + 2 * r, 38 * s + 2 * r), outline=acc, width=max(2, int(2.5 * s)))
    cx, cy = 46 * s + r, 38 * s + r
    d.polygon([(cx - 6 * s, cy - 9 * s), (cx - 6 * s, cy + 9 * s), (cx + 10 * s, cy)], fill=acc)
    bf = font("bold", int(28 * s))
    _spaced(d, 112 * s, 44 * s, brand.upper(), bf, (255, 255, 255, 255), 4 * s)
    # hook text
    words = hook.upper().split()
    size, lines = 170, []
    maxw = 700 * s
    while size > 56:
        fnt = font("heavy", int(size * s))
        lines, cur = [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if d.textlength(t, font=fnt) <= maxw:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w_
        if cur:
            lines.append(cur)
        capc = fnt.getbbox('H')[3] - fnt.getbbox('H')[1]
        if len(lines) <= 3 and len(lines) * (capc + size * 0.16 * s) / s <= 330:
            break
        size -= 6
    cap = fnt.getbbox('H')[3] - fnt.getbbox('H')[1]
    lh = int(cap + size * 0.16 * s)
    block = len(lines) * lh - int(size * 0.16 * s)
    y = int(128 * s) + max(0, int((330 * s - block) / 2))
    for i, line in enumerate(lines):
        if i == 0:
            _gradient_text(layer, int(48 * s), y, line, fnt, (255, 255, 255), (206, 212, 224), s)
        else:
            _gradient_text(layer, int(48 * s), y, line, fnt, pal["light"], pal["dark"], s)
        y += lh
    # boxed subtitle
    sf = font("medium", int(21 * s))
    sw = _spaced_width(d, subtitle, sf, 3 * s)
    bx0, by0 = 50 * s, y - int(size * 0.16 * s) + 30 * s
    d.rectangle((bx0, by0, bx0 + sw + 40 * s, by0 + 46 * s), outline=acc + (255,), width=max(2, int(2 * s)),
                fill=(0, 0, 0, 90))
    _spaced(d, bx0 + 20 * s, by0 + 9 * s, subtitle, sf, (255, 255, 255, 255), 3 * s)
    # singer tag (bottom-left)
    r2 = int(26 * s)
    ty = 540 * s
    d.ellipse((50 * s, ty, 50 * s + 2 * r2, ty + 2 * r2), outline=acc, width=max(2, int(2.5 * s)))
    cx, cy = 50 * s + r2, ty + r2
    d.polygon([(cx - 7 * s, cy - 10 * s), (cx - 7 * s, cy + 10 * s), (cx + 11 * s, cy)], fill=acc)
    _spaced(d, 118 * s, ty - 2 * s, singer.upper(), font("bold", int(30 * s)), (255, 255, 255, 255), 3 * s)
    _spaced(d, 118 * s, ty + 34 * s, "ORIGINAL SONG", font("medium", int(19 * s)), acc + (255,), 4 * s)
    return layer


def sparkle_layer(W, H, pal, n=46, seed=3):
    """Static glitter + soft bokeh for the thumbnail."""
    rng = np.random.default_rng(seed)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = pal["rgb"]
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.9)
        r = rng.choice([2, 3, 4, 6, 10, 16], p=[.25, .25, .2, .15, .1, .05]) * H / 720
        a = int(rng.uniform(110, 255) if r < 7 * H / 720 else rng.uniform(40, 90))
        d.ellipse((x - r, y - r, x + r, y + r), fill=acc + (a,))
    return layer.filter(ImageFilter.GaussianBlur(1.2 * H / 720))


def eq_decor(W, H, pal, seed=5):
    """Static LED-style equalizer bars along the bottom (thumbnail only)."""
    rng = np.random.default_rng(seed)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    s = H / 720
    bw, gap, cell = 16 * s, 6 * s, 9 * s
    x, i = 0, 0
    while x < W:
        env = 0.35 + 0.65 * abs(np.sin(i * 0.23)) * rng.uniform(0.6, 1.0)
        cells = int(env * (4 if x < W * 0.5 else 9))
        for c in range(cells):
            y1 = H - 6 * s - c * (cell + 3 * s)
            d.rectangle((x, y1 - cell, x + bw, y1), fill=pal["rgb"] + (int(215 - c * 12),))
        x += bw + gap
        i += 1
    return layer


def make_particles(path, pal, w=1920, h=1080, seconds=10, fps=30, n=80, seed=11):
    """A seamless 10-second loop of drifting, twinkling sparkles on black (screen-blended onto the video)."""
    rng = np.random.default_rng(seed)
    xs, ys = rng.uniform(0, w, n), rng.uniform(0, h, n)
    big = rng.random(n) < 0.18
    sizes = np.where(big, rng.uniform(26, 60, n), rng.uniform(3, 11, n))
    cyc = rng.choice([1, 1, 2], n)
    phase = rng.uniform(0, 1, n)
    amp = rng.uniform(8, 45, n)
    swm = rng.integers(1, 3, n)
    twm = rng.integers(2, 6, n)
    col = np.array(pal["rgb"], np.float32) / 255.0
    sprites = {}

    def sprite(sz):
        k = int(sz)
        if k not in sprites:
            r = k * 2
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
            rr = np.sqrt(xx ** 2 + yy ** 2) / max(k, 1)
            sprites[k] = np.exp(-(rr ** 2) * (1.6 if k > 20 else 3.0))
        return sprites[k]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(round(seconds * fps))
    for f in range(total):
        t = f / total
        frame = np.zeros((h, w, 3), np.float32)
        for i in range(n):
            y = (ys[i] - cyc[i] * h * t) % h
            x = xs[i] + amp[i] * np.sin(2 * np.pi * (swm[i] * t + phase[i]))
            tw = 0.55 + 0.45 * np.sin(2 * np.pi * (twm[i] * t + phase[i] * 3))
            b = tw * (0.30 if big[i] else 1.0)
            sp = sprite(sizes[i])
            r = sp.shape[0] // 2
            x0, y0 = int(x) - r, int(y) - r
            xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + sp.shape[1], w), min(y0 + sp.shape[0], h)
            if xb <= xa or yb <= ya:
                continue
            piece = sp[ya - y0:yb - y0, xa - x0:xb - x0, None] * b
            frame[ya:yb, xa:xb] += piece * col * 1.4
        p.stdin.write((np.clip(frame, 0, 1) * 255).astype(np.uint8).tobytes())
    p.stdin.close()
    p.wait()


def nowplaying_layer(W, H, brand, singer, song, pal):
    """Small persistent tag (top-left) shown after the title card fades."""
    s = H / 720.0
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = pal["rgb"]
    f1, f2 = font("bold", int(24 * s)), font("medium", int(21 * s))
    line2 = f"{singer}  \u2022  {song}"
    w2 = d.textlength(line2, font=f2)
    wbox = max(_spaced_width(d, brand.upper(), f1, 3 * s) + 70 * s, w2 + 40 * s)
    d.rounded_rectangle((36 * s, 30 * s, 36 * s + wbox, 106 * s), int(14 * s), fill=(0, 0, 0, 120))
    r = int(15 * s)
    d.ellipse((50 * s, 42 * s, 50 * s + 2 * r, 42 * s + 2 * r), outline=acc, width=max(2, int(2 * s)))
    cx, cy = 50 * s + r, 42 * s + r
    d.polygon([(cx - 4 * s, cy - 6 * s), (cx - 4 * s, cy + 6 * s), (cx + 7 * s, cy)], fill=acc)
    _spaced(d, 92 * s, 41 * s, brand.upper(), f1, (255, 255, 255, 255), 3 * s)
    d.text((54 * s, 74 * s), line2, font=f2, fill=acc + (255,))
    return layer


# ============================== brand emblem + animated intro ==============================
def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def emblem(size, pal, p_disc=1.0, p_lines=1.0):
    """Half-sun with sound lines under it (our version of a channel logo). Drawn at 2x then reduced."""
    S = size * 2
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx, cy, R = S / 2, S * 0.50, S * 0.30
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).pieslice((cx - R, cy - R, cx + R, cy + R), 180, 360, fill=255)
    top = int(cy - R * p_disc)
    if p_disc < 1.0:
        ImageDraw.Draw(mask).rectangle((0, 0, S, top), fill=0)
    t = np.linspace(0, 1, S, dtype=np.float32)[:, None, None]
    col = np.array((255, 255, 255), np.float32) * (1 - t) + np.array(pal["light"], np.float32) * t
    grad = Image.fromarray(np.broadcast_to(col, (S, S, 3)).astype(np.uint8), "RGB")
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    for i in range(7):
        a = max(0.0, min(1.0, p_lines * 8 - i))
        if a <= 0:
            continue
        y = cy + S * 0.035 + i * S * 0.038
        half = R * (1.25 - i * 0.12)
        d.rectangle((cx - half, y, cx + half, y + S * 0.011), fill=tuple(pal["rgb"]) + (int(255 * a * (1 - i * 0.09)),))
    return im.resize((size, size), Image.LANCZOS)


def _spaced_layer(text, fnt, fill, spacing, pad=30):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    w = int(sum(tmp.textlength(c, font=fnt) + spacing for c in text)) + pad * 2
    h = int(fnt.size * 1.5) + pad
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = pad
    for ch in text:
        d.text((x, pad // 2), ch, font=fnt, fill=fill)
        x += tmp.textlength(ch, font=fnt) + spacing
    return layer


def make_intro(path, brand, pal, seconds=4.0, fps=24, w=1920, h=1080):
    """~4 s channel intro: logo draws in, name fades in, tagline appears. The caller cross-fades it into the video."""
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    dark = np.array([8, 8, 14], np.float32)
    tint = np.array(pal["dark"], np.float32) * 0.16
    bg = (dark * (1 - yy) + (dark + tint) * yy) * np.ones((h, w, 3), np.float32)
    xx = np.linspace(-1, 1, w, dtype=np.float32)[None, :, None]
    bg = bg * (1.0 - 0.35 * (xx ** 2)) + np.array(pal["dark"], np.float32) * 0.05
    bg_img = np.clip(bg, 0, 255).astype(np.uint8)
    name_font, tag_font = font("heavy", 78), font("medium", 30)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(fps), str(path)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(seconds * fps)
    for f in range(total):
        t = f / fps
        base = Image.fromarray(bg_img, "RGB").convert("RGBA")
        fade_in = _ease(t / 0.5)
        em = emblem(420, pal, _ease((t - 0.3) / 1.0), _ease((t - 1.0) / 0.9))
        pulse = 1.0 + 0.035 * np.sin(max(t - 1.8, 0) * 3.0) * min(1.0, max(t - 1.8, 0))
        if pulse != 1.0:
            em = em.resize((int(420 * pulse), int(420 * pulse)), Image.LANCZOS)
        glow = em.filter(ImageFilter.GaussianBlur(22))
        glow.putalpha(glow.getchannel("A").point(lambda v: int(v * 0.55)))
        ex, ey = w // 2 - em.width // 2, int(h * 0.30) - em.height // 2 + 40
        base.alpha_composite(glow, (ex, ey))
        base.alpha_composite(em, (ex, ey))
        a_name = _ease((t - 1.6) / 0.8)
        if a_name > 0:
            sp = 10 + 22 * (1 - a_name)
            lay = _spaced_layer(brand.upper(), name_font, (255, 255, 255, 255), sp)
            lay.putalpha(lay.getchannel("A").point(lambda v, a=a_name: int(v * a)))
            base.alpha_composite(lay, (w // 2 - lay.width // 2, int(h * 0.62)))
        a_tag = _ease((t - 2.3) / 0.6)
        if a_tag > 0:
            lay = _spaced_layer("NEW SONGS EVERY DAY", tag_font, tuple(pal["rgb"]) + (255,), 9)
            lay.putalpha(lay.getchannel("A").point(lambda v, a=a_tag: int(v * a)))
            base.alpha_composite(lay, (w // 2 - lay.width // 2, int(h * 0.62) + 118))
        frame = np.asarray(base.convert("RGB"), np.float32) * fade_in
        pr.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    pr.stdin.close()
    pr.wait()


def watermark(w, h, pal, size=92):
    """Small emblem for the top-right corner of the video."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    em = emblem(size, pal, 1.0, 1.0)
    em.putalpha(em.getchannel("A").point(lambda v: int(v * 0.75)))
    layer.alpha_composite(em, (w - size - 40, 26))
    return layer


def mix_title_layer(W, H, line1, line2, sub, badge, brand, singer, pal, tagline=None, show_singer=True):
    """Premium, consistent thumbnail template: big white line, accent 'MIX 2026' line, boxed sub-tags, duration badge."""
    s = H / 720.0
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = tuple(pal["rgb"])
    # brand
    em = emblem(int(58 * s), pal)
    layer.alpha_composite(em, (int(44 * s), int(30 * s)))
    _spaced(d, 112 * s, 44 * s, brand.upper(), font("bold", int(26 * s)), (255, 255, 255, 255), 4 * s)
    # line 1 (auto-fit, max 2 rows)
    words, size, rows = line1.upper().split(), 150, []
    maxw = 560 * s
    while size > 50:
        f1 = font("heavy", int(size * s))
        rows, cur = [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if d.textlength(t, font=f1) <= maxw:
                cur = t
            else:
                if cur:
                    rows.append(cur)
                cur = w_
        if cur:
            rows.append(cur)
        if len(rows) <= 2:
            break
        size -= 6
    cap = f1.getbbox("H")[3] - f1.getbbox("H")[1]
    y = int(150 * s)
    for r_ in rows:
        _gradient_text(layer, int(48 * s), y, r_, f1, (255, 255, 255), (214, 220, 232), s)
        y += int(cap + size * 0.14 * s)
    # line 2: accent
    size2 = int(size * 0.78)
    f2 = font("heavy", int(size2 * s))
    while d.textlength(line2.upper(), font=f2) > maxw and size2 > 30:
        size2 -= 4
        f2 = font("heavy", int(size2 * s))
    cap2 = f2.getbbox("H")[3] - f2.getbbox("H")[1]
    _gradient_text(layer, int(48 * s), y, line2.upper(), f2, pal["light"], pal["dark"], s)
    y += cap2 + int(30 * s)
    # sub tags with thin lines
    sf = font("medium", int(21 * s))
    sw = _spaced_width(d, sub, sf, 3 * s)
    d.line((50 * s, y, 50 * s + sw, y), fill=(255, 255, 255, 170), width=max(1, int(2 * s)))
    _spaced(d, 50 * s, y + 10 * s, sub, sf, (255, 255, 255, 235), 3 * s)
    d.line((50 * s, y + 46 * s, 50 * s + sw, y + 46 * s), fill=(255, 255, 255, 170), width=max(1, int(2 * s)))
    y += int(66 * s)
    # optional duration badge
    if badge:
        bf = font("bold", int(30 * s))
        bw = d.textlength(badge, font=bf)
        x0 = 50 * s
        d.rounded_rectangle((x0, y, x0 + bw + 78 * s, y + 56 * s), int(28 * s), fill=acc + (255,))
        cx, cy = x0 + 34 * s, y + 28 * s
        d.ellipse((cx - 13 * s, cy - 13 * s, cx + 13 * s, cy + 13 * s), outline=(15, 15, 25, 255), width=max(2, int(2.5 * s)))
        d.line((cx, cy, cx, cy - 8 * s), fill=(15, 15, 25, 255), width=max(2, int(2.5 * s)))
        d.line((cx, cy, cx + 6 * s, cy + 2 * s), fill=(15, 15, 25, 255), width=max(2, int(2.5 * s)))
        d.text((x0 + 58 * s, y + 8 * s), badge, font=bf, fill=(15, 15, 25, 255))
    y += int(66 * s) if badge else int(0)
    # script tagline (like the premium mix channels), then optional singer tag
    y += int(6 * s) if not badge else int(70 * s)
    if tagline:
        tf = font("script", int(40 * s))
        tw = d.textlength(tagline, font=tf)
        glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).text((52 * s, y), tagline, font=tf, fill=tuple(pal["rgb"]) + (255,))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(7 * s)))
        d.text((52 * s, y), tagline, font=tf, fill=tuple(pal["light"]) + (255,))
        d.line((54 * s, y + 52 * s, 54 * s + tw * 0.9, y + 52 * s), fill=acc + (200,), width=max(1, int(2 * s)))
    if show_singer:
        _spaced(d, 52 * s, 676 * s, singer.upper() + "   \u2022   ORIGINAL SONGS", font("medium", int(18 * s)), acc + (255,), 3 * s)
    return layer


def bottom_title_layer(W, H, line1, line2, pal, brand, tagline=None):
    """Variant C: close-up face, big centred words along the bottom."""
    s = H / 720.0
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = tuple(pal["rgb"])
    layer.alpha_composite(emblem(int(52 * s), pal), (int(40 * s), int(28 * s)))
    _spaced(d, 104 * s, 40 * s, brand.upper(), font("bold", int(24 * s)), (255, 255, 255, 255), 4 * s)
    size, maxw = 170, 1160 * s
    f1 = font("heavy", int(size * s))
    while d.textlength(line1.upper(), font=f1) > maxw and size > 60:
        size -= 6
        f1 = font("heavy", int(size * s))
    cap = f1.getbbox("H")[3] - f1.getbbox("H")[1]
    y = int(H - cap - 150 * s)
    x = int((W - d.textlength(line1.upper(), font=f1)) / 2)
    _gradient_text(layer, x, y, line1.upper(), f1, (255, 255, 255), (214, 220, 232), s)
    f2 = font("bold", int(46 * s))
    t2 = (line2.upper() + ("   \u2022   " + tagline if tagline else ""))
    x2 = int((W - _spaced_width(d, t2, f2, 4 * s)) / 2)
    _spaced(d, x2, y + cap + 26 * s, t2, f2, acc + (255,), 4 * s)
    return layer


# ----------------------------- bar equalizer (like the premium mix channels) -----------------------------
def render_eq(audio, start, dur, out, pal, w=780, h=170, fps=24, bars=24):
    """Rounded glowing bars that follow the music, resting as small dots when quiet. Black background (blended with 'screen')."""
    import subprocess
    sr = 22050
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(audio), "-ac", "1",
                          "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    nfr = int(dur * fps)
    win = 2048
    freqs = np.fft.rfftfreq(win, 1 / sr)
    edges = np.geomspace(55, 9000, bars + 1)
    idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(bars)]
    hann = np.hanning(win).astype(np.float32)
    spec = np.zeros((nfr, bars), np.float32)
    for f in range(nfr):
        c = int((f / fps) * sr)
        seg = x[c:c + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        m = np.abs(np.fft.rfft(seg * hann))
        spec[f] = [m[i].mean() if len(i) else 0 for i in idx]
    spec = np.log1p(spec * 30)
    spec = spec * (1 + 0.55 * np.linspace(0, 1, bars))[None, :]          # lift highs a little so every bar moves
    hi = np.percentile(spec, 97) or 1.0
    spec = np.clip(spec / hi, 0, 1) ** 1.25
    sm = np.zeros(bars, np.float32)
    bw = w / bars
    barw = bw * 0.52
    acc = np.array(pal["rgb"], np.float32)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-g", "48", str(out)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(nfr):
        v = spec[f]
        sm = np.where(v > sm, sm + (v - sm) * 0.75, sm + (v - sm) * 0.22)   # fast rise, slower fall = smooth
        mask = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(mask)
        for i in range(bars):
            bh = max(barw, sm[i] * (h - 14))
            cx = bw * (i + 0.5)
            dr.rounded_rectangle((cx - barw / 2, h - 7 - bh, cx + barw / 2, h - 7), radius=barw / 2, fill=255)
        glow = np.asarray(mask.filter(ImageFilter.GaussianBlur(9)), np.float32)[:, :, None] / 255.0
        core = np.asarray(mask, np.float32)[:, :, None] / 255.0
        frame = np.clip(core * 255 + glow * acc[None, None, :] * 0.85, 0, 255).astype(np.uint8)
        try:
            pr.stdin.write(frame.tobytes())
        except BrokenPipeError:
            break
    pr.stdin.close()
    if pr.wait() != 0:
        raise RuntimeError("equalizer video failed")


# ----------------------------- SIMPLE thumbnail text: song name + song type, two colours -----------------------------
# (song-name colour, song-type colour) per singer: bright, clearly different from each other, never yellow
TEXT_PAIRS = {
    "mira": ((255, 112, 170), (120, 232, 255)),    # hot pink  + ice blue
    "kai": ((90, 220, 255), (255, 156, 120)),      # cyan      + coral
    "luna": ((200, 140, 255), (130, 255, 214)),    # violet    + mint
    "jax": ((255, 150, 80), (120, 214, 255)),      # orange    + sky blue
    "nova": ((92, 255, 205), (255, 140, 196)),     # mint      + pink
}


def text_pair(persona_id):
    return TEXT_PAIRS.get(persona_id, TEXT_PAIRS["mira"])


def _tint(c, k):
    return tuple(int(v + (255 - v) * k) for v in c)


def simple_title_layer(W, H, name, genre, pair, where="left"):
    """Only two things: the song name (brush script, colour 1) and the song type (spaced capitals, colour 2)."""
    s = H / 720.0
    c1, c2 = pair
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    maxw = (600 if where == "left" else 1100) * s
    words = str(name).strip().split() or ["Song"]
    size = 190
    while True:
        f1 = font("script", int(size * s))
        rows = [" ".join(words)] if where != "left" or len(words) == 1 else None
        if rows is None:                                  # at most two rows, balanced
            best = None
            for k in range(1, len(words)):
                a, b = " ".join(words[:k]), " ".join(words[k:])
                w_ = max(d.textlength(a, font=f1), d.textlength(b, font=f1))
                if best is None or w_ < best[0]:
                    best = (w_, [a, b])
            rows = best[1] if best and d.textlength(" ".join(words), font=f1) > maxw else [" ".join(words)]
        if max(d.textlength(r, font=f1) for r in rows) <= maxw or size <= 60:
            break
        size -= 6
    asc = f1.getbbox("Hg")[3] - f1.getbbox("Hg")[1]
    lh = int(asc * 1.05)
    gf = font("medium", int(50 * s))
    gtxt = str(genre).upper()
    gw = _spaced_width(d, gtxt, gf, 9 * s)
    block_h = len(rows) * lh + int(34 * s) + int(52 * s)
    y0 = int((H - block_h) / 2) if where == "left" else int(H - block_h - 95 * s)
    for i, r_ in enumerate(rows):
        rw = d.textlength(r_, font=f1)
        x = int(60 * s) if where == "left" else int((W - rw) / 2)
        y = y0 + i * lh
        # soft coloured glow
        glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).text((x, y), r_, font=f1, fill=c1 + (255,))
        g = glow.filter(ImageFilter.GaussianBlur(14 * s))
        g.putalpha(g.getchannel("A").point(lambda v: int(v * 0.75)))
        layer.alpha_composite(g)
        # dark soft shadow so it reads on any picture
        sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x + 4 * s, y + 6 * s), r_, font=f1, fill=(0, 0, 0, 210))
        layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6 * s)))
        # letters: light tint on top fading to the full colour
        bb = d.textbbox((x, y), r_, font=f1)
        mask = Image.new("L", layer.size, 0)
        ImageDraw.Draw(mask).text((x, y), r_, font=f1, fill=255)
        top, bot = bb[1], bb[3]
        t = np.clip((np.arange(H)[:, None] - top) / max(bot - top, 1), 0, 1)
        col = np.zeros((H, W, 3), np.float32)
        a_, b_ = np.array(_tint(c1, 0.55), np.float32), np.array(c1, np.float32)
        col[:] = a_ * (1 - t[:, :, None]) + b_ * t[:, :, None]
        fill = Image.fromarray(col.astype(np.uint8), "RGB").convert("RGBA")
        fill.putalpha(mask)
        layer.alpha_composite(fill)
    gx = int(64 * s) if where == "left" else int((W - gw) / 2)
    gy = y0 + len(rows) * lh + int(34 * s)
    glow2 = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    _spaced(ImageDraw.Draw(glow2), gx, gy, gtxt, gf, c2 + (255,), 9 * s)
    g2 = glow2.filter(ImageFilter.GaussianBlur(8 * s))
    g2.putalpha(g2.getchannel("A").point(lambda v: int(v * 0.8)))
    layer.alpha_composite(g2)
    _spaced(d, gx + 2 * s, gy + 3 * s, gtxt, gf, (0, 0, 0, 150), 9 * s)
    _spaced(d, gx, gy, gtxt, gf, c2 + (255,), 9 * s)
    return layer


# ----------------------------- playlist thumbnail text: the words people SEARCH, nothing else -----------------------------
def playlist_title_layer(W, H, main, sub, accent, where="left"):
    """Elegant serif main words in white + one small line in an accent colour. where: left | center | bottom."""
    s = H / 720.0
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    words = str(main).strip().split() or ["Playlist"]
    maxw = (560 if where == "left" else 1000) * s
    size = 200
    while True:
        f1 = font("serif", int(size * s))
        rows = [" ".join(words)]
        if len(words) > 1 and d.textlength(rows[0], font=f1) > maxw and where == "left" or (len(words) > 2 and where == "bottom"):
            best = None
            for k in range(1, len(words)):
                a, b = " ".join(words[:k]), " ".join(words[k:])
                w_ = max(d.textlength(a, font=f1), d.textlength(b, font=f1))
                if best is None or w_ < best[0]:
                    best = (w_, [a, b])
            rows = best[1]
        if max(d.textlength(r, font=f1) for r in rows) <= maxw or size <= 70:
            break
        size -= 6
    bb = f1.getbbox("Hg")
    lh = int((bb[3] - bb[1]) * 1.08)
    sf = font("medium", int(44 * s))
    stxt = str(sub).upper()
    sw = _spaced_width(d, stxt, sf, 8 * s)
    block = len(rows) * lh + int(40 * s) + int(52 * s)
    if where == "bottom":
        y0 = int(H - block - 70 * s)
    elif where == "center":
        y0 = int(H * 0.16)
    else:
        y0 = int(H * 0.12)
    for i, r_ in enumerate(rows):
        rw = d.textlength(r_, font=f1)
        x = int(64 * s) if where == "left" else int((W - rw) / 2)
        y = y0 + i * lh
        sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x + 3 * s, y + 6 * s), r_, font=f1, fill=(0, 0, 0, 200))
        layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7 * s)))
        d.text((x, y), r_, font=f1, fill=(255, 255, 255, 255))
    sx = int(68 * s) if where == "left" else int((W - sw) / 2)
    sy = y0 + len(rows) * lh + int(40 * s)
    sh2 = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    _spaced(ImageDraw.Draw(sh2), sx + 2 * s, sy + 3 * s, stxt, sf, (0, 0, 0, 190), 8 * s)
    layer.alpha_composite(sh2.filter(ImageFilter.GaussianBlur(4 * s)))
    _spaced(d, sx, sy, stxt, sf, tuple(accent) + (255,), 8 * s)
    return layer
