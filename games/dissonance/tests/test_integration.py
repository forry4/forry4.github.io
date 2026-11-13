"""End-to-end: a room is actually creatable and playable to a result.

Mounting a screen is not the same as being able to start a game — Dontminion's
Renaissance set rendered fine and could not be created, because a list in
main.py had not been updated. This drives the real WS handlers from create
through the auction and all thirteen tricks to a scored result, so that class
of failure cannot pass silently here.
"""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.dissonance import engine as E
from games.dissonance import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def last(self, mtype=None):
        for t in reversed(self.sent):
            d = json.loads(t)
            if mtype is None or d.get("type") == mtype:
                return d
        return None

    def types(self):
        return [json.loads(t).get("type") for t in self.sent]


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
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_a_two_player_room_plays_from_create_to_a_scored_result():
    wa, wb = _FakeWS(), _FakeWS()
    assert run(m._handle_create(wa, "R", "alice", {"name": "Alice"})) is True
    assert run(m._handle_join(wb, "R", "bob", {"name": "Bob"})) is True
    run(m._handle_start(wa, "R", "alice"))

    room = m.ROOMS["R"]
    g = room["game"]
    assert g is not None, "starting must deal a game"
    assert g["phase"] == "auction"

    # A game is a MATCH, so this plays rounds until one side reaches the target
    # -- and asserts the room stays LIVE in between, which is the whole
    # difference between a round ending and a game ending.
    guard = 0
    rounds = 0
    while not E.is_over(g):
        guard += 1
        assert guard < 4000, "the room failed to reach a result"
        if E.round_over(g):
            rounds += 1
            assert room["status"] == "playing", \
                "a scored round is not the end of the match -- the room stays live"
            assert g["result"] is not None
            # Flat, not behind an `if`: since the overtrick bonus every round
            # runs all thirteen tricks, so an early end here is a regression
            # and must not read as the other half of a legitimate pair.
            assert g["trick"] == E.NTRICKS and sum(g["pts"]) == E.POOL
            # Either seat may deal the next one; Bob does, to prove it is not
            # the host's privilege.
            run(m._handle_move(wb, "R", "bob",
                               {"move": {"kind": "next_round",
                                         "round": g["result"]["round"]}}))
            continue
        pid = E.turn_pid(g)
        ws = wa if pid == "alice" else wb
        if g["phase"] == "auction":
            opt = E.auction_options(g)
            if opt["may_pass"]:
                move = {"kind": "pass"}
            else:
                lvl, den = opt["bids"][0]
                move = {"kind": "bid", "level": lvl, "denom": den}
        elif g["phase"] == "swap":
            move = {"kind": "swap", "take": None}
        elif g["phase"] == "double":
            move = {"kind": "double", "on": False}
        else:
            seat = E.seat_of(g, pid)
            move = {"kind": "play", "card": E.legal_moves(g, seat)[0]}
        run(m._handle_move(ws, "R", pid, {"move": move}))

    assert rounds >= 2, "a match to the target takes more than one deal"
    match = g["match"]
    assert max(match["scores"]) >= match["target"]
    assert g["result"]["match_scores"] == match["scores"], \
        "the stored result carries the final standing -- history never sees the live game"
    assert room["status"] == "over", "the room status must follow the MATCH"
    # And no handler ever reported an error along the way.
    assert "error" not in wa.types() and "error" not in wb.types()


