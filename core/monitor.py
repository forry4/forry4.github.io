"""Site health: periodic checks that raise owner alerts, and the owner's panel routes.

What is watched, and why each one:
  * STORAGE — the database size against STORAGE_BUDGET_MB (default 5120, Turso's
    free-plan storage). Warns at 75%, critical at 90%. Turso refuses writes past the
    plan, which is every game save on the site at once.
  * MEMORY — the process RSS against MEMORY_WARN_MB (default 420 of Render free's
    512MB). Past 512 the instance is OOM-killed and restarted, dropping every room.
  * OPEN LOBBIES — never-started tables across every game table (OPEN_LOBBIES_ALERT,
    default 150). The per-IP create throttle stops one address; this sees many.
  * ROOMS IN MEMORY — live rooms across every game (ROOMS_IN_MEMORY_ALERT, default 400).
  * THE EVENT LOOP — a heartbeat task on the loop and a watchdog THREAD beside it. If
    the loop has not ticked for LOOP_STALL_SECONDS the whole site is frozen (every
    socket and route shares that loop); that is exactly the CoC outage in CLAUDE.md,
    and the thread can still send the alert while the loop is stuck.
  * THE DATABASE BACKEND — TURSO_DATABASE_URL set but the process came up on local
    sqlite: the site looks healthy and nothing written survives the next restart.
  * UNHANDLED 500s — `ErrorAlertMiddleware`, one alert per path per hour.

Nothing here runs at import. `ErrorAlertMiddleware` ARMS the monitor on the first
ASGI call it sees (uvicorn's lifespan startup, or the first request), so tests that
call endpoints directly never start a thread or a task.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Callable

from fastapi import Depends, HTTPException, Query

from core import alerts
from core.auth import is_site_owner
from core.db import backend, get_db_conn

LOG = logging.getLogger("core.monitor")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


STORAGE_BUDGET_MB = _env_int("STORAGE_BUDGET_MB", 5120)
STORAGE_WARN, STORAGE_CRIT = 0.75, 0.90
MEMORY_WARN_MB = _env_int("MEMORY_WARN_MB", 420)
OPEN_LOBBIES_ALERT = _env_int("OPEN_LOBBIES_ALERT", 150)
ROOMS_IN_MEMORY_ALERT = _env_int("ROOMS_IN_MEMORY_ALERT", 400)
LOOP_STALL_SECONDS = 15
FAST_EVERY = 5 * 60          # memory, live rooms
SLOW_EVERY = 60 * 60         # storage, open lobbies (these read the DB)

_gauges: dict[str, Callable[[], int]] = {}


def register_gauge(name: str, fn: Callable[[], int]) -> None:
    """A live number the composition root knows how to read (e.g. rooms in memory
    across every game) — core may not import a game to count it itself."""
    _gauges[name] = fn


def _gauge(name: str) -> int | None:
    fn = _gauges.get(name)
    if fn is None:
        return None
    try:
        return int(fn())
    except Exception:  # noqa: BLE001
        return None


# ── measurements ─────────────────────────────────────────────────────────────
def db_size_bytes(conn) -> int | None:
    """page_count x page_size: the file's size on sqlite, and what libsql reports for
    the remote database. None if the backend refuses the pragma."""
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA page_count")
        pages = cur.fetchone()[0]
        cur.execute("PRAGMA page_size")
        return int(pages) * int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001
        return None


def _tables(conn) -> list[tuple[str, str]]:
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [(r[0], r[1] or "") for r in cur.fetchall()]


def game_tables(conn) -> list[str]:
    """Every game's rooms table, found by shape (a state_json blob and a status), so
    a new game is covered without anyone remembering to list it here."""
    return [n for n, sql in _tables(conn)
            if n.isidentifier() and "state_json" in sql and "status" in sql]


def open_lobbies(conn) -> int:
    total = 0
    cur = conn.cursor()
    for t in game_tables(conn):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE status='open'")
            total += cur.fetchone()[0]
        except Exception:  # noqa: BLE001 - one odd table must not blind the rest
            pass
    return total


def _scalar(conn, sql: str) -> int | None:
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return int(cur.fetchone()[0] or 0)
    except Exception:  # noqa: BLE001 - the table may not exist on this instance
        return None


def rss_mb() -> float | None:
    """Resident memory of this process (Linux /proc; None elsewhere)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def snapshot(conn) -> dict:
    size = db_size_bytes(conn)
    budget = STORAGE_BUDGET_MB * 1024 * 1024
    return {
        "db_backend": backend(),
        "db_bytes": size,
        "storage_budget_bytes": budget,
        "storage_fraction": (size / budget) if size is not None else None,
        "users": _scalar(conn, "SELECT COUNT(*) FROM users"),
        "open_lobbies": open_lobbies(conn),
        "notes_users": _scalar(conn, "SELECT COUNT(DISTINCT owner_id) FROM notes"),
        "notes_bytes": ((_scalar(conn, "SELECT SUM(size) FROM notes") or 0)
                        + (_scalar(conn, "SELECT SUM(bytes) FROM note_images") or 0)),
        "rooms_in_memory": _gauge("rooms_in_memory"),
        "rss_mb": rss_mb(),
        "memory_warn_mb": MEMORY_WARN_MB,
    }


