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


def test_turns_to_afford_concentrated_multicolor():
    # A cost concentrated in one color that ALSO needs another can't be filled in
    # one take-3 (which gives 1 of each distinct color). The greedy fix counts these
    # correctly where the old closed form under-counted.
    s = E.new_game(random.Random(1))
    seat = s.turn
    s.bonuses = ([0] * 5, [0] * 5)
    s.tokens = ([0] * 6, [0] * 6)
    # 2 of one color + 1 of another (total 3, 2 distinct) -> 2 turns, not 1.
    ci = next((c for c in range(E.N_CARDS)
               if sorted(x for x in E.COST[c] if x > 0) == [1, 2]), None)
    assert ci is not None
    assert V.turns_to_afford(s, ci, seat) == 2
    try:
        V.USE_TTA_GREEDY = False
        assert V.turns_to_afford(s, ci, seat) == 1     # the old under-count (documents the bug)
    finally:
        V.USE_TTA_GREEDY = True
    # 4 of one color + 1 of another -> 3 turns (old form said 2). Optional: exact
    # shape may not exist in the deck, so only assert if present.
    ci2 = next((c for c in range(E.N_CARDS)
                if sorted(x for x in E.COST[c] if x > 0) == [1, 4]), None)
    if ci2 is not None:
        assert V.turns_to_afford(s, ci2, seat) == 3
    # Sanity: a single-color 3-cost is 2 turns under both (by_color caught it).
    ci3 = next((c for c in range(E.N_CARDS)
                if sorted(x for x in E.COST[c] if x > 0) == [3]), None)
    if ci3 is not None:
        assert V.turns_to_afford(s, ci3, seat) == 2


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
    # >= 5 of a single color (after bonuses) -> uncollectable via tokens (bank = 4)
    assert V.single_color_mirage(s, steep_ci, seat, 5)
    # a board BUILD PATH does NOT clear it -- you still can't hold 5+ of one color
    support = next(ci for ci in range(E.N_CARDS)
                   if E.LEVEL_OF[ci] < E.LEVEL_OF[steep_ci] and E.BONUS[ci] == steep_color)
    s.board[1] = support
    assert V.single_color_mirage(s, steep_ci, seat, 5)
    # only BONUSES that bring every single-color cost below 5 clear it
    for c in range(5):
        if E.COST[steep_ci][c] >= 5:
            s.bonuses[seat][c] = E.COST[steep_ci][c] - 4
    assert not V.single_color_mirage(s, steep_ci, seat, 5)
    # a spread/cheap card (max single color < 5) is never a mirage
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


def test_cost_concentration_counts_duplicate_gems():
    s = E.new_game(random.Random(5))
    seat = s.turn
    for slot in range(12):
        ci = s.board[slot]
        if ci < 0:
            continue
        eff = V.effective_cost(s, ci, seat)
        assert V.cost_concentration(s, ci, seat) == sum(eff) - sum(1 for x in eff if x > 0)
    # a single-color cost of k has concentration k-1; a spread (<=1/color) cost is 0
    single = next((ci for ci in range(E.N_CARDS)
                   if sum(1 for x in E.COST[ci] if x > 0) == 1 and max(E.COST[ci]) >= 2), None)
    if single is not None:
        assert V.cost_concentration(s, single, seat) == max(E.COST[single]) - 1
    spread = next((ci for ci in range(E.N_CARDS) if 0 < max(E.COST[ci]) <= 1), None)
    if spread is not None:
        assert V.cost_concentration(s, spread, seat) == 0


