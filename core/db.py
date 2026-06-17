"""Database layer shared by all site features.

Two backends behind one tiny DBAPI-ish wrapper:
  * local stdlib sqlite3  — default (dev + tests; also the prod *fallback*)
  * Turso / libsql remote — used in production when TURSO_DATABASE_URL is set,
    so data survives Render's ephemeral filesystem (which wipes a local sqlite
    file on every deploy/cold-start).
The wrapper makes rows accessible by BOTH index (row[0]) and column name
(row["id"]) regardless of the underlying driver's native row type, so the
existing query code is unchanged. Turso is verified by a boot-time self-test;
if anything about it fails we fall back to local sqlite (the site stays up,
just non-persistent) instead of crashing.

``init_core_schema`` creates the cross-cutting tables (users / sessions, admins,
reconnect_tokens). Each feature owns its own tables elsewhere: Spender's ``games``
table, Castles of Crimson's ``coc_games``, and the Books tables.
"""
import logging
import os
import sqlite3
import time

LOG = logging.getLogger("core.db")

# Configure logging HERE, before the Turso self-test runs at import (below). This
# module is imported very early (main.py imports it at the top, before its own
# logging.basicConfig), and uvicorn's default config adds no root handler — so
# without this the "Turso/libsql verified" INFO line is silently dropped and you
# can't confirm persistence from the logs. (A failure WARNING would still surface
# via logging's lastResort handler, but the success line would not.) basicConfig is
# a no-op if the root logger already has handlers, so this never double-configures.
logging.basicConfig(level=logging.INFO)

# The site SQLite database. It historically lived at games/spender/users.db (it
# predates this package), so the default stays there for backward-compat with
# existing local/dev data; override with SITE_DB_PATH. In production
# TURSO_DATABASE_URL is set and this path is only the local fallback.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("SITE_DB_PATH") or os.path.join(_REPO_ROOT, "games", "spender", "users.db")
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


class _Row:
    """Row supporting row[i] and row['col'] (sqlite3.Row-compatible subset)."""
    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, vals):
        self._cols = cols
        self._vals = vals

    def __getitem__(self, k):
        if isinstance(k, str):
            return self._vals[self._cols.index(k)]
        return self._vals[k]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


class _Cursor:
    """Cursor over a raw connection's execute() result; yields _Row objects.
    Implements executemany via a loop so it works on drivers (libsql) that may
    not expose a native executemany."""

    def __init__(self, raw_conn):
        self._conn = raw_conn
        self._res = None

    def execute(self, sql, params=()):
        self._res = self._conn.execute(sql, params)
        return self

    def executemany(self, sql, seq):
        for p in seq:
            self._res = self._conn.execute(sql, p)
        return self

    @property
    def description(self):
        return getattr(self._res, "description", None)

    def _cols(self):
        d = self.description
        return [c[0] for c in d] if d else []

    def fetchone(self):
        r = self._res.fetchone()
        return None if r is None else _Row(self._cols(), list(r))

    def fetchall(self):
        cols = self._cols()
        return [_Row(cols, list(r)) for r in self._res.fetchall()]


class _Conn:
    """Thin connection wrapper exposing cursor()/execute()/commit()/close()
    uniformly over stdlib sqlite3 and libsql connections."""

    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _Cursor(self._raw)

    def execute(self, sql, params=()):
        return _Cursor(self._raw).execute(sql, params)

    def executemany(self, sql, seq):
        return _Cursor(self._raw).executemany(sql, seq)

    def commit(self):
        self._raw.commit()

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass


def _connect_turso():
    import libsql  # lazy: only imported when Turso is configured
    return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)


def _turso_selftest() -> bool:
    """Verify the Turso connection AND that name-based row access works through
    our wrapper. Any failure -> False (fall back to local sqlite)."""
    if not TURSO_URL:
        return False
    try:
        raw = _connect_turso()
        raw.execute("CREATE TABLE IF NOT EXISTS _selftest (id TEXT, name TEXT)")
        raw.execute("DELETE FROM _selftest")
        raw.execute("INSERT INTO _selftest (id, name) VALUES (?, ?)", ("x", "ok"))
        raw.commit()
        res = raw.execute("SELECT id, name FROM _selftest")
        row = res.fetchone()
        cols = [c[0] for c in res.description]
        assert row is not None and _Row(cols, list(row))["name"] == "ok"
        raw.execute("DROP TABLE _selftest")
        raw.commit()
        raw.close()
        LOG.info("Turso/libsql verified — using persistent Turso database.")
        return True
    except Exception as e:  # noqa: BLE001 - never let DB setup crash boot
        LOG.warning("TURSO_DATABASE_URL set but Turso is unusable (%s); "
                    "falling back to LOCAL sqlite (data will NOT persist).", e)
        return False


_USE_TURSO = _turso_selftest()


