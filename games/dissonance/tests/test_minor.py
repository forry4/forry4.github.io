"""MINOR mode — even tricks +1 over the classic auction (2026-08-09).

The one mode whose difference lives in the trick VALUES rather than the phase
machine, so what these pin is the currency: the parity itself, the compressed
1..6 ladder, the re-anchored prices (Null 6, set rate 2), the runtime path the
even value takes to the solver (`even_val` on the view, `even` on the deal
snapshot), and the fail-closed gate that keeps an old wasm from searching a
minor room under classic values.
"""

import asyncio
import json
import random

import pytest

from core import rooms as _rooms
from games.dissonance import bot as B
from games.dissonance import engine as E
from games.dissonance import main as m


def _minor(seed=1, opener=0):
    return E.new_game(["a", "b"], random.Random(seed), opener=opener, mode="minor")


def _drive_to(g, phase, seed=2):
    """Bot-drive a game until it reaches `phase` (or the round ends)."""
    rng = random.Random(seed)
    for _ in range(200):
        if g["phase"] == phase or g["phase"] == "over":
            return g
        seat = E.turn_seat(g)
        kind, mv = B.act(g, seat, rng)
        pid = g["seats"][seat]
        if kind == "bid":
            mv = ({"kind": "pass"} if mv.get("pass")
                  else {"kind": "bid", "level": mv["level"], "denom": mv["denom"]})
        elif kind == "play":
            mv = {"kind": "play", "card": mv}
        elif kind == "swap":
            mv = {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
        E.apply_move(g, pid, mv)
    raise AssertionError("never reached phase %r" % phase)


# ── the parity itself ────────────────────────────────────────────────────────


def test_the_mode_exists_and_the_others_did_not_move():
    # Minor's three, plus DUMMY since 2026-08-10. Pinned as a set membership
    # plus a length rather than an exact tuple: this test is about MINOR, and
    # it should not be the thing that fails every time a mode is added.
    assert {"classic", "skat", "minor"} <= set(E.MODES)
    assert E.DEFAULT_MODE == "classic"
    assert E.even_value("minor") == 1
    assert E.even_value("classic") == 2 and E.even_value("skat") == 2
    # An unknown mode reads as the default, like `mode_of` itself.
    assert E.even_value("nonsense") == 2


def test_minor_trick_values_are_plus_one_and_minus_one():
    g = _minor()
    vals = [E.trick_value_in(g, t) for t in range(E.NTRICKS)]
    assert vals == [-1, 1] * 6 + [-1]
    # Classic through the same path is untouched.
    gc = E.new_game(["a", "b"], random.Random(1))
    assert [E.trick_value_in(gc, t) for t in range(E.NTRICKS)] == [-1, 2] * 6 + [-1]


def test_the_pool_is_minus_one_over_a_completed_round():
    assert E.pool_for("minor") == -1
    assert E.pool_for("classic") == 5 == E.POOL
    g = _drive_to(_minor(seed=9), "over", seed=9)
    assert g["trick"] == E.NTRICKS, "the overtrick bonus means no early end"
    assert sum(g["pts"]) == -1


def test_the_ladder_is_derived_from_the_parity_not_typed_beside_it():
    # Six even tricks at +1 each IS the declarer's ceiling; the ladder must
    # never offer a rung above what the game contains.
    ceiling = sum(v for v in (E.trick_value(t, E.even_value("minor"))
                              for t in range(E.NTRICKS)) if v > 0)
    assert E.MINOR_MAX_LEVEL == ceiling == 6
    assert E.max_level_for("minor") == 6
    # ...and the OTHER modes cap below their own ceilings for different
    # reasons: classic's 10 is a product cap two rungs under its parity ceiling
    # of 12, skat's 12 is the multiplier ladder's full range.
    assert E.max_level_for("classic") == E.PARITY_MAX_LEVEL == 10
    assert E.max_level_for("skat") == E.MAX_LEVEL == 12


# ── the auction: classic's shape on the compressed ladder ────────────────────


def test_the_opener_is_offered_levels_1_to_6_and_no_more():
    opts = E.auction_options(_minor())
    levels = {lvl for lvl, _ in opts["bids"]}
    assert levels == set(range(1, 7))
    assert opts["may_pass"] is False


def test_an_overtake_may_not_raise_past_six():
    g = _minor()
    E.apply_bid(g, 0, 5, 2)
    opts = E.auction_options(g)
    assert all(lvl <= 6 for lvl, _ in opts["bids"])
    # ...and the same-level higher-rank overtake still exists at the top.
    assert [6, 0] in opts["bids"] and [5, 3] in opts["bids"]
    with pytest.raises(ValueError):
        E.apply_bid(g, 1, 7, 0)


def test_a_minor_round_runs_the_classic_phase_machine():
    g = _minor()
    E.apply_bid(g, 0, 1, 2)
    E.apply_pass(g, 1)
    assert g["phase"] == "swap"
    E.apply_swap(g, 0, None, None)
    assert g["phase"] == "double", "minor gets classic's Double, not Kontra"
    E.apply_double(g, 1, False)
    assert g["phase"] == "play" and g["leader"] == 0


# ── the re-anchored prices ───────────────────────────────────────────────────


def test_minor_terms_make_set_null_and_short_rate():
    t = E._terms_for("minor", 2, 3)
    # No flat stake at this scale -- the bare N^2 / N bases, deliberately.
    assert t["make"] == 9 and t["set_base"] == 3 and t["target"] == 3
    assert t["short"] == E.MINOR_SHORT_PENALTY == 2
    assert t["null"] == E.MINOR_NULL_MAKE == 6
    assert t["over"] == 1 and t["ramp"] == 0
    # Classic keeps ITS prices (stake, short 5, Null 20) -- the two modes'
    # terms must stay independently anchored.
    c = E._terms_for("classic", 2, 3)
    assert c["short"] == 5 and c["null"] == E.NULL_MAKE == 20
    assert c["make"] == 9 + E.FLAT_MAKE_BONUS["classic"]


def test_the_double_doubles_in_minor_too():
    """Minor shares classic's Double machinery, including the retirement of the
    shortfall ramp on 2026-08-16 -- `DOUBLE_RAMP` is ONE scalar for every mode,
    so minor lost it at the same time. Derived off the constant rather than
    pinned, so switching it back on needs no edit here."""
    t = E._terms_for("minor", 2, 3, doubling=2)
    assert t["make"] == 18 and t["set_base"] == 6 and t["over"] == 2
    assert t["ramp"] == E.DOUBLE_RAMP
    # Null is NOT doubled, same argument as classic's.
    assert t["null"] == 6
    # Set by 2, doubled: 2N + short*s + ramp*s(s+1)/2.
    #   ramp on : 6 + 4 + 3 = 13.   ramp off: 6 + 4 = 10.
    short, ramp = E.MINOR_SHORT_PENALTY, E.DOUBLE_RAMP
    assert E.payoff(t, 1, True) == -(6 + short * 2 + ramp * 2 * 3 // 2)
    assert E.payoff(t, 1, True) == (-13 if ramp else -10)


def test_null_pays_a_level_ones_ceiling_exactly():
    # The classic relationship (12 = 1 + 11 overtricks), carried to the minor
    # scale: a made level-1 sweeping every even trick pays 1 + 5 = 6 = Null.
    t = E._terms_for("minor", 0, 1)
    ceiling_pts = 6  # every even trick, no odd ones
    assert E.payoff(t, ceiling_pts, True) == E.MINOR_NULL_MAKE


def test_a_declarer_with_no_even_trick_scores_null_not_set():
    g = _minor()
    E.apply_bid(g, 0, 2, 1)
    E.apply_pass(g, 1)
    E.apply_swap(g, 0, None, None)
    E.apply_double(g, 1, False)
    rng = random.Random(4)
    guard = 0
    while g["phase"] == "play":
        seat = E.to_play(g)
        moves = E.legal_moves(g, seat)
        # The declarer ducks with all their strength; the defender plays high.
        if seat == 0:
            c = min(moves, key=lambda c: (E.rank(c), c))
        else:
            c = max(moves, key=lambda c: (E.rank(c), c))
        E.apply_play(g, seat, c)
        guard += 1
        assert guard <= 26
    res = g["result"]
    if g["etricks"][0] == 0:
        assert res["null"] and res["scores"][0] == E.MINOR_NULL_MAKE
        assert res["null_value"] == E.MINOR_NULL_MAKE
    else:
        # The deal forced a winner on the ducker; the round scored normally,
        # which is still worth asserting -- Null must never fire with an even
        # trick taken.
        assert not res["null"]


def test_the_result_row_names_the_mode_and_its_prices():
    g = _drive_to(_minor(seed=11), "over", seed=11)
    res = g["result"]
    assert res["mode"] == "minor"
    assert res["null_value"] == E.MINOR_NULL_MAKE
    assert res["short_rate"] == E.MINOR_SHORT_PENALTY
    lvl = res["level"]
    assert res["make_value"] == lvl * lvl * (2 if res["doubled"] else 1)
    # The scores agree with the payoff arithmetic the terms describe.
    terms = {"target": res["target"], "make": res["make_value"],
             "over": res["over_bonus"], "set_base": res["set_base"],
             "short": res["short_rate"], "ramp": res["ramp"],
             "null": res["null_value"]}
    v = E.payoff(terms, res["declarer_pts"], not res["null"])
    decl = res["declarer"]
    assert res["scores"][decl if v >= 0 else 1 - decl] == abs(v)


def test_the_match_target_is_25():
    g = _minor()
    assert g["match"]["target"] == E.MATCH_TARGET["minor"] == 25


# ── what crosses the wire ────────────────────────────────────────────────────


def test_the_view_ships_even_val_in_every_mode():
    assert E.view_for(_minor(), 0)["even_val"] == 1
    assert E.view_for(E.new_game(["a", "b"], random.Random(1)), 0)["even_val"] == 2
    skat = E.new_game(["a", "b"], random.Random(1), mode="skat")
    assert E.view_for(skat, 0)["even_val"] == 2


def test_the_board_trick_value_reads_the_minor_parity():
    g = _drive_to(_minor(seed=5), "play", seed=5)
    v = E.view_for(g, 0)
    assert v["trick_value"] == E.trick_value(g["trick"], 1)
    assert v["trick_value"] in (-1, 1)


def test_the_deal_snapshot_carries_the_parity_for_the_review():
    g = _drive_to(_minor(seed=6), "play", seed=6)
    assert g["deal"]["even"] == 1
    gc = _drive_to(E.new_game(["a", "b"], random.Random(6)), "play", seed=6)
    assert gc["deal"]["even"] == 2
    # ...and it survives the persistence boundary untouched (persist packs the
    # 32 cards and the terms, and passes every other key through).
    from games.dissonance import persist
    g2 = _drive_to(g, "over", seed=6)
    state = {"players": {}, "game": g2}
    packed = persist.compact_state(json.loads(json.dumps(state)))
    restored = persist.expand_state(json.loads(json.dumps(packed)))
    rounds = restored["game"]["match"]["rounds"]
    assert rounds and all(r["deal"]["even"] == 1 for r in rounds if "deal" in r)


def test_minor_priced_options_carry_minor_prices():
    g = _minor()
    opts = E.auction_payoff_options(g)
    assert opts, "the opener has options"
    assert all(o["null"] == E.MINOR_NULL_MAKE for o in opts)
    assert all(o["short"] == E.MINOR_SHORT_PENALTY for o in opts)
    assert all(o["level"] <= 6 for o in opts)


def test_the_expert_payload_ships_the_classic_shape_with_the_minor_ceiling():
    g = _minor()
    payload = E.auction_search_payload(g)
    assert payload["rules"]["mode"] == "classic", (
        "minor IS the classic auction shape; a third mode string would be a "
        "word an older wasm rejects for no information")
    assert payload["rules"]["max_level"] == 6
    assert all(row["null"] == E.MINOR_NULL_MAKE for row in payload["terms"])
    assert all(row["level"] <= 6 for row in payload["terms"])


def test_payoff_terms_reads_the_rooms_own_mode():
    g = _minor()
    E.apply_bid(g, 0, 2, 1)
    E.apply_pass(g, 1)
    t = E.payoff_terms(g)
    assert t["null"] == 6 and t["short"] == 2 and t["make"] == 4


# ── the server bot ───────────────────────────────────────────────────────────


def test_the_bot_bids_inside_the_minor_ladder_and_finishes_a_round():
    for seed in range(6):
        g = _drive_to(_minor(seed=seed, opener=seed % 2), "over", seed=seed)
        assert g["result"]["level"] <= 6
        assert sum(g["pts"]) == -1


def test_the_bot_level_map_is_the_minor_one_only_in_minor():
    strong = 16.0
    assert B._level_for(strong, "minor") < B._level_for(strong, "classic") <= 6
    assert B._level_for(strong, "skat") == B._level_for(strong, "classic")


# ── the fail-closed client-AI gate ───────────────────────────────────────────


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)


@pytest.fixture()
def _isolated_rooms(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_read_room", lambda rid: None)
    yield
    loop.close()


def _room(mode):
    g = E.new_game(["alice", m.AI_PID], random.Random(3), opener=0, mode=mode)
    return {"players": {"alice": "Alice", m.AI_PID: "Bot"}, "sockets": {},
            "status": "playing", "host": "alice", "game": g,
            "meta": {}, "vs_ai": True, "ai_player": m.AI_PID,
            "ai_difficulty": "hard", "mode": mode}


def test_a_minor_room_only_arms_a_client_that_speaks_even_val(_isolated_rooms):
    run = asyncio.get_event_loop().run_until_complete
    m.ROOMS["r1"] = _room("minor")
    ws = _FakeWS()
    # An old bundle never sends `wire`: refused, the room stays unarmed.
    run(m._handle_client_ai_ready(ws, "r1", "alice", {"ready": True}))
    assert not m.ROOMS["r1"].get("client_ai")
    # The current bundle declares wire 2 and is armed.
    run(m._handle_client_ai_ready(ws, "r1", "alice", {"ready": True, "wire": 2}))
    assert m.ROOMS["r1"].get("client_ai")


def test_classic_rooms_accept_any_client_vintage_and_skat_needs_the_top_rung(_isolated_rooms):
    """Classic never changed shape, so any bundle may search it. Skat scores
    CARDS (wire 3, 2026-08-09) and MUST-HEADS the trick (wire 4, 2026-08-10),
    and an older wasm would search the wrong game -- at rung 4 it answers with
    cards this room calls illegal -- so a skat room arms only the top rung,
    the same fail-closed gate minor mode runs at `wire: 2`.

    The requirement is DERIVED from the room's rules, so this asserts against
    what `MUST_HEAD` currently says rather than pinning a literal: turning the
    rule off must put skat back to rung 3 with no edit here."""
    run = asyncio.get_event_loop().run_until_complete
    m.ROOMS["r0"] = _room("classic")
    run(m._handle_client_ai_ready(_FakeWS(), "r0", "alice", {"ready": True}))
    assert m.ROOMS["r0"].get("client_ai"), "classic accepts any vintage"

    need = 4 if E.must_head_mode("skat") else 3
    m.ROOMS["r1"] = _room("skat")
    run(m._handle_client_ai_ready(_FakeWS(), "r1", "alice", {"ready": True}))
    assert not m.ROOMS["r1"].get("client_ai"), "no wire field: refused"
    run(m._handle_client_ai_ready(_FakeWS(), "r1", "alice",
                                  {"ready": True, "wire": need - 1}))
    assert not m.ROOMS["r1"].get("client_ai"), "one rung short is refused"
    run(m._handle_client_ai_ready(_FakeWS(), "r1", "alice",
                                  {"ready": True, "wire": need}))
    assert m.ROOMS["r1"].get("client_ai"), "the current bundle is armed"


def test_the_catalog_serves_the_minor_numbers():
    run = asyncio.new_event_loop().run_until_complete
    cat = run(m.catalog())
    assert cat["even_value"]["minor"] == 1
    assert cat["pools"]["minor"] == -1 and cat["pools"]["classic"] == 5
    assert cat["max_levels"]["minor"] == 6
    assert cat["minor_null_make"] == 6
    assert cat["minor_short_penalty"] == 2
    assert cat["match_targets"]["minor"] == 25
    assert "minor" in cat["modes"]
