"""Hold the engine to The White Castle as Board Game Arena actually plays it.

The fixture these read, `data/bga_ground_truth.json`, is DERIVED rather than typed:
`tools/bga_parity.py` reads 20 base-game BGA logs and, before writing anything, recomputes
all 70 final scoreboards from the formulas it is about to record. So a row here is not "we
believe the rule is X" -- it is "X reproduced real scoreboards, exactly, 70 times".

WHAT THESE TESTS DO NOT COVER, AND WHY THAT MATTERS
---------------------------------------------------
`cards.py` is still placeholder and says so: the stewards, diplomats and daimyo are
generated in loops and their effects are ours, not the printed game's. Everything below is
the BOARD -- geometry, prices, capacity, turn order, scoring -- which is the half that can
be checked against the corpus today. The card effects, the die-colour tiles that decide
which rows of a castle card resolve, and the courtier-takes-the-card loop are the half
that cannot be, and AGENTS.md lists them as open rather than pretending otherwise. A green
run here means the frame is right, not that the game is finished.
"""

from __future__ import annotations

import collections
import json
import os
import random

from games.black_castle import cards, engine

TRUTH = json.load(open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "bga_ground_truth.json"), encoding="utf-8"))


def _pairs(mapping):
    """The fixture's two-part keys ("11 2" -> position 11 cost 2 seals) as tuples."""
    return {tuple(int(part) for part in key.split()): value for key, value in mapping.items()}


def test_the_fixture_is_the_verified_one():
    # If the reconstruction ever stops being exact the fixture is a set of guesses, and
    # every assertion below becomes a test of those guesses rather than of the game.
    assert TRUTH["reconstruction"] == {"base_logs": 20, "seats_exact": 70, "seats_wrong": 0}


def test_final_scoring_matches_every_category_bga_reports():
    game = engine.new_game(["a", "b"], seed=5)
    a, b = game["turn_order"]
    pa = game["players"][a]
    pa["points"] = 4
    pa["coins"], pa["seals"] = 7, 3          # 10 // 5 = 2
    pa["resources"] = {"food": 7, "iron": 3, "pearl": 2}   # 2 + 1 + 0
    pa["influence"] = 12                      # third season
    pa["workers"]["courtiers"] = {"domain": 0, "gate": 1, "floor1": 1, "floor2": 2, "daimyo": 1}
    # Two warriors in the 2-point yard and one in a 1-point yard, times four courtiers
    # INSIDE the castle -- the one at the gate does not multiply anything.
    pa["yards"] = [{"vp": 2}, {"vp": 2}, {"vp": 1}]
    pa["workers"]["warriors"] = {"domain": 2, "yard_pool": 0, "yard": 3}
    pa["gardens"] = [{"vp": 9}, {"vp": 1}]
    pa["workers"]["gardeners"] = {"domain": 3, "garden_pool": 0, "garden": 2}
    engine._score_game(game)
    assert game["scores"][a] == 4 + 2 + 3 + 6 + (1 + 3 + 12 + 10) + (5 * 4) + 10
    assert game["winner"] == a and game["scores"][b] == 0


def test_passage_of_time_scores_by_season_exactly_as_the_corpus_does():
    # Each key is (space the marker finished on, points BGA awarded for it); the value is
    # how many seats ended there, which is evidence rather than part of the rule.
    observed = list(_pairs(TRUTH["passage_of_time"]["position_to_points"]))
    assert len(observed) >= 12, "the fixture carries too few track observations"
    for position, points in observed:
        assert engine._influence_points(position) == points, position
    # Every space the corpus ever showed, not just the ones a seat finished on.
    assert [engine._influence_points(i) for i in range(0, 16)] == (
        [0] * 6 + [3] * 5 + [6] * 4 + [10])


