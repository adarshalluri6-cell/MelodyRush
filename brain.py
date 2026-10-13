"""Strategy, learning from past videos, and content planning (LLM)."""
import datetime as dt
import json
import math
import os
import random
import re
import time
from pathlib import Path

import requests

DATA = Path(os.getenv("DATA_DIR", "data"))
HISTORY_FILE = DATA / "history.json"
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Your Channel Name")

# Fictional singers. Edit freely. Check that the names are not real artists before launching.
PERSONAS = [
    {"id": "mira", "name": "Mira Vale", "gender": "female", "voice": "warm airy female vocal", "seed": 1101,
     "look": "beautiful young American woman in her mid 20s, long wavy honey-blonde hair, blue-green eyes, natural freckles, warm smile, vintage denim jacket",
     "genres": ["indie pop", "acoustic pop", "dream pop"]},
    {"id": "kai", "name": "Kai Monroe", "gender": "male", "voice": "smooth soulful male tenor vocal", "seed": 2202,
     "look": "handsome young African American man in his late 20s, fresh fade haircut, neat short beard, warm brown eyes, cream knit sweater, gold chain",
     "genres": ["r&b", "soul pop", "chill pop"]},
    {"id": "luna", "name": "Luna Reyes", "gender": "female", "voice": "powerful emotional female pop vocal", "seed": 3303,
     "look": "gorgeous young Latina American woman in her mid 20s, long dark wavy hair, glossy lips, gold hoop earrings, black leather jacket",
     "genres": ["synth pop", "dance pop", "electropop"]},
    {"id": "jax", "name": "Jax Calloway", "gender": "male", "voice": "raspy heartfelt male vocal", "seed": 4404,
     "look": "rugged handsome young American man in his late 20s, dark blond hair, light stubble, blue eyes, worn brown leather jacket",
     "genres": ["country pop", "folk pop", "pop rock"]},
    {"id": "nova", "name": "Nova Hart", "gender": "female", "voice": "bright energetic female vocal", "seed": 5505,
     "look": "stylish young American woman in her early 20s, platinum blonde shaggy hair, bold eyeliner, glitter makeup, star earrings",
     "genres": ["alt pop", "bedroom pop", "pop punk"]},
]
LEN_BUCKETS = {"10-25 min": (10, 25), "30-45 min": (30, 45), "50-90 min": (50, 90)}
SHORT_HOOKS = ["hey guys listen", "wait for the chorus", "this hits different", "pov story", "question"]
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
    short_ids = [s["id"] for v in vids[-50:] for s in v.get("shorts", [])]
    all_ids = (ids + short_ids)[:200]
    stats = api.fetch_stats(all_ids)
    first = min(v["date"] for v in vids)[:10]
    extra = api.fetch_analytics(all_ids, first)
    for v in vids:
        m = v.setdefault("metrics", {})
        m.update(stats.get(v["id"], {}))
        m.update(extra.get(v["id"], {}))
        if age_days(v) >= 2:
            v["score"] = video_score(m, age_days(v))
        sc = []
        for s in v.get("shorts", []):
            sm = s.setdefault("metrics", {})
            sm.update(stats.get(s["id"], {}))
            sm.update(extra.get(s["id"], {}))
            if age_days(v) >= 2:
                sc.append(video_score(sm, age_days(v)))
        if sc:
            v["short_score"] = round(sum(sc) / len(sc), 4)
    print(f"[learn] updated metrics for {len(ids)} videos and {len(short_ids)} shorts")


# ----------------------------- decisions -------------------------------------
def pick(hist, key, options, eps=0.3, score_key="score"):
    """Epsilon-greedy: mostly repeat what works, sometimes try something new."""
    scored = [v for v in hist["videos"] if v.get(score_key) is not None]
    by = {o: [v[score_key] for v in scored if v.get(key) == o] for o in options}
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
    short_hook, m4 = pick(hist, "short_hook", SHORT_HOOKS, score_key="short_score")
    print(f"[strategy] persona={persona['name']} ({m1}), genre={genre} ({m2}), hook={hook} ({m3}), shorts hook={short_hook} ({m4})")
    return persona, genre, hook, short_hook


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
    models = [os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), "gemini-flash-latest"]
    last = ""
    for attempt in range(4):
        retry_later = False
        for m in dict.fromkeys(models):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                  headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                  json={"contents": [{"parts": [{"text": prompt}]}],
                                        "generationConfig": {"temperature": 1.0}}, timeout=150)
            except Exception as e:
                last = f"{m}: {type(e).__name__}"
                retry_later = True
                continue
            if r.ok:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            last = f"{m}: {r.status_code} {r.text[:120]}"
            if r.status_code in (429, 500, 502, 503, 504):
                retry_later = True
        print("[llm] gemini", last)
        if not retry_later:
            break
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(last)