def test_a_vs_bot_room_is_creatable_and_the_bot_takes_its_turn():
    ws = _FakeWS()
    assert run(m._handle_create(ws, "B", "alice",
                                {"name": "Alice", "vs_ai": True,
                                 "ai_difficulty": "normal"})) is True
    room = m.ROOMS["B"]
    assert room["game"] is not None, "a vs-bot room deals immediately"
    assert room["ai_player"] == m.AI_PID

    # Drive it to the end, letting the scheduler play every bot turn.
    guard = 0
    while room["game"]["phase"] != "over":
        guard += 1
        assert guard < 300
        g = room["game"]
        pid = E.turn_pid(g)
        if pid == m.AI_PID:
            run(m._schedule_bot_turn("B"))
            continue
        if g["phase"] == "auction":
            opt = E.auction_options(g)
            move = ({"kind": "pass"} if opt["may_pass"]
                    else {"kind": "bid", "level": opt["bids"][0][0],
                          "denom": opt["bids"][0][1]})
        elif g["phase"] == "swap":
            move = {"kind": "swap", "take": None}
        elif g["phase"] == "double":
            move = {"kind": "double", "on": False}
        else:
            move = {"kind": "play", "card": E.legal_moves(g, E.seat_of(g, pid))[0]}
        run(m._handle_move(ws, "B", pid, {"move": move}))

    assert room["game"]["result"] is not None
    # This room is dealt from an UNSEEDED rng, so the pool invariant has to be
    # stated the way the engine means it: over a round that ran to thirteen.
    if room["game"]["trick"] == E.NTRICKS:
        assert sum(room["game"]["pts"]) == E.POOL
    else:
        assert room["game"]["result"]["ended_early"]


def test_a_vs_bot_match_carries_on_into_the_next_round():
    """The case most likely to strand: only the human can deal the next round,
    and the bot has to pick its own turn back up once they do."""
    ws = _FakeWS()
    run(m._handle_create(ws, "N", "alice",
                         {"name": "Alice", "vs_ai": True, "ai_difficulty": "normal"}))
    room = m.ROOMS["N"]

    def drive_to_round_end():
        guard = 0
        while not E.round_over(room["game"]):
            guard += 1
            assert guard < 300, f"stuck in {room['game']['phase']}"
            g = room["game"]
            pid = E.turn_pid(g)
            if pid == m.AI_PID:
                run(m._schedule_bot_turn("N"))
                continue
            if g["phase"] == "auction":
                opt = E.auction_options(g)
                move = ({"kind": "pass"} if opt["may_pass"]
                        else {"kind": "bid", "level": opt["bids"][0][0],
                              "denom": opt["bids"][0][1]})
            elif g["phase"] == "swap":
                move = {"kind": "swap", "take": None}
            elif g["phase"] == "double":
                move = {"kind": "double", "on": False}
            else:
                move = {"kind": "play", "card": E.legal_moves(g, E.seat_of(g, pid))[0]}
            run(m._handle_move(ws, "N", pid, {"move": move}))

    drive_to_round_end()
    first = room["game"]["result"]
    assert room["status"] == "playing", "the room must not close after one round"

    run(m._handle_move(ws, "N", "alice",
                       {"move": {"kind": "next_round", "round": first["round"]}}))
    g = room["game"]
    assert g["phase"] == "auction" and g["result"] is None, "a fresh deal"
    assert g["match"]["round"] == first["round"] + 1
    assert g["match"]["scores"] == first["match_scores"], "the standing carries over"
    assert room.get("_ai_search") is None, \
        "an armed search must not outlive the deal it was asking about"

    # ...and the bot is playable again, which is the half that actually strands.
    drive_to_round_end()
    assert room["game"]["result"] is not None
    assert room["game"]["match"]["round"] == first["round"] + 1


def test_the_bot_never_deals_the_next_round_by_itself():
    """`turn_pid` is None between rounds, so the scheduler must find nothing to
    do -- a bot that dealt on its own would blow past the result panel."""
    ws = _FakeWS()
    run(m._handle_create(ws, "S", "alice",
                         {"name": "Alice", "vs_ai": True, "ai_difficulty": "normal"}))
    room = m.ROOMS["S"]
    g = room["game"]
    g["phase"] = "over"
    g["result"] = {"scores": [0, 0], "round": 1, "match_over": False}
    assert m._bot_should_act(room) is False
    run(m._schedule_bot_turn("S"))
    assert room["game"]["phase"] == "over", "the bot dealt the next round on its own"


