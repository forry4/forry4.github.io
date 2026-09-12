"""Cover the calibrated fixed-simulation screen and the mirror claim it can break.

An equal-time arena is load-dependent: its wall clock is decisions x budget, so
contention does not slow it, it starves each decision of simulations silently.
The deterministic screen exists to remove that failure mode -- but only if it is
calibrated PER ROLE, because the coherent search's speed advantage is the effect
being measured and a symmetric count deletes it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ..tools.calibrate_fixed_sims import actor_pool, tally
from ..tools.native_search_arena import mirror_control


def report(rows, *, workers=4, via_observation=True, complete=True):
    return {"workers": workers, "via_observation": via_observation, "complete": complete,
            "fixed_simulations": None, "games": rows}


def row(candidate, *, candidate_sims, opponent_sims, searches=10):
    """One game. Seat indices are absolute; the candidate's seat swaps per pair."""
    by_seat = [0, 0]
    searched = [0, 0]
    by_seat[candidate] = candidate_sims
    by_seat[1 - candidate] = opponent_sims
    searched[candidate] = searches
    searched[1 - candidate] = searches
    return {"candidate": candidate, "simulations_by_seat": by_seat,
            "searches_by_seat": searched}


def test_roles_are_pooled_by_role_not_by_seat():
    """The trap: the candidate swaps seats every game for common random numbers.

    Pooling by seat averages the two players together and hands back two
    identical numbers, which would calibrate both sides to the same count and
    silently restore the equal-sims question.
    """
    rows = [row(0, candidate_sims=8000, opponent_sims=4000),
            row(1, candidate_sims=8000, opponent_sims=4000)]
    out = tally([(Path("a.json"), report(rows))])
    assert out["candidate"]["simulations"] == 16000
    assert out["opponent"]["simulations"] == 8000
    assert out["candidate"]["per_decision"] != out["opponent"]["per_decision"]
    assert out["throughput_ratio"] == 2.0


def test_per_worker_counts_divide_by_the_pool_that_actually_runs():
    """``--simulations`` is per worker and the arena asserts total == n * pool."""
    rows = [row(0, candidate_sims=8000, opponent_sims=4000, searches=10)]
    out = tally([(Path("a.json"), report(rows, workers=4))])
    # 8000 simulations over 10 searched decisions = 800 per decision, across a
    # pool of four workers = 200 each.
    assert out["actor_pool"] == 4
    assert out["candidate"]["per_worker"] == 200
    assert out["opponent"]["per_worker"] == 100
    assert out["flags"] == "--simulations 200 --opponent-simulations 100"


def test_a_pool_only_runs_per_decision_when_the_search_is_via_observation():
    """`actor_pool` is 1 without --via-observation however many workers were asked for."""
    assert actor_pool({"workers": 4, "via_observation": True}) == 4
    assert actor_pool({"workers": 4, "via_observation": False}) == 1
    rows = [row(0, candidate_sims=8000, opponent_sims=4000, searches=10)]
    out = tally([(Path("a.json"), report(rows, via_observation=False))])
    assert out["candidate"]["per_worker"] == 800


def test_a_report_without_per_seat_counters_is_refused():
    """Older reports carry one blended total, which cannot be split by role."""
    rows = [{"candidate": 0, "simulations": 12000, "searches": 20}]
    with pytest.raises(ValueError, match="predates per-seat counters"):
        tally([(Path("old.json"), report(rows))])


def test_calibrating_from_a_fixed_simulation_run_is_refused():
    """Calibration must come from the equal-time shape, not from itself."""
    body = report([row(0, candidate_sims=8000, opponent_sims=4000)])
    body["fixed_simulations"] = 200
    with pytest.raises(ValueError, match="already a fixed-simulation run"):
        tally([(Path("fixed.json"), body)])


def test_a_count_outside_the_arenas_range_is_refused_not_clamped():
    """Silently clamping would produce a screen that is not the shape requested."""
    rows = [row(0, candidate_sims=8_000_000, opponent_sims=4_000, searches=1)]
    with pytest.raises(ValueError, match="outside the arena's 1..10000 range"):
        tally([(Path("a.json"), report(rows))])


