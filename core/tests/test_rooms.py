"""core/rooms.py — the shared room-server primitives.

These used to be four hand-maintained copies, one per game. The tests that matter
most here are the ones guarding the two rules that copies kept getting subtly
different: the SELECT-then-DELETE cancel (never cursor.rowcount, which raises on
libsql) and the stale-socket disconnect guard.
"""
import asyncio
import json
import random
import sqlite3

import pytest

from core import rooms


# ─── small helpers ───────────────────────────────────────────────────────────

def test_normalize_room_uppercases_and_tolerates_none():
    assert rooms.normalize_room("abc123") == "ABC123"
    assert rooms.normalize_room("ABC") == "ABC"
    assert rooms.normalize_room(None) == ""
    assert rooms.normalize_room("") == ""


def test_gen_room_token_is_random_and_sized():
    a, b = rooms.gen_room_token(), rooms.gen_room_token()
    assert a != b
    assert len(rooms.gen_room_token(6)) > 0


def test_ensure_room_loaded_hydrates_once():
    store = {}
    calls = []

    def loader(rid):
        calls.append(rid)
        store[rid] = {"players": {}, "sockets": {}}

    assert rooms.ensure_room_loaded(store, "R1", loader) is store["R1"]
    assert calls == ["R1"]
    # Already resident -> no second load.
    assert rooms.ensure_room_loaded(store, "R1", loader) is store["R1"]
    assert calls == ["R1"]


def test_ensure_room_loaded_returns_none_when_the_loader_finds_nothing():
    assert rooms.ensure_room_loaded({}, "GONE", lambda rid: None) is None


def test_send_json_serialises_the_payload():
    sent = []

    class WS:
        async def send_text(self, t):
            sent.append(t)

    asyncio.new_event_loop().run_until_complete(rooms.send_json(WS(), {"type": "ok", "n": 1}))
    assert json.loads(sent[0]) == {"type": "ok", "n": 1}


# ─── delete_open_game ────────────────────────────────────────────────────────

class _NoCloseConn:
    """Wraps a live sqlite3 connection so the helper's own `close()` is a no-op —
    otherwise the in-memory DB would vanish between statements. Everything else
    passes straight through."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def db(monkeypatch):
    """An in-memory DB standing in for the shared connection."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t_games (id TEXT PRIMARY KEY, owner TEXT, status TEXT)")
    conn.commit()
    monkeypatch.setattr(rooms, "db_conn", lambda: _NoCloseConn(conn))
    return conn


def _rows(conn):
    return conn.execute("SELECT id FROM t_games").fetchall()


def test_delete_open_game_removes_the_hosts_open_row(db):
    db.execute("INSERT INTO t_games VALUES ('g1', 'u1', 'open')")
    db.commit()
    assert rooms.delete_open_game("t_games", "owner", "g1", "u1") is True
    assert _rows(db) == []


def test_delete_open_game_refuses_someone_elses_game(db):
    db.execute("INSERT INTO t_games VALUES ('g1', 'u1', 'open')")
    db.commit()
    assert rooms.delete_open_game("t_games", "owner", "g1", "attacker") is False
    assert len(_rows(db)) == 1


def test_delete_open_game_refuses_a_game_in_progress(db):
    db.execute("INSERT INTO t_games VALUES ('g1', 'u1', 'playing')")
    db.commit()
    assert rooms.delete_open_game("t_games", "owner", "g1", "u1") is False
    assert len(_rows(db)) == 1


def test_delete_open_game_on_a_missing_row_is_false_not_an_error(db):
    assert rooms.delete_open_game("t_games", "owner", "nope", "u1") is False


