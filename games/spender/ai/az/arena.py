"""Arena: AZ agent vs the incumbent heuristic-MCTS variants.

The whole game runs in the fast engine. On the heuristic's turn the state is
converted to the incumbent dict format and main's MCTS picks a move, which is
mapped back to an action index. Heuristic discard/noble sub-decisions replicate
the incumbent's own helpers (_ai_discard_one / _ai_pick_noble) so it plays
exactly as it would on the server.

Usage:
    python -m games.spender.ai.az.arena --az <checkpoints/az_model.npz> \
        --opp B --games 200 --az-sims 300 --opp-iters 120
Opp choices: A, B, C, or a path to a weights json (e.g. weights.c2_candidate.json).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time

from games.spender import main as inc  # incumbent

from . import actions as A
from . import engine as E
from .mcts import Search

PIDS = ("az", "heu")


def wilson_ci(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    den = 1 + z * z / n
    center = (score + z * z / (2 * n)) / den
    half = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / den
    return center - half, center + half


def _heuristic_action(s: E.State, weights: dict, opp_iters: int) -> int:
    seat = s.turn
    game = E.to_game_dict(s, PIDS)
    pid = PIDS[seat]
    if s.phase == E.DISCARD:
        before = dict(game["players"][pid]["tokens"])
        inc._ai_discard_one(game, pid)
        after = game["players"][pid]["tokens"]
        color = next(c for c in A.COLOR_NAMES if after.get(c, 0) < before.get(c, 0))
        return A.move_to_action(s, {"type": "discard", "color": color})
    if s.phase == E.NOBLE:
        claimable = [dict(inc.ALL_NOBLES[s.nobles[slot]]) for slot in s.pending_nobles]
        noble = inc._ai_pick_noble(claimable, game, pid)
        return A.move_to_action(s, {"type": "pick_noble", "noble_id": noble["id"]})
    mv = inc._mcts_choose_move(game, pid, time_limit=1e9, max_iters=opp_iters,
                               weights=weights)
    return A.move_to_action(s, mv)


def play_game(evaluate, az_seat: int, weights: dict, *, az_sims: int,
              opp_iters: int, rng: random.Random, max_plies: int = 400) -> float:
    """Returns AZ's score in {0, 0.5, 1}."""
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
            E.apply(s, _heuristic_action(s, weights, opp_iters))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == az_seat else 0.0


def run_match(evaluate, weights: dict, n_games: int, *, az_sims: int,
              opp_iters: int, seed: int = 0, label: str = "") -> float:
    rng = random.Random(seed)
    total = 0.0
    t0 = time.time()
    for i in range(n_games):
        total += play_game(evaluate, i % 2, weights, az_sims=az_sims,
                           opp_iters=opp_iters, rng=rng)
        if (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{n_games}: az {total/(i+1):.3f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    score = total / n_games
    lo, hi = wilson_ci(score, n_games)
    print(f"[arena] AZ vs {label}: {score:.3f} over {n_games} games "
          f"(95% CI {lo:.3f}-{hi:.3f}, {time.time()-t0:.0f}s)", flush=True)
    return score


def _load_opp_weights(spec: str) -> dict:
    inc.load_weights()
    if spec in inc.WEIGHT_VARIANTS:
        return dict(inc.WEIGHT_VARIANTS[spec])
    with open(spec) as f:
        return {**inc.DEFAULT_WEIGHTS, **json.load(f)}


def _load_evaluator(path: str, device: str):
    if path.endswith(".npz"):
        from .infer_np import load_evaluator
        return load_evaluator(path)
    import torch
    from .net import SpenderNet, make_evaluator
    ck = torch.load(path, map_location="cpu", weights_only=False)
    net = SpenderNet()
    net.load_state_dict(ck["best"] if "best" in ck else ck)
    return make_evaluator(net, device)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--az", required=True, help=".npz or .pt checkpoint")
    ap.add_argument("--opp", default="B", help="A|B|C or weights-json path")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--az-sims", type=int, default=300)
    ap.add_argument("--opp-iters", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    inc.USE_VALUE_LEAF = False  # heuristic plays rollout MCTS (our eval standard)
    evaluate = _load_evaluator(args.az, args.device)
    weights = _load_opp_weights(args.opp)
    run_match(evaluate, weights, args.games, az_sims=args.az_sims,
              opp_iters=args.opp_iters, seed=args.seed, label=args.opp)


if __name__ == "__main__":
    main()
