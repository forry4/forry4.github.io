"""Sanity invariants for variant S: v_state (whole-position evaluator) + vsearch (V-leaf PUCT).

Permanent guards — keep green. They pin the contract the search relies on (bounded value, correct
perspective, monotonic in own points) and that the serving round-trip produces a legal move.
"""
import random

import pytest

from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic3 as H3
from games.spender.ai.az import v_state
from games.spender.ai.az import vsearch


def _state(seed: int, plies: int):
    """A reproducible mid-ish-game engine state reached by greedy-H3 self-play."""
    s = E.new_game(random.Random(seed))
    for _ in range(plies):
        if s.phase == E.OVER:
            break
        E.apply(s, H3.choose_action(s, s.turn))
    return s


def test_value_in_range():
    for seed in range(10):
        s = _state(seed, 12)
        if s.phase == E.OVER:
            continue
        assert -1.0 <= v_state.value(s, s.turn) <= 1.0


def test_fresh_game_is_balanced():
    # A brand-new symmetric position: both seats identical -> V == 0.
    s = E.new_game(random.Random(3))
    assert abs(v_state.value(s, s.turn)) < 1e-9


def test_perspective_antisymmetric_without_blind_reserves():
    # V(s, seat) = -V(s, 1-seat) EXCEPT for the deliberate hidden-info asymmetry (each perspective
    # hides the OTHER seat's face-down reserves). With no blind reserves, the two are exact negatives.
    s = _state(5, 14)
    if s.phase == E.OVER or any(s.reserved_blind[0]) or any(s.reserved_blind[1]):
        return
    assert abs(v_state.value(s, 0) + v_state.value(s, 1)) < 1e-9


def test_components_keys_present():
    s = _state(7, 10)
    c = v_state.components(s, s.turn)
    for k in ("value", "stand_me", "stand_opp", "points_me", "engine_me",
              "progress_me", "noble_me", "econ_me"):
        assert k in c


def test_more_own_points_raises_value():
    s = _state(9, 6)              # early/mid -> far from tanh saturation
    if s.phase == E.OVER:
        return
    me = s.turn
    v0 = v_state.value(s, me)
    s.points[me] += 3
    assert v_state.value(s, me) > v0


def test_vsearch_returns_legal_action():
    for seed in (4, 8, 15):
        s = _state(seed, 8)
        if s.phase == E.OVER:
            continue
        a = vsearch.choose_action(s, s.turn, sims=40)
        assert a in E.legal_actions(s)


def test_serving_roundtrip_produces_legal_move():
    # Serving path: engine state -> game dict -> _s_choose_move -> a typed move dict.
    import games.spender.main as M

    vsearch.SERVE_TIME = 0.2     # keep the test fast (overrides the 4.5s production budget)
    s = _state(6, 8)
    if s.phase == E.OVER:
        return
    g = E.to_game_dict(s, ("p0", "p1"))
    mv = M._s_choose_move(g, g["order"][s.turn])
    assert isinstance(mv, dict) and mv.get("type")


def _val(s):
    from games.spender.ai.az import valuation3 as V
    return V.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)


def test_tiebreak_default_is_byte_identical():
    """Default ENDGAME_TIEBREAK_W=0 -> the delta is always 0 (V unchanged from the shipped eval)."""
    assert v_state.ENDGAME_TIEBREAK_W == 0.0
    s = E.new_game(random.Random(3))
    s.points = [14, 14]; s.purchased_n = [8, 12]   # endgame, near-tie, lopsided cards
    assert v_state._tiebreak_delta(_val(s), 0, 1) == 0.0


def test_tiebreak_rewards_fewer_cards_in_live_endgame():
    """With the knob on, near the win and near-tied on points, the side with FEWER purchased cards
    gets a positive standing nudge (it wins the pts->fewest-cards tiebreak)."""
    s = E.new_game(random.Random(3))
    s.points = [14, 14]; s.purchased_n = [8, 12]   # seat 0 has 4 fewer cards
    v_state.ENDGAME_TIEBREAK_W = 0.05
    try:
        d = v_state._tiebreak_delta(_val(s), 0, 1)
        assert d > 0.0                              # fewer cards -> rewarded
        assert v_state._tiebreak_delta(_val(s), 1, 0) < 0.0   # opp (more cards) -> penalized, antisymmetric
    finally:
        v_state.ENDGAME_TIEBREAK_W = 0.0


