"""The Expert tier: what the server ships so the browser can SEARCH the auction.

Hard prices every option myopically -- "if I end up declaring this contract,
what does it pay" -- which cannot underbid to cap an auction and cannot judge
re-entering after being overtaken, because both of those are questions about the
opponent's reply. Expert minimaxes the auction tree instead. The search lives in
`rust-cores/dissonance-core/src/auc_search.rs`; everything here is the payload
that feeds it, and the properties the search relies on.

TWO GATES, ON PURPOSE, because the tier duplicates exactly one thing.

* The auction's SCORING is shipped as data, so it is not duplicated at all and
  these tests hold the table to `_terms_for` -- the same discipline
  `payoff_terms` established for card play.
* The auction's LEGALITY is mirrored in Rust, because it is a function of the
  node the SEARCH is standing on rather than the one the server is. That gate is
  `wire::auction_legality`, replaying `tests/fixtures/auction.jsonl` (from
  `tools/gen_auction_fixtures.py`) -- Rust-side, since that is where the mirror
  is. What is tested HERE is that the fixture's own source of truth, the payload,
  describes the same auction the engine is running.
"""

from __future__ import annotations

import os
import random

import pytest

from games.dissonance import engine as E
from games.dissonance import main as m


def _classic(seed=3, opener=0):
    return E.new_game(["a", "b"], random.Random(seed), opener=opener)


def _skat(seed=3, opener=0):
    return E.new_game(["a", "b"], random.Random(seed), opener=opener, mode="skat")


def _key(row):
    return row["key"]


# --- the tier is wired at all ----------------------------------------------


def test_both_searching_tiers_run_the_auction_tree():
    """THE LADDER MOVED UP A RUNG (2026-08-14). The tree measured +1.19 over
    the myopic price list, so it became HARD; Expert is the tree with the soft
    opponent model (+0.957 +- 0.454 over the same tree without it). Both are
    client-served: without a browser either falls through to the server bot."""
    assert {"hard", "expert"} <= set(m.DIFFICULTIES)
    assert {"hard", "expert"} <= set(m.CLIENT_AI_TIERS)
    assert set(m.SEARCH_AUCTION_TIERS) == {"hard", "expert"}
    # ...and they must still be DIFFERENT bots, or the ladder has a rung that
    # is a relabelling. The difference is the opponent model, and a temperature
    # of 0 would BE the Hard tree -- the property the whole A/B rested on, so
    # it is the thing to guard.
    assert m.EXPERT_OPP_TEMP > 0


def test_the_frontend_offers_exactly_the_tiers_the_server_accepts():
    """The picker is a second list of the same roster, and a tier the server
    knows about but the modal cannot select is a tier nobody ever plays."""
    # `os.path`, not `rsplit("/")`: on Windows `__file__` is backslash-separated,
    # so the split found nothing, the whole path survived as the "directory",
    # and this opened `…\engine.py/Dissonance.jsx`. It passed on Linux CI and
    # failed on every Windows dev box — the CoC-ratio shape again, a gate that
    # is green where it runs and red where it is read.
    text = os.path.join(os.path.dirname(E.__file__), "Dissonance.jsx")
    src = open(text, encoding="utf-8").read()
    # The picker's list lives in shared/botTiers.js, beside every other game's.
    shared = os.path.join(os.path.dirname(E.__file__), "..", "..", "shared", "botTiers.js")
    offered = open(shared, encoding="utf-8").read().split("const DISSONANCE_BOT_TIERS")[1].split("\n];")[0]
    for tier in m.DIFFICULTIES:
        assert f'id: "{tier}"' in offered, f"{tier} is not in DISSONANCE_BOT_TIERS"
    for tier in m.CLIENT_AI_TIERS:
        assert f'"{tier}"' in src.split("const CLIENT_AI_TIERS")[1].split("]")[0], \
            f"{tier} is a client tier the frontend never arms"


