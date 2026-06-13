"""Batched game driver for self-play data generation and net-vs-net matches.

Many games run concurrently in lockstep: each tick, every active game advances
its MCTS until it needs a net evaluation, requests are batched into (at most)
one forward pass per evaluator, results are distributed, repeat. This keeps
the GPU fed while the pure-Python engine works through simulations.

Forced moves (single legal action) skip search and are not recorded.
"""
from __future__ import annotations

import random
import time

import numpy as np

from . import engine as E
from . import features as F
from .mcts import Search, pick_action


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
              max_plies: int = 400, seed: int = 0, record: bool = True):
    """Play n_games. If eval_b is None this is self-play with eval_a.
    Otherwise A plays B (A's seat alternates per game; no recording).

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
        nonlocal finished, score_a, total_plies
        finished += 1
        total_plies += g.plies
        s = g.state
        if drawn or s.winner == E.WIN_DRAW:
            score_a += 0.5
            z_for = None
        else:
            z_for = s.winner
            if eval_b is not None and s.winner == g.seat_of_a:
                score_a += 1.0
        if record:
            for feats, pi, to_play in g.records:
                feats_out.append(feats)
                pis_out.append(pi)
                zs_out.append(0.0 if z_for is None else (1.0 if to_play == z_for else -1.0))

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
        "secs": time.time() - t0,
    }
    return examples, stats
