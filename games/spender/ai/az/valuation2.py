"""Card-valuation core — H2 SANDBOX fork of valuation.py.

A self-contained copy paired with `heuristic2.py` (variant H2), so aggressive
changes to the valuation model can be tried here WITHOUT touching the stable
shared `valuation.py` that variant H + the net's feature encoder depend on. When
an experiment proves out, fold it back into the shared valuation.py.

Per-card, per-seat scalar signals computed directly on `engine.State`.

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

# ─── Tuned valuation constants (found by the offline search; see H2.md) ───────
GOLD_BANK_CAP = 2   # gems of the bottleneck color assumed pullable from the bank in gold_cost
ENG_DIV = 8.0       # engine_value: PTS divisor (higher = flatter; values broad colors over point-heavy ones)
ENG_FLOOR = 0.2     # engine_value: zero-point floor in each card's weight
ENG_DECK_W = 1.0    # engine_value: weight on the forward-looking deck-demand term
NOBLE_CLOSE_FLOOR = 0.2   # noble_progress: a card whose color a visible noble needs scores at least
                          # this (per such noble) even at zero bonuses -- "relevance" survives distance


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


def cost_concentration(s: E.State, ci: int, seat: int) -> int:
    """Duplicate same-color gems the post-bonus cost forces you to collect:
    total_effective_cost - distinct_colors_still_needed. 0 = perfectly spread
    (<=1 gem per color -- takeable in a single 3-distinct take); higher = packed
    into fewer colors, which forces slower take-2-same turns (you net 2 useful
    gems that turn instead of 3). A pure tempo/acquisition signal, independent of
    points and efficiency -- it separates two cards of equal total cost + bonus
    that efficiency (0 for point-less L1s) and engine_value (bonus-color only)
    cannot: e.g. 3-green (conc 2) vs 2-green-1-red (conc 1)."""
    eff = effective_cost(s, ci, seat)
    return sum(eff) - sum(1 for x in eff if x > 0)


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


def discount_count(s: E.State, ci: int, seat: int) -> int:
    """How many OTHER board cards the +1 bonus from ci would discount -- i.e.
    still need ci's bonus color from `seat`. A 0-point card is only worth buying
    over just TAKING A GEM of that color if it discounts >= 2 such cards: a
    permanent bonus you cash in once is barely better than one token, and buying
    spends gems + adds a card toward the fewest-cards tiebreak (whereas taking a
    gem gains a flexible token at no tiebreak cost)."""
    bcol = E.BONUS[ci]
    held = s.bonuses[seat][bcol]
    return sum(1 for slot in range(12)
               if s.board[slot] >= 0 and s.board[slot] != ci
               and E.COST[s.board[slot]][bcol] > held)


def single_color_mirage(s: E.State, ci: int, seat: int, steep: int = 5) -> bool:
    """True if ci still needs >= `steep` of a SINGLE color after `seat`'s bonuses.
    The 2-player bank holds only 4 of each color, so a single-color cost this high
    CANNOT be collected as tokens -- it is affordable only by first building bonuses
    in that color (buying lower cards of it). So ci must NOT be a gem-TAKING target:
    collecting toward its raw single-color cost just hoards tokens you can never
    complete (you cap at 10 and discard forever -- the seed-70 deadlock). Skipping it
    as a take-target redirects the bot to a REACHABLE card, typically the lower cards
    that build the very color it is short on. A build path on the board does NOT make
    it collectable (you still can't hold 5+ of one color); only BONUSES do -- once
    they bring the single-color cost below `steep`, ci is a normal target again.
    (Reserving such a card is still fine -- that path uses build_path_count, not this;
    the deadlock was gem-TAKING toward an un-collectable cost.)"""
    cost = E.COST[ci]
    bon = s.bonuses[seat]
    return any(cost[c] - bon[c] >= steep for c in range(5))


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


USE_TTA_GREEDY = True   # corrected turns-to-afford via greedy take simulation. The old
                        # closed form `max(ceil(total/3), max ceil(d[c]/2))` UNDER-counted a
                        # cost concentrated in one color that ALSO needs others: a take-3
                        # supplies only 1 of any color, so 2g+1r is 2 turns (formula said 1),
                        # 4w+1u is 3 (formula said 2). Flag kept so the fix is A/B-able.


def turns_to_afford(s: E.State, ci: int, seat: int) -> int:
    """Estimated turns for `seat` to afford ci. A signal, not an oracle.

    Each turn a take grabs <=3 DISTINCT colors (1 each), or 2 of one color
    (bank>=4). So a color needing 2+ cannot be filled by spread take-3s at 3/turn
    -- it forces a take-2-same turn (2 gems, no room for others). The greedy
    simulation below (spend gold on the bottleneck, then each turn take the 3
    most-needed distinct colors, pairing the leader when <=2 colors remain) is
    optimal for this move set and gets those concentrated-multicolor costs right.
    Returns 0 if affordable now. Bank depletion / opponent contention ignored
    (it's a signal). The old closed form is kept behind USE_TTA_GREEDY for A/B.
    """
    d = list(_color_deficits(s, ci, seat))
    gold = s.tokens[seat][5]
    if not USE_TTA_GREEDY:
        net = sum(d) - gold  # gold covers any color
        if net <= 0:
            return 0
        by_spread = math.ceil(net / 3)
        by_color = max((math.ceil(x / 2) for x in d if x > 0), default=0)
        return max(by_spread, by_color)
    # Spend gold on the largest deficits first (relieve the pairing bottleneck).
    while gold > 0 and any(x > 0 for x in d):
        i = max(range(5), key=d.__getitem__)
        d[i] -= 1
        gold -= 1
    turns = 0
    while any(x > 0 for x in d):
        pos = sorted((c for c in range(5) if d[c] > 0), key=lambda c: -d[c])
        if len(pos) >= 3:                 # take 1 each of the 3 most-needed (take-3)
            for c in pos[:3]:
                d[c] -= 1
        elif len(pos) == 2:               # pair the leader if it needs 2+, else 1 of each
            c0, c1 = pos
            if d[c0] >= 2:
                d[c0] -= 2
            else:
                d[c0] -= 1
                d[c1] -= 1
        else:                             # one color left: take 2 (or the last 1)
            d[pos[0]] -= 2 if d[pos[0]] >= 2 else 1
        turns += 1
    return turns


def noble_progress(s: E.State, ci: int, seat: int) -> float:
    """How much ci's +1 bonus advances visible nobles for `seat`, in [0, 1].

    Folds in both *relevance* (does this bonus color still help a noble) and *closeness*
    (how near that noble already is), averaged over visible nobles. Closeness carries a
    floor (NOBLE_CLOSE_FLOOR): a card whose color a noble needs scores > 0 for that noble
    even at zero bonuses, so noble-relevance survives distance (a far noble still counts).
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
                close = 1.0 - deficit / total
                score += NOBLE_CLOSE_FLOOR + (1.0 - NOBLE_CLOSE_FLOOR) * close
    return score / n if n else 0.0


def noble_completion_pts(s: E.State, ci: int, seat: int) -> int:
    """Immediate noble VP `seat` would score by buying ci. ci grants +1 bonus in
    its color; if that newly satisfies a visible noble's full requirements the
    engine claims it (+NOBLE_PTS, see engine._after_buy_nobles). Splendor claims
    at most one noble per turn, so this returns the best single newly-claimable
    noble's points (else 0).

    A player never already-qualifies for an unclaimed visible noble (the engine
    auto-claims on the PRIOR buy), so 'would bon+1 satisfy it' is exactly 'this
    buy triggers a fresh claim' -- not double-counting a noble already won."""
    bcol = E.BONUS[ci]
    bon = s.bonuses[seat]
    best = 0
    for slot in range(3):
        ni = s.nobles[slot]
        if ni < 0:
            continue
        req = E.NOBLE_REQ[ni]
        if all(bon[c] + (1 if c == bcol else 0) >= req[c] for c in range(5)):
            p = E.NOBLE_PTS[ni]
            if p > best:
                best = p
    return best


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


# ─── take_value cost components (H2 take_value model) ─────────────────────────
# All on REMAINING need d = _color_deficits (post-bonus AND post-held-token), except
# gem_cost, which is the post-bonus STICKER price (tokens NOT subtracted). No take-2 is
# assumed: you gain at most 1 of a color per turn, so the steepest single color sets the
# turn count.

def tempo(s: E.State, ci: int, seat: int) -> int:
    """Turns to collect ci at 1 gem/color/turn: the steepest single-color REMAINING
    need, +1 if the remaining cost is exactly 1-1-1-1 (four distinct colors need a
    take-3 plus a take-1 = 2 turns, which the bare steepest of 1 would miss)."""
    d = _color_deficits(s, ci, seat)
    steepest = max(d)
    nonzero = sorted(x for x in d if x > 0)
    return steepest + (1 if nonzero == [1, 1, 1, 1] else 0)


def gem_cost(s: E.State, ci: int, seat: int) -> int:
    """Total gems to buy ci after this player's card discounts -- the post-bonus
    sticker price you pay (held tokens are NOT subtracted)."""
    return total_effective_cost(s, ci, seat)


def gold_cost(s: E.State, ci: int, seat: int) -> int:
    """Estimated gold coins needed: the bottleneck (steepest single REMAINING) color's need
    minus the up-to-GOLD_BANK_CAP of it you can pull from the bank (fewer if the opponent has
    drained it); the rest is paid in gold. Floored at 0 -- a cheap, easily-collected bottleneck
    contributes no gold cost (never a negative credit, which used to make a spread card score
    cheaper than a smaller concentrated one). 0 when nothing colored is still needed."""
    d = _color_deficits(s, ci, seat)
    steepest = max(d)
    if steepest <= 0:
        return 0
    color = max(range(5), key=d.__getitem__)
    return max(0, steepest - min(GOLD_BANK_CAP, s.bank[color]))


def gold_shortfall(s: E.State, ci: int, seat: int) -> int:
    """Gems for ci that CANNOT be collected from the bank -- per color, the remaining need
    (post bonuses + held colored tokens) beyond what the bank still holds -- summed. These
    must be covered by gold. If this exceeds the gold you hold, the card is unaffordable by
    taking alone, so gold (only obtainable by reserving) is REQUIRED. This is the exact
    'reserving is necessary' signal, e.g. needs 1 white but the bank has 0 white left."""
    d = _color_deficits(s, ci, seat)
    return sum(max(0, d[c] - s.bank[c]) for c in range(5))


RESERVED_ENGINE_W = 1.05   # a reserved card counts this much vs one board card in
                           # engine_value (committed target -> slight premium, not a pile)


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
        """Value of the permanent +1 `bcol` bonus ci grants: the discount it gives
        every *other* card that still needs `bcol` -- the visible board cards AND
        `seat`'s own RESERVED cards (committed targets you intend to buy, so a bonus
        that advances one is real engine value) -- weighted by each card's worth and
        `bcol`-hunger, plus a deck-wide term for unrevealed cards. A reserved card
        counts RESERVED_ENGINE_W *per card* (a slight commitment premium over a
        single board card), NOT a pile that dominates the board."""
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
                w_value = E.PTS[cj] / ENG_DIV + ENG_FLOOR   # high-point cards weigh more (+floor)
                sj = sum(costj)
                w_scarcity = costj[bcol] / sj if sj else 0.0  # cj is bcol-heavy
                ev += w_value * w_scarcity
        for cj in s.reserved[seat]:       # committed targets count too (slight premium)
            if cj == ci:
                continue
            costj = E.COST[cj]
            if costj[bcol] - bon_b > 0:
                sj = sum(costj)
                ev += RESERVED_ENGINE_W * (E.PTS[cj] / ENG_DIV + ENG_FLOOR) \
                    * (costj[bcol] / sj if sj else 0.0)
        ev += self.deck_color_demand[bcol] * ENG_DECK_W
        return ev

    # thin re-exports so a heuristic / encoder has one object to call ----------
    def effective_cost(self, ci: int, seat: int) -> list[int]:
        return effective_cost(self.s, ci, seat)

    def total_effective_cost(self, ci: int, seat: int) -> int:
        return total_effective_cost(self.s, ci, seat)

    def gold_needed(self, ci: int, seat: int) -> int:
        return gold_needed(self.s, ci, seat)

    def cost_concentration(self, ci: int, seat: int) -> int:
        return cost_concentration(self.s, ci, seat)

    def affordable_now(self, ci: int, seat: int) -> bool:
        return affordable_now(self.s, ci, seat)

    def gems_to_collect(self, ci: int, seat: int) -> int:
        return gems_to_collect(self.s, ci, seat)

    def turns_to_afford(self, ci: int, seat: int) -> int:
        return turns_to_afford(self.s, ci, seat)

    def noble_progress(self, ci: int, seat: int) -> float:
        return noble_progress(self.s, ci, seat)

    def noble_completion_pts(self, ci: int, seat: int) -> int:
        return noble_completion_pts(self.s, ci, seat)

    def efficiency(self, ci: int, seat: int) -> float:
        return efficiency(self.s, ci, seat)

    def victory_closeness(self, ci: int, seat: int, noble_pts: int = 0) -> float:
        return victory_closeness(self.s, ci, seat, noble_pts)

    def tempo(self, ci: int, seat: int) -> int:
        return tempo(self.s, ci, seat)

    def gem_cost(self, ci: int, seat: int) -> int:
        return gem_cost(self.s, ci, seat)

    def gold_cost(self, ci: int, seat: int) -> int:
        return gold_cost(self.s, ci, seat)

    def gold_shortfall(self, ci: int, seat: int) -> int:
        return gold_shortfall(self.s, ci, seat)
