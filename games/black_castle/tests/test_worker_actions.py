"""The decisions a card, tile, garden or Daimyo slot leaves a player -- and the rules behind
each, held to the BGA corpus (`data/bga_ground_truth.json`) or the rulebook.

WHY THIS FILE EXISTS
--------------------
Re-deriving the game from 132 BGA games (2026-10-10) found that a card's "Perform Warrior
Action" moved the warrior into a reserve and stopped: nothing ever asked which yard, so it
scored nothing. Over 60 random games, 306 of the 379 warriors and gardeners an effect
deployed were stranded that way. Chasing it turned up the rest of the worker system --
the courtier action, the yard tiles, the gardens, the main-board and Domain actions, the
Domain lines and the Daimyo floor -- each either missing or invented. They share one fix,
a queue of decisions (`choice_queue`), so they share a file.
"""

from __future__ import annotations

import collections
import json
import os
import random

from games.black_castle import bot, cards, engine

TRUTH = json.load(open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "bga_ground_truth.json"), encoding="utf-8"))


def _played(seats=3, seed=31):
    """A game past its draft, with every owed resource pick answered."""
    game = engine.new_game([f"p{i}" for i in range(seats)], seed=seed)
    while game["phase"] == "draft":
        pending = game.get("pending") or {}
        if pending.get("kind") == "choose_resource":
            assert engine.apply_move(game, pending["pid"],
                                     {"type": "choose_resource", "resource": "food"})[0]
            continue
        assert engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})[0]
    return game


def _queue(game, pid, effects):
    game["pending"] = None
    engine._apply_effects(game, pid, effects, source="test")
    assert engine._promote_choice(game, pid)
    return game["pending"]


def _random_games(count, seats_cycle=(2, 3, 4)):
    for seed in range(count):
        seats = seats_cycle[seed % len(seats_cycle)]
        game = engine.new_game([f"p{i}" for i in range(seats)], seed=seed)
        rng = random.Random(seed)
        for _ in range(6000):
            if engine.is_over(game):
                break
            movers = [pid for pid in game["players"] if engine.legal_moves(game, pid)]
            assert movers, ("a live game nobody can move in", seed, game.get("pending"))
            move = bot.choose_move(game, movers[0], seed=rng.randrange(1 << 30))
            assert engine.apply_move(game, movers[0], move) == (True, None), (seed, move)
            engine.validate_state(game)
        assert engine.is_over(game), seed
        yield game


# ------------------------------------------------------------------------- workers

def test_no_worker_is_ever_stranded_in_a_reserve():
    # THE BUG THIS FILE EXISTS FOR. Every warrior and gardener an effect deploys must end
    # up on a yard or a garden -- the reserve is only somewhere an old save parked one.
    placed = collections.Counter()
    for game in _random_games(30):
        for p in game["players"].values():
            assert p["workers"]["warriors"].get("yard_pool", 0) == 0
            assert p["workers"]["gardeners"].get("garden_pool", 0) == 0
            placed["yard"] += p["workers"]["warriors"]["yard"]
            placed["garden"] += p["workers"]["gardeners"]["garden"]
    assert placed["yard"] > 30 and placed["garden"] > 30, placed


def test_a_card_warrior_action_trains_a_warrior_in_a_yard_and_runs_its_tiles():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["resources"]["iron"] = 7
    pending = _queue(game, pid, [{"op": "worker_action", "worker": "warriors", "cost": {}}])
    assert pending["kind"] == "worker_destination"
    yards = [m for m in engine.legal_moves(game, pid) if m["type"] == "worker_destination"]
    assert {m["index"] for m in yards} == {0, 1, 2}
    assert {"type": "skip"} in engine.legal_moves(game, pid), "every granted action can be declined"

    yard = game["yards"][0]
    assert len(yard["tiles"]) == 2, "the 5-iron yard carries two tiles"
    before = engine._player(game, pid)["workers"]["warriors"]["domain"]
    assert engine.apply_move(game, pid, {"type": "worker_destination", "worker": "warriors",
                                         "index": 0}) == (True, None)
    assert p["workers"]["warriors"] == {**p["workers"]["warriors"],
                                        "domain": before - 1}
    assert p["workers"]["warriors"]["yard"] == 1
    assert p["resources"]["iron"] == 2, "5 iron for the outer yard"
    assert len(p["yards"]) == 1 and p["yards"][0]["vp"] == 2


