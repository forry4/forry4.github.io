"""Box Puzzles leaderboard (boxpuzzles/api.py).

Pure functions run on a real sqlite file through core.db's _Conn wrapper; routes
are called as their registered endpoints (the repo has no TestClient), like Notes.
"""
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException

from boxpuzzles import api as B
from boxpuzzles.engine import press, solve
from core.db import _Conn

FIRST = B.BANK[next(iter(B.BANK))]           # the easiest box
PID = FIRST["id"]
LINE = solve(FIRST["tiles"], FIRST["target"])  # a shortest solve
ALICE = {"id": "u_alice", "name": "alice"}
BOB = {"id": "u_bob", "name": "bob"}


def _longer_line():
    """A real solve LONGER than the minimum: two presses that cancel, then the line."""
    for i in range(9):
        for j in range(9):
            if press(press(FIRST["tiles"], i), j) == tuple(FIRST["tiles"]):
                return [i, j] + LINE
    raise AssertionError("no cancelling pair on the first box")


@pytest.fixture(autouse=True)
def _fresh_limits():
    B._solves_minute.reset()
    yield


@pytest.fixture()
def get_conn(tmp_path):
    path = str(tmp_path / "box.db")

    def make():
        c = _Conn(sqlite3.connect(path, check_same_thread=False))
        c.cursor().execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT)")
        c.commit()
        return c
    return make


@pytest.fixture()
def conn(get_conn):
    c = get_conn()
    B.init_box_db(c)
    cur = c.cursor()
    for u in (ALICE, BOB):
        cur.execute("INSERT INTO users (id, name) VALUES (?, ?)", (u["id"], u["name"]))
    c.commit()
    yield c
    c.close()


@pytest.fixture()
def app(get_conn, conn):
    a = FastAPI()
    users = {"tok_alice": ALICE, "tok_bob": BOB}
    B.setup_box_puzzles(a, get_conn, users.get)
    return a


def _endpoint(app, method: str, path: str):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r.endpoint
    raise AssertionError(f"no route {method} {path}")


# ── checking a solve ─────────────────────────────────────────────────────────
def test_a_real_solve_scores_its_length():
    assert B.check_solve(PID, LINE) == len(LINE) == B.MINIMUMS[PID]
    assert B.check_solve(PID, _longer_line()) == len(LINE) + 2


def test_a_solve_that_does_not_open_the_box_is_refused():
    for moves in ([], LINE[:-1], [4] * 3):
        with pytest.raises(ValueError):
            B.check_solve(PID, moves)
    with pytest.raises(ValueError):
        B.check_solve("nope", LINE)
    with pytest.raises(ValueError):
        B.check_solve(PID, LINE + [9])
    with pytest.raises(ValueError):
        B.check_solve(PID, [0] * (B.MAX_MOVES + 1))


# ── the board ────────────────────────────────────────────────────────────────
def test_best_is_kept_and_a_tie_keeps_the_earlier_time(conn):
    long = len(LINE) + 2
    assert B.record_solve(conn, "u_alice", PID, long, now=10) == {"best": long, "improved": True}
    assert B.record_solve(conn, "u_alice", PID, long + 4, now=11) == {"best": long, "improved": False}
    assert B.record_solve(conn, "u_bob", PID, long, now=12)["improved"]
    # alice tied first, so she ranks ahead of bob on the same count
    names = [e["name"] for e in B.leaderboard(conn, PID)["entries"]]
    assert names == ["alice", "bob"]
    # a tie with her own best does not refresh her time
    B.record_solve(conn, "u_alice", PID, long, now=99)
    assert [e["name"] for e in B.leaderboard(conn, PID)["entries"]] == ["alice", "bob"]
    assert B.record_solve(conn, "u_bob", PID, len(LINE), now=13) == {"best": len(LINE), "improved": True}
    assert [e["name"] for e in B.leaderboard(conn, PID)["entries"]] == ["bob", "alice"]


