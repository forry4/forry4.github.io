"""The room server: creating, joining, moving, and the bot playing along.

Drives the handlers directly with fake sockets so nothing touches a real DB.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.rag_tag import engine as E
from games.rag_tag import main as m
from games.rag_tag.fighters import ROSTER


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
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_read_room", lambda rid: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _two_player_room():
    run(m._handle_create(_FakeWS(), "r1", "alice", {"name": "Alice"}))
    run(m._handle_join(_FakeWS(), "r1", "bob", {"name": "Bob"}))
    return m.ROOMS["r1"]


# ------------------------------------------------------------------ lifecycle

def test_a_human_room_starts_only_when_the_host_says_so():
    room = _two_player_room()
    assert room["game"] is None

    ws = _FakeWS()
    run(m._handle_start(ws, "r1", "bob"))
    assert room["game"] is None, "only the host can start"

    run(m._handle_start(_FakeWS(), "r1", "alice"))
    assert room["game"] is not None
    assert room["status"] == "playing"
    assert room["game"]["phase"] == "draft"


def test_a_vs_bot_room_deals_immediately_and_seats_the_bot():
    ws = _FakeWS()
    run(m._handle_create(ws, "r1", "alice", {"name": "Alice", "vs_ai": True}))
    room = m.ROOMS["r1"]
    assert room["ai_player"] == m.AI_PID
    assert set(room["players"]) == {"alice", m.AI_PID}
    assert room["game"]["phase"] == "draft"


def test_a_move_out_of_turn_is_refused_not_applied():
    room = _two_player_room()
    run(m._handle_start(_FakeWS(), "r1", "alice"))
    game = room["game"]
    seat = E.seat_of(game, "alice")
    pick = game["draft_hands"][seat][0]

    ws = _FakeWS()
    run(m._handle_move(ws, "r1", "alice", {"move": {"kind": "draft", "fighter": pick}}))
    assert ws.types() == []          # accepted: a draft pick broadcasts, not replies

    again = _FakeWS()
    run(m._handle_move(again, "r1", "alice",
                       {"move": {"kind": "draft", "fighter": pick}}))
    assert again.msgs()[-1]["type"] == "error", "you only pick once a round"


def test_an_illegal_move_is_reported_and_changes_nothing():
    room = _two_player_room()
    run(m._handle_start(_FakeWS(), "r1", "alice"))
    before = json.dumps(room["game"], sort_keys=True)
    ws = _FakeWS()
    run(m._handle_move(ws, "r1", "alice",
                       {"move": {"kind": "draft", "fighter": "not_a_fighter"}}))
    assert ws.msgs()[-1]["type"] == "error"
    assert json.dumps(room["game"], sort_keys=True) == before


def test_abandoning_hands_the_fight_to_the_other_side():
    room = _two_player_room()
    run(m._handle_start(_FakeWS(), "r1", "alice"))
    run(m._handle_abandon(_FakeWS(), "r1", "alice"))
    assert room["game"]["winner"] == E.other_seat(E.seat_of(room["game"], "alice"))
    assert room["status"] == "over"


# ----------------------------------------------------------------- broadcast

def test_every_socket_gets_its_own_redacted_copy():
    room = _two_player_room()
    run(m._handle_start(_FakeWS(), "r1", "alice"))
    a, b = _FakeWS(), _FakeWS()
    room["sockets"] = {"alice": a, "bob": b}
    run(m.broadcast_state("r1"))

    seen = {}
    for pid, ws in (("alice", a), ("bob", b)):
        payload = ws.msgs()[-1]["room"]["game"]
        seen[pid] = payload["draft_hand"]
        assert payload["draft_hand"] == room["game"]["draft_hands"][
            E.seat_of(room["game"], pid)]
    assert seen["alice"] != seen["bob"], "two seats, two different views"


# ----------------------------------------------------------------------- bot

def test_the_bot_plays_a_whole_game_by_itself():
    """Both seats are bots, so the scheduler drives the game to the end.

    That is a real integration check rather than a bot check: it exercises the
    lock discipline, `_position_key` re-validation and `advance` together.
    """
    run(m._handle_create(_FakeWS(), "r1", "alice", {"name": "A", "vs_ai": True}))
    room = m.ROOMS["r1"]
    game = room["game"]

    # Drive the human seat with the same random bot, through the real handler.
    for _ in range(4000):
        if E.is_over(game):
            break
        run(m._schedule_bot_turn("r1"))
        if E.is_over(game):
            break
        seat = E.seat_of(game, "alice")
        if E.owes_move(game, seat):
            from games.rag_tag import bot
            move = bot.choose_move(game, seat, seed=seat + game["turn"] * 7 + game["round"])
            run(m._handle_move(_FakeWS(), "r1", "alice", {"move": move}))
        else:
            E.advance(game)
    assert E.is_over(game), "the game never finished"
    assert room["status"] == "over"


def test_the_bot_never_gets_to_skip_the_engine():
    """Its move goes through `apply_move` like anyone else's."""
    from games.rag_tag import bot

    game = E.new_game(["bot", "human"], seed=5)
    move = bot.choose_move(game, 0, seed=1)
    assert move in E.legal_moves(game, 0) or move["kind"] == "build"
    with pytest.raises(E.IllegalMove):
        E.apply_move(game, "bot", {"kind": "draft", "fighter": "nope"})


