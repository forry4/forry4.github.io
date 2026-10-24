"""Saved games (steamfilter/api.py).

Pure functions run on a real sqlite file through core.db's _Conn wrapper; routes
are called as their registered endpoints (the repo has no TestClient), like Box Puzzles.
"""
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from steamfilter import api as S
from core.db import _Conn

ALICE = {"id": "u_alice", "name": "alice"}
BOB = {"id": "u_bob", "name": "bob"}


@pytest.fixture(autouse=True)
def _fresh_limits():
    S._writes_minute.reset()
    yield


@pytest.fixture()
def get_conn(tmp_path):
    path = str(tmp_path / "steam.db")
    return lambda: _Conn(sqlite3.connect(path, check_same_thread=False))


@pytest.fixture()
def conn(get_conn):
    c = get_conn()
    S.init_saved_db(c)
    yield c
    c.close()


@pytest.fixture()
def app(get_conn):
    a = FastAPI()
    users = {"tok_alice": ALICE, "tok_bob": BOB}
    S.setup_steam_saved(a, get_conn, users.get)
    return a


def _endpoint(app, method: str, path: str):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r.endpoint
    raise AssertionError(f"no route {method} {path}")


# ── the list ─────────────────────────────────────────────────────────────────
def test_save_unsave_and_newest_first(conn):
    assert S.apply_changes(conn, "u_alice", [105600], [], now=10) == [[105600, 10.0]]
    assert S.apply_changes(conn, "u_alice", [1145360, 413150], [], now=20) == [
        [413150, 20.0], [1145360, 20.0], [105600, 10.0]]
    assert S.apply_changes(conn, "u_alice", [], [1145360, 999]) == [[413150, 20.0], [105600, 10.0]]
    assert S.list_saved(conn, "u_bob") == []


def test_saving_again_keeps_the_first_time(conn):
    S.apply_changes(conn, "u_alice", [105600], [], now=10)
    assert S.apply_changes(conn, "u_alice", [105600, 105600], [], now=99) == [[105600, 10.0]]


def test_a_batch_that_saves_and_unsaves_one_game_leaves_it_unsaved(conn):
    S.apply_changes(conn, "u_alice", [105600], [], now=10)
    assert S.apply_changes(conn, "u_alice", [105600, 7], [105600], now=20) == [[7, 20.0]]


def test_the_list_is_capped(conn, monkeypatch):
    monkeypatch.setattr(S, "MAX_SAVED", 3)
    S.apply_changes(conn, "u_alice", [1, 2, 3], [])
    with pytest.raises(ValueError):
        S.apply_changes(conn, "u_alice", [4], [])
    # ...but a batch that frees room first fits.
    assert {a for a, _ in S.apply_changes(conn, "u_alice", [4], [1])} == {2, 3, 4}


def test_ids_must_be_app_ids(conn):
    for bad in (0, -5, S.MAX_APP_ID):
        with pytest.raises(ValueError):
            S.apply_changes(conn, "u_alice", [bad], [])


# ── the routes ───────────────────────────────────────────────────────────────
def test_both_routes_need_an_account(app):
    for method in ("GET", "POST"):
        route = next(r for r in app.routes if getattr(r, "path", "") == "/steamfilter/saved"
                     and method in r.methods)
        member = route.dependant.dependencies[-1].call
        with pytest.raises(HTTPException) as e:
            member(None)
        assert e.value.status_code == 401
        with pytest.raises(HTTPException):
            member("tok_nobody")


def test_round_trip_per_account(app):
    get = _endpoint(app, "GET", "/steamfilter/saved")
    post = _endpoint(app, "POST", "/steamfilter/saved")
    r = post(S.SavedIn(save=[105600, 413150]), user=ALICE)
    assert {a for a, _ in r["saved"]} == {105600, 413150}
    r = post(S.SavedIn(unsave=[105600]), user=ALICE)
    assert [a for a, _ in r["saved"]] == [413150]
    assert [a for a, _ in get(user=ALICE)["saved"]] == [413150]
    assert get(user=BOB)["saved"] == []


def test_bad_input_maps_to_400_and_batches_are_bounded(app):
    post = _endpoint(app, "POST", "/steamfilter/saved")
    with pytest.raises(HTTPException) as e:
        post(S.SavedIn(save=[0]), user=ALICE)
    assert e.value.status_code == 400
    with pytest.raises(ValidationError):
        S.SavedIn(save=list(range(1, S.MAX_BATCH + 2)))


def test_writes_are_rate_limited_per_account(app, monkeypatch):
    from core import alerts
    raised = []
    monkeypatch.setattr(alerts, "alert", lambda *a, **k: raised.append(a))
    monkeypatch.setattr(S, "_writes_minute", S.SlidingWindowLimiter(max_hits=2, window_seconds=60))
    post = _endpoint(app, "POST", "/steamfilter/saved")
    post(S.SavedIn(save=[1]), user=ALICE)
    post(S.SavedIn(save=[2]), user=ALICE)
    with pytest.raises(HTTPException) as e:
        post(S.SavedIn(save=[3]), user=ALICE)
    assert e.value.status_code == 429 and raised
    post(S.SavedIn(save=[3]), user=BOB)   # someone else's budget is their own