def test_an_illegal_move_is_refused_without_corrupting_the_game():
    wa, wb = _FakeWS(), _FakeWS()
    run(m._handle_create(wa, "R", "alice", {"name": "Alice"}))
    run(m._handle_join(wb, "R", "bob", {"name": "Bob"}))
    run(m._handle_start(wa, "R", "alice"))
    g = m.ROOMS["R"]["game"]
    before = json.dumps(g, sort_keys=True)

    mover = E.turn_pid(g)
    other = "bob" if mover == "alice" else "alice"
    # Wrong player.
    run(m._handle_move(wa if other == "alice" else wb, "R", other,
                       {"move": {"kind": "bid", "level": 3, "denom": 0}}))
    # Right player, illegal level (the opener may not raise past the cap).
    run(m._handle_move(wa if mover == "alice" else wb, "R", mover,
                       {"move": {"kind": "bid", "level": 99, "denom": 0}}))
    # Right player, wrong phase.
    run(m._handle_move(wa if mover == "alice" else wb, "R", mover,
                       {"move": {"kind": "play", "card": 0}}))

    assert json.dumps(g, sort_keys=True) == before, "a refused move must not mutate state"


def _drive(g, pick_auction):
    """One move for whichever phase a room is in, in either mode."""
    pid = E.turn_pid(g)
    seat = E.seat_of(g, pid)
    phase = g["phase"]
    if phase == "auction":
        return pid, pick_auction(g)
    if phase == "commit":
        # QUARTET's stage two: lead from the declarer's own hand, no swap.
        return pid, {"kind": "commit", "lead": g["auction"]["declarer"]}
    if phase == "double":
        return pid, {"kind": "double", "on": False}
    if phase == "swap":
        return pid, {"kind": "swap", "take": None}
    if phase == "talon":
        return pid, {"kind": "hand"}
    if phase == "declare":
        d = E.declare_options(g)["denoms"][0]
        return pid, {"kind": "declare", "denom": d["denom"],
                     "level": d["min_level"], "sharp": True}
    if phase == "kontra":
        return pid, {"kind": "kontra", "on": True}
    if phase == "re":
        return pid, {"kind": "re", "on": True}
    return pid, {"kind": "play", "card": E.legal_moves(g, seat)[0]}


def _skat_auction_move(g):
    vals = E.auction_options(g)["values"]
    # Bid low enough that the auction settles instead of climbing to the top of
    # the ladder, but never pass out of a hand nobody has bid on.
    return ({"kind": "bid", "value": vals[0]} if vals and vals[0] <= 12
            else {"kind": "pass"})


def test_a_skat_room_plays_from_create_to_a_scored_result():
    """The mode is a room FLAG, not a second game: same table, same route, same
    handlers. If any of that were wrong the room would stall in a phase no
    handler advances.

    Rounds are driven until the MATCH is decided. With Hand, Sharp, Kontra and
    Re all on, most deals settle it in one round -- but whether one round's
    payout reaches the target is the DEAL's business, and the deal is unseeded:
    asserting a one-round match here failed CI (2026-08-07) on a deal that paid
    short while the identical suite passed in the other gate."""
    wa, wb = _FakeWS(), _FakeWS()
    assert run(m._handle_create(wa, "K", "alice",
                                {"name": "Alice", "mode": "skat"})) is True
    assert run(m._handle_join(wb, "K", "bob", {"name": "Bob"})) is True
    run(m._handle_start(wa, "K", "alice"))

    room = m.ROOMS["K"]
    g = room["game"]
    assert room["mode"] == "skat" and g["mode"] == "skat"

    rounds = 0
    while not E.is_over(g):
        rounds += 1
        assert rounds < 40, "the match never reached its target"
        guard = 0
        while g["phase"] != "over":
            guard += 1
            assert guard < 300, f"the room stalled in {g['phase']}"
            pid, move = _drive(g, _skat_auction_move)
            run(m._handle_move(wa if pid == "alice" else wb, "K", pid,
                               {"move": move}))

        # Flat, not behind an `if`: since the overtrick bonus every round runs
        # all thirteen tricks, so an early end is a regression and must not
        # read as the other half of a legitimate pair. The pool is the deal's
        # own -- skat scores captured cards (2026-08-09).
        assert g["trick"] == E.NTRICKS and sum(g["pts"]) == E.played_pool(g)
        res = g["result"]
        assert res["mode"] == "skat" and res["value"] > 0
        winner = (res["declarer"] if (res["made"] or res["null"])
                  else 1 - res["declarer"])
        assert res["scores"][winner] > 0
        if not E.is_over(g):
            assert room["status"] == "playing", \
                "a scored round is not the end of the match -- the room stays live"
            run(m._handle_move(wb, "K", "bob",
                               {"move": {"kind": "next_round",
                                         "round": res["round"]}}))

    assert room["status"] == "over"
    assert "error" not in wa.types() and "error" not in wb.types()


