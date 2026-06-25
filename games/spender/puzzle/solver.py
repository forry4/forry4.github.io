"""Forced-win solver — the make-or-break primitive for puzzle generation.

A position is a puzzle iff the hero (side to move) can FORCE a win within K of their
own turns AND the forcing line is unique at every hero decision. The opponent is a
pluggable single-best-reply oracle:

  * `s_opponent`  — variant S (the deployed AI; the real target). Seeded by POSITION
                    so a reply is a deterministic function of the state, not of call
                    order (the baked canonical reply must equal what the uniqueness
                    enumeration computes at the same node).
  * `h3_opponent` — greedy H3 (fast; for cheap screening before the S re-verify).

A single-best-reply opponent (not full minimax over all opponent moves) is the
FAITHFUL model here: a scripted puzzle ends the instant the player deviates, so the
opponent never has to respond to anything but the canonical line. "Unique forcing
line against S" is exactly the question a fully-scripted, deviation-fails puzzle asks.

Offline, pure-Python. Reuses the engine for rules/state.
"""
from __future__ import annotations

from dataclasses import dataclass

from games.spender.ai.az import engine as E
from games.spender.ai.az import heuristic3 as H3
# vsearch (variant S) pulls in numpy + the whole AZ stack; import it LAZILY inside
# s_opponent so an H3-only search stays lightweight (memory-safe on a loaded box).

MAX_CARD_PTS = 5          # a card is worth at most 5 points (loose feasibility ceiling)
_RECURSION_CAP = 400      # hard guard; the budget already bounds the tree


# ─── opponent oracles (return ONE legal action for the side to move) ──────────

def state_key(s: E.State) -> int:
    """Reproducible hash of the full position (so an opponent reply is a function of
    the POSITION, not of call order)."""
    parts = (
        tuple(s.bank),
        tuple(s.tokens[0]), tuple(s.tokens[1]),
        tuple(s.bonuses[0]), tuple(s.bonuses[1]),
        tuple(s.points), tuple(s.purchased_n),
        tuple(s.reserved[0]), tuple(s.reserved[1]),
        tuple(s.reserved_blind[0]), tuple(s.reserved_blind[1]),
        tuple(s.nobles_won[0]), tuple(s.nobles_won[1]),
        tuple(s.board), tuple(s.decks[0]), tuple(s.decks[1]), tuple(s.decks[2]),
        tuple(s.nobles), s.turn, s.phase, tuple(s.pending_nobles),
        s.final_trigger, s.win_points,
    )
    return hash(parts) & 0xFFFFFFFF


def s_opponent(sims: int = 200, seed_base: int = 0xC0FFEE):
    """Variant S as a deterministic, position-seeded opponent oracle."""
    from games.spender.ai.az import vsearch    # lazy: only the S path needs numpy/AZ
    def opp(s: E.State) -> int:
        vsearch._RNG.seed(seed_base ^ state_key(s))
        return vsearch.choose_action(s, s.turn, sims=sims)
    return opp


def h3_opponent():
    """Greedy H3 opponent (no search; fast screening)."""
    def opp(s: E.State) -> int:
        return H3.choose_action(s, s.turn)
    return opp


def h3_policy(s: E.State) -> int:
    """The hero playing the 'obvious' greedy move (for the triviality filter)."""
    return H3.choose_action(s, s.turn)


# ─── the forced-win / uniqueness search ──────────────────────────────────────

@dataclass
class Solution:
    hero: int
    K: int
    line: list           # [(seat, action, phase), ...] hero choices + frozen opp replies
    unique: bool         # exactly one winning choice at EVERY hero decision on the line
    opp_calls: int       # how many opponent-oracle calls the search made (perf signal)


def _bound(turns: int) -> int:
    # loose over-estimate of points the hero can add in `turns` turns: one card/turn
    # (<=5) plus at most one noble in the window. Never prunes a real win.
    return turns * MAX_CARD_PTS + 3


