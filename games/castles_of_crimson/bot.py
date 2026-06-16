"""Placeholder opponent for Castles of Crimson.

A trivial bot that plays random *legal* moves. It exists so the 1-player mode is
fully playable end-to-end now; the real AI will replace ``choose`` later behind
this same interface (the engine's ``legal_moves``/``apply_move`` contract).
"""
from __future__ import annotations

import random

from . import engine

# Moves that pass/skip rather than do something; deprioritized so the bot
# actually plays the game instead of immediately ending its turn.
_PASSIVE = {"end_turn", "skip_pending"}


def choose(game: dict, pid: str, rng: random.Random | None = None) -> dict | None:
    """Pick a random legal move for `pid` (whichever decision is pending)."""
    moves = engine.legal_moves(game, pid)
    if not moves:
        return None
    r = rng or random
    active = [m for m in moves if m["type"] not in _PASSIVE]
    return r.choice(active if active else moves)


def play_turn(game: dict, pid: str, rng: random.Random | None = None, max_steps: int = 300) -> None:
    """Drive `pid`'s decisions (its turn and any sub-decisions it owns) to a stop.

    Used by the server's scheduler: it keeps acting while the active decision
    belongs to `pid`, until the bot ends its turn or the game ends.
    """
    steps = 0
    while steps < max_steps and not engine.is_over(game):
        steps += 1
        actor = game.get("pending_pid") or game.get("turn")
        if actor != pid:
            break
        move = choose(game, pid, rng)
        if move is None:
            break
        ok, _ = engine.apply_move(game, pid, move)
        if not ok:
            break  # legal_moves should never yield an illegal move; bail defensively
        if move["type"] == "end_turn":
            break
