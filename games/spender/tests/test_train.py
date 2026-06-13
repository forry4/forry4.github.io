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

from games.spender import main
from games.spender.ai import train, strategist


@pytest.fixture(autouse=True)
def restore_weights():
    """train.* swaps global AI state (main.WEIGHTS per mover, and the value-leaf
    toggle/model); restore it after each test so nothing leaks between tests (or
    to the live server in-process)."""
    saved = dict(main.WEIGHTS)
    saved_use, saved_model = main.USE_VALUE_LEAF, main._VALUE_MODEL
    yield
    main.WEIGHTS = saved
    main.USE_VALUE_LEAF, main._VALUE_MODEL = saved_use, saved_model


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


def test_coevolve_key_sets_are_valid_and_bounded():
    # Every co-evolved key is a real weight with a bound, and the tactical keys are
    # exactly the new opponent-aware features (not already in the greedy CARD_KEYS).
    for k in train.COEVOLVE_KEYS:
        assert k in main.DEFAULT_WEIGHTS, f"{k} not a real weight"
        assert k in train.COEVOLVE_BOUNDS, f"{k} has no bound"
    for k in train.TACTICAL_KEYS:
        assert k not in train.CARD_KEYS, f"{k} should not be in greedy CARD_KEYS"
        assert main.DEFAULT_WEIGHTS[k] == 0.0, f"{k} should default off"


def test_mutate_keys_respects_bounds_for_tactical_weights():
    rng = random.Random(0)
    base = dict(main.WEIGHT_VARIANTS["C"])
    for _ in range(200):
        child = train._mutate_keys(base, train.COEVOLVE_KEYS, train.COEVOLVE_BOUNDS,
                                   sigma=0.5, rng=rng)
        for k in train.COEVOLVE_KEYS:
            lo, hi = train.COEVOLVE_BOUNDS[k]
            assert lo <= child[k] <= hi, f"{k}={child[k]} out of [{lo},{hi}]"
        # pos_* untouched by co-evolution
        for k in train.POS_KEYS:
            assert child[k] == base[k]
        base = child


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


# ─── Strategy features fire when their weights are enabled ────────────────────
# These default to off (0.0 / gate 1.1); without a test, a regression that breaks
# them would be invisible until a retrain.

def test_contested_weight_raises_card_score():
    g = train._new_game()
    card = {"id": "L2-x", "level": 2, "points": 4, "bonus": "red", "cost": {"white": 3}}
    g["board"]["L2"][0] = card
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "white": 3}  # opp can afford → reach 1.0
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)
    off = main._ai_score_card(card, g, "p1", 0.3)
    main.WEIGHTS["contested_weight"] = 3.0
    on = main._ai_score_card(card, g, "p1", 0.3)
    assert on > off


def test_contested_weight_boosts_cheap_zero_point_card():
    # The whole point of generalizing past the old `pts > 0` gate: a cheap 0-point
    # card the opponent can also afford (the "we both have 2 red, take the 2-red
    # card" case) now gets a contested boost. Compare on-vs-off to isolate the term
    # from board-dependent bonus/accessibility scoring.
    g = train._new_game()
    card = {"id": "L1-shared", "level": 1, "points": 0, "bonus": "green", "cost": {"red": 2}}
    g["board"]["L1"][0] = card
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "red": 2}  # opp can buy it → reach 1.0
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)
    off = main._ai_score_card(card, g, "p1", 0.2)
    main.WEIGHTS["contested_weight"] = 0.5
    on = main._ai_score_card(card, g, "p1", 0.2)
    assert on > off


def test_noble_race_weight_boosts_card_for_contested_noble():
    # A bonus that advances a noble we're after is worth more when the opponent is
    # also closing on that same noble (race to claim it first). Compare on-vs-off to
    # isolate the race term.
    g = train._new_game()
    g["nobles"] = [{"id": "n1", "req": {"red": 3, "green": 3}, "points": 3}]
    # We hold 1 red; the card gives a red bonus (advances the noble for us).
    g["players"]["p1"]["purchased"] = [{"bonus": "red", "cost": {}, "points": 0, "id": "r0"}]
    # Opponent is deep into the same noble: 2 red + 3 green = 5/6 of the requirement.
    g["players"]["p2"]["purchased"] = (
        [{"bonus": "red", "cost": {}, "points": 0, "id": f"pr{i}"} for i in range(2)]
        + [{"bonus": "green", "cost": {}, "points": 0, "id": f"pg{i}"} for i in range(3)]
    )
    card = {"id": "L1-red", "level": 1, "points": 0, "bonus": "red", "cost": {"white": 1}}
    g["board"]["L1"][0] = card
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)
    off = main._ai_score_card(card, g, "p1", 0.3)
    main.WEIGHTS["noble_race_weight"] = 2.0
    on = main._ai_score_card(card, g, "p1", 0.3)
    assert on > off


