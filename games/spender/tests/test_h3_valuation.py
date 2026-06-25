"""Permanent invariants for the H3 valuation model (valuation3 + heuristic3).

These encode the hand-checked sanity properties so a future model change can't silently break
them (they started as the interactive probes in az/h3_sanity.py):

  (a) reducing a card's single-color TEMPO need 2->1 raises its take value MORE than 7->6
      (the 1/(1+cost) convexity), at any gem level.
  (b) reducing total GEM cost by 1 raises take value MORE when total gem is low than when high,
      at a fixed tempo.
  (c) a steep-white card's POTENTIAL rises when cheap white-bonus cards are on the board
      (reachability), and reachability is ZERO for a card you can already afford.
  (Q1) the build-floor lifts a far card that is STEEP in the discounter's color, and leaves a
       near card unchanged.
  (d) a high-value discounter lifts the reachability of a card it (nearly) COMPLETES more than a
      card it only partially helps: a black builder helps a "1 black away" card more than a
      "1 black + 1 green away" card.

Inequalities (not magnitudes) are asserted, so the tests survive re-tuning of the weights.
"""
import random

import pytest

from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic3 as H3
from games.spender.ai.az import valuation3 as V3

WHITE, BLUE, GREEN, BLACK = 0, 1, 2, 4


def _blank_state(seat=0):
    """Fresh state with the acting seat zeroed out (no bonuses/tokens, 0 cards/points)."""
    s = E.new_game(random.Random(0))
    s.purchased_n = [0, 0]
    s.points = [0, 0]
    s.tokens = [[0] * 6, [0] * 6]
    s.bonuses = [[0] * 5, [0] * 5]
    return s


def _set_remaining(s, seat, ci, remaining):
    """Set `seat`'s bonuses so card ci's per-color remaining need == `remaining` (each <= cost)."""
    bon = [max(0, E.COST[ci][c] - remaining[c]) for c in range(5)]
    blank = [0] * 5
    s.bonuses = [bon, blank] if seat == 0 else [blank, bon]


def _val(s):
    return V3.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)


@pytest.fixture
def restore_flags():
    """Save/restore the module-level flags tests flip, so they don't leak between tests."""
    saved = (V3.USE_POTENTIAL_ENGINE, V3.POT_REACH_W, V3.BUILD_FLOOR_W)
    yield
    V3.USE_POTENTIAL_ENGINE, V3.POT_REACH_W, V3.BUILD_FLOOR_W = saved


def _steep_white_card(bonus_not_white=True):
    """The card with the steepest white cost (optionally requiring its bonus color != white, so
    varying the player's white bonus doesn't also move the card's own engine value)."""
    cands = [c for c in range(len(E.COST))
             if (not bonus_not_white or E.BONUS[c] != WHITE) and E.COST[c][WHITE] >= 7]
    assert cands, "expected a card costing >=7 white"
    return max(cands, key=lambda c: E.COST[c][WHITE])


# ─── (a) tempo convexity ─────────────────────────────────────────────────────
def test_a_tempo_convexity(restore_flags):
    s = _blank_state()
    seat = 0
    X = _steep_white_card()

    def take_need(n):
        rem = [0] * 5
        rem[WHITE] = n
        _set_remaining(s, seat, X, rem)
        return H3.take_value(_val(s), X, seat)

    assert take_need(1) - take_need(2) > take_need(6) - take_need(7)


# ─── (b) gem convexity at fixed tempo ────────────────────────────────────────
def _high_total_multicolor_card():
    """Highest-total card that also has a non-steepest color of cost >= 2 (so gem can be varied
    in that color while the steepest color holds tempo fixed)."""
    best = None
    for c in range(len(E.COST)):
        cost = E.COST[c]
        cs = max(range(5), key=lambda i: cost[i])
        others = [i for i in range(5) if i != cs and cost[i] >= 2]
        if others and (best is None or sum(cost) > sum(E.COST[best[0]])):
            best = (c, cs, max(others, key=lambda i: cost[i]))
    assert best, "expected a multi-color card with a non-steepest color of cost >= 2"
    return best


