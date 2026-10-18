"""Pip Market — the rules authority.

A dice auction for 2-4 players. Every die on the table has a stable integer
``id`` so the client can follow it from the market to a board, from a board to
the cup, and back into the market after the reroll; the faces change, the ids
never do.

Shape of ``game`` (JSON-safe; ``player_view`` strips only ``seed``):

    players   seat order (shuffled at the deal); players[0] moves first in round 1
    names     {pid: display name}
    round     1..3
    phase     "auction" | "scoring" | "over"
    turn      the pid to act (None once over)
    market    [set][column] -> [die, die?]  — a column's price is its index + 1
    boards    {pid: [{"id", "f", "r", "c"}]}  — normalised so min r = min c = 0
    money     {pid: 0..18}
    points    {pid: int}
    cup       dice scored this round, waiting for the reroll
    passed    pids with nothing left to score this round (scoring is compulsory)
    rerolled  pids who have used their one column reroll this round
    reroll_count  rerolls so far this game (salts each reroll's dice)
    last_buyer   the pid who bought the most recent column (goes first next round)

Randomness: the deal, each round's reroll and each paid column reroll draw from
``Random(f"{seed}:<salt>")``, so no generator state is persisted.
"""

from __future__ import annotations

import copy
import random

MIN_PLAYERS = 2
MAX_PLAYERS = 4
MAX_MONEY = 18
TAKE_AMOUNT = 2
SPAN = 6
ROUNDS = 3
PAIRS_PER_SET = 5
FIRST_SEAT_MONEY = 10
OTHER_SEAT_MONEY = 12
LOG_CAP = 400
SCHEMA = 1


def set_count(n_players: int) -> int:
    """Two players use three market sets; each extra player adds one."""
    return n_players + 1


def total_dice(n_players: int) -> int:
    return set_count(n_players) * PAIRS_PER_SET * 2


def money_after(points: int, money: int) -> int:
    """The money a scored line leaves you with: +1, +5 at 15+, set to 18 at 30+."""
    if points >= 30:
        return MAX_MONEY
    return min(MAX_MONEY, money + (5 if points >= 15 else 1))


# ── geometry ────────────────────────────────────────────────────────────────

def _grid(board: list[dict]) -> dict[tuple[int, int], dict]:
    return {(d["r"], d["c"]): d for d in board}


def _neighbours(r: int, c: int):
    return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))


def _fits(cells) -> bool:
    rows = [r for r, _ in cells]
    cols = [c for _, c in cells]
    return not rows or (max(rows) - min(rows) < SPAN and max(cols) - min(cols) < SPAN)


def _connected(cells: set) -> bool:
    if len(cells) <= 1:
        return True
    start = next(iter(cells))
    seen = {start}
    stack = [start]
    while stack:
        r, c = stack.pop()
        for q in _neighbours(r, c):
            if q in cells and q not in seen:
                seen.add(q)
                stack.append(q)
    return len(seen) == len(cells)


def _normalise(board: list[dict]) -> None:
    if not board:
        return
    r0 = min(d["r"] for d in board)
    c0 = min(d["c"] for d in board)
    for d in board:
        d["r"] -= r0
        d["c"] -= c0


def placement_ok(board: list[dict], cells: list[tuple[int, int]]) -> bool:
    """May these cells (1 or 2, a pair in order) take new dice on this board?"""
    if not cells or len(cells) > 2 or len(set(cells)) != len(cells):
        return False
    occupied = set(_grid(board))
    if any(cell in occupied for cell in cells):
        return False
    if len(cells) == 2:
        (r1, c1), (r2, c2) = cells
        if abs(r1 - r2) + abs(c1 - c2) != 1:
            return False
    if occupied and not any(q in occupied for r, c in cells for q in _neighbours(r, c)):
        return False
    return _fits(list(occupied) + list(cells))


def placements(board: list[dict], k: int) -> list[tuple[tuple[int, int], ...]]:
    """Every legal placement of k (1 or 2) new dice. On an empty board every spot
    is the same spot, so only the origin is offered."""
    occupied = set(_grid(board))
    if not occupied:
        return [((0, 0),)] if k == 1 else [((0, 0), (0, 1)), ((0, 0), (1, 0)),
                                           ((0, 1), (0, 0)), ((1, 0), (0, 0))]
    frontier = {q for r, c in occupied for q in _neighbours(r, c) if q not in occupied}
    out = []
    if k == 1:
        for p in sorted(frontier):
            if _fits(list(occupied) + [p]):
                out.append((p,))
        return out
    seen = set()
    for p in sorted(frontier):
        for q in _neighbours(*p):
            if q in occupied:
                continue
            for pair in ((p, q), (q, p)):
                if pair in seen:
                    continue
                seen.add(pair)
                if _fits(list(occupied) + [p, q]):
                    out.append(pair)
    return out


