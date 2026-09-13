"""Hold Orbit's three rankers to each other, and to the leaf they order for.

THE RANKER IS IMPLEMENTED THREE TIMES -- Python (`ai/serving.py::_score`), Rust
(`orbit_core::serving::action_score`) and JavaScript (`orbit-worker.js::score`)
-- and all three SERVE. Rust runs in the browser worker, Python is what the
server's watchdog plays when the browser does not answer in time, and the JS
copy is the last-resort fallback when the wasm asset fails to load. Nothing held
them to each other.

That is exactly the shape this repo has already paid for: the same hidden-info
broadcast leak had to be found and fixed THREE times because three copies of
`mk_room_state` each leaked differently. On 2026-09-13 the same thing had
happened here -- the victory-blind planet term was present, identically, in all
three files, and fixing it meant finding all three by reading.

WHAT IS CHECKED, and why it is a TEXT check for two of the three. Python is
imported and called directly. Rust and JS are checked structurally: the
constants and the branch shape must be present, because compiling a Rust crate
and booting a JS module inside the Python suite would make a fast test slow and
a hermetic test dependent on a toolchain. The differential that really matters
-- Python against the compiled Rust over real positions -- belongs in
`tools/native_parity.py`, which already has a built binary to hand. This file is
the cheap gate that fails the moment one copy is edited and another is not.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from games.orbit.ai import serving
from games.orbit.cards import PLANETS

REPO_ROOT = Path(__file__).resolve().parents[3]
RUST = REPO_ROOT / "rust-cores" / "orbit-core" / "src" / "serving.rs"
JS = REPO_ROOT / "webapp" / "public" / "wasm" / "orbit-worker.js"


def _observation(seat: int, influence: list[int | None], captured: list[int], task: str) -> dict:
    """A position with the opponent's captures and the track under our control."""
    other = 1 - seat
    players: list[dict] = [{} , {}]
    players[seat] = {
        "credits": 5, "zenithium": 1, "hand": [], "columns": [[] for _ in PLANETS],
        "technology": [0, 0, 0], "row_bonuses": [], "captured": [],
    }
    players[other] = {
        "credits": 5, "zenithium": 1, "hand": [], "columns": [[] for _ in PLANETS],
        "technology": [0, 0, 0], "row_bonuses": [], "captured": list(captured),
        "hand_count": 4,
    }
    return {
        "schema": serving.SCHEMA_VERSION, "seat": seat, "phase": "play",
        "turn_pid": seat, "turn_number": 8, "winner": None,
        "influence": list(influence), "captured_this_turn": [],
        "leader": {"owner": None, "level": 0}, "board_sides": [1, 2, 1],
        "planet_bonus": [None] * 5, "technology_bonus": [None] * 3,
        "agent_discard": [], "bonus_discard": [], "mulligan_done": [],
        "pending_pid": seat, "agent_deck_count": 20, "bonus_deck_count": 5,
        "players": players,
        "pending": {"source": "test", "task": {"type": task, "amount": 1}},
        "legal_moves": [],
    }


def _score_planet(obs: dict, planet: str) -> float:
    return serving._score(obs, {"action": "choose", "planet": planet})


# --------------------------------------------------------------------------
# What the fix is actually FOR.  These assert behaviour, not agreement, so they
# still fail if all three implementations regress together.
# --------------------------------------------------------------------------

def test_a_planet_the_opponent_is_about_to_win_on_outranks_a_quiet_one():
    """The playtest report, as an assertion.

    Seat 0 holds nothing.  Seat 1 has two terra captures and their terra disc is
    one influence from the third, which ENDS THE GAME.  Contesting terra must
    outrank pushing an uncontested planet -- before the fix it scored 0.4 * -3 =
    -1.2 and ranked last of all five.
    """
    terra, mars = PLANETS.index("terra"), PLANETS.index("mars")
    influence: list[int | None] = [0] * 5
    influence[terra] = -3          # seat 1 is one step from capturing terra
    influence[mars] = 2            # seat 0 is two steps along mars
    obs = _observation(0, influence, [terra, terra], "influence_other")

    contest = _score_planet(obs, "terra")
    quiet = _score_planet(obs, "mars")
    assert contest > quiet, (
        f"blocking a game-ending capture ({contest:.3f}) must outrank advancing "
        f"a quiet planet ({quiet:.3f})"
    )
    assert contest > 0.0, "a contested planet must never score as a penalty"


