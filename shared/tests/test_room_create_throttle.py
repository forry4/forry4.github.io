"""Every game's `create` passes through `core.rooms.reject_room_create` first.

A `create` is the one WebSocket message that writes a NEW row — an open lobby
that sits in the DB for 48h and in every lobby's Open list — and the connect and
message throttles alone allow about sixty a minute from one address. Each game
has its own dispatcher, so the throttle is one line in eleven places, and
forgetting it in the twelfth compiles, creates tables perfectly, and is the one
door a lobby flood goes through.

The roster is DERIVED from the tree (every games/*/main.py with a `create`
branch), so a new game joins it the day it ships. Read as an AST, not text: the
check is that the throttle is the FIRST thing the branch does.
"""
import ast
import asyncio
import json
from pathlib import Path

import pytest

from core import alerts
from core import rooms as _rooms

ROOT = Path(__file__).resolve().parents[2]


def _is_create_branch(node) -> bool:
    t = node.test if isinstance(node, ast.If) else None
    return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "action"
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == "create")


def _calls_throttle(stmt) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "reject_room_create" for n in ast.walk(stmt))


def _roster():
    out = {}
    for main in sorted((ROOT / "games").glob("*/main.py")):
        tree = ast.parse(main.read_text(encoding="utf-8"))
        branches = [n for n in ast.walk(tree) if _is_create_branch(n)]
        if branches:
            out[main.parent.name] = branches
    return out


def test_the_roster_is_every_game():
    roster = _roster()
    assert len(roster) >= 11, sorted(roster)
    assert {"spender", "orbit", "dontminion", "wherewolf"} <= set(roster)


@pytest.mark.parametrize("game", sorted(_roster()))
def test_create_is_throttled_before_anything_else(game):
    for branch in _roster()[game]:
        assert _calls_throttle(branch.body[0]), (
            f"games/{game}/main.py: the `create` branch must call "
            "_rooms.reject_room_create(websocket) as its first statement")


def test_the_ast_check_is_not_vacuous():
    good = ast.parse('if action == "create":\n    if not await _rooms.reject_room_create(ws):\n        x()\n',
                     mode="exec").body[0]
    bad = ast.parse('if action == "create":\n    x()\n    await _rooms.reject_room_create(ws)\n').body[0]
    assert _is_create_branch(good) and _calls_throttle(good.body[0])
    assert _is_create_branch(bad) and not _calls_throttle(bad.body[0])


# ── the throttle itself ──────────────────────────────────────────────────────
class _WS:
    def __init__(self, ip):
        self.headers = {"x-forwarded-for": f"9.9.9.9, {ip}"}   # the LAST hop is the real peer
        self.sent = []

    async def send_text(self, t):
        self.sent.append(json.loads(t))


def test_over_the_hourly_budget_a_create_is_refused_and_the_owner_told():
    a = _WS("1.1.1.1")
    for _ in range(_rooms.ROOM_CREATES_PER_HOUR):
        assert asyncio.run(_rooms.reject_room_create(a)) is False
    assert asyncio.run(_rooms.reject_room_create(a)) is True
    assert a.sent == [{"type": "error", "message": _rooms.ROOM_CREATE_REFUSED}]
    assert asyncio.run(_rooms.reject_room_create(_WS("2.2.2.2"))) is False   # per address
    assert [x["kind"] for x in alerts._sink] == ["lobby-flood"]
