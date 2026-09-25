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
    # (id, status, player1_id, player2_id, updated_at, should_survive)
    rows = [
        ("guest_old",    "over",    "guest_a", None,  now - 25 * HOUR, False),  # all-guest, >24h  -> gone
        ("guest_fresh",  "over",    "guest_b", None,  now - 1 * HOUR,  True),   # all-guest, <24h  -> stays
        ("guest_ai_old", "playing", "guest_c", "ai",  now - 2 * DAY,   False),  # guest vs AI, >24h -> gone
        ("user_25h",     "playing", "u1",      "ai",  now - 25 * HOUR, True),   # registered, 25h (<30d) -> stays
        ("user_31d",     "over",    "u1",      "ai",  now - 31 * DAY,  False),  # registered, >30d -> gone
        ("mixed_2d",     "playing", "guest_d", "u1",  now - 2 * DAY,   True),   # guest+registered, <30d -> stays (protected)
        ("user_p2_old",  "over",    "guest_e", "u1",  now - 31 * DAY,  False),  # registered as p2, >30d -> gone
        # Never-started open lobbies age out at 48h REGARDLESS of a registered
        # host — a waiting room outlives the game version it was created under
        # (the real case: a registered user's 4-day-old lobby from an old
        # release, sitting join-able in every player's Open list).
        ("open_user_4d", "open",    "u1",      None,  now - 4 * DAY,   False),  # registered open lobby, >48h -> gone
        ("open_user_1d", "open",    "u1",      None,  now - 1 * DAY,   True),   # registered open lobby, <48h -> stays
        ("open_guest_3d", "open",   "guest_f", None,  now - 3 * DAY,   False),  # guest open lobby, stale twice over -> gone (counted once)
    ]
    for gid, status, p1, p2, upd, _ in rows:
        cur.execute("INSERT INTO games (id, status, player1_id, player2_id, updated_at) VALUES (?,?,?,?,?)",
                    (gid, status, p1, p2, upd))
    conn.commit()
    conn.close()

    deleted = dbm.cleanup_stale_games("games")
    assert deleted == 6  # guest_old, guest_ai_old, user_31d, user_p2_old, open_user_4d, open_guest_3d

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


def test_cleanup_respects_custom_open_window(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    cur = conn.cursor()
    cur.execute(_GAMES_DDL)
    cur.execute("INSERT INTO users (id, name) VALUES ('u1', 'Alice')")
    now = int(time.time())
    cur.execute("INSERT INTO games (id, status, player1_id, updated_at) VALUES ('g', 'open', 'u1', ?)",
                (now - 2 * HOUR,))   # registered host's open lobby, 2h old
    conn.commit()
    conn.close()
    # survives the default 48h window...
    assert dbm.cleanup_stale_games("games") == 0
    # ...and a 1h open window makes it stale
    assert dbm.cleanup_stale_games("games", open_seconds=HOUR) == 1


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


def test_a_registered_player_in_any_seat_protects_the_game(tmp_path, monkeypatch):
    """Seats 3-4 (Spender, CoC, Dontminion, Black Castle) and Where Wolf?'s
    `player_ids` list count. The cleanup read only player1_id/player2_id, so a
    registered player in seat 3 lost their game as an all-guest one after a day."""
    _use_temp_db(tmp_path, monkeypatch)
    conn = dbm.get_db_conn()
    dbm.init_core_schema(conn)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE four (id TEXT PRIMARY KEY, status TEXT, player1_id TEXT,
                   player2_id TEXT, player3_id TEXT, player4_id TEXT, updated_at INTEGER)""")
    cur.execute("""CREATE TABLE wolf (id TEXT PRIMARY KEY, status TEXT, player1_id TEXT,
                   player2_id TEXT, player_ids TEXT, updated_at INTEGER)""")
    cur.execute("INSERT INTO users (id, name) VALUES ('u1', 'Alice')")
    now = int(time.time())
    two_days, old = now - 2 * DAY, now - 31 * DAY
    for row in [("seat3", "playing", "g1", "g2", "u1", None, two_days),      # stays: registered in seat 3
                ("seat4", "over", "g1", "g2", None, "u1", two_days),         # stays: registered in seat 4
                ("guests", "playing", "g1", "g2", "g3", "g4", two_days),     # gone: all guests
                ("seat4_old", "over", "g1", "g2", None, "u1", old)]:         # gone: registered, >30d
        cur.execute("INSERT INTO four VALUES (?,?,?,?,?,?,?)", row)
    for row in [("w_seat5", "over", "g1", "g2", '["g1","g2","g3","g4","u1"]', two_days),  # stays
                ("w_guests", "over", "g1", "g2", '["g1","g2","g3"]', two_days),           # gone
                ("w_badjson", "over", "g1", "g2", "not json", two_days)]:                 # gone
        cur.execute("INSERT INTO wolf VALUES (?,?,?,?,?,?)", row)
    conn.commit()
    conn.close()

    assert dbm.cleanup_stale_games("four") == 2
    assert dbm.cleanup_stale_games("wolf") == 2
    check = dbm.get_db_conn()
    assert {r[0] for r in check.cursor().execute("SELECT id FROM four").fetchall()} == {"seat3", "seat4"}
    assert {r[0] for r in check.cursor().execute("SELECT id FROM wolf").fetchall()} == {"w_seat5"}
    check.close()

