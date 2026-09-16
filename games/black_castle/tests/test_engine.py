from __future__ import annotations

import copy
import random

from games.black_castle import bot, cards, engine, persist
from core import rooms


def _draft_and_play(game):
    for _ in range(20):
        if game["phase"] != "draft":
            return
        pid = game["draft_queue"][0]
        assert engine.apply_move(game, pid, {"type": "draft", "index": 0})[0]


def test_base_catalogue_counts_and_standard_setup():
    assert len(cards.STEWARDS) == 15
    assert len(cards.DIPLOMATS) == 12
    assert len(cards.DAIMYO) == 9
    assert len(cards.GARDENS) == 10
    assert len(cards.TRAINING_YARDS) == 8
    game = engine.new_game(["a", "b", "c"], seed=7)
    assert game["phase"] == "draft"
    assert len(game["bridges"]["coral"]) == 4
    assert len(game["castle"]["rooms"]) == 5
    assert len(game["gardens"]) == 3
    assert len(game["yards"]) == 4
    assert all(len(p["workers"]["courtiers"]) for p in game["players"].values())
    assert all(values == sorted(values) for values in (
        [die["value"] for die in game["bridges"][color]] for color in engine.BRIDGE_ORDER
    ))


def test_draft_pairs_are_taken_once_and_trade_waits_for_action_resolution():
    game = engine.new_game(["a", "b"], seed=8)
    pid = game["draft_queue"][0]
    option_count = len(game["draft_options"])
    assert engine.apply_move(game, pid, {"type": "draft", "index": 0})[0]
    assert len(game["draft_options"]) == option_count - 1
    assert all(option["resource"]["id"] != game["players"][pid]["starting_pair"]["resource"]
               for option in game["draft_options"])

    _draft_and_play(game)
    pid = game["turn_pid"]
    take = next(move for move in engine.legal_moves(game, pid) if move["type"] == "take_die")
    assert engine.apply_move(game, pid, take)[0]
    game["players"][pid]["resources"]["food"] = 2
    assert engine.apply_move(game, pid, {"type": "convert", "from": "food"})[0] is False


def test_seeded_random_plans_finish_for_two_three_and_four_seats():
    for seat_count in (2, 3, 4):
        game = engine.new_game([f"p{i}" for i in range(seat_count)], seed=41)
        steps = 0
        while not engine.is_over(game):
            pid = game["draft_queue"][0] if game["phase"] == "draft" else (
                game["pending"]["pid"] if game.get("pending") else game["turn_pid"])
            move = bot.choose_move(game, pid, seed=steps)
            assert move is not None
            ok, error = engine.apply_move(game, pid, move)
            assert ok, error
            steps += 1
            assert steps < 300
            engine.validate_state(game)
        assert game["phase"] == "over"
        assert set(game["scores"]) == set(game["players"])


def test_undo_restores_the_position_until_a_well_reveals_hidden_benefit():
    game = engine.new_game(["a", "b"], seed=2)
    _draft_and_play(game)
    pid = game["turn_pid"]
    before = copy.deepcopy(game)
    take = next(m for m in engine.legal_moves(game, pid) if m["type"] == "take_die")
    assert engine.apply_move(game, pid, take)[0]
    assert engine.apply_move(game, pid, {"type": "undo"})[0]
    assert game["turn_pid"] == before["turn_pid"]
    assert game["bridges"] == before["bridges"]
    assert game["turn_undo"] is None

    take = next(m for m in engine.legal_moves(game, pid) if m["type"] == "take_die")
    assert engine.apply_move(game, pid, take)[0]
    place = next(m for m in engine.legal_moves(game, pid)
                 if m["space"] == "well")
    assert engine.apply_move(game, pid, place)[0]
    assert game["turn_undo"]["revealed"] is True
    assert engine.apply_move(game, pid, {"type": "undo"})[0] is False


def test_player_view_redacts_rng_decks_and_other_pending_choices():
    game = engine.new_game(["a", "b"], seed=3)
    _draft_and_play(game)
    pid = game["turn_pid"]
    view = engine.player_view(game, pid)
    assert "rng_state" not in view and "turn_undo" not in view
    assert "steward_deck" not in view and "diplomat_deck" not in view
    assert all(tile["back"] is None and tile["id"] is None and tile["number"] is None
               for tile in view["die_tiles"] if not tile["revealed"])
    game["die_tiles"][0]["revealed"] = True
    assert view["die_tiles"][0]["back"] is None
    assert engine.player_view(game, pid)["die_tiles"][0]["back"] == game["die_tiles"][0]["back"]
    other = next(x for x in game["players"] if x != pid)
    game["pending"] = {"pid": other, "kind": "end_turn", "secret": "hidden"}
    redacted = engine.player_view(game, pid)
    assert redacted["pending"] == {"pid": other, "kind": "end_turn"}
    assert redacted["legal_moves"] == []


def test_well_uses_only_the_die_difference_when_no_hidden_tiles_remain():
    game = engine.new_game(["a", "b"], seed=13)
    _draft_and_play(game)
    pid = game["turn_pid"]
    game["bridges"]["coral"][-1]["value"] = 3
    assert engine.apply_move(game, pid, {"type": "take_die", "bridge": "coral", "side": "right"})[0]
    game["die_tiles"] = []
    before = game["players"][pid]["coins"]
    assert engine.apply_move(game, pid, {"type": "place_die", "space": "well"})[0]
    assert game["players"][pid]["coins"] - before == 2
    assert game["players"][pid]["seals"] == 1


def test_daimyo_seals_can_be_traded_for_one_resource():
    game = engine.new_game(["a", "b"], seed=14)
    _draft_and_play(game)
    pid = game["turn_pid"]
    game["players"][pid]["seals"] = 2
    move = {"type": "convert", "from": "seals", "to": "food"}
    assert move in engine.legal_moves(game, pid)
    assert engine.apply_move(game, pid, move) == (True, None)
    assert game["players"][pid]["seals"] == 0
    assert game["players"][pid]["resources"]["food"] == 1


def test_compaction_round_trip_packs_rng_in_live_and_undo_snapshot():
    game = engine.new_game(["a", "b"], seed=9)
    _draft_and_play(game)
    pid = game["turn_pid"]
    take = next(m for m in engine.legal_moves(game, pid) if m["type"] == "take_die")
    assert engine.apply_move(game, pid, take)[0]
    packed = persist.compact_state({"game": game})
    assert packed["game"]["_c"] == 1
    assert isinstance(packed["game"]["rng_state"][1], dict)
    restored = persist.expand_state(packed)
    assert restored["game"] == game
    assert rooms.decode_state(rooms.encode_state(packed)) == packed
