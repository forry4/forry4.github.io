"""Decisive paired test: is ANY tuning change real on fresh seeds?

The 300-seed combo run showed the search's range(80) baseline (0.688) was
seed-overfit -- true win rate vs the A/B/C/C2 mix is ~0.56 and nothing cleared
significance. But that run fixed W_POINTS=2.5 as its baseline, so it never tested
the one "validated" change (2.0 -> 2.5) on fresh seeds. This does, PAIRED: every
config plays the SAME 600 fresh seeds with deterministic per-game opponent
rollouts, so config_a vs config_b is a per-seed paired comparison (each seed is
the same game) -- far more powerful than comparing two independent CIs. Reports
each config's win rate AND the paired mean difference vs the W_POINTS=2.0 default
(the currently shipped value) with a paired SE / z.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
from concurrent.futures import ProcessPoolExecutor

OPP_NAMES = ["A", "B", "C", "C2"]
SEEDS = list(range(2000, 2600))   # 600 fresh seeds, disjoint from all prior runs

BEST = {'W_POINTS': 2.0, 'W_EFFICIENCY': 5.0, 'W_ENGINE': 1.0, 'W_NOBLE': 3.0,
        'W_TEMPO': 0.3, 'BUY_FLOOR': 0.5, 'RESERVE_BASE': 4.0, 'RESERVE_STEP': 1.5,
        'RESERVE_GAP': 2.0, 'OPENING_PLY': 8, 'MIN_BUILD_PATH': 3,
        'PTS_STAGE_GAIN': 0.5, 'ENG_STAGE_DECAY': 0.7, 'ENGINE_STAGE_DIV': 10.0,
        'ENG_DECAY_RATE': 0.5, 'TAKE_TEMPO': 0.6}

CONFIGS = {
    "W_POINTS 2.0 (shipped)":     {},
    "W_POINTS 2.5":               {"W_POINTS": 2.5},
    "W_POINTS 2.5 + ESD 0.9":     {"W_POINTS": 2.5, "ENG_STAGE_DECAY": 0.9},
    "W_POINTS 2.5 + 3-combo":     {"W_POINTS": 2.5, "W_ENGINE": 1.5,
                                   "W_EFFICIENCY": 4.0, "W_TEMPO": 0.45},
}


def _outcomes(cfg):
    """Per-seed outcome vector (1 win / 0.5 draw / 0 loss) for paired stats."""
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    for k, v in cfg.items():
        setattr(H, k, v)
    opps = [_load_opp_weights(n) for n in OPP_NAMES]
    out = []
    for g in SEEDS:
        random.seed(g * 7919 + 13)
        opp = opps[g % len(opps)]
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opp, 1))
        out.append(1.0 if s.winner == v4 else (0.5 if s.winner == E.WIN_DRAW else 0.0))
    return out


def eval_job(job):
    label, overrides = job
    cfg = dict(BEST)
    cfg.update(overrides)
    return label, _outcomes(cfg)


def wilson(p, n, z=1.96):
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


if __name__ == "__main__":
    jobs = list(CONFIGS.items())
    n = len(SEEDS)
    print(f"paired confirm: {len(jobs)} configs x {n} fresh games vs mix "
          f"{'/'.join(OPP_NAMES)}", flush=True)
    res = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for label, vec in ex.map(eval_job, jobs):
            res[label] = vec
            p = sum(vec) / n
            lo, hi = wilson(p, n)
            print(f"  {p:.3f}  [{lo:.3f}, {hi:.3f}]  {label}", flush=True)

    ref = "W_POINTS 2.0 (shipped)"
    rv = res[ref]
    print(f"\n==== paired diff vs {ref} (p={sum(rv)/n:.3f}) ====", flush=True)
    for label, vec in res.items():
        if label == ref:
            continue
        diffs = [a - b for a, b in zip(vec, rv)]
        md = sum(diffs) / n
        var = sum((x - md) ** 2 for x in diffs) / (n - 1)
        se = math.sqrt(var / n)
        z = md / se if se > 0 else 0.0
        wins = sum(1 for x in diffs if x > 0)
        losses = sum(1 for x in diffs if x < 0)
        verdict = "SIGNIFICANT" if abs(z) >= 1.96 else "not sig (noise)"
        print(f"  {label}: paired d={md:+.4f}  z={z:+.2f}  "
              f"({wins} seeds better / {losses} worse) -> {verdict}", flush=True)
