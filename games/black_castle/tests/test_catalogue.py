"""Hold the generated card catalogue, and the engine's ops, to the printed game.

`catalogue.py` is GENERATED from `data/base_catalogue.json` by `tools/build_catalogue.py`.
Two things have to stay true for that to be worth anything, and each has a test here:

* the checked-in file must be what the generator currently produces (otherwise a hand edit
  silently becomes the catalogue), and
* every op the generator can emit must be one the engine actually implements (otherwise a
  card resolves to nothing at all, which no amount of play would make obvious).

The catalogue replaced placeholder data on 2026-09-20. Before that, stewards and diplomats
were built in loops keyed on `i % 3` with invented effects -- the port ran fine and played
a different game.
"""
from __future__ import annotations

import collections
import copy
import json
import os

from games.black_castle import cards, catalogue, engine
from games.black_castle.tools import build_catalogue

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_checked_in_catalogue_is_what_the_generator_produces():
    # A hand edit to catalogue.py is not merely lost on the next run, it is caught here.
    assert build_catalogue.main(["--check"]) == 0


def test_every_op_the_data_can_carry_is_one_the_engine_implements():
    # The failure this prevents is silent: an unimplemented op falls off the end of
    # `_apply_effects` and the card does nothing, which looks exactly like a card that
    # was supposed to do nothing.
    source = open(os.path.join(_PKG, "engine.py"), encoding="utf-8").read()
    for op in build_catalogue.OPS:
        assert f'op == "{op}"' in source or f'"{op}"' in source, op

    # Scoped to the GENERATED cards. The Daimyo's Favor cards are still ours -- they
    # appear nowhere in the corpus, because BGA only ships one once a courtier reaches
    # the third floor -- so they still speak the older hand-written vocabulary.
    generated = (catalogue.STEWARDS + catalogue.DIPLOMATS + catalogue.DECREE_CARDS
                 + catalogue.STARTING_RESOURCE_CARDS + catalogue.STARTING_ACTION_CARDS)
    used = {e["op"] for card in generated
            for e in (card.get("light") or []) + (card.get("dark") or [])}
    used |= {card["lantern"]["op"] for card in generated if card.get("lantern")}
    assert used <= set(build_catalogue.OPS), sorted(used - set(build_catalogue.OPS))
    assert not (used & set(build_catalogue.TILE_ONLY_OPS)), "tile grammar on a card"
    # And the placeholder daimyo are the ONLY cards still outside it, so this stops
    # being a blanket exemption the moment anything else drifts.
    everywhere = {e["op"] for card in cards.ALL_CARDS.values()
                  for e in (card.get("light") or []) + (card.get("dark") or [])}
    assert everywhere - set(build_catalogue.OPS) <= {"influence", "move", "lantern"}


def test_the_catalogue_lands_on_the_printed_counts():
    assert len(catalogue.STEWARDS) == 15
    assert len(catalogue.DIPLOMATS) == 12
    assert len(catalogue.DECREE_CARDS) == 3
    # NINE starting resource cards, three backed with each of pearl / iron / food. This
    # read 8 until 2026-09-20 because the 20-log corpus never turned up typeArg 3 -- the
    # same "the data does not show it, so it is not there" mistake that once deleted the
    # 2-player dice rule.
    assert len(catalogue.STARTING_RESOURCE_CARDS) == 9
    backs = sorted(c["back"] for c in catalogue.STARTING_RESOURCE_CARDS)
    assert backs == ["food"] * 3 + ["iron"] * 3 + ["pearl"] * 3
    # THREE starting action cards, one per worker -- not the six we used to generate.
    assert len(catalogue.STARTING_ACTION_CARDS) == 3
    workers = sorted(e["worker"] for c in catalogue.STARTING_ACTION_CARDS
                     for e in c["light"] if e["op"] == "worker_action")
    assert workers == ["courtiers", "gardeners", "warriors"]
    assert cards.CARD_COUNTS["starting_resource"] == 9
    assert cards.CARD_COUNTS["starting_action"] == 3


