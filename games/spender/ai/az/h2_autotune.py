"""Autonomous H2 tuner -- PARALLEL coordinate-descent campaign, NO human input.

Strategy (the rigor learned the hard way this session, automated):
  * SELF-GATE screen: sweep every tunable vs the CURRENT best config (H2-vs-H2). A copy of
    yourself is an equally-strong opponent, so a delta measures the *change* sensitively
    (empty change -> ~0.5).
  * SELF-EXPLOIT GUARD: a change is adopted only if, on DISJOINT HOLDOUT seeds it was NOT
    screened on, it BOTH (a) beats the current config on the self-gate by >= VAL_MARGIN AND
    (b) does NOT regress vs H (the external yardstick) -- killing rock-paper-scissors wins.
  * COORDINATE DESCENT: adopt the single best validated change per round, re-screen against the
    new best (so interactions are handled), until a round yields no validated improvement.

Parallel: every match is independent, so they fan out over a process pool. Each worker applies
its own (config, override) per job, so a reused worker never carries stale state. The launching
process never mutates module globals (all matches run in workers) -> the committed source/in-memory
config is left untouched; nothing is written to disk.

Run:  python -m games.spender.ai.az.h2_autotune
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor

from . import heuristic2 as H   # noqa: F401  (ensures workers load the module graph)
from . import valuation2 as V   # noqa: F401
from .h2_tune import run_match, _capture_baseline, _apply_cfg

# Candidate values per tunable (current value is implicit -- skipped when it comes up).
SPACE = {
    "V.ENG_DECK_W":        [3.0, 4.0, 4.5, 5.5, 7.0],
    "V.ENG_TEMPO_SCALE":   [0.2, 0.25, 0.35, 0.4],
    "H.W_TEMPO":           [0.2, 0.3, 0.4, 0.6, 0.7],
    "H.W_GOLD":            [0.2, 0.3, 0.5, 0.6, 0.8],
    "H.W_GEM":             [0.1, 0.3, 0.4],
    "H.NOBLE_SCALE":       [2.5, 3.5, 4.0],
    "H.STAGE_K":           [6, 10, 12],
    "H.STAGE_FLOOR":       [0.15, 0.2, 0.35],
    "H.ENG_DECAY":         [0.2, 0.4, 0.5],
    "H.GOLD_TIEBREAK":     [0.1, 0.3],
    "H.CAP8_BUY_ABOVE":    [0.6, 1.0],
    "H.CAP9_BUY_ABOVE":    [0.3, 0.7],
    "V.ENG_DIV":           [6.0, 10.0, 12.0],
    "V.ENG_FLOOR":         [0.1, 0.35],
    "V.NOBLE_CLOSE_FLOOR": [0.35, 0.5],
    "V.GOLD_BANK_CAP":     [1, 3],
}

SCREEN_SEED = 700000       # 1 disjoint seed, fast screen
N_SCREEN = 1000
HOLDOUT_SEEDS = [800000, 840000, 880000]   # disjoint from screen + each other, for validation
N_VAL = 1500
FINAL_SEEDS = [950000, 970000, 990000]     # disjoint again, for the closing report
N_FINAL = 2000

SCREEN_THRESH = 0.012      # screen delta over current to bother validating
VAL_MARGIN = 0.005         # holdout self-gate must beat current by at least this
VSH_TOL = 0.010            # allowed vs-H slippage (guards self-exploits; small tolerance for noise)
MAX_ROUNDS = 6
WORKERS = max(1, min(10, (os.cpu_count() or 4) - 2))


def _pool_match(job):
    """Worker: apply the given full config, run ONE match, return its score. Self-contained per job
    (each job carries its own base config + override), so a reused worker never has stale state."""
    base_full, override, base_seed, n, opp = job
    _apply_cfg(base_full)
    return run_match(n, base_seed=base_seed, overrides=override, opp=opp, quiet=True)


def main():
    orig = _capture_baseline()
    best = dict(orig)            # full current config (mutated as we adopt; main process only reads)
    adopted = {}                 # the overrides relative to orig
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        pmap = lambda jobs: list(pool.map(_pool_match, jobs))
        print(f"[autotune] start ({WORKERS} workers). {len(SPACE)} variables, screen seed "
              f"{SCREEN_SEED} (N={N_SCREEN}), holdout {HOLDOUT_SEEDS} (N={N_VAL}).", flush=True)
        vsh_cur = sum(pmap([(best, {}, sd, N_VAL, "H") for sd in HOLDOUT_SEEDS])) / len(HOLDOUT_SEEDS)
        print(f"[autotune] current H2 vs H (holdout): {vsh_cur:.4f}", flush=True)

        for rnd in range(1, MAX_ROUNDS + 1):
            print(f"\n[autotune] === round {rnd} === ({time.time()-t_start:.0f}s elapsed)", flush=True)
            # ---- screen (self-gate, 1 seed) -- all candidates in parallel ----
            cands = [(key, v) for key, vals in SPACE.items() for v in vals if v != best[key]]
            scores = pmap([(best, {key: v}, SCREEN_SEED, N_SCREEN, "h2") for key, v in cands])
            per_key = {}   # key -> (best_delta, best_v)
            for (key, v), sc in zip(cands, scores):
                d = sc - 0.5
                if key not in per_key or d > per_key[key][0]:
                    per_key[key] = (d, v)
            leaners = sorted(((d, key, v) for key, (d, v) in per_key.items() if d >= SCREEN_THRESH),
                             reverse=True)
            if not leaners:
                print("[autotune] no screen leaners >= thresh -> converged.", flush=True)
                break
            print("[autotune] screen leaners: " +
                  ", ".join(f"{k}={v}(+{d:.3f})" for d, k, v in leaners[:6]), flush=True)

            # ---- validate the top leaners on disjoint holdout (self + vs-H), all in parallel ----
            top = leaners[:5]
            jobs = []
            for _d, key, v in top:
                for sd in HOLDOUT_SEEDS:
                    jobs.append((best, {key: v}, sd, N_VAL, "h2"))
                    jobs.append((best, {key: v}, sd, N_VAL, "H"))
            res = pmap(jobs)
            chosen, idx = None, 0
            for _d, key, v in top:
                sgs, vshs = [], []
                for _sd in HOLDOUT_SEEDS:
                    sgs.append(res[idx]); idx += 1
                    vshs.append(res[idx]); idx += 1
                sg, vsh = sum(sgs) / len(sgs), sum(vshs) / len(vshs)
                ok = sg >= 0.5 + VAL_MARGIN and vsh >= vsh_cur - VSH_TOL
                print(f"  validate {key}={v}: self-gate {sg:.4f}  vs-H {vsh:.4f} "
                      f"(cur {vsh_cur:.4f})  -> {'ADOPT' if ok else 'reject'}", flush=True)
                if ok and chosen is None:
                    chosen = (key, v, sg, vsh)   # first (highest screen delta) that passes
            if chosen is None:
                print("[autotune] no leaner survived holdout validation -> converged.", flush=True)
                break
            key, v, sg, vsh = chosen
            best[key] = v
            adopted[key] = v
            vsh_cur = vsh
            print(f"[autotune] ADOPTED {key}={v}  (self-gate {sg:.4f}, vs-H {vsh:.4f})", flush=True)

        # ---- closing report on a fresh disjoint seed set ----
        print(f"\n[autotune] ===== RESULT ({time.time()-t_start:.0f}s) =====", flush=True)
        if not adopted:
            print("[autotune] no changes adopted -- current H2 is already at its tuned optimum.", flush=True)
        else:
            print("[autotune] adopted overrides:", adopted, flush=True)
            k = len(FINAL_SEEDS)
            fin = pmap([(best, {}, sd, N_FINAL, "H") for sd in FINAL_SEEDS] +     # tuned vs H
                       [(orig, {}, sd, N_FINAL, "H") for sd in FINAL_SEEDS] +     # original vs H
                       [(orig, adopted, sd, N_FINAL, "h2") for sd in FINAL_SEEDS])  # tuned vs original
            new_vs_h = sum(fin[0:k]) / k
            orig_vs_h = sum(fin[k:2 * k]) / k
            new_vs_orig = sum(fin[2 * k:3 * k]) / k
            print(f"[autotune] FINAL (fresh seeds {FINAL_SEEDS}, N={N_FINAL}):", flush=True)
            print(f"           original H2 vs H : {orig_vs_h:.4f}", flush=True)
            print(f"           tuned    H2 vs H : {new_vs_h:.4f}   ({new_vs_h-orig_vs_h:+.4f})", flush=True)
            print(f"           tuned vs original H2 (self-gate): {new_vs_orig:.4f} "
                  f"(>0.5 = genuine improvement)", flush=True)
    print("[autotune] done (workers isolated; committed source untouched).", flush=True)


if __name__ == "__main__":
    main()
