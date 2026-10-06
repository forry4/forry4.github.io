"""The daily box (boxpuzzles/daily.py + its routes in api.py).

Attempts are tested on a real bank box (its minimum is known and its line is short);
the generator is tested on its own, at the shallow end of the range so it stays fast.
"""
import random
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException

from boxpuzzles import api as B
from boxpuzzles import daily as D
from boxpuzzles.engine import CORNERS, corners_match, press, replay, solve
from core.db import _Conn

FIRST = B.BANK[next(iter(B.BANK))]
LINE = solve(FIRST["tiles"], FIRST["target"])
TODAY, YESTERDAY = "2026-10-05", "2026-10-04"
BOX = {"day": TODAY, "tiles": FIRST["tiles"], "target": FIRST["target"],
       "minimum": len(LINE), "solution": LINE}
ALICE = {"id": "u_alice", "name": "alice"}
BOB = {"id": "u_bob", "name": "bob"}


def _utc(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def _cancelling_pair():
    for i in range(9):
        for j in range(9):
            if press(press(FIRST["tiles"], i), j) == tuple(FIRST["tiles"]):
                return [i, j]
    raise AssertionError("no cancelling pair on the first box")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    B._daily_minute.reset()
    B._solves_minute.reset()
    # never start the background filler from a test
    monkeypatch.setattr(D, "start_filler", lambda get_db_conn: None)
    yield


@pytest.fixture()
def get_conn(tmp_path):
    path = str(tmp_path / "daily.db")

    def make():
        c = _Conn(sqlite3.connect(path, check_same_thread=False))
        c.cursor().execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT)")
        c.commit()
        return c
    return make


@pytest.fixture()
def conn(get_conn):
    c = get_conn()
    D.init_daily_db(c)
    cur = c.cursor()
    for u in (ALICE, BOB):
        cur.execute("INSERT INTO users (id, name) VALUES (?, ?)", (u["id"], u["name"]))
    c.commit()
    yield c
    c.close()


# ── the day ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("instant, day", [
    ("2026-03-08T07:59:59", "2026-03-07"),   # PST, the morning daylight time starts
    ("2026-03-08T08:00:00", "2026-03-08"),
    ("2026-07-01T06:59:59", "2026-06-30"),   # PDT
    ("2026-07-01T07:00:00", "2026-07-01"),
    ("2026-11-02T07:59:59", "2026-11-01"),   # PST again, the day after it ends
    ("2026-11-02T08:00:00", "2026-11-02"),
    ("2026-12-31T23:00:00", "2026-12-31"),
])
def test_the_day_turns_at_pacific_midnight(instant, day):
    assert D.pacific_day(_utc(instant)) == day


def test_daylight_time_starts_and_ends_on_the_us_sundays():
    # 2025: March 9 and November 2; 2026: March 8 and November 1
    assert D._nth_sunday(2025, 3, 2).isoformat() == "2025-03-09"
    assert D._nth_sunday(2025, 11, 1).isoformat() == "2025-11-02"
    assert D.pacific_offset(_utc("2026-03-08T09:59:59")) == -8
    assert D.pacific_offset(_utc("2026-03-08T10:00:00")) == -7
    assert D.pacific_offset(_utc("2026-11-01T08:59:59")) == -7
    assert D.pacific_offset(_utc("2026-11-01T09:00:00")) == -8


@pytest.mark.parametrize("day, instant", [
    ("2026-07-01", "2026-07-01T07:00:00"),
    ("2026-12-01", "2026-12-01T08:00:00"),
    ("2026-03-08", "2026-03-08T08:00:00"),   # still PST at midnight
    ("2026-03-09", "2026-03-09T07:00:00"),
    ("2026-11-01", "2026-11-01T07:00:00"),   # still PDT at midnight
    ("2026-11-02", "2026-11-02T08:00:00"),
])
def test_a_day_starts_at_its_pacific_midnight(day, instant):
    assert D.day_start(day) == _utc(instant)
    assert D.pacific_day(D.day_start(day)) == day
    assert D.pacific_day(D.day_start(day) - 1) == D.next_day(day, -1)