def test_a_worker_action_with_no_worker_left_is_dropped_not_stranded():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["workers"]["warriors"] = {"domain": 0, "yard_pool": 0, "yard": 5}
    game["pending"] = None
    engine._apply_effects(game, pid, [{"op": "worker_action", "worker": "warriors",
                                       "cost": {}}], source="test")
    assert not engine._promote_choice(game, pid)
    assert not game.get("choice_queue")


def test_the_courtier_action_is_an_audience_and_or_a_climb():
    # "Courtiers allow you to carry out up to 2 of these different actions: either just
    # one of them, or both once each." The engine offered them as either/or.
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["coins"], p["resources"]["pearl"] = 5, 7
    _queue(game, pid, [{"op": "worker_action", "worker": "courtiers", "cost": {}}])
    assert game["pending"]["kind"] == "courtier_actions"
    moves = engine.legal_moves(game, pid)
    assert {"type": "audience"} in moves
    assert engine.apply_move(game, pid, {"type": "audience"}) == (True, None)
    assert p["coins"] == 3 and p["workers"]["courtiers"]["gate"] == 1
    # ...and the climb is still on offer, from the courtier that just arrived.
    assert game["pending"]["kind"] == "courtier_actions"
    climb = next(m for m in engine.legal_moves(game, pid)
                 if m["type"] == "courtier_destination" and m["from"] == "gate")
    assert engine.apply_move(game, pid, climb)[0]
    assert p["workers"]["courtiers"]["gate"] == 0
    assert {"type": "audience"} not in engine.legal_moves(game, pid), "an audience once"


def test_an_audience_costs_two_coins_as_the_corpus_shows():
    assert list(TRUTH["worker_costs"]["courtier_gate_coins"]) == [str(engine.AUDIENCE_COINS)]


# ------------------------------------------------------------------------- yard tiles

def test_yard_tiles_are_laid_as_every_bga_game_lays_them():
    layout = TRUTH["yard_tile_layout"]
    assert layout["tiles_per_yard"] == {"2 1 1": sum(layout["tiles_per_yard"].values())}
    expected = {f"yard {y + 1} slot {i + 1} {side}"
                for i, (y, side) in enumerate(cards.YARD_TILE_SLOTS)}
    assert set(layout["slot_faces"]) == expected

    for seed in range(40):
        game = engine.new_game(["a", "b", "c"], seed=seed)
        laid = [(i, t["side"]) for i, y in enumerate(game["yards"]) for t in y["tiles"]]
        assert laid == list(cards.YARD_TILE_SLOTS)
        numbers = [t["tile"] for y in game["yards"] for t in y["tiles"]]
        assert len(set(numbers)) == 4 and set(numbers) <= set(range(1, 9))
        for yard in game["yards"]:
            for tile in yard["tiles"]:
                assert tile["effects"] == cards.YARD_TILE_FACES[f"{tile['tile']}:{tile['side']}"]


def test_yard_tiles_do_not_move_an_old_seed_s_deal():
    # Drawn LAST, so every earlier draw -- castle, decks, tiles, starting pairs -- is the
    # same as before the tiles existed, and a seeded test keeps its game.
    game = engine.new_game(["a", "b", "c"], seed=7)
    assert [r["card"]["id"] for r in game["castle"]["rooms"]]


# ------------------------------------------------------------------------- main board

