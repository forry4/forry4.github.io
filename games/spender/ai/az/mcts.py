"""PUCT MCTS with single-observer determinization (ISMCTS-style).

Hidden information (deck order, opponent blind reserves) is handled by
re-determinizing at the start of every simulation: the unseen pool — undealt
deck cards plus the opponent's blind-reserved cards, per level — is reshuffled,
and the simulation plays out in that sample. Tree statistics are keyed by
action index and shared across determinizations; at selection time only the
actions legal in the *current* determinization are considered.

Value convention: v in [-1, 1] from the perspective of the player to move at
the evaluated state. Turns do not strictly alternate (discard/noble phases),
so backups credit each edge by the acting player's identity, not by depth.

The search is incremental (leaf_batch/apply_evals) so a driver can batch NN
forwards across many concurrent games; run() is the sequential convenience.
"""
from __future__ import annotations

import math
import random

import numpy as np

from . import engine as E
from . import features as F


def determinize(s: E.State, perspective: int, rng: random.Random) -> E.State:
    """Clone s and reshuffle the unseen pool from `perspective`'s viewpoint."""
    d = s.clone()
    opp = 1 - perspective
    for lvl in range(3):
        pool = list(d.decks[lvl])
        blind_idx = [i for i, (ci, bl) in enumerate(zip(d.reserved[opp], d.reserved_blind[opp]))
                     if bl and E.LEVEL_OF[ci] - 1 == lvl]
        pool.extend(d.reserved[opp][i] for i in blind_idx)
        rng.shuffle(pool)
        for i in blind_idx:
            d.reserved[opp][i] = pool.pop()
        d.decks[lvl][:] = pool
    return d


class Node:
    __slots__ = ("to_play", "expanded", "P", "N", "W", "children")

    def __init__(self, to_play: int):
        self.to_play = to_play
        self.expanded = False
        self.P = None                       # np.ndarray[N_ACTIONS] priors
        self.N = [0] * E.N_ACTIONS
        self.W = [0.0] * E.N_ACTIONS        # from self.to_play's perspective
        self.children: dict[int, "Node"] = {}


_EPS_PRIOR = 1e-3  # actions legal in this determinization but unseen at expansion


class Search:
    """One MCTS search over a root state. Incremental API:
        leaf_batch() -> (features, mask) | None   (None: sim finished w/o NN)
        apply_evals(probs, value)                 (finish the pending sim)
    run(evaluate, n_sims) drives both sequentially.
    """

    def __init__(self, root: E.State, rng: random.Random, *,
                 c_puct: float = 2.0, dirichlet_alpha: float = 0.5,
                 dirichlet_eps: float = 0.25, add_noise: bool = True):
        if root.phase == E.OVER:
            raise ValueError("cannot search a terminal state")
        self.root_state = root
        self.rng = rng
        self.c_puct = c_puct
        self.dir_alpha = dirichlet_alpha
        self.dir_eps = dirichlet_eps
        self.add_noise = add_noise
        self.root = Node(root.turn)
        self._pending: tuple[list, Node, E.State] | None = None

    # ── simulation ────────────────────────────────────────────────────────────

    def leaf_batch(self):
        """Run selection for one simulation. Returns (features, mask) for the
        leaf needing NN eval, or None if the sim hit a terminal and was backed
        up internally (call again for the next sim)."""
        assert self._pending is None
        s = determinize(self.root_state, self.root_state.turn, self.rng)
        node = self.root
        path: list[tuple[Node, int]] = []

        while node.expanded:
            acts = E.legal_actions(s)
            a = self._select(node, acts)
            path.append((node, a))
            E.apply(s, a)
            if s.phase == E.OVER:
                # Terminal: value expressed for player 0, flipped per edge owner.
                v0 = 0.0 if s.winner == E.WIN_DRAW else (1.0 if s.winner == 0 else -1.0)
                self._backup_value(path, v0, ref_player=0)
                return None
            child = node.children.get(a)
            if child is None:
                child = Node(s.turn)
                node.children[a] = child
            node = child

        feats = F.encode(s)
        mask = np.zeros(E.N_ACTIONS, dtype=bool)
        for a in E.legal_actions(s):
            mask[a] = True
        self._pending = (path, node, s)
        return feats, mask

    def apply_evals(self, probs: np.ndarray, value: float) -> None:
        path, node, s = self._pending
        self._pending = None
        if not node.expanded:
            node.expanded = True
            node.P = probs.astype(np.float64)
            if self.add_noise and node is self.root:
                self._mix_root_noise(s)
        # value is for s.turn (the leaf's player to move)
        self._backup_value(path, value, s.turn)

    def run(self, evaluate, n_sims: int) -> list[int]:
        """Sequential driver. Returns root visit counts."""
        done = 0
        while done < n_sims:
            req = self.leaf_batch()
            if req is None:
                done += 1
                continue
            feats, mask = req
            probs, values = evaluate(feats[None, :], mask[None, :])
            self.apply_evals(probs[0], float(values[0]))
            done += 1
        return self.root.N[:]

    # ── internals ─────────────────────────────────────────────────────────────

    def _select(self, node: Node, acts: list[int]) -> int:
        sqrt_total = math.sqrt(sum(node.N[a] for a in acts) + 1)
        best_a, best_u = acts[0], -1e30
        for a in acts:
            n = node.N[a]
            q = node.W[a] / n if n else 0.0
            p = node.P[a] if node.P[a] > 0 else _EPS_PRIOR
            u = q + self.c_puct * p * sqrt_total / (1 + n)
            if u > best_u:
                best_a, best_u = a, u
        return best_a

    def _mix_root_noise(self, s: E.State) -> None:
        acts = E.legal_actions(s)
        noise = np.random.default_rng(self.rng.randrange(2**31)).dirichlet(
            [self.dir_alpha] * len(acts))
        for k, a in enumerate(acts):
            self.root.P[a] = (1 - self.dir_eps) * self.root.P[a] + self.dir_eps * noise[k]

    def _backup_value(self, path, value: float, ref_player: int) -> None:
        for node, a in path:
            v = value if node.to_play == ref_player else -value
            node.N[a] += 1
            node.W[a] += v


def pick_action(visits: list[int], rng: random.Random, temperature: float) -> int:
    """Sample from visit counts at the given temperature (0 = argmax)."""
    if temperature <= 1e-3:
        m = max(visits)
        best = [a for a, n in enumerate(visits) if n == m and n > 0]
        return rng.choice(best)
    weights = [n ** (1.0 / temperature) for n in visits]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for a, w in enumerate(weights):
        acc += w
        if acc >= r:
            return a
    return max(range(len(visits)), key=visits.__getitem__)
