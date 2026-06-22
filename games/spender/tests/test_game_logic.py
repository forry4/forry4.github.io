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


# ─── Final-round and tiebreaker logic ────────────────────────────────────────

def test_p1_hits_15_p2_still_gets_turn():
    """If p1 (index 0) hits 15+ pts, game must NOT end until p2 has played."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 15, "id": "c1"},
    ]
    # Simulate end of p1's turn
    main._finish_turn(g, "p1")
    # final_round_trigger set, but game not over — p2 still needs to play
    assert g.get("final_round_trigger") == "p1"
    assert g.get("phase") != "over"
    assert g["turn"] == "p2"


def test_p2_hits_15_game_ends_immediately():
    """If p2 (index 1) hits 15+ pts on their turn, the game ends — p1 already had their turn."""
    g = make_game_state("p1", "p2")
    g["turn"] = "p2"
    g["players"]["p2"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 15, "id": "c1"},
    ]
    main._finish_turn(g, "p2")
    assert g.get("phase") == "over"


def test_final_round_ends_after_p2_plays():
    """After p1 triggers 15+, p2 plays their final turn and then the game resolves."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 15, "id": "c1"},
    ]
    # p1's turn ends
    main._finish_turn(g, "p1")
    assert g.get("phase") != "over"
    # Now p2 takes their final turn (no points scored — p1 still wins)
    main._finish_turn(g, "p2")
    assert g.get("phase") == "over"
    assert g["winner"] == "p1"


