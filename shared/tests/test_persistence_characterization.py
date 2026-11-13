"""Every game's persistence layer, pinned byte for byte.

Each game's rooms are frozen in `persistence_baseline/<game>.rooms.json`: real
rooms, built once through the game's own create / join / start handlers (Spender,
whose dispatcher is inline, through the same steps by hand). The test installs
them, saves each one through the game's REAL `save_game` and write executor into a
fresh sqlite database, updates one (the UPDATE path rewrites a different set of
columns from the INSERT path), adds rows whose blob is garbage, and then records:

  * every column of every row (`state_json` as its decoded, still-COMPACTED JSON,
    so a different zlib — Windows ships zlib-ng — cannot move it),
  * every lobby list the game has, for a seated player, another player and a
    stranger, plus which retention sweep each list asked for,
  * a digest of the room each row loads back into, and of `load_game_state`'s answer.

That record must equal `persistence_baseline/<game>.json`. It was captured before
the shared persistence layer (`core.gamestore`) existed, so a green run means the
extraction changed no row, no list payload and no reloaded room.

The roster is the tree: a new game fails here until it has fixtures. To create
them, run with PERSIST_BASELINE=write (rooms are generated only when their file is
missing; regenerating them is deliberate — delete the file).
"""
import asyncio
import copy
import hashlib
import importlib
import inspect
import json
import os
import random
import re
import time
from pathlib import Path

import pytest

import core.db as coredb
from core import rooms as _rooms

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name("persistence_baseline")
WRITE = os.environ.get("PERSIST_BASELINE") == "write"
T0 = 1_790_000_000
GARBAGE = "this is not a state blob"


def _games():
    out = {}
    for main in sorted((ROOT / "games").glob("*/main.py")):
        text = main.read_text(encoding="utf-8")
        init = re.search(r"^def (\w*init_db)\(\)", text, re.M)
        assert init, f"{main.parent.name}: no *init_db()"
        out[main.parent.name] = init.group(1)
    return out


GAMES = _games()


def test_the_roster_is_the_whole_tree():
    assert len(GAMES) >= 12, sorted(GAMES)


# ── building the frozen rooms (only when a fixture is missing) ───────────────
class _WS:
    client = None

    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def close(self, code=1000):
        pass

    async def send_text(self, t):
        self.sent.append(json.loads(t))

    async def send_json(self, d):
        self.sent.append(d)


