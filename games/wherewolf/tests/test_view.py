"""player_view redaction matrix — one assertion per visibility rule."""
from games.wherewolf import engine
from .conftest import make_game, at_step


def night(step, role_map, players=("a", "b", "c", "d")):
    return at_step(make_game(players, seed=0), step, role_map)


def test_over_reveals_all_cards():
    g = night(engine.STEP_WOLVES, {"a": "werewolf", "b": "villager"})
    g["phase"] = engine.OVER
    v = engine.player_view(g, "b")
    assert all(pd["card"] is not None for pd in v["players"].values())
    assert all(c is not None for c in v["center"])


def test_dealing_shows_only_own_card():
    g = make_game(["a", "b", "c"], seed=0)   # DEALING
    v = engine.player_view(g, "a")
    assert v["players"]["a"]["card"] is not None
    assert v["players"]["b"]["card"] is None


def test_night_hides_own_card_except_robber_insomniac():
    g = night(engine.STEP_SEER, {"a": "seer", "b": "villager"})
    assert engine.player_view(g, "a")["players"]["a"]["card"] is None
    # robber sees own (new) card
    g2 = night(engine.STEP_ROBBER, {"a": "robber", "b": "villager"})
    assert engine.player_view(g2, "a")["players"]["a"]["card"] == "robber"


def test_werewolves_see_each_other_only():
    g = night(engine.STEP_WOLVES, {"a": "werewolf", "b": "werewolf", "c": "villager"},
              players=("a", "b", "c"))
    assert engine.player_view(g, "a")["players"]["b"]["card"] == "werewolf"
    assert engine.player_view(g, "a")["players"]["c"]["card"] is None
    assert engine.player_view(g, "c")["players"]["a"]["card"] is None


def test_is_lone_wolf_flag():
    g = night(engine.STEP_WOLVES, {"a": "werewolf", "b": "villager", "c": "villager"},
              players=("a", "b", "c"))
    assert engine.player_view(g, "a")["is_lone_wolf"] is True
    g2 = night(engine.STEP_WOLVES, {"a": "werewolf", "b": "werewolf", "c": "villager"},
               players=("a", "b", "c"))
    assert engine.player_view(g2, "a")["is_lone_wolf"] is False
