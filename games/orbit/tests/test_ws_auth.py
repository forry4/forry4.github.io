"""WebSocket identity binding (main.py).

The ``player`` path segment is client-supplied and every pid in a room is
broadcast in the public players map, so anyone who can see a game could open a
socket claiming the OPPONENT's pid. Orbit redacts state PER RECIPIENT: an
unproven socket handed that seat's view would receive its private Agent hand,
legal choices, and room reconnect token.

These pin the rule that a socket must PROVE ownership of its pid before it can
act as that seat or receive that seat's view. Mirrors the seven games that already
ship the same binding.

Drives the handlers directly with a fake websocket; DB access is stubbed so these
never touch a real users.db.
"""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.orbit import main as m


class _FakeWS:
    def __init__(self, inbox=None):
        self.sent = []
        self._inbox = list(inbox or [])

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        if self._inbox:
            return self._inbox.pop(0)
        raise WebSocketDisconnect()

    def msgs(self):
        return [json.loads(t) for t in self.sent]

    def types(self):
        return [d.get("type") for d in self.msgs()]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    # The WS connect throttle is a per-process sliding window keyed on client IP,
    # and every fake socket reports "unknown" — so without this reset the suite
    # eventually throttles itself and the failures look like anything but a rate
    # limit.
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_read_room", lambda rid: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _open_room(host="alice"):
    ws = _FakeWS()
    run(m._handle_create(ws, "r1", host, {"name": "Alice"}))
    return ws


# ------------------------------------------------------------------- create

def test_creating_a_room_owns_the_seat():
    ws = _FakeWS()
    assert run(m._handle_create(ws, "r1", "alice", {"name": "Alice"})) is True
    assert "created" in ws.types()


def test_a_second_create_on_the_same_room_is_refused():
    _open_room()
    ws = _FakeWS()
    assert run(m._handle_create(ws, "r1", "mallory", {"name": "M"})) is not True
    assert "error" in ws.types()


# --------------------------------------------------------------------- join

def test_joining_a_free_seat_owns_it():
    _open_room()
    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "bob", {"name": "Bob"})) is True
    assert "joined" in ws.types()


def test_claiming_someone_elses_seat_is_refused_and_ships_nothing():
    """The whole point: no proof, no seat, and above all no state."""
    _open_room()
    run(m._handle_join(_FakeWS(), "r1", "bob", {"name": "Bob"}))

    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "bob", {"name": "NotBob"})) is not True
    assert ws.types() == ["error"]
    assert m.ROOMS["r1"]["sockets"].get("bob") is not ws, (
        "an unproven socket must not displace the live one either")


def test_a_matching_session_token_reclaims_your_own_seat(monkeypatch):
    _open_room()
    run(m._handle_join(_FakeWS(), "r1", "bob", {"name": "Bob"}))
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: {"id": "bob"})

    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "bob",
                              {"name": "Bob", "session_token": "s"})) is True
    assert "joined" in ws.types()


def test_a_full_room_turns_away_a_third_player():
    _open_room()
    run(m._handle_join(_FakeWS(), "r1", "bob", {"name": "Bob"}))
    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "carol", {"name": "C"})) is not True
    assert "error" in ws.types()


# ---------------------------------------------------------------- reconnect

def test_reconnect_needs_the_rooms_own_token():
    _open_room()
    bad = _FakeWS()
    assert run(m._handle_reconnect(bad, "r1", "alice", {"token": "nope"})) is not True
    assert bad.types() == ["error"]

    good = _FakeWS()
    token = m.ROOMS["r1"]["meta"]["alice"]["token"]
    assert run(m._handle_reconnect(good, "r1", "alice", {"token": token})) is True
    assert "joined" in good.types()


def test_auth_reconnect_needs_a_session_that_matches_the_pid(monkeypatch):
    _open_room()
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: {"id": "someone_else"})
    ws = _FakeWS()
    assert run(m._handle_auth_reconnect(ws, "r1", "alice",
                                        {"session_token": "s"})) is not True
    assert ws.types() == ["error"]


# ------------------------------------------------------------- the gate itself

def test_every_mutating_action_is_gated_on_authed():
    """The socket loop refuses start/move/abandon until the handshake passed.

    Read off the source rather than driven, because the alternative is asserting
    on a loop that needs a live socket — and the thing worth pinning is that the
    LIST of gated actions has not quietly lost a member.
    """
    import inspect

    src = inspect.getsource(m.ws_room_player)
    gated = src.split('elif action in (')[1].split(')')[0]
    for action in ("start", "move", "abandon"):
        assert f'"{action}"' in gated, f"{action} is no longer behind the gate"
    assert "not authenticated for this seat" in src


def test_an_unauthed_socket_cannot_move():
    _open_room()
    ws = _FakeWS([json.dumps({"action": "move", "move": {"kind": "order", "slot": 0}})])
    run(m.ws_room_player(ws, "r1", "alice"))
    assert ws.msgs()[-1]["message"] == "not authenticated for this seat"


def test_a_socket_is_not_registered_before_the_handshake():
    """Merely opening a socket must not put it in the room.

    Spender used to register at connect time, and because broadcasts are built
    per recipient keyed on the socket's pid, a socket that claimed a victim's pid
    and sent NOTHING was handed that seat's view and its reconnect token.
    """
    _open_room()
    ws = _FakeWS([json.dumps({"action": "ping"})])
    run(m.ws_room_player(ws, "r1", "bob"))
    assert "bob" not in m.ROOMS["r1"]["sockets"]
    assert ws.msgs()[-1]["type"] == "error"


# ------------------------------------------------------------- token scoping

def test_a_recipient_only_ever_sees_their_own_reconnect_token():
    _open_room()
    run(m._handle_join(_FakeWS(), "r1", "bob", {"name": "Bob"}))
    for pid in ("alice", "bob"):
        state = m.mk_room_state("r1", viewer_pid=pid)
        assert set(state["reconnect_tokens"]) == {pid}
        other = "bob" if pid == "alice" else "alice"
        assert m.ROOMS["r1"]["meta"][other]["token"] not in json.dumps(state)


def test_a_spectator_gets_no_tokens_at_all():
    _open_room()
    assert m.mk_room_state("r1", viewer_pid=None)["reconnect_tokens"] == {}


def test_bot_position_key_changes_when_only_a_pending_choice_advances():
    game = {
        "phase": "play", "turn_pid": "bot", "turn_number": 3,
        "pending_pid": "bot", "log": [],
        "pending": {"source": "effect", "queue": [{"type": "exile", "done": 0}]},
    }
    before = m._position_key(game)
    game["pending"]["queue"][0]["done"] = 1
    assert m._position_key(game) != before
