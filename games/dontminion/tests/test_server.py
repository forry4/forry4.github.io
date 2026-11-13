"""Room-server tests: option coercers + 4-layer sync, lifecycle, join caps,
the multi-bot scheduler (a full 1-human+3-bot game through the REAL scheduler),
bots answering a human's attack, and the persistence blob round-trip."""

import asyncio
import json
import random

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.dontminion import bot, engine
from games.dontminion import main as m

# The real function objects, grabbed at import time — the autouse fixture stubs
# the module attributes, and the persistence tests need the real ones back.
_REAL_READ_ROOM = m._read_room
_REAL_SAVE_GAME = m.save_game


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def msgs(self):
        return [json.loads(t) for t in self.sent]


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
    # Bots run through _schedule_bots called EXPLICITLY in tests; the fire-and-
    # forget kick would leave dangling tasks on the per-test loop.
    monkeypatch.setattr(m, "_kick_bots", lambda room_id: None)
    # Zero the pacing so scheduler tests run in milliseconds. Any NEW pacing
    # constant must be zeroed here too (the Duel test_server rule).
    monkeypatch.setattr(m, "_BOT_THINK", 0.0)
    monkeypatch.setattr(m, "_new_rng", lambda: random.Random(1234))
    yield
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- option coercers + create ---------------------------------------------------

def test_every_shipped_expansion_is_creatable():
    """`KNOWN_EXPANSIONS` is a GATE, not a label: `_valid_expansions` filters
    the client's request through it, so a shipped set missing from it is
    silently unplayable — the create request falls back to base+intrigue with
    no error on any path, and every engine test still passes because the
    engine's own `KINGDOM` has the set.

    That is exactly what happened when Renaissance landed. `npm run screens`
    caught it (the picker offered nothing to click); nothing in the Python
    suite could, which is why this test exists. It is the ph.-3 "ask what the
    frontend hardcodes" lesson, one layer down: THE BACKEND HARDCODED IT TOO."""
    from games.dontminion import cards
    assert set(m.KNOWN_EXPANSIONS) == set(cards.KINGDOM), \
        sorted(set(cards.KINGDOM) ^ set(m.KNOWN_EXPANSIONS))
    # ...and each one really survives the coercer, in both directions
    for exp in cards.KINGDOM:
        assert m._valid_expansions([exp]) == [exp], exp


def test_create_coerces_bad_options():
    ws = _FakeWS()
    assert _run(m._handle_create(ws, "R1", "host", {
        "name": "Host", "expansions": ["romance", 7], "max_players": 99,
        "num_bots": -3, "ai_difficulty": "insane",
    })) is True
    room = m.ROOMS["R1"]
    assert room["expansions"] == ["base", "intrigue"]
    assert room["max_players"] == 4
    # the contract is "unknown tier -> the default", not any particular tier:
    # the ladder grows without a migration precisely because of this coercion
    assert room["ai_difficulty"] == m.DEFAULT_DIFFICULTY
    assert room["status"] == "open" and room["game"] is None


class _InlineExec:
    """Runs the DB write inline, so a test can capture the REAL save blob
    instead of hand-rebuilding one (a rebuilt blob can't catch save_game
    forgetting a key — which is the failure the four-way sync rule exists for)."""

    def submit(self, fn, *a, **kw):
        fn(*a, **kw)


def test_kingdom_requirements_reach_the_deal_and_survive_the_blob(monkeypatch):
    """The create option must be honoured AND stay in sync across create / save
    blob / load / wire state — the four places every other option lives."""
    from games.dontminion.cards import grants
    assert _run(m._handle_create(_FakeWS(), "RQ", "host", {
        "name": "Host", "vs_ai": True, "num_bots": 1, "expansions": ["base"],
        # unordered, with a bogus entry: coerced to dealing order, junk dropped
        "requires": ["draw", "nonsense", "actions"],
    })) is True
    room = m.ROOMS["RQ"]
    assert room["requires"] == ["actions", "draw"]
    for req in ("actions", "draw"):
        assert any(grants(c, req) for c in room["game"]["kingdom"]), req
    assert m.mk_room_state("RQ", viewer_pid="host")["requires"] == ["actions", "draw"]

    blob = {}
    monkeypatch.setattr(m, "_persist_row",
                        lambda rid, st, seats, host, sj, now, made: blob.update(m._rooms.decode_state(sj)))
    monkeypatch.setattr(m, "_DB_WRITE_EXEC", _InlineExec())
    _REAL_SAVE_GAME("RQ")
    assert blob["requires"] == ["actions", "draw"]     # save_game itself writes it

    monkeypatch.setattr(m, "load_game_state", lambda rid: blob)
    monkeypatch.setattr(m, "_read_room", _REAL_READ_ROOM)
    m.ROOMS.clear()
    assert m.load_game_to_memory("RQ") is True
    assert m.ROOMS["RQ"]["requires"] == ["actions", "draw"]

    # a blob written before the option existed loads as "no requirement"
    monkeypatch.setattr(m, "load_game_state",
                        lambda rid: {k: v for k, v in blob.items() if k != "requires"})
    m.ROOMS.clear()
    assert m.load_game_to_memory("RQ") is True
    assert m.ROOMS["RQ"]["requires"] == []


