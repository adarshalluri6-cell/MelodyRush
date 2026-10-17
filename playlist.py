"""Instrumental study/focus PLAYLISTS: niches, SEO plan, track list, automatic curation, mixdown, chapters, description.

Why this format: students and remote workers search for "study music", "lofi", "focus playlist" (so we can rank in search),
instrumental music is neutral-to-helpful for studying (lyrics slightly hurt reading/memory), long playlists create long
watch sessions, and chapters + a clean title make the video look curated instead of mass-produced.
"""
import math
import random
import re
import subprocess
import time
from pathlib import Path

import numpy as np

import brain
import media
import seo

CHANNEL = brain.CHANNEL_NAME

# Each niche = one search-demand family. 'accent' is the second thumbnail colour (never yellow).
NICHES = [
    {"id": "lofi", "label": "lofi study music", "accent": (255, 168, 150),
     "seeds": ["lofi study music", "lofi hip hop study", "lofi beats to study"],
     "base": "lofi hip hop, mellow Rhodes piano, dusty vinyl warmth, soft boom bap drums, warm bass, relaxed",
     "extras": ["jazzy guitar licks", "soft vibraphone", "gentle tape wobble", "muted trumpet touches", "warm pad", "light rain texture"],
     "moods": ["cozy", "calm", "nostalgic", "dreamy", "focused", "mellow"], "bpm": (68, 88),
     "scenes": ["a cozy study desk by a rain-streaked window at night, warm desk lamp, open notebooks, steaming coffee mug, a sleepy cat on the windowsill, blurred city lights",
                "a tidy wooden desk with a laptop and stacked books beside a window, soft evening rain outside, string lights, a small plant"]},
    {"id": "piano", "label": "soft piano study music", "accent": (160, 215, 255),
     "seeds": ["piano study music", "relaxing piano for studying", "soft piano focus music"],
     "base": "solo felt piano, gentle, intimate, warm room reverb, slow melodic, calm",
     "extras": ["very light strings pad", "soft cello touches", "gentle music box", "warm ambient texture"],
     "moods": ["peaceful", "tender", "reflective", "hopeful", "serene"], "bpm": (60, 78),
     "scenes": ["a grand piano in a sunlit quiet room with soft morning light through sheer curtains, books on a nearby shelf, a mug of tea",
                "an upright piano by a window at dusk, warm lamp glow, a small notebook on the keys, autumn leaves outside"]},
    {"id": "jazz", "label": "cafe jazz study music", "accent": (255, 190, 160),
     "seeds": ["cafe jazz study music", "smooth jazz for studying", "jazz study playlist"],
     "base": "smooth cafe jazz, upright bass, brushed drums, soft piano trio, warm, relaxed swing",
     "extras": ["muted trumpet", "soft saxophone", "nylon guitar comping", "light vibraphone"],
     "moods": ["cozy", "easygoing", "warm", "late-night", "mellow"], "bpm": (72, 100),
     "scenes": ["a quiet cozy cafe corner table by a rainy window with a latte, an open book and warm hanging lights, blurred street outside",
                "a small jazz cafe in the evening with candle-lit wooden tables, a steaming cup and a notebook, warm golden bokeh"]},
    {"id": "focus", "label": "deep focus music", "accent": (140, 235, 205),
     "seeds": ["deep focus music", "concentration music for studying", "focus music for work"],
     "base": "calm electronic focus music, soft synth pads, gentle pulse, light steady beat, minimal, clean, warm",
     "extras": ["soft arpeggio", "airy texture", "warm sub bass", "light glass bells"],
     "moods": ["focused", "steady", "clear", "calm", "flowing"], "bpm": (80, 104),
     "scenes": ["a minimalist desk setup near a large window at dawn, soft blue light, a laptop, a notebook and a green plant, calm atmosphere",
                "a quiet library reading nook with a lamp, tall bookshelves and a steaming mug, soft misty window light"]},
    {"id": "acoustic", "label": "acoustic chill study music", "accent": (255, 180, 160),
     "seeds": ["acoustic study music", "calm guitar music for studying", "chill acoustic instrumental"],
     "base": "gentle fingerstyle acoustic guitar, warm, soft, light percussion, calm, organic",
     "extras": ["soft piano", "light shaker", "warm upright bass", "gentle strings"],
     "moods": ["warm", "peaceful", "hopeful", "gentle", "sunny"], "bpm": (66, 92),
     "scenes": ["an acoustic guitar leaning on a cozy reading chair by a sunny window, open books and a cup of tea, soft morning light, a sleepy dog on a rug",
                "a wooden porch table with an acoustic guitar, notebook and mug, soft autumn light, blurred trees"]},
]
NAME_A = ["Quiet", "Golden", "Slow", "Soft", "Blue", "Paper", "Midnight", "Morning", "Warm", "Gentle", "Silver", "Distant", "Calm", "Hidden", "Faded"]
NAME_B = ["Hours", "Pages", "Window", "Rain", "Notes", "Light", "Thoughts", "Streets", "Tea", "Margins", "Lamp", "Drift", "Shelf", "Waves", "Echoes"]