_GROQ_MODEL = {}


def _groq_model(key):
    if _GROQ_MODEL:
        return _GROQ_MODEL["m"]
    forced = os.getenv("GROQ_MODEL", "").strip()
    if forced:
        _GROQ_MODEL["m"] = forced
        return forced
    pick_ = "llama-3.3-70b-versatile"
    try:
        r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
        ids = [m["id"] for m in r.json().get("data", [])
               if not any(x in m["id"].lower() for x in ("whisper", "guard", "tts", "playai", "prompt-guard", "distil"))]
        for pref in ("70b", "120b", "gpt-oss", "llama", "qwen", "kimi"):
            hit = [i for i in ids if pref in i.lower()]
            if hit:
                pick_ = hit[0]
                break
        else:
            pick_ = ids[0] if ids else pick_
    except Exception:
        pass
    print("[llm] groq model:", pick_)
    _GROQ_MODEL["m"] = pick_
    return pick_


def _groq(prompt):
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no GROQ_API_KEY")
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": _groq_model(key), "messages": [{"role": "user", "content": prompt}],
                            "temperature": 1.0}, timeout=120)
    if r.status_code == 404:
        _GROQ_MODEL.clear()
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
def build_prompt(persona, genre, hook, context, short_hook="hey guys listen"):
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
"image_prompt": ONE vivid description of the singer for the video cover picture: emotion on the face, outfit details, setting, time of day, lighting and colors that match the song mood. The singer must be on the right side of the frame with empty space on the left. No text, no logos, no other people.
"shorts": array of EXACTLY 2 objects for two vertical YouTube Shorts that promote this song. Shorts hook style: {short_hook}. Each object has: "hook_text" (3 to 6 words in CAPS shown on screen in the first 3 seconds, creates curiosity or emotion), "spoken_hook" (ONE casual friendly sentence a narrator says in about 2 seconds, in the spirit of "Hey guys, listen to this song" but with fresh wording that fits the hook style), "title" (max 70 characters, English, curiosity or emotion, no hashtags, no fake claims), "description_hook" (one gripping sentence), "hashtags" (array of 5 hashtags, include #shorts)."""


def fallback_shorts():
    return [{"hook_text": "LISTEN TO THIS", "spoken_hook": "Hey guys, listen to this song.", "title": "This song hits different at night",
             "description_hook": "Press play and tell me this chorus is not stuck in your head.",
             "hashtags": ["#shorts", "#newmusic", "#popmusic", "#lyrics", "#originalsong"]},
            {"hook_text": "WAIT FOR THE CHORUS", "spoken_hook": "Hey guys, wait for the chorus on this one.", "title": "Wait for the chorus",
             "description_hook": "The chorus is the part you will replay.",
             "hashtags": ["#shorts", "#newsong", "#music", "#lyrics", "#trending"]}]


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
            "image_prompt": "emotional close-up portrait, eyes glistening, singing into a vintage microphone, neon city bokeh at night, teal and magenta lighting",
            "shorts": fallback_shorts()}


