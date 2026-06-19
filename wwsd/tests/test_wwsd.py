"""Tests for the WWSD service: deck-rebuild correctness, analyze() on real dumps, and the
HTTP handler's secret/json guards. No external deps (no httpx) — the handler is tested via the
pure `process_move` function. Search budget is forced small via WWSD_TIME for speed."""
import json
import os
from collections import Counter

os.environ.setdefault("WWSD_SECRET", "testsecret")   # must be set BEFORE importing wwsd.app
os.environ.setdefault("WWSD_TIME", "0.4")

from wwsd import analyze as W           # noqa: E402
from wwsd import app as A               # noqa: E402
from wwsd import bookmarklet as B       # noqa: E402

# A real in-progress dump (CPU vs guest2273055, 15-pt, guest's opening turn).
LIVE = {"games": [{
    "status": "INPROGRESS",
    "settings": {"targetScore": "15"},
    "players": [{"name": "CPU"}, {"name": "guest2273055"}],
    "data": {"bank": {
        "hiddenCards": [[17,34,32,29,27,37,33,16,28,25,19,38,8,24,26,36,22,20,10,30,31,9,6,0,11,13,18,4,35,7,21,15,1,3,14,23],
                        [40,50,41,62,66,53,45,49,60,52,69,43,56,42,51,57,64,63,44,55,67,59,54,68,58,46],
                        [85,82,77,75,81,83,76,70,87,84,79,71,80,72,88,89]],
        "showedCards": [[39,2,5,12],[61,65,47,48],[73,74,86,78]],
        "nobles": [2,3,4], "chips": [4,3,3,3,4], "goldChips": 5},
        "players": [{"purchasedCards": [], "reservedCards": [], "nobles": [], "chips": [0,1,1,1,0], "goldChips": 0},
                    {"purchasedCards": [], "reservedCards": [], "nobles": [], "chips": [0,0,0,0,0], "goldChips": 0}],
        "state": {"currentPlayerIndex": 1, "currentJob": "SPENDEE_REGULAR"}}}]}

# Final snapshot of a completed game (guest2254478 vs NguyenTu65, 21-pt) — for deck-rebuild checks.
FINAL = {"bank": {
    "hiddenCards": [[35,3,17,23,15,5,19,24,0,18,37,28],
                    [42,47,49,62,50,56,53,64,52,69,40,68,45,54,60,58],
                    [78,73,74,80,87,70,72,82,86,84,77,79,81]],
    "showedCards": [[27,9,31,26],[48,55,66,57],[71,None,83,88]],
    "nobles": [], "chips": [3,4,3,3,3], "goldChips": 3},
    "players": [
        {"purchasedCards": [6,16,59,33,61,13,21,39,1,11,30,12,22,32,67,65,85], "reservedCards": [43,41], "nobles": [2], "chips": [1,0,0,1,0], "goldChips": 2},
        {"purchasedCards": [20,4,51,38,2,8,25,29,14,10,44,7,36,46,34,89,63,76], "reservedCards": [75], "nobles": [6,5], "chips": [0,0,1,0,1], "goldChips": 0}]}


def test_deck_rebuild_partition_and_scoring():
    """Override installs the friend's deck: all 90 cards partition once, tokens conserve, and each
    claimed noble is satisfied by that player's card bonuses + the winner reaches the target."""
    W.prepare()
    seen = Counter()
    for lvl in range(3):
        seen.update(FINAL["bank"]["hiddenCards"][lvl])
        seen.update(x for x in FINAL["bank"]["showedCards"][lvl] if x is not None)
    for p in FINAL["players"]:
        seen.update(p["purchasedCards"]); seen.update(p["reservedCards"])
    assert set(seen) == set(range(90)) and all(v == 1 for v in seen.values())

    tot = [FINAL["bank"]["chips"][k] + sum(p["chips"][k] for p in FINAL["players"]) for k in range(5)]
    assert tot == [4, 4, 4, 4, 4]
    assert FINAL["bank"]["goldChips"] + sum(p["goldChips"] for p in FINAL["players"]) == 5

    pts = []
    for p in FINAL["players"]:
        from wwsd.analyze import E
        bon = Counter(E.BONUS[ci] for ci in p["purchasedCards"])
        assert all(all(bon[c] >= E.NOBLE_REQ[ni][c] for c in range(5)) for ni in p["nobles"])
        pts.append(sum(E.PTS[ci] for ci in p["purchasedCards"]) + sum(E.NOBLE_PTS[i] for i in p["nobles"]))
    assert max(pts) >= 21          # the winner reached the (21-pt) target


def test_analyze_live_position_returns_a_move():
    r = W.analyze(LIVE, time_limit=0.4)
    assert r["ok"] is True
    assert r["turn_name"] == "guest2273055" and r["target"] == 15
    assert isinstance(r["recommendation"], str) and r["recommendation"]
    assert r["sims"] >= 1


def test_analyze_finished_game_has_no_move():
    r = W.analyze({"games": [{"status": "FINISHED", "settings": {"targetScore": "21"},
                              "players": [{"name": "a"}, {"name": "b"}],
                              "data": {**FINAL, "state": {"currentPlayerIndex": 0}}}]})
    assert r["ok"] is False and "finished" in r["message"].lower()


def test_process_move_secret_and_json_guards():
    body = json.dumps(LIVE).encode()
    assert A.process_move(body, "", "1.1.1.1")[0] == 401              # missing secret
    assert A.process_move(body, "wrong", "1.1.1.1")[0] == 401         # wrong secret
    assert A.process_move(b"{not json", "testsecret", "1.1.1.1")[0] == 400
    code, out = A.process_move(body, "testsecret", "1.1.1.1")
    assert code == 200 and out["ok"] is True and out["recommendation"]


def test_build_bookmarklet_fills_placeholders():
    bm = B.build_bookmarklet("https://wwsd.example.com/move", "s3cr3t")
    assert "https://wwsd.example.com/move" in bm and "s3cr3t" in bm
    assert "__MOVE_URL__" not in bm and "__SECRET__" not in bm and "__SECS__" not in bm
    assert bm.startswith("javascript:")
    assert "var SECS=0;" in bm                                   # default think-time (server default)


def test_build_bookmarklet_seconds_front_loaded():
    bm = B.build_bookmarklet("https://wwsd.example.com/move", "s3cr3t", seconds=15)
    assert "var SECS=15;" in bm
    assert bm.index("SECS=15") < bm.index("https://wwsd.example.com/move")  # config is at the front


def test_budget_clamps_t_param():
    assert A._budget(None) == A.TIME_BUDGET          # absent -> server default
    assert A._budget("abc") == A.TIME_BUDGET         # invalid -> server default
    assert A._budget("12") == 12.0                   # within range, honoured
    assert A._budget("9999") == A.TIME_MAX           # clamp to ceiling (Cloudflare safety)
    assert A._budget("0.01") == A.TIME_MIN           # clamp to floor
