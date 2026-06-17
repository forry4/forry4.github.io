"""H2 tuning harness (offline, greedy in the fast engine).

Plays variant H2 (`heuristic2` + `valuation2`) head-to-head, both 1-ply greedy in
`engine.py` (no MCTS), so a match is fast. Two opponents:
  --opp H   : H2(candidate) vs the stable variant H (`heuristic`).  [default]
  --opp h2  : H2(candidate) vs the CURRENT committed H2 config -- a self-gate. Far more
              sensitive now that H2 >> H: a delta vs an equally-strong copy of yourself
              measures the *change* directly (empty overrides -> ~0.5 by symmetry).

Design choices that make small effects measurable:
  * Common random numbers (CRN): every config plays the IDENTICAL set of games (same deck
    seeds, same seat per game), so a win-rate delta is the parameter change, not luck.
  * Constant overrides: {"H.W_GOLD": 0.3, "V.ENG_DIV": 6.0} patch the module globals. For
    --opp h2 the candidate's config is toggled in per move (the baseline plays the other side).

Usage:
    python -m games.spender.ai.az.h2_tune --opp h2 --games 1600           # self-gate sanity (~0.5)
    python -m games.spender.ai.az.h2_tune --opp h2 --sweep W_GOLD 0.3 0.4 0.5 0.6
    python -m games.spender.ai.az.h2_tune --opp h2 --set V.ENG_DECK_W=4.0 H.NOBLE_SCALE=3.5
"""
from __future__ import annotations

import argparse
import random
import time

from . import engine as E
from . import heuristic as H_BASE      # variant H (opponent for --opp H)
from . import heuristic2 as H          # variant H2 (the bot we tune)
from . import valuation2 as V
from .arena import wilson_ci

# Every tunable the candidate may override -- snapshotted to define the "current H2" baseline.
_H_KEYS = ["W_TEMPO", "W_GEM", "W_GOLD", "W_SHORTFALL", "NOBLE_SCALE", "NOBLE_SCARCITY",
           "STAGE_K", "STAGE_FLOOR", "ENG_DECAY", "CAP9_BUY_ABOVE", "CAP8_BUY_ABOVE",
           "GOLD_TIEBREAK", "RESERVE_GAP", "TAKE2_MIN_STEEP",
           "USE_RESERVE", "USE_SPECULATIVE_RESERVE", "USE_TAKE2", "USE_OPP_SNIPE",
           "SNIPE_REQUIRE_OPP_TOP"]
_V_KEYS = ["GOLD_BANK_CAP", "ENG_DIV", "ENG_FLOOR", "ENG_DECK_W", "NOBLE_CLOSE_FLOOR",
           "EFF_REF", "RESERVED_ENGINE_W", "ENG_WEIGHT_MODE", "ENG_TEMPO_SCALE", "ENG_RECURSE_W"]


def _capture_baseline() -> dict:
    """Snapshot the current committed config of every tunable as {"H.NAME"|"V.NAME": value}."""
    cfg = {f"H.{k}": getattr(H, k) for k in _H_KEYS}
    cfg.update({f"V.{k}": getattr(V, k) for k in _V_KEYS})
    return cfg


def _apply_cfg(cfg: dict) -> None:
    for key, val in cfg.items():
        mod_tag, name = key.split(".", 1)
        setattr(H if mod_tag == "H" else V, name, val)


def _set_overrides(overrides: dict):
    """Apply overrides to the modules; return prior values for restore (used by --opp H)."""
    prev = {}
    for key, val in overrides.items():
        mod_tag, name = key.split(".", 1)
        mod = H if mod_tag == "H" else V
        prev[key] = getattr(mod, name)
        setattr(mod, name, val)
    return prev


def play_game_vs_h(h2_seat: int, seed: int, max_plies: int = 400) -> float:
    """One H2-vs-H game on deck `seed`; H2 plays `h2_seat` (overrides applied by caller)."""
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


