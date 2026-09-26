"""Server-layer tests for Spender Duel main.py: room lifecycle, per-recipient
redaction on the wire, the bot scheduler finishing games, and reconnects.

Drives the WS handlers directly (no real websocket), DB stubbed out — never
touches users.db (the CoC test_client_ai.py pattern).
"""
import asyncio
import json
import random

from games.spender_duel import engine
from games.spender_duel import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(t)

    def last(self, mtype=None):
        for raw in reversed(self.sent):
            msg = json.loads(raw)
            if mtype is None or msg.get("type") == mtype:
                return msg
        return None


def _isolate(monkeypatch, rid):
    """No DB reads/writes; fast pacing; a clean room slate.

    Any NEW pacing constant must be zeroed here too — the CoC lesson: a real
    per-move sleep left in a test loop overflows the driver on CI's fine timers
    while passing locally on Windows' coarse ones.
    """
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_state", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_to_memory", lambda room_id: False)
    monkeypatch.setattr(m, "_BOT_MOVE_DELAY", 0.001)
    monkeypatch.setattr(m, "_MIN_BOT_THINK", 0.0)   # skip the real-time first-move floor in tests
    # Pin the BOT's rng. Without this the bot's moves come off real entropy, so a test
    # can only hope it exercises the path under assertion — the flake that made this
    # suite fail ~1/14 on nothing but luck. Deploy gates must not be coin flips.
    monkeypatch.setattr(m, "_new_rng", lambda: random.Random(20260716))


