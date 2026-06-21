"""Win-condition matrix — official ONUW multi-death + Hunter chain + the full
team / tanner / minion logic. Win uses FINAL cards."""
from games.wherewolf import engine
from .conftest import make_game, force_roles


def day(cards, players=None, seed=0):
    """A DAY-phase game where each player's FINAL card == cards[pid]."""
    players = players or list(cards.keys())
    g = make_game(players, seed=seed)
    force_roles(g, cards)
    engine.begin_day(g, deadline=None)
    return g


# ── basic single-elimination cases (still valid under multi-death) ────────────
def test_werewolf_voted_out_villagers_win():
    g = day({"a": "werewolf", "b": "villager", "c": "villager"})
    g["votes"] = {"b": "a", "c": "a", "a": "b"}
    engine.resolve_votes(g)
    assert g["deaths"] == ["a"]
    assert "village" in g["winning_teams"] and g["winner"] == "villagers"


def test_villager_voted_out_wolves_win():
    g = day({"a": "werewolf", "b": "villager", "c": "villager"})
    g["votes"] = {"a": "b", "c": "b", "b": "a"}
    engine.resolve_votes(g)
    assert g["deaths"] == ["b"]
    assert g["winning_teams"] == ["werewolf"] and g["winner"] == "wolves"


def test_final_card_decides_after_swap():
    g = day({"a": "robber", "b": "villager", "c": "werewolf"})
    g["players"]["b"]["card"] = "werewolf"   # a swap moved a wolf card onto b
    g["votes"] = {"a": "b", "c": "b", "b": "a"}
    engine.resolve_votes(g)
    assert g["deaths"] == ["b"] and g["winner"] == "villagers"


def test_resolve_is_noop_outside_day():
    g = make_game(("a", "b", "c"), seed=1)
    engine.resolve_votes(g)
    assert g["phase"] == engine.DEALING and g["winner"] is None


# ── the multi-death + roles matrix ────────────────────────────────────────────
def test_max_one_vote_no_death():
    g = day({"a": "werewolf", "b": "villager", "c": "villager"})
    g["votes"] = {"a": "b", "b": "c", "c": "a"}      # 1 each → nobody dies
    engine.resolve_votes(g)
    assert g["deaths"] == [] and g["winning_teams"] == ["werewolf"]


def test_no_werewolf_nobody_dies_village_wins():
    g = day({"a": "villager", "b": "seer", "c": "villager"})
    g["votes"] = {"a": "b", "b": "c", "c": "a"}      # no death
    engine.resolve_votes(g)
    assert g["deaths"] == [] and g["winning_teams"] == ["village"]


def test_no_werewolf_someone_dies_nobody_wins():
    g = day({"a": "villager", "b": "seer", "c": "villager"})
    g["votes"] = {"a": "b", "c": "b", "b": "a"}      # b dies; no wolves in play
    engine.resolve_votes(g)
    assert g["deaths"] == ["b"]
    assert g["winning_teams"] == [] and g["headline"] == "No one wins"


def test_tanner_wins_alone_and_suppresses_wolves():
    g = day({"a": "tanner", "b": "villager", "c": "werewolf"})
    g["votes"] = {"b": "a", "c": "a", "a": "b"}      # tanner dies; no wolf dies
    engine.resolve_votes(g)
    assert g["deaths"] == ["a"]
    assert g["winning_teams"] == ["tanner"]          # wolves suppressed
    assert g["winner"] is None


def test_tanner_and_village_both_win():
    g = day({"a": "tanner", "b": "werewolf", "c": "villager", "d": "villager"})
    g["votes"] = {"c": "a", "d": "a", "a": "b", "b": "b"}   # a:2, b:2 → both die
    engine.resolve_votes(g)
    assert set(g["deaths"]) == {"a", "b"}
    assert "tanner" in g["winning_teams"] and "village" in g["winning_teams"]


def test_minion_death_is_not_a_werewolf_death():
    g = day({"a": "werewolf", "b": "minion", "c": "villager"})
    g["votes"] = {"a": "b", "c": "b", "b": "a"}      # minion dies, wolf survives
    engine.resolve_votes(g)
    assert g["deaths"] == ["b"]
    assert g["winning_teams"] == ["werewolf"]        # killing the minion didn't save the village


def test_minion_no_werewolf_special_win():
    g = day({"a": "minion", "b": "villager", "c": "villager"})
    g["votes"] = {"a": "b", "c": "b", "b": "a"}      # b dies; no werewolf in play
    engine.resolve_votes(g)
    assert g["deaths"] == ["b"]
    assert "minion" in g["winning_teams"] and "village" not in g["winning_teams"]
    assert "a" in g["winners"]                       # the minion won


def test_hunter_chain_flips_outcome():
    g = day({"a": "hunter", "b": "werewolf", "c": "villager"})
    g["votes"] = {"c": "a", "b": "a", "a": "b"}      # a (hunter) dies, voted b → b also dies
    engine.resolve_votes(g)
    assert set(g["deaths"]) == {"a", "b"}            # hunter chain killed the wolf
    assert "village" in g["winning_teams"]


def test_hunter_chain_transitive_and_terminates():
    g = day({"a": "hunter", "b": "hunter", "c": "villager", "d": "werewolf"})
    g["votes"] = {"c": "a", "d": "a", "a": "b", "b": "a"}   # a dies → b (hunter, voted a) dies → a already dead
    engine.resolve_votes(g)
    assert "a" in g["deaths"] and "b" in g["deaths"]


def test_multi_death_tie_kills_all():
    g = day({"a": "werewolf", "b": "villager", "c": "villager", "d": "villager"})
    g["votes"] = {"a": "b", "c": "b", "b": "a", "d": "a"}   # a:2, b:2 → both die
    engine.resolve_votes(g)
    assert set(g["deaths"]) == {"a", "b"}
    assert "village" in g["winning_teams"]           # a werewolf died
