"""THE TIME FLOOR: a fight the server times faster than its boss can fall is refused,
and the run posts no time (api.MIN_CLEAR_S)."""
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from bossrush import api
from bossrush.dungeon import BOSS_SETS, BOSSES
from core.db import _Conn


@pytest.fixture
def rush(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "MIN_CLEAR_SCALE", 1.0)          # the conftest turns it off for every other test
    clock = [1000.0]
    monkeypatch.setattr(api, "time", type("Clock", (), {"time": lambda: clock[0]}))
    monkeypatch.setattr(api, "_starts", api.SlidingWindowLimiter(1000, 60))
    db = tmp_path / "runs.db"
    app = FastAPI()
    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(db)), lambda token: None, lambda: None)
    ep = {route.path: route.endpoint for route in app.routes if route.path.startswith("/bossrush")}
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    return SimpleNamespace(
        clock=clock, db=db, board=ep["/bossrush/leaderboard"],
        start=lambda: ep["/bossrush/runs"](api.StartIn(character="ranger", starter_timer=True), request, None),
        enter=ep["/bossrush/runs/{run_id}/entries/{stage}"], clear=ep["/bossrush/runs/{run_id}/clears/{stage}"])


def floor_of(key):
    return api.MIN_CLEAR_S[BOSSES[key][2]]


def test_every_boss_in_every_set_has_a_floor():
    assert {BOSSES[key][2] for _, keys in BOSS_SETS.values() for key in keys} == set(api.MIN_CLEAR_S)


def test_a_fight_shorter_than_its_boss_allows_posts_nothing(rush):
    run = rush.start()
    order = json.loads(sqlite3.connect(rush.db).execute(
        "SELECT boss_order FROM boss_rush_runs WHERE run_id=?", (run["run_id"],)).fetchone()[0])
    assert order == [stage["id"] for stage in run["stages"]], "the server keeps the order it dealt"
    rush.enter(run["run_id"], 1)
    rush.clock[0] += floor_of(order[0]) - 0.5                 # entry and clear a hair too close
    with pytest.raises(HTTPException) as fast:
        rush.clear(run["run_id"], 1)
    assert fast.value.status_code == 409 and "too short to count" in fast.value.detail
    row = sqlite3.connect(rush.db).execute("SELECT cleared, combat_ms FROM boss_rush_runs WHERE run_id=?",
                                           (run["run_id"],)).fetchone()
    assert row == (0, 0), "a refused clear writes nothing"


def test_honest_fights_post_and_the_floor_is_each_bosss_own(rush):
    run = rush.start()
    order = [stage["id"] for stage in run["stages"]]
    for stage, key in enumerate(order, 1):
        rush.enter(run["run_id"], stage)
        rush.clock[0] += floor_of(key) + 0.1
        result = rush.clear(run["run_id"], stage)
    assert result["elapsed_ms"] == round(sum(floor_of(key) + 0.1 for key in order) * 1000)
    assert [e["elapsed_ms"] for e in rush.board()["entries"]] == [result["elapsed_ms"]]


def test_a_run_from_before_the_order_was_kept_meets_the_lowest_floor(rush):
    run = rush.start()
    with sqlite3.connect(rush.db) as conn:
        conn.execute("UPDATE boss_rush_runs SET boss_order=NULL WHERE run_id=?", (run["run_id"],))
    rush.enter(run["run_id"], 1)
    rush.clock[0] += min(api.MIN_CLEAR_S.values()) - 0.1
    with pytest.raises(HTTPException):
        rush.clear(run["run_id"], 1)
    rush.clock[0] += 0.2
    assert rush.clear(run["run_id"], 1)["cleared"] == 1
