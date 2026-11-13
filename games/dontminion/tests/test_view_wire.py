"""Wire-redaction tests: capture EVERY payload each socket ever receives and
assert the hidden-information matrix over all of them — no deck arrays, hands
only to their owner, discard as top+count, the pending frame's constraint only
to the actor (and its data to nobody), reconnect_tokens only the viewer's own,
rng_state/seed absent, and the game-over reveal."""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.dontminion import engine
from games.dontminion import main as m

A, B, C = "alice", "bob", "carol"


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def rooms_seen(self):
        return [json.loads(t)["room"] for t in self.sent
                if json.loads(t).get("room")]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    _rooms._ws_connect_limiter.reset()
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)
    monkeypatch.setattr(m, "_kick_bots", lambda room_id: None)
    yield
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _three_player_room(rid="WIRE"):
    sockets = {A: _FakeWS(), B: _FakeWS(), C: _FakeWS()}
    _run(m._handle_create(sockets[A], rid, A, {"name": "Alice"}))
    _run(m._handle_join(sockets[B], rid, B, {"name": "Bob"}))
    _run(m._handle_join(sockets[C], rid, C, {"name": "Carol"}))
    _run(m._handle_start(sockets[A], rid, A))
    return sockets


def _assert_room_redacted(room_payload, viewer):
    game = room_payload.get("game")
    toks = room_payload.get("reconnect_tokens", {})
    assert set(toks) <= {viewer}, "reconnect token leaked to another seat"
    if not game:
        return
    assert "rng_state" not in game and "seed" not in game
    assert "undo_stack" not in game, "the undo snapshots (every hidden zone!) on the wire"
    assert "pending" not in game, "raw pending stack (frame data!) on the wire"
    pv = game.get("pending_view")
    if pv is not None:
        assert "data" not in pv
        if game.get("pending_pid") == viewer:
            assert "constraint" in pv
        else:
            assert "constraint" not in pv and pv.get("waiting_on") == game["pending_pid"]
    over = game.get("over")
    for pid, seat in game.get("seats", {}).items():
        if over:
            continue
        assert "deck" not in seat, "deck order on the wire"
        assert "discard" not in seat and "aside" not in seat
        assert isinstance(seat.get("discard_view"), dict)
        assert set(seat["discard_view"]) == {"top", "count"}
        if pid != viewer:
            assert "hand" not in seat, f"{pid}'s hand leaked to {viewer}"
        else:
            assert isinstance(seat.get("hand"), list)


def test_wire_redaction_through_a_militia_pending():
    sockets = _three_player_room()
    room = m.ROOMS["WIRE"]
    game = room["game"]
    turn = game["turn"]
    others = [p for p in game["players"] if p != turn]
    game["phase"] = "action"
    game["actions"] = 1
    game["seats"][turn]["hand"] = ["Militia", "Copper"]
    for o in others:
        game["seats"][o]["hand"] = ["Copper", "Silver", "Gold", "Estate", "Duchy"]
    _run(m._handle_move(sockets[turn], "WIRE", turn,
                        {"move": {"type": "play_action", "card": "Militia"}}))
    assert game["pending_pid"] == others[0]
    # the pending opponent answers over the wire path too
    hand2 = game["seats"][others[0]]["hand"][:2]
    _run(m._handle_move(sockets[others[0]], "WIRE", others[0],
                        {"move": {"type": "decision", "cards": hand2}}))
    # every payload every socket ever received is redacted for ITS viewer
    for viewer, ws in sockets.items():
        seen = ws.rooms_seen()
        assert seen, f"{viewer} never received a state frame"
        for payload in seen:
            _assert_room_redacted(payload, viewer)
    # the actor saw a constraint at least once; a non-actor saw waiting_on
    actor_frames = [p["game"]["pending_view"] for p in sockets[others[0]].rooms_seen()
                    if p.get("game") and p["game"].get("pending_view")
                    and "constraint" in p["game"]["pending_view"]]
    assert actor_frames and actor_frames[-1]["kind"] == "choose_cards"
    waiting = [p["game"]["pending_view"] for p in sockets[turn].rooms_seen()
               if p.get("game") and p["game"].get("pending_view")
               and "waiting_on" in p["game"]["pending_view"]]
    assert waiting


def test_game_over_reveals_everything():
    sockets = _three_player_room("WIRE2")
    room = m.ROOMS["WIRE2"]
    room["game"]["over"] = True
    room["game"]["scores"] = engine.score_game(room["game"])
    room["game"]["winners"] = [A]
    _run(m.broadcast_state("WIRE2"))
    for viewer, ws in sockets.items():
        last = ws.rooms_seen()[-1]
        for pid, seat in last["game"]["seats"].items():
            assert "hand" in seat and "deck" in seat and "discard" in seat