def log(m):
    print(f"[playlist] {m}", flush=True)


def niche_by_id(i):
    return next((n for n in NICHES if n["id"] == i), NICHES[0])


# ----------------------------- plan --------------------------------------------------------------
def _prompt(niche, minutes, seo_block, context):
    return f"""You run the YouTube channel "{CHANNEL}": long INSTRUMENTAL playlists for students and remote workers in the US, UK, Canada and Australia.
Today's playlist: {niche['label']}, about {brain.duration_label(minutes)} long. There is no singing: viewers use it to study, read, code and work.

{seo_block}

{context}

Return ONLY a JSON object with these keys:
"primary_keyword": the ONE most-searched phrase from the research that honestly fits (lowercase, e.g. "lofi study music"). If there is no research, use "{niche['label']}".
"theme": 2 to 4 words for today's angle, e.g. "rainy night focus", "exam week", "sunday reading".
"title": max 68 characters. Pattern: "<Primary Keyword in Title Case> | <theme or benefit phrase> ([DURATION])". Keep the exact text [DURATION]. The primary keyword must come first. Natural English, no emojis, no ALL CAPS, no clickbait, no fake claims, no artist or brand names. It must tell the viewer what they get and when to use it.
"thumb_main": the 2 or 3 words people actually search, Title Case, shown big on the thumbnail (e.g. "Study Playlist", "Lofi Study", "Deep Focus").
"thumb_sub": 2 or 3 words for the mood or moment (e.g. "Rainy Night", "Exam Week").
"description_intro": 3 sentences. The FIRST sentence (the only part visible before "show more") must contain the primary keyword and be under 140 characters. Then say it is instrumental, what it helps with, and the mood. Truthful, warm, no begging.
"perfect_for": array of 6 short uses (e.g. "studying", "homework", "reading", "coding", "working from home", "relaxing").
"first_comment": one friendly question asking what they are studying or working on tonight (max 160 characters, no asking for likes or subscribes).
"tags": array of 18 search tags (primary keyword first, then specific phrases from the research, then broad ones; include "instrumental", "no lyrics", "2026").
"hashtags": array of 3 hashtags.
"scene": ONE vivid description (max 45 words) of a photorealistic, cozy, beautiful scene matching the theme, in the style of: {random.choice(niche['scenes'])}. No people, no text."""


def _names_prompt(niche, theme, k, used):
    return (f'Give {k} DIFFERENT short evocative instrumental track titles (2 to 3 words each) for a "{niche["label"]}" playlist with the theme '
            f'"{theme}". Calm, poetic, no artist names, no numbers. Already used (do not repeat): {", ".join(used[-40:]) or "none"}. '
            'Return ONLY JSON: {"names": ["...", "..."]}')


def fallback_names(k, used):
    pool = [f"{a} {b}" for a in NAME_A for b in NAME_B if f"{a} {b}" not in used]
    random.shuffle(pool)
    return pool[:k]


def make_tracks(niche, names, n):
    rng = random.Random()
    tracks = []
    for i in range(n):
        ex = rng.sample(niche["extras"], k=min(2, len(niche["extras"])))
        bpm = rng.randint(*niche["bpm"])
        cap = f"{niche['base']}, {', '.join(ex)}, {rng.choice(niche['moods'])}, {bpm} bpm, instrumental, no vocals, no singing"
        tracks.append({"song_title": names[i], "caption": cap, "bpm": bpm, "duration": rng.randint(150, 190),
                       "lyrics": "[Instrumental]", "instrumental": True})
    return tracks


