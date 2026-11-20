"""One ranked clear requires all three stages in sequence."""
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from bossrush import api
from core.db import _Conn


def test_a_run_draws_each_arena_once_and_posts_one_server_timed_clear(tmp_path, monkeypatch):
    clock = [1000]
    monkeypatch.setattr(api, "time", type("Clock", (), {"time": lambda: clock[0]}))
    monkeypatch.setattr(api, "_starts", api.SlidingWindowLimiter(30, 60))
    orders = iter([["ashen", "shallows", "fracture"], ["fracture", "ashen", "shallows"]])
    monkeypatch.setattr(api, "random", type("Order", (), {"sample": lambda keys, n: next(orders)}))
    app = FastAPI()

    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(tmp_path / "runs.db")),
                        lambda token: {"name": "Wren"} if token == "wren" else None, lambda: None)
    endpoints = {route.path: route.endpoint for route in app.routes if route.path.startswith("/bossrush")}
    board = endpoints["/bossrush/leaderboard"]
    start = endpoints["/bossrush/runs"]
    clear = endpoints["/bossrush/runs/{run_id}/clears/{stage}"]
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    assert board() == {"entries": []}
    with pytest.raises(ValidationError):
        api.StartIn(character="alien")
    with pytest.raises(HTTPException) as expired:
        start(api.StartIn(character="ninja"), request, "expired")
    assert expired.value.status_code == 401
    run = start(api.StartIn(character="ninja"), request, "wren")
    assert [stage["id"] for stage in run["stages"]] == ["ashen", "shallows", "fracture"]
    for stage in run["stages"]:
        first, boss_room = stage["rooms"]
        assert (first["kind"], boss_room["kind"]) == ("entrance", "boss")
        row = stage["tiles"][stage["door_y"]]
        assert set(row[first["x1"]:boss_room["x0"]]) == {"."}
        assert int(stage["start"]["x"]) in range(first["x0"], first["x1"])
        assert all(e["room"] == 1 for e in stage["enemies"].values())

    run_id = run["run_id"]
    with pytest.raises(HTTPException) as early:
        clear(run_id, 3)
    assert early.value.status_code == 409
    assert clear(run_id, 1) == {"cleared": 1, "elapsed_ms": None}
    assert clear(run_id, 1) == {"cleared": 1, "elapsed_ms": None}
    assert clear(run_id, 2) == {"cleared": 2, "elapsed_ms": None}
    assert board() == {"entries": []}
    clock[0] += 42.5
    win = clear(run_id, 3)
    assert win == {"cleared": 3, "elapsed_ms": 42500}
    clock[0] += 10
    assert clear(run_id, 3) == win
    assert board() == {"entries": [
        {"rank": 1, "name": "Wren", "character": "ninja", "elapsed_ms": 42500},
    ]}

    guest = start(api.StartIn(character="paladin"), request, None)
    assert [stage["id"] for stage in guest["stages"]] == ["fracture", "ashen", "shallows"]
    clock[0] += api.RUN_TTL + 1
    with pytest.raises(HTTPException) as timed_out:
        clear(guest["run_id"], 1)
    assert timed_out.value.status_code == 404
    assert len(board()["entries"]) == 1
