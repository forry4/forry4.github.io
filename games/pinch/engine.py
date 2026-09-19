"""Pure, JSON-safe rules engine for Pinch.

The browser is a renderer.  Every action it can submit is returned by
``legal_moves`` and revalidated here before the state changes.
"""

from __future__ import annotations

import copy
import random
from typing import Iterable

SCHEMA = 1
RING_COUNT = 5
MARKER_COUNT = 51
LOG_CAP = 240
MODES = ("standard", "blitz")
WIN_ROWS = {"standard": 3, "blitz": 1}

DIRECTIONS = ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))
ROW_DIRECTIONS = ((1, 0), (0, 1), (1, -1))
CORNERS = {(5, 0), (5, -5), (0, -5), (-5, 0), (-5, 5), (0, 5)}


def _make_nodes() -> tuple[tuple[int, int], ...]:
    nodes = []
    for r in range(-5, 6):
        for q in range(-5, 6):
            s = -q - r
            if max(abs(q), abs(r), abs(s)) <= 5 and (q, r) not in CORNERS:
                nodes.append((q, r))
    return tuple(nodes)


NODES = _make_nodes()
NODE_TO_ID = {coord: index for index, coord in enumerate(NODES)}
NODE_COUNT = len(NODES)
assert NODE_COUNT == 85


def node_coord(node: int) -> tuple[int, int]:
    return NODES[node]


def _other(game: dict, pid: str) -> str:
    return game["order"][1] if game["order"][0] == pid else game["order"][0]


def _occupied(game: dict) -> set[int]:
    occupied = set(game["markers"])
    for rings in game["rings"].values():
        occupied.update(rings)
    return occupied


def marker_pool(game: dict) -> int:
    return MARKER_COUNT - len(game["markers"])


def _event(game: dict, kind: str, pid: str | None = None, **parts) -> None:
    game["event_seq"] += 1
    entry = {"seq": game["event_seq"], "kind": kind}
    if pid is not None:
        entry["pid"] = pid
    entry.update(parts)
    game["log"].append(entry)
    if len(game["log"]) > LOG_CAP:
        del game["log"][:-LOG_CAP]


def new_game(players: list[str], *, names: dict[str, str] | None = None,
             seed: int | None = None, mode: str = "standard") -> dict:
    if len(players) != 2 or len(set(players)) != 2:
        raise ValueError("Pinch requires exactly two distinct players")
    if mode not in MODES:
        raise ValueError("unknown Pinch mode")
    order = list(players)
    random.Random(seed).shuffle(order)
    game = {
        "schema": SCHEMA,
        "mode": mode,
        "phase": "setup",
        "players": {pid: (names or {}).get(pid, pid) for pid in order},
        "order": order,
        "turn_pid": order[0],
        "rings": {pid: [] for pid in order},
        "markers": {},
        "removed": {pid: 0 for pid in order},
        "placements": {pid: 0 for pid in order},
        "pending_pid": None,
        "pending_kind": None,
        "pending": None,
        "resolution_order": [],
        "next_turn_pid": None,
        "winner": None,
        "result": None,
        "turn_number": 0,
        "consecutive_passes": 0,
        "event_seq": 0,
        "log": [],
    }
    _event(game, "start", mode=mode, first=order[0])
    validate_state(game)
    return game


def is_over(game: dict | None) -> bool:
    return not game or game.get("phase") == "over"


def winner(game: dict | None) -> str | None:
    return game.get("winner") if game else None


def final_scores(game: dict | None) -> dict[str, int]:
    return dict((game or {}).get("removed", {}))


def _ray(src: int, direction: tuple[int, int]) -> Iterable[int]:
    q, r = NODES[src]
    dq, dr = direction
    while True:
        q, r = q + dq, r + dr
        node = NODE_TO_ID.get((q, r))
        if node is None:
            return
        yield node


def ring_destinations(game: dict, src: int) -> list[int]:
    ring_nodes = {node for rings in game["rings"].values() for node in rings}
    markers = game["markers"]
    destinations: list[int] = []
    for direction in DIRECTIONS:
        jumping = False
        for node in _ray(src, direction):
            if node in ring_nodes:
                break
            if str(node) in markers:
                jumping = True
                continue
            destinations.append(node)
            if jumping:
                break
    return destinations


def _path_between(src: int, dst: int) -> list[int]:
    for direction in DIRECTIONS:
        path = []
        for node in _ray(src, direction):
            if node == dst:
                return path
            path.append(node)
    raise ValueError("nodes are not collinear")


