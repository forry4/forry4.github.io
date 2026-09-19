import json
import random

from games.pinch import engine


def game_to_play(seed=1, mode="standard"):
    game = engine.new_game(["a", "b"], seed=seed, mode=mode)
    while game["phase"] == "setup":
        pid = game["turn_pid"]
        assert engine.apply_move(game, pid, engine.legal_moves(game, pid)[0])[0]
    return game


def test_board_has_85_stable_unique_nodes():
    assert engine.NODE_COUNT == 85
    assert len(set(engine.NODES)) == 85
    assert not engine.CORNERS.intersection(engine.NODES)


def test_setup_alternates_and_white_starts_play():
    game = engine.new_game(["a", "b"], seed=4)
    first = game["order"][0]
    seen = []
    while game["phase"] == "setup":
        seen.append(game["turn_pid"])
        move = engine.legal_moves(game, game["turn_pid"])[0]
        assert engine.apply_move(game, game["turn_pid"], move) == (True, None)
    assert seen == [game["order"][i % 2] for i in range(10)]
    assert game["turn_pid"] == first
    assert all(len(game["rings"][pid]) == 5 for pid in game["order"])


def test_ring_crosses_markers_and_flips_only_the_crossed_group():
    game = game_to_play()
    a, b = game["order"]
    # Replace the opening with a small controlled position on one horizontal ray.
    game["rings"] = {a: [engine.NODE_TO_ID[(-3, 0)]], b: [engine.NODE_TO_ID[(4, 0)]]}
    game["removed"] = {a: 4, b: 4}
    game["markers"] = {
        str(engine.NODE_TO_ID[(-1, 0)]): a,
        str(engine.NODE_TO_ID[(0, 0)]): b,
        str(engine.NODE_TO_ID[(1, 0)]): a,
    }
    game["turn_pid"] = a
    src = engine.NODE_TO_ID[(-3, 0)]
    dst = engine.NODE_TO_ID[(2, 0)]
    legal = engine.legal_moves(game, a)
    assert {"action": "move_ring", "from": src, "to": dst} in legal
    assert {"action": "move_ring", "from": src, "to": engine.NODE_TO_ID[(3, 0)]} not in legal
    assert engine.apply_move(game, a, {"action": "move_ring", "from": src, "to": dst})[0]
    assert game["markers"][str(src)] == a
    assert [game["markers"][str(engine.NODE_TO_ID[(q, 0)])] for q in (-1, 0, 1)] == [b, a, b]


def test_every_axial_direction_accepts_straight_empty_travel():
    game = game_to_play()
    a, b = game["order"]
    center = engine.NODE_TO_ID[(0, 0)]
    game["rings"] = {a: [center], b: [engine.NODE_TO_ID[(4, -4)]]}
    game["removed"] = {a: 4, b: 4}
    game["markers"] = {}
    game["turn_pid"] = a
    legal = engine.legal_moves(game, a)
    for dq, dr in engine.DIRECTIONS:
        destination = engine.NODE_TO_ID[(2 * dq, 2 * dr)]
        assert {"action": "move_ring", "from": center, "to": destination} in legal


def test_a_ring_blocks_its_line_and_cannot_be_crossed():
    game = game_to_play()
    a, b = game["order"]
    source = engine.NODE_TO_ID[(0, 0)]
    blocker = engine.NODE_TO_ID[(2, 0)]
    game["rings"] = {a: [source], b: [blocker]}
    game["removed"] = {a: 4, b: 4}
    game["markers"] = {}
    game["turn_pid"] = a
    destinations = {move["to"] for move in engine.legal_moves(game, a)}
    assert engine.NODE_TO_ID[(1, 0)] in destinations
    assert blocker not in destinations
    assert engine.NODE_TO_ID[(3, 0)] not in destinations


def test_six_marker_run_offers_both_windows_then_requires_a_ring():
    game = game_to_play()
    a = game["order"][0]
    game["markers"] = {str(engine.NODE_TO_ID[(q, 0)]): a for q in range(-3, 3)}
    game["resolution_order"] = [a]
    game["next_turn_pid"] = game["order"][1]
    engine._advance_resolution(game)
    moves = engine.legal_moves(game, a)
    assert len(moves) == 2
    assert engine.apply_move(game, a, moves[0])[0]
    assert game["pending_kind"] == "remove_ring"
    assert len(game["markers"]) == 1


def test_intersecting_row_is_rescanned_after_the_shared_marker_is_removed():
    game = game_to_play()
    a = game["order"][0]
    horizontal = {engine.NODE_TO_ID[(q, 0)] for q in range(-2, 3)}
    diagonal = {engine.NODE_TO_ID[(0, r)] for r in range(-2, 3)}
    game["markers"] = {str(node): a for node in horizontal | diagonal}
    game["resolution_order"] = [a]
    game["next_turn_pid"] = game["order"][1]
    engine._advance_resolution(game)
    assert len(engine.legal_moves(game, a)) == 2
    chosen = next(move for move in engine.legal_moves(game, a)
                  if set(move["cells"]) == horizontal)
    assert engine.apply_move(game, a, chosen)[0]
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert game["pending_pid"] is None
    assert not engine.completed_rows(game, a)


def test_disjoint_rows_score_one_at_a_time_and_survive_serialization():
    game = game_to_play()
    a = game["order"][0]
    first = {engine.NODE_TO_ID[(q, -1)] for q in range(-2, 3)}
    second = {engine.NODE_TO_ID[(q, 1)] for q in range(-2, 3)}
    game["markers"] = {str(node): a for node in first | second}
    game["resolution_order"] = [a]
    game["next_turn_pid"] = game["order"][1]
    engine._advance_resolution(game)
    snapshot = json.loads(json.dumps(game))
    assert snapshot["pending_kind"] == "choose_row"
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert game["pending_kind"] == "choose_row"
    assert len(engine.legal_moves(game, a)) == 1


