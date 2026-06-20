"""Self-gate autotuner for variant S — maximize candidate win rate vs FROZEN today's-S.

Tunes v_state/vsearch knobs (incl. the new RESERVE_PENALTY) by playing a CANDIDATE config
head-to-head against a FIXED frozen baseline = S exactly as committed today (RESERVE_PENALTY=0,
W_ENGINE_STK=0.4, C_PUCT=1.5, ...). Rationale: the heuristic panel is too weak to distinguish a good
S from a great one (it saturates ~0.8); a strong, equal opponent gives a sharp gradient.

Coordinate descent: for each knob, SCREEN its candidate values on a small CRN self-gate set (candidate
vs frozen, same decks, seats swapped), VALIDATE the best on a larger DISJOINT holdout, ADOPT if it
beats frozen by --adopt-margin. The frozen opponent stays FIXED (we maximize "beat today's S"); the
candidate accumulates adopted knob changes. Both sides run a full search, so each game is ~2x a
vs-panel game — keep N modest.

GUARD (the documented self-exploit / rock-paper-scissors trap): a config can beat THIS frozen-S
without being objectively stronger. So the FINAL candidate is ALSO measured vs the heuristic panel
{H3,H2,H2N,H2R}; if it regresses there, the vs-frozen gain is suspect (report side-by-side).

Writes best to vsearch_selfgate_best.json + a transcript to vsearch_selfgate.log.

Usage:
  python -m games.spender.ai.az.vsearch_selfgate --sims 120 --screen-n 60 --holdout-n 160 --workers 12
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import json
import logging
import math
import multiprocessing as mp
import random
import time

logging.getLogger("games.spender").setLevel(logging.ERROR)

from . import engine as E          # noqa: E402
from . import heuristic3 as H3     # noqa: E402
from . import v_state              # noqa: E402
from . import valuation3 as V3     # noqa: E402
from . import vsearch              # noqa: E402
from .vsearch_camp import OPP, play_one   # noqa: E402  (panel anchor)

PANEL = ["H3", "H2", "H2N", "H2R"]
_MODS = (vsearch, v_state, H3, V3)

# knob registry: name -> (defining module, candidate values). RESERVE_PENALTY first (the new lever);
# the rest mirror vsearch_autotune so the self-gate can re-find optima the weak panel couldn't.
KNOBS = {
    "RESERVE_PENALTY": (v_state, [0.0, 0.3, 0.6]),
    "W_PROGRESS":   (v_state, [1.0, 1.5, 2.0, 2.5]),
    "W_ENGINE_STK": (v_state, [0.2, 0.4, 0.8]),
    "W_NOBLE":      (v_state, [0.3, 0.6, 0.9]),
    "W_ECON":       (v_state, [0.0, 0.3, 0.6]),
    "W_POINTS":     (v_state, [0.8, 1.0, 1.3]),
    "SCALE":        (v_state, [6.0, 8.0, 10.0]),
    "WIN_CONVEX":   (v_state, [0.0, 0.1, 0.2]),
    "PROGRESS_TOPK": (v_state, [1, 2, 3]),
    "POLICY_TEMP":  (vsearch, [0.5, 0.7, 1.0]),
    "C_PUCT":       (vsearch, [1.0, 1.5, 2.0]),
    "H3_PICK_W":    (vsearch, [1.0, 1.5, 2.5]),
    "RESERVE_PRIOR_W": (vsearch, [0.3, 0.5, 0.7]),
}

_DIR = os.path.dirname(__file__)
LOG_PATH = os.path.join(_DIR, "vsearch_selfgate.log")
BEST_PATH = os.path.join(_DIR, "vsearch_selfgate_best.json")

_cache: dict = {}
_POOL = None
_WORKERS = 1
_SIMS = 120
_WP = 15            # win_points for the games (15 default; 21 for the S21 retune). Set in main + workers.
FROZEN: dict = {}


def _set(cfg_mod_attr, k, v):
    for mod in _MODS:
        if hasattr(mod, k):
            setattr(mod, k, v)
            return
    raise SystemExit(f"unknown knob '{k}'")


def set_config(cfg: dict) -> None:
    for k, v in cfg.items():
        _set(None, k, v)


def read_current() -> dict:
    return {k: getattr(mod, k) for k, (mod, _) in KNOBS.items()}


def _play_selfgate(cand: dict, frozen: dict, cand_seat: int, seed: int, sims: int,
                   max_plies: int = 400) -> float:
    """One candidate-vs-frozen game on board `seed`; `cand_seat` is the candidate's seat (seat 0 is
    ALWAYS the first mover — see engine.new_game), so cand_seat=0 => candidate moves first. The
    determinization RNG is reset to `seed` so paired games / CRN across configs share the search's
    random draws (differ only by config/first-player). Returns the candidate's score in {0,0.5,1}."""
    vsearch._RNG = random.Random(seed)          # reproducible determinization (CRN pairing)
    s = E.new_game(random.Random(seed), win_points=_WP)
    for _ in range(max_plies):
        if s.phase == E.OVER:
            break
        set_config(cand if s.turn == cand_seat else frozen)
        E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == cand_seat else 0.0


