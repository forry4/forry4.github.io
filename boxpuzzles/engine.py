"""Box Puzzles rules — a 3x3 box of coloured tiles and four corner buttons.

THIS IS A PORT, and the reference is chandler.io's Mora Jai simulator (its WASM,
driven directly). `engine.js` beside this file is the same rules for the browser,
and `tests/fixtures/parity.json` holds the reference's own answers, which BOTH
engines are tested against — so the three cannot drift apart without a test going
red. Regenerate the fixtures with `tools/gen_parity_fixtures.mjs`.

The board is nine colour codes, row-major (index 0 is top-left). Pressing a tile
applies ITS colour's rule; pressing a corner button lights it if that corner tile
shows the button's colour, and resets the box to its starting board if it does not.
A lit button goes dark the moment its tile stops matching, so the box opens exactly
when all four corner tiles match at once and each button has been pressed. That is
why the server only needs tile presses to check a solve: the buttons add nothing a
player could get wrong once the corners match.

The rules, as the reference implements them:
  GY gray    nothing
  WH white   itself and each orthogonal neighbour of ITS colour turn gray; each
             gray neighbour turns its colour
  PU violet  swaps with the tile below
  YE yellow  swaps with the tile above
  GN green   swaps with the tile opposite it through the centre
  PI pink    rotates the (up to eight) surrounding tiles one step clockwise
  BK black   rotates its row one step to the right
  RD red     every white tile turns black, and every black tile turns ITS colour
  OR orange  turns the colour that most orthogonal neighbours share, when exactly
             one colour has the most (a tie changes nothing)
  BU blue    does whatever the CENTRE tile's colour does, from where it stands

"Its colour" in WH and RD is the PRESSED tile's colour, and it only differs from
white/red when a blue tile is borrowing the rule: a blue copying white toggles
blue<->gray and leaves white tiles alone, and a blue copying red turns black tiles
blue. Those are the quirks the reference calls out, and four of the 71 boxes are
unsolvable without them.
"""
from __future__ import annotations

from collections import deque

COLORS = ("GY", "WH", "PU", "YE", "GN", "PI", "BK", "RD", "OR", "BU")
# Corner button k sits at corner tile CORNERS[k], clockwise from the top-left, and a
# puzzle's four target colours are listed in the same order.
CORNERS = (0, 2, 8, 6)


def _ortho(i: int) -> tuple[int, ...]:
    r, c = divmod(i, 3)
    out = []
    if r > 0:
        out.append(i - 3)
    if c < 2:
        out.append(i + 1)
    if r < 2:
        out.append(i + 3)
    if c > 0:
        out.append(i - 1)
    return tuple(out)


# The surrounding ring, clockwise from the top-left, clipped to the board.
_RING_STEPS = ((-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1))


def _ring(i: int) -> tuple[int, ...]:
    r, c = divmod(i, 3)
    return tuple((r + dr) * 3 + (c + dc) for dr, dc in _RING_STEPS
                 if 0 <= r + dr < 3 and 0 <= c + dc < 3)


ORTHO = tuple(_ortho(i) for i in range(9))
RING = tuple(_ring(i) for i in range(9))


def press(tiles, i: int) -> tuple:
    """The board after pressing tile `i`. Never mutates its input."""
    t = list(tiles)
    me = t[i]
    act = t[4] if me == "BU" else me
    if act == "WH":
        for j in (i, *ORTHO[i]):
            if t[j] == me:
                t[j] = "GY"
            elif t[j] == "GY":
                t[j] = me
    elif act == "PU":
        if i < 6:
            t[i], t[i + 3] = t[i + 3], t[i]
    elif act == "YE":
        if i >= 3:
            t[i], t[i - 3] = t[i - 3], t[i]
    elif act == "GN":
        t[i], t[8 - i] = t[8 - i], t[i]
    elif act == "PI":
        ring = RING[i]
        vals = [t[j] for j in ring]
        for k, j in enumerate(ring):
            t[j] = vals[k - 1]
    elif act == "BK":
        r = i - i % 3
        t[r], t[r + 1], t[r + 2] = t[r + 2], t[r], t[r + 1]
    elif act == "RD":
        for j in range(9):
            if t[j] == "WH":
                t[j] = "BK"
            elif t[j] == "BK":
                t[j] = me
    elif act == "OR":
        counts: dict[str, int] = {}
        for j in ORTHO[i]:
            counts[t[j]] = counts.get(t[j], 0) + 1
        top = max(counts.values())
        leaders = [c for c, n in counts.items() if n == top]
        if len(leaders) == 1:
            t[i] = leaders[0]
    # GY, and a blue tile whose centre is blue (or gray), do nothing.
    return tuple(t)


def corners_match(tiles, target) -> bool:
    return all(tiles[c] == target[k] for k, c in enumerate(CORNERS))


def replay(start, moves) -> tuple:
    """Apply a list of tile presses to `start`. Raises ValueError on a bad move."""
    t = tuple(start)
    for m in moves:
        if not isinstance(m, int) or isinstance(m, bool) or not 0 <= m <= 8:
            raise ValueError(f"not a tile: {m!r}")
        t = press(t, m)
    return t


def solve(start, target, limit: int = 2_000_000) -> list[int] | None:
    """A shortest list of tile presses that makes all four corners match, by
    breadth-first search. None if no board within `limit` states does."""
    start = tuple(start)
    if corners_match(start, target):
        return []
    prev: dict[tuple, tuple | None] = {start: None}
    q = deque([start])
    while q:
        t = q.popleft()
        for i in range(9):
            u = press(t, i)
            if u in prev:
                continue
            prev[u] = (t, i)
            if corners_match(u, target):
                path = []
                while prev[u] is not None:
                    u, step = prev[u]
                    path.append(step)
                return path[::-1]
            if len(prev) > limit:
                return None
            q.append(u)
    return None