def test_reports_that_disagree_on_the_pool_cannot_be_pooled():
    rows = [row(0, candidate_sims=8000, opponent_sims=4000)]
    with pytest.raises(ValueError, match="disagree on the worker pool"):
        tally([(Path("a.json"), report(rows, workers=4)),
               (Path("b.json"), report(rows, workers=2))])


MIRROR = dict(simulations=200, opponent_simulations=200, heuristic=False, models_match=True,
              leaf="state-value", opponent_leaf="state-value",
              determinization_period=0, opponent_determinization_period=0)


def test_identical_seats_are_a_mirror():
    assert mirror_control(**MIRROR)
    # The opponent count defaulting to the candidate's is still a mirror.
    assert mirror_control(**{**MIRROR, "opponent_simulations": None})


@pytest.mark.parametrize("difference", [
    {"opponent_simulations": 100},               # the new asymmetry
    {"opponent_leaf": "capture-progress-only"},
    {"opponent_determinization_period": 1},
    {"models_match": False},
    {"heuristic": True},
    {"simulations": None},                       # equal-time cannot reproduce itself
])
def test_any_per_seat_difference_is_not_a_mirror(difference):
    """A mirror is held to exactly 0.5000, so a false one asserts something untrue."""
    assert not mirror_control(**{**MIRROR, **difference})


# --- the binary equivalence gate ---------------------------------------------
# Pools measured on an old binary and pools measured on a new one are two
# experiments wearing one name, and nothing in either report says so.

from ..tools.arena_equivalence import compare


def _run(games, **settings):
    body = {"pool": "development-x", "fixed_simulations": 64,
            "fixed_opponent_simulations": 64, "workers": 2, "game_workers": 1,
            "via_observation": True, "leaf": "state-value", "opponent_leaf": "state-value",
            "determinization_period": 0, "opponent_determinization_period": 1,
            "checkpoint": "heuristic", "opponent": "expert", "games": games}
    body.update(settings)
    return body


def _game(index, winner, simulations=256, decisions=40):
    return {"index": index, "seed": 100 + index, "candidate": index % 2, "winner": winner,
            "simulations": simulations, "decisions": decisions, "censored": False,
            "error": None, "elapsed_ms": 12.5 * index}


def test_identical_runs_compare_equal_despite_differing_wall_clock():
    """Timing fields MUST be excluded or the gate cries wolf and gets ignored."""
    left = _run([_game(0, 0), _game(1, 1)])
    right = _run([dict(_game(0, 0), elapsed_ms=999.0), dict(_game(1, 1), elapsed_ms=0.1)])
    assert compare(left, right)["identical"]


@pytest.mark.parametrize("field,value", [
    ("winner", 1), ("simulations", 257), ("decisions", 41), ("censored", True),
    ("seed", 999), ("error", "boom"),
])
def test_any_deterministic_difference_is_caught(field, value):
    left = _run([_game(0, 0), _game(1, 1)])
    changed = dict(_game(0, 0))
    changed[field] = value
    report = compare(left, _run([changed, _game(1, 1)]))
    assert not report["identical"]
    assert report["differences"][0]["field"] == field


def test_a_different_game_count_is_a_difference_not_a_crash():
    report = compare(_run([_game(0, 0), _game(1, 1)]), _run([_game(0, 0)]))
    assert not report["identical"]


def test_runs_with_different_settings_are_refused_rather_than_compared():
    """Agreement between two different experiments would be luck, not evidence."""
    with pytest.raises(ValueError, match="not the same experiment"):
        compare(_run([_game(0, 0)]), _run([_game(0, 0)], workers=4))


def test_an_equal_time_run_cannot_prove_equivalence():
    """It does not reproduce itself even on one binary, so it can prove nothing."""
    with pytest.raises(ValueError, match="fixed simulations"):
        compare(_run([_game(0, 0)], fixed_simulations=None), _run([_game(0, 0)]))