def get_db_conn():
    if _USE_TURSO:
        return _Conn(_connect_turso())
    return _Conn(sqlite3.connect(DB_PATH, check_same_thread=False))


def init_core_schema(conn) -> None:
    """Create the cross-cutting tables: users (accounts + sessions), admins, and
    reconnect_tokens. Idempotent (CREATE TABLE IF NOT EXISTS). Feature-specific
    tables (Spender's `games`, CoC's `coc_games`, Books' tables) are created by
    those features. Commits on the given connection; does not close it."""
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT,
        password_hash TEXT,
        session_token TEXT,
        session_expiry INTEGER
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reconnect_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT,
        room_id TEXT,
        player_id TEXT,
        expires_at INTEGER,
        used INTEGER DEFAULT 0
    )""")
    # Site admins (durable role). Membership = a row keyed by user id. Kept as its
    # own table (not a users column) so it needs only CREATE TABLE IF NOT EXISTS —
    # no ALTER-TABLE migration against the existing prod/Turso users table.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id    TEXT PRIMARY KEY,
        granted_at INTEGER
    )""")
    conn.commit()
    # Enforce CASE-INSENSITIVE unique usernames at the DB level (defense in depth alongside
    # create_user's explicit NOCASE check). users.name predates this, so it's a unique-INDEX
    # migration, not a column constraint. Drop the earlier case-sensitive index it supersedes.
    # Tolerant: if case-folded duplicate names already exist the index can't be built — log and
    # continue (boot must never fail); it builds itself once the duplicates are cleaned up.
    try:
        cur.execute("DROP INDEX IF EXISTS idx_users_name")  # superseded by the NOCASE index below
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name_ci ON users(name COLLATE NOCASE)")
        conn.commit()
    except Exception as e:  # noqa: BLE001
        LOG.warning("case-insensitive unique index on users.name not created — duplicate "
                    "usernames (ignoring case) likely exist; clean them up so it can build (%s)", e)


# ── Game retention / cleanup ──────────────────────────────────────────────────
# Shared by both game tables (`games`, `coc_games`), which share the same shape:
# player1_id / player2_id (a registered user's id is a row in `users`; a guest's
# is a random id that isn't) + updated_at (epoch seconds, last activity).
DEFAULT_GUEST_RETENTION = 24 * 3600        # guest games: 24 hours
DEFAULT_USER_RETENTION = 30 * 24 * 3600    # registered-user games: 30 days

# Throttle: this runs opportunistically off lobby browsing, so cap it to once per
# hour per table per process (races are harmless — the DELETE is idempotent).
_CLEANUP_MIN_INTERVAL = 3600
_last_cleanup: dict[str, int] = {}


def cleanup_stale_games(table: str, guest_seconds: int = DEFAULT_GUEST_RETENTION,
                        user_seconds: int = DEFAULT_USER_RETENTION) -> int:
    """Delete stale rows from a games table by LAST ACTIVITY (`updated_at`):
      * an all-guest game (no player id present in `users`) once it's older than
        `guest_seconds` (default 24h),
      * a game with ANY registered player once it's older than `user_seconds`
        (default 30d) — so a registered user's history survives even a game they
        played with a guest.
    `table` is a trusted internal constant ("games" / "coc_games"), not user input.
    Returns the number of rows deleted (counted first, since the driver-agnostic
    cursor has no reliable rowcount on libsql)."""
    now = int(time.time())
    guest_where = ("updated_at < ? "
                   "AND (player1_id IS NULL OR player1_id NOT IN (SELECT id FROM users)) "
                   "AND (player2_id IS NULL OR player2_id NOT IN (SELECT id FROM users))")
    user_where = ("updated_at < ? "
                  "AND (player1_id IN (SELECT id FROM users) OR player2_id IN (SELECT id FROM users))")
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        deleted = 0
        for where, cutoff in ((guest_where, now - guest_seconds), (user_where, now - user_seconds)):
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (cutoff,))
            n = cur.fetchone()[0]
            if n:
                cur.execute(f"DELETE FROM {table} WHERE {where}", (cutoff,))
                deleted += n
        conn.commit()
        if deleted:
            LOG.info("cleanup_stale_games(%s): removed %d stale game(s)", table, deleted)
        return deleted
    finally:
        conn.close()


def maybe_cleanup_games(table: str, **kwargs) -> int:
    """Throttled `cleanup_stale_games` — a no-op unless at least an hour has passed
    since this process last cleaned `table`. Safe to call on every lobby fetch."""
    now = int(time.time())
    if now - _last_cleanup.get(table, 0) < _CLEANUP_MIN_INTERVAL:
        return 0
    _last_cleanup[table] = now
    try:
        return cleanup_stale_games(table, **kwargs)
    except Exception as e:  # noqa: BLE001 - cleanup must never break a lobby request
        LOG.warning("maybe_cleanup_games(%s) failed: %s", table, e)
        return 0
