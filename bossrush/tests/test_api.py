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
    orders = iter([
        ["ashen", "shallows", "fracture"],
        ["fracture", "ashen", "shallows"],
        ["shallows", "fracture", "ashen"],
        ["bell-court", "fen", "seal-court"],
    ])

    def sample(keys, n):
        order = next(orders)
        assert set(keys) == set(order) and n == 3
        return order

    monkeypatch.setattr(api, "random", type("Order", (), {"sample": sample}))
    app = FastAPI()

    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(tmp_path / "runs.db")),
                        lambda token: {"name": "Wren"} if token == "wren" else None, lambda: None)
    endpoints = {route.path: route.endpoint for route in app.routes if route.path.startswith("/bossrush")}
    sets = endpoints["/bossrush/sets"]
    board = endpoints["/bossrush/leaderboard"]
    start = endpoints["/bossrush/runs"]
    clear = endpoints["/bossrush/runs/{run_id}/clears/{stage}"]
    enter = endpoints["/bossrush/runs/{run_id}/entries/{stage}"]
    set_clock = endpoints["/bossrush/runs/{run_id}/clock/{stage}/{action}"]
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    available = {entry["id"]: entry for entry in sets()["sets"]}
    assert available["rift-trio"]["playable"]
    assert not available["lantern-trio"]["playable"]
    lantern = {entry["id"]: entry for entry in sets(lantern=True)["sets"]}["lantern-trio"]
    assert lantern["playable"]
    assert lantern["bosses"] == ["The Cinderwake", "The Warden", "The Hollow Bellkeeper"]
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
    with pytest.raises(HTTPException) as too_far:
        clear(run_id, 4)
    assert too_far.value.status_code == 404
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

    timed = start(api.StartIn(character="paladin", starter_timer=True), request, None)
    assert timed["starter_timer"] is True
    assert [stage["id"] for stage in timed["stages"]] == ["fracture", "ashen", "shallows"]
    with pytest.raises(HTTPException) as wrong_room:
        enter(timed["run_id"], 2)
    assert wrong_room.value.status_code == 409
    for stage in range(1, 4):
        clock[0] += 30  # waiting in the starter room is free
        with pytest.raises(HTTPException) as too_soon:
            clear(timed["run_id"], stage)
        assert too_soon.value.status_code == 409
        assert enter(timed["run_id"], stage) == {"entered": stage}
        clock[0] += 1
        assert enter(timed["run_id"], stage) == {"entered": stage}
        assert set_clock(timed["run_id"], stage, "pause") == {"paused": True}
        clock[0] += 5
        assert set_clock(timed["run_id"], stage, "pause") == {"paused": True}
        with pytest.raises(HTTPException) as still_paused:
            clear(timed["run_id"], stage)
        assert still_paused.value.status_code == 409
        clock[0] += 12
        assert set_clock(timed["run_id"], stage, "resume") == {"paused": False}
        clock[0] += 1
        assert set_clock(timed["run_id"], stage, "resume") == {"paused": False}
        clock[0] += 0.5
        timed_result = clear(timed["run_id"], stage)
    assert timed_result == {"cleared": 3, "elapsed_ms": 7500}
    assert board()["entries"][0] == {
        "rank": 1, "name": "Guest", "character": "paladin", "elapsed_ms": 7500,
    }

    guest = start(api.StartIn(character="paladin"), request, None)
    clock[0] += api.RUN_TTL + 1
    with pytest.raises(HTTPException) as timed_out:
        clear(guest["run_id"], 1)
    assert timed_out.value.status_code == 404
    assert len(board()["entries"]) == 2
    assert board(character="ninja")["entries"] == [
        {"rank": 1, "name": "Wren", "character": "ninja", "elapsed_ms": 42500},
    ]
    assert board(set_id="lantern-trio") == {"entries": []}
    lantern_run = start(api.StartIn(character="ranger", set_id="lantern-trio"), request, "wren")
    assert [stage["boss_kind"] for stage in lantern_run["stages"]] == ["bellkeeper", "cinderwake", "warden"]
    # Five bells, three braziers, three seals.
    for stage, count in zip(lantern_run["stages"], (5, 3, 3)):
        assert len(stage["objectives"]) == count
        for point in stage["objectives"]:
            assert stage["tiles"][int(point["y"])][int(point["x"])] == "."
    for stage in range(1, 4):
        clock[0] += 3
        result = clear(lantern_run["run_id"], stage)
    assert result["elapsed_ms"] == 9000
    assert board("lantern-trio", "ranger")["entries"] == [
        {"rank": 1, "name": "Wren", "character": "ranger", "elapsed_ms": 9000},
    ]
    assert len(board()["entries"]) == 2


def test_existing_scores_migrate_to_rift_trio_and_future_scores_stay_in_their_set(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.execute("""
            CREATE TABLE boss_rush_runs (
                run_id TEXT PRIMARY KEY, player_name TEXT NOT NULL, character TEXT NOT NULL,
                started_at REAL NOT NULL, cleared INTEGER NOT NULL DEFAULT 0, elapsed_ms INTEGER
            )
        """)
        conn.execute("INSERT INTO boss_rush_runs VALUES ('legacy', 'Wren', 'ranger', 1000, 3, 9876)")
    app = FastAPI()
    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(database)), lambda _: None, lambda: None)
    board = next(route.endpoint for route in app.routes if route.path == "/bossrush/leaderboard")
    with sqlite3.connect(database) as conn:
        conn.execute("""
            INSERT INTO boss_rush_runs (run_id, player_name, character, started_at, cleared, elapsed_ms, set_id)
            VALUES ('future', 'Kai', 'ranger', 1100, 3, 1234, 'lantern-trio')
        """)
    assert board("rift-trio", "ranger")["entries"] == [
        {"rank": 1, "name": "Wren", "character": "ranger", "elapsed_ms": 9876},
    ]
    assert board("lantern-trio", "ranger")["entries"] == [
        {"rank": 1, "name": "Kai", "character": "ranger", "elapsed_ms": 1234},
    ]
    assert board("rift-trio", "diviner") == {"entries": []}


def test_a_run_can_open_on_the_boss_you_pick_and_otherwise_stays_random(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_starts", api.SlidingWindowLimiter(1000, 60))
    monkeypatch.setattr(api, "random", __import__("random").Random(7))   # seeded: the checks below cannot flake
    app = FastAPI()
    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(tmp_path / "runs.db")),
                        lambda token: None, lambda: None)
    endpoints = {route.path: route.endpoint for route in app.routes if route.path.startswith("/bossrush")}
    start, sets = endpoints["/bossrush/runs"], endpoints["/bossrush/sets"]
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    trio = {entry["id"]: entry for entry in sets()["sets"]}["rift-trio"]
    assert trio["keys"] == ["shallows", "fracture", "ashen"], "the picker gets each boss's key"
    for key in trio["keys"]:
        seen = set()
        for _ in range(30):
            order = [s["id"] for s in start(api.StartIn(character="ranger", first=key), request, None)["stages"]]
            assert order[0] == key and sorted(order) == sorted(trio["keys"])
            seen.add(tuple(order[1:]))
        assert len(seen) == 2, "the other two still come in either order"
    with pytest.raises(HTTPException) as wrong:
        start(api.StartIn(character="ranger", first="warden"), request, None)
    assert wrong.value.status_code == 422
    firsts = {start(api.StartIn(character="ranger"), request, None)["stages"][0]["id"] for _ in range(40)}
    assert firsts == set(trio["keys"]), "with no pick, any boss can open"
