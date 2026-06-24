"""Generic self-gate A/B: arbitrary candidate configs vs FROZEN today's-S, at a chosen sims level.

Generalizes backup_lambda_ab.py to any set of vsearch/v_state/H3/valuation3 overrides, so a probe can
sweep e.g. PRIOR_UNIFORM / POLICY_TEMP across the LOW-sims regime the deployed site actually runs (a
small Render CPU budget) AND a higher regime. Frozen = the module values at import (today's committed S).

Each config is "K=V;K=V" (e.g. "PRIOR_UNIFORM=0.2;POLICY_TEMP=1.0"). Frozen always runs with all probe
knobs at their committed default, so cand==default scores ~0.5 (paired CRN sanity).

Methodology (CLAUDE.md): paired CRN (each board both first-player ways, vsearch._RNG reset per game);
SCREEN all configs on one seed base; re-measure the leader on a DISJOINT fresh base; PANEL RPS guard
({H3,H2,H2N,H2R}) — a config can beat THIS frozen via rock-paper-scissors yet be weaker vs the panel.

Usage:
  python -m games.spender.ai.az.config_selfgate --sims 160 --n 140 --workers 12 \
      --configs "PRIOR_UNIFORM=0.1" "PRIOR_UNIFORM=0.25" "POLICY_TEMP=1.0" "PRIOR_UNIFORM=0.15;POLICY_TEMP=1.0"
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import math
import multiprocessing as mp
import random
import time

from . import engine as E
from . import heuristic3 as H3
from . import v_state
from . import valuation3 as V3
from . import vsearch
from .vsearch_camp import OPP, play_one
from .h3_vs_h2 import wilson_ci

PANEL = ["H3", "H3N", "H3R"]   # STRONG sanity checks only (user directive: never H2/H2N/H2R). H3R = racer proxy.
_MODS = (vsearch, v_state, H3, V3)

# every knob any config may touch — frozen pins these to their committed defaults, captured at import.
# (A new knob MUST be listed here or frozen won't reset it each turn -> both sides would inherit it,
#  silently breaking the A/B.)
_PROBE_KEYS = ["PRIOR_UNIFORM", "POLICY_TEMP", "C_PUCT", "BACKUP_LAMBDA",
               "H3_PICK_W", "RESERVE_PRIOR_W", "TAKE_PRIOR_W",
               "ENDGAME_TIEBREAK_W", "NOBLE_MULTI_W", "W_NOBLE",  # v_state (Gap A + multi-noble + its magnitude)
               "NOBLE_SCALE", "NOBLE_COUNT_W",                    # heuristic3/valuation3 (noble weight + overlap shape)
               "ENDGAME_SIM_MULT", "ENDGAME_SERVE_TIME", "ENDGAME_NEAR",  # vsearch (Gap B)
               "USE_DENY2",  # heuristic3 (2-turn endgame denial)
               "TEMPO_TURNS_SCALE", "TEMPO_TURNS_T0",  # heuristic3 (late-game tempo-weight scaling)
               "ENG_DECK_W", "DECK_STAGE_TILT", "DECK_STAGE_T0",  # valuation3 (deck-demand weight + level tilt)
               "DECK_BONUS_DISCOUNT",  # valuation3 (seat-aware bonus-discounted deck demand)
               "PROGRESS_TOPK", "PROGRESS_DECAY", "W_PROGRESS"]  # v_state (cascade-weighted progress over top-K targets + its weight)
FROZEN: dict = {}


def _set(k, v):
    for mod in _MODS:
        if hasattr(mod, k):
            setattr(mod, k, v)
            return
    raise SystemExit(f"unknown knob '{k}'")


def _apply(cfg: dict):
    for k, v in cfg.items():
        _set(k, v)


def _parse_cfg(spec: str) -> dict:
    out = {}
    for tok in spec.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        k, v = tok.split("=")
        try:
            f = float(v)
            out[k] = int(f) if (f.is_integer() and "." not in v) else f
        except ValueError:
            out[k] = v
    return out


def _play(cand: dict, frozen: dict, cand_seat: int, seed: int, sims: int, max_plies: int = 400) -> float:
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        _apply(cand if s.turn == cand_seat else frozen)
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def _trial(cand, frozen, seed, sims):
    return _play(cand, frozen, 0, seed, sims) + _play(cand, frozen, 1, seed, sims)


def _chunk(args):
    cand, frozen, seed_base, lo, hi, sims = args
    return sum(_trial(cand, frozen, seed_base + g, sims) for g in range(lo, hi))


def selfgate(cand, n, seed_base, sims, pool, workers):
    if pool is None:
        total = sum(_trial(cand, FROZEN, seed_base + g, sims) for g in range(n))
    else:
        step = math.ceil(n / workers)
        tasks = [(cand, FROZEN, seed_base, lo, min(lo + step, n), sims) for lo in range(0, n, step)]
        total = sum(pool.map(_chunk, tasks))
    return total / (2 * n)


def _panel_chunk(args):
    nm, sb, lo, hi, sims, cand = args
    _apply(cand)
    opp = OPP[nm]
    return sum(play_one(opp, i % 2, seed=sb + i, sims=sims) for i in range(lo, hi))


def panel(cand, n, seed0, step, sims, pool, workers):
    _apply(cand)
    out = {}
    for i, nm in enumerate(PANEL):
        sb = seed0 + i * step
        if pool is None:
            tot = sum(play_one(OPP[nm], j % 2, seed=sb + j, sims=sims) for j in range(n))
        else:
            st = math.ceil(n / workers)
            tasks = [(nm, sb, lo, min(lo + st, n), sims, cand) for lo in range(0, n, st)]
            tot = sum(pool.map(_panel_chunk, tasks))
        out[nm] = tot / n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=160)
    ap.add_argument("--n", type=int, default=140)
    ap.add_argument("--sanity-n", type=int, default=10,
                    help="seed-PAIRS for the frozen-vs-frozen sanity (each pair = 2 games, so default "
                         "10 = 20 games). Deterministically 0.5 under paired CRN, so a small count "
                         "confirms the harness is unbiased; no need to spend the full --n.")
    ap.add_argument("--panel-n", type=int, default=140)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--configs", nargs="+", required=True)
    ap.add_argument("--screen-seed", type=int, default=200_000)
    ap.add_argument("--hold-seed", type=int, default=3_000_000)
    ap.add_argument("--panel-seed", type=int, default=130_000_000)
    ap.add_argument("--step", type=int, default=100_000)
    ap.add_argument("--panel", action="store_true",
                    help="ALSO run the H3/H3N/H3R sanity panel. OFF by default: tuning is judged "
                         "ONLY by S-vs-frozen-S (screen + fresh) unless this is explicitly passed.")
    args = ap.parse_args()

    global FROZEN
    FROZEN = {k: getattr(mod, k) for k in _PROBE_KEYS for mod in _MODS if hasattr(mod, k)}
    cfgs = [_parse_cfg(c) for c in args.configs]
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    t0 = time.time()
    print(f"[config-selfgate] sims={args.sims} n={args.n} (={2*args.n} g/cfg) workers={workers}", flush=True)
    print(f"[frozen] {FROZEN}", flush=True)
    try:
        s0 = selfgate(dict(FROZEN), args.sanity_n, args.screen_seed, args.sims, pool, workers)
        print(f"[sanity] frozen-vs-frozen = {s0:.4f} (expect 0.5; n={args.sanity_n})", flush=True)
        scored = []
        for c, spec in zip(cfgs, args.configs):
            r = selfgate(c, args.n, args.screen_seed, args.sims, pool, workers)
            lo, hi = wilson_ci(r, 2 * args.n)
            print(f"[screen] {spec:<34} vs frozen = {r:.4f}  (95% CI {lo:.3f}-{hi:.3f})  "
                  f"[{time.time()-t0:.0f}s]", flush=True)
            scored.append((r, c, spec))
        scored.sort(key=lambda x: x[0], reverse=True)
        _r, best, best_spec = scored[0]
        fresh = selfgate(best, args.n, args.hold_seed, args.sims, pool, workers)
        flo, fhi = wilson_ci(fresh, 2 * args.n)
        print(f"[fresh]  {best_spec} vs frozen (disjoint) = {fresh:.4f} (95% CI {flo:.3f}-{fhi:.3f})",
              flush=True)
        if args.panel:  # opt-in ONLY; default is S-vs-frozen-S exclusively
            cp = panel(best, args.panel_n, args.panel_seed, args.step, args.sims, pool, workers)
            fp = panel(dict(FROZEN), args.panel_n, args.panel_seed, args.step, args.sims, pool, workers)
            cmin, fmin = min(cp.values()), min(fp.values())
            print(f"[panel] cand   avg {sum(cp.values())/len(cp):.4f} min {cmin:.3f}  {cp}", flush=True)
            print(f"[panel] frozen avg {sum(fp.values())/len(fp):.4f} min {fmin:.3f}  {fp}", flush=True)
            verdict = "SHIP" if (fresh > 0.52 and cmin >= fmin - 0.02) else "REJECT/WASH"
            print(f"[verdict] {best_spec}: fresh {fresh:.4f}, panel-min {cmin-fmin:+.3f} -> {verdict}",
                  flush=True)
        else:
            verdict = "SHIP" if fresh > 0.52 else "REJECT/WASH"
            print(f"[verdict] {best_spec}: fresh {fresh:.4f} -> {verdict}", flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
