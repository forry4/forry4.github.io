"""The Hard tier's client-AI protocol (main.py).

Hard searches its CARD PLAY in the player's browser — an exact double-dummy
solve per sampled deal, which cannot run on Render's free tier. That makes the
BOT'S move arrive over the same WebSocket a human plays on, so every one of
these is really the same question: what stops that channel from being a way to
play the bot's seat badly, or to hang the room?

The answers this pins:

* nothing is trusted — the card is re-validated against ``engine.legal_moves``
  for the BOT's seat, and a refusal is treated exactly like silence;
* a stale answer (one to a decision that has been superseded) is dropped, which
  is why the armed decision carries a monotonic counter rather than a ply;
* degradation is per-DECISION — an unarmed client, a timeout, a bad card and a
  disarmed socket all fall through to the server's own bot, so a room can never
  stall waiting on a browser;
* the request is only ever armed on a vs-AI room, because it carries the bot's
  own view (its hand) and a human opponent must never receive it.

Drives the handlers directly with a fake websocket, like ``test_ws_auth.py``.
"""

import asyncio
import json
import random

import pytest

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

    def msgs(self):
        return [json.loads(t) for t in self.sent]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    # Process-global WS throttle keyed on client IP; every fake socket reports
    # "unknown", so without this reset the suite eventually throttles itself.
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _playing_room(difficulty="hard", mode="classic", seed=5):
    """A vs-AI room driven to trick play, with the bot on the lead."""
    g = E.new_game(["alice", m.AI_PID], random.Random(seed), opener=0, mode=mode)
    from games.dissonance import bot as B
    rng = random.Random(seed)
    for _ in range(80):
        if g["phase"] in ("play", "over"):
            break
        seat = E.turn_seat(g)
        kind, mv = B.act(g, seat, rng)
        pid = g["seats"][seat]
        if kind == "bid":
            E.apply_move(g, pid, {"kind": "pass"} if mv.get("pass") else {"kind": "bid", **mv})
        elif kind == "swap":
            E.apply_move(g, pid, {"kind": "swap", **mv})
        elif kind == "play":
            E.apply_move(g, pid, {"kind": "play", "card": mv})
        else:
            E.apply_move(g, pid, mv)
    assert g["phase"] == "play"
    # Make it the bot's move, whichever seat it drew.
    if E.turn_pid(g) != m.AI_PID:
        seat = E.to_play(g)
        E.apply_move(g, g["seats"][seat], {"kind": "play", "card": B.choose_card(g, seat)})
    assert E.turn_pid(g) == m.AI_PID
    room = {
        "players": {"alice": "Alice"},
        "sockets": {},
        "status": "playing",
        "host": "alice",
        "game": g,
        "meta": {"alice": {"token": "tok"}},
        "vs_ai": True,
        "ai_player": m.AI_PID,
        "ai_difficulty": difficulty,
        "mode": mode,
    }
    m.ROOMS["r1"] = room
    return room


def _arm(room):
    """Run the request half of one decision, without waiting for an answer."""
    seat = E.seat_of(room["game"], m.AI_PID)
    task = asyncio.ensure_future(m._ask_the_client("r1", seat))
    # Let `_ask_the_client` reach its wait; the arm happens before it blocks.
    run(asyncio.sleep(0))
    run(asyncio.sleep(0))
    return task


# --- the request -----------------------------------------------------------


def test_arming_ships_the_bots_own_view_and_only_on_a_vs_ai_room():
    room = _playing_room()
    room["client_ai"] = True
    ws = _FakeWS()
    room["sockets"]["alice"] = ws
    task = _arm(room)

    armed = room["_ai_search"]
    seat = E.seat_of(room["game"], m.AI_PID)
    assert armed["seat"] == seat and armed["decision"] == 1
    # The BOT's view, not the human's: its own hand, and the opponent's as a
    # count. This is the whole reason the flag is refused off a vs-AI room.
    assert sorted(armed["view"]["hand"]) == sorted(room["game"]["hands"][seat])
    assert armed["view"]["you"] == seat
    # And it rides ROOM STATE, so every re-broadcast and every reconnect
    # re-ships it rather than the request being a one-shot message.
    state = m.mk_room_state("r1", viewer_pid="alice")
    assert state["ai_search"]["decision"] == 1

    run(m._handle_ai_move(ws, "r1", "alice", {
        "decision": 1, "card": E.legal_moves(room["game"], seat)[0]}))
    assert run(task) is not None


