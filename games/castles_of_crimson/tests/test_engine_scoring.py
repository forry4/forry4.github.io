"""M4: area-completion scoring, color bonus tiles, and selling goods."""
from games.castles_of_crimson import engine, board, tiles
from .conftest import complete_setup


def fresh():
    g = engine.new_game(["p1", "p2"], seed=1)
    complete_setup(g)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    return g


def mine(tid, color="gray"):
    # type "mine" placed on any-color space: color match is what placement checks;
    # the mine type avoids color-specific side effects (livestock/building/etc.) so
    # the area-score assertion stays clean regardless of the region's color.
    return {"id": tid, "kind": "hex", "type": "mine", "color": color}


def region_of_size(size):
    """A region of exactly `size` whose completion scores ONLY the area value.

    Picks a non-burgundy region (burgundy = castle, special scoring) whose color
    has more than one region, so completing this one does NOT complete the whole
    color and therefore does not also award the color-bonus tile.
    """
    import collections
    per_color = collections.Counter(r["color"] for r in board.REGIONS.values())
    for reg in board.REGIONS.values():
        if reg["size"] == size and reg["color"] != "burgundy" and per_color[reg["color"]] > 1:
            return reg
    raise AssertionError(f"no clean (non-color-completing) region of size {size}")


def prefill(g, pid, spaces, color="gray"):
    for k, sid in enumerate(spaces):
        g["players"][pid]["duchy"][sid] = mine(f"pre_{pid}_{k}", color)


# ── Area completion ──────────────────────────────────────────────────────────
def test_area_completion_size3_phase_a():
    g = fresh()
    reg = region_of_size(3)
    color = reg["color"]
    spaces = sorted(reg["spaces"])
    last = spaces[-1]
    prefill(g, "p1", spaces[:-1], color)
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place", color)]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": last})
    assert ok, err
    assert g["players"]["p1"]["vp"] == tiles.AREA_SCORE[2] + tiles.PHASE_BONUS["A"]  # 6 + 10 = 16


def test_area_completion_phase_bonus_varies():
    g = fresh()
    g["phase_letter"] = "E"
    reg = region_of_size(3)
    color = reg["color"]
    spaces = sorted(reg["spaces"])
    last = spaces[-1]
    prefill(g, "p1", spaces[:-1], color)
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place", color)]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": last})
    assert ok, err
    assert g["players"]["p1"]["vp"] == tiles.AREA_SCORE[2] + tiles.PHASE_BONUS["E"]  # 6 + 2 = 8


def test_area_completion_size5():
    g = fresh()
    reg = region_of_size(5)
    color = reg["color"]
    spaces = sorted(reg["spaces"])
    last = spaces[-1]
    prefill(g, "p1", spaces[:-1], color)
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[last]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place", color)]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": last})
    assert ok, err
    assert g["players"]["p1"]["vp"] == tiles.AREA_SCORE[4] + tiles.PHASE_BONUS["A"]  # 15 + 10 = 25


def test_partial_area_does_not_score():
    g = fresh()
    castle = g["players"]["p1"]["castle_sid"]
    # A castle-adjacent space whose region has >1 space, so one tile can't complete it.
    target = next(s for s in board.neighbors(castle)
                  if board.REGIONS[board.region_of(s)]["size"] > 1
                  and g["players"]["p1"]["duchy"][s] is None)
    color = board.SPACES[target]["color"]
    g["players"]["p1"]["vp"] = 0
    g["dice"]["p1"]["values"] = [board.SPACES[target]["number"], 5]
    g["players"]["p1"]["storage"] = [mine("place", color)]
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "place", "space_id": target})
    assert ok, err
    # one tile cannot complete a multi-space region.
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
