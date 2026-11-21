"""Boss Rush run tokens, server timing and the public times board."""
from __future__ import annotations

import random
import secrets
import time
from contextlib import closing
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from bossrush.dungeon import BOSSES, BOSS_SETS, DEFAULT_BOSS_SET, arena
from core.ratelimit import SlidingWindowLimiter

RUN_TTL = 2 * 60 * 60
BOARD_SIZE = 20
STAGES_PER_RUN = 3
_starts = SlidingWindowLimiter(max_hits=30, window_seconds=60)


Character = Literal["ranger", "paladin", "diviner", "ninja"]


class StartIn(BaseModel):
    character: Character
    set_id: str = DEFAULT_BOSS_SET
    starter_timer: bool = False


def setup_boss_rush(app, connect, user_by_session, token_resolver) -> None:
    with closing(connect()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boss_rush_runs (
                run_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL,
                character TEXT NOT NULL,
                started_at REAL NOT NULL,
                cleared INTEGER NOT NULL DEFAULT 0,
                elapsed_ms INTEGER,
                combat_ms INTEGER,
                entered_at REAL,
                paused_at REAL,
                set_id TEXT NOT NULL DEFAULT 'rift-trio'
            )
        """)
        # Existing runs use the old wall clock; NULL combat_ms preserves their protocol.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(boss_rush_runs)").fetchall()}
        if "combat_ms" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN combat_ms INTEGER")
        if "entered_at" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN entered_at REAL")
        if "paused_at" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN paused_at REAL")
        if "set_id" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN set_id TEXT NOT NULL DEFAULT 'rift-trio'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_set_times "
                     "ON boss_rush_runs (set_id, elapsed_ms, started_at, run_id) WHERE elapsed_ms IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_open "
                     "ON boss_rush_runs (started_at) WHERE elapsed_ms IS NULL")
        conn.commit()

    @app.get("/bossrush/sets")
    def sets(lantern: bool = False):
        # Bundles cached before Lantern Trio shipped cannot simulate its bosses.
        return {"sets": [
            {"id": set_id, "name": name, "bosses": [BOSSES[key][1] for key in bosses],
             "playable": len(bosses) == STAGES_PER_RUN and (set_id != "lantern-trio" or lantern)}
            for set_id, (name, bosses) in BOSS_SETS.items()
        ]}

    @app.get("/bossrush/leaderboard")
    def leaderboard(set_id: str = DEFAULT_BOSS_SET, character: Character | None = None):
        if set_id not in BOSS_SETS:
            raise HTTPException(404, "Boss set not found.")
        where = "set_id=? AND elapsed_ms IS NOT NULL"
        values = [set_id]
        if character is not None:
            where += " AND character=?"
            values.append(character)
        with closing(connect()) as conn:
            rows = conn.execute(f"""
                SELECT player_name, character, elapsed_ms FROM boss_rush_runs
                WHERE {where} ORDER BY elapsed_ms, started_at, run_id LIMIT ?
            """, (*values, BOARD_SIZE)).fetchall()
        return {"entries": [
            {"rank": rank, "name": row[0], "character": row[1], "elapsed_ms": row[2]}
            for rank, row in enumerate(rows, 1)
        ]}

    @app.post("/bossrush/runs")
    def start(body: StartIn, request: Request, token: str | None = Depends(token_resolver)):
        boss_set = BOSS_SETS.get(body.set_id)
        if boss_set is None:
            raise HTTPException(404, "Boss set not found.")
        _, bosses = boss_set
        if len(bosses) != STAGES_PER_RUN:
            raise HTTPException(409, "This boss set is still in development.")
        ip = request.client.host if request.client else "unknown"
        if _starts.exceeded(ip):
            raise HTTPException(429, "Too many starts. Try again in a minute.")
        _starts.record(ip)
        user = user_by_session(token) if token else None
        if token and user is None:
            raise HTTPException(401, "Your session expired. Sign in again to start a run.")
        run_id = secrets.token_urlsafe(24)
        order = random.sample(bosses, STAGES_PER_RUN)
        stages = [arena(rift, f"{run_id}:{rift}") for rift in order]
        now = time.time()
        with closing(connect()) as conn:
            conn.execute("DELETE FROM boss_rush_runs WHERE elapsed_ms IS NULL AND started_at < ?", (now - RUN_TTL,))
            conn.execute("""INSERT INTO boss_rush_runs (run_id, player_name, character, started_at, combat_ms, set_id)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                         (run_id, user["name"] if user else "Guest", body.character, now,
                          0 if body.starter_timer else None, body.set_id))
            conn.commit()
        return {"run_id": run_id, "stages": stages, "starter_timer": body.starter_timer, "set_id": body.set_id}

    @app.post("/bossrush/runs/{run_id}/entries/{stage}")
    def enter(run_id: str, stage: int):
        if len(run_id) != 32 or not 1 <= stage <= STAGES_PER_RUN:
            raise HTTPException(404, "Run or stage not found.")
        now = time.time()
        with closing(connect()) as conn:
            conn.execute("""
                UPDATE boss_rush_runs SET entered_at=?
                WHERE run_id=? AND cleared=? AND started_at>=?
                      AND combat_ms IS NOT NULL AND entered_at IS NULL
            """, (now, run_id, stage - 1, now - RUN_TTL))
            conn.commit()
            row = conn.execute("SELECT cleared, entered_at, started_at FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
        if row is None or row[2] < now - RUN_TTL:
            raise HTTPException(404, "This run expired. Start a new one to post a time.")
        if stage > row[0] and (stage != row[0] + 1 or row[1] is None):
            raise HTTPException(409, "Enter the boss rooms in order.")
        return {"entered": stage}

    @app.post("/bossrush/runs/{run_id}/clock/{stage}/{action}")
    def set_clock(run_id: str, stage: int, action: Literal["pause", "resume"]):
        if len(run_id) != 32 or not 1 <= stage <= STAGES_PER_RUN:
            raise HTTPException(404, "Run or stage not found.")
        now = time.time()
        with closing(connect()) as conn:
            # Same-action retries keep the original pause or resume timestamp.
            if action == "pause":
                conn.execute("""
                    UPDATE boss_rush_runs SET paused_at=?
                    WHERE run_id=? AND cleared=? AND started_at>=?
                          AND entered_at IS NOT NULL AND paused_at IS NULL
                """, (now, run_id, stage - 1, now - RUN_TTL))
            else:
                conn.execute("""
                    UPDATE boss_rush_runs SET entered_at=entered_at + MAX(0, ? - paused_at), paused_at=NULL
                    WHERE run_id=? AND cleared=? AND started_at>=?
                          AND entered_at IS NOT NULL AND paused_at IS NOT NULL
                """, (now, run_id, stage - 1, now - RUN_TTL))
            conn.commit()
            row = conn.execute("SELECT cleared, entered_at, started_at FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
        if row is None or row[2] < now - RUN_TTL:
            raise HTTPException(404, "This run expired. Start a new one to post a time.")
        if stage != row[0] + 1 or row[1] is None:
            raise HTTPException(409, "Enter the boss room before changing the clock.")
        return {"paused": action == "pause"}

    @app.post("/bossrush/runs/{run_id}/clears/{stage}")
    def clear(run_id: str, stage: int):
        if len(run_id) != 32 or not 1 <= stage <= STAGES_PER_RUN:
            raise HTTPException(404, "Run or stage not found.")
        now = time.time()
        with closing(connect()) as conn:
            # Conditional write makes repeated clears and overlapping requests safe.
            # The browser reports combat outcomes. The server owns order and time.
            conn.execute("""
                UPDATE boss_rush_runs SET cleared=?,
                    elapsed_ms=CASE WHEN ? = ? THEN COALESCE(
                        combat_ms + MAX(1, CAST(ROUND((? - entered_at) * 1000) AS INTEGER)),
                        MAX(1, CAST((? - started_at) * 1000 AS INTEGER))
                    ) END,
                    combat_ms=combat_ms + MAX(1, CAST(ROUND((? - entered_at) * 1000) AS INTEGER)),
                    entered_at=NULL
                WHERE run_id=? AND cleared=? AND started_at>=?
                      AND (combat_ms IS NULL OR (entered_at IS NOT NULL AND paused_at IS NULL))
            """, (stage, stage, STAGES_PER_RUN, now, now, now, run_id, stage - 1, now - RUN_TTL))
            conn.commit()
            row = conn.execute("SELECT cleared, elapsed_ms, started_at FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
        if row is None or (row[1] is None and row[2] < now - RUN_TTL):
            raise HTTPException(404, "This run expired. Start a new one to post a time.")
        if stage > row[0]:
            raise HTTPException(409, "Clear the earlier stages first.")
        return {"cleared": stage, "elapsed_ms": row[1] if stage == STAGES_PER_RUN else None}
