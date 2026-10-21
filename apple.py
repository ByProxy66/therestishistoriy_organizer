"""
Find each episode's Apple Podcasts ID, so the page can open it in the Podcasts app.

  python apple.py              # match the ~200 newest episodes (fast, runs daily)
  python apple.py --backfill   # also search for older ones one by one (slow, run once)

Result is cached in apple_ids.json  ->  {feed guid: apple track id}
"""
import argparse, json, re, sys, time
from datetime import datetime
from pathlib import Path

import requests

from build import parse_feed

ROOT = Path(__file__).parent
CACHE = ROOT / "apple_ids.json"
PODCAST_ID = 1537788786
API = "https://itunes.apple.com"


def norm(title):
    t = title.lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"^\s*\d+\s*[.:]\s*", "", t)          # "715. " / "340: "
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def days_apart(a, b):
    da = datetime.fromisoformat(a.replace("Z", "+00:00")).replace(tzinfo=None)
    db = datetime.fromisoformat(b).replace(tzinfo=None)
    return abs((da - db).days)


def match(ep, results):
    """Pick the Apple episode with the same title (or guid), released within 3 days."""
    for r in results:
        if r.get("collectionId") != PODCAST_ID or "trackId" not in r:
            continue
        if r.get("episodeGuid") == ep["guid"]:
            return r["trackId"]
        if norm(r.get("trackName", "")) == norm(ep["title"]) and days_apart(r["releaseDate"], ep["date"]) <= 3:
            return r["trackId"]
    return None


def get(url, params):
    for attempt in range(4):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json().get("results", [])
        time.sleep(60 * (attempt + 1))                  # Apple rate-limits (403/429); back off
    return None                                         # gave up: try again next run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--max", type=int, default=10_000, help="stop backfill after N searches")
    a = ap.parse_args()

    eps = parse_feed(ROOT / "data" / "feed.xml")
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    recent = get(f"{API}/lookup", {"id": PODCAST_ID, "entity": "podcastEpisode", "limit": 300}) or []
    for ep in eps:
        if ep["guid"] not in cache and (tid := match(ep, recent)):
            cache[ep["guid"]] = tid

    if a.backfill:
        missing = [e for e in eps if e["guid"] not in cache][:a.max]   # null = searched, not found
        print(f"searching for {len(missing)} older episodes (about 4 s each)…", flush=True)
        for i, ep in enumerate(missing, 1):
            term = re.sub(r"^\s*\d+\s*[.:]\s*", "", ep["title"])
            # short titles like "Greatness" drown in other podcasts, so add the show name first
            res = get(f"{API}/search", {"term": term + " The Rest Is History", "entity": "podcastEpisode", "limit": 50})
            tid = match(ep, res or [])
            if not tid and res is not None:
                time.sleep(4)
                res = get(f"{API}/search", {"term": term, "entity": "podcastEpisode", "limit": 50})
                tid = match(ep, res or [])
            if res is not None:
                cache[ep["guid"]] = tid
            if i % 25 == 0:
                CACHE.write_text(json.dumps(cache, indent=0))
                print(f"  {i}/{len(missing)}", flush=True)
            time.sleep(4)

    CACHE.write_text(json.dumps(cache, indent=0))
    found = sum(1 for v in cache.values() if v)
    print(f"Apple Podcasts: {found} of {len(eps)} episodes linked")


if __name__ == "__main__":
    sys.exit(main())