def make_plan(persona, genre, hook, context, short_hook="hey guys listen"):
    plan = llm_json(build_prompt(persona, genre, hook, context, short_hook))
    if not plan or "lyrics" not in plan:
        print("[plan] LLM unavailable, using fallback plan")
        plan = fallback_plan(persona, genre, hook)
    f = fallback_plan(persona, genre, hook)
    for k, v in f.items():
        plan.setdefault(k, v)
    plan["duration"] = max(120, min(210, int(plan["duration"])))
    plan["title"] = re.sub(r"[<>]", "", str(plan["title"]))[:95].strip()
    plan["thumbnail_hook"] = str(plan["thumbnail_hook"]).upper()[:34]
    plan["image_prompt"] = str(plan["image_prompt"])[:600]
    fb = fallback_shorts()
    good = []
    for i, sp in enumerate(plan.get("shorts") or []):
        if not isinstance(sp, dict):
            continue
        d = fb[i % 2]
        tags5 = [str(h).strip() for h in (sp.get("hashtags") or []) if str(h).strip()][:5]
        tags5 = [h if h.startswith("#") else "#" + h.replace(" ", "") for h in tags5]
        if "#shorts" not in [h.lower() for h in tags5]:
            tags5 = ["#shorts"] + tags5[:4]
        good.append({"hook_text": re.sub(r"[<>]", "", str(sp.get("hook_text") or d["hook_text"])).upper()[:38],
                     "spoken_hook": re.sub(r"[<>]", "", str(sp.get("spoken_hook") or d["spoken_hook"]))[:110],
                     "title": re.sub(r"[<>#]", "", str(sp.get("title") or d["title"]))[:78].strip(),
                     "description_hook": re.sub(r"[<>]", "", str(sp.get("description_hook") or d["description_hook"]))[:220],
                     "hashtags": tags5 or d["hashtags"]})
    while len(good) < 2:
        good.append(fb[len(good)])
    plan["shorts"] = good[:2]
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


def image_prompt_for(persona, plan):
    return (f"professional photo of {persona['look']}, {plan['image_prompt']}, singing into a microphone, "
            "subject positioned on the right third of the frame, empty dark space on the left, "
            "cinematic lighting, 85mm lens, shallow depth of field, sharp focus on the eyes, "
            "ultra detailed skin and hair, vibrant color grading, no text, no watermark")


def portrait_prompt_for(persona, plan):
    return (f"professional vertical photo of {persona['look']}, {plan['image_prompt']}, singing into a microphone, "
            "upper body, subject centered with some space above the head, tall 9:16 composition, "
            "cinematic lighting, 85mm lens, shallow depth of field, sharp focus on the eyes, "
            "ultra detailed skin and hair, vibrant color grading, no text, no watermark")


# ============================== MIX (long video) PLANNING ==============================
def choose_length(hist):
    bucket, mode = pick(hist, "len_bucket", list(LEN_BUCKETS))
    lo, hi = LEN_BUCKETS[bucket]
    minutes = random.randint(lo, hi)
    forced = os.getenv("MIX_MINUTES", "").strip()
    if forced.isdigit():
        minutes = int(forced)
    print(f"[strategy] length bucket={bucket} ({mode}) -> {minutes} minutes")
    return bucket, minutes


def mix_n_songs(minutes):
    return max(3, round(minutes / 2.9))


def duration_label(minutes):
    if minutes < 55:
        return f"{minutes} Minutes"
    if minutes < 70:
        return "1 Hour"
    h = round(minutes / 60 * 2) / 2
    return f"{h:g} Hours"


def badge_label(minutes):
    return duration_label(minutes).upper().replace("MINUTES", "MIN")


def build_mix_prompt(persona, genre, hook, context, minutes):
    return f"""You run a YouTube music channel called "{CHANNEL_NAME}" for a US audience (ages 16-34). Today's upload is a long MIX of {minutes} minutes: original English songs by one fictional singer, {persona['name']} ({persona['voice']}, {persona['gender']}). Main genre: {genre}. Title hook style: {hook}.

Successful channels in this niche use SEARCHABLE titles like "Deep House Mix 2026 - Vocal House, Nu Disco & Late Night Deep House" and one consistent look. Do the same for our genre.

{context}

Return ONLY a JSON object with these keys:
"mix_name": 2 to 4 words naming the vibe, e.g. "Late Night Pop" or "Chill Indie Pop".
"title": max 95 characters. Pattern: "<Mix Name> Mix 2026 | <3 related searchable genres or moods> | {duration_label(minutes)} of Songs With Lyrics". Natural American English, no emojis, no fake claims.
"thumbnail_line": 1 to 3 words in CAPS for the first thumbnail line (usually the mix name's strongest words, e.g. "CHILL POP").
"thumbnail_sub": three short mood or genre tags in CAPS separated by commas, e.g. "VOCAL POP, LATE NIGHT, NEW SONGS".
"description_intro": 3 sentences, SEO-rich, natural, welcoming, naming the vibe, when to listen (study, drive, relax, late night), and that every track has lyrics on screen.
"first_comment": a friendly comment from the channel that asks one fun question about the listener's life AND asks which track number they like best, with a short like-and-subscribe request. Max 300 characters.
"cta_question": one short question shown on screen (max 70 characters).
"tags": array of 20 search tags (mix broad and specific, include "{genre}", "2026", "songs with lyrics", "playlist").
"hashtags": array of 3 hashtags.
"image_prompt": ONE vivid description (max 55 words) of the hero picture for the thumbnail and the video: {persona['name']} as {persona['look']}, in a cinematic scene that matches the mood, expressive face looking at the camera, subject on the RIGHT third of the frame with empty space on the LEFT. No text, no logos, no other people."""


