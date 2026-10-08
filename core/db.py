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

TURSO IS SPOKEN OVER ITS HTTP API (Hrana v2 `/v2/pipeline`) WITH THE STDLIB, NOT
THROUGH THE `libsql` DRIVER (2026-10-08). libsql 0.1.11 — the newest release —
HOLDS THE GIL WHILE IT WAITS ON THE NETWORK, so a Turso call stalled in a worker
thread froze the event loop and every socket with it: the "loop has not run for
24s" alert of 2026-10-07 arrived in the same minute as a Turso storage error on
a plain-`def` route, which is exactly the case moving routes off the loop was
supposed to make safe. `http.client` releases the GIL while it waits (measured:
the same hung server froze the loop for >60s through libsql, 0.10s through
http.client). `core/tests/test_db_hrana.py` holds both halves. libsql stays as
the FALLBACK when the HTTP self-test fails at boot; /health then reports
`turso-libsql`, which the deploy gate fails loudly while the data still persists.

``init_core_schema`` creates the cross-cutting tables (users / sessions, admins,
reconnect_tokens). Each feature owns its own tables elsewhere: Spender's ``games``
table, Castles of Crimson's ``coc_games``, and the Books tables.
"""
import base64
import http.client
import json
import logging
import os
import re
import sqlite3
import ssl
import threading
import time
import urllib.parse

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


# ── Turso over HTTP (Hrana v2) ───────────────────────────────────────────────
HRANA_TIMEOUT = float(os.environ.get("TURSO_HTTP_TIMEOUT", "20"))   # per socket operation
_KEEPALIVE_IDLE = 25.0     # reuse a connection only if it was used this recently
_DML = re.compile(r"^\s*(?:--[^\n]*\n\s*|/\*.*?\*/\s*)*(INSERT|UPDATE|DELETE|REPLACE)\b",
                  re.IGNORECASE | re.DOTALL)


class HranaError(ValueError):
    """A statement or request Turso refused. A ValueError, as libsql's errors were,
    so every existing `except` keeps catching what it caught."""


def _http_url(url: str) -> str:
    for a, b in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(a):
            return b + url[len(a):]
    return url


def _encode(v) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool) or isinstance(v, int):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, str):
        return {"type": "text", "value": v}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    raise HranaError(f"unsupported parameter type {type(v).__name__}")


def _decode(v: dict):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "text":
        return v["value"]
    if t == "blob":
        b = v.get("base64") or ""
        return base64.b64decode(b + "=" * (-len(b) % 4))
    raise HranaError(f"unknown value type {t!r}")


_local = threading.local()


def _post(url: str, token: str | None, body: dict) -> dict:
    """POST one pipeline on this thread's keep-alive connection to the host.

    A reused connection the server has already dropped is the one failure that is
    retried (once, on a fresh connection): the request either never left or the
    server closed without answering, which is the idle keep-alive race."""
    u = urllib.parse.urlsplit(url)
    key = (u.scheme, u.netloc)
    pool = getattr(_local, "pool", None)
    if pool is None:
        pool = _local.pool = {}
    payload = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    path = (u.path.rstrip("/") or "") + "/v2/pipeline"
    for attempt in (0, 1):
        conn, last = pool.pop(key, (None, 0.0))
        reused = conn is not None and time.monotonic() - last < _KEEPALIVE_IDLE
        if conn is not None and not reused:
            conn.close()
        if not reused:
            conn = (http.client.HTTPSConnection(u.hostname, u.port, timeout=HRANA_TIMEOUT,
                                                context=ssl.create_default_context())
                    if u.scheme == "https" else
                    http.client.HTTPConnection(u.hostname, u.port, timeout=HRANA_TIMEOUT))
        try:
            conn.request("POST", path, payload, headers)
            resp = conn.getresponse()
            data = resp.read()
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
            conn.close()
            if reused and attempt == 0:
                continue
            raise
        except Exception:
            conn.close()
            raise
        if resp.status != 200:
            conn.close()
            raise HranaError(f"Hrana: HTTP {resp.status}: {data[:500].decode(errors='replace')}")
        pool[key] = (conn, time.monotonic())
        return json.loads(data)
    raise AssertionError("unreachable")


class _HranaResult:
    """One statement's rows, with the sqlite3 cursor surface `_Cursor` reads."""

    def __init__(self, result: dict):
        cols = result.get("cols") or []
        self.description = tuple((c.get("name"), None, None, None, None, None, None) for c in cols) or None
        self._rows = [tuple(_decode(v) for v in row) for row in result.get("rows") or []]
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        rows, self._i = self._rows[self._i:], len(self._rows)
        return rows