# ── the generator ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("seed", range(4))
def test_a_generated_box_is_a_good_one(seed):
    box = D.generate(random.Random(seed), D.MIN_DEPTH, budget=60)
    tiles, target, m = tuple(box["tiles"]), tuple(box["target"]), box["minimum"]
    assert m == D.MIN_DEPTH
    # the stored line is a shortest one, and nothing shorter opens it
    assert len(box["solution"]) == m and corners_match(replay(tiles, box["solution"]), target)
    assert len(solve(tiles, target)) == m
    # the target is one of the allowed shapes, never gray
    assert any(shape(a, b) == target for shape in D.SHAPES for a in target for b in target)
    assert "GY" not in target
    assert not corners_match(tiles, target)
    # every colour matters: graying any one changes the minimum
    for c in set(tiles) - {"GY"}:
        grayed = tuple("GY" if x == c else x for x in tiles)
        line = solve(grayed, target)
        assert line is None or len(line) != m, f"{c} is decoration on {tiles}"
    assert 1 <= D.shortest_ways(tiles, target) <= D.MAX_WAYS


def test_the_generator_reaches_the_deep_end_too():
    box = D.generate(random.Random(7), 12, budget=60)
    assert box["minimum"] == 12


def test_a_day_is_generated_once_and_kept(conn, monkeypatch):
    monkeypatch.setattr(D, "MAX_DEPTH", D.MIN_DEPTH)    # keep the draw at the fast end
    first = D.ensure_day(conn, TODAY)
    assert D.MIN_DEPTH <= first["minimum"] <= D.MAX_DEPTH
    assert D.ensure_day(conn, TODAY) == first
    # a second writer racing for the same day gets the stored box back, not its own
    other = {**first, "tiles": list(reversed(first["tiles"]))}
    assert D.store_day(conn, TODAY, other) == first


# ── attempts ─────────────────────────────────────────────────────────────────
def test_an_attempt_only_grows():
    assert D.extends([[]], [[1]])
    assert D.extends([[1, 2]], [[1, 2, 3]])
    assert D.extends([[1, 2]], [[1, 2], [4]])
    assert D.extends([[1, 2], [3]], [[1, 2], [3, 5], []])
    assert not D.extends([[1, 2]], [[1]])                 # a press taken back
    assert not D.extends([[1, 2]], [[1, 3]])              # a different press
    assert not D.extends([[1, 2], [3]], [[1, 2]])         # a reset taken back
    assert not D.extends([[1, 2], [3]], [[1], [3]])       # an earlier segment changed


def test_a_reset_keeps_the_count(conn):
    pair = _cancelling_pair()
    D.save_attempt(conn, "u_alice", BOX, [pair], opened=False)
    r = D.save_attempt(conn, "u_alice", BOX, [pair, []], opened=False)   # the reset
    assert r["moves"] == 2
    r = D.save_attempt(conn, "u_alice", BOX, [pair, LINE], opened=True)
    assert r == {"segments": [pair, LINE], "moves": 2 + len(LINE), "solved": True}
    assert D.load_attempt(conn, "u_alice", TODAY)["solved"] is True


def test_progress_is_saved_and_cannot_be_rewound(conn):
    D.save_attempt(conn, "u_alice", BOX, [[LINE[0]]], opened=False)
    assert D.load_attempt(conn, "u_alice", TODAY) == {"segments": [[LINE[0]]], "moves": 1, "solved": False}
    with pytest.raises(D.Refused) as e:
        D.save_attempt(conn, "u_alice", BOX, [[]], opened=False)
    assert e.value.status == 409


def test_one_attempt_an_opened_box_is_final(conn):
    D.save_attempt(conn, "u_alice", BOX, [LINE], opened=True)
    # the same final post again (a retry after a dropped response) answers the same
    assert D.save_attempt(conn, "u_alice", BOX, [LINE], opened=True)["moves"] == len(LINE)
    for segs in ([LINE + [0]], [LINE, []], [LINE, LINE]):
        with pytest.raises(D.Refused) as e:
            D.save_attempt(conn, "u_alice", BOX, segs, opened=True)
        assert e.value.status == 409


