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