def test_resolve_winner_tiebreak_fewest_purchased():
    """Tiebreak: both at same pts → player with fewer purchased cards wins."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 15, "id": "c1"},
        {"bonus": "red",  "cost": {}, "points": 0,  "id": "c2"},
        {"bonus": "red",  "cost": {}, "points": 0,  "id": "c3"},
    ]
    g["players"]["p2"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 15, "id": "c4"},
    ]
    main._resolve_winner(g)
    # p2 has 1 card vs p1's 3 — p2 wins the tiebreak
    assert g["winner"] == "p2"


def test_resolve_winner_tiebreak_fewest_reserved():
    """Reserved cards no longer break ties per official rules → shared victory."""
    g = make_game_state("p1", "p2")
    card = {"bonus": "blue", "cost": {}, "points": 15, "id": "c1"}
    g["players"]["p1"]["purchased"] = [dict(card, id="c1")]
    g["players"]["p2"]["purchased"] = [dict(card, id="c2")]
    g["players"]["p1"]["reserved"] = [{"bonus": "red", "cost": {}, "points": 0, "id": "r1"}]
    main._resolve_winner(g)
    assert isinstance(g["winner"], list)
    assert set(g["winner"]) == {"p1", "p2"}


def test_resolve_winner_shared_victory():
    """All tiebreakers exhausted → shared victory returned as a list."""
    g = make_game_state("p1", "p2")
    card = {"bonus": "blue", "cost": {}, "points": 15, "id": "c1"}
    g["players"]["p1"]["purchased"] = [dict(card, id="c1")]
    g["players"]["p2"]["purchased"] = [dict(card, id="c2")]
    main._resolve_winner(g)
    assert isinstance(g["winner"], list)
    assert set(g["winner"]) == {"p1", "p2"}


# ─── _calc_points ─────────────────────────────────────────────────────────────

def test_calc_points_zero():
    ps = {"purchased": [], "nobles": []}
    assert main._calc_points(ps) == 0


def test_calc_points_from_cards_only():
    ps = {"purchased": [
        {"bonus": "blue", "cost": {}, "points": 3, "id": "c1"},
        {"bonus": "red",  "cost": {}, "points": 2, "id": "c2"},
    ], "nobles": []}
    assert main._calc_points(ps) == 5


def test_calc_points_from_nobles_only():
    ps = {"purchased": [], "nobles": [{"id": "n1", "points": 3, "req": {}}]}
    assert main._calc_points(ps) == 3


def test_calc_points_combined():
    ps = {
        "purchased": [{"bonus": "blue", "cost": {}, "points": 4, "id": "c1"}],
        "nobles":    [{"id": "n1", "points": 3, "req": {}}],
    }
    assert main._calc_points(ps) == 7


# ─── Noble claiming — multiple and partial matches ────────────────────────────

def test_check_nobles_multiple_match():
    """Player qualifying for two nobles simultaneously — both returned."""
    g = make_game_state("p1", "p2")
    g["nobles"] = [
        {"id": "n1", "points": 3, "req": {"white": 3}},
        {"id": "n2", "points": 3, "req": {"blue": 3}},
    ]
    g["players"]["p1"]["purchased"] = (
        [{"bonus": "white", "cost": {}, "points": 0, "id": f"w{i}"} for i in range(3)] +
        [{"bonus": "blue",  "cost": {}, "points": 0, "id": f"b{i}"} for i in range(3)]
    )
    claimable = main._check_nobles(g, "p1")
    assert len(claimable) == 2
    assert {n["id"] for n in claimable} == {"n1", "n2"}


def test_check_nobles_partial_multi_color_no_match():
    """Noble needing two colors fails if only one color is met."""
    g = make_game_state("p1", "p2")
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"white": 3, "blue": 3}}]
    g["players"]["p1"]["purchased"] = [
        {"bonus": "white", "cost": {}, "points": 0, "id": f"c{i}"} for i in range(3)
    ]
    assert main._check_nobles(g, "p1") == []


def test_noble_requires_exact_bonus_threshold():
    """Noble needs exactly N cards of a color; N-1 is not enough."""
    g = make_game_state("p1", "p2")
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"green": 4}}]
    g["players"]["p1"]["purchased"] = [
        {"bonus": "green", "cost": {}, "points": 0, "id": f"g{i}"} for i in range(3)
    ]
    assert main._check_nobles(g, "p1") == []
    g["players"]["p1"]["purchased"].append(
        {"bonus": "green", "cost": {}, "points": 0, "id": "g3"}
    )
    assert len(main._check_nobles(g, "p1")) == 1


# ─── _ai_pick_noble ───────────────────────────────────────────────────────────

def test_ai_pick_noble_single():
    """Single claimable noble is always returned as-is."""
    g = make_game_state("p1", "p2")
    noble = {"id": "n1", "points": 3, "req": {"white": 4}}
    assert main._ai_pick_noble([noble], g, "p1") == noble


def test_ai_pick_noble_picks_closest_for_opponent():
    """AI picks the noble the opponent is closest to (minimum opponent deficit)."""
    g = make_game_state("p1", "p2")
    # Opponent already has 3 white bonuses — only 1 more white needed for n_close
    g["players"]["p2"]["purchased"] = [
        {"bonus": "white", "cost": {}, "points": 0, "id": f"w{i}"} for i in range(3)
    ]
    noble_close = {"id": "n_close", "points": 3, "req": {"white": 4}}  # opponent deficit = 1
    noble_far   = {"id": "n_far",   "points": 3, "req": {"blue": 4}}   # opponent deficit = 4
    picked = main._ai_pick_noble([noble_close, noble_far], g, "p1")
    assert picked["id"] == "n_close"


def test_ai_pick_noble_no_opponent_returns_first():
    """With only one player in order, falls back to first noble."""
    g = make_game_state("p1", "p2")
    g["order"] = ["p1"]
    nobles = [
        {"id": "n1", "points": 3, "req": {"white": 3}},
        {"id": "n2", "points": 3, "req": {"blue": 3}},
    ]
    assert main._ai_pick_noble(nobles, g, "p1") == nobles[0]


# ─── _sim_apply_move — buy ────────────────────────────────────────────────────

def test_sim_buy_board_card_moves_to_purchased():
    """Buying a board card places it in purchased, slot filled from deck."""
    g = make_game_state("p1", "p2")
    card = g["board"]["L1"][0]
    assert card is not None
    deck_before = len(g["decks"]["L1"])
    g["players"]["p1"]["tokens"] = {c: 4 for c in main.GEM_COLORS}
    g["players"]["p1"]["tokens"]["gold"] = 0
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": card["id"]})
    assert card in g["players"]["p1"]["purchased"]
    assert len(g["decks"]["L1"]) == deck_before - 1


def test_sim_buy_deck_empty_leaves_slot_none():
    """When deck is exhausted, buying from board leaves that slot as None."""
    g = make_game_state("p1", "p2")
    g["decks"]["L1"] = []
    card = g["board"]["L1"][0]
    assert card is not None
    g["players"]["p1"]["tokens"] = {c: 4 for c in main.GEM_COLORS}
    g["players"]["p1"]["tokens"]["gold"] = 0
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": card["id"]})
    assert card in g["players"]["p1"]["purchased"]
    assert any(slot is None for slot in g["board"]["L1"])


def test_sim_buy_reserved_card():
    """Buying a reserved card removes it from the reserved hand."""
    g = make_game_state("p1", "p2")
    reserved = {"bonus": "blue", "cost": {"blue": 2}, "points": 1, "id": "r1"}
    g["players"]["p1"]["reserved"] = [reserved]
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "blue": 2}
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": "r1"})
    assert reserved in g["players"]["p1"]["purchased"]
    assert g["players"]["p1"]["reserved"] == []


def test_sim_buy_spends_tokens_to_bank():
    """Token cost is deducted from player and returned to the bank."""
    g = make_game_state("p1", "p2")
    card = {"bonus": "blue", "cost": {"white": 2, "red": 1}, "points": 1, "id": "tc1"}
    g["board"]["L1"][0] = card
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "white": 2, "red": 1}
    bank_white_before = g["bank"]["white"]
    bank_red_before   = g["bank"]["red"]
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert g["players"]["p1"]["tokens"]["white"] == 0
    assert g["players"]["p1"]["tokens"]["red"]   == 0
    assert g["bank"]["white"] == bank_white_before + 2
    assert g["bank"]["red"]   == bank_red_before   + 1


def test_sim_buy_gold_covers_shortfall():
    """Gold is spent to cover the gap between cost and available tokens."""
    g = make_game_state("p1", "p2")
    card = {"bonus": "red", "cost": {"red": 3}, "points": 1, "id": "gc1"}
    g["board"]["L2"][0] = card
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "red": 1, "gold": 2}
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": "gc1"})
    assert card in g["players"]["p1"]["purchased"]
    assert g["players"]["p1"]["tokens"]["gold"] == 0
    assert g["players"]["p1"]["tokens"]["red"]  == 0


def test_sim_buy_bonuses_reduce_cost():
    """Purchased card bonuses reduce the token cost for buying."""
    g = make_game_state("p1", "p2")
    # 2 white bonuses; card costs 2 white → free
    g["players"]["p1"]["purchased"] = [
        {"bonus": "white", "cost": {}, "points": 0, "id": f"b{i}"} for i in range(2)
    ]
    card = {"bonus": "green", "cost": {"white": 2}, "points": 1, "id": "disc1"}
    g["board"]["L1"][0] = card
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": "disc1"})
    assert card in g["players"]["p1"]["purchased"]
    # No tokens were spent
    assert g["players"]["p1"]["tokens"]["white"] == 0


def test_sim_buy_triggers_noble():
    """Noble is auto-claimed after a purchase completes its requirement."""
    g = make_game_state("p1", "p2")
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"white": 3}}]
    g["players"]["p1"]["purchased"] = [
        {"bonus": "white", "cost": {}, "points": 0, "id": f"pw{i}"} for i in range(2)
    ]
    triggering = {"bonus": "white", "cost": {}, "points": 1, "id": "pw3"}
    g["board"]["L1"][0] = triggering
    main._sim_apply_move(g, "p1", {"type": "buy", "card_id": "pw3"})
    assert len(g["players"]["p1"]["nobles"]) == 1
    assert g["nobles"] == []


# ─── _sim_apply_move — take_gems ─────────────────────────────────────────────

def test_sim_take_gems_moves_to_player():
    """Gems move from bank to player tokens."""
    g = make_game_state("p1", "p2")
    bank_white_before = g["bank"]["white"]
    main._sim_apply_move(g, "p1", {"type": "take_gems", "colors": ["white", "blue", "green"]})
    assert g["players"]["p1"]["tokens"]["white"] == 1
    assert g["players"]["p1"]["tokens"]["blue"]  == 1
    assert g["players"]["p1"]["tokens"]["green"] == 1
    assert g["bank"]["white"] == bank_white_before - 1


def test_sim_take_gems_skips_empty_bank_color():
    """If requested color is empty in the bank, it is skipped silently."""
    g = make_game_state("p1", "p2")
    g["bank"]["white"] = 0
    main._sim_apply_move(g, "p1", {"type": "take_gems", "colors": ["white"]})
    assert g["players"]["p1"]["tokens"]["white"] == 0


def test_sim_take_gems_double():
    """Double-taking the same color gives 2 gems."""
    g = make_game_state("p1", "p2")
    g["bank"]["red"] = 4
    main._sim_apply_move(g, "p1", {"type": "take_gems", "colors": ["red", "red"]})
    assert g["players"]["p1"]["tokens"]["red"] == 2
    assert g["bank"]["red"] == 2


def test_sim_take_gems_overflow_trimmed_to_10():
    """When taking gems pushes total past 10, ai_discard_one trims back to ≤10."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "white": 9}
    main._sim_apply_move(g, "p1", {"type": "take_gems", "colors": ["blue", "red", "green"]})
    assert sum(g["players"]["p1"]["tokens"].values()) <= 10