def test_a_light_background_action_offers_every_light_block_on_the_castle():
    game = _played()
    pid = game["turn_pid"]
    _queue(game, pid, [{"op": "main_board_action", "die_tile": "action-light-background",
                        "cost": {}}])
    offered = {(m["room"], m["block"]) for m in engine.legal_moves(game, pid)
               if m["type"] == "board_action"}
    lights = {(r, b) for r, room in enumerate(game["castle"]["rooms"])
              for b, block in enumerate(room["card"]["blocks"]) if block["type"] == "light"}
    assert offered == lights
    # The corpus: a light-background action offered exactly 8 blocks every one of 68
    # times -- three stewards' two lights and two diplomats' one.
    assert len(lights) == 8


def test_a_die_tile_action_offers_the_blocks_beside_that_colour():
    game = _played()
    pid = game["turn_pid"]
    _queue(game, pid, [{"op": "main_board_action", "die_tile": "action-black-die-tile",
                        "cost": {}}])
    offered = {(m["room"], m["block"]) for m in engine.legal_moves(game, pid)
               if m["type"] == "board_action"}
    beside = {(r, b) for r, room in enumerate(game["castle"]["rooms"])
              for b, tile in enumerate(room["tiles"]) if tile["color"] == "black"}
    assert offered == beside and 1 <= len(beside) <= 5


def test_the_any_tile_action_costs_four_coins_and_offers_all_thirteen():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["coins"] = 3
    game["pending"] = None
    plant1 = next(c for c in cards.GARDENS if c["id"] == "plant-01")
    engine._apply_effects(game, pid, plant1["light"], source="test")
    assert not engine._promote_choice(game, pid), "unaffordable at 3 coins"
    p["coins"] = 4
    _queue(game, pid, plant1["light"])
    offered = [m for m in engine.legal_moves(game, pid) if m["type"] == "board_action"]
    assert len(offered) == 13
    assert engine.apply_move(game, pid, offered[0])[0]
    assert p["coins"] <= 4 - 4 + 10, "four coins paid (the block may pay some back)"


# ------------------------------------------------------------------------- domain lines

def test_a_domain_line_pays_what_its_departed_workers_uncovered():
    # The table the engine implements, held to the corpus's modal payout per line and
    # departed-worker count (right-end dice only, so no Lantern from the bridge).
    bga = {"red": "coral", "black": "black", "white": "white"}
    for key, outcomes in TRUTH["domain_lines"].items():
        line, gone = key.split()
        colour, gone = bga[line], int(gone)
        modal = max(outcomes, key=outcomes.get)
        if outcomes[modal] < 4:
            continue                       # too few sightings to call a mode
        game = _played()
        pid = game["turn_pid"]
        p = engine._player(game, pid)
        p["action_card"] = None
        p["lantern"] = [{"icon": "vp", "amount": 1}]
        worker = engine.DOMAIN_WORKER[colour]
        p["workers"][worker] = {**{k: 0 for k in p["workers"][worker]},
                                "domain": 5 - gone, "gate" if worker == "courtiers"
                                else ("yard" if worker == "warriors" else "garden"): gone}
        for r in cards.RESOURCES:
            p["resources"][r] = 0
        p["coins"], p["seals"], p["points"] = 0, 0, 0
        engine._domain_payout(game, pid, colour)
        got = collections.Counter()
        for r in cards.RESOURCES:
            if p["resources"][r]:
                got[r] = p["resources"][r]
        if p["coins"]:
            got["coin"] = p["coins"]
        if p["seals"]:
            got["seal"] = p["seals"]
        if p["points"]:
            got["lantern"] = p["points"]          # the Lantern fired (it pays 1 vp here)
        mine = " ".join("%s+%d" % kv for kv in sorted(got.items()))
        assert mine == modal, (key, mine, outcomes)