def make_plan(niche, minutes, research, context):
    """Header (title, SEO, thumbnail words, scene) from the AI, track list built here. Never fails: has fallbacks."""
    top = None
    for attempt in range(3):
        top = brain.llm_json(_prompt(niche, minutes, seo.prompt_block(research), context))
        if top and top.get("title"):
            break
        log(f"plan header failed ({attempt + 1}/3)")
        top = None
        time.sleep(20)
    top = top or {}
    kw = str(top.get("primary_keyword") or (research.get("keywords") or [niche["label"]])[0]).lower().strip()[:60]
    theme = str(top.get("theme") or "deep focus")[:40]
    title = re.sub(r"[<>]", "", str(top.get("title") or "")).strip()
    if "[DURATION]" not in title:
        title = f"{title} ([DURATION])" if title and len(title) < 80 else ""
    if not title or kw.split()[0] not in title.lower():
        title = f"{kw.title()} | {theme.title()} ([DURATION])"
    avg = 170
    n_target = max(6, math.ceil(minutes * 60 / avg))
    n_make = n_target + max(3, math.ceil(0.15 * n_target))
    names, fails = [], 0
    while len(names) < n_make and fails < 3:
        k = min(25, n_make - len(names))
        got = (brain.llm_json(_names_prompt(niche, theme, k, names)) or {}).get("names") or []
        good = []
        for g in got:
            g = re.sub(r"[<>{}\\\\]", "", str(g)).strip()[:40]
            if g and g.lower() not in {x.lower() for x in names + good}:
                good.append(g)
        if not good:
            fails += 1
            time.sleep(15)
            continue
        names += good[:k]
    if len(names) < n_make:
        names += fallback_names(n_make - len(names), names)
    tracks = make_tracks(niche, names[:n_make], n_make)
    scene = str(top.get("scene") or random.choice(niche["scenes"]))[:400]
    plan = {
        "niche": niche["id"], "minutes": minutes, "primary_keyword": kw, "theme": theme,
        "title": title[:100],
        "thumb_main": str(top.get("thumb_main") or niche["label"].split(" music")[0].title())[:28],
        "thumb_sub": str(top.get("thumb_sub") or theme.title())[:28],
        "description_intro": str(top.get("description_intro") or
                                 f"{kw.capitalize()}: a long instrumental playlist for {theme}. No vocals, just calm music to help you focus.")[:700],
        "perfect_for": [str(x)[:30] for x in (top.get("perfect_for") or ["studying", "homework", "reading", "coding", "working from home", "relaxing"])][:8],
        "first_comment": str(top.get("first_comment") or "What are you studying or working on tonight?")[:200],
        "hashtags": [h if str(h).startswith("#") else "#" + str(h).replace(" ", "")
                     for h in (top.get("hashtags") or ["#studymusic", "#lofi", "#focus"])][:3],
        "image_prompt": (f"{scene}, photorealistic, cinematic soft lighting, shallow depth of field, rich warm colors, highly detailed, "
                         "wide shot, empty calm space in the upper part of the frame, no people, no text"),
        "negative_prompt": ("people, person, human, face, hands, text, letters, words, watermark, logo, signature, blurry, low quality, "
                            "cartoon, 3d render, oversaturated, deformed, cluttered"),
        "tracks": tracks, "n_target": n_target,
    }
    plan["tags"] = seo.merge_tags(kw, theme, top.get("tags") or [kw, "study music", "instrumental", "no lyrics", "2026"], research, lyrics=False)
    log(f"plan: '{plan['title']}' | {n_make} tracks to make, keep about {n_target}")
    return plan


# ----------------------------- automatic curation ------------------------------------------------
def _decode(path, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32), sr


def analyze(path):
    """Cheap objective checks. Returns features + a quality score (higher is better) + reject reason (or None)."""
    x, sr = _decode(path)
    if len(x) < sr * 20:
        return {"score": -999, "reject": "too short", "energy": -99, "bright": 0}
    win = sr // 2
    n = len(x) // win
    fr = x[: n * win].reshape(n, win)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    silent = float((db < -52).mean())
    peak = float(np.abs(x).max())
    clip = float((np.abs(x) > 0.985).mean())
    live = db[db > -52]
    energy = float(live.mean()) if len(live) else -99.0
    dyn = float(live.std()) if len(live) else 0.0
    # spectral shape on ~1 s frames
    seg = 2048
    hop = sr
    spans = [x[i:i + seg] for i in range(0, len(x) - seg, hop)]
    cent, flat = [], []
    hann = np.hanning(seg).astype(np.float32)
    freqs = np.fft.rfftfreq(seg, 1 / sr)
    for s_ in spans:
        m = np.abs(np.fft.rfft(s_ * hann)) + 1e-9
        cent.append(float((freqs * m).sum() / m.sum()))
        flat.append(float(np.exp(np.log(m).mean()) / m.mean()))
    cent, flat = np.array(cent), np.array(flat)
    bright, flatness, cvar = float(cent.mean()), float(np.median(flat)), float(cent.std())
    score, reject = 100.0, None
    if energy < -45:
        reject = "almost silent"
    elif silent > 0.18:
        reject = "long silent parts"
    elif flatness > 0.42:
        reject = "sounds like noise"
    elif clip > 0.02:
        reject = "heavily distorted"
    elif peak < 0.02:
        reject = "no signal"
    score -= silent * 220 + clip * 600
    score -= max(0.0, flatness - 0.2) * 120
    score -= max(0.0, bright - 3500) / 60
    score -= max(0.0, dyn - 9) * 3
    score -= 15 if cvar < 120 else 0                      # static drone, nothing happens
    return {"score": round(score, 1), "reject": reject, "energy": energy, "bright": bright, "dyn": dyn, "silent": silent,
            "clip": clip, "flat": flatness}


