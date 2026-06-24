"""One-off RPS guard: the H3/H3N/H3R panel for FROZEN-S vs a candidate S config.

Runs ONLY the panel (no screen/fresh self-gate) so it's cheap. cand and frozen face the
IDENTICAL decks per opponent (same --seed0), so the per-opponent difference is CRN-paired.
Verdict mirrors config_selfgate: cand is OK if its WORST matchup isn't >0.02 below frozen's worst.

  python -m games.spender.ai.az.panel_check --sims 500 --n 300 --workers 10 \
      --config "PROGRESS_TOPK=6;PROGRESS_DECAY=1.0;W_PROGRESS=3.54"
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import multiprocessing as mp
import time

from . import config_selfgate as cs
from .h3_vs_h2 import wilson_ci


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed0", type=int, default=130_000_000)
    ap.add_argument("--step", type=int, default=100_000)
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cs.FROZEN = {k: getattr(mod, k) for k in cs._PROBE_KEYS for mod in cs._MODS if hasattr(mod, k)}
    cand = cs._parse_cfg(args.config)
    pool = mp.Pool(args.workers)
    t0 = time.time()
    print(f"[panel-check] sims={args.sims} n={args.n} workers={args.workers} opponents={cs.PANEL}", flush=True)
    print(f"[config] {args.config}", flush=True)
    try:
        fp = cs.panel(dict(cs.FROZEN), args.n, args.seed0, args.step, args.sims, pool, args.workers)
        print(f"[frozen] {fp}  avg {sum(fp.values())/len(fp):.4f} min {min(fp.values()):.4f}  [{time.time()-t0:.0f}s]", flush=True)
        cp = cs.panel(cand, args.n, args.seed0, args.step, args.sims, pool, args.workers)
        print(f"[cand  ] {cp}  avg {sum(cp.values())/len(cp):.4f} min {min(cp.values()):.4f}  [{time.time()-t0:.0f}s]", flush=True)
        for nm in cs.PANEL:
            lo, hi = wilson_ci(cp[nm], args.n)
            flo, fhi = wilson_ci(fp[nm], args.n)
            print(f"  {nm}: cand {cp[nm]:.4f} (CI {lo:.3f}-{hi:.3f})  "
                  f"frozen {fp[nm]:.4f} (CI {flo:.3f}-{fhi:.3f})  d{cp[nm]-fp[nm]:+.4f}", flush=True)
        cmin, fmin = min(cp.values()), min(fp.values())
        cavg, favg = sum(cp.values())/len(cp), sum(fp.values())/len(fp)
        ok = cmin >= fmin - 0.02
        print(f"[verdict] cand min {cmin:.4f} vs frozen min {fmin:.4f} (d{cmin-fmin:+.4f}); "
              f"avg {cavg:.4f} vs {favg:.4f} (d{cavg-favg:+.4f}) -> {'OK (no RPS regression)' if ok else 'RPS-RISK'}",
              flush=True)
    finally:
        pool.close()
        pool.join()


if __name__ == "__main__":
    main()
