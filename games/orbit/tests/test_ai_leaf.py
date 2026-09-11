"""The search leaf must be a real state evaluator, not a capture counter.

`rust-cores/orbit-core/src/search.rs` shipped a leaf that was only the first
term of `ai/search.py::state_value`: capture progress, without the 1.4 weight or
any of the influence, technology, leader, bonus, economy and hand terms. That
reduced leaf took 21-25 distinct values in an entire game, was exactly 0.0 on
~35% of positions, and was flat for the first quarter of every game -- so the
tree had nothing to propagate and the simulation ladder stopped paying at ~192.

These tests pin the PYTHON reference's sensitivity to each dropped term. The
Rust port is held to this reference bit-for-bit by
`python -m games.orbit.tools.leaf_parity` (2,728 positions, max delta 0.0),
which needs a built Rust binary and so stays a local gate like the other parity
harnesses rather than a CI test.
"""
from __future__ import annotations

import copy

import pytest

from games.orbit import engine
from games.orbit.ai.search import _actor, state_value


def _game():
    return engine.new_game(["alpha", "beta"], seed=9300)


def _both(game):
    return state_value(game, "alpha"), state_value(game, "beta")


def test_leaf_is_zero_sum_in_every_public_term():
    # Strip the one term that compares different quantities for the two seats
    # (own hand cost against the opponent's column cost) and the evaluator is
    # EXACTLY antisymmetric. Worth pinning: the search only ever evaluates the
    # searching seat's own observation, so the asymmetry is harmless there, but
    # a future minimax backup over opponent nodes would be relying on a
    # zero-sum leaf and must account for this term.
    game = _game()
    for pid in game["order"]:
        game["players"][pid]["hand"] = []
        for planet in game["players"][pid]["columns"]:
            game["players"][pid]["columns"][planet] = []
    a, b = _both(game)
    assert a == pytest.approx(-b, abs=1e-12)


def test_the_private_hand_term_is_the_only_asymmetry():
    # And it is real, not rounding: at the opening deal the two seats hold
    # different hand values, so their leaf values do not sum to zero.
    a, b = _both(_game())
    assert abs(a + b) > 1e-3


@pytest.mark.parametrize("planet_index", range(5))
def test_influence_position_moves_the_leaf(planet_index):
    # The single largest thing the old leaf could not see: a disc three steps
    # into your zone is one influence from a capture, and the old leaf scored
    # that identically to an untouched track.
    game = _game()
    planet = engine.PLANETS[planet_index]
    values = []
    for position in (-3, -1, 0, 1, 3):
        probe = copy.deepcopy(game)
        probe["influence"][planet] = position
        values.append(state_value(probe, probe["order"][0]))
    assert len(set(values)) == len(values), "every influence position must be distinguishable"
    assert values == sorted(values), "more influence toward your zone must never score worse"


def test_influence_urgency_is_superlinear_near_a_capture():
    # Two steps of influence close to a capture must be worth more than two
    # steps in the middle of the track, or the search cannot see a race.
    game = _game()
    planet = engine.PLANETS[0]

    def at(position):
        probe = copy.deepcopy(game)
        probe["influence"][planet] = position
        return state_value(probe, probe["order"][0])

    near = at(3) - at(1)
    middle = at(1) - at(-1)
    assert near > middle


@pytest.mark.parametrize("field, delta", [("credits", 6), ("zenithium", 3)])
def test_economy_moves_the_leaf_but_never_outscores_a_capture(field, delta):
    # The repo-wide rule: a resource must not out-score what it converts into,
    # or the bot hoards forever. A capture is the thing these buy.
    game = _game()
    richer = copy.deepcopy(game)
    richer["players"]["alpha"][field] += delta
    captured = copy.deepcopy(game)
    captured["players"]["alpha"]["captured"].append(engine.PLANETS[0])
    base = state_value(game, "alpha")
    assert state_value(richer, "alpha") > base
    assert state_value(captured, "alpha") > state_value(richer, "alpha")


def test_technology_leader_and_bonuses_all_move_the_leaf():
    game = _game()
    base = state_value(game, "alpha")
    tech = copy.deepcopy(game)
    tech["players"]["alpha"]["technology"][engine.FACTIONS[0]] += 2
    assert state_value(tech, "alpha") > base

    leader = copy.deepcopy(game)
    leader["leader"] = {"owner": "alpha", "level": 2}
    assert state_value(leader, "alpha") > base
    opposed = copy.deepcopy(game)
    opposed["leader"] = {"owner": "beta", "level": 2}
    assert state_value(opposed, "alpha") < base

    bonuses = copy.deepcopy(game)
    bonuses["players"]["alpha"]["row_bonuses"].append(0)
    assert state_value(bonuses, "alpha") > base


def test_the_leaf_is_dense_over_a_real_game():
    # The defect this file exists for, stated as a number. A capture-only leaf
    # measures ~21 distinct values and ~35% exact zeros over a whole game; a
    # usable evaluator must be far denser and must not be blind early.
    game = _game()
    values = []
    for _ in range(1600):
        if engine.is_over(game):
            break
        pid = _actor(game)
        if pid is None:
            break
        moves = engine.legal_moves(game, pid)
        if not moves:
            break
        values.append(state_value(game, game["order"][0]))
        engine.apply_move(game, pid, moves[0])
    assert len(values) > 50, "the probe game must actually be played out"
    distinct = len({round(v, 9) for v in values})
    zeros = sum(1 for v in values if abs(v) < 1e-12)
    assert distinct > len(values) // 2, f"leaf collapsed to {distinct} values over {len(values)}"
    assert zeros <= 1, f"leaf returned exact zero on {zeros} positions"
    # ...and it must not be flat through the opening, which is where the search
    # most needs something to propagate.
    opening = values[: max(4, len(values) // 4)]
    assert len({round(v, 9) for v in opening}) > 1, "leaf is flat through the opening"
