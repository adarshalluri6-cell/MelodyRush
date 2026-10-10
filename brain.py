"""Strategy, learning from past videos, and content planning (LLM)."""
import datetime as dt
import json
import math
import os
import random
import re
from pathlib import Path

import requests

DATA = Path(os.getenv("DATA_DIR", "data"))
HISTORY_FILE = DATA / "history.json"
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "MelodyRush")

# Fictional singers. Edit freely. Check that the names are not real artists before launching.
PERSONAS = [
    {"id": "mira", "name": "Mira Vale", "voice": "warm airy female vocal",
     "look": "young woman, long wavy auburn hair, freckles, vintage denim jacket, golden hour light",
     "genres": ["indie pop", "acoustic pop", "dream pop"]},
    {"id": "kai", "name": "Kai Monroe", "voice": "smooth soulful male tenor vocal",
     "look": "young man, short curly black hair, round gold glasses, cream oversized knit sweater",
     "genres": ["r&b", "soul pop", "chill pop"]},
    {"id": "luna", "name": "Luna Reyes", "voice": "powerful emotional female pop vocal",
     "look": "woman, sleek silver-blue bob haircut, glossy lips, metallic jacket, neon city glow",
     "genres": ["synth pop", "dance pop", "electropop"]},
    {"id": "jax", "name": "Jax Calloway", "voice": "raspy heartfelt male vocal",
     "look": "man with stubble beard, worn leather jacket, acoustic guitar, sunset backlight",
     "genres": ["country pop", "folk pop", "pop rock"]},
    {"id": "nova", "name": "Nova Hart", "voice": "bright dynamic gender-neutral vocal",
     "look": "singer with shaggy platinum hair, glitter makeup, star earrings, colorful stage lights",
     "genres": ["alt pop", "bedroom pop", "pop punk"]},
]
HOOKS = ["emotional confession", "curiosity question", "bold statement", "relatable moment", "story tease"]


# ----------------------------- history ---------------------------------------
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"videos": [], "playlists": {}}


def save_history(h):
    DATA.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(h, indent=2), encoding="utf-8")


def age_days(v):
    t = dt.datetime.fromisoformat(v["date"])
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


def video_score(m, age):
    """One number: how well a video did. Higher is better."""
    views, likes, comments = m.get("views", 0), m.get("likes", 0), m.get("comments", 0)
    vpd = views / max(min(age, 14), 1)
    engagement = (likes + 3 * comments) / max(views, 20)
    retention = (m.get("avg_view_pct") or 35) / 100
    subs = m.get("subs", 0)
    return round(math.log1p(vpd) + 8 * engagement + 1.5 * retention + 0.7 * math.log1p(subs), 4)


def update_metrics(hist, api):
    vids = [v for v in hist["videos"] if age_days(v) > 0.5]
    if not vids:
        return
    ids = [v["id"] for v in vids][-50:]
    stats = api.fetch_stats(ids)
    first = min(v["date"] for v in vids)[:10]
    extra = api.fetch_analytics(ids, first)
    for v in vids:
        m = v.setdefault("metrics", {})
        m.update(stats.get(v["id"], {}))
        m.update(extra.get(v["id"], {}))
        if age_days(v) >= 2:
            v["score"] = video_score(m, age_days(v))
    print(f"[learn] updated metrics for {len(ids)} videos")


# ----------------------------- decisions -------------------------------------
def pick(hist, key, options, eps=0.3):
    """Epsilon-greedy: mostly repeat what works, sometimes try something new."""
    scored = [v for v in hist["videos"] if v.get("score") is not None]
    by = {o: [v["score"] for v in scored if v.get(key) == o] for o in options}
    unseen = [o for o in options if not by[o]]
    if unseen:
        return random.choice(unseen), "try-new"
    if random.random() < eps:
        return random.choice(options), "explore"
    return max(options, key=lambda o: sum(by[o]) / len(by[o])), "best-so-far"


