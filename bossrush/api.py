"""Boss Rush run tokens, server timing and the public times board.

FILMS (owner's ask, 2026-11-21): each character's five best times on each set keep a
film of the run — the fight's state frame by frame (bossrush/film.js), gzipped by
the browser that played it — so anyone can watch the run, even after the rules
have changed. The server only asks for one when the time ranks in the top
FILM_RANK, stores it under a public `film_id` (never the run id, which is the run's
secret), and deletes a film the moment its run falls out of the top FILM_RANK.

CO-OP (owner's ask, 2026-11-22): a run can have two players (`mode='coop'`, the
second seat in `player_name2`/`character2`/`player_id2`), opened by the co-op room
socket (bossrush/coop.py) rather than `POST /runs`. Co-op times have a board of their
own, and its five best keep films whichever characters played them."""
from __future__ import annotations

import json
import random
import zlib
import secrets
import time
from contextlib import closing
from typing import Annotated, Literal

from fastapi import Body, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from bossrush.dungeon import BOSSES, BOSS_SETS, DEFAULT_BOSS_SET, arena
from core.auth import is_admin_id, is_site_owner
from core.ratelimit import SlidingWindowLimiter

RUN_TTL = 2 * 60 * 60
BOARD_SIZE = 5          # the board is a top five, everyone's or your own (owner, 2026-11-21)
STAGES_PER_RUN = 3
_starts = SlidingWindowLimiter(max_hits=30, window_seconds=60)
FILM_RANK = 5
FILM_MAX_BYTES = 4_000_000            # gzipped; a 3-minute run is ~0.3 MB
FILM_MAX_RAW = 80_000_000             # unzipped, so a small upload cannot unpack into gigabytes
_film_uploads = SlidingWindowLimiter(max_hits=10, window_seconds=60 * 60)


Character = Literal["ranger", "paladin", "diviner", "ninja", "simon"]


# Sets still being built: listed, played and ranked only for the site owner (owner,
# 2026-11-21: "hide the lantern trio from anyone but me"). Everyone else never sees
# them — not greyed out, not at all — and the routes refuse them.
SOLO_ONLY_SETS = {"crypt-trio"}
IN_DEVELOPMENT = {"lantern-trio"}


def _is_owner(conn, user) -> bool:
    return bool(user) and is_site_owner({**user, "is_admin": is_admin_id(conn, user["id"])})


