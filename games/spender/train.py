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
    python -m games.spender.train all       --out games/spender/weights.json
    python -m games.spender.train evolve     --generations 15 --pop 10
    python -m games.spender.train td         --games 2000
    python -m games.spender.train validate   --games 40        # MCTS, learned vs default
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import time

from games.spender import main

# ─── Weight groups ────────────────────────────────────────────────────────────

# Tuned by Phase 1 (how the policy picks moves).
CARD_KEYS = [
    "point_urgency_mult", "bonus_l1", "bonus_l2", "bonus_l3", "bonus_reserved",
    "bonus_urgency_decay", "noble_card", "access_base", "access_urgency",
    "rollout_reserve_threshold",
]

# Tuned by Phase 2 (how the policy evaluates truncated positions). Order MUST
# match _player_features() below.
POS_KEYS = ["pos_points", "pos_buyable", "pos_noble", "pos_bonus_count"]

# (min, max) clamps applied after every mutation so the search stays in a sane,
# meaningful region (non-negative utilities; decay kept a true 0..1 fraction).
CARD_BOUNDS = {
    "point_urgency_mult": (0.0, 10.0),
    "bonus_l1": (0.0, 2.0),
    "bonus_l2": (0.0, 2.0),
    "bonus_l3": (0.0, 2.0),
    "bonus_reserved": (0.0, 2.0),
    "bonus_urgency_decay": (0.0, 1.0),
    "noble_card": (0.0, 3.0),
    "access_base": (0.01, 2.0),
    "access_urgency": (0.0, 2.0),
    "rollout_reserve_threshold": (0.0, 15.0),
}

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
              mcts_iters: int = 150, max_plies: int = 250) -> tuple[str | list, dict]:
    """Play one headless game. ``weights_p1``/``weights_p2`` are full weight dicts;
    the global WEIGHTS is swapped to the mover's weights before each decision so
    each side reasons through its own heuristic. Returns (winner, final_game)."""
    g = _new_game()
    by_pid = {"p1": weights_p1, "p2": weights_p2}
    plies = 0
    while g["phase"] == "playing" and plies < max_plies:
        pid = g["turn"]
        main.WEIGHTS = by_pid[pid]
        if policy == "mcts":
            mv = main._mcts_choose_move(g, pid, time_limit=1e9, max_iters=mcts_iters)
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
    return [float(pts), float(buyable), float(noble_prox), float(bonus_count)]


def _global_features(game: dict) -> list[float]:
    """p1-minus-p2 feature differential — a perspective-independent state vector."""
    fa = _player_features(game, "p1")
    fb = _player_features(game, "p2")
    return [a - b for a, b in zip(fa, fb)]


# Rough magnitudes of each raw feature, used to scale them to ~O(1) so a single
# fixed learning rate behaves well across features. Learning happens in scaled
# space; weights are converted back to raw units before being returned.
FEATURE_SCALE = [15.0, 10.0, 3.0, 8.0]   # points, buyable, noble_prox, bonus_count


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

def validate(weights: dict, n_games: int, mcts_iters: int, seed: int = 7) -> None:
    """Play learned weights vs the original defaults using real MCTS and report
    the learned side's score. This is the honest 'did it actually get better?'."""
    default = dict(main.DEFAULT_WEIGHTS)
    print(f"[validate] {n_games} MCTS games ({mcts_iters} iters/move), learned vs default...")
    t0 = time.time()
    s = match(weights, default, n_games, policy="mcts", mcts_iters=mcts_iters, base_seed=seed)
    print(f"[validate] learned scored {s:.3f} vs default {1-s:.3f}  "
          f"({'better' if s > 0.5 else 'not better'})  ({time.time()-t0:.1f}s)")


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
    pa.add_argument("--out", default=WEIGHTS_OUT)
    pa.add_argument("--validate-games", type=int, default=0)
    pa.add_argument("--mcts-iters", type=int, default=150)

    pv = sub.add_parser("validate", help="Play learned vs default with real MCTS")
    pv.add_argument("--games", type=int, default=40)
    pv.add_argument("--mcts-iters", type=int, default=150)
    pv.add_argument("--in", dest="infile", default=WEIGHTS_OUT)

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
        best = evolve(args.generations, args.pop, args.games_per_pair)
        merged = dict(main.DEFAULT_WEIGHTS)
        merged.update({k: best[k] for k in CARD_KEYS})
        theta = td_learn(merged, args.td_games, alpha=args.alpha,
                         theta0=[merged[k] for k in POS_KEYS])
        merged.update({k: v for k, v in zip(POS_KEYS, theta)})
        _save(merged, args.out)
        if args.validate_games:
            validate(merged, args.validate_games, args.mcts_iters)

    elif args.cmd == "validate":
        validate(_load(args.infile), args.games, args.mcts_iters)


if __name__ == "__main__":
    main_cli()