def choose(hist):
    persona_id, m1 = pick(hist, "persona", [p["id"] for p in PERSONAS])
    persona = next(p for p in PERSONAS if p["id"] == persona_id)
    genre, m2 = pick(hist, "genre", persona["genres"])
    hook, m3 = pick(hist, "hook", HOOKS)
    print(f"[strategy] persona={persona['name']} ({m1}), genre={genre} ({m2}), hook={hook} ({m3})")
    return persona, genre, hook


def learning_context(hist, api):
    scored = sorted([v for v in hist["videos"] if v.get("score") is not None], key=lambda v: -v["score"])
    if len(scored) < 3:
        return "No performance data yet. Use your best judgment for the US audience."
    fmt = lambda v: f'- "{v["title"]}" (singer {v["persona"]}, {v["genre"]}, hook {v["hook"]}, score {v["score"]})'
    ctx = ["BEST performing videos so far:"] + [fmt(v) for v in scored[:3]]
    ctx += ["WORST performing videos so far:"] + [fmt(v) for v in scored[-3:]]
    try:
        comments = api.top_comments(scored[0]["id"])
        if comments:
            ctx.append("What viewers wrote under the best video (use their language and themes):")
            ctx += [f"- {c[:140]}" for c in comments[:6]]
    except Exception:
        pass
    ctx.append("Make the new video resemble what worked, without copying titles or lyrics.")
    return "\n".join(ctx)


# ----------------------------- LLM -------------------------------------------
def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a:b + 1])


def _gemini(prompt):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no GEMINI_API_KEY")
    models = [os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), "gemini-flash-latest", "gemini-2.5-flash"]
    last = ""
    for attempt in range(2):
        for m in dict.fromkeys(models):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                  headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                  json={"contents": [{"parts": [{"text": prompt}]}],
                                        "generationConfig": {"temperature": 1.0}}, timeout=75)
            except Exception as e:
                last = f"{m}: {type(e).__name__}"
                print("[llm] gemini", last)
                continue
            if r.ok:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            last = f"{m}: {r.status_code} {r.text[:160]}"
            print("[llm] gemini", last)
    raise RuntimeError(last)


def _groq(prompt):
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no GROQ_API_KEY")
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                            "messages": [{"role": "user", "content": prompt}], "temperature": 1.0},
                      timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def llm_json(prompt):
    for fn in (_gemini, _groq):
        try:
            return _extract_json(fn(prompt))
        except Exception as e:
            print(f"[llm] {fn.__name__} failed: {str(e)[:200]}")
    return None


# ----------------------------- planning --------------------------------------
def build_prompt(persona, genre, hook, context):
    return f"""You are the head of content for a YouTube music channel called "{CHANNEL_NAME}" aimed at a US audience (ages 16-34).
Each video is an ORIGINAL English song performed by a fictional AI singer. Create everything for ONE new video.

Singer: {persona['name']} ({persona['voice']}). Look: {persona['look']}.
Genre: {genre}. Title/thumbnail hook style: {hook}.

{context}

Return ONLY a JSON object with these keys:
"song_title": short, memorable.
"caption": comma-separated music tags for the song generator, include genre, mood, instruments, vocal type ("{persona['voice']}"), tempo, e.g. "indie pop, warm female vocal, acoustic guitar, soft drums, nostalgic, 92 bpm".
"bpm": integer 70-130.
"duration": integer seconds between 150 and 200.
"lyrics": fully ORIGINAL lyrics, 28-36 lines, with section tags on their own lines like [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Chorus], [Bridge], [Final Chorus]. Simple, emotional, singable, a chorus hook that repeats, everyday US-life imagery. No real artist names, no copied lyrics.
"title": max 70 characters. Strong curiosity or emotion, natural American English, add a short tag like "(Lyrics)" only if it fits. No fake claims, no ALL CAPS sentences.
"thumbnail_hook": 2 to 4 words in CAPS that create curiosity or emotion.
"description_hook": 2 gripping sentences that make people want to listen.
"about_song": 2 sentences about the story behind the song.
"cta_question": one fun question that makes viewers comment (about their own life, related to the song).
"tags": array of 15 search tags (mix of broad and specific).
"hashtags": array of 3 hashtags.
"scene_prompts": array of 6 image descriptions of the singer in different scenes that match the song (first one is an emotional close-up of the face, no text, no logos)."""


