"""M6: non-monastery placement effects."""
from games.castles_of_crimson import engine, board, tiles

CASTLE = board.space_id(*board.CASTLE_SPACE)


def fresh():
    g = engine.new_game(["p1", "p2"], seed=1)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    # quiet board so building "take" effects don't fire unless a test wants them
    for d in range(1, 7):
        g["depots"][str(d)]["hexes"] = []
        g["depots"][str(d)]["goods"] = []
    g["players"]["p1"]["goods"] = {}
    g["players"]["p1"]["vp"] = 0
    return g


def hext(ttype, color, tid="t", **extra):
    t = {"id": tid, "kind": "hex", "type": ttype, "color": color}
    t.update(extra)
    return t


def adj(color):
    out = []
    for nb in board.neighbors(CASTLE):
        if board.SPACES[nb]["color"] == color:
            out.append((nb, board.SPACES[nb]["number"]))
    return out


def enable_adj(g, sid):
    nb = board.neighbors(sid)[0]
    if g["players"]["p1"]["duchy"][nb] is None:
        g["players"]["p1"]["duchy"][nb] = hext("mine", "gray", "dummy_" + nb)


def place_building(g, building, sid, num, tid="b"):
    g["dice"]["p1"]["values"] = [num, 6]
    g["dice"]["p1"]["used"] = [False, False]
    g["players"]["p1"]["storage"] = [hext("building", "beige", tid, building=building)]
    return engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": tid, "space_id": sid})


# ── Simple immediate buildings ────────────────────────────────────────────────
def test_bank_gives_silver():
    g = fresh()
    sid, num = adj("beige")[0]
    g["players"]["p1"]["silver"] = 0
    ok, err = place_building(g, "bank", sid, num)
    assert ok, err
    assert g["players"]["p1"]["silver"] == 2
    assert g["pending_pid"] is None


def test_boarding_gives_workers():
    g = fresh()
    sid, num = adj("beige")[0]
    g["players"]["p1"]["workers"] = 0
    ok, err = place_building(g, "boarding", sid, num)
    assert ok, err
    assert g["players"]["p1"]["workers"] == 4


def test_watchtower_scores():
    g = fresh()
    sid, num = adj("beige")[0]
    ok, err = place_building(g, "watchtower", sid, num)
    assert ok, err
    assert g["players"]["p1"]["vp"] == 4


# ── Buildings that take a tile to storage ─────────────────────────────────────
def test_market_take_ship_or_livestock():
    g = fresh()
    sid, num = adj("beige")[0]
    g["depots"]["1"]["hexes"] = [hext("ship", "blue", "ship_cand")]
    ok, err = place_building(g, "market", sid, num)
    assert ok, err
    assert g["pending_kind"] == "building_take_choice"
    ok2, err2 = engine.apply_move(g, "p1", {"type": "building_take_choice", "tile_id": "ship_cand"})
    assert ok2, err2
    assert any(t["id"] == "ship_cand" for t in g["players"]["p1"]["storage"])
    assert g["pending_pid"] is None


def test_market_no_candidates_no_pending():
    g = fresh()
    sid, num = adj("beige")[0]
    ok, err = place_building(g, "market", sid, num)
    assert ok, err
    assert g["pending_pid"] is None  # nothing to take -> just placed


def test_church_take_mine():
    g = fresh()
    sid, num = adj("beige")[0]
    g["depots"]["2"]["hexes"] = [hext("mine", "gray", "mine_cand")]
    ok, err = place_building(g, "church", sid, num)
    assert ok, err
    assert g["pending_kind"] == "building_take_choice"
    ok2, _ = engine.apply_move(g, "p1", {"type": "building_take_choice", "tile_id": "mine_cand"})
    assert ok2
    assert any(t["id"] == "mine_cand" for t in g["players"]["p1"]["storage"])


def test_skip_pending_works():
    g = fresh()
    sid, num = adj("beige")[0]
    g["depots"]["1"]["hexes"] = [hext("ship", "blue", "ship_cand")]
    place_building(g, "market", sid, num)
    assert g["pending_kind"] == "building_take_choice"
    ok, err = engine.apply_move(g, "p1", {"type": "skip_pending"})
    assert ok, err
    assert g["pending_pid"] is None
    assert g["players"]["p1"]["storage"] == []


# ── Warehouse + town hall ─────────────────────────────────────────────────────
def test_warehouse_sells_goods():
    g = fresh()
    sid, num = adj("beige")[0]
    g["players"]["p1"]["goods"] = {"amber": 2}
    ok, err = place_building(g, "warehouse", sid, num)
    assert ok, err
    assert g["pending_kind"] == "warehouse_sell"
    ok2, err2 = engine.apply_move(g, "p1", {"type": "warehouse_sell", "color": "amber"})
    assert ok2, err2
    assert "amber" not in g["players"]["p1"]["goods"]
    assert g["players"]["p1"]["vp"] == tiles.sell_vp_per_tile(2) * 2


