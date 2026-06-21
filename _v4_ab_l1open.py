"""A/B: forced L1 0-point opening (USE_FORCED_L1_OPENING) off vs on.

Until the bot buys its first card it may only pursue L1 0-point cards (buy the
best affordable, else take toward the best such target). Paired on the SAME fresh
seeds vs the A/B/C/C2 greedy mix. Screen @1000; if promising, confirm @2000
disjoint before shipping (the replication bar). ASCII only.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

OPP_NAMES = ["A", "B", "C", "C2"]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
START = int(sys.argv[2]) if len(sys.argv) > 2 else 90000
SEEDS = list(range(START, START + N))
N_SHARDS = 16


def _run(force_on, seeds):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    H.USE_FORCED_L1_OPENING = force_on
    opps = {n: _load_opp_weights(n) for n in OPP_NAMES}
    out = {}
    for g in seeds:
        random.seed(g * 7919 + 13)
        on = OPP_NAMES[g % len(OPP_NAMES)]
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opps[on], 1))
        out[g] = 1.0 if s.winner == v4 else (0.5 if s.winner == E.WIN_DRAW else 0.0)
    return out


def eval_job(job):
    label, force_on, seeds = job
    return label, _run(force_on, seeds)


if __name__ == "__main__":
    shards = [SEEDS[i::N_SHARDS] for i in range(N_SHARDS)]
    CONFIGS = {"off": False, "on": True}
    jobs = [(label, fo, sh) for label, fo in CONFIGS.items() for sh in shards]
    print(f"A/B forced-L1-opening: {len(SEEDS)} paired seeds vs "
          f"{'/'.join(OPP_NAMES)}", flush=True)
    merged = {label: {} for label in CONFIGS}
    tot = len(CONFIGS) * len(SEEDS)
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(eval_job, job) for job in jobs]
        for fut in as_completed(futs):
            label, out = fut.result()
            merged[label].update(out)
            done += len(out)
            if done % 4000 < len(out):
                el = time.time() - t0
                print(f"  [progress] {done}/{tot}  ({el:.0f}s, "
                      f"~{el/done*(tot-done):.0f}s left)", flush=True)

    n = len(SEEDS)
    off = merged["off"]
    on = merged["on"]
    p_off = sum(off.values()) / n
    p_on = sum(on.values()) / n
    diffs = [on[g] - off[g] for g in SEEDS]
    md = sum(diffs) / n
    var = sum((x - md) ** 2 for x in diffs) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    z = md / se if se > 0 else 0.0
    print(f"\noff winrate = {p_off:.4f}", flush=True)
    print(f"on  winrate = {p_on:.4f}", flush=True)
    print(f"diff (on-off) = {md:+.4f}   z = {z:+.2f}   "
          f"{'<<< ON better' if z >= 1.96 else ('<<< ON worse' if z <= -1.96 else '(ns)')}",
          flush=True)
