"""Arena: a net (numpy PUCT via infer_np) vs variant S (vsearch) -- the bootstrap PRECONDITION gate.

Can a base-feature net distilled from S actually MATCH S? If net-vs-S >= ~0.45, the net holds S and
self-play-beyond-S has a starting point; if it's well below, the base-feature net can't represent S
(features wall) and the bet starts behind. Paired CRN: each board played both seat assignments, with
the determinization RNGs reset per game so the two sides see the same shuffles.

The net moves via mcts.Search.run(evaluate, sims) (determinized PUCT on base F.encode features, same as
production net serving); S moves via vsearch.choose_action at matched sims.

Usage:
  python -m games.spender.ai.az.net_vs_s --npz games/spender/ai/az/checkpoints_bootstrap/az_bootstrap.npz \
      --n 120 --sims 160 --workers 12
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

import numpy as np                    # noqa: E402

from . import engine as E              # noqa: E402
from . import vsearch                  # noqa: E402
from .distill_features import feat_enriched  # noqa: E402
from .infer_np import load_evaluator   # noqa: E402
from .mcts import Search               # noqa: E402
from .vsearch_camp import wilson_ci    # noqa: E402

_EVAL = None
_NPZ = None
_ENRICHED = False


def _net_move_impl(s, rng, sims):
    if not _ENRICHED:
        search = Search(s, rng, add_noise=False)      # base-feature PUCT (leaf_state=False)
        visits = search.run(_EVAL, sims)
        return max(E.legal_actions(s), key=lambda a: visits[a])
    # enriched-feature PUCT: compute feat_enriched at each leaf and feed the net (like vsearch._expand)
    search = Search(s, rng, add_noise=False, leaf_state=True)
    for _ in range(sims):
        req = search.leaf_batch()
        if req is None:
            continue
        leaf_s, mask = req
        f = feat_enriched(leaf_s, leaf_s.turn)[None, :].astype(np.float32)
        probs, value = _EVAL(f, mask[None, :])
        search.apply_evals(probs[0], float(value[0]))
    return max(E.legal_actions(s), key=lambda a: search.root.N[a])


def _play(net_seat, seed, sims):
    global _EVAL
    if _EVAL is None:
        _EVAL = load_evaluator(_NPZ)
    rng = random.Random(seed)
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(400):
        if s.phase == E.OVER:
            break
        if s.turn == net_seat:
            a = _net_move_impl(s, rng, sims)
        else:
            a = vsearch.choose_action(s, s.turn, sims=sims)
        E.apply(s, a)
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == net_seat else 0.0


def _chunk(args):
    npz, seed_base, lo, hi, sims, enriched = args
    global _NPZ, _ENRICHED
    _NPZ = npz
    _ENRICHED = enriched
    tot = 0.0
    for g in range(lo, hi):
        tot += _play(0, seed_base + g, sims)
        tot += _play(1, seed_base + g, sims)
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", default="games/spender/ai/az/checkpoints_bootstrap/az_bootstrap.npz")
    ap.add_argument("--n", type=int, default=120, help="paired trials (=2n games)")
    ap.add_argument("--sims", type=int, default=160)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=250_000_000)
    ap.add_argument("--enriched", action="store_true",
                    help="net uses enriched features (feat_enriched per leaf) instead of base F.encode")
    args = ap.parse_args()

    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    t0 = time.time()
    step = math.ceil(args.n / workers)
    tasks = [(args.npz, args.seed0, lo, min(lo + step, args.n), args.sims, args.enriched)
             for lo in range(0, args.n, step)]
    try:
        tot = sum(pool.map(_chunk, tasks)) if pool else sum(_chunk(t) for t in tasks)
    finally:
        if pool is not None:
            pool.close(); pool.join()
    wr = tot / (2 * args.n)
    lo, hi = wilson_ci(wr, 2 * args.n)
    gate = "HOLDS S (proceed)" if wr >= 0.45 else "BELOW S (base-feature net can't hold S)"
    print(f"[net-vs-s] net-vs-S {wr:.4f} (95% CI {lo:.3f}-{hi:.3f})  N={2*args.n} sims={args.sims}  "
          f"[{time.time()-t0:.0f}s] -> {gate}", flush=True)


if __name__ == "__main__":
    main()
