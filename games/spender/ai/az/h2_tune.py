"""H2-vs-H tuning harness (offline, both greedy in the fast engine).

Plays variant H2 (`heuristic2` + `valuation2`) head-to-head against the stable
variant H (`heuristic` + `valuation`), both 1-ply greedy in `engine.py` (no MCTS),
so a match is fast. Used to tune H2's constants by win rate vs H.

Two design choices that make small effects measurable:
  * Common random numbers (CRN): every config plays the IDENTICAL set of games
    (same deck seeds, same seat assignment per game), so a win-rate delta between
    two configs is the parameter change, not luck. Paired by game index.
  * Constant overrides: a dict like {"H.W_GOLD": 0.3, "V.ENG_DIV": 6.0} patches
    the module globals for the duration of a match, then restores them.

Usage:
    python -m games.spender.ai.az.h2_tune --games 800            # baseline H2 vs H
    python -m games.spender.ai.az.h2_tune --sweep W_GOLD 0.2 0.3 0.4 0.5 0.6
"""
from __future__ import annotations

import argparse
import random
import time

from . import engine as E
from . import heuristic as H_BASE      # variant H (opponent)
from . import heuristic2 as H          # variant H2 (the bot we tune)
from . import valuation2 as V
from .arena import wilson_ci


def _set_overrides(overrides: dict):
    """Apply {"H.NAME": val | "V.NAME": val} to the H2/valuation2 modules.
    Returns the prior values so the caller can restore them."""
    prev = {}
    for key, val in overrides.items():
        mod_tag, name = key.split(".", 1)
        mod = H if mod_tag == "H" else V
        prev[key] = getattr(mod, name)
        setattr(mod, name, val)
    return prev


def play_game(h2_seat: int, seed: int, max_plies: int = 400) -> float:
    """One H2-vs-H game on deck `seed`; H2 plays `h2_seat`. Returns H2's score."""
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        if s.turn == h2_seat:
            E.apply(s, H.choose_action(s, s.turn))
        else:
            E.apply(s, H_BASE.choose_action(s, s.turn))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == h2_seat else 0.0


def run_match(n_games: int, *, base_seed: int = 1000, overrides: dict | None = None,
              quiet: bool = False) -> float:
    """H2 vs H over `n_games` with CRN. Game i uses deck seed base_seed+i and
    H2 takes seat i%2 (seat-swapped). Same i -> same game across configs."""
    prev = _set_overrides(overrides or {})
    try:
        total = 0.0
        for i in range(n_games):
            total += play_game(i % 2, base_seed + i)
        score = total / n_games
    finally:
        _set_overrides(prev)  # restore
    if not quiet:
        lo, hi = wilson_ci(score, n_games)
        tag = ", ".join(f"{k}={v}" for k, v in (overrides or {}).items()) or "baseline"
        print(f"[h2-tune] H2 vs H: {score:.4f}  N={n_games}  CI {lo:.3f}-{hi:.3f}  ({tag})",
              flush=True)
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=800)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--sweep", nargs="+", default=None,
                    help="NAME v1 v2 ...  (NAME in H2 unless prefixed V.)")
    ap.add_argument("--set", nargs="+", default=None, dest="overrides",
                    help="KEY=VAL ...  (KEY in H2 unless prefixed V.) -- one combo match")
    args = ap.parse_args()

    def _parse_kv(tok):
        k, v = tok.split("=")
        key = k if "." in k else f"H.{k}"
        f = float(v)
        return key, (int(f) if f.is_integer() and "." not in v else f)

    if args.overrides:
        ov = dict(_parse_kv(t) for t in args.overrides)
        t0 = time.time()
        base = run_match(args.games, base_seed=args.seed, quiet=True)
        sc = run_match(args.games, base_seed=args.seed, overrides=ov)
        print(f"  baseline {base:.4f} -> combo {sc:.4f}  ({sc-base:+.4f})  ({time.time()-t0:.0f}s)")
        return

    if not args.sweep:
        t0 = time.time()
        run_match(args.games, base_seed=args.seed)
        print(f"  ({time.time()-t0:.0f}s)")
        return

    name = args.sweep[0]
    key = name if "." in name else f"H.{name}"
    # parse values as float (fall back to int when integral)
    vals = []
    for v in args.sweep[1:]:
        f = float(v)
        vals.append(int(f) if f.is_integer() and "." not in v else f)
    print(f"[h2-tune] sweeping {key} over {vals}  (N={args.games}, CRN seed {args.seed})",
          flush=True)
    base = run_match(args.games, base_seed=args.seed, quiet=True)
    print(f"  baseline (current default): {base:.4f}", flush=True)
    results = []
    for v in vals:
        t0 = time.time()
        sc = run_match(args.games, base_seed=args.seed, overrides={key: v}, quiet=True)
        results.append((v, sc))
        print(f"  {key}={v:<8} -> {sc:.4f}  ({sc-base:+.4f})  [{time.time()-t0:.0f}s]",
              flush=True)
    best = max(results, key=lambda r: r[1])
    print(f"[h2-tune] best {key}={best[0]} -> {best[1]:.4f} (default {base:.4f})", flush=True)


if __name__ == "__main__":
    main()
