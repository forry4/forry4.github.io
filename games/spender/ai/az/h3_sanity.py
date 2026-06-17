"""Sanity checks on H3's engine/take value behavior (the user's three invariants).

(a) reducing a 5-pt card's TEMPO 2->1 should raise its take value MORE than 7->6 (any gem cost).
(b) reducing a 5-pt card's GEM cost 7->6 should raise take value MORE than 14->13 (any tempo).
(c) the more white-bonus cards on the board, the higher a steep-white card's POTENTIAL value
    should be -- WITHOUT its take value rising.

(a)/(b) are probed on the real take formula (validated against components() first); (c) is probed
on real constructed states. Run: python -m games.spender.ai.az.h3_sanity
"""
from __future__ import annotations

import random

from . import engine as E
from . import heuristic3 as H3
from . import valuation3 as V3

WHITE, BLACK = 0, 4


def _take_formula(point, engine, tempo, gem, gold, T):
    """The exact take_value assembly (mirrors heuristic3.components)."""
    mult = T - tempo
    eng_term = engine * H3.W_ENGINE * (mult if mult > 0.0 else 0.0)
    cost = H3.W_TEMPO * tempo + H3.W_GEM * gem + H3.W_GOLD * gold
    return (eng_term + point) / (1.0 + cost)


def _validate_formula():
    """Confirm _take_formula matches components() on a constructed single-white-need state."""
    s = E.new_game(random.Random(0))
    seat = 0
    s.purchased_n = [0, 0]
    s.points = [0, 0]
    s.tokens = [[0] * 6, [0] * 6]
    # pick a card; make it need exactly 3 white (cover other colors with bonuses)
    X = max(range(len(E.COST)), key=lambda c: E.COST[c][WHITE])
    need = 3
    bon = [E.COST[X][c] for c in range(5)]
    bon[WHITE] = max(0, E.COST[X][WHITE] - need)
    s.bonuses = [bon, [0] * 5]
    val = V3.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    take, eng, pt, cost = H3.components(val, s, X, seat)
    T = val.turns_remaining()
    tempo = val.tempo(X, seat)
    raw_eng = val.engine_value(X, seat)   # components returns the POST-multiplier engine; pass raw here
    mine = _take_formula(pt, raw_eng, tempo, val.gem_cost(X, seat), val.gold_cost(X, seat), T)
    ok = abs(mine - take) < 1e-9
    print(f"[validate] formula vs components: {mine:.6f} vs {take:.6f}  {'OK' if ok else 'MISMATCH'}")
    return ok


def check_a():
    print("\n(a) TEMPO: reduce 5pt card 2->1 vs 7->6 (engine=2.0, T=24)")
    T, eng, pt = 24.0, 2.0, 5.0
    for extra_gem in (0, 4, 8):    # "regardless of gem cost": fixed extra gem from other colors
        # a +1 in the bottleneck color drops tempo AND gem by 1 (gold tracks the bottleneck)
        def tk(tempo):
            gem = tempo + extra_gem
            gold = max(0, tempo - 2)
            return _take_formula(pt, eng, tempo, gem, gold, T)
        d_lo = tk(1) - tk(2)
        d_hi = tk(6) - tk(7)
        verdict = "PASS" if d_lo > d_hi else "FAIL"
        print(f"   extra_gem={extra_gem}: dtake(2->1)={d_lo:.4f}  dtake(7->6)={d_hi:.4f}   {verdict}")


def check_b():
    print("\n(b) GEM: reduce 5pt card 7->6 vs 14->13 (engine=2.0, T=24)")
    T, eng, pt = 24.0, 2.0, 5.0
    for tempo in (1, 3, 7):        # "regardless of tempo": a non-bottleneck +1 drops gem only
        def tk(gem):
            gold = max(0, tempo - 2)
            return _take_formula(pt, eng, tempo, gem, gold, T)
        d_lo = tk(6) - tk(7)
        d_hi = tk(13) - tk(14)
        verdict = "PASS" if d_lo > d_hi else "FAIL"
        print(f"   tempo={tempo}: dtake(7->6)={d_lo:.4f}  dtake(14->13)={d_hi:.4f}   {verdict}")


def check_c():
    print("\n(c) REACHABILITY: steep-white card potential vs # white-bonus cards on board")
    # X: steep white cost, bonus NOT white (so its own engine value is about a different color)
    cands = [c for c in range(len(E.COST)) if E.BONUS[c] != WHITE and E.COST[c][WHITE] >= 5]
    X = max(cands, key=lambda c: E.COST[c][WHITE])
    whites = [c for c in range(len(E.COST)) if E.BONUS[c] == WHITE and c != X]
    print(f"   X=card {X} (white cost {E.COST[X][WHITE]}, bonus color {E.BONUS[X]}, {E.PTS[X]}pt); "
          f"{len(whites)} white-bonus cards available")
    for reach_w in (0.0, 0.3):
        V3.POT_REACH_W = reach_w
        row = []
        for k in (0, 2, 4, 6):
            s = E.new_game(random.Random(1))
            seat = 0
            s.purchased_n = [0, 0]; s.points = [0, 0]
            s.bonuses = [[0] * 5, [0] * 5]; s.tokens = [[0] * 6, [0] * 6]
            s.board = [-1] * 12
            s.board[0] = X
            for i in range(k):
                s.board[1 + i] = whites[i]
            val = V3.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
            pot = val.potential_value(X, seat)
            tk = H3.take_value(val, s, X, seat)
            row.append((k, pot, tk))
        desc = ", ".join(f"k={k}:pot={p:.3f},take={t:.3f}" for k, p, t in row)
        rising = row[-1][1] > row[0][1] + 1e-9
        print(f"   POT_REACH_W={reach_w}: {desc}   potential {'RISES' if rising else 'FLAT'}")
    V3.POT_REACH_W = 0.0


def main():
    _validate_formula()
    check_a()
    check_b()
    check_c()


if __name__ == "__main__":
    main()