def test_a_decree_is_a_lantern_reward_and_nothing_else():
    # All three carry no action block at all, which is also why the printed
    # `Gain <icon> Decree Card` texts name exactly coin, seal and vp.
    icons = sorted(c["lantern"]["op"] for c in catalogue.DECREE_CARDS)
    assert icons == ["gain"] * 3
    assert all(not c["blocks"] for c in catalogue.DECREE_CARDS)


def test_the_diamond_cards_are_the_cards_own_and_not_a_second_list():
    assert cards.DIAMOND_STEWARDS == (1, 3, 6, 8, 11, 14)
    assert cards.DIAMOND_DIPLOMATS == (1, 9, 12)
    assert sum(1 for c in catalogue.STEWARDS if c["diamond"]) == 6
    assert sum(1 for c in catalogue.DIPLOMATS if c["diamond"]) == 3


def test_every_block_records_which_rows_it_covers():
    # The castle die-colour rule selects a ROW, so this field is what that rule will read.
    # It is carried now so the rule can land without re-deriving the catalogue.
    rows = {"top", "middle", "bottom"}
    for card in catalogue.STEWARDS + catalogue.DIPLOMATS:
        assert card["blocks"], card["id"]
        for block in card["blocks"]:
            assert block["type"] in ("light", "dark"), card["id"]
            assert block["position"], card["id"]
            assert set(block["position"]) <= rows, card["id"]


def test_a_card_that_grants_any_resource_asks_instead_of_picking_one():
    # Ten of the sixty-eight cards say "gain a resource" without naming it. Resolving
    # that silently -- always food, say -- is the kind of divergence that never surfaces
    # as an error, so the generator keeps it as "any" and the engine must ASK.
    anyone = [c for c in cards.ALL_CARDS.values()
              for e in (c.get("light") or []) + (c.get("dark") or [])
              if e.get("op") == "gain" and e.get("resource") == "any"]
    assert anyone, "the catalogue should carry unnamed-resource gains"

    game = engine.new_game(["a", "b"], seed=3)
    pid = game["draft_queue"][0]
    engine._apply_effects(game, pid, [{"op": "gain", "resource": "any", "amount": 2}],
                          source="test")
    assert len(game["choice_queue"]) == 2, "two units means two separate picks"
    assert engine._promote_choice(game, pid)
    assert game["pending"]["kind"] == "choose_resource"

    before = dict(engine._player(game, pid)["resources"])
    moves = engine.legal_moves(game, pid)
    assert {m["resource"] for m in moves} == set(cards.RESOURCES)
    ok, err = engine.apply_move(game, pid, {"type": "choose_resource", "resource": "pearl"})
    assert ok, err
    assert engine._player(game, pid)["resources"]["pearl"] == before["pearl"] + 1
    # ...and the second pick is offered straight after, rather than being lost.
    assert game["pending"]["kind"] == "choose_resource"
    assert len(game["choice_queue"]) == 1


def test_the_draft_stays_open_until_a_granted_resource_is_chosen():
    # draft_queue is reversed(turn_order), so the LAST seat to draft is turn_order[0] --
    # the player about to take turn 1. Closing the draft over their unresolved choice
    # left it pending into the play phase and then handed them an `end_turn` for a turn
    # they had not taken.
    game = engine.new_game(["a", "b", "c"], seed=7)
    saw_choice = False
    for _ in range(40):
        if game["phase"] != "draft":
            break
        pending = game.get("pending") or {}
        if pending.get("kind") == "choose_resource":
            saw_choice = True
            assert game["phase"] == "draft", "the draft must not close over an owed pick"
            ok, err = engine.apply_move(
                game, pending["pid"], {"type": "choose_resource", "resource": "iron"})
            assert ok, err
            continue
        ok, err = engine.apply_move(game, game["draft_queue"][0],
                                    {"type": "draft", "index": 0})
        assert ok, err
    assert saw_choice, "seed 7 deals a card that grants an unnamed resource"
    assert game["phase"] == "play"
    assert not game.get("choice_queue")
    # The first turn is a real turn, not an `end_turn` left over from the draft.
    assert game["pending"] is None or game["pending"].get("kind") != "end_turn"


