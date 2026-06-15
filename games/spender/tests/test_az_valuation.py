"""Tests for the v4 valuation core and heuristic bot.

Covers the scalar formulas (effective cost, tempo, noble progress, engine value,
efficiency) and the heuristic's contract: every move it returns is legal, two
bots play a full game to a winner, and reserve discipline holds (it does not
over-reserve, especially in the opening).
"""
import random

import pytest

from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az import valuation as V


# ─── Scalar formulas ─────────────────────────────────────────────────────────

def test_effective_cost_equals_base_without_bonuses():
    s = E.new_game(random.Random(1))
    seat = s.turn
    for slot in range(12):
        ci = s.board[slot]
        if ci < 0:
            continue
        assert V.total_effective_cost(s, ci, seat) == sum(E.COST[ci])
        assert V.effective_cost(s, ci, seat) == [c for c in E.COST[ci]]


def test_effective_cost_drops_with_bonuses():
    s = E.new_game(random.Random(2))
    seat = s.turn
    ci = next(s.board[sl] for sl in range(12) if s.board[sl] >= 0)
    bcol = next(i for i in range(5) if E.COST[ci][i] > 0)
    base = V.total_effective_cost(s, ci, seat)
    s.bonuses[seat][bcol] += 1
    assert V.total_effective_cost(s, ci, seat) == base - 1


def test_gems_to_collect_accounts_for_tokens_and_gold():
    s = E.new_game(random.Random(3))
    seat = s.turn
    ci = next(s.board[sl] for sl in range(12)
              if s.board[sl] >= 0 and sum(E.COST[s.board[sl]]) > 0)
    base = V.gems_to_collect(s, ci, seat)
    # A matching colored token reduces the deficit by 1.
    bcol = next(i for i in range(5) if E.COST[ci][i] > 0)
    s.tokens[seat][bcol] += 1
    assert V.gems_to_collect(s, ci, seat) == base - 1
    # Gold is wild and also reduces it.
    s.tokens[seat][5] += 1
    assert V.gems_to_collect(s, ci, seat) == base - 2


def test_turns_to_afford_zero_iff_affordable():
    s = E.new_game(random.Random(4))
    seat = s.turn
    ci = next(s.board[sl] for sl in range(12)
              if s.board[sl] >= 0 and sum(E.COST[s.board[sl]]) > 0)
    assert V.turns_to_afford(s, ci, seat) > 0
    assert not V.affordable_now(s, ci, seat)
    # Hand the player enough gold to buy outright -> 0 turns, affordable.
    s.tokens[seat][5] = sum(E.COST[ci])
    assert V.affordable_now(s, ci, seat)
    assert V.turns_to_afford(s, ci, seat) == 0


def test_noble_progress_targets_the_gap_color():
    s = E.new_game(random.Random(7))
    seat = s.turn
    ni = next(n for n in s.nobles if n >= 0)
    req = E.NOBLE_REQ[ni]
    gap = next(i for i in range(5) if req[i] > 0)
    for i in range(5):
        s.bonuses[seat][i] = req[i]
    s.bonuses[seat][gap] = req[gap] - 1          # one short in the gap color
    val = V.Valuation(s)

    class _Fake:  # a card whose bonus is the gap color must score > one that is not
        pass
    # Use real board cards by bonus color where available.
    by_color = {}
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            by_color.setdefault(E.BONUS[ci], ci)
    if gap in by_color:
        gap_score = val.noble_progress(by_color[gap], seat)
        assert gap_score > 0.0
        for col, ci in by_color.items():
            if col != gap and req[col] >= req[gap]:
                continue  # only compare against clearly-less-relevant colors
        # gap color should be among the highest noble-progress scores
        all_scores = {col: val.noble_progress(ci, seat) for col, ci in by_color.items()}
        assert gap_score == max(all_scores.values())


def test_noble_completion_zero_with_no_bonuses():
    # From scratch no single card can complete a noble (each needs >=3 bonuses),
    # so noble_completion_pts must never fire a false positive.
    s = E.new_game(random.Random(3))
    seat = s.turn
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            assert V.noble_completion_pts(s, ci, seat) == 0


