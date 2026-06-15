"""M3: accept/reject matrix for the core die-actions."""
import pytest

from games.castles_of_crimson import engine, board, tiles


def fresh(seed=1):
    from .conftest import complete_setup
    g = engine.new_game(["p1", "p2"], seed=seed)
    complete_setup(g)
    # Force a deterministic, controlled turn for p1.
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    return g


def castle_sid():
    return "0,0"


def a_gray_castle_neighbor():
    """A gray space adjacent to the castle (mine tile needs no extra fields)."""
    for nb in board.neighbors(castle_sid()):
        if board.SPACES[nb]["color"] == "gray":
            return nb, board.SPACES[nb]["number"]
    raise AssertionError("expected a gray castle neighbor")


def mine_tile(tid="m_test"):
    return {"id": tid, "kind": "hex", "type": "mine", "color": "gray"}


# ── place_tile ──────────────────────────────────────────────────────────────
def test_place_tile_success():
    g = fresh()
    sid, num = a_gray_castle_neighbor()
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [mine_tile()]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "m_test", "space_id": sid})
    assert ok, err
    assert g["players"]["p1"]["duchy"][sid]["id"] == "m_test"
    assert g["players"]["p1"]["storage"] == []
    assert g["dice"]["p1"]["used"][0] is True
    assert g["players"]["p1"]["mines_count"] == 1


def test_place_tile_rejects_wrong_number():
    g = fresh()
    sid, num = a_gray_castle_neighbor()
    g["dice"]["p1"]["values"] = [(num % 6) + 1, 6]  # not the space number
    g["players"]["p1"]["storage"] = [mine_tile()]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "m_test", "space_id": sid})
    assert not ok and "number" in err


def test_place_tile_rejects_wrong_color():
    g = fresh()
    sid, num = a_gray_castle_neighbor()
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [{"id": "s1", "kind": "hex", "type": "ship", "color": "blue"}]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "s1", "space_id": sid})
    assert not ok and "color" in err


def test_place_tile_rejects_non_adjacent():
    g = fresh()
    # Find a gray space NOT adjacent to any placed tile (only castle is placed).
    far = None
    for sid, info in board.SPACES.items():
        if info["color"] == "gray" and not engine._has_placed_neighbor(g, "p1", sid):
            far = (sid, info["number"])
            break
    assert far, "expected a non-adjacent gray space"
    sid, num = far
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [mine_tile()]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "m_test", "space_id": sid})
    assert not ok and "adjacent" in err


def test_place_tile_rejects_occupied():
    g = fresh()
    sid, num = a_gray_castle_neighbor()
    g["players"]["p1"]["duchy"][sid] = mine_tile("occupied")
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [mine_tile()]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "m_test", "space_id": sid})
    assert not ok and "filled" in err


def test_place_tile_rejects_used_die():
    g = fresh()
    sid, num = a_gray_castle_neighbor()
    g["dice"]["p1"]["values"] = [num, 6]
    g["dice"]["p1"]["used"] = [True, False]
    g["players"]["p1"]["storage"] = [mine_tile()]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "m_test", "space_id": sid})
    assert not ok and "used" in err


# ── take_hex ──────────────────────────────────────────────────────────────────
def test_take_hex_success():
    g = fresh()
    g["dice"]["p1"]["values"] = [3, 6]
    g["players"]["p1"]["storage"] = []
    tile = mine_tile("d3")
    g["depots"]["3"]["hexes"] = [tile]
    ok, err = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 0, "tile_id": "d3"})
    assert ok, err
    assert any(t["id"] == "d3" for t in g["players"]["p1"]["storage"])
    assert tile not in g["depots"]["3"]["hexes"]
    assert g["dice"]["p1"]["used"][0] is True


def test_take_hex_rejects_wrong_depot():
    g = fresh()
    g["dice"]["p1"]["values"] = [3, 6]
    g["depots"]["4"]["hexes"] = [mine_tile("d4")]
    ok, err = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 0, "tile_id": "d4"})
    assert not ok and "depot" in err


def test_take_hex_rejects_full_storage():
    g = fresh()
    g["dice"]["p1"]["values"] = [3, 6]
    g["players"]["p1"]["storage"] = [mine_tile("a"), mine_tile("b"), mine_tile("c")]
    g["depots"]["3"]["hexes"] = [mine_tile("d3")]
    ok, err = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 0, "tile_id": "d3"})
    assert not ok and "storage full" in err


