"""Render out/series.json into a single browsable page: out/index.html"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
d = json.loads((ROOT / "out" / "series.json").read_text())


def short(s, n=240):
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def ep(e):
    return {"n": e.get("number"), "p": e.get("part"), "t": e["title"], "d": e["date"][:10],
            "x": short(e["description"]), "a": e.get("audio"),
            "m": round(int(e["duration"]) / 60) if (e.get("duration") or "").isdigit() else None}


data = {
    "generated": d["generated"][:10],
    "count": d["episode_count"],
    "series": [{"id": s["id"], "name": s["name"], "src": s["name_source"], "saga": s.get("saga"),
                "start": s["start"], "end": s["end"], "eps": [ep(e) for e in s["episodes"]]}
               for s in d["series"]],
    "solo": [ep(e) | {"ty": e["type"]} for e in d["standalone"]],
}
tpl = (ROOT / "page.html").read_text()
(ROOT / "out" / "index.html").write_text(
    tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":"))),
    encoding="utf-8")
print("wrote out/index.html", round((ROOT / "out" / "index.html").stat().st_size / 1024), "KB")