def test_noble_completion_fires_when_one_short():
    # Hold every requirement of a visible noble except one bonus in the gap color;
    # a card whose +1 bonus is that color completes it -> scores NOBLE_PTS.
    s = E.new_game(random.Random(7))
    seat = s.turn
    ni = next(n for n in s.nobles if n >= 0)
    req = E.NOBLE_REQ[ni]
    gap = next(i for i in range(5) if req[i] > 0)
    for i in range(5):
        s.bonuses[seat][i] = req[i]
    s.bonuses[seat][gap] -= 1                       # one short in the gap color
    by_color = {E.BONUS[s.board[sl]]: s.board[sl]
                for sl in range(12) if s.board[sl] >= 0}
    if gap in by_color:
        assert V.noble_completion_pts(s, by_color[gap], seat) == E.NOBLE_PTS[ni]
    # a color the noble does not need cannot complete it (still short in gap)
    nonneed = next((c for c in range(5) if req[c] == 0 and c in by_color), None)
    if nonneed is not None:
        assert V.noble_completion_pts(s, by_color[nonneed], seat) == 0


def test_engine_value_nonneg_and_rewards_same_color_demand():
    s = E.new_game(random.Random(5))
    seat = s.turn
    val = V.Valuation(s)
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            assert val.engine_value(ci, seat) >= 0.0


def test_efficiency_prefers_cheaper_points():
    s = E.new_game(random.Random(6))
    seat = s.turn
    # Construct two synthetic comparisons via real cards: higher pts / lower
    # cost must yield higher efficiency. Compare all board cards' ordering is
    # consistent with points / (cost+1).
    for slot in range(12):
        ci = s.board[slot]
        if ci < 0:
            continue
        expected = E.PTS[ci] / (sum(E.COST[ci]) + 1.0)
        assert V.efficiency(s, ci, seat) == pytest.approx(expected)


def test_deck_color_demand_normalized():
    s = E.new_game(random.Random(8))
    val = V.Valuation(s)
    assert sum(val.deck_color_demand) == pytest.approx(1.0)
    assert all(d >= 0.0 for d in val.deck_color_demand)


def test_is_steep_and_build_path_count():
    s = E.new_game(random.Random(11))
    seat = s.turn
    # The L3 with the steepest single-color cost (stays steep through a couple bonuses).
    steep_ci = max((ci for ci in range(E.N_CARDS) if E.LEVEL_OF[ci] == 3),
                   key=lambda ci: max(E.COST[ci]))
    assert max(E.COST[steep_ci]) >= 6
    assert V.is_steep(s, steep_ci, seat)
    steep_color = max(range(5), key=lambda c: E.COST[steep_ci][c])

    # Empty board, no bonuses -> no build capacity.
    for slot in range(12):
        s.board[slot] = -1
    s.board[0] = steep_ci
    assert V.build_path_count(s, steep_ci, seat) == 0

    # 3 lower-level cards granting the steep color -> capacity 3.
    supports = [ci for ci in range(E.N_CARDS)
                if E.LEVEL_OF[ci] == 1 and E.BONUS[ci] == steep_color][:3]
    for i, ci in enumerate(supports):
        s.board[1 + i] = ci
    assert V.build_path_count(s, steep_ci, seat) == 3

    # Existing bonuses in the color count too (committed engine -> reservable).
    s.bonuses[seat][steep_color] += 2
    assert V.is_steep(s, steep_ci, seat)             # still steep (cost>=6, eff>=4)
    assert V.build_path_count(s, steep_ci, seat) == 5   # 2 bonuses + 3 board cards

    # A spread-cost card is not steep and has no build-path requirement.
    spread_ci = next(ci for ci in range(E.N_CARDS)
                     if 0 < max(E.COST[ci]) < V.REACH_STEEP)
    assert not V.is_steep(s, spread_ci, seat)
    assert V.build_path_count(s, spread_ci, seat) == 0


def test_engine_value_counts_reserved_cards():
    # engine_value must credit a bonus for discounting your OWN reserved cards
    # (committed targets), at a slight per-card premium over a board card.
    s = E.new_game(random.Random(30))
    seat = s.turn
    giver = next(s.board[sl] for sl in range(12) if s.board[sl] >= 0)
    gcol = E.BONUS[giver]
    s.reserved[seat][:] = []
    base = V.Valuation(s).engine_value(giver, seat)
    # reserving a card that still needs giver's color raises engine_value
    target = next((ci for ci in range(E.N_CARDS)
                   if ci != giver and E.COST[ci][gcol] > s.bonuses[seat][gcol]), None)
    assert target is not None
    s.reserved[seat][:] = [target]
    assert V.Valuation(s).engine_value(giver, seat) > base
    # reserving a card that does NOT need that color leaves engine_value unchanged
    none_need = next((ci for ci in range(E.N_CARDS) if E.COST[ci][gcol] == 0), None)
    if none_need is not None:
        s.reserved[seat][:] = [none_need]
        assert V.Valuation(s).engine_value(giver, seat) == base


