"""M8: end-of-game scoring and tiebreak chain."""
from games.castles_of_crimson import engine, board


def over_game():
    g = engine.new_game(["p1", "p2"], seed=1)
    g["phase"] = "over"
    for pid in ("p1", "p2"):
        p = g["players"][pid]
        p["vp"] = 0
        p["goods"] = {}
        p["silver"] = 0
        p["workers"] = 0
        p["monastery_effects"] = []
        p["claimed_bonus"] = []
    return g


def test_final_score_composition():
    g = over_game()
    p = g["players"]["p1"]
    p["vp"] = 10
    p["goods"] = {"amber": 2, "rose": 1}   # +3 (1 each)
    p["silver"] = 4                          # +4
    p["workers"] = 5                         # +2 (5 // 2)
    p["monastery_effects"] = [26]            # 3 VP per bonus tile
    p["claimed_bonus"] = [{"color": "gray", "vp": 5}]   # +3
    assert engine.final_scores(g)["p1"] == 10 + 3 + 4 + 2 + 3


def test_workers_round_down():
    g = over_game()
    g["players"]["p1"]["workers"] = 3   # -> +1
    assert engine.final_scores(g)["p1"] == 1


def test_winner_by_points():
    g = over_game()
    g["players"]["p1"]["vp"] = 12
    g["players"]["p2"]["vp"] = 9
    assert engine.winner(g) == "p1"


def test_tiebreak_fewest_empty_spaces():
    g = over_game()
    g["players"]["p1"]["vp"] = 5
    g["players"]["p2"]["vp"] = 5
    # Fill three extra spaces for p1 so it has fewer empty duchy spaces.
    empties_p1 = [sid for sid, t in g["players"]["p1"]["duchy"].items() if t is None][:3]
    for sid in empties_p1:
        g["players"]["p1"]["duchy"][sid] = {"id": "x" + sid, "kind": "hex", "type": "mine", "color": "gray"}
    assert engine.winner(g) == "p1"


def test_tiebreak_furthest_back_on_track():
    g = over_game()
    g["players"]["p1"]["vp"] = 5
    g["players"]["p2"]["vp"] = 5
    # Equal empties (touch neither duchy). Farthest back on the track wins.
    # p2 is furthest forward (space 6), p1 is at the back (space 0) -> p1 wins the tie.
    g["track"] = [["p1"], [], [], [], [], [], ["p2"]]
    assert engine.winner(g) == "p1"


def test_endgame_runs_to_completion_sets_winner():
    g = engine.new_game(["p1", "p2"], seed=21)
    while not engine.is_over(g):
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    assert g["winner"] in ("p1", "p2")
    s = engine.final_scores(g)
    assert s["p1"] >= 0 and s["p2"] >= 0
