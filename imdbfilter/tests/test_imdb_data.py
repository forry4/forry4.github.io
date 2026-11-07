"""harvest.py and make_data.py on hand-written dataset files (IMDb is never asked)."""
import gzip, importlib.util, os
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, file):
	spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, "..", "tools", file))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


hv = load("imdb_harvest", "harvest.py")
md = load("imdb_make_data", "make_data.py")


def write(d, name, rows, header=None):
	with gzip.open(d / f"{name}.tsv.gz", "wt", encoding="utf-8", newline="") as f:
		f.write("\t".join(header or hv.HEADERS[name]) + "\n")
		for r in rows:
			f.write("\t".join(r) + "\n")


@pytest.fixture
def src(tmp_path, monkeypatch):
	monkeypatch.setattr(hv, "MIN_TITLES", 1)
	monkeypatch.setattr(hv, "CANARIES", {"tt0111161": "The Shawshank Redemption", "tt0903747": "Breaking Bad"})
	write(tmp_path, "title.ratings", [
		["tt0111161", "9.3", "3000000"], ["tt0903747", "9.5", "2200000"], ["tt0000002", "6.0", "40"],
		["tt0000003", "7.0", "80000"], ["tt0000004", "8.0", "90000"], ["tt0000005", "7.5", "20000"],
		["tt10000006", "8.1", "12000"]])
	write(tmp_path, "title.basics", [
		["tt0111161", "movie", "The Shawshank Redemption", "The Shawshank Redemption", "0", "1994", "\\N", "142", "Drama"],
		["tt0903747", "tvSeries", "Breaking Bad", "Breaking Bad", "0", "2008", "2013", "45", "Crime,Drama,Thriller"],
		["tt0000002", "movie", "Too Few Votes", "Too Few Votes", "0", "2001", "\\N", "90", "Comedy"],
		["tt0000003", "movie", "Adult Film", "Adult Film", "1", "2001", "\\N", "90", "Adult"],
		["tt0000004", "tvEpisode", "An Episode", "An Episode", "0", "2009", "\\N", "47", "Drama"],
		["tt0000005", "movie", "Amélie", "Le fabuleux destin d'Amélie Poulain", "0", "2001", "\\N", "\\N", "Comedy,Romance"],
		["tt10000006", "tvMiniSeries", "A Mini", "A Mini", "0", "2020", "2020", "60", "\\N"]])
	write(tmp_path, "title.crew", [
		["tt0111161", "nm0001104", "nm0000175"], ["tt0903747", "nm0000001", "nm0319213"],
		["tt0000005", "nm0000002,nm0000003,nm0000004,nm0000005", "\\N"]])
	write(tmp_path, "title.episode", [
		["tt0959621", "tt0903747", "1", "1"], ["tt1054724", "tt0903747", "1", "2"],
		["tt1232248", "tt0903747", "2", "1"], ["tt1232249", "tt0903747", "\\N", "\\N"],
		["tt9999999", "tt0000004", "1", "1"]])
	write(tmp_path, "title.principals", [
		["tt0111161", "1", "nm0000209", "actor", "\\N", '["Andy"]'],
		["tt0111161", "2", "nm0000151", "actor", "\\N", '["Red"]'],
		["tt0111161", "3", "nm0001104", "director", "\\N", "\\N"],
		["tt0903747", "1", "nm0186505", "actor", "\\N", '["Walter"]'],
		["tt0903747", "2", "nm0666739", "actress", "\\N", '["Skyler"]'],
		["tt0903747", "3", "nm0348152", "actor", "\\N", "\\N"],
		["tt0903747", "4", "nm0000006", "actor", "\\N", "\\N"],
		["tt0903747", "5", "nm0000007", "actor", "\\N", "\\N"]])
	write(tmp_path, "name.basics", [[n, f"Name {n}", "\\N", "\\N", "\\N", "\\N"] for n in
		["nm0001104", "nm0000209", "nm0000151", "nm0186505", "nm0666739", "nm0348152", "nm0000006",
			"nm0000002", "nm0000003", "nm0000004", "nm0000001"]])
	return tmp_path


def test_harvest_keeps_rated_titles_of_the_four_kinds(src):
	raw = hv.harvest(str(src), floor=1000)
	assert set(raw["titles"]) == {"tt0111161", "tt0903747", "tt0000005", "tt10000006"}
	s = raw["titles"]["tt0111161"]
	assert s == {"t": "The Shawshank Redemption", "ty": "movie", "y": 1994, "rt": 142, "g": ["Drama"],
		"r": 9.3, "v": 3000000, "d": ["nm0001104"], "c": ["nm0000209", "nm0000151"]}
	bb = raw["titles"]["tt0903747"]
	assert bb["ye"] == 2013 and bb["ep"] == 4 and bb["se"] == 2   # an unnumbered episode counts, not as a season
	assert "d" not in bb                                          # a series' crew is every episode's: not read
	assert len(bb["c"]) == hv.CAST_PER_TITLE                      # top-billed only
	am = raw["titles"]["tt0000005"]
	assert am["o"] == "Le fabuleux destin d'Amélie Poulain" and am["rt"] is None
	assert am["d"] == ["nm0000002", "nm0000003", "nm0000004"]     # capped at three
	assert raw["titles"]["tt10000006"]["g"] == []
	assert raw["names"]["nm0000209"] == "Name nm0000209"


def test_a_renamed_column_is_refused_not_misread(src):
	write(src, "title.ratings", [["tt0111161", "3000000", "9.3"]], header=["tconst", "numVotes", "averageRating"])
	with pytest.raises(hv.Reject):
		hv.harvest(str(src), floor=1000)


def test_a_missing_canary_fails_the_harvest(src, monkeypatch):
	monkeypatch.setattr(hv, "CANARIES", {"tt0068646": "The Godfather"})
	with pytest.raises(SystemExit, match="Godfather"):
		hv.harvest(str(src), floor=1000)


def test_make_data_interns_names_and_floors_votes(src):
	raw = hv.harvest(str(src), floor=1000)
	out = md.build(raw, floor=15000)
	ids = [r["i"] for r in out["titles"]]
	assert ids == [111161, 903747, 5]                  # most-voted first; the 12k mini-series is under the floor
	assert out["count"] == 3 and out["kinds"] == {"f": 2, "s": 1}
	shaw = out["titles"][0]
	assert [out["names"][i] for i in shaw["c"]] == ["Name nm0000209", "Name nm0000151"]
	assert [out["genres"][i] for i in out["titles"][1]["g"]] == ["Crime", "Drama", "Thriller"]
	assert out["genres"][0] == "Drama"                 # roster is most common first
	assert "rt" not in out["titles"][2]                # an unknown runtime is left out, not zero
	assert out["titles"][2]["d"] == [out["names"].index("Name nm0000002"),
		out["names"].index("Name nm0000003"), out["names"].index("Name nm0000004")]
	assert out["bayes"] == {"m": md.BAYES_M, "c": round((9.3 + 9.5 + 7.5) / 3, 3)}
	assert len(out["names"]) == len(set(out["names"]))


def test_thin_refuses_a_half_answered_harvest():
	old = {"titles": 1000, "cast": 990, "directed": 700, "episodes": 200}
	assert md.thin(dict(old), old) is None
	assert "cast" in md.thin({**old, "cast": 400}, old)
	assert "titles" in md.thin({**old, "titles": 850}, old)
	assert md.thin({**old, "titles": 950}, old) is None