def test_a_worker_action_pays_the_currency_its_card_names():
    # A castle card charges SEALS to repeat a worker action; a yard tile charges COINS.
    # Both arrive as the same `qty` beside an icon, so a cost that lost its currency
    # would bill a tile's 3 coins to the seal track.
    game = engine.new_game(["a", "b"], seed=5)
    while game["phase"] == "draft":
        pending = game.get("pending") or {}
        if pending.get("kind") == "choose_resource":
            engine.apply_move(game, pending["pid"],
                              {"type": "choose_resource", "resource": "food"})
            continue
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["seals"], p["coins"] = 3, 9
    p["workers"]["warriors"]["domain"] = 2

    engine._apply_effects(game, pid, [{"op": "worker_action", "worker": "warriors",
                                       "cost": {"seals": 1}}], source="test")
    assert (p["seals"], p["coins"]) == (2, 9), "a seal price comes off the seals"
    engine._apply_effects(game, pid, [{"op": "worker_action", "worker": "warriors",
                                       "cost": {"coins": 3}}], source="test")
    assert (p["seals"], p["coins"]) == (2, 6), "a coin price comes off the coins"


def test_the_generator_refuses_a_template_it_has_no_op_for():
    # The whole contract: an unknown effect stops the build instead of being dropped.
    try:
        build_catalogue.translate({"description": "Summon a dragon", "args": {}}, "nowhere")
    except SystemExit as exc:
        assert "Summon a dragon" in str(exc) and "nowhere" in str(exc)
    else:
        raise AssertionError("an unknown template must stop the build")


def test_the_source_json_and_the_module_describe_the_same_cards():
    raw = json.load(open(os.path.join(_PKG, "data", "base_catalogue.json"), encoding="utf-8"))
    stewards = sum(1 for d in raw.values()
                   if d.get("kind") == "card" and d.get("type") == "steward")
    assert stewards == len(catalogue.STEWARDS)
    assert len(raw) == 68

# --------------------------------------------------------------------------------------
# The castle Die tiles: which rows of a room's card a die actually resolves.
# --------------------------------------------------------------------------------------

def _played(seats=3, seed=11):
    game = engine.new_game([f"p{i}" for i in range(seats)], seed=seed)
    while game["phase"] == "draft":
        pending = game.get("pending") or {}
        if pending.get("kind") == "choose_resource":
            engine.apply_move(game, pending["pid"],
                              {"type": "choose_resource", "resource": "food"})
            continue
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    return game


def test_a_room_holds_one_die_tile_per_action_block():
    # The two halves of this were derived from DIFFERENT evidence and agree: every
    # printed Steward card has 3 action blocks and every Diplomat 2 (from the card
    # catalogue), and a steward room holds 3 Die tiles and a diplomat room 2 (from the
    # colour sets the corpus offers, via `die_tile_bag`). One tile per block.
    for seed in range(8):
        game = engine.new_game(["a", "b", "c"], seed=seed)
        for room in game["castle"]["rooms"]:
            assert len(room["tiles"]) == len(room["card"]["blocks"]), room["id"]
        assert [len(r["tiles"]) for r in game["castle"]["rooms"]] == list(
            engine.ROOM_TILE_COUNT)


def test_the_castle_tiles_and_the_well_tiles_are_the_whole_bag():
    # 13 in the castle and 2 at the Well, and the colours still total five of each.
    for seed in range(8):
        game = engine.new_game(["a", "b", "c"], seed=seed)
        laid = [t["color"] for room in game["castle"]["rooms"] for t in room["tiles"]]
        laid += [t["color"] for t in game["well_tiles"]]
        assert len(laid) == 15
        assert sorted(collections.Counter(laid).values()) == [5, 5, 5]


def test_no_room_is_ever_all_one_colour():
    # A monochrome room would be a DEAD room: two of the three die colours would resolve
    # nothing in it at all. The printed setup moves a tile on rather than allow it, and
    # the corpus agrees -- a diplomat room showed exactly two distinct colours 40 times
    # out of 40, and a steward room two or three but never one.
    for seed in range(40):
        game = engine.new_game(["a", "b", "c"], seed=seed)
        for room in game["castle"]["rooms"]:
            colours = {t["color"] for t in room["tiles"]}
            assert len(colours) > 1, (seed, room["id"], colours)


