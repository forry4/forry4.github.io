"""Autonomous coordinate-descent tuner for variant S (vsearch + v_state) — panel-average objective.

Maximizes the MEAN win rate over the style-diverse panel {H3, H2, H2N, H2R}, subject to no single
matchup falling below --min-opp (so a gain can't be bought by collapsing one style — the documented
"panel mean can hide a bad matchup" guard). Per knob: SCREEN candidate values on a small CRN seed
set (panel mean, same boards across candidates), then VALIDATE the best few on a larger DISJOINT
holdout; adopt if the holdout panel mean beats the incumbent by --adopt-margin AND every opp stays
>= --min-opp. A final FRESH-seed confirm (seeds used nowhere else) reports the honest gain.

Never edits source. Writes the running best to vsearch_best.json (so a kill leaves best-so-far) and
a transcript to vsearch_autotune.log. Starts from the current v_state/vsearch module defaults.

Search games are ~50x slower than greedy H3 games — keep --screen-n / --holdout-n modest and --sims
at a tuning value; final strength is measured separately at production sims (vsearch_camp / arena).

Usage:
    python -m games.spender.ai.az.vsearch_autotune --sims 120 --screen-n 48 --holdout-n 160 --workers 12
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

from . import heuristic3 as H3  # noqa: E402
from . import v_state  # noqa: E402
from . import valuation3 as V3  # noqa: E402
from . import vsearch  # noqa: E402
from .vsearch_camp import OPP, play_one  # noqa: E402

PANEL = ["H3", "H2", "H2N", "H2R"]
_MODS = (vsearch, v_state, H3, V3)   # override-routing precedence

# knob registry: name -> (defining module, candidate values). v_state weights + the search knobs.
KNOBS = {
    "W_PROGRESS":   (v_state, [1.0, 1.5, 2.0, 2.5]),
    "W_ENGINE_STK": (v_state, [0.4, 0.8, 1.2]),
    "W_NOBLE":      (v_state, [0.3, 0.6, 0.9]),
    "W_ECON":       (v_state, [0.0, 0.3, 0.6]),
    "W_POINTS":     (v_state, [0.8, 1.0, 1.3]),
    "SCALE":        (v_state, [6.0, 8.0, 10.0]),
    "WIN_CONVEX":   (v_state, [0.0, 0.1, 0.2]),
    "PROGRESS_TOPK": (v_state, [1, 2, 3]),
    "POLICY_TEMP":  (vsearch, [0.5, 0.7, 1.0]),
    "C_PUCT":       (vsearch, [1.5, 2.0, 3.0]),
    "H3_PICK_W":    (vsearch, [1.0, 1.5, 2.5]),
    "RESERVE_PRIOR_W": (vsearch, [0.3, 0.5, 0.7]),
}

_DIR = os.path.dirname(__file__)
LOG_PATH = os.path.join(_DIR, "vsearch_autotune.log")
BEST_PATH = os.path.join(_DIR, "vsearch_best.json")

_cache: dict = {}
_POOL = None
_WORKERS = 1
_SIMS = 120


def _set(k, v):
    for mod in _MODS:
        if hasattr(mod, k):
            setattr(mod, k, v)
            return
    raise SystemExit(f"unknown knob '{k}'")


def read_current() -> dict:
    return {k: getattr(mod, k) for k, (mod, _) in KNOBS.items()}


def set_config(cfg: dict) -> None:
    for k, v in cfg.items():
        _set(k, v)


def _chunk(args):
    cfg, opp_name, seed_base, lo, hi, sims = args
    set_config(cfg)
    opp = OPP[opp_name]
    return sum(play_one(opp, i % 2, seed=seed_base + i, sims=sims) for i in range(lo, hi))


def score(cfg: dict, opp_name: str, n: int, seed: int) -> float:
    """Win rate of vsearch(cfg) vs opp over n CRN games from `seed` (at _SIMS). Cached; parallel."""
    key = (tuple(sorted(cfg.items())), opp_name, n, seed, _SIMS)
    if key in _cache:
        return _cache[key]
    if _POOL is None:
        set_config(cfg)
        total = sum(play_one(OPP[opp_name], i % 2, seed=seed + i, sims=_SIMS) for i in range(n))
    else:
        step = math.ceil(n / _WORKERS)
        tasks = [(cfg, opp_name, seed, lo, min(lo + step, n), _SIMS) for lo in range(0, n, step)]
        total = sum(_POOL.map(_chunk, tasks))
    _cache[key] = r = total / n
    return r


MEAN_EPS = 0.001  # tiny mean weight: MIN is the primary objective; mean only breaks near-ties


def panel(cfg: dict, n: int, seed0: int, step: int):
    """(per-opp win rates, MAXIMIN objective). objective = min(win rates) + MEAN_EPS*mean, so the
    tuner maximizes the WORST matchup (fewest weaknesses) and uses the mean only to break ties among
    configs with the same min. Each opp gets a disjoint seed base seed0 + i*step."""
    wrs = {opp: score(cfg, opp, n, seed0 + i * step) for i, opp in enumerate(PANEL)}
    vals = list(wrs.values())
    return wrs, min(vals) + MEAN_EPS * (sum(vals) / len(vals))


def _log(msg: str, fh) -> None:
    print(msg, flush=True)
    fh.write(msg + "\n")
    fh.flush()


def _save(cfg: dict, wrs: dict, obj: float) -> None:
    with open(BEST_PATH, "w") as f:
        json.dump({"config": cfg, "panel": wrs, "min": min(wrs.values()), "obj": obj,
                   "sims": _SIMS}, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=120)
    ap.add_argument("--screen-n", type=int, default=72)    # MIN objective is noisier than mean -> larger N
    ap.add_argument("--holdout-n", type=int, default=240)
    ap.add_argument("--fresh-n", type=int, default=360)
    ap.add_argument("--max-passes", type=int, default=3)
    ap.add_argument("--adopt-margin", type=float, default=0.01)
    ap.add_argument("--min-opp", type=float, default=0.50)
    ap.add_argument("--screen-seed", type=int, default=1_000)
    ap.add_argument("--hold-seed", type=int, default=2_000_000)
    ap.add_argument("--fresh-seed", type=int, default=5_000_000)
    ap.add_argument("--step", type=int, default=100_000)   # per-opp seed spacing (>> n -> disjoint)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    global _POOL, _WORKERS, _SIMS
    _WORKERS = max(1, args.workers)
    _SIMS = args.sims
    if _WORKERS > 1:
        _POOL = mp.Pool(processes=_WORKERS)

    fh = open(LOG_PATH, "a")
    t0 = time.time()
    _log(f"\n===== vsearch_autotune start (MAXIMIN: maximize min-over-panel; sims={_SIMS} "
         f"screen_n={args.screen_n} holdout_n={args.holdout_n} workers={_WORKERS}) =====", fh)

    best = read_current()
    bw, bavg = panel(best, args.holdout_n, args.hold_seed, args.step)
    _log(f"[start] incumbent holdout: min {min(bw.values()):.4f} (obj {bavg:.4f})  {bw}  | {best}", fh)
    _save(best, bw, bavg)

    for p in range(args.max_passes):
        improved = False
        for knob, (mod, vals) in KNOBS.items():
            cur = best[knob]
            scored = []
            for v in vals:
                _, a = panel({**best, knob: v}, args.screen_n, args.screen_seed, args.step)
                scored.append((a, v))
            scored.sort(reverse=True, key=lambda t: t[0])
            _log(f"[p{p}] {knob} (cur={cur}) screen min-obj: "
                 + ", ".join(f"{v}={a:.3f}" for a, v in scored), fh)

            for _a, v in scored[:2]:                  # validate the top couple that differ
                if v == cur:
                    continue
                cand = {**best, knob: v}
                cw, cavg = panel(cand, args.holdout_n, args.hold_seed, args.step)
                if cavg <= bavg + args.adopt_margin:
                    continue
                if min(cw.values()) < args.min_opp:
                    _log(f"[p{p}]   {knob}={v}: holdout obj {cavg:.4f} but min opp "
                         f"{min(cw.values()):.3f} < {args.min_opp} -> REJECT (constraint)", fh)
                    continue
                best[knob] = v
                bw, bavg = cw, cavg
                set_config(best)
                improved = True
                _log(f"[p{p}]   ADOPT {knob}: {cur} -> {v}  holdout min {min(cw.values()):.4f} "
                     f"(obj {cavg:.4f})  {cw}  ({time.time()-t0:.0f}s)", fh)
                _save(best, bw, bavg)
                break
        if not improved:
            _log(f"[p{p}] no adoption this pass -> converged", fh)
            break

    fw, favg = panel(best, args.fresh_n, args.fresh_seed, args.step)
    _log(f"[final] best config: {best}", fh)
    _log(f"[final] holdout min {min(bw.values()):.4f} (obj {bavg:.4f})  |  FRESH (N={args.fresh_n}) "
         f"min {min(fw.values()):.4f} (obj {favg:.4f})  {fw}  ({time.time()-t0:.0f}s)", fh)
    _save(best, fw, favg)
    fh.close()
    if _POOL is not None:
        _POOL.close()
        _POOL.join()


if __name__ == "__main__":
    main()
