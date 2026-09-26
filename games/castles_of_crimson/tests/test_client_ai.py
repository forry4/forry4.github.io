"""Expert-tier client-AI protocol (main.py): ai_search shipping, ai_move apply,
stale-move dropping, and the watchdog fallback.

Drives the WS handlers directly (no real websocket); the simulated client answers
each shipped decision through the SAME compact bridge the browser wasm uses
(bridge.move_to_compact -> ai_move), so a protocol/bridge drift fails here before
it can reach prod. DB access is stubbed out — these tests never touch users.db.
"""
import asyncio
import random

from games.castles_of_crimson import engine
from games.castles_of_crimson import main as m
from games.castles_of_crimson.az import bridge as az_bridge


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(t)


def _isolate(monkeypatch, rid):
    """No DB reads/writes; fast pacing; a clean room slate."""
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_to_memory", lambda room_id: False)
    monkeypatch.setattr(m, "_BOT_MOVE_DELAY", 0.001)
    monkeypatch.setattr(m, "_PHASE_END_PAUSE", 0.001)
    monkeypatch.setattr(m, "_POST_TURN_PAUSE", 0.001)
    monkeypatch.setattr(m, "_MIN_BOT_THINK", 0.0)


async def _create_expert(rid, pid):
    ws = _FakeWS()
    await m._handle_create(ws, rid, pid, {
        "name": "H", "vs_ai": True, "ai_difficulty": "expert",
        "board_id": "1", "opp_board_id": "1",
    })
    await m._handle_client_ai_ready(ws, rid, pid, {})
    return ws


def test_expert_client_plays_full_game(monkeypatch):
    """Every bot decision is answered like the wasm client; the game finishes."""
    rid, pid = "CLAI01", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = await _create_expert(rid, pid)
        room = m.ROOMS[rid]
        assert room["ai_difficulty"] == "expert"
        assert room["client_ai"] is True
        rng = random.Random(11)
        answered = 0
        # A DEADLINE, not an iteration count: a count's real budget depends on the
        # sleep's granularity (15ms on Windows vs ~1ms on Linux) and on how fast the
        # machine runs the bot, so the same count was patient here and short on a
        # loaded CI runner (the 2026-08-07 deploy block). It only pays when broken.
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.002)
            g = room.get("game")
            if g is None or engine.is_over(g):
                break
            pend = room.get("_ai_search")
            if pend is not None:
                assert pend["mode"] == m._EXPERT_MODE
                assert pend["seat"] == g["order"].index(room["ai_player"])
                # the shipped projection must not reveal the true draw order
                assert pend["state"]["supply"] == sorted(pend["state"]["supply"])
                legal = engine.legal_moves(g, room["ai_player"])
                mv = rng.choice(legal)
                compact = az_bridge.move_to_compact(g, room["ai_player"], mv)
                await m._handle_ai_move(ws, rid, pid, {
                    "decision": pend["decision"], "move": compact,
                })
                answered += 1
                continue
            actor = g.get("pending_pid") or g.get("turn")
            if actor == pid and not room.get("_bot_running"):
                await m._handle_move(ws, rid, pid,
                                     {"move": rng.choice(engine.legal_moves(g, pid))})
        g = room["game"]
        assert engine.is_over(g), "game did not finish through the client path"
        assert answered > 20, f"client path barely exercised ({answered})"
        # a stale/garbage ai_move after the fact is ignored quietly (no exception)
        await m._handle_ai_move(ws, rid, pid, {"decision": 999999, "move": {"t": "end"}})

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_expert_watchdog_falls_back_to_server(monkeypatch):
    """The client never answers: after CLIENT_AI_TIMEOUT the server finishes the
    bot's turn itself (here via the trivial-bot finisher) — no deadlock."""
    rid, pid = "CLAI02", "human1"
    _isolate(monkeypatch, rid)
    monkeypatch.setattr(m, "CLIENT_AI_TIMEOUT", 0.05)
    # empty plan -> the finisher (trivial bot) completes the turn, so the test
    # exercises the timeout->server wiring without paying for real MCTS
    monkeypatch.setattr(m.coc_ai, "play_turn_plan",
                        lambda *a, **k: [])

    async def run():
        await _create_expert(rid, pid)
        room = m.ROOMS[rid]
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
            g = room.get("game")
            if g is None:
                continue
            actor = g.get("pending_pid") or g.get("turn")
            if actor == pid and not room.get("_bot_running"):
                break
        g = room["game"]
        actor = g.get("pending_pid") or g.get("turn")
        assert actor == pid, "bot turn never ended after client silence"
        assert room.get("_ai_search") is None, "stale decision left armed"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_illegal_client_move_is_dropped(monkeypatch):
    """An illegal/garbage ai_move is logged and dropped — never applied, never an
    error to the user; the decision stays armed for the watchdog."""
    rid, pid = "CLAI03", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = await _create_expert(rid, pid)
        room = m.ROOMS[rid]
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.002)
            if room.get("_ai_search") is not None:
                break
            g = room.get("game")
            actor = g and (g.get("pending_pid") or g.get("turn"))
            if actor == pid and not room.get("_bot_running"):
                await m._handle_move(ws, rid, pid, {
                    "move": random.Random(3).choice(engine.legal_moves(g, pid))})
        pend = room.get("_ai_search")
        assert pend is not None, "no decision was ever shipped"
        g = room["game"]
        before = len(g["log"]) if "log" in g else None
        await m._handle_ai_move(ws, rid, pid, {
            "decision": pend["decision"], "move": {"t": "bogus"},
        })
        assert room.get("_ai_search") is not None, "illegal move consumed the decision"
        if before is not None:
            assert len(g["log"]) == before, "illegal move mutated the game"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)
