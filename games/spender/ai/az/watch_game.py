"""Play one AZ-vs-heuristic game and print a human-readable play-by-play.

Usage:
    python -m games.spender.ai.az.watch_game \
        --az games/spender/ai/az/checkpoints/az_model.npz \
        --opp C2 --az-sims 300 --opp-iters 120 [--seed 42]
"""
from __future__ import annotations

import argparse
import random

from games.spender import main as inc

from . import actions as A
from . import engine as E
from .arena import _heuristic_action, _load_evaluator, _load_opp_weights
from .mcts import Search

_C = ["W", "B", "G", "R", "K", "Au"]  # color abbreviations


def _fmt_tokens(tok: list[int]) -> str:
    parts = [f"{_C[i]}:{tok[i]}" for i in range(6) if tok[i] > 0]
    return " ".join(parts) if parts else "none"


def _fmt_card(cid: int) -> str:
    if cid < 0:
        return "---"
    c = E.COST[cid]
    cost_str = " ".join(f"{_C[i]}:{c[i]}" for i in range(5) if c[i] > 0)
    return f"L{E.LEVEL_OF[cid]}[{E.PTS[cid]}pt +{_C[E.BONUS[cid]]} | {cost_str}]"


def _fmt_noble(nid: int) -> str:
    req = E.NOBLE_REQ[nid]
    req_str = " ".join(f"{_C[i]}:{req[i]}" for i in range(5) if req[i] > 0)
    return f"Noble[{E.NOBLE_PTS[nid]}pt | {req_str}]"


def _card_int(card_id) -> int:
    """Convert incumbent string card_id (e.g. 'L1-3') or int to engine int index."""
    if isinstance(card_id, int):
        return card_id
    return E.CARD_ID_BY_NAME.get(str(card_id), -1)


def _fmt_action(s: E.State, a: int) -> str:
    try:
        mv = A.action_to_move(s, a)
    except Exception:
        return A.action_name(a)
    t = mv["type"]
    if t == "take_gems":
        return f"take {'+'.join(_C[A.COLOR_NAMES.index(c)] for c in mv['colors'])}"
    if t == "reserve":
        if "card_id" in mv:
            return f"reserve {_fmt_card(_card_int(mv['card_id']))}"
        return f"reserve deck-L{mv.get('level', '?')}"
    if t == "buy":
        return f"BUY {_fmt_card(_card_int(mv['card_id']))}"
    if t == "discard":
        return f"discard {_C[A.COLOR_NAMES.index(mv['color'])]}"
    if t == "pick_noble":
        nid = E.NOBLE_ID_BY_NAME.get(mv.get("noble_id", ""), -1)
        return f"claim noble {_fmt_noble(nid)}" if nid >= 0 else "claim noble"
    return t