class _HranaConn:
    """A Turso connection over HTTP with sqlite3's (and libsql's) transaction
    semantics: an INSERT/UPDATE/DELETE/REPLACE outside a transaction opens one,
    commit() ends it, and close() without commit() rolls it back. A transaction
    is one Hrana STREAM (its baton carried between requests); anything outside one
    runs on a stream of its own that closes in the same request."""

    def __init__(self, url: str, token: str | None):
        self._url = _http_url(url)
        self._token = token
        self._baton = None
        self._base = None          # a stream may be pinned to another URL (base_url)
        self.in_transaction = False

    def _pipeline(self, stmts: list[str | tuple], close: bool) -> list:
        reqs = []
        for st in stmts:
            sql, params = (st, ()) if isinstance(st, str) else st
            reqs.append({"type": "execute",
                         "stmt": {"sql": sql, "args": [_encode(p) for p in params]}})
        if close:
            reqs.append({"type": "close"})
        out = _post(self._base or self._url, self._token, {"baton": self._baton, "requests": reqs})
        self._baton = None if close else out.get("baton")
        self._base = None if close else (out.get("base_url") or self._base)
        results = out.get("results") or []
        for r in results:
            if r.get("type") == "error":
                err = r.get("error") or {}
                raise HranaError(f"Hrana: {err.get('message')} ({err.get('code')})")
        return [r["response"]["result"] for r in results
                if r.get("type") == "ok" and r["response"].get("type") == "execute"]

    def execute(self, sql, params=()):
        params = tuple(params or ())
        if self.in_transaction:
            return _HranaResult(self._pipeline([(sql, params)], close=False)[-1])
        if _DML.match(sql):
            self.in_transaction = True
            try:
                return _HranaResult(self._pipeline(["BEGIN", (sql, params)], close=False)[-1])
            except Exception:
                if self._baton is None:      # the stream never opened: nothing to roll back
                    self.in_transaction = False
                raise
        return _HranaResult(self._pipeline([(sql, params)], close=True)[-1])

    def commit(self):
        if not self.in_transaction:
            return
        self.in_transaction = False
        self._pipeline(["COMMIT"], close=True)

    def close(self):
        if self._baton is not None:
            try:
                self._pipeline([], close=True)     # an open transaction is rolled back
            except Exception:
                pass
        self._baton, self.in_transaction = None, False


def _connect_http():
    return _HranaConn(TURSO_URL, TURSO_TOKEN)


def _connect_libsql():
    import libsql  # lazy: only the fallback path needs it
    return libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)


def _connect_turso():
    return _connect_libsql() if _TURSO_DRIVER == "libsql" else _connect_http()


def _turso_selftest(connect=None) -> bool:
    """Verify the Turso connection AND that name-based row access works through
    our wrapper. Any failure -> False (fall back to local sqlite)."""
    if not TURSO_URL:
        return False
    try:
        raw = (connect or _connect_turso)()
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
        LOG.info("Turso verified (%s) — using persistent Turso database.",
                 getattr(connect, "__name__", "_connect_turso"))
        return True
    except Exception as e:  # noqa: BLE001 - never let DB setup crash boot
        LOG.warning("TURSO_DATABASE_URL set but Turso is unusable through %s (%s).",
                    getattr(connect, "__name__", "_connect_turso"), e)
        return False


def _choose_turso() -> tuple[bool, str]:
    if not TURSO_URL:
        return False, "http"
    if _turso_selftest(_connect_http):
        return True, "http"
    if _turso_selftest(_connect_libsql):
        LOG.warning("Turso over HTTP failed its self-test; using the libsql driver, which "
                    "holds the GIL on every round trip (a slow Turso freezes the site).")
        return True, "libsql"
    LOG.warning("Falling back to LOCAL sqlite (data will NOT persist).")
    return False, "http"


