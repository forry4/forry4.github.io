"""At-rest compaction boundary for SecretNames room state.

A PERSISTENCE BOUNDARY, never a change to the live dict: `_encode_state` /
`_decode_state` in `main.py` are the only call sites, the wire and the engine
keep the verbose shape, and a blob carries a `_c` marker so pre-compaction rows
load untouched and need no migration.

WHAT IS ACTUALLY BIG HERE, and it is not what it is in the other games. A
SecretNames blob has no undo stack, no move-log of card names and NO
``rng_state`` at all (see the engine's header — every draw happens in the deal).
What it does carry twice is the ROLE VOCABULARY: 50 key entries plus one log
line per action, each spelling out "agent"/"bystander"/"assassin" in full. The
keys pack to 50 single characters, which is the whole of the saving and is worth
having because it is also the part that is least compressible — two 25-long
lists of three repeated words are exactly the shape zlib eats, right up until
they sit beside a log that repeats the same words in prose.

The ratio is deliberately NOT asserted anywhere. A stored ratio's denominator is
the compressor, not the codec (the repo has measured the same blobs at 0.660 and
0.755 across zlib levels, and Python 3.14 ships zlib-ng), so the size guard in
`tests/test_persist.py` is on RAW bytes and the real no-op detection is the
structural round-trip test beside it.
"""
from __future__ import annotations

MARKER = "_c"

# One character per role. Chosen so the packed form is still readable in a
# `SELECT state_json` — "aabxbxx…" tells you what you are looking at.
_ROLE_CODE = {"agent": "a", "bystander": "b", "assassin": "x"}
_CODE_ROLE = {v: k for k, v in _ROLE_CODE.items()}


def _pack_side(side) -> str | list:
    if not isinstance(side, list) or not all(r in _ROLE_CODE for r in side):
        return side                      # unknown shape -> leave it verbatim
    return "".join(_ROLE_CODE[r] for r in side)


def _unpack_side(side):
    if not isinstance(side, str):
        return side
    return [_CODE_ROLE[c] for c in side]


def _pack_game(game: dict) -> dict:
    small = dict(game)
    keys = small.get("keys")
    if isinstance(keys, list) and len(keys) == 2:
        small["keys"] = [_pack_side(keys[0]), _pack_side(keys[1])]
    small[MARKER] = 1
    return small


def _expand_game(game: dict) -> dict:
    big = dict(game)
    big.pop(MARKER, None)
    keys = big.get("keys")
    if isinstance(keys, list) and len(keys) == 2:
        big["keys"] = [_unpack_side(keys[0]), _unpack_side(keys[1])]
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
