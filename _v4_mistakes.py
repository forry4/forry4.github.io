"""Mistake hunter: where is the v4 greedy heuristic myopic?

Greedy play is DETERMINISTIC given a seed (the deck is fixed at new_game, and
both policies are argmax), so we can build a perfect depth-1 oracle with zero
rollout variance: at each of v4's decisions, try every legal move, then play BOTH
sides greedy to the end, and record the true final outcome of each move. Where
v4's actual (myopic) pick differs from the move with the best outcome -- and
especially where the pick LOSES but an alternative WINS -- that is a concrete
1-ply mistake. Aggregate by (greedy move-type -> oracle move-type) to surface the
SYSTEMATIC blind spot (the kind of finding that produced noble-completion), and
dump a few human-readable examples to inspect.

Self-contained, ASCII output. Does not touch the deployed bot.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

OPP_NAME = "C2"
SEEDS = list(range(12000, 12040))     # 40 games
MARGIN_TO_FLAG = 1                     # min final point-margin gain to call it a mistake


def _move_kind(a):
    from games.spender.ai.az import engine as E
    if E.A_TAKE3 <= a < E.A_TAKE1:
        return "take2-3"
    if E.A_TAKE1 <= a < E.A_TAKE2S:
        return "take1"
    if E.A_TAKE2S <= a < E.A_PASS:
        return "take2same"
    if a == E.A_PASS:
        return "pass"
    if E.A_RES_BOARD <= a < E.A_BUY_BOARD:
        return "reserve"
    if E.A_BUY_BOARD <= a < E.A_DISCARD:
        return "buy"
    if E.A_DISCARD <= a < E.A_NOBLE:
        return "discard"
    return "noble"


def _playout_outcome(s, v4, H, E):
    """Play both sides greedy to the end from s; return (win?1:0, point margin)."""
    while s.phase != E.OVER and s.ply < 400:
        E.apply(s, H.choose_action(s, s.turn))
    win = 1 if s.winner == v4 else 0
    return win, s.points[v4] - s.points[1 - v4]


def _hunt(seeds):
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    opp = _load_opp_weights(OPP_NAME)

    transitions = Counter()          # (greedy_kind -> oracle_kind) : count
    flip_to_win = Counter()          # same, but only pick-loses / oracle-wins
    samples = []                     # (seed, ply, greedy_kind, oracle_kind, dmargin, flipwin)
    n_decisions = 0
    n_mistakes = 0

    for g in seeds:
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        v4 = g % 2
        while s.phase != E.OVER and s.ply < 400:
            if s.turn != v4 or s.phase != E.PLAY:
                E.apply(s, H.choose_action(s, s.turn) if s.turn == v4
                        else _heuristic_action(s, opp, 1))
                continue
            legal = E.legal_actions(s)
            greedy_a = H.choose_action(s, s.turn)
            if len(legal) > 1:
                n_decisions += 1
                # evaluate every legal move by deterministic greedy playout
                best = None
                gout = None
                for a in legal:
                    sc = s.clone()
                    E.apply(sc, a)
                    win, marg = _playout_outcome(sc, v4, H, E)
                    key = (win, marg)
                    if a == greedy_a:
                        gout = key
                    if best is None or key > best[0]:
                        best = (key, a)
                oracle_key, oracle_a = best
                if oracle_a != greedy_a and gout is not None:
                    dwin = oracle_key[0] - gout[0]
                    dmarg = oracle_key[1] - gout[1]
                    if dwin > 0 or dmarg >= MARGIN_TO_FLAG:
                        n_mistakes += 1
                        gk, ok = _move_kind(greedy_a), _move_kind(oracle_a)
                        transitions[(gk, ok)] += 1
                        if dwin > 0:
                            flip_to_win[(gk, ok)] += 1
                        if len(samples) < 12:
                            samples.append((g, s.ply, gk, ok, dmarg, dwin > 0))
            E.apply(s, greedy_a)
    return n_decisions, n_mistakes, transitions, flip_to_win, samples


if __name__ == "__main__":
    shards = [SEEDS[i::8] for i in range(8)]
    nd = nm = 0
    trans = Counter()
    flips = Counter()
    samples = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        for d, m, t, f, sm in ex.map(_hunt, shards):
            nd += d
            nm += m
            trans.update(t)
            flips.update(f)
            samples.extend(sm)

    print(f"mistake hunt: {len(SEEDS)} games vs {OPP_NAME}, depth-1 greedy oracle",
          flush=True)
    print(f"  decisions analyzed: {nd}", flush=True)
    print(f"  myopic mistakes (oracle strictly better): {nm} "
          f"({100*nm/max(1,nd):.1f}% of decisions)", flush=True)
    win_flips = sum(flips.values())
    print(f"  of which the pick LOSES a game an alternative WINS: {win_flips}",
          flush=True)
    print("\n  top mistake transitions (greedy did -> oracle wanted):", flush=True)
    for (gk, ok), c in trans.most_common(10):
        wf = flips.get((gk, ok), 0)
        print(f"    {gk:10s} -> {ok:10s}  {c:4d}   ({wf} are game-flips)", flush=True)
    print("\n  sample positions:", flush=True)
    for g, ply, gk, ok, dm, fw in samples:
        tag = "GAME-FLIP" if fw else f"+{dm} pts"
        print(f"    seed {g} ply {ply}: greedy {gk} -> oracle {ok}  ({tag})", flush=True)
