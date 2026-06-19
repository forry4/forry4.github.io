"""Adversarial blunder / behavior audit for variant S (offline scratch).

Plays S-vs-S at a SHALLOW (serving-ish) budget and audits the moves three ways:
  1. Move-type distribution S vs greedy H3 — does S over-RESERVE relative to the greedy baseline?
  2. Wasted-reserve rate — fraction of reserved cards never bought by game end (dead tempo).
  3. search-vs-H3 top-move agreement — the cheap policy ceiling: if the search almost always agrees
     with the H3 prior, a learned policy has little room (informs the policy pre-check).
  4. Deep-disagreement audit — on a sampled subset, run a DEEP search (ground-truth-ish) and flag
     positions where the shallow move differs with a big value gap (per the deep search's Q),
     bucketed by the type-shift (e.g. shallow=reserve -> deep=buy ⇒ over-reserve, concretely).

ASCII-only output (Windows console). Usage:
  python -m games.spender.ai.az.blunder_finder --games 40 --sims 512 --deep 2500 --deep-every 4 --workers 6
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import collections
import logging
import math
import multiprocessing as mp
import random
import time

logging.getLogger("games.spender").setLevel(logging.ERROR)

from . import engine as E          # noqa: E402
from . import heuristic3 as H3     # noqa: E402
from . import v_state              # noqa: E402
from . import vsearch              # noqa: E402
from .mcts import Search           # noqa: E402


def _mtype(a):
    if E.A_TAKE3 <= a < E.A_TAKE2D: return "take3"
    if E.A_TAKE2D <= a < E.A_TAKE1: return "take2-diff"
    if E.A_TAKE1 <= a < E.A_TAKE2S: return "take1"
    if E.A_TAKE2S <= a < E.A_PASS: return "take2-same"
    if a == E.A_PASS: return "pass"
    if E.A_RES_BOARD <= a < E.A_BUY_BOARD: return "reserve"
    if E.A_BUY_BOARD <= a < E.A_DISCARD: return "buy"
    if E.A_DISCARD <= a < E.A_NOBLE: return "discard"
    return "noble"


def _search_move(s, sims):
    """Return (best action, root N list, root W list) for a sims-budget search at s."""
    search = Search(s, vsearch._RNG, c_puct=vsearch.C_PUCT, add_noise=False, leaf_state=True)
    for _ in range(sims):
        vsearch._expand(search)
    n = search.root.N
    legal = E.legal_actions(s)
    best = max(legal, key=lambda a: n[a])
    return best, n, search.root.W


def _chunk(args):
    seed_base, lo, hi, sims, deep, deep_every, reserve_penalty = args
    v_state.RESERVE_PENALTY = reserve_penalty   # apply the fix knob inside the worker process
    mt = collections.Counter()         # S move types (PLAY phase)
    mt_h3 = collections.Counter()      # H3 greedy move types at the same positions
    agree = 0
    n_play = 0
    reserves_made = 0
    wasted = 0
    deep_n = 0
    deep_disagree = 0
    shift = collections.Counter()      # (shallow_type -> deep_type) on deep-audited disagreements
    gap_sum = 0.0
    gap_blunders = 0                   # disagreements with value gap > 0.10
    pos_idx = 0
    for i in range(lo, hi):
        s = E.new_game(random.Random(seed_base + i))
        steps = 0
        while s.phase != E.OVER and steps < 400:
            if s.phase == E.PLAY:
                legal = E.legal_actions(s)
                if len(legal) > 1:
                    seat = s.turn
                    a, n, w = _search_move(s, sims)
                    mt[_mtype(a)] += 1
                    n_play += 1
                    h3a = H3.choose_action(s, seat)
                    mt_h3[_mtype(h3a)] += 1
                    if h3a == a:
                        agree += 1
                    if _mtype(a) == "reserve":
                        reserves_made += 1
                    if deep_every and pos_idx % deep_every == 0:
                        da, dn, dw = _search_move(s, deep)
                        deep_n += 1
                        if da != a:
                            deep_disagree += 1
                            shift[(_mtype(a), _mtype(da))] += 1
                            qd = dw[da] / dn[da] if dn[da] else 0.0
                            qs = dw[a] / dn[a] if dn[a] else 0.0
                            gap = qd - qs
                            gap_sum += gap
                            if gap > 0.10:
                                gap_blunders += 1
                    pos_idx += 1
                    E.apply(s, a)
                    steps += 1
                    continue
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
            steps += 1
        # wasted reserves: cards still held in reserve at game end (never bought)
        if s.phase == E.OVER:
            wasted += len(s.reserved[0]) + len(s.reserved[1])
    return (mt, mt_h3, agree, n_play, reserves_made, wasted, deep_n, deep_disagree,
            shift, gap_sum, gap_blunders)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--sims", type=int, default=512)
    ap.add_argument("--deep", type=int, default=2500)
    ap.add_argument("--deep-every", type=int, default=4)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed0", type=int, default=90_000_000)
    ap.add_argument("--reserve-penalty", type=float, default=0.0)
    args = ap.parse_args()

    t0 = time.time()
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    step = math.ceil(args.games / workers)
    tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims, args.deep, args.deep_every,
              args.reserve_penalty) for lo in range(0, args.games, step)]
    parts = pool.map(_chunk, tasks) if pool else [_chunk(t) for t in tasks]
    if pool:
        pool.close(); pool.join()

    mt, mt_h3 = collections.Counter(), collections.Counter()
    agree = n_play = reserves = wasted = deep_n = deep_dis = gap_bl = 0
    shift = collections.Counter()
    gap_sum = 0.0
    for (a_mt, a_h3, a_ag, a_np, a_res, a_w, a_dn, a_dd, a_sh, a_gs, a_gb) in parts:
        mt += a_mt; mt_h3 += a_h3; shift += a_sh
        agree += a_ag; n_play += a_np; reserves += a_res; wasted += a_w
        deep_n += a_dn; deep_dis += a_dd; gap_sum += a_gs; gap_bl += a_gb

    print(f"[blunder] {args.games} S-vs-S games, {n_play} PLAY decisions @ sims={args.sims} "
          f"(deep={args.deep} every {args.deep_every})  ({time.time()-t0:.0f}s)")
    print("  move-type distribution (S vs greedy H3):")
    for k in ("buy", "reserve", "take3", "take2-diff", "take2-same", "take1", "pass"):
        s_pct = 100 * mt[k] / n_play if n_play else 0
        h_tot = sum(mt_h3.values())
        h_pct = 100 * mt_h3[k] / h_tot if h_tot else 0
        print(f"    {k:11} S {s_pct:5.1f}%   H3 {h_pct:5.1f}%")
    print(f"  reserves made: {reserves}  ({100*reserves/n_play:.1f}% of moves)   "
          f"wasted (held at game end): {wasted}  -> ~{100*wasted/max(1,reserves):.0f}% of reserves unused")
    print(f"  search-vs-H3 top-move agreement: {100*agree/max(1,n_play):.1f}%  "
          f"(low => a learned policy has room; high => H3 prior already near-optimal)")
    if deep_n:
        print(f"  deep audit: {deep_n} positions, deep DISAGREES with shallow {100*deep_dis/deep_n:.1f}% "
              f"(mean value gap {gap_sum/max(1,deep_dis):.3f}; {gap_bl} big blunders gap>0.10)")
        print("    top type-shifts (shallow -> deep) on disagreements:")
        for (st, dt), c in shift.most_common(6):
            print(f"      {st:11} -> {dt:11}  x{c}")


if __name__ == "__main__":
    main()
