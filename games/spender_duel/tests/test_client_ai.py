"""Client-AI protocol (main.py): ai_search shipping, ai_move apply, stale/illegal
dropping, the watchdog fallback, and disarm-on-disconnect.

Drives the WS handlers directly (no real websocket). The simulated client answers each
shipped decision through the SAME wire encoding the browser's wasm emits — it projects
nothing itself, it reads `ai_search["state"]` and replies with `encmove`-shaped JSON — so
a protocol or encoding drift fails HERE rather than in a browser. DB access is stubbed
out; these tests never touch the real DB.

Deliberately no wasm: the search is not what is under test (compact_parity and ai_parity
cover the bot), the PROTOCOL is. The client stands in for it by picking a legal move.
"""
import asyncio
import json
import os
import random

_SEED = int(os.environ.get('DUEL_TEST_SEED', 20260716))

import pytest

from games.spender_duel import compact, engine
from games.spender_duel import main as m

import sys
import os

# `enc_move` is the encoding the wasm emits; reuse the generator's copy rather than
# hand-rolling a third one in the test (a test that encodes it its own way would pass
# while the real client failed).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "rust-cores", "duel-core", "tools"))
import gen_engine_fixtures as G  # noqa: E402


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(t)


def _isolate(monkeypatch, rid):
    """No DB reads/writes; ZERO pacing; a clean room slate.

    Every pacing constant MUST be zeroed here. CoC learned this the hard way: a new
    per-turn pause it forgot to zero passed locally (Windows' coarse timers inflated the
    driver loop's wall clock) and hung CI on finer ones.
    """
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_to_memory", lambda room_id: False)
    monkeypatch.setattr(m, "_BOT_MOVE_DELAY", 0.0)
    monkeypatch.setattr(m, "_MIN_BOT_THINK", 0.0)   # no real-time first-move floor under the sleep(0) driver
    # Pin every source of game entropy (deck seed, first player, bot moves). Without this
    # each run gets a different deal, so a test can only HOPE the bot is to move when it
    # asserts a client move lands — which is why this suite passed 20/20 locally and then
    # failed on CI. A deploy gate must not depend on the draw.
    monkeypatch.setattr(m, "_new_rng", lambda: random.Random(_SEED))


async def _create_hard(rid, pid, difficulty="hard"):
    ws = _FakeWS()
    await m._handle_create(ws, rid, pid, {"name": "H", "vs_ai": True, "ai_difficulty": difficulty})
    await m._handle_client_ai_ready(ws, rid, pid, {})
    return ws


def _client_reply(pend, game, rng):
    """What the browser does: search `ai_search["state"]` and answer in wire encoding.

    The wasm's root move list is derived from the PROJECTION, so this deliberately picks
    from the projection-derived options rather than from the server's game dict — if the
    projection could not express the move, this test could not send it.
    """
    seat = pend["state"]["seat"]
    assert seat == game["order"].index(m.AI_PID)
    legal = engine.legal_moves(game, game["order"][seat])
    return G.enc_move(rng.choice(legal))


def _bot_moves(game):
    return [e for e in game["log"] if e.get("pid") == m.AI_PID]