def test_discard_storage_then_take():
    g = fresh()
    g["dice"]["p1"]["values"] = [3, 6]
    g["players"]["p1"]["storage"] = [mine_tile("a"), mine_tile("b"), mine_tile("c")]
    g["depots"]["3"]["hexes"] = [mine_tile("d3")]
    # discard is offered only when storage is full
    assert {"type": "discard_storage", "tile_id": "a"} in engine.legal_moves(g, "p1")
    ok, err = engine.apply_move(g, "p1", {"type": "discard_storage", "tile_id": "a"})
    assert ok, err
    assert all(t["id"] != "a" for t in g["players"]["p1"]["storage"])
    assert g["dice"]["p1"]["used"] == [False, False]   # discarding is free, no die spent
    # now a key space is free, so the take-hex action succeeds
    ok2, err2 = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 0, "tile_id": "d3"})
    assert ok2, err2
    assert any(t["id"] == "d3" for t in g["players"]["p1"]["storage"])


def test_discard_storage_rejected_when_not_full():
    g = fresh()
    g["players"]["p1"]["storage"] = [mine_tile("a")]
    ok, err = engine.apply_move(g, "p1", {"type": "discard_storage", "tile_id": "a"})
    assert not ok and "full" in err
    assert {"type": "discard_storage", "tile_id": "a"} not in engine.legal_moves(g, "p1")


# ── take_workers ──────────────────────────────────────────────────────────────
def test_take_workers():
    g = fresh()
    before = g["players"]["p1"]["workers"]
    ok, err = engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert ok, err
    assert g["players"]["p1"]["workers"] == before + 2
    assert g["dice"]["p1"]["used"][0] is True


# ── buy_black ─────────────────────────────────────────────────────────────────
def test_buy_black_success_and_once_per_turn():
    g = fresh()
    g["players"]["p1"]["silver"] = 5
    g["players"]["p1"]["storage"] = []
    g["black_depot"] = [mine_tile("bd1"), mine_tile("bd2")]
    ok, err = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": "bd1"})
    assert ok, err
    assert g["players"]["p1"]["silver"] == 3
    assert g["black_depot_used_this_turn"] is True
    # Second buy same turn is rejected.
    ok2, err2 = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": "bd2"})
    assert not ok2 and "black depot" in err2


def test_buy_black_needs_silver():
    g = fresh()
    g["players"]["p1"]["silver"] = 1
    g["black_depot"] = [mine_tile("bd1")]
    ok, err = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": "bd1"})
    assert not ok and "silver" in err


# ── adjust_die ────────────────────────────────────────────────────────────────
def test_adjust_die_spends_workers_and_wraps():
    g = fresh()
    g["dice"]["p1"]["values"] = [1, 4]
    g["players"]["p1"]["workers"] = 3
    # 1 -> 6 is a single wrap step (1 worker).
    ok, err = engine.apply_move(g, "p1", {"type": "adjust_die", "die_index": 0, "to": 6})
    assert ok, err
    assert g["dice"]["p1"]["values"][0] == 6
    assert g["players"]["p1"]["workers"] == 2


def test_adjust_die_rejects_insufficient_workers():
    g = fresh()
    g["dice"]["p1"]["values"] = [1, 4]
    g["players"]["p1"]["workers"] = 1
    # 1 -> 4 is 3 steps -> needs 3 workers.
    ok, err = engine.apply_move(g, "p1", {"type": "adjust_die", "die_index": 0, "to": 4})
    assert not ok and "workers" in err


# ── turn ownership ────────────────────────────────────────────────────────────
def test_not_your_turn():
    g = fresh()
    ok, err = engine.apply_move(g, "p2", {"type": "take_workers", "die_index": 0})
    assert not ok and "your turn" in err


def test_end_turn_passes_to_next_player():
    g = fresh()
    ok, err = engine.apply_move(g, "p1", {"type": "end_turn"})
    assert ok, err
    assert g["turn"] == "p2"


def test_legal_moves_never_empty_on_your_turn():
    g = fresh()
    moves = engine.legal_moves(g, "p1")
    assert any(m["type"] == "end_turn" for m in moves)
    assert any(m["type"] == "take_workers" for m in moves)
