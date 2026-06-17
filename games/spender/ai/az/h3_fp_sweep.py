"""Parallel A/B sweep: H3's damped FIXED-POINT engine vs the current 1-level H3.

Tests the deep-recursion idea (valuation3.ENG_FIXEDPOINT): solve engine_value as a damped fixed
point -- engine[A] = Sum_B convexity(A->B) * (PTS[B] + w*engine[B]) -- instead of the one-level
_eng_base truncation. The expectation (from the contraction condition POT_ENGINE_W*rho(M) < 1) is
that the best w here sits BELOW the 1-level peak of 0.5, since the fixed point amplifies more.

Method (the documented rigor): SCREEN every (w, iters) on CRN seeds vs BOTH H2 (head-to-head) and
H (the trustworthy external yardstick), pick the best FP config by vs-H (tie-break vs-H2), then
CONFIRM the winner against the current 1-level H3 baseline on a FRESH disjoint seed range. CRN is
for the comparison; the honest estimate is the fresh confirm. Seeds are spaced >> N so no two seed
sets share games (the seed-overlap bug).

Every match runs in a worker that applies its OWN full config (USE_POTENTIAL_ENGINE on +
ENG_FIXEDPOINT/ENG_FP_ITERS/POT_ENGINE_W all set explicitly each job), so a reused worker never
carries stale flags. Nothing is written to disk; module source is untouched.

Run:  python -m games.spender.ai.az.h3_fp_sweep
      python -m games.spender.ai.az.h3_fp_sweep --screen-n 800 --fresh-n 2000 --workers 10
"""
from __future__ import annotations

import argparse
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor

from . import heuristic as H1   # noqa: F401  (ensures the module graph loads in workers)
from . import heuristic2 as H2  # noqa: F401
from . import heuristic3 as H3  # noqa: F401
from . import valuation3 as V3  # noqa: F401
from .h3_vs_h2 import play_game, wilson_ci

OPP = {"H2": H2, "H": H1}

# FP grid: w should peak below the 1-level 0.5; iters>=2 to get any recursion (1 = points-only).
W_GRID = [0.1, 0.2, 0.3, 0.4, 0.5]
ITERS_GRID = [2, 3, 4, 6]


def _cfg(label, fixedpoint, iters, w):
    return {"label": label, "ENG_FIXEDPOINT": fixedpoint, "ENG_FP_ITERS": iters, "POT_ENGINE_W": w}


# baseline = current committed H3 (one-level, POT_ENGINE_W=0.5); FP candidates over the grid.
BASELINE = _cfg("cur-H3 (1-level w=0.5)", False, 4, 0.5)
CANDIDATES = [_cfg(f"FP i{it} w{w}", True, it, w) for it in ITERS_GRID for w in W_GRID]


def _apply(cfg):
    """Set ALL swept flags explicitly (no bleed between reused-worker jobs)."""
    V3.USE_POTENTIAL_ENGINE = True
    V3.ENG_FIXEDPOINT = cfg["ENG_FIXEDPOINT"]
    V3.ENG_FP_ITERS = cfg["ENG_FP_ITERS"]
    V3.POT_ENGINE_W = cfg["POT_ENGINE_W"]


def _chunk(job):
    """Worker: apply cfg, play games [lo, hi) (seat=i%2, deck seed=base+i), return summed score."""
    cfg, opp_name, base, lo, hi = job
    _apply(cfg)
    opp = OPP[opp_name]
    return sum(play_game(opp, i % 2, seed=base + i) for i in range(lo, hi))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen-n", type=int, default=600)
    ap.add_argument("--fresh-n", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--screen-seed-h2", type=int, default=2_000_000)
    ap.add_argument("--screen-seed-h", type=int, default=2_500_000)
    ap.add_argument("--fresh-seed-h2", type=int, default=3_000_000)
    ap.add_argument("--fresh-seed-h", type=int, default=3_500_000)
    ap.add_argument("--top", type=int, default=3, help="FP configs to carry into the fresh confirm")
    args = ap.parse_args()

    workers = max(1, args.workers)
    t0 = time.time()
    print(f"[fp-sweep] {len(CANDIDATES)} FP configs + baseline, {workers} workers. "
          f"screen N={args.screen_n} (vs H2 seed {args.screen_seed_h2}, vs H seed {args.screen_seed_h}); "
          f"fresh N={args.fresh_n}.", flush=True)

    def run(cfgs, n, seed_h2, seed_h):
        """Score each cfg vs H2 and vs H over n CRN games, all fanned across the pool."""
        step = math.ceil(n / workers)
        jobs, owner = [], []
        for ci, cfg in enumerate(cfgs):
            for opp, base in (("H2", seed_h2), ("H", seed_h)):
                for lo in range(0, n, step):
                    jobs.append((cfg, opp, base, lo, min(lo + step, n)))
                    owner.append((ci, opp))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            res = list(pool.map(_chunk, jobs))
        agg = {}
        for (ci, opp), sc in zip(owner, res):
            agg[(ci, opp)] = agg.get((ci, opp), 0.0) + sc
        return [{"cfg": cfgs[ci], "H2": agg[(ci, "H2")] / n, "H": agg[(ci, "H")] / n}
                for ci in range(len(cfgs))]

    # ---- screen: baseline + all FP candidates on the same CRN boards ----
    screen = run([BASELINE] + CANDIDATES, args.screen_n, args.screen_seed_h2, args.screen_seed_h)
    base_row = screen[0]
    # rank by the SENSITIVE metric (vs-H2 head-to-head); vs-H is saturated/flat so it can't
    # discriminate -- it serves only as the no-regression guard in the fresh confirm.
    cand_rows = sorted(screen[1:], key=lambda r: (r["H2"], r["H"]), reverse=True)
    print(f"\n[fp-sweep] SCREEN (N={args.screen_n})  baseline {base_row['cfg']['label']}: "
          f"vs H2 {base_row['H2']:.4f}  vs H {base_row['H']:.4f}", flush=True)
    print("[fp-sweep] FP candidates, best vs-H first:", flush=True)
    for r in cand_rows:
        print(f"    {r['cfg']['label']:>14}:  vs H2 {r['H2']:.4f}  vs H {r['H']:.4f}"
              f"   (dH {r['H']-base_row['H']:+.4f}, dH2 {r['H2']-base_row['H2']:+.4f})", flush=True)

    # ---- fresh confirm: baseline + top FP candidates on a DISJOINT seed range ----
    top = [r["cfg"] for r in cand_rows[:args.top]]
    confirm = run([BASELINE] + top, args.fresh_n, args.fresh_seed_h2, args.fresh_seed_h)
    b = confirm[0]
    print(f"\n[fp-sweep] FRESH CONFIRM (N={args.fresh_n}, disjoint seeds)  "
          f"({time.time()-t0:.0f}s elapsed)", flush=True)
    for row in confirm:
        lo_h, hi_h = wilson_ci(row["H"], args.fresh_n)
        tag = "  <- baseline" if row is b else (f"   (dH {row['H']-b['H']:+.4f}, dH2 {row['H2']-b['H2']:+.4f})")
        print(f"    {row['cfg']['label']:>22}:  vs H2 {row['H2']:.4f}  vs H {row['H']:.4f} "
              f"[{lo_h:.3f}-{hi_h:.3f}]{tag}", flush=True)
    print(f"\n[fp-sweep] done ({time.time()-t0:.0f}s).", flush=True)


if __name__ == "__main__":
    main()
