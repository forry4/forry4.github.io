"""Every game's lobby History query returns at most `core.rooms.HISTORY_LIMIT` rows,
newest first.

One test over every game that defines `list_user_history`, derived from the tree.
It replaces four per-game copies (Spender, CoC, Duel, Dontminion) that covered four
of the ten. It is a real sqlite round-trip rather than a source check because the
query's parameter tuple has to match its placeholders, and getting the arity wrong
is a runtime binding error.

The game table is found by SHAPE after the game's own init runs (a new table with
`state_json` and `status`), the same way `core.monitor` counts open lobbies, so a
new game joins without an edit here.
"""
import importlib
import json
import re
import time
from pathlib import Path

import pytest

import core.db as coredb
from core import rooms as _rooms

ROOT = Path(__file__).resolve().parents[2]


def _games():
    out = []
    for main in sorted((ROOT / "games").glob("*/main.py")):
        text = main.read_text(encoding="utf-8")
        if "\ndef list_user_history(" not in text:
            continue
        init = re.search(r"^def (\w*init_db)\(\)", text, re.M)
        assert init, f"{main.parent.name} has list_user_history but no *init_db()"
        out.append((main.parent.name, init.group(1)))
    return out


GAMES = _games()


def test_the_roster_is_found():
    """Non-vacuity: if the walk breaks, the parametrized test below runs zero times."""
    assert len(GAMES) >= 10, GAMES


def _tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}


def _columns(conn, table):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


@pytest.fixture
def game_db(request, tmp_path, monkeypatch):
    name, init = request.param
    main = importlib.import_module(f"games.{name}.main")
    monkeypatch.setattr(coredb, "DB_PATH", str(tmp_path / f"{name}_hist.db"))
    conn = coredb.get_db_conn()
    coredb.init_core_schema(conn)
    before = _tables(conn)
    conn.close()
    monkeypatch.setattr(main, "_save_conn", None, raising=False)
    getattr(main, init)()
    conn = coredb.get_db_conn()
    new = [t for t in _tables(conn) - before
           if {"state_json", "status"} <= set(_columns(conn, t))]
    assert len(new) == 1, f"{name}: expected one game table, init created {new}"
    table, cols = new[0], _columns(conn, new[0])
    conn.close()
    yield main, table, cols
    main._save_conn = None


def _finished_rows(main, table, cols, n):
    """n finished games between seats a and b, oldest first: `updated_at` rises
    with the index, so the newest row is the LAST one written."""
    # The union of what each game's reader needs to keep a row: a winner and a
    # players map for most, a scored round result and seat list for Dissonance.
    state = {"players": {"a": "A", "b": "B"}, "host": "a", "status": "over",
             "game": {"winner": "a", "players": {"a": {}, "b": {}}, "seats": ["a", "b"],
                      "result": {"scores": [5, 0], "round": 1}}}
    encode = getattr(main, "_encode_state", json.dumps)
    blob = encode(state)
    now = int(time.time())
    fills = {"status": "over", "player1_id": "a", "player1_name": "A",
             "player2_id": "b", "player2_name": "B", "host_id": "a",
             "state_json": blob, "created_at": now}
    conn = coredb.get_db_conn()
    cur = conn.cursor()
    for i in range(n):
        row = {"id": f"H{i:03d}", "updated_at": now + i,
               **{k: v for k, v in fills.items() if k in cols}}
        keys = list(row)
        cur.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                    [row[k] for k in keys])
    conn.commit()
    conn.close()


@pytest.mark.parametrize("game_db", GAMES, ids=[g for g, _ in GAMES], indirect=True)
def test_history_is_capped_at_the_shared_limit_and_newest_first(game_db):
    main, table, cols = game_db
    extra = 12
    _finished_rows(main, table, cols, _rooms.HISTORY_LIMIT + extra)
    rows = main.list_user_history("a")
    assert len(rows) == _rooms.HISTORY_LIMIT
    # the cap must drop the OLDEST games, not an arbitrary window
    assert rows[0]["id"] == f"H{_rooms.HISTORY_LIMIT + extra - 1:03d}"
    assert rows[-1]["id"] == f"H{extra:03d}"


@pytest.mark.parametrize("game_db", GAMES, ids=[g for g, _ in GAMES], indirect=True)
def test_a_short_history_is_returned_whole(game_db):
    """Non-vacuity: the cap must be a ceiling, not a fixed page size."""
    main, table, cols = game_db
    _finished_rows(main, table, cols, 3)
    assert len(main.list_user_history("a")) == 3
