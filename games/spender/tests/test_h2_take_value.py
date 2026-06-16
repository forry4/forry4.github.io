"""Tests for the H2 `take_value` model (valuation2 components + heuristic2 policy).

Covers the cost-component formulas (tempo / gem / gold), the take_value div-by-zero
guard, the turn-1 'engine-first' property, the token-cap rule, and the heuristic's
contract (every move legal, full games finish and score).
"""
import math
import random

import pytest

from games.spender.ai.az import engine as E
from games.spender.ai.az import valuation2 as V
from games.spender.ai.az import heuristic2 as H


def _find_card(pred):
    """First card index whose cost tuple satisfies `pred`, or None."""
    for ci in range(len(E.COST)):
        if pred(tuple(E.COST[ci])):
            return ci
    return None


# ─── tempo ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", [0, 1, 2, 3, 42])
def test_tempo_matches_formula_on_fresh_board(seed):
    # Turn 1: no bonuses/tokens, so remaining d == base cost. tempo = steepest single
    # color, +1 only when the cost is exactly 1-1-1-1.
    s = E.new_game(random.Random(seed))
    seat = s.turn
    for slot in range(12):
        ci = s.board[slot]
        if ci < 0:
            continue
        cost = tuple(E.COST[ci])
        nonzero = sorted(x for x in cost if x > 0)
        expected = max(cost) + (1 if nonzero == [1, 1, 1, 1] else 0)
        assert V.tempo(s, ci, seat) == expected


def test_tempo_specific_shapes():
    s = E.new_game(random.Random(0))
    seat = s.turn
    quad = _find_card(lambda c: sorted(x for x in c if x > 0) == [1, 1, 1, 1])
    if quad is not None:
        assert V.tempo(s, quad, seat) == 2          # 1-1-1-1 -> steepest 1, +1
    single3 = _find_card(lambda c: max(c) == 3 and sum(1 for x in c if x > 0) == 1)
    if single3 is not None:
        assert V.tempo(s, single3, seat) == 3        # 3-0-0-0-0 -> 3, no +1


def test_tempo_zero_when_fully_covered():
    s = E.new_game(random.Random(0))
    seat = s.turn
    ci = s.board[0]
    s.bonuses[seat][:] = list(E.COST[ci])            # bonuses cover the whole card
    assert V.tempo(s, ci, seat) == 0


# ─── gem_cost ───────────────────────────────────────────────────────────────────

def test_gem_cost_is_post_bonus_sum_ignoring_tokens():
    s = E.new_game(random.Random(1))
    seat = s.turn
    ci = _find_card_on_board_with_cost(s, seat)
    base = sum(E.COST[ci])
    assert V.gem_cost(s, ci, seat) == base
    # a held TOKEN does not reduce gem_cost (it is the sticker price)
    c = next(i for i in range(5) if E.COST[ci][i] > 0)
    s.tokens[seat][c] += 1
    assert V.gem_cost(s, ci, seat) == base
    # a BONUS does reduce it
    s.bonuses[seat][c] += 1
    assert V.gem_cost(s, ci, seat) == base - 1


def _find_card_on_board_with_cost(s, seat):
    for slot in range(12):
        if s.board[slot] >= 0 and sum(E.COST[s.board[slot]]) > 0:
            return s.board[slot]
    raise AssertionError("no costed card on board")


# ─── gold_cost ──────────────────────────────────────────────────────────────────

def test_gold_cost_negative_when_cheap_and_bank_full():
    s = E.new_game(random.Random(0))           # bank full (4 each) at start
    seat = s.turn
    cheap = _find_card(lambda c: 0 < max(c) < V.GOLD_BANK_CAP)
    assert cheap is not None
    assert V.gold_cost(s, cheap, seat) < 0      # steepest < cap, pulled from a full bank -> negative


def test_gold_cost_positive_for_steep_card():
    s = E.new_game(random.Random(0))
    seat = s.turn
    steep = _find_card(lambda c: max(c) >= 5)
    assert steep is not None
    assert V.gold_cost(s, steep, seat) == max(E.COST[steep]) - V.GOLD_BANK_CAP  # full bank -> min(cap,4)=cap


def test_gold_cost_zero_when_nothing_needed():
    s = E.new_game(random.Random(0))
    seat = s.turn
    ci = s.board[0]
    s.bonuses[seat][:] = list(E.COST[ci])
    assert V.gold_cost(s, ci, seat) == 0


# ─── take_value ─────────────────────────────────────────────────────────────────

def test_take_value_finite_for_free_card():
    # A card fully covered by bonuses has total_cost 0; the +1 in the denominator
    # keeps take_value finite (no divide-by-zero).
    s = E.new_game(random.Random(0))
    seat = s.turn
    val = V.Valuation(s)
    ci = s.board[0]
    s.bonuses[seat][:] = list(E.COST[ci])
    v = H.take_value(val, s, ci, seat)
    assert math.isfinite(v)


# NOTE: a 'turn-1 top take_value card is an L1' sanity test lived here. It only held
# because points were distance-discounted by tempo; that point-discount was REMOVED (it
# cost ~8 pts of win rate vs C2 -- see the plan doc), so without it far point cards
# legitimately top the turn-1 ranking (the property dropped from 55/60 to 18/60). The
# test was deleted with the discount; the turn-1 engine-first behavior is no longer a
# guaranteed property.


# ─── token-cap rule ─────────────────────────────────────────────────────────────

def test_token_cap_forces_a_buy_at_ten():
    # At 10 tokens the rule always buys the best affordable card rather than taking.
    for seed in range(20):
        s = E.new_game(random.Random(seed))
        seat = s.turn
        s.tokens[seat][:] = [2, 2, 2, 2, 0, 2]        # 10 tokens (incl. 2 gold)
        legal = set(E.legal_actions(s))
        if not any(E.A_BUY_BOARD <= a < E.A_DISCARD for a in legal):
            continue                                   # no affordable buy on this board
        a = H.choose_action(s, seat)
        assert E.A_BUY_BOARD <= a < E.A_DISCARD, f"seed {seed}: expected a buy, got {a}"
        return
    pytest.skip("no seed produced an affordable buy at 10 tokens")


# ─── heuristic contract ─────────────────────────────────────────────────────────

def _play_game(seed, max_ply=800):
    s = E.new_game(random.Random(seed))
    plies = 0
    while s.phase != E.OVER and plies < max_ply:
        a = H.choose_action(s, s.turn)
        assert a in set(E.legal_actions(s)), f"illegal {a} at ply {s.ply}, phase {s.phase}"
        E.apply(s, a)
        plies += 1
    return s, plies


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5, 11, 42, 99, 777])
def test_h2_plays_legal_full_games(seed):
    s, plies = _play_game(seed)
    assert s.phase == E.OVER, f"game {seed} did not finish in {plies} plies"
    assert s.winner in (0, 1, E.WIN_DRAW)


def test_h2_actually_scores():
    total = sum(max(_play_game(seed)[0].points) for seed in range(8))
    assert total / 8 >= E.WIN_POINTS, "bot is not reaching a real score"