#: Bid AROUND THE SETTLED MODE (6) rather than the floor. Not cosmetic: a
#: level-1 quartet contract pays about 7 against a match target of 140, so a
#: floor-bidding driver needs 40+ rounds to decide a match and the test reads
#: as a stall in a phase no handler advances -- which is the failure this file
#: is for and would then be indistinguishable from a real one.
_QUARTET_TEST_LEVEL = 6


def _quartet_auction_move(g):
    """Open near the settled mode in a denomination this seat can BACK, then
    pass -- quartet's gate means the opener cannot simply name a suit."""
    bids = E.auction_options(g)["bids"]
    if not bids or g["auction"]["level"] > 0:
        return {"kind": "pass"}
    at = [b for b in bids if b[0] == _QUARTET_TEST_LEVEL]
    lvl, den = min(at) if at else max(bids)
    return {"kind": "bid", "level": lvl, "denom": den}


def test_a_quartet_room_plays_from_create_to_a_scored_result():
    """FOUR HANDS through the real WS handlers. A mode that deals a different
    number of hands, plays a different number of tricks and adds a phase
    (`commit`) is exactly the shape that stalls in a phase no handler
    advances -- which is what this file exists to catch."""
    wa, wb = _FakeWS(), _FakeWS()
    assert run(m._handle_create(wa, "Q", "alice",
                                {"name": "Alice", "mode": "quartet"})) is True
    assert run(m._handle_join(wb, "Q", "bob", {"name": "Bob"})) is True
    run(m._handle_start(wa, "Q", "alice"))

    room = m.ROOMS["Q"]
    g = room["game"]
    assert room["mode"] == "quartet" and g["mode"] == "quartet"
    assert [len(h) for h in g["hands"]] == [12] * 4
    assert len(g["out"]) == 4

    rounds = 0
    while not E.is_over(g):
        rounds += 1
        assert rounds < 40, "the match never reached its target"
        guard = 0
        while g["phase"] != "over":
            guard += 1
            assert guard < 300, f"the room stalled in {g['phase']}"
            pid, move = _drive(g, _quartet_auction_move)
            run(m._handle_move(wa if pid == "alice" else wb, "Q", pid,
                               {"move": move}))
        # Nine tricks, four cards each, three left in every hand -- and the
        # TRICK pool conserved at +3 with the keeps deliberately outside it.
        assert g["trick"] == 9
        assert [len(h) for h in g["hands"]] == [3] * 4
        assert sum(g["pts"]) == E.pool_for("quartet") == 3
        res = g["result"]
        assert res["mode"] == "quartet"
        assert res["declarer_pts"] == (res["trick_pts"][res["declarer"]]
                                       + res["keeps"][res["declarer"]])
        if not E.is_over(g):
            run(m._handle_move(wb, "Q", "bob",
                               {"move": {"kind": "next_round",
                                         "round": res["round"]}}))

    assert room["status"] == "over"
    assert "error" not in wa.types() and "error" not in wb.types()