def test_delete_open_game_never_reads_rowcount(db, monkeypatch):
    """THE REGRESSION THIS EXISTS FOR: libsql's wrapper has no cursor.rowcount, and
    reading it RAISED on the prod Turso backend — 500ing the cancel endpoint. Stand
    up a connection whose cursors explode on `.rowcount` and prove the helper works."""

    class NoRowcountCursor:
        def __init__(self, cur):
            self._cur = cur

        def __getattr__(self, name):
            if name == "rowcount":
                raise AttributeError("libsql cursors have no rowcount")
            return getattr(self._cur, name)

    class NoRowcountConn(_NoCloseConn):
        def cursor(self):
            return NoRowcountCursor(self._conn.cursor())

    monkeypatch.setattr(rooms, "db_conn", lambda: NoRowcountConn(db))
    db.execute("INSERT INTO t_games VALUES ('g1', 'u1', 'open')")
    db.commit()
    assert rooms.delete_open_game("t_games", "owner", "g1", "u1") is True
    assert _rows(db) == []


def test_delete_open_game_rejects_a_non_identifier_table():
    with pytest.raises(AssertionError):
        rooms.delete_open_game("t_games; DROP TABLE users", "owner", "g", "u")


# ─── release_socket (the stale-socket guard) ─────────────────────────────────

def _room(status="open", game=None, **sockets):
    return {"players": {}, "sockets": dict(sockets), "status": status, "game": game}


def test_release_socket_removes_only_the_matching_socket():
    ws = object()
    store = {"R": _room(p1=ws, p2=object())}
    rooms.release_socket(store, "R", "p1", ws)
    assert "p1" not in store["R"]["sockets"]
    assert "p2" in store["R"]["sockets"]


def test_release_socket_ignores_a_superseded_socket():
    """THE RECONNECT RACE: WS1 drops after WS2 has already registered. The departing
    handler must not remove the live socket (that once deleted rooms mid-game)."""
    old, new = object(), object()
    store = {"R": _room(p1=new)}
    dropped = rooms.release_socket(store, "R", "p1", old)
    assert dropped is False
    assert store["R"]["sockets"]["p1"] is new
    assert "R" in store


def test_release_socket_drops_an_empty_never_started_lobby():
    ws = object()
    store = {"R": _room(status="open", game=None, p1=ws)}
    assert rooms.release_socket(store, "R", "p1", ws) is True
    assert "R" not in store


def test_release_socket_keeps_an_empty_game_in_progress():
    """A playing/over game stays resident so it can be resumed."""
    ws = object()
    store = {"R": _room(status="playing", game={"phase": "playing"}, p1=ws)}
    assert rooms.release_socket(store, "R", "p1", ws) is False
    assert "R" in store


def test_release_socket_drop_empty_open_only_false_drops_anything():
    """Spender's variant: any empty room goes."""
    ws = object()
    store = {"R": _room(status="playing", game={"phase": "playing"}, p1=ws)}
    assert rooms.release_socket(store, "R", "p1", ws, drop_empty_open_only=False) is True
    assert "R" not in store


def test_release_socket_disarms_the_client_ai_when_asked():
    ws = object()
    store = {"R": _room(status="playing", game={}, p1=ws, p2=object())}
    store["R"]["client_ai"] = True
    rooms.release_socket(store, "R", "p1", ws, disarm_client_ai=True)
    assert store["R"]["client_ai"] is False


def test_release_socket_leaves_client_ai_alone_by_default():
    ws = object()
    store = {"R": _room(status="playing", game={}, p1=ws, p2=object())}
    store["R"]["client_ai"] = True
    rooms.release_socket(store, "R", "p1", ws)
    assert store["R"]["client_ai"] is True


def test_release_socket_on_a_missing_room_is_a_noop():
    assert rooms.release_socket({}, "GONE", "p1", object()) is False


def test_phantom_room_is_collected_even_though_no_socket_matched():
    """REGRESSION: Spender's WS handler setdefaults a room shell on CONNECT but no
    longer registers the socket until a handshake proves identity — so a client that
    connects and leaves never matches the ownership check, and the shell used to
    leak forever. Unauthenticated and repeatable with random room codes."""
    store = {"R": {"players": {}, "sockets": {}, "status": "open", "game": None, "meta": {}}}
    assert rooms.release_socket(store, "R", "nobody", object()) is True
    assert store == {}


