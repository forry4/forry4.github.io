"""Calibrate H's noble/rusher league variants: win rate + avg nobles claimed.

Plays a paired, seat-swapped match in the fast engine between side A (an H-family
noble-aggressiveness variant) and side B (any opponent spec). Reports each side's
win rate, avg points, and avg nobles_won/game -- the last is the divergence metric
that confirms the noble variant actually chases nobles harder than the rusher while
both keep a solid win rate.

    # noble (2.5) vs base H, 200 paired games:
    python -m games.spender.ai.az.heuristic_variants_arena --a HN --b H --games 200
    # rusher vs base H:
    python -m games.spender.ai.az.heuristic_variants_arena --a HR --b H --games 200
    # a raw aggr scalar vs C2 (confirm solid win rate vs the incumbent):
    python -m games.spender.ai.az.heuristic_variants_arena --a 2.5 --b C2 --games 80 --opp-iters 80

--a is an H-family variant: a float noble_aggr, or HN/HR/H. --b is the same OR any
arena opponent spec (C2/B/A/weights-json) via arena.make_opponent.
"""
from __future__ import annotations

import argparse
import random
import time

from games.spender import main as inc

from . import engine as E
from . import heuristic as H
from .arena import make_opponent, wilson_ci


def _resolve_aggr(spec: str) -> float:
    """Map an H-family spec to its noble_aggr scalar."""
    table = {"H": 1.0, "HN": H.NOBLE_AGGR_HN, "HR": H.NOBLE_AGGR_HR}
    if spec in table:
        return table[spec]
    return float(spec)  # a raw scalar like "2.5"


def _side_b_move(spec: str, opp_iters: int):
    """Side-B move-fn. An H-family spec stays engine-native (fast); anything else
    routes through arena.make_opponent (C2/B/A/weights-json)."""
    if spec in ("H", "HN", "HR") or _is_float(spec):
        aggr = _resolve_aggr(spec)
        return lambda s: H.choose_action(s, s.turn, noble_aggr=aggr)
    return make_opponent(spec, opp_iters)


def _is_float(spec: str) -> bool:
    try:
        float(spec)
        return True
    except ValueError:
        return False


def play_game(a_aggr: float, b_move, a_seat: int, rng: random.Random,
              max_plies: int = 400):
    """Returns (a_score in {0,.5,1}, nobles_a, nobles_b, pts_a, pts_b)."""
    s = E.new_game(rng)
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        if s.turn == a_seat:
            E.apply(s, H.choose_action(s, s.turn, noble_aggr=a_aggr))
        else:
            E.apply(s, b_move(s))
    b_seat = 1 - a_seat
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        sc = 0.5
    else:
        sc = 1.0 if s.winner == a_seat else 0.0
    return (sc, len(s.nobles_won[a_seat]), len(s.nobles_won[b_seat]),
            s.points[a_seat], s.points[b_seat])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="HN", help="side A: HN|HR|H or a raw noble_aggr float")
    ap.add_argument("--b", default="H", help="side B: HN|HR|H|C2|B|A|weights-json")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--opp-iters", type=int, default=80, help="only used if B is a C2/B/A spec")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    inc.USE_VALUE_LEAF = False
    a_aggr = _resolve_aggr(args.a)
    b_move = _side_b_move(args.b, args.opp_iters)

    rng = random.Random(args.seed)
    tot = 0.0
    nob_a = nob_b = 0
    pts_a = pts_b = 0
    t0 = time.time()
    for i in range(args.games):
        sc, na, nb, pa, pb = play_game(a_aggr, b_move, i % 2, rng)
        tot += sc
        nob_a += na
        nob_b += nb
        pts_a += pa
        pts_b += pb
        if (i + 1) % 40 == 0:
            print(f"  ... {i+1}/{args.games}: A {tot/(i+1):.3f} | "
                  f"nobles A {nob_a/(i+1):.2f} B {nob_b/(i+1):.2f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    n = args.games
    score = tot / n
    lo, hi = wilson_ci(score, n)
    print(f"\n[variants] A={args.a} (aggr {a_aggr:g}) vs B={args.b}: "
          f"A win {score:.3f} (95% CI {lo:.3f}-{hi:.3f}) over {n} games", flush=True)
    print(f"           avg points  A {pts_a/n:.1f}  B {pts_b/n:.1f}", flush=True)
    print(f"           avg nobles  A {nob_a/n:.2f}  B {nob_b/n:.2f}  "
          f"(divergence A-B = {(nob_a-nob_b)/n:+.2f})", flush=True)


if __name__ == "__main__":
    main()
