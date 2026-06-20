"""Panel A/B for variant "S" (vsearch = V(state) + determinized PUCT) vs the style-diverse panel.

Protagonist = vsearch. Opponents = {H3, H2, H2N, H2R} (engine / balanced / noble-rush / point-rush),
reusing h3_vs_h2's OPPONENTS. The decisive matchup is vs greedy H3 (search must beat its own base).
Reports per-opponent win rate + Wilson CI + the panel AVERAGE (the chosen tuning objective).

CRN: per-game deck seed = base + i, seats swapped (i % 2); each opponent gets a disjoint seed base
(--step >> N). Parallel across processes; opponents + overrides are passed by value (modules aren't
picklable), applied inside each worker. The FINAL ship number must come from a DISJOINT seed range
(pass a fresh --seed0) — tuning-set optimism is real.

Usage:
    python -m games.spender.ai.az.vsearch_camp --n 200 --workers 12 --sims 200 --opps H3,H2,H2N,H2R
    python -m games.spender.ai.az.vsearch_camp --n 120 --sims 160 --set W_PROGRESS=2.0 SCALE=7
"""
from __future__ import annotations

import argparse
import math
import multiprocessing as mp
import random
import time

from . import engine as E
from . import heuristic3 as H3
from . import v_state
from . import vsearch
from . import valuation3 as V3
from .h3_vs_h2 import OPPONENTS, wilson_ci

OPP = {**OPPONENTS, "H3": H3}   # fast-engine panel: {H, H2, H2N, H2R} + greedy H3


def _apply_overrides(overrides: dict):
    """Route KEY=VAL overrides to vsearch / v_state / heuristic3 / valuation3 (first that defines it)."""
    for k, v in overrides.items():
        for mod in (vsearch, v_state, H3, V3):
            if hasattr(mod, k):
                setattr(mod, k, v)
                break
        else:
            raise SystemExit(f"unknown override key '{k}'")


def play_one(opp, prot_seat: int, *, seed: int, sims: int, max_plies: int = 400,
             win_points: int = 15) -> float:
    """One vsearch-vs-opp game on deck `seed`; returns vsearch's score in {0, 0.5, 1}."""
    s = E.new_game(random.Random(seed), win_points=win_points)
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        if s.turn == prot_seat:
            a = vsearch.choose_action(s, s.turn, sims=sims)
        else:
            a = opp.choose_action(s, s.turn)
        E.apply(s, a)
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == prot_seat else 0.0


def _chunk(args):
    opp_name, seed_base, lo, hi, sims, overrides, win_points = args
    if overrides:
        _apply_overrides(overrides)
    opp = OPP[opp_name]
    return sum(play_one(opp, i % 2, seed=seed_base + i, sims=sims, win_points=win_points)
               for i in range(lo, hi))


def run(opp_name, n, seed_base, sims, overrides, pool, workers, win_points=15):
    t0 = time.time()
    if pool is None:
        if overrides:
            _apply_overrides(overrides)
        total = sum(play_one(OPP[opp_name], i % 2, seed=seed_base + i, sims=sims, win_points=win_points)
                    for i in range(n))
    else:
        step = math.ceil(n / workers)
        tasks = [(opp_name, seed_base, lo, min(lo + step, n), sims, overrides, win_points)
                 for lo in range(0, n, step)]
        total = sum(pool.map(_chunk, tasks))
    wr = total / n
    lo, hi = wilson_ci(wr, n)
    print(f"  S vs {opp_name:<4}: {wr:.4f}   (95% CI {lo:.3f}-{hi:.3f})   N={n}  [{time.time()-t0:.0f}s]",
          flush=True)
    return wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--sims", type=int, default=vsearch.SIMS)
    ap.add_argument("--opps", default="H3,H2,H2N,H2R")
    ap.add_argument("--seed0", type=int, default=30_000_000)
    ap.add_argument("--step", type=int, default=1_000_000)
    ap.add_argument("--set", nargs="+", default=None, dest="overrides",
                    help="vsearch/v_state/H3/valuation3 overrides, e.g. W_PROGRESS=2.0 SCALE=7 SIMS=300")
    ap.add_argument("--win-points", type=int, default=15, help="play games to this many points (15 or 21)")
    args = ap.parse_args()

    overrides = {}
    if args.overrides:
        for tok in args.overrides:
            k, v = tok.split("=")
            try:
                f = float(v)
                overrides[k] = int(f) if f.is_integer() and "." not in v else f
            except ValueError:
                overrides[k] = v
    if overrides:
        _apply_overrides(overrides)

    opps = args.opps.split(",")
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    print(f"[vsearch-camp] sims={args.sims}  N={args.n}/opp  opps={opps}  workers={workers}  "
          f"overrides={overrides or '{}'}", flush=True)
    try:
        wrs = {}
        for i, nm in enumerate(opps):
            wrs[nm] = run(nm, args.n, args.seed0 + i * args.step, args.sims, overrides, pool, workers,
                          args.win_points)
        avg = sum(wrs.values()) / len(wrs)
        print(f"[vsearch-camp] panel avg = {avg:.4f}   "
              + "  ".join(f"{k} {v:.3f}" for k, v in wrs.items()), flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
