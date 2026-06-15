"""M7: one test per monastery effect (1-26)."""
import pytest

from games.castles_of_crimson import engine, board, tiles
from .conftest import complete_setup, DEFAULT_CASTLE

CASTLE = DEFAULT_CASTLE


def fresh(effects=()):
    g = engine.new_game(["p1", "p2"], seed=1)
    complete_setup(g)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    for d in range(1, 7):
        g["depots"][str(d)]["hexes"] = []
        g["depots"][str(d)]["goods"] = []
    p = g["players"]["p1"]
    p["goods"] = {}
    p["vp"] = 0
    p["monastery_effects"] = list(effects)
    return g


def hext(ttype, color, tid="t", **extra):
    t = {"id": tid, "kind": "hex", "type": ttype, "color": color}
    t.update(extra)
    return t


def adj(color):
    return [(nb, board.SPACES[nb]["number"]) for nb in board.neighbors(CASTLE)
            if board.SPACES[nb]["color"] == color]


def enable_adj(g, sid):
    nb = board.neighbors(sid)[0]
    if g["players"]["p1"]["duchy"][nb] is None:
        g["players"]["p1"]["duchy"][nb] = hext("mine", "gray", "dummy_" + nb)


def place(g, tile, sid, die):
    g["dice"]["p1"]["values"] = [die, 6]
    g["dice"]["p1"]["used"] = [False, False]
    g["players"]["p1"]["storage"] = [tile]
    return engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": tile["id"], "space_id": sid})


def green_pair():
    reg = next(r for r in board.REGIONS.values() if r["color"] == "green")
    for a in reg["spaces"]:
        for b in board.neighbors(a):
            if b in reg["spaces"]:
                return a, b
    raise AssertionError


# ── Continuous effects ────────────────────────────────────────────────────────
def test_m1_no_one_building_per_town():
    g = fresh(effects=[1])
    (s1, n1), (s2, n2) = adj("beige")[0], adj("beige")[1]
    assert place(g, hext("building", "beige", "m1", building="market"), s1, n1)[0]
    # second market in same town normally illegal; effect 1 permits it
    ok, err = place(g, hext("building", "beige", "m2", building="market"), s2, n2)
    assert ok, err


def test_m2_worker_per_mine_at_phase_end():
    g = fresh(effects=[2])
    g["players"]["p1"]["mines_count"] = 3
    w0 = g["players"]["p1"]["workers"]
    for _ in range(10):  # one full phase
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    assert g["players"]["p1"]["workers"] == w0 + 3


def test_m3_two_silver_on_sell():
    g = fresh(effects=[3])
    g["players"]["p1"]["goods"] = {"amber": 1}
    g["players"]["p1"]["silver"] = 0
    g["dice"]["p1"]["values"] = [1, 6]
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert g["players"]["p1"]["silver"] == 2


def test_m4_worker_on_sell():
    g = fresh(effects=[4])
    g["players"]["p1"]["goods"] = {"amber": 1}
    g["players"]["p1"]["workers"] = 0
    g["dice"]["p1"]["values"] = [1, 6]
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert g["players"]["p1"]["workers"] == 1


def test_m5_ship_takes_adjacent_depot():
    g = fresh(effects=[5])
    sid, num = next((s, i["number"]) for s, i in board.SPACES.items() if i["color"] == "blue")
    enable_adj(g, sid)
    g["depots"]["3"]["goods"] = [{"id": "g3", "kind": "goods", "color": "rose"}]
    g["depots"]["4"]["goods"] = [{"id": "g4", "kind": "goods", "color": "jade"}]
    assert place(g, hext("ship", "blue", "sh"), sid, num)[0]
    engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    assert g["players"]["p1"]["goods"].get("rose") == 1
    # Monastery 5 now offers a CHOICE of adjacent depot (depot 4 holds goods).
    assert g["pending_kind"] == "ship_adjacent_depot"
    assert g["pending"]["ctx"]["candidates"] == [4]
    ok, err = engine.apply_move(g, "p1", {"type": "ship_adjacent_take", "depot": 4})
    assert ok, err
    assert g["players"]["p1"]["goods"].get("jade") == 1   # chose adjacent depot 4
    assert g["pending_pid"] is None


def test_m5_adjacent_choice_can_be_skipped():
    g = fresh(effects=[5])
    sid, num = next((s, i["number"]) for s, i in board.SPACES.items() if i["color"] == "blue")
    enable_adj(g, sid)
    g["depots"]["3"]["goods"] = [{"id": "g3", "kind": "goods", "color": "rose"}]
    g["depots"]["4"]["goods"] = [{"id": "g4", "kind": "goods", "color": "jade"}]
    assert place(g, hext("ship", "blue", "sh"), sid, num)[0]
    engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    assert g["pending_kind"] == "ship_adjacent_depot"
    engine.apply_move(g, "p1", {"type": "skip_pending"})
    assert g["players"]["p1"]["goods"].get("jade") is None  # declined the bonus
    assert g["pending_pid"] is None