# --- the payload describes the auction the engine is running ---------------


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_there_is_no_payload_outside_the_auction(mode):
    """`declare`, `kontra`, `re` and `double` have no reply after them, so a
    tree over them would be one node deep and Hard's pricing is the whole
    answer. Expert is deliberately identical there."""
    g = _skat() if mode == "skat" else _classic()
    assert E.auction_search_payload(g) is not None
    while g["phase"] == "auction":
        seat = E.turn_seat(g)
        opt = E.auction_options(g)
        if opt.get("bids"):
            lvl, d = opt["bids"][0]
            E.apply_bid(g, seat, lvl, d)
        elif opt.get("values"):
            E.apply_skat_bid(g, seat, opt["values"][0])
        else:
            E.apply_pass(g, seat)
        if g["phase"] == "auction" and E.mode_of(g) == "skat":
            E.apply_pass(g, E.turn_seat(g))
    assert g["phase"] != "auction"
    assert E.auction_search_payload(g) is None


def test_the_classic_state_is_the_auction_verbatim():
    g = _classic()
    E.apply_bid(g, 0, 4, 2)
    st = E.auction_search_payload(g)["state"]
    a = g["auction"]
    assert (st["level"], st["denom"], st["declarer"], st["to_act"]) == (4, 2, 0, 1)
    assert st["used"] == a["used"]


def test_nothing_standing_ships_a_denomination_of_zero_not_minus_one():
    """`denom` is -1 while nothing stands, which is a sentinel this side and an
    unsigned field on the wire -- read back as 255 it would be a denomination
    the rank comparison treats as the highest there is."""
    st = E.auction_search_payload(_classic())["state"]
    assert st["level"] == 0 and st["denom"] == 0 and st["declarer"] == -1


def test_the_skat_state_carries_the_pass_count_because_a_pass_is_not_a_leaf():
    """One open pass hands the deal over and the auction CONTINUES; only the
    second throws the hand in. A tree that treated every pass as a leaf would
    price a pass-out as a settled contract."""
    g = _skat()
    st = E.auction_search_payload(g)["state"]
    assert st["passes"] == 0
    E.apply_pass(g, E.turn_seat(g))
    st = E.auction_search_payload(g)["state"]
    assert st["passes"] == 1 and g["phase"] == "auction"


# --- the terms table -------------------------------------------------------


def test_the_key_encoding_matches_the_rust_side():
    """`auc_search::Bid::key` is `(level << 8) | denom` in classic and the bare
    ladder value in skat. Two encodings of the same thing, so they are asserted
    against the shape rather than against each other's constants."""
    rows = E.auction_search_payload(_classic())["terms"]
    for r in rows:
        assert _key(r) == (r["level"] << 8) | r["denom"]
    rows = E.auction_search_payload(_skat())["terms"]
    for r in rows:
        # The key is the RUNG BID, not the declaration's own value -- a rung of
        # 2 is bought by a base-3 denomination at level 1, which is worth 3.
        # Keying on the declaration would split one settlement into six.
        assert _key(r) in E.SKAT_VALUES
        assert r["level"] == E.skat_min_level(r["denom"], _key(r))
        assert E.skat_value_of(r["denom"], r["level"]) >= _key(r)