# ─── _sim_apply_move — reserve ────────────────────────────────────────────────

def test_sim_reserve_board_card_awards_gold():
    """Reserving a board card moves it to hand and gives 1 gold from bank."""
    g = make_game_state("p1", "p2")
    card = g["board"]["L2"][0]
    assert card is not None
    gold_before = g["bank"]["gold"]
    main._sim_apply_move(g, "p1", {"type": "reserve", "card_id": card["id"]})
    assert card in g["players"]["p1"]["reserved"]
    assert g["players"]["p1"]["tokens"]["gold"] == 1
    assert g["bank"]["gold"] == gold_before - 1


def test_sim_reserve_no_gold_when_bank_empty():
    """Reserving when gold bank is exhausted gives no gold."""
    g = make_game_state("p1", "p2")
    g["bank"]["gold"] = 0
    card = g["board"]["L1"][0]
    main._sim_apply_move(g, "p1", {"type": "reserve", "card_id": card["id"]})
    assert card in g["players"]["p1"]["reserved"]
    assert g["players"]["p1"]["tokens"]["gold"] == 0


def test_sim_reserve_slot_replenished_from_deck():
    """After reserving a board card, deck fills the empty slot."""
    g = make_game_state("p1", "p2")
    card = g["board"]["L1"][0]
    deck_before = len(g["decks"]["L1"])
    main._sim_apply_move(g, "p1", {"type": "reserve", "card_id": card["id"]})
    assert len(g["decks"]["L1"]) == deck_before - 1
    assert card not in g["board"]["L1"]


