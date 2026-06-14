"""M4: area-completion scoring, color bonus tiles, and selling goods."""
from games.castles_of_crimson import engine, board, tiles


def fresh():
    g = engine.new_game(["p1", "p2"], seed=1)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    return g


def mine(tid):
    return {"id": tid, "kind": "hex", "type": "mine", "color": "gray"}


def region_by(color, size):
    for reg in board.REGIONS.values():
        if reg["color"] == color and reg["size"] == size:
            return reg
    raise AssertionError(f"no {color} region of size {size}")


def prefill(g, pid, spaces):
    for k, sid in enumerate(spaces):
        g["players"][pid]["duchy"][sid] = mine(f"pre_{pid}_{k}")


# ── Area completion ──────────────────────────────────────────────────────────
def test_area_completion_size2_phase_a():
    g = fresh()
    reg = region_by("gray", 2)
    spaces = sorted(reg["spaces"])
    last = spaces[-1]
    prefill(g, "p1", spaces[:-1])
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place")]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": last})
    assert ok, err
    assert g["players"]["p1"]["vp"] == tiles.AREA_SCORE[1] + tiles.PHASE_BONUS["A"]  # 3 + 10 = 13


def test_area_completion_phase_bonus_varies():
    g = fresh()
    g["phase_letter"] = "E"
    reg = region_by("gray", 2)
    spaces = sorted(reg["spaces"])
    last = spaces[-1]
    prefill(g, "p1", spaces[:-1])
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place")]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": last})
    assert ok, err
    assert g["players"]["p1"]["vp"] == tiles.AREA_SCORE[1] + tiles.PHASE_BONUS["E"]  # 3 + 2 = 5


def test_area_completion_size5():
    g = fresh()
    reg = region_by("gray", 5)
    spaces = sorted(reg["spaces"])
    last = spaces[-1]
    prefill(g, "p1", spaces[:-1])
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place")]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": last})
    assert ok, err
    assert g["players"]["p1"]["vp"] == tiles.AREA_SCORE[4] + tiles.PHASE_BONUS["A"]  # 15 + 10 = 25


def test_partial_area_does_not_score():
    g = fresh()
    reg = region_by("gray", 5)
    spaces = sorted(reg["spaces"])
    # Fill only the first space via placement (region not complete).
    target = spaces[0]
    # Ensure a placed neighbor: pre-fill an adjacent gray space outside scoring path?
    # Simpler: place on a castle-adjacent gray space and check no area score.
    castle = board.space_id(*board.CASTLE_SPACE)
    gray_nbr = next(s for s in board.neighbors(castle) if board.SPACES[s]["color"] == "gray")
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[gray_nbr]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place")]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": gray_nbr})
    assert ok, err
    # The size-5 gray region has 5 spaces; one tile cannot complete it.
    assert g["players"]["p1"]["vp"] == 0


# ── Color bonus tiles ─────────────────────────────────────────────────────────
def test_color_bonus_first_and_second():
    g = fresh()
    gray_spaces = sorted(board.SPACES_BY_COLOR["gray"])
    # p1 completes gray.
    last1 = gray_spaces[-1]
    prefill(g, "p1", gray_spaces[:-1])
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last1]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("p1last")]
    ok, _ = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "p1last", "space_id": last1})
    assert ok
    assert {"color": "gray", "vp": tiles.bonus_first(2)} in g["players"]["p1"]["claimed_bonus"]
    assert g["bonus_tiles"]["gray"] == [tiles.bonus_second(2)]

    # p2 completes gray -> gets the second bonus.
    g["turn"] = "p2"
    g["dice"]["p2"] = {"values": [1, 1], "used": [False, False]}
    last2 = gray_spaces[-1]
    prefill(g, "p2", gray_spaces[:-1])
    g["players"]["p2"]["vp"] = 0
    g["dice"]["p2"]["values"] = [board.SPACES[last2]["number"], 5]
    g["players"]["p2"]["storage"] = [mine("p2last")]
    ok2, _ = engine.apply_move(g, "p2", {"type": "place_tile", "die_index": 0, "tile_id": "p2last", "space_id": last2})
    assert ok2
    assert {"color": "gray", "vp": tiles.bonus_second(2)} in g["players"]["p2"]["claimed_bonus"]
    assert g["bonus_tiles"]["gray"] == []


# ── Selling goods ─────────────────────────────────────────────────────────────
def test_sell_goods():
    g = fresh()
    p = g["players"]["p1"]
    p["goods"] = {"amber": 3}
    p["silver"] = 0
    p["vp"] = 0
    # amber is GOODS_COLORS[0] -> sellable with a die showing 1.
    g["dice"]["p1"]["values"] = [1, 5]
    ok, err = engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert ok, err
    assert p["silver"] == tiles.SELL_SILVER
    assert p["vp"] == tiles.sell_vp_per_tile(2) * 3  # 2 * 3 = 6
    assert "amber" not in p["goods"]
    assert p["sold_goods"] == ["amber", "amber", "amber"]
    assert g["dice"]["p1"]["used"][0] is True


def test_sell_rejects_no_goods():
    g = fresh()
    g["players"]["p1"]["goods"] = {}
    g["dice"]["p1"]["values"] = [1, 5]
    ok, err = engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert not ok and "goods" in err