class _Searcher:
    def __init__(self, hero: int, opp):
        self.hero = hero
        self.opp = opp
        self.opp_calls = 0

    def run(self, s: E.State, budget: int):
        return self._win_line(s, budget, 0)

    def _win_line(self, s: E.State, budget: int, depth: int):
        """Return (line, unique). line is a [(seat, action, phase)] hero-win line, or
        None if the hero cannot force a win within `budget` hero turns. `unique` = at
        every hero decision on the line there was exactly one winning choice."""
        if depth > _RECURSION_CAP:
            return (None, True)
        if s.phase == E.OVER:
            return ([], True) if s.winner == self.hero else (None, True)

        if s.turn == self.hero:
            is_play = s.phase == E.PLAY
            if is_play:
                if budget <= 0:
                    return (None, True)
                if s.final_trigger < 0 and s.points[self.hero] + _bound(budget) < s.win_points:
                    return (None, True)            # can't reach the threshold in time
            nb = budget - 1 if is_play else budget   # a PLAY action spends one hero turn
            first = None                              # (line, unique) of the first winner
            n_winners = 0
            for a in E.legal_actions(s):
                c = s.clone()
                E.apply(c, a)
                sl, su = self._win_line(c, nb, depth + 1)
                if sl is not None:
                    n_winners += 1
                    if first is None:
                        first = ([(self.hero, a, s.phase)] + sl, su)
                    if n_winners >= 2:
                        break                         # uniqueness already dead; keep canonical
            if first is None:
                return (None, True)
            line, su = first
            return (line, (n_winners == 1) and su)

        # opponent node — single frozen reply. Skip the oracle call when the hero is
        # already doomed (no turns left and the game won't end on its own).
        if budget <= 0 and s.final_trigger < 0:
            return (None, True)
        self.opp_calls += 1
        a = self.opp(s)
        c = s.clone()
        E.apply(c, a)
        sl, su = self._win_line(c, budget, depth + 1)
        if sl is None:
            return (None, su)
        return ([(1 - self.hero, a, s.phase)] + sl, su)


def solve(s: E.State, hero: int, K: int, opp) -> Solution | None:
    """Find the unique forced-win line for `hero` within K of their turns vs `opp`.
    Returns None if no forced win exists. The returned Solution may have unique=False
    (a win exists but more than one line wins) — the generator rejects those."""
    srch = _Searcher(hero, opp)
    line, unique = srch.run(s, K)
    if line is None:
        return None
    return Solution(hero=hero, K=K, line=line, unique=unique, opp_calls=srch.opp_calls)


# ─── triviality filter (the "obvious move must FAIL") ─────────────────────────

def policy_wins(s: E.State, hero: int, K: int, hero_policy, opp) -> bool:
    """Does the hero win within K turns by just following `hero_policy` (vs `opp`)?
    If the greedy policy already wins, the position is trivial — not a puzzle."""
    sim = s.clone()
    budget = K
    for _ in range(_RECURSION_CAP):
        if sim.phase == E.OVER:
            return sim.winner == hero
        if sim.turn == hero:
            if sim.phase == E.PLAY:
                if budget <= 0:
                    return False
                budget -= 1
            a = hero_policy(sim)
        else:
            a = opp(sim)
        E.apply(sim, a)
    return False


def is_trivial(s: E.State, hero: int, K: int, opp) -> bool:
    """The obvious (H3-greedy) hero line already wins → not a puzzle."""
    return policy_wins(s, hero, K, h3_policy, opp)


# ─── strict "every deviation loses" check (race puzzles) ──────────────────────

def _rollout_winner(s: E.State, hero: int, opp) -> int:
    """Play it out — hero greedy (H3), opponent its policy — and return the winner
    seat (or WIN_DRAW / WIN_NONE)."""
    sim = s.clone()
    for _ in range(_RECURSION_CAP):
        if sim.phase == E.OVER:
            return sim.winner
        a = H3.choose_action(sim, sim.turn) if sim.turn == hero else opp(sim)
        E.apply(sim, a)
    return E.WIN_NONE


def every_deviation_loses(s: E.State, hero: int, line: list, opp, slack: int = 2) -> bool:
    """True iff the canonical `line` is a knife's edge: at EVERY hero PLAY decision,
    every NON-canonical legal move (a) cannot force a win even given `slack` extra
    moves, AND (b) loses under continued play (the opponent wins). So the only way to
    avoid losing is the exact sequence — "play these moves or lose".

    Mostly cheap: it early-outs the moment one deviation fails to lose (the common
    case). Only a true race position checks all deviations. Applied only to positions
    already known to be a unique forced win, which are rare."""
    cur = s.clone()
    total = sum(1 for (seat, _a, ph) in line if seat == hero and ph == E.PLAY)
    done = 0
    for (seat, action, phase) in line:
        if seat == hero and phase == E.PLAY:
            remaining = total - done                     # hero PLAY moves left incl. this one
            for a in E.legal_actions(cur):
                if a == action:
                    continue
                c = cur.clone()
                E.apply(c, a)
                if solve(c, hero, remaining + slack, opp) is not None:
                    return False                         # could still force a win → not forced-losing
                if _rollout_winner(c, hero, opp) != (1 - hero):
                    return False                         # not a clear loss (draw / unresolved)
            done += 1
        E.apply(cur, action)
    return True
