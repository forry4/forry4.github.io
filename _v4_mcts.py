"""Prototype v2: PUCT MCTS over the compact engine, PRIOR = v4 card_value.

v1 used a generic positional leaf eval that ignored the v4 valuation -> deeper
search amplified the crude eval and got WORSE than greedy. This version injects
the v4 valuation where it belongs: as the PUCT move prior (softmax over
H.card_value for buy/reserve, a board-average baseline for takes/other), so
search spends its sims on valuation-preferred moves. Leaf = cheap positional eval
only as a tiebreaker. One Valuation per node (not 30 per rollout) -> stays fast.

Perfect-info (beneficial cheat for a training opponent). Negamax via root-seat
perspective. ASCII output. Touches nothing deployed.

Benchmarks ms/move and win rate vs greedy-v4 and vs C2.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import math
import random
import time
from concurrent.futures import ProcessPoolExecutor

CPUCT = 2.0
TEMP = 3.0          # softmax temperature over card_value for the prior


class _Node:
    __slots__ = ("to_move", "N", "W", "children", "priors", "legal", "terminal")

    def __init__(self, to_move, legal, priors, terminal):
        self.to_move = to_move
        self.N = 0
        self.W = 0.0            # ROOT-seat perspective
        self.children = {}
        self.priors = priors
        self.legal = legal
        self.terminal = terminal


def _leaf_static(s, seat, E):
    opp = 1 - seat
    if s.phase == E.OVER:
        return 1.0 if s.winner == seat else (-1.0 if s.winner == opp else 0.0)
    dp = s.points[seat] - s.points[opp]
    dc = s.purchased_n[seat] - s.purchased_n[opp]
    db = sum(s.bonuses[seat]) - sum(s.bonuses[opp])
    return math.tanh((dp + 0.3 * dc + 0.1 * db) / 5.0)


def _action_card(s, a, mover, E):
    if E.A_BUY_BOARD <= a < E.A_BUY_RESV:
        return s.board[a - E.A_BUY_BOARD]
    if E.A_BUY_RESV <= a < E.A_DISCARD:
        idx = a - E.A_BUY_RESV
        return s.reserved[mover][idx] if idx < len(s.reserved[mover]) else -1
    if E.A_RES_BOARD <= a < E.A_RES_BOARD + 12:
        return s.board[a - E.A_RES_BOARD]
    return -1


def _priors(s, mover, legal, E, H, V):
    """Softmax over H.card_value for buy/reserve actions; takes/other get the
    board-average card value as a baseline so they compete with a median card."""
    val = V.Valuation(s)
    raw = {}
    cvs = []
    for a in legal:
        ci = _action_card(s, a, mover, E)
        if ci is not None and ci >= 0:
            cv = H.card_value(val, s, ci, mover)
            raw[a] = cv
            cvs.append(cv)
        else:
            raw[a] = None
    base = (sum(cvs) / len(cvs)) if cvs else 0.0
    h = {a: (raw[a] if raw[a] is not None else base) for a in legal}
    mx = max(h.values())
    exps = {a: math.exp((h[a] - mx) / TEMP) for a in legal}
    z = sum(exps.values())
    return {a: exps[a] / z for a in legal}


def _make_node(s, E, H, V):
    if s.phase == E.OVER:
        return _Node(s.turn, [], {}, True)
    legal = E.legal_actions(s)
    return _Node(s.turn, legal, _priors(s, s.turn, legal, E, H, V), False)


def mcts_choose(s, seat, sims, E, H, V):
    if s.phase != E.PLAY:
        return H.choose_action(s, seat)
    root = _make_node(s, E, H, V)
    if len(root.legal) <= 1:
        return root.legal[0] if root.legal else E.A_PASS

    for _ in range(sims):
        sc = s.clone()
        node = root
        path = [root]
        while not node.terminal:
            sN = math.sqrt(node.N + 1)
            best_u, best_a, best_ch = -1e18, None, None
            for a in node.legal:
                ch = node.children.get(a)
                if ch is None:
                    q, n = 0.0, 0
                else:
                    q = ch.W / ch.N
                    q = q if node.to_move == seat else -q
                    n = ch.N
                u = q + CPUCT * node.priors[a] * sN / (1 + n)
                if u > best_u:
                    best_u, best_a, best_ch = u, a, ch
            E.apply(sc, best_a)
            if best_ch is None:
                child = _make_node(sc, E, H, V)
                node.children[best_a] = child
                path.append(child)
                node = child
                break
            node = best_ch
            path.append(node)
        v = _leaf_static(sc, seat, E)
        for nd in path:
            nd.N += 1
            nd.W += v

    return max(root.children.items(), key=lambda kv: kv[1].N)[0]


# ─── workers ─────────────────────────────────────────────────────────────────

def _imports():
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az import valuation as V
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    return E, H, V, _heuristic_action, _load_opp_weights


def speed_job(cfg):
    label, sims = cfg
    E, H, V, _, _ = _imports()
    positions = []
    for g in range(20000, 20060):
        s = E.new_game(random.Random(g))
        while s.phase != E.OVER and s.ply < 400:
            if s.phase == E.PLAY and len(E.legal_actions(s)) > 1:
                positions.append(s.clone())
                if len(positions) >= 120:
                    break
            E.apply(s, H.choose_action(s, s.turn))
        if len(positions) >= 120:
            break
    t0 = time.time()
    for s in positions:
        mcts_choose(s, s.turn, sims, E, H, V)
    return label, (time.time() - t0) / len(positions) * 1000.0


def strength_job(job):
    label, sims, opp_name, seeds = job
    E, H, V, heur_action, load_opp = _imports()
    opp_w = load_opp(opp_name) if opp_name != "greedyV4" else None
    w = d = 0
    for g in seeds:
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            if s.turn == v4:
                a = mcts_choose(s, s.turn, sims, E, H, V)
            elif opp_name == "greedyV4":
                a = H.choose_action(s, s.turn)
            else:
                a = heur_action(s, opp_w, 1)
            E.apply(s, a)
        if s.winner == v4:
            w += 1
        elif s.winner == E.WIN_DRAW:
            d += 1
    return label, opp_name, (w + 0.5 * d), len(seeds)


if __name__ == "__main__":
    CONFIGS = [("prior@200", 200), ("prior@400", 400)]
    print("=== SPEED (ms/move) ===", flush=True)
    speed = {}
    with ProcessPoolExecutor(max_workers=3) as ex:
        for label, mspm in ex.map(speed_job, CONFIGS):
            speed[label] = mspm
            print(f"  {label:14s} {mspm:7.2f} ms/move  (~{mspm*30/1000:.2f}s/game)",
                  flush=True)

    print("\n=== STRENGTH (win rate, 64 games each, paired) ===", flush=True)
    SEEDS = list(range(21000, 21064))
    shards = [SEEDS[i::8] for i in range(8)]
    jobs = [(label, sims, opp, sh) for (label, sims) in CONFIGS
            for opp in ("greedyV4", "C2") for sh in shards]
    agg = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for label, opp, score, n in ex.map(strength_job, jobs):
            sc, tot = agg.get((label, opp), (0.0, 0))
            agg[(label, opp)] = (sc + score, tot + n)
    for (label, _s) in CONFIGS:
        row = f"  {label:14s}"
        for opp in ("greedyV4", "C2"):
            sc, tot = agg[(label, opp)]
            row += f"  vs {opp}: {sc/tot:.3f}"
        print(row + f"   [{speed[label]:.1f} ms/move]", flush=True)
    print("\n  (greedy-v4 baseline vs C2 ~0.59-0.65; beat 0.50 vs greedyV4 = search helps)",
          flush=True)