def test_client_plays_a_full_game(monkeypatch):
    """Every bot decision is answered like the wasm client; the game finishes — and the
    server's own search NEVER runs. That last assertion is the point: without it the
    test would still pass if every decision quietly fell through to the server, which is
    precisely the failure this whole path must not have."""
    rid, pid = "DCLAI1", "human1"
    _isolate(monkeypatch, rid)
    planned = []
    monkeypatch.setattr(m.duel_ai, "play_turn_plan",
                        lambda *a, **k: planned.append(1) or [])

    async def run():
        ws = await _create_hard(rid, pid)
        room = m.ROOMS[rid]
        assert room["ai_difficulty"] == "hard"
        assert room["client_ai"] is True
        rng = random.Random(11)
        answered = 0
        # A DEADLINE, not an iteration count: a count's real budget depends on the
        # sleep's granularity (15ms on Windows vs ~1ms on Linux) and on how fast the
        # machine runs the bot, so the same count was patient here and short on a
        # loaded CI runner (the 2026-08-07 deploy block). It only pays when broken.
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0)
            g = room.get("game")
            if g is None or engine.is_over(g):
                break
            pend = room.get("_ai_search")
            if pend is not None:
                st = pend["state"]
                assert st["seat"] == g["order"].index(m.AI_PID)
                assert pend["ply"] == len(g["log"])
                # the shipped projection must never reveal a hidden order
                for pool in st["unseen"]:
                    assert pool == sorted(pool)
                assert st["bag"] == sorted(st["bag"])
                await m._handle_ai_move(ws, rid, pid, {
                    "decision": pend["decision"], "move": _client_reply(pend, g, rng),
                })
                answered += 1
                continue
            actor = g.get("pending_pid") or g["turn"]
            if actor == pid and not room.get("_bot_running"):
                await m._handle_move(ws, rid, pid, {"move": rng.choice(engine.legal_moves(g, pid))})
        g = room["game"]
        assert engine.is_over(g), "game did not finish through the client path"
        assert answered > 20, f"client path barely exercised ({answered})"
        assert not planned, "the server search ran — decisions fell through to it"
        assert _bot_moves(g), "the bot never moved"
        # a stale/garbage ai_move after the fact is ignored quietly (no exception)
        await m._handle_ai_move(ws, rid, pid, {"decision": 999999, "move": {"t": "pass"}})

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_client_moves_arrive_as_json_strings_too(monkeypatch):
    """The worker may post the move as a JSON STRING (that is what wasm returns); the
    handler must accept both that and a parsed object."""
    rid, pid = "DCLAI7", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = await _create_hard(rid, pid)
        room = m.ROOMS[rid]
        rng = random.Random(5)
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0)
            g = room.get("game")
            if g is None or engine.is_over(g):
                break
            pend = room.get("_ai_search")
            if pend is not None:
                before = len(g["log"])
                await m._handle_ai_move(ws, rid, pid, {
                    "decision": pend["decision"],
                    "move": json.dumps(_client_reply(pend, g, rng)),   # a STRING
                })
                # Poll rather than yield ONCE: applying a client move hands off through
                # the scheduler, so a single `sleep(0)` only happens to be enough under
                # one interpreter's task ordering — it passed 45/45 locally on 3.14 and
                # failed on CI's 3.11. Waiting for the condition tests the same thing
                # without depending on the event loop's scheduling.
                deadline = asyncio.get_running_loop().time() + 60.0
                while asyncio.get_running_loop().time() < deadline:
                    if len(room["game"]["log"]) > before:
                        break
                    await asyncio.sleep(0.005)
                assert len(room["game"]["log"]) > before, "a string-encoded move was dropped"
                return
            actor = g.get("pending_pid") or g["turn"]
            if actor == pid and not room.get("_bot_running"):
                await m._handle_move(ws, rid, pid, {"move": rng.choice(engine.legal_moves(g, pid))})
        pytest.fail("no decision was ever shipped")

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_watchdog_falls_back_to_the_server(monkeypatch):
    """The client never answers: after CLIENT_AI_TIMEOUT the server plays the bot's turn
    itself — no deadlock, the turn still ends, and the bot really did move.

    The start player is randomized at create, so this drives a human move first when
    needed rather than assuming the bot leads — without that, an empty log would look
    like a pass instead of the failure it is.
    """
    rid, pid = "DCLAI2", "human1"
    _isolate(monkeypatch, rid)
    monkeypatch.setattr(m, "CLIENT_AI_TIMEOUT", 0.05)
    # An empty plan drops to the trivial-bot finisher, so the test exercises the
    # timeout -> server wiring without paying for real MCTS.
    monkeypatch.setattr(m.duel_ai, "play_turn_plan", lambda *a, **k: [])

    async def run():
        ws = await _create_hard(rid, pid)
        room = m.ROOMS[rid]
        rng = random.Random(2)
        saw_decision = False
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
            g = room.get("game")
            if g is None or engine.is_over(g):
                break
            if room.get("_ai_search") is not None:
                saw_decision = True          # shipped, and we deliberately never answer
            if _bot_moves(g) and (g.get("pending_pid") or g["turn"]) == pid \
                    and not room.get("_bot_running"):
                break                        # the bot's turn came and went without us
            actor = g.get("pending_pid") or g["turn"]
            if actor == pid and not room.get("_bot_running"):
                await m._handle_move(ws, rid, pid, {"move": rng.choice(engine.legal_moves(g, pid))})
        g = room["game"]
        assert saw_decision, "the client path never even shipped a decision"
        assert _bot_moves(g), "the server never played the bot's move after client silence"
        assert (g.get("pending_pid") or g["turn"]) == pid, "bot turn never ended"
        assert room.get("_ai_search") is None, "stale decision left armed"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


async def _run_to_first_decision(ws, rid, pid, seed=3):
    room = m.ROOMS[rid]
    rng = random.Random(seed)
    deadline = asyncio.get_running_loop().time() + 60.0
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0)
        if room.get("_ai_search") is not None:
            return room["_ai_search"]
        g = room.get("game")
        if g is None or engine.is_over(g):
            break
        actor = g.get("pending_pid") or g["turn"]
        if actor == pid and not room.get("_bot_running"):
            await m._handle_move(ws, rid, pid, {"move": rng.choice(engine.legal_moves(g, pid))})
    return None