# ── checks ───────────────────────────────────────────────────────────────────
def _mb(n: float) -> str:
    return f"{n / (1024 * 1024):,.0f} MB"


def check_storage(conn) -> None:
    size = db_size_bytes(conn)
    if size is None:
        return
    budget = STORAGE_BUDGET_MB * 1024 * 1024
    frac = size / budget
    if frac >= STORAGE_CRIT:
        alerts.alert("storage", f"Database is {_mb(size)} of the {_mb(budget)} budget ({frac:.0%}). "
                     "Writes start failing at 100%: every game save and every note.",
                     key="storage:crit", severity="critical", cooldown=6 * 3600)
    elif frac >= STORAGE_WARN:
        alerts.alert("storage", f"Database is {_mb(size)} of the {_mb(budget)} budget ({frac:.0%}).",
                     key="storage:warn", cooldown=24 * 3600)


def check_lobbies(conn) -> None:
    n = open_lobbies(conn)
    if n >= OPEN_LOBBIES_ALERT:
        alerts.alert("lobbies", f"{n} never-started tables are open across the games "
                     f"(alert level {OPEN_LOBBIES_ALERT}). Someone may be creating tables in bulk.")


def check_memory() -> None:
    mb = rss_mb()
    if mb is not None and mb >= MEMORY_WARN_MB:
        alerts.alert("memory", f"The server is using {mb:.0f} MB of memory; Render's free "
                     "instance is killed at 512 MB, which drops every live game.",
                     severity="critical" if mb >= 480 else "warn")


def check_rooms() -> None:
    n = _gauge("rooms_in_memory")
    if n is not None and n >= ROOMS_IN_MEMORY_ALERT:
        alerts.alert("rooms", f"{n} rooms are live in memory (alert level {ROOMS_IN_MEMORY_ALERT}).")


def check_backend() -> None:
    if os.environ.get("TURSO_DATABASE_URL") and backend() != "turso":
        alerts.alert("database", "Turso is configured but the server came up on LOCAL sqlite. "
                     "The site works, but nothing written now (accounts, games, notes) survives "
                     "the next restart. Check Render's logs for the Turso error.",
                     severity="critical", cooldown=6 * 3600)


def _with_conn(fn) -> None:
    conn = get_db_conn()
    try:
        fn(conn)
    except Exception as e:  # noqa: BLE001 - a failed check must not stop the monitor
        LOG.warning("health check %s failed: %s", getattr(fn, "__name__", fn), e)
    finally:
        conn.close()


def _checker() -> None:
    check_backend()
    last_slow = 0.0
    time.sleep(60)   # let boot settle before the first reading
    while True:
        check_memory()
        check_rooms()
        if time.time() - last_slow >= SLOW_EVERY:
            last_slow = time.time()
            _with_conn(check_storage)
            _with_conn(check_lobbies)
        time.sleep(FAST_EVERY)


