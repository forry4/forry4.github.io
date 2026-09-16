"""At-rest compaction boundary for Black Castle room state."""

from __future__ import annotations

from core import rooms as _rooms

MARKER = "_c"


def _pack_game(game: dict) -> dict:
    small = dict(game)
    if isinstance(small.get("rng_state"), list):
        small["rng_state"] = _rooms.pack_rng(small["rng_state"])
    undo = small.get("turn_undo")
    if isinstance(undo, dict) and isinstance(undo.get("state"), dict):
        undo_copy = dict(undo)
        undo_copy["state"] = _pack_game(undo_copy["state"])
        small["turn_undo"] = undo_copy
    small[MARKER] = 1
    return small


def _expand_game(game: dict) -> dict:
    big = dict(game)
    big.pop(MARKER, None)
    if big.get("rng_state") is not None:
        big["rng_state"] = _rooms.unpack_rng(big["rng_state"])
    undo = big.get("turn_undo")
    if isinstance(undo, dict) and isinstance(undo.get("state"), dict):
        undo_copy = dict(undo)
        undo_copy["state"] = _expand_game(undo_copy["state"])
        big["turn_undo"] = undo_copy
    return big


def compact_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return state
    game = state.get("game")
    if not isinstance(game, dict) or game.get(MARKER):
        return state
    out = dict(state)
    out["game"] = _pack_game(game)
    return out


def expand_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return state
    game = state.get("game")
    if not isinstance(game, dict) or not game.get(MARKER):
        return state
    out = dict(state)
    out["game"] = _expand_game(game)
    return out

