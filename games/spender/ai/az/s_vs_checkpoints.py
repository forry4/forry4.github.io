"""Panel of past selves: a protagonist S config vs a SET of saved S checkpoints.

Each game is S-vs-S with DIFFERENT per-module configs, so the right (and only safe) harness is the
per-turn config swap (config_selfgate's pattern, generalized to full per-module configs): apply the
protagonist's config before its move, the checkpoint's before the checkpoint's move -- they share the
module globals, so whoever moved last leaves them set, and the next mover must re-assert its own.
Paired CRN (each deck played both seatings, vsearch._RNG reset per game), parallel across processes.

Protagonist = the live modules' current config (optionally + --set overrides), captured ONCE at start.
Opponents = the named checkpoints (default: all saved). Reports the protagonist's win rate vs each +
Wilson CI + the panel min/avg -- the same-strength, style-diverse RPS guard the H3 panel can't be.

Sanity: with NO --set, protagonist == live == the s_<today> checkpoint, so it scores ~0.5 vs it
(paired CRN). With --set matching a self-gate candidate vs the frozen-baseline checkpoint, it
reproduces the self-gate number -- an end-to-end check that the checkpoint machinery is faithful.

Usage:
  python -m games.spender.ai.az.s_vs_checkpoints --sims 500 --n 300 --workers 10 \
      --set "PROGRESS_TOPK=6;PROGRESS_DECAY=1.0;W_PROGRESS=3.54" --vs s_2026-06-24
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import copy
import math
import multiprocessing as mp
import random
import time

from . import engine as E
from . import s_checkpoints as ckpt
from . import vsearch
from .h3_vs_h2 import wilson_ci


def _parse_overrides(spec: str) -> dict:
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


def _patch(base: dict, overrides: dict) -> dict:
    """Apply flat KEY=VAL overrides onto a per-module base config (sets EVERY module that has it,
    so duplicate names like NOBLE_TURN_W are kept consistent across modules)."""
    cfg = copy.deepcopy(base)
    for k, v in overrides.items():
        placed = False
        for d in cfg.values():
            if k in d:
                d[k] = v
                placed = True
        if not placed:
            raise SystemExit(f"override key '{k}' not in any module's snapshot")
    return cfg


def _play(prot_cfg, opp_cfg, prot_seat, seed, sims, max_plies=400):
    vsearch._RNG = random.Random(seed)
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        ckpt.apply_config(prot_cfg if s.turn == prot_seat else opp_cfg)
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == prot_seat else 0.0


def _trial(prot_cfg, opp_cfg, seed, sims):
    return _play(prot_cfg, opp_cfg, 0, seed, sims) + _play(prot_cfg, opp_cfg, 1, seed, sims)


def _chunk(args):
    prot, opp, sb, lo, hi, sims = args
    return sum(_trial(prot, opp, sb + g, sims) for g in range(lo, hi))


def run_vs(prot, opp, n, seed_base, sims, pool, workers):
    if pool is None:
        return sum(_trial(prot, opp, seed_base + g, sims) for g in range(n)) / (2 * n)
    st = math.ceil(n / workers)
    tasks = [(prot, opp, seed_base, lo, min(lo + st, n), sims) for lo in range(0, n, st)]
    return sum(pool.map(_chunk, tasks)) / (2 * n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=200_000)
    ap.add_argument("--step", type=int, default=1_000_000)
    ap.add_argument("--set", default="", help="flat KEY=VAL;... overrides on the protagonist")
    ap.add_argument("--vs", nargs="*", default=None, help="checkpoint names (default: all saved)")
    args = ap.parse_args()

    base = ckpt.snapshot()
    prot = _patch(base, _parse_overrides(args.set)) if args.set else base
    names = args.vs if args.vs else ckpt.available()
    if not names:
        raise SystemExit("no checkpoints to play against (save one first)")
    workers = max(1, args.workers)
    pool = mp.Pool(workers) if workers > 1 else None
    t0 = time.time()
    print(f"[s-vs-ckpt] sims={args.sims} n={args.n} (={2*args.n} g/opp) workers={workers}", flush=True)
    print(f"[protagonist] {'live + ' + args.set if args.set else 'live config'}", flush=True)
    try:
        results = {}
        for i, nm in enumerate(names):
            opp = ckpt.load_config(nm)
            r = run_vs(prot, opp, args.n, args.seed + i * args.step, args.sims, pool, workers)
            lo_, hi_ = wilson_ci(r, 2 * args.n)
            results[nm] = r
            print(f"[vs] {nm:<24} = {r:.4f}  (95% CI {lo_:.3f}-{hi_:.3f})  [{time.time()-t0:.0f}s]", flush=True)
        vals = list(results.values())
        worst = min(results, key=results.get)
        print(f"[panel] avg {sum(vals)/len(vals):.4f}  min {min(vals):.4f}  (worst vs {worst})", flush=True)
    finally:
        if pool is not None:
            pool.close()
            pool.join()


if __name__ == "__main__":
    main()