def test_vs_ai_full_game_and_wire_redaction(monkeypatch):
    """A whole vs-bot game through the WS handlers. Uses the "easy" tier: this
    test is about the room/redaction/scheduler wiring, not search strength, and
    the MCTS tiers would spend seconds per decision on CI."""
    rid, pid = "DUEL01", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = _FakeWS()
        await m._handle_create(ws, rid, pid, {"name": "H", "vs_ai": True, "ai_difficulty": "easy"})
        created = ws.last("created")
        assert created and created["room"]["status"] == "playing"
        g_wire = created["room"]["game"]
        # the wire never carries hidden info
        assert "bag" not in g_wire and "decks" not in g_wire and "rng_state" not in g_wire
        assert isinstance(g_wire["bag_count"], int) and set(g_wire["deck_counts"]) == {"1", "2", "3"}

        room = m.ROOMS[rid]
        rng = random.Random(3)
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
            actor = g.get("pending_pid") or g.get("turn")
            if actor == pid and not room.get("_bot_running"):
                mv = rng.choice(engine.legal_moves(g, pid))
                await m._handle_move(ws, rid, pid, {"move": mv})
        g = room["game"]
        assert engine.is_over(g), "game did not finish"
        assert g["winner"] in (pid, m.AI_PID)
        # Every room_update sent to the human redacted the bot's BLIND reserves pre-over.
        # Face-up (pyramid) reserves are deliberately NOT redacted: the human watched that
        # card leave the pyramid and its id is already in the broadcast log, so hiding it
        # on the wire would be theatre. Blind deck draws stay hidden until game over.
        blind_seen = faceup_seen = 0
        for raw in ws.sent:
            msg = json.loads(raw)
            gm = (msg.get("room") or {}).get("game")
            if not gm or gm.get("phase") == "over":
                continue
            for opid, p in gm["players"].items():
                if opid == pid:
                    continue
                for x in p["reserved"]:
                    if isinstance(x, dict):
                        assert set(x) == {"level", "facedown"}, "blind reserve leaks its id"
                        blind_seen += 1
                    else:
                        assert isinstance(x, str)          # a public, already-logged id
                        faceup_seen += 1
            assert "bag" not in gm and "decks" not in gm
            # the blind-source list is card IDS — it must never reach any client
            for p in gm["players"].values():
                assert "reserved_from_deck" not in p
        assert blind_seen or faceup_seen, "the game never exercised a bot reserve"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_join_capped_at_two_and_reconnect(monkeypatch):
    rid = "DUEL02"
    _isolate(monkeypatch, rid)

    async def run():
        ws1, ws2, ws3 = _FakeWS(), _FakeWS(), _FakeWS()
        await m._handle_create(ws1, rid, "p1", {"name": "One", "vs_ai": False})
        await m._handle_join(ws2, rid, "p2", {"name": "Two"})
        assert ws2.last("joined")
        await m._handle_join(ws3, rid, "p3", {"name": "Three"})
        assert ws3.last("error")["message"] == "room is full"

        await m._handle_start(ws1, rid, "p1")
        room = m.ROOMS[rid]
        assert room["status"] == "playing"
        g = room["game"]
        assert set(g["order"]) == {"p1", "p2"}
        # each socket got ITS OWN redacted view + only its own reconnect token
        for pid, ws in (("p1", ws1), ("p2", ws2)):
            upd = ws.last("room_update")
            toks = upd["room"]["reconnect_tokens"]
            assert set(toks) <= {pid}
        # reconnect with the room token
        tok = room["meta"]["p2"]["token"]
        ws2b = _FakeWS()
        await m._handle_reconnect(ws2b, rid, "p2", {"token": tok})
        assert ws2b.last("reconnected")
        ws2c = _FakeWS()
        await m._handle_reconnect(ws2c, rid, "p2", {"token": "WRONG"})
        assert ws2c.last("error")["message"] == "invalid token"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_mcts_tier_plans_and_applies(monkeypatch):
    """The MCTS tier drives real turns through the scheduler (tiny budget so this
    stays a wiring test, not a strength test), and the search runs OFF the event
    loop — never under ROOM_LOCK."""
    rid, pid = "DUEL04", "human1"
    _isolate(monkeypatch, rid)
    monkeypatch.setitem(m.duel_ai.DIFFICULTY, "hard",
                        {"time_limit": 0.05, "max_iters": 12, "temperature": 0.0,
                         "rollout_steps": 2})

    async def run():
        ws = _FakeWS()
        await m._handle_create(ws, rid, pid, {"name": "H", "vs_ai": True, "ai_difficulty": "hard"})
        room = m.ROOMS[rid]
        assert room["ai_difficulty"] == "hard"
        rng = random.Random(5)
        # Wait on CONDITIONS, never an iteration count: this used to be a fixed
        # 400 x 5ms loop, and on a slow CI runner the budget ran out with the
        # bot mid-search — so the `_bot_running is False` assert below read a
        # race, not a property, and blocked a deploy (2026-08-07). The deadline
        # only pays when something is actually broken.
        deadline = asyncio.get_running_loop().time() + 60.0
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
            g = room.get("game")
            if g is None or engine.is_over(g):
                break
            actor = g.get("pending_pid") or g.get("turn")
            if actor == pid and not room.get("_bot_running"):
                await m._handle_move(ws, rid, pid, {"move": rng.choice(engine.legal_moves(g, pid))})
        g = room["game"]
        assert engine.is_over(g), "the game did not finish before the deadline"
        # the bot actually took turns via the planner (not just the finisher)
        assert sum(1 for e in g["log"] if e["pid"] == m.AI_PID) > 3
        # the scheduler may still be unwinding its final (no-op) turn when the
        # game ends under it — give it the same deadline to clear the flag
        while room.get("_bot_running") and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
        assert room.get("_bot_running") is False

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_bogus_difficulty_falls_back_to_default(monkeypatch):
    rid = "DUEL05"
    _isolate(monkeypatch, rid)

    async def run():
        await m._handle_create(_FakeWS(), rid, "p1",
                               {"name": "One", "vs_ai": True, "ai_difficulty": "TOTALLY-BOGUS"})
        assert m.ROOMS[rid]["ai_difficulty"] == m.DEFAULT_DIFFICULTY

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_difficulty_survives_a_reload(monkeypatch):
    """A vs-bot room reloaded from the DB (e.g. after a redeploy wipes ROOMS) keeps
    its tier — the Spender `ai_variant` bug was exactly this silently defaulting."""
    rid = "DUEL06"
    m.ROOMS.pop(rid, None)
    game = engine.new_game(["p1", m.AI_PID], seed=1)
    state = {"players": {"p1": "One", m.AI_PID: "Bot"}, "host": "p1", "status": "playing",
             "game": game, "meta": {}, "vs_ai": True, "ai_player": m.AI_PID,
             "ai_difficulty": "normal"}
    monkeypatch.setattr(m, "load_game_state", lambda room_id: state)
    assert m.load_game_to_memory(rid)
    assert m.ROOMS[rid]["ai_difficulty"] == "normal"
    # a legacy row with no tier recorded loads as the default, not as None
    state.pop("ai_difficulty")
    m.ROOMS.pop(rid)
    assert m.load_game_to_memory(rid)
    assert m.ROOMS[rid]["ai_difficulty"] == m.DEFAULT_DIFFICULTY
    m.ROOMS.pop(rid, None)