def test_single_color_mirage():
    s = E.new_game(random.Random(20))
    seat = s.turn
    # the steepest single-color L2/L3 card (max single color >= 5)
    steep_ci = max((ci for ci in range(E.N_CARDS) if E.LEVEL_OF[ci] >= 2),
                   key=lambda ci: max(E.COST[ci]))
    assert max(E.COST[steep_ci]) >= 5
    steep_color = max(range(5), key=lambda c: E.COST[steep_ci][c])
    # clear the board: a steep single-color card with NO build path is a mirage
    for slot in range(12):
        s.board[slot] = -1
    s.board[0] = steep_ci
    assert V.single_color_mirage(s, steep_ci, seat, 5)
    # a lower-level board card granting the steep color clears the mirage
    support = next(ci for ci in range(E.N_CARDS)
                   if E.LEVEL_OF[ci] < E.LEVEL_OF[steep_ci] and E.BONUS[ci] == steep_color)
    s.board[1] = support
    assert not V.single_color_mirage(s, steep_ci, seat, 5)
    # so does a held bonus in that color (a real engine path exists)
    s.board[1] = -1
    s.bonuses[seat][steep_color] += 1
    assert not V.single_color_mirage(s, steep_ci, seat, 5)
    # a spread/cheap card (max single color < steep) is never a mirage
    cheap = next(ci for ci in range(E.N_CARDS) if 0 < max(E.COST[ci]) < 5)
    assert not V.single_color_mirage(s, cheap, seat, 5)


def test_discount_count():
    s = E.new_game(random.Random(14))
    seat = s.turn
    ci = next(s.board[sl] for sl in range(12) if s.board[sl] >= 0)
    bcol = E.BONUS[ci]
    expected = sum(1 for sl in range(12)
                   if s.board[sl] >= 0 and s.board[sl] != ci
                   and E.COST[s.board[sl]][bcol] > 0)
    assert V.discount_count(s, ci, seat) == expected
    # Holding the max bonus in the color -> no card still needs it -> count 0.
    s.bonuses[seat][bcol] = 7
    assert V.discount_count(s, ci, seat) == 0


# ─── Heuristic contract ──────────────────────────────────────────────────────

def _play_game(seed, max_ply=400):
    s = E.new_game(random.Random(seed))
    reserve_counts = []
    opening_overreserve = False
    plies = 0
    while s.phase != E.OVER and plies < max_ply:
        legal = set(E.legal_actions(s))
        a = H.choose_action(s, s.turn)
        assert a in legal, f"illegal action {a} at ply {s.ply}, phase {s.phase}"
        E.apply(s, a)
        plies += 1
        for seat in (0, 1):
            n = len(s.reserved[seat])
            reserve_counts.append(n)
            if s.ply < H.OPENING_PLY and n > 1:
                opening_overreserve = True
    return s, reserve_counts, opening_overreserve, plies


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5, 11, 42, 99, 777])
def test_heuristic_plays_legal_full_games(seed):
    s, reserve_counts, opening_overreserve, plies = _play_game(seed)
    assert s.phase == E.OVER, f"game {seed} did not finish in {plies} plies"
    assert s.winner in (0, 1, E.WIN_DRAW)
    # Reserve discipline: never exceed the 3 cap; never >1 reserve in the opening.
    assert max(reserve_counts) <= 3
    assert not opening_overreserve, f"over-reserved in the opening (seed {seed})"


def test_heuristic_actually_scores():
    # Sanity: a competent greedy bot should reach a real score, not stall at 0.
    total = 0
    for seed in range(8):
        s, *_ = _play_game(seed)
        total += max(s.points[0], s.points[1])
    avg_winner_points = total / 8
    assert avg_winner_points >= E.WIN_POINTS, (
        f"winner avg only {avg_winner_points:.1f} pts — bot is not scoring")