def test_tiebreak_inert_in_midgame():
    """Far from the win the tiebreak never fires, even with the knob on (no midgame card discouragement)."""
    s = E.new_game(random.Random(3))
    s.points = [5, 5]; s.purchased_n = [3, 7]
    v_state.ENDGAME_TIEBREAK_W = 0.05
    try:
        assert v_state._tiebreak_delta(_val(s), 0, 1) == 0.0   # zone <= 0
    finally:
        v_state.ENDGAME_TIEBREAK_W = 0.0


def test_tiebreak_inert_when_points_gap_wide():
    """When one side is far ahead on points, the tiebreak is moot (it only decides near-ties)."""
    s = E.new_game(random.Random(3))
    s.points = [14, 8]; s.purchased_n = [12, 5]    # seat 0 winning on POINTS; card lead irrelevant
    v_state.ENDGAME_TIEBREAK_W = 0.05
    try:
        assert v_state._tiebreak_delta(_val(s), 0, 1) == 0.0   # gap 6 > ENDGAME_TIE_GAP -> close <= 0
    finally:
        v_state.ENDGAME_TIEBREAK_W = 0.0


def test_noble_multi_default_is_max_only():
    """Default NOBLE_MULTI_W=0 -> _noble_stand counts only the best noble (byte-identical)."""
    assert v_state.NOBLE_MULTI_W == 0.0


def test_noble_multi_credits_secondary_nobles():
    """With the knob on, a position progressing toward multiple nobles scores >= one toward a single
    noble (sum >= max for non-negative per-noble standings), and STRICTLY greater on boards where 2+
    nobles contribute. Broad bonuses make several nobles partially-met across seeds."""
    strictly_greater = 0
    for seed in range(12):
        s = E.new_game(random.Random(seed))
        s.bonuses = ([2, 2, 2, 2, 2], [0, 0, 0, 0, 0])   # broad progress -> several nobles partially met
        base = v_state._noble_stand(_val(s), 0)          # W=0 (max only)
        v_state.NOBLE_MULTI_W = 1.0
        try:
            multi = v_state._noble_stand(_val(s), 0)      # W=1 (best + full sum of the others)
        finally:
            v_state.NOBLE_MULTI_W = 0.0
        assert multi >= base - 1e-9
        if multi > base + 1e-9:
            strictly_greater += 1
    assert strictly_greater > 0                          # the knob demonstrably credits secondary nobles


def test_is_endgame_detection():
    s = E.new_game(random.Random(3))
    assert not vsearch._is_endgame(s)              # fresh game, 0-0
    s.points = [E.WIN_POINTS - vsearch.ENDGAME_NEAR, 0]
    assert vsearch._is_endgame(s)                  # within ENDGAME_NEAR of the win
    s.points = [0, 0]; s.final_trigger = 0
    assert vsearch._is_endgame(s)                  # final round triggered


def test_endgame_sim_mult_default_is_noop():
    """Defaults -> serving/offline budget unchanged (byte-identical). ENDGAME_SERVE_TIME's committed
    default (4.5) == SERVE_TIME's committed default, so endgame serving adds no time out of the box.
    (SERVE_TIME itself may be mutated by an earlier test, so compare to the literal default.)"""
    assert vsearch.ENDGAME_SIM_MULT == 1.0
    assert vsearch.ENDGAME_SERVE_TIME == 4.5


def test_freshness_guard_fires_on_stale_reuse():
    """The valuation3 freshness guard must FAIL LOUDLY if a Valuation is reused after its state
    mutates (the lookahead footgun) — single chokepoint = estimated_turns_remaining. Any PLAY move
    changes the (ply, phase, turn) fingerprint, so re-querying the stale Valuation must raise."""
    from games.spender.ai.az import valuation3 as V
    s = _state(6, 8)
    guard = 0
    while s.phase != E.PLAY and s.phase != E.OVER and guard < 20:
        E.apply(s, H3.choose_action(s, s.turn))
        guard += 1
    assert s.phase == E.PLAY
    val = V.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    val.estimated_turns_remaining()                 # fresh: fine
    E.apply(s, H3.choose_action(s, s.turn))         # mutate the state out from under val
    with pytest.raises(AssertionError):
        val.estimated_turns_remaining()
