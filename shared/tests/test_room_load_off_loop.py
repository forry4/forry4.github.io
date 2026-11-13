"""A cold room's database read does not stall the rest of its game — in every game.

`core/tests/test_room_loading.py` pins `core.rooms.locked_room` itself. This drives
each game's REAL handler: the `/games/{game_id}/leave` route, which every game
server has and which loads its room exactly as the socket handlers do. Room A is
cold and its read hangs (a slow Turso call); room B is already live. B's leave
must finish while A's read is still parked. On the old shape — a synchronous load
under ROOM_LOCK on the event loop — B could not even start until A's read
returned, so the timestamps below would come out the other way round.

The roster is derived from the routes the game modules register, so a new game is
held to it the day it ships.
"""
import asyncio
import importlib
import threading
import time
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI

ROOT = Path(__file__).resolve().parents[2]


def _leave_routes() -> dict:
    out = {}
    for main in sorted((ROOT / "games").glob("*/main.py")):
        mod = importlib.import_module(f"games.{main.parent.name}.main")
        for obj in list(vars(mod).values()):
            if isinstance(obj, (FastAPI, APIRouter)):
                for route in obj.routes:
                    if getattr(route, "path", "").endswith("/games/{game_id}/leave"):
                        out[main.parent.name] = (mod, route.endpoint)
    return out


LEAVES = _leave_routes()


def test_the_roster_is_the_whole_tree():
    assert len(LEAVES) == len(list((ROOT / "games").glob("*/main.py"))) >= 12, sorted(LEAVES)


@pytest.mark.parametrize("game", sorted(LEAVES))
def test_a_stalled_cold_room_does_not_block_a_live_one(game, monkeypatch):
    mod, leave = LEAVES[game]
    gate, reads = threading.Event(), []

    def stalled_read(rid):
        reads.append(rid)
        assert gate.wait(10), "test gate never opened"
        return None

    monkeypatch.setattr(mod, "_read_room", stalled_read)
    monkeypatch.setattr(mod, "save_game", lambda *a, **k: None)
    monkeypatch.setattr(mod, "get_user_by_session", lambda *a, **k: None)
    rid_a, rid_b = mod.normalize_room("COLDAA"), mod.normalize_room("LIVEBB")
    mod.ROOMS.clear()
    mod.ROOMS[rid_b] = {"players": {"host": "Host"}, "sockets": {}, "status": "open",
                        "host": "host", "meta": {"host": {"token": "t"}}, "game": None}

    async def go():
        a = asyncio.create_task(leave(rid_a, token=None, player_id="nobody", room_token=None))
        while not reads:                       # A's read is now parked on its thread
            await asyncio.sleep(0.005)
        b = await asyncio.wait_for(
            leave(rid_b, token=None, player_id="nobody", room_token=None), timeout=3)
        b_done = time.monotonic()
        assert not a.done(), f"{game}: A finished without its read"
        gate.set()
        a_got = await asyncio.wait_for(a, timeout=5)
        return b, b_done, a_got

    try:
        b, b_done, a_got = asyncio.run(go())
    finally:
        gate.set()
        mod.ROOMS.clear()
    assert b.get("ok") is False, (game, b)        # answered from the LIVE room...
    assert reads == [rid_a], (game, reads)        # ...which was never read again
    assert a_got.get("ok") is False, (game, a_got)
    assert rid_a not in mod.ROOMS, game           # no row -> nothing installed