def test_the_public_landscape_tavern_and_token_state_reaches_every_socket():
    """ph. 6H's three new public keys, asserted against the payloads a REAL
    room actually sent rather than a synthetic dict — the nested-snapshot
    lesson, in the other direction. Landscapes lie face up on the table, Tavern
    mats are face UP (unlike the Native Village mat), and tokens are public
    markers, so "it's public" has to be a thing the wire demonstrably does, not
    an assumption about what deepcopy happened to carry."""
    sockets = _three_player_room("WIRE4")
    game = m.ROOMS["WIRE4"]["game"]
    game["landscapes"]["Errand"] = {"kind": "event", "bought_turn": None,
                                    "bought_by": [A]}
    game["seats"][B]["tavern"] = ["Village"]
    game["seats"][C]["tokens"] = {"-card": True}
    engine.move_token(game, A, "-cost", "Copper")
    # ph. 7H: Debt (per player) and the VP / Debt a landmark puts on a pile.
    # Same argument — Debt sits in front of you where everyone can count it,
    # and everyone must, since it is why that player is not buying anything.
    engine.add_debt(game, B, 4)
    engine.add_pile_vp(game, "Gold", 8)
    engine.add_pile_debt(game, "Silver", 1)
    _run(m.broadcast_state("WIRE4"))
    for viewer, ws in sockets.items():
        last = ws.rooms_seen()[-1]["game"]
        _assert_room_redacted(ws.rooms_seen()[-1], viewer)
        assert last["landscapes"]["Errand"]["bought_by"] == [A]
        assert last["seats"][B]["tavern"] == ["Village"]
        assert last["seats"][C]["tokens"] == {"-card": True}
        assert last["piles"]["Copper"]["attach"]["tokens"] == {A: ["-cost"]}
        assert last["debt"] == {A: 0, B: 4, C: 0}
        assert last["piles"]["Gold"]["attach"]["vp"] == 8
        assert last["piles"]["Silver"]["attach"]["debt"] == 1


def test_spectator_view_is_fully_redacted():
    _three_player_room("WIRE3")
    payload = m.mk_room_state("WIRE3", viewer_pid=None)
    _assert_room_redacted(payload, viewer=None)
    for seat in payload["game"]["seats"].values():
        assert "hand" not in seat


# --- effective prices ride the wire (the client must not re-derive them) -----

def test_player_view_ships_effective_costs_incl_peddler_and_quarry():
    """USER-REPORTED: Peddler showed its printed $8 in the UI because the
    client priced piles itself with only the Bridge discount — so a discounted
    Peddler never lit up and the click handler refused to send the buy.
    player_view now ships engine.cost for every supply pile."""
    g = engine.new_game([A, B], ["base", "prosperity"], seed=11,
                        kingdom=["Peddler", "Quarry", "Village", "Smithy", "Market",
                                 "Militia", "Moat", "Bandit", "Monument", "Bishop"])
    view = engine.player_view(g, A)
    assert view["costs"]["Peddler"] == 8            # action phase: no discount
    assert view["costs"]["Village"] == 3
    assert set(view["costs"]) == set(g["supply"])   # every pile priced

    # three Actions on the table during the buy phase -> Peddler costs $8-$6
    g["phase"] = "buy"
    g["seats"][A]["in_play"] = ["Village", "Smithy", "Market"]
    view = engine.player_view(g, A)
    assert engine.cost(g, "Peddler") == 2
    assert view["costs"]["Peddler"] == 2, "the discount must reach the wire"
    # opponents price it the same way (it is keyed to the ACTIVE player)
    assert engine.player_view(g, B)["costs"]["Peddler"] == 2
    assert engine.player_view(g, None)["costs"]["Peddler"] == 2

    # Quarry's turn-scoped discount also shows: Actions cost $2 less
    g["turn_ctx"]["quarries"] = 1
    view = engine.player_view(g, A)
    assert view["costs"]["Village"] == 1            # 3 - 2
    assert view["costs"]["Smithy"] == 2             # 4 - 2
    assert view["costs"]["Estate"] == 2             # not an Action: unchanged
    assert view["costs"]["Peddler"] == 0            # 8 - 6 - 2, floored at 0

    # and a Bridge stacks on top, still floored at 0
    g["turn_ctx"]["bridges"] = 2
    view = engine.player_view(g, A)
    assert view["costs"]["Village"] == 0
    assert view["costs"]["Province"] == 6           # 8 - 2