def test_create_vs_ai_starts_immediately_with_bots():
    ws = _FakeWS()
    assert _run(m._handle_create(ws, "R2", "host", {
        "name": "Host", "vs_ai": True, "num_bots": 3,
        "expansions": ["base"], "ai_difficulty": "easy",
    })) is True
    room = m.ROOMS["R2"]
    assert room["status"] == "playing" and room["game"] is not None
    assert room["ai_players"] == ["bot1", "bot2", "bot3"]
    assert room["max_players"] == 4
    assert set(room["game"]["players"]) == {"host", "bot1", "bot2", "bot3"}
    assert all(b not in room.get("meta", {}) for b in room["ai_players"])
    assert room["game"]["expansions"] == ["base"]
    created = [d for d in ws.msgs() if d["type"] == "created"]
    assert created and created[0]["room"]["ai_players"] == ["bot1", "bot2", "bot3"]


def test_friend_lifecycle_and_join_cap():
    _run(m._handle_create(_FakeWS(), "R3", "host", {"name": "Host", "max_players": 2}))
    assert _run(m._handle_join(_FakeWS(), "R3", "p2", {"name": "P2"})) is True
    late = _FakeWS()
    assert _run(m._handle_join(late, "R3", "p3", {"name": "P3"})) is False
    assert late.msgs()[-1]["message"] == "room is full"
    # non-host can't start
    nh = _FakeWS()
    _run(m._handle_start(nh, "R3", "p2"))
    assert nh.msgs()[-1]["message"] == "only the host can start"
    ws = _FakeWS()
    _run(m._handle_start(ws, "R3", "host"))
    room = m.ROOMS["R3"]
    assert room["status"] == "playing"
    assert set(room["game"]["players"]) == {"host", "p2"}
    # already started
    again = _FakeWS()
    _run(m._handle_start(again, "R3", "host"))
    assert again.msgs()[-1]["message"] == "already started"


def test_start_needs_two_players():
    _run(m._handle_create(_FakeWS(), "R4", "host", {"name": "Host"}))
    ws = _FakeWS()
    _run(m._handle_start(ws, "R4", "host"))
    assert "need at least 2" in ws.msgs()[-1]["message"]


# --- the multi-bot scheduler -----------------------------------------------------

def test_full_game_one_human_three_bots_through_the_real_scheduler():
    _run(m._handle_create(_FakeWS(), "R5", "human", {
        "name": "H", "vs_ai": True, "num_bots": 3, "expansions": ["base"]}))
    room = m.ROOMS["R5"]
    ws = _FakeWS()
    room["sockets"]["human"] = ws
    rng = random.Random(7)
    for _ in range(1500):
        game = room["game"]
        if engine.is_over(game):
            break
        actor = game["pending_pid"] or game["turn"]
        if actor == "human":
            mv = bot.choose(game, "human", rng)
            _run(m._handle_move(ws, "R5", "human", {"move": mv}))
        else:
            _run(m._schedule_bots("R5"))
    assert engine.is_over(room["game"])
    assert room["status"] == "over"
    assert room["game"]["winners"]
    assert room.get("_bot_running") is False


def test_bots_answer_a_humans_attack_mid_turn():
    _run(m._handle_create(_FakeWS(), "R6", "human", {
        "name": "H", "vs_ai": True, "num_bots": 2, "expansions": ["base"]}))
    room = m.ROOMS["R6"]
    game = room["game"]
    # force the human on turn with a Militia; fatten the bots' hands
    game["pending"].clear()
    engine._sync_pending(game)
    game["turn"] = "human"
    game["phase"] = "action"
    game["actions"] = 1
    game["seats"]["human"]["hand"] = ["Militia"]
    for b in room["ai_players"]:
        game["seats"][b]["hand"] = ["Copper"] * 5
    ws = _FakeWS()
    room["sockets"]["human"] = ws
    _run(m._handle_move(ws, "R6", "human",
                        {"move": {"type": "play_action", "card": "Militia"}}))
    assert room["game"]["pending_pid"] in room["ai_players"]
    _run(m._schedule_bots("R6"))                       # drains BOTH bots' discards
    assert room["game"]["pending_pid"] is None
    assert room["game"]["turn"] == "human"             # still the human's turn
    for b in room["ai_players"]:
        assert len(room["game"]["seats"][b]["hand"]) == 3


