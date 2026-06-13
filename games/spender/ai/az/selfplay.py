"""Batched game driver for self-play data generation and net-vs-net matches.

Many games run concurrently in lockstep: each tick, every active game advances
its MCTS until it needs a net evaluation, requests are batched into (at most)
one forward pass per evaluator, results are distributed, repeat. This keeps
the GPU fed while the pure-Python engine works through simulations.

Forced moves (single legal action) skip search and are not recorded.
"""
from __future__ import annotations

import math
import random
import time

import numpy as np

from . import engine as E
from . import features as F
from .mcts import Search, pick_action


def shaped_value(terminal: float, margin: int, weight: float, scale: float,
                 mode: str = "tanh") -> float:
    """Blend terminal win/loss (+/-1, 0 draw) with a point-margin term.

    mode="tanh": shaped = tanh(margin/scale) — bounded but SATURATES, so the
      per-point gradient vanishes at large deficits (a net stuck losing by ~12
      gets almost no signal to improve). Kept for back-compat.
    mode="linear": shaped = clamp(margin/scale, -1, 1) — constant per-point
      gradient until the clamp; the right choice when the net loses most games
      and needs a live signal to claw the margin back. Use scale >= the typical
      deficit (~15) so the operating range isn't clamped flat.
    """
    if weight <= 0.0:
        return terminal
    if mode == "linear":
        shaped = max(-1.0, min(1.0, margin / scale))
    else:
        shaped = math.tanh(margin / scale)
    return (1.0 - weight) * terminal + weight * shaped


class _Game:
    __slots__ = ("state", "search", "sims_done", "records", "plies", "rng",
                 "seat_of_a", "moves_made")

    def __init__(self, rng: random.Random, seat_of_a: int):
        self.state = E.new_game(rng)
        self.search = None
        self.sims_done = 0
        self.records = []           # (features, pi, to_play)
        self.plies = 0
        self.rng = rng
        self.seat_of_a = seat_of_a  # which seat evaluator A plays
        self.moves_made = 0


