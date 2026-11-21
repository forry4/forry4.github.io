"""Boss Rush run tokens, server timing and the public times board.

FILMS (owner's ask, 2026-11-21): each character's five best times on each set keep a
film of the run — the fight's state frame by frame (bossrush/film.js), gzipped by
the browser that played it — so anyone can watch the run, even after the rules
have changed. The server only asks for one when the time ranks in the top
FILM_RANK, stores it under a public `film_id` (never the run id, which is the run's
secret), and deletes a film the moment its run falls out of the top FILM_RANK."""
from __future__ import annotations

import json
import random
import zlib
import secrets
import time
from contextlib import closing
from typing import Annotated, Literal

from fastapi import Body, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from bossrush.dungeon import BOSSES, BOSS_SETS, DEFAULT_BOSS_SET, arena
from core.ratelimit import SlidingWindowLimiter

RUN_TTL = 2 * 60 * 60
BOARD_SIZE = 20
STAGES_PER_RUN = 3
_starts = SlidingWindowLimiter(max_hits=30, window_seconds=60)
FILM_RANK = 5
FILM_MAX_BYTES = 4_000_000            # gzipped; a 3-minute run is ~0.3 MB
FILM_MAX_RAW = 80_000_000             # unzipped, so a small upload cannot unpack into gigabytes
_film_uploads = SlidingWindowLimiter(max_hits=10, window_seconds=60 * 60)


Character = Literal["ranger", "paladin", "diviner", "ninja"]


