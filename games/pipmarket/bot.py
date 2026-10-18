"""The Pip Market opponent — the heuristic measured in the design simulation.

Auction: every legal (column, placement) is scored by how much it raises a
board VALUE, minus its price; taking money is worth 2 (money is points at the
end). The value of a board is, per straight row/column:

* a run already long enough to score is worth its points plus the money its
  line would pay (+1 / +5 / about +10 for "set to 18"), and
* a run still too short is POTENTIAL — what the finished line would be worth,
  scaled by (length / face)^2 — but only if the line still has room to reach
  that length without the board spanning more than 6x6.

Potential is discounted (``POT_W``) and, in the final round, shrinks with the
market: an unfinished line is worth nothing once there is nothing left to buy.

Scoring: the order of removals that maximises points + money is found by an
exhaustive search over this board (boards are small), and the bot plays its
first line, re-planning every turn.

All of it is deterministic except tie-breaks, which draw from the scheduler's
seed so the bot cannot be learned by rote.
"""

from __future__ import annotations

import random
from functools import lru_cache

from . import engine

POT_W = 0.5
MONEY_VALUE = 1.0
SPAN = engine.SPAN


def _money_equiv(points: int) -> int:
    return 10 if points >= 30 else 5 if points >= 15 else 1


@lru_cache(maxsize=200_000)
def _line_value(cells: tuple, is_col: bool) -> tuple[float, float]:
    """(realised, potential) for one line, given only the cells it may still grow
    into (0 = empty). 1s count in rows only, so a lone 1 is not valued twice."""
    real = pot = 0.0
    n = len(cells)
    i = 0
    while i < n:
        f = cells[i]
        if f == 0:
            i += 1
            continue
        j = i
        while j < n and cells[j] == f:
            j += 1
        length = j - i
        if f == 1:
            if not is_col:
                real += 2 * length
            i = j
            continue
        lo = i
        while lo > 0 and cells[lo - 1] in (0, f):
            lo -= 1
        hi = j
        while hi < n and cells[hi] in (0, f):
            hi += 1
        if length >= f:
            real += f * length + _money_equiv(f * length)
        elif hi - lo >= f:
            pot += (f * f + _money_equiv(f * f)) * (length / f) ** 2
        i = j
    return real, pot


def board_value(grid: dict, w: float) -> float:
    if not grid:
        return 0.0
    rows = [r for r, _ in grid]
    cols = [c for _, c in grid]
    r0, r1, c0, c1 = min(rows), max(rows), min(cols), max(cols)
    # The cells each line may still grow into without the board passing 6 wide.
    clo, chi = c1 - SPAN + 1, c0 + SPAN - 1
    rlo, rhi = r1 - SPAN + 1, r0 + SPAN - 1
    total = 0.0
    for r in range(r0, r1 + 1):
        real, pot = _line_value(tuple(grid.get((r, c), 0) for c in range(clo, chi + 1)), False)
        total += real + w * pot
    for c in range(c0, c1 + 1):
        real, pot = _line_value(tuple(grid.get((r, c), 0) for r in range(rlo, rhi + 1)), True)
        total += real + w * pot
    return total


def _potential_weight(game: dict) -> float:
    if game["round"] < engine.ROUNDS:
        return POT_W
    return POT_W * engine.market_left(game) / max(1, game.get("round_dice") or 1)


def choose_auction(game: dict, pid: str, rng: random.Random) -> dict:
    board = game["boards"][pid]
    grid = {(d["r"], d["c"]): d["f"] for d in board}
    money = game["money"][pid]
    w = _potential_weight(game)
    base = board_value(grid, w)
    cache: dict[tuple, tuple[float, tuple] | None] = {}
    best: tuple[float, float, dict] | None = None
    for s, cols in enumerate(game["market"]):
        for c, col in enumerate(cols):
            price = c + 1
            if price > money:
                break
            faces = tuple(d["f"] for d in col)
            if faces not in cache:
                found = None
                for cells in engine.placements(board, len(faces)):
                    trial = dict(grid)
                    for cell, f in zip(cells, faces):
                        trial[cell] = f
                    gain = board_value(trial, w) - base
                    if found is None or gain > found[0]:
                        found = (gain, cells)
                cache[faces] = found
            found = cache[faces]
            if found is None:
                continue
            value = found[0] - MONEY_VALUE * price
            tie = rng.random()
            if best is None or (value, tie) > (best[0], best[1]):
                best = (value, tie, {"type": "buy", "set": s, "col": c,
                                     "cells": [list(cell) for cell in found[1]]})
    if engine.can_take(game, pid):
        take = MONEY_VALUE * min(engine.TAKE_AMOUNT, engine.MAX_MONEY - money)
        if best is None or take > best[0]:
            return {"type": "take"}
    if best is None:
        return {"type": "take"}
    return best[2]


def best_scoring(board: list[dict], money: int) -> tuple[int, list[list[list[int]]]]:
    """The removal order maximising points + money. Returns (value, [cells, ...])."""
    memo: dict = {}

    def rec(cur: list[dict], m: int):
        key = (frozenset((d["r"], d["c"], d["f"]) for d in cur), m)
        if key in memo:
            return memo[key]
        best = (0, [])
        for line in engine.scoring_lines(cur):
            gone = {tuple(cell) for cell in line["cells"]}
            rest = [d for d in cur if (d["r"], d["c"]) not in gone]
            nm = engine.money_after(line["points"], m)
            sub = rec(rest, nm)
            value = line["points"] + (nm - m) + sub[0]
            if value > best[0]:
                best = (value, [line["cells"]] + sub[1])
        memo[key] = best
        return best

    return rec(list(board), money)


def choose_scoring(game: dict, pid: str) -> dict:
    _, plan = best_scoring(game["boards"][pid], game["money"][pid])
    if not plan:
        return {"type": "pass"}
    return {"type": "score", "cells": plan[0]}


def choose_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    if engine.to_act(game) != pid:
        return None
    if game["phase"] == "auction":
        return choose_auction(game, pid, random.Random(seed))
    return choose_scoring(game, pid)
