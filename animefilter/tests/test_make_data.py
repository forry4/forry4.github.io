"""make_data.py on a hand-built harvest: grouping, averaging, dubs, titles, scale."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("anime_make_data", os.path.join(HERE, "..", "tools", "make_data.py"))
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)


def al(i, mal, year, score, fmt="TV", seq=(), pre=(), english=None, romaji=None, genres=("Action",), tags=(), pop=50000):
	edges = [{"relationType": "SEQUEL", "node": {"id": n, "type": "ANIME", "format": "TV"}} for n in seq]
	edges += [{"relationType": "PREQUEL", "node": {"id": n, "type": "ANIME", "format": "TV"}} for n in pre]
	return {"id": i, "idMal": mal, "title": {"english": english, "romaji": romaji or f"Romaji {i}"},
		"format": fmt, "status": "FINISHED", "episodes": 12, "countryOfOrigin": "JP",
		"startDate": {"year": year, "month": 1, "day": 1}, "averageScore": score, "popularity": pop,
		"genres": list(genres), "tags": [{"name": t, "rank": r, "category": "Demographic" if t == "Shounen" else "Theme"} for t, r in tags],
		"studios": {"nodes": [{"name": "Studio"}]}, "relations": {"edges": edges}}


def mal(i, score, members=100000, english=None):
	return {"id": i, "score": score, "members": members, "rank": 1, "title_english": english}


def raw():
	# Show A: three seasons (10 -> 11 -> 12), the middle one unloved.
	# Show B: one film. Show C: a show nobody watches (members under the floor).
	anilist = {
		10: al(10, 110, 2013, 85, seq=[11], english="Show A", tags=[("Gore", 90), ("Military", 40), ("Shounen", 95)]),
		11: al(11, 111, 2017, 75, pre=[10], seq=[12], genres=("Action", "Drama"), tags=[("Gore", 80)]),
		12: al(12, 112, 2019, 92, pre=[11], tags=[("Gore", 70)]),
		20: al(20, 120, 2016, 88, fmt="MOVIE", english=None, romaji="Kimi no Na wa.", genres=("Romance",)),
		30: al(30, 130, 2020, 95),
		# A special: not a show format, never listed even though it scores.
		40: al(40, 140, 2014, 99, fmt="SPECIAL"),
	}
	m = {110: mal(110, 8.5), 111: mal(111, 7.5), 112: mal(112, 9.1), 120: mal(120, 8.8, english="Your Name."),
		130: mal(130, 9.5, members=100), 140: mal(140, 9.9)}
	kitsu = {1: {"rating": 84.0, "votes": 500}, 2: {"rating": 70.0, "votes": 500}, 3: {"rating": 88.0, "votes": 500},
		4: {"rating": 86.0, "votes": 500}}
	return {"collected": "2026-11-03",
		"anilist": {str(k): v for k, v in anilist.items()}, "mal": {str(k): v for k, v in m.items()},
		"kitsu": {str(k): v for k, v in kitsu.items()},
		"kitsu_for": {"10": 1, "11": 2, "12": 3, "20": 4},
		"dubbed": [110, 111, 120], "dub_incomplete": [120]}


def test_seasons_join_and_average():
	out = md.build(raw(), top=10, min_members=1000)
	shows = {s["n"]: s for s in out["shows"]}
	a = shows["Show A"]
	assert [p["id"] for p in a["p"]] == [10, 11, 12]
	assert a["m"] == round((8.5 + 7.5 + 9.1) / 3, 3)
	assert a["a"] == round((8.5 + 7.5 + 9.2) / 3, 3)
	assert a["k"] == round((8.4 + 7.0 + 8.8) / 3, 3)
	assert a["y"] == 2013                      # dated by its first season
	assert set(a["g"]) == {"Action", "Drama"}  # genres across every season
	assert a["t"] == ["Gore"]                  # Military averages 13 — under the bar
	assert a["dm"] == "Shounen"                # a Demographic tag is the demographic, not a tag


def test_floors_formats_and_titles():
	out = md.build(raw(), top=10, min_members=1000)
	names = [s["n"] for s in out["shows"]]
	assert "Romaji 30" not in names            # 100 members: under the floor
	assert "Romaji 40" not in names            # a special is not a show
	assert "Your Name." in names               # AniList has no English title; MAL's is used


def test_dub_levels():
	out = md.build(raw(), top=10, min_members=1000)
	shows = {s["n"]: s for s in out["shows"]}
	assert shows["Show A"]["dub"] == 1         # two of three seasons dubbed
	assert [p["d"] for p in shows["Show A"]["p"]] == [2, 2, 0]
	assert shows["Your Name."]["dub"] == 1     # on the list, but the dub is incomplete


def test_split_cuts_a_chain():
	out = md.build(raw(), top=10, min_members=1000, split={(11, 12)})
	sizes = sorted(len(s["p"]) for s in out["shows"])
	assert sizes == [1, 1, 2]


def test_combined_score_ranks_and_rides_on_mal_scale():
	out = md.build(raw(), top=10, min_members=1000)
	scores = [md.combine({"m": s["m"], "a": s["a"], "k": s["k"]},
		{k: tuple(v) for k, v in out["scale"].items()}) for s in out["shows"]]
	assert scores == sorted(scores, reverse=True)
	assert [s["rk"] for s in out["shows"]] == list(range(1, len(out["shows"]) + 1))
	# z-scores average to zero, so the mean combined score is MAL's own mean.
	assert abs(sum(scores) / len(scores) - out["scale"]["m"][0]) < 1e-2
