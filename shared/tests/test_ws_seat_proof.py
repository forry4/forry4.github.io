"""A seat is handed only to a socket that PROVES it owns it — in every game.

Each game's `tests/test_ws_auth.py` pins its own handshake, and three holes sat
underneath all of them until the 2026-11-09 audit, because each was a property
no single game's file thought to ask:

  1. A `reconnect` that sent NO token matched a seat that HAD none. Four games
     compared `stored != sent`, and a bot seat has no meta entry, so that read
     `None != None`: an anonymous socket became the bot — its private view (a
     Dontminion hand, Duel's reserves) and its moves — in every vs-bot room of
     Duel, Dontminion and Castles of Crimson.
  2. A server-issued reconnect token recorded only what its caller ASKED for.
     `POST /me/session-token` minted one for any `player_id`, and `auth_reconnect`
     compared room and seat but never who minted it, so any signed-in account
     could take any seat in the five games that accept those tokens.
  3. A message that was valid JSON but not an OBJECT (`[]`, `1`, `null`) reached
     `msg.get("action")` and dropped the socket with an AttributeError, in all
     twelve dispatchers.

The rosters are DERIVED from the tree, so the thirteenth game is held to all of
it the day it ships. Spender's dispatcher is inline (it has no `_handle_*`
functions), so 1 and 2 for Spender live in its own test_ws_auth.py; 3 is here
for every game, Spender included.
"""
import asyncio
import importlib
import inspect
import json
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms

ROOT = Path(__file__).resolve().parents[2]


def _all_games() -> dict:
    return {main.parent.name: importlib.import_module(f"games.{main.parent.name}.main")
            for main in sorted((ROOT / "games").glob("*/main.py"))}


GAMES = _all_games()
HANDLER_GAMES = {g: m for g, m in GAMES.items()
                 if hasattr(m, "_handle_create") and hasattr(m, "_handle_reconnect")}
TOKEN_GAMES = {g: m for g, m in HANDLER_GAMES.items()
               if hasattr(m, "consume_reconnect_token") and hasattr(m, "_handle_auth_reconnect")}


class _WS:
    def __init__(self, inbox=()):
        self.sent, self._inbox = [], list(inbox)

    async def accept(self):
        pass

    async def close(self, code=1000):
        pass

    async def send_text(self, t):
        self.sent.append(json.loads(t))

    async def receive_text(self):
        if self._inbox:
            return self._inbox.pop(0)
        raise WebSocketDisconnect()

    def types(self):
        return [d.get("type") for d in self.sent]


@pytest.fixture()
def quiet(monkeypatch):
    """No database, no bot scheduling and nobody signed in, for whichever game a
    test drives. The schedulers are found by NAME rather than listed, so a new
    game's is stubbed too."""
    touched = []

    def _quiet(mod):
        touched.append(mod)
        mod.ROOMS.clear()
        _rooms._ws_connect_limiter.reset()
        monkeypatch.setattr(mod, "save_game", lambda *a, **k: None)
        if hasattr(mod, "load_game_to_memory"):
            monkeypatch.setattr(mod, "load_game_to_memory", lambda *a, **k: False)
        monkeypatch.setattr(mod, "get_user_by_session", lambda *a, **k: None)

        async def _anoop(*a, **k):
            return None
        for name, fn in list(vars(mod).items()):
            if name.startswith(("_schedule", "_kick_bots", "_ensure_day_timer")) and callable(fn):
                monkeypatch.setattr(mod, name, _anoop if inspect.iscoroutinefunction(fn)
                                    else (lambda *a, **k: None))
        return mod
    yield _quiet
    for mod in touched:
        mod.ROOMS.clear()


def _vs_bot_room(mod, rid="SEATS", host="human"):
    """A table with every bot seat the game will give one host."""
    async def go():
        made = await mod._handle_create(_WS(), rid, host, {"name": "Host", "vs_ai": True, "num_bots": 1})
        assert made, "create failed"
    asyncio.run(go())
    return mod.ROOMS[rid]


# ── the rosters ──────────────────────────────────────────────────────────────
def test_the_rosters_are_the_whole_tree():
    assert len(GAMES) >= 12, sorted(GAMES)
    assert len(HANDLER_GAMES) >= 11, sorted(HANDLER_GAMES)
    # The games that redeem a core.auth reconnect token. If this set grows, the
    # new game is covered below on its own; if it SHRINKS, a rename hid one.
    assert {"spender_duel", "dontminion", "castles_of_crimson", "wherewolf"} <= set(TOKEN_GAMES)


