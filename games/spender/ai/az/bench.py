"""Engine throughput benchmark: random playouts, moves/second on one core.

Run: python -m games.spender.ai.az.bench
Target: >=30k moves/s/core (plan M1). Informational, not a test.
"""
import random
import time

from . import engine as E


def bench(n_games: int = 2000, seed: int = 0) -> None:
    rng = random.Random(seed)
    moves = 0
    finished = 0
    t0 = time.perf_counter()
    for _ in range(n_games):
        s = E.new_game(rng)
        for _ply in range(600):
            if s.phase == E.OVER:
                finished += 1
                break
            acts = E.legal_actions(s)
            E.apply(s, acts[rng.randrange(len(acts))])
            moves += 1
    dt = time.perf_counter() - t0
    print(f"{n_games} games ({finished} finished), {moves} moves in {dt:.2f}s "
          f"-> {moves/dt:,.0f} moves/s, {n_games/dt:,.1f} games/s")


if __name__ == "__main__":
    bench()