def test_a_vs_bot_quartet_room_is_creatable_and_the_bot_commits(monkeypatch):
    """The bot has to answer a NEW prompt (`commit`), and one that stalls there
    leaves the human with no way forward. Also pins that a quartet room is
    never armed for the browser search core, which is two-seat to its bones --
    an armed client would answer with a card for the wrong hand."""
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    ws = _FakeWS()
    # A vs-AI room is dealt at CREATE -- starting it again is an error, and
    # `types()` below would report it.
    assert run(m._handle_create(ws, "QB", "alice",
                                {"name": "Alice", "vs_ai": True,
                                 "ai_difficulty": "normal",
                                 "mode": "quartet"})) is True
    room = m.ROOMS["QB"]
    g = room["game"]
    assert not E.client_searchable("quartet")

    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 400, f"the room stalled in {g['phase']}"
        pid = E.turn_pid(g)
        if pid != "alice":
            run(m._schedule_bot_turn("QB"))
            continue
        seat = E.seat_of(g, pid)
        if g["phase"] == "auction":
            move = _quartet_auction_move(g)
        elif g["phase"] == "commit":
            move = {"kind": "commit", "lead": g["auction"]["declarer"]}
        elif g["phase"] == "double":
            move = {"kind": "double", "on": False}
        else:
            move = {"kind": "play", "card": E.legal_moves(g, seat)[0]}
        run(m._handle_move(ws, "QB", "alice", {"move": move}))
    assert g["result"]["mode"] == "quartet"
    assert "error" not in ws.types()


def test_a_vs_bot_skat_room_is_creatable_and_the_bot_takes_every_phase(monkeypatch):
    """The bot has to answer four NEW prompts (talon, declaration, Kontra, Re),
    and a bot that stalls on any of them leaves the human with no way forward."""
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    ws = _FakeWS()
    assert run(m._handle_create(ws, "KB", "alice",
                                {"name": "Alice", "vs_ai": True,
                                 "ai_difficulty": "normal", "mode": "skat"})) is True
    room = m.ROOMS["KB"]
    assert room["game"]["mode"] == "skat"

    guard = 0
    while room["game"]["phase"] != "over":
        guard += 1
        assert guard < 400, f"stalled in {room['game']['phase']}"
        g = room["game"]
        if E.turn_pid(g) == m.AI_PID:
            run(m._schedule_bot_turn("KB"))
            continue
        pid, move = _drive(g, _skat_auction_move)
        run(m._handle_move(ws, "KB", pid, {"move": move}))

    assert room["game"]["result"] is not None
    # Unseeded deal, so the pool invariant is stated the way the engine means
    # it: over a round that ran to thirteen tricks.
    if room["game"]["trick"] == E.NTRICKS:
        assert sum(room["game"]["pts"]) == E.played_pool(room["game"])
    else:
        assert room["game"]["result"]["ended_early"]
    assert "error" not in ws.types(), "the bot never produced an illegal move"


def test_abandoning_a_skat_room_scores_it_in_skat_currency():
    """Reachable in skat mode with NOTHING agreed — both players may pass, so
    the room can be walked out of with no declarer at all."""
    wa, wb = _FakeWS(), _FakeWS()
    run(m._handle_create(wa, "A1", "alice", {"name": "Alice", "mode": "skat"}))
    run(m._handle_join(wb, "A1", "bob", {"name": "Bob"}))
    run(m._handle_start(wa, "A1", "alice"))
    g = m.ROOMS["A1"]["game"]
    assert g["auction"]["declarer"] == -1

    run(m._handle_abandon(wa, "A1", "alice"))
    res = m.ROOMS["A1"]["game"]["result"]
    assert res["mode"] == "skat" and res["abandoned_by"] == E.seat_of(g, "alice")
    # Whoever stayed is paid, and named by a seat index that really exists.
    assert res["scores"][1 - res["abandoned_by"]] > 0
    assert res["scores"][res["abandoned_by"]] == 0
    assert m.ROOMS["A1"]["status"] == "over"
    assert "error" not in wa.types() and "error" not in wb.types()


