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
    {"id": "card", "label": "Card game", "tags": ["Card Game", "Deckbuilding"]},
]
SPY = {"Roguelike": {"1": {}, "2": {}}, "Roguelite": {"3": {}},
       "Card Game": {"2": {}}, "Deckbuilding": {}}


def spy_fetch(answers):
    def fetch(url, check):
        tag = urllib.parse.unquote_plus(url.split("tag=", 1)[1])
        return check(json.dumps(answers[tag]))
    return fetch


def test_category_members_are_the_union_of_their_tags(monkeypatch):
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    logs = []
    m = e.category_members(spy_fetch(SPY), logs.append, CATS)
    assert m == {"rogue": {1, 2, 3}, "card": {2}}
    # A tag that answers empty is named, since it silently narrows its group.
    assert any("Deckbuilding" in l and "WARNING" in l for l in logs)


def test_a_category_with_no_members_fails(monkeypatch):
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    answers = dict(SPY, **{"Card Game": {}})
    with pytest.raises(SystemExit):
        e.category_members(spy_fetch(answers), lambda m: None, CATS)


def eshop_fetch(titles, page_sizes):
    def fetch(url, check):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        start, rows = int(q["start"][0]), int(q["rows"][0])
        page_sizes.append(start)
        docs = [{"title": t} for t in titles[start:start + rows]]
        return check(json.dumps({"response": {"numFound": len(titles), "docs": docs}}))
    return fetch


def test_switch_titles_pages_through_the_whole_index():
    titles = [f"Game {i}" for i in range(6000)] + ["Dead Cells™"]
    starts = []
    keys = e.switch_titles(eshop_fetch(titles, starts), lambda m: None, rows=2000)
    assert starts == [0, 2000, 4000, 6000]
    assert "dead cells" in keys and "game 5999" in keys


def test_a_truncated_eshop_index_fails():
    with pytest.raises(SystemExit):
        e.switch_titles(eshop_fetch(["Only One"], []), lambda m: None)


def test_eshop_answer_must_have_the_solr_shape():
    with pytest.raises(e.Rejected):
        e.validate_nintendo("<html>blocked</html>")
    with pytest.raises(e.Rejected):
        e.validate_nintendo(json.dumps({"docs": []}))


def test_enrich_marks_categories_and_switch(monkeypatch):
    monkeypatch.setattr(e, "load_categories", lambda: CATS)
    monkeypatch.setattr(e.time, "sleep", lambda s: None)
    titles = [f"Filler {i}" for i in range(6000)] + ["Dead Cells - Nintendo Switch Edition"]
    spy = spy_fetch(SPY)
    eshop = eshop_fetch(titles, [])
    fetch = lambda url, check: (spy if "steamspy" in url else eshop)(url, check)
    games = [{"n": "Dead Cells", "id": 2}, {"n": "Nothing", "id": 9, "sw": 1}]
    e.enrich(games, fetch, lambda m: None)
    assert games[0]["c"] == ["rogue", "card"] and games[0]["sw"] == 1
    assert games[1]["c"] == [] and "sw" not in games[1]   # a stale flag is cleared
