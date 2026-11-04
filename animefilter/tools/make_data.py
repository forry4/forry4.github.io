"""results_all.json (from harvest.py) -> webapp/public/data/anime-filter.json

Offline and re-runnable: the harvest is the only step that asks the sites.

1. ENTRIES. Every AniList entry in a show format (TV, TV short, ONA, movie) with a
   score on at least one site that clears that site's vote floor.
2. SHOWS. Entries joined by AniList SEQUEL/PREQUEL edges are one show — Attack on
   Titan's seven parts, Gintama's ten. `SPLIT` cuts the chains that run between
   genuinely different series.
3. SITE SCORES. Per site, a show's score is the plain mean of its seasons' scores
   (each season counts once, whatever its length or vote count).
4. COMBINED. The three sites score on different curves (Kitsu's is compressed, MAL's
   long-tailed), so each site's show score becomes a z-score over the shows that site
   rates, the z-scores present are averaged, and the result is put back on MAL's
   scale (MAL mean + z * MAL sd). The page recomputes this when a site is switched
   off, so the header carries each site's mean and sd.
5. The top TOP shows by that combined score, among those with enough MAL members.
"""
import datetime, json, math, os, re, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "results_all.json")
DST = os.path.join(ROOT, "webapp", "public", "data", "anime-filter.json")

TOP = 500
SHOW_FORMATS = {"TV", "TV_SHORT", "ONA", "MOVIE"}
FMT = {"TV": "TV", "TV_SHORT": "TV", "ONA": "ONA", "MOVIE": "Movie"}
# Specials and OVAs never count as a season, but a sequel chain often runs THROUGH one
# (Gintama -> The Semi-Final (special) -> The Final; Euphonium 2 -> Ensemble Contest
# (OVA) -> Euphonium 3), so they still join what is on either side of them.
BRIDGE_FORMATS = {"SPECIAL", "OVA"}
# A season's score on a site only counts with this many people behind it there: MAL
# members (its top list prints no voter count), AniList list adds, Kitsu ratings.
FLOOR = {"m": 5000, "a": 1000, "k": 100}
# A show must be this widely watched on MAL (its most-watched season) to be listed.
MIN_MEMBERS = 40000
# Tags shown per show, and the AniList relevance a tag must reach on average.
TAGS_PER_SHOW, TAG_RANK = 6, 55
# AniList tag categories that describe the cast or the audience rather than the show.
TAG_SKIP_CATS = {"Sexual Content", "Demographic"}
DEMOS = ("Shounen", "Seinen", "Shoujo", "Josei", "Kids")

# Sequel/prequel edges AniList draws between what are really separate series. Each
# pair is cut. Ids are AniList's; found by reading the grouped output for chains that
# span decades or studios (see CLAUDE.md).
SPLIT = {
	# Fate/Zero Season 2 is drawn as the prequel of every later Fate/stay night
	# adaptation — four different series (2006 TV, the UBW film, UBW TV, Heaven's Feel).
	(11741, 356), (11741, 6922), (11741, 19603), (11741, 20791),
	(19613, 143327),   # Initial D Final Stage -> MF GHOST, a new series set decades on
	(32, 2759),        # The End of Evangelion -> Rebuild 1.0: the Rebuild films are a remake
	(167404, 21),      # MONSTERS (a one-shot short) -> ONE PIECE
	(21394, 14513),    # Magi: Adventure of Sinbad, a prequel spin-off series
	(21626, 20722),    # Handa-kun, a prequel spin-off series of Barakamon
	# Reached through a special once the harvest followed bridges (2026-11-03):
	(1566, 106154),    # GitS SAC: Solid State Society -> SAC_2045, a later, separate production
	(1539, 103555),    # Touch: Cross Road (special) -> MIX, a sequel series set 30 years on
}


def ascore(m):
	return m.get("averageScore") / 10 if m.get("averageScore") else None


def entry_scores(m, mal, kitsu):
	out = {}
	if ascore(m) is not None and (m.get("popularity") or 0) >= FLOOR["a"]:
		out["a"] = ascore(m)
	if mal and mal.get("score") and (mal.get("members") or 0) >= FLOOR["m"]:
		out["m"] = mal["score"]
	if kitsu and kitsu.get("rating") and (kitsu.get("votes") or 0) >= FLOOR["k"]:
		out["k"] = kitsu["rating"] / 10
	return out


# A show is named after its first season, which sometimes says so ("Natsume's Book of
# Friends Season 1", "Major S1"); the show's row drops that.
_FIRST = re.compile(r"(?:[\s:,-]+(?:Season 1|S1|1st Season|First Season|Part 1|1st Stage)|\s*\((?:Season 1|TV)\))$", re.I)


def show_name(n):
	return _FIRST.sub("", n).strip() or n


