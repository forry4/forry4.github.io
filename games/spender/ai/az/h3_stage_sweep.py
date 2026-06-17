"""Focused parallel sweep of H3's STAGE knobs (STAGE_FLOOR, STAGE_K) vs the updated H2 and H.

Reuses h3_autotune's parallel `score()` (multiprocessing pool, CRN seeds). Anchored on run-1's
frontier config so stage effects are measured ON TOP of the best-known H3, not the stale default.
Sweeps each knob one-at-a-time and prints vs-H2 (objective) + vs-H (constraint >= H_FLOOR).
STAGE_FLOOR is swept up to 1.0 (== staging DISABLED, points always full) -- a region the
autotuner never tried (its grid capped at 0.5).

Usage:
    python -m games.spender.ai.az.h3_stage_sweep --n 1500 --workers 10
"""
from __future__ import annotations

import argparse
import multiprocessing as mp

from . import h3_autotune as AT

# run-1 validated frontier (NOT yet baked into source): W_TEMPO down, NOBLE_CLOSE_FLOOR up.
FRONTIER = {"W_TEMPO": 0.1, "NOBLE_CLOSE_FLOOR": 0.3}

STAGE_FLOOR_GRID = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25]
STAGE_K_GRID = [8, 10, 14, 18, 22, 28]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed-h2", type=int, default=1_000_000)
    ap.add_argument("--seed-h", type=int, default=1_100_000)
    ap.add_argument("--h-floor", type=float, default=0.69)
    args = ap.parse_args()

    AT._WORKERS = max(1, args.workers)
    if AT._WORKERS > 1:
        AT._POOL = mp.Pool(processes=AT._WORKERS)

    base = AT.read_current()
    base.update(FRONTIER)

    def evalcfg(cfg):
        h2 = AT.score(cfg, "H2", args.n, args.seed_h2)
        h = AT.score(cfg, "H", args.n, args.seed_h)
        return h2, h

    b2, bh = evalcfg(base)
    print(f"[stage-sweep] base (frontier) STAGE_FLOOR={base['STAGE_FLOOR']} STAGE_K={base['STAGE_K']}: "
          f"vs H2 {b2:.4f}  vs H {bh:.4f}  (N={args.n})", flush=True)

    best_sf, best_sf_h2 = base["STAGE_FLOOR"], b2
    print(f"\n-- STAGE_FLOOR sweep (STAGE_K={base['STAGE_K']}) --", flush=True)
    for sf in STAGE_FLOOR_GRID:
        h2, h = evalcfg({**base, "STAGE_FLOOR": sf})
        flag = "" if h >= args.h_floor else "  <-- vs-H BELOW FLOOR"
        print(f"  STAGE_FLOOR={sf:<4}: vs H2 {h2:.4f}  vs H {h:.4f}{flag}", flush=True)
        if h >= args.h_floor and h2 > best_sf_h2:
            best_sf, best_sf_h2 = sf, h2

    best_sk, best_sk_h2 = base["STAGE_K"], b2
    print(f"\n-- STAGE_K sweep (STAGE_FLOOR={base['STAGE_FLOOR']}) --", flush=True)
    for sk in STAGE_K_GRID:
        h2, h = evalcfg({**base, "STAGE_K": sk})
        flag = "" if h >= args.h_floor else "  <-- vs-H BELOW FLOOR"
        print(f"  STAGE_K={sk:<3}: vs H2 {h2:.4f}  vs H {h:.4f}{flag}", flush=True)
        if h >= args.h_floor and h2 > best_sk_h2:
            best_sk, best_sk_h2 = sk, h2

    # combination of the best feasible value of each, with a DISJOINT-seed confirm.
    combo = {**base, "STAGE_FLOOR": best_sf, "STAGE_K": best_sk}
    c2, ch = evalcfg(combo)
    cf2 = AT.score(combo, "H2", args.n, args.seed_h2 + 333_000)   # disjoint confirm seeds
    cfh = AT.score(combo, "H", args.n, args.seed_h + 333_000)
    print(f"\n-- COMBO STAGE_FLOOR={best_sf} STAGE_K={best_sk} --", flush=True)
    print(f"  sweep-seed : vs H2 {c2:.4f}  vs H {ch:.4f}", flush=True)
    print(f"  CONFIRM    : vs H2 {cf2:.4f}  vs H {cfh:.4f}"
          f"{'' if cfh >= args.h_floor else '  <-- vs-H BELOW FLOOR'}", flush=True)

    if AT._POOL is not None:
        AT._POOL.close()
        AT._POOL.join()


if __name__ == "__main__":
    main()
