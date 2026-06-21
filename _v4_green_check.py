"""If the green 2blue+2red card is genuinely the take-FOCUS, does the bot take
blue (toward it) or not? Put that card on the board with a black-needing card and
trace the focus + the take."""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import random
from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az import valuation as V

COLORS = ["w", "b", "g", "r", "k"]
GREEN, BLACK = 2, 4


def cf(ci):
    return "+".join(f"{E.COST[ci][i]}{COLORS[i]}" for i in range(5) if E.COST[ci][i])


# the green-bonus L1 card costing 2 blue + 2 red
gc = next(ci for ci in range(E.N_CARDS) if E.LEVEL_OF[ci] == 1
          and E.BONUS[ci] == GREEN and tuple(E.COST[ci]) == (0, 2, 0, 2, 0))
# an L1 card that needs black (so the need-vector has a reason to grab black)
blk = next(ci for ci in range(E.N_CARDS) if E.LEVEL_OF[ci] == 1
           and E.COST[ci][BLACK] > 0 and ci != gc)

s = E.new_game(random.Random(0))
seat = s.turn
for slot in range(12):
    s.board[slot] = -1
s.board[0] = gc
s.board[4] = blk

val = V.Valuation(s)
targets = H._targets(val, s, seat)
focus = H._take_target(val, s, seat, targets)
a = H.choose_action(s, seat)
cols = H._take_colors(a)
print(f"green card gc = {cf(gc)} (bonus {COLORS[E.BONUS[gc]]})", flush=True)
print(f"black-needing card = {cf(blk)} (bonus {COLORS[E.BONUS[blk]]})", flush=True)
print("targets by value:", flush=True)
for tv, ci, idx, kind in targets:
    print(f"   v={tv:.3f} cost={cf(ci):9s} tta={val.turns_to_afford(ci, seat)}"
          f"{'  <-FOCUS' if ci == focus else ''}", flush=True)
print(f"-> took {[COLORS[c] for c in cols] if cols else cols}  "
      f"(blue taken? {'b' in [COLORS[c] for c in (cols or [])]})", flush=True)