# ── event-loop watchdog ──────────────────────────────────────────────────────
_beat = 0.0


async def _heartbeat() -> None:
    global _beat
    while True:
        _beat = time.monotonic()
        await asyncio.sleep(1)


def _watchdog() -> None:
    stalled = False
    while True:
        time.sleep(2)
        gap = time.monotonic() - _beat
        if gap >= LOOP_STALL_SECONDS and not stalled:
            stalled = True
            alerts.alert("frozen", f"The server's event loop has not run for {gap:.0f}s — every "
                         "game, socket and page is frozen until it does. Something is doing heavy "
                         "work on the loop (see Render's logs around now).",
                         severity="critical")
        elif gap < LOOP_STALL_SECONDS:
            stalled = False


_armed = False
_arm_lock = threading.Lock()


def arm() -> None:
    """Start the heartbeat (on the running loop) and the two monitor threads, once."""
    global _armed, _beat
    if _armed:
        return
    with _arm_lock:
        if _armed:
            return
        _armed = True
    _beat = time.monotonic()
    try:
        asyncio.get_running_loop().create_task(_heartbeat())
        threading.Thread(target=_watchdog, name="loop-watchdog", daemon=True).start()
    except RuntimeError:
        pass   # no running loop: nothing to watch
    threading.Thread(target=_checker, name="health-checks", daemon=True).start()


class ErrorAlertMiddleware:
    """Pure-ASGI (so it threads into the mounted game sub-apps, like the security
    headers). Arms the monitor on its first call, and alerts on any HTTP response
    that is a 5xx or an exception that escapes the app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not _armed:
            arm()
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        # Key on the first two segments so /notes/note/<id> is one key, not one per id.
        route = "/".join(path.split("/")[:3]) or "/"

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and message.get("status", 200) >= 500:
                alerts.alert("server-error", f"{scope.get('method')} {path} answered "
                             f"{message['status']}.", key=f"5xx:{route}")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            alerts.alert("server-error", f"{scope.get('method')} {path} crashed: "
                         f"{type(e).__name__}: {e}", key=f"5xx:{route}")
            raise


# ── the owner's panel ────────────────────────────────────────────────────────
def require_site_owner(user: dict | None) -> dict:
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="sign in")
    if not is_site_owner(user):
        raise HTTPException(status_code=403, detail="site owner only")
    return user


def _default_token_resolver(token: str | None = Query(default=None)) -> str | None:
    return token


def setup_site_health(app, get_user_by_session, token_resolver=None) -> None:
    resolve = token_resolver or _default_token_resolver

    def site_owner(token: str | None = Depends(resolve)) -> dict:
        return require_site_owner(get_user_by_session(token) if token else None)

    def run(fn):
        conn = get_db_conn()
        try:
            return fn(conn)
        finally:
            conn.close()

    # Plain `def`: FastAPI runs these in its threadpool, so the DB reads (and the
    # sqlite_master walk) never hold up the event loop.
    @app.get("/admin/alerts")
    def admin_alerts(_: dict = Depends(site_owner)):
        return {"ok": True, "unacked": run(alerts.unacked), "channels": alerts.channels()}

    @app.get("/admin/health")
    def admin_health(_: dict = Depends(site_owner)):
        def go(c):
            return {"alerts": alerts.recent(c, 100), "unacked": alerts.unacked(c), "snapshot": snapshot(c)}
        return {"ok": True, "channels": alerts.channels(), **run(go)}

    @app.post("/admin/alerts/ack")
    def admin_ack(_: dict = Depends(site_owner)):
        run(alerts.ack_all)
        return {"ok": True}

    @app.post("/admin/alerts/test")
    def admin_test(_: dict = Depends(site_owner)):
        channels = alerts.channels()
        alerts.alert("test", "Test alert from Site health. If this reached your phone, alerts work.",
                     key=f"test:{time.time()}", severity="info", cooldown=0)
        return {"ok": True, "channels": channels}