def play_game_self(cand_cfg: dict, base_cfg: dict, cand_seat: int, seed: int,
                   max_plies: int = 400) -> float:
    """One H2(candidate)-vs-H2(baseline) game; the config is toggled in per move so each side
    plays under its own constants. Returns the candidate's score."""
    s = E.new_game(random.Random(seed))
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        seat = s.turn
        _apply_cfg(cand_cfg if seat == cand_seat else base_cfg)
        E.apply(s, H.choose_action(s, seat))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def run_match(n_games: int, *, base_seed: int = 1000, overrides: dict | None = None,
              opp: str = "H", quiet: bool = False) -> float:
    """Candidate vs `opp` over `n_games` with CRN (game i: deck seed base_seed+i, candidate
    seat i%2). opp='H' -> vs heuristic H; opp='h2' -> vs the current committed H2 (self-gate)."""
    if opp == "h2":
        base_cfg = _capture_baseline()
        cand_cfg = {**base_cfg, **(overrides or {})}
        try:
            total = sum(play_game_self(cand_cfg, base_cfg, i % 2, base_seed + i)
                        for i in range(n_games))
            score = total / n_games
        finally:
            _apply_cfg(base_cfg)  # restore
    else:
        prev = _set_overrides(overrides or {})
        try:
            total = sum(play_game_vs_h(i % 2, base_seed + i) for i in range(n_games))
            score = total / n_games
        finally:
            _set_overrides(prev)
    if not quiet:
        lo, hi = wilson_ci(score, n_games)
        tag = ", ".join(f"{k}={v}" for k, v in (overrides or {}).items()) or "baseline"
        opp_lbl = "H2(self)" if opp == "h2" else "H"
        print(f"[h2-tune] H2 vs {opp_lbl}: {score:.4f}  N={n_games}  CI {lo:.3f}-{hi:.3f}  ({tag})",
              flush=True)
    return score


def _parse_kv(tok):
    k, v = tok.split("=")
    key = k if "." in k else f"H.{k}"
    f = float(v)
    return key, (int(f) if f.is_integer() and "." not in v else f)


def _parse_val(v):
    f = float(v)
    return int(f) if f.is_integer() and "." not in v else f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=800)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--opp", default="H", choices=["H", "h2"],
                    help="opponent: H (heuristic, default) or h2 (current committed H2 self-gate)")
    ap.add_argument("--sweep", nargs="+", default=None,
                    help="NAME v1 v2 ...  (NAME in H2 unless prefixed V.)")
    ap.add_argument("--set", nargs="+", default=None, dest="overrides",
                    help="KEY=VAL ...  (KEY in H2 unless prefixed V.) -- one combo match")
    args = ap.parse_args()

    if args.overrides:
        ov = dict(_parse_kv(t) for t in args.overrides)
        t0 = time.time()
        base = run_match(args.games, base_seed=args.seed, opp=args.opp, quiet=True)
        sc = run_match(args.games, base_seed=args.seed, overrides=ov, opp=args.opp)
        print(f"  baseline {base:.4f} -> combo {sc:.4f}  ({sc-base:+.4f})  ({time.time()-t0:.0f}s)")
        return

    if not args.sweep:
        t0 = time.time()
        run_match(args.games, base_seed=args.seed, opp=args.opp)
        print(f"  ({time.time()-t0:.0f}s)")
        return

    name = args.sweep[0]
    key = name if "." in name else f"H.{name}"
    vals = [_parse_val(v) for v in args.sweep[1:]]
    print(f"[h2-tune] sweeping {key} over {vals}  (N={args.games}, CRN seed {args.seed}, "
          f"opp={args.opp})", flush=True)
    base = run_match(args.games, base_seed=args.seed, opp=args.opp, quiet=True)
    print(f"  baseline (current default): {base:.4f}", flush=True)
    results = []
    for v in vals:
        t0 = time.time()
        sc = run_match(args.games, base_seed=args.seed, overrides={key: v}, opp=args.opp, quiet=True)
        results.append((v, sc))
        print(f"  {key}={v:<8} -> {sc:.4f}  ({sc-base:+.4f})  [{time.time()-t0:.0f}s]", flush=True)
    best = max(results, key=lambda r: r[1])
    print(f"[h2-tune] best {key}={best[0]} -> {best[1]:.4f} (default {base:.4f})", flush=True)


if __name__ == "__main__":
    main()