def test_sim_reserve_overflow_trimmed():
    """Reserving gold while already at 10 tokens triggers a discard."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "white": 10}
    g["bank"]["gold"] = 3
    card = g["board"]["L1"][0]
    main._sim_apply_move(g, "p1", {"type": "reserve", "card_id": card["id"]})
    assert sum(g["players"]["p1"]["tokens"].values()) <= 10


# ─── Reserve limit ────────────────────────────────────────────────────────────

def test_get_all_moves_no_reserve_at_three():
    """When already holding 3 reserved cards, no reserve moves are generated."""
    g = make_game_state("p1", "p2")
    ps = g["players"]["p1"]
    for i in range(3):
        c = g["board"]["L1"][i]
        if c:
            ps["reserved"].append(c)
            g["board"]["L1"][i] = None
    moves = main._get_all_moves(g, "p1")
    assert not any(m["type"] == "reserve" for m in moves)


# ─── _get_all_moves ───────────────────────────────────────────────────────────

def test_get_all_moves_always_nonempty():
    """Move list is never empty even at the start of the game."""
    g = make_game_state("p1", "p2")
    assert len(main._get_all_moves(g, "p1")) > 0


def test_get_all_moves_includes_affordable_buy():
    """A zero-cost card on the board appears as a buy move."""
    g = make_game_state("p1", "p2")
    free_card = {"bonus": "red", "cost": {}, "points": 1, "id": "free1"}
    g["board"]["L1"][0] = free_card
    moves = main._get_all_moves(g, "p1")
    assert any(m["type"] == "buy" and m["card_id"] == "free1" for m in moves)


def test_get_all_moves_excludes_unaffordable_buy():
    """A card requiring 7 gems the player doesn't have is excluded."""
    g = make_game_state("p1", "p2")
    expensive = {"bonus": "blue", "cost": {"blue": 7}, "points": 4, "id": "exp1"}
    g["board"]["L3"][0] = expensive
    moves = main._get_all_moves(g, "p1")
    assert not any(m["type"] == "buy" and m["card_id"] == "exp1" for m in moves)