def test_a_room_created_without_a_mode_is_still_the_classic_auction():
    ws = _FakeWS()
    run(m._handle_create(ws, "C", "alice", {"name": "Alice", "vs_ai": True}))
    room = m.ROOMS["C"]
    assert room["mode"] == "classic"
    assert room["game"]["mode"] == "classic"
    assert "contract" not in room["game"]
    # ...and a nonsense mode falls back rather than dealing something undefined.
    run(m._handle_create(_FakeWS(), "C2", "alice", {"name": "A", "mode": "chess"}))
    assert m.ROOMS["C2"]["mode"] == "classic"


def test_the_catalog_matches_the_engine():
    """The client renders trick values from /catalog; if the two ever disagree
    the board would lie about what a trick is worth."""
    cat = run(m.catalog())
    assert cat["trick_values"] == [E.trick_value(t) for t in range(E.NTRICKS)]
    assert cat["pool"] == E.POOL
    assert sum(cat["trick_values"]) == cat["pool"]
    assert cat["max_raise"] == E.MAX_RAISE
    # Per-mode since classic dropped its cap: classic's entry is its own
    # ceiling (never binds), minor/dummy keep the 2.
    assert cat["max_raises"] == {mode: E.raise_cap_for(mode) for mode in E.MODES}
    assert cat["max_raises"]["classic"] == E.max_level_for("classic")
    assert cat["max_raises"]["minor"] == E.MAX_RAISE
    assert cat["jump_set_bonus"] == E.JUMP_SET_BONUS
    assert cat["short_penalty"] == E.SHORT_PENALTY
    # Skat mode's price table is served, never copied into the client — the
    # bases and the ladder they generate must agree.
    assert cat["modes"] == list(E.MODES)
    assert cat["skat_bases"] == list(E.SKAT_BASE)
    assert cat["skat_values"] == list(E.SKAT_VALUES)
    # A base of 0 marks a denomination that is NOT on the ladder (Null), so
    # a client has to filter it out to reproduce the rungs -- which is what
    # `levelsFor` does, and why this asserts the filtered form.
    assert 0 in cat["skat_bases"], "the unbuyable slot ships as 0, not as a gap"
    assert set(cat["skat_values"]) == (
        {b * lvl for b in cat["skat_bases"] if b > 0
         for lvl in range(cat["min_level"], cat["max_level"] + 1)}
        | {cat["skat_null_value"]})


def test_a_match_between_rounds_prompts_BOTH_players_in_the_lobby():
    """Nobody is on turn between rounds, so a lobby keyed on the turn alone
    would list the match as Active with no prompt on either side -- which is
    exactly how one gets forgotten."""
    wa, wb = _FakeWS(), _FakeWS()
    run(m._handle_create(wa, "L", "alice", {"name": "Alice"}))
    run(m._handle_join(wb, "L", "bob", {"name": "Bob"}))
    run(m._handle_start(wa, "L", "alice"))
    g = m.ROOMS["L"]["game"]

    on_turn = E.turn_pid(g)
    other = "bob" if on_turn == "alice" else "alice"
    assert m.engine.may_act(g, on_turn) and not m.engine.may_act(g, other)

    g["phase"] = "over"
    g["result"] = {"scores": [0, 0], "round": 1, "match_over": False}
    assert m.engine.may_act(g, "alice") and m.engine.may_act(g, "bob")
    g["match"]["over"] = True
    assert not m.engine.may_act(g, "alice") and not m.engine.may_act(g, "bob")