# Listed shows no site gives an English title for, by AniList id — their English
# release names. (Major, Touch, Baby Steps, City Hunter and capeta need none: the
# romaji IS the English name.)
ENGLISH = {
	20760: "Gintama: The Best of Gintama on Theater 2D",
	127099: "Fog Hill of the Five Elements",
	21678: "Assassination Classroom: Extracurricular Lesson",
}


def english(m, mal, kitsu):
	if m.get("id") in ENGLISH:
		return ENGLISH[m["id"]]
	t = m.get("title") or {}
	for cand in (t.get("english"), mal and mal.get("title_english"), kitsu and kitsu.get("title_en")):
		if cand and cand.strip():
			return cand.strip()
	return (t.get("romaji") or (mal or {}).get("title") or "").strip()


def start_key(m):
	d = m.get("startDate") or {}
	return (d.get("year") or 9999, d.get("month") or 13, d.get("day") or 32, m["id"])


class DSU:
	def __init__(self):
		self.p = {}

	def find(self, x):
		self.p.setdefault(x, x)
		while self.p[x] != x:
			self.p[x] = self.p[self.p[x]]
			x = self.p[x]
		return x

	def union(self, a, b):
		ra, rb = self.find(a), self.find(b)
		if ra != rb:
			self.p[max(ra, rb)] = min(ra, rb)


def group(entries, split=SPLIT, bridges=None):
	"""AniList id -> show root, joining sequel/prequel edges inside `entries`, passing
	through `bridges` (held specials/OVAs), which join but are never listed."""
	nodes = {**(bridges or {}), **entries}
	d = DSU()
	for i, m in nodes.items():
		d.find(i)
		for e in (m.get("relations") or {}).get("edges") or []:
			n = (e.get("node") or {}).get("id")
			if e.get("relationType") in ("SEQUEL", "PREQUEL") and n in nodes:
				if (i, n) in split or (n, i) in split:
					continue
				d.union(i, n)
	shows = defaultdict(list)
	for i in entries:
		shows[d.find(i)].append(i)
	return shows


def mean(xs):
	return sum(xs) / len(xs) if xs else None


def stats(xs):
	mu = mean(xs)
	sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) if len(xs) > 1 else 1.0
	return mu, sd or 1.0


def combine(site, st, use=("m", "a", "k")):
	zs = [(site[s] - st[s][0]) / st[s][1] for s in use if site.get(s) is not None]
	if not zs:
		return None
	return st["m"][0] + mean(zs) * st["m"][1]