def test_a_die_resolves_every_block_whose_tile_matches_its_colour():
    # The rule, and the thing the engine used to get wrong: it picked `light` or `dark`
    # from `(die value + room index) % 2`, which made the die's COLOUR meaningless in the
    # castle and its VALUE decide the action -- the printed game is the other way round.
    game = _played()
    room = game["castle"]["rooms"][0]
    room["tiles"][0]["color"] = "coral"
    room["tiles"][1]["color"] = "black"
    room["tiles"][2]["color"] = "coral"
    blocks = room["card"]["blocks"]
    assert engine._fired_blocks(room, {"color": "coral"}) == [blocks[0], blocks[2]]
    assert engine._fired_blocks(room, {"color": "black"}) == [blocks[1]]
    assert engine._fired_blocks(room, {"color": "white"}) == []
    # The die's VALUE must not enter into it.
    for value in range(1, 7):
        assert engine._fired_blocks(room, {"color": "black", "value": value}) == [blocks[1]]


def test_a_colour_on_two_tiles_performs_both_rows():
    # Not a special case bolted on -- it falls out of matching every tile, and the corpus
    # shows it: 13 rooms fired two slots for one colour, always a room whose tiles showed
    # only two distinct colours.
    game = _played()
    room = game["castle"]["rooms"][0]
    for tile in room["tiles"]:
        tile["color"] = "coral"
    room["tiles"][1]["color"] = "white"
    pid = game["turn_pid"]
    fired = engine._fired_blocks(room, {"color": "coral"})
    assert len(fired) == 2, "two coral tiles, two rows"
    assert len(engine._fired_blocks(room, {"color": "white"})) == 1


def test_a_die_may_only_enter_a_room_that_shows_its_colour():
    # Without this a die could be placed where it resolves nothing, which is not a move
    # the printed game offers.
    game = _played()
    pid = game["turn_pid"]
    for room in game["castle"]["rooms"]:
        for tile in room["tiles"]:
            tile["color"] = "black"
        room["tiles"][0]["color"] = "white"   # keep every room legal for white
    game["castle"]["rooms"][0]["tiles"][0]["color"] = "black"   # ...except room 0
    game["pending"] = {"pid": pid, "kind": "place_die",
                       "die": {"color": "white", "value": 6}}
    spaces = {m.get("space") for m in engine.legal_moves(game, pid)
              if m["type"] == "place_die"}
    assert "castle:0" not in spaces, "no white tile there"
    assert "castle:1" in spaces


def test_a_game_saved_before_the_die_tiles_still_resolves_its_rooms():
    # Expand/contract: a room on an older save has no `tiles`, and refusing to resolve it
    # would silently make every castle placement do nothing. Fall back to the old
    # light/dark pick instead.
    game = _played()
    pid = game["turn_pid"]
    for room in game["castle"]["rooms"]:
        room.pop("tiles", None)
    game["pending"] = {"pid": pid, "kind": "place_die",
                       "die": {"color": "coral", "value": 6}}
    spaces = {m.get("space") for m in engine.legal_moves(game, pid)
              if m["type"] == "place_die"}
    assert "castle:0" in spaces, "an untiled room stays open"
    before = dict(engine._player(game, pid)["resources"])
    game["last_move"] = {}          # _resolve_castle stamps the card it resolved
    engine._resolve_castle(game, pid, 0, {"color": "coral", "value": 2})
    after = dict(engine._player(game, pid)["resources"])
    p = engine._player(game, pid)
    assert (after != before or p["coins"] or p["seals"] or game["log"]), "something resolved"


def test_a_die_always_has_somewhere_legal_to_go():
    # The colour rule closes rooms to a die, so it is worth pinning that it can never
    # close ALL of them: the Well takes any colour and never fills up, and Outside the
    # Walls is colour-blind too. A die with no destination would stall the turn forever.
    for seats in (2, 3, 4):
        for seed in (5, 17, 41, 93):
            game = _played(seats, seed)
            pid = game["turn_pid"]
            for colour in cards.COLORS:
                for value in (1, 6):
                    game["pending"] = {"pid": pid, "kind": "place_die",
                                       "die": {"color": colour, "value": value}}
                    moves = [m for m in engine.legal_moves(game, pid)
                             if m["type"] == "place_die"]
                    assert moves, (seats, seed, colour, value)


