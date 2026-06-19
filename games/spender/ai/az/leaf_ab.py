"""The decisive retrain-premise test: does a SHARPER leaf -> stronger S at equal sims?

Candidate = vsearch with LEAF_MODE="distill" (ridge-on-enriched distilled toward V_search; leaf_model.npz,
held-out AUC ~0.718 vs the static leaf's ~0.670). Frozen = LEAF_MODE="vstate" (production). Same sims,
same H3 policy prior -- ONLY the value leaf differs. Paired CRN vs frozen-S (each board both first-player
ways, vsearch._RNG reset) + the heuristic panel as the RPS guard.

This is the go/no-go for the enriched-features retrain: if a measurably better-fitting leaf does NOT make
S stronger here, the retrain premise fails the same way the turns horizon did (AUC/R^2 != strength), and
we save the whole pipeline build. If it converts, the retrain has a basis.

NOTE: the distilled leaf computes the enriched features (H3 + v_state terms) per leaf, so it is NOT
faster than v_state -- this isolates the ACCURACY question (does a smarter leaf help), not speed.

Usage:
  python -m games.spender.ai.az.leaf_ab --n 160 --sims 160 --workers 12 --panel-n 80
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
from . import vsearch                  # noqa: E402
from .vsearch_camp import OPP, play_one, wilson_ci  # noqa: E402


def _play_h2h(cand_seat, seed, sims):
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(400):
        if s.phase == E.OVER:
            break
        vsearch.LEAF_MODE = "distill" if s.turn == cand_seat else "vstate"
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def _h2h_chunk(args):
    seed_base, lo, hi, sims = args
    tot = 0.0
    for g in range(lo, hi):
        tot += _play_h2h(0, seed_base + g, sims)
        tot += _play_h2h(1, seed_base + g, sims)
    return tot


def _panel_chunk(args):
    mode, nm, sb, lo, hi, sims = args
    vsearch.LEAF_MODE = mode
    opp = OPP[nm]
    return sum(play_one(opp, i % 2, seed=sb + i, sims=sims) for i in range(lo, hi))


def _panel(pool, workers, mode, n, seed0, step, sims):
    out = {}
    for i, nm in enumerate(["H3", "H2", "H2N", "H2R"]):
        sb = seed0 + i * step
        st = math.ceil(n / workers)
        tasks = [(mode, nm, sb, lo, min(lo + st, n), sims) for lo in range(0, n, st)]
        out[nm] = sum(pool.map(_panel_chunk, tasks)) / n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=160, help="paired trials vs frozen (=2n games)")
    ap.add_argument("--sims", type=int, default=160)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=220_000_000)
    ap.add_argument("--panel-n", type=int, default=80)
    ap.add_argument("--panel-seed", type=int, default=225_000_000)
    ap.add_argument("--panel-step", type=int, default=1_000_000)
    args = ap.parse_args()

    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    print(f"[leaf-ab] distill-leaf vs FROZEN vstate-leaf  sims={args.sims}  N={2*args.n} games  "
          f"workers={workers}", flush=True)
    try:
        base = _panel(pool, workers, "vstate", args.panel_n, args.panel_seed, args.panel_step, args.sims)
        print(f"[leaf-ab] frozen vstate panel: avg {sum(base.values())/len(base):.4f}  "
              f"{ {k: round(v,3) for k,v in base.items()} }", flush=True)
        t0 = time.time()
        st = math.ceil(args.n / workers)
        tasks = [(args.seed0, lo, min(lo + st, args.n), args.sims) for lo in range(0, args.n, st)]
        tot = sum(pool.map(_h2h_chunk, tasks)) if pool else sum(_h2h_chunk(t) for t in tasks)
        wr = tot / (2 * args.n)
        lo, hi = wilson_ci(wr, 2 * args.n)
        panel = _panel(pool, workers, "distill", args.panel_n, args.panel_seed, args.panel_step, args.sims)
        dmin = min(panel.values()) - min(base.values())
        rps = "OK" if dmin >= -0.02 else "SUSPECT"
        print(f"[leaf-ab] distill-leaf: vs-frozen {wr:.4f} (95% CI {lo:.3f}-{hi:.3f})  "
              f"panel avg {sum(panel.values())/len(panel):.4f} min {min(panel.values()):.3f} "
              f"(d {dmin:+.3f} {rps})  [{time.time()-t0:.0f}s]  "
              f"{{ {', '.join(f'{k} {v:.3f}' for k,v in panel.items())} }}", flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