def build(raw, top=TOP, min_members=MIN_MEMBERS, split=SPLIT):
	al = {int(k): v for k, v in raw["anilist"].items()}
	mal = {int(k): v for k, v in raw["mal"].items()}
	kit = {int(k): v for k, v in raw["kitsu"].items()}
	kfor = {int(k): v for k, v in raw["kitsu_for"].items()}
	dubbed, partial = set(raw.get("dubbed") or []), set(raw.get("dub_incomplete") or [])

	entries, info = {}, {}
	for i, m in al.items():
		if m.get("format") not in SHOW_FORMATS or m.get("status") == "NOT_YET_RELEASED":
			continue
		mm = mal.get(m.get("idMal")) if m.get("idMal") else None
		kk = kit.get(kfor.get(i))
		sc = entry_scores(m, mm, kk)
		if not sc:
			continue
		entries[i] = m
		info[i] = {"m": mm, "k": kk, "sc": sc}

	bridges = {i: m for i, m in al.items() if m.get("format") in BRIDGE_FORMATS}
	shows = group(entries, split, bridges)
	rows = []
	for root, ids in shows.items():
		ids.sort(key=lambda i: start_key(entries[i]))
		first = entries[ids[0]]
		site = {}
		for s in ("m", "a", "k"):
			site[s] = mean([info[i]["sc"][s] for i in ids if s in info[i]["sc"]])
		members = max((info[i]["m"] or {}).get("members") or 0 for i in ids)
		rows.append({"ids": ids, "first": first, "site": site, "members": members})

	# Each site's spread over the shows it rates — the yardstick that puts all three on one scale.
	st = {s: stats([r["site"][s] for r in rows if r["site"][s] is not None and r["members"] >= min_members])
		for s in ("m", "a", "k")}
	for r in rows:
		r["score"] = combine(r["site"], st)
	pool = [r for r in rows if r["members"] >= min_members and sum(v is not None for v in r["site"].values()) >= 2]
	pool.sort(key=lambda r: -r["score"])
	keep = pool[:top]

	genre_n, tag_n = Counter(), Counter()
	out = []
	for rank, r in enumerate(keep, 1):
		ids, first = r["ids"], r["first"]
		fi = info[ids[0]]
		genres = Counter(g for i in ids for g in entries[i].get("genres") or [])
		tag_rank = defaultdict(float)
		for i in ids:
			for t in entries[i].get("tags") or []:
				if t.get("isGeneralSpoiler") or t.get("isMediaSpoiler") or t.get("isAdult") or t.get("category") in TAG_SKIP_CATS:
					continue
				tag_rank[t["name"]] += (t.get("rank") or 0) / len(ids)
		tags = [t for t, v in sorted(tag_rank.items(), key=lambda kv: -kv[1]) if v >= TAG_RANK][:TAGS_PER_SHOW]
		gl = [g for g, _ in genres.most_common()]
		genre_n.update(gl)
		tag_n.update(tags)
		parts, dubs = [], []
		for i in ids:
			m, x = entries[i], info[i]
			mid = m.get("idMal")
			dub = 2 if mid in dubbed and mid not in partial else 1 if mid in dubbed else 0
			dubs.append(dub)
			parts.append({
				"id": i, "mal": mid, "n": english(m, x["m"], x["k"]), "y": (m.get("startDate") or {}).get("year"),
				"f": FMT[m["format"]], "e": m.get("episodes"),
				"m": x["sc"].get("m"), "a": x["sc"].get("a"), "k": round(x["sc"]["k"], 2) if "k" in x["sc"] else None,
				"mr": (x["m"] or {}).get("rank"), "d": dub,
			})
		# 2 = every season dubbed, 1 = some, 0 = none known.
		dub = 2 if all(d == 2 for d in dubs) else 1 if any(dubs) else 0
		# The demographic is an AniList tag in the "Demographic" category (MAL's pages are
		# not read for it); the first season's strongest one wins.
		demo = next((t["name"] for t in sorted(first.get("tags") or [], key=lambda t: -(t.get("rank") or 0))
			if t.get("category") == "Demographic" and t["name"] in DEMOS), None)
		studios = [s["name"] for s in ((first.get("studios") or {}).get("nodes") or [])][:2]
		out.append({
			"id": first["id"], "n": show_name(english(first, fi["m"], fi["k"])),
			"r": (first.get("title") or {}).get("romaji"),
			"y": (first.get("startDate") or {}).get("year"), "f": FMT[first["format"]],
			"c": first.get("countryOfOrigin") or "JP", "dm": demo, "st": studios,
			"g": gl, "t": tags, "dub": dub,
			"m": round(r["site"]["m"], 3) if r["site"]["m"] is not None else None,
			"a": round(r["site"]["a"], 3) if r["site"]["a"] is not None else None,
			"k": round(r["site"]["k"], 3) if r["site"]["k"] is not None else None,
			"mv": r["members"], "rk": rank, "p": parts,
		})

	header = {
		"collected": raw.get("collected") or datetime.date.today().isoformat(),
		"top": top, "min_members": min_members, "floors": FLOOR,
		"scale": {s: [round(st[s][0], 4), round(st[s][1], 4)] for s in st},
		"genres": [g for g, _ in genre_n.most_common()],
		"tags": [t for t, n in tag_n.most_common() if n >= 5],
		"compare": compare(rows, entries, info, keep, min_members),
		"shows": out,
	}
	return header


def compare(rows, entries, info, keep, min_members):
	"""How the merged list differs from ranking every season on its own (for the notes)."""
	show_of = {i: r["first"]["id"] for r in rows for i in r["ids"]}
	singles = [(info[i]["sc"]["m"], i) for i in entries if "m" in info[i]["sc"]
		and ((info[i]["m"] or {}).get("members") or 0) >= min_members]
	singles.sort(reverse=True)
	top100 = [i for _, i in singles[:100]]
	per = Counter(show_of[i] for i in top100)
	big, n = per.most_common(1)[0] if per else (None, 0)
	name = next((english(r["first"], info[r["ids"][0]]["m"], info[r["ids"][0]]["k"]) for r in rows if r["first"]["id"] == big), None)
	multi = sum(1 for r in keep if len(r["ids"]) > 1)
	return {"mal_top100_shows": len(per), "most_spots": name, "most_spots_n": n,
		"multi_season": multi, "entries": sum(len(r["ids"]) for r in keep)}


def coverage(payload):
	"""How many listed shows carry a score from each site."""
	shows = payload.get("shows") or []
	return {"shows": len(shows), **{s: sum(x.get(s) is not None for x in shows) for s in "mak"}}


def thin(new, old, share=0.9):
	"""Why `new` looks like a harvest a site half-answered, or None. The quarterly run
	publishes unattended, and a site that failed or blocked part-way would otherwise
	ship as a list missing that site's scores."""
	if new["shows"] < TOP:
		return f"only {new['shows']} shows, not {TOP}"
	low = [s for s in "mak" if new[s] < share * old.get(s, 0)]
	return f"site coverage fell {[(s, old[s], new[s]) for s in low]}" if low else None


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
	c = out["compare"]
	print(f"{len(out['shows'])} shows ({c['entries']} seasons/films, {c['multi_season']} with more than one) -> {DST} "
		f"({os.path.getsize(DST):,} bytes)")
	print(f"MAL's top 100 single entries come from {c['mal_top100_shows']} shows; {c['most_spots']} holds {c['most_spots_n']}")


if __name__ == "__main__":
	main()
