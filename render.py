"""Render out/series.json into a single browsable page: out/index.html"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
d = json.loads((ROOT / "out" / "series.json").read_text(encoding="utf-8"))


def short(s, n=240):
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


# Apple Podcasts IDs (made by apple.py). Missing file = no Apple links, page still works.
apple_path = ROOT / "apple_ids.json"
APPLE = json.loads(apple_path.read_text()) if apple_path.exists() else {}


def ep(e):
    return {"n": e.get("number"), "p": e.get("part"), "t": e["title"], "d": e["date"][:10],
            "x": short(e["description"]), "a": e.get("audio"), "ap": APPLE.get(e["guid"]),
            "m": round(int(e["duration"]) / 60) if (e.get("duration") or "").isdigit() else None}


data = {
    "generated": d["generated"][:10],
    "count": d["episode_count"],
    "series": [{"id": s["id"], "name": s["name"], "src": s["name_source"], "saga": s.get("saga"),
                "start": s["start"], "end": s["end"], "eps": [ep(e) for e in s["episodes"]]}
               for s in d["series"]],
    "solo": [ep(e) | {"ty": e["type"]} for e in d["standalone"]],
}

# Head tags so the page works on phones and as a home-screen app
HEAD = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="TRIH Serier">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#eef0ec" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#131816" media="(prefers-color-scheme: dark)">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="icons/favicon-32.png">
<link rel="manifest" href="manifest.webmanifest">
"""

# Icons + manifest (for Android / Chrome "Add to home screen")
(ROOT / "out" / "icons").mkdir(parents=True, exist_ok=True)
for name in ("apple-touch-icon.png", "favicon-32.png", "icon-192.png", "icon-512.png"):
    src = ROOT / "icons" / name
    if src.exists():
        (ROOT / "out" / "icons" / name).write_bytes(src.read_bytes())
(ROOT / "out" / "manifest.webmanifest").write_text(json.dumps({
    "name": "The Rest Is History – Serier",
    "short_name": "TRIH Serier",
    "start_url": ".",
    "display": "standalone",
    "background_color": "#131816",
    "theme_color": "#131816",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}, ensure_ascii=False, indent=1), encoding="utf-8")

tpl = (ROOT / "page.html").read_text(encoding="utf-8")
tpl = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
head, body = tpl.split("</style>", 1)
page = f'<!doctype html>\n<html lang="da">\n<head>\n{HEAD}{head}</style>\n</head>\n<body>{body}</body>\n</html>\n'
(ROOT / "out" / "index.html").write_text(page, encoding="utf-8")
print("wrote out/index.html", round((ROOT / "out" / "index.html").stat().st_size / 1024), "KB")
