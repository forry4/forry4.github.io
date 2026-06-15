"""Books ranking feature — a small public-read / owner-write list living in the
shared `users.db`.

Design mirrors the rest of the site: it reuses Spender's SQLite connection and
session-auth helpers (injected by `setup_books` to avoid an import cycle), reads
are public, writes are restricted to a single owner.

Owner gating (resolved per request, never cached):
  * If the SITE_OWNER env var is set, it is the owner's *username* and is
    authoritative. This is the site-wide owner identity (see main.is_site_owner),
    not a books-specific one.
  * Otherwise the FIRST authenticated (non-guest) user to save claims ownership;
    their user id is persisted in the `books_meta` table. Zero config, and the
    site owner will be first.

The page asks for "an ordered list but also a star rating" — i.e. books are
grouped by star rating (5 down to 1) and manually ordered *within* each rating.
The frontend sends the full list in display order; `sort_order` is recomputed
per-rating from that order, so one PUT captures both reorders and rating changes.

The route handlers are thin wrappers around pure functions (`fetch_books`,
`can_user_edit`, `replace_books`) that take a sqlite connection, so they can be
unit-tested against an in-memory DB without standing up the web server.
"""
import os
import time
import random
import string

from pydantic import BaseModel


# ── data model ───────────────────────────────────────────────────────────────
class BookIn(BaseModel):
    id: str | None = None
    title: str
    author: str = ""
    rating: int = 3
    note: str = ""
    cover_url: str = ""


class BooksPayload(BaseModel):
    books: list[BookIn] = []


class SuggestionIn(BaseModel):
    id: str | None = None
    title: str
    author: str = ""
    cover_url: str = ""
    blurb: str = ""


class SuggestionsPayload(BaseModel):
    suggestions: list[SuggestionIn] = []


# Each logged-in user may suggest at most this many books for the owner to read.
MAX_SUGGESTIONS = 10


def _gen_id(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _clamp_rating(r) -> int:
    try:
        r = int(r)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, r))