def can_place(board: list[dict], k: int) -> bool:
    return bool(placements(board, k))


def scoring_lines(board: list[dict]) -> list[dict]:
    """Every line this board may score right now: a straight unbroken run of one
    face at least as long as the face (a sub-run is fine) whose removal leaves
    the board connected. 1s are offered one at a time — removing a run of 1s
    together scores the same points for less money."""
    grid = _grid(board)
    cells = set(grid)
    out = []
    seen = set()

    def runs(axis):
        lines = {}
        for (r, c) in grid:
            lines.setdefault(r if axis == 0 else c, []).append(c if axis == 0 else r)
        for key, positions in lines.items():
            positions.sort()
            i = 0
            while i < len(positions):
                face = grid[(key, positions[i]) if axis == 0 else (positions[i], key)]["f"]
                j = i
                while (j + 1 < len(positions) and positions[j + 1] == positions[j] + 1
                       and grid[(key, positions[j + 1]) if axis == 0 else (positions[j + 1], key)]["f"] == face):
                    j += 1
                run = [((key, p) if axis == 0 else (p, key)) for p in positions[i:j + 1]]
                yield face, run
                i = j + 1

    for axis in (0, 1):
        for face, run in runs(axis):
            if len(run) < face:
                continue
            lengths = [1] if face == 1 else range(face, len(run) + 1)
            for k in lengths:
                for o in range(len(run) - k + 1):
                    seg = tuple(run[o:o + k])
                    key = frozenset(seg)
                    if key in seen:
                        continue
                    seen.add(key)
                    if not _connected(cells - key):
                        continue
                    pts = face * k
                    out.append({"cells": [list(cell) for cell in seg], "face": face,
                                "count": k, "points": pts,
                                "money": "max" if pts >= 30 else (5 if pts >= 15 else 1)})
    out.sort(key=lambda line: (-line["points"], -line["count"], line["cells"]))
    return out


def _line_of(board: list[dict], cells) -> dict | None:
    """Validate a requested line; returns {"face", "points"} or None."""
    if not isinstance(cells, list) or not cells:
        return None
    try:
        seg = [(int(r), int(c)) for r, c in cells]
    except (TypeError, ValueError):
        return None
    if len(set(seg)) != len(seg):
        return None
    grid = _grid(board)
    if any(cell not in grid for cell in seg):
        return None
    face = grid[seg[0]]["f"]
    if any(grid[cell]["f"] != face for cell in seg) or len(seg) < face:
        return None
    rows = {r for r, _ in seg}
    cols = {c for _, c in seg}
    if len(rows) == 1:
        span = sorted(c for _, c in seg)
    elif len(cols) == 1:
        span = sorted(r for r, _ in seg)
    else:
        return None
    if span[-1] - span[0] != len(seg) - 1:
        return None
    if not _connected(set(grid) - set(seg)):
        return None
    return {"face": face, "points": face * len(seg)}


# ── setup ───────────────────────────────────────────────────────────────────

def _deal(dice: list[dict], n_sets: int) -> list[list[list[dict]]]:
    """Fill the stalls as evenly as possible: every stall gets n // S dice, the
    first n % S one more, so no two stalls differ by more than a die. Within a
    stall the dice stand in vertical pairs, and a stall with an odd count ends on
    a single die. (Dealing PAIRS round-robin instead left 17 dice over five stalls
    as 4/4/4/3/2.)"""
    base, extra = divmod(len(dice), n_sets)
    market = []
    at = 0
    for s in range(n_sets):
        take = base + (1 if s < extra else 0)
        mine = dice[at:at + take]
        at += take
        market.append([mine[k:k + 2] for k in range(0, len(mine), 2)])
    return market


