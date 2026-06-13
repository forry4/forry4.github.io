"""League self-play: the training net plays recorded games against a POOL of
opponents (heuristic A/B/C2 + frozen past AZ checkpoints), not only itself.

Why: pure self-play plateaued at ~0.03 vs C2 (iters 9 and 27 identical) — the
net got better at beating its own clones but never learned C2's style because it
never saw it. Training *against* the real targets is the strength lever. See
CLAUDE.md "self-play ceiling".

Only the training net's moves are recorded (we learn to BEAT opponents, not to
imitate them). Value targets use the same reward shaping as selfplay.run_games
(terminal +/-1 blended with tanh(point_margin/scale)) — crucial here because the
net loses most early games, and the margin term turns "lost by 2" vs "lost by
15" into a usable gradient.

Opponent moves are NOT batchable (heuristic = incumbent MCTS in dict format;
past-AZ = its own determinized PUCT), so league games run one-at-a-time inside
pool workers rather than through selfplay's lockstep batched driver.
"""
from __future__ import annotations

import math
import random
import time

import numpy as np

from games.spender import main as inc

from . import actions as A
from . import engine as E
from . import features as F
from .arena import _heuristic_action, _load_opp_weights
from .infer_np import load_evaluator
from .mcts import Search, pick_action


def _az_opponent_action(evaluate, s: E.State, rng: random.Random, n_sims: int) -> int:
    """A frozen-AZ opponent's move: greedy (no noise) PUCT with its own net."""
    legal = E.legal_actions(s)
    if len(legal) == 1:
        return legal[0]
    search = Search(s, rng, add_noise=False)
    visits = search.run(evaluate, n_sims)
    return max(range(len(visits)), key=visits.__getitem__)


def play_recorded_game(net_eval, opponent_fn, net_seat: int, rng: random.Random, *,
                       n_sims: int, temperature: float, temp_moves: int,
                       c_puct: float = 2.0, dirichlet_alpha: float = 0.5,
                       dirichlet_eps: float = 0.25, add_noise: bool = True,
                       max_plies: int = 400, reward_shaping: float = 0.5,
                       shaping_scale: float = 6.0):
    """Play one game; record only the net's decisions. Returns
    (feats[k,F], pis[k,A], zs[k], result) where result is the net's game score
    in {0,0.5,1} and net/opp final points for stats."""
    s = E.new_game(rng)
    records = []  # (features, pi, to_play)
    moves_made = 0
    while s.phase != E.OVER and s.ply < max_plies:
        if s.turn == net_seat:
            legal = E.legal_actions(s)
            if len(legal) == 1:
                E.apply(s, legal[0])
                continue
            search = Search(s, rng, c_puct=c_puct, dirichlet_alpha=dirichlet_alpha,
                            dirichlet_eps=dirichlet_eps, add_noise=add_noise)
            visits = search.run(net_eval, n_sims)
            total = sum(visits)
            if total > 0:
                pi = np.asarray(visits, dtype=np.float32)
                pi /= total
                records.append((F.encode(s), pi, s.turn))
            temp = temperature if moves_made < temp_moves else 0.0
            E.apply(s, pick_action(visits, rng, temp))
            moves_made += 1
        else:
            E.apply(s, opponent_fn(s))

    drawn = s.phase != E.OVER or s.winner == E.WIN_DRAW
    if drawn:
        result, z_for = 0.5, None
    else:
        result = 1.0 if s.winner == net_seat else 0.0
        z_for = s.winner
    feats, pis, zs = [], [], []
    for f, pi, to_play in records:
        terminal = 0.0 if z_for is None else (1.0 if to_play == z_for else -1.0)
        if reward_shaping > 0.0:
            margin = s.points[to_play] - s.points[1 - to_play]
            z = (1.0 - reward_shaping) * terminal + reward_shaping * math.tanh(margin / shaping_scale)
        else:
            z = terminal
        feats.append(f)
        pis.append(pi)
        zs.append(z)
    return feats, pis, zs, result, s.points[net_seat], s.points[1 - net_seat]


