"""One-shot sensitivity table around the current best (W_POINTS=2.5).

Answers "what do the OTHER params do?" — the running search only logs configs
that CLEAR the accept bar, so sub-threshold gradients are invisible. This sweeps
every param +/- one step from the best and prints the resulting fitness vs the
SAME A/B/C/C2 mix on the SAME 80 paired seeds, so each number is directly
comparable to the best's 0.688. Parallel across cores (pure-Python engine games,
no BLAS) so it finishes in a few minutes. Does NOT touch the deployed bot.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import random
from concurrent.futures import ProcessPoolExecutor

OPP_NAMES = ["A", "B", "C", "C2"]
SEEDS = list(range(80))

BEST = {'W_POINTS': 2.5, 'W_EFFICIENCY': 5.0, 'W_ENGINE': 1.0, 'W_NOBLE': 3.0,
        'W_TEMPO': 0.3, 'BUY_FLOOR': 0.5, 'RESERVE_BASE': 4.0, 'RESERVE_STEP': 1.5,
        'RESERVE_GAP': 2.0, 'OPENING_PLY': 8, 'MIN_BUILD_PATH': 3,
        'PTS_STAGE_GAIN': 0.5, 'ENG_STAGE_DECAY': 0.7, 'ENGINE_STAGE_DIV': 10.0,
        'ENG_DECAY_RATE': 0.5, 'TAKE_TEMPO': 0.6}

# name: (step, lo, hi, is_int) — same grid as the search
PARAMS = {
    "W_POINTS":         (0.5, 0.5, 6.0, False),
    "W_EFFICIENCY":     (1.0, 1.0, 12.0, False),
    "W_ENGINE":         (0.5, 0.0, 4.0, False),
    "W_NOBLE":          (1.0, 0.0, 8.0, False),
    "W_TEMPO":          (0.15, 0.0, 1.5, False),
    "BUY_FLOOR":        (0.25, 0.0, 2.0, False),
    "RESERVE_BASE":     (1.0, 1.0, 8.0, False),
    "RESERVE_STEP":     (0.75, 0.0, 4.0, False),
    "RESERVE_GAP":      (1.0, 0.0, 5.0, False),
    "OPENING_PLY":      (2, 0, 16, True),
    "MIN_BUILD_PATH":   (1, 1, 6, True),
    "PTS_STAGE_GAIN":   (0.25, 0.0, 1.5, False),
    "ENG_STAGE_DECAY":  (0.2, 0.0, 1.0, False),
    "ENGINE_STAGE_DIV": (2.0, 4.0, 20.0, False),
    "ENG_DECAY_RATE":   (0.25, 0.0, 1.5, False),
    "TAKE_TEMPO":       (0.3, 0.0, 2.0, False),
}


def _fitness(cfg):
    # imports inside so each spawned worker sets up its own module state
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
    label, cfg = job
    return label, _fitness(cfg)


def build_jobs():
    jobs = [("baseline  W_POINTS=2.5", dict(BEST))]
    for name, (step, lo, hi, is_int) in PARAMS.items():
        for delta in (step, -step):
            nv = BEST[name] + delta
            if is_int:
                nv = int(round(nv))
            if nv < lo or nv > hi or nv == BEST[name]:
                continue
            cfg = dict(BEST)
            cfg[name] = nv
            jobs.append((f"{name:16s} {BEST[name]} -> {nv}", cfg))
    return jobs


if __name__ == "__main__":
    jobs = build_jobs()
    print(f"sensitivity sweep: {len(jobs)} configs x {len(SEEDS)} games "
          f"vs mix {'/'.join(OPP_NAMES)}", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        for label, f in ex.map(eval_job, jobs):
            results.append((label, f))
            print(f"  {f:.3f}  {label}", flush=True)
    base = next(f for lbl, f in results if lbl.startswith("baseline"))
    print("\n==== sorted by fitness (baseline = %.3f) ====" % base, flush=True)
    for label, f in sorted(results, key=lambda x: -x[1]):
        mark = "  <-- baseline" if label.startswith("baseline") else \
               ("  +" if f > base else ("   " if f == base else "  -"))
        print(f"  {f:.3f}  ({f-base:+.3f}){mark}  {label}", flush=True)
