"""results_all.json (from scan_steam.py) -> webapp/public/data/steam-filter.json

Kept separate from the scan so the shipped payload can be re-trimmed without
re-hitting Steam. Each game is {n, id, y, p, t[, c, sw]}: name, app id, release
year (or null), positive English reviews, total English reviews, category ids
(see tools/categories.json) and 1 when the game is on Nintendo Switch. The percentages and the
two derived ratings are computed in the browser, never stored.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results_all.json")
dst = os.path.join(ROOT, "webapp", "public", "data", "steam-filter.json")

raw = json.load(open(src, encoding="utf-8"))
# `c` (category ids) and `sw` (on Switch) are added by enrich.py; an empty `c` and a
# missing `sw` are left out of the row to keep the payload small.
def row(g):
    r = {"n": g["n"], "id": g["id"], "y": g.get("y"), "p": g["p"], "t": g["t"]}
    if g.get("c"):
        r["c"] = g["c"]
    if g.get("sw"):
        r["sw"] = 1
    return r


out = [row(g) for g in raw["games"] if g.get("n") and g["t"] > 0]
out.sort(key=lambda g: (-g["t"], g["id"]))
os.makedirs(os.path.dirname(dst), exist_ok=True)
# Header fields are READ OFF THE HARVEST, never typed: the page prints the
# collection date and the floors, and a hand-set copy goes stale silently.
json.dump({"collected": raw["collected"], "enriched": raw.get("enriched"),
           "min_reviews": raw["min_reviews"], "min_positive": raw["min_positive"],
           "categories": raw.get("categories", []), "games": out},
          open(dst, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"{len(out)} games -> {dst} ({os.path.getsize(dst):,} bytes)")