def run_games(n_games: int, eval_a, eval_b=None, *,
              n_sims: int = 128, max_parallel: int = 128,
              temperature: float = 1.0, temp_moves: int = 10,
              c_puct: float = 2.0, dirichlet_alpha: float = 0.5,
              dirichlet_eps: float = 0.25, add_noise: bool = True,
              max_plies: int = 400, seed: int = 0, record: bool = True,
              reward_shaping: float = 0.0, shaping_scale: float = 6.0,
              shaping_mode: str = "tanh"):
    """Play n_games. If eval_b is None this is self-play with eval_a.
    Otherwise A plays B (A's seat alternates per game; no recording).

    reward_shaping (0..1) blends the terminal win/loss (+/-1, 0 draw) value
    target with tanh(point_margin / shaping_scale) from each position's mover
    perspective. This breaks the degenerate self-play equilibrium where games
    finish 0-0 and the *fewest-cards* tiebreak rewards buying nothing: with
    shaping > 0 a 0-0 game is a true neutral and actually scoring points is
    what gets rewarded. shaping=0 reproduces the old pure-terminal target.

    Returns (examples, stats):
      examples: (features [N,Ff], policies [N,A], values [N]) float32 arrays
                (empty arrays when record=False)
      stats: {"score_a": float, "games": int, "avg_plies": float, "secs": float}
    """
    master = random.Random(seed)
    started = 0
    finished = 0
    score_a = 0.0
    total_plies = 0
    total_points = 0      # combined end-of-game points across both seats
    total_winpts = 0      # winner's points (0 on draw)
    feats_out, pis_out, zs_out = [], [], []
    t0 = time.time()

    def new_game():
        nonlocal started
        g = _Game(random.Random(master.randrange(2**62)), seat_of_a=started % 2)
        started += 1
        return g

    active = [new_game() for _ in range(min(max_parallel, n_games))]

    def evaluator_for(g: _Game):
        if eval_b is None:
            return eval_a
        return eval_a if g.state.turn == g.seat_of_a else eval_b

    def finish_game(g: _Game, drawn: bool):
        nonlocal finished, score_a, total_plies, total_points, total_winpts
        finished += 1
        total_plies += g.plies
        s = g.state
        total_points += s.points[0] + s.points[1]
        if not (drawn or s.winner == E.WIN_DRAW):
            total_winpts += s.points[s.winner]
        if drawn or s.winner == E.WIN_DRAW:
            score_a += 0.5
            z_for = None
        else:
            z_for = s.winner
            if eval_b is not None and s.winner == g.seat_of_a:
                score_a += 1.0
        if record:
            for feats, pi, to_play in g.records:
                terminal = 0.0 if z_for is None else (1.0 if to_play == z_for else -1.0)
                margin = s.points[to_play] - s.points[1 - to_play]
                z = shaped_value(terminal, margin, reward_shaping, shaping_scale,
                                 shaping_mode)
                feats_out.append(feats)
                pis_out.append(pi)
                zs_out.append(z)

    def step_move(g: _Game) -> bool:
        """Finish the current move decision. Returns False if game ended."""
        s = g.state
        visits = g.search.root.N
        total = sum(visits)
        if record and total > 0:
            pi = np.asarray(visits, dtype=np.float32)
            pi /= total
            g.records.append((F.encode(s), pi, s.turn))
        temp = temperature if g.moves_made < temp_moves else 0.0
        a = pick_action(visits, g.rng, temp)
        E.apply(s, a)
        g.search = None
        g.sims_done = 0
        g.plies += 1
        g.moves_made += 1
        if s.phase == E.OVER:
            finish_game(g, drawn=False)
            return False
        if g.plies >= max_plies:
            finish_game(g, drawn=True)
            return False
        return True

    while active:
        requests = []   # (game, feats, mask)
        next_active = []
        for g in active:
            alive = True
            req = None
            while alive and req is None:
                if g.search is None:
                    legal = E.legal_actions(g.state)
                    if len(legal) == 1:  # forced: skip search, don't record
                        E.apply(g.state, legal[0])
                        g.plies += 1
                        if g.state.phase == E.OVER:
                            finish_game(g, drawn=False)
                            alive = False
                        elif g.plies >= max_plies:
                            finish_game(g, drawn=True)
                            alive = False
                        continue
                    g.search = Search(g.state, g.rng, c_puct=c_puct,
                                      dirichlet_alpha=dirichlet_alpha,
                                      dirichlet_eps=dirichlet_eps,
                                      add_noise=add_noise and eval_b is None)
                if g.sims_done >= n_sims:
                    alive = step_move(g)
                    continue
                req = g.search.leaf_batch()
                if req is None:
                    g.sims_done += 1
            if not alive:
                if started < n_games:
                    next_active.append(new_game())
                continue
            requests.append((g, req[0], req[1]))
            next_active.append(g)
        active = next_active
        if not requests:
            continue

        if eval_b is None:
            groups = [(eval_a, requests)]
        else:
            ga = [r for r in requests if r[0].state.turn == r[0].seat_of_a]
            gb = [r for r in requests if r[0].state.turn != r[0].seat_of_a]
            groups = [(eval_a, ga), (eval_b, gb)]
        for ev, group in groups:
            if not group:
                continue
            feats = np.stack([r[1] for r in group])
            masks = np.stack([r[2] for r in group])
            probs, values = ev(feats, masks)
            for k, (g, _, _) in enumerate(group):
                g.search.apply_evals(probs[k], float(values[k]))
                g.sims_done += 1

    examples = (
        np.stack(feats_out) if feats_out else np.zeros((0, F.N_FEATURES), np.float32),
        np.stack(pis_out) if pis_out else np.zeros((0, E.N_ACTIONS), np.float32),
        np.asarray(zs_out, dtype=np.float32),
    )
    stats = {
        "score_a": score_a / max(1, finished),
        "games": finished,
        "avg_plies": total_plies / max(1, finished),
        "avg_points": total_points / max(1, finished),    # combined pts/game
        "avg_winpts": total_winpts / max(1, finished),     # winner's pts/game
        "secs": time.time() - t0,
    }
    return examples, stats