def test_every_settlement_is_priced_by_the_engines_own_arithmetic():
    """The whole point of shipping a table: change a payoff and the bot follows
    with no bot code at all. A row that disagreed with `_terms_for` would be a
    second copy of the scoring, which is what this design exists to prevent."""
    for g, mode in ((_classic(), "classic"), (_skat(), "skat")):
        for r in E.auction_search_payload(g)["terms"]:
            want = E._terms_for(mode, r["denom"], r["level"])
            assert {k: v for k, v in r.items() if k != "key"} == want


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_every_option_the_server_offers_has_a_row_to_settle_on(mode):
    """A bid whose settlement is missing from the table prices as a flat 0 in
    the tree -- a plausible-looking number that outranks every genuinely bad
    contract. So the table must cover the whole option list, at every node."""
    g = _skat() if mode == "skat" else _classic()
    seen = 0
    for _ in range(6):
        if g["phase"] != "auction":
            break
        payload = E.auction_search_payload(g)
        keys = {_key(r) for r in payload["terms"]}
        opts = E.auction_payoff_options(g)
        assert opts
        a = g["auction"]
        for o in opts:
            mv = o["move"]
            if mv["kind"] == "pass":
                # A pass settles on what STANDS (or redeals, in skat).
                if a["declarer"] < 0:
                    continue
                key = (a["value"] if mode == "skat"
                       else (a["level"] << 8) | a["denom"])
            elif mode == "skat":
                key = mv["value"]
            else:
                key = (mv["level"] << 8) | mv["denom"]
            assert key in keys, f"{mv} has no row to settle on"
            seen += 1
        # Take a middling option and keep going, so deeper nodes are covered.
        bids = [o["move"] for o in opts if o["move"]["kind"] == "bid"]
        if not bids:
            break
        mv = bids[len(bids) // 2]
        E.apply_move(g, g["seats"][E.turn_seat(g)], mv)
    assert seen > 50


def test_a_skat_rung_carries_one_row_per_declaration_it_buys():
    """A number is a PRICE, not a shape -- the winner names their game after
    winning it -- so a rung is worth the best declaration it buys. Same
    approximation `pass_options` already makes."""
    rows = E.auction_search_payload(_skat())["terms"]
    by_key: dict[int, list] = {}
    for r in rows:
        by_key.setdefault(_key(r), []).append(r)
    for value, got in by_key.items():
        want = E.skat_declarable(value)
        assert sorted(r["denom"] for r in got) == sorted(d["denom"] for d in want)
        for r in got:
            lo = next(d["min_level"] for d in want if d["denom"] == r["denom"])
            assert r["level"] == lo
    assert max(len(v) for v in by_key.values()) > 1, "no rung buys two games"


def test_unreachable_settlements_are_pruned():
    """The bidding only ever ascends, so everything below the standing bid is
    ~60 rows of JSON re-broadcast on every room update for nothing. The standing
    bid itself stays: that is what a pass settles on."""
    g = _classic()
    before = len(E.auction_search_payload(g)["terms"])
    E.apply_bid(g, 0, 7, 1)
    after = E.auction_search_payload(g)["terms"]
    assert len(after) < before
    assert min(r["level"] for r in after) == 7
    assert (7 << 8) | 1 in {_key(r) for r in after}

    g = _skat()
    E.apply_skat_bid(g, 0, 20)
    rows = E.auction_search_payload(g)
    assert min(_key(r) for r in rows["terms"]) == 20
    assert all(v > 20 for v in rows["rules"]["ladder"])


def test_the_skat_ladder_is_what_the_engine_says_is_bidable():
    g = _skat()
    E.apply_skat_bid(g, 0, 12)
    payload = E.auction_search_payload(g)
    assert payload["rules"]["ladder"] == E.auction_options(g)["values"]


def test_the_rules_are_the_engines_own_knobs():
    for g, mode, top in ((_classic(), "classic", E.NOTRUMP), (_skat(), "skat", E.GRAND)):
        r = E.auction_search_payload(g)["rules"]
        assert r == {"mode": mode, "min_level": E.MIN_LEVEL,
                     "max_level": E.max_level_for(mode),
                     # Classic's cap is its own ceiling (i.e. uncapped) since
                     # 2026-08-13; the tree learns the jump bonus as a RULE
                     # because the terms rows are keyed by settlement and the
                     # jump belongs to the path.
                     "max_raise": E.raise_cap_for(mode),
                     "jump_set_bonus": E.JUMP_SET_BONUS.get(mode, 0),
                     "denom_rule": E.denom_rule_for(mode),
                     "opener_may_pass": E.opener_may_pass(mode),
                     "top_denom": top,
                     "ladder": [v for v in E.SKAT_VALUES if v > 0] if mode == "skat" else []}


def test_the_payload_state_carries_the_standing_bids_jump():
    """A pass settles on the standing state, and the set price at that leaf
    includes the bonus the standing bid's own rise earned -- so the tree must
    know it, and it cannot be derived from the level alone."""
    g = _classic()
    E.apply_bid(g, 0, 2, 1)
    assert E.auction_search_payload(g)["state"]["jump"] == 2, \
        "the opening counts, as a raise over level 0 (v2)"
    E.apply_bid(g, 1, 5, 2)
    assert E.auction_search_payload(g)["state"]["jump"] == 3


# --- the armed request -----------------------------------------------------


def test_the_two_searching_tiers_differ_by_the_opponent_model(monkeypatch):
    """BOTH tiers carry the tree since 2026-08-14; what separates them is that
    Expert's modelled opponent is good rather than clairvoyant. The block stays
    optional on the wire, so a wasm that predates the soft model reads Expert's
    payload as the Hard tree -- degrading one rung, never to nothing.

    This is the test that would catch the ladder becoming a relabelling."""
    import asyncio
    import json as _json

    for tier, want in (("expert", True), ("hard", True)):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        m.ROOMS.clear()
        m.ROOM_LOCK = asyncio.Lock()
        monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
        g = _classic(seed=11)
        room = {"players": {"a": "A"}, "sockets": {}, "status": "playing", "host": "a",
                "game": g, "meta": {"a": {"token": "t"}}, "vs_ai": True,
                "ai_player": m.AI_PID, "ai_difficulty": tier, "client_ai": True,
                "mode": "classic"}
        g["seats"] = ["a", m.AI_PID]
        m.ROOMS["r"] = room
        task = asyncio.ensure_future(m._ask_the_client("r", 1))
        loop.run_until_complete(asyncio.sleep(0))
        loop.run_until_complete(asyncio.sleep(0))
        auc = room["_ai_search"]["auction"]
        assert ("search" in auc) is want, f"{tier} carried search={'search' in auc}"
        # THE RUNG ITSELF: Expert softens the opponent, Hard does not. A
        # temperature of 0 would be the Hard tree exactly (pinned in Rust and
        # by the arena's +0.0000 null control), so a soft model that arrived on
        # Hard, or an Expert that lost it, is two tiers with one bot in them.
        rules = auc["search"]["rules"]
        if tier == "expert":
            assert rules.get("opp_model") == "soft", rules
            assert rules.get("opp_temp") == m.EXPERT_OPP_TEMP > 0, rules
        else:
            assert "opp_model" not in rules, rules
        # The TALON MODEL rides on every classic auction request, Hard's and
        # Expert's alike -- the leaf that prices contracts is shared, and
        # without the swap weights it under-prices every declarable contract
        # by the ~+1.5 the swap is worth (measured: talon model on-vs-off is
        # +1.54 +- 0.51). The weights must be bot.py's own, or a re-fit there
        # would strand the leaf on stale numbers.
        from games.dissonance import bot as B
        assert auc.get("swap") == B.swap_policy_terms(), tier
        # ...and the WORLD BUDGET rides with the tier: 8 for Expert's auction
        # (the measured lever -- see CLIENT_AI_AUCTION_WORLDS_EXPERT), 3 for
        # Hard's. A tier that got the search block but Hard's budget would be
        # the unmeasured configuration nobody arena'd.
        # Both tree tiers get the tree's own budget: the pooling trap means a
        # tree must be ONE tree over all its worlds, so the count is a property
        # of the search shape rather than of the tier.
        want_k = m.CLIENT_AI_AUCTION_WORLDS_EXPERT
        assert room["_ai_search"]["max_worlds"] == want_k, tier
        if want:
            # It has to survive the JSON boundary -- the armed request is
            # broadcast as room state, not handed over in process.
            assert _json.loads(_json.dumps(auc))["search"]["terms"]
        task.cancel()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