_USE_TURSO, _TURSO_DRIVER = _choose_turso()


def backend() -> str:
    """Which store this process actually writes to: "turso" or "sqlite".

    Reported on /health because the fallback above keeps the site UP — a Turso
    failure on boot looks exactly like a healthy deploy from outside, while
    nothing written after it survives the next restart. deploy-render.yml fails
    a deploy that comes up on "sqlite"."""
    if not _USE_TURSO:
        return "sqlite"
    return "turso" if _TURSO_DRIVER == "http" else "turso-libsql"


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
    # One row per signed-in DEVICE (see core.auth). users.session_token held a single
    # token per account, so signing in on the laptop signed the phone out. The token
    # is stored as its SHA-256, never raw.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL,
        created_at INTEGER,
        expires_at INTEGER,
        last_used  INTEGER
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)")
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
# Shared by every game table (`games`, `coc_games`, …), which share the same
# shape: player1_id / player2_id (a registered user's id is a row in `users`; a
# guest's is a random id that isn't) + status + updated_at (epoch seconds, last
# activity).
DEFAULT_GUEST_RETENTION = 24 * 3600        # guest games: 24 hours
DEFAULT_USER_RETENTION = 30 * 24 * 3600    # registered-user games: 30 days
# A row still `status='open'` is a waiting room nobody ever started. Unlike a
# finished game it is not history worth keeping, and unlike a `playing` one it
# has no state anyone can resume — it just sits in every player's Open list,
# outliving the game version it was created under (a real 4-day-old lobby
# prompted this: created before a release, join-able forever after it).
# So open rooms age out on their own, registered host or not.
DEFAULT_OPEN_RETENTION = 48 * 3600         # never-started open lobbies: 48 hours

# Throttle: this runs opportunistically off lobby browsing, so cap it to once per
# hour per table per process (races are harmless — the DELETE is idempotent).
_CLEANUP_MIN_INTERVAL = 3600
_last_cleanup: dict[str, int] = {}


_SEAT_COL = re.compile(r"player\d+_id")
_DELETE_CHUNK = 200


