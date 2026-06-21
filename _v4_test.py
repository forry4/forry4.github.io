"""A/B test of reachability + steep-tempo changes (not committed).
Current-version baselines: reserves 213 conv 22%, 0-pt 64%, pts/card 0.64,
greedy-C2 0.688, vs-C2@60 reached-15 6/16, wins 4/16."""
import random
import statistics

from games.spender import main as inc
from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az import valuation as V
from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights

inc.USE_VALUE_LEAF = False
C2 = _load_opp_weights("C2")
avg = lambda xs: statistics.mean(xs) if xs else float("nan")

# Reserve audit + buy quality (v4 vs v4, 100 games)
reserves = buys_from_res = buys = buys0 = buy_pts = 0
for g in range(100):
    s = E.new_game(random.Random(7000 + g))
    while s.phase != E.OVER and s.ply < 400:
        seat = s.turn
        a = H.choose_action(s, seat)
        if E.A_RES_BOARD <= a < E.A_BUY_BOARD:
            reserves += 1
        elif E.A_BUY_BOARD <= a < E.A_DISCARD:
            ci = (s.board[a - E.A_BUY_BOARD] if a < E.A_BUY_RESV
                  else s.reserved[seat][a - E.A_BUY_RESV])
            buys += 1; buy_pts += E.PTS[ci]
            if E.PTS[ci] == 0: buys0 += 1
            if a >= E.A_BUY_RESV: buys_from_res += 1
        E.apply(s, a)
conv = 100 * buys_from_res / max(1, reserves)
print(f"reserves {reserves} (rg 190) | conversion {buys_from_res}/{reserves} "
      f"({conv:.0f}%, rg 26%) | 0-pt {100*buys0/max(1,buys):.0f}% (65) | "
      f"pts/card {buy_pts/max(1,buys):.2f} (0.62)", flush=True)

def greedy(n=16):
    w = d = 0
    for g in range(n):
        s = E.new_game(random.Random(3000 + g)); v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                    else _heuristic_action(s, C2, 1))
        if s.winner == v4: w += 1
        elif s.winner == E.WIN_DRAW: d += 1
    return (w + 0.5 * d) / n
print(f"vs greedy C2: {greedy():.3f} (rg 0.750)", flush=True)

r15 = wins = 0
for g in range(16):
    s = E.new_game(random.Random(5000 + g)); v4 = g % 2
    hit = False
    while s.phase != E.OVER and s.ply < 400:
        E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                else _heuristic_action(s, C2, 60))
        if not hit and s.points[v4] >= 15: hit = True; r15 += 1
    if s.winner == v4: wins += 1
print(f"vs C2@60: reached 15 {r15}/16 (rg 7/16) | wins {wins}/16 (rg 6/16)", flush=True)
print("DONE", flush=True)