# ── Multiprocessing self-play ────────────────────────────────────────────────
# Self-play games are independent, so they parallelize across CPU cores with no
# quality cost (the only bottleneck is single-core Python MCTS; the net is tiny).
# Workers run CPU numpy inference (infer_np) off a .npz snapshot of the current
# net, so the GPU stays free for the training step. The worker fn and its
# imports are module-level for Windows 'spawn' picklability; create the Pool
# from inside an `if __name__ == "__main__"` entry point.

def _run_chunk(task: dict):
    """Pool worker: load numpy evaluator(s) from .npz and run a chunk of games."""
    from .infer_np import load_evaluator
    eval_a = load_evaluator(task["npz_a"])
    eval_b = load_evaluator(task["npz_b"]) if task.get("npz_b") else None
    (feats, pis, zs), stats = run_games(
        task["n_games"], eval_a, eval_b,
        n_sims=task["n_sims"], max_parallel=task["max_parallel"],
        temperature=task["temperature"], temp_moves=task["temp_moves"],
        c_puct=task["c_puct"], dirichlet_alpha=task["dirichlet_alpha"],
        dirichlet_eps=task["dirichlet_eps"], add_noise=task["add_noise"],
        max_plies=task["max_plies"], seed=task["seed"], record=task["record"],
        reward_shaping=task["reward_shaping"], shaping_scale=task["shaping_scale"],
        shaping_mode=task.get("shaping_mode", "tanh"))
    return feats, pis, zs, stats


def run_games_parallel(pool, n_workers: int, npz_a: str, n_games: int, *,
                       npz_b: str | None = None, n_sims: int = 128,
                       worker_parallel: int | None = None,
                       temperature: float = 1.0, temp_moves: int = 10,
                       c_puct: float = 2.0, dirichlet_alpha: float = 0.5,
                       dirichlet_eps: float = 0.25, add_noise: bool = True,
                       max_plies: int = 400, seed: int = 0, record: bool = True,
                       reward_shaping: float = 0.0, shaping_scale: float = 6.0,
                       shaping_mode: str = "tanh"):
    """Fan `n_games` across `n_workers` pool processes, each running run_games on
    a chunk. Same (examples, stats) contract as run_games; stats are merged
    (games summed, the rest game-weighted, secs = wall-clock of the fan-out).
    Per-worker seeds are widely spaced so games stay independent + reproducible.
    """
    base, rem = divmod(n_games, n_workers)
    chunks = [base + (1 if i < rem else 0) for i in range(n_workers)]
    tasks = []
    for i, c in enumerate(chunks):
        if c <= 0:
            continue
        tasks.append({
            "npz_a": npz_a, "npz_b": npz_b, "n_games": c, "n_sims": n_sims,
            "max_parallel": min(worker_parallel or c, c),
            "temperature": temperature, "temp_moves": temp_moves,
            "c_puct": c_puct, "dirichlet_alpha": dirichlet_alpha,
            "dirichlet_eps": dirichlet_eps, "add_noise": add_noise,
            "max_plies": max_plies, "seed": seed + i * 999331, "record": record,
            "reward_shaping": reward_shaping, "shaping_scale": shaping_scale,
            "shaping_mode": shaping_mode,
        })
    t0 = time.time()
    results = pool.map(_run_chunk, tasks)
    secs = time.time() - t0

    feats = np.concatenate([r[0] for r in results])
    pis = np.concatenate([r[1] for r in results])
    zs = np.concatenate([r[2] for r in results])
    tot_g = sum(r[3]["games"] for r in results)

    def wavg(key):
        return sum(r[3][key] * r[3]["games"] for r in results) / max(1, tot_g)

    stats = {
        "score_a": wavg("score_a"),
        "games": tot_g,
        "avg_plies": wavg("avg_plies"),
        "avg_points": wavg("avg_points"),
        "avg_winpts": wavg("avg_winpts"),
        "secs": secs,
    }
    return (feats, pis, zs), stats