def fallback_plan(persona, genre, hook):
    lyrics = "\n".join(["[Verse 1]", "Streetlights flicker on the avenue", "I keep on thinking about you",
                        "Every little thing I never said", "Keeps on spinning round my head",
                        "[Chorus]", "Hold me like it's the last night", "Under the city lights",
                        "Say you'll stay till the morning comes", "Hold me like it's the last night",
                        "[Verse 2]", "Coffee cold on the window seat", "Hearts still skipping a beat",
                        "Maybe we were never wrong", "Maybe we just waited too long",
                        "[Chorus]", "Hold me like it's the last night", "Under the city lights",
                        "Say you'll stay till the morning comes", "Hold me like it's the last night"])
    return {"song_title": "Last Night", "caption": f"{genre}, {persona['voice']}, emotional, 95 bpm",
            "bpm": 95, "duration": 160, "lyrics": lyrics,
            "title": "Hold Me Like It's The Last Night (Lyrics)", "thumbnail_hook": "THE LAST NIGHT",
            "description_hook": "Some nights you just need a song that gets it. This one is for you.",
            "about_song": "A late-night song about the words we never said.",
            "cta_question": "What song gets you through late nights? Tell me below!",
            "tags": ["new song", genre, "lyrics", "pop songs 2026", "emotional songs", "late night songs"],
            "hashtags": ["#newmusic", "#lyrics", "#popmusic"],
            "scene_prompts": ["emotional close-up portrait, eyes glistening, city bokeh", "singing on a rooftop at night",
                              "walking down a neon-lit street in the rain", "sitting by a window with coffee",
                              "performing on a small stage with warm lights", "standing on a quiet bridge at dawn"]}


def make_plan(persona, genre, hook, context):
    plan = llm_json(build_prompt(persona, genre, hook, context))
    if not plan or "lyrics" not in plan:
        print("[plan] LLM unavailable, using fallback plan")
        plan = fallback_plan(persona, genre, hook)
    f = fallback_plan(persona, genre, hook)
    for k, v in f.items():
        plan.setdefault(k, v)
    plan["duration"] = max(120, min(210, int(plan["duration"])))
    plan["title"] = re.sub(r"[<>]", "", str(plan["title"]))[:95].strip()
    plan["thumbnail_hook"] = str(plan["thumbnail_hook"]).upper()[:34]
    scenes = list(plan["scene_prompts"])[:6]
    while len(scenes) < 6:
        scenes.append(f["scene_prompts"][len(scenes)])
    plan["scene_prompts"] = scenes
    plan["lyric_lines"] = [ln.strip() for ln in plan["lyrics"].splitlines() if ln.strip() and not ln.strip().startswith("[")]
    tags, total = [], 0
    for t in plan["tags"]:
        t = re.sub(r"[<>,]", "", str(t)).strip()
        if t and total + len(t) + 1 < 450:
            tags.append(t)
            total += len(t) + 1
    plan["tags"] = tags
    return plan


def build_description(plan, persona):
    excerpt = "\n".join(plan["lyric_lines"][:8])
    parts = [plan["description_hook"], "",
             f"💬 {plan['cta_question']}", "👍 Like if this one hit you, and subscribe for a new original song every day.", "",
             "LYRICS (excerpt)", excerpt, "",
             f"About the song: {plan['about_song']}", "",
             f"{persona['name']} is the fictional AI singer of {CHANNEL_NAME}. New songs every day.", "",
             ", ".join(plan["tags"]), " ".join(plan["hashtags"]), "",
             "Music and vocals are AI-generated. All characters are fictional."]
    return "\n".join(parts)[:4900]