def test_the_threat_is_priced_by_what_their_capture_is_worth():
    """A capture that WINS outranks one that merely advances, at equal distance.

    This is the half `capture_gain` exists for.  Both positions put the opponent
    three steps up terra; they differ only in what is already banked, which is
    what decides whether the capture ends the game.
    """
    terra = PLANETS.index("terra")
    influence: list[int | None] = [0] * 5
    influence[terra] = -3

    decisive = _score_planet(_observation(0, influence, [terra, terra], "influence"), "terra")
    harmless = _score_planet(_observation(0, influence, [], "influence"), "terra")
    assert decisive > harmless, (
        f"a game-ending threat ({decisive:.3f}) must outrank a harmless one "
        f"({harmless:.3f}) from the same square"
    )


def test_four_distinct_planets_is_recognised_as_a_victory_condition():
    """Holding three DIFFERENT planets, any fourth wins; a repeat does not."""
    terra, mars, mercury, venus = (PLANETS.index(p) for p in ("terra", "mars", "mercury", "venus"))
    influence: list[int | None] = [0] * 5
    influence[venus] = -3          # a fourth, distinct planet: wins
    influence[terra] = -3          # a repeat: does not
    obs = _observation(0, influence, [terra, mars, mercury], "influence")
    assert _score_planet(obs, "venus") > _score_planet(obs, "terra")


def test_closeness_reaches_its_maximum_at_the_opponents_match_point():
    """The scale tops out at 3, because a disc at 4 is captured and removed.

    v2's leaf divided by 4 and so priced match point at 56% of the capture's
    worth, with its own clamp unreachable.  The ranker must not repeat that.
    """
    terra = PLANETS.index("terra")
    scores = []
    for distance in (1, 2, 3):
        influence: list[int | None] = [0] * 5
        influence[terra] = -distance
        scores.append(_score_planet(_observation(0, influence, [terra, terra], "influence"), "terra"))
    assert scores[0] < scores[1] < scores[2], f"urgency must rise with proximity: {scores}"
    gain = serving.WINNING_CAPTURE
    assert scores[2] == pytest.approx(serving.POLICY_WEIGHTS["threat"] * gain), (
        "at match point the denial term must be the full weight * gain"
    )


def test_the_seats_own_advance_is_unchanged():
    """The fix must only touch the branch that was wrong.

    A planet this seat leads is still scored at `choice * position`, so every
    number this campaign measured on uncontested planets still holds.
    """
    mars = PLANETS.index("mars")
    influence: list[int | None] = [0] * 5
    influence[mars] = 2
    obs = _observation(0, influence, [], "influence")
    assert _score_planet(obs, "mars") == pytest.approx(serving.POLICY_WEIGHTS["choice"] * 2)


def test_a_transfer_task_does_not_take_the_denial_branch():
    """`transfer`/`exile` name a COLUMN, not a disc, so the track is a weak proxy.

    Denial through those is already priced by the opponent-column term, and
    double-counting it would be a different bug in the same place.
    """
    terra = PLANETS.index("terra")
    influence: list[int | None] = [0] * 5
    influence[terra] = -3
    obs = _observation(0, influence, [terra, terra], "transfer")
    expected = (serving.POLICY_WEIGHTS["choice"] * -3
                - serving.POLICY_WEIGHTS["choice_opponent"] * -3)
    assert _score_planet(obs, "terra") == pytest.approx(expected)


