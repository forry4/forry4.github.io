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
import string
import time

from core import db as dbm
from core import auth as authm


def _conn():
    return dbm._Conn(sqlite3.connect(":memory:"))


def test_gen_token_length_alphabet_and_uniqueness():
    t = authm.gen_token(32)
    assert len(t) == 32
    assert all(c in string.ascii_letters + string.digits for c in t)
    # CSPRNG-backed: two draws practically never collide.
    assert authm.gen_token(16) != authm.gen_token(16)


def test_validate_credentials_username_rules():
    assert authm.validate_credentials("bob", "pw") is None
    assert authm.validate_credentials("abcdefghijklmnop", "pw") is None  # 16 chars OK
    assert authm.validate_credentials("", "pw") == "Username is required."
    assert "16 characters" in authm.validate_credentials("abcdefghijklmnopq", "pw")  # 17 chars
    assert "letters and numbers" in authm.validate_credentials("has space", "pw")
    assert "letters and numbers" in authm.validate_credentials("bad!", "pw")


def test_validate_credentials_password_rules():
    assert authm.validate_credentials("bob", "x") is None
    assert authm.validate_credentials("bob", "x" * 16) is None           # 16 chars OK
    assert authm.validate_credentials("bob", "") == "Password is required."
    assert "16 characters" in authm.validate_credentials("bob", "x" * 17)


def test_cleanup_reconnect_tokens_removes_used_and_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "rt.db"))
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.close()

    now = int(time.time())
    c = dbm.get_db_conn()
    cur = c.cursor()
    ins = ("INSERT INTO reconnect_tokens (token,user_id,room_id,player_id,expires_at,used) "
           "VALUES (?,?,?,?,?,?)")
    cur.execute(ins, ("fresh", "u", "R", "p", now + 1000, 0))     # valid, unused -> keep
    cur.execute(ins, ("expired", "u", "R", "p", now - 1000, 0))   # expired -> drop
    cur.execute(ins, ("used", "u", "R", "p", now + 1000, 1))      # used -> drop
    c.commit()
    c.close()

    assert authm.cleanup_reconnect_tokens() == 2
    c = dbm.get_db_conn()
    rows = c.cursor().execute("SELECT token FROM reconnect_tokens").fetchall()
    c.close()
    assert {r[0] for r in rows} == {"fresh"}


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


def test_get_user_by_session_agrees_with_login_on_admin(tmp_path, monkeypatch):
    # Regression: get_user_by_session computed is_admin via a correlated subquery
    # that read NULL on the prod libsql driver, so a refreshed session saw any admin
    # as non-admin even though login (is_admin_id) saw admin. The session path must
    # now agree with login, and a SITE_OWNER name-match must self-heal regardless.
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "site.db"))
    monkeypatch.setenv("SITE_OWNER", "owner")
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.close()

    authm.create_user("owner", "pw")     # the SITE_OWNER
    authm.create_user("staff", "pw")     # a non-owner admin (granted via the table)
    authm.create_user("rando", "pw")     # a normal user

    # Owner: login grants admin; the session path must agree.
    owner_login = authm.authenticate_user("owner", "pw")
    assert owner_login["is_admin"] is True
    assert authm.get_user_by_session(owner_login["session_token"])["is_admin"] is True

    # Non-owner admin: grant via the table directly (no name match), then log in.
    staff_login = authm.authenticate_user("staff", "pw")
    grant_conn = dbm.get_db_conn()
    authm.grant_admin(grant_conn, staff_login["id"])
    grant_conn.close()
    # Session path must report admin for them too (the bug hid this behind the owner-only fallback).
    assert authm.get_user_by_session(staff_login["session_token"])["is_admin"] is True

    # Normal user: not admin via either path.
    rando_login = authm.authenticate_user("rando", "pw")
    assert rando_login["is_admin"] is False
    assert authm.get_user_by_session(rando_login["session_token"])["is_admin"] is False


def test_create_user_rejects_duplicate_usernames_case_insensitively(tmp_path, monkeypatch):
    # Regression: users.name had no UNIQUE constraint and create_user only caught
    # IntegrityError, so duplicate usernames slipped through (two "Forrestm" rows in prod).
    # Now rejected CASE-INSENSITIVELY, enforced by a NOCASE unique index, and login matches.
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "u.db"))
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.close()

    assert authm.create_user("Forrestm", "pw") is not None       # first registration wins
    assert authm.create_user("Forrestm", "other") is None        # exact duplicate rejected
    assert authm.create_user("forrestm", "other") is None        # case-variant rejected too
    assert authm.create_user("FORRESTM", "other") is None

    # login is case-insensitive: any casing authenticates the single account
    assert authm.authenticate_user("forrestm", "pw") is not None
    assert authm.authenticate_user("FORRESTM", "pw") is not None

    c = dbm.get_db_conn()
    n = c.cursor().execute("SELECT COUNT(*) FROM users WHERE name = ? COLLATE NOCASE",
                           ("forrestm",)).fetchone()[0]
    raised = False
    try:  # the NOCASE unique index blocks a case-variant insert that raced past the check
        c.execute("INSERT INTO users (id,name,password_hash) VALUES (?,?,?)", ("x", "FORRESTM", "h"))
        c.commit()
    except Exception:
        raised = True
    c.close()
    assert n == 1
    assert raised


def test_is_site_owner_honors_admin_flag_and_env(monkeypatch):
    monkeypatch.delenv("SITE_OWNER", raising=False)
    assert authm.is_site_owner({"id": "x", "name": "bob"}) is False
    assert authm.is_site_owner({"id": "x", "name": "bob", "is_admin": True}) is True  # durable role
    monkeypatch.setenv("SITE_OWNER", "bob")
    assert authm.is_site_owner({"id": "x", "name": "bob"}) is True   # env bootstrap
    assert authm.is_site_owner({"id": "x", "name": "eve"}) is False
    assert authm.is_site_owner(None) is False