def _make_opponent_fn(spec: dict, rng: random.Random):
    """Build an opponent move-fn from a picklable spec."""
    if spec["kind"] == "heur":
        weights = _load_opp_weights(spec["variant"])
        opp_iters = spec["opp_iters"]
        return lambda s: _heuristic_action(s, weights, opp_iters)
    if spec["kind"] == "az":
        ev = load_evaluator(spec["npz"])
        n = spec["opp_sims"]
        return lambda s: _az_opponent_action(ev, s, rng, n)
    raise ValueError(f"unknown opponent kind: {spec['kind']}")


def _league_worker(task: dict):
    """Pool worker: net (from npz) plays `n_games` vs one opponent spec.
    Records only the net's moves. Returns (feats, pis, zs, stats)."""
    inc.USE_VALUE_LEAF = False
    rng = random.Random(task["seed"])
    net_eval = load_evaluator(task["net_npz"])
    opponent_fn = _make_opponent_fn(task["spec"], rng)
    feats_all, pis_all, zs_all = [], [], []
    score = 0.0
    for i in range(task["n_games"]):
        f, p, z, result, _, _ = play_recorded_game(
            net_eval, opponent_fn, i % 2, rng,
            n_sims=task["n_sims"], temperature=task["temperature"],
            temp_moves=task["temp_moves"], dirichlet_eps=task["dirichlet_eps"],
            add_noise=task["add_noise"], reward_shaping=task["reward_shaping"],
            shaping_scale=task["shaping_scale"])
        feats_all.extend(f)
        pis_all.extend(p)
        zs_all.extend(z)
        score += result
    label = task["spec"].get("variant") or task["spec"].get("label", "az")
    stats = {"label": label, "games": task["n_games"], "net_score": score}
    feats = np.stack(feats_all) if feats_all else np.zeros((0, F.N_FEATURES), np.float32)
    pis = np.stack(pis_all) if pis_all else np.zeros((0, E.N_ACTIONS), np.float32)
    zs = np.asarray(zs_all, dtype=np.float32)
    return feats, pis, zs, stats


def run_league_games(pool, net_npz: str, assignments: list[tuple[dict, int]], *,
                     n_sims: int = 128, temperature: float = 1.0, temp_moves: int = 20,
                     dirichlet_eps: float = 0.35, add_noise: bool = True,
                     reward_shaping: float = 0.5, shaping_scale: float = 6.0,
                     seed: int = 0):
    """Fan league games across the pool. `assignments` is a list of
    (opponent_spec, n_games); each is split into worker-sized sub-tasks.
    Returns (examples, per_opponent_scores) where per_opponent_scores maps
    opponent label -> net win rate (the live progress-toward-goal signal)."""
    n_workers = pool._processes
    tasks = []
    si = 0
    for spec, n_games in assignments:
        base, rem = divmod(n_games, n_workers)
        for w in range(n_workers):
            c = base + (1 if w < rem else 0)
            if c <= 0:
                continue
            tasks.append({
                "net_npz": net_npz, "spec": spec, "n_games": c, "n_sims": n_sims,
                "temperature": temperature, "temp_moves": temp_moves,
                "dirichlet_eps": dirichlet_eps, "add_noise": add_noise,
                "reward_shaping": reward_shaping, "shaping_scale": shaping_scale,
                "seed": seed + si * 99989,
            })
            si += 1
    t0 = time.time()
    results = pool.map(_league_worker, tasks)
    secs = time.time() - t0

    feats = np.concatenate([r[0] for r in results]) if results else np.zeros((0, F.N_FEATURES), np.float32)
    pis = np.concatenate([r[1] for r in results]) if results else np.zeros((0, E.N_ACTIONS), np.float32)
    zs = np.concatenate([r[2] for r in results]) if results else np.zeros((0,), np.float32)

    agg: dict[str, list] = {}
    for _, _, _, st in results:
        g, s = agg.setdefault(st["label"], [0, 0.0])
        agg[st["label"]] = [g + st["games"], s + st["net_score"]]
    scores = {lbl: s / g for lbl, (g, s) in agg.items()}
    return (feats, pis, zs), scores, secs
