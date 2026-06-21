"""A/B: TTA_PAIR_ONCE (bank-aware single-color tempo) off vs on, plus a higher-N
re-check of the only positive-leaning aggressive knob (noble_contest 1.0).

TTA_PAIR_ONCE: take-2-same needs bank>=4, so a color pairs at most once -- the
greedy otherwise pairs every turn and under-rates 4-of-a-color (reads 2, really 3).
Paired vs the all-off base on the SAME fresh seeds vs the A/B/C/C2 mix. ASCII only.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

OPP_NAMES = ["A", "B", "C", "C2"]
SEEDS = list(range(66000, 67000))   # 1000 fresh seeds (disjoint from prior runs)
N_SHARDS = 16

# (V_overrides, H_overrides)
CONFIGS = {
    "ref (off)":          ({}, {}),
    "pair_once ON":       ({"TTA_PAIR_ONCE": True}, {}),
    "noble_contest 1.0":  ({}, {"NOBLE_CONTEST": 1.0}),
}
REF = "ref (off)"


def _run(overrides, seeds):
    v_ov, h_ov = overrides
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az import valuation as V
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    V.TTA_PAIR_ONCE = False                 # reset (workers are reused)
    H.NOBLE_CONTEST = 0.0
    for k, v in v_ov.items():
        setattr(V, k, v)
    for k, v in h_ov.items():
        setattr(H, k, v)
    opps = {n: _load_opp_weights(n) for n in OPP_NAMES}
    out = {}
    peropp = {n: [0.0, 0] for n in OPP_NAMES}
    for g in seeds:
        random.seed(g * 7919 + 13)
        on = OPP_NAMES[g % len(OPP_NAMES)]
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opps[on], 1))
        r = 1.0 if s.winner == v4 else (0.5 if s.winner == E.WIN_DRAW else 0.0)
        out[g] = r
        peropp[on][0] += r
        peropp[on][1] += 1
    return out, peropp


def eval_job(job):
    label, overrides, seeds = job
    out, peropp = _run(overrides, seeds)
    return label, out, peropp


def wilson(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


if __name__ == "__main__":
    shards = [SEEDS[i::N_SHARDS] for i in range(N_SHARDS)]
    jobs = [(label, ov, sh) for label, ov in CONFIGS.items() for sh in shards]
    print(f"A/B pair-once + noble_contest recheck x {len(SEEDS)} fresh games vs mix "
          f"{'/'.join(OPP_NAMES)}", flush=True)
    merged = {label: ({}, {n: [0.0, 0] for n in OPP_NAMES}) for label in CONFIGS}
    tot = len(CONFIGS) * len(SEEDS)
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(eval_job, job) for job in jobs]
        for fut in as_completed(futs):
            label, out, peropp = fut.result()
            merged[label][0].update(out)
            for nm in OPP_NAMES:
                merged[label][1][nm][0] += peropp[nm][0]
                merged[label][1][nm][1] += peropp[nm][1]
            done += len(out)
            el = time.time() - t0
            eta = el / done * (tot - done) if done else 0
            print(f"  [progress] {done}/{tot} games  ({el:.0f}s, ~{eta:.0f}s left)",
                  flush=True)

    n = len(SEEDS)
    print("\n=== overall + per-opponent winrate ===", flush=True)
    for label in CONFIGS:
        out, peropp = merged[label]
        p = sum(out.values()) / n
        lo, hi = wilson(p, n)
        pieces = "  ".join(f"{nm} {peropp[nm][0]/peropp[nm][1]:.3f}"
                           for nm in OPP_NAMES)
        print(f"  {p:.3f} [{lo:.3f},{hi:.3f}]  {label:20s} | {pieces}", flush=True)

    rv = merged[REF][0]
    print(f"\n=== paired diff vs '{REF}' ===", flush=True)
    for label in CONFIGS:
        if label == REF:
            continue
        cv = merged[label][0]
        diffs = [cv[g] - rv[g] for g in SEEDS]
        md = sum(diffs) / n
        var = sum((x - md) ** 2 for x in diffs) / (n - 1)
        se = math.sqrt(var / n) if var > 0 else 0.0
        z = md / se if se > 0 else 0.0
        better = sum(1 for x in diffs if x > 0)
        worse = sum(1 for x in diffs if x < 0)
        verdict = "SIGNIFICANT (+)" if z >= 1.96 else (
            "SIGNIFICANT (-)" if z <= -1.96 else "not sig (noise)")
        print(f"  {label}: mean diff {md:+.4f}  z={z:+.2f}  "
              f"({better} better / {worse} worse)  -> {verdict}", flush=True)