def test_optimal_is_shown_only_on_your_own_row(conn):
    B.record_solve(conn, "u_alice", PID, len(LINE), now=1)          # alice: optimal
    B.record_solve(conn, "u_bob", PID, len(LINE) + 2, now=2)        # bob: not
    as_bob = B.leaderboard(conn, PID, "u_bob")
    alice_row, bob_row = as_bob["entries"]
    assert "optimal" not in alice_row and "you" not in alice_row
    assert bob_row["you"] and bob_row["optimal"] is False
    assert as_bob["you"] == {"rank": 2, "moves": len(LINE) + 2, "optimal": False}
    as_alice = B.leaderboard(conn, PID, "u_alice")
    assert as_alice["entries"][0]["optimal"] is True
    assert "optimal" not in as_alice["entries"][1]
    anon = B.leaderboard(conn, PID)
    assert all("optimal" not in e and "you" not in e for e in anon["entries"])
    assert anon["you"] is None and anon["total"] == 2


def test_your_rank_is_reported_when_you_are_off_the_top(conn):
    for n in range(5):
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, name) VALUES (?, ?)", (f"u{n}", f"p{n}"))
        B.record_solve(conn, f"u{n}", PID, len(LINE), now=n)
    B.record_solve(conn, "u_bob", PID, len(LINE) + 2, now=50)
    board = B.leaderboard(conn, PID, "u_bob", size=3)
    assert len(board["entries"]) == 3 and board["total"] == 6
    assert board["you"]["rank"] == 6


def test_my_results_carry_your_own_optimal_flags(conn):
    B.record_solve(conn, "u_alice", PID, len(LINE) + 2)
    assert B.my_results(conn, "u_alice") == {PID: {"moves": len(LINE) + 2, "optimal": False}}
    B.record_solve(conn, "u_alice", PID, len(LINE))
    assert B.my_results(conn, "u_alice")[PID]["optimal"] is True
    assert B.my_results(conn, "u_bob") == {}


# ── the routes ───────────────────────────────────────────────────────────────
def test_posting_and_your_results_need_an_account(app):
    member = next(d.call for r in app.routes if getattr(r, "path", "") == "/boxpuzzles/mine"
                  for d in r.dependant.dependencies)
    with pytest.raises(HTTPException) as e:
        member(None)
    assert e.value.status_code == 401
    # the leaderboard read is open to everyone
    board = _endpoint(app, "GET", "/boxpuzzles/leaderboard/{puzzle_id}")
    assert board(PID, user=None)["entries"] == []


def test_solve_round_trip(app):
    post = _endpoint(app, "POST", "/boxpuzzles/solve")
    mine = _endpoint(app, "GET", "/boxpuzzles/mine")
    board = _endpoint(app, "GET", "/boxpuzzles/leaderboard/{puzzle_id}")

    r = post(B.SolveIn(puzzle=PID, moves=_longer_line()), user=ALICE)
    assert r["improved"] and r["optimal"] is False and r["best"] == len(LINE) + 2
    assert r["leaderboard"]["you"]["rank"] == 1

    r = post(B.SolveIn(puzzle=PID, moves=LINE), user=ALICE)
    assert r["improved"] and r["optimal"] is True
    assert mine(user=ALICE)["results"][PID] == {"moves": len(LINE), "optimal": True}

    seen_by_bob = board(PID, user=BOB)
    assert seen_by_bob["entries"] == [{"rank": 1, "name": "alice", "moves": len(LINE)}]


def test_solve_errors_map_to_http(app):
    post = _endpoint(app, "POST", "/boxpuzzles/solve")
    board = _endpoint(app, "GET", "/boxpuzzles/leaderboard/{puzzle_id}")
    for call, code in (
        (lambda: post(B.SolveIn(puzzle=PID, moves=LINE[:-1]), user=ALICE), 400),
        (lambda: post(B.SolveIn(puzzle="nope", moves=LINE), user=ALICE), 400),
        (lambda: board("nope", user=None), 404),
    ):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == code


def test_solves_are_rate_limited_per_account(app, monkeypatch):
    from core import alerts
    raised = []
    monkeypatch.setattr(alerts, "alert", lambda *a, **k: raised.append(a))
    post = _endpoint(app, "POST", "/boxpuzzles/solve")
    for _ in range(B._solves_minute.max_hits):
        post(B.SolveIn(puzzle=PID, moves=LINE), user=ALICE)
    with pytest.raises(HTTPException) as e:
        post(B.SolveIn(puzzle=PID, moves=LINE), user=ALICE)
    assert e.value.status_code == 429 and raised
    post(B.SolveIn(puzzle=PID, moves=LINE), user=BOB)    # another account is unaffected