def _trial(cand, frozen, seed, sims):
    """One PAIRED trial on board `seed`: play it twice (candidate first, then frozen first) so the
    two halves differ only in who moves first -> first-player balanced + board variance cancelled.
    Returns the candidate's total over the 2 games (out of 2)."""
    return (_play_selfgate(cand, frozen, 0, seed, sims)      # candidate first
            + _play_selfgate(cand, frozen, 1, seed, sims))   # frozen first, same board


def _chunk(args):
    cand, frozen, seed_base, lo, hi, sims, wp = args
    global _WP
    _WP = wp
    return sum(_trial(cand, frozen, seed_base + g, sims) for g in range(lo, hi))


def score(cand: dict, n: int, seed: int) -> float:
    """Candidate win rate vs FROZEN over n PAIRED trials (= 2n games, first player swapped per board,
    CRN) from `seed`. Cached."""
    key = (tuple(sorted(cand.items())), n, seed, _SIMS)
    if key in _cache:
        return _cache[key]
    if _POOL is None:
        total = sum(_trial(cand, FROZEN, seed + g, _SIMS) for g in range(n))
    else:
        step = math.ceil(n / _WORKERS)
        tasks = [(cand, FROZEN, seed, lo, min(lo + step, n), _SIMS, _WP) for lo in range(0, n, step)]
        total = sum(_POOL.map(_chunk, tasks))
    _cache[key] = r = total / (2 * n)
    return r


def _panel_anchor(cand: dict, n: int, seed0: int, step: int) -> dict:
    """Candidate vs each heuristic-panel opponent (the RPS sanity check). Reuses vsearch_camp."""
    set_config(cand)
    out = {}
    for i, nm in enumerate(PANEL):
        sb = seed0 + i * step
        if _POOL is None:
            tot = sum(play_one(OPP[nm], j % 2, seed=sb + j, sims=_SIMS, win_points=_WP) for j in range(n))
        else:
            st = math.ceil(n / _WORKERS)
            tasks = [(nm, sb, lo, min(lo + st, n), _SIMS, cand, _WP) for lo in range(0, n, st)]
            tot = sum(_POOL.map(_panel_chunk, tasks))
        out[nm] = tot / n
    return out


def _panel_chunk(args):
    nm, sb, lo, hi, sims, cand, wp = args
    global _WP
    _WP = wp
    set_config(cand)
    opp = OPP[nm]
    return sum(play_one(opp, i % 2, seed=sb + i, sims=sims, win_points=wp) for i in range(lo, hi))


def _log(msg, fh):
    print(msg, flush=True)
    fh.write(msg + "\n")
    fh.flush()