def test_get_all_moves_has_gem_takes_with_nonempty_bank():
    """take_gems moves are generated when the bank has gems."""
    g = make_game_state("p1", "p2")
    assert any(m["type"] == "take_gems" for m in main._get_all_moves(g, "p1"))


def test_get_all_moves_no_gems_at_capacity():
    """Player at 10 tokens cannot take gems — no take_gems in move list."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["tokens"] = {c: 2 for c in main.GEM_COLORS}
    moves = main._get_all_moves(g, "p1")
    assert not any(m["type"] == "take_gems" for m in moves)


# ─── _fast_rollout_move ───────────────────────────────────────────────────────

def test_fast_rollout_always_returns_move():
    """Rollout policy always returns a well-formed move dict."""
    g = make_game_state("p1", "p2")
    mv = main._fast_rollout_move(g, "p1")
    assert isinstance(mv, dict) and "type" in mv


def test_fast_rollout_buys_affordable_card():
    """With a free card on the board the rollout chooses to buy it."""
    g = make_game_state("p1", "p2")
    free_card = {"bonus": "blue", "cost": {}, "points": 2, "id": "fr1"}
    g["board"]["L1"][0] = free_card
    mv = main._fast_rollout_move(g, "p1")
    assert mv["type"] == "buy" and mv["card_id"] == "fr1"


# ─── _game_urgency ────────────────────────────────────────────────────────────

def test_game_urgency_zero_at_start():
    g = make_game_state("p1", "p2")
    assert main._game_urgency(g) == 0.0


def test_game_urgency_one_at_15():
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [{"bonus": "blue", "cost": {}, "points": 15, "id": "c1"}]
    assert main._game_urgency(g) == 1.0


def test_game_urgency_proportional():
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [
        {"bonus": "blue", "cost": {}, "points": 7, "id": "c1"},
        {"bonus": "red",  "cost": {}, "points": 1, "id": "c2"},
    ]
    urgency = main._game_urgency(g)
    assert abs(urgency - 8 / 15) < 0.01


# ─── _ai_discard_one ─────────────────────────────────────────────────────────

def test_ai_discard_removes_least_needed():
    """AI discards the token with lowest future need, not the most valuable color."""
    g = make_game_state("p1", "p2")
    # Board card needs red; player has plenty of blue (not needed) and 1 red
    g["board"] = {
        "L1": [{"bonus": "red", "cost": {"red": 3}, "points": 1, "id": "rd1"}, None, None, None],
        "L2": [None, None, None, None],
        "L3": [None, None, None, None],
    }
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "blue": 5, "red": 1}
    main._ai_discard_one(g, "p1")
    assert g["players"]["p1"]["tokens"]["blue"] == 4  # blue discarded
    assert g["players"]["p1"]["tokens"]["red"]  == 1  # red kept


def test_ai_discard_one_reduces_total_by_one():
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "white": 3, "blue": 2}
    total_before = sum(g["players"]["p1"]["tokens"].values())
    main._ai_discard_one(g, "p1")
    assert sum(g["players"]["p1"]["tokens"].values()) == total_before - 1


# ─── _sim_rollout ─────────────────────────────────────────────────────────────

def test_sim_rollout_terminates():
    """Rollout always completes without raising, regardless of initial state."""
    g = make_game_state("p1", "p2")
    result = main._sim_rollout(g, max_turns=100)
    assert result is None or isinstance(result, (str, list))


def test_sim_rollout_returns_winner_string_or_list():
    """If game ends during rollout, winner is a string (solo) or list (tie)."""
    import time
    for _ in range(5):
        g = make_game_state("p1", "p2")
        result = main._sim_rollout(g, max_turns=200)
        if result is not None:
            assert isinstance(result, (str, list))


# ─── Final round with both players at 15+ ────────────────────────────────────

def test_both_players_hit_15_tiebreaker_applies():
    """Both players reach 15+ in the final round; fewest-purchased tiebreaker decides."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [{"bonus": "blue", "cost": {}, "points": 15, "id": "c1"}]
    main._finish_turn(g, "p1")
    assert g.get("final_round_trigger") == "p1"
    # p2 also reaches 15 but buys an extra card (more purchased → loses tiebreak)
    g["players"]["p2"]["purchased"] = [
        {"bonus": "red", "cost": {}, "points": 15, "id": "c2"},
        {"bonus": "red", "cost": {}, "points": 0,  "id": "c3"},
    ]
    main._finish_turn(g, "p2")
    assert g["phase"] == "over"
    assert g["winner"] == "p1"


