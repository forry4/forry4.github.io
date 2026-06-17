"""Tests for game retention cleanup (core.db.cleanup_stale_games / maybe_cleanup_games).

Uses a temp-file SQLite DB (not :memory:, since cleanup opens its own connection
via get_db_conn) seeded with the `games`-table shape shared by Spender and CoC.
"""
import sqlite3
import time

from core import db as dbm

HOUR = 3600
DAY = 86400

_GAMES_DDL = """CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY, status TEXT, player1_id TEXT, player1_name TEXT,
    player2_id TEXT, player2_name TEXT, host_id TEXT, state_json TEXT,
    created_at INTEGER, updated_at INTEGER)"""


def _use_temp_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "retention.db")
    monkeypatch.setattr(dbm, "get_db_conn",
                        lambda: dbm._Conn(sqlite3.connect(db_file, check_same_thread=False)))


def test_cleanup_stale_games(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)                 # creates `users`
    cur = conn.cursor()
    cur.execute(_GAMES_DDL)
    cur.execute("INSERT INTO users (id, name) VALUES ('u1', 'Alice')")   # the only registered user
    conn.commit()

    now = int(time.time())
    # (id, player1_id, player2_id, updated_at, should_survive)
    rows = [
        ("guest_old",    "guest_a", None,  now - 25 * HOUR, False),  # all-guest, >24h  -> gone
        ("guest_fresh",  "guest_b", None,  now - 1 * HOUR,  True),   # all-guest, <24h  -> stays
        ("guest_ai_old", "guest_c", "ai",  now - 2 * DAY,   False),  # guest vs AI, >24h -> gone
        ("user_25h",     "u1",      "ai",  now - 25 * HOUR, True),   # registered, 25h (<30d) -> stays
        ("user_31d",     "u1",      "ai",  now - 31 * DAY,  False),  # registered, >30d -> gone
        ("mixed_2d",     "guest_d", "u1",  now - 2 * DAY,   True),   # guest+registered, <30d -> stays (protected)
        ("user_p2_old",  "guest_e", "u1",  now - 31 * DAY,  False),  # registered as p2, >30d -> gone
    ]
    for gid, p1, p2, upd, _ in rows:
        cur.execute("INSERT INTO games (id, player1_id, player2_id, updated_at) VALUES (?,?,?,?)",
                    (gid, p1, p2, upd))
    conn.commit()
    conn.close()

    deleted = dbm.cleanup_stale_games("games")
    assert deleted == 4  # guest_old, guest_ai_old, user_31d, user_p2_old

    check = dbm.get_db_conn()
    survivors = {r[0] for r in check.cursor().execute("SELECT id FROM games").fetchall()}
    check.close()
    assert survivors == {gid for gid, *_rest, survive in rows if survive}


def test_cleanup_respects_custom_windows(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.cursor().execute(_GAMES_DDL)
    now = int(time.time())
    conn.cursor().execute("INSERT INTO games (id, player1_id, updated_at) VALUES ('g', 'guest', ?)",
                          (now - 2 * HOUR,))   # all-guest, 2h old
    conn.commit()
    conn.close()
    # 1h guest window -> the 2h-old guest game is stale
    assert dbm.cleanup_stale_games("games", guest_seconds=HOUR) == 1


def test_maybe_cleanup_is_throttled(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    conn.cursor().execute(_GAMES_DDL)
    conn.commit()
    conn.close()
    dbm._last_cleanup.clear()
    calls = []
    monkeypatch.setattr(dbm, "cleanup_stale_games", lambda table, **kw: (calls.append(table), 0)[1])
    dbm.maybe_cleanup_games("games")   # first call this hour -> runs
    dbm.maybe_cleanup_games("games")   # throttled -> skipped
    dbm.maybe_cleanup_games("coc_games")  # different table -> runs
    assert calls == ["games", "coc_games"]
