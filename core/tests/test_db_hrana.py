"""Turso over HTTP (core.db._HranaConn) — the client that replaced the libsql driver.

Why it exists: libsql 0.1.11 holds the GIL while it waits on the network, so one
slow Turso call in a WORKER thread froze the event loop and every socket on the
site (the 2026-10-07 "event loop has not run for 24s" alert, in the same minute
as a Turso storage error on a plain-`def` route). The client speaks Hrana v2
(`POST /v2/pipeline`) through http.client, which waits with the GIL released.

The server here is a small Hrana stand-in over a real sqlite file (streams,
batons, typed values, per-statement errors), so the client's protocol and its
sqlite3 transaction semantics are checked in CI without a Turso account. The same
client was also checked line-for-line against libsql on a real `sqld` (v0.24.32)
when it was written.
"""
import asyncio
import base64
import json
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core import db, monitor


# ── a Hrana v2 stand-in ──────────────────────────────────────────────────────
def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, str):
        return {"type": "text", "value": v}
    return {"type": "blob", "base64": base64.b64encode(v).decode().rstrip("=")}   # sqld omits padding


def _dec(v):
    t = v["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "text":
        return v["value"]
    return base64.b64decode(v["base64"])


class _Hrana:
    def __init__(self, path):
        self.path = path
        self.streams = {}
        self.n = 0
        self.lock = threading.Lock()
        self.requests = 0
        srv = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"          # keep-alive, like Turso

            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps(srv.pipeline(body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def pipeline(self, body):
        with self.lock:
            self.requests += 1
            baton = body.get("baton")
            if baton is None:
                conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            else:
                conn = self.streams.pop(baton)
            results, closed = [], False
            for r in body["requests"]:
                if r["type"] == "close":
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    conn.close()
                    closed = True
                    results.append({"type": "ok", "response": {"type": "close"}})
                    continue
                st = r["stmt"]
                try:
                    cur = conn.execute(st["sql"], [_dec(a) for a in st.get("args", [])])
                    cols = [{"name": d[0], "decltype": None} for d in cur.description or ()]
                    rows = [[_enc(v) for v in row] for row in cur.fetchall()]
                    results.append({"type": "ok", "response": {"type": "execute", "result": {
                        "cols": cols, "rows": rows, "affected_row_count": 0, "last_insert_rowid": None}}})
                except sqlite3.Error as e:
                    results.append({"type": "error", "error": {"message": str(e), "code": "SQLITE_ERROR"}})
            new = None
            if not closed:
                self.n += 1
                new = f"b{self.n}"
                self.streams[new] = conn
            return {"baton": new, "base_url": None, "results": results}

    def stop(self):
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def hrana(tmp_path):
    s = _Hrana(str(tmp_path / "turso.db"))
    yield s
    s.stop()


def _script(conn, reopen):
    """One script of everything the site's queries rely on; returns what it saw."""
    seen = []
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT, f REAL, x BLOB)")
    conn.execute("INSERT INTO t VALUES (?,?,?,?)", (1, "one", 1.5, b"\x00\xff" * 40))
    conn.close()                                   # no commit: rolled back
    conn = reopen()
    seen.append(conn.execute("SELECT count(*) FROM t").fetchone()[0])
    cur = conn.cursor()
    cur.execute("INSERT INTO t VALUES (?,?,?,?)", (2, "two", None, bytes(range(256))))
    cur.execute("INSERT INTO t VALUES (?,?,?,?)", (True, "bool", 3, None))
    conn.commit()
    cur.executemany("INSERT INTO t (a, b) VALUES (?, ?)", [(10, "x"), (2 ** 62, "big")])
    conn.commit()
    rows = conn.execute("SELECT a, b, f, x FROM t ORDER BY a").fetchall()
    seen.append([tuple(r) for r in rows])
    seen.append([(r["a"], r["b"]) for r in rows])            # by column name
    seen.append(conn.execute("SELECT a FROM t WHERE a=?", (99,)).fetchone())
    seen.append([c[0] for c in conn.execute("SELECT a AS alias, b FROM t").description])
    other = reopen()
    conn.execute("UPDATE t SET b='changed' WHERE a=2")
    seen.append(other.execute("SELECT b FROM t WHERE a=2").fetchone()[0])   # not yet visible
    conn.commit()
    seen.append(other.execute("SELECT b FROM t WHERE a=2").fetchone()[0])
    other.close()
    try:
        conn.execute("SELECT nope FROM t")
    except Exception as e:  # noqa: BLE001
        seen.append(isinstance(e, ValueError) or isinstance(e, sqlite3.Error))
    conn.close()
    return seen


def test_http_client_behaves_like_sqlite3(hrana, tmp_path):
    path = str(tmp_path / "local.db")
    local = _script(db._Conn(sqlite3.connect(path)), lambda: db._Conn(sqlite3.connect(path)))
    remote = _script(db._Conn(db._HranaConn(hrana.url, "tok")), lambda: db._Conn(db._HranaConn(hrana.url, "tok")))
    assert remote == local
    assert local[0] == 0 and local[-1] is True and local[-3] == "two" and local[-2] == "changed"


def test_errors_are_value_errors_and_the_stream_survives_them(hrana):
    conn = db._HranaConn(hrana.url, None)
    conn.execute("CREATE TABLE u (k TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO u VALUES ('a')")
    conn.commit()
    conn.execute("INSERT INTO u VALUES ('b')")
    with pytest.raises(ValueError, match="UNIQUE"):
        conn.execute("INSERT INTO u VALUES ('a')")
    conn.commit()                                 # 'b' is still in the transaction
    assert [r[0] for r in conn.execute("SELECT k FROM u ORDER BY k").fetchall()] == ["a", "b"]
    assert hrana.streams == {}                    # nothing left open on the server


def test_a_closed_connection_leaves_no_stream_open(hrana):
    conn = db._HranaConn(hrana.url, None)
    conn.execute("CREATE TABLE v (a INTEGER)")
    conn.execute("INSERT INTO v VALUES (1)")
    assert len(hrana.streams) == 1
    conn.close()
    assert hrana.streams == {}


def test_a_keepalive_connection_the_server_dropped_is_retried(hrana):
    conn = db._HranaConn(hrana.url, None)
    conn.execute("SELECT 1")
    held = db._local.pool[("http", hrana.url.split("://")[1])][0]
    held.sock.shutdown(socket.SHUT_RDWR)          # the server side going away while idle
    assert conn.execute("SELECT 2").fetchone() == (2,)


def test_turso_over_http_is_chosen_and_reported(hrana, monkeypatch):
    monkeypatch.setattr(db, "TURSO_URL", hrana.url)
    monkeypatch.setattr(db, "TURSO_TOKEN", "tok")
    assert db._choose_turso() == (True, "http")
    monkeypatch.setattr(db, "_USE_TURSO", True)
    monkeypatch.setattr(db, "_TURSO_DRIVER", "http")
    assert db.backend() == "turso"
    assert isinstance(db.get_db_conn()._raw, db._HranaConn)
    monkeypatch.setattr(db, "_TURSO_DRIVER", "libsql")
    assert db.backend() == "turso-libsql"         # the deploy gate fails this, loudly


def test_a_stalled_turso_call_in_a_thread_does_not_freeze_the_loop(monkeypatch):
    """THE regression: libsql held the GIL here and the loop stopped dead."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    held = []
    threading.Thread(target=lambda: held.append(srv.accept()), daemon=True).start()   # accept, never answer
    monkeypatch.setattr(db, "HRANA_TIMEOUT", 3.0)
    url = f"http://127.0.0.1:{srv.getsockname()[1]}"

    def call():
        with pytest.raises(OSError):
            db._HranaConn(url, None).execute("SELECT 1")

    async def main():
        beats = []

        async def hb():
            while True:
                beats.append(time.monotonic())
                await asyncio.sleep(0.05)
        task = asyncio.create_task(hb())
        stalled = asyncio.get_running_loop().run_in_executor(None, call)
        await asyncio.sleep(1.5)                  # the call is still hanging throughout
        assert not stalled.done()
        task.cancel()
        await stalled
        return max(b - a for a, b in zip(beats, beats[1:])), len(beats)
    gap, n = asyncio.run(main())
    srv.close()
    assert n >= 20 and gap < 0.5, f"the loop stalled {gap:.2f}s ({n} beats) while Turso hung"


def test_the_frozen_alert_names_where_the_loop_is(monkeypatch):
    stop = threading.Event()

    def stuck_somewhere():
        stop.wait(5)
    t = threading.Thread(target=stuck_somewhere, daemon=True)
    t.start()
    time.sleep(0.05)
    monkeypatch.setattr(monitor, "_loop_thread", t.ident)
    where = monitor._loop_stack()
    stop.set()
    # Separator-agnostic: `_loop_stack` reports whatever the interpreter put in the frame,
    # so this file is `core/tests/...` on the Linux image and `core\tests\...` on a Windows
    # dev box. Asserting the posix spelling passed CI and failed every local run.
    assert "core/tests/test_db_hrana.py" in where.replace("\\", "/"), where
    assert "stuck_somewhere" in where, where
    assert where.split(" <- ")[0].endswith(" wait"), where       # the innermost call, wherever it is
