"""WebSocket seat identity, and the one leak that would end this game.

`player` is a client-supplied path segment and every pid is broadcast in the
public players map, so a socket must PROVE it owns a seat before it can act as
that seat OR RECEIVE THAT SEAT'S VIEW. In SecretNames the seat's view is its KEY
CARD — the whole secret — so the usual binding tests are joined here by a
payload check on every path that sends a room.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocketDisconnect
import pytest

from core import rooms as _rooms
from games.secretnames import engine as E
from games.secretnames import main as m


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
    # The WS connect throttle is per-PROCESS and every fake socket reports
    # "unknown", so a module driving `ws_room_player` shares one budget with the
    # rest of the suite unless it resets.
    m._rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(_rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)


def run(coro):
    return asyncio.run(coro)


def _table(room="r1"):
    """A started two-seat table: alice creates, bob joins, the game deals."""
    run(m._handle_create(FakeWS(), room, "alice", {"name": "Alice"}))
    run(m._handle_join(FakeWS(), room, "bob", {"name": "Bob"}))
    return m.ROOMS[m.normalize_room(room)]


# ── Identity binding ─────────────────────────────────────────────────────────
def test_creating_binds_the_creator_and_opens_a_table_for_one():
    ws = FakeWS()
    assert run(m._handle_create(ws, "abc123", "alice", {"name": "Alice"})) is True
    room = m.ROOMS["ABC123"]
    assert room["players"] == {"alice": "Alice"}
    assert room["status"] == "open" and room["game"] is None
    assert ws.sent[-1]["type"] == "created"


def test_the_second_seat_starts_the_game_by_itself():
    room = _table()
    assert set(room["players"]) == {"alice", "bob"}
    assert room["status"] == "playing"
    assert room["game"]["phase"] == "clue"


def test_a_third_socket_cannot_take_a_seat_at_a_two_player_table():
    _table()
    ws = FakeWS()
    assert run(m._handle_join(ws, "r1", "carol", {"name": "Carol"})) is False
    assert ws.sent[-1]["message"] == "this table is full"


def test_an_impostor_cannot_claim_an_existing_seat_by_joining():
    _table()
    stranger = FakeWS()
    assert run(m._handle_join(stranger, "r1", "bob", {"name": "Mallory"})) is False
    assert stranger.sent == [{"type": "error",
                              "message": "seat already taken — reconnect to rejoin"}]
    # ...and nothing about bob's key went out with the refusal.
    assert "room" not in stranger.sent[0]


def test_an_unauthenticated_socket_can_neither_move_nor_be_registered():
    _table()
    ws = FakeWS([json.dumps({"action": "move", "move": {"type": "guess", "pos": 0}})])
    run(m.ws_room_player(ws, "r1", "alice"))
    assert ws.sent[-1]["message"] == "not authenticated for this seat"
    # The seat already HAS a registered socket from the create handshake, so the
    # question is whether this one displaced it — a socket registered before its
    # own handshake would start receiving that seat's key card.
    assert ws not in m.ROOMS["R1"]["sockets"].values(), \
        "a socket was registered before the handshake — it would receive the seat's key"


def test_merely_connecting_as_a_victim_returns_nothing_at_all():
    """The Spender bug, checked directly: open a socket claiming a live seat,
    send nothing, disconnect. It must receive no room payload and must not
    displace the victim's socket."""
    room = _table()
    live = FakeWS()
    room["sockets"]["bob"] = live
    attacker = FakeWS()
    run(m.ws_room_player(attacker, "r1", "bob"))
    assert attacker.sent == []
    assert m.ROOMS["R1"]["sockets"]["bob"] is live


def test_a_reconnect_token_is_scoped_to_the_seat_that_owns_it():
    _table()
    token = m.ROOMS["R1"]["meta"]["alice"]["token"]
    bad = FakeWS()
    assert run(m._handle_reconnect(bad, "r1", "bob", {"token": token})) is False
    assert bad.sent[-1]["type"] == "error"
    good = FakeWS()
    assert run(m._handle_reconnect(good, "r1", "alice", {"token": token})) is True


def test_a_room_payload_only_ever_carries_the_recipients_own_token():
    _table()
    payload = m.mk_room_state("R1", "alice")
    assert set(payload["reconnect_tokens"]) == {"alice"}
    assert m.ROOMS["R1"]["meta"]["bob"]["token"] not in json.dumps(payload)


def test_auth_reconnect_needs_a_session_that_matches_the_claimed_seat(monkeypatch):
    _table()
    monkeypatch.setattr(m, "get_user_by_session", lambda t: {"id": "alice"} if t == "S" else None)
    wrong = FakeWS()
    assert run(m._handle_auth_reconnect(wrong, "r1", "bob", {"session_token": "S"})) is False
    right = FakeWS()
    assert run(m._handle_auth_reconnect(right, "r1", "alice", {"session_token": "S"})) is True


