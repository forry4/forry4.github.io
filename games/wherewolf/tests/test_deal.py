"""Deal / center split + determinism."""
from games.wherewolf import engine
from .conftest import make_game


def test_deal_shape():
    g = make_game(["a", "b", "c", "d"], seed=1)
    assert g["phase"] == engine.DEALING
    assert len(g["players"]) == 4
    assert len(g["center"]) == 3
    for p in g["players"].values():
        assert p["card"] == p["dealt_role"]   # before any swap, card == dealt role
        assert p["ready"] is False


def test_total_cards_equals_players_plus_center():
    g = make_game(["a", "b", "c"], seed=2)
    dealt = [p["dealt_role"] for p in g["players"].values()]
    assert len(dealt) + len(g["center"]) == 6


def test_roles_in_play_tokens_are_public_multiset():
    g = make_game(["a", "b", "c"], seed=3)
    # The 3-player set has exactly two werewolves → two "W" tokens.
    assert g["roles_in_play"].count("W") == 2
    assert "S" in g["roles_in_play"] and "R" in g["roles_in_play"] and "T" in g["roles_in_play"]
    assert len(g["roles_in_play"]) == 6


def test_determinism():
    g1 = make_game(["a", "b", "c", "d", "e"], seed=42)
    g2 = make_game(["a", "b", "c", "d", "e"], seed=42)
    assert {p: g1["players"][p]["dealt_role"] for p in g1["order"]} == \
           {p: g2["players"][p]["dealt_role"] for p in g2["order"]}
    assert g1["center"] == g2["center"]
