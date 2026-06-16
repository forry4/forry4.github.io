"""MCTS AI: strength, no-deadlock across pendings, determinization fairness, eval.

Search budgets are kept tiny so the suite stays fast; strength still shows clearly
because the AI crushes the random bot by large margins even at low iteration counts.
"""
import random

import pytest

from games.castles_of_crimson import engine, ai, bot, board
from games.castles_of_crimson import ai_selfplay
from .conftest import complete_setup

# Tiny, iteration-bound budgets (high time_limit so wall-clock never binds in CI).
TINY = {"time_limit": 5.0, "max_iters": 25, "temperature": 0.0, "rollout_depth": 5}
TINY_N = {"time_limit": 5.0, "max_iters": 25, "temperature": 0.6, "rollout_depth": 5}


@pytest.fixture
def tiny_budgets(monkeypatch):
    monkeypatch.setitem(ai.DIFFICULTY, "hard", dict(TINY))
    monkeypatch.setitem(ai.DIFFICULTY, "normal", dict(TINY_N))


def _playing_game(seed=2):
    g = engine.new_game(["p1", "p2"], seed=seed)
    complete_setup(g)
    return g


# ── Strength ──────────────────────────────────────────────────────────────────
def test_hard_beats_random(tiny_budgets):
    win_rate, a_pts, b_pts = ai_selfplay.arena("hard", "random", n=4, seed0=0)
    assert win_rate >= 0.75, f"win_rate={win_rate}"
    assert a_pts > b_pts + 15, f"AI {a_pts} vs random {b_pts}"


# ── No deadlock: full AI-vs-AI games complete and resolve every pending kind ─────
def test_full_ai_game_completes_no_deadlock(tiny_budgets):
    for seed in (1, 7):
        rng = random.Random(seed)
        g = ai_selfplay.play_game(
            ai_selfplay.make_player("hard"), ai_selfplay.make_player("normal"),
            seed=seed, rng=rng)
        assert engine.is_over(g), f"seed {seed} did not finish"
        assert g["winner"] in ("P0", "P1") or isinstance(g["winner"], list)
        s = engine.final_scores(g)
        assert set(s) == {"P0", "P1"}


def test_plan_resolves_a_ship_pending(tiny_budgets):
    # Force a ship-placement pending and confirm the planner drives through it.
    g = _playing_game(seed=3)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    b = board.get_board("1")
    sid, num = next((s, i["number"]) for s, i in b.SPACES.items() if i["color"] == "blue")
    nb = b.neighbors(sid)[0]
    g["players"]["p1"]["duchy"][nb] = {"id": "d", "kind": "hex", "type": "mine", "color": "gray"}
    g["dice"]["p1"]["values"] = [num, 6]
    g["players"]["p1"]["storage"] = [{"id": "sh", "kind": "hex", "type": "ship", "color": "blue"}]
    g["depots"]["3"]["goods"] = [{"id": "gd", "kind": "goods", "color": "rose"}]
    seq = ai.play_turn_plan(g, "p1", difficulty="hard", rng=random.Random(0))
    # apply the plan to a fresh copy and confirm it ends the turn cleanly
    work = ai._clone_game(g)
    for mv in seq:
        if ai._actor(work) != "p1":
            break
        assert engine.apply_move(work, "p1", mv)[0], mv
    assert seq and seq[-1]["type"] == "end_turn"
    assert work["pending_pid"] is None


# ── Fairness: the AI must not exploit the hidden (undrawn) supply order ──────────
def test_move_invariant_under_supply_reshuffle():
    g = _playing_game(seed=5)
    pid = ai._actor(g)
    kw = dict(time_limit=5.0, max_iters=120, temperature=0.0, rollout_depth=6)
    m1 = ai.choose_move(g, pid, rng=random.Random(7), **kw)

    g2 = ai._clone_game(g)
    random.Random(999).shuffle(g2["supply"])     # scramble the hidden order
    random.Random(998).shuffle(g2["black_supply"])
    m2 = ai.choose_move(g2, pid, rng=random.Random(7), **kw)

    assert ai._move_key(m1) == ai._move_key(m2), (m1, m2)


def test_determinism_same_seed():
    g = _playing_game(seed=8)
    pid = ai._actor(g)
    kw = dict(time_limit=5.0, max_iters=120, temperature=0.0, rollout_depth=6)
    m1 = ai.choose_move(g, pid, rng=random.Random(3), **kw)
    m2 = ai.choose_move(g, pid, rng=random.Random(3), **kw)
    assert ai._move_key(m1) == ai._move_key(m2)


# ── Eval sanity ─────────────────────────────────────────────────────────────────
def test_value_rewards_scoring_and_filling():
    g = _playing_game(seed=4)
    pid = "p1"
    base = ai._value(g, pid)
    g2 = ai._clone_game(g)
    p = g2["players"][pid]
    b = board.get_board(p.get("board_id"))
    empty = next(s for s, t in p["duchy"].items() if t is None)
    p["duchy"][empty] = {"id": "x", "kind": "hex", "type": "mine",
                         "color": b.SPACES[empty]["color"]}
    p["vp"] += 5                     # banked some points + filled a space
    assert ai._value(g2, pid) > base


def test_setup_move_picks_a_burgundy_space():
    g = engine.new_game(["p1", "p2"], seed=1)
    mv = ai._setup_move(g, "p1")
    assert mv["type"] == "place_starting_castle"
    assert board.get_board("1").SPACES[mv["space_id"]]["color"] == "burgundy"
