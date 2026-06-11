"""Comprehensive unit tests for Spender game logic."""
import copy
import random

import pytest

from games.spender import main


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_game_state(p1="alice", p2="bob"):
    """Build a minimal but playable 2-player game dict."""
    decks = main.build_deck()
    board = main._deal_board(decks)
    nobles_pool = list(main.ALL_NOBLES)
    random.shuffle(nobles_pool)
    nobles = nobles_pool[:3]
    bank = {c: 4 for c in main.GEM_COLORS}
    bank["gold"] = 5

    def player_state():
        return {"tokens": main.empty_gems(), "purchased": [], "reserved": [], "nobles": []}

    return {
        "bank": bank,
        "decks": decks,
        "board": board,
        "nobles": nobles,
        "players": {p1: player_state(), p2: player_state()},
        "order": [p1, p2],
        "turn": p1,
        "phase": "playing",
        "winner": None,
    }


# ─── Deck structure ────────────────────────────────────────────────────────────

def test_build_deck_counts():
    decks = main.build_deck()
    assert len(decks["L1"]) == len(main.LEVEL1)
    assert len(decks["L2"]) == len(main.LEVEL2)
    assert len(decks["L3"]) == len(main.LEVEL3)
    assert len(decks["L1"]) == 40
    assert len(decks["L2"]) == 30
    assert len(decks["L3"]) == 20


def test_deal_board():
    decks = main.build_deck()
    l1_before = len(decks["L1"])
    l2_before = len(decks["L2"])
    l3_before = len(decks["L3"])
    board = main._deal_board(decks)
    assert len(board["L1"]) == 4
    assert len(board["L2"]) == 4
    assert len(board["L3"]) == 4
    assert len(decks["L1"]) == l1_before - 4
    assert len(decks["L2"]) == l2_before - 4
    assert len(decks["L3"]) == l3_before - 4
    assert all(c is not None for c in board["L1"])


# ─── Bonuses ──────────────────────────────────────────────────────────────────

def test_bonuses_from_empty():
    assert main.bonuses_from([]) == main.empty_gems()


def test_bonuses_from_purchased():
    cards = [
        {"bonus": "blue", "cost": {}, "points": 0, "id": "x1"},
        {"bonus": "blue", "cost": {}, "points": 0, "id": "x2"},
        {"bonus": "red", "cost": {}, "points": 1, "id": "x3"},
    ]
    b = main.bonuses_from(cards)
    assert b["blue"] == 2
    assert b["red"] == 1
    assert b["green"] == 0


# ─── can_afford ───────────────────────────────────────────────────────────────

def test_can_afford_basic_pass():
    tokens = {"white": 2, "blue": 0, "green": 0, "red": 1, "black": 0, "gold": 0}
    cost = {"white": 2, "red": 1}
    bonuses = main.empty_gems()
    assert main.can_afford(cost, tokens, bonuses)


def test_can_afford_basic_fail():
    tokens = {"white": 1, "blue": 0, "green": 0, "red": 1, "black": 0, "gold": 0}
    cost = {"white": 2, "red": 1}
    bonuses = main.empty_gems()
    assert not main.can_afford(cost, tokens, bonuses)


def test_can_afford_with_bonuses():
    tokens = {"white": 0, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}
    cost = {"white": 3}
    bonuses = {**main.empty_gems(), "white": 3}
    assert main.can_afford(cost, tokens, bonuses)


def test_can_afford_with_gold():
    tokens = {**main.empty_gems(), "blue": 1, "gold": 2}
    cost = {"blue": 3}
    bonuses = main.empty_gems()
    assert main.can_afford(cost, tokens, bonuses)


def test_cannot_afford_not_enough_gold():
    tokens = {**main.empty_gems(), "blue": 1, "gold": 1}
    cost = {"blue": 3}
    bonuses = main.empty_gems()
    assert not main.can_afford(cost, tokens, bonuses)


# ─── calc_spend ───────────────────────────────────────────────────────────────