def test_the_room_tier_reaches_the_bot():
    """The scheduler must play the room's OWN tier. The two are told apart at
    $0 with an empty hand: random-legal takes any active move over ending the
    phase, so it buys a Copper or a Curse; every ladder tier wants NOTHING
    below $2 and ends the turn. Same forced position, one create option apart.

    The probe used to be an Action in hand (random plays it, plain Big Money
    never does), which stopped discriminating when `bigmoney` was retired —
    bmplus owns Actions and plays them too. A create option that silently
    stopped reaching the scheduler would then have looked identical for both
    tiers, i.e. the test would have passed while checking nothing."""
    def bought_junk(room_id, difficulty):
        _run(m._handle_create(_FakeWS(), room_id, "human", {
            "name": "H", "vs_ai": True, "num_bots": 1, "expansions": ["base"],
            "ai_difficulty": difficulty}))
        room = m.ROOMS[room_id]
        assert room["ai_difficulty"] == difficulty     # validated, not coerced away
        game = room["game"]
        game["pending"].clear()
        engine._sync_pending(game)
        game["turn"] = "bot1"
        game["phase"] = "buy"
        game["coins"] = 0
        game["seats"]["bot1"]["hand"] = []             # nothing left to play
        _run(m._schedule_bots(room_id))                # finishes bot1's turn
        return any(e.get("event") == "buy" and e.get("pid") == "bot1"
                   for e in room["game"]["log"])

    assert bought_junk("R9a", "easy") is True
    assert bought_junk("R9b", bot.BM_PLUS) is False


def test_scheduler_noops_when_no_bot_owes_a_move():
    _run(m._handle_create(_FakeWS(), "R7", "host", {"name": "Host"}))
    _run(m._schedule_bots("R7"))                       # open room, no game
    assert m.ROOMS["R7"].get("_bot_running") in (None, False)


# --- lobby history shaping ---------------------------------------------------------

def _fake_db(rows):
    """Minimal stand-in for the dual sqlite/Turso connection: enough for
    list_user_history's cursor/execute/fetchall + name-indexed rows."""
    class _Cur:
        def execute(self, *a, **kw): pass
        def fetchall(self): return rows
    class _Conn:
        def cursor(self): return _Cur()
        def close(self): pass
    return lambda: _Conn()


def test_history_reports_every_players_score(monkeypatch):
    """The lobby line needs the OPPONENT's score, not just yours (the CoC
    shape). `standings` is seat-ordered with you first and carries pids'
    scores positionally, so two players sharing a display name can't collapse
    into one entry the way the name-keyed `scores` map does."""
    state = {
        "players": {"me": "Dup", "them": "Dup", "bot1": "Bot 1"},
        "game": {
            "players": ["me", "them", "bot1"],
            "winners": ["them"],
            "scores": {"me": {"vp": 31}, "them": {"vp": 44}, "bot1": {"vp": 12}},
        },
    }
    monkeypatch.setattr(m, "_db", _fake_db(
        [{"id": "H1", "state_json": json.dumps(state), "updated_at": 99}]))
    monkeypatch.setattr(m, "maybe_cleanup_games", lambda *a, **kw: None)

    [row] = m.list_user_history("me")
    assert [s["vp"] for s in row["standings"]] == [31, 44, 12]     # you first
    assert row["standings"][0]["you"] is True
    assert [s["you"] for s in row["standings"][1:]] == [False, False]
    assert [s["won"] for s in row["standings"]] == [False, True, False]
    assert row["your_vp"] == 31 and row["you_won"] is False
    # the two "Dup" players collapse in the legacy name-keyed map — which is
    # exactly why standings exists; the old field is kept for cached bundles
    assert len(row["scores"]) == 2 and len(row["standings"]) == 3


def test_history_marks_a_shared_win(monkeypatch):
    state = {
        "players": {"me": "Me", "bot1": "Bot 1"},
        "game": {"players": ["me", "bot1"], "winners": ["me", "bot1"],
                 "scores": {"me": {"vp": 20}, "bot1": {"vp": 20}}},
    }
    monkeypatch.setattr(m, "_db", _fake_db(
        [{"id": "H2", "state_json": json.dumps(state), "updated_at": 1}]))
    monkeypatch.setattr(m, "maybe_cleanup_games", lambda *a, **kw: None)
    [row] = m.list_user_history("me")
    # the client renders "Tie" from you_won + more than one winner
    assert row["you_won"] is True and len(row["winners"]) == 2
    assert [s["vp"] for s in row["standings"]] == [20, 20]


# --- persistence blob round-trip ---------------------------------------------------

