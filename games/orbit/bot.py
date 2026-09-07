"""Orbit's server bot policies and their validated serving fallback."""

from __future__ import annotations

import random

from . import engine
from .ai.serving import choose_move as choose_serving_move
from .ai.state import observation


def choose_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    moves = engine.legal_moves(game, pid)
    if not moves:
        return None
    return random.Random(seed).choice(moves)


def choose_fallback_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    """Use the strongest cheap, policy-safe fallback available on the server.

    Hard rooms normally answer through the browser worker.  If that worker is
    unavailable or times out, the room must still finish the turn.  This path
    uses the same observation-only serving ranker as the worker and falls back
    to the historical random choice if a malformed legacy position cannot be
    encoded.  The public ``choose_move`` function remains the random baseline.
    """

    moves = engine.legal_moves(game, pid)
    if not moves:
        return None
    try:
        result = choose_serving_move(
            observation(game, pid), moves, None, 0, int(seed or 0))
        if result.move in moves:
            return result.move
    except Exception:  # pragma: no cover - defensive legacy-save fallback
        pass
    return random.Random(seed).choice(moves)
