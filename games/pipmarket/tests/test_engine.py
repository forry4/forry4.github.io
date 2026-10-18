"""Rules coverage for the Pip Market engine."""

import json

import pytest

from games.pipmarket import bot, engine


def fresh(n=2, seed=7):
    return engine.new_game([f"p{i}" for i in range(n)], seed=seed)


def die(i, f, r, c):
    return {"id": i, "f": f, "r": r, "c": c}


def all_ids(game):
    return sorted([d["id"] for cols in game["market"] for col in cols for d in col]
                  + [d["id"] for board in game["boards"].values() for d in board]
                  + [d["id"] for d in game["cup"]])


def first_buy(game, s=0, c=0):
    pid = game["turn"]
    cells = engine.placements(game["boards"][pid], len(game["market"][s][c]))[0]
    return pid, {"type": "buy", "set": s, "col": c, "cells": [list(x) for x in cells]}


@pytest.mark.parametrize("n", [2, 3, 4])
def test_the_deal_scales_with_the_table(n):
    game = fresh(n)
    assert len(game["market"]) == n + 1
    assert all(len(cols) == 5 and all(len(col) == 2 for col in cols) for cols in game["market"])
    assert all_ids(game) == list(range(engine.total_dice(n)))
    # the last seat starts on 12 and each earlier seat on one less
    assert [game["money"][p] for p in game["players"]] == list(range(13 - n, 13))
    assert game["turn"] == game["players"][0]


def test_the_seat_order_is_shuffled_from_the_seed_and_reproducible():
    a = engine.new_game(["a", "b", "c", "d"], seed=11)
    b = engine.new_game(["a", "b", "c", "d"], seed=11)
    assert a == b
    orders = {tuple(engine.new_game(["a", "b", "c", "d"], seed=s)["players"]) for s in range(30)}
    assert len(orders) > 5


def test_rejects_bad_tables():
    with pytest.raises(ValueError):
        engine.new_game(["solo"])
    with pytest.raises(ValueError):
        engine.new_game(["a", "b", "c", "d", "e"])
    with pytest.raises(ValueError):
        engine.new_game(["a", "a"])


def test_buying_pays_the_position_slides_the_set_and_places_the_pair():
    game = fresh()
    pid = game["turn"]
    before = game["money"][pid]
    s = 1
    target = game["market"][s][2]
    ok, err = engine.apply_move(game, pid, {"type": "buy", "set": s, "col": 2,
                                            "cells": [[0, 0], [1, 0]]})
    assert ok, err
    assert game["money"][pid] == before - 3
    assert len(game["market"][s]) == 4
    assert target not in game["market"][s]
    board = game["boards"][pid]
    assert sorted((d["r"], d["c"]) for d in board) == [(0, 0), (1, 0)]
    assert {d["id"] for d in board} == {d["id"] for d in target}
    assert game["last_buyer"] == pid
    assert game["turn"] != pid


def test_cannot_buy_what_you_cannot_afford_or_out_of_turn():
    game = fresh()
    pid = game["turn"]
    other = [p for p in game["players"] if p != pid][0]
    assert engine.apply_move(game, other, {"type": "take"}) == (False, "not your turn")
    game["money"][pid] = 2
    ok, err = engine.apply_move(game, pid, {"type": "buy", "set": 0, "col": 2,
                                            "cells": [[0, 0], [0, 1]]})
    assert not ok and "afford" in err
    for bad in ({"type": "buy", "set": -1, "col": 0, "cells": [[0, 0], [0, 1]]},
                {"type": "buy", "set": 0, "col": -1, "cells": [[0, 0], [0, 1]]},
                {"type": "buy", "set": 9, "col": 0, "cells": [[0, 0], [0, 1]]},
                {"type": "buy", "set": 0, "col": 0, "cells": "zz"},
                {"type": "buy", "set": 0, "col": 0, "cells": [[0, 0], [0, 2]]},
                {"type": "buy", "set": 0, "col": 0, "cells": [[0, 0]]}):
        assert engine.apply_move(game, pid, bad)[0] is False, bad


def test_placement_must_touch_the_board_and_stay_within_six_by_six():
    board = [die(0, 3, 0, c) for c in range(5)]
    assert engine.placement_ok(board, [(0, 5)])
    assert not engine.placement_ok(board, [(0, 5), (0, 6)])       # seven wide
    assert engine.placement_ok(board, [(0, -1)])                   # grows left instead
    assert not engine.placement_ok(board, [(2, 0), (3, 0)])        # does not touch
    assert not engine.placement_ok(board, [(0, 0)])                # occupied
    assert engine.placement_ok(board, [(1, 2), (2, 2)])
    assert not engine.placement_ok(board, [(1, 2), (2, 3)])        # pair not adjacent


