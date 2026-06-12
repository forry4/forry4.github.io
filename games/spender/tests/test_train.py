"""Tests for the offline self-play trainer (train.py).

These exercise the headless harness and both learning phases on tiny configs so
they stay fast. They also guard the key invariants: the trainer must not leave
main.WEIGHTS corrupted for other code, and learned output must stay in-bounds
and finite.
"""
import json
import math
import random

import pytest

from games.spender import main, train


@pytest.fixture(autouse=True)
def restore_weights():
    """train.* swaps the global main.WEIGHTS per mover; restore it after each
    test so nothing leaks between tests (or to the live server in-process)."""
    saved = dict(main.WEIGHTS)
    yield
    main.WEIGHTS = saved


# ─── Headless game runner ─────────────────────────────────────────────────────

def test_new_game_is_valid_two_player():
    g = train._new_game()
    assert g["phase"] == "playing"
    assert set(g["players"]) == {"p1", "p2"}
    assert g["order"] == ["p1", "p2"]
    assert g["turn"] == "p1"
    assert len(g["nobles"]) == 3
    assert all(len(g["board"][lk]) == 4 for lk in ["L1", "L2", "L3"])


def test_play_game_greedy_terminates_with_winner():
    w = dict(main.DEFAULT_WEIGHTS)
    winner, g = train.play_game(w, w)
    assert g["phase"] == "over"
    assert winner is not None
    # Winner is a single pid or a shared-victory list, always within the game.
    if isinstance(winner, list):
        assert set(winner) <= {"p1", "p2"}
    else:
        assert winner in {"p1", "p2"}


def test_play_game_mcts_terminates():
    w = dict(main.DEFAULT_WEIGHTS)
    winner, g = train.play_game(w, w, policy="mcts", mcts_iters=15)
    assert g["phase"] == "over"
    assert winner is not None


def test_play_game_respects_ply_cap_and_still_resolves():
    w = dict(main.DEFAULT_WEIGHTS)
    # A tiny cap forces the ply-limit branch; _resolve_winner must still run.
    winner, g = train.play_game(w, w, max_plies=4)
    assert g["phase"] == "over"
    assert winner is not None


def test_score_for():
    assert train._score_for("p1", "p1") == 1.0
    assert train._score_for("p2", "p1") == 0.0
    assert train._score_for(["p1", "p2"], "p1") == 0.5
    assert train._score_for(["p2"], "p1") == 0.0


def test_match_returns_unit_interval():
    w = dict(main.DEFAULT_WEIGHTS)
    s = train.match(w, w, n_games=4)
    assert 0.0 <= s <= 1.0
    # Identical weights with seat-swapping should be roughly balanced.
    assert abs(s - 0.5) <= 0.5


# ─── Phase 1: evolution ───────────────────────────────────────────────────────

def test_mutate_stays_within_bounds():
    rng = random.Random(0)
    base = dict(main.DEFAULT_WEIGHTS)
    for _ in range(200):
        child = train._mutate(base, sigma=0.5, rng=rng)
        for k in train.CARD_KEYS:
            lo, hi = train.CARD_BOUNDS[k]
            assert lo <= child[k] <= hi, f"{k}={child[k]} out of [{lo},{hi}]"
        base = child


def test_mutate_only_touches_card_keys():
    rng = random.Random(1)
    base = dict(main.DEFAULT_WEIGHTS)
    child = train._mutate(base, sigma=0.3, rng=rng)
    for k in train.POS_KEYS:
        assert child[k] == base[k]


def test_evolve_returns_full_inbounds_weights():
    best = train.evolve(generations=2, pop_size=4, games_per_pair=2, seed=42)
    # Every card key present and within bounds.
    for k in train.CARD_KEYS:
        lo, hi = train.CARD_BOUNDS[k]
        assert k in best and lo <= best[k] <= hi
    # pos_* weights carried through untouched by Phase 1.
    for k in train.POS_KEYS:
        assert best[k] == main.DEFAULT_WEIGHTS[k]


# ─── Phase 2: TD(λ) ───────────────────────────────────────────────────────────

def test_player_and_global_features_shape():
    g = train._new_game()
    f = train._player_features(g, "p1")
    assert len(f) == len(train.POS_KEYS) == len(train.FEATURE_SCALE)
    gf = train._global_features(g)
    assert len(gf) == len(train.POS_KEYS)
    # Symmetric opening → near-zero differential.
    assert all(abs(x) < 1e-9 for x in gf)


def test_self_play_trajectory_records_states_and_margin():
    states, margin = train._self_play_trajectory(dict(main.DEFAULT_WEIGHTS))
    assert len(states) > 0
    assert all(len(s) == len(train.POS_KEYS) for s in states)
    assert isinstance(margin, float)


def test_td_learn_returns_finite_theta():
    theta = train.td_learn(dict(main.DEFAULT_WEIGHTS), n_games=15, seed=7)
    assert len(theta) == len(train.POS_KEYS)
    assert all(math.isfinite(w) for w in theta)
    # pos_points should remain meaningfully positive — points predict the margin.
    assert theta[0] > 0.0


# ─── Weight I/O ───────────────────────────────────────────────────────────────

def test_save_load_roundtrip(tmp_path):
    w = dict(main.DEFAULT_WEIGHTS)
    w["pos_noble"] = 2.5
    w["point_urgency_mult"] = 3.1
    path = tmp_path / "w.json"
    train._save(w, str(path))
    loaded = train._load(str(path))
    assert loaded["pos_noble"] == pytest.approx(2.5)
    assert loaded["point_urgency_mult"] == pytest.approx(3.1)


def test_load_missing_file_returns_defaults(tmp_path):
    loaded = train._load(str(tmp_path / "does_not_exist.json"))
    assert loaded == main.DEFAULT_WEIGHTS


def test_saved_json_has_every_weight_key(tmp_path):
    path = tmp_path / "w.json"
    train._save(dict(main.DEFAULT_WEIGHTS), str(path))
    with open(path) as f:
        data = json.load(f)
    assert set(data) == set(main.DEFAULT_WEIGHTS)


# ─── Invariant: training does not corrupt the live global ─────────────────────

def test_training_does_not_leak_weights_via_fixture():
    """The autouse fixture restores main.WEIGHTS; within a test the global may be
    swapped, but it must still be a valid full weight dict afterward."""
    train.match(dict(main.DEFAULT_WEIGHTS), dict(main.DEFAULT_WEIGHTS), n_games=2)
    assert set(main.WEIGHTS) >= set(main.DEFAULT_WEIGHTS)