def test_a_domain_line_performs_only_the_action_card_block_for_that_line():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["action_card"] = {"id": "x", "name": "probe", "blocks": [
        {"type": "light", "position": ["top"], "effects": [{"op": "gain", "points": 1}]},
        {"type": "dark", "position": ["middle"], "effects": [{"op": "gain", "points": 10}]},
        {"type": "light", "position": ["bottom"], "effects": [{"op": "gain", "points": 100}]},
    ]}
    for colour, expected in (("coral", 1), ("black", 10), ("white", 100)):
        p["points"] = 0
        p["lantern"] = []
        engine._domain_payout(game, pid, colour)
        assert p["points"] == expected, colour


# ------------------------------------------------------------------------- the Daimyo

def test_daimyo_slots_hold_one_courtier_of_any_clan():
    truth = TRUTH["daimyo"]
    assert truth["placement_prompts"] > 1000
    assert truth["prompts_offering_exactly_the_free_slots"] == truth["placement_prompts"]


def test_every_daimyo_slot_we_print_is_one_the_corpus_shows():
    # Each card's three slots, translated back into the fixture's vocabulary, must appear
    # together in some game -- whole, or as the pair a partial game shows. The one field
    # nobody has seen is named in `DAIMYO_INFERRED` and exempted BY NAME.
    def word(effects):
        op = effects[0]
        if op["op"] == "well_action":
            return "action-well"
        if op["op"] == "lantern_rewards":
            return "action-lantern"
        if op["op"] == "main_board_action":
            return "main_board:" + op["die_tile"]
        if op["op"] == "passage":
            return "passage"
        field = op.get("resource") or {"points": "vp", "seals": "seal", "coins": "coin"}[
            next(k for k in ("points", "seals", "coins") if k in op)]
        amount = op.get("amount") or op.get("points") or op.get("seals") or op.get("coins")
        return f"{field}+{amount}"

    seen = list(TRUTH["daimyo"]["whole_cards_seen"]) + list(TRUTH["daimyo"]["partial_cards_seen"])
    seen = [row.split(" | ") for row in seen]
    for card in cards.DAIMYO:
        mine = [word(slot) for slot in card["slots"]]
        known = [i for i in range(3) if (card["id"], i + 1) not in cards.DAIMYO_INFERRED]
        assert any(all(row[i] == mine[i] for i in known) for row in seen), (card["id"], mine)
    assert len(cards.DAIMYO) == 9 and len(cards.DAIMYO_INFERRED) == 1


def test_reaching_the_daimyo_fires_the_lantern_then_takes_a_slot():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["workers"]["courtiers"] = {"domain": 4, "gate": 0, "floor1": 0, "floor2": 1, "daimyo": 0}
    p["resources"]["pearl"] = 7
    p["lantern"] = [{"icon": "vp", "amount": 3}]
    points = p["points"]
    game["castle"]["daimyo"] = next(c for c in cards.DAIMYO if c["id"] == "daimyo-01")
    game["pending"] = {"pid": pid, "kind": "courtier_destination"}
    assert engine.apply_move(game, pid, {"type": "courtier_destination", "from": "floor2",
                                         "to": "daimyo", "cost": 2}) == (True, None)
    assert p["points"] == points + 3, "the Lantern first"
    assert game["pending"]["kind"] == "daimyo_slot"
    assert {m["slot"] for m in engine.legal_moves(game, pid) if m["type"] == "daimyo_slot"} \
        == {1, 2, 3}
    assert engine.apply_move(game, pid, {"type": "daimyo_slot", "slot": 2}) == (True, None)
    assert p["points"] == points + 3 + 2, "daimyo-01 slot 2 pays 2 Clan Points"
    assert game["castle"]["daimyo_slots"]["2"] == pid


def test_a_full_daimyo_card_gives_nothing_more():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["workers"]["courtiers"] = {"domain": 4, "gate": 0, "floor1": 0, "floor2": 1, "daimyo": 0}
    p["resources"]["pearl"] = 7
    p["lantern"] = []
    game["castle"]["daimyo_slots"] = {"1": "x", "2": "y", "3": "z"}
    game["pending"] = {"pid": pid, "kind": "courtier_destination"}
    assert engine.apply_move(game, pid, {"type": "courtier_destination", "from": "floor2",
                                         "to": "daimyo", "cost": 2}) == (True, None)
    assert game["pending"]["kind"] == "end_turn"