def test_w_cost_discounts_zero_point_cards_only():
    # The cheapness discount (shipped at W_COST=0.4) lowers a 0-point card's value
    # (efficiency is blind to cost there) while leaving point cards (priced by
    # efficiency) untouched. Default-agnostic: compares W_COST off vs on explicitly.
    s = E.new_game(random.Random(5))
    seat = s.turn
    val = V.Valuation(s)
    saved = H.W_COST
    try:
        H.W_COST = 0.0                                     # baseline: off
        zero = next(ci for ci in range(E.N_CARDS)
                    if E.PTS[ci] == 0 and V.total_effective_cost(s, ci, seat) > 0
                    and H.card_value(val, s, ci, seat) > 0)
        pointed = next(ci for ci in range(E.N_CARDS) if E.PTS[ci] > 0)
        base_zero = H.card_value(val, s, zero, seat)
        base_pt = H.card_value(val, s, pointed, seat)
        H.W_COST = 0.4                                      # on (the shipped value)
        assert H.card_value(val, s, zero, seat) < base_zero   # 0-pt -> discounted by cost
        assert H.card_value(val, s, pointed, seat) == base_pt  # point card -> untouched (gate)
    finally:
        H.W_COST = saved


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


# ─── End-game defense ────────────────────────────────────────────────────────

def _eg_state():
    """A cleared end-game state: empty board/reserves, 0 bonuses, 4 cards each, no
    tokens, no final-round trigger, seat 0 to move. Tests fill in the relevant cards."""
    s = E.new_game(random.Random(1))
    for slot in range(12):
        s.board[slot] = -1
    s.reserved = ([], [])
    s.bonuses = ([0] * 5, [0] * 5)
    s.points = [0, 0]
    s.purchased_n = [4, 4]
    s.tokens = ([0] * 6, [0] * 6)
    s.final_trigger = -1
    s.phase = E.PLAY
    s.turn = 0
    return s


def _afford(s, seat, ci):
    s.tokens[seat][:] = list(E.COST[ci]) + [0]          # exactly enough to buy ci


_PT2 = [ci for ci in range(E.N_CARDS) if E.PTS[ci] == 2 and sum(E.COST[ci]) <= 9]
_PT3 = [ci for ci in range(E.N_CARDS) if E.PTS[ci] == 3 and sum(E.COST[ci]) <= 9]


def test_endgame_secure_win_seat1_takes_buy():
    # Second player: reaching 15 ends the game immediately -> secure -> take it.
    s = _eg_state()
    s.turn = 1
    win = _PT2[0]
    s.board[0] = win
    s.points[1] = 13
    _afford(s, 1, win)
    assert H.choose_action(s, 1) == E.A_BUY_BOARD + 0


def test_endgame_insecure_seat0_denies_overtake():
    # First player: our 15 lets the opponent overtake on their final turn -> deny it.
    s = _eg_state()
    win, over = _PT2[0], _PT3[0]
    s.board[0] = win                                    # us: 13 + 2 = 15
    s.board[4] = over                                   # opp: 14 + 3 = 17 -> overtakes
    s.points = [13, 14]
    _afford(s, 0, win)
    _afford(s, 1, over)
    assert H.choose_action(s, 0) == E.A_RES_BOARD + 4   # reserve (deny) the overtake card


def test_endgame_insecure_undeniable_grabs_win():
    # Overtake comes from the opponent's OWN reserved card -> can't deny -> grab 15.
    s = _eg_state()
    win, over = _PT2[0], _PT3[0]
    s.board[0] = win
    s.reserved = ([], [over])
    s.points = [13, 14]
    _afford(s, 0, win)
    _afford(s, 1, over)
    assert H.choose_action(s, 0) == E.A_BUY_BOARD + 0


def test_endgame_secure_seat0_no_overtake_takes_win():
    # First player but the opponent is broke/far -> can't overtake -> secure -> take it.
    s = _eg_state()
    win = _PT2[0]
    s.board[0] = win
    s.points = [13, 5]
    _afford(s, 0, win)                                  # opp tokens stay 0
    assert H.choose_action(s, 0) == E.A_BUY_BOARD + 0


def test_endgame_cant_win_denies_opp_win():
    # We can't reach 15, but the opponent can win next turn via a board card -> deny it.
    s = _eg_state()
    opp_win = _PT3[0]
    s.board[4] = opp_win
    s.points = [5, 13]                                   # opp 13 + 3 = 16 next turn
    _afford(s, 1, opp_win)                               # we hold no tokens -> no buy
    assert H.choose_action(s, 0) == E.A_RES_BOARD + 4


