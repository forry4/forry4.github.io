"""Profile variant-S search — where does the per-move serving budget actually go?

Two passes:
  1. CLEAN wall-clock (no profiler): real sims/sec and the implied sims/move at a 4.5s budget.
  2. cProfile breakdown by self-time: which functions dominate — engine sim (apply/clone/
     legal_actions/determinize) vs Valuation build vs the valuation hot loops (_cost_scalar/
     _delta_take/engine_value) vs the H3 policy-prior anchor. This is what decides whether (and
     what) a Cython/C rewrite — or distillation to a numpy net — would actually buy.

cProfile inflates absolute times (per-call overhead) and skews toward many-small-call functions,
so read pass #2 as RELATIVE structure and pass #1 for the true throughput number.

Usage: python -m games.spender.ai.az.vsearch_profile --sims 600 --positions 4 --seed 42
"""
from __future__ import annotations

import argparse
import cProfile
import pstats
import random
import time

from . import engine as E
from . import heuristic3 as H3
from . import vsearch


def _play_position(seed: int, plies: int):
    s = E.new_game(random.Random(seed))
    for _ in range(plies):
        if s.phase == E.OVER:
            break
        E.apply(s, H3.choose_action(s, s.turn))
    return s


def _collect(seed: int, plies: int, n: int):
    """n distinct PLAY positions with a real choice, from greedy-H3 self-play."""
    out, i = [], 0
    while len(out) < n:
        s = _play_position(seed + i, plies)
        i += 1
        if s.phase == E.PLAY and len(E.legal_actions(s)) > 1:
            out.append(s)
        if i > seed + 10000:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=600)
    ap.add_argument("--positions", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--plies", type=int, default=14)
    ap.add_argument("--budget", type=float, default=4.5)
    ap.add_argument("--top", type=int, default=28)
    args = ap.parse_args()

    states = _collect(args.seed, args.plies, args.positions)

    # ── pass 1: clean wall-clock (no profiler) ──
    t0 = time.time()
    for s in states:
        vsearch.choose_action(s.clone(), s.turn, sims=args.sims)
    dt = time.time() - t0
    sims_total = args.sims * len(states)
    sps = sims_total / dt if dt else 0.0
    print(f"\n[clean] {len(states)} moves x {args.sims} sims = {dt:.2f}s  "
          f"({dt/len(states):.3f}s/move, {sps:.0f} sims/s)")
    print(f"[clean] => at a {args.budget}s budget that's ~{args.budget * sps:.0f} sims/move "
          f"(NOTE: depressed if the box is busy with the autotuner / other jobs)\n")

    # ── pass 2: cProfile breakdown ──
    pr = cProfile.Profile()
    pr.enable()
    for s in states:
        vsearch.choose_action(s.clone(), s.turn, sims=args.sims)
    pr.disable()
    st = pstats.Stats(pr)
    st.strip_dirs()
    print(f"== cProfile: top {args.top} by SELF time (tottime) — relative structure ==")
    st.sort_stats("tottime").print_stats(args.top)


if __name__ == "__main__":
    main()