def test_the_three_checkpoints_charge_one_two_and_three_seals():
    # Each key is (space entered, seals paid) and the value counts the crossings, so the
    # keys alone are the price list -- and a second price for one space would show up
    # here as a duplicate space rather than being silently averaged away.
    crossings = list(_pairs(TRUTH["passage_of_time"]["checkpoint_seals"]))
    assert len({space for space, _ in crossings}) == len(crossings) == 3
    assert engine.CHECKPOINT_COSTS == dict(crossings) == {6: 1, 11: 2, 15: 3}
    # A marker stops dead at the space BEFORE a gate it cannot pay for, which is what BGA
    # reports as a move of zero steps.
    for space in TRUTH["passage_of_time"]["blocked_at"]:
        assert int(space) + 1 in engine.CHECKPOINT_COSTS


def test_a_marker_without_seals_stops_at_the_checkpoint():
    game = engine.new_game(["a", "b"], seed=6)
    pid = game["turn_order"][0]
    p = game["players"][pid]
    p["influence"], p["seals"] = 5, 0
    assert engine._advance_influence(game, pid, 3) == 0
    assert p["influence"] == 5
    p["seals"] = 1
    assert engine._advance_influence(game, pid, 3) == 3
    assert (p["influence"], p["seals"]) == (8, 0)


def test_a_room_and_an_outside_space_stack_two_dice_at_three_or_four_seats():
    # BGA prints two on every castle room AND on both Outside the Walls spaces. The
    # corpus shows dice actually reaching two on all of them -- the Outside spaces 114
    # times, which is how many placements the engine used to refuse for holding one.
    for space, row in TRUTH["action_spaces"].items():
        if space.startswith(("steward-", "diplomat-", "outside-the-walls-")):
            assert row["max_dice"] == engine.CASTLE_ROOM_DICE, space
        elif space.startswith("personal-domain:"):
            assert row["max_dice"] == 1, space
    for seats, capacity in ((2, 1), (3, 2), (4, 2)):
        game = engine.new_game([f"p{i}" for i in range(seats)], seed=11)
        while game["phase"] == "draft":
            engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
        pid = game["turn_pid"]
        for space, put in (("castle:0", lambda d: game["castle"]["rooms"][0]
                            .setdefault("dice", []).append(d)),
                           ("outside:0", lambda d: game.setdefault("outside", {})
                            .setdefault("0", []).append({"pid": pid, "die": d}))):
            for filled in range(capacity + 1):
                game["pending"] = {"pid": pid, "kind": "place_die",
                                   "die": {"color": "coral", "value": 6}}
                offered = {"type": "place_die", "space": space} in engine.legal_moves(game, pid)
                assert offered == (filled < capacity), (seats, space, filled)
                put({"color": "white", "value": 3})


def test_two_players_cannot_stack_dice_anywhere():
    # A separate 2-player rule, not a smaller board: "in a 1- or 2-player game, dice
    # cannot be stacked on top of other dice in any part of the game". The corpus has no
    # 2-player games at all, so nothing here is derived from it -- and an earlier pass
    # deleted this very check on the reasoning that board printing does not shrink.
    assert engine.SOLO_OR_DUEL_DICE == 1
    two = engine.new_game(["a", "b"], seed=13)
    four = engine.new_game(["a", "b", "c", "d"], seed=13)
    assert (engine._dice_per_space(two), engine._dice_per_space(four)) == (1, 2)


def test_a_personal_domain_row_only_takes_its_own_colour():
    truth = {space.split(":")[1]: row["die_colors"]
             for space, row in TRUTH["action_spaces"].items()
             if space.startswith("personal-domain:")}
    # BGA names the dice red / black / white; the port calls the coral bridge's dice
    # coral. Same three rows, same one-colour rule.
    assert {k: len(v) for k, v in truth.items()} == {"red": 1, "black": 1, "white": 1}
    assert {truth["red"][0], truth["black"][0], truth["white"][0]} == {"red", "black", "white"}

    game = engine.new_game(["a", "b"], seed=12)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    for color in engine.BRIDGE_ORDER:
        game["pending"] = {"pid": pid, "kind": "place_die",
                           "die": {"color": color, "value": 6}}
        rows = {move["space"] for move in engine.legal_moves(game, pid)
                if move["space"].startswith("domain:")}
        assert rows == {f"domain:{color}"}, (color, rows)


