"""Boss Rush run tokens, server timing and the public times board."""
from __future__ import annotations

import random
import secrets
import time
from contextlib import closing
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from bossrush.dungeon import BOSSES, arena
from core.ratelimit import SlidingWindowLimiter

RUN_TTL = 2 * 60 * 60
BOARD_SIZE = 20
_starts = SlidingWindowLimiter(max_hits=30, window_seconds=60)


class StartIn(BaseModel):
    character: Literal["ranger", "paladin", "diviner", "ninja"]


def setup_boss_rush(app, connect, user_by_session, token_resolver) -> None:
    with closing(connect()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boss_rush_runs (
                run_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL,
                character TEXT NOT NULL,
                started_at REAL NOT NULL,
                cleared INTEGER NOT NULL DEFAULT 0,
                elapsed_ms INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_times "
                     "ON boss_rush_runs (elapsed_ms, started_at, run_id) WHERE elapsed_ms IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_open "
                     "ON boss_rush_runs (started_at) WHERE elapsed_ms IS NULL")
        conn.commit()

    @app.get("/bossrush/leaderboard")
    def leaderboard():
        with closing(connect()) as conn:
            rows = conn.execute("""
                SELECT player_name, character, elapsed_ms FROM boss_rush_runs
                WHERE elapsed_ms IS NOT NULL ORDER BY elapsed_ms, started_at, run_id LIMIT ?
            """, (BOARD_SIZE,)).fetchall()
        return {"entries": [
            {"rank": rank, "name": row[0], "character": row[1], "elapsed_ms": row[2]}
            for rank, row in enumerate(rows, 1)
        ]}

    @app.post("/bossrush/runs")
    def start(body: StartIn, request: Request, token: str | None = Depends(token_resolver)):
        ip = request.client.host if request.client else "unknown"
        if _starts.exceeded(ip):
            raise HTTPException(429, "Too many starts. Try again in a minute.")
        _starts.record(ip)
        user = user_by_session(token) if token else None
        if token and user is None:
            raise HTTPException(401, "Your session expired. Sign in again to start a run.")
        run_id = secrets.token_urlsafe(24)
        order = random.sample(list(BOSSES), len(BOSSES))
        stages = [arena(rift, f"{run_id}:{rift}") for rift in order]
        now = time.time()
        with closing(connect()) as conn:
            conn.execute("DELETE FROM boss_rush_runs WHERE elapsed_ms IS NULL AND started_at < ?", (now - RUN_TTL,))
            conn.execute("INSERT INTO boss_rush_runs (run_id, player_name, character, started_at) VALUES (?, ?, ?, ?)",
                         (run_id, user["name"] if user else "Guest", body.character, now))
            conn.commit()
        return {"run_id": run_id, "stages": stages}

    @app.post("/bossrush/runs/{run_id}/clears/{stage}")
    def clear(run_id: str, stage: int):
        if len(run_id) != 32 or not 1 <= stage <= len(BOSSES):
            raise HTTPException(404, "Run or stage not found.")
        now = time.time()
        with closing(connect()) as conn:
            # Conditional write makes repeated clears and overlapping requests safe.
            # The browser reports combat outcomes. The server owns order and time.
            conn.execute("""
                UPDATE boss_rush_runs SET cleared=?, elapsed_ms=CASE
                    WHEN ? = ? THEN MAX(1, CAST((? - started_at) * 1000 AS INTEGER)) ELSE NULL END
                WHERE run_id=? AND cleared=? AND started_at >= ?
            """, (stage, stage, len(BOSSES), now, run_id, stage - 1, now - RUN_TTL))
            conn.commit()
            row = conn.execute("SELECT cleared, elapsed_ms, started_at FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
        if row is None or (row[1] is None and row[2] < now - RUN_TTL):
            raise HTTPException(404, "This run expired. Start a new one to post a time.")
        if stage > row[0]:
            raise HTTPException(409, "Clear the earlier stages first.")
        return {"cleared": stage, "elapsed_ms": row[1] if stage == len(BOSSES) else None}
