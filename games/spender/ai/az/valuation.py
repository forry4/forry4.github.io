"""Shared card-valuation core (v4).

Per-card, per-seat scalar signals computed directly on `engine.State`. This is
the single source of truth for the v4 card model, imported by BOTH:
  - the v4 heuristic bot (`card_value` + `choose_move`), and
  - the net's feature encoder (`features.py`, which packs these scalars into the
    input vector).
Build once, use twice.

No torch/numpy here — plain Python on the compact engine state (features.py does
the array packing). Color order matches engine: white,blue,green,red,black,gold.

Factor definitions and rationale: see FEATURES_V4.md. Quantities, all from the
perspective of `seat` (0 or 1):
  effective_cost      gem cost after this player's permanent card discounts
  gems_to_collect     gems still to gather after spending owned tokens + gold
  gold_needed         gold required to buy now (engine parity helper)
  affordable_now      can buy this turn
  turns_to_afford     tempo estimate (a signal, not an oracle)
  noble_progress      how much this card's bonus advances visible nobles (0..1)
  engine_value        cross-card cost-reduction this card grants + deck-demand term
  efficiency          points per effective gem (deal quality)
  victory_closeness   how near to 15 buying this card brings the player
"""
from __future__ import annotations

import math

from . import engine as E


# ─── Stateless per-card/seat scalars ─────────────────────────────────────────

def effective_cost(s: E.State, ci: int, seat: int) -> list[int]:
    """Per-color gem cost after `seat`'s permanent card discounts (>= 0)."""
    cost = E.COST[ci]
    bon = s.bonuses[seat]
    return [c - b if c > b else 0 for c, b in zip(cost, bon)]


def total_effective_cost(s: E.State, ci: int, seat: int) -> int:
    """Sum of the post-discount gem cost (ignores tokens already held)."""
    cost = E.COST[ci]
    bon = s.bonuses[seat]
    return sum(c - b for c, b in zip(cost, bon) if c > b)


def gold_needed(s: E.State, ci: int, seat: int) -> int:
    """Gold tokens required to buy ci now (matches engine legality helper)."""
    return E._gold_needed(E.COST[ci], s.tokens[seat], s.bonuses[seat])


def affordable_now(s: E.State, ci: int, seat: int) -> bool:
    """True if `seat` can buy ci this turn (enough tokens + gold)."""
    return gold_needed(s, ci, seat) <= s.tokens[seat][5]


REACH_STEEP = 4   # a single-color cost this high (after bonuses) needs a build path


def is_steep(s: E.State, ci: int, seat: int) -> bool:
    """True if ci has a single-color cost >= REACH_STEEP after `seat`'s bonuses
    -- i.e. it needs a build path to be realistically affordable, rather than
    being gettable by normal spread gem-taking."""
    cost = E.COST[ci]
    bon = s.bonuses[seat]
    return any(cost[c] - bon[c] >= REACH_STEEP for c in range(5))


def build_path_count(s: E.State, ci: int, seat: int) -> int:
    """Build *capacity* toward ci's steepest single color: the bonuses `seat`
    ALREADY holds in that color PLUS the lower-level board cards that grant it.
    0 if ci isn't steep. Counting existing bonuses is deliberate -- if you've
    already built that color you should be free to reserve the expensive card
    (the requirement is really 'do you have a real path', which a committed
    engine satisfies); a thin path (1-2) on an unbuilt color means you'd land
    1-2 bonuses, still 5-6 gems short -> a speculative reserve that goes unused."""
    cost = E.COST[ci]
    bon = s.bonuses[seat]
    eff = [cost[c] - bon[c] for c in range(5)]
    c = max(range(5), key=eff.__getitem__)   # the steepest single color (after bonuses)
    if eff[c] < REACH_STEEP:
        return 0
    lvl = E.LEVEL_OF[ci]
    board = sum(1 for slot in range(12)
                if s.board[slot] >= 0 and s.board[slot] != ci
                and E.LEVEL_OF[s.board[slot]] < lvl and E.BONUS[s.board[slot]] == c)
    return bon[c] + board   # existing bonuses count as build capacity


def _color_deficits(s: E.State, ci: int, seat: int) -> list[int]:
    """Per-color gems still needed after discounts and owned colored tokens
    (gold NOT applied here — callers fold gold in where appropriate)."""
    cost = E.COST[ci]
    bon = s.bonuses[seat]
    tok = s.tokens[seat]
    out = []
    for i in range(5):
        need = cost[i] - bon[i] - tok[i]
        out.append(need if need > 0 else 0)
    return out


def gems_to_collect(s: E.State, ci: int, seat: int) -> int:
    """Gems `seat` must still gather to afford ci, after spending matching
    colored tokens and any gold (gold is wild). 0 if already affordable."""
    deficit = sum(_color_deficits(s, ci, seat)) - s.tokens[seat][5]
    return deficit if deficit > 0 else 0