def completed_rows(game: dict, pid: str) -> list[list[int]]:
    owned = {int(node) for node, owner in game["markers"].items() if owner == pid}
    rows: set[tuple[int, ...]] = set()
    for direction in ROW_DIRECTIONS:
        dq, dr = direction
        for node in sorted(owned):
            q, r = NODES[node]
            predecessor = NODE_TO_ID.get((q - dq, r - dr))
            if predecessor in owned:
                continue
            run = []
            cq, cr = q, r
            while True:
                current = NODE_TO_ID.get((cq, cr))
                if current not in owned:
                    break
                run.append(current)
                cq, cr = cq + dq, cr + dr
            for index in range(max(0, len(run) - 4)):
                rows.add(tuple(run[index:index + 5]))
    return [list(row) for row in sorted(rows)]


def _ring_moves(game: dict, pid: str) -> list[dict]:
    return [
        {"action": "move_ring", "from": src, "to": dst}
        for src in sorted(game["rings"][pid])
        for dst in ring_destinations(game, src)
    ]


def legal_moves(game: dict | None, pid: str) -> list[dict]:
    if not game or is_over(game) or pid not in game.get("players", {}):
        return []
    pending_pid = game.get("pending_pid")
    if pending_pid:
        if pending_pid != pid:
            return []
        if game.get("pending_kind") == "choose_row":
            return [{"action": "remove_row", "cells": list(row)}
                    for row in game.get("pending", {}).get("rows", [])]
        if game.get("pending_kind") == "remove_ring":
            return [{"action": "remove_ring", "at": node}
                    for node in sorted(game["rings"][pid])]
        return []
    if game.get("turn_pid") != pid:
        return []
    if game["phase"] == "setup":
        occupied = _occupied(game)
        return [{"action": "place_ring", "at": node}
                for node in range(NODE_COUNT) if node not in occupied]
    if game["phase"] == "play":
        moves = _ring_moves(game, pid)
        return moves or [{"action": "pass"}]
    return []


def _clear_pending(game: dict) -> None:
    game["pending_pid"] = None
    game["pending_kind"] = None
    game["pending"] = None


def _finish_by_removed(game: dict, result: str) -> None:
    a, b = game["order"]
    game["phase"] = "over"
    game["result"] = result
    game["winner"] = a if game["removed"][a] > game["removed"][b] else (
        b if game["removed"][b] > game["removed"][a] else None)
    game["turn_pid"] = None
    game["resolution_order"] = []
    game["next_turn_pid"] = None
    _clear_pending(game)
    _event(game, "game_over", game.get("winner"), result=result,
           scores=dict(game["removed"]))


def _advance_resolution(game: dict) -> None:
    _clear_pending(game)
    while game["resolution_order"]:
        pid = game["resolution_order"][0]
        rows = completed_rows(game, pid)
        if rows:
            game["pending_pid"] = pid
            game["pending_kind"] = "choose_row"
            game["pending"] = {"rows": rows}
            return
        game["resolution_order"].pop(0)
    if marker_pool(game) == 0:
        _finish_by_removed(game, "marker_pool")
        return
    game["turn_pid"] = game.pop("next_turn_pid", None)
    game["next_turn_pid"] = None


def _apply_setup(game: dict, pid: str, move: dict) -> None:
    node = move["at"]
    game["rings"][pid].append(node)
    game["rings"][pid].sort()
    game["placements"][pid] += 1
    _event(game, "place_ring", pid, at=node)
    if all(game["placements"][seat] == RING_COUNT for seat in game["order"]):
        game["phase"] = "play"
        game["turn_pid"] = game["order"][0]
        _event(game, "setup_complete", first=game["turn_pid"])
    else:
        game["turn_pid"] = _other(game, pid)


def _apply_ring_move(game: dict, pid: str, move: dict) -> None:
    src, dst = move["from"], move["to"]
    game["rings"][pid].remove(src)
    game["rings"][pid].append(dst)
    game["rings"][pid].sort()
    game["markers"][str(src)] = pid
    flipped = []
    for node in _path_between(src, dst):
        key = str(node)
        if key in game["markers"]:
            game["markers"][key] = _other(game, game["markers"][key])
            flipped.append(node)
    game["turn_number"] += 1
    game["consecutive_passes"] = 0
    _event(game, "move_ring", pid, **{"from": src, "to": dst}, flipped=flipped)
    game["turn_pid"] = None
    game["resolution_order"] = [pid, _other(game, pid)]
    game["next_turn_pid"] = _other(game, pid)
    _advance_resolution(game)