def build_songs_prompt(persona, genre, mix_name, start, k, used):
    return f"""You write original songs for the fictional singer {persona['name']} ({persona['voice']}), genre {genre}, mix "{mix_name}".
Write {k} DIFFERENT songs (track numbers {start + 1} to {start + k}). Titles already used, do not repeat: {', '.join(used[-30:]) or 'none'}.
Return ONLY JSON: {{"songs": [ ... ]}} where each song has:
"song_title": short and memorable (2 to 5 words).
"caption": comma-separated music tags for the generator, include genre, mood, instruments, "{persona['voice']}", tempo, e.g. "indie pop, warm female vocal, acoustic guitar, soft drums, nostalgic, 92 bpm". Vary mood and tempo between songs but stay in the genre family.
"bpm": integer 70-130.
"duration": integer seconds between 150 and 190.
"lyrics": fully ORIGINAL lyrics, 22 to 28 lines, with section tags on their own lines ([Verse 1], [Chorus], [Verse 2], [Chorus], [Bridge], [Final Chorus]). Simple, emotional, singable, a repeating chorus hook, everyday US-life imagery. No real artist names, no copied lyrics."""


def fallback_songs(persona, genre, n, start=0):
    base = fallback_plan(persona, genre, "x")
    names = ["Last Night", "City Lights", "Almost Home", "Slow Burn", "Summer Static", "Paper Hearts", "Stay Awhile",
             "Midnight Drive", "Golden Hour", "Out Loud", "Blue Hour", "Hold On"]
    out = []
    for i in range(n):
        out.append({"song_title": names[(start + i) % len(names)] + ("" if start + i < len(names) else f" {start + i}"),
                    "caption": base["caption"], "bpm": base["bpm"], "duration": 160, "lyrics": base["lyrics"]})
    return out


def _clean_song(s, persona, genre):
    try:
        lyrics = str(s["lyrics"])
        if len([x for x in lyrics.splitlines() if x.strip()]) < 10:
            return None
        return {"song_title": re.sub(r"[<>]", "", str(s.get("song_title") or "Untitled"))[:48].strip(),
                "caption": str(s.get("caption") or f"{genre}, {persona['voice']}")[:300],
                "bpm": int(s.get("bpm") or 95),
                "duration": max(130, min(200, int(s.get("duration") or 165))),
                "lyrics": lyrics}
    except Exception:
        return None