def new_game(player_ids, names: dict | None = None, seed: int | None = None) -> dict:
    players = list(player_ids)
    if not MIN_PLAYERS <= len(players) <= MAX_PLAYERS or len(set(players)) != len(players):
        raise ValueError("Pip Market seats two to four players")
    if seed is None:
        seed = random.randrange(2 ** 31)
    rng = random.Random(f"{seed}:deal")
    rng.shuffle(players)
    n = len(players)
    dice = [{"id": i, "f": rng.randint(1, 6)} for i in range(total_dice(n))]
    game = {
        "schema": SCHEMA,
        "players": players,
        "names": {pid: str((names or {}).get(pid) or pid) for pid in players},
        "seed": int(seed),
        "round": 1,
        "phase": "auction",
        "turn": players[0],
        "first": players[0],
        "market": _deal(dice, set_count(n)),
        "boards": {pid: [] for pid in players},
        # The first seat starts on 10 to pay for moving first; everyone else on 12.
        "money": {pid: FIRST_SEAT_MONEY if i == 0 else OTHER_SEAT_MONEY
                  for i, pid in enumerate(players)},
        "points": {pid: 0 for pid in players},
        "cup": [],
        "passed": [],
        "rerolled": [],
        "reroll_count": 0,
        "last_buyer": None,
        "round_dice": len(dice),
        "round_scored": 0,
        "stats": {pid: {"lines": 0, "best": 0, "takes": 0, "buys": 0, "rerolls": 0}
                  for pid in players},
        "final": None,
        "winners": [],
        "conceded": None,
        "event_seq": 0,
        "log": [],
    }
    _log(game, "deal", round=1, first=players[0])
    return game


def validate_state(game: dict) -> None:
    """Cheap shape check run when a saved room is loaded."""
    for key in ("players", "market", "boards", "money", "points", "phase", "round"):
        if key not in game:
            raise ValueError(f"Pip Market state is missing {key}")


# ── queries ─────────────────────────────────────────────────────────────────

def is_over(game: dict | None) -> bool:
    return bool(game) and game.get("phase") == "over"


def to_act(game: dict | None) -> str | None:
    if not game or is_over(game):
        return None
    return game.get("turn")


def market_left(game: dict) -> int:
    return sum(len(col) for cols in game["market"] for col in cols)


def buyable_columns(game: dict, pid: str) -> list[list[int]]:
    """[set, column] pairs this player can afford AND place."""
    money = game["money"][pid]
    board = game["boards"][pid]
    fits = {1: None, 2: None}
    out = []
    for s, cols in enumerate(game["market"]):
        for c, col in enumerate(cols):
            if c + 1 > money:
                break
            k = len(col)
            if fits[k] is None:
                fits[k] = can_place(board, k)
            if fits[k]:
                out.append([s, c])
    return out


def can_take(game: dict, pid: str) -> bool:
    return game["money"][pid] < MAX_MONEY


def _fill(game: dict) -> None:
    """Keys added after the first release; a game saved before them gains them here."""
    game.setdefault("rerolled", [])
    game.setdefault("reroll_count", 0)


def rerollable_columns(game: dict, pid: str) -> list[int]:
    """Column positions this player may pay to reroll: once per round, a price
    they can afford, and at least one die standing in that position somewhere.

    Once per round is the anti-stall rule. Without it a player could alternate
    "reroll column 2" (-2) and "take 2 money" (+2) forever and the market would
    never empty."""
    if pid in game.get("rerolled", []):
        return []
    money = game["money"][pid]
    deepest = max((len(cols) for cols in game["market"]), default=0)
    return [c for c in range(min(deepest, money))]


def can_reroll(game: dict, pid: str) -> bool:
    return bool(rerollable_columns(game, pid))


def has_auction_action(game: dict, pid: str) -> bool:
    return can_take(game, pid) or bool(buyable_columns(game, pid)) or can_reroll(game, pid)


def legal_moves(game: dict | None, pid: str) -> list[dict]:
    """A SUMMARY of what pid may do — not every placement (those are geometry the
    caller enumerates with ``placements``). Non-empty exactly when it is pid's turn."""
    if not game or to_act(game) != pid:
        return []
    if game["phase"] == "auction":
        moves = [{"type": "buy", "set": s, "col": c} for s, c in buyable_columns(game, pid)]
        if can_take(game, pid):
            moves.append({"type": "take"})
        moves += [{"type": "reroll", "col": c} for c in rerollable_columns(game, pid)]
        return moves
    # Scoring is compulsory: the turn only reaches a player who has a line.
    return [{"type": "score", "cells": line["cells"]} for line in scoring_lines(game["boards"][pid])]


def totals(game: dict) -> dict:
    return {pid: game["points"][pid] + game["money"][pid] for pid in game["players"]}


# ── moves ───────────────────────────────────────────────────────────────────

def _log(game: dict, kind: str, **fields) -> None:
    game["event_seq"] = int(game.get("event_seq", 0)) + 1
    game["log"].append({"seq": game["event_seq"], "kind": kind, **fields})
    if len(game["log"]) > LOG_CAP:
        del game["log"][:len(game["log"]) - LOG_CAP]


