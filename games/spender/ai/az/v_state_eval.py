"""Offline discrimination test for V(state) — the Phase-0 leaf-quality gate.

Two modes:

--teacher H3 (default, cheap): harvest every PLAY position from H3-vs-panel games, compute
  ``v_state.value(s, to_move)`` live, label by whether the to-move seat eventually WON (+ final
  margin). Reports sign(V) accuracy, a point-diff baseline, and corr(V, margin). Catches a BROKEN
  V (acc < ~0.6 or below baseline). A static V plateauing ~0.65 is EXPECTED — its job is to be a
  good search LEAF, not a standalone predictor.

--teacher S (the THREE-WAY diagnostic): play S-vs-S games (search-driven), and at every PLAY
  snapshot record THREE things from the mover's perspective:
    * V_static = v_state.value(s)              -- the cheap leaf
    * V_search = sum(root.W)/sum(root.N)        -- the search-backed value (root value of the same
                                                   search that picks the move; in [-1,1])
    * outcome  = did this seat eventually win   -- strong-play ground truth (+ final margin)
  Then it decomposes which lever raises strength (the documented Path-C gate):
    * V_static ~= V_search, both modest vs outcome -> the LEAF is the ceiling; search can't fix a
      biased leaf -> structural feature work / fresh net (NOT distilling THIS V).
    * V_search clearly beats V_static vs outcome    -> lookahead extracts signal the leaf misses
      -> Path C (distill V+search into a numpy net for deeper search) pays.
    * V_search WORSE than V_static                   -> search adds noise with this leaf -> fix the
      leaf before spending on depth.
  Metrics: sign accuracy, AUC, and Brier (calibration) of each vs outcome; their agreement
  (corr, mean|diff|); and corr(V, final margin). AUC/Brier "closer to outcome" is the decider.

Snapshots within a game share an outcome (correlated) -> the effective N for the AUC *difference*
is ~#games, not #snapshots; keep --games healthy. Parallel; spawn-safe (no pickled modules).

Usage:
    python -m games.spender.ai.az.v_state_eval --teacher S --games 240 --sims 256 --workers 12
    python -m games.spender.ai.az.v_state_eval --teacher H3 --games 200 --opps H3,H2,H2N,H2R
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
from . import vsearch
from .h3_vs_h2 import OPPONENTS
from .mcts import Search

OPP = {**OPPONENTS, "H3": H3}   # {H, H2, H2N, H2R} + greedy H3


# ─── teacher H3 (cheap static-V discrimination) ──────────────────────────────────

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
    return _pearson([r[0] for r in rows], [r[2] for r in rows])


def _run_h3(args, opps):
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
    print(f"[v_state_eval H3] {len(rows)} positions from {args.games}x{len(opps)} games  ({dt:.0f}s)")
    print(f"  sign(V) accuracy (all)        : {acc_all:.4f}  (N={n_all})")
    print(f"  sign(V) accuracy (|V|>=0.2)   : {acc_conf:.4f}  (N={n_conf})")
    print(f"  baseline sign(point-diff) acc : {_baseline_accuracy(rows):.4f}")
    print(f"  corr(V, final margin)         : {_corr(rows):.4f}")


# ─── teacher S (three-way leaf-quality diagnostic) ───────────────────────────────

def _harvest_chunk_S(args):
    """Play S-vs-S games [lo, hi); at every multi-choice PLAY snapshot record
    (V_static, V_search, seat, point_diff). One search per PLAY move (it both picks the move and
    yields the root value), so static + search + outcome come from a single pass. Picklable."""
    seed_base, lo, hi, sims = args
    rows = []
    for i in range(lo, hi):
        s = E.new_game(random.Random(seed_base + i))
        recs = []
        steps = 0
        while s.phase != E.OVER and steps < 400:
            if s.phase == E.PLAY:
                legal = E.legal_actions(s)
                if len(legal) > 1:
                    seat = s.turn
                    search = Search(s, vsearch._RNG, c_puct=vsearch.C_PUCT,
                                    add_noise=False, leaf_state=True)
                    for _ in range(sims):
                        vsearch._expand(search)
                    tot = sum(search.root.N)
                    v_search = (sum(search.root.W) / tot) if tot else 0.0
                    v_static = v_state.value(s, seat)
                    recs.append((v_static, v_search, seat, s.points[seat] - s.points[1 - seat]))
                    E.apply(s, max(legal, key=lambda a: search.root.N[a]))
                    steps += 1
                    continue
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))   # single-legal / discard / noble
            steps += 1
        if s.phase == E.OVER and s.winner != E.WIN_DRAW:
            for v_static, v_search, seat, pdiff in recs:
                won = 1.0 if s.winner == seat else 0.0
                margin = float(s.points[seat] - s.points[1 - seat])
                rows.append((v_static, v_search, won, margin, float(pdiff)))
    return rows


def _auc(scores, labels):
    """ROC-AUC of continuous `scores` against binary `labels` (Mann-Whitney, tie-averaged ranks)."""
    data = sorted(zip(scores, labels), key=lambda t: t[0])
    n = len(data)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and data[j][0] == data[i][0]:
            j += 1
        avg = (i + j - 1) / 2.0 + 1.0       # 1-based average rank for the tie block
        for k in range(i, j):
            ranks[k] = avg
        i = j
    n_pos = sum(1 for _s, l in data if l > 0.5)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    sum_pos = sum(r for r, (_s, l) in zip(ranks, data) if l > 0.5)
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _sign_acc(scores, labels):
    n = len(scores)
    if not n:
        return 0.0
    c = 0.0
    for v, w in zip(scores, labels):
        if v == 0.0:
            c += 0.5
        elif (v > 0.0) == (w > 0.5):
            c += 1.0
    return c / n


def _brier(scores, labels):
    """Mean squared error of p=(V+1)/2 vs the win label — calibration + discrimination, lower=better."""
    n = len(scores)
    return sum(((v + 1.0) / 2.0 - w) ** 2 for v, w in zip(scores, labels)) / n if n else 0.0


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0.0 and syy > 0.0 else 0.0


def _run_S(args):
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    t0 = time.time()
    rows = []
    try:
        if pool is None:
            rows = _harvest_chunk_S((args.seed0, 0, args.games, args.sims))
        else:
            step = math.ceil(args.games / workers)
            tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims)
                     for lo in range(0, args.games, step)]
            for part in pool.map(_harvest_chunk_S, tasks):
                rows += part
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    dt = time.time() - t0
    vst = [r[0] for r in rows]
    vse = [r[1] for r in rows]
    won = [r[2] for r in rows]
    marg = [r[3] for r in rows]
    pdiff = [r[4] for r in rows]
    winrate = sum(won) / len(won) if won else 0.0

    auc_st, auc_se, auc_bl = _auc(vst, won), _auc(vse, won), _auc(pdiff, won)
    print(f"[v_state_eval S] {len(rows)} PLAY snapshots from {args.games} S-vs-S games "
          f"@ sims={args.sims}  ({dt:.0f}s)   harvest winrate(mover)={winrate:.3f}")
    print(f"  {'':16} {'sign-acc':>9} {'AUC':>7} {'Brier':>7}   (vs eventual outcome)")
    print(f"  {'V_static (leaf)':16} {_sign_acc(vst, won):>9.4f} {auc_st:>7.4f} {_brier(vst, won):>7.4f}")
    print(f"  {'V_search (root)':16} {_sign_acc(vse, won):>9.4f} {auc_se:>7.4f} {_brier(vse, won):>7.4f}")
    print(f"  {'point-diff base':16} {'':>9} {auc_bl:>7.4f}")
    print(f"  agreement: corr(V_static,V_search)={_pearson(vst, vse):.4f}  "
          f"mean|diff|={sum(abs(a - b) for a, b in zip(vst, vse)) / len(rows):.4f}")
    print(f"  corr(V_static, margin)={_pearson(vst, marg):.4f}   "
          f"corr(V_search, margin)={_pearson(vse, marg):.4f}")

    d_auc = auc_se - auc_st
    bri_st, bri_se = _brier(vst, won), _brier(vse, won)
    if d_auc > 0.03 and bri_se < bri_st:
        verdict = ("SEARCH extracts signal the leaf misses (AUC +%.3f, lower Brier) -> Path C "
                   "(distill V+search into a numpy net for DEEPER search) is the lever." % d_auc)
    elif abs(d_auc) <= 0.02:
        verdict = ("search ~= leaf (dAUC %.3f) -> the LEAF is the ceiling; a biased leaf can't be "
                   "fixed by more search -> structural feature work / fresh net, NOT distilling THIS "
                   "V. Both AUC ~%.2f." % (d_auc, auc_st))
    elif d_auc < -0.03:
        verdict = ("search is NOISIER than the leaf (dAUC %.3f) -> fix the leaf before spending on "
                   "depth." % d_auc)
    else:
        verdict = "marginal/mixed (dAUC %.3f) -> inconclusive; raise --games or --sims." % d_auc
    print(f"  VERDICT: {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", choices=["H3", "S"], default="H3")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--sims", type=int, default=256, help="search budget per PLAY move (teacher S)")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--opps", default="H3,H2,H2N,H2R", help="teacher H3 only")
    ap.add_argument("--seed0", type=int, default=None)
    ap.add_argument("--step", type=int, default=1_000_000)
    args = ap.parse_args()

    if args.teacher == "S":
        if args.seed0 is None:
            args.seed0 = 60_000_000
        _run_S(args)
    else:
        if args.seed0 is None:
            args.seed0 = 20_000_000
        _run_h3(args, args.opps.split(","))


if __name__ == "__main__":
    main()
