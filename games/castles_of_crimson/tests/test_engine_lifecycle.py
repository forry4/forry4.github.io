"""new_game setup + (later) phase/turn lifecycle."""
import copy

from games.castles_of_crimson import engine, board, tiles


def _strip_ids(game):
    """Tile ids include a global counter; compare structure modulo ids."""
    g = copy.deepcopy(game)
    def scrub(t):
        if isinstance(t, dict):
            t.pop("id", None)
            for v in t.values():
                scrub(v)
        elif isinstance(t, list):
            for v in t:
                scrub(v)
    scrub(g)
    return g


def test_new_game_basic_shape():
    g = engine.new_game(["p1", "p2"], names={"p1": "A", "p2": "B"}, seed=1)
    assert g["num_players"] == 2
    assert g["phase_letter"] == "A"
    assert g["round"] == 1
    assert g["phase"] == "playing"
    assert set(g["players"]) == {"p1", "p2"}
    # Every duchy has all 37 spaces, only the castle pre-filled.
    for pid in ("p1", "p2"):
        duchy = g["players"][pid]["duchy"]
        assert len(duchy) == 37
        filled = [sid for sid, t in duchy.items() if t is not None]
        assert filled == [board.space_id(*board.CASTLE_SPACE)]
        assert duchy[filled[0]]["type"] == "castle"
        assert duchy[filled[0]].get("starting") is True


def test_depots_filled_to_2p_count():
    g = engine.new_game(["p1", "p2"], seed=7)
    for i in range(1, 7):
        assert len(g["depots"][str(i)]["hexes"]) == tiles.DEPOT_FILL_2P
    assert len(g["black_depot"]) == tiles.BLACK_FILL_2P


def test_initial_round_rolled_and_goods_placed():
    g = engine.new_game(["p1", "p2"], seed=3)
    for pid in ("p1", "p2"):
        assert len(g["dice"][pid]["values"]) == 2
        assert all(1 <= v <= 6 for v in g["dice"][pid]["values"])
        assert g["dice"][pid]["used"] == [False, False]
    assert 1 <= g["white_die"] <= 6
    # The round's goods tile landed on the white-die depot.
    assert len(g["depots"][str(g["white_die"])]["goods"]) == 1
    assert g["turn"] == g["start_player"] == "p1"


def test_starting_resources():
    g = engine.new_game(["p1", "p2"], seed=5)
    for pid in ("p1", "p2"):
        p = g["players"][pid]
        assert p["silver"] == tiles.START_SILVER
        assert p["workers"] == tiles.START_WORKERS
        assert sum(p["goods"].values()) == tiles.START_GOODS
        assert len(p["goods"]) <= 3


def test_determinism_same_seed():
    a = engine.new_game(["p1", "p2"], seed=42)
    b = engine.new_game(["p1", "p2"], seed=42)
    assert _strip_ids(a) == _strip_ids(b)


def test_different_seeds_differ():
    a = engine.new_game(["p1", "p2"], seed=1)
    b = engine.new_game(["p1", "p2"], seed=2)
    # Extremely unlikely to be identical; guards against ignoring the seed.
    assert _strip_ids(a) != _strip_ids(b)


# ── M5: phase / turn lifecycle ────────────────────────────────────────────────
def test_full_game_phase_progression():
    g = engine.new_game(["p1", "p2"], seed=11)
    phases_seen = []
    end_turns = 0
    guard = 0
    while not engine.is_over(g) and guard < 200:
        guard += 1
        phases_seen.append(g["phase_letter"])
        cur = g["turn"]
        ok, err = engine.apply_move(g, cur, {"type": "end_turn"})
        assert ok, err
        end_turns += 1
    assert engine.is_over(g)
    # 5 phases x 5 rounds x 2 players = 50 end_turns.
    assert end_turns == 50
    # Phases advance A->E in order.
    assert sorted(set(phases_seen)) == ["A", "B", "C", "D", "E"]
    assert phases_seen[0] == "A"
    assert phases_seen[-1] == "E"


def test_round_advances_after_both_players():
    g = engine.new_game(["p1", "p2"], seed=4)
    assert g["round"] == 1 and g["turn"] == "p1"
    engine.apply_move(g, "p1", {"type": "end_turn"})
    assert g["round"] == 1 and g["turn"] == "p2"
    engine.apply_move(g, "p2", {"type": "end_turn"})
    assert g["round"] == 2 and g["turn"] == "p1"


def test_mine_silver_paid_at_phase_end():
    g = engine.new_game(["p1", "p2"], seed=9)
    g["players"]["p1"]["mines_count"] = 2
    start_silver = g["players"]["p1"]["silver"]
    # Play exactly one full phase (5 rounds = 10 end_turns) to trigger end-of-phase.
    for _ in range(10):
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    assert g["phase_letter"] == "B"
    assert g["players"]["p1"]["silver"] == start_silver + 2


def test_depots_refilled_each_phase():
    g = engine.new_game(["p1", "p2"], seed=2)
    for _ in range(10):  # one full phase
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    assert g["phase_letter"] == "B"
    for i in range(1, 7):
        assert len(g["depots"][str(i)]["hexes"]) == tiles.DEPOT_FILL_2P


def test_undo_turn_reverts_actions():
    g = engine.new_game(["p1", "p2"], seed=4)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    engine._snapshot_turn(g)  # snapshot this controlled turn start
    w0 = g["players"]["p1"]["workers"]
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert g["players"]["p1"]["workers"] == w0 + 2
    assert g["dice"]["p1"]["used"][0] is True
    ok, err = engine.apply_move(g, "p1", {"type": "undo_turn"})
    assert ok, err
    assert g["players"]["p1"]["workers"] == w0
    assert g["dice"]["p1"]["used"] == [False, False]
    # the undone action is no longer in the log (only the undo marker is most-recent)
    assert g["moves"][0]["type"] == "undo_turn"
    assert all(m["type"] != "take_workers" for m in g["moves"])


def test_undo_turn_clears_pending():
    g = engine.new_game(["p1", "p2"], seed=4)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    engine._snapshot_turn(g)
    # find a burgundy (castle) space and enable adjacency without completing it
    burg = next((s, i["number"]) for s, i in board.SPACES.items() if i["color"] == "burgundy" and not i["is_castle"])
    sid, num = burg
    nb = board.neighbors(sid)[0]
    g["players"]["p1"]["duchy"][nb] = {"id": "d", "kind": "hex", "type": "mine", "color": "gray"}
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [{"id": "c", "kind": "hex", "type": "castle", "color": "burgundy"}]
    engine._snapshot_turn(g)  # snapshot AFTER this setup so undo returns here
    engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "c", "space_id": sid})
    assert g["pending_kind"] == "extra_action"
    engine.apply_move(g, "p1", {"type": "undo_turn"})
    assert g["pending_pid"] is None
    assert g["players"]["p1"]["duchy"][sid] is None
    assert any(t["id"] == "c" for t in g["players"]["p1"]["storage"])


def test_winner_declared_on_game_over():
    g = engine.new_game(["p1", "p2"], seed=11)
    while not engine.is_over(g):
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    assert g["winner"] in ("p1", "p2")
    scores = engine.final_scores(g)
    assert set(scores) == {"p1", "p2"}