def test_an_unarmed_room_is_never_asked():
    room = _playing_room()
    room["client_ai"] = False
    assert run(m._ask_the_client("r1", E.seat_of(room["game"], m.AI_PID))) is None
    assert room.get("_ai_search") is None
    assert "ai_search" not in m.mk_room_state("r1", viewer_pid="alice")


def test_ready_is_refused_unless_the_room_is_vs_ai_on_a_client_tier():
    for difficulty, vs_ai, want in (("hard", True, True),
                                    ("normal", True, False),
                                    ("easy", True, False),
                                    ("hard", False, False)):
        room = _playing_room(difficulty=difficulty)
        room["vs_ai"] = vs_ai
        run(m._handle_client_ai_ready(_FakeWS(), "r1", "alice", {}))
        assert bool(room.get("client_ai")) is want, (difficulty, vs_ai)


def test_a_stranger_cannot_arm_the_room():
    room = _playing_room()
    run(m._handle_client_ai_ready(_FakeWS(), "r1", "mallory", {}))
    assert not room.get("client_ai")


def test_a_dropped_socket_disarms_the_room():
    """With the tab gone there is nobody to answer, and every later decision
    would burn the whole watchdog before the server took over."""
    room = _playing_room()
    room["client_ai"] = True
    ws = _FakeWS()
    room["sockets"]["alice"] = ws
    _rooms.release_socket(m.ROOMS, "r1", "alice", ws, disarm_client_ai=True)
    assert room["client_ai"] is False


# --- the answer ------------------------------------------------------------


def test_a_legal_card_is_taken():
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = E.legal_moves(room["game"], seat)
    assert len(legal) > 1, "a forced move would make this test vacuous"
    task = _arm(room)
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[-1]}))
    assert run(task) == {"kind": "play", "card": legal[-1]}


def test_a_card_the_engine_refuses_is_treated_exactly_like_silence():
    """The move arrives over the human's socket. Every card is re-validated
    against `legal_moves` for the BOT's seat, so the worst a tampered client can
    do is make its own opponent play the server's heuristic move instead."""
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = set(E.legal_moves(room["game"], seat))
    illegal = next(c for c in range(E.NCARD) if c not in legal)
    for bad in (illegal, "7♠", None, -1, 999):
        task = _arm(room)
        run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                              {"decision": room["_ai_search"]["decision"], "card": bad}))
        assert run(task) is None, bad


def test_an_answer_to_a_superseded_decision_is_dropped():
    """The staleness key is a monotonic counter, not the ply: every play happens
    to append exactly one history entry today, but nothing ENFORCES that, and
    two decisions sharing a key make a late reply indistinguishable."""
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = E.legal_moves(room["game"], seat)
    first = _arm(room)
    assert room["_ai_search"]["decision"] == 1
    # Answering decision 1 correctly, then re-arming, gives decision 2.
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    assert run(first) is not None
    second = _arm(room)
    assert room["_ai_search"]["decision"] == 2
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    # The stale reply did not release the waiter; a fresh one still does.
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 2, "card": legal[0]}))
    assert run(second) is not None


def test_an_answer_that_arrives_after_the_decision_closed_is_harmless():
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = E.legal_moves(room["game"], seat)
    task = _arm(room)
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    run(task)
    assert room["_ai_search"] is None
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    assert room.get("_ai_pending_move") is None


def test_the_client_never_answers_and_the_server_finishes_the_turn(monkeypatch):
    """The watchdog is the reason a browser cannot stall a room. Nobody replies,
    the wait times out, and the scheduler plays the decision itself."""
    monkeypatch.setattr(m, "CLIENT_AI_TIMEOUT", 0.05)
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    room = _playing_room()
    room["client_ai"] = True
    before = len(room["game"]["history"])
    run(m._schedule_bot_turn("r1"))
    assert len(room["game"]["history"]) > before, "the turn must still advance"
    assert room["_ai_search"] is None


# --- the tier --------------------------------------------------------------


def test_hard_is_offered_and_the_other_tiers_stay_server_side():
    assert "hard" in m.DIFFICULTIES
    # Expert is Hard plus a minimax over the AUCTION, so it is client-served for
    # the same reason and by the same protocol -- see `test_expert.py`.
    assert m.CLIENT_AI_TIERS == ("hard", "expert")
    # Easy and Normal are the shipped ladder; handing a one-trick-deep policy a
    # solver would be a strength change dressed up as a serving one.
    assert set(m.CLIENT_AI_TIERS).isdisjoint({"easy", "normal"})
    assert m._valid_difficulty("hard") == "hard"
    assert m._valid_difficulty("wasm") == m.DEFAULT_DIFFICULTY