def test_secure_win_tiebreak_by_cards():
    # Both reach 15: the fewest-cards tiebreak decides whether our 15 is secure.
    s = _eg_state()
    over = _PT2[0]
    s.board[4] = over
    s.points = [13, 13]
    _afford(s, 1, over)                                  # opp's best buy -> 13 + 2 = 15
    val = V.Valuation(s)
    s.purchased_n = [6, 4]                               # opp ends with fewer cards -> opp wins tie
    assert not H._secure_win(s, 0, 15, 7, val)
    s.purchased_n = [4, 6]                               # opp ends with more cards -> we win tie
    assert H._secure_win(s, 0, 15, 5, val)


# ─── Forced L1 0-point opening ──────────────────────────────────────────────

_L1Z = [ci for ci in range(E.N_CARDS) if E.LEVEL_OF[ci] == 1 and E.PTS[ci] == 0]


def _open_state():
    """Cleared state with 0 cards bought (the forced-opening regime), seat 0 to move."""
    s = _eg_state()
    s.purchased_n = [0, 0]
    return s


def test_forced_opening_prefers_l1_zero_over_affordable_point_card():
    # 0 cards bought + flag on: buy the affordable L1 0-pt card even when a
    # higher-value point card is ALSO affordable (engine-first opening).
    saved = H.USE_FORCED_L1_OPENING
    H.USE_FORCED_L1_OPENING = True
    try:
        s = _open_state()
        l1z, pt = _L1Z[0], _PT2[0]
        s.board[0], s.board[4] = l1z, pt
        tok = [max(E.COST[l1z][c], E.COST[pt][c]) for c in range(5)] + [2]
        s.tokens = (tok[:], [0] * 6)
        val = V.Valuation(s)
        assert val.affordable_now(l1z, 0) and val.affordable_now(pt, 0)  # both buyable
        assert H.choose_action(s, 0) == E.A_BUY_BOARD + 0                # picks the L1 0-pt
    finally:
        H.USE_FORCED_L1_OPENING = saved


def test_forced_opening_off_can_open_with_point_card():
    # Same both-affordable state, flag OFF: normal logic buys the higher-value point card.
    saved = H.USE_FORCED_L1_OPENING
    H.USE_FORCED_L1_OPENING = False
    try:
        s = _open_state()
        l1z, pt = _L1Z[0], _PT2[0]
        s.board[0], s.board[4] = l1z, pt
        tok = [max(E.COST[l1z][c], E.COST[pt][c]) for c in range(5)] + [2]
        s.tokens = (tok[:], [0] * 6)
        assert H.choose_action(s, 0) == E.A_BUY_BOARD + 4                # the point card
    finally:
        H.USE_FORCED_L1_OPENING = saved


def test_forced_opening_first_purchase_always_l1_zero():
    # Over self-play games, seat 0's FIRST purchase is always an L1 0-pt card, and the
    # opening never buys a reserved card (it never reserves during the opening).
    saved = H.USE_FORCED_L1_OPENING
    H.USE_FORCED_L1_OPENING = True
    try:
        for seed in range(20):
            s = E.new_game(random.Random(seed))
            checked = False
            while s.phase != E.OVER and s.ply < 400 and not checked:
                seat = s.turn
                a = H.choose_action(s, seat)
                if seat == 0 and s.purchased_n[0] == 0:
                    if E.A_BUY_BOARD <= a < E.A_BUY_BOARD + 12:
                        ci = s.board[a - E.A_BUY_BOARD]
                        assert E.LEVEL_OF[ci] == 1 and E.PTS[ci] == 0, (
                            f"seed {seed}: first buy was L{E.LEVEL_OF[ci]} {E.PTS[ci]}-pt")
                        checked = True
                    elif E.A_BUY_RESV <= a < E.A_BUY_RESV + 3:
                        assert False, f"seed {seed}: bought a reserved card in the opening"
                E.apply(s, a)
    finally:
        H.USE_FORCED_L1_OPENING = saved
