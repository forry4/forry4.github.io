"""The selectable duchy boards for Castles of Crimson.

Each player plays on one of several hand-authored layouts (the 9 official
Castles of Burgundy player boards). A board is a radius-3 hexagon (exactly 37
spaces) in axial coordinates ``(q, r)``. Every space has a required die
``number`` (1-6) and a ``color``; placing a hex tile on a space requires a die
matching ``number`` and a tile whose color matches the space.

Colors map to tile types:
    burgundy -> castle, blue -> ship, gray -> mine,
    green -> livestock, beige -> building, yellow -> monastery.

A "region" (scoring area) is a maximal connected component of same-colored
spaces; regions are *computed* from the layout so they are always contiguous by
construction.

Before dice are ever rolled, each player picks one of their board's burgundy
spaces and places their starting castle there. That choice is game state (in
``engine.py``), not board data — the board simply records which spaces are
burgundy.

Per-board derived data lives on a ``Board`` object (``SPACES``/``ADJACENCY``/
``REGIONS``/``REGION_OF``/``SPACES_BY_COLOR`` + ``neighbors``/``region_of``).
The registry ``BOARDS`` maps a board id ("1".."9") to a ``Board``; the engine
resolves the acting player's board via ``get_board(player["board_id"])``.

For backwards compatibility, the module also exposes ``SPACES``/``ADJACENCY``/
``REGIONS``/``neighbors``/``region_of``/... aliased to the default board so
older call sites (and the test suite) that reference ``board.SPACES`` directly
keep working.

Everything here is static, deterministic, and has no web/game dependency.
"""
from __future__ import annotations

from collections import deque

COLORS = ["burgundy", "blue", "gray", "green", "beige", "yellow"]

# Axial neighbor directions (pointy-top hex).
_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]


def space_id(q: int, r: int) -> str:
    return f"{q},{r}"


def parse_space_id(sid: str) -> tuple[int, int]:
    q, r = sid.split(",")
    return int(q), int(r)


def axial_to_pixel(q: int, r: int, size: float = 1.0) -> tuple[float, float]:
    """Pointy-top axial -> pixel center, for the frontend hex layout.

    Returned in 'size' units; the caller scales. x grows right, y grows down.
    """
    x = size * (3 ** 0.5) * (q + r / 2.0)
    y = size * 1.5 * r
    return x, y


def _connected_components(space_ids: set[str], adjacency: dict[str, list[str]]) -> list[set[str]]:
    """Connected components (via the given adjacency) of a set of spaces."""
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
            for nb in adjacency[cur]:
                if nb in space_ids and nb not in seen:
                    seen.add(nb)
                    dq.append(nb)
        comps.append(comp)
    return comps


class Board:
    """One duchy layout and its derived adjacency / regions."""

    def __init__(self, board_id: str, name: str, layout: dict[tuple[int, int], tuple[str, int]]):
        self.id = board_id
        self.name = name

        # space_id -> {"q","r","number","color","is_castle"}
        self.SPACES: dict[str, dict] = {}
        for (q, r), (color, number) in layout.items():
            sid = space_id(q, r)
            self.SPACES[sid] = {
                "q": q,
                "r": r,
                "number": number,
                "color": color,
                "is_castle": color == "burgundy",
            }

        # Precomputed adjacency restricted to existing spaces.
        self.ADJACENCY: dict[str, list[str]] = {}
        for sid, info in self.SPACES.items():
            q, r = info["q"], info["r"]
            nbrs = []
            for dq, dr in _DIRS:
                nsid = space_id(q + dq, r + dr)
                if nsid in self.SPACES:
                    nbrs.append(nsid)
            self.ADJACENCY[sid] = sorted(nbrs)

        # Regions = connected components of same-colored spaces.
        # region_id -> {"id","color","spaces":set,"size","has_castle"}
        self.REGIONS: dict[str, dict] = {}
        self.REGION_OF: dict[str, str] = {}  # space_id -> region_id
        for color in COLORS:
            color_spaces = {sid for sid, info in self.SPACES.items() if info["color"] == color}
            comps = _connected_components(color_spaces, self.ADJACENCY)
            for i, comp in enumerate(comps, start=1):
                rid = f"{color}-{i}"
                has_castle = any(self.SPACES[s]["is_castle"] for s in comp)
                self.REGIONS[rid] = {
                    "id": rid,
                    "color": color,
                    "spaces": comp,
                    "size": len(comp),
                    "has_castle": has_castle,
                }
                for s in comp:
                    self.REGION_OF[s] = rid

        # Spaces grouped by color (for color-completion / bonus-tile checks).
        self.SPACES_BY_COLOR: dict[str, set[str]] = {c: set() for c in COLORS}
        for sid, info in self.SPACES.items():
            self.SPACES_BY_COLOR[info["color"]].add(sid)

    def neighbors(self, sid: str) -> list[str]:
        return self.ADJACENCY.get(sid, [])

    def region_of(self, sid: str) -> str:
        return self.REGION_OF[sid]


