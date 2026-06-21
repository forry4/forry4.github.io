"""List every L1 card's turns_to_afford from a fresh start (no tokens/bonuses),
to see whether L1 cards really all share the same tta or differ by cost shape.
Specifically: is a 2-of-two-colors card (e.g. 2blue+2red) the same tta as a
3-distinct-colors card?"""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import random
from games.spender.ai.az import engine as E
from games.spender.ai.az import valuation as V

COLORS = ["w", "b", "g", "r", "k"]


def cf(ci):
    return "+".join(f"{E.COST[ci][i]}{COLORS[i]}" for i in range(5) if E.COST[ci][i])


s = E.new_game(random.Random(0))
seat = s.turn
rows = []
seen = set()
for ci in range(E.N_CARDS):
    if E.LEVEL_OF[ci] != 1:
        continue
    key = tuple(E.COST[ci])
    if key in seen:
        continue
    seen.add(key)
    tta = V.turns_to_afford(s, ci, seat)
    rows.append((tta, sum(E.COST[ci]), E.PTS[ci], COLORS[E.BONUS[ci]], cf(ci)))
rows.sort()
print("Every distinct L1 cost shape, fresh start (no tokens/bonuses):", flush=True)
print("  tta total pts bonus cost", flush=True)
for tta, tot, pts, bon, cost in rows:
    print(f"   {tta}    {tot}    {pts}    {bon}   {cost}", flush=True)
