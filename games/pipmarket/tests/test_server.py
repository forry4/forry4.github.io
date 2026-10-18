"""Room lifecycle for Pip Market: seats, bots, start, moves, lobby lists."""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as shared_rooms
from games.pipmarket import engine
from games.pipmarket import main as m


class FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(text)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def last(self):
        return json.loads(self.sent[-1])


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    shared_rooms._ws_connect_limiter = shared_rooms.SlidingWindowLimiter(
        shared_rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)
    monkeypatch.setattr(m, "BOT_THINK", 0)
    # The handlers fire the bot scheduler as a background task; the tests drive it
    # explicitly instead, so a run never races a task left on a closed loop.
    monkeypatch.setattr(m.asyncio, "create_task", lambda coro: coro.close())
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_a_table_filled_by_bots_deals_at_once():
    ws = FakeWS()
    assert run(m._handle_create(ws, "full", "alice", {"name": "Alice", "max_players": 4, "num_bots": 3}))
    room = m.ROOMS["full"]
    assert room["status"] == "playing"
    assert len(room["game"]["players"]) == 4
    assert room["ai_players"] == ["pm-bot-1", "pm-bot-2", "pm-bot-3"]
    assert ws.last()["room"]["game"]["phase"] == "auction"


def test_a_table_with_open_seats_waits_then_the_host_starts_it():
    host = FakeWS()
    run(m._handle_create(host, "mixed", "alice", {"name": "Alice", "max_players": 4, "num_bots": 1}))
    room = m.ROOMS["mixed"]
    assert room["status"] == "open" and room["game"] is None
    friend = FakeWS()
    assert run(m._handle_join(friend, "mixed", "bob", {"name": "Bob"}))
    assert run(m._handle_join(FakeWS(), "mixed", "cara", {"name": "Cara"}))
    assert not run(m._handle_join(FakeWS(), "mixed", "dave", {"name": "Dave"}))   # 4 seats taken
    outsider = FakeWS()
    run(m._handle_start(outsider, "mixed", "bob"))
    assert json.loads(outsider.sent[-1])["message"] == "only the host can start"
    run(m._handle_start(host, "mixed", "alice"))
    assert room["status"] == "playing"
    assert set(room["game"]["players"]) == set(room["players"])


def test_bots_play_until_a_human_must_act():
    ws = FakeWS()
    run(m._handle_create(ws, "vsbot", "alice", {"name": "Alice", "max_players": 2, "num_bots": 1}))
    room = m.ROOMS["vsbot"]
    run(m._schedule_bots("vsbot"))
    assert engine.to_act(room["game"]) == "alice" or engine.is_over(room["game"])


def test_a_whole_game_against_bots_through_the_server():
    ws = FakeWS()
    run(m._handle_create(ws, "long", "alice", {"name": "Alice", "max_players": 3, "num_bots": 2}))
    room = m.ROOMS["long"]
    room["sockets"]["alice"] = ws
    from games.pipmarket import bot
    for _ in range(600):
        run(m._schedule_bots("long"))
        game = room["game"]
        if engine.is_over(game):
            break
        assert engine.to_act(game) == "alice"
        move = bot.choose_move(game, "alice", 1)
        run(m._handle_move(ws, "long", "alice", {"move": move}))
    assert engine.is_over(room["game"])
    assert room["status"] == "over"


def test_illegal_moves_are_refused_with_a_reason():
    ws = FakeWS()
    run(m._handle_create(ws, "r", "alice", {"name": "Alice", "max_players": 2, "num_bots": 1}))
    run(m._schedule_bots("r"))
    run(m._handle_move(ws, "r", "alice", {"move": {"type": "score", "cells": [[0, 0]]}}))
    assert ws.last()["type"] == "error"


def test_room_state_ships_the_view_not_the_seed():
    ws = FakeWS()
    run(m._handle_create(ws, "v", "alice", {"name": "Alice", "max_players": 2, "num_bots": 1}))
    state = m.mk_room_state("v", "alice")
    assert "seed" not in state["game"]
    assert state["max_players"] == 2


def test_create_coerces_bad_options():
    ws = FakeWS()
    run(m._handle_create(ws, "c", "alice", {"name": "A", "max_players": 9, "num_bots": 7,
                                            "ai_difficulty": "godlike"}))
    room = m.ROOMS["c"]
    assert room["max_players"] == 4 and len(room["ai_players"]) == 3
    assert room["ai_difficulty"] == m.DEFAULT_DIFFICULTY


def test_lists_round_trip_through_sqlite(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "pm.db"

    def conn():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(m, "_db", conn)
    m._init_db()
    m._save_conn = None
    state = {"players": {"alice": "Alice", "pm-bot-1": "Bot"}, "host": "alice",
             "status": "over", "meta": {}, "max_players": 2, "ai_players": ["pm-bot-1"],
             "ai_difficulty": "normal"}
    game = engine.new_game(["alice", "pm-bot-1"], seed=3)
    game["points"] = {"alice": 30, "pm-bot-1": 10}
    engine._finish(game)
    state["game"] = game
    m._persist_row("HIST", "over", [("alice", "Alice"), ("pm-bot-1", "Bot"), (None, None), (None, None)],
                   2, "alice", m._encode_state(state), 100)
    rows = m.list_user_history("alice")
    assert rows[0]["outcome"] == "won"
    assert rows[0]["ai_difficulty"] == "normal"
    assert rows[0]["standings"][0]["you"] is True
    open_state = dict(state, status="open", game=None)
    m._persist_row("OPEN", "open", [("alice", "Alice"), ("pm-bot-1", "Bot"), (None, None), (None, None)],
                   3, "alice", m._encode_state(dict(open_state, max_players=3)), 101)
    opened = m.list_open_games()
    assert opened[0]["id"] == "OPEN" and opened[0]["player_count"] == 2 and opened[0]["max_players"] == 3
    m._save_conn = None
