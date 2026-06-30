"""Phase-0 probe: does the existing shallow searcher (H3L = h3_lookahead) beat the panel?

The plan's #1 open risk is "is pure-Python search strong enough (and fast enough) to beat greedy
H3?" h3_lookahead.py already implements a determinized shallow search on top of H3's eval, so we
can answer that for ~free BEFORE building the richer V(state)+PUCT variant.

Protagonist = h3_lookahead (H3L). Opponents = the style-diverse panel {H3, H2, H2N, H2R} (engine /
balanced / noble-rush / point-rush), reusing h3_vs_h2's OPPONENTS. The decisive test is H3L vs the
GREEDY H3 it is built on: search must add value over the base. Reports per-opponent win rate +
Wilson CI + the panel average (the user's chosen tuning objective).

CRN: per-game deck seed = base + i, seats swapped (i % 2); each opponent gets a disjoint seed base
(spaced by --step >> N). Parallel across processes, passing opponent NAMES (modules aren't
picklable) exactly like h3_autotune.

Usage:
    python -m games.spender.ai.az.h3l_probe --n 80 --workers 10 --mode rollout
    python -m games.spender.ai.az.h3l_probe --n 200 --workers 10 --mode static --opps H3,H2,H2N,H2R
"""
from __future__ import annotations

import argparse
import math
import multiprocessing as mp
import time

from . import engine as E
from . import h3_lookahead as H3L
from . import heuristic3 as H3
from .h3_vs_h2 import OPPONENTS, wilson_ci

# Panel: greedy H3 (the base H3L must beat) + the H2 family. Reuse h3_vs_h2's instances.
OPP = {**OPPONENTS, "H3": H3}   # OPPONENTS = {H, H2, H2N, H2R}; add greedy H3


def play_one(opp, prot_seat: int, *, seed: int, max_plies: int = 400) -> float:
    """One H3L-vs-opp game on deck `seed`; returns H3L's score in {0, 0.5, 1}."""
    import random
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        if s.turn == prot_seat:
            a = H3L.choose_action(s, s.turn)
        else:
            a = opp.choose_action(s, s.turn)
        E.apply(s, a)
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == prot_seat else 0.0


def _chunk(args):
    """Play games [lo, hi) of opponent `opp_name` on seed base `seed_base`. Picklable worker."""
    opp_name, seed_base, lo, hi, use_rollout = args
    H3L.USE_ROLLOUT = use_rollout
    opp = OPP[opp_name]
    return sum(play_one(opp, i % 2, seed=seed_base + i) for i in range(lo, hi))


def run(opp_name: str, n: int, seed_base: int, pool, workers: int, use_rollout: bool) -> float:
    t0 = time.time()
    if pool is None:
        total = sum(play_one(OPP[opp_name], i % 2, seed=seed_base + i) for i in range(n))
    else:
        step = math.ceil(n / workers)
        tasks = [(opp_name, seed_base, lo, min(lo + step, n), use_rollout)
                 for lo in range(0, n, step)]
        total = sum(pool.map(_chunk, tasks))
    wr = total / n
    lo, hi = wilson_ci(wr, n)
    print(f"  H3L vs {opp_name:<4}: {wr:.4f}   (95% CI {lo:.3f}-{hi:.3f})   N={n}  "
          f"[{time.time()-t0:.0f}s]", flush=True)
    return wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--opps", default="H3,H2,H2N,H2R")
    ap.add_argument("--mode", default="rollout", choices=["rollout", "static"],
                    help="H3L leaf: full greedy-H3 rollout (default) or the static position_value")
    ap.add_argument("--seed0", type=int, default=90_000_000)
    ap.add_argument("--step", type=int, default=1_000_000)   # >> n so per-opp seed ranges are disjoint
    args = ap.parse_args()

    use_rollout = args.mode == "rollout"
    H3L.USE_ROLLOUT = use_rollout
    opps = args.opps.split(",")

    workers = max(1, args.workers)
    pool = mp.Pool(processes=workers) if workers > 1 else None
    print(f"[h3l-probe] mode={args.mode}  N={args.n}/opp  opps={opps}  workers={workers}  "
          f"CAND_CAP={H3L.CAND_CAP}", flush=True)
    try:
        wrs = {}
        for i, nm in enumerate(opps):
            wrs[nm] = run(nm, args.n, args.seed0 + i * args.step, pool, workers, use_rollout)
        avg = sum(wrs.values()) / len(wrs)
        print(f"[h3l-probe] panel avg = {avg:.4f}   "
              + "  ".join(f"{k} {v:.3f}" for k, v in wrs.items()), flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