def test_a_social_climb_costs_two_pearls_a_floor_and_five_for_two():
    charged = _pairs(TRUTH["worker_costs"]["courtier_climb_pearl_by_levels"])
    # Several courtiers can move in one BGA packet, so the payments read back are counts
    # rather than a clean table -- take the price the overwhelming majority paid.
    for levels in (1, 2):
        rows = {cost: n for (lv, cost), n in charged.items() if lv == levels}
        assert max(rows, key=rows.get) == engine.CLIMB_COSTS[levels], (levels, rows)

    game = engine.new_game(["a", "b"], seed=15)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = game["players"][pid]
    p["resources"]["pearl"] = 7
    p["workers"]["courtiers"] = {"domain": 1, "gate": 1, "floor1": 1, "floor2": 2, "daimyo": 0}
    game["pending"] = {"pid": pid, "kind": "courtier_destination"}
    assert {(m["from"], m["to"], m["cost"]) for m in engine.legal_moves(game, pid)} == {
        ("gate", "floor1", 2), ("gate", "floor2", 5),
        ("floor1", "floor2", 2), ("floor1", "daimyo", 5),
        ("floor2", "daimyo", 2),
    }
    assert engine.apply_move(game, pid, {"type": "courtier_destination", "from": "floor2",
                                         "to": "daimyo", "cost": 2}) == (True, None)
    assert p["resources"]["pearl"] == 5
    assert p["workers"]["courtiers"]["daimyo"] == 1


def test_an_audience_at_the_gate_costs_two_coins():
    assert list(TRUTH["worker_costs"]["courtier_gate_coins"]) == ["2"]


def test_the_training_yards_are_the_printed_three():
    truth = {int(k): v for k, v in TRUTH["training_yards"].items()}
    assert [(row["iron_cost"], row["point_value"]) for _, row in sorted(truth.items())] \
        == list(cards.TRAINING_YARD_PRICES)
    # And every warrior placement in the corpus paid exactly that yard's iron.
    for (yard, iron), _ in _pairs(TRUTH["worker_costs"]["warrior_iron_by_yard"]).items():
        assert iron == truth[yard]["iron_cost"]
    assert [(y["cost"], y["vp"]) for y in cards.TRAINING_YARDS] == list(cards.TRAINING_YARD_PRICES)


def test_the_garden_deck_is_the_printed_price_ladder():
    truth = sorted((row["type"], row["food_cost"], row["point_value"])
                   for row in TRUTH["gardens"])
    assert len(truth) == 10
    ours = sorted((("plant" if card["icon"] == "plant" else "rock"), card["cost"], card["vp"])
                  for card in cards.GARDENS)
    assert ours == truth
    # Food cost c always pays 2c-1, which is the shape of the ladder rather than ten
    # separately memorised numbers.
    assert all(points == 2 * cost - 1 for _, cost, points in truth)


def test_a_gardener_can_reach_both_plots_on_a_bridge_but_a_plot_only_once():
    game = engine.new_game(["a", "b"], seed=17)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = game["players"][pid]
    p["resources"]["food"] = 7
    p["workers"]["gardeners"] = {"domain": 3, "garden_pool": 2, "garden": 0}
    game["pending"] = {"pid": pid, "kind": "worker_destination", "worker": "gardeners"}
    moves = engine.legal_moves(game, pid)
    assert {(m["index"], m["kind"]) for m in moves} == {
        (i, kind) for i in range(3) for kind in ("plant", "stone")}

    stone = next(m for m in moves if m["index"] == 0 and m["kind"] == "stone")
    assert engine.apply_move(game, pid, stone) == (True, None)
    assert game["gardens"][0]["occupants"] == {"plant": [], "stone": [pid]}
    game["pending"] = {"pid": pid, "kind": "worker_destination", "worker": "gardeners"}
    again = {(m["index"], m["kind"]) for m in engine.legal_moves(game, pid)}
    assert (0, "stone") not in again
    assert (0, "plant") in again


