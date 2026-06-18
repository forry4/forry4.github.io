"""Clean A/B of full H3 configs vs the updated H2 and H, parallel, on fresh seeds.

Decomposes the candidate changes so each can be judged on its own merit against the COMMITTED
source baseline (read_current), not stacked assumptions. Reuses h3_autotune's parallel score().

Usage:
    python -m games.spender.ai.az.h3_eval --n 2500 --workers 10
"""
from __future__ import annotations

import argparse
import multiprocessing as mp

from . import h3_autotune as AT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2500)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed-h2", type=int, default=3_000_000)
    ap.add_argument("--seed-h", type=int, default=3_100_000)
    ap.add_argument("--h-floor", type=float, default=0.69)
    args = ap.parse_args()

    AT._WORKERS = max(1, args.workers)
    if AT._WORKERS > 1:
        AT._POOL = mp.Pool(processes=AT._WORKERS)

    base = AT.read_current()
    CONFIGS = [("baseline H3 (deployed)", {})]
    print(f"[h3-eval] N={args.n} seeds H2={args.seed_h2} H={args.seed_h}  "
          f"(source W_TEMPO={base['W_TEMPO']} NCF={base['NOBLE_CLOSE_FLOOR']} W_ENGINE={base['W_ENGINE']})",
          flush=True)
    for name, ov in CONFIGS:
        cfg = {**base, **ov}
        h2 = AT.score(cfg, "H2", args.n, args.seed_h2)
        h = AT.score(cfg, "H", args.n, args.seed_h)
        flag = "" if h >= args.h_floor else "  <-- vs-H BELOW FLOOR"
        print(f"  {name:<30}: vs H2 {h2:.4f}  vs H {h:.4f}{flag}", flush=True)

    if AT._POOL is not None:
        AT._POOL.close()
        AT._POOL.join()


if __name__ == "__main__":
    main()
