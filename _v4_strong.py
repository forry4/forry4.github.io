"""Pre-deploy gate: does a validated change hold vs a SEARCHING opponent?

The greedy-mix A/B uses opponents at 1 MCTS iter. This re-tests noble-completion
ON vs OFF against MCTS-C2 at OPP_ITERS (a much stronger, lookahead opponent),
paired on fresh seeds. A change that helps vs greedy but not vs search would be a
greedy-quirk exploit; noble-completion (strictly-correct VP info) should hold or
grow. Fewer games since MCTS is slow, but paired => still sensitive. ASCII only.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

OPP_ITERS = 80                      # lookahead opponent, ~3x faster than 150
SEEDS = list(range(6000, 6060))     # 60 fresh seeds (paired => still sensitive)
N_SHARDS = 16                       # fine-grained progress ticks (~4 games each)

CONFIGS = {
    "noble-comp OFF": {"USE_NOBLE_COMPLETION": False},
    "noble-comp ON":  {"USE_NOBLE_COMPLETION": True},
}
REF = "noble-comp OFF"


def _run(overrides, seeds):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    for k, v in overrides.items():
        setattr(H, k, v)
    opp = _load_opp_weights("C2")
    out = {}
    for g in seeds:
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            if s.turn == v4:
                a = H.choose_action(s, s.turn)
            else:
                a = _heuristic_action(s, opp, OPP_ITERS)
            E.apply(s, a)
        out[g] = 1.0 if s.winner == v4 else (0.5 if s.winner == E.WIN_DRAW else 0.0)
    return out


def eval_job(job):
    label, overrides, seeds = job
    return label, _run(overrides, seeds)


def wilson(p, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


if __name__ == "__main__":
    shards = [SEEDS[i::N_SHARDS] for i in range(N_SHARDS)]
    jobs = [(label, ov, sh) for label, ov in CONFIGS.items() for sh in shards]
    n = len(SEEDS)
    print(f"strong gate: noble ON vs OFF vs MCTS-C2@{OPP_ITERS}, {n} fresh games",
          flush=True)
    merged = {label: {} for label in CONFIGS}
    tot = len(CONFIGS) * n
    done = 0
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(eval_job, job) for job in jobs]
        for fut in as_completed(futs):
            label, out = fut.result()
            merged[label].update(out)
            done += len(out)
            el = time.time() - t0
            eta = el / done * (tot - done) if done else 0
            print(f"  [progress] {done}/{tot} games  ({el:.0f}s elapsed, "
                  f"~{eta:.0f}s left)  +{len(out)} {label}", flush=True)
    for label in CONFIGS:
        p = sum(merged[label].values()) / n
        lo, hi = wilson(p, n)
        print(f"  {p:.3f} [{lo:.3f},{hi:.3f}]  {label}", flush=True)
    rv = merged[REF]
    cv = merged["noble-comp ON"]
    diffs = [cv[g] - rv[g] for g in SEEDS]
    md = sum(diffs) / n
    var = sum((x - md) ** 2 for x in diffs) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    z = md / se if se > 0 else 0.0
    better = sum(1 for x in diffs if x > 0)
    worse = sum(1 for x in diffs if x < 0)
    print(f"\n  paired diff (ON - OFF): {md:+.4f}  z={z:+.2f}  "
          f"({better} better / {worse} worse)", flush=True)