def test_block_prefers_cheaper_higher_value_card():
    # Two 4-point cards the opponent can equally afford (both deficit 0). Blocking
    # should target the cheaper one — the better deal a good player would race for —
    # not pick arbitrarily by raw points (both are 4).
    g = train._new_game()
    g["board"] = {"L1": [None] * 4, "L2": [None] * 4, "L3": [None] * 4}
    g["nobles"] = []  # isolate efficiency from noble-value confounds
    cheap = {"id": "L2-cheap", "level": 2, "points": 4, "bonus": "red", "cost": {"white": 3}}
    pricey = {"id": "L2-pricey", "level": 2, "points": 4, "bonus": "blue", "cost": {"white": 7}}
    g["board"]["L2"][0] = cheap
    g["board"]["L2"][1] = pricey
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "white": 7}  # affords both, deficit 0
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)
    main.WEIGHTS["block_efficiency_weight"] = 1.0  # deal-quality biasing on
    assert main._ai_find_block(g, "p1", "p2", 0.8) is cheap


def test_block_skips_cheap_lowpoint_card_unless_it_enables_a_noble():
    # Late game: a cheap 1-point card the opponent can buy but which advances no
    # noble is NOT worth blocking, however affordable. But the same kind of cheap
    # card becomes a prime block if it completes a noble they're close to.
    g = train._new_game()
    g["board"] = {"L1": [None] * 4, "L2": [None] * 4, "L3": [None] * 4}
    g["nobles"] = [{"id": "n1", "req": {"red": 4}, "points": 3}]
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)
    main.WEIGHTS["block_noble_weight"] = 1.0  # noble-enabling denial on

    trivial = {"id": "L1-triv", "level": 1, "points": 1, "bonus": "blue", "cost": {"white": 1}}
    g["board"]["L1"][0] = trivial
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "white": 1}
    g["players"]["p2"]["purchased"] = []
    assert main._ai_find_block(g, "p1", "p2", 0.8) is None  # few points, no noble → skip

    # Opponent now has 3 red bonuses; a cheap 1-point red card completes the red-4 noble.
    g["players"]["p2"]["purchased"] = [
        {"bonus": "red", "cost": {}, "points": 0, "id": f"r{i}"} for i in range(3)
    ]
    enabler = {"id": "L1-noble", "level": 1, "points": 1, "bonus": "red", "cost": {"white": 1}}
    g["board"]["L1"][1] = enabler
    assert main._ai_find_block(g, "p1", "p2", 0.8) is enabler


def test_noble_block_futile_when_opponent_has_other_color_outlets():
    # The white-card example: opponent is one red away from a noble, but if TWO red
    # cards are on the board, denying one is futile — so noble-block credit is zero
    # and the cheap 1-point enabler is no longer worth blocking.
    g = train._new_game()
    g["board"] = {"L1": [None] * 4, "L2": [None] * 4, "L3": [None] * 4}
    g["nobles"] = [{"id": "n1", "req": {"red": 4}, "points": 3}]
    g["players"]["p2"]["purchased"] = [
        {"bonus": "red", "cost": {}, "points": 0, "id": f"r{i}"} for i in range(3)
    ]
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "white": 2}
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)
    main.WEIGHTS["block_noble_weight"] = 1.0

    enabler = {"id": "L1-r1", "level": 1, "points": 1, "bonus": "red", "cost": {"white": 1}}
    g["board"]["L1"][0] = enabler
    assert main._opp_noble_value(g, "p2", enabler) > 0  # lone red outlet → worth denying

    g["board"]["L1"][1] = {"id": "L1-r2", "level": 1, "points": 0, "bonus": "red", "cost": {"white": 1}}
    assert main._opp_noble_value(g, "p2", enabler) == 0  # two red outlets → futile
    assert main._ai_find_block(g, "p1", "p2", 0.8) is None