def curate(tracks, target_s, avg_default=170):
    """tracks: [{'audio','title','bpm',...}]. Keep the best until the target length is reached, then order them smoothly."""
    scored = []
    for t in tracks:
        try:
            f = analyze(t["audio"])
        except Exception as e:
            f = {"score": -999, "reject": f"unreadable ({str(e)[:40]})", "energy": -99, "bright": 0}
        t = dict(t, **f)
        try:
            t["dur"] = media.probe_duration(t["audio"])
        except Exception:
            t["dur"] = 0
        scored.append(t)
        log(f"  {t.get('song_title', '?')[:28]:28s} score {t['score']:6.1f} {('REJECT: ' + t['reject']) if t.get('reject') else ''}")
    good = sorted([t for t in scored if not t.get("reject") and t["score"] >= 30], key=lambda t: -t["score"])
    keep, total = [], 0.0
    for t in good:
        if total >= target_s:
            break
        keep.append(t)
        total += t["dur"]
    if len(keep) < 3:                                         # never end up with nothing: take whatever exists
        keep = [t for t in scored if t["dur"] > 20][:max(3, len(keep))] or scored[:3]
    log(f"kept {len(keep)} of {len(scored)} tracks ({total / 60:.0f} min), dropped {len(scored) - len(keep)}")
    return order_for_flow(keep)


def order_for_flow(tracks, seed=None):
    """Smooth listening path: neighbours are similar in loudness, brightness and tempo (no jarring jumps)."""
    if len(tracks) <= 2:
        return tracks
    rng = random.Random(seed)
    def col(k, default=0.0):
        v = np.array([float(t.get(k) or default) for t in tracks])
        sd = v.std() or 1.0
        return (v - v.mean()) / sd
    feats = np.stack([col("energy"), col("bright"), col("bpm", 80)], axis=1)
    left = list(range(len(tracks)))
    start = min(left, key=lambda i: abs(feats[i][0]) + rng.random() * 0.3)
    path = [start]
    left.remove(start)
    while left:
        cur = feats[path[-1]]
        nxt = min(left, key=lambda i: float(np.linalg.norm(feats[i] - cur)) + rng.random() * 0.35)
        path.append(nxt)
        left.remove(nxt)
    return [tracks[i] for i in path]


# ----------------------------- mixdown ----------------------------------------------------------
def build_audio(tracks, workdir, out_mp3):
    """Trim silence, level every track to the same loudness, soft fade in/out, join. Returns (durations, offsets)."""
    workdir = Path(workdir)
    wavs, durs = [], []
    chain = ("silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.1,areverse,"
             "silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.1,areverse,"
             "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=1.0,areverse,afade=t=in:d=2.5,areverse")
    for i, t in enumerate(tracks):
        w = workdir / f"pl_{i:03d}.wav"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(t["audio"]), "-af", chain, "-ar", "44100", "-ac", "2", str(w)], check=True)
        except Exception:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(t["audio"]), "-af", "afade=t=in:d=1.0", "-ar", "44100",
                            "-ac", "2", str(w)], check=True)
        d = media.probe_duration(w)
        if d < 20:
            w.unlink(missing_ok=True)
            continue
        wavs.append((w, t))
        durs.append(d)
    lst = workdir / "pl_parts.txt"
    lst.write_text("".join(f"file '{Path(w).resolve()}'\n" for w, _ in wavs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", "-b:a", "192k",
                    str(out_mp3)], check=True)
    for w, _ in wavs:
        w.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    offsets, t0 = [], 0.0
    for d in durs:
        offsets.append(t0)
        t0 += d
    kept = [t for _, t in wavs]
    log(f"audio ready: {len(kept)} tracks, {t0 / 60:.1f} minutes")
    return kept, durs, offsets


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def chapter_lines(tracks, offsets):
    return [f"{stamp(o)} {t['song_title']}" for t, o in zip(tracks, offsets)]


def build_description(plan, chapters):
    uses = ", ".join(plan["perfect_for"])
    lines = [plan["description_intro"], "",
             f"Perfect for: {uses}.", "",
             "Instrumental, no lyrics, no interruptions. Save this playlist for your next study session.", "",
             "TRACKLIST", *chapters, "",
             " ".join(plan["hashtags"]), "",
             "All music and images are AI-generated. Original instrumental tracks."]
    text = "\n".join(lines)
    while len(text) > 4900 and chapters:                     # very long playlists: keep the description under YouTube's limit
        chapters = chapters[:-1]
        lines = lines[: lines.index("TRACKLIST") + 1] + chapters + [""] + [" ".join(plan["hashtags"]), "",
                 "All music and images are AI-generated. Original instrumental tracks."]
        text = "\n".join(lines)
    return text
