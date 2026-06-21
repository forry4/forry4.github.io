"""Diagnostic: on turn 1, which card does _take_target FOCUS on, and what gems
does the bot take? Tests whether the focus (argmax value - 0.6*tta) differs from
the highest card_value card, explaining a take that serves a lower card."""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import random
from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az import valuation as V

COLORS = ["w", "b", "g", "r", "k"]


def cf(ci):
    return "+".join(f"{E.COST[ci][i]}{COLORS[i]}" for i in range(5) if E.COST[ci][i])


for seed in range(8):
    s = E.new_game(random.Random(seed))
    seat = s.turn
    val = V.Valuation(s)
    targets = H._targets(val, s, seat)
    focus = H._take_target(val, s, seat, targets)
    a = H.choose_action(s, seat)
    cols = H._take_colors(a)
    top_ci = targets[0][1]
    flag = "" if focus == top_ci else "  <<< FOCUS != top-value card"
    print(f"seed {seed}:{flag}", flush=True)
    for tv, ci, idx, kind in targets[:4]:
        mark = " <-FOCUS" if ci == focus else ""
        sc = tv - H.TAKE_TEMPO * val.turns_to_afford(ci, seat)
        print(f"   v={tv:.3f} score={sc:+.3f} pts={E.PTS[ci]} cost={cf(ci):9s} "
              f"tta={val.turns_to_afford(ci, seat)} bonus={COLORS[E.BONUS[ci]]}{mark}",
              flush=True)
    took = [COLORS[c] for c in cols] if cols else cols
    print(f"   -> took {took}", flush=True)
