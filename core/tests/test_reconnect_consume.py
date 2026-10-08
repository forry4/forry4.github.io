"""`core.auth.consume_reconnect_token` — validate + mark-used as ONE step.

The game servers used to call `validate_reconnect_token` and then
`mark_reconnect_token_used` synchronously on the event loop. Nothing could run
between the two, so a single-use token was single-use for free. Moving the
round trips off the loop (`asyncio.to_thread`) opens a gap between them, and two
reconnects presenting the same token could both validate before either marked
it. These tests hold the helper to the old guarantee — and the race test proves
it would catch the gap, by taking the lock away and watching it fail.
"""
import contextlib
import threading
import time

from core import auth as authm
from core import db as dbm


def _token(tmp_path, monkeypatch, room="ROOM", pid="p1"):
    monkeypatch.setattr(dbm, "DB_PATH", str(tmp_path / "rc.db"))
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.close()
    return authm.create_reconnect_token("u1", room, pid)


def _ours(info):
    return info["room_id"] == "ROOM" and info["player_id"] == "p1"


def test_a_token_is_consumed_once(tmp_path, monkeypatch):
    tok = _token(tmp_path, monkeypatch)
    info, ok = authm.consume_reconnect_token(tok, _ours)
    assert ok and info["user_id"] == "u1"
    assert authm.consume_reconnect_token(tok, _ours) == (None, False)


def test_a_token_for_another_seat_is_refused_and_not_burned(tmp_path, monkeypatch):
    tok = _token(tmp_path, monkeypatch)
    info, ok = authm.consume_reconnect_token(tok, lambda i: False)
    assert info is not None and not ok          # the record, so a caller can tell "mismatch"
    assert authm.consume_reconnect_token(tok, _ours)[1]   # still good for its own seat


def test_an_unknown_token_is_refused(tmp_path, monkeypatch):
    _token(tmp_path, monkeypatch)
    assert authm.consume_reconnect_token("nope", _ours) == (None, False)


def _race(monkeypatch, tok, n=6):
    real = authm.validate_reconnect_token

    def slow(t):                     # widen the validate->mark gap so a race is certain
        info = real(t)
        time.sleep(0.05)
        return info
    monkeypatch.setattr(authm, "validate_reconnect_token", slow)
    go = threading.Barrier(n)
    won = []

    def attempt():
        go.wait()
        if authm.consume_reconnect_token(tok, _ours)[1]:
            won.append(1)
    threads = [threading.Thread(target=attempt) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return len(won)


def test_racing_reconnects_consume_a_token_exactly_once(tmp_path, monkeypatch):
    tok = _token(tmp_path, monkeypatch)
    assert _race(monkeypatch, tok) == 1


def test_the_race_test_fails_without_the_lock(tmp_path, monkeypatch):
    tok = _token(tmp_path, monkeypatch)
    monkeypatch.setattr(authm, "_consume_lock", contextlib.nullcontext())
    assert _race(monkeypatch, tok) > 1
