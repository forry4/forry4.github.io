"""core.gamestore — the table plumbing every game server shares.

Each game's behaviour through it is pinned end to end by
shared/tests/test_persistence_characterization.py. These pin the store's own
contract, against a real sqlite database and a connection that has no
`rowcount` (the libsql wrapper had none; the HTTP client has none).
"""
import json
import sqlite3
import threading

import pytest

from core import rooms as _rooms
from core.gamestore import GameStore

TABLE = "t_games"


class _NoRowcountCursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(sql, params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        raise AttributeError("rowcount")       # what the libsql wrapper did


class _Conn:
    def __init__(self, path):
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row

    def cursor(self):
        return _NoRowcountCursor(self._c.cursor())

    def execute(self, sql, params=()):
        return self._c.execute(sql, params)

    def commit(self):
        self._c.commit()

    def close(self):
        self._c.close()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "g.db")
    c = sqlite3.connect(path)
    c.execute(f"""CREATE TABLE {TABLE} (id TEXT PRIMARY KEY, status TEXT,
        player1_id TEXT, player1_name TEXT, player2_id TEXT, player2_name TEXT,
        host_id TEXT, state_json TEXT, created_at INTEGER, updated_at INTEGER)""")
    c.commit()
    c.close()
    return path


def _store(db, **kw):
    calls = {"connect": 0, "sweeps": 0}

    def connect():
        calls["connect"] += 1
        return _Conn(db)

    def sweep():
        calls["sweeps"] += 1
    store = GameStore(TABLE, seats=2, connect=connect, decode=json.loads, label="t",
                      cleanup=sweep, **kw)
    return store, calls


def _row(db, rid):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    r = c.execute(f"SELECT * FROM {TABLE} WHERE id=?", (rid,)).fetchone()
    c.close()
    return dict(r) if r else None


def _put(store, rid, status, p1, p2, state, t):
    seats = [(p1, p1 and p1.title()), (p2, p2 and p2.title())]
    cols = {"status": status, **store.seat_columns(seats), "state_json": json.dumps(state)}
    store.upsert(rid, update={**cols, "updated_at": t},
                 insert={**cols, "host_id": p1, "created_at": t, "updated_at": t})


def test_upsert_inserts_then_updates_only_the_update_columns(db):
    store, _ = _store(db)
    store.upsert("R", update={"status": "x"},
                 insert={"status": "open", "player1_id": "a", "host_id": "a",
                         "created_at": 1, "updated_at": 1})
    assert _row(db, "R")["status"] == "open"
    store.upsert("R", update={"status": "playing", "player2_id": "b", "updated_at": 5},
                 insert={"status": "WRONG", "host_id": "WRONG"})
    row = _row(db, "R")
    assert (row["status"], row["player2_id"], row["host_id"], row["created_at"],
            row["updated_at"]) == ("playing", "b", "a", 1, 5)


def test_the_write_connection_is_reused_and_a_failure_drops_it(db, caplog):
    store, calls = _store(db)
    _put(store, "A", "open", "a", None, {}, 1)
    _put(store, "B", "open", "b", None, {}, 2)
    assert calls["connect"] == 1                      # one handshake for both saves
    store.upsert("C", update={}, insert={"no_such_column": 1})   # fails, never raises
    assert "save failed for C" in caplog.text
    _put(store, "D", "open", "d", None, {}, 3)
    assert calls["connect"] == 2                      # the next save reconnected
    assert _row(db, "D") is not None


def test_remove_runs_on_the_write_thread_after_pending_saves(db):
    store, _ = _store(db)
    seen = []
    store.executor.submit(lambda: seen.append(threading.current_thread().name))
    store.executor.submit(_put, store, "R", "open", "a", None, {}, 1)
    store.executor.submit(store.remove, "R").result(timeout=10)
    assert _row(db, "R") is None
    assert seen and seen[0].startswith("t-db-write")


def test_load_state_goes_through_the_codec_and_never_raises(db):
    decoded = []

    def decode(blob):
        decoded.append(blob)
        return json.loads(blob)
    store = GameStore(TABLE, seats=2, connect=lambda: _Conn(db), decode=decode, label="t")
    _put(store, "OK", "open", "a", None, {"players": {"a": "A"}}, 1)
    store.upsert("BAD", update={}, insert={"status": "open", "state_json": "not json"})
    store.upsert("EMPTY", update={}, insert={"status": "open", "state_json": ""})
    assert store.load_state("OK") == {"players": {"a": "A"}}
    assert store.load_state("BAD") is None
    assert store.load_state("EMPTY") is None
    assert store.load_state("MISSING") is None
    assert decoded == [json.dumps({"players": {"a": "A"}}), "not json"]


def test_connect_and_decode_are_looked_up_per_call(db):
    """A game passes `lambda: _db()`, so a test that patches the game's `_db`
    is honoured by the store it built at import."""
    target = {"path": db}
    store = GameStore(TABLE, seats=2, connect=lambda: _Conn(target["path"]),
                      decode=json.loads, label="t")
    _put(store, "R", "open", "a", None, {}, 1)
    target["path"] = ":memory:"
    with pytest.raises(sqlite3.OperationalError):
        store.fetch("id")                             # reads the NEW target


def test_the_lists(db):
    store, calls = _store(db)
    _put(store, "O1", "open", "a", None, {"n": 1}, 10)
    _put(store, "O2", "open", "b", None, {"n": 2}, 20)
    _put(store, "P1", "playing", "a", "b", {"n": 3}, 30)
    _put(store, "P2", "playing", "c", "a", {"n": 4}, 40)
    for i in range(_rooms.HISTORY_LIMIT + 5):
        _put(store, f"H{i:03d}", "over", "a", "b", {"n": i}, 100 + i)
    store.upsert("BAD", update={}, insert={"status": "playing", "player1_id": "a",
                                           "state_json": "garbage", "updated_at": 50})

    def shape(r, state):
        return {"id": r["id"], "n": state.get("n")}

    assert [g["id"] for g in store.open_games("id, state_json", shape)] == ["O2", "O1"]
    assert calls["sweeps"] == 1
    assert [g["id"] for g in store.active_games("id, state_json", shape)] == ["BAD", "P2", "P1"]
    # a player's unfinished games, any seat, never a finished one; the corrupt row
    # reaches the shaper as {} rather than taking the list down
    mine = store.user_games("a", "id, state_json", shape)
    assert [g["id"] for g in mine] == ["BAD", "P2", "P1", "O1"]
    assert mine[0]["n"] is None
    assert store.user_games("zed", "id, state_json", shape) == []
    hist = store.user_history("b", "id, state_json", shape)
    assert len(hist) == _rooms.HISTORY_LIMIT
    assert hist[0]["id"] == f"H{_rooms.HISTORY_LIMIT + 4:03d}"     # newest first
    assert len(store.user_history("b", "id, state_json", shape, limit=3)) == 3
    # a shaper's None drops the row; a list without state_json decodes nothing
    assert store.open_games("id, state_json", lambda r, s: None) == []
    assert store.open_games("id", lambda r, s: s) == [{}, {}]


def test_safe_state_is_a_dict_or_empty(db):
    store = GameStore(TABLE, seats=2, connect=lambda: _Conn(db), decode=json.loads, label="t")
    assert store.safe_state('{"a": 1}') == {"a": 1}
    assert store.safe_state("[1, 2]") == {}
    assert store.safe_state("nope") == {}
    assert store.safe_state(None) == {}