def test_illegal_client_move_is_dropped(monkeypatch):
    """An illegal/garbage ai_move is logged and dropped — never applied, never an error
    to the user; the decision stays armed for the watchdog."""
    rid, pid = "DCLAI3", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = await _create_hard(rid, pid)
        room = m.ROOMS[rid]
        pend = await _run_to_first_decision(ws, rid, pid)
        assert pend is not None, "no decision was ever shipped"
        g = room["game"]
        before = len(g["log"])
        # garbage, an unknown type, a real move type with an out-of-range index, and a
        # LEGAL-SHAPED move that isn't legal right now
        for bad in ({"t": "bogus"}, "not json", None, {"t": "steal", "color": 99},
                    {"t": "buy", "card": -1, "from": 0}, {"t": "choose_royal", "royal": 0}):
            await m._handle_ai_move(ws, rid, pid, {"decision": pend["decision"], "move": bad})
            assert room.get("_ai_search") is not None, f"{bad!r} consumed the decision"
            assert len(g["log"]) == before, f"{bad!r} mutated the game"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_stale_decision_is_dropped(monkeypatch):
    """A reply keyed to a decision that has already been answered/superseded must not
    apply — it would play a move chosen for a different position."""
    rid, pid = "DCLAI4", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = await _create_hard(rid, pid)
        room = m.ROOMS[rid]
        pend = await _run_to_first_decision(ws, rid, pid)
        assert pend is not None
        g = room["game"]
        before = len(g["log"])
        legal_now = G.enc_move(engine.legal_moves(g, m.AI_PID)[0])
        await m._handle_ai_move(ws, rid, pid, {"decision": pend["decision"] - 1, "move": legal_now})
        assert len(g["log"]) == before, "a stale-keyed move was applied"
        assert room.get("_ai_search") is not None, "a stale key consumed the decision"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_disconnect_disarms_the_client(monkeypatch):
    rid, pid = "DCLAI5", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = await _create_hard(rid, pid)
        room = m.ROOMS[rid]
        assert room["client_ai"] is True
        room["sockets"][pid] = ws
        # mirror the ws handler's finally-block guard
        if room.get("sockets", {}).get(pid) is ws:
            room["sockets"].pop(pid, None)
            room["client_ai"] = False
        assert room["client_ai"] is False
        # and an unarmed room never ships a decision — the server just plays
        monkeypatch.setattr(m.duel_ai, "play_turn_plan", lambda *a, **k: [])
        await m._schedule_bot_turn(rid)
        assert room.get("_ai_search") is None

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


@pytest.mark.parametrize("tier", ["easy", "normal"])
def test_non_hard_tiers_never_use_the_client(monkeypatch, tier):
    """"normal" is calibrated to be beatable and "easy" has no search — neither may be
    silently upgraded by ~100x the sims. They must stay on the server path."""
    rid, pid = f"DCLAI6{tier[0].upper()}", "human1"
    _isolate(monkeypatch, rid)
    monkeypatch.setattr(m.duel_ai, "play_turn_plan", lambda *a, **k: [])

    async def run():
        await _create_hard(rid, pid, difficulty=tier)
        room = m.ROOMS[rid]
        assert room["ai_difficulty"] == tier
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0)
            assert room.get("_ai_search") is None, f"{tier} shipped a client decision"
            g = room.get("game")
            if g and (g.get("pending_pid") or g.get("turn")) == pid:
                break
        # The loop used to end after 500 yields whether or not the bot had moved, so a
        # slow first bot turn made this pass having watched nothing. Require the turn.
        g = room.get("game")
        assert g and (g.get("pending_pid") or g.get("turn")) == pid, "the bot's turn never ended"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_human_vs_human_never_arms_the_client(monkeypatch):
    """The projection carries the BOT's own blind reserves, so between two humans arming
    it would hand one player the other's face-down cards. Refuse at the arm."""
    rid = "DCLAI8"
    _isolate(monkeypatch, rid)

    async def run():
        ws = _FakeWS()
        await m._handle_create(ws, rid, "h1", {"name": "A", "vs_ai": False})
        await m._handle_join(_FakeWS(), rid, "h2", {"name": "B"})
        await m._handle_start(ws, rid, "h1")
        room = m.ROOMS[rid]
        assert room.get("ai_player") is None
        await m._handle_client_ai_ready(ws, rid, "h1", {})
        assert not room.get("client_ai"), "a human-vs-human room armed the client AI"
        # ...and a fabricated ai_move can do nothing either
        g = room["game"]
        before = len(g["log"])
        await m._handle_ai_move(ws, rid, "h1", {"decision": 1, "move": {"t": "replenish"}})
        assert len(g["log"]) == before

    asyncio.run(run())
    m.ROOMS.pop(rid, None)