class StartIn(BaseModel):
    character: Character
    set_id: str = DEFAULT_BOSS_SET
    starter_timer: bool = False
    # A guest's device id, so "My best" can find a guest's own runs (an account is
    # known from its session instead). Only ever used to filter that guest's view.
    guest_id: str | None = Field(None, max_length=64)
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
        # Who played the run, for "My best": "u:<account id>" or "g:<guest device id>".
        # Runs from before it are matched to their account by name (names are unique,
        # ignoring case); a guest's earlier runs cannot be told apart and stay unowned.
        # Co-op (2026-11-22): the mode, and the second seat. Every run before it is solo.
        if "mode" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'solo'")
        for column in ("player_name2", "character2", "player_id2"):
            if column not in columns:
                conn.execute(f"ALTER TABLE boss_rush_runs ADD COLUMN {column} TEXT")
        if "player_id" not in columns:
            conn.execute("ALTER TABLE boss_rush_runs ADD COLUMN player_id TEXT")
            try:
                names = [r[0] for r in conn.execute(
                    "SELECT DISTINCT player_name FROM boss_rush_runs WHERE player_name <> 'Guest'").fetchall()]
                for name in names:
                    user = conn.execute("SELECT id FROM users WHERE name=? COLLATE NOCASE", (name,)).fetchone()
                    if user:
                        conn.execute("UPDATE boss_rush_runs SET player_id=? WHERE player_name=? AND player_id IS NULL",
                                     (f"u:{user[0]}", name))
            except Exception:   # no users table (a bare test database): nothing to match
                pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_boss_rush_player "
                     "ON boss_rush_runs (player_id, set_id, elapsed_ms) WHERE elapsed_ms IS NOT NULL")
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

    def film_group(set_id, character, mode):
        """Which runs compete for the same films: a solo run's set and character, or every
        co-op run of the set (a pair of characters would split five films thirty ways)."""
        if mode == "coop":
            return "set_id=? AND mode='coop'", (set_id,)
        return "set_id=? AND character=? AND mode='solo'", (set_id, character)

    def top_runs(conn, set_id, character, mode="solo"):
        where, values = film_group(set_id, character, mode)
        rows = conn.execute(f"""
            SELECT run_id FROM boss_rush_runs WHERE {where} AND elapsed_ms IS NOT NULL
            ORDER BY elapsed_ms, started_at, run_id LIMIT ?
        """, (*values, FILM_RANK)).fetchall()
        return [row[0] for row in rows]

    def prune_films(conn, set_id, character, mode="solo"):
        """Delete the films of this group whose runs are no longer top FILM_RANK."""
        keep = top_runs(conn, set_id, character, mode)
        marks = ",".join("?" * len(keep)) or "''"
        where, values = film_group(set_id, character, mode)
        conn.execute(f"""
            DELETE FROM boss_rush_films WHERE run_id IN (
                SELECT run_id FROM boss_rush_runs WHERE {where}
            ) AND run_id NOT IN ({marks})
        """, (*values, *keep))

    def session_user(token):
        return user_by_session(token) if isinstance(token, str) and token else None

    def check_set(set_id, token):
        """404 for a set that does not exist, or that is in development and you are not the owner."""
        if set_id not in BOSS_SETS or (set_id in IN_DEVELOPMENT and not _owner_user(session_user(token))):
            raise HTTPException(404, "Boss set not found.")

    @app.get("/bossrush/sets")
    def sets(lantern: bool = False, crypt: bool = False, token: str | None = Depends(token_resolver)):
        # Older bundles cannot simulate newly added bosses.
        user = session_user(token)
        owner = bool(user) and _owner_user(user)
        return {"sets": [
            {"id": set_id, "name": name, "bosses": [BOSSES[key][1] for key in bosses], "keys": list(bosses),
             "playable": len(bosses) == STAGES_PER_RUN and (set_id != "lantern-trio" or lantern),
             **({"solo_only": True} if set_id in SOLO_ONLY_SETS else {})}
            for set_id, (name, bosses) in BOSS_SETS.items()
            if set_id not in IN_DEVELOPMENT or owner
            if set_id != "crypt-trio" or crypt
        ]}

    @app.get("/bossrush/leaderboard")
    def leaderboard(set_id: str = DEFAULT_BOSS_SET, character: Character | None = None, mine: bool = False,
                    guest: Annotated[str | None, Query(max_length=64)] = None,
                    mode: Literal["solo", "coop"] = "solo",
                    token: str | None = Depends(token_resolver)):
        check_set(set_id, token)
        coop = mode == "coop"
        where = "r.set_id=? AND r.mode=? AND r.elapsed_ms IS NOT NULL"
        values = [set_id, mode]
        if character is not None:       # co-op: a run either player played it in
            where += " AND (r.character=? OR r.character2=?)" if coop else " AND r.character=?"
            values += [character, character] if coop else [character]
        if mine:     # your own five best: an account by its session, a guest by its device id
            user = user_by_session(token) if token else None
            if token and user is None:
                raise HTTPException(401, "Your session expired. Sign in again to see your times.")
            player = f"u:{user['id']}" if user else f"g:{guest}" if guest else None
            if player is None:
                return {"entries": []}
            where += " AND (r.player_id=? OR r.player_id2=?)" if coop else " AND r.player_id=?"
            values += [player, player] if coop else [player]
        with closing(connect()) as conn:
            rows = conn.execute(f"""
                SELECT r.player_name, r.character, r.elapsed_ms, f.film_id,
                       COALESCE(r.finished_at, r.started_at), r.damage_taken,
                       r.player_name2, r.character2 FROM boss_rush_runs r
                LEFT JOIN boss_rush_films f ON f.run_id = r.run_id
                WHERE {where}
                ORDER BY r.elapsed_ms, r.started_at, r.run_id LIMIT ?
            """, (*values, BOARD_SIZE)).fetchall()
        return {"entries": [
            {"rank": rank, "name": row[0], "character": row[1], "elapsed_ms": row[2], "film_id": row[3],
             "finished_at": row[4], "damage_taken": None if row[5] is None else round(row[5], 1),
             **({"name2": row[6], "character2": row[7]} if coop else {})}
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
            row = conn.execute("SELECT set_id, character, elapsed_ms, mode, character2 FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
            if row is None or row[2] is None:
                raise HTTPException(404, "Only a finished run keeps a replay.")
            set_id, character, mode, character2 = row[0], row[1], row[3], row[4]
            existing = conn.execute("SELECT film_id FROM boss_rush_films WHERE run_id=?", (run_id,)).fetchone()
            if existing is not None:
                return {"film_id": existing[0]}
            if run_id not in top_runs(conn, set_id, character, mode):
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
            if mode == "coop" and film.get("characters") != [character, character2]:
                raise ValueError("not a film of this pair")
        except (ValueError, zlib.error) as exc:
            raise HTTPException(422, "That is not a replay of this run.") from exc
        film_id = secrets.token_urlsafe(12)
        with closing(connect()) as conn:
            conn.execute("""INSERT OR IGNORE INTO boss_rush_films (run_id, film_id, film, bytes, created_at)
                            VALUES (?, ?, ?, ?, ?)""", (run_id, film_id, data, len(data), time.time()))
            prune_films(conn, set_id, character, mode)
            conn.commit()
            stored = conn.execute("SELECT film_id FROM boss_rush_films WHERE run_id=?", (run_id,)).fetchone()
        if stored is None:          # it fell out of the top while it uploaded
            raise HTTPException(409, f"Only the top {FILM_RANK} times keep a replay.")
        return {"film_id": stored[0]}

    def create_run(set_id, first, seats, starter_timer=True):
        """Open a run: its boss order, its arenas and its row. `seats` is one or two
        {name, character, player_id} — two is a co-op run. Raises ValueError with a
        message the player can read. The caller has checked the set may be played."""
        _, bosses = BOSS_SETS[set_id]
        if len(bosses) != STAGES_PER_RUN:
            raise ValueError("This boss set is still in development.")
        if first is not None and first not in bosses:
            raise ValueError("That boss is not in this set.")
        run_id = secrets.token_urlsafe(24)
        if first is None:
            order = random.sample(bosses, STAGES_PER_RUN)
        else:   # the chosen boss first, the other two in a random order
            rest = [key for key in bosses if key != first]
            order = [first, *random.sample(rest, len(rest))]
        stages = [arena(rift, f"{run_id}:{rift}") for rift in order]
        now = time.time()
        one, two = seats[0], (seats[1] if len(seats) > 1 else None)
        with closing(connect()) as conn:
            conn.execute("DELETE FROM boss_rush_runs WHERE elapsed_ms IS NULL AND started_at < ?", (now - RUN_TTL,))
            conn.execute("""INSERT INTO boss_rush_runs (run_id, player_name, character, started_at, combat_ms, set_id,
                                                        damage_taken, player_id, mode, player_name2, character2, player_id2)
                            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)""",
                         (run_id, one["name"], one["character"], now, 0 if starter_timer else None, set_id,
                          one["player_id"], "coop" if two else "solo",
                          two and two["name"], two and two["character"], two and two["player_id"]))
            conn.commit()
        return {"run_id": run_id, "stages": stages, "starter_timer": starter_timer, "set_id": set_id}

    @app.post("/bossrush/runs")
    def start(body: StartIn, request: Request, token: str | None = Depends(token_resolver)):
        check_set(body.set_id, token)
        _, bosses = BOSS_SETS[body.set_id]
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
        player = f"u:{user['id']}" if user else f"g:{body.guest_id}" if body.guest_id else None
        return create_run(body.set_id, body.first, [{"name": user["name"] if user else "Guest",
                                                    "character": body.character, "player_id": player}],
                          body.starter_timer)

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
            row = conn.execute("SELECT cleared, elapsed_ms, started_at, set_id, character, mode FROM boss_rush_runs WHERE run_id=?",
                               (run_id,)).fetchone()
            wanted = False
            if row is not None and row[1] is not None and stage == STAGES_PER_RUN:
                prune_films(conn, row[3], row[4], row[5])     # a new time can push a film off the top
                wanted = run_id in top_runs(conn, row[3], row[4], row[5]) and conn.execute(
                    "SELECT 1 FROM boss_rush_films WHERE run_id=?", (run_id,)).fetchone() is None
            conn.commit()
        if row is None or (row[1] is None and row[2] < now - RUN_TTL):
            raise HTTPException(404, "This run expired. Start a new one to post a time.")
        if stage > row[0]:
            raise HTTPException(409, "Clear the earlier stages first.")
        return {"cleared": stage, "elapsed_ms": row[1] if stage == STAGES_PER_RUN else None, "film_wanted": wanted}

    from bossrush.coop import setup_coop
    setup_coop(app, connect, user_by_session, create_run, playable=lambda set_id, user: (
        set_id in BOSS_SETS and set_id not in SOLO_ONLY_SETS and len(BOSS_SETS[set_id][1]) == STAGES_PER_RUN
        and (set_id not in IN_DEVELOPMENT or _owner_user(user))))

    def _owner_user(user):
        if not user:
            return False
        with closing(connect()) as conn:
            return _is_owner(conn, user)