def _cycle(game: dict, pid: str, inclusive: bool) -> list[str]:
    order = game["players"]
    i = order.index(pid)
    n = len(order)
    steps = range(0, n) if inclusive else range(1, n + 1)
    return [order[(i + k) % n] for k in steps]


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if not isinstance(move, dict):
        return False, "bad move"
    if is_over(game):
        return False, "the game is over"
    if pid not in game["players"]:
        return False, "not seated"
    if game["turn"] != pid:
        return False, "not your turn"
    kind = move.get("type")
    _fill(game)
    if game["phase"] == "auction":
        if kind == "take":
            return _take(game, pid)
        if kind == "buy":
            return _buy(game, pid, move)
        if kind == "reroll":
            return _reroll(game, pid, move)
        return False, "the market is open — buy a column, take money or reroll a column"
    if game["phase"] == "scoring":
        if kind == "score":
            return _score(game, pid, move)
        if kind == "pass":
            return False, "you must score while you have a line"
        return False, "score one of your lines"
    return False, "unknown phase"


def _take(game: dict, pid: str):
    money = game["money"][pid]
    if money >= MAX_MONEY:
        return False, "you hold the maximum 18 — buy or reroll instead"
    gained = min(TAKE_AMOUNT, MAX_MONEY - money)
    game["money"][pid] = money + gained
    game["stats"][pid]["takes"] += 1
    _log(game, "take", pid=pid, amount=gained, money=game["money"][pid])
    _settle_auction(game, pid, inclusive=False)
    return True, None


def _reroll(game: dict, pid: str, move: dict):
    """Pay a column's price to reroll the dice standing in that position in EVERY
    stall. The dice keep their ids and their places; only the faces change."""
    try:
        c = int(move.get("col"))
    except (TypeError, ValueError):
        return False, "no such column"
    if pid in game["rerolled"]:
        return False, "you have already rerolled this round"
    if c < 0 or not any(len(cols) > c for cols in game["market"]):
        return False, "no dice stand in that column"
    price = c + 1
    if price > game["money"][pid]:
        return False, "you cannot afford that reroll"
    game["reroll_count"] += 1
    rng = random.Random(f"{game['seed']}:reroll:{game['reroll_count']}")
    dice = [die for cols in game["market"] if len(cols) > c for die in cols[c]]
    for die in dice:
        die["f"] = rng.randint(1, 6)
    game["money"][pid] -= price
    game["rerolled"].append(pid)
    game["stats"][pid].setdefault("rerolls", 0)
    game["stats"][pid]["rerolls"] += 1
    _log(game, "reroll", pid=pid, col=c, price=price,
         dice=[die["id"] for die in dice], faces=[die["f"] for die in dice])
    _settle_auction(game, pid, inclusive=False)
    return True, None


def _buy(game: dict, pid: str, move: dict):
    try:
        s, c = int(move.get("set")), int(move.get("col"))
    except (TypeError, ValueError):
        return False, "no such column"
    if not 0 <= s < len(game["market"]) or not 0 <= c < len(game["market"][s]):
        return False, "no such column"
    cols = game["market"][s]
    col = cols[c]
    price = c + 1
    if price > game["money"][pid]:
        return False, "you cannot afford that column"
    try:
        cells = [(int(r), int(cc)) for r, cc in move.get("cells") or []]
    except (TypeError, ValueError):
        return False, "bad placement"
    if len(cells) != len(col) or any(abs(v) > 12 for cell in cells for v in cell):
        return False, "bad placement"
    board = game["boards"][pid]
    if not placement_ok(board, cells):
        return False, "those dice cannot go there"
    del cols[c]
    for die, (r, cc) in zip(col, cells):
        board.append({"id": die["id"], "f": die["f"], "r": r, "c": cc})
    _normalise(board)
    game["money"][pid] -= price
    game["last_buyer"] = pid
    game["stats"][pid]["buys"] += 1
    _log(game, "buy", pid=pid, set=s, col=c, price=price,
         dice=[die["id"] for die in col], faces=[die["f"] for die in col])
    _settle_auction(game, pid, inclusive=False)
    return True, None


def _settle_auction(game: dict, after: str, inclusive: bool) -> None:
    """Hand the turn to the next player able to act, or close the market."""
    if not market_left(game):
        game["market"] = [[] for _ in game["market"]]
        _start_scoring(game)
        return
    for pid in _cycle(game, after, inclusive):
        if has_auction_action(game, pid):
            game["turn"] = pid
            return
    # Nobody can act: every player holds 18 and has nowhere to put what is left.
    left = [die for cols in game["market"] for col in cols for die in col]
    game["cup"].extend(left)
    game["market"] = [[] for _ in game["market"]]
    _log(game, "market_closed", left=len(left))
    _start_scoring(game)


