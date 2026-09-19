"""Identity binding and per-recipient room-state coverage for Pinch."""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as shared_rooms
from games.pinch import main as m


class FakeWS:
    def __init__(self, inbox=None):
        self.sent = []
        self.inbox = list(inbox or [])

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(text)

    async def receive_text(self):
        if self.inbox:
            return self.inbox.pop(0)
        raise WebSocketDisconnect()

    def messages(self):
        return [json.loads(text) for text in self.sent]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    shared_rooms._ws_connect_limiter = shared_rooms.SlidingWindowLimiter(
        shared_rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    monkeypatch.setattr(m, "get_user_by_session", lambda _token: None)
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def open_room():
    ws = FakeWS()
    assert run(m._handle_create(ws, "room", "alice", {"name": "Alice"}))
    return ws


def test_create_join_and_full_room():
    open_room()
    bob = FakeWS()
    assert run(m._handle_join(bob, "room", "bob", {"name": "Bob"}))
    assert bob.messages()[0]["type"] == "joined"
    mallory = FakeWS()
    assert not run(m._handle_join(mallory, "room", "mallory", {"name": "M"}))
    assert mallory.messages() == [{"type": "error", "message": "room is full or already started"}]


def test_existing_seat_needs_account_or_room_proof(monkeypatch):
    open_room()
    run(m._handle_join(FakeWS(), "room", "bob", {"name": "Bob"}))
    impostor = FakeWS()
    assert not run(m._handle_join(impostor, "room", "bob", {"name": "Not Bob"}))
    assert m.ROOMS["room"]["sockets"]["bob"] is not impostor

    monkeypatch.setattr(m, "get_user_by_session", lambda _token: {"id": "bob"})
    owner = FakeWS()
    assert run(m._handle_join(owner, "room", "bob", {"name": "Bob", "session_token": "ok"}))
    assert m.ROOMS["room"]["sockets"]["bob"] is owner


def test_reconnect_token_and_session_are_bound_to_pid(monkeypatch):
    open_room()
    bad = FakeWS()
    assert not run(m._handle_reconnect(bad, "room", "alice", {"token": "wrong"}))
    token = m.ROOMS["room"]["meta"]["alice"]["token"]
    good = FakeWS()
    assert run(m._handle_reconnect(good, "room", "alice", {"token": token}))

    monkeypatch.setattr(m, "get_user_by_session", lambda _token: {"id": "somebody-else"})
    wrong_account = FakeWS()
    assert not run(m._handle_auth_reconnect(
        wrong_account, "room", "alice", {"session_token": "session"}))


def test_room_state_only_contains_the_viewers_reconnect_token():
    open_room()
    run(m._handle_join(FakeWS(), "room", "bob", {"name": "Bob"}))
    for pid, other in (("alice", "bob"), ("bob", "alice")):
        view = m.mk_room_state("room", pid)
        assert set(view["reconnect_tokens"]) == {pid}
        assert m.ROOMS["room"]["meta"][other]["token"] not in json.dumps(view)
    assert m.mk_room_state("room", None)["reconnect_tokens"] == {}


def test_socket_is_not_registered_and_mutations_are_rejected_before_handshake():
    open_room()
    unauthenticated = FakeWS([json.dumps({"action": "move", "move": {"action": "pass"}})])
    run(m.ws_room_player(unauthenticated, "room", "bob"))
    assert "bob" not in m.ROOMS["room"]["sockets"]
    assert unauthenticated.messages()[-1]["message"] == "not authenticated for this seat"


def test_stale_socket_release_cannot_displace_a_reconnect():
    old = open_room()
    token = m.ROOMS["room"]["meta"]["alice"]["token"]
    current = FakeWS()
    assert run(m._handle_reconnect(current, "room", "alice", {"token": token}))
    m._release_socket("room", "alice", old)
    assert m.ROOMS["room"]["sockets"]["alice"] is current
