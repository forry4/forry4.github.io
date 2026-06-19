"""A/B the reserve-blind-key correction RESERVE_TURN_ADJ for variant S, vs FROZEN today's-S.

turns_feat_diag showed holding reserves correlates with ~0.72 fewer turns left than the
(cards,points,gems) table key implies -> the table over-estimates the horizon in S's reserve-heavy
states. valuation3.RESERVE_TURN_ADJ subtracts that per reserved card (default 0). This tests whether
applying it makes S PLAY better (R^2 != strength -- table_s rebuild was a wash, so the head-to-head
is the real judge).

Candidate = (RESERVE_TURN_ADJ=adj), frozen = (adj=0); both TURNS_MODE="table". Paired CRN (each board
both first-player ways, vsearch._RNG reset), same design as vsearch_selfgate, so cand==frozen -> 0.5.
Plus the heuristic panel as the RPS guard.

Usage:
  python -m games.spender.ai.az.reserve_adj_ab --adjs 0.4,0.7,1.0 --n 160 --sims 200 --workers 12
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import logging
import math
import multiprocessing as mp
import random
import time

logging.getLogger("games.spender").setLevel(logging.ERROR)

from . import engine as E              # noqa: E402
from . import valuation3 as V3         # noqa: E402
from . import vsearch                  # noqa: E402
from .vsearch_camp import OPP, play_one, wilson_ci  # noqa: E402


def _play_h2h(adj, cand_seat, seed, sims):
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(400):
        if s.phase == E.OVER:
            break
        V3.RESERVE_TURN_ADJ = adj if s.turn == cand_seat else 0.0
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def _h2h_chunk(args):
    adj, seed_base, lo, hi, sims = args
    tot = 0.0
    for g in range(lo, hi):
        tot += _play_h2h(adj, 0, seed_base + g, sims)
        tot += _play_h2h(adj, 1, seed_base + g, sims)
    return tot


def _panel_chunk(args):
    adj, nm, sb, lo, hi, sims = args
    V3.RESERVE_TURN_ADJ = adj
    opp = OPP[nm]
    return sum(play_one(opp, i % 2, seed=sb + i, sims=sims) for i in range(lo, hi))


def _panel(pool, workers, adj, n, seed0, step, sims):
    out = {}
    for i, nm in enumerate(["H3", "H2", "H2N", "H2R"]):
        sb = seed0 + i * step
        st = math.ceil(n / workers)
        tasks = [(adj, nm, sb, lo, min(lo + st, n), sims) for lo in range(0, n, st)]
        out[nm] = sum(pool.map(_panel_chunk, tasks)) / n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjs", default="0.4,0.7,1.0")
    ap.add_argument("--n", type=int, default=160, help="paired trials vs frozen (=2n games)")
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=185_000_000)
    ap.add_argument("--panel-n", type=int, default=80)
    ap.add_argument("--panel-seed", type=int, default=190_000_000)
    ap.add_argument("--panel-step", type=int, default=1_000_000)
    args = ap.parse_args()

    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    adjs = [float(x) for x in args.adjs.split(",")]
    print(f"[reserve-adj-ab] vs FROZEN (adj=0)  sims={args.sims}  N={2*args.n} games/adj  "
          f"workers={workers}", flush=True)
    try:
        base = _panel(pool, workers, 0.0, args.panel_n, args.panel_seed, args.panel_step, args.sims)
        print(f"[reserve-adj-ab] frozen adj=0 panel: avg {sum(base.values())/len(base):.4f}  "
              f"{ {k: round(v,3) for k,v in base.items()} }", flush=True)
        for adj in adjs:
            t0 = time.time()
            st = math.ceil(args.n / workers)
            tasks = [(adj, args.seed0, lo, min(lo + st, args.n), args.sims)
                     for lo in range(0, args.n, st)]
            tot = sum(pool.map(_h2h_chunk, tasks)) if pool else sum(_h2h_chunk(t) for t in tasks)
            wr = tot / (2 * args.n)
            lo, hi = wilson_ci(wr, 2 * args.n)
            panel = _panel(pool, workers, adj, args.panel_n, args.panel_seed, args.panel_step, args.sims)
            dmin = min(panel.values()) - min(base.values())
            rps = "OK" if dmin >= -0.02 else "SUSPECT"
            print(f"[reserve-adj-ab] adj={adj}: vs-frozen {wr:.4f} (95% CI {lo:.3f}-{hi:.3f})  "
                  f"panel avg {sum(panel.values())/len(panel):.4f} min {min(panel.values()):.3f} "
                  f"(d {dmin:+.3f} {rps})  [{time.time()-t0:.0f}s]  "
                  f"{{ {', '.join(f'{k} {v:.3f}' for k,v in panel.items())} }}", flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
