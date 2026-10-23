"""Categories and Switch availability, off canned SteamSpy / eShop answers."""
import json
import urllib.parse

import pytest

from steamfilter.tools import enrich as e


@pytest.mark.parametrize("title,key", [
    ("Dead Cells™", "dead cells"),
    ("DEAD CELLS", "dead cells"),
    ("Dead Cells - Nintendo Switch Edition", "dead cells"),
    ("Celeste Remastered Nintendo Switch Edition", "celeste"),
    ("Hades II – Nintendo Switch™ 2 Edition", "hades ii"),
    ("Dispatch Nintendo Switch 2 Edition", "dispatch"),
    ("The Witcher 3: Wild Hunt – Complete Edition", "the witcher 3 wild hunt"),
    ("Pokémon", "pokemon"),
    ("Baldur's Gate 3", "baldurs gate 3"),
    ("Baldur’s Gate 3", "baldurs gate 3"),
    ("Hades II", "hades ii"),
    # An edition NAME that is part of the game's identity is kept.
    ("Hollow Knight: Voidheart Edition", "hollow knight voidheart edition"),
])
def test_norm_title(title, key):
    assert e.norm_title(title) == key


def test_sequels_do_not_collide():
    assert e.norm_title("Hades") != e.norm_title("Hades II")


CATS = [
    {"id": "rogue", "label": "Roguelike / Roguelite", "tags": ["Roguelike", "Roguelite"]},
    {"id": "card", "label": "Card game", "tags": ["Card Game", "Deckbuilding", "Misspelt"]},
]
NAMES = [{"tagid": 1716, "name": "Roguelike"}, {"tagid": 3959, "name": "Roguelite"},
         {"tagid": 1666, "name": "Card Game"}, {"tagid": 32322, "name": "Deckbuilding"}] + [
         {"tagid": 90000 + i, "name": f"Filler {i}"} for i in range(300)]
# What GetItems answers per app: some carry `tagids`, some `tags` with weights.
ITEMS = {1: {"tagids": [1716]}, 2: {"tags": [{"tagid": 3959, "weight": 9}, {"tagid": 32322}]},
         3: {"tagids": [90001]}}


def steam_fetch(items=ITEMS, names=NAMES, seen=None):
    def fetch(url, check):
        if "populartags" in url:
            return check(json.dumps(names))
        q = json.loads(urllib.parse.unquote(url.split("input_json=", 1)[1]))
        ids = [x["appid"] for x in q["ids"]]
        if seen is not None:
            seen.append(ids)
        return check(json.dumps({"response": {"store_items": [
            dict(items[a], appid=a) for a in ids if a in items]}}))
    return fetch


def test_category_members_union_their_tags_and_name_unknown_ones(monkeypatch):
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    logs = []
    m = e.category_members(steam_fetch(), logs.append, [1, 2, 3], CATS)
    assert m == {"rogue": {1, 2}, "card": {2}}
    assert any("Misspelt" in l and "WARNING" in l for l in logs)


def test_tags_are_asked_for_in_batches(monkeypatch):
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    seen = []
    items = {a: {"tagids": [1716]} for a in range(1, 251)}
    e.category_members(steam_fetch(items, seen=seen), lambda m: None, list(range(1, 251)), CATS[:1])
    assert [len(b) for b in seen] == [100, 100, 50]


def test_a_category_with_no_members_fails(monkeypatch):
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    items = {1: {"tagids": [1716]}, 2: {"tagids": [3959]}, 3: {"tagids": [90001]}}
    with pytest.raises(SystemExit):
        e.category_members(steam_fetch(items), lambda m: None, [1, 2, 3], CATS)


def test_a_thin_tag_answer_fails(monkeypatch):
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):   # 1 of 3 games tagged
        e.category_members(steam_fetch({1: {"tagids": [1716]}}), lambda m: None, [1, 2, 3], CATS)


def test_responses_must_have_the_expected_shape():
    with pytest.raises(e.Rejected):
        e.validate_tag_names(json.dumps(NAMES[:10]))   # too few to be the real list
    with pytest.raises(e.Rejected):
        e.validate_items("<html>Access Denied</html>")


def eshop_fetch(titles, page_sizes, cap=None):
    """Answers like the real index, including its silent cap on the page size."""
    def fetch(url, check):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        start, rows = int(q["start"][0]), int(q["rows"][0])
        rows = min(rows, cap) if cap else rows
        page_sizes.append(start)
        docs = [{"title": t} for t in titles[start:start + rows]]
        return check(json.dumps({"response": {"numFound": len(titles), "docs": docs}}))
    return fetch


def test_switch_titles_pages_through_the_whole_index():
    titles = [f"Game {i}" for i in range(6000)] + ["Dead Cells™"]
    starts = []
    keys = e.switch_titles(eshop_fetch(titles, starts), lambda m: None, rows=2000, canaries=["Dead Cells"])
    assert starts == [0, 2000, 4000, 6000]
    assert "dead cells" in keys and "game 5999" in keys


def test_a_capped_page_size_is_followed_not_skipped():
    titles = [f"Game {i}" for i in range(6000)] + ["Dead Cells"]
    starts = []
    keys = e.switch_titles(eshop_fetch(titles, starts, cap=1000), lambda m: None, rows=2000,
                           canaries=["Dead Cells"])
    assert starts == [0, 1000, 2000, 3000, 4000, 5000, 6000]
    assert len(keys) == 6001


def test_a_truncated_eshop_index_fails():
    with pytest.raises(SystemExit):
        e.switch_titles(eshop_fetch(["Only One"], []), lambda m: None, canaries=[])


def test_a_catalogue_missing_a_canary_fails():
    titles = [f"Game {i}" for i in range(6000)]
    with pytest.raises(SystemExit, match="Hades"):
        e.switch_titles(eshop_fetch(titles, []), lambda m: None, canaries=["Hades"])


def test_eshop_answer_must_have_the_solr_shape():
    with pytest.raises(e.Rejected):
        e.validate_nintendo("<html>blocked</html>")
    with pytest.raises(e.Rejected):
        e.validate_nintendo(json.dumps({"docs": []}))


def test_enrich_marks_categories_and_switch(monkeypatch):
    monkeypatch.setattr(e, "load_categories", lambda: CATS)
    monkeypatch.setattr(e, "CANARIES", ["Dead Cells"])
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    titles = [f"Filler {i}" for i in range(6000)] + ["Dead Cells - Nintendo Switch Edition"]
    steam = steam_fetch()
    eshop = eshop_fetch(titles, [])
    fetch = lambda url, check: (eshop if "nintendo" in url else steam)(url, check)
    games = [{"n": "Dead Cells", "id": 2}, {"n": "Nothing", "id": 3, "sw": 1}, {"n": "Rogue", "id": 1}]
    e.enrich(games, fetch, lambda m: None)
    assert games[0]["c"] == ["rogue", "card"] and games[0]["sw"] == 1
    assert games[1]["c"] == [] and "sw" not in games[1]   # a stale flag is cleared
    assert games[2]["c"] == ["rogue"]