def test_the_next_round_is_led_by_the_marker_on_top_of_the_pile():
    # 60 of 60 turn-order changes in the corpus follow this and nothing else: position
    # first, and on a tie the clan that stepped onto the space most recently.
    assert TRUTH["turn_order"] == {"stack_top_first": 60, "mismatches": 0}
    game = engine.new_game(["a", "b", "c"], seed=21)
    first, second, third = game["turn_order"]
    for pid in (second, first):          # second arrives, then first lands on top of it
        game["players"][pid]["influence"] = 0
        engine._advance_influence(game, pid, 1)
    game["players"][third]["influence"] = 3
    game["round"] = 1
    engine._end_round(game)
    assert game["turn_order"] == [third, first, second]


def test_the_board_offers_exactly_the_base_games_action_spaces():
    expected = {"well": 1, "steward-1": 3, "steward-2": 3, "steward-3": 3,
                "diplomat-1": 4, "diplomat-2": 4,
                "outside-the-walls-1": 5, "outside-the-walls-2": 5,
                "personal-domain:red": 6, "personal-domain:black": 6,
                "personal-domain:white": 6}
    assert {k: v["value"] for k, v in TRUTH["action_spaces"].items()} == expected
    # The Tea Fields and the Outskirts of Himeji are Matcha, and the derivation excludes
    # the expansion logs -- if either ever appears here the corpus split has broken.
    assert not any("tea-fields" in k or "outskirts" in k for k in TRUTH["action_spaces"])

    game = engine.new_game(["a", "b"], seed=23)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    for space, row in TRUTH["action_spaces"].items():
        if space.startswith("personal-domain:"):
            continue
        ours = ("well" if space == "well" else
                f"castle:{int(space[-1]) - 1}" if space.startswith("steward-") else
                f"castle:{int(space[-1]) + 2}" if space.startswith("diplomat-") else
                f"outside:{int(space[-1]) - 1}")
        assert engine._die_value_target(game, ours) == row["value"], (space, ours)
    for color in engine.BRIDGE_ORDER:
        assert engine._die_value_target(game, f"domain:{color}") == 6


def test_the_caps_on_what_a_clan_can_hold():
    assert TRUTH["caps"] == {"seals": 5, "resources": 7, "coins": None}
    assert (engine.MAX_SEALS, engine.MAX_RESOURCE) == (5, 7)


def test_the_round_and_dice_structure():
    structure = TRUTH["structure"]
    assert (engine.ROUND_COUNT, engine.TURNS_PER_ROUND) == (
        structure["rounds"], structure["turns_per_player_per_round"])
    for seats, per_color in structure["dice_per_color"].items():
        game = engine.new_game([f"p{i}" for i in range(int(seats))], seed=29)
        assert {color: len(dice) for color, dice in game["bridges"].items()} == {
            color: per_color for color in engine.BRIDGE_ORDER}
        # Ascending left to right, which is what makes "take an end die" a real choice.
        assert all([die["value"] for die in game["bridges"][color]] ==
                   sorted(die["value"] for die in game["bridges"][color])
                   for color in engine.BRIDGE_ORDER)


