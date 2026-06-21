"""Tuning round 3 — the UNTESTED knobs (reserve / take / anti-hoard / structure).

Round 1 swept the value/stage weights; round 2 confirmed ENG_STAGE_DECAY=0.9 (now
the shipped baseline). Round 3 screens the reserve-policy, take-target, anti-hoard,
and opening/build-path thresholds that have never been A/B'd, plus a fine probe of
ENG_STAGE_DECAY=0.85 (between old 0.7 and new 0.9) to confirm 0.9 is the peak.

Screen @1000 fresh disjoint seeds; any |z|>=1.5 leaner gets a disjoint 2000+ confirm
before adoption (the replication bar that caught BUY_FLOOR's mirage). ASCII only.
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
SEEDS = list(range(76000, 77000))   # 1000 fresh seeds, disjoint from rounds 1-2 + confirm
N_SHARDS = 16

# (module, name) for every tunable touched -> reset target captured at runtime.
PARAMS = [
    ("H", "RESERVE_BASE"), ("H", "RESERVE_STEP"), ("H", "RESERVE_GAP"),
    ("H", "MIRAGE_STEEP"), ("H", "TOKEN_HOARD"), ("H", "MIN_BUILD_PATH"),
    ("H", "OPENING_PLY"), ("H", "TAKE_TEMPO"), ("H", "ENG_STAGE_DECAY"),
]

_P = {
    "RESERVE_BASE": [3.0, 5.0], "RESERVE_STEP": [1.0, 2.5], "RESERVE_GAP": [1.0, 3.0],
    "MIRAGE_STEEP": [4, 6], "TOKEN_HOARD": [7, 9], "MIN_BUILD_PATH": [2, 4],
    "OPENING_PLY": [6, 10], "TAKE_TEMPO": [0.4, 0.85],
    "ENG_STAGE_DECAY": [0.85],   # peak probe (current baseline = 0.9)
}

CONFIGS = {"ref": {}}
for name, vals in _P.items():
    for v in vals:
        CONFIGS[f"{name}={v}"] = {("H", name): v}
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
    print(f"tune round 3: {len(CONFIGS)} configs x {len(SEEDS)} seeds vs "
          f"{'/'.join(OPP_NAMES)}", flush=True)
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
            if done % 4000 < len(out):
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
        verdict = "<<< PROMISING (+)" if z >= 1.5 else ("(-)" if z <= -1.5 else "")
        print(f"  {label:24s}  {p:.3f}   {md:+.4f}  {z:+.2f}  {verdict}", flush=True)