def turns_to_afford(s: E.State, ci: int, seat: int) -> int:
    """Estimated turns for `seat` to afford ci. A signal, not an oracle.

    A take grabs <=3 different colors, or 2 of one color (bank>=4). The two
    binding constraints are therefore total volume and the most-needed single
    color, so estimate = max(ceil(net / 3), max_color ceil(deficit / 2)).
    Returns 0 if affordable now.
    """
    d = _color_deficits(s, ci, seat)
    net = sum(d) - s.tokens[seat][5]  # gold covers any color
    if net <= 0:
        return 0
    by_spread = math.ceil(net / 3)
    by_color = max((math.ceil(x / 2) for x in d if x > 0), default=0)
    return max(by_spread, by_color)


def noble_progress(s: E.State, ci: int, seat: int) -> float:
    """How much ci's +1 bonus advances visible nobles for `seat`, in [0, 1].

    Folds in both *progress* (does this bonus color still help a noble) and
    *closeness* (how near that noble already is), averaged over visible nobles.
    """
    bcol = E.BONUS[ci]
    bon = s.bonuses[seat]
    score = 0.0
    n = 0
    for slot in range(3):
        ni = s.nobles[slot]
        if ni < 0:
            continue
        n += 1
        req = E.NOBLE_REQ[ni]
        if req[bcol] > bon[bcol]:  # this color is still needed by the noble
            total = sum(req)
            if total:
                deficit = sum(req[i] - bon[i] for i in range(5) if req[i] > bon[i])
                score += 1.0 - deficit / total
    return score / n if n else 0.0


def efficiency(s: E.State, ci: int, seat: int) -> float:
    """Points per effective gem — the 'good deal' lever. +1 in the denominator
    keeps 0-cost / 0-point cards finite and ranks free points highest."""
    return E.PTS[ci] / (total_effective_cost(s, ci, seat) + 1.0)


def victory_closeness(s: E.State, ci: int, seat: int, noble_pts: int = 0) -> float:
    """How near to the 15-point win buying ci (plus any noble it triggers)
    brings `seat`, capped at 1.0."""
    pts = s.points[seat] + E.PTS[ci] + noble_pts
    v = pts / E.WIN_POINTS
    return v if v < 1.0 else 1.0


# ─── Stateful context (precomputes state-wide aggregates once) ───────────────

class Valuation:
    """Per-state valuation context. Precomputes aggregates that are constant
    across cards (deck color demand) so per-card queries stay cheap. Build one
    per state evaluation and reuse across all candidate cards and both seats.

    Stateless scalars above are re-exposed as methods for a single call site.
    """

    __slots__ = ("s", "deck_color_demand")

    def __init__(self, s: E.State):
        self.s = s
        # Permanent-bonus future value: share of remaining (undealt) deck cost
        # that is each color. A bonus in a deck-heavy color keeps paying off on
        # cards not yet revealed, not just the 12 on the board.
        demand = [0, 0, 0, 0, 0]
        total = 0
        for lvl in range(3):
            for ci in s.decks[lvl]:
                cost = E.COST[ci]
                for i in range(5):
                    demand[i] += cost[i]
                    total += cost[i]
        self.deck_color_demand = [d / total for d in demand] if total else [0.0] * 5

    # cross-card factor (the one an MLP cannot assemble from a flat vector) ----
    def engine_value(self, ci: int, seat: int) -> float:
        """Value of the permanent +1 `bcol` bonus ci grants: the discount it
        gives every *other* visible card (weighted by that card's worth and how
        `bcol`-hungry it is) plus a deck-wide term for unrevealed cards."""
        s = self.s
        bcol = E.BONUS[ci]
        bon_b = s.bonuses[seat][bcol]
        ev = 0.0
        for slot in range(12):
            cj = s.board[slot]
            if cj < 0 or cj == ci:
                continue
            costj = E.COST[cj]
            if costj[bcol] - bon_b > 0:  # cj still needs this color
                w_value = E.PTS[cj] / 5.0 + 0.2          # high-point cards weigh more (+floor)
                sj = sum(costj)
                w_scarcity = costj[bcol] / sj if sj else 0.0  # cj is bcol-heavy
                ev += w_value * w_scarcity
        ev += self.deck_color_demand[bcol] * 0.5
        return ev

    # thin re-exports so a heuristic / encoder has one object to call ----------
    def effective_cost(self, ci: int, seat: int) -> list[int]:
        return effective_cost(self.s, ci, seat)

    def total_effective_cost(self, ci: int, seat: int) -> int:
        return total_effective_cost(self.s, ci, seat)

    def gold_needed(self, ci: int, seat: int) -> int:
        return gold_needed(self.s, ci, seat)

    def affordable_now(self, ci: int, seat: int) -> bool:
        return affordable_now(self.s, ci, seat)

    def gems_to_collect(self, ci: int, seat: int) -> int:
        return gems_to_collect(self.s, ci, seat)

    def turns_to_afford(self, ci: int, seat: int) -> int:
        return turns_to_afford(self.s, ci, seat)

    def noble_progress(self, ci: int, seat: int) -> float:
        return noble_progress(self.s, ci, seat)

    def efficiency(self, ci: int, seat: int) -> float:
        return efficiency(self.s, ci, seat)

    def victory_closeness(self, ci: int, seat: int, noble_pts: int = 0) -> float:
        return victory_closeness(self.s, ci, seat, noble_pts)