def test_save_blob_round_trip_restores_options(monkeypatch):
    _run(m._handle_create(_FakeWS(), "R8", "human", {
        "name": "H", "vs_ai": True, "num_bots": 2,
        "expansions": ["intrigue"], "ai_difficulty": "hard"}))
    captured = {}

    def fake_persist(room_id, status, seats, host, state_json, now, created_at):
        captured["state"] = m._rooms.decode_state(state_json)   # state_json is now compressed
        captured["seats"] = seats
        captured["status"] = status

    monkeypatch.setattr(m, "_persist_row", fake_persist)

    # save_game submits to the executor — build + persist the blob synchronously
    room = m.ROOMS["R8"]
    players = room["players"]
    seats = [(pid, players[pid]) for pid in players]
    seats += [(None, None)] * (4 - len(seats))
    state = {
        "players": players, "host": room["host"], "status": room["status"],
        "game": room["game"], "meta": room["meta"], "vs_ai": room["vs_ai"],
        "ai_players": room["ai_players"], "ai_difficulty": room["ai_difficulty"],
        "expansions": room["expansions"], "max_players": room["max_players"],
    }
    fake_persist("R8", room["status"], seats[:4], room["host"],
                 json.dumps(state), 0, 0)
    assert captured["seats"][0][0] == "human"          # creator is player1 (host col)
    assert len(captured["seats"]) == 4                 # padded to 4 columns
    assert captured["seats"][3] == (None, None) or captured["seats"][3] == [None, None]

    # wipe + reload through the REAL load_game_to_memory (state read stubbed)
    monkeypatch.setattr(m, "load_game_state", lambda rid: captured["state"])
    monkeypatch.setattr(m, "_read_room", _REAL_READ_ROOM)
    m.ROOMS.clear()
    assert m.load_game_to_memory("R8") is True
    r2 = m.ROOMS["R8"]
    assert r2["expansions"] == ["intrigue"]
    assert r2["ai_difficulty"] == "hard"
    assert r2["ai_players"] == ["bot1", "bot2"]
    assert r2["max_players"] == 3
    assert r2["sockets"] == {}                         # always reset on load
    assert r2["game"]["expansions"] == ["intrigue"]


def test_load_revalidates_difficulty(monkeypatch):
    blob = {"players": {"h": "H"}, "host": "h", "status": "open", "game": None,
            "meta": {}, "vs_ai": False, "ai_players": [],
            "ai_difficulty": "cheater", "expansions": ["nope"], "max_players": 99}
    monkeypatch.setattr(m, "load_game_state", lambda rid: blob)
    monkeypatch.setattr(m, "_read_room", _REAL_READ_ROOM)
    assert m.load_game_to_memory("R9") is True
    r = m.ROOMS["R9"]
    assert r["ai_difficulty"] == m.DEFAULT_DIFFICULTY
    assert r["expansions"] == ["base", "intrigue"]
    assert r["max_players"] == 4


def test_a_dark_ages_vs_ai_room_creates_saves_and_reloads(monkeypatch):
    """The e2e sanity for a new set: create a vs-bot room with it enabled, let
    the bots play, and round-trip the room through save + load. The shuffled
    piles (Ruins/Knights) and the non-Supply ones live in the save blob, so a
    codec or migrate gap shows up here rather than on a live room."""
    ws = _FakeWS()
    assert _run(m._handle_create(ws, "RDA", "host", {
        "name": "Host", "vs_ai": True, "num_bots": 1,
        "expansions": ["darkages"], "ai_difficulty": "bmplus",
    })) is True
    room = m.ROOMS["RDA"]
    game = room["game"]
    assert game["expansions"] == ["darkages"]
    assert len(game["kingdom"]) == 10
    # play it out with the shipped tier, exactly as the scheduler would
    import random
    from games.dontminion import bot, engine
    rng = random.Random(3)
    for _ in range(6000):
        if engine.is_over(game):
            break
        pid = game["pending_pid"] or game["turn"]
        ok, err = engine.apply_move(game, pid, bot.choose(game, pid, rng, "bmplus"))
        assert ok, err
    assert engine.is_over(game)

    blob = {}
    monkeypatch.setattr(m, "_persist_row",
                        lambda rid, st, seats, host, sj, now, made: blob.update(m._rooms.decode_state(sj)))
    monkeypatch.setattr(m, "_DB_WRITE_EXEC", _InlineExec())
    _REAL_SAVE_GAME("RDA")
    assert blob["game"]["schema"] == engine.SCHEMA
    monkeypatch.setattr(m, "load_game_state", lambda rid: blob)
    monkeypatch.setattr(m, "_read_room", _REAL_READ_ROOM)
    m.ROOMS.clear()
    assert m.load_game_to_memory("RDA") is True
    loaded = m.ROOMS["RDA"]["game"]
    assert loaded["kingdom"] == game["kingdom"]
    for name, p in loaded["piles"].items():
        assert engine.pile_count(loaded, name) >= 0
    # and every seat's view still builds
    for viewer in list(loaded["players"]) + [None]:
        m.engine.player_view(loaded, viewer)