def test_seat_one_reads_the_track_in_its_own_direction():
    """Seat 1 advances a disc NEGATIVE, so the whole sign convention mirrors.

    A sign bug here would be invisible in every seat-0 test above and would make
    the bot contest its own planets.
    """
    terra = PLANETS.index("terra")
    influence: list[int | None] = [0] * 5
    influence[terra] = 3           # POSITIVE is seat 0 advancing -> a threat to seat 1
    obs = _observation(1, influence, [terra, terra], "influence")
    assert _score_planet(obs, "terra") > 0.0


# --------------------------------------------------------------------------
# The three copies must agree.  Structural for Rust and JS -- see the module
# docstring for why, and `tools/native_parity.py` for the differential.
# --------------------------------------------------------------------------

def test_every_implementation_carries_the_same_constants():
    rust, js = RUST.read_text(encoding="utf-8"), JS.read_text(encoding="utf-8")
    for label, value in (("WINNING_CAPTURE", serving.WINNING_CAPTURE),
                         ("CONTEST_REACH", serving.CONTEST_REACH)):
        # WINNING_CAPTURE lives in search.rs on the Rust side; the ranker calls
        # `capture_gain` rather than re-deriving it, which is the stronger form
        # of agreement and is asserted separately below.
        assert f"{label}" in js, f"the JS fallback has lost {label}"
        assert str(value) in js, f"the JS fallback disagrees about {label}"
    assert "CONTEST_REACH: f64 = 3.0" in rust, "Rust disagrees about the denial scale"
    assert f'"threat": {serving.POLICY_WEIGHTS["threat"]}' in js or \
        f"threat: {serving.POLICY_WEIGHTS['threat']}" in js, \
        "the JS default policy disagrees about the threat weight"
    assert f"THREAT: f64 = {serving.POLICY_WEIGHTS['threat']}" in rust, \
        "Rust disagrees about the threat weight"


def test_every_implementation_gates_the_denial_branch_on_influence_tasks():
    rust, js = RUST.read_text(encoding="utf-8"), JS.read_text(encoding="utf-8")
    for name, text in (("rust", rust), ("js", js)):
        for task in serving.INFLUENCE_TASKS:
            assert f'"{task}"' in text, f"{name} has lost the {task} task type"
    assert "planet_choice_value" in rust, "Rust no longer routes through the shared branch"
    assert "planetChoiceValue" in js, "the JS fallback no longer routes through the shared branch"


def test_the_ranker_and_the_leaf_price_a_capture_with_one_function():
    """The ordering prior must not disagree with the evaluator it orders for.

    Rust calls `search::capture_gain` directly, which is agreement by
    construction.  Python has its own copy, so it is checked against the leaf's
    own definition over every reachable capture set.
    """
    rust = RUST.read_text(encoding="utf-8")
    assert "crate::search::capture_gain" in rust, (
        "Rust's ranker stopped using the leaf's capture_gain, so the two can now drift"
    )
    # Python: the same three victory conditions, exhaustively.
    from itertools import combinations_with_replacement
    for size in range(0, 5):
        for captured in combinations_with_replacement(range(5), size):
            counts = [0] * 5
            for value in captured:
                counts[value] += 1
            if max(counts) >= 3 or sum(1 for n in counts if n) >= 4 or len(captured) >= 5:
                continue  # already won; not a position a ranker is asked about
            for planet in range(5):
                obs = _observation(0, [0] * 5, list(captured), "influence")
                gain = serving._capture_gain(obs, 1, planet)
                after = list(counts)
                after[planet] += 1
                wins = (max(after) >= 3 or sum(1 for n in after if n) >= 4
                        or sum(after) >= 5)
                if wins:
                    assert gain == serving.WINNING_CAPTURE, (
                        f"{captured} + {planet} ends the game and must be priced as a win"
                    )
                else:
                    assert 0.0 <= gain < serving.WINNING_CAPTURE
