"""Coordinate-descent weight tuning for the v4 heuristic (variant H).

Screens single-variable perturbations of the kept tunables around their current
values, paired vs the unchanged baseline on the SAME fresh seeds vs the A/B/C/C2
mix. Reports each config's paired diff sorted by z. Promising hits (|z|>=1.96)
get confirmed at higher N in a separate run before adoption. ASCII only.

Params live on heuristic (H) or valuation (V); each config overrides ONE.
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
SEEDS = list(range(70000, 71000))   # 1000 fresh seeds
N_SHARDS = 16

# every tunable we touch, as (module, name) -> reset target captured at runtime.
PARAMS = [
    ("H", "W_POINTS"), ("H", "W_EFFICIENCY"), ("H", "W_ENGINE"), ("H", "W_NOBLE"),
    ("H", "W_TEMPO"), ("H", "W_COST"), ("H", "TAKE_TEMPO"), ("H", "W_GOLD_SPEND"),
    ("H", "BUY_FLOOR"), ("H", "NOBLE_CONTRIB"), ("H", "ENG_DECAY_RATE"),
    ("H", "PTS_STAGE_GAIN"), ("H", "ENG_STAGE_DECAY"), ("H", "ENGINE_STAGE_DIV"),
    ("V", "RESERVED_ENGINE_W"),
]

# label -> {(module,name): value}.  "ref" = all defaults.
_P = {
    "W_POINTS": [1.5, 2.5], "W_EFFICIENCY": [4.0, 6.5], "W_ENGINE": [0.6, 1.5],
    "W_NOBLE": [2.25, 3.75], "W_TEMPO": [0.2, 0.45], "W_COST": [0.25, 0.6],
    "TAKE_TEMPO": [0.4, 0.85], "W_GOLD_SPEND": [0.2, 0.6], "BUY_FLOOR": [0.3, 0.7],
    "NOBLE_CONTRIB": [0.2, 0.5], "ENG_DECAY_RATE": [0.3, 0.7], "PTS_STAGE_GAIN": [0.3, 0.7],
    "ENG_STAGE_DECAY": [0.5, 0.9], "ENGINE_STAGE_DIV": [7.0, 14.0],
}
_VMOD = {"RESERVED_ENGINE_W": "V"}
_P_V = {"RESERVED_ENGINE_W": [1.0, 1.25]}

CONFIGS = {"ref": {}}
for name, vals in _P.items():
    for v in vals:
        CONFIGS[f"{name}={v}"] = {("H", name): v}
for name, vals in _P_V.items():
    for v in vals:
        CONFIGS[f"{name}={v}"] = {("V", name): v}
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
    for (m, n), v in _BASE.items():            # reset to baseline (workers reused)
        setattr(mods[m], n, v)
    for (m, n), v in overrides.items():        # apply the single perturbation
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
    print(f"tune round: {len(CONFIGS)} configs x {len(SEEDS)} seeds vs "
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
    base_p = sum(rv.values()) / n
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
    print(f"\nbaseline winrate = {base_p:.3f}  ({n} seeds)\n", flush=True)
    print("config                      winrate   diff      z      verdict", flush=True)
    for z, md, label, p in rows:
        verdict = "<<< PROMISING (+)" if z >= 1.96 else (
            "(-)" if z <= -1.96 else "")
        print(f"  {label:24s}  {p:.3f}   {md:+.4f}  {z:+.2f}  {verdict}", flush=True)
