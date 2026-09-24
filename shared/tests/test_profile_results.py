"""Every game feeds the profile, and each game's reader tells a win from a loss.

`core.results` records finished games for the profile page through one reader
per game, registered from the game's own main.py. Forgetting to register is
silent: that game's results are simply never on anyone's profile, and nothing
else on the site looks wrong. So the roster is DERIVED from the catalogue
(shared/catalog.js), never hand-written — the next game joins it automatically.

The readers are then run on finished games made by each game's REAL engine,
for the three games that had no finished game in production to check them
against when this shipped (Where Wolf?, Dontminion, Black Castle), plus the two
whose outcomes are unusual: SecretNames (cooperative — both seats share it) and
Pinch (a concession).
"""
from __future__ import annotations

import importlib
import pathlib
import random
import re

import pytest

from core import results

ROOT = pathlib.Path(__file__).resolve().parents[2]
CATALOG = ROOT / "shared" / "catalog.js"
REGISTER = re.compile(r'_results\.register\(\s*"(\w+)"')


def _catalog_ids() -> list[str]:
    ids = re.findall(r'\{\s*id:\s*"(\w+)"', CATALOG.read_text(encoding="utf-8"))
    assert len(ids) >= 11, f"read too few games out of shared/catalog.js: {ids}"
    return ids


def _registrations() -> dict[str, list[pathlib.Path]]:
    found: dict[str, list[pathlib.Path]] = {}
    for main in sorted((ROOT / "games").glob("*/main.py")):
        for game in REGISTER.findall(main.read_text(encoding="utf-8")):
            found.setdefault(game, []).append(main)
    return found


def test_every_game_in_the_catalogue_feeds_the_profile():
    found = _registrations()
    missing = [g for g in _catalog_ids() if g not in found]
    assert not missing, (
        "these games never register a results reader with core.results, so their "
        f"finished games are on nobody's profile: {missing}")
    twice = {g: [str(p.relative_to(ROOT)) for p in ps] for g, ps in found.items() if len(ps) > 1}
    assert not twice, f"registered more than once: {twice}"
    stray = sorted(set(found) - set(_catalog_ids()))
    assert not stray, f"registered under an id the catalogue does not have (the page cannot name it): {stray}"


def _source(game: str, module: str) -> results.Source:
    importlib.import_module(module)
    return results.sources()[game]


def _outcomes(res) -> dict[str, str]:
    return {p["id"]: p["outcome"] for p in res["players"]}


MODULES = {
    "spender": "games.spender.main", "coc": "games.castles_of_crimson.main",
    "wherewolf": "games.wherewolf.main", "duel": "games.spender_duel.main",
    "dontminion": "games.dontminion.main", "dissonance": "games.dissonance.main",
    "ragtag": "games.rag_tag.main", "orbit": "games.orbit.main",
    "blackcastle": "games.black_castle.main", "secretnames": "games.secretnames.main",
    "pinch": "games.pinch.main",
}


def test_the_module_list_matches_the_catalogue():
    assert sorted(MODULES) == sorted(_catalog_ids())


@pytest.mark.parametrize("game", sorted(MODULES))
def test_a_game_that_has_not_finished_records_nothing(game):
    src = _source(game, MODULES[game])
    for state in ({}, {"players": {"a": "A"}}, {"players": {"a": "A"}, "game": {}},
                  {"players": {"a": "A"}, "game": None}):
        assert src.standings(state) is None, f"{game} reads a result out of {state}"


def test_where_wolf_is_a_team_game_and_carries_the_card():
    from games.wherewolf import engine, roles
    src = _source("wherewolf", MODULES["wherewolf"])
    pids = ["p1", "p2", "p3", "p4"]
    g = engine.new_game(pids, names={p: p.upper() for p in pids}, seed=7,
                        deck=roles.recommended_deck(len(pids)))
    g["phase"] = engine.DAY
    engine.resolve_votes(g)
    res = src.standings({"players": {p: p.upper() for p in pids}, "game": g})
    outs = _outcomes(res)
    assert {p for p, o in outs.items() if o == "win"} == set(g["winners"])
    assert "draw" not in outs.values(), "a team win was read as a tie between its members"
    assert [p["detail"] for p in res["players"]] == [g["players"][p]["card"] for p in g["order"]]


def test_dontminion_reads_its_winners_and_vp():
    from games.dontminion import engine
    src = _source("dontminion", MODULES["dontminion"])
    g = engine.new_game(["a", "b"], ["base"], seed=3, names={"a": "A", "b": "B"})
    engine._finish_game(g)
    state = {"players": {"a": "A", "b": "B"}, "game": g, "ai_players": ["b"]}
    # Nobody has played a turn: equal VP, equal turns, so the engine's own
    # tiebreak leaves both seats winning — which the profile calls a draw.
    assert sorted(g["winners"]) == ["a", "b"]
    res = src.standings(state)
    assert _outcomes(res) == {"a": "draw", "b": "draw"}
    assert [p["score"] for p in res["players"]] == [g["scores"][p]["vp"] for p in g["players"]]
    assert [p["bot"] for p in res["players"]] == [False, True]
    g["winners"] = ["b"]
    assert _outcomes(src.standings(state)) == {"a": "loss", "b": "win"}


def test_black_castle_has_one_winner_and_its_score():
    from games.black_castle import engine
    src = _source("blackcastle", MODULES["blackcastle"])
    g = engine.new_game(["a", "b", "c"], names={"a": "A", "b": "B", "c": "C"}, seed=5)
    engine._score_game(g)
    res = src.standings({"players": {"a": "A", "b": "B", "c": "C"}, "game": g})
    outs = _outcomes(res)
    assert outs[g["winner"]] == "win" and sorted(outs.values()) == ["loss", "loss", "win"]
    assert {p["id"]: p["score"] for p in res["players"]} == g["scores"]


def test_secretnames_is_shared_by_both_seats():
    from games.secretnames import engine
    src = _source("secretnames", MODULES["secretnames"])
    names = {"a": "A", "b": "B"}
    g = engine.new_game(["a", "b"], names, rng=random.Random(1))
    engine.abandon(g, "a")
    assert set(_outcomes(src.standings({"players": names, "game": g})).values()) == {"loss"}
    g["phase"] = "won"
    assert set(_outcomes(src.standings({"players": names, "game": g})).values()) == {"win"}


def test_pinch_concession_is_a_loss_for_the_player_who_conceded():
    from games.pinch import engine
    src = _source("pinch", MODULES["pinch"])
    names = {"a": "A", "b": "B"}
    g = engine.new_game(["a", "b"], names=names, seed=2, mode="blitz")
    engine.concede(g, "a")
    res = src.standings({"players": names, "game": g, "mode": "blitz",
                         "ai_player": "b", "ai_difficulty": "easy"})
    assert _outcomes(res) == {"a": "loss", "b": "win"} and res["mode"] == "blitz"
