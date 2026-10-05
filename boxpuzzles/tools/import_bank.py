"""Build the Box Puzzles bank from chandler.io's Mora Jai simulator data.

    python -m boxpuzzles.tools.import_bank <path to morajai.json>

The source is the JSON the simulator page loads (`/js/morajai.<hash>.json` on
chandler.io/posts/2025/07/mora-jai-box-simulator/). Only its `puzzles` list is
used — the 71 boxes from the game. Its `puzzles_challenge` list is the author's own
computer-found designs, and is deliberately left out.

WRITES TWO FILES, and the split is the point:
  * `puzzles.json` — what the browser gets: each box's id, starting tiles and four
    corner targets, ordered easiest first. No names (the site's boxes are not tied
    to the game) and NO MINIMUMS: the leaderboard tells only the player who reached
    a box's minimum that they did, so the minimum must not ship in the bundle.
  * `minimums.json` — id -> fewest tile presses, read by the server alone.

Order is difficulty: fewest presses first, then the box with MORE shortest
solutions first (more ways in is easier), then the source order. Ids are the board
itself (`<tiles>-<targets>`), so a re-sort renumbers the boxes without orphaning a
single leaderboard row.
"""
from __future__ import annotations

import json
import pathlib
import sys

from boxpuzzles.engine import corners_match, press, solve

HERE = pathlib.Path(__file__).resolve().parents[1]


def puzzle_id(tiles, target) -> str:
    return "".join(tiles) + "-" + "".join(target)


def shortest_solution_count(start, target) -> int:
    """How many distinct shortest press sequences open the box (layered BFS)."""
    start = tuple(start)
    if corners_match(start, target):
        return 1
    layer = {start: 1}
    seen = {start}
    while layer:
        nxt: dict[tuple, int] = {}
        for t, n in layer.items():
            for i in range(9):
                u = press(t, i)
                if u in seen:
                    continue
                nxt[u] = nxt.get(u, 0) + n
        seen.update(nxt)
        hits = sum(n for u, n in nxt.items() if corners_match(u, target))
        if hits:
            return hits
        layer = nxt
    return 0


def main(src: str) -> None:
    raw = json.loads(pathlib.Path(src).read_text(encoding="utf-8"))["puzzles"]
    rows = []
    for order, p in enumerate(raw):
        target = p["target"] if isinstance(p["target"], list) else [p["target"]] * 4
        tiles = list(p["tiles"])
        path = solve(tiles, target)
        if path is None:
            raise SystemExit(f"unsolvable box in the source: {tiles} -> {target}")
        rows.append({"id": puzzle_id(tiles, target), "tiles": tiles, "target": target,
                     "min": len(path), "ways": shortest_solution_count(tiles, target),
                     "order": order})
    rows.sort(key=lambda r: (r["min"], -r["ways"], r["order"]))
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit("two boxes share a board")
    bank = [{"id": r["id"], "tiles": r["tiles"], "target": r["target"]} for r in rows]
    (HERE / "puzzles.json").write_text(
        "[\n" + ",\n".join(json.dumps(b, separators=(",", ":")) for b in bank) + "\n]\n",
        encoding="utf-8")
    (HERE / "minimums.json").write_text(
        json.dumps({r["id"]: r["min"] for r in rows}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(bank)} boxes; minimums {rows[0]['min']}..{rows[-1]['min']}")


if __name__ == "__main__":
    main(sys.argv[1])