def test_final_round_trigger_set_only_once():
    """final_round_trigger is not overwritten if a second player also hits 15."""
    g = make_game_state("p1", "p2")
    g["players"]["p1"]["purchased"] = [{"bonus": "blue", "cost": {}, "points": 15, "id": "c1"}]
    main._finish_turn(g, "p1")
    assert g["final_round_trigger"] == "p1"
    # Even if p2 would also trigger it, the key stays as p1 (already set)
    g["players"]["p2"]["purchased"] = [{"bonus": "red", "cost": {}, "points": 16, "id": "c2"}]
    main._finish_turn(g, "p2")
    assert g["final_round_trigger"] == "p1"  # unchanged


# ─── Three-way shared victory ─────────────────────────────────────────────────

def test_resolve_winner_three_way_tie():
    """Three players all tied → shared victory list contains all three."""
    decks = main.build_deck()
    board = main._deal_board(decks)
    nobles = list(main.ALL_NOBLES)[:4]
    bank = {c: 7 for c in main.GEM_COLORS}
    bank["gold"] = 5

    def ps():
        return {"tokens": main.empty_gems(), "purchased": [], "reserved": [], "nobles": []}

    g = {
        "bank": bank, "decks": decks, "board": board, "nobles": nobles,
        "players": {"p1": ps(), "p2": ps(), "p3": ps()},
        "order": ["p1", "p2", "p3"], "turn": "p1", "phase": "playing", "winner": None,
    }
    card = {"bonus": "blue", "cost": {}, "points": 15, "id": "base"}
    for pid in ["p1", "p2", "p3"]:
        g["players"][pid]["purchased"] = [dict(card, id=f"c_{pid}")]
    main._resolve_winner(g)
    assert isinstance(g["winner"], list)
    assert set(g["winner"]) == {"p1", "p2", "p3"}


# ─── can_afford edge cases ────────────────────────────────────────────────────

def test_can_afford_combined_bonus_token_gold():
    """Cost covered by a combination of bonus, regular token, and gold."""
    tokens  = {**main.empty_gems(), "blue": 1, "gold": 1}
    cost    = {"blue": 3}
    bonuses = {**main.empty_gems(), "blue": 1}
    # effective need = 3-1=2; have 1 blue + 1 gold → just enough
    assert main.can_afford(cost, tokens, bonuses)


def test_can_afford_zero_cost_card():
    """A card with no cost requirements is always affordable."""
    tokens  = main.empty_gems()
    bonuses = main.empty_gems()
    assert main.can_afford({}, tokens, bonuses)


def test_cannot_afford_gold_only_covers_part():
    """One gold cannot cover a 3-gem deficit."""
    tokens  = {**main.empty_gems(), "gold": 1}
    cost    = {"red": 3}
    bonuses = main.empty_gems()
    assert not main.can_afford(cost, tokens, bonuses)


# ─── Blind deck-reserve hidden info (_redact_blind_reserves) ────────────────────

def _blind_card():
    return {"id": "L2-r3", "cost": {"red": 3}, "points": 1, "bonus": "blue", "level": 2,
            "from_deck": True}

def _faceup_card():
    return {"id": "L1-w1", "cost": {"white": 1}, "points": 0, "bonus": "green", "level": 1}


