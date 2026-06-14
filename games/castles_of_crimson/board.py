"""The single standard duchy board for Castles of Crimson.

Both players share this one hand-authored layout. The board is a radius-3
hexagon (exactly 37 spaces) in axial coordinates ``(q, r)``. Every space has a
required die ``number`` (1-6) and a ``color``; placing a hex tile on a space
requires a die matching ``number`` and a tile whose color matches the space.

Colors map to tile types:
    burgundy -> castle, blue -> ship, gray -> mine,
    green -> livestock, beige -> building, yellow -> monastery.

A "region" (scoring area) is a maximal connected component of same-colored
spaces; regions are *computed* from the layout so they are always contiguous by
construction. The starting castle sits at the center (0, 0) and is pre-placed at
game start, so its (size-1) region is already complete and never scores during
play.

Everything here is static, deterministic, and has no web/game dependency.
"""
from __future__ import annotations

from collections import deque

COLORS = ["burgundy", "blue", "gray", "green", "beige", "yellow"]

CASTLE_SPACE = (0, 0)

# Axial neighbor directions (pointy-top hex).
_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]

# (q, r) -> (color, required die number). 37 spaces forming a radius-3 hexagon.
# Hand-designed so that same-color regions are contiguous and none exceed size 8.
_LAYOUT: dict[tuple[int, int], tuple[str, int]] = {
    # r = -3
    (0, -3): ("yellow", 1), (1, -3): ("blue", 1), (2, -3): ("blue", 2), (3, -3): ("blue", 3),
    # r = -2
    (-1, -2): ("yellow", 3), (0, -2): ("yellow", 5), (1, -2): ("blue", 4), (2, -2): ("blue", 5), (3, -2): ("burgundy", 3),
    # r = -1
    (-2, -1): ("beige", 1), (-1, -1): ("beige", 2), (0, -1): ("beige", 3), (1, -1): ("gray", 1), (2, -1): ("blue", 6), (3, -1): ("burgundy", 6),
    # r = 0  (center = starting castle)
    (-3, 0): ("beige", 4), (-2, 0): ("beige", 5), (-1, 0): ("beige", 6), (0, 0): ("burgundy", 4), (1, 0): ("gray", 2), (2, 0): ("gray", 3), (3, 0): ("gray", 4),
    # r = 1
    (-3, 1): ("beige", 2), (-2, 1): ("beige", 4), (-1, 1): ("yellow", 4), (0, 1): ("gray", 5), (1, 1): ("green", 1), (2, 1): ("green", 2),
    # r = 2
    (-3, 2): ("gray", 6), (-2, 2): ("gray", 2), (-1, 2): ("green", 3), (0, 2): ("green", 4), (1, 2): ("green", 5),
    # r = 3
    (-3, 3): ("yellow", 2), (-2, 3): ("green", 6), (-1, 3): ("green", 1), (0, 3): ("green", 3),
}


def space_id(q: int, r: int) -> str:
    return f"{q},{r}"


def parse_space_id(sid: str) -> tuple[int, int]:
    q, r = sid.split(",")
    return int(q), int(r)


# space_id -> {"q","r","number","color","is_castle"}
SPACES: dict[str, dict] = {}
for (q, r), (color, number) in _LAYOUT.items():
    sid = space_id(q, r)
    SPACES[sid] = {
        "q": q,
        "r": r,
        "number": number,
        "color": color,
        "is_castle": (q, r) == CASTLE_SPACE,
    }

# Precomputed adjacency restricted to existing spaces.
ADJACENCY: dict[str, list[str]] = {}
for sid, info in SPACES.items():
    q, r = info["q"], info["r"]
    nbrs = []
    for dq, dr in _DIRS:
        nsid = space_id(q + dq, r + dr)
        if nsid in SPACES:
            nbrs.append(nsid)
    ADJACENCY[sid] = sorted(nbrs)


def neighbors(sid: str) -> list[str]:
    return ADJACENCY.get(sid, [])


def _connected_components(space_ids: set[str]) -> list[set[str]]:
    """Connected components (via ADJACENCY) of a given set of spaces."""
    seen: set[str] = set()
    comps: list[set[str]] = []
    for start in sorted(space_ids):
        if start in seen:
            continue
        comp: set[str] = set()
        dq: deque[str] = deque([start])
        seen.add(start)
        while dq:
            cur = dq.popleft()
            comp.add(cur)
            for nb in ADJACENCY[cur]:
                if nb in space_ids and nb not in seen:
                    seen.add(nb)
                    dq.append(nb)
        comps.append(comp)
    return comps


# Regions = connected components of same-colored spaces.
# region_id -> {"id","color","spaces":set,"size","has_castle"}
REGIONS: dict[str, dict] = {}
REGION_OF: dict[str, str] = {}  # space_id -> region_id
for _color in COLORS:
    color_spaces = {sid for sid, info in SPACES.items() if info["color"] == _color}
    comps = _connected_components(color_spaces)
    for i, comp in enumerate(comps, start=1):
        rid = f"{_color}-{i}"
        has_castle = any(SPACES[s]["is_castle"] for s in comp)
        REGIONS[rid] = {
            "id": rid,
            "color": _color,
            "spaces": comp,
            "size": len(comp),
            "has_castle": has_castle,
        }
        for s in comp:
            REGION_OF[s] = rid


def region_of(sid: str) -> str:
    return REGION_OF[sid]


# Spaces grouped by color (for color-completion / bonus-tile checks).
SPACES_BY_COLOR: dict[str, set[str]] = {c: set() for c in COLORS}
for _sid, _info in SPACES.items():
    SPACES_BY_COLOR[_info["color"]].add(_sid)


def axial_to_pixel(q: int, r: int, size: float = 1.0) -> tuple[float, float]:
    """Pointy-top axial -> pixel center, for the frontend hex layout.

    Returned in 'size' units; the caller scales. x grows right, y grows down.
    """
    x = size * (3 ** 0.5) * (q + r / 2.0)
    y = size * 1.5 * r
    return x, y
