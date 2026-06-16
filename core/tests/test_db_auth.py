"""Tests for the shared DB wrapper (core.db: _Conn/_Cursor/_Row) and the auth /
password / admin helpers (core.auth).

The wrapper is exercised over an in-memory sqlite connection — the same wrapper
the app uses over libsql in production — so row access by index AND name,
executemany, and fetchone/fetchall are covered without a server or the real
site database. (Relocated from games/spender/tests/test_db_wrapper.py when this
infrastructure moved out of games.spender.main into the neutral core package.)
"""
import hashlib
import sqlite3

from core import db as dbm
from core import auth as authm


def _conn():
    return dbm._Conn(sqlite3.connect(":memory:"))


def test_row_index_and_name_access():
    c = _conn()
    cur = c.cursor()
    cur.execute("CREATE TABLE t (id TEXT, name TEXT, n INTEGER)")
    cur.execute("INSERT INTO t VALUES (?,?,?)", ("a", "Alice", 1))
    c.commit()
    row = c.cursor().execute("SELECT id, name, n FROM t").fetchone()
    assert row[0] == "a" and row["id"] == "a"          # index + name
    assert row[1] == "Alice" and row["name"] == "Alice"
    assert row["n"] == 1
    assert len(row) == 3
    assert list(row) == ["a", "Alice", 1]
    c.close()


def test_executemany_loop_and_fetchall():
    c = _conn()
    cur = c.cursor()
    cur.execute("CREATE TABLE t (id TEXT, n INTEGER)")
    cur.executemany("INSERT INTO t VALUES (?,?)", [("a", 1), ("b", 2), ("c", 3)])
    c.commit()
    rows = c.cursor().execute("SELECT id, n FROM t ORDER BY id").fetchall()
    assert [r["id"] for r in rows] == ["a", "b", "c"]
    assert [r[1] for r in rows] == [1, 2, 3]
    c.close()


def test_fetchone_none_when_empty():
    c = _conn()
    c.cursor().execute("CREATE TABLE t (id TEXT)")
    assert c.cursor().execute("SELECT id FROM t").fetchone() is None
    c.close()


def test_conn_execute_shortcut():
    c = _conn()
    c.execute("CREATE TABLE t (id TEXT)")
    c.execute("INSERT INTO t VALUES (?)", ("x",))
    c.commit()
    assert c.execute("SELECT id FROM t").fetchone()["id"] == "x"
    c.close()


def test_init_core_schema_creates_tables():
    c = _conn()
    dbm.init_core_schema(c)
    names = {r[0] for r in c.cursor().execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"users", "admins", "reconnect_tokens"} <= names
    c.close()


def test_password_hash_roundtrip():
    h = authm.hash_password("hunter2")
    assert h.startswith("pbkdf2$")
    assert authm.verify_password(h, "hunter2") is True
    assert authm.verify_password(h, "wrong") is False


def test_password_legacy_sha256_still_verifies():
    # Back-compat: pre-upgrade users stored "<salt>$<sha256hex>".
    salt = "abc123"
    legacy = f"{salt}${hashlib.sha256((salt + 'hunter2').encode()).hexdigest()}"
    assert authm.verify_password(legacy, "hunter2") is True
    assert authm.verify_password(legacy, "nope") is False
    assert authm.verify_password("garbage-no-dollar", "x") is False


def test_admin_grant_and_check_idempotent():
    c = _conn()
    c.cursor().execute("CREATE TABLE admins (user_id TEXT PRIMARY KEY, granted_at INTEGER)")
    c.commit()
    assert authm.is_admin_id(c, "u1") is False
    authm.grant_admin(c, "u1")
    assert authm.is_admin_id(c, "u1") is True
    authm.grant_admin(c, "u1")  # INSERT OR IGNORE -> idempotent
    assert authm.is_admin_id(c, "u1") is True
    c.close()


def test_is_site_owner_honors_admin_flag_and_env(monkeypatch):
    monkeypatch.delenv("SITE_OWNER", raising=False)
    assert authm.is_site_owner({"id": "x", "name": "bob"}) is False
    assert authm.is_site_owner({"id": "x", "name": "bob", "is_admin": True}) is True  # durable role
    monkeypatch.setenv("SITE_OWNER", "bob")
    assert authm.is_site_owner({"id": "x", "name": "bob"}) is True   # env bootstrap
    assert authm.is_site_owner({"id": "x", "name": "eve"}) is False
    assert authm.is_site_owner(None) is False
