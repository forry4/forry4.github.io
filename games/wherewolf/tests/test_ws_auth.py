"""WebSocket identity binding (main.py).

The `player` path segment is client-supplied: anyone can open a socket claiming any
pid (all pids are broadcast publicly). These tests pin the rule that a socket must
PROVE ownership of its pid before it can act as that seat or receive that seat's
private (secret-role / night) view — closing the impersonation hole where an attacker
could read a co-player's role and vote as them.

Drives the handlers / the WS loop directly with a fake websocket; DB access is stubbed
so these never touch a real users.db.
"""
import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.wherewolf import main as m


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
    # Shared 60/min WS connect budget, keyed "unknown" for every fake socket here —
    # reset it per test or the suite eventually throttles itself. See core.rooms.
    _rooms._ws_connect_limiter.reset()
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)
    yield
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── handler-level: join to an existing seat requires proof ────────────────────
def test_join_new_seat_authenticates():
    rid = "ROOMA"
    _run(m._handle_create(_FakeWS(), rid, "host", {"name": "Host"}))
    victim_ws = _FakeWS()
    authed = _run(m._handle_join(victim_ws, rid, "victim", {"name": "Victim"}))
    assert authed is True
    assert m.ROOMS[rid]["sockets"]["victim"] is victim_ws
    assert "joined" in victim_ws.types()


def test_join_existing_seat_without_proof_is_rejected():
    """The core exploit: a stranger claiming a seated pid must NOT get the seat."""
    rid = "ROOMB"
    _run(m._handle_create(_FakeWS(), rid, "host", {"name": "Host"}))
    victim_ws = _FakeWS()
    _run(m._handle_join(victim_ws, rid, "victim", {"name": "Victim"}))

    attacker_ws = _FakeWS()
    authed = _run(m._handle_join(attacker_ws, rid, "victim", {"name": "hijack"}))

    assert authed is False
    # No private-view frame ("joined") was ever sent to the attacker.
    assert attacker_ws.types() == ["error"]
    # The seat's live socket is still the victim's — not hijacked.
    assert m.ROOMS[rid]["sockets"]["victim"] is victim_ws


def test_join_existing_seat_with_matching_session_token_ok(monkeypatch):
    """A logged-in user re-entering their OWN seat (pid == account id) is allowed."""
    rid = "ROOMC"
    _run(m._handle_create(_FakeWS(), rid, "host", {"name": "Host"}))
    _run(m._handle_join(_FakeWS(), rid, "acct-1", {"name": "Real"}))

    monkeypatch.setattr(m, "get_user_by_session",
                        lambda tok: {"id": "acct-1"} if tok == "good" else None)
    ws2 = _FakeWS()
    authed = _run(m._handle_join(ws2, rid, "acct-1", {"name": "Real", "session_token": "good"}))
    assert authed is True
    assert m.ROOMS[rid]["sockets"]["acct-1"] is ws2


def test_join_existing_seat_with_wrong_account_rejected(monkeypatch):
    """A valid session for a DIFFERENT account can't claim someone else's seat."""
    rid = "ROOMD"
    _run(m._handle_create(_FakeWS(), rid, "host", {"name": "Host"}))
    victim_ws = _FakeWS()
    _run(m._handle_join(victim_ws, rid, "acct-victim", {"name": "Victim"}))

    monkeypatch.setattr(m, "get_user_by_session", lambda tok: {"id": "acct-attacker"})
    attacker_ws = _FakeWS()
    authed = _run(m._handle_join(attacker_ws, rid, "acct-victim",
                                 {"name": "x", "session_token": "attacker-sess"}))
    assert authed is False
    assert m.ROOMS[rid]["sockets"]["acct-victim"] is victim_ws


# ── loop-level: privileged actions require an authenticated socket ────────────
def test_move_before_handshake_is_gated():
    """A spoofed-pid socket that never handshakes can't move — the gate fires before
    _handle_move (whose own error would be 'game not started')."""
    rid = "ROOME"
    ws = _FakeWS(inbox=[json.dumps({"action": "move", "move": {"type": "ready"}})])
    _run(m.ws_room_player(ws, rid, "victim"))
    assert any(d.get("message") == "not authenticated for this seat"
               for d in ws.msgs() if d.get("type") == "error")


def test_set_roles_and_start_gated_for_unauthenticated_socket():
    """Spoofing the host pid can't drive set_roles/start without authenticating."""
    for action in ("set_roles", "start"):
        rid = "ROOMF" + action[:1]
        ws = _FakeWS(inbox=[json.dumps({"action": action, "deck": ["villager"]})])
        _run(m.ws_room_player(ws, rid, "host"))
        assert any(d.get("message") == "not authenticated for this seat"
                   for d in ws.msgs() if d.get("type") == "error")