def test_every_tier_the_picker_offers_is_one_the_server_accepts():
    """This seam fails SILENTLY: an id that drifts out of `DIFFICULTIES` does not
    error, `_valid_difficulty` quietly coerces it, and the room seats a different
    bot than the player picked. Read as text — the JSX is not importable here."""
    import pathlib
    import re
    jsx = (pathlib.Path(__file__).resolve().parents[1] / "Dissonance.jsx").read_text(encoding="utf-8")
    # The picker's list lives in shared/botTiers.js (the profile page names tiers too).
    tiers = (pathlib.Path(__file__).resolve().parents[3] / "shared" / "botTiers.js").read_text(encoding="utf-8")
    assert "DISSONANCE_BOT_TIERS as BOT_TIERS" in jsx, "Dissonance no longer renders the shared tier list"
    block = re.search(r"const DISSONANCE_BOT_TIERS = \[(.*?)\];", tiers, re.S)
    assert block, "DISSONANCE_BOT_TIERS moved; this test is reading the wrong thing"
    offered = set(re.findall(r'id:\s*"([a-z]+)"', block.group(1)))
    assert offered, "no tiers parsed"
    assert offered <= set(m.DIFFICULTIES), offered - set(m.DIFFICULTIES)
    # And the client-side tier list agrees with the server's, or a Hard room
    # would never load a worker and would silently play at Normal.
    client = set(re.findall(r'const CLIENT_AI_TIERS = \[([^\]]*)\]', jsx))
    assert client, "CLIENT_AI_TIERS moved"
    assert set(re.findall(r'"([a-z]+)"', client.pop())) == set(m.CLIENT_AI_TIERS)


# --- the auction, searched in the browser too --------------------------------


def _auction_room(mode="skat", seed=5):
    """A vs-AI room parked on the BOT's auction turn."""
    g = E.new_game(["alice", m.AI_PID], random.Random(seed), opener=1, mode=mode)
    assert g["phase"] == "auction" and E.turn_pid(g) == m.AI_PID
    room = {"players": {"alice": "Alice"}, "sockets": {}, "status": "playing",
            "host": "alice", "game": g, "meta": {"alice": {"token": "tok"}},
            "vs_ai": True, "ai_player": m.AI_PID, "ai_difficulty": "hard",
            "mode": mode}
    m.ROOMS["r1"] = room
    return room


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_an_auction_decision_ships_priced_options_that_each_carry_their_move(mode):
    """The browser holds NO rule about what a bid is. It ranks the options and
    sends back one of the moves it was handed, so the four move shapes across
    two auction modes stay entirely server-side."""
    room = _auction_room(mode)
    room["client_ai"] = True
    task = _arm(room)
    auc = room["_ai_search"]["auction"]
    assert auc["phase"] == "auction" and auc["options"]
    for o in auc["options"]:
        # Priced by `payoff_terms`' own arithmetic...
        assert {"target", "make", "set_base", "short", "null"} <= set(o)
        # ...and carrying the move it stands for. PASSING is one of them: it
        # is worth minus what the standing contract pays the opponent, not
        # zero, so it is priced like everything else rather than left to a
        # client-side "value <= 0" rule.
        assert o["move"]["kind"] in ("bid", "pass")
    kinds = {o["move"]["kind"] for o in auc["options"]}
    assert "bid" in kinds
    if E.auction_options(room["game"])["may_pass"]:
        assert "pass" in kinds, "a legal pass must be priced, not implicit"
        for o in auc["options"]:
            if o["move"]["kind"] == "pass":
                assert o.get("opp") or o.get("redeal"), \
                    "a pass is priced for the OPPONENT, or is a redeal worth 0"
    # A card-play request ships `payoff`; an auction one cannot, because there
    # is no contract yet for those terms to describe.
    assert "payoff" not in room["_ai_search"]

    run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                          {"decision": 1, "move": auc["options"][0]["move"]}))
    assert run(task) == auc["options"][0]["move"]