def test_the_position_key_notices_the_other_player_submitting():
    """A phase-and-round key would call a simultaneous submission 'unchanged'.

    That is the whole hazard of a simultaneous game: the human can move WHILE the
    bot is thinking without any phase advancing, and a stale bot move would then
    be applied against a position that had already moved on.
    """
    game = E.new_game(["alice", "bob"], seed=8)
    before = m._position_key(game)
    E.draft_pick(game, "alice", game["draft_hands"][0][0])
    assert m._position_key(game) != before


# ------------------------------------------------------------------- catalog

def test_the_catalog_ships_the_whole_roster_and_every_card():
    from games.rag_tag.fighters import CARDS

    payload = run(m.catalog())
    assert set(payload["roster"]) == set(ROSTER)
    assert set(payload["fighters"]) == set(ROSTER)
    assert len(payload["cards"]) == len(CARDS)
    joan = payload["fighters"]["joan"]
    assert joan["base_power"] == 1 and joan["hp_track"], "boards ship with their tracks"


def test_the_catalog_ships_the_board_rules_the_tracks_do_not_draw():
    """The detail modal writes its own sentences, so it needs the fields to write from.

    Each of these was on the board and not on the wire, so the modal could not say
    it: the Wild Bunch's setup icon (their partner starts a Power up), the Golem's
    shield token, the health Maman Brijit comes back on, and Bödvar's note about
    what the Bear arrives with. A missing field is not an error here — the modal
    simply renders one fewer line and reads like a complete description.
    """
    payload = run(m.catalog())
    assert payload["fighters"]["the_wild_bunch"]["setup_icons"]
    assert payload["fighters"]["golem"]["absorbs_attack"] == ["presence"]
    assert payload["fighters"]["maman_brijit"]["revive_to_hp"] == 4
    assert payload["fighters"]["bodvar"]["note"], "Bödvar's transformation note"
    assert payload["fighters"]["joan"]["note"] is None, "a board with nothing extra to say"


def test_the_catalog_ships_the_fighter_profile():
    """The modal's whole top half — epithet, paragraph, five bars — is catalog data."""
    fighters = run(m.catalog())["fighters"]
    joan = fighters["joan"]
    assert joan["title"] == "The Divine Shield"
    assert joan["profile"] and joan["rating"]["health"] == 4
    assert all(f.get("rating") for f in fighters.values()), "a board with no ratings"
    assert all(f.get("guide") for f in fighters.values()), "a board with no guide entry"


def test_an_instant_bonus_ships_as_its_ops_not_as_a_flag():
    """It was `bool(...)`, so the modal could flag the card and not say what it paid."""
    from games.rag_tag.fighters import CARDS

    cid = next(c for c, card in CARDS.items() if card.get("instant_bonus"))
    shipped = run(m.catalog())["cards"][str(cid)]["instant_bonus"]
    assert isinstance(shipped, list) and shipped == CARDS[cid]["instant_bonus"]
