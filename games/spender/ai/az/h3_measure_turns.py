"""Measure the typical-game length curve for H3's turns_remaining estimator.

Plays H3-vs-H2 games offline; at every main (PLAY) turn it records the acting player's
(cards_owned, points) and, after the game ends, the actual number of that player's FUTURE
main turns (turns-left). Aggregates into a (cards, points) -> average turns-left table written
to turns_table.json, which valuation3 loads to estimate turns_remaining at runtime.

Both players' snapshots are recorded (turns-left is just game_end - now, independent of who
won; we store a won-count too for optional later analysis). H3 plays a representative "frontier"
config so the trajectories reflect decent play (the table is mildly self-referential -- re-measure
after big model changes).

Usage:
    python -m games.spender.ai.az.h3_measure_turns --games 4000 --workers 10
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import random
from collections import defaultdict

from . import engine as E
from . import heuristic2 as H2
from . import heuristic3 as H3
from . import valuation3 as V3

# representative H3 config for measurement (the best non-new-model "frontier" + stage blend)
H3_MEASURE = {"W_TEMPO": 0.1, "NOBLE_CLOSE_FLOOR": 0.3, "STAGE_K": 14, "ENG_TEMPO_DIV": 0.0,
              "STAGE_BLEND": True, "STAGE_CARD_OPP_W": 0.5, "STAGE_PTS_OPP_W": 0.5}

_DIR = os.path.dirname(__file__)
TABLE_PATH = os.path.join(_DIR, "turns_table.json")


def _set(cfg):
    for k, v in cfg.items():
        if hasattr(H3, k):
            setattr(H3, k, v)
        elif hasattr(V3, k):
            setattr(V3, k, v)


def _play_chunk(args):
    """Play games [lo, hi); return {(cards,points): [sum_turnsleft, count, won_count]}."""
    lo, hi = args
    _set(H3_MEASURE)
    local = defaultdict(lambda: [0.0, 0, 0])
    for seed in range(lo, hi):
        s = E.new_game(random.Random(seed))
        h3_seat = seed % 2
        snaps = {0: [], 1: []}              # per seat: (cards, points, gems) at each PLAY turn
        for _ in range(800):
            if s.phase == E.OVER:
                break
            if s.phase == E.PLAY:
                seat = s.turn
                snaps[seat].append((s.purchased_n[seat], s.points[seat], sum(s.tokens[seat])))
            actor = H3 if s.turn == h3_seat else H2
            E.apply(s, actor.choose_action(s, s.turn))
        won = [0, 0]
        if s.phase == E.OVER and s.winner in (0, 1):
            won[s.winner] = 1
        for seat in (0, 1):
            lst = snaps[seat]
            T = len(lst)
            for j, (c, p, g) in enumerate(lst):
                cell = local[(c, p, g)]
                cell[0] += (T - 1 - j)      # future main turns after this one
                cell[1] += 1
                cell[2] += won[seat]
    return dict(local)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    workers = max(1, args.workers)
    step = math.ceil(args.games / workers)
    tasks = [(lo, min(lo + step, args.games)) for lo in range(0, args.games, step)]

    merged = defaultdict(lambda: [0.0, 0, 0])
    if workers > 1:
        with mp.Pool(processes=workers) as pool:
            parts = pool.map(_play_chunk, tasks)
    else:
        parts = [_play_chunk(t) for t in tasks]
    for part in parts:
        for key, (s_tl, cnt, won) in part.items():
            m = merged[key]
            m[0] += s_tl
            m[1] += cnt
            m[2] += won

    # build table rows; report a coarse summary
    rows = []
    for (c, p, g), (s_tl, cnt, won) in sorted(merged.items()):
        rows.append([c, p, g, round(s_tl / cnt, 3), cnt, won])
    max_cards = max(r[0] for r in rows)
    max_points = max(r[1] for r in rows)
    max_gems = max(r[2] for r in rows)
    payload = {"rows": rows, "max_cards": max_cards, "max_points": max_points,
               "max_gems": max_gems, "n_games": args.games, "n_cells": len(rows)}
    with open(TABLE_PATH, "w") as f:
        json.dump(payload, f)
    print(f"[measure] {args.games} games -> {len(rows)} (cards,points,gems) cells; "
          f"max_cards={max_cards} max_points={max_points} max_gems={max_gems}", flush=True)
    # gem gradient at (0 cards, 0 pts): turn 0 (0 gems) vs after taking gems
    print("   gem gradient at (cards=0, pts=0):", flush=True)
    for g in (0, 3, 6, 9):
        hit = [r for r in rows if r[0] == 0 and r[1] == 0 and r[2] == g]
        if hit:
            r = hit[0]
            print(f"     gems={g}: {r[3]:>6} turns-left  (n={r[4]})", flush=True)
    for key in [(3, 2), (6, 5), (8, 8), (10, 11)]:
        hits = [r for r in rows if r[0] == key[0] and r[1] == key[1]]
        if hits:
            tot = sum(r[3] * r[4] for r in hits) / sum(r[4] for r in hits)
            print(f"   (cards={key[0]:>2}, pts={key[1]:>2}) -> {tot:>5.2f} turns-left (gem-avg, "
                  f"n={sum(r[4] for r in hits)})", flush=True)


if __name__ == "__main__":
    main()