def test_b_gem_convexity(restore_flags):
    s = _blank_state()
    seat = 0
    Y, cs, other = _high_total_multicolor_card()
    ts = E.COST[Y][cs]

    def take_rem(rem):
        _set_remaining(s, seat, Y, rem)
        v = _val(s)
        assert v.tempo(Y, seat) == ts  # tempo held fixed across the comparison
        return H3.take_value(v, Y, seat)

    # low total gem: steepest at ts, `other` needs 2 -> reduce it to 1
    lo = [0] * 5
    lo[cs] = ts
    lo[other] = 2
    lo1 = lo[:]
    lo1[other] = 1
    d_lo = take_rem(lo1) - take_rem(lo)
    # high total gem: full cost -> reduce `other` by 1
    hi = list(E.COST[Y])
    hi[cs] = ts
    hi1 = hi[:]
    hi1[other] -= 1
    d_hi = take_rem(hi1) - take_rem(hi)

    assert d_lo > d_hi


# ─── (c) reachability ────────────────────────────────────────────────────────
def _cheap_white_cards():
    return sorted((c for c in range(len(E.COST)) if E.BONUS[c] == WHITE), key=lambda c: sum(E.COST[c]))


def test_c_reachability_lifts_steep_white_card(restore_flags):
    """Turning reachability on raises a steep-white card's potential when white builders exist."""
    seat = 0
    X = _steep_white_card()
    whites = _cheap_white_cards()

    def potential(reach_w, k):
        V3.POT_REACH_W = reach_w
        s = _blank_state()
        s.board = [-1] * 12
        s.board[0] = X
        for i in range(k):
            s.board[1 + i] = whites[i]
        return _val(s).potential_value(X, seat)

    # with reachability on, more white cards -> higher potential, and on > off at fixed board
    assert potential(0.2, 6) > potential(0.2, 0)
    assert potential(0.2, 6) > potential(0.0, 6)


def test_c_reachability_zero_when_affordable(restore_flags):
    """A card you can already afford gets NO reachability boost (nothing to 'reach')."""
    V3.POT_REACH_W = 0.2
    seat = 0
    s = _blank_state()
    ci = min(range(len(E.COST)), key=lambda c: sum(E.COST[c]))  # a cheap card
    tok = [0] * 6
    for c in range(5):
        tok[c] = E.COST[ci][c]                                   # hold exactly its cost -> affordable
    s.tokens = [tok, [0] * 6]
    v = _val(s)
    assert v.affordable_now(ci, seat)
    assert v._reachability(ci, seat) == 0.0


# ─── (Q1) build-floor isolates steep-in-color far cards ──────────────────────
def test_build_floor_lifts_steep_not_cheap(restore_flags):
    """The build-floor raises _delta_take for a far card STEEP in the bonus color, but leaves a
    near (cheap) card unchanged (its convexity already exceeds the floor)."""
    seat = 0
    X = _steep_white_card()

    def delta(floor_w, need):
        V3.BUILD_FLOOR_W = floor_w
        s = _blank_state()
        rem = [0] * 5
        rem[WHITE] = need
        _set_remaining(s, seat, X, rem)
        return _val(s)._delta_take(X, seat, WHITE)

    # steep far need (6 white): floor binds -> lifted above pure convexity
    assert delta(0.15, 6) > delta(0.0, 6)
    # near need (1 white): convexity dominates -> floor does not change it
    assert delta(0.15, 1) == pytest.approx(delta(0.0, 1))