# ── The key card never crosses the wire to the wrong seat ────────────────────
def _other_side(room, pid):
    seat = room["game"]["seats"].index(pid)
    return room["game"]["keys"][1 - seat]


def test_a_serialized_room_update_never_contains_the_other_seats_key():
    room = _table()
    for pid in ("alice", "bob"):
        payload = m.mk_room_state("R1", pid)
        seat = room["game"]["seats"].index(pid)
        assert payload["game"]["key"] == room["game"]["keys"][seat]
        blob = json.dumps(payload)
        # The engine's own list must not appear under any name...
        assert '"keys"' not in blob
        # ...and neither must its CONTENT, which is the check that survives a
        # future field being added with a different name.
        assert json.dumps(_other_side(room, pid)) not in blob


def test_the_broadcast_is_rebuilt_per_recipient():
    """One shared payload would hand both key cards to both players, and the
    game would look completely normal from either seat."""
    room = _table()
    a, b = FakeWS(), FakeWS()
    room["sockets"] = {"alice": a, "bob": b}
    run(m.broadcast_state("R1"))
    ka = a.sent[-1]["room"]["game"]["key"]
    kb = b.sent[-1]["room"]["game"]["key"]
    assert ka == room["game"]["keys"][room["game"]["seats"].index("alice")]
    assert kb == room["game"]["keys"][room["game"]["seats"].index("bob")]
    assert ka != kb


def test_the_reveal_only_appears_once_the_game_is_over():
    room = _table()
    assert m.mk_room_state("R1", "alice")["game"]["reveal"] is None
    E.abandon(room["game"], "alice")
    revealed = m.mk_room_state("R1", "alice")["game"]["reveal"]
    assert revealed == [room["game"]["keys"][0], room["game"]["keys"][1]]


# ── Moves go through the engine, and only the engine ─────────────────────────
def test_the_server_resolves_a_guess_and_ignores_any_result_the_client_claims():
    room = _table()
    game = room["game"]
    giver = game["seats"][game["clue_giver"]]
    guess_pid = game["seats"][E.guesser(game)]
    run(m._handle_move(FakeWS(), "r1", giver, {"move": {"type": "clue", "word": "SIGNAL", "number": 2}}))
    # A position that is a bystander from the resolving side, sent with a lie.
    seat = game["seats"].index(guess_pid)
    pos = next(i for i in range(25) if game["keys"][1 - seat][i] == E.BYSTANDER)
    run(m._handle_move(FakeWS(), "r1", guess_pid,
                       {"move": {"type": "guess", "pos": pos, "result": "agent"}}))
    assert pos not in game["found"], "the client's claimed result was believed"
    assert pos in game["bystanders"][seat]


def test_an_illegal_move_is_reported_to_that_socket_and_changes_nothing():
    room = _table()
    game = room["game"]
    wrong = game["seats"][E.guesser(game)]      # the guesser cannot give a clue
    ws = FakeWS()
    before = json.dumps(game, sort_keys=True)
    run(m._handle_move(ws, "r1", wrong, {"move": {"type": "clue", "word": "X", "number": 1}}))
    assert ws.sent[-1]["type"] == "error"
    assert json.dumps(game, sort_keys=True) == before


def test_abandoning_ends_the_room_and_marks_it_over():
    room = _table()
    run(m._handle_abandon("r1", "alice"))
    assert room["status"] == "over"
    assert room["game"]["phase"] == "lost"
    assert room["game"]["loss_reason"] == "abandoned"


def test_a_dropped_socket_does_not_evict_the_live_one_for_the_same_seat():
    """The stale-socket guard: WS1 disconnecting while WS2 is already live must
    not remove WS2 or delete a room that is being played."""
    room = _table()
    first, second = FakeWS(), FakeWS()
    room["sockets"]["alice"] = first
    room["sockets"]["alice"] = second
    m._release_socket("R1", "alice", first)
    assert m.ROOMS["R1"]["sockets"]["alice"] is second


def test_an_unknown_action_is_refused_without_authenticating_anything():
    ws = FakeWS([json.dumps({"action": "sudo"})])
    run(m.ws_room_player(ws, "r1", "alice"))
    assert ws.sent[-1] == {"type": "error", "message": "unknown action"}
    assert "R1" not in m.ROOMS


def test_a_created_table_persists_its_chosen_turn_count():
    run(m._handle_create(FakeWS(), "r9", "alice", {"name": "Alice", "turns": 11}))
    run(m._handle_join(FakeWS(), "r9", "bob", {"name": "Bob"}))
    assert m.ROOMS["R9"]["game"]["turns_max"] == 11


def test_a_bogus_turn_count_falls_back_to_the_standard_game():
    run(m._handle_create(FakeWS(), "r8", "alice", {"name": "Alice", "turns": 99}))
    assert m.ROOMS["R8"]["turns"] == E.DEFAULT_TURNS