def _save(cand, vs_frozen, panel):
    with open(BEST_PATH, "w") as f:
        json.dump({"candidate": cand, "vs_frozen": vs_frozen, "panel": panel,
                   "frozen": FROZEN, "sims": _SIMS}, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=120)
    ap.add_argument("--screen-n", type=int, default=60)
    ap.add_argument("--holdout-n", type=int, default=160)
    ap.add_argument("--panel-n", type=int, default=120)
    ap.add_argument("--max-passes", type=int, default=3)
    ap.add_argument("--adopt-margin", type=float, default=0.02)   # must beat frozen by this on holdout
    ap.add_argument("--screen-seed", type=int, default=200_000)
    ap.add_argument("--hold-seed", type=int, default=3_000_000)
    ap.add_argument("--panel-seed", type=int, default=130_000_000)
    ap.add_argument("--step", type=int, default=100_000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--win-points", type=int, default=15, help="retune for games to this many points (15/21)")
    args = ap.parse_args()

    global _POOL, _WORKERS, _SIMS, _WP, FROZEN
    _WORKERS = max(1, args.workers)
    _SIMS = args.sims
    _WP = args.win_points
    FROZEN = read_current()                 # today's committed S (the fixed opponent)
    if _WORKERS > 1:
        _POOL = mp.Pool(processes=_WORKERS)

    fh = open(LOG_PATH, "a")
    t0 = time.time()
    _log(f"\n===== vsearch_selfgate (vs FROZEN today's-S; sims={_SIMS} screen_n={args.screen_n} "
         f"holdout_n={args.holdout_n} workers={_WORKERS}) =====", fh)
    _log(f"[frozen] {FROZEN}", fh)

    best = read_current()
    bw = score(best, args.holdout_n, args.hold_seed)        # == 0.5 (candidate == frozen)
    _log(f"[start] best==frozen vs-frozen holdout = {bw:.4f} (expect ~0.5)", fh)

    for p in range(args.max_passes):
        improved = False
        for knob, (mod, vals) in KNOBS.items():
            cur = best[knob]
            scored = []
            for v in vals:
                if v == cur:
                    continue
                r = score({**best, knob: v}, args.screen_n, args.screen_seed)
                scored.append((r, v))
            if not scored:
                continue
            scored.sort(reverse=True)
            _log(f"[p{p}] {knob} (cur={cur}) screen vs-frozen: "
                 + ", ".join(f"{v}={r:.3f}" for r, v in scored), fh)
            for _r, v in scored[:2]:
                cand = {**best, knob: v}
                cw = score(cand, args.holdout_n, args.hold_seed)
                if cw > bw + args.adopt_margin:
                    best[knob] = v
                    bw = cw
                    improved = True
                    _log(f"[p{p}]   ADOPT {knob}: {cur} -> {v}  vs-frozen holdout {cw:.4f} "
                         f"({time.time()-t0:.0f}s)", fh)
                    _save(best, bw, None)
                    break
        if not improved:
            _log(f"[p{p}] no adoption -> converged", fh)
            break

    # final honest numbers + RPS guard
    fresh = score(best, args.holdout_n, args.hold_seed + 7_777)   # disjoint seeds
    panel = _panel_anchor(best, args.panel_n, args.panel_seed, args.step)
    base_panel = _panel_anchor(FROZEN, args.panel_n, args.panel_seed, args.step)
    _log(f"[final] candidate: {best}", fh)
    _log(f"[final] vs-frozen (fresh N={args.holdout_n}): {fresh:.4f}", fh)
    _log(f"[final] candidate panel: avg {sum(panel.values())/len(panel):.4f}  {panel}", fh)
    _log(f"[final] frozen    panel: avg {sum(base_panel.values())/len(base_panel):.4f}  {base_panel}", fh)
    dmin = min(panel.values()) - min(base_panel.values())
    _log(f"[final] RPS guard: candidate min-panel {min(panel.values()):.3f} vs frozen min-panel "
         f"{min(base_panel.values()):.3f} (delta {dmin:+.3f}) -> "
         f"{'OK (real)' if dmin >= -0.02 else 'SUSPECT (beats frozen but worse vs panel)'}", fh)
    _save(best, fresh, panel)
    fh.close()
    if _POOL is not None:
        _POOL.close()
        _POOL.join()


if __name__ == "__main__":
    main()