# ─── (d) a discounter matters more to a card it (nearly) completes ───────────
def test_d_reachability_completion_sensitivity(restore_flags):
    """A high-value BLACK builder lifts the reachability of a 0-pt white card that is 1 BLACK away
    significantly MORE than a 0-pt white card that is 1 black + 1 green away (the latter is only
    partially helped -- it still needs green)."""
    seat = 0
    # W: a 0-pt white-bonus card costing >= 1 green and >= 1 black, so we can dial the two scenarios
    W = next((c for c in range(len(E.COST))
              if E.BONUS[c] == WHITE and E.PTS[c] == 0
              and E.COST[c][GREEN] >= 1 and E.COST[c][BLACK] >= 1), None)
    assert W is not None, "expected a 0-pt white card costing >=1 green and >=1 black"
    # D: a high-value black builder that does NOT cost green, so its builder weight is identical in
    #    both scenarios (which differ only in the green bonus)
    blacks = [c for c in range(len(E.COST)) if E.BONUS[c] == BLACK and E.COST[c][GREEN] == 0]
    assert blacks, "expected a black-bonus card with no green cost"
    D = max(blacks, key=lambda c: E.PTS[c])

    def reach(remaining):
        s = _blank_state()
        _set_remaining(s, seat, W, remaining)
        s.board = [-1] * 12
        s.board[0] = W
        s.board[1] = D                      # the only black builder on the board
        return _val(s)._reachability(W, seat)

    reach_one_black = reach([0, 0, 0, 0, 1])        # 1 black away  -> D drops both gem AND tempo
    reach_black_green = reach([0, 0, 1, 0, 1])      # 1 black + 1 green away -> D drops only a gem
    # D removes (W_TEMPO + W_GEM) of cost from the first card but only W_GEM from the second, so the
    # first's reachability is lifted ~ (W_TEMPO+W_GEM)/W_GEM as much; assert a clear margin.
    assert reach_one_black > 1.2 * reach_black_green


# ─── reachability changes BUILDERS' value, never the card's own take value ───
def test_reachability_does_not_affect_own_take(restore_flags):
    """A card's OWN reachability must not change its OWN take value -- reachability only flows into
    the take value of the cards that BUILD toward it (its discounters). Toggling POT_REACH_W must
    leave the target's own take value identical while lifting a builder's take value."""
    seat = 0
    # X: steep-white target whose BONUS is blue -> on a board with no blue-cost card, X discounts
    #    nothing, so its own engine value is constant. B: a white builder X needs, not costing blue.
    X = max((c for c in range(len(E.COST)) if E.BONUS[c] == BLUE and E.COST[c][WHITE] >= 5),
            key=lambda c: E.COST[c][WHITE])
    B = next(c for c in range(len(E.COST))
             if E.BONUS[c] == WHITE and E.COST[c][BLUE] == 0 and c != X)

    def takes(reach_w):
        V3.POT_REACH_W = reach_w
        s = _blank_state()
        s.board = [-1] * 12
        s.board[0] = X
        s.board[1] = B
        v = _val(s)
        return H3.take_value(v, X, seat), H3.take_value(v, B, seat)

    tX_off, tB_off = takes(0.0)
    tX_on, tB_on = takes(0.3)
    assert tX_off == pytest.approx(tX_on)   # the target's OWN take value is invariant to its reachability
    assert tB_on > tB_off                   # but a builder toward it becomes more valuable


# ─── a builder is worth more toward a HIGH-point target than a 0-point one ───
def test_higher_point_target_lifts_builder_more(restore_flags):
    """A white builder toward a 5pt card (7 white 3 blue) is worth significantly more than toward a
    0pt card of the SAME cost: the target's points flow into its potential and thus into the credit
    the builder earns for discounting it. Uses two synthetic same-cost cards (no real Splendor pair
    has identical cost but different points)."""
    seat = 0
    n = E.N_CARDS
    orig = (E.COST, E.PTS, E.BONUS, E.LEVEL_OF)
    try:
        # W = cheap white builder; T_hi = 5pt 7w3b; T_lo = 0pt 7w3b (same cost, different points)
        E.COST = E.COST + ((1, 1, 0, 0, 0), (7, 3, 0, 0, 0), (7, 3, 0, 0, 0))
        E.PTS = E.PTS + (0, 5, 0)
        E.BONUS = E.BONUS + (WHITE, BLACK, BLACK)
        E.LEVEL_OF = E.LEVEL_OF + (1, 3, 3)
        W, T_hi, T_lo = n, n + 1, n + 2

        def measure(target):
            s = _blank_state()
            s.board = [-1] * 12
            s.board[0] = W
            s.board[1] = target
            v = _val(s)
            return H3.take_value(v, W, seat), v._delta_take(target, seat, WHITE)

        take_hi, dt_hi = measure(T_hi)
        take_lo, dt_lo = measure(T_lo)
        # the credit the target gives the builder is far larger for the 5pt card (points -> potential)
        assert dt_hi > 3.0 * dt_lo
        # and buying the builder is meaningfully more valuable toward the 5pt target
        assert take_hi > 1.08 * take_lo
    finally:
        E.COST, E.PTS, E.BONUS, E.LEVEL_OF = orig