def test_phantom_collection_never_touches_a_room_with_players():
    """A real room whose last socket dropped is NOT a phantom — a resumable game
    keeps its seats and must stay resident."""
    store = {"R": {"players": {"p1": "Ann"}, "sockets": {}, "status": "playing",
                   "game": {"phase": "playing"}}}
    assert rooms.release_socket(store, "R", "p1", object()) is False
    assert "R" in store


def test_phantom_collection_does_not_break_the_stale_socket_guard():
    """A superseded socket must still not disturb a LIVE room."""
    new = object()
    store = {"R": {"players": {"p1": "Ann"}, "sockets": {"p1": new}, "status": "playing",
                   "game": {"phase": "playing"}}}
    assert rooms.release_socket(store, "R", "p1", object()) is False
    assert store["R"]["sockets"]["p1"] is new


# ─── WebSocket abuse throttles ───────────────────────────────────────────────

class _FakeWS:
    def __init__(self, headers=None, host="1.2.3.4"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()
        self.closed_with = None

    async def close(self, code=1000):
        self.closed_with = code


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_client_ip_uses_the_last_xff_hop():
    """Render APPENDS the real peer to any client-supplied X-Forwarded-For, so the
    LAST hop is trustworthy. Trusting the leftmost is the classic XFF bug: a peer
    rotating a spoofed header would land under a fresh key every time."""
    ws = _FakeWS(headers={"x-forwarded-for": "9.9.9.9, 8.8.8.8, 203.0.113.7"})
    assert rooms.client_ip(ws) == "203.0.113.7"


def test_client_ip_falls_back_to_the_socket_peer():
    assert rooms.client_ip(_FakeWS(host="10.0.0.5")) == "10.0.0.5"
    assert rooms.client_ip(_FakeWS(host=None)) == "unknown"


def test_connect_flood_is_cut_off_and_the_socket_closed():
    rooms._ws_connect_limiter.reset()
    allowed = 0
    for _ in range(rooms.WS_CONNECTS_PER_MIN + 10):
        ws = _FakeWS(host="203.0.113.9")
        if not _run(rooms.reject_if_connecting_too_fast(ws)):
            allowed += 1
        else:
            assert ws.closed_with == 1008
    assert allowed == rooms.WS_CONNECTS_PER_MIN
    rooms._ws_connect_limiter.reset()


def test_connect_limit_is_per_ip_not_global():
    rooms._ws_connect_limiter.reset()
    for _ in range(rooms.WS_CONNECTS_PER_MIN):
        _run(rooms.reject_if_connecting_too_fast(_FakeWS(host="198.51.100.1")))
    # A different peer is unaffected.
    assert _run(rooms.reject_if_connecting_too_fast(_FakeWS(host="198.51.100.2"))) is False
    rooms._ws_connect_limiter.reset()


def test_an_oversized_room_or_player_id_is_refused_at_the_connect_gate():
    """Both path segments are client-chosen and become dict keys, DB columns and
    part of every broadcast. Only Spender bounded them; the other eleven sockets
    took ~16KB each. The bound lives in the one call every game makes on connect."""
    rooms._ws_connect_limiter.reset()
    ok = _FakeWS(host="203.0.113.50")
    ok.path_params = {"room": "ABC123", "player": "p" * rooms.MAX_ID_LEN}
    assert _run(rooms.reject_if_connecting_too_fast(ok)) is False and ok.closed_with is None

    for bad in ({"room": "R" * (rooms.MAX_ID_LEN + 1), "player": "p1"},
                {"room": "ABC123", "player": "p" * 5000}):
        ws = _FakeWS(host="203.0.113.51")
        ws.path_params = bad
        assert _run(rooms.reject_if_connecting_too_fast(ws)) is True
        assert ws.closed_with == 1008
    # Refused before it is counted: junk must not spend the peer's connect budget.
    assert rooms._ws_connect_limiter.count("203.0.113.51") == 0
    rooms._ws_connect_limiter.reset()


def test_every_game_socket_passes_through_the_connect_gate():
    """The id bound above only reaches a game that calls the gate. Derived from
    the tree, so the next game is held to it the day it ships."""
    import ast
    from pathlib import Path
    mains = sorted((Path(__file__).resolve().parents[2] / "games").glob("*/main.py"))
    assert len(mains) >= 12, mains
    for main in mains:
        tree = ast.parse(main.read_text(encoding="utf-8"))
        sockets = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                   and any(".websocket(" in ast.unparse(d) for d in n.decorator_list)]
        assert sockets, f"{main}: no websocket endpoint found"
        for fn in sockets:
            assert any(isinstance(n, ast.Attribute) and n.attr == "reject_if_connecting_too_fast"
                       for n in ast.walk(fn)), (
                f"{main}: {fn.name}() must call _rooms.reject_if_connecting_too_fast(websocket)")


