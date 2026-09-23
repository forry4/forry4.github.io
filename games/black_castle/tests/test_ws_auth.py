from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.black_castle import main as m


class FakeWS:
    def __init__(self, inbox=None):
        self.sent = []
        self.inbox = list(inbox or [])

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def receive_text(self):
        if self.inbox:
            return self.inbox.pop(0)
        raise WebSocketDisconnect()

    async def accept(self):
        pass


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    m._rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(_rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)


def run(coro):
    return asyncio.run(coro)


def test_create_supports_two_easy_bots_and_binds_creator():
    ws = FakeWS()
    assert run(m._handle_create(ws, "abc123", "alice", {"name": "Alice", "max_players": 3, "num_bots": 2}))
    assert set(m.ROOMS["ABC123"]["players"]) == {"alice", "bot1", "bot2"}
    assert m.ROOMS["ABC123"]["status"] == "playing"
    # FIRST, not last: `created` is sent before the bot task exists, which is the
    # guarantee a client relies on. What arrives after it depends on how far that
    # fire-and-forget task gets before asyncio.run() tears the loop down — on 3.11
    # it never starts, on 3.14.7 it plays a move and broadcasts it first.
    assert ws.sent[0]["type"] == "created"


def test_unauthed_socket_cannot_move_or_claim_an_existing_seat():
    run(m._handle_create(FakeWS(), "r1", "alice", {"name": "Alice", "max_players": 2}))
    run(m._handle_join(FakeWS(), "r1", "bob", {"name": "Bob"}))
    stranger = FakeWS()
    assert run(m._handle_join(stranger, "r1", "bob", {"name": "Mallory"})) is False
    assert stranger.sent == [{"type": "error", "message": "seat already taken — reconnect to rejoin"}]
    ws = FakeWS([json.dumps({"action": "move", "move": {"type": "take_die", "bridge": "coral", "side": "left"}})])
    run(m.ws_room_player(ws, "r1", "alice"))
    assert ws.sent[-1]["message"] == "not authenticated for this seat"


def test_reconnect_token_is_scoped_to_the_claimed_seat():
    run(m._handle_create(FakeWS(), "r1", "alice", {"name": "Alice", "max_players": 2}))
    token = m.ROOMS["R1"]["meta"]["alice"]["token"]
    bad = FakeWS()
    assert run(m._handle_reconnect(bad, "r1", "bob", {"token": token})) is False
    assert bad.sent[-1]["type"] == "error"
    good = FakeWS()
    assert run(m._handle_reconnect(good, "r1", "alice", {"token": token})) is True


def test_serialized_room_update_redacts_private_decks_and_rng():
    run(m._handle_create(FakeWS(), "r1", "alice", {"name": "Alice", "max_players": 2, "num_bots": 1}))
    payload = json.dumps(m.mk_room_state("R1", "alice"))
    assert "steward_deck" not in payload
    assert "diplomat_deck" not in payload
    assert "garden_deck" not in payload
    assert "yard_deck" not in payload
    assert "rng_state" not in payload
    assert "turn_undo" not in payload
