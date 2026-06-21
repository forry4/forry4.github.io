"""Tuning round 2 — confirm round-1 directions at higher N (2000 fresh seeds).

Pushes BUY_FLOOR (the strongest lever) up to find its optimum, and re-tests the
mild positive leaners. Paired vs the unchanged baseline. Adopt only |z|>=1.96.
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
SEEDS = list(range(71000, 73000))   # 2000 fresh seeds (disjoint)
N_SHARDS = 16

PARAMS = [("H", "BUY_FLOOR"), ("H", "W_NOBLE"), ("H", "NOBLE_CONTRIB"),
          ("H", "ENG_STAGE_DECAY"), ("H", "PTS_STAGE_GAIN"), ("H", "W_COST")]

CONFIGS = {
    "ref":                 {},
    "BUY_FLOOR=0.7":       {("H", "BUY_FLOOR"): 0.7},
    "BUY_FLOOR=0.9":       {("H", "BUY_FLOOR"): 0.9},
    "BUY_FLOOR=1.1":       {("H", "BUY_FLOOR"): 1.1},
    "W_NOBLE=4.0":         {("H", "W_NOBLE"): 4.0},
    "NOBLE_CONTRIB=0.5":   {("H", "NOBLE_CONTRIB"): 0.5},
    "ENG_STAGE_DECAY=0.9": {("H", "ENG_STAGE_DECAY"): 0.9},
    "PTS_STAGE_GAIN=0.25": {("H", "PTS_STAGE_GAIN"): 0.25},
    "W_COST=0.6":          {("H", "W_COST"): 0.6},
}
REF = "ref"
_BASE = {}


def _run(overrides, seeds):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az import valuation as V
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    mods = {"H": H, "V": V}
    if not _BASE:
        for m, n in PARAMS:
            _BASE[(m, n)] = getattr(mods[m], n)
    for (m, n), v in _BASE.items():
        setattr(mods[m], n, v)
    for (m, n), v in overrides.items():
        setattr(mods[m], n, v)
    opps = {n: _load_opp_weights(n) for n in OPP_NAMES}
    out = {}
    for g in seeds:
        random.seed(g * 7919 + 13)
        on = OPP_NAMES[g % len(OPP_NAMES)]
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opps[on], 1))
        out[g] = 1.0 if s.winner == v4 else (0.5 if s.winner == E.WIN_DRAW else 0.0)
    return out


def eval_job(job):
    label, overrides, seeds = job
    return label, _run(overrides, seeds)


if __name__ == "__main__":
    shards = [SEEDS[i::N_SHARDS] for i in range(N_SHARDS)]
    jobs = [(label, ov, sh) for label, ov in CONFIGS.items() for sh in shards]
    print(f"tune round 2: {len(CONFIGS)} configs x {len(SEEDS)} seeds", flush=True)
    merged = {label: {} for label in CONFIGS}
    tot = len(CONFIGS) * len(SEEDS)
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(eval_job, job) for job in jobs]
        for fut in as_completed(futs):
            label, out = fut.result()
            merged[label].update(out)
            done += len(out)
            if done % 6000 < len(out):
                el = time.time() - t0
                print(f"  [progress] {done}/{tot}  ({el:.0f}s, "
                      f"~{el/done*(tot-done):.0f}s left)", flush=True)

    n = len(SEEDS)
    rv = merged[REF]
    print(f"\nbaseline winrate = {sum(rv.values())/n:.3f}  ({n} seeds)\n", flush=True)
    rows = []
    for label in CONFIGS:
        if label == REF:
            continue
        cv = merged[label]
        diffs = [cv[g] - rv[g] for g in SEEDS]
        md = sum(diffs) / n
        var = sum((x - md) ** 2 for x in diffs) / (n - 1)
        se = math.sqrt(var / n) if var > 0 else 0.0
        z = md / se if se > 0 else 0.0
        rows.append((z, md, label, sum(cv.values()) / n))
    rows.sort(reverse=True)
    print("config                      winrate   diff      z      verdict", flush=True)
    for z, md, label, p in rows:
        verdict = "<<< CONFIRMED (+)" if z >= 1.96 else ("(-)" if z <= -1.96 else "")
        print(f"  {label:24s}  {p:.3f}   {md:+.4f}  {z:+.2f}  {verdict}", flush=True)
