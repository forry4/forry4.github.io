"""WebSocket identity binding (main.py).

The `player` path segment is client-supplied, and every pid in a room is broadcast in
the public players map — so anyone who can see a game could open a socket claiming the
OPPONENT's pid. Duel redacts state PER RECIPIENT (`viewer_pid`), so an unproven socket
would be handed that seat's own secret reserves, and could submit moves on its turn
(`_handle_move` only checks whose turn it is).

These tests pin the rule that a socket must PROVE ownership of its pid before it can
act as that seat or receive that seat's view. Mirrors games/wherewolf/tests/test_ws_auth.py,
which is where this binding pattern was first shipped.

Drives the handlers / the WS loop directly with a fake websocket; DB access is stubbed
so these never touch a real users.db.
"""
import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.spender_duel import main as m


class _FakeWS:
    """Records sent frames; optionally replays a scripted inbox for the WS loop."""

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
    """No DB; a clean ROOMS slate; no logged-in users unless a test says so. A fresh
    per-test event loop + ROOM_LOCK so the module lock never straddles two loops."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    # The WS connect throttle (core.rooms) is a per-process sliding window keyed on
    # client IP — and every fake socket here reports "unknown", so the whole suite
    # shares ONE 60/min budget with no natural reset. Left alone, adding tests (or a
    # re-run inside the same minute) starts closing sockets with 1008 and the failures
    # look like anything but a rate limit. Reset it per test.
    _rooms._ws_connect_limiter.reset()
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)
    yield
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _open_room(rid, host="host"):
    _run(m._handle_create(_FakeWS(), rid, host, {"name": "Host"}))


# ── handler-level: join to an existing seat requires proof ────────────────────
def test_create_authenticates_the_creator():
    ws = _FakeWS()
    assert _run(m._handle_create(ws, "ROOMA", "host", {"name": "Host"})) is True
    assert "created" in ws.types()


def test_join_new_seat_authenticates():
    rid = "ROOMB"
    _open_room(rid)
    joiner = _FakeWS()
    assert _run(m._handle_join(joiner, rid, "guest", {"name": "Guest"})) is True
    assert m.ROOMS[rid]["sockets"]["guest"] is joiner
    assert "joined" in joiner.types()


def test_join_existing_seat_without_proof_is_rejected():
    """The core exploit: a stranger claiming a seated pid must NOT get the seat —
    the 'joined' reply carries that seat's un-redacted reserves."""
    rid = "ROOMC"
    _open_room(rid)
    victim = _FakeWS()
    _run(m._handle_join(victim, rid, "victim", {"name": "Victim"}))

    attacker = _FakeWS()
    authed = _run(m._handle_join(attacker, rid, "victim", {"name": "hijack"}))

    assert authed is False
    assert attacker.types() == ["error"]          # never got a private-view frame
    assert m.ROOMS[rid]["sockets"]["victim"] is victim   # seat not hijacked


def test_join_existing_seat_with_matching_session_token_ok(monkeypatch):
    """A logged-in user re-entering their OWN seat (pid == account id) is allowed."""
    rid = "ROOMD"
    _open_room(rid)
    _run(m._handle_join(_FakeWS(), rid, "acct-1", {"name": "Real"}))

    monkeypatch.setattr(m, "get_user_by_session",
                        lambda tok: {"id": "acct-1"} if tok == "good" else None)
    ws2 = _FakeWS()
    authed = _run(m._handle_join(ws2, rid, "acct-1", {"name": "Real", "session_token": "good"}))
    assert authed is True
    assert m.ROOMS[rid]["sockets"]["acct-1"] is ws2


def test_join_existing_seat_with_wrong_account_rejected(monkeypatch):
    """A valid session for a DIFFERENT account can't claim someone else's seat."""
    rid = "ROOME"
    _open_room(rid)
    victim = _FakeWS()
    _run(m._handle_join(victim, rid, "acct-victim", {"name": "Victim"}))

    monkeypatch.setattr(m, "get_user_by_session", lambda tok: {"id": "acct-attacker"})
    attacker = _FakeWS()
    authed = _run(m._handle_join(attacker, rid, "acct-victim",
                                 {"name": "x", "session_token": "attacker-sess"}))
    assert authed is False
    assert m.ROOMS[rid]["sockets"]["acct-victim"] is victim


def test_reconnect_with_wrong_room_token_does_not_authenticate():
    rid = "ROOMF"
    _open_room(rid)
    _run(m._handle_join(_FakeWS(), rid, "victim", {"name": "Victim"}))
    attacker = _FakeWS()
    assert _run(m._handle_reconnect(attacker, rid, "victim", {"token": "nope"})) is False
    assert attacker.types() == ["error"]


def test_reconnect_with_the_seat_token_authenticates():
    rid = "ROOMG"
    _open_room(rid)
    _run(m._handle_join(_FakeWS(), rid, "guest", {"name": "Guest"}))
    tok = m.ROOMS[rid]["meta"]["guest"]["token"]
    ws2 = _FakeWS()
    assert _run(m._handle_reconnect(ws2, rid, "guest", {"token": tok})) is True
    assert m.ROOMS[rid]["sockets"]["guest"] is ws2


# ── loop-level: privileged actions require an authenticated socket ────────────
@pytest.mark.parametrize("action", ["move", "start", "abandon", "client_ai_ready", "ai_move"])
def test_privileged_actions_gated_before_handshake(action):
    """A spoofed-pid socket that never handshakes can't act. The gate fires BEFORE the
    handler, so the error is the auth one, not the handler's own complaint."""
    ws = _FakeWS(inbox=[json.dumps({"action": action, "move": {"type": "pass"}})])
    _run(m.ws_room_player(ws, "ROOMH", "victim"))
    assert any(d.get("message") == "not authenticated for this seat"
               for d in ws.msgs() if d.get("type") == "error")


def test_move_allowed_after_a_real_handshake():
    """Sanity control: the gate is about identity, not a blanket block — an authed
    socket reaches _handle_move (whose own rejection is a game-state message)."""
    rid = "ROOMI"
    ws = _FakeWS(inbox=[
        json.dumps({"action": "create", "name": "Host"}),
        json.dumps({"action": "move", "move": {"type": "pass"}}),
    ])
    _run(m.ws_room_player(ws, rid, "host"))
    assert not any(d.get("message") == "not authenticated for this seat"
                   for d in ws.msgs() if d.get("type") == "error")
