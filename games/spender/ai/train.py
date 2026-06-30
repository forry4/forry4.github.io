"""Self-play training for the Spender AI.

This is an OFFLINE tool. It never touches the server, the database, or any live
game. It plays the AI against itself thousands of times to learn better values
for the heuristic constants defined in ``main.DEFAULT_WEIGHTS`` and writes the
result to ``weights.json`` (loaded by ``main.load_weights`` at server startup).

Two complementary learners, run in sequence by ``all``:

  Phase 1 — Evolutionary search (``evolve``)
      A population of weight vectors plays a round-robin self-play tournament.
      The card-scoring weights (``_ai_score_card`` / rollout policy) are mutated
      and selected by win rate. This is a broad, gradient-free global search over
      how the AI *chooses moves*.

  Phase 2 — TD(0) learning (``td``)
      Starting from Phase 1's policy, the AI plays itself and we learn a linear
      position-evaluator (the ``pos_*`` weights used to score truncated MCTS
      rollouts) via temporal-difference updates toward the realised point margin.
      This refines how the AI *evaluates positions*.

The two phases tune different, composable parts of the same agent: Phase 1 the
move policy, Phase 2 the position evaluation that policy's tree search leans on.

Usage:
    python -m games.spender.ai.train all      --out games/spender/ai/weights.json
    python -m games.spender.ai.train evolve    --generations 15 --pop 10
    python -m games.spender.ai.train td        --games 2000
    python -m games.spender.ai.train validate  --games 40        # MCTS, learned vs default
    python -m games.spender.ai.train tournament                  # real-MCTS A/B/C round-robin
    python -m games.spender.ai.train coevolve                    # tune tactics under real MCTS
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import time

from games.spender import main
from games.spender.ai import strategist

# ─── Weight groups ────────────────────────────────────────────────────────────

# Tuned by Phase 1 (how the policy picks moves).
CARD_KEYS = [
    "point_urgency_mult", "efficiency_weight", "bonus_l1", "bonus_l2", "bonus_l3",
    "bonus_reserved", "bonus_target_pts", "bonus_urgency_decay", "noble_card",
    "noble_scarcity", "contested_weight", "access_base", "access_urgency",
    "rollout_reserve_threshold", "block_urgency_gate",
]

# Tuned by Phase 2 (how the policy evaluates truncated positions). Order MUST
# match _player_features() below.
POS_KEYS = ["pos_points", "pos_buyable", "pos_noble", "pos_bonus_count", "pos_noble_scarcity"]

# (min, max) clamps applied after every mutation so the search stays in a sane,
# meaningful region (non-negative utilities; decay kept a true 0..1 fraction).
CARD_BOUNDS = {
    "point_urgency_mult": (0.0, 10.0),
    "efficiency_weight": (0.0, 10.0),
    "bonus_l1": (0.0, 2.0),
    "bonus_l2": (0.0, 2.0),
    "bonus_l3": (0.0, 2.0),
    "bonus_reserved": (0.0, 2.0),
    "bonus_target_pts": (0.0, 1.0),
    "bonus_urgency_decay": (0.0, 1.0),
    "noble_card": (0.0, 3.0),
    "noble_scarcity": (0.0, 4.0),
    "contested_weight": (0.0, 5.0),
    "access_base": (0.01, 2.0),
    "access_urgency": (0.0, 2.0),
    "rollout_reserve_threshold": (0.0, 15.0),
    "block_urgency_gate": (0.0, 1.1),
}

# Opponent-aware tactical weights (added after the original CARD_KEYS were frozen).
# These are excluded from the greedy `evolve` because greedy self-play can't judge
# them — its opponent never threatens coherently, so denial/race/lose-prevention
# never pay off (documented). The `coevolve` mode tunes them under REAL-MCTS games,
# where threats ARE coherent, to test whether they survive selection.
TACTICAL_KEYS = [
    "noble_race_weight", "block_efficiency_weight", "block_noble_weight",
    "lose_prevention", "gold_reserve",
]
TACTICAL_BOUNDS = {
    "noble_race_weight": (0.0, 4.0),
    "block_efficiency_weight": (0.0, 3.0),
    "block_noble_weight": (0.0, 3.0),
    "lose_prevention": (0.0, 1.0),   # used as a truthy gate (>0 = on)
    "gold_reserve": (0.0, 1.0),      # used as a truthy gate (>0 = on)
}
# Co-evolution tunes the move policy AND the tactical features together. CARD_KEYS
# already covers contested_weight / noble_scarcity; pos_* are left fixed.
COEVOLVE_KEYS = CARD_KEYS + TACTICAL_KEYS
COEVOLVE_BOUNDS = {**CARD_BOUNDS, **TACTICAL_BOUNDS}

WEIGHTS_OUT = os.path.join(os.path.dirname(__file__), "weights.json")


# ─── Headless game runner ─────────────────────────────────────────────────────

def _new_game(order=("p1", "p2")) -> dict:
    """Build a fresh 2-player game dict (mirrors the server's vs-AI setup)."""
    decks = main.build_deck()
    bank = {c: 4 for c in main.GEM_COLORS}
    bank["gold"] = 5
    g = {
        "bank": bank,
        "decks": decks,
        "board": main._deal_board(decks),
        "players": {p: {"tokens": main.empty_gems(), "purchased": [],
                        "reserved": [], "nobles": []} for p in order},
        "order": list(order),
        "turn": order[0],
        "phase": "playing",
        "winner": None,
        "moves": [],
    }
    nobles = list(main.ALL_NOBLES)
    random.shuffle(nobles)
    g["nobles"] = nobles[:3]
    return g


def play_game(weights_p1: dict, weights_p2: dict, *, policy: str = "greedy",
              mcts_iters: int = 150, mcts_time: float | None = None, max_plies: int = 250,
              value_pids: set | None = None) -> tuple[str | list, dict]:
    """Play one headless game. ``weights_p1``/``weights_p2`` are full weight dicts;
    the global WEIGHTS is swapped to the mover's weights before each decision so
    each side reasons through its own heuristic. ``value_pids`` (mcts policy only)
    selects which side evaluates MCTS leaves with the learned value model vs the
    greedy rollout. ``mcts_time`` (seconds/move) uses a wall-clock budget instead
    of a fixed ``mcts_iters`` — the realistic test, since value-leaf does far more
    iterations per second. Returns (winner, final_game)."""
    g = _new_game()
    by_pid = {"p1": weights_p1, "p2": weights_p2}
    plies = 0
    while g["phase"] == "playing" and plies < max_plies:
        pid = g["turn"]
        main.WEIGHTS = by_pid[pid]
        if policy == "mcts":
            if value_pids is not None:
                main.USE_VALUE_LEAF = (pid in value_pids) and (main._VALUE_MODEL is not None)
            mv = main._mcts_choose_move(
                g, pid,
                time_limit=(mcts_time if mcts_time else 1e9),
                max_iters=(None if mcts_time else mcts_iters))
        else:
            mv = main._fast_rollout_move(g, pid)
        main._sim_apply_move(g, pid, mv)
        plies += 1
    if g["phase"] != "over":
        main._resolve_winner(g)  # hit ply cap — score by points/tiebreak
    return g["winner"], g


def _score_for(winner: str | list, pid: str) -> float:
    """1.0 win, 0.5 shared, 0.0 loss."""
    if winner == pid:
        return 1.0
    if isinstance(winner, list) and pid in winner:
        return 0.5
    return 0.0


def match(weights_a: dict, weights_b: dict, n_games: int, *,
          policy: str = "greedy", mcts_iters: int = 150,
          base_seed: int = 0) -> float:
    """Play ``n_games`` between A and B, alternating who moves first to cancel the
    first-move advantage. Returns A's average score in [0,1]."""
    total = 0.0
    for i in range(n_games):
        random.seed(base_seed + i)
        if i % 2 == 0:
            winner, _ = play_game(weights_a, weights_b, policy=policy, mcts_iters=mcts_iters)
            total += _score_for(winner, "p1")
        else:  # swap seats so B leads
            winner, _ = play_game(weights_b, weights_a, policy=policy, mcts_iters=mcts_iters)
            total += _score_for(winner, "p2")
    return total / n_games


# ─── Phase 1: evolutionary search ─────────────────────────────────────────────

def _mutate(weights: dict, sigma: float, rng: random.Random) -> dict:
    """Gaussian perturbation of the card-scoring weights, clamped to bounds."""
    child = dict(weights)
    for k in CARD_KEYS:
        lo, hi = CARD_BOUNDS[k]
        span = hi - lo
        child[k] = min(hi, max(lo, weights[k] + rng.gauss(0.0, sigma * span)))
    return child


def _round_robin_fitness(pop: list[dict], games_per_pair: int, seed: int) -> list[float]:
    """Every individual plays every other; fitness = average score across all its
    games (so the strongest move-policy rises regardless of seat or opponent)."""
    n = len(pop)
    score = [0.0] * n
    played = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            a = match(pop[i], pop[j], games_per_pair, base_seed=seed + i * 1000 + j)
            score[i] += a * games_per_pair
            score[j] += (1.0 - a) * games_per_pair
            played[i] += games_per_pair
            played[j] += games_per_pair
    return [score[i] / played[i] if played[i] else 0.0 for i in range(n)]


def evolve(generations: int, pop_size: int, games_per_pair: int, *,
           elite_frac: float = 0.3, sigma: float = 0.15, seed: int = 1234,
           start: dict | None = None) -> dict:
    """Evolve the card-scoring weights by self-play tournament. Returns the best
    full weight dict found (pos_* weights carried through unchanged)."""
    rng = random.Random(seed)
    base = start or dict(main.DEFAULT_WEIGHTS)
    # Seed the population with the incumbent plus mutated variants.
    pop = [dict(base)] + [_mutate(base, sigma, rng) for _ in range(pop_size - 1)]
    n_elite = max(1, int(round(pop_size * elite_frac)))

    best, best_fit = dict(base), -1.0
    for gen in range(generations):
        t0 = time.time()
        fit = _round_robin_fitness(pop, games_per_pair, seed + gen)
        ranked = sorted(range(len(pop)), key=lambda i: fit[i], reverse=True)
        elites = [pop[i] for i in ranked[:n_elite]]
        if fit[ranked[0]] > best_fit:
            best_fit, best = fit[ranked[0]], dict(pop[ranked[0]])

        # Next generation: keep elites, fill the rest with mutated elites.
        decay = sigma * (1.0 - 0.6 * gen / max(1, generations - 1))  # anneal step size
        nxt = [dict(e) for e in elites]
        while len(nxt) < pop_size:
            parent = elites[rng.randrange(len(elites))]
            nxt.append(_mutate(parent, decay, rng))
        pop = nxt
        print(f"[evolve] gen {gen+1}/{generations}  best_fit={fit[ranked[0]]:.3f}  "
              f"overall_best={best_fit:.3f}  ({time.time()-t0:.1f}s)")
    print("[evolve] best card weights:")
    for k in CARD_KEYS:
        print(f"    {k:28s} {best[k]:.3f}  (was {main.DEFAULT_WEIGHTS[k]})")
    return best


# ─── Real-MCTS tournament + tactical co-evolution ─────────────────────────────
# The greedy `evolve` above can't judge opponent-aware tactics (its rollout
# opponent never threatens coherently). These run games under ACTUAL MCTS, so a
# competent racing/blocking opponent exists and tactical features can be rewarded
# — or shown to still not matter. Value-leaf is forced off (rollout MCTS) so the
# card weights / tactical features are what's being measured, matching the
# A/B/C playtest configs.

def _mutate_keys(weights: dict, keys: list[str], bounds: dict, sigma: float,
                 rng: random.Random) -> dict:
    """Gaussian perturbation of `keys`, each clamped to its bound."""
    child = dict(weights)
    for k in keys:
        lo, hi = bounds[k]
        child[k] = min(hi, max(lo, weights[k] + rng.gauss(0.0, sigma * (hi - lo))))
    return child


def _round_robin_fitness_mcts(pop: list[dict], games_per_pair: int,
                              mcts_iters: int, seed: int) -> list[float]:
    """Round-robin fitness under real-MCTS games (coherent threats)."""
    n = len(pop)
    score = [0.0] * n
    played = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            a = match(pop[i], pop[j], games_per_pair, policy="mcts",
                      mcts_iters=mcts_iters, base_seed=seed + i * 1000 + j)
            score[i] += a * games_per_pair
            score[j] += (1.0 - a) * games_per_pair
            played[i] += games_per_pair
            played[j] += games_per_pair
    return [score[i] / played[i] if played[i] else 0.0 for i in range(n)]


def tournament(configs: dict[str, dict], games_per_pair: int, mcts_iters: int,
               seed: int = 20) -> dict[str, float]:
    """Real-MCTS round-robin among named weight configs. Prints a win-rate matrix
    and ranking; returns {name: avg_score across all its games}."""
    main.USE_VALUE_LEAF = False  # rollout MCTS — measure the card/tactical weights
    names = list(configs)
    n = len(names)
    mat: dict[str, dict[str, float | None]] = {a: {b: None for b in names} for a in names}
    tot = {a: 0.0 for a in names}
    played = {a: 0 for a in names}
    print(f"[tournament] {n} configs, {games_per_pair} games/pair, "
          f"{mcts_iters} iters/move (rollout MCTS)")
    for i in range(n):
        for j in range(i + 1, n):
            a, b = names[i], names[j]
            t0 = time.time()
            s = match(configs[a], configs[b], games_per_pair, policy="mcts",
                      mcts_iters=mcts_iters, base_seed=seed + i * 1000 + j)
            mat[a][b], mat[b][a] = s, 1.0 - s
            tot[a] += s * games_per_pair
            tot[b] += (1.0 - s) * games_per_pair
            played[a] += games_per_pair
            played[b] += games_per_pair
            print(f"  {a:>12} vs {b:<12} {s:.3f} : {1 - s:.3f}  ({time.time() - t0:.0f}s)")
    avg = {a: (tot[a] / played[a] if played[a] else 0.0) for a in names}
    print("\n[tournament] win-rate matrix (row's score vs col):")
    print("            " + "".join(f"{b:>12}" for b in names))
    for a in names:
        cells = "".join((f"{mat[a][b]:>12.3f}" if mat[a][b] is not None else f"{'—':>12}")
                        for b in names)
        print(f"{a:>12}{cells}")
    print("\n[tournament] ranking:")
    for a in sorted(names, key=lambda x: -avg[x]):
        print(f"  {a:>12}  {avg[a]:.3f}")
    return avg


def coevolve(generations: int, pop_size: int, games_per_pair: int, mcts_iters: int, *,
             start: dict, sigma: float = 0.15, seed: int = 2024,
             also_seed: dict | None = None) -> dict:
    """Evolve move-policy + tactical weights together under real-MCTS round-robin
    self-play. Each generation prints the best fitness and the population-MEAN of
    every tactical weight, so we can watch whether selection keeps the opponent-
    aware features on (they help) or erodes them toward 0 (the documented blindness,
    now under coherent threats). Returns the best full weight dict found."""
    main.USE_VALUE_LEAF = False
    rng = random.Random(seed)
    base = dict(start)
    pop = [dict(base)] + [_mutate_keys(base, COEVOLVE_KEYS, COEVOLVE_BOUNDS, sigma, rng)
                          for _ in range(pop_size - 1)]
    if also_seed is not None and pop_size >= 2:
        pop[1] = dict(also_seed)  # guarantee a tactics-off lineage is represented
    n_elite = max(1, int(round(pop_size * 0.3)))
    best, best_fit = dict(base), -1.0
    print(f"[coevolve] pop={pop_size} gpp={games_per_pair} iters={mcts_iters} "
          f"gens={generations} — tuning {len(COEVOLVE_KEYS)} weights under rollout MCTS")
    for gen in range(generations):
        t0 = time.time()
        fit = _round_robin_fitness_mcts(pop, games_per_pair, mcts_iters, seed + gen)
        ranked = sorted(range(len(pop)), key=lambda i: fit[i], reverse=True)
        elites = [pop[i] for i in ranked[:n_elite]]
        if fit[ranked[0]] > best_fit:
            best_fit, best = fit[ranked[0]], dict(pop[ranked[0]])
        tmeans = {k: sum(p[k] for p in pop) / len(pop) for k in TACTICAL_KEYS}
        decay = sigma * (1.0 - 0.6 * gen / max(1, generations - 1))
        nxt = [dict(e) for e in elites]
        while len(nxt) < pop_size:
            parent = elites[rng.randrange(len(elites))]
            nxt.append(_mutate_keys(parent, COEVOLVE_KEYS, COEVOLVE_BOUNDS, decay, rng))
        pop = nxt
        tm = "  ".join(f"{k.split('_')[0]}={tmeans[k]:.2f}" for k in TACTICAL_KEYS)
        print(f"[coevolve] gen {gen + 1}/{generations} best={fit[ranked[0]]:.3f} "
              f"overall={best_fit:.3f} | pop-mean {tm} ({time.time() - t0:.0f}s)")
    print("[coevolve] best tactical weights:")
    for k in TACTICAL_KEYS:
        print(f"    {k:28s} {best[k]:.3f}")
    return best


# ─── Phase 2: TD(0) position-evaluator learning ───────────────────────────────

def _player_features(game: dict, pid: str) -> list[float]:
    """Feature vector for one player, ordered to match POS_KEYS. Mirrors the
    quantities used by main._sim_rollout's _pos_score."""
    ps = game["players"][pid]
    bonuses = main.bonuses_from(ps["purchased"])
    pts = main._calc_points(ps)
    buyable = sum(
        c["points"] for lk in ["L3", "L2", "L1"]
        for c in (game["board"].get(lk) or [])
        if c and main.can_afford(c["cost"], ps["tokens"], bonuses)
    ) + sum(
        c["points"] for c in ps["reserved"]
        if main.can_afford(c["cost"], ps["tokens"], bonuses)
    )
    noble_prox = sum(
        n["points"] / (sum(max(0, need - bonuses.get(c, 0))
                           for c, need in n["req"].items()) + 1)
        for n in (game.get("nobles") or [])
    )
    bonus_count = sum(bonuses.get(c, 0) for c in main.GEM_COLORS)
    # Scarcity-gated noble proximity (board scarcity is shared by both players).
    scarce_noble = noble_prox * main._board_scarcity(game)
    return [float(pts), float(buyable), float(noble_prox), float(bonus_count), float(scarce_noble)]


def _global_features(game: dict) -> list[float]:
    """p1-minus-p2 feature differential — a perspective-independent state vector."""
    fa = _player_features(game, "p1")
    fb = _player_features(game, "p2")
    return [a - b for a, b in zip(fa, fb)]


# Rough magnitudes of each raw feature, used to scale them to ~O(1) so a single
# fixed learning rate behaves well across features. Learning happens in scaled
# space; weights are converted back to raw units before being returned.
FEATURE_SCALE = [15.0, 10.0, 3.0, 8.0, 3.0]   # points, buyable, noble_prox, bonus_count, scarce_noble


def _self_play_trajectory(card_weights: dict, max_plies: int = 250):
    """Play one greedy self-play game (both sides share the policy) and return
    (list_of_scaled_global_feature_vectors, final_point_margin p1-p2)."""
    g = _new_game()
    main.WEIGHTS = card_weights
    states: list[list[float]] = []
    plies = 0
    while g["phase"] == "playing" and plies < max_plies:
        raw = _global_features(g)
        states.append([x / s for x, s in zip(raw, FEATURE_SCALE)])
        main._sim_apply_move(g, g["turn"], main._fast_rollout_move(g, g["turn"]))
        plies += 1
    if g["phase"] != "over":
        main._resolve_winner(g)
    margin = (main._calc_points(g["players"]["p1"])
              - main._calc_points(g["players"]["p2"]))
    return states, float(margin)


def td_learn(card_weights: dict, n_games: int, *, alpha: float = 0.02,
             gamma: float = 1.0, lam: float = 0.9, seed: int = 99,
             theta0: list[float] | None = None):
    """TD(λ) learning (with eligibility traces) of the linear position evaluator
    V(s) = theta · phi(s), trained to predict the realised point margin from
    self-play trajectories.

    Eligibility traces with λ close to 1 blend toward a Monte-Carlo target, which
    avoids the instability of pure one-step bootstrapping (TD(0)) on the highly
    correlated consecutive board states this game produces. Features are scaled
    to ~O(1) (see FEATURE_SCALE); the returned theta is converted back to raw
    units aligned to POS_KEYS."""
    rng = random.Random(seed)
    # Convert any incoming raw weights into scaled space for learning.
    raw0 = theta0 if theta0 else [main.DEFAULT_WEIGHTS[k] for k in POS_KEYS]
    theta = [w * s for w, s in zip(raw0, FEATURE_SCALE)]

    running = None
    for game_i in range(n_games):
        random.seed(rng.randrange(1 << 30))
        states, margin = _self_play_trajectory(card_weights)
        if not states:
            continue
        elig = [0.0] * len(theta)
        for t in range(len(states)):
            phi = states[t]
            v = sum(w * x for w, x in zip(theta, phi))
            if t + 1 < len(states):
                v_next = sum(w * x for w, x in zip(theta, states[t + 1]))
                reward = 0.0
            else:
                v_next = 0.0          # terminal: outcome carried by reward
                reward = margin
            delta = reward + gamma * v_next - v
            elig = [gamma * lam * e + x for e, x in zip(elig, phi)]
            theta = [w + alpha * delta * e for w, e in zip(theta, elig)]

        # Smoothed prediction error over the informative *second half* of the
        # game (the symmetric opening has a ~zero differential and carries no
        # signal about the outcome, so averaging it in would just measure the
        # inherent variance of game margins).
        half = states[len(states) // 2:]
        err = sum(abs(margin - sum(w * x for w, x in zip(theta, s))) for s in half) / len(half)
        running = err if running is None else 0.99 * running + 0.01 * err
        if (game_i + 1) % max(1, n_games // 10) == 0:
            raw = [w / s for w, s in zip(theta, FEATURE_SCALE)]
            print(f"[td] game {game_i+1}/{n_games}  smoothed_err={running:.3f}  "
                  f"theta_raw=[{', '.join(f'{w:.3f}' for w in raw)}]")

    theta_raw = [w / s for w, s in zip(theta, FEATURE_SCALE)]
    print("[td] learned position weights:")
    for k, w in zip(POS_KEYS, theta_raw):
        print(f"    {k:18s} {w:.3f}  (was {main.DEFAULT_WEIGHTS[k]})")
    return theta_raw


# ─── Stage 1: learned value model (NNUE-style leaf evaluation) ────────────────

VALUE_MODEL_OUT = os.path.join(os.path.dirname(__file__), "value_model.json")


def _exploratory_move(game: dict, pid: str, epsilon: float, rng: random.Random) -> dict:
    """Greedy policy with epsilon-random deviations. Exploration is what gives the
    value model varied positions — including the threatening / blockable ones that
    pure greedy self-play never visits."""
    if rng.random() < epsilon:
        moves = main._get_all_moves(game, pid)
        return moves[rng.randrange(len(moves))]
    return main._fast_rollout_move(game, pid)


def _value_self_play(card_weights: dict, epsilon: float, rng: random.Random,
                     max_plies: int = 250):
    """Play one exploratory self-play game; return (list of value-feature vectors
    for each visited state, outcome label for order[0]: 1.0 win / 0.5 tie / 0.0 loss)."""
    main.WEIGHTS = card_weights
    g = _new_game()
    states: list[list[float]] = []
    plies = 0
    while g["phase"] == "playing" and plies < max_plies:
        states.append(main._value_features(g))
        mv = _exploratory_move(g, g["turn"], epsilon, rng)
        main._sim_apply_move(g, g["turn"], mv)
        plies += 1
    if g["phase"] != "over":
        main._resolve_winner(g)
    w = g.get("winner")
    order = g["order"]
    label = 0.5 if isinstance(w, list) else (1.0 if w == order[0] else 0.0)
    return states, label


def _logloss_acc(Xs, y, w, b):
    """Mean cross-entropy and decisive-game accuracy (ties excluded) of the model."""
    ll = 0.0
    correct = decisive = 0
    for xi, yi in zip(Xs, y):
        z = b + sum(wj * xj for wj, xj in zip(w, xi))
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
        ll -= yi * math.log(p + 1e-9) + (1 - yi) * math.log(1 - p + 1e-9)
        if yi != 0.5:
            decisive += 1
            correct += int((p >= 0.5) == (yi >= 0.5))
    return ll / len(y), (correct / decisive if decisive else float("nan"))


def train_value_model(card_weights: dict, n_games: int, *, epsilon: float = 0.08,
                      epochs: int = 12, lr: float = 0.05, l2: float = 1e-3,
                      seed: int = 2024) -> dict:
    """Generate self-play data and fit a logistic value model V(s)=sigmoid(w·φ+b)
    predicting P(order[0] wins). Light exploration keeps games strong (so outcomes
    stay learnable); L2 + lr-decay keep the weights conditioned. Reports held-out
    logloss/accuracy each epoch (split by GAME to avoid leaking correlated
    positions). Folds standardisation into raw-feature weights before returning."""
    rng = random.Random(seed)
    games_data: list[tuple[list, float]] = []
    for i in range(n_games):
        random.seed(rng.randrange(1 << 30))
        games_data.append(_value_self_play(card_weights, epsilon, rng))
        if (i + 1) % max(1, n_games // 10) == 0:
            pos = sum(len(s) for s, _ in games_data)
            print(f"[value] self-play {i+1}/{n_games} games  ({pos} positions)")

    n_test = max(1, n_games // 5)                     # hold out whole games
    def flat(gs):
        X, y = [], []
        for states, label in gs:
            X.extend(states); y.extend([label] * len(states))
        return X, y
    Xte_raw, yte = flat(games_data[:n_test])
    Xtr_raw, ytr = flat(games_data[n_test:])

    d = len(Xtr_raw[0])
    n = len(Xtr_raw)
    mean = [sum(r[j] for r in Xtr_raw) / n for j in range(d)]
    var = [sum((r[j] - mean[j]) ** 2 for r in Xtr_raw) / n for j in range(d)]
    std = [math.sqrt(v) if v > 1e-9 else 1.0 for v in var]
    def stdize(R): return [[(r[j] - mean[j]) / std[j] for j in range(d)] for r in R]
    Xtr, Xte = stdize(Xtr_raw), stdize(Xte_raw)

    w = [0.0] * d
    b = 0.0
    idx = list(range(n))
    for ep in range(epochs):
        lr_ep = lr / (1.0 + 0.3 * ep)                 # decay
        rng.shuffle(idx)
        for i in idx:
            xi = Xtr[i]
            z = b + sum(w[j] * xi[j] for j in range(d))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = p - ytr[i]
            for j in range(d):
                w[j] -= lr_ep * (err * xi[j] + l2 * w[j])   # L2 weight decay
            b -= lr_ep * err
        tr_ll, _ = _logloss_acc(Xtr, ytr, w, b)
        te_ll, te_acc = _logloss_acc(Xte, yte, w, b)
        print(f"[value] epoch {ep+1}/{epochs}  train_ll={tr_ll:.4f}  "
              f"test_ll={te_ll:.4f}  test_acc={te_acc:.3f}")

    w_raw = [w[j] / std[j] for j in range(d)]
    b_raw = b - sum(w[j] * mean[j] / std[j] for j in range(d))
    return {"w": w_raw, "b": b_raw, "features": main.VALUE_FEATURES,
            "trained_games": n_games, "positions": n + len(Xte_raw)}


def train_value_mlp(card_weights: dict, n_games: int, *, hidden: int = 24,
                    epsilon: float = 0.08, epochs: int = 30, lr: float = 0.05,
                    l2: float = 1e-4, batch: int = 256, seed: int = 2024) -> dict:
    """Fit a one-hidden-layer tanh MLP value model V(s)=sigmoid(W2·tanh(W1·x+b1)+b2)
    predicting P(order[0] wins). Non-linear, so it can capture engine interactions
    the linear model can't (which is why the linear model capped ~0.65 accuracy).
    Trains with numpy (offline); the saved model is plain JSON lists so main.py
    runs inference in pure Python. Reports held-out logloss/accuracy (split by game)."""
    try:
        import numpy as np
    except ImportError:
        raise SystemExit("MLP training needs numpy (offline only): pip install numpy")

    rng = random.Random(seed)
    games_data = []
    for i in range(n_games):
        random.seed(rng.randrange(1 << 30))
        games_data.append(_value_self_play(card_weights, epsilon, rng))
        if (i + 1) % max(1, n_games // 10) == 0:
            pos = sum(len(s) for s, _ in games_data)
            print(f"[mlp] self-play {i+1}/{n_games} games  ({pos} positions)")

    n_test = max(1, n_games // 5)
    def flat(gs):
        X, y = [], []
        for states, label in gs:
            X.extend(states); y.extend([label] * len(states))
        return np.array(X, dtype=float), np.array(y, dtype=float)
    Xte, yte = flat(games_data[:n_test])
    Xtr, ytr = flat(games_data[n_test:])

    mean, std = Xtr.mean(0), Xtr.std(0)
    std[std < 1e-9] = 1.0
    Xtr = (Xtr - mean) / std
    Xte = (Xte - mean) / std

    d = Xtr.shape[1]
    nprng = np.random.RandomState(seed)
    W1 = nprng.randn(hidden, d) * math.sqrt(1.0 / d)
    b1 = np.zeros(hidden)
    W2 = nprng.randn(hidden) * math.sqrt(1.0 / hidden)
    b2 = 0.0

    def fwd(X):
        A1 = np.tanh(X @ W1.T + b1)
        Z2 = A1 @ W2 + b2
        return A1, 1.0 / (1.0 + np.exp(-np.clip(Z2, -30, 30)))

    def metrics(X, y):
        _, p = fwd(X)
        ll = -np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9))
        dec = y != 0.5
        acc = np.mean((p[dec] >= 0.5) == (y[dec] >= 0.5)) if dec.any() else float("nan")
        return float(ll), float(acc)

    n = Xtr.shape[0]
    order = np.arange(n)
    for ep in range(epochs):
        lr_ep = lr / (1.0 + 0.2 * ep)
        nprng.shuffle(order)
        for s in range(0, n, batch):
            bi = order[s:s + batch]
            X, y = Xtr[bi], ytr[bi]
            A1, p = fwd(X)
            m = len(bi)
            dZ2 = (p - y) / m
            dW2 = A1.T @ dZ2 + l2 * W2
            db2 = dZ2.sum()
            dA1 = np.outer(dZ2, W2)
            dZ1 = dA1 * (1 - A1 ** 2)
            dW1 = dZ1.T @ X + l2 * W1
            db1 = dZ1.sum(0)
            W1 -= lr_ep * dW1; b1 -= lr_ep * db1
            W2 -= lr_ep * dW2; b2 -= lr_ep * db2
        tr_ll, _ = metrics(Xtr, ytr)
        te_ll, te_acc = metrics(Xte, yte)
        print(f"[mlp] epoch {ep+1}/{epochs}  train_ll={tr_ll:.4f}  "
              f"test_ll={te_ll:.4f}  test_acc={te_acc:.3f}")

    return {"type": "mlp", "mean": mean.tolist(), "std": std.tolist(),
            "W1": W1.tolist(), "b1": b1.tolist(), "W2": W2.tolist(), "b2": float(b2),
            "hidden": hidden, "features": main.VALUE_FEATURES, "trained_games": n_games}


def _save_value(model: dict, path: str) -> None:
    """Write a value model (linear or MLP) to JSON, rounding floats for compactness."""
    def rnd(o):
        if isinstance(o, float):
            return round(o, 6)
        if isinstance(o, list):
            return [rnd(x) for x in o]
        return o
    with open(path, "w") as f:
        json.dump({k: rnd(v) for k, v in model.items()}, f, indent=2)
    print(f"[io] wrote {path}")


def validate_value(weights: dict, n_games: int, mcts_iters: int,
                   mcts_time: float | None = None, seed: int = 11) -> float:
    """A/B test: same weights both sides, but one side evaluates MCTS leaves with
    the learned value model and the other with the greedy rollout. Isolates the
    ONLY difference — leaf evaluation. With ``mcts_time`` (seconds/move) this is the
    realistic test — value-leaf gets to do many more iterations in the same wall
    time (its actual advantage). Returns the value side's score."""
    if main.load_value_model() is None:
        raise SystemExit("no value model to validate")
    budget = f"{mcts_time}s/move" if mcts_time else f"{mcts_iters} iters/move"
    print(f"[validate-value] {n_games} MCTS games ({budget}), value-leaf vs rollout-leaf...")
    t0 = time.time()
    total = 0.0
    for i in range(n_games):
        random.seed(seed + i)
        vside = "p1" if i % 2 == 0 else "p2"   # alternate which seat uses value
        winner, _ = play_game(weights, weights, policy="mcts", mcts_iters=mcts_iters,
                              mcts_time=mcts_time, value_pids={vside})
        total += _score_for(winner, vside)
    main.load_value_model()  # reset USE_VALUE_LEAF to its loaded default
    s = total / n_games
    print(f"[validate-value] value-leaf scored {s:.3f} vs rollout {1-s:.3f}  "
          f"({'better' if s > 0.5 else 'not better'})  ({time.time()-t0:.1f}s)")
    return s


# ─── Benchmark vs the scripted strategist (non-self-play opponent) ────────────

def play_ai_vs_strategist(weights: dict, *, mcts_iters: int | None = 150,
                          mcts_time: float | None = None, ai_first: bool = True,
                          use_value: bool = False, max_plies: int = 250):
    """One game: the real MCTS AI vs the scripted strategist. Returns (winner, ai_pid)."""
    g = _new_game()
    ai_pid = "p1" if ai_first else "p2"
    main.WEIGHTS = weights
    main.USE_VALUE_LEAF = use_value and main._VALUE_MODEL is not None
    plies = 0
    while g["phase"] == "playing" and plies < max_plies:
        pid = g["turn"]
        if pid == ai_pid:
            mv = main._mcts_choose_move(
                g, pid, time_limit=(mcts_time if mcts_time else 1e9),
                max_iters=(None if mcts_time else mcts_iters))
        else:
            mv = strategist.strategist_move(g, pid)
        main._sim_apply_move(g, pid, mv)
        plies += 1
    if g["phase"] != "over":
        main._resolve_winner(g)
    return g["winner"], ai_pid


def benchmark_vs_strategist(weights: dict, n_games: int, *, mcts_iters: int = 150,
                            mcts_time: float | None = None, use_value: bool = False,
                            seed: int = 5) -> float:
    """Play the AI against the strategist over n_games (alternating who starts).
    This is the measurement self-play can't give us: a coherent, *threatening*
    opponent against which target-play and blocking actually matter. Returns the
    AI's score."""
    if use_value and main.load_value_model() is None:
        raise SystemExit("--value requested but no value model is loaded")
    budget = f"{mcts_time}s/move" if mcts_time else f"{mcts_iters} iters/move"
    leaf = "value-leaf" if use_value else "rollout-leaf"
    print(f"[benchmark] {n_games} games, {leaf} MCTS ({budget}) vs strategist...")
    t0 = time.time()
    total = 0.0
    for i in range(n_games):
        random.seed(seed + i)
        winner, ai_pid = play_ai_vs_strategist(
            weights, mcts_iters=mcts_iters, mcts_time=mcts_time,
            ai_first=(i % 2 == 0), use_value=use_value)
        total += _score_for(winner, ai_pid)
    s = total / n_games
    print(f"[benchmark] {leaf} AI scored {s:.3f} vs strategist {1-s:.3f}  ({time.time()-t0:.1f}s)")
    return s


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    w = dict(main.DEFAULT_WEIGHTS)
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        for k, v in data.items():
            if k in main.DEFAULT_WEIGHTS:
                w[k] = float(v)
    return w


def _save(weights: dict, path: str) -> None:
    ordered = {k: round(float(weights[k]), 4) for k in main.DEFAULT_WEIGHTS}
    with open(path, "w") as f:
        json.dump(ordered, f, indent=2)
    print(f"[io] wrote {path}")


# ─── Validation (real MCTS) ───────────────────────────────────────────────────

def validate(weights: dict, n_games: int, mcts_iters: int, seed: int = 7,
             baseline: dict | None = None, baseline_label: str = "default") -> float:
    """Play learned weights vs a baseline using real MCTS and report the learned
    side's score. Baseline defaults to the original hand-tuned weights; pass the
    currently-deployed weights to prove an *incremental* gain over what's live.
    Returns the learned side's score."""
    base = baseline if baseline is not None else dict(main.DEFAULT_WEIGHTS)
    print(f"[validate] {n_games} MCTS games ({mcts_iters} iters/move), learned vs {baseline_label}...")
    t0 = time.time()
    s = match(weights, base, n_games, policy="mcts", mcts_iters=mcts_iters, base_seed=seed)
    print(f"[validate] learned scored {s:.3f} vs {baseline_label} {1-s:.3f}  "
          f"({'better' if s > 0.5 else 'not better'})  ({time.time()-t0:.1f}s)")
    return s


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main_cli() -> None:
    ap = argparse.ArgumentParser(description="Self-play trainer for the Spender AI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("evolve", help="Phase 1: evolve card-scoring weights")
    pe.add_argument("--generations", type=int, default=15)
    pe.add_argument("--pop", type=int, default=10)
    pe.add_argument("--games-per-pair", type=int, default=10)
    pe.add_argument("--sigma", type=float, default=0.15)
    pe.add_argument("--in", dest="infile", default=WEIGHTS_OUT)
    pe.add_argument("--out", default=WEIGHTS_OUT)

    pt = sub.add_parser("td", help="Phase 2: TD-learn position-eval weights")
    pt.add_argument("--games", type=int, default=2000)
    pt.add_argument("--alpha", type=float, default=0.05)
    pt.add_argument("--in", dest="infile", default=WEIGHTS_OUT)
    pt.add_argument("--out", default=WEIGHTS_OUT)

    pa = sub.add_parser("all", help="Run Phase 1 then Phase 2")
    pa.add_argument("--generations", type=int, default=15)
    pa.add_argument("--pop", type=int, default=10)
    pa.add_argument("--games-per-pair", type=int, default=10)
    pa.add_argument("--td-games", type=int, default=2000)
    pa.add_argument("--alpha", type=float, default=0.05)
    pa.add_argument("--in", dest="infile", default=None,
                    help="seed evolution from these weights (default: fresh from DEFAULT_WEIGHTS)")
    pa.add_argument("--out", default=WEIGHTS_OUT)
    pa.add_argument("--validate-games", type=int, default=0)
    pa.add_argument("--mcts-iters", type=int, default=150)
    pa.add_argument("--baseline", default=None,
                    help="validate against these weights instead of the original defaults")

    pv = sub.add_parser("validate", help="Play learned vs a baseline with real MCTS")
    pv.add_argument("--games", type=int, default=40)
    pv.add_argument("--mcts-iters", type=int, default=150)
    pv.add_argument("--in", dest="infile", default=WEIGHTS_OUT)
    pv.add_argument("--baseline", default=None,
                    help="opponent weights (default: original DEFAULT_WEIGHTS)")

    pval = sub.add_parser("value", help="Stage 1: train the learned value model (NNUE-style)")
    pval.add_argument("--games", type=int, default=3000)
    pval.add_argument("--epsilon", type=float, default=0.08, help="exploration rate")
    pval.add_argument("--epochs", type=int, default=12)
    pval.add_argument("--lr", type=float, default=0.05)
    pval.add_argument("--l2", type=float, default=1e-3, help="L2 weight decay")
    pval.add_argument("--hidden", type=int, default=0,
                      help="hidden units for an MLP value model (0 = linear logistic)")
    pval.add_argument("--weights", default=WEIGHTS_OUT, help="card weights for the self-play policy")
    pval.add_argument("--out", default=VALUE_MODEL_OUT)
    pval.add_argument("--validate-games", type=int, default=0)
    pval.add_argument("--mcts-iters", type=int, default=200)
    pval.add_argument("--time", type=float, default=0.0,
                      help="A/B with this wall-clock budget (s/move) instead of fixed iters")

    pvv = sub.add_parser("validate-value", help="A/B test value-leaf vs rollout-leaf MCTS")
    pvv.add_argument("--games", type=int, default=40)
    pvv.add_argument("--mcts-iters", type=int, default=200)
    pvv.add_argument("--time", type=float, default=0.0,
                     help="wall-clock budget (s/move) instead of fixed iters")
    pvv.add_argument("--weights", default=WEIGHTS_OUT)

    ptr = sub.add_parser("tournament", help="Real-MCTS round-robin among A/B/C (+ extra files)")
    ptr.add_argument("--games-per-pair", type=int, default=30)
    ptr.add_argument("--mcts-iters", type=int, default=120)
    ptr.add_argument("--configs", nargs="*", default=[],
                     help="extra configs as name=path/to/weights.json")

    pco = sub.add_parser("coevolve", help="Evolve policy+tactical weights under real-MCTS self-play")
    pco.add_argument("--generations", type=int, default=8)
    pco.add_argument("--pop", type=int, default=8)
    pco.add_argument("--games-per-pair", type=int, default=6)
    pco.add_argument("--mcts-iters", type=int, default=100)
    pco.add_argument("--sigma", type=float, default=0.15)
    pco.add_argument("--start", default=None, help="seed config file (default: variant C)")
    pco.add_argument("--out", default=None, help="write the best config to this file")
    pco.add_argument("--validate-games", type=int, default=0,
                     help="after evolving, validate the best vs deployed weights with MCTS")

    pb = sub.add_parser("benchmark", help="Play the AI vs the scripted strategist")
    pb.add_argument("--games", type=int, default=40)
    pb.add_argument("--mcts-iters", type=int, default=150)
    pb.add_argument("--time", type=float, default=0.0,
                    help="wall-clock budget (s/move) instead of fixed iters")
    pb.add_argument("--weights", default=WEIGHTS_OUT)
    pb.add_argument("--value", action="store_true", help="use the learned value-leaf MCTS")

    args = ap.parse_args()

    if args.cmd == "evolve":
        start = _load(args.infile)
        best = evolve(args.generations, args.pop, args.games_per_pair,
                      sigma=args.sigma, start=start)
        merged = _load(args.infile)
        merged.update({k: best[k] for k in CARD_KEYS})
        _save(merged, args.out)

    elif args.cmd == "td":
        cw = _load(args.infile)
        theta = td_learn(cw, args.games, alpha=args.alpha,
                         theta0=[cw[k] for k in POS_KEYS])
        cw.update({k: v for k, v in zip(POS_KEYS, theta)})
        _save(cw, args.out)

    elif args.cmd == "all":
        start = _load(args.infile) if args.infile else None
        best = evolve(args.generations, args.pop, args.games_per_pair, start=start)
        merged = dict(start) if start else dict(main.DEFAULT_WEIGHTS)
        merged.update({k: best[k] for k in CARD_KEYS})
        theta = td_learn(merged, args.td_games, alpha=args.alpha,
                         theta0=[merged[k] for k in POS_KEYS])
        merged.update({k: v for k, v in zip(POS_KEYS, theta)})
        _save(merged, args.out)
        if args.validate_games:
            baseline = _load(args.baseline) if args.baseline else None
            label = args.baseline if args.baseline else "default"
            validate(merged, args.validate_games, args.mcts_iters,
                     baseline=baseline, baseline_label=label)

    elif args.cmd == "validate":
        baseline = _load(args.baseline) if args.baseline else None
        label = args.baseline if args.baseline else "default"
        validate(_load(args.infile), args.games, args.mcts_iters,
                 baseline=baseline, baseline_label=label)

    elif args.cmd == "tournament":
        main.load_weights()
        configs = {name: dict(main.WEIGHT_VARIANTS[name]) for name in ("A", "B", "C")}
        for spec in args.configs:
            name, path = spec.split("=", 1)
            configs[name] = _load(path)
        tournament(configs, args.games_per_pair, args.mcts_iters)

    elif args.cmd == "coevolve":
        main.load_weights()
        start = _load(args.start) if args.start else dict(main.WEIGHT_VARIANTS["C"])
        a_off = dict(main.WEIGHT_VARIANTS["A"])
        best = coevolve(args.generations, args.pop, args.games_per_pair, args.mcts_iters,
                        start=start, sigma=args.sigma, also_seed=a_off)
        if args.out:
            _save(best, args.out)
        if args.validate_games:
            validate(best, args.validate_games, args.mcts_iters,
                     baseline=dict(main.WEIGHT_VARIANTS["A"]), baseline_label="deployed-A")

    elif args.cmd == "value":
        cw = _load(args.weights)
        if args.hidden > 0:
            model = train_value_mlp(cw, args.games, hidden=args.hidden,
                                    epsilon=args.epsilon, epochs=args.epochs,
                                    lr=args.lr, l2=args.l2)
        else:
            model = train_value_model(cw, args.games, epsilon=args.epsilon,
                                      epochs=args.epochs, lr=args.lr, l2=args.l2)
        _save_value(model, args.out)
        if args.validate_games:
            main.load_value_model(args.out)
            validate_value(cw, args.validate_games, args.mcts_iters,
                           mcts_time=(args.time or None))

    elif args.cmd == "validate-value":
        main.load_value_model()
        validate_value(_load(args.weights), args.games, args.mcts_iters,
                       mcts_time=(args.time or None))

    elif args.cmd == "benchmark":
        if args.value:
            main.load_value_model()
        benchmark_vs_strategist(_load(args.weights), args.games,
                                mcts_iters=args.mcts_iters,
                                mcts_time=(args.time or None), use_value=args.value)


if __name__ == "__main__":
    main_cli()