def test_an_open_must_open_the_box_from_its_first_board(conn):
    with pytest.raises(D.Refused) as e:
        D.save_attempt(conn, "u_alice", BOX, [LINE[:-1]], opened=True)
    assert e.value.status == 400
    # the solving presses BEFORE a reset do not count as opening it
    with pytest.raises(D.Refused):
        D.save_attempt(conn, "u_alice", BOX, [LINE, []], opened=True)
    assert D.load_attempt(conn, "u_alice", TODAY) is None


@pytest.mark.parametrize("segs", [[], [[9]], [[-1]], [["1"]], [[True]], [1, 2], [[0] * (D.MAX_MOVES + 1)]])
def test_malformed_attempts_are_refused(conn, segs):
    with pytest.raises(D.Refused):
        D.save_attempt(conn, "u_alice", BOX, segs, opened=False)


# ── the board ────────────────────────────────────────────────────────────────
def test_fewest_presses_then_first_to_finish(conn):
    pair = _cancelling_pair()
    D.save_attempt(conn, "u_bob", BOX, [pair, LINE], opened=True, now=100.0)
    D.save_attempt(conn, "u_alice", BOX, [LINE], opened=True, now=200.0)
    D.save_attempt(conn, "u_carol", BOX, [LINE], opened=True, now=150.0)
    D.save_attempt(conn, "u_dan", BOX, [[LINE[0]]], opened=False, now=50.0)   # unfinished
    board = D.daily_board(conn, BOX, "u_alice", reveal=False)
    assert [(e["rank"], e["name"], e["moves"]) for e in board["entries"]] == [
        (1, "?", len(LINE)), (2, "alice", len(LINE)), (3, "bob", len(LINE) + 2)]
    assert board["total"] == 3 and board["you"]["rank"] == 2


def test_today_keeps_the_minimum_secret_and_yesterday_reveals_it(conn):
    D.save_attempt(conn, "u_alice", BOX, [LINE], opened=True)
    D.save_attempt(conn, "u_bob", BOX, [LINE], opened=True)
    live = D.daily_board(conn, BOX, "u_alice", reveal=False)
    assert "minimum" not in live and "solution" not in live
    assert [("optimal" in e) for e in live["entries"]] == [True, False]   # only your own row
    done = D.daily_board(conn, BOX, None, reveal=True)
    assert done["minimum"] == len(LINE) and done["solution"] == LINE
    assert done["tiles"] == FIRST["tiles"] and done["target"] == FIRST["target"]
    assert all(e["optimal"] for e in done["entries"])


# ── retries: Best Attempt ───────────────────────────────────────────────────────
def test_the_one_attempt_seeds_best_shot(conn):
    pair = _cancelling_pair()
    D.save_attempt(conn, "u_alice", BOX, [pair, LINE], opened=True, now=100.0)
    board = D.daily_board(conn, BOX, "u_alice", reveal=False)
    assert [(e["name"], e["moves"]) for e in board["entries"]] == [("alice", len(LINE) + 2)]
    assert [(e["name"], e["moves"]) for e in board["best"]["entries"]] == [("alice", len(LINE) + 2)]


def test_a_retry_needs_the_one_attempt_opened_first(conn):
    with pytest.raises(D.Refused) as e:
        D.save_retry(conn, "u_alice", BOX, LINE)
    assert e.value.status == 403
    D.save_attempt(conn, "u_alice", BOX, [[LINE[0]]], opened=False)          # partway through
    with pytest.raises(D.Refused) as e:
        D.save_retry(conn, "u_alice", BOX, LINE)
    assert e.value.status == 403


def test_retries_keep_the_best_and_leave_one_shot_alone(conn):
    pair = _cancelling_pair()
    D.save_attempt(conn, "u_alice", BOX, [pair + LINE], opened=True, now=100.0)
    assert D.save_retry(conn, "u_alice", BOX, pair + pair + LINE, now=150.0) == {
        "best": len(LINE) + 2, "improved": False}                              # worse: ignored
    assert D.save_retry(conn, "u_alice", BOX, LINE, now=200.0) == {"best": len(LINE), "improved": True}
    with pytest.raises(D.Refused):
        D.save_retry(conn, "u_alice", BOX, LINE[:-1])                          # does not open it
    board = D.daily_board(conn, BOX, "u_alice", reveal=False)
    assert board["you"] == {"rank": 1, "moves": len(LINE) + 2, "optimal": False}
    assert board["best"]["you"] == {"rank": 1, "moves": len(LINE), "optimal": True}