# ── 1. no token, no seat ─────────────────────────────────────────────────────
@pytest.mark.parametrize("game", sorted(HANDLER_GAMES))
def test_a_reconnect_without_a_token_takes_no_seat(game, quiet):
    mod = quiet(HANDLER_GAMES[game])
    room = _vs_bot_room(mod)
    seats = list(room["players"])
    assert "human" in seats
    if game in {"spender_duel", "dontminion", "castles_of_crimson"}:
        assert len(seats) >= 2, f"{game}: the vs-bot room has no bot seat, so this proves nothing"

    async def go():
        for seat in seats:
            for payload in ({}, {"token": None}, {"token": ""}, {"token": "None"}):
                ws = _WS()
                got = await mod._handle_reconnect(ws, "SEATS", seat, dict(payload))
                assert not got, f"{game}: seat {seat!r} was handed to a reconnect with {payload!r}"
                assert room.get("sockets", {}).get(seat) is not ws, (game, seat, payload)
                assert not ({"reconnected", "joined"} & set(ws.types())), (game, seat, ws.types())
        # The control: the real token still opens its own seat.
        token = room["meta"]["human"]["token"]
        ws = _WS()
        assert await mod._handle_reconnect(ws, "SEATS", "human", {"token": token}), game
        assert room["sockets"]["human"] is ws
    asyncio.run(go())


# ── 2. a reconnect token is only good for the account that minted it ─────────
@pytest.mark.parametrize("game", sorted(TOKEN_GAMES))
def test_a_reconnect_token_minted_by_another_account_takes_no_seat(game, quiet, monkeypatch):
    mod = quiet(TOKEN_GAMES[game])
    room = _vs_bot_room(mod, host="acct-victim")
    live = room["sockets"]["acct-victim"]
    record = {"token": "rt", "room_id": "SEATS", "player_id": "acct-victim", "user_id": "acct-attacker"}

    def consume(token, matches):          # core.auth.consume_reconnect_token's contract
        if token != "rt":
            return None, False
        return dict(record), bool(matches(dict(record)))
    monkeypatch.setattr(mod, "consume_reconnect_token", consume)

    async def go():
        ws = _WS()
        got = await mod._handle_auth_reconnect(ws, "SEATS", "acct-victim", {"token": "rt"})
        assert not got, f"{game}: a token minted by another account took the seat"
        assert room["sockets"]["acct-victim"] is live
        assert "reconnected" not in ws.types()
        # The control: minted by the seat's own account, the same token works.
        record["user_id"] = "acct-victim"
        ws = _WS()
        assert await mod._handle_auth_reconnect(ws, "SEATS", "acct-victim", {"token": "rt"}), game
        assert room["sockets"]["acct-victim"] is ws
    asyncio.run(go())


# ── 3. JSON that is not an object ────────────────────────────────────────────
@pytest.mark.parametrize("game", sorted(GAMES))
def test_a_non_object_message_is_an_error_not_a_dropped_socket(game, quiet):
    mod = quiet(GAMES[game])
    junk = ["[]", "1", "null", '"create"', "true", "[{\"action\": \"create\"}]"]
    ws = _WS(inbox=junk + [json.dumps({"action": "no-such-action"})])
    asyncio.run(mod.ws_room_player(ws, "JUNKRM", "stranger"))      # must not raise
    assert ws.types() == ["error"] * (len(junk) + 1), (game, ws.sent)
    assert "JUNKRM" not in mod.ROOMS or not mod.ROOMS["JUNKRM"].get("players")


@pytest.mark.parametrize("game", sorted(HANDLER_GAMES))
def test_a_non_object_move_is_refused_not_raised(game, quiet):
    """`msg.get("move") or {}` covered a missing move; a truthy non-object one went
    to the engine, whose first act is `move.get(...)`."""
    mod = quiet(HANDLER_GAMES[game])
    _vs_bot_room(mod)
    token = mod.ROOMS["SEATS"]["meta"]["human"]["token"]
    ws = _WS(inbox=[json.dumps({"action": "reconnect", "token": token}),
                    json.dumps({"action": "move", "move": [1, 2]}),
                    json.dumps({"action": "move", "move": "x"}),
                    json.dumps({"action": "move", "move": 7})])
    asyncio.run(mod.ws_room_player(ws, "SEATS", "human"))          # must not raise
