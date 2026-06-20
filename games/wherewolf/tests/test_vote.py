"""Voting: cast/change, lock/unlock, tie handling, all-locked."""
from games.wherewolf import engine
from .conftest import make_game, force_roles


def setup_day(role_map, players=("a", "b", "c", "d"), seed=0):
    g = make_game(players, seed=seed)
    force_roles(g, role_map)
    engine.begin_day(g, deadline=None)
    return g


def test_vote_and_change():
    g = setup_day({"a": "villager", "b": "werewolf", "c": "villager", "d": "villager"})
    assert engine.apply_move(g, "a", {"type": "vote", "target": "b"})[0]
    assert g["votes"]["a"] == "b"
    assert engine.apply_move(g, "a", {"type": "vote", "target": "c"})[0]
    assert g["votes"]["a"] == "c"


def test_self_vote_allowed():
    g = setup_day({"a": "villager", "b": "werewolf", "c": "villager"}, players=("a", "b", "c"))
    assert engine.apply_move(g, "a", {"type": "vote", "target": "a"})[0]


def test_lock_requires_a_vote():
    g = setup_day({"a": "villager", "b": "werewolf", "c": "villager"}, players=("a", "b", "c"))
    assert not engine.apply_move(g, "a", {"type": "lock_vote"})[0]
    engine.apply_move(g, "a", {"type": "vote", "target": "b"})
    assert engine.apply_move(g, "a", {"type": "lock_vote"})[0]


def test_cannot_vote_while_locked_then_unlock():
    g = setup_day({"a": "villager", "b": "werewolf", "c": "villager"}, players=("a", "b", "c"))
    engine.apply_move(g, "a", {"type": "vote", "target": "b"})
    engine.apply_move(g, "a", {"type": "lock_vote"})
    assert not engine.apply_move(g, "a", {"type": "vote", "target": "c"})[0]
    assert engine.apply_move(g, "a", {"type": "unlock_vote"})[0]
    assert engine.apply_move(g, "a", {"type": "vote", "target": "c"})[0]


def test_all_locked():
    g = setup_day({"a": "villager", "b": "werewolf", "c": "villager"}, players=("a", "b", "c"))
    assert not engine.all_locked(g)
    for p in ("a", "b", "c"):
        engine.apply_move(g, p, {"type": "vote", "target": "b"})
        engine.apply_move(g, p, {"type": "lock_vote"})
    assert engine.all_locked(g)


def test_tie_no_reveal_wolves_win():
    g = setup_day({"a": "werewolf", "b": "villager", "c": "villager", "d": "villager"})
    engine.apply_move(g, "a", {"type": "vote", "target": "b"})
    engine.apply_move(g, "b", {"type": "vote", "target": "a"})
    engine.resolve_votes(g)
    assert g["revealed_pid"] is None
    assert g["winner"] == "wolves"
    assert g["phase"] == engine.OVER


def test_votes_hidden_before_day():
    g = make_game(["a", "b", "c"], seed=1)  # DEALING
    assert engine.player_view(g, "a")["votes"] == {}
    # during day they are public
    force_roles(g, {"a": "villager", "b": "werewolf", "c": "villager"})
    engine.begin_day(g, deadline=None)
    engine.apply_move(g, "a", {"type": "vote", "target": "b"})
    assert engine.player_view(g, "c")["votes"]["a"] == "b"
