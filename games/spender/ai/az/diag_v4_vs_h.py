"""Behavioral diagnostics: how the v4 AZ net and the H heuristic play differently.

Plays the current best v4 net head-to-head vs H (seat-swapped) in the fast engine and
tallies, PER AGENT, average per-game: cards bought (total + by level + from-reserve),
reserves (board + blind deck), nobles claimed, takes (3/2-diff/1/2-same), discards,
final points, and game length. A direct same-games contrast of playstyle.

    python -m games.spender.ai.az.diag_v4_vs_h \
        --az games/spender/ai/az/checkpoints_v4_features/_work_best.npz --games 60 --az-sims 128
"""
from __future__ import annotations

import argparse
import random
import time
from collections import defaultdict

from games.spender import main as inc  # noqa: F401 (keeps weight-load parity w/ arena)

from . import engine as E
from . import heuristic as H
from .arena import _load_evaluator
from .mcts import Search


def _categorize(s: E.State, seat: int, a: int):
    """(category, level|None) for action `a` at `s`. Reads the card BEFORE apply."""
    if E.A_TAKE3 <= a < E.A_TAKE2D:
        return "take3", None
    if E.A_TAKE2D <= a < E.A_TAKE1:
        return "take2diff", None
    if E.A_TAKE1 <= a < E.A_TAKE2S:
        return "take1", None
    if E.A_TAKE2S <= a < E.A_PASS:
        return "take2same", None
    if a == E.A_PASS:
        return "pass", None
    if E.A_RES_BOARD <= a < E.A_RES_DECK:
        ci = s.board[a - E.A_RES_BOARD]
        return "reserve_board", (E.LEVEL_OF[ci] if ci >= 0 else None)
    if E.A_RES_DECK <= a < E.A_BUY_BOARD:
        return "reserve_deck", (a - E.A_RES_DECK) + 1
    if E.A_BUY_BOARD <= a < E.A_BUY_RESV:
        ci = s.board[a - E.A_BUY_BOARD]
        return "buy_board", (E.LEVEL_OF[ci] if ci >= 0 else None)
    if E.A_BUY_RESV <= a < E.A_DISCARD:
        ci = s.reserved[seat][a - E.A_BUY_RESV]
        return "buy_resv", E.LEVEL_OF[ci]
    if E.A_DISCARD <= a < E.A_NOBLE:
        return "discard", None
    return "noble_pick", None


def play(evaluate, az_seat: int, rng: random.Random, az_sims: int, max_plies: int = 400):
    s = E.new_game(rng)
    stat = {0: defaultdict(float), 1: defaultdict(float)}
    while s.phase != E.OVER and s.ply < max_plies:
        seat = s.turn
        if seat == az_seat:
            legal = E.legal_actions(s)
            if len(legal) == 1:
                a = legal[0]
            else:
                visits = Search(s, rng, add_noise=False).run(evaluate, az_sims)
                a = max(range(len(visits)), key=visits.__getitem__)
        else:
            a = H.choose_action(s, seat)
        cat, lvl = _categorize(s, seat, a)
        stat[seat][cat] += 1
        if cat.startswith("buy") and lvl:
            stat[seat][f"buy_L{lvl}"] += 1
        E.apply(s, a)
    for seat in (0, 1):
        stat[seat]["cards"] = s.purchased_n[seat]
        stat[seat]["nobles"] = len(s.nobles_won[seat])
        stat[seat]["points"] = s.points[seat]
    result = 0.5 if (s.phase != E.OVER or s.winner == E.WIN_DRAW) \
        else (1.0 if s.winner == az_seat else 0.0)
    return stat, result, s.ply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--az", required=True)
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--az-sims", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    evaluate = _load_evaluator(args.az, args.device)
    rng = random.Random(args.seed)
    agg = {"v4": defaultdict(float), "H": defaultdict(float)}
    wins = 0.0
    plies = 0
    t0 = time.time()
    for i in range(args.games):
        az_seat = i % 2
        stat, result, ply = play(evaluate, az_seat, rng, args.az_sims)
        wins += result
        plies += ply
        for k, v in stat[az_seat].items():
            agg["v4"][k] += v
        for k, v in stat[1 - az_seat].items():
            agg["H"][k] += v
        if (i + 1) % 10 == 0:
            print(f"  ... {i+1}/{args.games} (v4 win {wins/(i+1):.3f}, {time.time()-t0:.0f}s)", flush=True)

    n = args.games
    rows = [
        ("RESULT", None),
        ("win rate (v4)", "win"),
        ("final points", "points"),
        ("game length (plies)", "_plies"),
        ("BUYING", None),
        ("cards bought", "cards"),
        ("  buy L1", "buy_L1"),
        ("  buy L2", "buy_L2"),
        ("  buy L3", "buy_L3"),
        ("  buy from reserve", "buy_resv"),
        ("nobles claimed", "nobles"),
        ("RESERVING", None),
        ("reserves (board)", "reserve_board"),
        ("reserves (blind deck)", "reserve_deck"),
        ("GEM TAKES", None),
        ("take 3-different", "take3"),
        ("take 2-different", "take2diff"),
        ("take 1", "take1"),
        ("take 2-same", "take2same"),
        ("discards", "discard"),
        ("pass", "pass"),
    ]
    print(f"\n=== v4 (best, sims={args.az_sims}) vs H -- per-game averages over {n} games ===")
    print(f"{'metric':<24}{'v4':>10}{'H':>10}")
    print("-" * 44)
    for label, key in rows:
        if key is None:
            print(f"{label}")
            continue
        if key == "win":
            print(f"{label:<24}{wins/n:>10.3f}{'-':>10}")
        elif key == "_plies":
            print(f"{label:<24}{plies/n:>10.1f}{plies/n:>10.1f}")
        else:
            print(f"{label:<24}{agg['v4'][key]/n:>10.2f}{agg['H'][key]/n:>10.2f}")
    print(f"\n({time.time()-t0:.0f}s total)", flush=True)


if __name__ == "__main__":
    main()
