"""Free, vidIQ-style keyword research. Never breaks the run: every step is wrapped, and it returns {} if anything fails.

What it does (the same ideas vidIQ uses, from free public sources):
  1. YouTube search-box suggestions for your genre/mood  -> what people really type (earlier in the list = more searched)
  2. Top current videos for those searches (YouTube Data API) -> their titles, tags, views per day, length
  3. Optional: keywords you paste from vidIQ (free extension) into data/vidiq_keywords.txt -> highest priority
The result is handed to the title/description/tags writer, and tags are merged with the verified search phrases.
"""
import collections
import datetime as dt
import json
import re
import time
from pathlib import Path

import requests

DATA = Path("data")
CACHE = DATA / "seo_cache.json"
MANUAL = DATA / "vidiq_keywords.txt"
STOP = set("the a an and or of for to in on with is are my your you i me it this that at from by as be".split())


def log(m):
    print(f"[seo] {m}", flush=True)


def autocomplete(q, timeout=10):
    """YouTube search suggestions (public endpoint, no key)."""
    r = requests.get("https://suggestqueries.google.com/complete/search",
                     params={"client": "firefox", "ds": "yt", "hl": "en", "gl": "us", "q": q}, timeout=timeout)
    r.raise_for_status()
    data = json.loads(r.text)
    return [str(x).strip().lower() for x in data[1]][:10]


def manual_keywords():
    try:
        if MANUAL.exists():
            return [ln.strip().lower() for ln in MANUAL.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.startswith("#")][:30]
    except Exception:
        pass
    return []


def suggestions(seeds):
    """Ranked phrases: a phrase that appears early, or for several seeds, scores higher."""
    score = collections.Counter()
    for seed in seeds:
        for q in (seed, seed + " for", seed + " 1 hour"):
            try:
                for rank, ph in enumerate(autocomplete(q)):
                    score[ph] += 10 - rank
                time.sleep(0.3)
            except Exception as e:
                log(f"suggest '{q}' failed: {str(e)[:80]}")
    return [p for p, _ in score.most_common(25)]


def parse_iso_minutes(d):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 60 + mi + s / 60


def competitors(api, queries, per_query=12):
    """Top English/US videos (long form) for the queries: title, tags, views per day."""
    rows, seen = [], set()
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q in queries:
        try:
            res = api.yt.search().list(part="id", q=q, type="video", maxResults=per_query, videoDuration="long",
                                       regionCode="US", relevanceLanguage="en", publishedAfter=after).execute()
            ids = [i["id"]["videoId"] for i in res.get("items", []) if i["id"]["videoId"] not in seen]
            seen.update(ids)
            if not ids:
                continue
            vs = api.yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids)).execute()
            for v in vs.get("items", []):
                sn, st = v["snippet"], v.get("statistics", {})
                pub = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
                days = max((dt.datetime.now(dt.timezone.utc) - pub).days, 1)
                views = int(st.get("viewCount", 0))
                rows.append({"title": sn["title"], "tags": sn.get("tags", []), "views": views, "vpd": views / days,
                             "minutes": parse_iso_minutes(v["contentDetails"].get("duration"))})
        except Exception as e:
            log(f"competitor search '{q}' failed: {str(e)[:100]}")
    return rows


def analyse(rows):
    if not rows:
        return {}
    rows = sorted(rows, key=lambda r: r["vpd"], reverse=True)
    top = rows[:10]
    tagc = collections.Counter(t.lower() for r in top for t in r["tags"] if 2 < len(t) < 40)
    common = [t for t, c in tagc.most_common(30) if c >= 2][:14]
    words = collections.Counter(w for r in top for w in re.findall(r"[a-z']+", r["title"].lower()) if w not in STOP and len(w) > 2)
    return {"top_titles": [r["title"] for r in top[:6]], "common_tags": common,
            "title_words": [w for w, _ in words.most_common(14)],
            "median_vpd": sorted(r["vpd"] for r in top)[len(top) // 2],
            "typical_minutes": round(sorted(r["minutes"] for r in top)[len(top) // 2])}


def research(api, genre, moods=(), seeds=None):
    """Returns {} on any problem. Cached for the day so quota is only used once."""
    try:
        DATA.mkdir(exist_ok=True)
        key = f"{dt.date.today()}|{genre}"
        if CACHE.exists():
            c = json.loads(CACHE.read_text())
            if c.get("key") == key:
                return c["result"]
        seeds = list(seeds) if seeds else [f"{genre} songs", f"{genre} music", f"{genre} playlist"] + [f"{m} songs" for m in list(moods)[:2]]
        sug = suggestions(seeds)
        res = {"keywords": manual_keywords() + [s for s in sug if s not in manual_keywords()]}
        if api is not None and sug:
            res.update(analyse(competitors(api, res["keywords"][:3])))
        CACHE.write_text(json.dumps({"key": key, "result": res}))
        log(f"{len(res.get('keywords', []))} keywords, {len(res.get('top_titles', []))} competitor titles")
        return res
    except Exception as e:
        log(f"research skipped: {str(e)[:120]}")
        return {}


def prompt_block(res):
    if not res:
        return ""
    out = ["SEARCH RESEARCH (real data; use it, do not copy any title or name an artist/brand):"]
    if res.get("keywords"):
        out.append("People search for (best first): " + "; ".join(res["keywords"][:14]))
    if res.get("top_titles"):
        out.append("Current top videos in this niche: " + " || ".join(res["top_titles"]))
    if res.get("common_tags"):
        out.append("Tags the winners share: " + ", ".join(res["common_tags"]))
    if res.get("typical_minutes"):
        out.append(f"Winners are about {res['typical_minutes']} minutes long.")
    return "\n".join(out)


def merge_tags(primary, song_title, llm_tags, res, limit=460, lyrics=True):
    """Best tags first: primary keyword, song name, researched phrases, then the writer's tags."""
    cands = [primary, song_title] + ([f"{song_title} lyrics"] if lyrics else []) + (res.get("keywords", [])[:8] if res else []) \
        + list(llm_tags or []) + (res.get("common_tags", [])[:8] if res else [])
    tags, seen, total = [], set(), 0
    for t in cands:
        t = re.sub(r"[<>,]", "", str(t or "")).strip()
        if t and t.lower() not in seen and total + len(t) + 1 <= limit:
            seen.add(t.lower())
            tags.append(t)
            total += len(t) + 1
    return tags
