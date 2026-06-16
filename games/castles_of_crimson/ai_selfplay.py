"""Offline self-play arena for the Castles of Crimson MCTS AI.

Headless validation + (optional) tuning aid: imports the engine + ai only, never
starts the server or touches the DB (mirrors `games/spender/ai/train.py` discipline).

Usage:
    python -m games.castles_of_crimson.ai_selfplay --a hard --b random -n 10
    python -m games.castles_of_crimson.ai_selfplay --a hard --b normal -n 20

A "player kind" is either ``"random"`` (the trivial `bot`) or a difficulty name
from `ai.DIFFICULTY` ("normal"/"hard").
"""
from __future__ import annotations

import argparse
import random
import time

from . import engine
from . import ai
from . import bot


def _setup(game):
    while game["phase"] == "setup":
        pid = ai._actor(game)
        engine.apply_move(game, pid, ai._setup_move(game, pid))


def _drive_ai_turn(game, pid, difficulty, rng):
    for mv in ai.play_turn_plan(game, pid, difficulty=difficulty, rng=rng):
        if ai._actor(game) != pid:
            break
        if not engine.apply_move(game, pid, mv)[0]:
            break
    guard = 0
    while not engine.is_over(game) and ai._actor(game) == pid and guard < 60:
        guard += 1
        bot.play_turn(game, pid, rng)


def make_player(kind):
    """Return a callable (game, pid, rng) -> None that drives one full turn."""
    if kind == "random":
        return lambda game, pid, rng: bot.play_turn(game, pid, rng)
    return lambda game, pid, rng: _drive_ai_turn(game, pid, kind, rng)


def play_game(p0, p1, seed, rng):
    game = engine.new_game(["P0", "P1"], seed=seed)
    _setup(game)
    players = {"P0": p0, "P1": p1}
    guard = 0
    while not engine.is_over(game) and guard < 5000:
        guard += 1
        pid = ai._actor(game)
        if pid is None:
            break
        players[pid](game, pid, rng)
    return game


def arena(kind_a, kind_b, n=10, seed0=0):
    """`kind_a` vs `kind_b` over n games, ALTERNATING seats. Returns
    (win_rate_a, avg_pts_a, avg_pts_b). A tie counts as half a win."""
    pa, pb = make_player(kind_a), make_player(kind_b)
    a_wins = 0.0
    a_pts = b_pts = 0
    for i in range(n):
        rng = random.Random(1000 + seed0 + i)
        if i % 2 == 0:
            game = play_game(pa, pb, seed=seed0 + i, rng=rng)
            a_seat, b_seat = "P0", "P1"
        else:
            game = play_game(pb, pa, seed=seed0 + i, rng=rng)
            a_seat, b_seat = "P1", "P0"
        scores = engine.final_scores(game)
        winner = engine.winner(game)
        a_pts += scores[a_seat]
        b_pts += scores[b_seat]
        if winner == a_seat:
            a_wins += 1
        elif isinstance(winner, list) and a_seat in winner:
            a_wins += 0.5
    return a_wins / n, a_pts / n, b_pts / n


def main():
    ap = argparse.ArgumentParser(description="CoC MCTS AI arena")
    ap.add_argument("--a", default="hard", help="player A kind: random|normal|hard")
    ap.add_argument("--b", default="random", help="player B kind: random|normal|hard")
    ap.add_argument("-n", type=int, default=10, help="number of games (seats alternate)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    t = time.time()
    win_rate, a_pts, b_pts = arena(args.a, args.b, n=args.n, seed0=args.seed)
    print(f"{args.a} vs {args.b}: win rate {win_rate:.3f}  "
          f"(avg pts {a_pts:.1f} vs {b_pts:.1f})  over {args.n} games in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
