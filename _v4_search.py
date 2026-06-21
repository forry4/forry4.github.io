"""Continuous heuristic weight/gate search (scratch, not committed).

Fitness = win rate vs greedy C2 (C2 @ 1 MCTS iter), PAIRED on a fixed seed set
(same games for every config, so a difference reflects the config, not luck).
A candidate must beat the best on the search set by MARGIN AND not regress on a
separate HOLDOUT set (overfit guard). Hill-climb each param +/- a step; on a
plateau, try random multi-param perturbations. Prints NEW BEST lines. Runs until
killed. Monkeypatches the in-process heuristic only -- does NOT touch the
deployed bot.
"""
import random
import time

from games.spender import main as inc
from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights

inc.USE_VALUE_LEAF = False
OPP_NAMES = ["A", "B", "C", "C2"]          # fight a MIX, not just C2 (robust strength)
OPPS = [_load_opp_weights(n) for n in OPP_NAMES]

# name: (default, step, lo, hi, is_int)
PARAMS = {
    "W_POINTS":         (2.0, 0.5, 0.5, 6.0, False),
    "W_EFFICIENCY":     (5.0, 1.0, 1.0, 12.0, False),
    "W_ENGINE":         (1.0, 0.5, 0.0, 4.0, False),
    "W_NOBLE":          (3.0, 1.0, 0.0, 8.0, False),
    "W_TEMPO":          (0.3, 0.15, 0.0, 1.5, False),
    "BUY_FLOOR":        (0.5, 0.25, 0.0, 2.0, False),
    "RESERVE_BASE":     (4.0, 1.0, 1.0, 8.0, False),
    "RESERVE_STEP":     (1.5, 0.75, 0.0, 4.0, False),
    "RESERVE_GAP":      (2.0, 1.0, 0.0, 5.0, False),
    "OPENING_PLY":      (8, 2, 0, 16, True),
    "MIN_BUILD_PATH":   (3, 1, 1, 6, True),
    "PTS_STAGE_GAIN":   (0.5, 0.25, 0.0, 1.5, False),
    "ENG_STAGE_DECAY":  (0.7, 0.2, 0.0, 1.0, False),
    "ENGINE_STAGE_DIV": (10.0, 2.0, 4.0, 20.0, False),
    "ENG_DECAY_RATE":   (0.5, 0.25, 0.0, 1.5, False),
    "TAKE_TEMPO":       (0.6, 0.3, 0.0, 2.0, False),
}
SEARCH_SEEDS = list(range(80))
HOLDOUT_SEEDS = list(range(5000, 5060))
MARGIN = 0.025      # beat best by >= this on the search set (avoid 1-game noise)
HOLD_TOL = 0.02     # holdout may dip at most this much vs the best's holdout


def apply_cfg(cfg):
    for k, v in cfg.items():
        setattr(H, k, v)


def fitness(cfg, seeds):
    apply_cfg(cfg)
    w = d = 0
    for g in seeds:
        opp = OPPS[g % len(OPPS)]           # cycle A/B/C/C2 by seed (paired)
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opp, 1))
        if s.winner == v4:
            w += 1
        elif s.winner == E.WIN_DRAW:
            d += 1
    return (w + 0.5 * d) / len(seeds)


def main():
    best = {k: v[0] for k, v in PARAMS.items()}
    t0 = time.time()
    best_fit = fitness(best, SEARCH_SEEDS)
    best_hold = fitness(best, HOLDOUT_SEEDS)
    print(f"START (vs mix {'/'.join(OPP_NAMES)}) fit {best_fit:.3f} hold "
          f"{best_hold:.3f} ({time.time()-t0:.0f}s/2evals) cfg {best}", flush=True)
    evals = 2
    rnd = 0
    while True:
        rnd += 1
        improved = False
        for name, (cur, step, lo, hi, is_int) in PARAMS.items():
            for delta in (step, -step):
                nv = best[name] + delta
                if is_int:
                    nv = int(round(nv))
                if nv < lo or nv > hi or nv == best[name]:
                    continue
                cand = dict(best)
                cand[name] = nv
                f = fitness(cand, SEARCH_SEEDS)
                evals += 1
                if f > best_fit + MARGIN:
                    h = fitness(cand, HOLDOUT_SEEDS)
                    evals += 1
                    if h >= best_hold - HOLD_TOL:
                        best, best_fit, best_hold = cand, f, h
                        improved = True
                        print(f"NEW BEST fit {best_fit:.3f} hold {best_hold:.3f} "
                              f"| {name}={nv} | evals {evals} {time.time()-t0:.0f}s",
                              flush=True)
                        print(f"   cfg {best}", flush=True)
        if not improved:
            print(f"[round {rnd}] coord plateau (fit {best_fit:.3f} hold "
                  f"{best_hold:.3f}); random perturbations | evals {evals} "
                  f"{time.time()-t0:.0f}s", flush=True)
            for _ in range(40):
                cand = dict(best)
                for name in random.sample(list(PARAMS), random.choice([2, 3])):
                    cur, step, lo, hi, is_int = PARAMS[name]
                    nv = best[name] + random.choice([-2, -1, 1, 2]) * step
                    if is_int:
                        nv = int(round(nv))
                    cand[name] = min(hi, max(lo, nv))
                f = fitness(cand, SEARCH_SEEDS)
                evals += 1
                if f > best_fit + MARGIN:
                    h = fitness(cand, HOLDOUT_SEEDS)
                    evals += 1
                    if h >= best_hold - HOLD_TOL:
                        best, best_fit, best_hold = cand, f, h
                        print(f"NEW BEST (perturb) fit {best_fit:.3f} hold "
                              f"{best_hold:.3f} | evals {evals} {time.time()-t0:.0f}s",
                              flush=True)
                        print(f"   cfg {best}", flush=True)
                        break


if __name__ == "__main__":
    main()
