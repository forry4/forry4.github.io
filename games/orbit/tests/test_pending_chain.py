"""The pending chain the browser search rebuilds from, and what it may carry.

WHY THIS EXISTS.  `State::from_observation` refused any position with a pending
chain, because `observation()` redacts the effect queue to its first task.  The
served Expert therefore could not rebuild an effect-resolution position and
handed every one of them to the 1-ply ranker instead of searching it -- 45.0% of
all decisions with a real choice.  `pending_chain` is the missing half.

Two things are checked here, and they are different in kind:

* AGREEMENT.  The chain must be exactly the projection Rust already reads, so it
  is asserted against `native_state(game)["pending"]` -- the structure
  `tools/native_parity.py` already holds Python and Rust to.  Tying the new
  function to an ALREADY-GATED one is stronger than writing a second gate that
  could itself drift.
* CONTAINMENT.  The chain goes to the browser, and the browser belongs to the
  opponent.  It must carry nothing the viewing seat cannot already see.  The
  Rust suite has the same gate over its own walk
  (`the_pending_chain_carries_no_hidden_cards`); this is the Python side of the
  same invariant, because the Python engine is what actually builds the payload
  the server sends.
"""
from __future__ import annotations

import pytest

from games.orbit import engine as E
from games.orbit.ai.search import _actor
from games.orbit.ai.state import native_state, observation, pending_chain
from games.orbit.ai.serving import choose_move
from games.orbit.cards import CARDS


def _walk(seed: int, steps: int = 400):
    """Play a real game with the shipped ranker, yielding every decision point.

    `_actor` rather than `turn_pid`: during the mulligan BOTH seats are owed a
    decision and `turn_pid` is None, so a naive walk returns before the game has
    begun -- which is exactly what the first cut of this file did, leaving every
    assertion below unreached and one of them passing vacuously.
    """
    game = E.new_game(["a", "b"], seed=seed)
    for _ in range(steps):
        pid = _actor(game)
        if pid is None:
            return
        legal = E.legal_moves(game, pid)
        if not legal:
            return
        yield game, pid
        obs = observation(game, pid)
        move = choose_move(obs, legal, None, 5000, seed).move
        if move is None:
            return
        accepted, _error = E.apply_move(game, pid, move)
        if not accepted:
            return


def test_the_chain_is_the_projection_rust_already_reads():
    """Agreement with the structure the native parity gate already covers."""
    seen = 0
    for seed in (7, 77, 404, 1234):
        for game, _pid in _walk(seed):
            expected = native_state(game)["pending"]
            assert pending_chain(game) == expected, (
                "pending_chain drifted from native_state's projection, so the browser "
                "would rebuild a different position than the parity gate checks"
            )
            if game.get("pending"):
                seen += 1
    assert seen > 50, f"only {seen} pending positions reached; this test would prove little"


def test_a_position_with_no_chain_sends_nothing():
    for seed in (7, 404):
        for game, _pid in _walk(seed, steps=120):
            if not game.get("pending"):
                assert pending_chain(game) is None


def test_the_chain_names_no_card_the_seat_cannot_see():
    """CONTAINMENT.  The payload goes to the opponent's browser.

    Agent card ids are 101..518 and share that space with nothing, so a hit is a
    real leak.  Bonus token ids are 1..8, which is the same value space as a
    task's ``amount`` and ``index``, so they cannot be separated by value -- and
    they cannot leak by construction either, because a token enters the queue as
    its EFFECT PROGRAM, never as its id.
    """

    def ids_in(value):
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            yield value
        elif isinstance(value, str):
            if value.lstrip("-").isdigit():
                yield int(value)
        elif isinstance(value, list):
            for item in value:
                yield from ids_in(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from ids_in(item)

    checked = 0
    for seed in (7, 77, 404, 1234):
        for game, pid in _walk(seed):
            chain = pending_chain(game)
            if chain is None:
                continue
            other = next(p for p in game["order"] if p != pid)
            hidden = set(game["players"][other]["hand"]) | set(game["agent_deck"])
            for value in ids_in(chain):
                if value in CARDS:
                    assert value not in hidden, (
                        f"seed {seed}: the chain names card {value}, hidden from {pid} -- "
                        "sending it would leak the deck or the opposing hand"
                    )
            checked += 1
    assert checked > 50, f"only {checked} chains inspected; this gate would prove little"


def test_the_chain_carries_seats_not_player_ids():
    """Rust reads seat indices.  A pid string would deserialize into nothing.

    This is the one field `native_state` rewrites, so it is the one most likely
    to be dropped by a future hand-rolled copy of this projection.
    """
    found_actor = False
    for seed in (7, 77, 404):
        for game, _pid in _walk(seed):
            chain = pending_chain(game)
            if chain is None:
                continue
            for task in chain["queue"]:
                if "actor" in task:
                    found_actor = True
                    assert task["actor"] in (0, 1, None), (
                        f"actor {task['actor']!r} is not a seat index"
                    )
    assert found_actor, "no queued task carried an actor; this test proved nothing"


def test_the_chain_is_a_copy_and_not_the_live_game():
    """It is serialized onto the wire, so a caller must not be able to mutate state."""
    for seed in (7, 77):
        for game, _pid in _walk(seed):
            chain = pending_chain(game)
            if chain is None or not chain["queue"]:
                continue
            chain["queue"][0]["__poison__"] = True
            assert "__poison__" not in game["pending"]["queue"][0]
            return
    pytest.fail("no chain with a queued task was reached")
