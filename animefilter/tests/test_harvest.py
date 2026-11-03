"""harvest.py's parsers and guards, off canned answers (the sites are never asked)."""
import importlib.util, os
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("anime_harvest", os.path.join(HERE, "..", "tools", "harvest.py"))
hv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hv)


def test_kitsu_votes_are_the_sum_of_its_rating_frequencies():
	k = hv.kitsu_trim({"id": "7442", "attributes": {"averageRating": "84.12", "userCount": 99,
		"ratingFrequencies": {"2": "10", "20": "30", "junk": "x"}, "titles": {"en": "Attack on Titan"}}})
	assert k == {"id": 7442, "rating": 84.12, "votes": 40, "users": 99, "title_en": "Attack on Titan",
		"canonical": None, "subtype": None}


def test_the_cross_site_map_reads_both_kitsu_domains():
	aod = {"data": [
		{"sources": ["https://anilist.co/anime/16498", "https://kitsu.app/anime/7442", "https://myanimelist.net/anime/16498"]},
		{"sources": ["https://anilist.co/anime/5114", "https://kitsu.io/anime/3936"]},
		{"sources": ["https://anilist.co/anime/1"]},   # no Kitsu entry: no link
	]}
	by_al, by_mal = hv.aod_maps(aod)
	assert by_al == {16498: 7442, 5114: 3936}
	assert by_mal == {16498: 7442}


def test_only_sequel_edges_to_shows_and_bridges_group():
	m = {"relations": {"edges": [
		{"relationType": "SEQUEL", "node": {"id": 2, "type": "ANIME", "format": "TV"}},
		{"relationType": "PREQUEL", "node": {"id": 3, "type": "ANIME", "format": "MOVIE"}},
		{"relationType": "SIDE_STORY", "node": {"id": 4, "type": "ANIME", "format": "TV"}},
		{"relationType": "SEQUEL", "node": {"id": 5, "type": "ANIME", "format": "OVA"}},
		{"relationType": "SEQUEL", "node": {"id": 6, "type": "MANGA", "format": "MANGA"}},
	]}}
	assert list(hv.group_neighbours(m)) == [2, 3, 5]   # an OVA is a bridge


@pytest.mark.parametrize("bad", [{"errors": [{"message": "Too Many Requests"}], "data": None},
	{"data": {"Page": None}}, "<html>Just a moment...</html>"])
def test_a_non_answer_from_anilist_is_rejected_not_cached(bad):
	with pytest.raises(hv.Reject):
		hv.v_anilist(bad)


# Trimmed from real myanimelist.net markup (the runner probe, 2026-11-03).
TOP_ROW = b'''<tr class="ranking-list"><td class="rank ac" valign="top">
<span class="lightLink top-anime-rank-text rank1">1</span></td>
<td class="title al va-t word-break"><a class="hoverinfo_trigger fl-l ml12 mr8"
href="https://myanimelist.net/anime/52991/Sousou_no_Frieren" id="#area52991"></a>
<div class="information di-ib mt4">TV (28 eps)<br>Sep 2023 - Mar 2024<br>1,539,455 members<br></div></td>
<td class="score ac fs14"><div class="js-top-ranking-score-col di-ib al"><i class="icon-score-star"></i>
<span class="text on score-label score-9">9.24</span></div></td></tr>'''


def test_the_top_list_parses_id_rank_members_and_score():
	assert hv.parse_top(TOP_ROW * 2) == [{"id": 52991, "rank": 1, "members": 1539455, "score": 9.24}] * 2


def test_an_anime_page_parses_and_an_unscored_one_reads_none():
	page = b'''<span class="dark_text">English:</span> Attack on Titan &amp; Co</div>
<span itemprop="ratingValue" class="score-label score-8">8.58</span>
<span itemprop="ratingCount" style="display: none">3125107</span>
<span class="dark_text">Ranked:</span> #116<sup>2</sup>
<span class="dark_text">Members:</span>
 4,123,456</div>'''
	assert hv.parse_anime(page) == {"score": 8.58, "scored_by": 3125107, "members": 4123456, "rank": 116,
		"title_english": "Attack on Titan & Co"}
	na = b'<span class="score-label score-na">N/A</span><span class="dark_text">Members:</span> 1,200'
	assert hv.parse_anime(na)["score"] is None


@pytest.mark.parametrize("bad", [b"<html>429 Too Many Requests</html>", b"<html>nothing here</html>"])
def test_a_mal_non_answer_is_rejected(bad):
	with pytest.raises(hv.Reject):
		hv.parse_top(bad)
	with pytest.raises(hv.Reject):
		hv.parse_anime(bad)
