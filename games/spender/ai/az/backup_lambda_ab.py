"""Focused self-gate A/B for the mixmax backup knob `vsearch.BACKUP_LAMBDA`.

The documented #1 lever is SEARCH AGGREGATION, not eval quality (six net-path negatives proved a
sharper leaf doesn't convert). This isolates ONE aggregation change: blend each edge's diluted mean Q
with the best reply one ply down (lam>0), i.e. "assume both sides find their best reply" instead of
averaging over every move the opponent tried. lam=0 == today's S (pure averaging).

Methodology (per CLAUDE.md, mirrors vsearch_selfgate):
  * candidate (lam=L) vs FROZEN today's-S (lam=0), PAIRED CRN (each board both first-player ways,
    vsearch._RNG reset per game) -> unbiased 0.5 when cand==frozen;
  * SCREEN on one seed base, then re-measure the leader on a DISJOINT fresh seed base (holdout-reuse
    optimism is real);
  * PANEL RPS guard: a config can beat THIS frozen-S via rock-paper-scissors yet be weaker vs the
    style-diverse panel {H3,H2,H2N,H2R}. Report cand vs frozen min-panel side by side.

Usage:
  python -m games.spender.ai.az.backup_lambda_ab --sims 160 --n 120 --workers 12 --lams 0.2,0.35,0.5
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import math
import multiprocessing as mp
import random
import time

from . import engine as E
from . import vsearch
from .vsearch_camp import OPP, play_one, _apply_overrides
from .h3_vs_h2 import wilson_ci

PANEL = ["H3", "H2", "H2N", "H2R"]


def _play(cand_lam: float, frozen_lam: float, cand_seat: int, seed: int, sims: int,
          max_plies: int = 400) -> float:
    """One candidate-vs-frozen game; cand_seat is the candidate's seat (seat 0 moves first)."""
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        vsearch.BACKUP_LAMBDA = cand_lam if s.turn == cand_seat else frozen_lam
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def _trial(cand_lam, frozen_lam, seed, sims):
    return (_play(cand_lam, frozen_lam, 0, seed, sims)
            + _play(cand_lam, frozen_lam, 1, seed, sims))


def _chunk(args):
    cand_lam, frozen_lam, seed_base, lo, hi, sims = args
    return sum(_trial(cand_lam, frozen_lam, seed_base + g, sims) for g in range(lo, hi))


def selfgate(cand_lam, frozen_lam, n, seed_base, sims, pool, workers):
    if pool is None:
        total = sum(_trial(cand_lam, frozen_lam, seed_base + g, sims) for g in range(n))
    else:
        step = math.ceil(n / workers)
        tasks = [(cand_lam, frozen_lam, seed_base, lo, min(lo + step, n), sims)
                 for lo in range(0, n, step)]
        total = sum(pool.map(_chunk, tasks))
    return total / (2 * n)


def _panel_chunk(args):
    nm, sb, lo, hi, sims, lam = args
    vsearch.BACKUP_LAMBDA = lam
    opp = OPP[nm]
    return sum(play_one(opp, i % 2, seed=sb + i, sims=sims) for i in range(lo, hi))


def panel(lam, n, seed0, step, sims, pool, workers):
    vsearch.BACKUP_LAMBDA = lam
    out = {}
    for i, nm in enumerate(PANEL):
        sb = seed0 + i * step
        if pool is None:
            tot = sum(play_one(OPP[nm], j % 2, seed=sb + j, sims=sims) for j in range(n))
        else:
            st = math.ceil(n / workers)
            tasks = [(nm, sb, lo, min(lo + st, n), sims, lam) for lo in range(0, n, st)]
            tot = sum(pool.map(_panel_chunk, tasks))
        out[nm] = tot / n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=160)
    ap.add_argument("--n", type=int, default=120)         # PAIRED trials => 2n games per measurement
    ap.add_argument("--panel-n", type=int, default=120)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--lams", default="0.2,0.35,0.5")
    ap.add_argument("--screen-seed", type=int, default=200_000)
    ap.add_argument("--hold-seed", type=int, default=3_000_000)
    ap.add_argument("--panel-seed", type=int, default=130_000_000)
    ap.add_argument("--step", type=int, default=100_000)
    args = ap.parse_args()

    lams = [float(x) for x in args.lams.split(",")]
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    t0 = time.time()
    print(f"[backup-lambda-ab] sims={args.sims} n={args.n} (={2*args.n} games) lams={lams} "
          f"workers={workers}", flush=True)
    try:
        # sanity: cand==frozen (lam=0 vs lam=0) must be ~0.5
        s00 = selfgate(0.0, 0.0, args.n, args.screen_seed, args.sims, pool, workers)
        print(f"[sanity] lam=0 vs frozen lam=0 = {s00:.4f}  (expect ~0.5)", flush=True)

        screened = []
        for L in lams:
            r = selfgate(L, 0.0, args.n, args.screen_seed, args.sims, pool, workers)
            lo, hi = wilson_ci(r, 2 * args.n)
            print(f"[screen] lam={L} vs frozen = {r:.4f}  (95% CI {lo:.3f}-{hi:.3f})  "
                  f"[{time.time()-t0:.0f}s]", flush=True)
            screened.append((r, L))
        screened.sort(reverse=True)
        best_r, best_L = screened[0]

        # fresh disjoint-seed re-measurement of the screen leader
        fresh = selfgate(best_L, 0.0, args.n, args.hold_seed, args.sims, pool, workers)
        flo, fhi = wilson_ci(fresh, 2 * args.n)
        print(f"[fresh]  lam={best_L} vs frozen (disjoint seeds) = {fresh:.4f}  "
              f"(95% CI {flo:.3f}-{fhi:.3f})", flush=True)

        # panel RPS guard
        cp = panel(best_L, args.panel_n, args.panel_seed, args.step, args.sims, pool, workers)
        fp = panel(0.0, args.panel_n, args.panel_seed, args.step, args.sims, pool, workers)
        cavg, favg = sum(cp.values()) / len(cp), sum(fp.values()) / len(fp)
        cmin, fmin = min(cp.values()), min(fp.values())
        print(f"[panel] cand lam={best_L}: avg {cavg:.4f} min {cmin:.3f}  {cp}", flush=True)
        print(f"[panel] frozen lam=0  : avg {favg:.4f} min {fmin:.3f}  {fp}", flush=True)
        verdict = ("SHIP" if (fresh > 0.52 and cmin >= fmin - 0.02) else
                   "REJECT (fresh<=0.52 or panel-min regressed)")
        print(f"[verdict] lam={best_L}: fresh {fresh:.4f}, panel-min delta {cmin-fmin:+.3f} -> {verdict}",
              flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