# ─── builders are complementary: a 2nd builder lifts the target's reach AND the 1st builder ──
def test_second_builder_lifts_reach_and_first_builder(restore_flags):
    """Adding a second white builder raises the white target's reachability, and -- with reachability
    on -- that in turn raises the FIRST white builder's engine value: the shared target became more
    reachable, so discounting it is worth more. (The builders cost non-white, so they don't discount
    each other; W1's engine value reflects only the shared target T.)"""
    V3.POT_REACH_W = 0.3
    seat = 0
    n = E.N_CARDS
    orig = (E.COST, E.PTS, E.BONUS, E.LEVEL_OF)
    try:
        # T = 5pt 7white+3blue (bonus black); W1 = 1pt white builder (cost 2 blue);
        # W2 = 0pt white builder (cost 1 blue + 1 green) -- both white sources, neither costs white
        E.COST = E.COST + ((7, 3, 0, 0, 0), (0, 2, 0, 0, 0), (0, 1, 1, 0, 0))
        E.PTS = E.PTS + (5, 1, 0)
        E.BONUS = E.BONUS + (BLACK, WHITE, WHITE)
        E.LEVEL_OF = E.LEVEL_OF + (3, 1, 1)
        T, W1, W2 = n, n + 1, n + 2

        def measure(board_cards):
            s = _blank_state()
            s.board = [-1] * 12
            for i, c in enumerate(board_cards):
                s.board[i] = c
            v = _val(s)
            return v._reachability(T, seat), v.engine_value(W1, seat)

        reach_one, eng_one = measure([T, W1])          # one white builder
        reach_two, eng_two = measure([T, W1, W2])      # add a second white builder
        assert reach_two > reach_one     # target more reachable with more white builders
        assert eng_two > eng_one         # and the first builder is worth more (shared target's reach rose)
    finally:
        E.COST, E.PTS, E.BONUS, E.LEVEL_OF = orig


# ─── (e) slot-pressure reserve finisher (policy: choose_action, not valuation) ─
def _reserve_state(white_deficit, n_tokens, *, n_reserved=0, bank_gold=5):
    """Seat-0 state: board slot 0 holds a steep-white card the seat is `white_deficit` white short of,
    with `n_tokens` non-white / non-gold tokens, `n_reserved` (unaffordable) reserved cards, and
    `bank_gold` gold in the bank. The card is the SOLE board card -> the top take_value target."""
    s = _blank_state()
    X = _steep_white_card()
    rem = [0] * 5
    rem[WHITE] = white_deficit
    _set_remaining(s, 0, X, rem)
    s.board = [-1] * 12
    s.board[0] = X
    # tokens spread over non-white colors (so they don't reduce the white deficit); no gold held
    s.tokens = [[0] * 6, [0] * 6]
    for i in range(n_tokens):
        s.tokens[0][[BLUE, GREEN, 3, BLACK][i % 4]] += 1
    # reserved slots filled with steep white cards the seat can't afford (so the bot won't just buy them)
    steep = [c for c in sorted(range(len(E.COST)), key=lambda c: -E.COST[c][WHITE]) if c != X]
    s.reserved = [steep[:n_reserved], []]
    s.bank = [4, 4, 4, 4, 4, bank_gold]
    s.turn = 0
    return s, X


def test_e_reserve_fires_8tokens_two_of_one_color():
    """At 8 tokens and exactly 2 of ONE color short of the top board card, the bot RESERVES it."""
    assert H3.USE_FINISH_RESERVE                       # the validated default
    s, _X = _reserve_state(white_deficit=2, n_tokens=8)
    assert H3.choose_action(s, 0) == E.A_RES_BOARD + 0


def test_e_reserve_fires_9tokens_one_gem():
    """At 9 tokens and 1 gem short of the top board card, the bot RESERVES it (banked gold finishes it)."""
    s, _X = _reserve_state(white_deficit=1, n_tokens=9)
    assert H3.choose_action(s, 0) == E.A_RES_BOARD + 0


