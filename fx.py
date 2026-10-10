"""Visual effects: title graphic, sparkles, equalizer look. Shared by the thumbnail and the video."""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path("fonts")
PALETTES = {
    "gold": {"light": (255, 226, 135), "dark": (196, 135, 36), "hex": "0xF5C85A", "rgb": (245, 200, 90)},
    "blue": {"light": (160, 210, 255), "dark": (40, 110, 235), "hex": "0x6CB4FF", "rgb": (108, 180, 255)},
    "pink": {"light": (255, 175, 218), "dark": (215, 50, 140), "hex": "0xFF6EC0", "rgb": (255, 110, 192)},
    "teal": {"light": (150, 255, 236), "dark": (20, 165, 155), "hex": "0x4FF0D8", "rgb": (79, 240, 216)},
}
PERSONA_PALETTE = {"mira": "gold", "kai": "blue", "luna": "pink", "jax": "gold", "nova": "teal"}


def palette_for(persona_id):
    return PALETTES[PERSONA_PALETTE.get(persona_id, "gold")]


def font(kind, size):
    """kind: heavy | medium | bold. Uses nicer fonts if they were downloaded, else safe fallbacks."""
    order = {
        "heavy": [FONTS / "Poppins-ExtraBold.ttf", FONTS / "Anton-Regular.ttf"],
        "bold": [FONTS / "Poppins-Bold.ttf", FONTS / "Anton-Regular.ttf"],
        "medium": [FONTS / "Poppins-Medium.ttf"],
    }[kind] + [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]
    for f in order:
        if f.exists():
            return ImageFont.truetype(str(f), size)
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
    total = seconds * fps
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