def test_m5_no_pending_when_no_adjacent_goods():
    g = fresh(effects=[5])
    sid, num = next((s, i["number"]) for s, i in board.SPACES.items() if i["color"] == "blue")
    enable_adj(g, sid)
    g["depots"]["3"]["goods"] = [{"id": "g3", "kind": "goods", "color": "rose"}]
    assert place(g, hext("ship", "blue", "sh"), sid, num)[0]
    engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    # Neither depot 2 nor 4 holds goods -> no follow-up decision.
    assert g["pending_pid"] is None
    assert g["players"]["p1"]["goods"].get("rose") == 1


def test_m6_spend_workers_for_building():
    g = fresh(effects=[6])
    g["players"]["p1"]["workers"] = 2
    g["depots"]["2"]["hexes"] = [hext("building", "beige", "bb", building="bank")]
    ok, err = engine.apply_move(g, "p1", {"type": "monastery6_take", "tile_id": "bb"})
    assert ok, err
    assert any(t["id"] == "bb" for t in g["players"]["p1"]["storage"])
    assert g["players"]["p1"]["workers"] == 0
    # once per turn
    g["depots"]["2"]["hexes"] = [hext("building", "beige", "bb2", building="bank")]
    g["players"]["p1"]["workers"] = 2
    ok2, _ = engine.apply_move(g, "p1", {"type": "monastery6_take", "tile_id": "bb2"})
    assert not ok2


def test_m7_livestock_bonus():
    g = fresh(effects=[7])
    a, b = green_pair()
    g["players"]["p1"]["duchy"][a] = hext("livestock", "green", "cowA", animal="cow", count=3)
    ok, err = place(g, hext("livestock", "green", "cowB", animal="cow", count=4), b, board.SPACES[b]["number"])
    assert ok, err
    # base 4+3=7, plus +1 per scoring tile (2 tiles) = 9
    assert g["players"]["p1"]["vp"] == 9


def test_m8_worker_adjusts_by_two():
    g = fresh(effects=[8])
    g["players"]["p1"]["workers"] = 1
    g["dice"]["p1"]["values"] = [1, 6]
    # 1 -> 3 is two steps; with effect 8 one worker covers it
    ok, err = engine.apply_move(g, "p1", {"type": "adjust_die", "die_index": 0, "to": 3})
    assert ok, err
    assert g["dice"]["p1"]["values"][0] == 3
    assert g["players"]["p1"]["workers"] == 0


@pytest.mark.parametrize("eid,color,ttype,extra", [
    (9, "beige", "building", {"building": "bank"}),
    (10, "blue", "ship", {}),
    (11, "gray", "mine", {}),
])
def test_m9_10_11_free_shift_on_place(eid, color, ttype, extra):
    g = fresh(effects=[eid])
    sid, num = next((s, i["number"]) for s, i in board.SPACES.items() if i["color"] == color)
    enable_adj(g, sid)
    off = num % 6 + 1  # a die value one step away from the required number
    ok, err = place(g, hext(ttype, color, "x", **extra), sid, off)
    assert ok, err
    # without the effect the same off-by-one placement must fail
    g2 = fresh()
    enable_adj(g2, sid)
    ok2, _ = place(g2, hext(ttype, color, "x", **extra), sid, off)
    assert not ok2


def test_m12_free_shift_on_take():
    g = fresh(effects=[12])
    g["dice"]["p1"]["values"] = [3, 6]
    g["depots"]["4"]["hexes"] = [hext("mine", "gray", "adj")]  # adjacent depot
    ok, err = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 0, "depot": 4, "tile_id": "adj"})
    assert ok, err


def test_m13_silver_on_take_workers():
    g = fresh(effects=[13])
    g["players"]["p1"]["silver"] = 0
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert g["players"]["p1"]["silver"] == 1


def test_m14_four_workers():
    g = fresh(effects=[14])
    g["players"]["p1"]["workers"] = 0
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert g["players"]["p1"]["workers"] == 4


# ── End-game scoring effects ──────────────────────────────────────────────────
def test_m15_sold_goods_types():
    g = fresh(effects=[15])
    g["players"]["p1"]["sold_goods"] = ["amber", "amber", "rose"]   # 2 types
    assert engine._endgame_monastery_vp(g, "p1") == 4


@pytest.mark.parametrize("eid,bt", list(tiles.MONASTERY_BUILDING_SCORING.items()))
def test_m16_23_building_scoring(eid, bt):
    g = fresh(effects=[eid])
    g["players"]["p1"]["buildings_placed"][bt] = 2
    assert engine._endgame_monastery_vp(g, "p1") == 8


def test_m24_livestock_types():
    g = fresh(effects=[24])
    g["players"]["p1"]["livestock_types"] = ["cow", "sheep", "pig"]
    assert engine._endgame_monastery_vp(g, "p1") == 12


def test_m25_goods_sold_count():
    g = fresh(effects=[25])
    g["players"]["p1"]["sold_goods"] = ["amber", "rose", "jade", "rose"]
    assert engine._endgame_monastery_vp(g, "p1") == 4


def test_m26_bonus_tiles():
    g = fresh(effects=[26])
    g["players"]["p1"]["claimed_bonus"] = [{"color": "gray", "vp": 5}, {"color": "blue", "vp": 2}]
    assert engine._endgame_monastery_vp(g, "p1") == 6


def test_all_26_effects_have_meta():
    assert set(tiles.MONASTERY_META) == set(range(1, 27))