def test_a_pair_you_cannot_place_cannot_be_bought():
    # A full 6x6 has no free cell inside the span.
    board = [die(r * 6 + c, 1 + (r + c) % 6, r, c) for r in range(6) for c in range(6)]
    assert engine.placements(board, 1) == []
    game = fresh()
    pid = game["turn"]
    game["boards"][pid] = board
    assert engine.buyable_columns(game, pid) == []
    ok, _ = engine.apply_move(game, pid, {"type": "buy", "set": 0, "col": 0,
                                          "cells": [[0, 6], [0, 7]]})
    assert not ok


def test_take_adds_two_caps_at_eighteen_and_is_refused_at_eighteen():
    game = fresh()
    pid = game["turn"]
    game["money"][pid] = 17
    assert engine.apply_move(game, pid, {"type": "take"}) == (True, None)
    assert game["money"][pid] == 18
    # back round to the same player
    while game["turn"] != pid:
        assert engine.apply_move(game, game["turn"], {"type": "take"})[0]
    ok, err = engine.apply_move(game, pid, {"type": "take"})
    assert not ok and "must buy" in err


def test_a_player_with_no_legal_action_is_skipped():
    game = fresh(3)
    a, b, c = game["players"]
    full = [die(100 + r * 6 + cc, 1 + (r + cc) % 6, r, cc) for r in range(6) for cc in range(6)]
    game["boards"][b] = full
    game["money"][b] = 18
    assert not engine.has_auction_action(game, b)
    assert engine.apply_move(game, a, {"type": "take"})[0]
    assert game["turn"] == c


def test_lines_must_be_long_enough_straight_and_keep_the_board_connected():
    board = [die(0, 3, 0, 0), die(1, 3, 0, 1), die(2, 3, 0, 2), die(3, 2, 1, 1), die(4, 2, 2, 1)]
    lines = engine.scoring_lines(board)
    # Removing the 3s leaves the two 2s, which still touch each other.
    faces = sorted((line["face"], line["count"]) for line in lines)
    assert (3, 3) in faces and (2, 2) in faces
    # two 3s are too short
    assert not any(line["face"] == 3 and line["count"] == 2 for line in lines)


def test_a_line_whose_removal_would_split_the_board_is_not_offered():
    # 4 - 1 - 4 : removing the 1 splits the 4s
    board = [die(0, 4, 0, 0), die(1, 1, 0, 1), die(2, 4, 0, 2)]
    assert engine.scoring_lines(board) == []
    # adding a bridge under it makes it legal
    board += [die(3, 5, 1, 0), die(4, 5, 1, 1), die(5, 5, 1, 2)]
    assert any(line["face"] == 1 for line in engine.scoring_lines(board))


def test_scoring_points_money_and_the_cup():
    game = fresh()
    pid = game["players"][0]
    game["phase"] = "scoring"
    game["turn"] = pid
    game["passed"] = []
    game["boards"][pid] = [die(c, 4, 0, c) for c in range(4)] + [die(9, 6, 1, 0)]
    # the other seat still has a line, so the round stays open and the cup is visible
    game["boards"][game["players"][1]] = [die(20, 1, 0, 0)]
    game["money"][pid] = 3
    ok, err = engine.apply_move(game, pid, {"type": "score",
                                            "cells": [[0, 0], [0, 1], [0, 2], [0, 3]]})
    assert ok, err
    assert game["points"][pid] == 16
    assert game["money"][pid] == 8          # 15+ pays 5
    assert sorted(d["id"] for d in game["cup"]) == [0, 1, 2, 3]
    assert [(d["r"], d["c"]) for d in game["boards"][pid]] == [(0, 0)]   # re-normalised


def test_money_after():
    assert engine.money_after(4, 3) == 4
    assert engine.money_after(16, 3) == 8
    assert engine.money_after(16, 15) == 18
    assert engine.money_after(30, 2) == 18
    assert engine.money_after(36, 17) == 18


def test_scoring_alternates_and_is_compulsory():
    game = fresh()
    a, b = game["players"]
    game["boards"][a] = [die(0, 1, 0, 0), die(1, 1, 0, 1), die(2, 6, 0, 2)]
    game["boards"][b] = [die(3, 1, 0, 0), die(4, 5, 0, 1)]
    game["market"] = [[] for _ in game["market"]]
    game["last_buyer"] = a
    engine._start_scoring(game)
    assert game["phase"] == "scoring" and game["turn"] == a
    assert engine.apply_move(game, a, {"type": "score", "cells": [[0, 0]]})[0]
    assert game["turn"] == b
    # b has a line, so b may not stop: there is no pass while a line is open
    assert engine.apply_move(game, b, {"type": "pass"}) == (False, "you must score while you have a line")
    assert {"type": "pass"} not in engine.legal_moves(game, b)
    assert engine.apply_move(game, b, {"type": "score", "cells": [[0, 0]]})[0]
    assert game["turn"] == a
    assert engine.apply_move(game, a, {"type": "score", "cells": [[0, 0]]})[0]
    # nobody has a line left: the round ends and every scored die comes back
    assert game["phase"] == "auction" and game["round"] == 2
    assert market_ids(game) == {0, 1, 3}
    assert game["turn"] == a      # the last buyer goes first


