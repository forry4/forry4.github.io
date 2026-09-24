"""Game results — the data behind a player's profile.

ONE ROW PER REGISTERED PLAYER PER FINISHED GAME, in `game_results`, and nothing
deletes it. That is why the table exists at all: every game's own table is
pruned 30 days after its last activity (`core.db.cleanup_stale_games`), and the
winner lives inside a compressed state blob that each game decodes its own way,
so "how have I done at Duel" could not be answered from the game tables even
for the games they still hold.

HOW ROWS GET HERE IS A SYNC, NOT A HOOK. Each game registers one reader
(`register`): its table, its seat columns, its decoder, and a `standings`
function that turns a finished state into who won. `sync()` finds every
finished game (`status='over'`) with a registered player and no rows yet,
decodes it, and writes the rows. It runs
  * for ONE player when their profile is opened, so the game they just finished
    is already on it; and
  * for everyone on the site monitor's hourly tick (`core.monitor`), so a game
    is recorded long before the 30-day prune even if nobody opens a profile.
The first hourly run after this shipped was the backfill: history starts with
whatever finished games were still in the database, i.e. about 30 days back.
A call in every game's save path was the alternative. It was turned down
because a game reaches "over" from two or three places (a normal end, an
abandon, a bot's last move), which is eleven games' worth of places to forget
it. The sync reads the one thing every one of those paths already writes.

Guests get no rows: only ids in `users` are recorded. Rows go in with INSERT OR
IGNORE, so the two callers can race and a re-run changes nothing — the first
write wins, which keeps `finished_at` at the moment the game was first seen.

This is core/: it imports no game. Games import it and register.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from fastapi import Depends, HTTPException, Query

from core import db as _db
from core.ratelimit import SlidingWindowLimiter
from core.rooms import state_ai_tier, state_bot_ids

LOG = logging.getLogger("core.results")

OUTCOMES = ("win", "loss", "draw")
SYNC_BATCH = 20                 # blobs fetched per query (a Turso read is a network round trip)
RECORDED_WINDOW = 60 * 86400    # the global sync's "already recorded" lookback — see _recorded
PROFILE_ROWS = 5000             # history rows one profile response carries


def init_results_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS game_results (
        game TEXT NOT NULL,
        game_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        finished_at INTEGER NOT NULL,
        outcome TEXT NOT NULL,
        score REAL,
        vs_bot INTEGER NOT NULL DEFAULT 0,
        ai_tier TEXT,
        mode TEXT,
        detail TEXT,
        players_json TEXT NOT NULL,
        PRIMARY KEY (game, game_id, user_id)
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_game_results_user ON game_results(user_id, finished_at)")
    conn.commit()


# ── the registry ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Source:
    game: str                                # the catalogue id (shared/catalog.js)
    table: str
    decode: Callable[[object], dict]         # the game's own `_decode_state`
    standings: Callable[[dict], dict | None]
    seat_cols: tuple[str, ...]
    ids_col: str | None                      # a JSON list of every seat (Where Wolf?)


_SOURCES: dict[str, Source] = {}


def register(game: str, table: str, *, decode, standings,
             seat_cols: Iterable[str] = ("player1_id", "player2_id"),
             ids_col: str | None = None) -> None:
    """Called once by each game's main.py at import. `standings(state)` returns
    what `standings()` below builds, or None for a game that ended without a
    result (nothing is recorded for it)."""
    _SOURCES[game] = Source(game, table, decode, standings, tuple(seat_cols), ids_col)


def sources() -> dict[str, Source]:
    return dict(_SOURCES)


def standings(state: dict, order: Iterable[str], winners: Iterable[str] = (), *,
              scores: dict | None = None, draw: bool = False, shared_win_is_a_draw: bool = True,
              mode: str | None = None, details: dict | None = None) -> dict:
    """The one shape every game's reader returns.

    `winners` are pids. More than one winner is a DRAW between them (a points tie
    in Spender, CoC, Dontminion) unless `shared_win_is_a_draw=False` — a team
    game (Where Wolf?) or a cooperative one (SecretNames), where every winner
    simply won. `draw=True` makes every seat a draw.
    """
    names = state.get("players") if isinstance(state.get("players"), dict) else {}
    bots = set(state_bot_ids(state))
    won = set(winners or ())
    tie = shared_win_is_a_draw and len(won) > 1
    out = []
    for pid in order:
        if draw:
            outcome = "draw"
        elif pid in won:
            outcome = "draw" if tie else "win"
        else:
            outcome = "loss"
        score = (scores or {}).get(pid)
        out.append({
            "id": pid,
            "name": names.get(pid) or "Player",
            "outcome": outcome,
            "score": score if isinstance(score, (int, float)) else None,
            "bot": pid in bots,
            "detail": (details or {}).get(pid),
        })
    return {"players": out, "mode": mode}


# ── the sync ─────────────────────────────────────────────────────────────────
# Finished games whose reader returned None (no result). Remembered per process
# so the hourly sync does not decode the same blob every hour; a restart forgets
# them, which costs one decode each.
_void: set[tuple[str, str]] = set()


def _seat_ids(row, src: Source) -> set[str]:
    ids = {row[c] for c in src.seat_cols if row[c]}
    if src.ids_col and row[src.ids_col]:
        try:
            ids.update(str(p) for p in json.loads(row[src.ids_col]) if p)
        except (TypeError, ValueError):
            pass
    return ids


def _recorded(cur, game: str, user_id: str | None) -> set[str]:
    """Game ids that already have rows. For one player, their own rows. For the
    global sync, every game id seen in the last RECORDED_WINDOW — wider than the
    30-day prune, so anything still in a game table is inside it; a row finished
    earlier than that but still present is simply decoded again and ignored."""
    if user_id:
        cur.execute("SELECT game_id FROM game_results WHERE game=? AND user_id=?", (game, user_id))
    else:
        cur.execute("SELECT DISTINCT game_id FROM game_results WHERE game=? AND finished_at>=?",
                    (game, int(time.time()) - RECORDED_WINDOW))
    return {r[0] for r in cur.fetchall()}


def _write(cur, src: Source, game_id: str, finished_at: int, state: dict,
           result: dict, registered: set[str]) -> int:
    players = result.get("players") or []
    public = [{k: p.get(k) for k in ("id", "name", "outcome", "score", "bot", "detail")} for p in players]
    vs_bot = int(any(p.get("bot") for p in players))
    tier = state_ai_tier(state)
    blob = json.dumps(public, separators=(",", ":"))
    n = 0
    for p in players:
        if p.get("bot") or p.get("id") not in registered or p.get("outcome") not in OUTCOMES:
            continue
        cur.execute(
            """INSERT OR IGNORE INTO game_results
               (game, game_id, user_id, finished_at, outcome, score, vs_bot, ai_tier, mode, detail, players_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (src.game, game_id, p["id"], int(finished_at or time.time()), p["outcome"], p.get("score"),
             vs_bot, tier, result.get("mode"), p.get("detail"), blob))
        n += 1
    return n


