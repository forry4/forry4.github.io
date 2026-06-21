"""Scratch diagnostic #2 for the CURRENT committed v4 heuristic (no tweaks).
Reserve audit, deficit-based wasted-takes, points-passed-up, nobles, discards,
tempo vs C2, and a move trace."""
import random
import statistics
from collections import Counter

from games.spender import main as inc
from games.spender.ai.az import actions as A
from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic as H
from games.spender.ai.az import valuation as V
from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights

inc.USE_VALUE_LEAF = False
C2 = _load_opp_weights("C2")
avg = lambda xs: statistics.mean(xs) if xs else float("nan")

# ── A. behavioral + reserve audit + buy quality (v4 vs v4, 100 games) ────────
takes = wasted = reserves = buys = buys0 = discards = 0
buy_pts = 0
res_plies = []; res_threat = 0; res_gap = 0; res_levels = Counter()
res_deck = 0; buys_from_res = 0; nobles = 0
pass_early = pass_late = buys_early = buys_late = 0
disc_cols = Counter()
for g in range(100):
    s = E.new_game(random.Random(7000 + g))
    while s.phase != E.OVER and s.ply < 400:
        seat = s.turn
        val = V.Valuation(s)
        a = H.choose_action(s, seat)
        colors = H._take_colors(a)
        if colors is not None:
            takes += 1
            tgt = H._take_target(val, s, seat, H._targets(val, s, seat))
            if tgt is not None:
                tok = s.tokens[seat]
                before = val.gems_to_collect(tgt, seat)
                for c in colors:
                    tok[c] += 1
                after = val.gems_to_collect(tgt, seat)
                for c in colors:
                    tok[c] -= 1
                if after >= before:
                    wasted += 1
        elif E.A_RES_BOARD <= a < E.A_BUY_BOARD:
            reserves += 1; res_plies.append(s.ply)
            if a < E.A_RES_DECK:
                ci = s.board[a - E.A_RES_BOARD]
                res_levels[E.LEVEL_OF[ci]] += 1
                opp = 1 - seat
                if val.affordable_now(ci, opp) or val.turns_to_afford(ci, opp) <= 1:
                    res_threat += 1
                else:
                    res_gap += 1
            else:
                res_deck += 1
        elif E.A_BUY_BOARD <= a < E.A_DISCARD:
            ci = (s.board[a - E.A_BUY_BOARD] if a < E.A_BUY_RESV
                  else s.reserved[seat][a - E.A_BUY_RESV])
            buys += 1; buy_pts += E.PTS[ci]
            if E.PTS[ci] == 0:
                buys0 += 1
            if a >= E.A_BUY_RESV:
                buys_from_res += 1
            maxaff = 0
            for slot in range(12):
                cj = s.board[slot]
                if cj >= 0 and val.affordable_now(cj, seat):
                    maxaff = max(maxaff, E.PTS[cj])
            for cj in s.reserved[seat]:
                if val.affordable_now(cj, seat):
                    maxaff = max(maxaff, E.PTS[cj])
            late = s.purchased_n[seat] >= 6
            if maxaff > E.PTS[ci]:
                pass_late += late; pass_early += (not late)
            buys_late += late; buys_early += (not late)
        elif E.A_DISCARD <= a < E.A_NOBLE:
            discards += 1; disc_cols["wbgrkG"[a - E.A_DISCARD]] += 1
        b0 = len(s.nobles_won[0]) + len(s.nobles_won[1])
        E.apply(s, a)
        nobles += (len(s.nobles_won[0]) + len(s.nobles_won[1])) - b0

moves = takes + reserves + buys + discards
print("=== A. behavioral (v4-v4, 100 games) ===")
print(f"  move mix: takes {takes} buys {buys} reserves {reserves} discards {discards}")
print(f"  wasted takes (deficit-based): {wasted}/{takes} ({100*wasted/max(1,takes):.0f}%)")
print(f"  0-pt buys {100*buys0/max(1,buys):.0f}% | pts/card {buy_pts/max(1,buys):.2f}")
print(f"  RESERVE audit: rate {100*reserves/max(1,moves):.1f}% of moves | "
      f"board-lvls {dict(res_levels)} deck {res_deck} | "
      f"reason threat {res_threat}/gap {res_gap} | bought-from-reserve {buys_from_res}/{reserves}")
print(f"  reserve timing: opening<8ply {sum(p<8 for p in res_plies)}, "
      f"8-20 {sum(8<=p<20 for p in res_plies)}, 20+ {sum(p>=20 for p in res_plies)} | avg ply {avg(res_plies):.1f}")
print(f"  POINTS PASSED UP (affordable higher-pt card not bought): "
      f"early(<6 cards) {pass_early}/{buys_early} ({100*pass_early/max(1,buys_early):.0f}%) | "
      f"late {pass_late}/{buys_late} ({100*pass_late/max(1,buys_late):.0f}%)")
print(f"  nobles claimed/game {nobles/100:.2f} | discards by color {dict(disc_cols)}", flush=True)

# ── B. tempo milestones vs C2@60 (16 games) ──────────────────────────────────
print("\n=== B. tempo vs C2@60 (16 games) ===", flush=True)
ms = {5: [], 10: [], 15: []}; cms = {5: [], 10: [], 15: []}; wins = 0
for g in range(16):
    s = E.new_game(random.Random(5000 + g)); v4 = g % 2; c2 = 1 - v4
    rr = {5: None, 10: None, 15: None}; cc = {5: None, 10: None, 15: None}
    while s.phase != E.OVER and s.ply < 400:
        E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                else _heuristic_action(s, C2, 60))
        for m in (5, 10, 15):
            if rr[m] is None and s.points[v4] >= m: rr[m] = s.ply
            if cc[m] is None and s.points[c2] >= m: cc[m] = s.ply
    if s.winner == v4: wins += 1
    for m in (5, 10, 15):
        if rr[m] is not None: ms[m].append(rr[m])
        if cc[m] is not None: cms[m].append(cc[m])
for m in (5, 10, 15):
    print(f"  {m:>2} pts: v4 {avg(ms[m]):>5.1f} ({len(ms[m])}/16)  c2 {avg(cms[m]):>5.1f} ({len(cms[m])}/16)")
print(f"  v4 wins {wins}/16", flush=True)

# ── C. move trace vs C2 (seed 5000) ─────────────────────────────────────────
print("\n=== C. trace vs C2@60 (seed 5000) ===", flush=True)
s = E.new_game(random.Random(5000)); v4 = 0; t = 0
while s.phase != E.OVER and s.ply < 200:
    if s.turn == v4:
        t += 1
        a = H.choose_action(s, v4); name = A.action_name(a); extra = ""
        if E.A_BUY_BOARD <= a < E.A_DISCARD:
            ci = (s.board[a - E.A_BUY_BOARD] if a < E.A_BUY_RESV
                  else s.reserved[v4][a - E.A_BUY_RESV])
            extra = f" [{E.PTS[ci]}pt c{sum(E.COST[ci])}]"
        print(f"  t{t:>2} (v4 {s.points[v4]}/c2 {s.points[1-v4]}) {name}{extra}", flush=True)
        E.apply(s, a)
    else:
        E.apply(s, _heuristic_action(s, C2, 60))
print(f"  RESULT v4 {s.points[v4]} / c2 {s.points[1-v4]}", flush=True)
print("DONE", flush=True)