# ── Board layouts ─────────────────────────────────────────────────────────────
# The 9 official Castles of Burgundy player boards, transcribed from the source
# image. Authored row-by-row (top to bottom = r -3..3) so each row lines up with
# the image for visual verification; ``_layout_from_rows`` maps a row to its
# axial (q, r) coordinates. Center (0, 0) is always the burgundy starting castle.
#
# Color codes: C=castle(burgundy) S=ship(blue) M=mine(gray)
#              P=pasture(green) B=building(beige) Y=monastery(yellow)
#
# NOTE: die numbers are a best-effort read of the image (the user verifies +
# corrects against ``tools/render_boards.py``). Same-color touching spaces form
# one scoring area, which must never exceed size 8 (enforced by test_board.py).
_CODE2COLOR = {"C": "burgundy", "S": "blue", "M": "gray", "P": "green", "B": "beige", "Y": "yellow"}

# Axial q-start per row r (-3..3) for a radius-3 hexagon (row widths 4-5-6-7-6-5-4).
_ROW_QSTART = {-3: 0, -2: -1, -1: -2, 0: -3, 1: -3, 2: -3, 3: -3}
_ROW_WIDTH = {-3: 4, -2: 5, -1: 6, 0: 7, 1: 6, 2: 5, 3: 4}


def _layout_from_rows(rows: list[list[tuple[str, int]]]) -> dict[tuple[int, int], tuple[str, int]]:
    """Map 7 rows (r = -3..3) of (code, number) cells to an axial layout dict."""
    layout: dict[tuple[int, int], tuple[str, int]] = {}
    for i, r in enumerate(range(-3, 4)):
        row = rows[i]
        assert len(row) == _ROW_WIDTH[r], f"row r={r} needs {_ROW_WIDTH[r]} cells, got {len(row)}"
        for j, (code, num) in enumerate(row):
            q = _ROW_QSTART[r] + j
            layout[(q, r)] = (_CODE2COLOR[code], num)
    return layout