def test_an_outside_space_only_pauses_the_turn_if_it_has_an_option():
    # `_outside_offer` keys on WHICH space the die went to -- left offers Gardener or
    # Courtier, right offers Warrior or Courtier -- so the probe that decides whether to
    # raise the decision has to name the space too. Asking without it reported choices
    # the real pending did not have, and the turn stopped on a decision with no options.
    # A random-play plan deadlocked on exactly that.
    game = _played(2, 41)
    pid = game["turn_pid"]
    for space in ("outside:0", "outside:1"):
        probe = {"pid": pid, "kind": "outside_worker", "space": space}
        spaceless = {"pid": pid, "kind": "outside_worker"}
        offered = engine.legal_moves({**game, "pending": probe}, pid)
        # Whatever the spaceless probe says, the real pending must never be raised with
        # nothing to choose.
        game2 = copy.deepcopy(game)
        game2["pending"] = probe
        assert bool(engine.legal_moves(game2, pid)) == bool(offered)


def test_a_rooms_die_tiles_ship_their_colour_and_not_their_reward():
    # A Die tile is double-sided and a castle tile lies COLOUR side up, so its reward is
    # face down and must not reach a client. The tiles are nested inside castle.rooms,
    # and a nested copy of hidden state is exactly how this repo's redaction was defeated
    # once before -- so assert against the SERIALIZED payload of a real game, not a
    # synthetic dict.
    game = _played(3, 23)
    view = engine.player_view(game, game["turn_pid"])
    for room in view["castle"]["rooms"]:
        assert room["tiles"], room["id"]
        for tile in room["tiles"]:
            assert tile["color"], "the colour IS public board state"
            assert tile["reward"] is None, "the reward face is down"
    # ...and the rewards are genuinely absent from the CASTLE section of the wire, not
    # merely nulled beside a copy that still carries them. Scoped to the castle on
    # purpose: a WELL tile lies reward side UP, so its reward is public and appears in
    # the payload legitimately.
    rewards = {t["reward"] for room in game["castle"]["rooms"] for t in room["tiles"]
               if t.get("reward")}
    assert rewards, "the tiles do have reward faces to hide"
    castle_blob = json.dumps(view["castle"])
    for reward in rewards:
        assert f'"reward": "{reward}"' not in castle_blob


# --------------------------------------------------------------------------------------
# A courtier climbing INTO a room takes that room's card. This is the loop that fills the
# Lantern Area, and the engine did not have it at all.
# --------------------------------------------------------------------------------------

def _climber(seats=3, seed=31):
    game = _played(seats, seed)
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["workers"]["courtiers"]["gate"] = 2
    p["resources"]["pearl"] = 7
    return game, pid


def test_a_climb_names_the_room_it_enters():
    # The corpus is unambiguous: across 414 climbs where both were observable, the card
    # gained was the card standing in the room climbed into, every single time.
    game, pid = _climber()
    moves = engine._climb_moves(game, pid)
    first = [m for m in moves if m["to"] == "floor1"]
    assert {m["room"] for m in first} == set(engine.FLOOR_ROOMS["floor1"])
    second = [m for m in moves if m["to"] == "floor2"]
    assert {m["room"] for m in second} == set(engine.FLOOR_ROOMS["floor2"])
    # The Daimyo hall holds no room card, so a climb there names no room.
    assert all("room" not in m for m in moves if m["to"] == "daimyo")


def test_climbing_into_a_room_takes_its_card_and_refills_the_room():
    game, pid = _climber()
    p = engine._player(game, pid)
    room = game["castle"]["rooms"][0]
    standing = room["card"]
    had = copy.deepcopy(p.get("action_card"))
    before_lantern = len(p["lantern"])
    deck_before = len(game["steward_deck"])

    move = next(m for m in engine._climb_moves(game, pid)
                if m["to"] == "floor1" and m["room"] == 0)
    game["pending"] = {"pid": pid, "kind": "courtier_destination"}
    ok, err = engine.apply_move(game, pid, move)
    assert ok, err

    assert p["action_card"]["id"] == standing["id"], "the room's card is now ours"
    assert room["card"] is not None and room["card"]["id"] != standing["id"], "refilled"
    assert len(game["steward_deck"]) == deck_before - 1
    # ...and the card it replaced went to the Lantern Area, which is the whole point:
    # the Lantern is what the left end of a bridge pays out, and it used to hold only
    # the card drafted at setup.
    assert len(p["lantern"]) == before_lantern + 1
    assert p["lantern"][-1]["card"] == had["id"]


