"""Diagnostic: does end-game defense reduce 'reached 15 first but lost'?

Plays the v4 bot as the FIRST player (seat 0, the side whose 15 lets the opponent
take a final turn) vs C2, with USE_ENDGAME_DEFENSE off then on, on the SAME seeds.
Counts games where the bot triggered the final round (final_trigger == bot) but the
opponent still won -- the exact failure the feature targets -- plus overall win rate.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import random
from concurrent.futures import ProcessPoolExecutor

SEEDS = list(range(60000, 60800))    # 800 games, bot always first player
N_SHARDS = 8


def _run(job):
    defense, seeds = job
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    H.USE_ENDGAME_DEFENSE = defense
    opp = _load_opp_weights("C2")
    wins = trig_but_lost = 0
    for g in seeds:
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        v4 = 0                                   # bot is the FIRST player
        while s.phase != E.OVER and s.ply < 400:
            a = H.choose_action(s, s.turn) if s.turn == v4 \
                else _heuristic_action(s, opp, 1)
            E.apply(s, a)
        if s.winner == v4:
            wins += 1
        if s.final_trigger == v4 and s.winner != v4:
            trig_but_lost += 1
    return defense, wins, trig_but_lost, len(seeds)


if __name__ == "__main__":
    shards = [SEEDS[i::N_SHARDS] for i in range(N_SHARDS)]
    jobs = [(d, sh) for d in (False, True) for sh in shards]
    agg = {False: [0, 0, 0], True: [0, 0, 0]}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for defense, w, tbl, n in ex.map(_run, jobs):
            agg[defense][0] += w
            agg[defense][1] += tbl
            agg[defense][2] += n
    print(f"v4 as FIRST player vs C2, {len(SEEDS)} games:", flush=True)
    for defense in (False, True):
        w, tbl, n = agg[defense]
        tag = "ON " if defense else "OFF"
        print(f"  defense {tag}: win {w/n:.3f}   'reached 15 first but LOST' = "
              f"{tbl} ({100*tbl/n:.1f}% of games)", flush=True)
