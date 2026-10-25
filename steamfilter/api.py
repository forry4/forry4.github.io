"""Steam Filter — each account's saved and not-interested games, the page's one
piece of server state.

Everything else on the page is a static file. The two lists are per ACCOUNT so they
follow a reader from phone to laptop; a guest keeps them in the browser only, and the
page hands them over the first time they sign in. A game is on at most one of them:
saving a game takes it off "not interested", and the reverse.

  GET  /steamfilter/saved   -> {"saved": [[app id, at], ...], "hidden": [[app id, at], ...]}
  POST /steamfilter/saved {"save", "unsave", "hide", "unhide": [...]}  -> the same, after

ONE write route, for a single tap and for a batch alike: the page queues changes made
offline (or as a guest) and sends them together, and every answer is both whole lists,
so the page never has to reconcile a partial reply. Marking twice keeps the first time;
removing a mark a game does not carry is a no-op. Within one batch a removal beats an
addition, so a game both saved and hidden in the same request ends up on neither.
`hide`/`unhide` arrived after `save`/`unsave`; a page from before them sends neither,
and pydantic defaults both to empty.

App ids are not checked against the payload (the server never loads it); they are
bounded integers and the lists are capped, which is all a stray id can cost.

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
MAX_HIDDEN = 5000         # a reader weeding the list hides far more than they save
MAX_BATCH = 500
MAX_APP_ID = 10 ** 8      # Steam app ids are under 4 million today

# A tap is one request; a reader clicking down a list makes a few a second at most.
_writes_minute = SlidingWindowLimiter(max_hits=120, window_seconds=60)

# list name -> (table, cap). Both tables share one shape.
LISTS = {"saved": ("steam_saved", MAX_SAVED), "hidden": ("steam_hidden", MAX_HIDDEN)}


class SavedIn(BaseModel):
    save: list[int] = Field(default_factory=list, max_length=MAX_BATCH)
    unsave: list[int] = Field(default_factory=list, max_length=MAX_BATCH)
    hide: list[int] = Field(default_factory=list, max_length=MAX_BATCH)
    unhide: list[int] = Field(default_factory=list, max_length=MAX_BATCH)


def init_saved_db(conn) -> None:
    cur = conn.cursor()
    for table, _ in LISTS.values():
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            user_id TEXT NOT NULL,
            app_id INTEGER NOT NULL,
            saved_at REAL NOT NULL,
            PRIMARY KEY (user_id, app_id)
        )""")
    conn.commit()


# ── pure functions (each takes a connection; tested on a real sqlite file) ────
def _list(conn, table: str, user_id: str) -> list[list]:
    """[[app id, at], ...], newest first."""
    cur = conn.cursor()
    cur.execute(f"SELECT app_id, saved_at FROM {table} WHERE user_id=? "
                "ORDER BY saved_at DESC, app_id", (user_id,))
    return [[int(r[0]), float(r[1])] for r in cur.fetchall()]


def marks(conn, user_id: str) -> dict:
    return {name: _list(conn, table, user_id) for name, (table, _) in LISTS.items()}


def apply_changes(conn, user_id: str, save=(), unsave=(), hide=(), unhide=(), now: float | None = None) -> dict:
    """Applies one batch and returns both whole lists. Refuses (ValueError) a batch
    that would take either list past its cap, before writing anything."""
    bad = [a for a in [*save, *unsave, *hide, *unhide] if not (1 <= a < MAX_APP_ID)]
    if bad:
        raise ValueError(f"not an app id: {bad[0]}")
    now = time.time() if now is None else now
    # Each list's removals include the other list's additions: one mark per game.
    plan = {"saved": (save, {*unsave, *hide}), "hidden": (hide, {*unhide, *save})}
    work = []
    for name, (add, gone) in plan.items():
        table, cap = LISTS[name]
        have = {a for a, _ in _list(conn, table, user_id)}
        new = [a for a in dict.fromkeys(add) if a not in gone and a not in have]
        if len(have - gone) + len(new) > cap:
            raise ValueError(f"the {'saved' if name == 'saved' else 'not-interested'} list "
                             f"holds at most {cap:,} games")
        work.append((table, gone & have, new))
    cur = conn.cursor()
    for table, drop, new in work:
        for a in drop:
            cur.execute(f"DELETE FROM {table} WHERE user_id=? AND app_id=?", (user_id, a))
        # Marking an already-marked game keeps its first time.
        for a in new:
            cur.execute(f"INSERT OR IGNORE INTO {table} (user_id, app_id, saved_at) VALUES (?, ?, ?)",
                        (user_id, a, now))
    conn.commit()
    return marks(conn, user_id)


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
        return run(lambda c: marks(c, user["id"]))

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
                return apply_changes(c, uid, payload.save, payload.unsave, payload.hide, payload.unhide)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        return run(go)