def test_a_missing_room_token_never_matches_a_seat_that_has_none():
    """A bot seat has no meta entry. `stored != sent` read None != None for a
    `reconnect` with no token, and handed an anonymous socket the bot's seat."""
    room = {"players": {"human": "H", "bot": "Bot"}, "meta": {"human": {"token": "tok123"}, "odd": {}}}
    for missing in (None, "", 0, [], {}):
        assert not rooms.seat_proof_matches(room, "bot", room_token=missing)
        assert not rooms.seat_proof_matches(room, "odd", room_token=missing)
        assert not rooms.seat_proof_matches(room, "human", room_token=missing)
    assert not rooms.seat_proof_matches(room, "bot", room_token="None")
    assert not rooms.seat_proof_matches(room, "human", room_token="tok124")
    assert rooms.seat_proof_matches(room, "human", room_token="tok123")
    # Straight off the wire: a non-ASCII token is a wrong token, not a TypeError
    # (hmac.compare_digest refuses non-ASCII str).
    assert not rooms.seat_proof_matches(room, "human", room_token="tök123")
    assert not rooms.seat_proof_matches({"meta": {"human": None}}, "human", room_token="x")


def test_a_reconnect_token_must_be_minted_by_the_seats_own_account():
    """room + seat + USER. Without the third, a token recorded only what its
    caller asked for, so any account could mint one for anyone's seat."""
    mine = {"room_id": "ROOMA", "player_id": "acct1", "user_id": "acct1"}
    assert rooms.reconnect_token_matches(mine, "ROOMA", "acct1")
    assert rooms.reconnect_token_matches({**mine, "room_id": "rooma"}, "ROOMA", "acct1")   # codes fold
    assert not rooms.reconnect_token_matches(mine, "ROOMB", "acct1")
    assert not rooms.reconnect_token_matches(mine, "ROOMA", "acct2")
    # THE HOLE: minted by acct2 FOR acct1's seat.
    assert not rooms.reconnect_token_matches({**mine, "user_id": "acct2"}, "ROOMA", "acct1")
    assert not rooms.reconnect_token_matches({**mine, "user_id": None}, "ROOMA", "acct1")
    assert not rooms.reconnect_token_matches(None, "ROOMA", "acct1")
    assert not rooms.reconnect_token_matches({}, "ROOMA", "")


def test_move_of_only_ever_returns_an_object():
    assert rooms.move_of({"move": {"type": "buy"}}) == {"type": "buy"}
    for junk in ({}, {"move": None}, {"move": [1]}, {"move": "x"}, {"move": 7}, {"move": True}):
        assert rooms.move_of(junk) == {}


def test_message_throttle_allows_then_blocks_within_the_window():
    t = rooms.MessageThrottle(max_per_min=3)
    assert [t.allow(now=1000.0) for _ in range(3)] == [True, True, True]
    assert t.allow(now=1000.0) is False


def test_message_throttle_recovers_after_the_window():
    t = rooms.MessageThrottle(max_per_min=2)
    t.allow(now=1000.0); t.allow(now=1000.0)
    assert t.allow(now=1000.0) is False
    assert t.allow(now=1061.0) is True      # window rolled past


def test_message_throttle_is_per_socket_so_it_cannot_leak():
    """Per-instance deque, not a shared dict keyed by socket — it dies with the
    connection rather than accumulating entries for every peer ever seen."""
    a, b = rooms.MessageThrottle(max_per_min=1), rooms.MessageThrottle(max_per_min=1)
    assert a.allow(now=1.0) is True and a.allow(now=1.0) is False
    assert b.allow(now=1.0) is True        # independent budget


