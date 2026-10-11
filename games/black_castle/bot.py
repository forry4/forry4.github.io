"""Easy Black Castle opponent: a reproducible random legal move."""

from __future__ import annotations

import random

from . import engine


def choose_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    moves = [m for m in engine.legal_moves(game, pid) if m.get("type") != "undo"]
    if not moves:
        return None
    # Every action a card grants can be declined, but a bot that declines at random
    # throws away half of what it is given. Skip only when nothing else is legal.
    taken = [m for m in moves if m.get("type") != "skip"]
    moves = taken or moves
    rng = random.Random(seed)
    return dict(rng.choice(moves))


def choose_random_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    return choose_move(game, pid, seed)