def _sync_source(conn, src: Source, registered: set[str], user_id: str | None, pause: float) -> int:
    cur = conn.cursor()
    cols = list(src.seat_cols) + ([src.ids_col] if src.ids_col else [])
    where, params = "status='over'", []
    if user_id:
        conds = [f"{c}=?" for c in src.seat_cols]
        params = [user_id] * len(src.seat_cols)
        if src.ids_col:
            conds.append(f"{src.ids_col} LIKE ?")
            params.append(f'%"{user_id}"%')
        where += " AND (" + " OR ".join(conds) + ")"
    # Ids and seats only — no blob — so this is cheap enough to run every hour.
    cur.execute(f"SELECT id, updated_at, {', '.join(cols)} FROM {src.table} WHERE {where}", tuple(params))
    found = {}
    for r in cur.fetchall():
        seats = _seat_ids(r, src)
        if user_id and user_id not in seats:
            continue        # a LIKE on the JSON list can match a longer id
        if seats & registered and (src.game, r["id"]) not in _void:
            found[r["id"]] = r["updated_at"]
    if not found:
        return 0
    missing = sorted(set(found) - _recorded(cur, src.game, user_id))
    written = 0
    for i in range(0, len(missing), SYNC_BATCH):
        chunk = missing[i:i + SYNC_BATCH]
        cur.execute(f"SELECT id, state_json FROM {src.table} WHERE id IN ({','.join('?' * len(chunk))})",
                    tuple(chunk))
        for r in cur.fetchall():
            try:
                state = src.decode(r["state_json"])
                result = src.standings(state) if isinstance(state, dict) else None
            except Exception:  # noqa: BLE001 — one unreadable blob must not stop the rest
                LOG.warning("results: could not read %s %s", src.game, r["id"], exc_info=True)
                result = None
            if not result or not result.get("players"):
                _void.add((src.game, r["id"]))
                continue
            written += _write(cur, src, r["id"], found[r["id"]], state, result, registered)
            if pause:
                time.sleep(pause)    # the hourly sync runs on a thread; let the event loop in
        conn.commit()
    return written