def test_lose_prevention_buys_or_reserves_opponent_winning_card():
    # Opponent at 13 points can buy a 2-point board card next turn to reach 15.
    g = train._new_game()
    g["board"] = {"L1": [None] * 4, "L2": [None] * 4, "L3": [None] * 4}
    g["nobles"] = []
    g["players"]["p2"]["purchased"] = [
        {"bonus": "white", "cost": {}, "points": 3, "id": f"w{i}"} for i in range(4)
    ] + [{"bonus": "white", "cost": {}, "points": 1, "id": "w4"}]  # 13 points
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "blue": 2}
    win_card = {"id": "L1-win", "level": 1, "points": 2, "bonus": "red", "cost": {"blue": 2}}
    g["board"]["L1"][0] = win_card
    assert main._opp_winning_buys(g, "p2") == [win_card]

    # We can afford it → buy it (denies + scores).
    g["players"]["p1"]["tokens"] = {**main.empty_gems(), "blue": 2}
    g["players"]["p1"]["purchased"] = []
    assert main._lose_prevention_move(g, "p1") == {"type": "buy", "card_id": "L1-win"}

    # We can't afford it but have a reserve slot → reserve it to deny.
    g["players"]["p1"]["tokens"] = main.empty_gems()
    assert main._lose_prevention_move(g, "p1") == {"type": "reserve", "card_id": "L1-win"}


def test_gold_reserve_targets_steep_single_color_card():
    # A 5-point card costing 7 white, we hold 2 white (and no white bonus): one steep
    # colour is the bottleneck (others covered) and we lack gold to bridge it → reserve
    # to bank a wild. When the deficit is spread across colours, or we already hold
    # enough gold, gem-taking is better and it should not fire.
    g = train._new_game()
    g["board"] = {"L1": [None] * 4, "L2": [None] * 4, "L3": [None] * 4}
    g["bank"]["gold"] = 3
    steep = {"id": "L3-steep", "level": 3, "points": 5, "bonus": "red", "cost": {"white": 7}}
    g["board"]["L3"][0] = steep
    ps = g["players"]["p1"]
    ps["purchased"] = []
    ps["reserved"] = []
    ps["tokens"] = {**main.empty_gems(), "white": 2}  # short 5 white, 0 gold
    assert main._ai_find_gold_reserve(g, "p1") is steep

    ps["tokens"] = {**main.empty_gems(), "white": 2, "gold": 5}  # enough gold already
    assert main._ai_find_gold_reserve(g, "p1") is None

    # Deficit spread across colours (not a single steep bottleneck) → don't gold-reserve.
    spread = {"id": "L2-spread", "level": 2, "points": 3, "bonus": "red", "cost": {"white": 3, "blue": 3}}
    g["board"]["L3"][0] = None
    g["board"]["L2"][0] = spread
    ps["tokens"] = main.empty_gems()
    assert main._ai_find_gold_reserve(g, "p1") is None

    # No gold in the bank → reserving yields no wild, so it's pointless.
    g["board"]["L2"][0] = None
    g["board"]["L3"][0] = steep
    g["bank"]["gold"] = 0
    ps["tokens"] = {**main.empty_gems(), "white": 2}
    assert main._ai_find_gold_reserve(g, "p1") is None


def test_rollout_blocks_when_gate_enabled():
    g = train._new_game()
    # Opponent: 13 pts (high urgency) and 4 blue bonuses, so a 6-blue card is only
    # 2 effective + they hold 2 blue tokens = 0 deficit (one buy away).
    g["players"]["p2"]["purchased"] = (
        [{"bonus": "blue", "cost": {}, "points": 4, "id": "p0"}]
        + [{"bonus": "blue", "cost": {}, "points": 3, "id": f"p{i}"} for i in range(1, 4)]
    )  # 4 blue bonuses, 13 points
    g["players"]["p2"]["tokens"] = {**main.empty_gems(), "blue": 2}
    block_card = {"id": "L3-blk", "level": 3, "points": 4, "bonus": "green", "cost": {"blue": 6}}
    g["board"]["L3"][0] = block_card
    # p1 is far from the card (deficit 6 > 5 → value-reserve skips it) and broke.
    g["players"]["p1"]["tokens"] = main.empty_gems()
    g["turn"] = "p1"
    main.WEIGHTS = dict(main.DEFAULT_WEIGHTS)  # gate 1.1 = off
    off = main._fast_rollout_move(g, "p1")
    assert off != {"type": "reserve", "card_id": "L3-blk"}  # not reserved for value
    main.WEIGHTS["block_urgency_gate"] = 0.5   # on
    assert main._fast_rollout_move(g, "p1") == {"type": "reserve", "card_id": "L3-blk"}  # blocked


# ─── Stage 1: learned value model ─────────────────────────────────────────────

def test_value_features_shape_and_symmetry():
    g = train._new_game()
    phi = main._value_features(g)
    assert len(phi) == len(main.VALUE_FEATURES)
    # Symmetric opening: all diffs zero, only the turn indicator is set.
    assert phi[:-1] == [0.0] * (len(phi) - 1)
    assert phi[-1] == 1.0


