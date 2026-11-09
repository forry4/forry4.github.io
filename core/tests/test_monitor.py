"""Site health (core/monitor.py): the checks, the 5xx middleware and the owner routes."""
import asyncio
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException

from core import alerts, monitor
from core.db import _Conn


@pytest.fixture()
def conn(tmp_path):
    c = _Conn(sqlite3.connect(str(tmp_path / "site.db"), check_same_thread=False))
    yield c
    c.close()


def _kinds():
    return [(a["kind"], a["severity"]) for a in alerts._sink]


def test_game_tables_are_found_by_shape_and_open_lobbies_counted(conn):
    conn.execute("CREATE TABLE games (id TEXT, status TEXT, state_json TEXT)")
    conn.execute("CREATE TABLE orbit_games (id TEXT, status TEXT, state_json TEXT, updated_at INT)")
    conn.execute("CREATE TABLE users (id TEXT, name TEXT)")           # no state_json: not a game
    conn.execute("CREATE TABLE books (id TEXT, status TEXT)")         # a status alone is not enough
    for t, statuses in (("games", ["open", "open", "playing"]), ("orbit_games", ["open", "over"])):
        for s in statuses:
            conn.execute(f"INSERT INTO {t} (id, status, state_json) VALUES ('x', ?, '{{}}')", (s,))
    conn.commit()
    assert sorted(monitor.game_tables(conn)) == ["games", "orbit_games"]
    assert monitor.open_lobbies(conn) == 3


def test_storage_warns_then_goes_critical(conn, monkeypatch):
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.commit()
    size = monitor.db_size_bytes(conn)
    assert size and size > 0
    mb = size / (1024 * 1024)
    monkeypatch.setattr(monitor, "STORAGE_BUDGET_MB", mb / 0.8)    # 80%
    monitor.check_storage(conn)
    monkeypatch.setattr(monitor, "STORAGE_BUDGET_MB", mb / 0.95)   # 95%
    monitor.check_storage(conn)
    monkeypatch.setattr(monitor, "STORAGE_BUDGET_MB", mb * 10)     # 10%: quiet
    monitor.check_storage(conn)
    assert _kinds() == [("storage", "warn"), ("storage", "critical")]


def test_lobbies_memory_and_rooms_thresholds(conn, monkeypatch):
    conn.execute("CREATE TABLE games (id TEXT, status TEXT, state_json TEXT)")
    conn.executemany("INSERT INTO games VALUES ('x', 'open', '{}')", [()] * 5)
    conn.commit()
    monkeypatch.setattr(monitor, "OPEN_LOBBIES_ALERT", 5)
    monitor.check_lobbies(conn)
    monkeypatch.setattr(monitor, "rss_mb", lambda: 490.0)
    monitor.check_memory()
    monkeypatch.setitem(monitor._gauges, "rooms_in_memory", lambda: 999)
    monitor.check_rooms()
    assert _kinds() == [("lobbies", "warn"), ("memory", "critical"), ("rooms", "warn")]


