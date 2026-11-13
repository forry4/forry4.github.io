"""End-to-end 4-human-player flow through the WS handlers (no real socket, no DB):
create a VS-Friend room, three joins, start, then play a full game to completion —
turns cycle through all four seats and a single winner results."""
import asyncio
import random

from games.castles_of_crimson import engine
from games.castles_of_crimson import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(t)


def test_four_human_players_full_game(monkeypatch):
    rid = "MP4TEST"
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)
    pids = ["h1", "h2", "h3", "h4"]

    async def run():
        ws = {p: _FakeWS() for p in pids}
        await m._handle_create(ws["h1"], rid, "h1", {"name": "H1", "vs_ai": False, "board_id": "1"})
        for p in pids[1:]:
            await m._handle_join(ws[p], rid, p, {"name": p.upper(), "board_id": "1"})
        room = m.ROOMS[rid]
        assert [x for x in room["players"] if x != m.AI_PID] == pids
        assert room.get("vs_ai") is False

        # a 5th join is rejected (room full at MAX_PLAYERS)
        ws5 = _FakeWS()
        await m._handle_join(ws5, rid, "h5", {"name": "H5", "board_id": "1"})
        assert any('"error"' in s and "full" in s for s in ws5.sent)
        assert "h5" not in room["players"]

        await m._handle_start(ws["h1"], rid, "h1")
        g = room["game"]
        assert g["num_players"] == 4 and len(g["order"]) == 4

        rng = random.Random(4)
        movers = set()
        for _ in range(8000):
            g = room["game"]
            if engine.is_over(g):
                break
            mover = g["pending_pid"] or g["turn"]
            movers.add(mover)
            moves = engine.legal_moves(g, mover)
            assert moves, (mover, g["phase"])
            await m._handle_move(ws[mover], rid, mover, {"move": rng.choice(moves)})
        g = room["game"]
        assert engine.is_over(g)
        assert g["winner"] in pids
        assert movers == set(pids)                 # every seat took turns

    asyncio.run(run())


def test_host_chosen_max_players_caps_joins(monkeypatch):
    rid = "CAP3"
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)

    async def run():
        h = _FakeWS()
        await m._handle_create(h, rid, "h1", {"name": "H1", "vs_ai": False, "board_id": "1", "max_players": 3})
        assert m.ROOMS[rid]["max_players"] == 3
        for p in ("h2", "h3"):
            await m._handle_join(_FakeWS(), rid, p, {"name": p, "board_id": "1"})
        assert len(m.ROOMS[rid]["players"]) == 3
        # 4th join is rejected — room capped at the chosen 3
        ws4 = _FakeWS()
        await m._handle_join(ws4, rid, "h4", {"name": "H4", "board_id": "1"})
        assert any('"error"' in s and "full" in s for s in ws4.sent)
        assert "h4" not in m.ROOMS[rid]["players"]
    asyncio.run(run())


def test_missing_max_players_defaults_to_four(monkeypatch):
    rid = "DEF4"
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)

    async def run():
        await m._handle_create(_FakeWS(), rid, "h1", {"name": "H1", "vs_ai": False, "board_id": "1"})
        assert m.ROOMS[rid]["max_players"] == m.MAX_PLAYERS  # permissive default for older clients
    asyncio.run(run())


def test_same_board_forces_everyone_onto_host_board(monkeypatch):
    rid = "SAMEBRD"
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)

    async def run():
        # host on board 3, same_board on; joiners pick different boards
        await m._handle_create(_FakeWS(), rid, "h1", {"name": "H1", "vs_ai": False, "board_id": "3", "same_board": True})
        assert m.ROOMS[rid]["same_board"] is True
        await m._handle_join(_FakeWS(), rid, "h2", {"name": "H2", "board_id": "5"})
        await m._handle_join(_FakeWS(), rid, "h3", {"name": "H3", "board_id": "7"})
        await m._handle_start(_FakeWS(), rid, "h1")
        g = m.ROOMS[rid]["game"]
        boards = {pid: g["players"][pid]["board_id"] for pid in g["order"]}
        assert set(boards.values()) == {"3"}, boards        # everyone on the host's board

        # control: same_board OFF keeps each player's own pick
        rid2 = "OWNBRD"
        m.ROOMS.pop(rid2, None)
        await m._handle_create(_FakeWS(), rid2, "a", {"name": "A", "vs_ai": False, "board_id": "3", "same_board": False})
        await m._handle_join(_FakeWS(), rid2, "b", {"name": "B", "board_id": "5"})
        await m._handle_start(_FakeWS(), rid2, "a")
        g2 = m.ROOMS[rid2]["game"]
        assert g2["players"]["a"]["board_id"] == "3" and g2["players"]["b"]["board_id"] == "5"
    asyncio.run(run())


def test_cannot_join_a_vs_ai_room(monkeypatch):
    rid = "VSAIJOIN"
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "_read_room", lambda room_id: None)

    async def run():
        host = _FakeWS()
        await m._handle_create(host, rid, "p1", {"name": "P1", "vs_ai": True,
                                                 "ai_difficulty": "hard", "board_id": "1", "opp_board_id": "1"})
        joiner = _FakeWS()
        await m._handle_join(joiner, rid, "p2", {"name": "P2", "board_id": "1"})
        assert any('"error"' in s for s in joiner.sent)
        assert "p2" not in m.ROOMS[rid]["players"]

    asyncio.run(run())