def _start_scoring(game: dict) -> None:
    game["phase"] = "scoring"
    game["passed"] = []
    start = game["last_buyer"] or game["first"]
    _log(game, "scoring", round=game["round"], first=start)
    _settle_scoring(game, start, inclusive=True)


def _settle_scoring(game: dict, after: str, inclusive: bool) -> None:
    for pid in _cycle(game, after, inclusive):
        if pid in game["passed"]:
            continue
        if scoring_lines(game["boards"][pid]):
            game["turn"] = pid
            return
        game["passed"].append(pid)
        _log(game, "pass", pid=pid, auto=True)
    _end_round(game)


def _score(game: dict, pid: str, move: dict):
    board = game["boards"][pid]
    line = _line_of(board, move.get("cells"))
    if not line:
        return False, "that is not a line you can score"
    cells = {(int(r), int(c)) for r, c in move["cells"]}
    removed = [d for d in board if (d["r"], d["c"]) in cells]
    game["boards"][pid] = [d for d in board if (d["r"], d["c"]) not in cells]
    _normalise(game["boards"][pid])
    pts = line["points"]
    before = game["money"][pid]
    game["money"][pid] = money_after(pts, before)
    game["points"][pid] += pts
    game["cup"].extend({"id": d["id"], "f": d["f"]} for d in removed)
    game["round_scored"] += len(removed)
    st = game["stats"][pid]
    st["lines"] += 1
    st["best"] = max(st["best"], pts)
    _log(game, "score", pid=pid, face=line["face"], count=len(removed), points=pts,
         money=game["money"][pid] - before, dice=[d["id"] for d in removed],
         cells=[[d["r"], d["c"]] for d in removed])
    _settle_scoring(game, pid, inclusive=False)
    return True, None


def _end_round(game: dict) -> None:
    if game["round_scored"] == 0 or game["round"] >= ROUNDS:
        _finish(game, early=game["round_scored"] == 0 and game["round"] < ROUNDS)
        return
    rng = random.Random(f"{game['seed']}:roll:{game['round']}")
    dice = game["cup"]
    for die in dice:
        die["f"] = rng.randint(1, 6)
    game["market"] = _deal(dice, len(game["market"]))
    game["cup"] = []
    game["round"] += 1
    game["phase"] = "auction"
    game["passed"] = []
    game["rerolled"] = []
    game["first"] = game["last_buyer"] or game["first"]
    game["last_buyer"] = None
    game["round_dice"] = len(dice)
    game["round_scored"] = 0
    _log(game, "round", round=game["round"], first=game["first"], dice=len(dice),
         faces=[die["f"] for die in dice])
    _settle_auction(game, game["first"], inclusive=True)


def _finish(game: dict, early: bool = False, conceded: str | None = None) -> None:
    final = totals(game)
    contenders = [pid for pid in game["players"] if pid != conceded] or list(game["players"])
    best = max(final[pid] for pid in contenders)
    game["final"] = final
    game["winners"] = [pid for pid in contenders if final[pid] == best]
    game["phase"] = "over"
    game["turn"] = None
    game["conceded"] = conceded
    _log(game, "game_over", winners=list(game["winners"]), final=final, early=early,
         conceded=conceded)


def concede(game: dict, pid: str) -> None:
    if not game or is_over(game) or pid not in game["players"]:
        return
    _log(game, "concede", pid=pid)
    _finish(game, conceded=pid)


# ── wire ────────────────────────────────────────────────────────────────────

def player_view(game: dict | None, viewer: str | None = None) -> dict | None:
    """Pip Market is perfect information apart from future rolls, so the view is
    the game minus the seed those rolls come from, plus what the player to act
    may do (computed here so the client never has to agree with the server about
    connectivity)."""
    if not game:
        return None
    view = copy.deepcopy(game)
    view.pop("seed", None)
    actor = to_act(game)
    view["options"] = None
    if actor:
        if game["phase"] == "auction":
            view["options"] = {"pid": actor, "take": can_take(game, actor),
                               "columns": buyable_columns(game, actor),
                               "rerolls": rerollable_columns(game, actor)}
        else:
            view["options"] = {"pid": actor, "lines": scoring_lines(game["boards"][actor])}
    view["totals"] = totals(game)
    view["max_money"] = MAX_MONEY
    view["span"] = SPAN
    view["rounds"] = ROUNDS
    return view