def test_every_option_the_server_offers_is_a_move_the_engine_accepts():
    """The list is generated, not hand-written, so it can drift into offering a
    bid the auction refuses — and the bot would then answer with it and be
    silently dropped to the server tier for that decision."""
    for mode in ("classic", "skat"):
        room = _auction_room(mode)
        g = room["game"]
        opts = E.auction_payoff_options(g)
        assert opts
        for o in opts:
            assert m._validated_bot_move(g, m.AI_PID, o["move"]) is not None, o


def test_an_auction_move_the_engine_refuses_is_treated_like_silence():
    room = _auction_room("classic")
    room["client_ai"] = True
    for bad in ({"kind": "bid", "level": 99, "denom": 0},
                {"kind": "play", "card": 0},
                {"kind": "declare", "denom": 0, "level": 1},
                {"nonsense": True}, "bid", None):
        task = _arm(room)
        run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                              {"decision": room["_ai_search"]["decision"], "move": bad}))
        assert run(task) is None, bad


def test_the_talon_and_the_swap_stay_on_the_server():
    """Both are decisions about INFORMATION, not about a contract: what
    declining to look is worth depends on a game that has not been named yet,
    so there is no payoff for the solver to price them against."""
    assert "talon" not in m.CLIENT_AI_PHASES and "swap" not in m.CLIENT_AI_PHASES
    assert set(m.CLIENT_AI_PHASES) == {"auction", "declare", "kontra", "re",
                                       "double"}
    g = E.new_game(["alice", m.AI_PID], random.Random(5), opener=0, mode="skat")
    E.apply_skat_bid(g, 0, 12)
    E.apply_pass(g, 1)
    assert g["phase"] == "talon"
    assert E.auction_payoff_options(g) == []


def test_an_auction_world_budget_is_its_own_knob():
    """A card decision solves the deal once; an auction decision solves it in
    every denomination — measured 417ms against 74ms natively. The first wired
    version inherited the card cap and spent 7.5-9.2s on a bid, which the
    watchdog then timed out. The budgets are separate KNOBS; since 2026-08-08
    they happen to both read 8 (the auction cap was raised on measurement:
    hard k=8 - hard k=3 = +0.86 +- 0.49), and what matters is that the auction
    one is the one an auction decision gets. Pooled 4 ways that is ~850ms a
    bid, still far under the card play's wall-clock ceiling."""
    assert m.CLIENT_AI_AUCTION_WORLDS <= m.CLIENT_AI_MAX_WORLDS
    room = _auction_room("skat")
    room["client_ai"] = True
    task = _arm(room)
    assert room["_ai_search"]["max_worlds"] == m.CLIENT_AI_AUCTION_WORLDS
    task.cancel()      # nobody answers this one; don't leave it pending


# --- pricing the pass -------------------------------------------------------


def test_a_legal_pass_is_priced_for_the_opponent_not_left_at_zero():
    """The blind spot both tiers used to share.

    A pass hands the standing contract to the OPPONENT at their price, so it is
    worth minus what that contract pays them. Valued at zero instead, a bot can
    never SACRIFICE -- a sacrifice is a contract that prices negative, bought
    because passing prices worse -- and it also buys contracts it should decline
    whenever the opponent's standing contract was worse for them.
    """
    g = E.new_game(["alice", "bob"], random.Random(3), opener=0)
    E.apply_bid(g, 0, 3, 2)
    assert E.auction_options(g)["may_pass"] is True
    opts = E.auction_payoff_options(g)
    passes = [o for o in opts if o["move"]["kind"] == "pass"]
    assert len(passes) == 1
    p = passes[0]
    assert p["opp"] is True, "priced for the opponent, and negated by the search"
    # It is the STANDING contract, exactly as the opponent would play it.
    assert (p["denom"], p["level"]) == (2, 3)
    assert p["make"] == 9 + E.FLAT_MAKE_BONUS["classic"] and p["target"] == 3
    # ...and it is the same arithmetic `_finish` would apply to that contract
    # -- the standing bid's jump included (an opening at 3 carries 3, v2).
    assert p | {"opp": True} == E._terms_for("classic", 2, 3, jump=3) | {
        "opp": True, "move": p["move"]}


def test_the_classic_opener_gets_no_pass_because_it_may_not():
    g = E.new_game(["alice", "bob"], random.Random(3), opener=0)
    assert E.auction_options(g)["may_pass"] is False
    assert not [o for o in E.auction_payoff_options(g) if o["move"]["kind"] == "pass"]