def test_mover_rows_resolve_before_opponent_rows():
    game = game_to_play()
    a, b = game["order"]
    row_a = {engine.NODE_TO_ID[(q, -1)] for q in range(-2, 3)}
    row_b = {engine.NODE_TO_ID[(q, 1)] for q in range(-2, 3)}
    game["markers"] = {
        **{str(node): a for node in row_a},
        **{str(node): b for node in row_b},
    }
    game["resolution_order"] = [a, b]
    game["next_turn_pid"] = b
    engine._advance_resolution(game)
    assert game["pending_pid"] == a
    assert set(engine.legal_moves(game, a)[0]["cells"]) == row_a


def test_blitz_ends_after_first_row_and_ring_removal():
    game = game_to_play(mode="blitz")
    a = game["order"][0]
    game["markers"] = {str(engine.NODE_TO_ID[(q, 0)]): a for q in range(-2, 3)}
    game["resolution_order"] = [a]
    game["next_turn_pid"] = game["order"][1]
    engine._advance_resolution(game)
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert game["phase"] == "over"
    assert game["winner"] == a


def test_standard_ends_after_the_third_removed_ring():
    game = game_to_play()
    a = game["order"][0]
    game["removed"][a] = 2
    game["rings"][a] = game["rings"][a][:3]
    game["markers"] = {str(engine.NODE_TO_ID[(q, 0)]): a for q in range(-2, 3)}
    game["resolution_order"] = [a]
    game["next_turn_pid"] = game["order"][1]
    engine._advance_resolution(game)
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert engine.apply_move(game, a, engine.legal_moves(game, a)[0])[0]
    assert (game["phase"], game["winner"], game["removed"][a]) == ("over", a, 3)


def test_marker_exhaustion_compares_removed_rings_and_can_draw():
    game = game_to_play()
    a, b = game["order"]
    free = [node for node in range(engine.NODE_COUNT)
            if all(node not in rings for rings in game["rings"].values())]
    rng = random.Random(91)
    for _ in range(10_000):
        chosen = rng.sample(free, engine.MARKER_COUNT)
        game["markers"] = {str(node): rng.choice((a, b)) for node in chosen}
        if not engine.completed_rows(game, a) and not engine.completed_rows(game, b):
            break
    else:  # pragma: no cover - deterministic seed finds one quickly
        raise AssertionError("could not construct an exhausted row-free position")
    game["removed"] = {a: 2, b: 1}
    game["rings"] = {a: game["rings"][a][:3], b: game["rings"][b][:4]}
    game["resolution_order"] = [a, b]
    game["next_turn_pid"] = b
    engine._advance_resolution(game)
    assert game["phase"] == "over" and game["winner"] == a

    drawn = json.loads(json.dumps(game))
    drawn["phase"] = "play"
    drawn["winner"] = None
    drawn["removed"] = {a: 2, b: 2}
    drawn["rings"] = {a: drawn["rings"][a][:3], b: drawn["rings"][b][:3]}
    drawn["resolution_order"] = [a, b]
    drawn["next_turn_pid"] = b
    engine._advance_resolution(drawn)
    assert drawn["phase"] == "over" and drawn["winner"] is None


def test_pass_is_only_advertised_when_every_ring_is_blocked():
    game = game_to_play()
    a, b = game["order"]
    source = min(range(engine.NODE_COUNT), key=lambda node: sum(
        (engine.NODES[node][0] + dq, engine.NODES[node][1] + dr) in engine.NODE_TO_ID
        for dq, dr in engine.DIRECTIONS))
    q, r = engine.NODES[source]
    blockers = [engine.NODE_TO_ID[(q + dq, r + dr)] for dq, dr in engine.DIRECTIONS
                if (q + dq, r + dr) in engine.NODE_TO_ID]
    assert len(blockers) <= 5
    game["rings"] = {a: [source], b: blockers}
    game["removed"] = {a: 4, b: 5 - len(blockers)}
    game["markers"] = {}
    game["turn_pid"] = a
    assert engine.legal_moves(game, a) == [{"action": "pass"}]
    assert engine.apply_move(game, a, {"action": "pass"})[0]
    assert game["turn_pid"] == b


def test_concession_ends_immediately_for_the_other_player():
    game = game_to_play()
    loser = game["order"][0]
    engine.concede(game, loser)
    assert game["phase"] == "over"
    assert game["winner"] == game["order"][1]
    assert game["result"] == "concession"


def test_player_view_only_advertises_moves_to_acting_viewer():
    game = engine.new_game(["a", "b"], seed=2)
    assert engine.player_view(game, game["turn_pid"])["legal_moves"]
    assert engine.player_view(game, engine._other(game, game["turn_pid"]))["legal_moves"] == []


def test_random_legal_play_stays_json_safe_and_valid():
    game = engine.new_game(["a", "b"], seed=8, mode="blitz")
    rng = random.Random(18)
    for _ in range(1200):
        if engine.is_over(game):
            break
        actor = game.get("pending_pid") or game.get("turn_pid")
        moves = engine.legal_moves(game, actor)
        assert moves
        ok, error = engine.apply_move(game, actor, rng.choice(moves))
        assert ok, error
        engine.validate_state(game)
        json.dumps(game)
    assert engine.is_over(game)
