"""Win determination — the revealed player's FINAL card decides."""
from games.wherewolf import engine
from .conftest import make_game, force_roles


def setup_day(role_map, players, seed=0):
    g = make_game(players, seed=seed)
    force_roles(g, role_map)
    engine.begin_day(g, deadline=None)
    return g


def test_werewolf_voted_out_villagers_win():
    g = setup_day({"a": "werewolf", "b": "villager", "c": "villager"}, ("a", "b", "c"))
    for p in ("b", "c"):
        engine.apply_move(g, p, {"type": "vote", "target": "a"})
    engine.apply_move(g, "a", {"type": "vote", "target": "b"})
    engine.resolve_votes(g)
    assert g["revealed_pid"] == "a"
    assert g["winner"] == "villagers"


def test_villager_voted_out_wolves_win():
    g = setup_day({"a": "werewolf", "b": "villager", "c": "villager"}, ("a", "b", "c"))
    for p in ("a", "c"):
        engine.apply_move(g, p, {"type": "vote", "target": "b"})
    engine.apply_move(g, "b", {"type": "vote", "target": "c"})
    engine.resolve_votes(g)
    assert g["revealed_pid"] == "b"
    assert g["winner"] == "wolves"


def test_final_card_decides_after_swap():
    # b was dealt a villager, but a swap left a WEREWOLF card in front of b. If b is
    # voted out, the villagers win — the final card, not the dealt role, decides.
    g = make_game(("a", "b", "c"), seed=1)
    force_roles(g, {"a": "robber", "b": "villager", "c": "werewolf"})
    g["players"]["b"]["card"] = "werewolf"   # a swap moved a wolf card onto b
    engine.begin_day(g, deadline=None)
    for p in ("a", "c"):
        engine.apply_move(g, p, {"type": "vote", "target": "b"})
    engine.apply_move(g, "b", {"type": "vote", "target": "a"})
    engine.resolve_votes(g)
    assert g["revealed_pid"] == "b"
    assert g["winner"] == "villagers"


def test_resolve_is_noop_outside_day():
    g = make_game(("a", "b", "c"), seed=1)  # DEALING
    engine.resolve_votes(g)
    assert g["phase"] == engine.DEALING
    assert g["winner"] is None
