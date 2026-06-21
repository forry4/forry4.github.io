"""Where is the v4 heuristic actually weak? Per-opponent + tempo breakdown.

Plays the SHIPPED heuristic (all defaults) vs A, B, C, C2 SEPARATELY on fresh
seeds, reporting for each: win rate, the bot's avg points, the opponent's avg
points, avg cards bought by each, and avg game length. If the bot loses to a
WEAK opponent (A/B) that's a fundamental valuation flaw; if it scores far fewer
points than the opponent, it's getting out-raced on tempo (the documented "scores
4 while C2 scores 16" failure). This tells us which structural fix matters before
we touch a formula.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
from concurrent.futures import ProcessPoolExecutor

OPP_NAMES = ["A", "B", "C", "C2"]
SEEDS = list(range(3000, 3200))   # 200 fresh seeds per opponent


def _play_vs(opp_name):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    opp = _load_opp_weights(opp_name)
    w = d = 0
    bot_pts = opp_pts = bot_cards = opp_cards = plies = 0
    for g in SEEDS:
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, opp, 1))
        o = 1 - v4
        bot_pts += s.points[v4]
        opp_pts += s.points[o]
        bot_cards += s.purchased_n[v4]
        opp_cards += s.purchased_n[o]
        plies += s.ply
        if s.winner == v4:
            w += 1
        elif s.winner == E.WIN_DRAW:
            d += 1
    n = len(SEEDS)
    return (opp_name, (w + 0.5 * d) / n, bot_pts / n, opp_pts / n,
            bot_cards / n, opp_cards / n, plies / n)


def wilson(p, n, z=1.96):
    dd = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / dd, (c + half) / dd)


if __name__ == "__main__":
    n = len(SEEDS)
    print(f"per-opponent breakdown: shipped heuristic vs each, {n} fresh games",
          flush=True)
    print(f"  {'opp':4s} {'winrate':>16s}  {'botPts':>7s} {'oppPts':>7s}  "
          f"{'botCrd':>7s} {'oppCrd':>7s}  {'plies':>6s}", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=4) as ex:
        for r in ex.map(_play_vs, OPP_NAMES):
            rows.append(r)
    rows.sort(key=lambda r: r[1])
    for name, wr, bp, op, bc, oc, pl in rows:
        lo, hi = wilson(wr, n)
        print(f"  {name:4s}  {wr:.3f} [{lo:.2f},{hi:.2f}]  {bp:7.2f} {op:7.2f}  "
              f"{bc:7.2f} {oc:7.2f}  {pl:6.1f}", flush=True)
    avg = sum(r[1] for r in rows) / len(rows)
    print(f"\n  mean winrate vs mix: {avg:.3f}", flush=True)
