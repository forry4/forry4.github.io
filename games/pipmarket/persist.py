"""At-rest persistence boundary for Pip Market room state.

The blob is small (a few hundred dice positions and a capped log) and carries no
generator state — the deal and every reroll are derived from the seed — so there
is nothing worth packing yet. The marker exists so a later compaction can tell
old rows from new ones without a migration.
"""

from __future__ import annotations

import copy

COMPACTION_VERSION = 1


def compact_state(state: dict) -> dict:
    packed = copy.deepcopy(state)
    packed["_c"] = COMPACTION_VERSION
    return packed


def expand_state(state: dict) -> dict:
    expanded = copy.deepcopy(state)
    expanded.pop("_c", None)
    return expanded