def test_a_silent_fall_back_to_sqlite_is_critical(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monitor.check_backend()
    assert alerts._sink == []                       # local dev: sqlite is expected
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x")
    monkeypatch.setattr(monitor, "backend", lambda: "sqlite")
    monitor.check_backend()
    assert _kinds() == [("database", "critical")]


def test_the_libsql_fallback_is_not_reported_as_lost_data(monkeypatch):
    """`turso-libsql` PERSISTS — what is wrong is the driver (it holds the GIL).
    The alert used to say "came up on LOCAL sqlite ... nothing survives the next
    restart" for it too, which is the wrong emergency."""
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://x")
    monkeypatch.setattr(monitor, "backend", lambda: "turso-libsql")
    monitor.check_backend()
    assert _kinds() == [("database", "critical")]
    said = alerts._sink[0]["message"]
    assert "libsql" in said and "IS being saved" in said and "sqlite" not in said
    alerts._sink.clear()
    alerts.reset()
    monkeypatch.setattr(monitor, "backend", lambda: "turso")
    monitor.check_backend()
    assert alerts._sink == []                       # the healthy case stays quiet


def test_the_heartbeat_task_is_held_so_it_cannot_be_collected(monkeypatch):
    """The event loop keeps only a weak reference to a task. An unreferenced
    heartbeat that is collected stops beating, and the watchdog then reports a
    frozen site that is running fine."""
    started = []

    class _NoThread:                 # arm() also starts the two monitor threads
        def __init__(self, *a, **k):
            started.append(k.get("name"))

        def start(self):
            pass
    monkeypatch.setattr(monitor.threading, "Thread", _NoThread)
    monkeypatch.setattr(monitor, "_armed", False)
    monkeypatch.setattr(monitor, "_heartbeat_task", None)

    async def go():
        monitor.arm()
        task = monitor._heartbeat_task
        try:
            assert isinstance(task, asyncio.Task) and not task.done()
            await asyncio.sleep(0)
            assert monitor._loop_thread is not None      # it ran, on this loop
        finally:
            task.cancel()
    asyncio.run(go())
    assert started == ["loop-watchdog", "health-checks"]


def test_snapshot_reads_without_the_notes_tables(conn):
    snap = monitor.snapshot(conn)
    assert snap["db_backend"] in ("sqlite", "turso") and snap["notes_bytes"] == 0
    assert snap["storage_budget_bytes"] == monitor.STORAGE_BUDGET_MB * 1024 * 1024


# ── the 5xx middleware ───────────────────────────────────────────────────────
def _call(mw, path="/notes/note/abc"):
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(m):
        sent.append(m)
    asyncio.run(mw({"type": "http", "method": "GET", "path": path}, receive, send))
    return sent


def test_a_500_response_and_a_crash_both_alert(monkeypatch):
    monkeypatch.setattr(monitor, "_armed", True)   # never start the real monitor in a test

    async def five_hundred(scope, receive, send):
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def crash(scope, receive, send):
        raise ValueError("boom")

    _call(monitor.ErrorAlertMiddleware(ok))
    assert alerts._sink == []
    _call(monitor.ErrorAlertMiddleware(five_hundred), "/duel/games/open")
    with pytest.raises(ValueError):
        _call(monitor.ErrorAlertMiddleware(crash), "/books/list")
    msgs = [a["message"] for a in alerts._sink]
    assert msgs[0] == "GET /duel/games/open answered 503." and "ValueError: boom" in msgs[1]


def test_5xx_alerts_are_keyed_per_route_not_per_id(monkeypatch):
    monkeypatch.setattr(monitor, "_armed", True)

    async def crash(scope, receive, send):
        raise RuntimeError("x")
    for nid in ("a", "b", "c"):
        with pytest.raises(RuntimeError):
            _call(monitor.ErrorAlertMiddleware(crash), f"/notes/note/{nid}")
    assert len(alerts._sink) == 1


# ── the owner's routes ───────────────────────────────────────────────────────
def _routes(sessions):
    app = FastAPI()
    monitor.setup_site_health(app, sessions.get)
    eps = {(m, r.path): r.endpoint for r in app.routes for m in getattr(r, "methods", ())}
    dep = next(d.call for d in next(r for r in app.routes if getattr(r, "path", "") == "/admin/health")
               .dependant.dependencies)
    return app, eps, dep


def test_every_admin_route_is_owner_only(monkeypatch):
    monkeypatch.delenv("SITE_OWNER", raising=False)
    owner = {"id": "o", "name": "forrest", "is_admin": True}
    other = {"id": "u", "name": "someone", "is_admin": False}
    app, _, dep = _routes({"o": owner, "u": other})
    admin = [r for r in app.routes if getattr(r, "path", "").startswith("/admin")]
    assert len(admin) == 4
    for r in admin:
        assert any(d.call.__name__ == "site_owner" for d in r.dependant.dependencies), r.path
    assert dep(token="o") is owner
    for tok, code in (("u", 403), (None, 401), ("bogus", 401)):
        with pytest.raises(HTTPException) as e:
            dep(token=tok)
        assert e.value.status_code == code


def test_the_test_button_always_sends(monkeypatch):
    _, eps, _ = _routes({})
    owner = {"id": "o", "is_admin": True}
    eps[("POST", "/admin/alerts/test")](_=owner)
    eps[("POST", "/admin/alerts/test")](_=owner)
    assert [a["kind"] for a in alerts._sink] == ["test", "test"]   # never folded


def test_accounts_lists_every_name_most_recently_active_first(conn):
    conn.execute("CREATE TABLE users (id TEXT, name TEXT)")
    conn.executemany("INSERT INTO users VALUES (?, ?)", [("a", "Ann"), ("b", "Bob"), ("c", "Cy")])
    conn.commit()
    # Neither side table exists yet: names alone, never an error.
    assert [a["name"] for a in monitor.accounts(conn)] == ["Ann", "Bob", "Cy"]
    conn.execute("CREATE TABLE user_sessions (token_hash TEXT, user_id TEXT, created_at INTEGER, last_used INTEGER)")
    conn.executemany("INSERT INTO user_sessions VALUES (?, ?, ?, ?)",
                     [("t1", "b", 50, 100), ("t2", "b", 400, 500), ("t3", "c", 300, 300)])
    conn.execute("CREATE TABLE game_results (user_id TEXT, game TEXT)")
    conn.executemany("INSERT INTO game_results VALUES (?, ?)",
                     [("b", "orbit"), ("b", "orbit"), ("b", "duel"), ("a", "pinch")])
    conn.commit()
    assert monitor.accounts(conn) == [
        {"name": "Bob", "last_login": 400, "last_seen": 500, "games": 3, "by_game": {"orbit": 2, "duel": 1}},
        {"name": "Cy", "last_login": 300, "last_seen": 300, "games": 0, "by_game": {}},
        {"name": "Ann", "last_login": None, "last_seen": None, "games": 1, "by_game": {"pinch": 1}},
    ]