def watch(evaluate, weights: dict, *, az_sims: int, opp_iters: int,
          az_seat: int = 0, seed: int = 42) -> None:
    rng = random.Random(seed)
    s = E.new_game(rng)
    names = ["AZ", "C2"]
    if az_seat == 1:
        names = ["C2", "AZ"]

    print(f"\n{'='*60}")
    print(f"  {names[0]} (seat 0)  vs  {names[1]} (seat 1)   seed={seed}")
    print(f"{'='*60}")

    # Print nobles in play
    print("\nNobles in play:")
    for nid in s.nobles:
        print(f"  {_fmt_noble(nid)}")

    turn_n = 0
    while s.phase != E.OVER and s.ply < 400:
        seat = s.turn
        actor = names[seat]
        is_az = (seat == az_seat)

        # -- header ----------------------------------------------------------
        phase_label = {E.PLAY: "PLAY", E.DISCARD: "DISCARD", E.NOBLE: "NOBLE"}[s.phase]
        print(f"\n{'-'*60}")
        print(f"Ply {s.ply+1}  [{actor}]  phase={phase_label}  "
              f"score: AZ {s.points[az_seat]}  C2 {s.points[1-az_seat]}"
              + ("  <- FINAL ROUND" if s.final_trigger >= 0 else ""))

        # -- board (play phase only) ------------------------------------------
        if s.phase == E.PLAY:
            bank_str = "  ".join(
                f"{_C[i]}:{s.bank[i]}" for i in range(6) if s.bank[i] > 0
            )
            print(f"Bank: {bank_str}")
            for lvl in range(3):
                cards = [s.board[lvl * 4 + i] for i in range(4)]
                row = "  ".join(
                    f"[{i}]{_fmt_card(c)}" for i, c in enumerate(cards)
                )
                print(f"L{lvl+1}: {row}")

        # -- player state -----------------------------------------------------
        for seat_i, label in enumerate(names):
            tok = _fmt_tokens(s.tokens[seat_i])
            bon = " ".join(
                f"+{_C[c]}:{s.bonuses[seat_i][c]}"
                for c in range(5) if s.bonuses[seat_i][c] > 0
            ) or "none"
            resv = ", ".join(_fmt_card(c) for c in s.reserved[seat_i]) or "none"
            print(f"  {label}: {s.points[seat_i]}pt | tokens {tok} | "
                  f"bonuses {bon} | reserved {resv}")

        # -- pick action ------------------------------------------------------
        legal = E.legal_actions(s)
        if len(legal) == 1:
            a = legal[0]
            print(f"-> {actor} (forced): {_fmt_action(s, a)}")
        elif is_az:
            search = Search(s, rng, add_noise=False)
            visits = search.run(evaluate, az_sims)
            top = sorted(
                [(v, a) for a, v in enumerate(visits) if v > 0],
                reverse=True
            )[:6]
            print(f"  AZ top visits ({az_sims} sims):")
            for v, a in top:
                print(f"    {v:4d}  {_fmt_action(s, a)}")
            best_a = top[0][1]
            print(f"-> AZ plays: {_fmt_action(s, best_a)}")
            a = best_a
        else:
            a = _heuristic_action(s, weights, opp_iters)
            print(f"-> C2 plays: {_fmt_action(s, a)}")

        E.apply(s, a)
        turn_n += 1

    # -- end of game ----------------------------------------------------------
    print(f"\n{'='*60}")
    print("GAME OVER")
    print(f"  AZ  (seat {az_seat}): {s.points[az_seat]} pts, "
          f"{s.purchased_n[az_seat]} cards bought")
    print(f"  C2  (seat {1-az_seat}): {s.points[1-az_seat]} pts, "
          f"{s.purchased_n[1-az_seat]} cards bought")
    if s.winner == E.WIN_DRAW:
        print("Result: DRAW")
    elif s.winner == az_seat:
        print("Result: AZ WINS")
    else:
        print("Result: C2 WINS")
        margin = s.points[1-az_seat] - s.points[az_seat]
        card_margin = s.purchased_n[az_seat] - s.purchased_n[1-az_seat]
        print(f"  C2 won by {margin} points "
              f"({'fewer' if card_margin > 0 else 'more'} cards: "
              f"AZ bought {s.purchased_n[az_seat]}, C2 bought {s.purchased_n[1-az_seat]})")
    print(f"  Total plies: {s.ply}")
    print(f"{'='*60}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--az", required=True)
    ap.add_argument("--opp", default="C2")
    ap.add_argument("--az-sims", type=int, default=300)
    ap.add_argument("--opp-iters", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--az-seat", type=int, default=0, choices=[0, 1])
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    inc.USE_VALUE_LEAF = False
    evaluate = _load_evaluator(args.az, args.device)
    weights = _load_opp_weights(args.opp)
    watch(evaluate, weights, az_sims=args.az_sims, opp_iters=args.opp_iters,
          az_seat=args.az_seat, seed=args.seed)


if __name__ == "__main__":
    main()
