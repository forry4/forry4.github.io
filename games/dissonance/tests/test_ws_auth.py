"""WebSocket identity binding (main.py).

The ``player`` path segment is client-supplied and every pid in a room is
broadcast in the public players map, so anyone who can see a game could open a
socket claiming the OPPONENT's pid. Dissonance redacts state PER RECIPIENT, so an
unproven socket would be handed that seat's own hand — and could submit moves
on its turn, since ``_handle_move`` only checks whose turn it is.

These pin the rule that a socket must PROVE ownership of its pid before it can
act as that seat or receive that seat's view. Mirrors the four games that ship
the same binding.

Drives the handlers directly with a fake websocket; DB access is stubbed so
these never touch a real users.db.
"""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.dissonance import main as m


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
    # The WS connect throttle is a per-process sliding window keyed on client
    # IP, and every fake socket reports "unknown" — so without this reset the
    # suite eventually throttles itself and the failures look like anything but
    # a rate limit.
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_read_room", lambda rid: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_room(host="alice", other=None, game=True):
    room = {
        "players": {host: "Alice"},
        "sockets": {},
        "status": "open",
        "host": host,
        "game": None,
        "meta": {host: {"token": "tok-alice"}},
        "vs_ai": False,
        "ai_player": None,
        "ai_difficulty": "normal",
    }
    if other:
        room["players"][other] = "Bob"
        room["meta"][other] = {"token": "tok-bob"}
        if game:
            from games.dissonance import engine as E
            import random
            room["game"] = E.new_game([host, other], random.Random(1))
            room["status"] = "playing"
    m.ROOMS["r1"] = room
    return room


# --- the core attack -------------------------------------------------------


def test_an_unproven_socket_claiming_a_seat_is_refused_and_gets_no_view():
    _make_room("alice", "bob")
    ws = _FakeWS()
    ok = run(m._handle_join(ws, "r1", "bob", {"name": "Mallory"}))
    assert ok is False
    assert "joined" not in ws.types(), "a refused join must not ship the seat's view"
    blob = "".join(ws.sent)
    assert "hand" not in blob


def test_a_refused_socket_does_not_displace_the_live_one():
    room = _make_room("alice", "bob")
    live = _FakeWS()
    room["sockets"]["bob"] = live
    run(m._handle_join(_FakeWS(), "r1", "bob", {"name": "Mallory"}))
    assert room["sockets"]["bob"] is live


def test_the_ws_loop_refuses_privileged_actions_before_a_handshake():
    _make_room("alice", "bob")
    for action in ("start", "move", "abandon"):
        ws = _FakeWS(inbox=[json.dumps({"action": action, "move": {"kind": "pass"}})])
        run(m.ws_room_player(ws, "r1", "bob"))
        msgs = ws.msgs()
        assert msgs and msgs[0]["type"] == "error"
        assert "not authenticated" in msgs[0]["message"], action


def test_an_unproven_socket_is_never_registered_in_the_room():
    """Registering before the handshake is what leaked a seat's view in
    Spender: broadcast_room rebuilds state PER RECIPIENT keyed on the socket's
    pid, so merely opening a socket and sending nothing was enough."""
    room = _make_room("alice", "bob")
    ws = _FakeWS(inbox=[json.dumps({"action": "move", "move": {"kind": "pass"}})])
    run(m.ws_room_player(ws, "r1", "bob"))
    assert room["sockets"].get("bob") is not ws


# --- the legitimate routes in ---------------------------------------------


def test_create_authenticates_the_creator():
    ws = _FakeWS()
    ok = run(m._handle_create(ws, "r1", "alice", {"name": "Alice"}))
    assert ok is True
    assert ws.types() == ["created"]


def test_joining_a_brand_new_seat_authenticates():
    _make_room("alice")
    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "bob", {"name": "Bob"})) is True
    assert "joined" in ws.types()


def test_rejoining_your_own_seat_with_a_matching_session_authenticates(monkeypatch):
    _make_room("alice", "bob")
    monkeypatch.setattr(m, "get_user_by_session",
                        lambda t: {"id": "bob"} if t == "good" else None)
    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "bob", {"session_token": "good"})) is True
    assert "joined" in ws.types()


def test_a_session_for_a_different_account_does_not_open_the_seat(monkeypatch):
    _make_room("alice", "bob")
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: {"id": "carol"})
    ws = _FakeWS()
    assert run(m._handle_join(ws, "r1", "bob", {"session_token": "carols"})) is False


def test_reconnect_requires_the_matching_room_token():
    _make_room("alice", "bob")
    bad = _FakeWS()
    assert run(m._handle_reconnect(bad, "r1", "bob", {"token": "wrong"})) is False
    assert "joined" not in bad.types()
    good = _FakeWS()
    assert run(m._handle_reconnect(good, "r1", "bob", {"token": "tok-bob"})) is True


def test_auth_reconnect_requires_a_session_matching_the_pid(monkeypatch):
    _make_room("alice", "bob")
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: {"id": "carol"})
    assert run(m._handle_auth_reconnect(_FakeWS(), "r1", "bob", {"session_token": "x"})) is False
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: {"id": "bob"})
    assert run(m._handle_auth_reconnect(_FakeWS(), "r1", "bob", {"session_token": "x"})) is True


# --- redaction on the wire -------------------------------------------------


def test_a_broadcast_never_carries_the_opponents_hand_or_the_hidden_piles():
    """Asserted against the whole SERIALIZED payload of a real in-progress
    game, not a synthetic dict — a nested copy is exactly how CoC's redaction
    was correct at the top level and still leaking."""
    from games.dissonance import engine as E
    room = _make_room("alice", "bob")
    g = room["game"]
    E.apply_bid(g, 0, 3, 1)
    E.apply_pass(g, 1)
    E.apply_swap(g, 0, g["shown"][0], sorted(g["hands"][0])[0])
    E.apply_double(g, 1, True)      # doubled: the wire must redact it the same
    for _ in range(6):
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[0])

    for me, opp in (("alice", "bob"), ("bob", "alice")):
        payload = json.dumps(m.mk_room_state("r1", viewer_pid=me))
        seat = E.seat_of(g, me)
        oseat = 1 - seat

        secret = set(g["hands"][oseat]) | set(g["out"])
        for owner in range(2):
            for j, pile in enumerate(g["piles"][owner]):
                if len(pile) == 2 and j != 1:
                    secret.add(pile[0])   # side-pile bottoms, ours included

        view = json.loads(payload)["game"]
        assert view["opp_hand_n"] == len(g["hands"][oseat])
        assert "hands" not in view, "raw hands must never be on the wire"
        assert view["out"] is None, "the out-of-play cards are secret until the end"
        # The shown out-cards are the DECLARER's private knowledge; the wire
        # payload to the defender must not carry them.
        if seat == g["auction"]["declarer"]:
            assert view["shown"] == g["shown"]
        else:
            assert view["shown"] is None
        for owner in range(2):
            for j, pv in enumerate(view["piles"][owner]):
                real = g["piles"][owner][j]
                assert pv["under"] == (real[0] if (len(real) == 2 and j == 1) else None)
        # And the recipient's own hand IS present — redaction must not be so
        # broad that the game becomes unplayable.
        assert sorted(view["hand"]) == sorted(g["hands"][seat])
        _ = secret


def test_reconnect_tokens_are_scoped_to_the_recipient():
    _make_room("alice", "bob")
    st = m.mk_room_state("r1", viewer_pid="alice")
    assert set(st["reconnect_tokens"]) == {"alice"}
    assert "bob" not in json.dumps(st["reconnect_tokens"])