def test_a_cached_bundle_can_still_climb_and_plant_during_the_deploy_window():
    # Pages serves the previous bundle for about ten minutes after a push, and every move
    # is validated with `move in legal_moves(...)` -- so a move shape that grew a field is
    # not degraded for that window, it is refused. Both of the shapes that grew one on
    # this change must still resolve to the right action.
    game = engine.new_game(["a", "b"], seed=31)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = game["players"][pid]

    p["resources"]["pearl"] = 5
    p["workers"]["courtiers"] = {"domain": 2, "gate": 1, "floor1": 0, "floor2": 2, "daimyo": 0}
    game["pending"] = {"pid": pid, "kind": "courtier_destination"}
    # The old client sent no `from`, and priced floor2 -> daimyo at 5 rather than 2.
    assert engine.apply_move(game, pid, {"type": "courtier_destination",
                                         "to": "daimyo", "cost": 5}) == (True, None)
    assert p["workers"]["courtiers"]["daimyo"] == 1
    assert p["resources"]["pearl"] == 3, "the old client's stale price must not be charged"

    p["resources"]["food"] = 7
    p["workers"]["gardeners"] = {"domain": 4, "garden_pool": 1, "garden": 0}
    game["pending"] = {"pid": pid, "kind": "worker_destination", "worker": "gardeners"}
    assert engine.apply_move(game, pid, {"type": "worker_destination",
                                         "worker": "gardeners", "index": 1}) == (True, None)
    assert game["gardens"][1]["occupants"]["plant"] == [pid]


def test_a_game_saved_before_the_six_plots_still_loads_and_plays():
    game = engine.new_game(["a", "b"], seed=33)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = game["players"][pid]
    # What a blob written by the previous build looks like: one flat occupant list per
    # bridge, and no marker-stack field on any seat.
    for seat in game["players"].values():
        seat.pop("influence_stack", None)
    game.pop("influence_seq", None)
    game["gardens"][0]["occupants"] = [pid]

    p["resources"]["food"] = 7
    p["workers"]["gardeners"] = {"domain": 3, "garden_pool": 2, "garden": 0}
    game["pending"] = {"pid": pid, "kind": "worker_destination", "worker": "gardeners"}
    plots = {(m["index"], m["kind"]) for m in engine.legal_moves(game, pid)}
    # The seat is read as standing on that bridge's Plant card -- the only one it could
    # have reached -- so the Plant plot is taken and the Stone plot is still open.
    assert (0, "plant") not in plots and (0, "stone") in plots
    game["round"] = 1
    engine._end_round(game)   # must not raise on the missing stack field
    assert set(game["turn_order"]) == set(game["players"])


def test_the_well_pays_the_same_thing_every_visit():
    well = TRUTH["well"]["distinct_payouts_within_one_game"]
    one, more = well.get("1", 0), sum(v for k, v in well.items() if k != "1")
    # Fixed, face-up tiles: a game with several visits shows ONE payout signature. Two
    # games read as two, and both are a card effect landing in the same turn with no
    # cardId to tell it apart -- so this asserts the weight of the evidence, not purity,
    # and would still fail outright if the Well were the lottery the port used to run.
    assert one >= 15 and one > 4 * more, well
    assert all("seal+1" in sig for sig in TRUTH["well"]["payout_signatures"])

    game = engine.new_game(["a", "b"], seed=41)
    assert len(game["well_tiles"]) == 2, "two Die tiles are laid at the Well"
    assert all(tile.get("reward") for tile in game["well_tiles"])
    # Nothing at the Well is hidden, so visiting it cannot compromise an undo.
    assert "revealed" not in str(game["well_tiles"])


def test_each_outside_the_walls_space_offers_one_worker_and_the_courtier():
    truth = TRUTH["outside_the_walls"]
    # Read only from the turns that deployed exactly one kind of worker, so a castle card
    # granting a second one cannot muddy it. Those separate with nothing in between: no
    # warrior ever came off the left space, no gardener off the right.
    assert set(truth["1"]) == {"courtier", "gardener"}
    assert set(truth["2"]) == {"courtier", "warrior"}
    assert engine.OUTSIDE_WORKERS == ("gardeners", "warriors")
    assert engine._outside_offer(None, "outside:0") == ("gardeners",)
    assert engine._outside_offer(None, "outside:1") == ("warriors",)

    game = engine.new_game(["a", "b", "c"], seed=43)
    while game["phase"] == "draft":
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = game["players"][pid]
    p["resources"] = {"food": 7, "iron": 7, "pearl": 7}
    p["coins"] = 9
    for index, worker in enumerate(engine.OUTSIDE_WORKERS):
        game["pending"] = {"pid": pid, "kind": "outside_worker", "space": f"outside:{index}"}
        offered = {m["worker"] for m in engine.legal_moves(game, pid)}
        assert offered == {worker, "courtiers"}, (index, offered)