def _quiet(mod, monkeypatch):
    mod.ROOMS.clear()
    _rooms._ws_connect_limiter.reset()
    monkeypatch.setattr(mod, "save_game", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_read_room", lambda *a, **k: None)
    monkeypatch.setattr(mod, "get_user_by_session", lambda *a, **k: None)

    async def _anoop(*a, **k):
        return None
    for name, fn in list(vars(mod).items()):
        if name.startswith(("_schedule", "_kick_bots", "_ensure_day_timer")) and callable(fn):
            monkeypatch.setattr(mod, name, _anoop if inspect.iscoroutinefunction(fn)
                                else (lambda *a, **k: None))


def _jsonable(room):
    out = {}
    for k, v in room.items():
        if k == "sockets":
            continue
        try:
            json.dumps(v)
        except TypeError:
            continue
        out[k] = copy.deepcopy(v)
    return out


def _finish(room):
    room = copy.deepcopy(room)
    room["status"] = "over"
    game = room.get("game")
    if isinstance(game, dict) and "winner" in game and game["winner"] is None:
        game["winner"] = next(iter(room["players"]))
    return room


def _build_handler_rooms(mod):
    async def table(rid, host, guests, vs_ai):
        await mod._handle_create(_WS(), rid, host, {"name": host.title(), "vs_ai": vs_ai,
                                                    "num_bots": 1})
        room = mod.ROOMS[rid]
        for g in guests:
            if room["status"] != "open":
                break
            await mod._handle_start(_WS(), rid, host)
            if room["status"] != "open":
                break
            await mod._handle_join(_WS(), rid, g, {"name": g.title()})
        if room["status"] == "open":
            await mod._handle_start(_WS(), rid, host)
        return room

    async def go():
        rooms = {}
        await mod._handle_create(_WS(), "OPEN1", "alice", {"name": "Alice", "vs_ai": False})
        rooms["OPEN1"] = mod.ROOMS["OPEN1"]
        rooms["PLAY1"] = await table("PLAY1", "alice", ["bob", "carol", "dave"], False)
        rooms["BOT1"] = await table("BOT1", "bob", [], True)
        return rooms

    rooms = {rid: _jsonable(r) for rid, r in asyncio.run(go()).items()}
    rooms["OVER1"] = _finish(rooms["PLAY1"])
    return rooms


def _build_spender_rooms(mod):
    def room(host, others, *, start, ai=None):
        players = {host: host.title(), **{o: o.title() for o in others}}
        if ai:
            players["ai"] = f"AI ({ai})"
        game = {"bank": mod._bank_for(2), "decks": mod.build_deck(), "board": None,
                "nobles": None, "players": {}, "turn": None, "order": [],
                "phase": "waiting", "winner": None, "moves": [], "win_points": 15}
        for pid in players:
            game["players"][pid] = {"tokens": mod.empty_gems(), "purchased": [],
                                    "reserved": [], "nobles": []}
        r = {"players": players, "status": "open", "game": game, "host": host,
             "meta": {host: {"token": mod.gen_token(6)}}, "ai_variant": ai,
             "max_players": mod.MAX_PLAYERS}
        if start:
            order = list(players)
            random.shuffle(order)
            game.update(order=order, turn=order[0], phase="playing",
                        bank=mod._bank_for(len(order)), board=mod._deal_board(game["decks"]))
            nobles = list(mod.ALL_NOBLES)
            random.shuffle(nobles)
            game["nobles"] = nobles[:len(order) + 1]
            r["status"] = "playing"
        return r

    rooms = {"OPEN1": room("alice", [], start=False),
             "PLAY1": room("alice", ["bob", "carol"], start=True),
             "BOT1": room("bob", [], start=True, ai="S")}
    rooms["OVER1"] = _finish(rooms["PLAY1"])
    return rooms


def _frozen_rooms(game, mod, monkeypatch):
    path = FIXTURES / f"{game}.rooms.json"
    if not path.exists():
        assert WRITE, (f"{game} has no {path.name}: run this test with "
                       "PERSIST_BASELINE=write to build its rooms and baseline")
        with monkeypatch.context() as mp:
            _quiet(mod, mp)
            rooms = (_build_handler_rooms(mod) if hasattr(mod, "_handle_create")
                     else _build_spender_rooms(mod))
            mod.ROOMS.clear()
        FIXTURES.mkdir(exist_ok=True)
        path.write_text(json.dumps(rooms, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


# ── the record ────────────────────────────────────────────────────────────────
def _reset_writer(mod):
    store = getattr(mod, "STORE", None)
    if store is not None:
        store.reset_writer()
    if hasattr(mod, "_save_conn"):
        mod._save_conn = None


def _flush(mod):
    mod._DB_WRITE_EXEC.submit(lambda: None).result(timeout=30)


def _digest(value):
    """A whole state or room, by the sha256 of its JSON IN KEY ORDER: any changed
    value or reordered key moves it, and the baseline stays small."""
    if value is None:
        return None
    text = json.dumps(value, default=lambda o: type(o).__name__)
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()} ({len(text)} chars)"


def _plain(value):
    return json.loads(json.dumps(value, default=lambda o: type(o).__name__))


def _record(game, mod, init, rooms, tmp_path, monkeypatch):
    monkeypatch.setattr(coredb, "DB_PATH", str(tmp_path / f"{game}.db"))
    conn = coredb.get_db_conn()
    coredb.init_core_schema(conn)
    conn.close()
    _reset_writer(mod)
    getattr(mod, init)()
    sweeps = []
    monkeypatch.setattr(mod, "maybe_cleanup_games",
                        lambda *a, **k: sweeps.append([list(a), k]))
    clock = {"t": T0}
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    try:
        mod.ROOMS.clear()
        # PLAY1 is written once while still open, so its real save below takes the
        # UPDATE path with a status change.
        clock["t"] = T0 - 100
        mod.ROOMS["PLAY1"] = {**copy.deepcopy(rooms["PLAY1"]), "status": "open", "sockets": {}}
        mod.save_game("PLAY1")
        _flush(mod)
        for i, rid in enumerate(sorted(rooms)):
            clock["t"] = T0 + 10 * i
            mod.ROOMS[rid] = {**copy.deepcopy(rooms[rid]), "sockets": {}}
            mod.save_game(rid)
            _flush(mod)
        # the UPDATE path again: a late joiner on a table that is still open
        clock["t"] = T0 + 500
        mod.ROOMS["OPEN1"]["players"]["erin"] = "Erin"
        mod.save_game("OPEN1")
        _flush(mod)
    finally:
        mod.ROOMS.clear()

    conn = coredb.get_db_conn()
    cur = conn.cursor()
    table = _game_table(conn, mod)
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    for n, status in enumerate(("open", "playing", "over")):
        row = {"id": f"BAD{n}", "status": status, "state_json": GARBAGE,
               "created_at": T0 + 600 + n, "updated_at": T0 + 600 + n}
        for c in cols:
            if c in ("player1_id", "host_id"):
                row[c] = "alice"
            elif c in ("player1_name", "host_name"):
                row[c] = "Alice"
            elif c == "player_ids":
                row[c] = json.dumps(["alice"])
        keys = [k for k in row if k in cols]
        cur.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                    [row[k] for k in keys])
    conn.commit()
    stored = []
    for r in cur.execute(f"SELECT * FROM {table} ORDER BY id").fetchall():
        row = {c: r[c] for c in cols}
        if row.get("state_json") and row["state_json"] != GARBAGE:
            row["state_json"] = _digest(_rooms.decode_state(row["state_json"]))
        stored.append(row)
    conn.close()

    lists = {}
    for name in ("list_open_games", "list_active_games"):
        if hasattr(mod, name):
            lists[name] = getattr(mod, name)()
    for name in ("list_user_games", "list_user_history"):
        if hasattr(mod, name):
            for who in ("alice", "bob", "erin", "zed"):
                lists[f"{name}({who})"] = getattr(mod, name)(who)
    clock["t"] = T0 + 1000
    loads = {}
    for rid in [r["id"] for r in stored] + ["MISSING"]:
        mod.ROOMS.clear()
        ok = mod.load_game_to_memory(rid)
        room = mod.ROOMS.get(rid)
        loads[rid] = {"ok": ok, "room": None if room is None else _digest(_jsonable(room))}
        if hasattr(mod, "load_game_state"):
            loads[rid]["load_game_state"] = _digest(mod.load_game_state(rid))
    mod.ROOMS.clear()
    return _plain({"rows": stored, "lists": lists, "sweeps": sweeps, "loads": loads})


def _game_table(conn, mod):
    table = getattr(mod, "TABLE", None)
    if table:
        return table
    names = [r[0] for r in conn.cursor().execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    games = [n for n in names if n not in ("users", "admins", "reconnect_tokens",
                                           "user_sessions")
             and {"state_json", "status"} <= {r[1] for r in conn.cursor().execute(
                 f"PRAGMA table_info({n})").fetchall()}]
    assert len(games) == 1, games
    return games[0]


@pytest.mark.parametrize("game", sorted(GAMES))
def test_persistence_matches_its_baseline(game, tmp_path, monkeypatch):
    mod = importlib.import_module(f"games.{game}.main")
    rooms = _frozen_rooms(game, mod, monkeypatch)
    assert {"OPEN1", "PLAY1", "BOT1", "OVER1"} <= set(rooms), sorted(rooms)
    got = _record(game, mod, GAMES[game], rooms, tmp_path, monkeypatch)
    # Non-vacuity: every saved room reached the table and the seated player's
    # lists came back non-empty.
    assert len(got["rows"]) == len(rooms) + 3, [r["id"] for r in got["rows"]]
    assert got["lists"].get("list_user_games(alice)") or got["lists"].get("list_open_games")
    text = json.dumps(got, indent=1) + "\n"
    path = FIXTURES / f"{game}.json"
    if WRITE:
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"{game}: no baseline; run with PERSIST_BASELINE=write"
    want = path.read_text(encoding="utf-8")
    if text != want:
        a, b = json.loads(want), got
        diff = [k for k in a if a[k] != b.get(k)] + [k for k in b if k not in a]
        detail = []
        for k in diff:
            if isinstance(a.get(k), dict) and isinstance(b.get(k), dict):
                detail += [f"{k}.{s}" for s in set(a[k]) | set(b[k]) if a[k].get(s) != b[k].get(s)]
            else:
                detail.append(k)
        pytest.fail(f"{game}: persistence output changed in {sorted(detail)}")