def test_the_lantern_reward_is_the_cards_own_printed_one():
    # Every card carries its own lantern line; the Lantern Area stores the {icon, amount}
    # shape the resolver already reads, so this maps onto that rather than inventing a
    # second vocabulary.
    for card in catalogue.STEWARDS + catalogue.DIPLOMATS + catalogue.DECREE_CARDS:
        entry = engine._lantern_entry(card)
        assert entry, card["id"]
        assert entry["amount"] >= 1
        assert entry["icon"] in ("coin", "seal", "vp", "influence") or \
            entry["icon"] in cards.RESOURCES, entry
    assert engine._lantern_entry({"lantern": None}) is None


def test_a_cached_bundle_can_still_climb_during_the_deploy_window():
    # Pages caches a bundle ~10 minutes, and every move is checked with
    # `move in legal_moves(...)` -- so a climb without the new `room` field is not
    # slightly wrong, it is refused outright and the player is told their own legal
    # action is illegal.
    game, pid = _climber()
    room0 = game["castle"]["rooms"][0]["card"]["id"]
    old_shape = {"type": "courtier_destination", "from": "gate", "to": "floor1", "cost": 2}
    game["pending"] = {"pid": pid, "kind": "courtier_destination"}
    ok, err = engine.apply_move(game, pid, dict(old_shape))
    assert ok, err
    # it lands in the first room on that floor, which is the only thing a client that did
    # not know about rooms could have meant
    assert engine._player(game, pid)["action_card"]["id"] == room0


def test_a_room_with_no_card_left_is_not_offered_to_a_climber():
    game, pid = _climber()
    for i in engine.FLOOR_ROOMS["floor1"]:
        game["castle"]["rooms"][i]["card"] = None
    rooms = {m.get("room") for m in engine._climb_moves(game, pid) if m["to"] == "floor1"}
    assert rooms == set() or rooms == {None}


def test_the_manifest_matches_the_publishers_own_component_list():
    """Pin the box's printed counts to Devir's published component list.

    Source: devir.world/thewhitecastle/components_ENG.html (the publisher's own page).
    Two of these were wrong and both were wrong in the same direction -- inferred from
    what the corpus happened to show rather than looked up:

      * `starting_action_cards` is 6 PRINTED CARDS over 3 DESIGNS. The corpus shows 3
        distinct `typeArg`s and 7 distinct `id`s, which is the copy-vs-design split this
        package already documents -- 2 copies of each design. Reading 3 off the corpus and
        writing it into the box count conflated the two.
      * `daimyo_cards` is 9, not 3. `cards.py` had 9 all along; only the manifest said 3.
    """
    manifest = json.load(open(os.path.join(_PKG, "data", "base_game_manifest.json"),
                              encoding="utf-8"))["components"]
    published = {
        "player_aids": 4, "starting_action_cards": 6, "starting_resource_cards": 9,
        "decree_cards": 3, "steward_cards": 15, "diplomat_cards": 12, "daimyo_cards": 9,
        "plant_gardens": 5, "stone_gardens": 5, "yard_tiles": 8, "die_tiles": 15,
    }
    for key, count in published.items():
        assert manifest[key] == count, key
    # The catalogue carries DESIGNS, which is what the engine deals from.
    assert len(catalogue.STARTING_ACTION_CARDS) == 3, "three designs, six cards"
    assert len(cards.DAIMYO) == manifest["daimyo_cards"]


def test_a_die_tiles_reward_vocabulary_is_the_published_one():
    # Devir's rules list what a Die tile's benefit side can show: resources (food, iron,
    # mother-of-pearl), coins, Clan Points, Daimyo Seals, Influence advancement, and a
    # resource of your choice. Ours is that set -- which is worth pinning because the
    # individual tiles' faces are NOT published and ours are generated.
    assert set(cards.DIE_TILE_REWARDS) == {
        "coin", "resource", "food", "iron", "pearl", "seal", "influence", "vp"}