class StartIn(BaseModel):
    character: Character
    set_id: str = DEFAULT_BOSS_SET
    starter_timer: bool = False
    # The boss to fight first (a key of the set), or None for a random order (owner, 2026-11-21).
    first: str | None = None


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
        # When the last boss fell, for the board's date (owner, 2026-11-21). Runs
        # finished before it show the day they started, which for a run is the same day.
        if "finished_at" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN finished_at REAL")
        # Damage the player took over the run, as their browser counted it (owner,
        # 2026-11-21) — shown beside the time, never ranked by. A run starts at 0 and
        # each clear adds its fight's share; a clear that sends none (a page from
        # before this) makes it NULL for good, so the board shows "—", not a false 0.
        if "damage_taken" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN damage_taken REAL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_set_times "
                     "ON boss_rush_runs (set_id, elapsed_ms, started_at, run_id) WHERE elapsed_ms IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_open "
                     "ON boss_rush_runs (started_at) WHERE elapsed_ms IS NULL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boss_rush_films (
                run_id TEXT PRIMARY KEY,
                film_id TEXT NOT NULL UNIQUE,
                film BLOB NOT NULL,
                bytes INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()

    def top_runs(conn, set_id, character):
        rows = conn.execute("""
            SELECT run_id FROM boss_rush_runs WHERE set_id=? AND character=? AND elapsed_ms IS NOT NULL
            ORDER BY elapsed_ms, started_at, run_id LIMIT ?
        """, (set_id, character, FILM_RANK)).fetchall()
        return [row[0] for row in rows]

    def prune_films(conn, set_id, character):
        """Delete the films of this set and character whose runs are no longer top FILM_RANK."""
        keep = top_runs(conn, set_id, character)
        marks = ",".join("?" * len(keep)) or "''"
        conn.execute(f"""
            DELETE FROM boss_rush_films WHERE run_id IN (
                SELECT run_id FROM boss_rush_runs WHERE set_id=? AND character=?
            ) AND run_id NOT IN ({marks})
        """, (set_id, character, *keep))

    @app.get("/bossrush/sets")
    def sets(lantern: bool = False):
        # Bundles cached before Lantern Trio shipped cannot simulate its bosses.
        return {"sets": [
            {"id": set_id, "name": name, "bosses": [BOSSES[key][1] for key in bosses], "keys": list(bosses),
             "playable": len(bosses) == STAGES_PER_RUN and (set_id != "lantern-trio" or lantern)}
            for set_id, (name, bosses) in BOSS_SETS.items()
        ]}

    @app.get("/bossrush/leaderboard")
    def leaderboard(set_id: str = DEFAULT_BOSS_SET, character: Character | None = None):
        if set_id not in BOSS_SETS:
            raise HTTPException(404, "Boss set not found.")
        where = "r.set_id=? AND r.elapsed_ms IS NOT NULL"
        values = [set_id]
        if character is not None:
            where += " AND r.character=?"
            values.append(character)
        with closing(connect()) as conn:
            rows = conn.execute(f"""
                SELECT r.player_name, r.character, r.elapsed_ms, f.film_id,
                       COALESCE(r.finished_at, r.started_at), r.damage_taken FROM boss_rush_runs r
                LEFT JOIN boss_rush_films f ON f.run_id = r.run_id
                WHERE {where}
                ORDER BY r.elapsed_ms, r.started_at, r.run_id LIMIT ?
            """, (*values, BOARD_SIZE)).fetchall()
        return {"entries": [
            {"rank": rank, "name": row[0], "character": row[1], "elapsed_ms": row[2], "film_id": row[3],
             "finished_at": row[4], "damage_taken": None if row[5] is None else round(row[5], 1)}
            for rank, row in enumerate(rows, 1)
        ]}

    @app.get("/bossrush/films/{film_id}")
    def film(film_id: str):
        if not 8 <= len(film_id) <= 32:
            raise HTTPException(404, "Replay not found.")
        with closing(connect()) as conn:
            row = conn.execute("SELECT film FROM boss_rush_films WHERE film_id=?", (film_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "This replay is no longer on the board.")
        # The gzipped film as stored; the browser unpacks it. A film never changes.
        return Response(bytes(row[0]), media_type="application/octet-stream",
                        headers={"Cache-Control": "public, max-age=86400, immutable"})

    @app.post("/bossrush/runs/{run_id}/film")
    def upload_film(run_id: str, request: Request, data: bytes = Body(..., media_type="application/octet-stream")):
        if len(run_id) != 32:
            raise HTTPException(404, "Run not found.")
        if not data or len(data) > FILM_MAX_BYTES:
            raise HTTPException(413, "This replay is too large to keep.")
        ip = request.client.host if request.client else "unknown"
        if _film_uploads.exceeded(ip):
            raise HTTPException(429, "Too many replays. Try again later.")
        with closing(connect()) as conn:
            row = conn.execute("SELECT set_id, character, elapsed_ms FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
            if row is None or row[2] is None:
                raise HTTPException(404, "Only a finished run keeps a replay.")
            set_id, character = row[0], row[1]
            existing = conn.execute("SELECT film_id FROM boss_rush_films WHERE run_id=?", (run_id,)).fetchone()
            if existing is not None:
                return {"film_id": existing[0]}
            if run_id not in top_runs(conn, set_id, character):
                raise HTTPException(409, f"Only the top {FILM_RANK} times keep a replay.")
        _film_uploads.record(ip)
        try:
            unpack = zlib.decompressobj(16 + zlib.MAX_WBITS)
            raw = unpack.decompress(data, FILM_MAX_RAW)
            if unpack.unconsumed_tail or not unpack.eof:
                raise ValueError("too large or cut short")
            film = json.loads(raw)
            if not isinstance(film, dict) or film.get("v") != 1 or film.get("character") != character \
                    or not isinstance(film.get("stages"), list) or len(film["stages"]) != STAGES_PER_RUN:
                raise ValueError("not a film of this run")
        except (ValueError, zlib.error) as exc:
            raise HTTPException(422, "That is not a replay of this run.") from exc
        film_id = secrets.token_urlsafe(12)
        with closing(connect()) as conn:
            conn.execute("""INSERT OR IGNORE INTO boss_rush_films (run_id, film_id, film, bytes, created_at)
                            VALUES (?, ?, ?, ?, ?)""", (run_id, film_id, data, len(data), time.time()))
            prune_films(conn, set_id, character)
            conn.commit()
            stored = conn.execute("SELECT film_id FROM boss_rush_films WHERE run_id=?", (run_id,)).fetchone()
        if stored is None:          # it fell out of the top while it uploaded
            raise HTTPException(409, f"Only the top {FILM_RANK} times keep a replay.")
        return {"film_id": stored[0]}

    @app.post("/bossrush/runs")
    def start(body: StartIn, request: Request, token: str | None = Depends(token_resolver)):
        boss_set = BOSS_SETS.get(body.set_id)
        if boss_set is None:
            raise HTTPException(404, "Boss set not found.")
        _, bosses = boss_set
        if len(bosses) != STAGES_PER_RUN:
            raise HTTPException(409, "This boss set is still in development.")
        if body.first is not None and body.first not in bosses:
            raise HTTPException(422, "That boss is not in this set.")
        ip = request.client.host if request.client else "unknown"
        if _starts.exceeded(ip):
            raise HTTPException(429, "Too many starts. Try again in a minute.")
        _starts.record(ip)
        user = user_by_session(token) if token else None
        if token and user is None:
            raise HTTPException(401, "Your session expired. Sign in again to start a run.")
        run_id = secrets.token_urlsafe(24)
        if body.first is None:
            order = random.sample(bosses, STAGES_PER_RUN)
        else:   # the chosen boss first, the other two in a random order
            rest = [key for key in bosses if key != body.first]
            order = [body.first, *random.sample(rest, len(rest))]
        stages = [arena(rift, f"{run_id}:{rift}") for rift in order]
        now = time.time()
        with closing(connect()) as conn:
            conn.execute("DELETE FROM boss_rush_runs WHERE elapsed_ms IS NULL AND started_at < ?", (now - RUN_TTL,))
            conn.execute("""INSERT INTO boss_rush_runs (run_id, player_name, character, started_at, combat_ms, set_id, damage_taken)
                            VALUES (?, ?, ?, ?, ?, ?, 0)""",
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
    def clear(run_id: str, stage: int, taken: Annotated[float | None, Query(ge=0, le=1_000_000)] = None):
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
                    finished_at=CASE WHEN ? = ? THEN ? END,
                    damage_taken=damage_taken + ?,
                    entered_at=NULL
                WHERE run_id=? AND cleared=? AND started_at>=?
                      AND (combat_ms IS NULL OR (entered_at IS NOT NULL AND paused_at IS NULL))
            """, (stage, stage, STAGES_PER_RUN, now, now, now, stage, STAGES_PER_RUN, now, taken, run_id, stage - 1, now - RUN_TTL))
            row = conn.execute("SELECT cleared, elapsed_ms, started_at, set_id, character FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
            wanted = False
            if row is not None and row[1] is not None and stage == STAGES_PER_RUN:
                prune_films(conn, row[3], row[4])     # a new time can push a film off the top
                wanted = run_id in top_runs(conn, row[3], row[4]) and conn.execute(
                    "SELECT 1 FROM boss_rush_films WHERE run_id=?", (run_id,)).fetchone() is None
            conn.commit()
        if row is None or (row[1] is None and row[2] < now - RUN_TTL):
            raise HTTPException(404, "This run expired. Start a new one to post a time.")
        if stage > row[0]:
            raise HTTPException(409, "Clear the earlier stages first.")
        return {"cleared": stage, "elapsed_ms": row[1] if stage == STAGES_PER_RUN else None, "film_wanted": wanted}
