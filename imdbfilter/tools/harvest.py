"""IMDb's non-commercial datasets -> results_all.json (the raw harvest).

Runs on a GitHub runner (.github/workflows/imdb-harvest.yml): the dev container
cannot reach datasets.imdbws.com. Every file is STREAMED — gunzipped line by line
off the response, never saved — and only the rows for titles that clear the vote
floor are kept, so the ~1.5GB of downloads leaves a few MB behind.

  title.ratings    averageRating, numVotes        -> who clears HARVEST_FLOOR
  title.basics     type, titles, years, runtime, genres (adult titles dropped)
  title.crew       a film's directors
  title.episode    a series' seasons and episode count
  title.principals the top-billed cast
  name.basics      the names those two reference

The datasets are documented at https://developer.imdb.com/non-commercial-datasets/.
Their terms: personal and non-commercial use, with the attribution the page carries.

    python imdbfilter/tools/harvest.py              # from the datasets
    python imdbfilter/tools/harvest.py --src DIR    # from local copies of the .tsv.gz
"""
import argparse, datetime, gzip, io, json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results_all.json")
BASE = "https://datasets.imdbws.com/"
UA = "forrest-games-imdb-filter/1.0 (+https://forry4.github.io/imdbfilter)"

# Lower than make_data.py's listing floor, so the floor can be re-tuned off one harvest.
HARVEST_FLOOR = 5000
TYPES = {"movie", "tvMovie", "tvSeries", "tvMiniSeries"}
SERIES = {"tvSeries", "tvMiniSeries"}
FILMS = {"movie", "tvMovie"}
CAST = {"actor", "actress", "self"}
CAST_PER_TITLE = 4
DIRECTORS_PER_TITLE = 3

# Each file's header, checked before a row is read: a renamed or reordered column
# would otherwise be read as the wrong field in silence.
HEADERS = {
	"title.ratings": ["tconst", "averageRating", "numVotes"],
	"title.basics": ["tconst", "titleType", "primaryTitle", "originalTitle", "isAdult", "startYear",
		"endYear", "runtimeMinutes", "genres"],
	"title.crew": ["tconst", "directors", "writers"],
	"title.episode": ["tconst", "parentTconst", "seasonNumber", "episodeNumber"],
	"title.principals": ["tconst", "ordering", "nconst", "category", "job", "characters"],
	"name.basics": ["nconst", "primaryName", "birthYear", "deathYear", "primaryProfession", "knownForTitles"],
}

# A harvest that lost one of these lost far more in silence.
CANARIES = {
	"tt0111161": "The Shawshank Redemption", "tt0068646": "The Godfather",
	"tt0903747": "Breaking Bad", "tt0944947": "Game of Thrones", "tt0185906": "Band of Brothers",
}
MIN_TITLES = 8000


class Reject(Exception):
	"""A file that answered but is not what it should be."""


def nul(v):
	return None if v == "\\N" or v == "" else v


def num(v, cast=int):
	v = nul(v)
	try:
		return cast(v) if v is not None else None
	except ValueError:
		return None


def lines(name, src=None, tries=4):
	"""Yield each data line of a dataset file (newline stripped), header checked."""
	n = 0
	for attempt in range(tries):
		try:
			if src:
				fh = gzip.open(os.path.join(src, f"{name}.tsv.gz"), "rt", encoding="utf-8", newline="")
			else:
				req = urllib.request.Request(f"{BASE}{name}.tsv.gz", headers={"User-Agent": UA})
				resp = urllib.request.urlopen(req, timeout=120)
				fh = io.TextIOWrapper(gzip.GzipFile(fileobj=resp), encoding="utf-8", newline="")
			with fh:
				head = fh.readline().rstrip("\n").split("\t")
				if head != HEADERS[name]:
					raise Reject(f"{name}: header {head!r}")
				for line in fh:
					n += 1
					yield line.rstrip("\n")
			print(f"  {name}: {n:,} rows", flush=True)
			return
		except (urllib.error.URLError, OSError, EOFError) as e:
			# Only a failure BEFORE the first row can be retried cleanly: the callers
			# build dicts as rows arrive, so a mid-stream restart would double-count.
			if attempt == tries - 1 or n:
				raise
			wait = 10 * (attempt + 1)
			print(f"  {name}: {e} — retrying in {wait}s", flush=True)
			time.sleep(wait)