# ------------------------------------------------------------------------- gardens, Well

def test_the_gardens_are_the_printed_ten():
    raw = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "data", "base_catalogue.json"), encoding="utf-8"))
    printed = {(d["foodCost"], d["pointValue"]) for d in raw.values()
               if d.get("type") in ("plant", "rock")}
    assert {(g["cost"], g["vp"]) for g in cards.GARDENS} == printed
    assert all(g["light"] for g in cards.GARDENS), "every garden does something"
    stone = sorted((g["cost"], g["vp"]) for g in cards.GARDENS if g["icon"] == "stone")
    plant = sorted((g["cost"], g["vp"]) for g in cards.GARDENS if g["icon"] == "plant")
    assert stone == sorted(cards.STONE_GARDEN_PRICES)
    assert plant == sorted(cards.PLANT_GARDEN_PRICES)


def test_round_end_garden_decisions_belong_to_the_gardener_and_the_round_waits():
    game = _played(seats=3)
    first, second = game["turn_order"][0], game["turn_order"][1]
    garden = game["gardens"][0]
    garden["stone"] = {"id": "probe", "name": "probe garden", "cost": 0, "vp": 0,
                       "icon": "stone",
                       "light": [{"op": "gain", "resource": "any", "amount": 1}]}
    garden["occupants"] = {"plant": [], "stone": [second]}
    game["bridges"]["coral"] = [{"id": "d", "color": "coral", "value": 3}]
    game["turn_in_round"] = len(game["turn_order"]) * engine.TURNS_PER_ROUND - 1
    game["pending"] = {"pid": game["turn_pid"], "kind": "end_turn"}
    round_before = game["round"]
    assert engine.apply_move(game, game["turn_pid"], {"type": "end_turn"}) == (True, None)
    assert game["round"] == round_before, "the round waits for its gardens"
    assert game["pending"]["pid"] == second and game["pending"]["kind"] == "choose_resource"
    assert engine.apply_move(game, second, {"type": "choose_resource", "resource": "iron"})[0]
    assert game["round"] == round_before + 1
    assert game["turn_pid"] == game["turn_order"][0]
    del first


def test_a_well_coin_tile_pays_one_coin():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    game["well_tiles"] = [{"reward": "coin"}, {"reward": "seal"}]
    coins = p["coins"]
    engine._well_bonus(game, pid)
    assert p["coins"] == coins + 1
    assert any(sig.startswith("coin+1") for sig in TRUTH["well"]["payout_signatures"])
    assert not any("coin+2" in sig for sig in TRUTH["well"]["payout_signatures"])


def test_a_well_resource_tile_asks_which_resource():
    game = _played()
    pid = game["turn_pid"]
    game["well_tiles"] = [{"reward": "resource"}]
    game["choice_queue"] = []
    engine._well_bonus(game, pid)
    assert len(game["choice_queue"]) == 1


# ------------------------------------------------------------------------- the Lantern

def test_the_lantern_takes_a_seal_first_when_it_pays_a_checkpoint():
    # "In the order you choose": with no seals, a Passage step cannot cross into space 6
    # unless the Lantern's seal arrives first.
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["seals"], p["influence"] = 0, 5
    p["lantern"] = [{"icon": "influence", "amount": 1}, {"icon": "seal", "amount": 1}]
    engine._resolve_lantern(game, pid)
    assert (p["influence"], p["seals"]) == (6, 0)


def test_the_lantern_takes_the_step_first_when_the_seal_cap_would_waste_the_seal():
    game = _played()
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["seals"], p["influence"] = engine.MAX_SEALS, 5
    p["lantern"] = [{"icon": "seal", "amount": 1}, {"icon": "influence", "amount": 1}]
    engine._resolve_lantern(game, pid)
    assert (p["influence"], p["seals"]) == (6, engine.MAX_SEALS)