def test_best_shot_ties_go_to_the_first_to_get_there(conn):
    pair = _cancelling_pair()
    D.save_attempt(conn, "u_alice", BOX, [pair + LINE], opened=True, now=100.0)
    D.save_attempt(conn, "u_bob", BOX, [pair + LINE], opened=True, now=110.0)
    D.save_retry(conn, "u_bob", BOX, LINE, now=120.0)
    D.save_retry(conn, "u_alice", BOX, LINE, now=130.0)
    D.save_retry(conn, "u_bob", BOX, LINE, now=140.0)                          # a tie with yourself: no move
    best = D.daily_board(conn, BOX, None, reveal=False)["best"]
    assert [e["name"] for e in best["entries"]] == ["bob", "alice"]
    assert all("optimal" not in e for e in best["entries"])                    # still today's secret
    done = D.daily_board(conn, BOX, None, reveal=True)["best"]
    assert all(e["optimal"] for e in done["entries"])


def test_attempts_opened_before_best_shot_are_carried_over(conn):
    conn.cursor().execute("INSERT INTO box_daily_attempts (user_id, day, segments, moves, solved_at, updated_at) "
                          "VALUES ('u_bob', ?, '[[0]]', 9, 50.0, 50.0)", (TODAY,))
    conn.commit()
    D.init_daily_db(conn)
    D.init_daily_db(conn)                                                      # and only once
    best = D.daily_board(conn, BOX, None, reveal=False)["best"]
    assert [(e["name"], e["moves"]) for e in best["entries"]] == [("bob", 9)] and best["total"] == 1


# ── the routes ───────────────────────────────────────────────────────────────
@pytest.fixture()
def app(get_conn, conn, monkeypatch):
    monkeypatch.setattr(D, "pacific_day", lambda ts=None: TODAY)
    D.store_day(conn, TODAY, BOX)
    D.store_day(conn, YESTERDAY, {**BOX, "day": YESTERDAY})
    a = FastAPI()
    B.setup_box_puzzles(a, get_conn, {"tok_alice": ALICE}.get)
    return a


def _endpoint(app, method: str, path: str):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r.endpoint
    raise AssertionError(f"no route {method} {path}")


def test_the_daily_route_hands_out_today_without_its_answer(app):
    get = _endpoint(app, "GET", "/boxpuzzles/daily")
    r = get(user=None)
    assert r["day"] == TODAY and r["tiles"] == FIRST["tiles"] and r["target"] == FIRST["target"]
    assert r["attempt"] is None and r["yesterday"] == YESTERDAY
    assert r["next_at"] == D.day_start("2026-10-06")
    assert "minimum" not in r and "solution" not in r


def test_the_attempt_round_trip(app):
    get = _endpoint(app, "GET", "/boxpuzzles/daily")
    post = _endpoint(app, "POST", "/boxpuzzles/daily/attempt")
    board = _endpoint(app, "GET", "/boxpuzzles/daily/{day}/board")
    r = post(B.AttemptIn(day=TODAY, segments=[[LINE[0]]]), user=ALICE)
    assert r == {"moves": 1, "solved": False}
    assert get(user=ALICE)["attempt"] == {"segments": [[LINE[0]]], "moves": 1, "solved": False}
    r = post(B.AttemptIn(day=TODAY, segments=[LINE], open=True), user=ALICE)
    assert r["solved"] and r["optimal"] is True and r["leaderboard"]["you"]["rank"] == 1
    assert "minimum" not in r["leaderboard"]
    assert "minimum" not in board(TODAY, line=None, user=ALICE)
    assert board(YESTERDAY, line=None, user=None)["minimum"] == len(LINE)


