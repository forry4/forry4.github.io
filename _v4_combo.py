"""Controlled combo validation around the W_POINTS=2.5 best.

The 80-game sensitivity sweep flagged W_ENGINE 1.0->1.5 (+0.037) plus three
+0.012 nudges (W_EFFICIENCY->4.0, W_TEMPO->0.45, ENG_STAGE_DECAY->0.9). At 80
games SE ~= 0.05, so those are inside the noise band. This re-tests the leads
and their COMBINATIONS on 300 FRESH seeds (disjoint from the search's range(80)
and holdout) with per-game global-RNG seeding, so the opponent's 1-iter MCTS
rollouts are deterministic and each config's number is a clean function of the
config -- not worker order or luck. Prints win rate + Wilson 95% CI vs baseline.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
from concurrent.futures import ProcessPoolExecutor

OPP_NAMES = ["A", "B", "C", "C2"]
SEEDS = list(range(1000, 1300))   # 300 fresh seeds, disjoint from search/holdout

BEST = {'W_POINTS': 2.5, 'W_EFFICIENCY': 5.0, 'W_ENGINE': 1.0, 'W_NOBLE': 3.0,
        'W_TEMPO': 0.3, 'BUY_FLOOR': 0.5, 'RESERVE_BASE': 4.0, 'RESERVE_STEP': 1.5,
        'RESERVE_GAP': 2.0, 'OPENING_PLY': 8, 'MIN_BUILD_PATH': 3,
        'PTS_STAGE_GAIN': 0.5, 'ENG_STAGE_DECAY': 0.7, 'ENGINE_STAGE_DIV': 10.0,
        'ENG_DECAY_RATE': 0.5, 'TAKE_TEMPO': 0.6}

# overrides layered on BEST
CONFIGS = {
    "baseline Wp2.5":            {},
    "ENGINE 1.5":                {"W_ENGINE": 1.5},
    "ENGINE 2.0":                {"W_ENGINE": 2.0},
    "EFFIC 4.0":                 {"W_EFFICIENCY": 4.0},
    "TEMPO 0.45":                {"W_TEMPO": 0.45},
    "ENG_STAGE_DECAY 0.9":       {"ENG_STAGE_DECAY": 0.9},
    "ENG1.5 + EFFIC4.0":         {"W_ENGINE": 1.5, "W_EFFICIENCY": 4.0},
    "ENG1.5 + TEMPO0.45":        {"W_ENGINE": 1.5, "W_TEMPO": 0.45},
    "ENG1.5 + EFFIC4.0 + TEMPO0.45":
        {"W_ENGINE": 1.5, "W_EFFICIENCY": 4.0, "W_TEMPO": 0.45},
    "all 4 positives":
        {"W_ENGINE": 1.5, "W_EFFICIENCY": 4.0, "W_TEMPO": 0.45,
         "ENG_STAGE_DECAY": 0.9},
}


def _fitness(cfg):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    for k, v in cfg.items():
        setattr(H, k, v)
    opps = [_load_opp_weights(n) for n in OPP_NAMES]
    w = d = 0
    for g in SEEDS:
        random.seed(g * 7919 + 13)      # deterministic opponent rollouts per game
        opp = opps[g % len(opps)]
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opp, 1))
        if s.winner == v4:
            w += 1
        elif s.winner == E.WIN_DRAW:
            d += 1
    return (w + 0.5 * d) / len(SEEDS)


def eval_job(job):
    label, overrides = job
    cfg = dict(BEST)
    cfg.update(overrides)
    return label, _fitness(cfg)


def wilson(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


if __name__ == "__main__":
    jobs = list(CONFIGS.items())
    print(f"combo validation: {len(jobs)} configs x {len(SEEDS)} fresh games "
          f"vs mix {'/'.join(OPP_NAMES)} (SE ~= {0.5/math.sqrt(len(SEEDS)):.3f})",
          flush=True)
    results = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for label, f in ex.map(eval_job, jobs):
            results[label] = f
            lo, hi = wilson(f, len(SEEDS))
            print(f"  {f:.3f}  [{lo:.3f}, {hi:.3f}]  {label}", flush=True)
    base = results["baseline Wp2.5"]
    print(f"\n==== sorted (baseline = {base:.3f}) ====", flush=True)
    for label, f in sorted(results.items(), key=lambda x: -x[1]):
        lo, hi = wilson(f, len(SEEDS))
        sig = "  SIG" if lo > base else ("" if f <= base else "  (overlaps)")
        print(f"  {f:.3f}  ({f-base:+.3f})  [{lo:.3f}, {hi:.3f}]{sig}  {label}",
              flush=True)