def test_a_two_player_game_leaves_the_diamond_cards_in_the_box():
    truth = TRUTH["diamond_cards"]
    assert sorted(truth["steward"]["diamond"]) == list(cards.DIAMOND_STEWARDS)
    assert sorted(truth["diplomat"]["diamond"]) == list(cards.DIAMOND_DIPLOMATS)
    duel = engine.new_game(["a", "b"], seed=47)
    table = engine.new_game(["a", "b", "c"], seed=47)

    def deck(game, kind):
        rooms = [r["card"] for r in game["castle"]["rooms"] if r["card"]["kind"] == kind]
        return len(game[f"{kind}_deck"]) + len(rooms)
    assert (deck(duel, "steward"), deck(duel, "diplomat")) == (9, 9)
    assert (deck(table, "steward"), deck(table, "diplomat")) == (15, 12)
    assert not any(c.get("diamond") for c in duel["steward_deck"] + duel["diplomat_deck"])


def test_the_effect_vocabulary_left_to_port_is_small_and_enumerated():
    # The size of the remaining job, kept honest. If a later corpus turns up a twelfth
    # template or an `or` conditional, this fails and AGENTS.md is wrong about the scope.
    vocab = TRUTH["effect_vocabulary"]
    assert set(vocab["block_types"]) == {"light", "dark"}, "curtains are Matcha, not base"
    assert set(vocab["conditionals"]) == {"and"}, "no `or` in the base box"
    assert len(vocab["templates"]) == 11, sorted(vocab["templates"])
    assert sum(len(v) for v in vocab["templates"].values()) == 31
    # 19 of those 31 are the amounts on one template -- Gain <icon> <n> -- which is a
    # table, not eleven more behaviours to write.
    gain = next(v for k, v in vocab["templates"].items()
                if k.startswith("Gain ${iconPlaceholder} ${numberOfResources}"))
    assert len(gain) == 19


def test_four_of_the_eight_yard_tiles_are_in_play():
    tiles = TRUTH["yard_tiles"]
    assert len(tiles["faces"]) == 16, "eight tiles, two faces each"
    # Partial payloads list only the yards a prompt needed, so the count per game is a
    # floor; the games that carry all three yards agree on four.
    assert max(int(k) for k in tiles["tiles_in_play_per_game"]) == 4


def test_the_die_tile_bag_is_five_of_each_colour():
    bag = TRUTH["die_tile_bag"]
    assert bag["bags_consistent_with_every_game"] == [{"red": 5, "black": 5, "white": 5}]
    assert bag["games_used"] == 20 and bag["games_needed_for_a_unique_bag"] > 1, (
        "one game cannot fix the bag; if it could, the constraint is not what we think")
    # The geometry is derived, not assumed, and these two rows are the evidence.
    # A diplomat room never showed a third colour, which is what makes it a 2-tile room...
    assert bag["diplomat_rooms_showing_three_colours"] == 0
    assert bag["tiles_per_room"] == {"steward": 3, "diplomat": 2}
    assert bag["castle_tiles"] + bag["well_tiles"] == 15
    # ...and only a 2-tile Well leaves any consistent bag at all, which is the rulebook's
    # own count. A wrong geometry gives an empty set here, not a slightly wrong answer.
    assert bag["bags_if_the_well_took_n_tiles"]["0"] == 0
    assert bag["bags_if_the_well_took_n_tiles"]["1"] == 0
    assert bag["bags_if_the_well_took_n_tiles"]["2"] == 1

    tiles = cards.make_die_tiles(random.Random(5))
    assert len(tiles) == cards.CASTLE_DIE_TILES + cards.WELL_DIE_TILES == 15
    assert collections.Counter(t["color"] for t in tiles) == {c: 5 for c in cards.COLORS}