def _apply_remove_row(game: dict, pid: str, move: dict) -> None:
    cells = list(move["cells"])
    for node in cells:
        del game["markers"][str(node)]
    _event(game, "remove_row", pid, cells=cells)
    game["pending_kind"] = "remove_ring"
    game["pending"] = {"row": cells}


def _apply_remove_ring(game: dict, pid: str, move: dict) -> None:
    node = move["at"]
    game["rings"][pid].remove(node)
    game["removed"][pid] += 1
    _event(game, "remove_ring", pid, at=node, score=game["removed"][pid])
    if game["removed"][pid] >= WIN_ROWS[game["mode"]]:
        game["phase"] = "over"
        game["winner"] = pid
        game["result"] = "rings"
        game["turn_pid"] = None
        game["resolution_order"] = []
        game["next_turn_pid"] = None
        _clear_pending(game)
        _event(game, "game_over", pid, result="rings",
               scores=dict(game["removed"]))
        return
    _advance_resolution(game)


def _apply_pass(game: dict, pid: str) -> None:
    game["consecutive_passes"] += 1
    _event(game, "pass", pid)
    if game["consecutive_passes"] >= 2:
        _finish_by_removed(game, "blocked")
    else:
        game["turn_pid"] = _other(game, pid)


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if not isinstance(move, dict):
        return False, "move must be an object"
    legal = legal_moves(game, pid)
    if move not in legal:
        return False, "illegal move"
    action = move.get("action")
    if action == "place_ring":
        _apply_setup(game, pid, move)
    elif action == "move_ring":
        _apply_ring_move(game, pid, move)
    elif action == "remove_row":
        _apply_remove_row(game, pid, move)
    elif action == "remove_ring":
        _apply_remove_ring(game, pid, move)
    elif action == "pass":
        _apply_pass(game, pid)
    else:  # pragma: no cover - membership above makes this unreachable
        return False, "unknown move"
    validate_state(game)
    return True, None


def concede(game: dict, pid: str) -> None:
    if is_over(game) or pid not in game.get("players", {}):
        return
    game["phase"] = "over"
    game["winner"] = _other(game, pid)
    game["result"] = "concession"
    game["turn_pid"] = None
    game["resolution_order"] = []
    game["next_turn_pid"] = None
    _clear_pending(game)
    _event(game, "concede", pid, winner=game["winner"])


def validate_state(game: dict) -> None:
    if game.get("schema") != SCHEMA:
        raise AssertionError("Pinch schema mismatch")
    if game.get("mode") not in MODES:
        raise AssertionError("invalid mode")
    order = game.get("order")
    if not isinstance(order, list) or len(order) != 2 or len(set(order)) != 2:
        raise AssertionError("invalid seats")
    all_rings = []
    for pid in order:
        rings = game["rings"].get(pid)
        if not isinstance(rings, list) or len(rings) + game["removed"][pid] > RING_COUNT:
            raise AssertionError("invalid rings")
        all_rings.extend(rings)
    marker_nodes = [int(node) for node in game["markers"]]
    if any(node < 0 or node >= NODE_COUNT for node in all_rings + marker_nodes):
        raise AssertionError("piece outside board")
    if len(all_rings) != len(set(all_rings)) or len(marker_nodes) != len(set(marker_nodes)):
        raise AssertionError("duplicate piece")
    if set(all_rings) & set(marker_nodes):
        raise AssertionError("ring overlaps marker")
    if len(marker_nodes) > MARKER_COUNT:
        raise AssertionError("too many markers")
    if any(owner not in order for owner in game["markers"].values()):
        raise AssertionError("invalid marker owner")
    if game.get("pending_pid") is None:
        if game.get("pending_kind") is not None or game.get("pending") is not None:
            raise AssertionError("orphan pending state")
    elif game.get("pending_pid") not in order:
        raise AssertionError("invalid pending seat")
    if game.get("phase") not in {"setup", "play", "over"}:
        raise AssertionError("invalid phase")


def player_view(game: dict | None, viewer_pid: str | None) -> dict | None:
    if game is None:
        return None
    view = copy.deepcopy(game)
    view["marker_pool"] = marker_pool(game)
    view["legal_moves"] = legal_moves(game, viewer_pid) if viewer_pid else []
    return view