# ─── state_json codec (compressed at-rest storage, all five games) ───────────

def test_encode_decode_round_trips_a_state():
    state = {"players": {"a": "Al", "b": "Bo"}, "game": {"log": [1, 2, 3] * 50},
             "meta": {"a": {"token": "x"}}, "unicode": "würfel — 石"}
    blob = rooms.encode_state(state)
    assert isinstance(blob, str) and blob.startswith("z:")
    assert rooms.decode_state(blob) == state


def test_encoded_blob_is_much_smaller_than_plain_json():
    # the whole point: repetitive game state compresses hard
    state = {"log": [{"event": "draw", "cards": ["Copper", "Estate"], "pid": "a"}] * 300}
    blob = rooms.encode_state(state)
    assert len(blob) < len(json.dumps(state)) // 3


def test_decode_reads_legacy_plain_json_blobs_unchanged():
    """Live prod rows are plain JSON (start with '{'); they must load with no
    migration and re-encode compressed on the next save."""
    legacy = json.dumps({"game": {"turn": "a"}, "status": "playing"})
    assert legacy.startswith("{")
    assert rooms.decode_state(legacy) == {"game": {"turn": "a"}, "status": "playing"}


def test_decode_empty_or_none_is_an_empty_dict():
    # the read sites that used `json.loads(x or "{}")` rely on this
    assert rooms.decode_state(None) == {}
    assert rooms.decode_state("") == {}


def test_decode_accepts_bytes_from_the_driver():
    blob = rooms.encode_state({"k": "v"})
    assert rooms.decode_state(blob.encode("ascii")) == {"k": "v"}


# ── rng_state packing (shared by CoC / Duel / Dontminion persist.py) ─────────
def _rng_state(seed=7, draws=50):
    r = random.Random(seed)
    for _ in range(draws):
        r.random()
    st = r.getstate()
    return [st[0], list(st[1]), st[2]]          # the JSON-safe shape games persist


def test_pack_rng_round_trips_exactly():
    st = _rng_state()
    assert rooms.unpack_rng(rooms.pack_rng(st)) == st


def test_packed_rng_reproduces_the_same_stream():
    """A lossy pack would silently change every future draw in a resumed game."""
    st = _rng_state()
    back = rooms.unpack_rng(rooms.pack_rng(st))
    a, b = random.Random(), random.Random()
    a.setstate((st[0], tuple(st[1]), st[2]))
    b.setstate((back[0], tuple(back[1]), back[2]))
    assert [a.random() for _ in range(500)] == [b.random() for _ in range(500)]
    assert [a.getrandbits(32) for _ in range(100)] == [b.getrandbits(32) for _ in range(100)]


def test_pack_rng_actually_shrinks_it():
    st = _rng_state()
    assert len(json.dumps(rooms.pack_rng(st))) < len(json.dumps(st)) * 0.6


def test_pack_rng_leaves_anything_unexpected_alone():
    """Already packed, None, or a shape it doesn't recognise -> returned unchanged,
    so a legacy or double-applied blob can't be corrupted."""
    for odd in (None, [], [3], "nope", {"a": 1}, [3, "notalist", None]):
        assert rooms.pack_rng(odd) == odd
        assert rooms.unpack_rng(odd) == odd
    packed = rooms.pack_rng(_rng_state())
    assert rooms.pack_rng(packed) == packed          # idempotent
    assert rooms.unpack_rng(rooms.unpack_rng(packed)) == rooms.unpack_rng(packed)


def test_unpack_rng_passes_a_legacy_unpacked_value_through():
    st = _rng_state()
    assert rooms.unpack_rng(st) == st                # a pre-compaction row


def test_a_corrupt_blob_still_raises_like_json_loads():
    # callers wrap these reads in try/except; the codec must not swallow errors
    with pytest.raises(Exception):
        rooms.decode_state("{not valid json")
