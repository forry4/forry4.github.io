"""Arena: the H3 sandbox heuristic vs the deployed H2, both greedy in the fast engine.

H3 (`heuristic3` + `valuation3`) is a copy of H2 with the new potential/engine model behind
`valuation3.USE_POTENTIAL_ENGINE` (default OFF == byte-identical to H2). This harness flips it
on and measures H3 vs H2 head-to-head so the new model + its knobs can be A/B'd.

Sanity: with USE_POTENTIAL_ENGINE off, H3 == H2, so the score is ~0.500 (identical bots over
seat-swapped pairs) -- that is the calibration baseline. Turn the flag on (or pass --potential)
and watch whether the score clears 0.500.

CRN: each game i uses its OWN deck seed `--seed + i`, and seats swap every game, so two configs
see the IDENTICAL set of boards -> differences are signal, not seed luck. The final estimate
should still come from a FRESH disjoint seed range (tuning-set optimism) -- see H2.md.

Usage:
    python -m games.spender.ai.az.h3_vs_h2 --games 200 --potential
    python -m games.spender.ai.az.h3_vs_h2 --games 200 --potential --set POT_REACH_W=0.5 POT_ENGINE_W=1.5
    python -m games.spender.ai.az.h3_vs_h2 --games 200 --potential --set W_TEMPO=0.4 W_GEM=0.3
"""
from __future__ import annotations

import argparse
import math
import random
import time

from . import engine as E
from . import heuristic as H1
from . import heuristic2 as H2
from . import heuristic3 as H3
from . import valuation3 as V3

class _AggrH2:
    """H2 at a noble-aggressiveness multiplier on NOBLE_SCALE -- the H2N/H2R league variants ported
    from feat/az-v4-features. The multiplier scales ONLY noble_progress (completion +3 is untouched,
    so both variants stay competent): H2N=2.0 (noble-heavy), H2R=0.4 (rusher, races points)."""
    def __init__(self, aggr: float):
        self.aggr = aggr

    def choose_action(self, s, seat=None):
        saved = H2.NOBLE_SCALE
        H2.NOBLE_SCALE = saved * self.aggr
        try:
            return H2.choose_action(s, seat)
        finally:
            H2.NOBLE_SCALE = saved


H2N = _AggrH2(2.0)   # noble variant (NOBLE_AGGR_H2N from feat)
H2R = _AggrH2(0.4)   # rusher variant (NOBLE_AGGR_H2R from feat)
OPPONENTS = {"H": H1, "H2": H2, "H2N": H2N, "H2R": H2R}

# H3-based style variants -- STRONG sanity opponents (H3 is far closer to S than H2). H3N is
# noble-heavy, H3R a rusher/racer (a good proxy for a human racing style). They wrap H3's
# choose_action at a NOBLE_SCALE multiplier off the COMMITTED base (captured at import) -- NOT the
# live H3.NOBLE_SCALE, because candidate configs mutate H3.NOBLE_SCALE, which would otherwise make
# these opponents drift with the candidate and break the A/B. They restore whatever was set.
_H3_BASE_NOBLE = H3.NOBLE_SCALE   # committed default at import, before any candidate override
class _AggrH3:
    def __init__(self, aggr: float):
        self.aggr = aggr

    def choose_action(self, s, seat=None):
        saved = H3.NOBLE_SCALE
        H3.NOBLE_SCALE = _H3_BASE_NOBLE * self.aggr   # FIXED reference, independent of the candidate
        try:
            return H3.choose_action(s, seat)
        finally:
            H3.NOBLE_SCALE = saved


H3N = _AggrH3(2.0)   # noble-heavy strong opponent
H3R = _AggrH3(0.4)   # rusher/racer strong opponent (proxies the human racing style)


def wilson_ci(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    den = 1 + z * z / n
    center = (score + z * z / (2 * n)) / den
    half = z * math.sqrt(score * (1 - score) / n + z * z / (4 * n * n)) / den
    return center - half, center + half


def play_game(opp, h3_seat: int, *, seed: int, max_plies: int = 400) -> float:
    """One H3-vs-opp game on deck `seed`; returns H3's score in {0, 0.5, 1}."""
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        actor = H3 if s.turn == h3_seat else opp
        E.apply(s, actor.choose_action(s, s.turn))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == h3_seat else 0.0


def run_match(opp, opp_name: str, n_games: int, *, seed: int = 0, quiet: bool = False) -> float:
    total = 0.0
    t0 = time.time()
    for i in range(n_games):
        total += play_game(opp, i % 2, seed=seed + i)   # swap seats; per-game CRN seed
        if not quiet and (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{n_games}: H3 {total/(i+1):.3f}  {opp_name} {1-total/(i+1):.3f}  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    h3 = total / n_games
    lo, hi = wilson_ci(h3, n_games)
    print(f"[h3-vs-{opp_name.lower()}] H3 {h3:.3f}  |  {opp_name} {1-h3:.3f}   N={n_games}  "
          f"(H3 95% CI {lo:.3f}-{hi:.3f}){'' if not quiet else f' seed={seed}'}", flush=True)
    return h3


def _parse_kv(tok):
    k, v = tok.split("=")
    try:
        f = float(v)
        return k, (int(f) if f.is_integer() and "." not in v else f)
    except ValueError:
        return k, v   # leave non-numeric (e.g. a mode string) as-is


def _apply_override(k, v):
    """Route a KEY=VAL override to whichever module defines it (heuristic3 or valuation3)."""
    if hasattr(H3, k):
        setattr(H3, k, v); return "heuristic3"
    if hasattr(V3, k):
        setattr(V3, k, v); return "valuation3"
    raise SystemExit(f"unknown override key '{k}' (not in heuristic3 or valuation3)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--opp", default="H2", choices=["H", "H2", "both"],
                    help="opponent: H (heuristic), H2 (heuristic2), or both")
    ap.add_argument("--potential", action="store_true",
                    help="turn on valuation3.USE_POTENTIAL_ENGINE (the H3 model)")
    ap.add_argument("--set", nargs="+", default=None, dest="overrides",
                    help="H3/valuation3 overrides, e.g. POT_REACH_W=0.5 W_TEMPO=0.4")
    args = ap.parse_args()

    if args.potential:
        V3.USE_POTENTIAL_ENGINE = True
    if args.overrides:
        for k, v in (_parse_kv(t) for t in args.overrides):
            where = _apply_override(k, v)
            print(f"[h3] override {where}.{k} = {v}")
    print(f"[h3] USE_POTENTIAL_ENGINE={V3.USE_POTENTIAL_ENGINE} "
          f"POT_ENGINE_W={V3.POT_ENGINE_W} POT_REACH_W={V3.POT_REACH_W} REACH_DIV={V3.REACH_DIV} "
          f"| W_TEMPO={H3.W_TEMPO} W_GEM={H3.W_GEM} W_GOLD={H3.W_GOLD}", flush=True)
    names = ["H", "H2"] if args.opp == "both" else [args.opp]
    for nm in names:
        run_match(OPPONENTS[nm], nm, args.games, seed=args.seed)


if __name__ == "__main__":
    main()
