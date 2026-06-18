"""Offline discrimination test for V(state) — the cheap Phase-0 gate before building search.

Harvests every PLAY-turn position from H3-vs-panel games, computes ``v_state.value(s, to_move)``
live, then labels each position by whether the to-move seat eventually WON (+ the final point
margin). Reports:
  * sign(V) win-prediction accuracy, overall and on confidently-evaluated states (|V| >= tau),
  * a trivial point-difference baseline (predict the current leader), and
  * Pearson corr(V, final margin).

A BROKEN V (accuracy < ~0.6, or below the point-diff baseline) is caught here. A static V
plateauing near ~0.65 is EXPECTED and fine — its job is to be a good search LEAF (the decisive test
is the arena), but it must at least beat the trivial baseline and not be broken.

Parallel; opponents are passed by NAME (modules aren't picklable on spawn), mirroring h3_autotune.

Usage:
    python -m games.spender.ai.az.v_state_eval --games 200 --workers 12 --opps H3,H2,H2N,H2R
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
from .h3_vs_h2 import OPPONENTS

OPP = {**OPPONENTS, "H3": H3}   # {H, H2, H2N, H2R} + greedy H3


def _harvest_chunk(args):
    """Play games [lo, hi) of `opp_name`, recording (V, won, final_margin, point_diff) for every
    PLAY-turn position from the MOVER's perspective. Picklable worker."""
    opp_name, seed_base, lo, hi = args
    opp = OPP[opp_name]
    rows = []
    for i in range(lo, hi):
        s = E.new_game(random.Random(seed_base + i))
        prot = i % 2                       # H3 is the protagonist seat; opp is the other
        recs = []
        steps = 0
        while s.phase != E.OVER and steps < 400:
            if s.phase == E.PLAY:
                seat = s.turn
                recs.append((v_state.value(s, seat), seat, s.points[seat] - s.points[1 - seat]))
            actor = H3 if s.turn == prot else opp
            E.apply(s, actor.choose_action(s, s.turn))
            steps += 1
        if s.phase == E.OVER and s.winner != E.WIN_DRAW:
            for v, seat, pdiff in recs:
                won = 1.0 if s.winner == seat else 0.0
                rows.append((v, won, float(s.points[seat] - s.points[1 - seat]), float(pdiff)))
    return rows


def _accuracy(rows, tau: float):
    """Fraction of positions where sign(V) matches the eventual outcome, over states with |V|>=tau."""
    n = 0
    correct = 0.0
    for v, won, _margin, _pdiff in rows:
        if abs(v) < tau:
            continue
        n += 1
        if v == 0.0:
            correct += 0.5
        elif (v > 0.0) == (won > 0.5):
            correct += 1.0
    return (correct / n if n else 0.0), n


def _baseline_accuracy(rows):
    """Trivial baseline: predict the eventual winner from the CURRENT point difference."""
    n = len(rows)
    if not n:
        return 0.0
    correct = 0.0
    for _v, won, _margin, pdiff in rows:
        if pdiff == 0.0:
            correct += 0.5
        elif (pdiff > 0.0) == (won > 0.5):
            correct += 1.0
    return correct / n


def _corr(rows):
    """Pearson correlation of V with the final point margin (from the mover's perspective)."""
    n = len(rows)
    if n < 2:
        return 0.0
    xs = [r[0] for r in rows]
    ys = [r[2] for r in rows]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0.0 and syy > 0.0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--opps", default="H3,H2,H2N,H2R")
    ap.add_argument("--seed0", type=int, default=20_000_000)
    ap.add_argument("--step", type=int, default=1_000_000)
    args = ap.parse_args()

    opps = args.opps.split(",")
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    t0 = time.time()
    rows = []
    try:
        for oi, nm in enumerate(opps):
            sb = args.seed0 + oi * args.step
            if pool is None:
                rows += _harvest_chunk((nm, sb, 0, args.games))
            else:
                step = math.ceil(args.games / workers)
                tasks = [(nm, sb, lo, min(lo + step, args.games)) for lo in range(0, args.games, step)]
                for part in pool.map(_harvest_chunk, tasks):
                    rows += part
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    dt = time.time() - t0
    acc_all, n_all = _accuracy(rows, 0.0)
    acc_conf, n_conf = _accuracy(rows, 0.2)
    print(f"[v_state_eval] {len(rows)} positions from {args.games}x{len(opps)} games  "
          f"({dt:.0f}s)", flush=True)
    print(f"  sign(V) accuracy (all)        : {acc_all:.4f}  (N={n_all})")
    print(f"  sign(V) accuracy (|V|>=0.2)   : {acc_conf:.4f}  (N={n_conf})")
    print(f"  baseline sign(point-diff) acc : {_baseline_accuracy(rows):.4f}")
    print(f"  corr(V, final margin)         : {_corr(rows):.4f}")


if __name__ == "__main__":
    main()