# Each board: (name, 7 rows). Codes are used as-is; no cell is forced.
# Burgundy (C) spaces are where a player may place their starting castle.
_BOARD_ROWS: dict[str, tuple[str, list[list[tuple[str, int]]]]] = {
    "1": ("Starter", [
        [("P", 6), ("C", 5), ("C", 4), ("Y", 3)],
        [("P", 2), ("P", 1), ("C", 6), ("Y", 5), ("B", 4)],
        [("P", 5), ("P", 4), ("B", 3), ("Y", 1), ("B", 2), ("B", 3)],
        [("S", 6), ("S", 1), ("S", 2), ("C", 6), ("S", 5), ("S", 4), ("S", 1)],
        [("B", 2), ("B", 5), ("M", 4), ("B", 3), ("B", 1), ("P", 2)],
        [("B", 6), ("M", 1), ("Y", 2), ("B", 5), ("B", 6)],
        [("M", 3), ("Y", 4), ("Y", 1), ("B", 3)],
    ]),
    "2": ("Big City", [
        [("S", 6), ("B", 5), ("P", 4), ("C", 3)],
        [("P", 2), ("S", 1), ("B", 6), ("P", 5), ("B", 4)],
        [("P", 5), ("P", 4), ("P", 3), ("B", 1), ("Y", 2), ("B", 3)],
        [("B", 6), ("B", 1), ("B", 2), ("B", 6), ("B", 5), ("Y", 4), ("C", 1)],
        [("Y", 2), ("Y", 5), ("M", 4), ("Y", 3), ("M", 1), ("S", 2)],
        [("B", 6), ("B", 1), ("M", 2), ("Y", 5), ("S", 6)],
        [("C", 3), ("S", 4), ("S", 1), ("C", 3)],
    ]),
    "3": ("Ring of Knowledge", [
        [("P", 6), ("P", 5), ("P", 4), ("P", 3)],
        [("S", 2), ("S", 1), ("C", 6), ("S", 5), ("S", 4)],
        [("B", 5), ("M", 4), ("Y", 3), ("Y", 1), ("S", 2), ("B", 3)],
        [("B", 6), ("B", 1), ("Y", 2), ("C", 6), ("Y", 5), ("B", 4), ("B", 1)],
        [("B", 2), ("B", 5), ("Y", 4), ("Y", 3), ("B", 1), ("B", 2)],
        [("C", 6), ("P", 1), ("M", 2), ("M", 5), ("C", 6)],
        [("B", 3), ("P", 4), ("S", 1), ("B", 3)],
    ]),
    "4": ("Twin Cities", [
        [("C", 6), ("P", 5), ("B", 4), ("S", 3)],
        [("P", 2), ("P", 1), ("B", 6), ("S", 2), ("S", 4)],
        [("B", 5), ("B", 4), ("B", 3), ("S", 1), ("C", 2), ("M", 3)],
        [("P", 6), ("P", 1), ("P", 2), ("Y", 6), ("Y", 5), ("M", 4), ("S", 1)],
        [("B", 2), ("C", 5), ("Y", 4), ("B", 3), ("B", 1), ("B", 2)],
        [("B", 6), ("M", 1), ("B", 2), ("Y", 5), ("Y", 6)],
        [("S", 3), ("B", 4), ("Y", 1), ("C", 3)],
    ]),
    "5": ("One, Two, Three", [
        [("P", 6), ("B", 5), ("B", 4), ("S", 3)],
        [("P", 2), ("P", 1), ("B", 6), ("M", 5), ("M", 4)],
        [("B", 5), ("C", 4), ("Y", 3), ("S", 1), ("S", 2), ("S", 3)],
        [("B", 6), ("B", 1), ("P", 2), ("Y", 6), ("C", 5), ("B", 4), ("B", 1)],
        [("Y", 2), ("C", 5), ("P", 4), ("Y", 3), ("S", 1), ("B", 2)],
        [("B", 6), ("P", 1), ("B", 2), ("C", 5), ("S", 6)],
        [("Y", 3), ("Y", 4), ("B", 1), ("M", 3)],
    ]),
    "6": ("Big River", [
        [("Y", 6), ("Y", 5), ("C", 4), ("S", 3)],
        [("Y", 2), ("B", 1), ("B", 6), ("S", 5), ("B", 4)],
        [("P", 5), ("P", 4), ("M", 3), ("S", 1), ("B", 2), ("B", 3)],
        [("Y", 6), ("B", 1), ("B", 2), ("C", 6), ("S", 5), ("B", 4), ("B", 1)],
        [("Y", 2), ("B", 5), ("B", 4), ("M", 3), ("S", 1), ("B", 2)],
        [("Y", 6), ("M", 1), ("P", 2), ("P", 5), ("S", 6)],
        [("C", 3), ("P", 4), ("P", 1), ("C", 3)],
    ]),
    "7": ("Central City", [
        [("Y", 6), ("C", 5), ("C", 4), ("S", 3)],
        [("Y", 2), ("P", 1), ("P", 6), ("P", 5), ("S", 4)],
        [("S", 5), ("M", 4), ("B", 3), ("B", 1), ("M", 2), ("P", 3)],
        [("S", 6), ("Y", 1), ("B", 2), ("B", 6), ("B", 5), ("P", 4), ("B", 1)],
        [("B", 2), ("Y", 5), ("B", 4), ("B", 3), ("P", 1), ("B", 2)],
        [("B", 6), ("S", 1), ("M", 2), ("Y", 5), ("B", 6)],
        [("S", 3), ("C", 4), ("C", 1), ("Y", 3)],
    ]),
    "8": ("Outer Cities", [
        [("B", 6), ("B", 5), ("S", 4), ("B", 3)],
        [("S", 2), ("C", 1), ("Y", 6), ("C", 5), ("B", 4)],
        [("B", 5), ("Y", 4), ("M", 3), ("Y", 1), ("Y", 2), ("S", 3)],
        [("B", 6), ("P", 1), ("Y", 2), ("M", 6), ("P", 5), ("Y", 4), ("B", 1)],
        [("S", 2), ("P", 5), ("P", 4), ("P", 3), ("M", 1), ("B", 2)],
        [("B", 6), ("C", 1), ("P", 2), ("C", 5), ("S", 6)],
        [("B", 3), ("S", 4), ("B", 1), ("B", 3)],
    ]),
    "9": ("Two Cities", [
        [("B", 6), ("B", 5), ("C", 4), ("Y", 3)],
        [("B", 2), ("B", 1), ("P", 6), ("P", 5), ("S", 4)],
        [("B", 5), ("B", 4), ("P", 3), ("P", 1), ("S", 2), ("S", 3)],
        [("C", 6), ("Y", 1), ("Y", 2), ("M", 6), ("S", 5), ("C", 4), ("Y", 1)],
        [("S", 2), ("S", 5), ("Y", 4), ("M", 3), ("B", 1), ("P", 2)],
        [("Y", 6), ("B", 1), ("B", 2), ("B", 5), ("P", 6)],
        [("M", 3), ("C", 4), ("B", 1), ("B", 3)],
    ]),
}

