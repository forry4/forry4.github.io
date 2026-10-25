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


# ── the lists ────────────────────────────────────────────────────────────────
def saved(r):
    return r["saved"]


def test_save_unsave_and_newest_first(conn):
    assert saved(S.apply_changes(conn, "u_alice", [105600], [], now=10)) == [[105600, 10.0]]
    assert saved(S.apply_changes(conn, "u_alice", [1145360, 413150], [], now=20)) == [
        [413150, 20.0], [1145360, 20.0], [105600, 10.0]]
    assert saved(S.apply_changes(conn, "u_alice", [], [1145360, 999])) == [[413150, 20.0], [105600, 10.0]]
    assert S.marks(conn, "u_bob") == {"saved": [], "hidden": []}


def test_saving_again_keeps_the_first_time(conn):
    S.apply_changes(conn, "u_alice", [105600], [], now=10)
    assert saved(S.apply_changes(conn, "u_alice", [105600, 105600], [], now=99)) == [[105600, 10.0]]


def test_a_batch_that_saves_and_unsaves_one_game_leaves_it_unsaved(conn):
    S.apply_changes(conn, "u_alice", [105600], [], now=10)
    assert saved(S.apply_changes(conn, "u_alice", [105600, 7], [105600], now=20)) == [[7, 20.0]]


def test_a_game_carries_one_mark(conn):
    S.apply_changes(conn, "u_alice", save=[1, 2], now=10)
    # hiding a saved game takes it off saved...
    assert S.apply_changes(conn, "u_alice", hide=[1], now=20) == {"saved": [[2, 10.0]], "hidden": [[1, 20.0]]}
    # ...saving a hidden one takes it off hidden...
    assert S.apply_changes(conn, "u_alice", save=[1], now=30) == {"saved": [[1, 30.0], [2, 10.0]], "hidden": []}
    # ...and both at once in one batch leaves it on neither.
    S.apply_changes(conn, "u_alice", hide=[3], now=40)
    assert S.apply_changes(conn, "u_alice", save=[3], hide=[3], now=50) == {"saved": [[1, 30.0], [2, 10.0]], "hidden": []}


def test_unhide(conn):
    S.apply_changes(conn, "u_alice", hide=[5, 6], now=10)
    assert S.apply_changes(conn, "u_alice", unhide=[5, 99])["hidden"] == [[6, 10.0]]


def test_the_lists_are_capped(conn, monkeypatch):
    monkeypatch.setattr(S, "LISTS", {"saved": ("steam_saved", 3), "hidden": ("steam_hidden", 2)})
    S.apply_changes(conn, "u_alice", [1, 2, 3], [])
    with pytest.raises(ValueError):
        S.apply_changes(conn, "u_alice", [4], [])
    # ...but a batch that frees room first fits.
    assert {a for a, _ in saved(S.apply_changes(conn, "u_alice", [4], [1]))} == {2, 3, 4}
    S.apply_changes(conn, "u_alice", hide=[7, 8])
    with pytest.raises(ValueError, match="not-interested"):
        S.apply_changes(conn, "u_alice", hide=[9], save=[5], unsave=[2])   # saved stays at 3
    # the refused batch wrote nothing — not even its save
    assert {a for a, _ in S.marks(conn, "u_alice")["saved"]} == {2, 3, 4}


def test_ids_must_be_app_ids(conn):
    for bad in (0, -5, S.MAX_APP_ID):
        with pytest.raises(ValueError):
            S.apply_changes(conn, "u_alice", [bad], [])
        with pytest.raises(ValueError):
            S.apply_changes(conn, "u_alice", hide=[bad])


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
    r = post(S.SavedIn(unsave=[105600], hide=[440]), user=ALICE)
    assert [a for a, _ in r["saved"]] == [413150] and [a for a, _ in r["hidden"]] == [440]
    mine = get(user=ALICE)
    assert [a for a, _ in mine["saved"]] == [413150] and [a for a, _ in mine["hidden"]] == [440]
    assert get(user=BOB) == {"saved": [], "hidden": []}


def test_a_page_from_before_hide_still_saves(app):
    post = _endpoint(app, "POST", "/steamfilter/saved")
    r = post(S.SavedIn.model_validate({"save": [1], "unsave": []}), user=ALICE)
    assert [a for a, _ in r["saved"]] == [1]


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
