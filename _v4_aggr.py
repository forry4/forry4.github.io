"""Sweep the three new H knobs (each off by default) on the current H base:
  - USE_CAP_AWARE        : cap-aware gem-taking (avoid overflow-then-discard)
  - USE_RESERVE_FOR_GOLD : reserve a 1-gold-short target for the wild gold (RESERVE_GOLD_MIN)
  - NOBLE_CONTEST        : boost a card's noble value by opponent closeness to the same noble
Each tested alone at a couple settings, plus all-on. Paired vs all-off on the SAME
fresh seeds vs the A/B/C/C2 mix. ASCII output only (cp1252).
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
SEEDS = list(range(65000, 66000))   # 1000 fresh seeds (disjoint from prior runs)
N_SHARDS = 16

CONFIGS = {
    "ref (all off)":         {},
    "cap_aware":             {"USE_CAP_AWARE": True},
    "reserve_gold m3":       {"USE_RESERVE_FOR_GOLD": True, "RESERVE_GOLD_MIN": 3.0},
    "reserve_gold m2":       {"USE_RESERVE_FOR_GOLD": True, "RESERVE_GOLD_MIN": 2.0},
    "noble_contest 0.5":     {"NOBLE_CONTEST": 0.5},
    "noble_contest 1.0":     {"NOBLE_CONTEST": 1.0},
    "all (cap+rfg3+nob.5)":  {"USE_CAP_AWARE": True, "USE_RESERVE_FOR_GOLD": True,
                              "NOBLE_CONTEST": 0.5},
}
REF = "ref (all off)"


def _run(overrides, seeds):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    # reset the three knobs to their defaults, then apply overrides (workers are reused)
    H.USE_CAP_AWARE = False
    H.USE_RESERVE_FOR_GOLD = False
    H.RESERVE_GOLD_MIN = 3.0
    H.NOBLE_CONTEST = 0.0
    for k, v in overrides.items():
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
    print(f"sweep aggressive knobs {list(CONFIGS)} x {len(SEEDS)} fresh games vs mix "
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
        print(f"  {p:.3f} [{lo:.3f},{hi:.3f}]  {label:22s} | {pieces}", flush=True)

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