def _to_double(seed=3):
    """A classic room parked on the DEFENDER's Double, with the bot defending."""
    g = E.new_game(["alice", m.AI_PID], random.Random(seed), opener=0)
    E.apply_bid(g, 0, 3, 2)
    E.apply_pass(g, 1)
    E.apply_swap(g, 0, None, None)
    assert g["phase"] == "double"
    return g


def _to_kontra(seed=3):
    """A skat room parked on the DEFENDER's Kontra, with the bot defending."""
    g = E.new_game(["alice", m.AI_PID], random.Random(seed), opener=0, mode="skat")
    E.apply_skat_bid(g, 0, 12)
    E.apply_pass(g, 1)
    E.apply_look(g, 0)
    E.apply_swap(g, 0, None, None)
    E.apply_declare(g, 0, 3, 4, False, False)
    assert g["phase"] == "kontra"
    return g


def test_a_settled_contract_names_its_real_declarer_not_the_seat_being_asked():
    """The bug that made classic's Double a coin flip (found + fixed 2026-08-14).

    `auction.declarer` is who would be DECLARING under these options, and
    `wire::answer_auction` derives two different things from it: which side the
    determinized worlds are solved for (the declarer LEADS trick 1), and the
    SIGN the answer comes back with. At the double phase the acting seat is the
    DEFENDER and the options describe the opponent's settled contract, so
    naming the acting seat solved the wrong position AND returned it
    declarer-signed and un-negated -- the defender then picked the branch best
    for the declarer.

    Silent in the usual way: two legal options, a plausible number on each. The
    only visible symptom was a tier that doubled contracts that made about as
    often as ones that failed. Measured against exact ground truth over 150 real
    rounds, the search found 2 of the 13 contracts that deserved a Double;
    naming the real declarer finds 9 of 13.

    Kontra and Re always got this right; `double` was simply missing from the
    tuple, which is why the test is written over ALL THREE settled-contract
    phases rather than over the one that broke.
    """
    for mode, phase, g in (("classic", "double", _to_double()),
                           ("skat", "kontra", _to_kontra())):
        seat = E.turn_seat(g)
        decl = g["auction"]["declarer"]
        assert seat == 1 - decl, f"{phase}: the DEFENDER is the one who acts"
        # ...and the BOT is that defender, so `_arm` asks about the right seat.
        assert g["seats"][seat] == m.AI_PID
        room = {"players": {"alice": "Alice"}, "sockets": {}, "status": "playing",
                "host": "alice", "game": g, "meta": {"alice": {"token": "tok"}},
                "vs_ai": True, "ai_player": m.AI_PID, "ai_difficulty": "hard",
                "mode": mode, "client_ai": True}
        m.ROOMS["r1"] = room
        task = _arm(room)
        auc = room["_ai_search"]["auction"]
        assert auc["phase"] == phase
        assert auc["declarer"] == decl, (
            f"{phase}: the request must name the contract's own declarer, "
            f"not the seat being asked")
        run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                              {"decision": room["_ai_search"]["decision"],
                               "move": auc["options"][0]["move"]}))
        run(task)
        m.ROOMS.pop("r1", None)


def test_the_double_ships_a_belief_prior_and_a_threshold_in_classic_only():
    """The two knobs turned on 2026-08-14, and the scope they were measured at.

    `bid_prior` conditions the searcher's world sample on the AUCTION -- the
    declarer won it, so their hand is not a uniform draw, and measured over 400
    real rounds their real holding sits at the 0.765 percentile of the uniform
    resample. `double_margin` stops the argmax doubling coin flips.

    CLASSIC ONLY, and that is the point of this test. The tilt map is a set of
    quantiles on classic's level distribution and the margin is in classic's
    payoff units; minor runs the SAME PHASE on a 1..6 ladder in a quarter-sized
    currency, so shipping either there would be a map applied on faith -- the
    mistake `_DUMMY_LEVEL_NEEDS` already paid for once.
    """
    for mode, wants in (("classic", True), ("minor", False)):
        g = _to_double(seed=3)
        g["mode"] = mode
        room = {"players": {"alice": "Alice"}, "sockets": {}, "status": "playing",
                "host": "alice", "game": g, "meta": {"alice": {"token": "tok"}},
                "vs_ai": True, "ai_player": m.AI_PID, "ai_difficulty": "hard",
                "mode": mode, "client_ai": True}
        m.ROOMS["r1"] = room
        task = _arm(room)
        auc = room["_ai_search"]["auction"]
        assert ("bid_prior" in auc) is wants, f"{mode}: belief prior"
        assert ("double_margin" in auc) is wants, f"{mode}: threshold"
        if wants:
            assert auc["double_margin"] == m.DOUBLE_MARGIN["classic"] > 0
            p = auc["bid_prior"]
            # A tilt of 0 or a single try IS uniform sampling, so shipping
            # either would be shipping nothing at all.
            assert p["tilt"] > 0 and p["tries"] > 1
            # Sliced to the BASE deck, like `swap_policy_terms` and
            # `card_values`: Rust takes its offset from the length.
            assert len(p["curve"]) == E.NRANK
        run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                              {"decision": room["_ai_search"]["decision"],
                               "move": auc["options"][0]["move"]}))
        run(task)
        m.ROOMS.pop("r1", None)


