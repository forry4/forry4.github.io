"""Easy Black Castle opponent: a reproducible random legal move."""

from __future__ import annotations

import random

from . import engine


def choose_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    moves = [m for m in engine.legal_moves(game, pid) if m.get("type") != "undo"]
    if not moves:
        return None
    rng = random.Random(seed)
    return dict(rng.choice(moves))


def choose_random_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    return choose_move(game, pid, seed)