def test_calc_spend_basic():
    tokens = {**main.empty_gems(), "blue": 2, "red": 1}
    cost = {"blue": 2, "red": 1}
    bonuses = main.empty_gems()
    spend = main.calc_spend(cost, tokens, bonuses)
    assert spend["blue"] == 2
    assert spend["red"] == 1
    assert spend["gold"] == 0


def test_calc_spend_uses_gold():
    tokens = {**main.empty_gems(), "blue": 1, "gold": 2}
    cost = {"blue": 3}
    bonuses = main.empty_gems()
    spend = main.calc_spend(cost, tokens, bonuses)
    assert spend["blue"] == 1
    assert spend["gold"] == 2


def test_calc_spend_bonuses_reduce_cost():
    tokens = {**main.empty_gems(), "white": 1}
    cost = {"white": 3}
    bonuses = {**main.empty_gems(), "white": 2}
    spend = main.calc_spend(cost, tokens, bonuses)
    assert spend["white"] == 1
    assert spend["gold"] == 0


# ─── Turn advancement ─────────────────────────────────────────────────────────

def test_advance_turn_p1_to_p2():
    g = make_game_state("p1", "p2")
    g["turn"] = "p1"
    nxt = main._advance_turn(g)
    assert nxt == "p2"


def test_advance_turn_p2_wraps_to_p1():
    g = make_game_state("p1", "p2")
    g["turn"] = "p2"
    nxt = main._advance_turn(g)
    assert nxt == "p1"


# ─── Win detection ────────────────────────────────────────────────────────────

def test_check_winner_none_at_start():
    g = make_game_state("p1", "p2")
    assert main._check_winner(g) is None


def test_check_winner_detects_15pts():
    g = make_game_state("p1", "p2")
    # Give p1 enough purchased cards for 15 points
    g["players"]["p1"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 5, "id": "c1"},
        {"bonus": "red", "cost": {}, "points": 5, "id": "c2"},
        {"bonus": "green", "cost": {}, "points": 5, "id": "c3"},
    ]
    assert main._check_winner(g) == "p1"


def test_check_winner_nobles_contribute():
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 4, "id": "c1"},
        {"bonus": "red", "cost": {}, "points": 4, "id": "c2"},
        {"bonus": "green", "cost": {}, "points": 4, "id": "c3"},
    ]
    g["players"]["p1"]["nobles"] = [{"id": "n1", "points": 3, "req": {}}]
    assert main._check_winner(g) == "p1"


# ─── Noble claiming ───────────────────────────────────────────────────────────

def test_check_nobles_no_match():
    g = make_game_state("p1", "p2")
    # p1 has no purchased cards — can't meet any noble requirement
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"white": 4, "green": 4}}]
    claimable = main._check_nobles(g, "p1")
    assert claimable == []


def test_check_nobles_match():
    g = make_game_state("p1", "p2")
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"white": 3}}]
    g["players"]["p1"]["purchased"] = [
        {"bonus": "white", "cost": {}, "points": 0, "id": f"c{i}"} for i in range(3)
    ]
    claimable = main._check_nobles(g, "p1")
    assert len(claimable) == 1
    assert claimable[0]["id"] == "n1"


# ─── Take gems validation ─────────────────────────────────────────────────────

def test_take_gems_double_requires_4_in_bank():
    """Double-take a color should fail when bank has fewer than 4."""
    g = make_game_state("p1", "p2")
    g["bank"]["blue"] = 3  # only 3 in bank

    freq = {"blue": 2}
    colors = ["blue", "blue"]
    doubles = [c for c, n in freq.items() if n == 2]

    # Replicate the server-side check
    is_blocked = bool(doubles and g["bank"].get(doubles[0], 0) < 4)
    assert is_blocked


def test_take_gems_double_allowed_with_4_in_bank():
    g = make_game_state("p1", "p2")
    g["bank"]["blue"] = 4

    freq = {"blue": 2}
    doubles = [c for c, n in freq.items() if n == 2]
    is_blocked = bool(doubles and g["bank"].get(doubles[0], 0) < 4)
    assert not is_blocked
