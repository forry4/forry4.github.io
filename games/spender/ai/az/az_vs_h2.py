"""Arena: the AZ net (variant Z) vs the greedy H2 heuristic, both in the fast engine.

arena.py only drives the dict-MCTS heuristics (A/B/C2). This plays the AZ net's PUCT
search on one seat and `heuristic2.choose_action` on the other -- both return an action
index applied with `engine.apply`, so no dict conversion is needed.

Usage:
    python -m games.spender.ai.az.az_vs_h2 --games 100 --az-sims 300
    python -m games.spender.ai.az.az_vs_h2 --games 100 --az-sims 300 --set W_TEMPO=0.4 W_GEM=0.3
"""
from __future__ import annotations

import argparse
import math
import random
import time

from . import engine as E
from . import heuristic2 as H2
from .mcts import Search


def wilson_ci(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    den = 1 + z * z / n
    center = (score + z * z / (2 * n)) / den
    half = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / den
    return center - half, center + half


def _load_evaluator(path: str, device: str = "cpu"):
    if path.endswith(".npz"):
        from .infer_np import load_evaluator
        return load_evaluator(path)
    import torch
    from .net import SpenderNet, make_evaluator
    ck = torch.load(path, map_location="cpu", weights_only=False)
    net = SpenderNet()
    net.load_state_dict(ck["best"] if "best" in ck else ck)
    return make_evaluator(net, device)


def play_game(evaluate, az_seat: int, *, az_sims: int, rng: random.Random,
              max_plies: int = 400) -> float:
    """One AZ-vs-H2 game; returns AZ's score in {0, 0.5, 1}. H2 plays the other seat."""
    s = E.new_game(rng)
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        if s.turn == az_seat:
            legal = E.legal_actions(s)
            if len(legal) == 1:
                E.apply(s, legal[0])
                continue
            search = Search(s, rng, add_noise=False)
            visits = search.run(evaluate, az_sims)
            E.apply(s, max(range(len(visits)), key=visits.__getitem__))
        else:
            E.apply(s, H2.choose_action(s, s.turn))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == az_seat else 0.0


def run_match(evaluate, n_games: int, *, az_sims: int, seed: int = 0) -> float:
    rng = random.Random(seed)
    total = 0.0
    t0 = time.time()
    for i in range(n_games):
        total += play_game(evaluate, i % 2, az_sims=az_sims, rng=rng)
        if (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{n_games}: az {total/(i+1):.3f}  h2 {1-total/(i+1):.3f}  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    az = total / n_games
    lo, hi = wilson_ci(az, n_games)
    print(f"[az-vs-h2] AZ {az:.3f}  |  H2 {1-az:.3f}   N={n_games}  "
          f"(AZ 95% CI {lo:.3f}-{hi:.3f})  az_sims={az_sims}", flush=True)
    return az


def _parse_kv(tok):
    k, v = tok.split("=")
    f = float(v)
    return k, (int(f) if f.is_integer() and "." not in v else f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--az", default="games/spender/ai/az_model.npz", help=".npz or .pt net")
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--az-sims", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--set", nargs="+", default=None, dest="overrides",
                    help="H2 weight overrides, e.g. W_TEMPO=0.4 W_GEM=0.3")
    args = ap.parse_args()

    if args.overrides:
        for k, v in (_parse_kv(t) for t in args.overrides):
            setattr(H2, k, v)
        print("[az-vs-h2] H2 overrides: " +
              ", ".join(f"{k}={getattr(H2, k)}" for k, _ in (_parse_kv(t) for t in args.overrides)))

    evaluate = _load_evaluator(args.az, args.device)
    run_match(evaluate, args.games, az_sims=args.az_sims, seed=args.seed)


if __name__ == "__main__":
    main()
