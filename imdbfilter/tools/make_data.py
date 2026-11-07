"""results_all.json (from harvest.py) -> webapp/public/data/imdb-filter.json

Offline and re-runnable: the harvest is the only step that asks IMDb.

1. LISTED: every film, TV film, series and mini-series with FLOOR+ votes.
2. NAMES are interned — a director or an actor is stored once in the header's
   `names` and referenced by index — because the same few thousand people appear
   on most of the rows, and spelling each out was most of the payload.
3. THE WEIGHTED RATING is not stored: the page derives it from the header's
   `bayes = {m, c}` — IMDb's own Top 250 formula, (v·R + m·C) / (v + m), a pile of
   m votes at the mean C added to every title so a few thousand devotees cannot
   crown a film. Same idea as BGG's Geek rating, and kept out of the payload for
   the same reason BGG's F average is: one formula, one place.
"""
import json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "results_all.json")
DST = os.path.join(ROOT, "webapp", "public", "data", "imdb-filter.json")

FLOOR = 10000
# The m of the weighted rating: how many votes at the mean every title is given.
# IMDb's Top 250 used 25,000 for years; the page's "Weighted" column uses it too.
BAYES_M = 25000
KIND = {"movie": "f", "tvMovie": "t", "tvSeries": "s", "tvMiniSeries": "m"}
# Shipped in every listed title's genres, so never worth a chip.
DROP_GENRES = {"Adult"}


def tid(t):
	"""'tt0111161' -> 111161. The page pads it back to IMDb's seven digits."""
	return int(t[2:])


def build(raw, floor=FLOOR, bayes_m=BAYES_M):
	keep = sorted(((t, x) for t, x in raw["titles"].items() if x["v"] >= floor and x["ty"] in KIND),
		key=lambda kv: (-kv[1]["v"], kv[0]))
	genres = Counter(g for _, x in keep for g in x["g"] if g not in DROP_GENRES)
	roster = [g for g, _ in sorted(genres.items(), key=lambda kv: (-kv[1], kv[0]))]
	gix = {g: i for i, g in enumerate(roster)}
	names, nix = [], {}

	def ref(ids):
		out = []
		for n in ids:
			name = raw["names"].get(n)
			if not name:
				continue
			if name not in nix:
				nix[name] = len(names)
				names.append(name)
			# Older harvests repeat a series' cast member once per role.
			if nix[name] not in out:
				out.append(nix[name])
		return out

	titles = []
	for t, x in keep:
		row = {"i": tid(t), "n": x["t"], "k": KIND[x["ty"]], "y": x.get("y"), "r": x["r"], "v": x["v"],
			"g": [gix[g] for g in x["g"] if g in gix]}
		if x.get("o"):
			row["o"] = x["o"]
		for k in ("ye", "rt", "se", "ep"):
			if x.get(k):
				row[k] = x[k]
		d, c = ref(x.get("d", [])), ref(x.get("c", []))
		if d:
			row["d"] = d
		if c:
			row["c"] = c
		titles.append(row)

	mean = sum(r["r"] for r in titles) / len(titles) if titles else 0
	kinds = Counter(r["k"] for r in titles)
	return {"collected": raw["collected"], "floor": floor, "count": len(titles),
		"bayes": {"m": bayes_m, "c": round(mean, 3)}, "kinds": dict(kinds),
		"genres": roster, "names": names, "titles": titles}


def coverage(out):
	"""How much of each source a payload carries: the shares the guard compares."""
	films = [r for r in out["titles"] if r["k"] in ("f", "t")]
	series = [r for r in out["titles"] if r["k"] in ("s", "m")]
	return {"titles": len(out["titles"]),
		"cast": sum(1 for r in out["titles"] if r.get("c")),
		"directed": sum(1 for r in films if r.get("d")),
		"episodes": sum(1 for r in series if r.get("ep"))}


def thin(new, old, share=0.9):
	"""Why `new` looks like a harvest that half-answered, or None. The monthly run
	publishes unattended, and a dataset file cut short would otherwise ship as a
	page missing its directors, its cast or half its titles."""
	low = [(k, old[k], new[k]) for k in ("titles", "cast", "directed", "episodes")
		if new.get(k, 0) < share * old.get(k, 0)]
	return f"coverage fell {low}" if low else None


def main():
	args = [a for a in sys.argv[1:] if a != "--force"]
	src = args[0] if args else SRC
	with open(src, encoding="utf-8") as f:
		raw = json.load(f)
	out = build(raw)
	if os.path.exists(DST) and "--force" not in sys.argv:
		with open(DST, encoding="utf-8") as f:
			why = thin(coverage(out), coverage(json.load(f)))
		if why:
			raise SystemExit(f"refusing to replace {DST}: {why} (--force to publish anyway)")
	os.makedirs(os.path.dirname(DST), exist_ok=True)
	with open(DST, "w", encoding="utf-8") as f:
		json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
	print(f"{out['count']:,} titles {out['kinds']}, {len(out['names']):,} names, mean {out['bayes']['c']} "
		f"-> {DST} ({os.path.getsize(DST):,} bytes)")


if __name__ == "__main__":
	main()