def test_e_reserve_skips_without_bank_gold():
    """No gold in the bank -> reserving banks nothing, so the bot takes gems rather than reserve."""
    s, _X = _reserve_state(white_deficit=2, n_tokens=8, bank_gold=0)
    assert H3.choose_action(s, 0) != E.A_RES_BOARD + 0


def test_e_reserve_skips_when_slots_full():
    """All 3 reserve slots used -> the finisher cannot fire (reserve is illegal); the bot takes gems."""
    s, _X = _reserve_state(white_deficit=2, n_tokens=8, n_reserved=3)
    assert H3.choose_action(s, 0) != E.A_RES_BOARD + 0


# ─── (f) winning-reserve tempo gate (don't lock a "win" too far to complete soon) ─
def _winning_reserve_state(white_need, *, pts_seat=13):
    """Seat-0 state: board slot 0 is a WINNING card (seat reaches >= WIN_POINTS) that's unaffordable and
    gold-blocked, with remaining need == `white_need` white (so tempo == white_need). No nobles, gold in
    the bank, none held -- the canonical winning-reserve setup."""
    s = _blank_state()
    s.nobles = [-1, -1, -1]
    s.points = [pts_seat, 0]
    X = next(c for c in range(len(E.COST))
             if E.PTS[c] >= E.WIN_POINTS - pts_seat and E.COST[c][WHITE] >= white_need)
    rem = [0] * 5
    rem[WHITE] = white_need
    _set_remaining(s, 0, X, rem)
    s.board = [-1] * 12
    s.board[0] = X
    s.reserved = [[], []]
    s.tokens = [[0] * 6, [0] * 6]                  # no gold held
    s.bank = [white_need - 2, 4, 4, 4, 4, 3]       # short 2 white -> gold_shortfall 2 (bankable); gold avail
    s.turn = 0
    return s, X


def test_winning_reserve_tempo_gate():
    """The tempo gate blocks a FAR winning card (tempo 5) -- the SAME card IS reserved with the gate
    disabled (isolating the gate as the cause) -- while a NEAR winning card (tempo 3) is still reserved."""
    saved = H3.WIN_RESERVE_MAX_TEMPO
    try:
        s_far, _ = _winning_reserve_state(white_need=5)        # tempo 5
        ls_far = set(E.legal_actions(s_far))
        H3.WIN_RESERVE_MAX_TEMPO = 99                          # gate OFF -> far card IS a winning reserve
        assert H3._winning_reserve(s_far, 0, _val(s_far), ls_far) == E.A_RES_BOARD + 0
        H3.WIN_RESERVE_MAX_TEMPO = 4                           # gate ON (default) -> far card skipped
        assert H3._winning_reserve(s_far, 0, _val(s_far), ls_far) is None

        s_near, _ = _winning_reserve_state(white_need=3)       # tempo 3 < 4 -> still reserved
        assert H3._winning_reserve(s_near, 0, _val(s_near),
                                   set(E.legal_actions(s_near))) == E.A_RES_BOARD + 0
    finally:
        H3.WIN_RESERVE_MAX_TEMPO = saved


# ─── (g) a COMPLETED noble is credited once (completion), never double-counted in progress ──
def _noble_state(reqs):
    """Seat-0 state with synthetic nobles `reqs` and a 0-pt WHITE card affordable; bonuses white 3 /
    blue 2 / red 2, so the card's +1 white completes a [4-white] noble. Returns (val, s, X)."""
    s = _blank_state()
    s.points = [6, 6]; s.purchased_n = [5, 5]
    s.bonuses = [[3, 2, 0, 2, 0], [0] * 5]
    s.tokens = [[5, 5, 5, 5, 5, 0], [0] * 6]                 # X affordable -> tempo 0
    X = next(c for c in range(len(E.COST)) if E.BONUS[c] == WHITE and E.PTS[c] == 0)
    s.board = [-1] * 12; s.board[0] = X
    s.nobles = [0, 1, 2]
    return _val(s), s, X