def test_todays_board_is_only_for_those_who_have_opened_the_box(app):
    """No score reaches anyone still playing (or not playing) today's box."""
    post = _endpoint(app, "POST", "/boxpuzzles/daily/attempt")
    board = _endpoint(app, "GET", "/boxpuzzles/daily/{day}/board")
    refused = (
        lambda: board(TODAY, line=None, user=None),                                   # a passer-by
        lambda: board(TODAY, line=None, user=ALICE),                                  # before playing
        lambda: board(TODAY, line=",".join(map(str, LINE[:-1])), user=None),          # a line that does not open it
        lambda: board(TODAY, line="9,x", user=None),
    )
    for call in refused:
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 403
    post(B.AttemptIn(day=TODAY, segments=[[LINE[0]]]), user=ALICE)
    with pytest.raises(HTTPException) as e:                                           # partway through
        board(TODAY, line=None, user=ALICE)
    assert e.value.status_code == 403
    post(B.AttemptIn(day=TODAY, segments=[LINE], open=True), user=ALICE)
    assert board(TODAY, line=None, user=ALICE)["you"]["rank"] == 1                    # opened: on record
    guest = board(TODAY, line=",".join(map(str, LINE)), user=None)                    # a guest's proof
    assert [e["name"] for e in guest["entries"]] == ["alice"] and "minimum" not in guest
    assert "optimal" not in guest["entries"][0]
    # the day before is open to everyone, minimum and all
    assert board(YESTERDAY, line=None, user=None)["minimum"] == len(LINE)


def test_the_routes_refuse_what_they_should(app):
    post = _endpoint(app, "POST", "/boxpuzzles/daily/attempt")
    board = _endpoint(app, "GET", "/boxpuzzles/daily/{day}/board")
    member = next(d.call for r in app.routes if getattr(r, "path", "") == "/boxpuzzles/daily/attempt"
                  for d in r.dependant.dependencies)
    for call, code in (
        (lambda: member(None), 401),                                                     # guests do not post
        (lambda: post(B.AttemptIn(day=YESTERDAY, segments=[LINE], open=True), user=ALICE), 409),
        (lambda: post(B.AttemptIn(day=TODAY, segments=[LINE[:-1]], open=True), user=ALICE), 400),
        (lambda: board("2026-10-06", line=None, user=None), 404),                         # tomorrow
        (lambda: board("2026-01-01", line=None, user=None), 404),                         # never generated
        (lambda: board("not-a-day", line=None, user=None), 404),
    ):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == code


def test_the_retry_round_trip(app):
    post = _endpoint(app, "POST", "/boxpuzzles/daily/attempt")
    retry = _endpoint(app, "POST", "/boxpuzzles/daily/retry")
    pair = _cancelling_pair()
    with pytest.raises(HTTPException) as e:
        retry(B.RetryIn(day=TODAY, moves=LINE), user=ALICE)                    # before the one attempt
    assert e.value.status_code == 403
    post(B.AttemptIn(day=TODAY, segments=[pair + LINE], open=True), user=ALICE)
    r = retry(B.RetryIn(day=TODAY, moves=LINE), user=ALICE)
    assert r["moves"] == len(LINE) and r["best"] == len(LINE) and r["improved"] and r["optimal"] is True
    assert r["leaderboard"]["you"]["moves"] == len(LINE) + 2                    # First Attempt never moves
    assert r["leaderboard"]["best"]["you"]["moves"] == len(LINE)
    assert "minimum" not in r["leaderboard"]
    for payload, code in ((B.RetryIn(day=YESTERDAY, moves=LINE), 409),
                          (B.RetryIn(day=TODAY, moves=LINE[:-1]), 400)):
        with pytest.raises(HTTPException) as e:
            retry(payload, user=ALICE)
        assert e.value.status_code == code


def test_saves_are_rate_limited_per_account(app):
    post = _endpoint(app, "POST", "/boxpuzzles/daily/attempt")
    seg = []
    for _ in range(B._daily_minute.max_hits):
        seg = seg + [CORNERS[0]]
        post(B.AttemptIn(day=TODAY, segments=[seg]), user=ALICE)
    with pytest.raises(HTTPException) as e:
        post(B.AttemptIn(day=TODAY, segments=[seg + [0]]), user=ALICE)
    assert e.value.status_code == 429