def make_mix_plan(persona, genre, hook, context, minutes):
    n = mix_n_songs(minutes)
    top = llm_json(build_mix_prompt(persona, genre, hook, context, minutes)) or {}
    fb = fallback_plan(persona, genre, hook)
    mix_name = str(top.get("mix_name") or genre.title())[:40]
    plan = {
        "mix_name": mix_name, "minutes": minutes, "n_songs": n,
        "title": re.sub(r"[<>]", "", str(top.get("title") or f"{mix_name} Mix 2026 | {genre.title()} Songs With Lyrics | {duration_label(minutes)}"))[:99].strip(),
        "thumbnail_line": str(top.get("thumbnail_line") or mix_name).upper()[:26],
        "thumbnail_sub": str(top.get("thumbnail_sub") or f"{genre}, new songs, with lyrics").upper()[:48],
        "description_intro": str(top.get("description_intro") or f"{mix_name} songs for studying, driving, relaxing and late nights. Every track has lyrics on screen. Press play and stay awhile.")[:900],
        "first_comment": str(top.get("first_comment") or "Which track number is your favorite? Tell me below, and what are you doing while you listen? Like and subscribe if this vibe is for you!")[:480],
        "cta_question": str(top.get("cta_question") or "Which track is your favorite? Comment its number!")[:80],
        "hashtags": [h if str(h).startswith("#") else "#" + str(h).replace(" ", "") for h in (top.get("hashtags") or ["#newmusic", "#songswithlyrics", "#playlist"])][:3],
        "image_prompt": str(top.get("image_prompt") or fb["image_prompt"])[:600],
    }
    tags, total = [], 0
    for t in (top.get("tags") or fb["tags"]):
        t = re.sub(r"[<>,]", "", str(t)).strip()
        if t and total + len(t) + 1 < 450:
            tags.append(t)
            total += len(t) + 1
    plan["tags"] = tags
    songs, used, fails = [], [], 0
    while len(songs) < n and fails < 3:
        k = min(5, n - len(songs))
        got = (llm_json(build_songs_prompt(persona, genre, mix_name, len(songs), k, used)) or {}).get("songs") or []
        good = [c for c in (_clean_song(s, persona, genre) for s in got) if c and c["song_title"] not in used]
        if not good:
            fails += 1
            print(f"[plan] song batch failed ({fails}/3), waiting before trying again")
            time.sleep(30)
            continue
        fails = 0
        for g in good[:k]:
            songs.append(g)
            used.append(g["song_title"])
    if len(songs) < 3:
        print("[plan] too few songs from the AI, adding built-in songs")
        songs += fallback_songs(persona, genre, 3 - len(songs), len(songs))
    n = len(songs)
    plan["n_songs"] = n
    for i, s in enumerate(songs):
        s["lyric_lines"] = [ln.strip() for ln in s["lyrics"].splitlines() if ln.strip() and not ln.strip().startswith("[")]
    plan["songs"] = songs
    print(f"[plan] mix '{plan['title']}' with {len(songs)} songs")
    return plan


def build_mix_description(plan, persona, chapters):
    parts = [plan["description_intro"], "",
             f"\U0001F4AC {plan['cta_question']}", "\U0001F44D Like, subscribe, and turn on the bell for a new mix every day.", "",
             "TRACKLIST", *chapters, "",
             f"Sung by {persona['name']}, the fictional AI singer of {CHANNEL_NAME}.", "",
             ", ".join(plan["tags"]), " ".join(plan["hashtags"]), "",
             "Music and vocals are AI-generated. All characters are fictional."]
    return "\n".join(parts)[:4990]


def llm_text(prompt):
    """Plain-text answer from the free text AIs (Gemini first, Groq as backup). Returns None if both fail."""
    for fn in (_gemini, _groq):
        try:
            return fn(prompt).strip()
        except Exception as e:
            print(f"[llm] {fn.__name__} failed: {str(e)[:160]}")
    return None


# ============================== ONE SONG, PLAYED FOR ABOUT AN HOUR ==============================
def build_loop_prompt(persona, genre, hook, context):
    return f"""You run a YouTube music channel called "{CHANNEL_NAME}" for a US audience (ages 16-34). Create ONE new original English song for the fictional singer {persona['name']} ({persona['voice']}, {persona['gender']}). Genre: {genre}. Title hook style: {hook}.
The video plays this song for about an hour, made for people who want to leave it on while they study, drive, work or fall asleep, so the song should be catchy, warm and easy to listen to again and again.

{context}

Return ONLY a JSON object with these keys:
"song_title": 2 to 5 words, memorable, easy to search.
"caption": comma-separated music tags for the song generator, include genre, mood, instruments, "{persona['voice']}", tempo, e.g. "indie pop, warm female vocal, acoustic guitar, soft drums, nostalgic, 92 bpm".
"bpm": integer 70-125.
"duration": integer seconds between 160 and 190.
"lyrics": fully ORIGINAL lyrics, 26 to 32 lines, with section tags on their own lines ([Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Chorus], [Bridge], [Final Chorus]). Simple, emotional, singable, a repeating chorus hook, everyday US-life imagery. No real artist names, no copied lyrics.
"title": max 95 characters. Pattern: "<Song Title> ([DURATION]) | <two or three searchable moods or genres> Song 2026 | Lyrics". Keep the exact text [DURATION] in it. Natural American English, no emojis, no fake claims.
"thumbnail_line": the song title in CAPS, max 3 words (shorten if needed).
"thumbnail_sub": three short mood or genre tags in CAPS separated by commas.
"description_intro": 3 sentences, SEO-rich and warm: name the song and the singer, the feeling of the song, and when it fits (late night, study, drive, relax). Truthful, no claims about other songs.
"first_comment": a friendly comment from the channel that asks one fun question about the listener's life or their favorite lyric, plus a short like-and-subscribe request. Max 300 characters.
"cta_question": one short question shown on screen (max 70 characters), e.g. about their favorite line.
"tags": array of 20 search tags (mix broad and specific; include the song title, "{genre}", "lyrics", "2026").
"hashtags": array of 3 hashtags.
"image_prompt": ONE vivid description (max 55 words) of the hero picture: {persona['name']} as {persona['look']}, in a cinematic scene that matches the song, expressive face looking at the camera, subject on the RIGHT third of the frame with empty space on the LEFT. No text, no logos, no other people."""