def test_review_endpoint_gates_and_ships_snapshots(monkeypatch):
    """/review: participants only, finished games only, and it carries the
    turn-by-turn snapshots the rewind UI needs."""
    import asyncio as _a
    from games.spender_duel import bot as _bot
    rid = "DUEL07"
    m.ROOMS.pop(rid, None)
    g = engine.new_game(["p1", "p2"], names={"p1": "One", "p2": "Two"}, seed=3)
    rng = random.Random(3)
    for _ in range(4000):
        if engine.is_over(g):
            break
        actor = g.get("pending_pid") or g["turn"]
        engine.apply_move(g, actor, _bot.choose(g, actor, rng))
    assert engine.is_over(g)
    m.ROOMS[rid] = {"players": {"p1": "One", "p2": "Two"}, "host": "p1", "status": "over",
                    "game": g, "meta": {}, "vs_ai": False, "ai_player": None, "sockets": {}}

    r = _a.run(m.games_review(rid, token=None, player_id="p1"))
    assert r["ok"] and r["winner"] == g["winner"]
    snaps = r["snapshots"]
    assert snaps and len(snaps) > 5
    assert snaps[0]["move"] is None                       # the initial deal
    assert snaps[-1]["game"]["phase"] == "over"
    for s in snaps:                                       # piles stay off the wire
        assert "bag" not in s["game"] and "decks" not in s["game"]

    # a non-participant is refused
    assert _a.run(m.games_review(rid, token=None, player_id="stranger"))["ok"] is False
    assert _a.run(m.games_review(rid, token=None, player_id=None))["ok"] is False

    # an in-progress game is not reviewable
    rid2 = "DUEL08"
    m.ROOMS[rid2] = {"players": {"p1": "One"}, "host": "p1", "status": "playing",
                     "game": engine.new_game(["p1", "p2"], seed=1), "meta": {},
                     "vs_ai": False, "ai_player": None, "sockets": {}}
    assert _a.run(m.games_review(rid2, token=None, player_id="p1"))["ok"] is False
    m.ROOMS.pop(rid, None); m.ROOMS.pop(rid2, None)


def test_abandon_ends_game(monkeypatch):
    rid = "DUEL03"
    _isolate(monkeypatch, rid)

    async def run():
        ws = _FakeWS()
        await m._handle_create(ws, rid, "p1", {"name": "One", "vs_ai": True, "ai_difficulty": "easy"})
        await m._handle_abandon(ws, rid, "p1")
        room = m.ROOMS[rid]
        assert room["status"] == "over"
        assert room["game"]["winner"] == m.AI_PID

    asyncio.run(run())
    m.ROOMS.pop(rid, None)