_LAYOUTS: dict[str, tuple[str, dict[tuple[int, int], tuple[str, int]]]] = {
    bid: (name, _layout_from_rows(rows)) for bid, (name, rows) in _BOARD_ROWS.items()
}

BOARDS: dict[str, Board] = {bid: Board(bid, name, layout) for bid, (name, layout) in _LAYOUTS.items()}

DEFAULT_BOARD_ID = "1"


def get_board(board_id: str | None) -> Board:
    """Resolve a board id to a Board, falling back to the default board."""
    return BOARDS.get(board_id, BOARDS[DEFAULT_BOARD_ID])


def board_list() -> list[dict]:
    """Lightweight listing for the lobby/board-picker (id + name only)."""
    return [{"id": b.id, "name": b.name} for b in BOARDS.values()]


# ── Backwards-compat module-level aliases (default board) ─────────────────────
# Older call sites and the test suite reference ``board.SPACES`` etc. directly.
_default = BOARDS[DEFAULT_BOARD_ID]
SPACES = _default.SPACES
ADJACENCY = _default.ADJACENCY
REGIONS = _default.REGIONS
REGION_OF = _default.REGION_OF
SPACES_BY_COLOR = _default.SPACES_BY_COLOR


def neighbors(sid: str) -> list[str]:
    return _default.neighbors(sid)


def region_of(sid: str) -> str:
    return _default.region_of(sid)
