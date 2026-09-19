"""Easy Pinch opponent: uniformly random legal actions."""

from __future__ import annotations

import random

from . import engine


def choose_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    moves = engine.legal_moves(game, pid)
    return dict(random.Random(seed).choice(moves)) if moves else None
