"""Autonomous coordinate-descent tuner for H3 (heuristic3 + valuation3).

Maximizes H3's greedy win rate vs H2, subject to win rate vs H >= H_FLOOR (default 0.69).
For each knob it SCREENS candidate values on a fixed tuning seed set (CRN -- same boards across
candidates, so the ranking is a paired comparison), then VALIDATES each proposed move on a large
DISJOINT holdout vs BOTH H2 and H before adopting. Adoptions require beating the incumbent's
holdout vs-H2 by --adopt-margin AND keeping holdout vs-H >= H_FLOOR. A final FRESH-seed confirm
(seeds used nowhere else) reports the honest end gain -- the guard against fixed-holdout overfit.

Never edits source. Writes the running best to h3_best.json (updated on every adoption, so a
kill/Ctrl-C leaves the best-so-far) and a transcript to h3_autotune.log. Starts from whatever the
heuristic3/valuation3 module defaults currently are.

Usage:
    python -m games.spender.ai.az.h3_autotune --screen-n 300 --holdout-n 1000 --max-passes 10
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import multiprocessing as mp
import os
import time

logging.getLogger("games.spender").setLevel(logging.ERROR)  # silence per-worker weight-load spam

from . import engine as E  # noqa: F401,E402  (kept for parity / future use)
from . import heuristic as H1  # noqa: E402
from . import heuristic2 as H2  # noqa: E402
from . import heuristic3 as H3  # noqa: E402
from . import valuation3 as V3  # noqa: E402
from .h3_vs_h2 import play_game  # noqa: E402

# knob registry: name -> (module, candidate values). Only knobs that are LIVE under the
# H3 model (USE_POTENTIAL_ENGINE on). ENG_DIV/ENG_FLOOR/ENG_TEMPO_SCALE/ENG_DECK_W still
# matter -- they shape potential_value via the level-0 engine term (_eng_base).
KNOBS = {
    "POT_ENGINE_W":      (V3, [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
    "W_GEM":             (H3, [0.2, 0.3, 0.4, 0.5]),
    "W_TEMPO":           (H3, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]),
    "W_GOLD":            (H3, [0.2, 0.3, 0.4, 0.5, 0.6]),
    "ENG_DECK_W":        (V3, [3.0, 3.5, 4.0, 4.5, 5.0]),
    "ENG_DIV":           (V3, [6.0, 8.0, 10.0, 12.0]),
    "ENG_FLOOR":         (V3, [0.1, 0.2, 0.3, 0.4]),
    "ENG_TEMPO_SCALE":   (V3, [0.2, 0.3, 0.4]),
    "NOBLE_SCALE":       (H3, [2.0, 2.5, 3.0, 3.5, 4.0]),
    "NOBLE_CLOSE_FLOOR": (V3, [0.1, 0.2, 0.3]),
    "NOBLE_TIME_GATE":   (V3, [False, True]),               # time-discount noble_progress (eff/(eff+w*deficit))
    "NOBLE_TURN_W":      (V3, [0.5, 1.0, 1.5, 2.0]),         # turns-per-bonus weight in the noble time fade
    "TURNS_FLOOR":       (V3, [0.0, 1.0, 2.0]),              # floor on estimated_turns_remaining
    "USE_FINISH_RESERVE": (H3, [False, True]),              # slot-pressure: reserve a near top board card
    "GOLD_BANK_CAP":     (V3, [1, 2, 3]),
    "GOLD_TIEBREAK":     (H3, [0.0, 0.1, 0.2, 0.3]),
    "POT_REACH_W":       (V3, [0.0, 0.05, 0.1, 0.2]),
    "BUILD_FLOOR_W":      (V3, [0.0, 0.05, 0.1, 0.2]),   # floor lets far cards transmit potential
    "CAP9_BUY_ABOVE":    (H3, [0.3, 0.5, 0.7]),
    "CAP8_BUY_ABOVE":    (H3, [0.6, 0.8, 1.0]),
    # turns_remaining engine model: the engine-vs-points balance lever (engine is now turns-scaled)
    "W_ENGINE":          (H3, [0.02, 0.05, 0.1, 0.15, 0.25, 0.4]),
    # NOTE: STAGE_*/ENG_DECAY/ENG_TEMPO_DIV were removed -- superseded by the turns_remaining model.
}

OPP = {"H2": H2, "H": H1}

_DIR = os.path.dirname(__file__)
LOG_PATH = os.path.join(_DIR, "h3_autotune.log")
BEST_PATH = os.path.join(_DIR, "h3_best.json")

_cache: dict = {}
_POOL = None
_WORKERS = 1


def read_current() -> dict:
    return {k: getattr(mod, k) for k, (mod, _) in KNOBS.items()}


def set_config(cfg: dict) -> None:
    for k, v in cfg.items():
        mod, _ = KNOBS[k]
        setattr(mod, k, v)


def _play_chunk(args):
    """Worker: set this process's config, play games [lo, hi) (global index -> seat=i%2,
    seed=seed_base+i, identical to the serial loop), return their summed score."""
    cfg, opp_name, seed_base, lo, hi = args
    set_config(cfg)
    opp = OPP[opp_name]
    return sum(play_game(opp, i % 2, seed=seed_base + i) for i in range(lo, hi))


def score(cfg: dict, opp_name: str, n: int, seed: int) -> float:
    """Win rate of H3(cfg) vs opp over n CRN games from `seed`. Cached on (cfg, opp, n, seed).
    With a worker pool, the n games are split into contiguous index ranges across processes;
    seat/seed are functions of the global index, so the result is bit-identical to serial."""
    key = (tuple(sorted(cfg.items())), opp_name, n, seed)
    if key in _cache:
        return _cache[key]
    if _POOL is None:
        set_config(cfg)
        opp = OPP[opp_name]
        total = sum(play_game(opp, i % 2, seed=seed + i) for i in range(n))
    else:
        step = math.ceil(n / _WORKERS)
        tasks = [(cfg, opp_name, seed, lo, min(lo + step, n)) for lo in range(0, n, step)]
        total = sum(_POOL.map(_play_chunk, tasks))
    _cache[key] = r = total / n
    return r


def _log(msg: str, fh) -> None:
    print(msg, flush=True)
    fh.write(msg + "\n")
    fh.flush()


def _save_best(cfg: dict, h2: float, h: float) -> None:
    with open(BEST_PATH, "w") as f:
        json.dump({"config": cfg, "holdout_vs_H2": h2, "holdout_vs_H": h}, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen-n", type=int, default=300)
    ap.add_argument("--holdout-n", type=int, default=1000)
    ap.add_argument("--fresh-n", type=int, default=1200)
    ap.add_argument("--max-passes", type=int, default=10)
    ap.add_argument("--h-floor", type=float, default=0.69)
    ap.add_argument("--adopt-margin", type=float, default=0.008)
    ap.add_argument("--screen-seed", type=int, default=1000)
    ap.add_argument("--hold-seed-h2", type=int, default=500_000)
    ap.add_argument("--hold-seed-h", type=int, default=600_000)
    ap.add_argument("--fresh-seed-h2", type=int, default=700_000)
    ap.add_argument("--fresh-seed-h", type=int, default=800_000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()

    global _POOL, _WORKERS
    _WORKERS = max(1, args.workers)
    if _WORKERS > 1:
        _POOL = mp.Pool(processes=_WORKERS)

    fh = open(LOG_PATH, "a")
    t0 = time.time()
    _log(f"\n===== h3_autotune start (screen_n={args.screen_n} holdout_n={args.holdout_n} "
         f"workers={_WORKERS} h_floor={args.h_floor} adopt_margin={args.adopt_margin}) =====", fh)

    best = read_current()
    base_h2 = score(best, "H2", args.holdout_n, args.hold_seed_h2)
    base_h = score(best, "H", args.holdout_n, args.hold_seed_h)
    _log(f"[start] incumbent holdout: vs H2 {base_h2:.4f}  vs H {base_h:.4f}  | {best}", fh)
    _save_best(best, base_h2, base_h)

    for p in range(args.max_passes):
        improved = False
        for knob, (mod, vals) in KNOBS.items():
            cur = best[knob]
            scored = []
            for v in vals:
                s2 = score({**best, knob: v}, "H2", args.screen_n, args.screen_seed)
                scored.append((s2, v))
            scored.sort(reverse=True, key=lambda t: t[0])
            _log(f"[p{p}] {knob} (cur={cur}) screen vs H2: "
                 + ", ".join(f"{v}={s:.3f}" for s, v in scored), fh)

            for s2_screen, v in scored[:3]:        # try the top few that differ from incumbent
                if v == cur:
                    continue
                cand = {**best, knob: v}
                ch2 = score(cand, "H2", args.holdout_n, args.hold_seed_h2)
                if ch2 <= base_h2 + args.adopt_margin:
                    continue
                ch = score(cand, "H", args.holdout_n, args.hold_seed_h)
                if ch < args.h_floor:
                    _log(f"[p{p}]   {knob}={v}: holdout vs H2 {ch2:.4f} (>{base_h2:.4f}) "
                         f"but vs H {ch:.4f} < {args.h_floor} -> REJECT (constraint)", fh)
                    continue
                best[knob] = v
                base_h2, base_h = ch2, ch
                set_config(best)
                improved = True
                _log(f"[p{p}]   ADOPT {knob}: {cur} -> {v}  | holdout vs H2 {ch2:.4f}  "
                     f"vs H {ch:.4f}  ({time.time()-t0:.0f}s)", fh)
                _save_best(best, base_h2, base_h)
                break
        if not improved:
            _log(f"[p{p}] no adoption this pass -> converged", fh)
            break

    fresh_h2 = score(best, "H2", args.fresh_n, args.fresh_seed_h2)
    fresh_h = score(best, "H", args.fresh_n, args.fresh_seed_h)
    _log(f"[final] best config: {best}", fh)
    _log(f"[final] holdout vs H2 {base_h2:.4f} vs H {base_h:.4f}  |  FRESH (N={args.fresh_n}) "
         f"vs H2 {fresh_h2:.4f} vs H {fresh_h:.4f}  ({time.time()-t0:.0f}s)", fh)
    _save_best(best, fresh_h2, fresh_h)
    fh.close()
    if _POOL is not None:
        _POOL.close()
        _POOL.join()


if __name__ == "__main__":
    main()
