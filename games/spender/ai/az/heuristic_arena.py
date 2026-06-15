"""Step-3 validation gate: v4 heuristic (engine-native) vs incumbent A/B/C2.

If the v4 valuation model is sound, a greedy bot built on it should match or beat
C2. Both sides run in the fast engine; the incumbent side converts to the dict
format and uses main's MCTS (reusing arena._heuristic_action), exactly as it
plays on the server. Seats are swapped each game to remove first-move bias.

Usage:
    python -m games.spender.ai.az.heuristic_arena --opp C2 --games 100 --opp-iters 120
"""
from __future__ import annotations

import argparse
import random
import time

from games.spender import main as inc

from . import engine as E
from . import heuristic as H
from .arena import _heuristic_action, _load_opp_weights, wilson_ci


def play_game(weights: dict, v4_seat: int, *, opp_iters: int,
              rng: random.Random, max_plies: int = 400) -> float:
    """Returns the v4 heuristic's score in {0, 0.5, 1}."""
    s = E.new_game(rng)
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        if s.turn == v4_seat:
            E.apply(s, H.choose_action(s, s.turn))
        else:
            E.apply(s, _heuristic_action(s, weights, opp_iters))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == v4_seat else 0.0


def run_match(weights: dict, n_games: int, *, opp_iters: int, seed: int = 0,
              label: str = "") -> float:
    rng = random.Random(seed)
    total = 0.0
    t0 = time.time()
    for i in range(n_games):
        r = play_game(weights, i % 2, opp_iters=opp_iters, rng=rng)
        total += r
        res = {1.0: "WIN ", 0.5: "draw", 0.0: "loss"}[r]
        print(f"  game {i+1:>3}/{n_games}: {res} (v4 seat {i % 2}) | "
              f"running v4 {total/(i+1):.3f} ({time.time()-t0:.0f}s)", flush=True)
    score = total / n_games
    lo, hi = wilson_ci(score, n_games)
    print(f"[arena] v4-heuristic vs {label}: {score:.3f} over {n_games} games "
          f"(95% CI {lo:.3f}-{hi:.3f}, {time.time()-t0:.0f}s)", flush=True)
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="C2", help="A|B|C|C2 or weights-json path")
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--opp-iters", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inc.USE_VALUE_LEAF = False  # incumbent plays rollout MCTS (our eval standard)
    weights = _load_opp_weights(args.opp)
    run_match(weights, args.games, opp_iters=args.opp_iters, seed=args.seed,
              label=args.opp)


if __name__ == "__main__":
    main()
