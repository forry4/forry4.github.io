"""Puzzle file format + (de)serialization.

A puzzle is a deterministic scripted walkthrough. The file embeds, per step:
  * the renderable game-dict SNAPSHOT the actor faces (engine.to_game_dict),
  * the action (engine id + human name + incumbent dict-move),
  * whether it's a hero step (the player must reproduce it) or a frozen opponent reply.

Embedding the snapshots means serving needs zero AI/engine compute: the frontend
renders snapshot[i], accepts a move, compares it to the hero step's move (✓ advance to
the next snapshot, which already includes the opponent's frozen reply / ✗ "wrong, start
over"), until the final winning position.
"""
from __future__ import annotations

import json

from games.spender.ai.az import actions as A
from games.spender.ai.az import engine as E

SCHEMA_VERSION = 1


def build_puzzle(start: E.State, sol, *, opponent: str, meta: dict | None = None) -> dict:
    """Replay the solved line from `start`, embedding a snapshot + move per step."""
    sim = start.clone()
    steps = []
    for (seat, a, phase) in sol.line:
        steps.append({
            "seat": seat,
            "is_hero": seat == sol.hero,
            "phase": phase,                       # engine phase int at the decision
            "action": a,                          # engine action id (0..69)
            "action_name": A.action_name(a),      # human-readable
            "move": A.action_to_move(sim, a),     # incumbent dict-move (resolved pre-apply)
            "snapshot": E.to_game_dict(sim),      # position the actor faces
        })
        E.apply(sim, a)
    return {
        "schema": SCHEMA_VERSION,
        "hero_seat": sol.hero,
        "win_points": start.win_points,
        "K": sol.K,
        "unique": sol.unique,
        "opponent": opponent,                     # "S" | "H3" — who the frozen replies are
        "position": E.to_game_dict(start),        # the puzzle's starting position
        "steps": steps,
        "final": E.to_game_dict(sim),             # the winning end position
        "winner_seat": sim.winner,
        "meta": meta or {},
    }


def hero_steps(puzzle: dict) -> list[dict]:
    """Just the hero decision steps (the moves the player must find), in order."""
    return [st for st in puzzle["steps"] if st["is_hero"]]


def save(puzzle: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(puzzle, f, indent=1)


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