def test_townhall_places_additional_tile_ignoring_number():
    g = fresh()
    sid, num = adj("beige")[0]
    # a second beige space to place the extra building on (number need NOT match)
    second = [s for s, n in adj("beige") if s != sid][0]
    g["players"]["p1"]["storage"] = [
        hext("building", "beige", "th", building="townhall"),
        hext("building", "beige", "extra", building="bank"),
    ]
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["silver"] = 0
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "th", "space_id": sid})
    assert ok, err
    assert g["pending_kind"] == "townhall_place"
    # place the bank on the second beige space ignoring its die number
    ok2, err2 = engine.apply_move(g, "p1", {"type": "townhall_place", "tile_id": "extra", "space_id": second})
    assert ok2, err2
    assert g["players"]["p1"]["duchy"][second]["building"] == "bank"
    assert g["players"]["p1"]["silver"] == 2  # bank effect fired
    assert g["pending_pid"] is None


# ── One building of each type per town ────────────────────────────────────────
def test_one_building_per_town():
    g = fresh()
    beige = adj("beige")
    (sid1, num1), (sid2, num2) = beige[0], beige[1]
    assert board.region_of(sid1) == board.region_of(sid2)  # same town
    ok, _ = place_building(g, "market", sid1, num1, tid="m1")
    assert ok
    # second market in the same town is rejected
    ok2, err2 = place_building(g, "market", sid2, num2, tid="m2")
    assert not ok2 and "town" in err2
    # a different building type IS allowed in the same town
    ok3, err3 = place_building(g, "bank", sid2, num2, tid="bk")
    assert ok3, err3


# ── Castle extra action ───────────────────────────────────────────────────────
def test_castle_grants_extra_action():
    g = fresh()
    # a burgundy space; enable adjacency without completing the burgundy region
    burg = [(s, i["number"]) for s, i in board.SPACES.items()
            if i["color"] == "burgundy" and not i["is_castle"]]
    sid, num = burg[0]
    enable_adj(g, sid)
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [hext("castle", "burgundy", "c")]
    g["players"]["p1"]["workers"] = 0
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "c", "space_id": sid})
    assert ok, err
    assert g["pending_kind"] == "extra_action"
    # use the extra action to take 2 workers (die value of your choice)
    ok2, err2 = engine.apply_move(g, "p1", {"type": "extra_action", "value": 3, "sub": {"type": "take_workers"}})
    assert ok2, err2
    assert g["players"]["p1"]["workers"] == 2
    assert g["pending_pid"] is None


# ── Ship: take goods now; advance the track marker at end of turn ─────────────
def test_ship_takes_goods_and_queues_track_advance():
    g = fresh()
    blue = [(s, i["number"]) for s, i in board.SPACES.items() if i["color"] == "blue"]
    sid, num = blue[0]
    enable_adj(g, sid)
    g["depots"]["4"]["goods"] = [{"id": "gd", "kind": "goods", "color": "rose"}]
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [hext("ship", "blue", "sh")]
    assert engine._player_space(g, "p1") == 0
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "sh", "space_id": sid})
    assert ok, err
    assert g["ship_advance_pending"] == 1
    assert g["pending_kind"] == "ship_choose_depot"
    ok2, err2 = engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 4})
    assert ok2, err2
    assert g["players"]["p1"]["goods"].get("rose") == 1
    assert engine._player_space(g, "p1") == 0          # not advanced yet
    engine.apply_move(g, "p1", {"type": "end_turn"})   # advance applies now
    assert engine._player_space(g, "p1") == 1


# ── Livestock pasture re-scoring ──────────────────────────────────────────────
def green_pair():
    reg = next(r for r in board.REGIONS.values() if r["color"] == "green")
    for a in reg["spaces"]:
        for b in board.neighbors(a):
            if b in reg["spaces"]:
                return a, b
    raise AssertionError("no adjacent green pair")


def test_livestock_same_animal_rescore():
    g = fresh()
    a, b = green_pair()
    g["players"]["p1"]["duchy"][a] = hext("livestock", "green", "cowA", animal="cow", count=3)
    g["dice"]["p1"]["values"] = [board.SPACES[b]["number"], 6]
    g["players"]["p1"]["storage"] = [hext("livestock", "green", "cowB", animal="cow", count=4)]
    g["players"]["p1"]["vp"] = 0
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "cowB", "space_id": b})
    assert ok, err
    # new 4-cow + existing 3-cow in same pasture = 7
    assert g["players"]["p1"]["vp"] == 7
    assert "cow" in g["players"]["p1"]["livestock_types"]


def test_livestock_single_scores_its_count():
    g = fresh()
    a, b = green_pair()
    enable_adj(g, b)
    g["dice"]["p1"]["values"] = [board.SPACES[b]["number"], 6]
    g["players"]["p1"]["storage"] = [hext("livestock", "green", "sheepB", animal="sheep", count=2)]
    g["players"]["p1"]["vp"] = 0
    ok, err = engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": "sheepB", "space_id": b})
    assert ok, err
    assert g["players"]["p1"]["vp"] == 2
