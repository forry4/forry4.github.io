"""Tuning round 5 — FINAL. Decisive high-N resolution of the live candidates.

The campaign has shown ~everything is at its optimum except two related leaners
that reduce NON-points emphasis: W_EFFICIENCY=4.5 (stable +0.006, z grew 1.70->1.90
as N went 1k->2k = a real small effect just under the bar) and W_ENGINE=0.8
(+0.009, noisier, z=1.06). PTS_STAGE_GAIN=0.4 was a mirage (washed to 0.000@2000).

This final round runs 4000 disjoint seeds (z=1.90@2000 -> ~2.7@4000 if real) to:
  - map the W_EFFICIENCY optimum (4.0 / 4.25 / 4.5),
  - confirm W_ENGINE=0.8,
  - test the COMBINATION (do they stack or are they redundant? both shift weight
    off non-points factors, so they may overlap).
Whatever clears |z|>=1.96 is adopted as the final locked config. ASCII only.
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
SEEDS = list(range(82000, 86000))   # 4000 fresh seeds, disjoint from all prior runs
N_SHARDS = 24

PARAMS = [("H", "W_EFFICIENCY"), ("H", "W_ENGINE")]

CONFIGS = {
    "ref":                       {},
    "W_EFFICIENCY=4.0":          {("H", "W_EFFICIENCY"): 4.0},
    "W_EFFICIENCY=4.25":         {("H", "W_EFFICIENCY"): 4.25},
    "W_EFFICIENCY=4.5":          {("H", "W_EFFICIENCY"): 4.5},
    "W_ENGINE=0.8":              {("H", "W_ENGINE"): 0.8},
    "WEFF=4.5+WENG=0.8":         {("H", "W_EFFICIENCY"): 4.5, ("H", "W_ENGINE"): 0.8},
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
    print(f"tune round 5 (FINAL): {len(CONFIGS)} configs x {len(SEEDS)} seeds",
          flush=True)
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
            if done % 8000 < len(out):
                el = time.time() - t0
                print(f"  [progress] {done}/{tot}  ({el:.0f}s, "
                      f"~{el/done*(tot-done):.0f}s left)", flush=True)

    n = len(SEEDS)
    rv = merged[REF]
    print(f"\nbaseline winrate = {sum(rv.values())/n:.3f}  ({n} seeds, "
          f"ENG_STAGE_DECAY=0.9)\n", flush=True)
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