def test_a_card_play_request_carries_the_belief_prior_too():
    """The auction is evidence for all THIRTEEN card decisions, not just the one.

    Measured (`tools/decayprobe.py`, 200 rounds): the declarer's remaining
    holding sits at the 0.769 percentile of a uniform resample at trick 1 and is
    STILL 0.617 at trick 11 -- 0.775 averaged over tricks 1-4 against 0.626 over
    9-13. The bias does not wash out as the hand reveals itself, so a card
    search that samples uniformly is wrong about the declarer all round.

    It rides at the TOP level of the request, not inside `auction`: a play
    request has no auction block. The frontend's whitelist has to carry it, and
    that half is asserted in `screens.mjs` rather than here.
    """
    g = E.new_game(["alice", m.AI_PID], random.Random(3), opener=0)
    E.apply_bid(g, 0, 3, 2)
    E.apply_pass(g, 1)
    E.apply_swap(g, 0, None, None)
    E.apply_double(g, 1, False)
    assert g["phase"] == "play"
    # Drive to a ply the BOT has to answer, so a real request gets armed.
    while E.turn_pid(g) != m.AI_PID:
        seat = E.turn_seat(g)
        E.apply_move(g, g["seats"][seat],
                     {"kind": "play", "card": E.legal_moves(g, seat)[0]})
    room = {"players": {"alice": "Alice"}, "sockets": {}, "status": "playing",
            "host": "alice", "game": g, "meta": {"alice": {"token": "tok"}},
            "vs_ai": True, "ai_player": m.AI_PID, "ai_difficulty": "hard",
            "mode": "classic", "client_ai": True}
    m.ROOMS["r1"] = room
    task = _arm(room)
    armed = room["_ai_search"]
    assert "payoff" in armed, "a play request still ships the scoring rule"
    p = armed.get("bid_prior")
    assert p, "a classic play request must carry the belief prior"
    # A tilt of 0 or a single try is uniform sampling, i.e. shipping nothing.
    assert p["tilt"] > 0 and p["tries"] > 1
    run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                          {"decision": armed["decision"],
                           "card": E.legal_moves(g, E.seat_of(g, m.AI_PID))[0]}))
    run(task)
    m.ROOMS.pop("r1", None)


def test_a_skat_pass_out_is_priced_at_zero_as_a_redeal():
    """Nothing stands, so passing throws the hand in -- a fresh deal neither
    seat has seen, worth 0 by symmetry. Priced rather than omitted so `pass` is
    always in the list when it is legal."""
    g = E.new_game(["alice", "bob"], random.Random(3), opener=0, mode="skat")
    passes = [o for o in E.auction_payoff_options(g) if o["move"]["kind"] == "pass"]
    assert len(passes) == 1 and passes[0]["redeal"] is True
    assert passes[0]["make"] == passes[0]["set_base"] == passes[0]["null"] == 0


def test_a_skat_pass_prices_every_game_the_standing_number_buys_them():
    """The skat winner has not named a game yet, so what passing concedes is the
    best declaration that number buys. One priced option per candidate; the
    search takes the worst for us, which assumes they declare well."""
    g = E.new_game(["alice", "bob"], random.Random(3), opener=0, mode="skat")
    E.apply_skat_bid(g, 0, 12)
    passes = [o for o in E.auction_payoff_options(g) if o["move"]["kind"] == "pass"]
    assert len(passes) == len(E.skat_declarable(12)) >= 3
    assert all(o["opp"] is True for o in passes)
    assert {o["denom"] for o in passes} == {d["denom"] for d in E.skat_declarable(12)}