@pytest.mark.parametrize("n_dice,n_sets,expected", [
    (17, 5, [4, 4, 3, 3, 3]),
    (11, 3, [4, 4, 3]),
    (6, 5, [2, 1, 1, 1, 1]),
    (30, 3, [10, 10, 10]),
    (3, 4, [1, 1, 1, 0]),
])
def test_the_stalls_are_filled_as_evenly_as_possible(n_dice, n_sets, expected):
    dice = [{"id": i, "f": 1} for i in range(n_dice)]
    market = engine._deal(dice, n_sets)
    counts = [sum(len(col) for col in cols) for cols in market]
    assert counts == expected
    for cols in market:
        # pairs first; only the last column of a stall may hold a single die
        assert all(len(col) == 2 for col in cols[:-1])
    assert sorted(d["id"] for cols in market for col in cols for d in col) == list(range(n_dice))


def test_a_later_round_deals_evenly():
    game = fresh(4)
    for pid in game["players"]:
        game["boards"][pid] = []
    # 17 dice come back from the cup into five stalls
    game["cup"] = [{"id": i, "f": 1} for i in range(17)]
    game["round_scored"] = 17
    game["phase"] = "scoring"
    engine._end_round(game)
    counts = [sum(len(col) for col in cols) for cols in game["market"]]
    assert counts == [4, 4, 3, 3, 3]


def market_ids(game):
    return {d["id"] for cols in game["market"] for col in cols for d in col}


def test_the_last_buyer_scores_first_and_leads_the_next_round():
    game = fresh(3)
    a, b, c = game["players"]
    for pid in game["players"]:
        game["boards"][pid] = [die(50 + game["players"].index(pid), 1, 0, 0)]
    game["market"] = [[] for _ in game["market"]]
    game["last_buyer"] = b
    engine._start_scoring(game)
    assert game["turn"] == b


def test_a_round_where_nobody_scores_ends_the_game():
    game = fresh()
    for pid in game["players"]:
        game["boards"][pid] = [die(60, 6, 0, 0)]
    game["market"] = [[] for _ in game["market"]]
    engine._start_scoring(game)
    assert engine.is_over(game)
    assert game["log"][-1]["early"] is True


def test_the_game_ends_after_round_three_with_money_added():
    game = fresh()
    a, b = game["players"]
    game["round"] = 3
    game["points"] = {a: 20, b: 25}
    game["money"] = {a: 10, b: 4}
    game["boards"][a] = [die(0, 1, 0, 0)]
    game["boards"][b] = []
    game["market"] = [[] for _ in game["market"]]
    game["last_buyer"] = a
    engine._start_scoring(game)
    assert engine.apply_move(game, a, {"type": "score", "cells": [[0, 0]]})[0]
    assert engine.is_over(game)
    assert game["final"] == {a: 21 + 11, b: 29}
    assert game["winners"] == [a]


def test_a_shared_top_score_is_a_shared_win():
    game = fresh()
    a, b = game["players"]
    game["points"] = {a: 10, b: 10}
    game["money"] = {a: 5, b: 5}
    engine._finish(game)
    assert game["winners"] == [a, b]


def test_concede_hands_the_win_to_someone_else():
    game = fresh(3)
    a, b, c = game["players"]
    game["points"] = {a: 50, b: 1, c: 2}
    engine.concede(game, a)
    assert engine.is_over(game)
    assert a not in game["winners"]


def test_player_view_hides_only_the_seed_and_names_the_options():
    game = fresh()
    view = engine.player_view(game, game["players"][1])
    assert "seed" not in view and "seed" in game
    assert view["options"]["pid"] == game["turn"]
    assert view["options"]["take"] is True
    assert [0, 0] in view["options"]["columns"]


@pytest.mark.parametrize("n", [2, 3, 4])
def test_full_bot_games_conserve_every_die_and_finish(n):
    for seed in range(4):
        game = engine.new_game([f"p{i}" for i in range(n)], seed=seed)
        steps = 0
        while not engine.is_over(game):
            pid = engine.to_act(game)
            assert engine.legal_moves(game, pid)
            move = bot.choose_move(game, pid, seed * 7919 + steps)
            ok, err = engine.apply_move(game, pid, move)
            assert ok, (err, move)
            assert all_ids(game) == list(range(engine.total_dice(n)))
            for board in game["boards"].values():
                cells = {(d["r"], d["c"]) for d in board}
                assert len(cells) == len(board)
                assert engine._connected(cells)
                assert engine._fits(cells)
            steps += 1
            assert steps < 3000
        json.loads(json.dumps(game))
        assert set(game["final"]) == set(game["players"])
        assert game["winners"]
