"""Does the turns_table KEY throw away signal that matters for S? (reserves + gold)

turns_table.json keys on (cards, points, total_gems) -- it has NO reserved-card dimension, and it
treats gold as a plain gem (the key is sum(tokens), gold included undifferentiated). S sits in
reserve-heavy / gold-heavy states far more than the H3 games the table was built from, so a key
blind to those axes could be systematically wrong for S even though the reserve-AVERAGED table looks
identical (s_measure_turns showed the marginal cells match to -0.02 turns).

This harvests S-vs-S positions with the FULL feature vector and asks the decisive question two ways:
  1. Fit a linear model on the TABLE'S inputs [cards, points, total_gems], then bucket its RESIDUALS
     (actual - predicted turns-left) by reserved-count and by gold. If the residual trends along an
     axis the model can't see, that axis carries omitted signal -> the key is lossy where it matters.
  2. Fit the FULL model [cards, points, colored_gems, gold, reserved] and report the extra R^2 and the
     coefficients -- in particular gold vs colored_gems (is a gold worth more turns-of-progress than a
     plain gem?) and reserved-count (does holding reserves change the horizon at fixed cards/points/gems?).

Effect sizes are in TURNS. <~0.3 turns = negligible (the key is fine); >~1 turn = the enriched key is
worth building + A/B-ing. ASCII-only. Usage:
    python -m games.spender.ai.az.turns_feat_diag --games 240 --sims 128 --workers 12
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

import numpy as np

logging.getLogger("games.spender").setLevel(logging.ERROR)

from . import engine as E          # noqa: E402
from . import vsearch              # noqa: E402

# feature columns: 0 cards, 1 points, 2 colored_gems, 3 gold, 4 reserved_count
def _play_chunk(args):
    seed_base, lo, hi, sims = args
    rows = []                                   # (cards, points, colored, gold, reserved, turns_left)
    for g in range(lo, hi):
        seed = seed_base + g
        vsearch._RNG = random.Random(seed)
        s = E.new_game(random.Random(seed))
        snaps = {0: [], 1: []}
        for _ in range(800):
            if s.phase == E.OVER:
                break
            if s.phase == E.PLAY:
                seat = s.turn
                tok = s.tokens[seat]
                colored = sum(tok[:5])
                gold = tok[5]
                snaps[seat].append((s.purchased_n[seat], s.points[seat], colored, gold,
                                    len(s.reserved[seat])))
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
        for seat in (0, 1):
            lst = snaps[seat]
            T = len(lst)
            for j, feat in enumerate(lst):
                rows.append(feat + (T - 1 - j,))
    return np.asarray(rows, dtype=np.float64) if rows else np.zeros((0, 6))


def _fit(X, y):
    """OLS with intercept; return (beta_with_intercept, r2, residuals)."""
    A = np.hstack([X, np.ones((len(X), 1))])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ beta
    resid = y - pred
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, r2, resid


def _bucket_residuals(resid, axis_vals, label, cap=3):
    print(f"   mean residual (actual - table-model pred) by {label}:", flush=True)
    b = np.minimum(axis_vals.astype(int), cap)
    for v in range(cap + 1):
        m = b == v
        n = int(m.sum())
        if n:
            tag = f"{v}+" if v == cap else f"{v}"
            print(f"     {label}={tag:>2}: {resid[m].mean():+6.3f} turns   (n={n})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=240)
    ap.add_argument("--sims", type=int, default=128)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=180_000_000)
    args = ap.parse_args()

    t0 = time.time()
    workers = max(1, args.workers)
    step = math.ceil(args.games / workers)
    tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims) for lo in range(0, args.games, step)]
    if workers > 1:
        with mp.Pool(processes=workers) as pool:
            parts = pool.map(_play_chunk, tasks)
    else:
        parts = [_play_chunk(t) for t in tasks]
    data = np.vstack([p for p in parts if len(p)])
    cards, points, colored, gold, reserved, y = [data[:, i] for i in range(6)]
    total_gems = colored + gold
    print(f"[feat-diag] {args.games} S-vs-S games @ sims={args.sims} -> {len(data)} positions  "
          f"({time.time()-t0:.0f}s)", flush=True)
    print("   reserved-count distribution: " +
          "  ".join(f"{v}:{int((np.minimum(reserved,3)==v).sum())}" for v in range(4)) +
          f"   (mean {reserved.mean():.2f})", flush=True)
    print("   gold distribution: " +
          "  ".join(f"{v}:{int((np.minimum(gold,3)==v).sum())}" for v in range(4)) +
          f"   (mean {gold.mean():.2f})", flush=True)

    # 1) model on the TABLE's inputs, then residual-vs-omitted-axis
    Xt = np.column_stack([cards, points, total_gems])
    _, r2_t, resid_t = _fit(Xt, y)
    print(f"\n[1] linear on TABLE inputs [cards, points, total_gems]: R^2 = {r2_t:.4f}", flush=True)
    _bucket_residuals(resid_t, reserved, "reserved")
    _bucket_residuals(resid_t, gold, "gold")

    # 2) full model -- coefficients + extra R^2
    Xf = np.column_stack([cards, points, colored, gold, reserved])
    beta, r2_f, _ = _fit(Xf, y)
    names = ["cards", "points", "colored_gem", "gold", "reserved"]
    print(f"\n[2] full linear [cards, points, colored_gems, gold, reserved]: R^2 = {r2_f:.4f}  "
          f"(dR^2 = {r2_f - r2_t:+.4f})", flush=True)
    print("   coefficients (turns-left per unit):", flush=True)
    for nm, b in zip(names, beta[:5]):
        print(f"     {nm:12} {b:+6.3f}", flush=True)
    print(f"   --> gold is worth {beta[3]-beta[2]:+.3f} turns vs a colored gem "
          f"(negative = gold advances you MORE); reserved coef {beta[4]:+.3f} turns/card", flush=True)


if __name__ == "__main__":
    main()