def sync(conn, user_id: str | None = None, *, pause: float = 0.0) -> int:
    """Record every finished game not yet in `game_results` — all of them, or
    only `user_id`'s. Never raises for one game's failure; each source is tried
    on its own. Returns the rows OFFERED, which is only for the log line: a row
    that already existed is ignored but still counted, because the libsql driver
    has no `rowcount` to tell the two apart."""
    init_results_schema(conn)
    cur = conn.cursor()
    # Every registered player, even in the one-player sync: a game is recorded
    # for all of its registered seats at once, and the global sync counts a game
    # id as done once any row for it exists.
    cur.execute("SELECT id FROM users")
    registered = {r[0] for r in cur.fetchall()}
    if user_id and user_id not in registered:
        return 0
    written = 0
    for src in list(_SOURCES.values()):
        try:
            written += _sync_source(conn, src, registered, user_id, pause)
        except Exception:  # noqa: BLE001 — a missing table (game not mounted) is not an error here
            LOG.warning("results: sync of %s failed", src.game, exc_info=True)
    return written


def sync_all(conn) -> None:
    """The monitor's hourly job. Paced, because it runs on a thread beside the loop."""
    n = sync(conn, pause=0.005)
    if n:
        LOG.info("results: recorded %d new result rows", n)


# ── the profile ──────────────────────────────────────────────────────────────
def fetch_history(conn, user_id: str) -> dict:
    cur = conn.cursor()
    cur.execute("""SELECT game, game_id, finished_at, outcome, score, vs_bot, ai_tier, mode, detail, players_json
                   FROM game_results WHERE user_id=? ORDER BY finished_at DESC LIMIT ?""",
                (user_id, PROFILE_ROWS))
    history = []
    for r in cur.fetchall():
        try:
            players = json.loads(r["players_json"] or "[]")
        except ValueError:
            players = []
        history.append({
            "game": r["game"], "id": r["game_id"], "finished_at": r["finished_at"],
            "outcome": r["outcome"], "score": r["score"], "vs_bot": bool(r["vs_bot"]),
            "ai_tier": r["ai_tier"], "mode": r["mode"], "detail": r["detail"],
            "players": [{**p, "you": p.get("id") == user_id} for p in players],
        })
    return {"history": history, "truncated": len(history) >= PROFILE_ROWS}


_profile_reads = SlidingWindowLimiter(30, 60)


def _default_token_resolver(token: str | None = Query(default=None)) -> str | None:
    return token


def setup_profile(app, get_user_by_session, token_resolver=None) -> None:
    """Register GET /profile: the signed-in player's own results. Private — there
    is no way to ask for anyone else's."""
    resolve = token_resolver or _default_token_resolver
    conn = _db.get_db_conn()
    try:
        init_results_schema(conn)
    finally:
        conn.close()

    def member(token: str | None = Depends(resolve)) -> dict:
        user = get_user_by_session(token) if token else None
        if not user:
            raise HTTPException(status_code=401, detail="Sign in to see your profile.")
        return user

    # Plain `def`: FastAPI runs it in its threadpool, so the sync's reads never
    # hold up the event loop.
    @app.get("/profile")
    def profile(user: dict = Depends(member)):
        if _profile_reads.exceeded(user["id"]):
            raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")
        _profile_reads.record(user["id"])
        conn = _db.get_db_conn()
        try:
            try:
                sync(conn, user["id"])
            except Exception:  # noqa: BLE001 — yesterday's rows beat an error page
                LOG.warning("results: profile sync failed for %s", user["id"], exc_info=True)
            return {"ok": True, "user": {"id": user["id"], "name": user["name"]}, **fetch_history(conn, user["id"])}
        finally:
            conn.close()
