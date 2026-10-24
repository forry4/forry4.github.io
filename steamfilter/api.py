"""Steam Filter — your saved games, the page's one piece of server state.

Everything else on the page is a static file. A saved list is per ACCOUNT so it
follows a reader from phone to laptop; a guest keeps one in the browser only, and
the page hands it over the first time they sign in.

  GET  /steamfilter/saved                          -> {"saved": [[app id, saved_at], ...]}
  POST /steamfilter/saved {"save": [...], "unsave": [...]}  -> the same, after the change

ONE write route, for a single star and for a batch alike: the page queues changes
made offline (or as a guest) and sends them together, and every answer is the whole
list, so the page never has to reconcile a partial reply. Saving twice keeps the
first time; unsaving a game that is not saved is a no-op.

App ids are not checked against the payload (the server never loads it); they are
bounded integers and the list is capped, which is all a stray id can cost.

The handlers are plain `def`, so their DB round-trips run in FastAPI's threadpool
rather than on the event loop the game sockets share.
"""
from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import alerts
from core.ratelimit import SlidingWindowLimiter

MAX_SAVED = 2000          # far past any real "look at later" list
MAX_BATCH = 500
MAX_APP_ID = 10 ** 8      # Steam app ids are under 4 million today

# A star is one request; a reader clicking down a list makes a few a second at most.
_writes_minute = SlidingWindowLimiter(max_hits=120, window_seconds=60)

class SavedIn(BaseModel):
    save: list[int] = Field(default_factory=list, max_length=MAX_BATCH)
    unsave: list[int] = Field(default_factory=list, max_length=MAX_BATCH)


def init_saved_db(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS steam_saved (
        user_id TEXT NOT NULL,
        app_id INTEGER NOT NULL,
        saved_at REAL NOT NULL,
        PRIMARY KEY (user_id, app_id)
    )""")
    conn.commit()


# ── pure functions (each takes a connection; tested on a real sqlite file) ────
def list_saved(conn, user_id: str) -> list[list]:
    """[[app id, saved_at], ...], newest first."""
    cur = conn.cursor()
    cur.execute("SELECT app_id, saved_at FROM steam_saved WHERE user_id=? "
                "ORDER BY saved_at DESC, app_id", (user_id,))
    return [[int(r[0]), float(r[1])] for r in cur.fetchall()]


def apply_changes(conn, user_id: str, save: list[int], unsave: list[int], now: float | None = None) -> list[list]:
    """Saves then unsaves, and returns the whole list. Refuses (ValueError) a save
    that would take the list past MAX_SAVED."""
    bad = [a for a in [*save, *unsave] if not (1 <= a < MAX_APP_ID)]
    if bad:
        raise ValueError(f"not an app id: {bad[0]}")
    now = time.time() if now is None else now
    gone = set(unsave)
    save = [a for a in dict.fromkeys(save) if a not in gone]
    cur = conn.cursor()
    have = {a for a, _ in list_saved(conn, user_id)}
    new = [a for a in save if a not in have]
    if len(have - gone) + len(new) > MAX_SAVED:
        raise ValueError(f"a saved list holds at most {MAX_SAVED:,} games")
    for a in gone & have:
        cur.execute("DELETE FROM steam_saved WHERE user_id=? AND app_id=?", (user_id, a))
    # Saving an already-saved game keeps its first time.
    for a in new:
        cur.execute("INSERT OR IGNORE INTO steam_saved (user_id, app_id, saved_at) VALUES (?, ?, ?)",
                    (user_id, a, now))
    conn.commit()
    return list_saved(conn, user_id)


# ── routes ────────────────────────────────────────────────────────────────────
def _default_token_resolver(token: str | None = Query(default=None)) -> str | None:
    return token


def setup_steam_saved(app, get_db_conn, get_user_by_session, token_resolver=None) -> None:
    """Create the table and register the /steamfilter routes. Dependencies are
    injected from the composition root (the Books/Notes pattern)."""
    conn = get_db_conn()
    try:
        init_saved_db(conn)
    finally:
        conn.close()

    resolve_token = token_resolver or _default_token_resolver

    def run(fn):
        conn = get_db_conn()
        try:
            return fn(conn)
        finally:
            conn.close()

    def member(token: str | None = Depends(resolve_token)) -> dict:
        user = get_user_by_session(token) if token else None
        if not user or not user.get("id"):
            raise HTTPException(status_code=401, detail="Sign in to save games to your account.")
        return user

    @app.get("/steamfilter/saved")
    def steam_saved(user: dict = Depends(member)):
        return {"saved": run(lambda c: list_saved(c, user["id"]))}

    @app.post("/steamfilter/saved")
    def steam_save(payload: SavedIn, user: dict = Depends(member)):
        uid = user["id"]
        if _writes_minute.exceeded(uid):
            alerts.alert("steamfilter-rate", f"{user.get('name') or uid} is saving Steam Filter games "
                         "faster than the limit; requests are refused.", key=f"steamfilter-rate:{uid}")
            raise HTTPException(status_code=429, detail="Too many saves. Wait a minute and try again.")
        _writes_minute.record(uid)

        def go(c):
            try:
                return {"saved": apply_changes(c, uid, payload.save, payload.unsave)}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        return run(go)