def test_g_noble_completion_not_double_counted():
    """A 0-pt card that COMPLETES a noble and helps no OTHER noble scores exactly the completion VP --
    the completed noble must not ALSO appear in noble_progress (the double-count this guards against)."""
    orig = (E.NOBLE_REQ, E.NOBLE_PTS)
    try:
        # A (4 white) is completed by the white card; B (4 blue), C (4 red) are NOT the card's color.
        E.NOBLE_REQ = ((4, 0, 0, 0, 0), (0, 4, 0, 0, 0), (0, 0, 0, 4, 0))
        E.NOBLE_PTS = (3, 3, 3)
        val, s, X = _noble_state(E.NOBLE_REQ)
        assert val.noble_completion_pts(X, 0) == 3          # completes noble A
        assert val.noble_progress(X, 0) == 0.0              # ...and is NOT also scored as progress
        _take, _eng, point, _cost = H3.components(val, X, 0)
        assert point == pytest.approx(E.PTS[X] + 3)         # P == own points + completion only
    finally:
        E.NOBLE_REQ, E.NOBLE_PTS = orig


def test_g_noble_progress_still_counts_other_nobles():
    """The fix removes ONLY the double-counted completed noble: a card completing one noble while
    genuinely advancing OTHERS of its color still credits those others in noble_progress."""
    orig = (E.NOBLE_REQ, E.NOBLE_PTS)
    try:
        # A (4 white) completed; B (4 white+4 blue), C (4 white+4 red) advanced by white, not completed.
        E.NOBLE_REQ = ((4, 0, 0, 0, 0), (4, 4, 0, 0, 0), (4, 0, 0, 4, 0))
        E.NOBLE_PTS = (3, 3, 3)
        val, s, X = _noble_state(E.NOBLE_REQ)
        assert val.noble_completion_pts(X, 0) == 3
        assert val.noble_progress(X, 0) > 0.0               # B and C (uncompleted, need white) still count
    finally:
        E.NOBLE_REQ, E.NOBLE_PTS = orig


# ─── (h) noble RACE gate: marginal win-probability model (NOBLE_RACE_W) ───────────────────────
RED = 3


def _noble_card_state(noble_req, me_bon, opp_bon):
    """A 1-noble state (slot 0 = `noble_req`) with both seats' bonuses set and a 0-pt WHITE card on the
    board (slot 0). No tokens. Both seats' cards/points are 0, so estimated_turns_remaining is identical
    across opp-bonus variations -> a fair within-state comparison of the marginal gain."""
    s = _blank_state()
    s.points = [0, 0]
    s.purchased_n = [0, 0]
    s.bonuses = [list(me_bon), list(opp_bon)]
    s.tokens = [[0] * 6, [0] * 6]
    white = next(c for c in range(len(E.COST)) if E.BONUS[c] == WHITE and E.PTS[c] == 0)
    s.board = [-1] * 12
    s.board[0] = white
    s.nobles = [0, -1, -1]
    return s, white


def test_h_winprob_monotone():
    """P_win rises as your OWN deficit falls (closer) and as the OPPONENT's deficit rises (further)."""
    val = _val(_blank_state())
    eff = 10.0
    assert val._noble_winprob(2, 3, eff) > val._noble_winprob(3, 3, eff)   # closer for me -> higher
    assert val._noble_winprob(3, 4, eff) > val._noble_winprob(3, 2, eff)   # opp further -> higher
    assert val._noble_winprob(3, 3, eff) == pytest.approx(0.5 * eff / (eff + V3.NOBLE_TURN_W * 3))


def test_h_marginal_gain_peaks_at_even_race():
    """The MARGINAL win-prob gain of a card (P_win(d-1) - P_win(d)) is LARGEST for a CONTESTED (even)
    race and smaller when you're clearly BEHIND or clearly AHEAD -- the sigmoid is steepest at even."""
    val = _val(_blank_state())
    eff = 10.0
    d = 3
    def gain(d_op):
        return val._noble_winprob(d - 1, d_op, eff) - val._noble_winprob(d, d_op, eff)
    even = gain(3)        # opponent equally far
    behind = gain(0)      # opponent essentially done -> I'm losing the race
    ahead = gain(9)       # opponent hopeless -> I've all but won it
    assert even > behind
    assert even > ahead
    assert behind > 0 and ahead > 0   # still a (small) positive marginal