def make_loop_plan(persona, genre, hook, context):
    top = None
    for attempt in range(3):
        top = llm_json(build_loop_prompt(persona, genre, hook, context))
        song = _clean_song(top or {}, persona, genre) if top else None
        if song:
            break
        print(f"[plan] song idea failed ({attempt + 1}/3)")
        time.sleep(25)
    else:
        song = None
    fb = fallback_plan(persona, genre, hook)
    top = top or {}
    if not song:
        print("[plan] using the built-in song")
        song = {"song_title": "Last Night", "caption": fb["caption"], "bpm": fb["bpm"], "duration": 170, "lyrics": fb["lyrics"]}
        top = {}
    song["lyric_lines"] = [ln.strip() for ln in song["lyrics"].splitlines() if ln.strip() and not ln.strip().startswith("[")]
    name = song["song_title"]
    tags, total = [], 0
    for t in (top.get("tags") or [name, genre, "lyrics", "2026", "new song"]):
        t = re.sub(r"[<>,]", "", str(t)).strip()
        if t and total + len(t) + 1 < 450:
            tags.append(t)
            total += len(t) + 1
    title = re.sub(r"[<>]", "", str(top.get("title") or f"{name} ([DURATION]) | {genre.title()} Song 2026 | Lyrics")).strip()
    if "[DURATION]" not in title:
        title = f"{title} ([DURATION])" if len(title) < 80 else title
    plan = {
        "title": title[:105], "song": song, "songs": [song], "song_title": name,
        "thumbnail_line": str(top.get("thumbnail_line") or name).upper()[:26],
        "thumbnail_sub": str(top.get("thumbnail_sub") or f"{genre}, lyrics, new song").upper()[:48],
        "description_intro": str(top.get("description_intro") or f"{name} by {persona['name']}. A {genre} song for late nights, study sessions and long drives. Press play and stay awhile.")[:900],
        "first_comment": str(top.get("first_comment") or "What's your favorite line in this song? Tell me below! Like and subscribe if it hit you.")[:480],
        "cta_question": str(top.get("cta_question") or "What's your favorite line?")[:80],
        "hashtags": [h if str(h).startswith("#") else "#" + str(h).replace(" ", "") for h in (top.get("hashtags") or ["#newmusic", "#lyrics", "#song"])][:3],
        "tags": tags, "image_prompt": str(top.get("image_prompt") or fb["image_prompt"])[:600],
    }
    print(f"[plan] song '{name}', title '{plan['title']}'")
    return plan


def build_loop_description(plan, persona):
    parts = [plan["description_intro"], "",
             f"\U0001F4AC {plan['cta_question']}", "\U0001F44D Like, subscribe, and turn on the bell for new songs every day.", "",
             f"LYRICS - {plan['song_title']}", plan["song"]["lyrics"], "",
             f"Sung by {persona['name']}, the fictional AI singer of {CHANNEL_NAME}.", "",
             ", ".join(plan["tags"]), " ".join(plan["hashtags"]), "",
             "Music and vocals are AI-generated. All characters are fictional."]
    return "\n".join(parts)[:4990]
