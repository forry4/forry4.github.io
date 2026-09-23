"""Sessions (core.auth): one per signed-in DEVICE, sliding expiry, hashed at rest.

The regression this file exists for: users.session_token held ONE token per
account and every login overwrote it, so signing in on a laptop silently signed
the phone out — and the token died exactly 7 days after login however often the
site was used. Both read as "the site keeps asking me to log in".
"""
import time

import pytest

from core import auth as authm
from core import db as dbm


@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "site.db"))
    monkeypatch.delenv("SITE_OWNER", raising=False)
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.close()
    authm.create_user("alice", "pw")
    authm.create_user("bob", "pw")


def _rows(sql, args=()):
    c = dbm.get_db_conn()
    cur = c.cursor()
    cur.execute(sql, args)
    out = cur.fetchall()
    c.close()
    return out


def _clock(monkeypatch, t):
    monkeypatch.setattr(authm.time, "time", lambda: t)


def test_signing_in_on_a_second_device_keeps_the_first_signed_in(site):
    phone = authm.authenticate_user("alice", "pw")["session_token"]
    laptop = authm.authenticate_user("alice", "pw")["session_token"]
    assert phone != laptop
    assert authm.get_user_by_session(phone)["name"] == "alice"
    assert authm.get_user_by_session(laptop)["name"] == "alice"


def test_tokens_are_stored_hashed_never_raw(site):
    tok = authm.authenticate_user("alice", "pw")["session_token"]
    stored = [r[0] for r in _rows("SELECT token_hash FROM user_sessions")]
    assert tok not in stored and authm._token_hash(tok) in stored
    assert _rows("SELECT 1 FROM users WHERE session_token=?", (tok,)) == []


def test_expiry_slides_with_use(site, monkeypatch):
    t0 = 1_800_000_000
    _clock(monkeypatch, t0)
    tok = authm.authenticate_user("alice", "pw")["session_token"]
    # used every 60 days, it outlives the 90-day TTL many times over
    for k in range(1, 6):
        _clock(monkeypatch, t0 + k * 60 * 86400)
        assert authm.get_user_by_session(tok) is not None, f"signed out after {k * 60} days of regular use"


def test_an_unused_session_expires_after_the_ttl(site, monkeypatch):
    t0 = 1_800_000_000
    _clock(monkeypatch, t0)
    tok = authm.authenticate_user("alice", "pw")["session_token"]
    _clock(monkeypatch, t0 + authm.SESSION_TTL - 1)
    assert authm.get_user_by_session(tok) is not None   # refreshed here...
    _clock(monkeypatch, t0 + 2 * authm.SESSION_TTL - 10)
    assert authm.get_user_by_session(tok) is not None   # ...so still inside the window
    _clock(monkeypatch, t0 + 3 * authm.SESSION_TTL + 1)
    assert authm.get_user_by_session(tok) is None       # a full TTL of disuse ends it


def test_a_read_writes_at_most_once_a_day(site, monkeypatch):
    t0 = 1_800_000_000
    _clock(monkeypatch, t0)
    tok = authm.authenticate_user("alice", "pw")["session_token"]
    _clock(monkeypatch, t0 + 3600)
    authm.get_user_by_session(tok)
    assert _rows("SELECT last_used FROM user_sessions")[0][0] == t0          # no write within the day
    _clock(monkeypatch, t0 + authm.SESSION_REFRESH + 5)
    authm.get_user_by_session(tok)
    assert _rows("SELECT last_used FROM user_sessions")[0][0] == t0 + authm.SESSION_REFRESH + 5


def test_logout_ends_only_that_device(site):
    phone = authm.authenticate_user("alice", "pw")["session_token"]
    laptop = authm.authenticate_user("alice", "pw")["session_token"]
    authm.end_session(laptop)
    assert authm.get_user_by_session(laptop) is None
    assert authm.get_user_by_session(phone)["name"] == "alice"
    authm.end_session("not-a-token")   # unknown token: a no-op, never an error
    authm.end_session("")


def test_a_pre_migration_token_is_honoured_once_then_moved(site, monkeypatch):
    # a token minted by the old code lives in users.session_token
    now = int(time.time())
    c = dbm.get_db_conn()
    c.execute("UPDATE users SET session_token=?, session_expiry=? WHERE name='bob'", ("legacyTok", now + 3600))
    c.commit()
    c.close()
    assert authm.get_user_by_session("legacyTok")["name"] == "bob"
    assert _rows("SELECT session_token FROM users WHERE name='bob'")[0][0] is None
    assert len(_rows("SELECT 1 FROM user_sessions WHERE token_hash=?", (authm._token_hash("legacyTok"),))) == 1
    # ...and it now slides like any other session, well past the old 7-day cutoff
    monkeypatch.setattr(authm.time, "time", lambda: now + 30 * 86400)
    assert authm.get_user_by_session("legacyTok")["name"] == "bob"


def test_an_expired_legacy_token_is_not_honoured(site):
    c = dbm.get_db_conn()
    c.execute("UPDATE users SET session_token=?, session_expiry=? WHERE name='bob'", ("old", int(time.time()) - 5))
    c.commit()
    c.close()
    assert authm.get_user_by_session("old") is None
    assert _rows("SELECT 1 FROM user_sessions") == []


def test_sessions_per_user_are_capped_least_recently_used_first(site, monkeypatch):
    t0 = 1_800_000_000
    toks = []
    for i in range(authm.MAX_SESSIONS_PER_USER + 3):
        _clock(monkeypatch, t0 + i)
        toks.append(authm.authenticate_user("alice", "pw")["session_token"])
    assert len(_rows("SELECT 1 FROM user_sessions WHERE user_id=(SELECT id FROM users WHERE name='alice')")) \
        == authm.MAX_SESSIONS_PER_USER
    assert authm.get_user_by_session(toks[0]) is None and authm.get_user_by_session(toks[-1]) is not None
    # another user's sessions are untouched by alice's cap
    assert authm.get_user_by_session(authm.authenticate_user("bob", "pw")["session_token"])["name"] == "bob"


def test_no_token_and_unknown_token(site):
    assert authm.get_user_by_session("") is None
    assert authm.get_user_by_session(None) is None
    assert authm.get_user_by_session("nope") is None