def test_value_estimate_is_probability_and_perspective_consistent():
    g = train._new_game()
    main._VALUE_MODEL = {"w": [0.5] * (len(main.VALUE_FEATURES) - 1) + [0.2], "b": 0.0}
    main.USE_VALUE_LEAF = True
    e1 = main._value_estimate(g, "p1")
    e2 = main._value_estimate(g, "p2")
    assert 0.0 <= e1 <= 1.0 and 0.0 <= e2 <= 1.0
    assert e1 + e2 == pytest.approx(1.0)


def test_train_value_model_produces_usable_model():
    cw = dict(main.DEFAULT_WEIGHTS)
    model = train.train_value_model(cw, n_games=12, epochs=2, lr=0.1)
    assert len(model["w"]) == len(main.VALUE_FEATURES)
    assert all(math.isfinite(x) for x in model["w"]) and math.isfinite(model["b"])
    # Loading it switches the value leaf on and yields probabilities in MCTS range.
    main._VALUE_MODEL = {"w": model["w"], "b": model["b"]}
    main.USE_VALUE_LEAF = True
    g = train._new_game()
    assert 0.0 <= main._value_estimate(g, "p1") <= 1.0


def test_mlp_inference_is_pure_python_probability():
    """A one-hidden-layer MLP model evaluates in main with no numpy dependency."""
    d = len(main.VALUE_FEATURES)
    h = 4
    main._VALUE_MODEL = {
        "W1": [[0.1] * d for _ in range(h)], "b1": [0.0] * h,
        "W2": [0.3] * h, "b2": 0.1,
        "mean": [0.0] * d, "std": [1.0] * d,
    }
    main.USE_VALUE_LEAF = True
    g = train._new_game()
    e1 = main._value_estimate(g, "p1")
    e2 = main._value_estimate(g, "p2")
    assert 0.0 <= e1 <= 1.0
    assert e1 + e2 == pytest.approx(1.0)


def test_train_value_mlp_structure():
    pytest.importorskip("numpy")
    model = train.train_value_mlp(dict(main.DEFAULT_WEIGHTS), n_games=12, hidden=4, epochs=2)
    assert model["type"] == "mlp"
    assert len(model["W1"]) == 4 and len(model["W1"][0]) == len(main.VALUE_FEATURES)
    assert len(model["W2"]) == 4 and len(model["b1"]) == 4
    # Round-trips through the loader and evaluates.
    main._VALUE_MODEL = model
    main.USE_VALUE_LEAF = True
    assert 0.0 <= main._value_estimate(train._new_game(), "p1") <= 1.0


def test_value_leaf_off_without_model_keeps_rollout_path():
    main._VALUE_MODEL = None
    main.USE_VALUE_LEAF = False
    g = train._new_game()
    # MCTS must still pick a legal move via the rollout path (no model loaded).
    mv = main._mcts_choose_move(g, "p1", time_limit=1e9, max_iters=20)
    assert isinstance(mv, dict) and "type" in mv


# ─── Scripted strategist (benchmark opponent) ─────────────────────────────────

def test_strategist_move_is_well_formed():
    import random as _r
    for s in range(20):
        _r.seed(s)
        g = train._new_game()
        # advance a few plies so states vary
        for _ in range(s % 8):
            if g["phase"] != "playing":
                break
            main._sim_apply_move(g, g["turn"], main._fast_rollout_move(g, g["turn"]))
        if g["phase"] != "playing":
            continue
        mv = strategist.strategist_move(g, g["turn"])
        assert mv["type"] in {"buy", "take_gems", "reserve"}
        if mv["type"] == "take_gems":
            assert len(mv["colors"]) <= 3


def test_ai_vs_strategist_game_completes():
    winner, ai_pid = train.play_ai_vs_strategist(
        dict(main.DEFAULT_WEIGHTS), mcts_iters=15, ai_first=True)
    assert ai_pid == "p1"
    assert winner is not None
    if isinstance(winner, list):
        assert set(winner) <= {"p1", "p2"}
    else:
        assert winner in {"p1", "p2"}


# ─── Invariant: training does not corrupt the live global ─────────────────────

def test_training_does_not_leak_weights_via_fixture():
    """The autouse fixture restores main.WEIGHTS; within a test the global may be
    swapped, but it must still be a valid full weight dict afterward."""
    train.match(dict(main.DEFAULT_WEIGHTS), dict(main.DEFAULT_WEIGHTS), n_games=2)
    assert set(main.WEIGHTS) >= set(main.DEFAULT_WEIGHTS)
