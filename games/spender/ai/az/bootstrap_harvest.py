"""Harvest S's (base features, V_search, visit-policy, outcome) to BOOTSTRAP a net toward S.

The retrain bet is self-play BEYOND S. To avoid variant-Z's from-scratch failure we start the net at
~S strength by distilling S's search outputs, then self-play from there. This records, per S-vs-S PLAY
position: F.encode(s) [base 305], V_search (root sum W/N), the visit policy pi over N_ACTIONS, the legal
mask, the acting seat; and per game the outcome. The net (net.SpenderNet) trains value<-V_search (and/or
outcome) + policy<-pi; then we arena net-vs-S (the precondition gate: can a base-feature net hold S?).

Reuses vsearch's Search/_expand exactly so the targets are S's actual search distribution.

Usage:
  python -m games.spender.ai.az.bootstrap_harvest --games 400 --sims 256 --workers 12 \
      --out games/spender/ai/az/bootstrap_cache.npz
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
from . import features as F        # noqa: E402
from . import vsearch              # noqa: E402
from .distill_features import feat_enriched  # noqa: E402
from .mcts import Search           # noqa: E402

NA = E.N_ACTIONS


def _harvest_chunk(args):
    seed_base, lo, hi, sims, enriched = args
    _feat = (lambda st, seat: feat_enriched(st, seat)) if enriched \
        else (lambda st, seat: F.encode(st).astype(np.float32))
    X, V, PI, MASK, SEAT, GID = [], [], [], [], [], []
    for i in range(lo, hi):
        vsearch._RNG = random.Random(seed_base + i)
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
                    n = np.asarray(search.root.N, dtype=np.float64)
                    tot = n.sum()
                    if tot > 0:
                        pi = (n / tot).astype(np.float32)
                        vsearch_val = float(sum(search.root.W) / tot)
                        mask = np.zeros(NA, dtype=bool)
                        for a in legal:
                            mask[a] = True
                        recs.append((_feat(s, seat), vsearch_val, pi, mask, seat, i))
                        E.apply(s, int(n.argmax()))
                        steps += 1
                        continue
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
            steps += 1
        if s.phase == E.OVER and s.winner != E.WIN_DRAW:
            for feats, vsv, pi, mask, seat, gid in recs:
                X.append(feats); V.append(vsv); PI.append(pi); MASK.append(mask)
                SEAT.append(1.0 if s.winner == seat else 0.0)   # store OUTCOME (won) in SEAT slot
                GID.append(gid)
    if not X:
        from .distill_features import ENRICHED_F
        w = ENRICHED_F if enriched else F.N_FEATURES
        return (np.zeros((0, w), np.float32), np.zeros(0, np.float32),
                np.zeros((0, NA), np.float32), np.zeros((0, NA), bool),
                np.zeros(0, np.float32), np.zeros(0, np.int32))
    return (np.asarray(X, np.float32), np.asarray(V, np.float32), np.asarray(PI, np.float32),
            np.asarray(MASK, bool), np.asarray(SEAT, np.float32), np.asarray(GID, np.int32))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--sims", type=int, default=256)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=240_000_000)
    ap.add_argument("--out", default="games/spender/ai/az/bootstrap_cache.npz")
    ap.add_argument("--enriched", action="store_true",
                    help="record enriched features (base + per-card H3 TEPC + v_state comps + turns)")
    args = ap.parse_args()

    t0 = time.time()
    workers = max(1, args.workers)
    step = math.ceil(args.games / workers)
    tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims, args.enriched)
             for lo in range(0, args.games, step)]
    pool = mp.Pool(workers) if workers > 1 else None
    try:
        parts = pool.map(_harvest_chunk, tasks) if pool else [_harvest_chunk(t) for t in tasks]
    finally:
        if pool is not None:
            pool.close(); pool.join()
    X = np.concatenate([p[0] for p in parts])
    Vv = np.concatenate([p[1] for p in parts])
    PI = np.concatenate([p[2] for p in parts])
    MASK = np.concatenate([p[3] for p in parts])
    WON = np.concatenate([p[4] for p in parts])
    GID = np.concatenate([p[5] for p in parts])
    np.savez(args.out, X=X, V=Vv, PI=PI, MASK=MASK, WON=WON, GID=GID)
    print(f"[bootstrap-harvest] {len(X)} positions from {args.games} S-vs-S games @ sims={args.sims} "
          f"({time.time()-t0:.0f}s) -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