def test_blind_reserve_hidden_from_opponent():
    """Bob's deck-top reserve is a face-down placeholder in Alice's view, never its identity."""
    g = make_game_state()
    g["players"]["bob"]["reserved"] = [_blind_card()]
    red = main._redact_blind_reserves(g, viewer_pid="alice")
    card = red["players"]["bob"]["reserved"][0]
    assert card.get("hidden") is True
    assert card.get("level") == 2          # the level (which deck) is public
    assert "cost" not in card and card.get("id") != "L2-r3"   # identity is gone


def test_blind_reserve_visible_to_owner():
    """The owner always sees their own reserved card in full."""
    g = make_game_state()
    g["players"]["bob"]["reserved"] = [_blind_card()]
    red = main._redact_blind_reserves(g, viewer_pid="bob")
    assert red["players"]["bob"]["reserved"][0]["id"] == "L2-r3"


def test_faceup_reserve_visible_to_all():
    """A face-up board reserve (no from_deck) is public — never redacted."""
    g = make_game_state()
    g["players"]["bob"]["reserved"] = [_faceup_card()]
    red = main._redact_blind_reserves(g, viewer_pid="alice")
    assert red["players"]["bob"]["reserved"][0]["id"] == "L1-w1"
    assert red is g                        # nothing to hide → no copy


def test_blind_reserve_revealed_at_game_over():
    """Once the game is over everything is revealed (review screen)."""
    g = make_game_state()
    g["phase"] = "over"
    g["players"]["bob"]["reserved"] = [_blind_card()]
    red = main._redact_blind_reserves(g, viewer_pid="alice")
    assert red["players"]["bob"]["reserved"][0]["id"] == "L2-r3"


def test_no_viewer_means_full_view():
    """viewer_pid=None (internal/full) is unredacted."""
    g = make_game_state()
    g["players"]["bob"]["reserved"] = [_blind_card()]
    assert main._redact_blind_reserves(g, viewer_pid=None) is g


def test_blind_reserve_move_log_stripped_for_opponent():
    """A blind-reserve log entry hides the card from the opponent but keeps it for the owner."""
    g = make_game_state()
    g["moves"] = [{"pid": "bob", "type": "reserve", "from_deck": True, "card": _blind_card()}]
    alice_view = main._redact_blind_reserves(g, viewer_pid="alice")
    assert alice_view["moves"][0]["card"] is None
    bob_view = main._redact_blind_reserves(g, viewer_pid="bob")
    assert bob_view["moves"][0]["card"]["id"] == "L2-r3"


def test_redaction_does_not_mutate_original():
    """Redaction copies — the canonical game keeps the true reserved card."""
    g = make_game_state()
    g["players"]["bob"]["reserved"] = [_blind_card()]
    main._redact_blind_reserves(g, viewer_pid="alice")
    assert g["players"]["bob"]["reserved"][0]["id"] == "L2-r3"


def test_blind_reserve_move_log_id_stripped_for_opponent():
    """Id-only log: a blind-reserve's card_id (which would reveal identity via the static
    catalog) is hidden from the opponent but kept for the owner."""
    g = make_game_state()
    g["moves"] = [{"pid": "bob", "type": "reserve", "from_deck": True, "card_id": "L2-r3"}]
    alice_view = main._redact_blind_reserves(g, viewer_pid="alice")
    assert alice_view["moves"][0]["card_id"] is None
    bob_view = main._redact_blind_reserves(g, viewer_pid="bob")
    assert bob_view["moves"][0]["card_id"] == "L2-r3"


def test_card_catalog_resolves_every_card():
    """The static catalog covers every deck card and round-trips id -> definition, so the
    id-only move log can always be resolved offline."""
    cat = main.card_catalog()
    deck = main.build_deck()
    assert len(cat) == sum(len(deck[lk]) for lk in ("L1", "L2", "L3"))
    for lk in ("L1", "L2", "L3"):
        for c in deck[lk]:
            entry = cat[c["id"]]
            assert (entry["points"], entry["bonus"], entry["cost"], entry["level"]) \
                == (c["points"], c["bonus"], c["cost"], c["level"])


# ─── 21-point (Long) mode ───────────────────────────────────────────────────────

def _pts_card(n):
    return {"id": "pc", "level": 1, "points": n, "bonus": "white", "cost": {}}


