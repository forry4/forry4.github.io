"""Measure the typical-game length curve from S-vs-S play AND validate the turns-remaining estimators.

The deployed turns_table.json was measured from H3-vs-H2 games (h3_measure_turns.py). S (v_state leaf +
vsearch PUCT) is far stronger than H3, so from a given state an S game reaches the win in a different
number of turns -- and the table is also board-BLIND (keys only on the player's own cards/points/gems).
estimated_turns_remaining() feeds the horizon-gated terms (v_state._engine_stock / _noble_stand,
valuation3.noble_progress time-gate); a mis-calibrated horizon biases those terms (an inflated horizon
pushes S toward engine/noble over-investment -- a plausible partial cause of the measured over-reserve).

This plays S-vs-S at a modest search budget and does TWO things at once:
  (1) BUILD a recalibrated table from S play -> turns_table_s.json (same shape valuation3 loads; the H3
      turns_table.json is left intact so H3/H2 are unaffected and we can A/B the two tables for S).
  (2) VALIDATE the estimators: at every PLAY ply it computes the deployed TABLE estimate (min over both
      seats of the H3 lookup) and the new PLANNER estimate (min over both seats of _planner_turns_seat),
      and pairs each with the GROUND TRUTH -- the acting seat's actual number of future own main turns.
      Reports each estimator's MAE / bias / Pearson correlation vs ground truth, so we know which one
      tracks reality (correlation is scale-invariant; bias tells us the PLANNER_SCALE to deploy).

ASCII-only output (Windows console). Usage:
    python -m games.spender.ai.az.s_measure_turns --games 300 --sims 128 --workers 12
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import logging
import math
import multiprocessing as mp
import random
import time
from collections import defaultdict

logging.getLogger("games.spender").setLevel(logging.ERROR)

from . import engine as E          # noqa: E402
from . import valuation3 as V3     # noqa: E402
from . import vsearch              # noqa: E402

_DIR = os.path.dirname(__file__)
OUT_PATH = os.path.join(_DIR, "turns_table_s.json")
H3_TABLE_PATH = os.path.join(_DIR, "turns_table.json")

# accuracy accumulator layout: [n, Sx, Sy, Sxx, Syy, Sxy, Sabs]   (x = estimate, y = ground truth)
def _acc():
    return [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _add(acc, x, y):
    acc[0] += 1
    acc[1] += x
    acc[2] += y
    acc[3] += x * x
    acc[4] += y * y
    acc[5] += x * y
    acc[6] += abs(x - y)


def _merge(dst, src):
    for i in range(7):
        dst[i] += src[i]


def _table_est(s):
    return min(V3._lookup_turns(s.purchased_n[0], s.points[0], sum(s.tokens[0])),
               V3._lookup_turns(s.purchased_n[1], s.points[1], sum(s.tokens[1])))


def _planner_est(s, win):
    return min(V3._planner_turns_seat(s, 0, win), V3._planner_turns_seat(s, 1, win))


def _play_chunk(args):
    seed_base, lo, hi, sims, win_points = args
    cells = defaultdict(lambda: [0.0, 0, 0])          # (cards,points,gems) -> [sum_tl, count, won]
    acc_t, acc_p = _acc(), _acc()                     # table / planner accuracy
    for g in range(lo, hi):
        seed = seed_base + g
        vsearch._RNG = random.Random(seed)
        s = E.new_game(random.Random(seed), win_points=win_points)
        win = getattr(s, "win_points", E.WIN_POINTS)
        snaps = {0: [], 1: []}                        # per seat: (triple, table_est, planner_est)
        for _ in range(800):
            if s.phase == E.OVER:
                break
            if s.phase == E.PLAY:
                seat = s.turn
                triple = (s.purchased_n[seat], s.points[seat], sum(s.tokens[seat]))
                snaps[seat].append((triple, _table_est(s), _planner_est(s, win)))
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
        won = [0, 0]
        if s.phase == E.OVER and s.winner in (0, 1):
            won[s.winner] = 1
        for seat in (0, 1):
            lst = snaps[seat]
            T = len(lst)
            for j, (triple, et, ep) in enumerate(lst):
                actual = T - 1 - j                    # this seat's future own main turns (ground truth)
                cell = cells[triple]
                cell[0] += actual
                cell[1] += 1
                cell[2] += won[seat]
                _add(acc_t, et, actual)
                _add(acc_p, ep, actual)
    return dict(cells), acc_t, acc_p


def _stats(acc, label):
    n = acc[0]
    if n == 0:
        return f"   {label:8} (no samples)"
    mae = acc[6] / n
    bias = (acc[1] - acc[2]) / n                      # mean(estimate - actual)
    cov = acc[5] - acc[1] * acc[2] / n
    vx = acc[3] - acc[1] * acc[1] / n
    vy = acc[4] - acc[2] * acc[2] / n
    corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else float("nan")
    mean_est = acc[1] / n
    mean_act = acc[2] / n
    scale = mean_act / mean_est if mean_est else float("nan")
    return (f"   {label:8} corr {corr:+.3f}  MAE {mae:5.2f}  bias {bias:+5.2f}  "
            f"(mean est {mean_est:5.2f} vs actual {mean_act:5.2f}; scale-to-match {scale:.3f})")


def _load_table(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    return {(r[0], r[1], r[2]): (r[3], r[4]) for r in data["rows"]}


def _compare_tables(rows, args):
    h3 = _load_table(H3_TABLE_PATH)
    if h3 is None:
        print("   [tables] no turns_table.json to compare against", flush=True)
        return
    s_tbl = {(r[0], r[1], r[2]): (r[3], r[4]) for r in rows}
    num = den = sdiff = 0.0
    ncells = 0
    for key, (s_avg, s_cnt) in s_tbl.items():
        if s_cnt < args.min_count or key not in h3:
            continue
        h_avg, _ = h3[key]
        num += s_avg * s_cnt
        den += s_cnt
        sdiff += (s_avg - h_avg) * s_cnt
        ncells += 1
    if den == 0:
        print("   [tables] no overlapping cells above --min-count", flush=True)
        return
    verdict = "S shorter -> H3 table OVER-estimates for S" if sdiff / den < 0 else "S longer than H3"
    print(f"   [tables] over {ncells} shared cells (S count>={args.min_count}, S-count-weighted): "
          f"S avg {num/den:.3f}  mean(S - H3) {sdiff/den:+.3f}  ({verdict})", flush=True)
    print("   [tables] sample cells (cards,pts,gems):   S(n)   vs   H3(n)", flush=True)
    for key in [(0, 0, 0), (2, 2, 5), (4, 3, 7), (6, 5, 8), (8, 8, 6), (10, 11, 5)]:
        sc, hc = s_tbl.get(key), h3.get(key)
        sstr = f"{sc[0]:5.2f}(n={sc[1]:>4})" if sc else "    -        "
        hstr = f"{hc[0]:5.2f}(n={hc[1]:>4})" if hc else "    -        "
        print(f"     {str(key):14}  S {sstr}   H3 {hstr}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--sims", type=int, default=128)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=160_000_000)
    ap.add_argument("--min-count", type=int, default=20)
    ap.add_argument("--win-points", type=int, default=15,
                    help="play games to this many points (21 -> writes turns_table_21.json for S21)")
    args = ap.parse_args()

    out_path = (os.path.join(_DIR, "turns_table_21.json") if args.win_points == 21 else OUT_PATH)
    t0 = time.time()
    workers = max(1, args.workers)
    step = math.ceil(args.games / workers)
    tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims, args.win_points)
             for lo in range(0, args.games, step)]

    merged = defaultdict(lambda: [0.0, 0, 0])
    acc_t, acc_p = _acc(), _acc()
    if workers > 1:
        with mp.Pool(processes=workers) as pool:
            parts = pool.map(_play_chunk, tasks)
    else:
        parts = [_play_chunk(t) for t in tasks]
    for cells, a_t, a_p in parts:
        for key, (s_tl, cnt, won) in cells.items():
            m = merged[key]
            m[0] += s_tl
            m[1] += cnt
            m[2] += won
        _merge(acc_t, a_t)
        _merge(acc_p, a_p)

    rows = []
    for (c, p, gm), (s_tl, cnt, won) in sorted(merged.items()):
        rows.append([c, p, gm, round(s_tl / cnt, 3), cnt, won])
    max_cards = max(r[0] for r in rows)
    max_points = max(r[1] for r in rows)
    max_gems = max(r[2] for r in rows)
    payload = {"rows": rows, "max_cards": max_cards, "max_points": max_points,
               "max_gems": max_gems, "n_games": args.games, "n_cells": len(rows),
               "source": "S-vs-S", "sims": args.sims, "win_points": args.win_points}
    with open(out_path, "w") as f:
        json.dump(payload, f)

    print(f"[s-measure] {args.games} S-vs-S games to {args.win_points}pts @ sims={args.sims} -> {len(rows)} "
          f"cells (max_cards={max_cards} max_points={max_points} max_gems={max_gems})  "
          f"({time.time()-t0:.0f}s)  -> {os.path.basename(out_path)}", flush=True)
    print(f"[accuracy] estimator vs ground-truth (acting seat's future own turns), {acc_t[0]} positions:",
          flush=True)
    print(_stats(acc_t, "TABLE"), flush=True)
    print(_stats(acc_p, "PLANNER"), flush=True)
    _compare_tables(rows, args)


if __name__ == "__main__":
    main()
