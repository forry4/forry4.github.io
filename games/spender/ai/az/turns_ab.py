"""A/B the turns-remaining estimators for variant S, head-to-head vs FROZEN today's-S.

Frozen S = TURNS_MODE="table" (the deployed H3-measured lookup, current behavior). Each CANDIDATE
mode ("table_s" = the S-remeasured table, "planner" = the board-conditional estimate) plays a full
search against frozen S on shared decks with seats swapped (paired CRN, same as vsearch_selfgate),
so start=0.5 is unbiased and board + first-player variance cancel. A mode that beats 0.5 by the
adopt margin is objectively stronger than the current horizon. Each candidate is ALSO measured vs
the heuristic panel (H3/H2/H2N/H2R) as the rock-paper-scissors guard (a mode can beat frozen-S via
a matchup quirk without being globally stronger).

The candidate mode is applied PER TURN (the acting player's whole search runs under its mode), exactly
mirroring vsearch_selfgate._play_selfgate's per-seat config swap.

Usage:
  python -m games.spender.ai.az.turns_ab --modes table_s,planner --n 200 --sims 200 --workers 12 \
      --planner-scale 0.9
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

FROZEN_MODE = "table"


def _play_h2h(cand_mode, cand_seat, seed, sims, planner_scale, deck_rate):
    """One candidate(cand_mode)-vs-frozen(table) game on board `seed`; cand_seat is the candidate's
    seat (seat 0 moves first). Returns candidate's score in {0,0.5,1}."""
    V3.PLANNER_SCALE = planner_scale
    V3.PLANNER_DECK_RATE = deck_rate
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(400):
        if s.phase == E.OVER:
            break
        V3.TURNS_MODE = cand_mode if s.turn == cand_seat else FROZEN_MODE
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def _h2h_chunk(args):
    cand_mode, seed_base, lo, hi, sims, planner_scale, deck_rate = args
    tot = 0.0
    for g in range(lo, hi):
        tot += _play_h2h(cand_mode, 0, seed_base + g, sims, planner_scale, deck_rate)   # cand first
        tot += _play_h2h(cand_mode, 1, seed_base + g, sims, planner_scale, deck_rate)   # frozen first
    return tot


def _panel_chunk(args):
    cand_mode, nm, sb, lo, hi, sims, planner_scale, deck_rate = args
    V3.PLANNER_SCALE = planner_scale
    V3.PLANNER_DECK_RATE = deck_rate
    V3.TURNS_MODE = cand_mode
    opp = OPP[nm]
    # play_one uses vsearch for the protagonist; TURNS_MODE governs every vsearch eval in-process
    return sum(play_one(opp, i % 2, seed=sb + i, sims=sims) for i in range(lo, hi))


def _panel(pool, workers, cand_mode, n, seed0, step, sims, planner_scale, deck_rate):
    out = {}
    for i, nm in enumerate(["H3", "H2", "H2N", "H2R"]):
        sb = seed0 + i * step
        st = math.ceil(n / workers)
        tasks = [(cand_mode, nm, sb, lo, min(lo + st, n), sims, planner_scale, deck_rate)
                 for lo in range(0, n, st)]
        out[nm] = sum(pool.map(_panel_chunk, tasks)) / n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="table_s,planner")
    ap.add_argument("--n", type=int, default=200, help="paired trials vs frozen (=2n games)")
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=170_000_000)
    ap.add_argument("--panel-n", type=int, default=120)
    ap.add_argument("--panel-seed", type=int, default=175_000_000)
    ap.add_argument("--panel-step", type=int, default=1_000_000)
    ap.add_argument("--planner-scale", type=float, default=V3.PLANNER_SCALE)
    ap.add_argument("--planner-deck-rate", type=float, default=V3.PLANNER_DECK_RATE)
    args = ap.parse_args()

    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    modes = args.modes.split(",")
    print(f"[turns-ab] vs FROZEN '{FROZEN_MODE}'  sims={args.sims}  N={2*args.n} games/mode  "
          f"planner_scale={args.planner_scale} deck_rate={args.planner_deck_rate}  workers={workers}",
          flush=True)
    try:
        # frozen panel baseline (mode 'table')
        base_panel = _panel(pool, workers, FROZEN_MODE, args.panel_n, args.panel_seed,
                            args.panel_step, args.sims, args.planner_scale, args.planner_deck_rate)
        print(f"[turns-ab] frozen 'table' panel: avg {sum(base_panel.values())/len(base_panel):.4f}  "
              f"{ {k: round(v,3) for k,v in base_panel.items()} }", flush=True)
        for mode in modes:
            t0 = time.time()
            st = math.ceil(args.n / workers)
            tasks = [(mode, args.seed0, lo, min(lo + st, args.n), args.sims,
                      args.planner_scale, args.planner_deck_rate) for lo in range(0, args.n, st)]
            tot = sum(pool.map(_h2h_chunk, tasks)) if pool else sum(_h2h_chunk(t) for t in tasks)
            wr = tot / (2 * args.n)
            lo, hi = wilson_ci(wr, 2 * args.n)
            panel = _panel(pool, workers, mode, args.panel_n, args.panel_seed, args.panel_step,
                          args.sims, args.planner_scale, args.planner_deck_rate)
            dmin = min(panel.values()) - min(base_panel.values())
            rps = "OK" if dmin >= -0.02 else "SUSPECT (worse vs panel)"
            print(f"[turns-ab] '{mode}': vs-frozen {wr:.4f} (95% CI {lo:.3f}-{hi:.3f})  "
                  f"panel avg {sum(panel.values())/len(panel):.4f} min {min(panel.values()):.3f} "
                  f"(d {dmin:+.3f} {rps})  [{time.time()-t0:.0f}s]  {{ {', '.join(f'{k} {v:.3f}' for k,v in panel.items())} }}",
                  flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
