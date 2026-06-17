"""Autonomous H2 tuner -- runs a full coordinate-descent campaign with NO human input.

Strategy (the rigor learned the hard way this session, automated):
  * SELF-GATE screen: sweep every tunable vs the CURRENT best config (H2-vs-H2). A copy of
    yourself is an equally-strong opponent, so a delta measures the *change* sensitively
    (empty change -> ~0.5).
  * SELF-EXPLOIT GUARD: a change is adopted only if, on DISJOINT HOLDOUT seeds it was NOT
    screened on, it BOTH (a) beats the current config on the self-gate by >= VAL_MARGIN AND
    (b) does NOT regress vs H (the external yardstick) -- killing rock-paper-scissors wins
    that beat this exact config but are actually weaker.
  * COORDINATE DESCENT: adopt the single best validated change per round, re-screen against the
    new best (so interactions are handled), until a round yields no validated improvement.

Search only -- restores heuristic2/valuation2 to their committed values at the end and prints
the recommended overrides + validated strength. Apply by hand after review.

Run:  python -m games.spender.ai.az.h2_autotune
"""
from __future__ import annotations

import time

from . import heuristic2 as H
from . import valuation2 as V
from .h2_tune import run_match, _capture_baseline, _apply_cfg

# Candidate values per tunable (current value is implicit -- skipped when it comes up).
SPACE = {
    "V.ENG_DECK_W":        [3.0, 4.0, 4.5, 5.5, 7.0],
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


def _avg(fn, seeds):
    return sum(fn(sd) for sd in seeds) / len(seeds)


def _self_gate(change, seed, n):
    """Score of (best_full + change) vs current modules (= best_full) on the self-gate."""
    return run_match(n, base_seed=seed, overrides=change, opp="h2", quiet=True)


def _vs_h(change, seed, n):
    """Score of (best_full + change) vs H. Modules are kept at best_full, so `change` is marginal."""
    return run_match(n, base_seed=seed, overrides=change, opp="H", quiet=True)


def main():
    orig = _capture_baseline()
    best = dict(orig)            # full current config (mutated as we adopt)
    adopted = {}                 # the overrides relative to orig
    _apply_cfg(best)
    t_start = time.time()
    print(f"[autotune] start. {len(SPACE)} variables, screen seed {SCREEN_SEED} (N={N_SCREEN}), "
          f"holdout {HOLDOUT_SEEDS} (N={N_VAL}).", flush=True)
    # reference: current H2 vs H on holdout (so we can detect vs-H regression each round)
    vsh_cur = _avg(lambda sd: _vs_h({}, sd, N_VAL), HOLDOUT_SEEDS)
    print(f"[autotune] current H2 vs H (holdout): {vsh_cur:.4f}", flush=True)

    for rnd in range(1, MAX_ROUNDS + 1):
        print(f"\n[autotune] === round {rnd} === ({time.time()-t_start:.0f}s elapsed)", flush=True)
        # ---- screen (self-gate, 1 seed) ----
        leaners = []
        for key, vals in SPACE.items():
            cur_v = best[key]
            best_v, best_d = None, 0.0
            for v in vals:
                if v == cur_v:
                    continue
                d = _self_gate({key: v}, SCREEN_SEED, N_SCREEN) - 0.5
                if d > best_d:
                    best_d, best_v = d, v
            if best_v is not None and best_d >= SCREEN_THRESH:
                leaners.append((best_d, key, best_v))
        leaners.sort(reverse=True)
        if not leaners:
            print("[autotune] no screen leaners >= thresh -> converged.", flush=True)
            break
        print(f"[autotune] screen leaners: " +
              ", ".join(f"{k}={v}(+{d:.3f})" for d, k, v in leaners[:6]), flush=True)

        # ---- validate top leaners on disjoint holdout, vs self AND vs H ----
        chosen = None
        for d, key, v in leaners[:5]:
            sg = _avg(lambda sd: _self_gate({key: v}, sd, N_VAL), HOLDOUT_SEEDS)
            vsh = _avg(lambda sd: _vs_h({key: v}, sd, N_VAL), HOLDOUT_SEEDS)
            ok = sg >= 0.5 + VAL_MARGIN and vsh >= vsh_cur - VSH_TOL
            print(f"  validate {key}={v}: self-gate {sg:.4f}  vs-H {vsh:.4f} "
                  f"(cur {vsh_cur:.4f})  -> {'ADOPT' if ok else 'reject'}", flush=True)
            if ok:
                chosen = (key, v, sg, vsh)
                break   # adopt the best validated; re-screen next round
        if chosen is None:
            print("[autotune] no leaner survived holdout validation -> converged.", flush=True)
            break
        key, v, sg, vsh = chosen
        best[key] = v
        adopted[key] = v
        vsh_cur = vsh                      # new vs-H reference
        _apply_cfg(best)                   # sync modules so next round screens vs the new best
        print(f"[autotune] ADOPTED {key}={v}  (self-gate {sg:.4f}, vs-H {vsh:.4f})", flush=True)

    # ---- closing report on a fresh disjoint seed set ----
    print(f"\n[autotune] ===== RESULT ({time.time()-t_start:.0f}s) =====", flush=True)
    if not adopted:
        print("[autotune] no changes adopted -- current H2 is already at its tuned optimum.", flush=True)
    else:
        print("[autotune] adopted overrides:", adopted, flush=True)
        _apply_cfg(best)
        new_vs_h = _avg(lambda sd: _vs_h({}, sd, N_FINAL), FINAL_SEEDS)
        _apply_cfg(orig)
        orig_vs_h = _avg(lambda sd: _vs_h({}, sd, N_FINAL), FINAL_SEEDS)
        # new config vs ORIGINAL committed H2 (modules at orig -> candidate = orig + adopted)
        new_vs_orig = _avg(lambda sd: run_match(N_FINAL, base_seed=sd, overrides=adopted,
                                                opp="h2", quiet=True), FINAL_SEEDS)
        print(f"[autotune] FINAL (fresh seeds {FINAL_SEEDS}, N={N_FINAL}):", flush=True)
        print(f"           original H2 vs H : {orig_vs_h:.4f}", flush=True)
        print(f"           tuned    H2 vs H : {new_vs_h:.4f}   ({new_vs_h-orig_vs_h:+.4f})", flush=True)
        print(f"           tuned vs original H2 (self-gate): {new_vs_orig:.4f} "
              f"(>0.5 = genuine improvement)", flush=True)

    _apply_cfg(orig)   # ALWAYS restore the committed config
    print("[autotune] modules restored to committed config.", flush=True)


if __name__ == "__main__":
    main()
