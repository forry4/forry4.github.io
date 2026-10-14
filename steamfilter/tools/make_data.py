"""results_all.json (from scan_steam.py) -> webapp/public/data/steam-filter.json

Kept separate from the scan so the shipped payload can be re-trimmed without
re-hitting Steam. Each game is {n, id, y, p, t}: name, app id, release year (or
null), positive English reviews, total English reviews. The percentages and the
two derived ratings are computed in the browser, never stored.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results_all.json")
dst = os.path.join(ROOT, "webapp", "public", "data", "steam-filter.json")

raw = json.load(open(src, encoding="utf-8"))
out = [{"n": g["n"], "id": g["id"], "y": g.get("y"), "p": g["p"], "t": g["t"]}
       for g in raw["games"] if g.get("n") and g["t"] > 0]
out.sort(key=lambda g: (-g["t"], g["id"]))
os.makedirs(os.path.dirname(dst), exist_ok=True)
# Header fields are READ OFF THE HARVEST, never typed: the page prints the
# collection date and the floors, and a hand-set copy goes stale silently.
json.dump({"collected": raw["collected"], "min_reviews": raw["min_reviews"],
           "min_positive": raw["min_positive"], "games": out},
          open(dst, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"{len(out)} games -> {dst} ({os.path.getsize(dst):,} bytes)")
