"""
The Rest Is History – series grouper (prototype)

  python build.py                # fetch feed, group, write out/
  python build.py --no-fetch     # reuse data/feed.xml
  ANTHROPIC_API_KEY=... python build.py --llm   # let Claude name series w/o shared prefix

Pipeline: fetch RSS -> parse -> segment into series (rules) -> name -> overrides -> output
"""
import argparse, json, os, re, sys, html
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

FEED_URL = "https://feeds.megaphone.fm/GLT4787413333"
ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "out"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

MAX_GAP = timedelta(days=45)   # max days between consecutive parts in a series
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}

# ---------------------------------------------------------------- parsing
NUM_RE = re.compile(r"^\s*(\d+)\s*[.:]\s*")
PART_RES = [
    re.compile(r"\s*[\(\[]\s*part\s+(\d+|[ivx]+)\s*[\)\]]", re.I),       # (Part 2)
    re.compile(r"\s*[-–:,]?\s*\bpart\s+(\d+|[ivx]+)\b\s*$", re.I),         # - Part 2 / part 2
    re.compile(r"\s*[-–:,]?\s*\bepisode\s+(\d+)\b\s*$", re.I),             # Episode 2
    re.compile(r"\s*[\(\[]\s*(\d+)\s*/\s*\d+\s*[\)\]]"),                   # (2/4)
]


def to_int(s):
    s = s.lower()
    return int(s) if s.isdigit() else ROMAN.get(s)


def parse_feed(xml_path):
    root = ET.parse(xml_path).getroot()
    eps = []
    for it in root.findall(".//item"):
        raw = (it.findtext("title") or "").strip()
        enc = it.find("enclosure")
        img = it.find(ITUNES + "image")
        t = re.sub(r"\s+", " ", raw)
        m = NUM_RE.match(t)
        num = int(m.group(1)) if m else None
        base = NUM_RE.sub("", t)
        part = None
        for rx in PART_RES:
            pm = rx.search(base)
            if pm:
                part = to_int(pm.group(1))
                base = (base[:pm.start()] + base[pm.end():]).strip(" -–:,")
                break
        prefix = None
        pm = re.match(r"^(.{3,60}?)\s*(?::| - | – )\s*\S", base)
        if pm:
            prefix = pm.group(1).strip()
        eps.append({
            "guid": it.findtext("guid"),
            "title": raw,
            "number": num,
            "part": part,
            "base": base,
            "prefix": prefix,
            "date": parsedate_to_datetime(it.findtext("pubDate")).isoformat(),
            "type": it.findtext(ITUNES + "episodeType") or "full",
            "duration": it.findtext(ITUNES + "duration"),
            "description": re.sub(r"\s+", " ", it.findtext("description") or "").strip(),
            "audio": enc.get("url") if enc is not None else None,
            "image": img.get("href") if img is not None else None,
        })
    eps.sort(key=lambda e: e["date"])
    return eps


# ---------------------------------------------------------------- segmentation
def segment(eps):
    """Walk chronologically. 'Part 1' opens a series; 'Part k' joins the open
    series whose last part is k-1 (within MAX_GAP). Bonus episodes in between
    don't break a series. Afterwards: consecutive unnumbered episodes that share
    a distinctive title prefix are merged too."""
    series, open_s = [], []
    for e in eps:
        d = datetime.fromisoformat(e["date"])
        if e["part"] is None:
            continue
        target = None
        if e["part"] > 1:
            cands = [s for s in open_s
                     if s["last_part"] == e["part"] - 1 and d - s["last_date"] <= MAX_GAP]
            # prefer same prefix
            cands.sort(key=lambda s: (s["prefix"] != e["prefix"], -s["last_date"].timestamp()))
            target = cands[0] if cands else None
        if target is None:
            target = {"guids": [], "prefix": e["prefix"], "last_part": 0, "last_date": d}
            series.append(target)
            open_s.append(target)
        target["guids"].append(e["guid"])
        target["last_part"], target["last_date"] = e["part"], d
        open_s = [s for s in open_s if d - s["last_date"] <= MAX_GAP]

    # unmarked runs with same prefix (e.g. "Napoleon: X", "Napoleon: Y" without Part)
    in_series = {g for s in series for g in s["guids"]}
    noisy = {"RIHC", "Rest Is History Club", "Historical Love Island", "Bonus", "Trailer"}
    run = []
    def flush():
        if len(run) >= 2:
            series.append({"guids": [x["guid"] for x in run], "prefix": run[0]["prefix"],
                           "unmarked": True})
    for e in eps:
        if e["guid"] in in_series or not e["prefix"] or e["prefix"] in noisy or e["type"] != "full":
            if e["type"] == "full":
                flush(); run = []
            continue
        if run and (e["prefix"].lower() == run[-1]["prefix"].lower()
                    and datetime.fromisoformat(e["date"]) - datetime.fromisoformat(run[-1]["date"]) <= MAX_GAP):
            run.append(e)
        else:
            flush(); run = [e]
    flush()

    by = {e["guid"]: e for e in eps}
    out = []
    for s in series:
        s_eps = [by[g] for g in s["guids"]]
        if len(s_eps) < 2:
            continue  # lone 'Part 2' etc.
        out.append({"episodes": s_eps, "unmarked": s.get("unmarked", False)})
    out.sort(key=lambda s: s["episodes"][0]["date"])
    return out


# ---------------------------------------------------------------- naming
def norm(s):
    s = (s or "").lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"\bvs\.?", "vs", s)
    return re.sub(r"\s+", " ", s).strip()


