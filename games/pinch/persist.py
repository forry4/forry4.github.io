"""Versioned at-rest persistence boundary for Pinch room state."""

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
