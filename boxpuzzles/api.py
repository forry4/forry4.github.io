"""Box Puzzles — the leaderboard. The puzzles themselves are played in the browser.

A box is solo and deterministic, so there is nothing to serve while one is being
played: the bank ships with the page (`puzzles.json`) and the browser runs the rules
(`engine.js`). The server's one job is the leaderboard, and it is the only part a
player could want to cheat, so:

  * A SOLVE IS A LIST OF TILE PRESSES, replayed here through `engine.py` from the
    box's starting board. It counts only if all four corners then match; its score is
    the length of the list. Corner buttons are not sent — a lit button goes dark the
    moment its corner stops matching, so "all four corners match" is exactly what
    opening the box takes. The count is the presses since the box was last reset,
    which the client keeps by starting a fresh list on every reset.
  * ONE ROW PER PLAYER PER BOX — their fewest presses. A tie with your own best does
    not move the row, so the earlier time stands and ties on the board go to whoever
    got there first.
  * THE MINIMUM IS THE SERVER'S SECRET. `minimums.json` never ships to the browser,
    and only YOUR OWN row ever carries `optimal`, so a reader of the leaderboard can
    see the best score but cannot tell whether anyone has reached the minimum.
  * Signed-in accounts only, for posting and for "your results". Reading a box's
    leaderboard needs no account.

The handlers are plain `def`, so their DB round-trips run in FastAPI's threadpool
rather than on the event loop the game sockets share.
"""
from __future__ import annotations

import json
import pathlib
import time

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import alerts
from core.ratelimit import SlidingWindowLimiter

from boxpuzzles.engine import corners_match, replay

HERE = pathlib.Path(__file__).resolve().parent
BANK = {p["id"]: p for p in json.loads((HERE / "puzzles.json").read_text(encoding="utf-8"))}
MINIMUMS: dict[str, int] = json.loads((HERE / "minimums.json").read_text(encoding="utf-8"))

MAX_MOVES = 1000          # a solve longer than this is not a leaderboard entry
BOARD_SIZE = 20           # rows shown per box

_solves_minute = SlidingWindowLimiter(max_hits=30, window_seconds=60)


def init_box_db(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS box_puzzle_results (
        user_id TEXT NOT NULL,
        puzzle_id TEXT NOT NULL,
        moves INTEGER NOT NULL,
        solved_at REAL NOT NULL,
        PRIMARY KEY (user_id, puzzle_id)
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_box_results_board "
                "ON box_puzzle_results (puzzle_id, moves, solved_at)")
    conn.commit()


# ── pure functions (each takes a connection; tested on a real sqlite file) ────
def check_solve(puzzle_id: str, moves: list) -> int:
    """The score of a submitted solve, or ValueError if it does not open the box."""
    p = BANK.get(puzzle_id)
    if p is None:
        raise ValueError("no such puzzle")
    if len(moves) > MAX_MOVES:
        raise ValueError("too many moves")
    if not corners_match(replay(p["tiles"], moves), p["target"]):
        raise ValueError("that does not open the box")
    return len(moves)


def is_optimal(puzzle_id: str, moves: int) -> bool:
    return moves <= MINIMUMS[puzzle_id]


def record_solve(conn, user_id: str, puzzle_id: str, moves: int, now: float | None = None) -> dict:
    """Keep the player's best. Returns {best, improved}."""
    now = time.time() if now is None else now
    cur = conn.cursor()
    cur.execute("SELECT moves FROM box_puzzle_results WHERE user_id=? AND puzzle_id=?",
                (user_id, puzzle_id))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO box_puzzle_results (user_id, puzzle_id, moves, solved_at) "
                    "VALUES (?, ?, ?, ?)", (user_id, puzzle_id, moves, now))
        conn.commit()
        return {"best": moves, "improved": True}
    if moves < row[0]:
        cur.execute("UPDATE box_puzzle_results SET moves=?, solved_at=? "
                    "WHERE user_id=? AND puzzle_id=?", (moves, now, user_id, puzzle_id))
        conn.commit()
        return {"best": moves, "improved": True}
    return {"best": row[0], "improved": False}


