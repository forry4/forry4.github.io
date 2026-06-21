"""Diagnose the hoard-then-discard bug: bot takes gems for many turns, hits the
10-token cap, discards, never buys. Finds a game where the v4 bot discards in the
opening, then traces WHY it takes instead of buying (affordable cards + card_value
+ the buy-vs-gem gate outcome at each take). ASCII output. Touches nothing deployed.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import random
from games.spender import main as inc
from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az import valuation as V
from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights

inc.USE_VALUE_LEAF = False


def _kind(a):
    if E.A_TAKE3 <= a < E.A_TAKE2D:
        return "take3"
    if E.A_TAKE2D <= a < E.A_TAKE1:
        return "take2diff"
    if E.A_TAKE1 <= a < E.A_TAKE2S:
        return "take1"
    if E.A_TAKE2S <= a < E.A_PASS:
        return "take2same"
    if a == E.A_PASS:
        return "pass"
    if E.A_RES_BOARD <= a < E.A_BUY_BOARD:
        return "reserve"
    if E.A_BUY_BOARD <= a < E.A_DISCARD:
        return "BUY"
    if E.A_DISCARD <= a < E.A_NOBLE:
        return "discard"
    return "noble"


def find_worst(opp, n=120):
    worst = None
    for g in range(n):
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        v4 = g % 2
        discards = first_buy = 0
        first_buy = None
        while s.phase != E.OVER and s.ply < 400:
            if s.turn == v4:
                if s.phase == E.DISCARD:
                    discards += 1
                a = H.choose_action(s, s.turn)
                if first_buy is None and s.phase == E.PLAY and E.A_BUY_BOARD <= a < E.A_DISCARD:
                    first_buy = s.ply
            else:
                a = _heuristic_action(s, opp, 1)
            E.apply(s, a)
        early = sum(1 for _ in range(0))  # placeholder
        score = discards * 100 + (first_buy or 60)
        if worst is None or score > worst[0]:
            worst = (score, g, discards, first_buy)
    return worst


def trace(g, opp, max_ply=34):
    random.seed(g * 7919 + 13)
    s = E.new_game(random.Random(g))
    v4 = g % 2
    print(f"\n=== trace seed {g} (v4 = seat {v4}) ===", flush=True)
    while s.phase != E.OVER and s.ply < max_ply:
        if s.turn == v4:
            val = V.Valuation(s)
            tok = s.tokens[v4]
            a = H.choose_action(s, v4)
            k = _kind(a)
            if s.phase == E.PLAY:
                line = (f"ply {s.ply:2d} tok={sum(tok)}({tok[:5]} g{tok[5]}) "
                        f"bon={s.bonuses[v4]} pts={s.points[v4]} -> {k}")
                print(line, flush=True)
                if k.startswith("take") or k == "reserve":
                    buys = []
                    for slot in range(12):
                        ci = s.board[slot]
                        if ci >= 0 and V.affordable_now(s, ci, v4):
                            buys.append((round(H.card_value(val, s, ci, v4), 2),
                                         E.PTS[ci], V.discount_count(s, ci, v4),
                                         list(E.COST[ci])))
                    buys.sort(reverse=True)
                    if buys:
                        print(f"        affordable now (cv,pts,disc,cost): {buys[:4]}"
                              f"   BUY_FLOOR={H.BUY_FLOOR}", flush=True)
                    else:
                        print(f"        (no affordable card)", flush=True)
                    tgt = H._take_target(val, s, v4, H._targets(val, s, v4))
                    if tgt is not None and tgt >= 0:
                        print(f"        take-target: cost={list(E.COST[tgt])} "
                              f"pts={E.PTS[tgt]} cv={round(H.card_value(val,s,tgt,v4),2)} "
                              f"tta={V.turns_to_afford(s,tgt,v4)}", flush=True)
            else:
                print(f"ply {s.ply:2d} phase={s.phase} -> {k}", flush=True)
        else:
            a = _heuristic_action(s, opp, 1)
        E.apply(s, a)


if __name__ == "__main__":
    opp = _load_opp_weights("C2")
    score, g, discards, first_buy = find_worst(opp)
    print(f"worst opening: seed {g}  discards={discards}  first_buy_ply={first_buy}",
          flush=True)
    trace(g, opp)
