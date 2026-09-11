"""results_all.json (from scan_bgg.py) -> webapp/public/data/bgg-filter.json

Kept separate from the scan so the shipped payload can be re-trimmed without
re-hitting BGG. Only the fields the UI reads survive, and each player-count row
is [best, recommended, not_recommended]; rows with no votes are dropped so the
component can treat "missing" as "nobody voted".
"""
import datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results_all.json")
dst = os.path.join(ROOT, "webapp", "public", "data", "bgg-filter.json")

raw = json.load(open(src, encoding="utf-8"))
games = raw["games"]
out = []
for g in games:
    p = g.get("p") or {}
    out.append({
        "n": g["n"], "id": g["id"], "y": g.get("y"), "rk": g.get("rk"),
        "geek": round(g["geek"], 3), "avg": round(g["avg"], 2),
        "v": g["v"], "w": round(g["w"], 2), "pt": g.get("pt") or 0,
        "p": {k: p[k] for k in ("2", "3", "4") if p.get(k) and sum(p[k])},
    })
out.sort(key=lambda g: -g["geek"])
os.makedirs(os.path.dirname(dst), exist_ok=True)
# Both header fields are READ OFF THE HARVEST, never typed: the UI prints the
# collection date and the ratings floor, and a hand-set pair goes stale silently.
json.dump({"collected": datetime.date.today().isoformat(),
           "min_ratings": raw.get("min_ratings", 100), "games": out},
          open(dst, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"{len(out)} games -> {dst} ({os.path.getsize(dst):,} bytes)")