def rows(name, src=None):
	for line in lines(name, src):
		yield line.split("\t")


def keyed(name, keep, src=None):
	"""Rows whose first field is in `keep`. The key is tested BEFORE the line is split:
	principals is ~90M rows and nearly all of them are dropped."""
	for line in lines(name, src):
		if line[:line.find("\t")] in keep:
			yield line.split("\t")


def harvest(src=None, floor=HARVEST_FLOOR):
	print("ratings", flush=True)
	rating = {}
	for t, r, v in rows("title.ratings", src):
		votes = num(v)
		if votes is not None and votes >= floor:
			rating[t] = (float(r), votes)
	if len(rating) < MIN_TITLES:
		raise Reject(f"only {len(rating)} rated titles over {floor} votes")

	print("basics", flush=True)
	titles = {}
	for t, ty, pt, ot, adult, y, ye, rt, g in keyed("title.basics", rating, src):
		if ty not in TYPES or adult == "1":
			continue
		r, v = rating[t]
		rec = {"t": pt, "ty": ty, "y": num(y), "rt": num(rt), "g": nul(g).split(",") if nul(g) else [],
			"r": r, "v": v}
		if ot != pt and nul(ot):
			rec["o"] = ot
		if ty in SERIES and num(ye):
			rec["ye"] = num(ye)
		titles[t] = rec

	print("crew", flush=True)
	films = {t for t, x in titles.items() if x["ty"] in FILMS}
	for t, d, _w in keyed("title.crew", films, src):
		if nul(d):
			titles[t]["d"] = d.split(",")[:DIRECTORS_PER_TITLE]

	print("episodes", flush=True)
	series = {t for t, x in titles.items() if x["ty"] in SERIES}
	eps, seasons = {}, {}
	for _e, parent, s, _n in rows("title.episode", src):
		if parent in series:
			eps[parent] = eps.get(parent, 0) + 1
			sn = num(s)
			if sn is not None and sn > 0:
				seasons.setdefault(parent, set()).add(sn)
	for t in series:
		if t in eps:
			titles[t]["ep"] = eps[t]
		if t in seasons:
			titles[t]["se"] = len(seasons[t])

	print("principals", flush=True)
	for t, _o, n, cat, _j, _c in keyed("title.principals", titles, src):
		if cat in CAST:
			cast = titles[t].setdefault("c", [])
			if len(cast) < CAST_PER_TITLE:
				cast.append(n)

	print("names", flush=True)
	wanted = {n for x in titles.values() for n in x.get("d", []) + x.get("c", [])}
	names = {}
	for n, name, *_ in keyed("name.basics", wanted, src):
		names[n] = name

	for t, name in CANARIES.items():
		if t not in titles:
			raise SystemExit(f"canary missing: {name} ({t})")
	if len(titles) < MIN_TITLES:
		raise SystemExit(f"only {len(titles)} titles kept")
	missing = len(wanted) - len(names)
	if missing > 0.02 * max(1, len(wanted)):
		raise SystemExit(f"{missing} of {len(wanted)} referenced people have no name")
	return {"collected": datetime.date.today().isoformat(), "floor": floor, "titles": titles, "names": names}


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("--src", help="a directory holding the .tsv.gz files, instead of downloading")
	ap.add_argument("--floor", type=int, default=HARVEST_FLOOR)
	a = ap.parse_args()
	out = harvest(a.src, a.floor)
	with open(OUT, "w", encoding="utf-8") as f:
		json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
	kinds = {}
	for x in out["titles"].values():
		kinds[x["ty"]] = kinds.get(x["ty"], 0) + 1
	print(f"{len(out['titles']):,} titles {kinds}, {len(out['names']):,} names -> {OUT} "
		f"({os.path.getsize(OUT):,} bytes)")


if __name__ == "__main__":
	sys.exit(main())