def common_prefix_name(s_eps):
    counts = {}
    for e in s_eps:
        if e["prefix"]:
            counts.setdefault(norm(e["prefix"]), []).append(e["prefix"])
    if counts:
        best = max(counts.values(), key=len)
        # all share it, or a majority incl. the first episode (e.g. Peasants' Revolt 2/4)
        if len(best) == len(s_eps) or (len(best) * 2 >= len(s_eps) and norm(s_eps[0]["prefix"]) == norm(best[0])):
            return best[0]
    bases = {e["base"].lower() for e in s_eps}
    if len(bases) == 1:                       # "Watergate: Part 1/2", "Sparta Part 1/2"
        return s_eps[0]["base"]
    # longest common word prefix of base titles (>= 2 words)
    words = [e["base"].split() for e in s_eps]
    common = []
    for ws in zip(*words):
        if len({w.lower() for w in ws}) == 1:
            common.append(ws[0])
        else:
            break
    if len(common) >= 2:
        return " ".join(common).strip(" -–:,")
    return None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def llm_names(unnamed):
    """Ask Claude for a short series name based on the episode titles + descriptions."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not unnamed:
        return {}
    payload = [{"id": sid, "episodes": [{"title": e["title"], "description": e["description"][:300]}
                                         for e in eps]} for sid, eps in unnamed]
    prompt = ("Each item below is a multi-part series from the history podcast 'The Rest Is History'. "
              "Give each a short, natural series name (2-6 words, English, Title Case), e.g. "
              "'The American Founding Fathers'. Reply with JSON only: {\"<id>\": \"<name>\", ...}\n\n"
              + json.dumps(payload, ensure_ascii=False))
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                      json={"model": os.environ.get("TRIH_MODEL", "claude-haiku-4-5"),
                            "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]},
                      timeout=120)
    r.raise_for_status()
    text = r.json()["content"][0]["text"]
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def build(series, overrides, use_llm):
    result, unnamed = [], []
    for s in series:
        eps = s["episodes"]
        first = eps[0]
        sid = f"{first['number'] or 'x'}-{slug(first['base'])}"
        name = common_prefix_name(eps)
        rec = {"id": sid, "name": name, "name_source": "title" if name else None,
               "unmarked": s["unmarked"], "start": first["date"][:10], "end": eps[-1]["date"][:10],
               "episodes": [{k: e[k] for k in ("guid", "number", "part", "title", "date",
                                               "duration", "description", "audio")} for e in eps]}
        if not name:
            unnamed.append((sid, eps))
        result.append(rec)

    names = llm_names(unnamed) if use_llm else {}
    on = overrides.get("names", {})
    for rec in result:
        if rec["id"] in on:
            rec["name"], rec["name_source"] = on[rec["id"]], "override"
        elif rec["id"] in names:
            rec["name"], rec["name_source"] = names[rec["id"]], "llm"
        elif not rec["name"]:
            rec["name"], rec["name_source"] = rec["episodes"][0]["title"], "fallback"
    drop = set(overrides.get("drop", []))
    result = [r for r in result if r["id"] not in drop]
    # "sagas": series with the same name released in several runs (e.g. The French Revolution I-III)
    groups = {}
    for r in result:
        groups.setdefault(norm(r["name"]), []).append(r)
    for g in groups.values():
        for i, r in enumerate(g):
            r["saga"] = {"name": g[0]["name"], "index": i + 1, "of": len(g)} if len(g) > 1 else None
    return result


# ---------------------------------------------------------------- output
def write_series_rss(rec, path):
    items = "".join(
        f"<item><title>{html.escape(e['title'])}</title><guid isPermaLink=\"false\">{e['guid']}</guid>"
        f"<pubDate>{datetime.fromisoformat(e['date']).strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
        f"<description>{html.escape(e['description'])}</description>"
        f"<enclosure url=\"{html.escape(e['audio'] or '')}\" type=\"audio/mpeg\"/></item>"
        for e in reversed(rec["episodes"]))
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{html.escape(rec['name'])} – The Rest Is History</title>"
        "<link>https://therestishistory.com</link>"
        f"<description>Unofficial series feed. Audio served from the original feed.</description>"
        f"{items}</channel></rss>", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    DATA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True); (OUT / "feeds").mkdir(exist_ok=True)
    feed = DATA / "feed.xml"
    if not a.no_fetch:
        r = requests.get(FEED_URL, timeout=60); r.raise_for_status()
        feed.write_bytes(r.content)
    eps = parse_feed(feed)
    ov_path = ROOT / "overrides.json"
    overrides = json.loads(ov_path.read_text()) if ov_path.exists() else {}
    series = build(segment(eps), overrides, a.llm)

    in_series = {e["guid"] for s in series for e in s["episodes"]}
    standalone = [{k: e[k] for k in ("guid", "number", "title", "date", "type", "duration", "description", "audio")}
                  for e in eps if e["guid"] not in in_series]
    (OUT / "series.json").write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="seconds"), "episode_count": len(eps),
         "series": series, "standalone": standalone}, ensure_ascii=False, indent=1), encoding="utf-8")
    for rec in series:
        write_series_rss(rec, OUT / "feeds" / f"{rec['id']}.xml")

    src = {}
    for s in series:
        src[s["name_source"]] = src.get(s["name_source"], 0) + 1
    print(f"{len(eps)} episodes, {len(series)} series covering {len(in_series)} episodes, "
          f"{len(standalone)} standalone. Name sources: {src}")


if __name__ == "__main__":
    main()