def _seat_columns(cur, table: str) -> tuple[list[str], str | None]:
    """The seat columns a games table actually has: every `playerN_id`, plus
    Where Wolf?'s `player_ids` JSON list (its only record of seats 3 and up).
    Read from the schema rather than assumed, because the tables differ: two
    seats (Duel, Orbit, ...), four (Spender, CoC, Dontminion, Black Castle), or
    two plus the list (Where Wolf?)."""
    try:
        cur.execute(f"PRAGMA table_info({table})")
        names = [r[1] for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 - fall back to the two columns every table has
        names = []
    seats = sorted((n for n in names if _SEAT_COL.fullmatch(n)), key=lambda n: int(n[6:-3]))
    return (seats or ["player1_id", "player2_id"]), ("player_ids" if "player_ids" in names else None)


def _row_seat_ids(row, seat_cols: list[str], ids_col: str | None) -> set[str]:
    ids = {row[c] for c in seat_cols if row[c]}
    if ids_col and row[ids_col]:
        try:
            ids.update(str(p) for p in json.loads(row[ids_col]) if p)
        except (TypeError, ValueError):
            pass
    return ids


def cleanup_stale_games(table: str, guest_seconds: int = DEFAULT_GUEST_RETENTION,
                        user_seconds: int = DEFAULT_USER_RETENTION,
                        open_seconds: int = DEFAULT_OPEN_RETENTION) -> int:
    """Delete stale rows from a games table by LAST ACTIVITY (`updated_at`):
      * a never-started open lobby (`status='open'`) once it's older than
        `open_seconds` (default 48h) — registered host or not, since a waiting
        room nobody joined has no state to resume and no history to keep,
      * an all-guest game (no seated id present in `users`) once it's older than
        `guest_seconds` (default 24h),
      * a game with ANY registered player once it's older than `user_seconds`
        (default 30d) — so a registered user's history survives even a game they
        played with a guest.
    "Any registered player" means ANY SEAT. This used to read only player1_id and
    player2_id, so a registered player in seat 3 or 4 (Spender, CoC, Dontminion,
    Black Castle) or seat 3+ of Where Wolf? had their game deleted as an all-guest
    one after a day. The seat test is done here in Python over ids-only rows —
    driver-agnostic, and the same answer for any number of seats.
    `table` is a trusted internal constant ("games" / "coc_games"), not user input.
    Returns the number of rows deleted (counted first, since the driver-agnostic
    cursor has no reliable rowcount on libsql)."""
    assert table.isidentifier(), "table is a SQL identifier, not user input"
    now = int(time.time())
    guest_cutoff, user_cutoff = now - guest_seconds, now - user_seconds
    open_where = "updated_at < ? AND status = 'open'"
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        deleted = 0
        # Open lobbies go FIRST so a row that is both stale-open and stale-by-players
        # is counted once, under the reason it goes.
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {open_where}", (now - open_seconds,))
        n = cur.fetchone()[0]
        if n:
            cur.execute(f"DELETE FROM {table} WHERE {open_where}", (now - open_seconds,))
            deleted += n

        seat_cols, ids_col = _seat_columns(cur, table)
        cols = seat_cols + ([ids_col] if ids_col else [])
        cur.execute(f"SELECT id, updated_at, {', '.join(cols)} FROM {table} WHERE updated_at < ?",
                    (max(guest_cutoff, user_cutoff),))
        rows = [(r["id"], r["updated_at"], _row_seat_ids(r, seat_cols, ids_col)) for r in cur.fetchall()]
        seated = sorted(set().union(*(ids for _, _, ids in rows))) if rows else []
        registered: set[str] = set()
        for i in range(0, len(seated), _DELETE_CHUNK):
            chunk = seated[i:i + _DELETE_CHUNK]
            cur.execute(f"SELECT id FROM users WHERE id IN ({','.join('?' * len(chunk))})", tuple(chunk))
            registered.update(r[0] for r in cur.fetchall())
        guest_ids = [gid for gid, upd, ids in rows if not (ids & registered) and upd < guest_cutoff]
        user_ids = [gid for gid, upd, ids in rows if ids & registered and upd < user_cutoff]
        # The cutoff is repeated in the DELETE, so a game resumed between the read
        # above and this write is not removed.
        for ids, cutoff in ((guest_ids, guest_cutoff), (user_ids, user_cutoff)):
            for i in range(0, len(ids), _DELETE_CHUNK):
                chunk = ids[i:i + _DELETE_CHUNK]
                cur.execute(f"DELETE FROM {table} WHERE updated_at < ? AND id IN ({','.join('?' * len(chunk))})",
                            (cutoff, *chunk))
            deleted += len(ids)
        conn.commit()
        if deleted:
            LOG.info("cleanup_stale_games(%s): removed %d stale game(s)", table, deleted)
        return deleted
    finally:
        conn.close()


def _cleanup_worker(table: str, kwargs: dict) -> None:
    try:
        cleanup_stale_games(table, **kwargs)
    except Exception as e:  # noqa: BLE001 - cleanup must never break a lobby request
        LOG.warning("cleanup_stale_games(%s) failed: %s", table, e)


def maybe_cleanup_games(table: str, background: bool = False, **kwargs) -> int:
    """Throttled `cleanup_stale_games` — a no-op unless at least an hour has passed since
    this process last cleaned `table`.

    With ``background=True`` (the lobby routes) the delete runs in a daemon THREAD so it
    never blocks the request — the stale-game DELETE's `NOT IN (SELECT id FROM users)`
    scans were adding ~1-2s to the FIRST open-games fetch each hour. The throttle slot is
    claimed synchronously first, so only ONE thread is spawned per window; returns 0
    immediately. ``background=False`` (default) keeps the old synchronous behavior +
    row-count return (used by tests and the module-import warm cleanup)."""
    now = int(time.time())
    if now - _last_cleanup.get(table, 0) < _CLEANUP_MIN_INTERVAL:
        return 0
    _last_cleanup[table] = now
    if background:
        threading.Thread(target=_cleanup_worker, args=(table, kwargs), daemon=True).start()
        return 0
    try:
        return cleanup_stale_games(table, **kwargs)
    except Exception as e:  # noqa: BLE001 - cleanup must never break a lobby request
        LOG.warning("maybe_cleanup_games(%s) failed: %s", table, e)
        return 0