def test_win_points_default_15():
    g = make_game_state()                         # no win_points key -> Classic 15
    assert main._win_points(g) == 15
    g["players"]["alice"]["purchased"] = [_pts_card(15)]
    assert main._check_winner(g) == "alice"
    g["players"]["alice"]["purchased"] = [_pts_card(14)]
    assert main._check_winner(g) is None


def test_win_points_21_production():
    g = make_game_state("p1", "p2")
    g["win_points"] = 21
    # 18 points must NOT trigger the final round at 21
    g["players"]["p1"]["purchased"] = [_pts_card(18)]
    g["turn"] = "p1"
    main._finish_turn(g, "p1")
    assert "final_round_trigger" not in g
    # 21 points triggers
    g["players"]["p1"]["purchased"] = [_pts_card(21)]
    g.pop("final_round_trigger", None)
    g["turn"] = "p1"
    main._finish_turn(g, "p1")
    assert g.get("final_round_trigger") == "p1"
    # _check_winner honors 21: 16-20 is not a win
    g2 = make_game_state()
    g2["win_points"] = 21
    g2["players"]["alice"]["purchased"] = [_pts_card(16)]
    assert main._check_winner(g2) is None
    g2["players"]["alice"]["purchased"] = [_pts_card(21)]
    assert main._check_winner(g2) == "alice"


# ─── Multiplayer (2-4 players) ──────────────────────────────────────────────────

def make_nplayer_state(pids):
    """Build a playable N-player game dict (N in 2..4), bank/nobles scaled."""
    decks = main.build_deck()
    board = main._deal_board(decks)
    nobles_pool = list(main.ALL_NOBLES)
    random.shuffle(nobles_pool)

    def player_state():
        return {"tokens": main.empty_gems(), "purchased": [], "reserved": [], "nobles": []}

    return {
        "bank": main._bank_for(len(pids)),
        "decks": decks, "board": board,
        "nobles": nobles_pool[:len(pids) + 1],
        "players": {p: player_state() for p in pids},
        "order": list(pids), "turn": pids[0],
        "phase": "playing", "winner": None, "win_points": 15,
    }


def _pts_card(pts):
    return {"id": f"x{pts}", "points": pts, "bonus": "white", "cost": {}, "level": 1}


def test_bank_for_scales_by_player_count():
    for n, per in [(2, 4), (3, 5), (4, 7)]:
        bank = main._bank_for(n)
        assert all(bank[c] == per for c in main.GEM_COLORS)
        assert bank["gold"] == 5


def test_nobles_scale_players_plus_one():
    for pids in (["a", "b"], ["a", "b", "c"], ["a", "b", "c", "d"]):
        g = make_nplayer_state(pids)
        assert len(g["nobles"]) == len(pids) + 1


def test_advance_turn_cycles_all_players():
    g = make_nplayer_state(["a", "b", "c", "d"])
    seen = []
    for _ in range(4):
        seen.append(g["turn"])
        g["turn"] = main._advance_turn(g)
    assert seen == ["a", "b", "c", "d"]
    assert g["turn"] == "a"  # wraps back to the first seat


def test_single_winner_among_four():
    g = make_nplayer_state(["a", "b", "c", "d"])
    g["players"]["a"]["purchased"] = [_pts_card(3)]
    g["players"]["b"]["purchased"] = [_pts_card(5)]
    g["players"]["c"]["purchased"] = [_pts_card(15)]
    g["players"]["d"]["purchased"] = [_pts_card(2)]
    main._resolve_winner(g)
    assert g["phase"] == "over"
    assert g["winner"] == "c"   # a single winner, not a list


def test_final_round_completes_around_all_seats():
    g = make_nplayer_state(["a", "b", "c", "d"])
    g["players"]["a"]["purchased"] = [_pts_card(15)]   # 'a' hits the threshold on their turn
    main._finish_turn(g, "a")
    assert g["phase"] == "playing" and g.get("final_round_trigger") == "a"
    for pid in ["b", "c"]:
        main._finish_turn(g, pid)
        assert g["phase"] == "playing"   # still mid final-round
    main._finish_turn(g, "d")            # round returns to 'a' -> resolved
    assert g["phase"] == "over"
    assert g["winner"] == "a"