# ── schema ───────────────────────────────────────────────────────────────────
def init_books_db(conn) -> None:
    """Create the books tables on the given connection (idempotent)."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id         TEXT PRIMARY KEY,
            title      TEXT NOT NULL,
            author     TEXT DEFAULT '',
            rating     INTEGER DEFAULT 3,
            sort_order INTEGER DEFAULT 0,
            note       TEXT DEFAULT '',
            cover_url  TEXT DEFAULT '',
            created_at INTEGER,
            updated_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS books_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS book_suggestions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            user_name  TEXT DEFAULT '',
            title      TEXT NOT NULL,
            author     TEXT DEFAULT '',
            cover_url  TEXT DEFAULT '',
            blurb      TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_user ON book_suggestions(user_id)")
    conn.commit()


# ── owner resolution ─────────────────────────────────────────────────────────
# The owner is the site-wide owner (you), identified by the SITE_OWNER env var
# (a username). main.is_site_owner reads the same key for non-books features.
def _site_owner_name() -> str | None:
    name = os.environ.get("SITE_OWNER")
    return name.strip() if name and name.strip() else None


def _stored_owner_id(conn) -> str | None:
    cur = conn.cursor()
    cur.execute("SELECT value FROM books_meta WHERE key='owner_id'")
    row = cur.fetchone()
    return row["value"] if row else None


def _is_admin(user: dict | None) -> bool:
    """Site admins (main.py's durable `admins` role, surfaced as user['is_admin'])
    always have owner powers here, regardless of the SITE_OWNER name match."""
    return bool(user and user.get("is_admin"))


def can_user_edit(conn, user: dict | None) -> bool:
    """True if `user` may edit. Does NOT claim ownership (that happens on save)."""
    if not user or not user.get("id"):
        return False
    if _is_admin(user):
        return True
    env_owner = _site_owner_name()
    if env_owner is not None:
        return user.get("name") == env_owner
    owner_id = _stored_owner_id(conn)
    if owner_id is None:
        return True  # unclaimed — any authenticated user may claim by saving
    return user["id"] == owner_id


def is_owner(conn, user: dict | None) -> bool:
    """Strict ownership check — only the confirmed owner (or a site admin). Unlike
    can_user_edit, an unclaimed list returns False (nobody is the owner yet)."""
    if not user or not user.get("id"):
        return False
    if _is_admin(user):
        return True
    env_owner = _site_owner_name()
    if env_owner is not None:
        return user.get("name") == env_owner
    owner_id = _stored_owner_id(conn)
    return owner_id is not None and user["id"] == owner_id


def _claim_or_check(conn, user: dict) -> bool:
    """Authorize a write, claiming an unclaimed list for `user`. Returns allowed."""
    if _is_admin(user):
        return True
    env_owner = _site_owner_name()
    if env_owner is not None:
        return user.get("name") == env_owner
    owner_id = _stored_owner_id(conn)
    if owner_id is None:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO books_meta (key, value) VALUES ('owner_id', ?)",
            (user["id"],),
        )
        conn.commit()
        return True
    return user["id"] == owner_id


# ── reads ────────────────────────────────────────────────────────────────────
def fetch_books(conn) -> list[dict]:
    """All books, grouped by rating (5→1) and ordered within each rating."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, author, rating, sort_order, note, cover_url
        FROM books
        ORDER BY rating DESC, sort_order ASC, title ASC
        """
    )
    out = []
    for r in cur.fetchall():
        out.append({
            "id": r["id"], "title": r["title"], "author": r["author"], "rating": r["rating"],
            "sort_order": r["sort_order"], "note": r["note"], "cover_url": r["cover_url"],
        })
    return out


# ── writes ───────────────────────────────────────────────────────────────────
def replace_books(conn, user: dict | None, items: list) -> tuple[bool, str | None]:
    """Replace the whole list with `items` (already in display order).

    `sort_order` is recomputed per-rating from the incoming order. Returns
    (ok, error_message).
    """
    if not user or not user.get("id"):
        return False, "unauthenticated"
    if not _claim_or_check(conn, user):
        return False, "not the owner"

    now = int(time.time())
    per_rating_seq: dict[int, int] = {}
    rows = []
    for it in items:
        # accept either pydantic BookIn or a plain dict
        get = (lambda k, d="": getattr(it, k, d)) if not isinstance(it, dict) else (lambda k, d="": it.get(k, d))
        title = (get("title") or "").strip()
        if not title:
            continue  # skip blank entries rather than persisting junk
        rating = _clamp_rating(get("rating", 3))
        seq = per_rating_seq.get(rating, 0)
        per_rating_seq[rating] = seq + 1
        rows.append((
            get("id") or _gen_id(),
            title,
            (get("author") or "").strip(),
            rating,
            seq,
            (get("note") or "").strip(),
            (get("cover_url") or "").strip(),
            now,
            now,
        ))

    cur = conn.cursor()
    cur.execute("DELETE FROM books")
    cur.executemany(
        """
        INSERT INTO books
            (id, title, author, rating, sort_order, note, cover_url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return True, None


# ── suggestions (per-user, public users suggest books for the owner) ──────────
def _row_to_suggestion(r) -> dict:
    return {
        "id": r["id"], "user_id": r["user_id"], "user_name": r["user_name"], "title": r["title"],
        "author": r["author"], "cover_url": r["cover_url"], "blurb": r["blurb"], "sort_order": r["sort_order"],
    }


_SUGG_COLS = "id, user_id, user_name, title, author, cover_url, blurb, sort_order"


def fetch_user_suggestions(conn, user_id: str) -> list[dict]:
    """One user's suggestions, in their chosen rank order."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT {_SUGG_COLS} FROM book_suggestions WHERE user_id=? "
        "ORDER BY sort_order ASC, created_at ASC",
        (user_id,),
    )
    return [_row_to_suggestion(r) for r in cur.fetchall()]


def fetch_all_suggestions(conn) -> list[dict]:
    """Every user's suggestions (for the owner), grouped by suggester then rank."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT {_SUGG_COLS} FROM book_suggestions "
        "ORDER BY user_name ASC, sort_order ASC, created_at ASC"
    )
    return [_row_to_suggestion(r) for r in cur.fetchall()]


def replace_user_suggestions(conn, user: dict | None, items: list) -> tuple[bool, str | None]:
    """Replace just this user's suggestions (capped at MAX_SUGGESTIONS), in the
    incoming order. Other users' suggestions are untouched."""
    if not user or not user.get("id"):
        return False, "unauthenticated"

    now = int(time.time())
    rows = []
    for it in items:
        get = (lambda k, d="": getattr(it, k, d)) if not isinstance(it, dict) else (lambda k, d="": it.get(k, d))
        title = (get("title") or "").strip()
        if not title:
            continue  # skip blanks
        rows.append((
            get("id") or _gen_id(),
            user["id"],
            user.get("name") or "",
            title,
            (get("author") or "").strip(),
            (get("cover_url") or "").strip(),
            (get("blurb") or "").strip(),
            len(rows),  # sort_order = rank by incoming position
            now,
            now,
        ))
        if len(rows) >= MAX_SUGGESTIONS:
            break  # enforce the cap server-side, not just in the UI

    cur = conn.cursor()
    cur.execute("DELETE FROM book_suggestions WHERE user_id=?", (user["id"],))
    cur.executemany(
        """
        INSERT INTO book_suggestions
            (id, user_id, user_name, title, author, cover_url, blurb, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return True, None


# ── route registration ───────────────────────────────────────────────────────
def setup_books(app, get_db_conn, get_user_by_session) -> None:
    """Create tables and register the /books routes on `app`.

    `get_db_conn` and `get_user_by_session` are injected from main.py so this
    module never imports main (avoiding the import cycle).
    """
    conn = get_db_conn()
    try:
        init_books_db(conn)
    finally:
        conn.close()

    @app.get("/books")
    async def get_books(token: str | None = None):
        conn = get_db_conn()
        try:
            user = get_user_by_session(token) if token else None
            return {
                "ok": True,
                "books": fetch_books(conn),
                "can_edit": can_user_edit(conn, user),
            }
        finally:
            conn.close()

    @app.put("/books")
    async def put_books(payload: BooksPayload, token: str | None = None):
        conn = get_db_conn()
        try:
            user = get_user_by_session(token) if token else None
            ok, err = replace_books(conn, user, payload.books)
            if not ok:
                return {"ok": False, "message": err}
            return {"ok": True, "books": fetch_books(conn)}
        finally:
            conn.close()

    @app.get("/books/suggestions")
    async def get_suggestions(token: str | None = None):
        conn = get_db_conn()
        try:
            user = get_user_by_session(token) if token else None
            owner = is_owner(conn, user)
            return {
                "ok": True,
                "mine": fetch_user_suggestions(conn, user["id"]) if user else [],
                "all": fetch_all_suggestions(conn) if owner else [],
                "is_owner": owner,
                "logged_in": bool(user),
                "max": MAX_SUGGESTIONS,
            }
        finally:
            conn.close()

    @app.put("/books/suggestions")
    async def put_suggestions(payload: SuggestionsPayload, token: str | None = None):
        conn = get_db_conn()
        try:
            user = get_user_by_session(token) if token else None
            ok, err = replace_user_suggestions(conn, user, payload.suggestions)
            if not ok:
                return {"ok": False, "message": err}
            return {"ok": True, "mine": fetch_user_suggestions(conn, user["id"])}
        finally:
            conn.close()