def leaderboard(conn, puzzle_id: str, user_id: str | None = None, size: int = BOARD_SIZE) -> dict:
    """The top `size` rows, plus the caller's own row (ranked) wherever it falls.
    `optimal` appears on the caller's row ONLY."""
    cur = conn.cursor()
    cur.execute("""
        SELECT r.user_id, u.name, r.moves FROM box_puzzle_results r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE r.puzzle_id=? ORDER BY r.moves, r.solved_at LIMIT ?""", (puzzle_id, size))
    entries = []
    for rank, (uid, name, moves) in enumerate(cur.fetchall(), 1):
        e = {"rank": rank, "name": name or "?", "moves": moves}
        if user_id and uid == user_id:
            e["you"] = True
            e["optimal"] = is_optimal(puzzle_id, moves)
        entries.append(e)
    cur.execute("SELECT COUNT(*) FROM box_puzzle_results WHERE puzzle_id=?", (puzzle_id,))
    total = cur.fetchone()[0]
    you = None
    if user_id:
        cur.execute("SELECT moves, solved_at FROM box_puzzle_results WHERE user_id=? AND puzzle_id=?",
                    (user_id, puzzle_id))
        mine = cur.fetchone()
        if mine is not None:
            cur.execute("""SELECT COUNT(*) FROM box_puzzle_results WHERE puzzle_id=?
                           AND (moves < ? OR (moves = ? AND solved_at < ?))""",
                        (puzzle_id, mine[0], mine[0], mine[1]))
            you = {"rank": cur.fetchone()[0] + 1, "moves": mine[0],
                   "optimal": is_optimal(puzzle_id, mine[0])}
    return {"entries": entries, "total": total, "you": you}


def my_results(conn, user_id: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT puzzle_id, moves FROM box_puzzle_results WHERE user_id=?", (user_id,))
    return {pid: {"moves": moves, "optimal": is_optimal(pid, moves)}
            for pid, moves in cur.fetchall() if pid in BANK}


# ── routes ──────────────────────────────────────────────────────────────────
class SolveIn(BaseModel):
    puzzle: str = Field(max_length=64)
    moves: list[int] = Field(max_length=MAX_MOVES)


def _default_token_resolver(token: str | None = Query(default=None)) -> str | None:
    return token


def setup_box_puzzles(app, get_db_conn, get_user_by_session, token_resolver=None) -> None:
    """Create the table and register the /boxpuzzles routes. Dependencies are
    injected from the composition root (the Books/Notes pattern)."""
    conn = get_db_conn()
    try:
        init_box_db(conn)
    finally:
        conn.close()

    resolve_token = token_resolver or _default_token_resolver

    def run(fn):
        conn = get_db_conn()
        try:
            return fn(conn)
        finally:
            conn.close()

    def viewer(token: str | None = Depends(resolve_token)) -> dict | None:
        user = get_user_by_session(token) if token else None
        return user if user and user.get("id") else None

    def member(user: dict | None = Depends(viewer)) -> dict:
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to post to the leaderboard.")
        return user

    @app.get("/boxpuzzles/leaderboard/{puzzle_id}")
    def box_leaderboard(puzzle_id: str, user: dict | None = Depends(viewer)):
        if puzzle_id not in BANK:
            raise HTTPException(status_code=404, detail="no such puzzle")
        return run(lambda c: leaderboard(c, puzzle_id, user["id"] if user else None))

    @app.get("/boxpuzzles/mine")
    def box_mine(user: dict = Depends(member)):
        return {"results": run(lambda c: my_results(c, user["id"]))}

    @app.post("/boxpuzzles/solve")
    def box_solve(payload: SolveIn, user: dict = Depends(member)):
        uid = user["id"]
        if _solves_minute.exceeded(uid):
            alerts.alert("boxpuzzles-rate", f"{user.get('name') or uid} is posting Box Puzzle solves "
                         "faster than the limit; requests are refused.", key=f"boxpuzzles-rate:{uid}")
            raise HTTPException(status_code=429, detail="Too many solves. Wait a minute and try again.")
        _solves_minute.record(uid)
        try:
            moves = check_solve(payload.puzzle, payload.moves)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        def write(c):
            rec = record_solve(c, uid, payload.puzzle, moves)
            board = leaderboard(c, payload.puzzle, uid)
            return {"moves": moves, **rec, "optimal": is_optimal(payload.puzzle, rec["best"]),
                    "leaderboard": board}
        return run(write)