def test_h_marginal_off_is_opponent_blind():
    """NOBLE_RACE_W == 0 (default) keeps the CLOSENESS model, which ignores the opponent: noble_progress
    is unchanged when the opponent's bonuses change. Turning the gate ON makes it opponent-AWARE."""
    orig = (E.NOBLE_REQ, E.NOBLE_PTS, V3.NOBLE_RACE_W)
    try:
        E.NOBLE_REQ = ((3, 3, 0, 3, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0))
        E.NOBLE_PTS = (3, 3, 3)
        s_close, white = _noble_card_state((3, 3, 0, 3, 0), (1, 3, 0, 2, 0), (1, 3, 0, 2, 0))  # even
        s_ahead, _ = _noble_card_state((3, 3, 0, 3, 0), (1, 3, 0, 2, 0), (0, 0, 0, 0, 0))       # opp hopeless

        V3.NOBLE_RACE_W = 0.0   # closeness: opp-blind -> identical
        assert _val(s_close).noble_progress(white, 0) == pytest.approx(_val(s_ahead).noble_progress(white, 0))

        V3.NOBLE_RACE_W = 1.0   # marginal: opp-aware -> winning-the-race-already is worth LESS marginally
        even = _val(s_close).noble_progress(white, 0)
        ahead = _val(s_ahead).noble_progress(white, 0)
        assert even > ahead
    finally:
        E.NOBLE_REQ, E.NOBLE_PTS, V3.NOBLE_RACE_W = orig


def test_h_marginal_behind_worth_less_than_even():
    """User example 1, end to end through noble_progress: a white card toward a 3/3/3 noble is worth
    LESS (marginally) when I'm clearly behind the opponent than when the race is even."""
    orig = (E.NOBLE_REQ, E.NOBLE_PTS, V3.NOBLE_RACE_W)
    try:
        E.NOBLE_REQ = ((3, 3, 0, 3, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0))
        E.NOBLE_PTS = (3, 3, 3)
        V3.NOBLE_RACE_W = 1.0
        s_even, white = _noble_card_state((3, 3, 0, 3, 0), (1, 3, 0, 2, 0), (1, 3, 0, 2, 0))
        s_behind, _ = _noble_card_state((3, 3, 0, 3, 0), (1, 3, 0, 2, 0), (3, 3, 0, 2, 0))  # opp 2 ahead in white
        assert _val(s_behind).noble_progress(white, 0) < _val(s_even).noble_progress(white, 0)
    finally:
        E.NOBLE_REQ, E.NOBLE_PTS, V3.NOBLE_RACE_W = orig


def test_h_marginal_zero_when_no_advance_or_completes():
    """The marginal model credits ZERO when the card's color doesn't advance the noble, and ZERO for a
    card that COMPLETES it (completion is scored separately by noble_completion_pts -- no double count)."""
    orig = (E.NOBLE_REQ, E.NOBLE_PTS, V3.NOBLE_RACE_W)
    try:
        E.NOBLE_PTS = (3, 3, 3)
        V3.NOBLE_RACE_W = 1.0
        # (i) white card, noble needs NO white -> no advance -> 0
        E.NOBLE_REQ = ((0, 3, 0, 3, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0))
        s, white = _noble_card_state((0, 3, 0, 3, 0), (0, 2, 0, 2, 0), (0, 1, 0, 1, 0))
        assert _val(s).noble_progress(white, 0) == 0.0
        # (ii) white card that COMPLETES the noble (need exactly 1 more white) -> 0 in progress
        E.NOBLE_REQ = ((3, 0, 0, 0, 0), (0, 0, 0, 0, 0), (0, 0, 0, 0, 0))
        s2, white2 = _noble_card_state((3, 0, 0, 0, 0), (2, 0, 0, 0, 0), (0, 0, 0, 0, 0))
        assert _val(s2).noble_progress(white2, 0) == 0.0
        assert _val(s2).noble_completion_pts(white2, 0) == 3   # ...scored as completion instead
    finally:
        E.NOBLE_REQ, E.NOBLE_PTS, V3.NOBLE_RACE_W = orig
