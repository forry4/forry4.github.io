"""Card-valuation core — H3 SANDBOX fork (copy of valuation2.py).

A self-contained copy paired with `heuristic3.py` (the H3 sandbox), so aggressive
changes to the valuation model can be tried here WITHOUT touching the deployed H2
(`valuation2.py`) or the stable shared `valuation.py` that variant H + the net's
feature encoder depend on. When an experiment proves out, fold it back.

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
ENG_DECK_W = 3.5    # engine_value: weight on the forward-looking deck-demand term
# Per-card weight model for engine_value. The +1 bcol bonus's value to card cj is the actual cost
# it saves cj: 1 gem (always, since cj needs bcol to be in this sum) + 1 turn if it lowers cj's
# steepest-remaining color (reduces_tempo). This REPLACED the old w_scarcity = COST[bcol]/sum(COST)
# fraction proxy (a +1 saves exactly 1 gem regardless of how bcol-heavy cj is, so the fraction was
# mis-weighting). Non-recursive: importance stays the PTS-based w_value (level-0 approximation).
#   ENG_WEIGHT_MODE = 1 (SHIPPED): cost+tempo model. 0 = revert to the fraction proxy.
#   Validated +0.0073 vs H on fresh holdout seeds (3/4 positive), +0.020 on the tuning seeds.
ENG_WEIGHT_MODE = 1
ENG_TEMPO_SCALE = 0.3   # scale on (1 + reduces_tempo); swept best of {0.2..0.4} (0.3: +0.020, 5/6 pos)
# level-1 recursion: a card is worth discounting MORE if it's itself a strong engine card. importance(cj)
# = PTS-weight + ENG_RECURSE_W * engine_value_0(cj), where engine_value_0 is cj's LEVEL-0 (non-recursive)
# engine value, precomputed/cached per state so the whole thing stays O(cards^2). 0.0 = OFF (level-0).
ENG_RECURSE_W = 0.0
NOBLE_CLOSE_FLOOR = 0.2   # noble_progress: a card whose color a visible noble needs scores at least
                          # this (per such noble) even at zero bonuses -- "relevance" survives distance
EFF_REF = 0.45            # board_scarcity: reference points-per-effective-gem. If the board offers an
                          # L2/L3 deal at/above this, nobles are noise (scarcity 0); a poor board
                          # (best deal well below this) -> high scarcity -> go wide for nobles.

# ─── H3 potential/engine model (behind USE_POTENTIAL_ENGINE; default OFF == H2) ─────────
# Reframes engine_value as the take-value UPLIFT a card's +1 bonus gives every other card
# (engine_value(d) = Sum over targets t of Delta-take(t)), weighting targets by a separate
# POTENTIAL value (what a card is worth as a DESTINATION) rather than raw points. The point:
#   - take_value stays cost-crushed -> a far 7-white card has ~0 take value (don't chase it now)
#   - but its POTENTIAL is high (high points + the board can cheaply build it) -> so a white
#     discounter earns real engine value for enabling it, even though chasing it now is bad.
#   - Delta-take = potential(t) * [1/(1+cost') - 1/(1+cost)]; the 1/(1+cost) convexity makes a
#     discount that brings t near-affordable (2->1) worth more than one on a far card (6->5)
#     FOR FREE -- no separate magnitude knob. See heuristic3 docstring for the full model.
# TUNED (h3_vs_h2 coordinate descent, validated on disjoint holdout seeds): the package
# {USE_POTENTIAL_ENGINE on, POT_ENGINE_W=0.5, heuristic3.W_GEM=0.3} scores ~0.51-0.55 vs H2
# head-to-head (a slight edge) and -- the more trustworthy signal -- beats the independent
# yardstick H by MORE than H2 does (0.72-0.73 vs H2's 0.67-0.69) across two disjoint ranges.
# To recover the exact H2 baseline for A/B: set USE_POTENTIAL_ENGINE=False AND heuristic3.W_GEM=0.2.
USE_POTENTIAL_ENGINE = True   # master switch. False => engine_value byte-identical to valuation2 (H2).
POT_ENGINE_W = 0.5   # weight on a target's OWN (level-0) engine value inside its potential -- a card
                     # you discount is worth more if it is itself a strong engine card (0-pt L1 chains).
                     # TUNED: a clean peak at 0.5 (1.0/2.0 over-weighted engine -> regressed vs H2).
POT_REACH_W = 0.0    # weight on REACHABILITY (cheap board discounters for this card). 0 = OFF (TUNED:
                     # every level tested REGRESSED vs H2 -- discounters already earn value via the
                     # Delta-take engine term, so multiplying potential by reach double-counts them).
REACH_DIV = 4.0      # normalizer for the summed discounter accessibility in _reachability


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


def _reduces_tempo(costj, bon, bcol: int) -> float:
    """1.0 if a +1 `bcol` bonus lowers card cj's steepest-remaining color (saves a TURN), else 0.0.
    Uses H2's tempo definition (steepest single need, +1 if the remainder is exactly 1-1-1-1) on the
    post-bonus remainder. Caller has gated on cj still needing bcol, so rem[bcol] >= 1. O(5), no recursion."""
    rem = [costj[c] - bon[c] if costj[c] > bon[c] else 0 for c in range(5)]

    def _t(r):
        st = max(r)
        nz = sorted(x for x in r if x > 0)
        return st + (1 if nz == [1, 1, 1, 1] else 0)

    before = _t(rem)
    rem[bcol] -= 1
    return 1.0 if _t(rem) < before else 0.0


RESERVED_ENGINE_W = 1.05   # a reserved card counts this much vs one board card in
                           # engine_value (committed target -> slight premium, not a pile)


# ─── Stateful context (precomputes state-wide aggregates once) ───────────────

class Valuation:
    """Per-state valuation context. Precomputes aggregates that are constant
    across cards (deck color demand) so per-card queries stay cheap. Build one
    per state evaluation and reuse across all candidate cards and both seats.

    Stateless scalars above are re-exposed as methods for a single call site.
    """

    __slots__ = ("s", "deck_color_demand", "_scarcity_cache", "_eng_base_cache",
                 "w_tempo", "w_gem", "w_gold", "_take0_cache", "_pot_cache")

    def __init__(self, s: E.State, w_tempo: float = 0.5, w_gem: float = 0.2,
                 w_gold: float = 0.4):
        self.s = s
        self._scarcity_cache = {}
        self._eng_base_cache = {}
        # take_value cost weights -- ONLY used by the H3 potential/engine model (so it
        # measures discounts in the same currency take_value charges). Defaults mirror
        # heuristic3's W_TEMPO/W_GEM/W_GOLD; heuristic3 passes its live values in. Unused
        # by the legacy engine_value, so the USE_POTENTIAL_ENGINE=False path is unaffected.
        self.w_tempo = w_tempo
        self.w_gem = w_gem
        self.w_gold = w_gold
        self._take0_cache = {}
        self._pot_cache = {}
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
    def engine_value(self, ci: int, seat: int, _recurse: bool = True) -> float:
        """Value of the permanent +1 bonus ci grants. Dispatches on USE_POTENTIAL_ENGINE:
        the legacy H2 proxy (default -- byte-identical to valuation2) or the H3 Delta-take
        model. The H3 path: engine_value(ci) = Sum over OTHER cards cj still needing ci's
        color of Delta-take(cj) (+ reserved at a premium + the deck-demand term) -- the
        take-value uplift ci's bonus gives each cj, already weighted by cj's POTENTIAL and
        its nearness-to-affordable (the 1/(1+cost) convexity inside _delta_take). No extra
        importance multiplier here: _delta_take carries both, so there is no double count."""
        if not USE_POTENTIAL_ENGINE:
            return self._engine_value_legacy(ci, seat, _recurse)
        s = self.s
        bcol = E.BONUS[ci]
        bon_b = s.bonuses[seat][bcol]
        ev = 0.0
        for slot in range(12):
            cj = s.board[slot]
            if cj < 0 or cj == ci:
                continue
            if E.COST[cj][bcol] - bon_b > 0:            # cj still needs this color
                ev += self._delta_take(cj, seat, bcol)
        for cj in s.reserved[seat]:                     # committed targets: slight premium
            if cj == ci:
                continue
            if E.COST[cj][bcol] - bon_b > 0:
                ev += RESERVED_ENGINE_W * self._delta_take(cj, seat, bcol)
        ev += self.deck_color_demand[bcol] * ENG_DECK_W
        return ev

    def _engine_value_legacy(self, ci: int, seat: int, _recurse: bool = True) -> float:
        """The H2/valuation2 engine value: the discount ci's +1 `bcol` bonus gives every
        *other* card that still needs `bcol` -- the visible board cards AND `seat`'s own
        RESERVED cards (committed targets) -- weighted by each card's worth and the
        cost/tempo it saves (`_w_card`), plus a deck-wide term for unrevealed cards.

        Each card cj's importance is its PTS-weight, plus (if ENG_RECURSE_W) a level-1
        term ENG_RECURSE_W * (cj's own LEVEL-0 engine value). `_recurse=False` computes the
        level-0 value (no recursion); the level-1 path calls it via `_eng_base` (cached)."""
        s = self.s
        bcol = E.BONUS[ci]
        bon_b = s.bonuses[seat][bcol]
        recurse = _recurse and ENG_RECURSE_W
        ev = 0.0
        for slot in range(12):
            cj = s.board[slot]
            if cj < 0 or cj == ci:
                continue
            costj = E.COST[cj]
            if costj[bcol] - bon_b > 0:  # cj still needs this color
                imp = E.PTS[cj] / ENG_DIV + ENG_FLOOR   # importance: high-point cards weigh more (+floor)
                if recurse:
                    imp += ENG_RECURSE_W * self._eng_base(cj, seat)
                ev += imp * self._w_card(costj, s.bonuses[seat], bcol)
        for cj in s.reserved[seat]:       # committed targets count too (slight premium)
            if cj == ci:
                continue
            costj = E.COST[cj]
            if costj[bcol] - bon_b > 0:
                imp = E.PTS[cj] / ENG_DIV + ENG_FLOOR
                if recurse:
                    imp += ENG_RECURSE_W * self._eng_base(cj, seat)
                ev += RESERVED_ENGINE_W * imp * self._w_card(costj, s.bonuses[seat], bcol)
        ev += self.deck_color_demand[bcol] * ENG_DECK_W
        return ev

    @staticmethod
    def _w_card(costj, bon, bcol: int) -> float:
        """Per-card engine weight: cost+tempo (gem saved 1 + turn saved 0/1, scaled) when
        ENG_WEIGHT_MODE, else the legacy w_scarcity cost-fraction proxy."""
        if ENG_WEIGHT_MODE:
            return ENG_TEMPO_SCALE * (1.0 + _reduces_tempo(costj, bon, bcol))
        sj = sum(costj)
        return costj[bcol] / sj if sj else 0.0

    def _eng_base(self, cj: int, seat: int) -> float:
        """cj's LEVEL-0 (legacy, non-recursive) engine value, cached per state. Used as the
        recursive importance term in the legacy model AND as the 'own engine strength' term
        inside H3's potential_value -- always the legacy level-0, never the H3 body (so the
        H3 recursion stays bounded at one level)."""
        key = (cj, seat)
        v = self._eng_base_cache.get(key)
        if v is None:
            v = self._engine_value_legacy(cj, seat, _recurse=False)
            self._eng_base_cache[key] = v
        return v

    # ─── H3 potential/engine model (active only when USE_POTENTIAL_ENGINE) ───────
    def _cost_scalar(self, ci: int, seat: int, extra_bcol: int | None = None) -> float:
        """take_value's total_cost (W_TEMPO*tempo + W_GEM*gem + W_GOLD*gold) for ci, optionally
        as if `seat` held one EXTRA bonus in `extra_bcol`. Mirrors tempo()/gem_cost()/gold_cost()
        so the H3 engine measures a discount in the exact currency take_value charges."""
        s = self.s
        cost = E.COST[ci]
        bon = s.bonuses[seat]
        tok = s.tokens[seat]

        def b(c):
            return bon[c] + (1 if c == extra_bcol else 0)

        gem = sum(cost[c] - b(c) for c in range(5) if cost[c] > b(c))   # sticker price (tokens NOT subtracted)
        d = [cost[c] - b(c) - tok[c] for c in range(5)]                 # remaining after bonuses + held tokens
        d = [x if x > 0 else 0 for x in d]
        steepest = max(d)
        if steepest <= 0:
            tempo = gold = 0
        else:
            nz = sorted(x for x in d if x > 0)
            tempo = steepest + (1 if nz == [1, 1, 1, 1] else 0)
            color = max(range(5), key=d.__getitem__)
            gold = max(0, steepest - min(GOLD_BANK_CAP, s.bank[color]))
        return self.w_tempo * tempo + self.w_gem * gem + self.w_gold * gold

    def take0(self, ci: int, seat: int) -> float:
        """Level-0 take value: realizable POINTS over (1 + cost), with NO engine term in the
        numerator (engine value is what H3 is computing, so it must not appear here -- this is
        what keeps the recursion bounded). Used for discounter accessibility in _reachability."""
        key = (ci, seat)
        v = self._take0_cache.get(key)
        if v is None:
            v = E.PTS[ci] / (1.0 + self._cost_scalar(ci, seat))
            self._take0_cache[key] = v
        return v

    def _reachability(self, ci: int, seat: int) -> float:
        """How reachable ci is via the engine: summed ACCESSIBILITY (1/(1+cost)) of OTHER
        board cards whose bonus color ci still needs -- cheap cards that build the colors ci
        is short on. High for a costly card the board can cheaply build (the '7-white amid
        white L1s' case). Cost-accessibility, not take value, so 0-pt engine cards still count."""
        s = self.s
        cost = E.COST[ci]
        bon = s.bonuses[seat]
        need = [cost[c] - bon[c] > 0 for c in range(5)]
        r = 0.0
        for slot in range(12):
            cj = s.board[slot]
            if cj < 0 or cj == ci:
                continue
            if need[E.BONUS[cj]]:
                r += 1.0 / (1.0 + self._cost_scalar(cj, seat))
        return r / REACH_DIV

    def potential_value(self, ci: int, seat: int) -> float:
        """Latent worth of ci as a DESTINATION (the importance the H3 engine weights targets by):
        realizable points + its own (level-0) engine value, scaled up by reachability. DISTINCT
        from take_value -- a far high-point card the board can cheaply build has high potential but
        ~0 take value, which is exactly why a discounter for it earns engine value while chasing it
        now would be bad. (Falls back to the legacy PTS/ENG_DIV+FLOOR importance when the flag is off,
        so other code paths can call it uniformly.)"""
        if not USE_POTENTIAL_ENGINE:
            return E.PTS[ci] / ENG_DIV + ENG_FLOOR
        key = (ci, seat)
        v = self._pot_cache.get(key)
        if v is None:
            v = E.PTS[ci] + POT_ENGINE_W * self._eng_base(ci, seat)
            if POT_REACH_W:
                v *= 1.0 + POT_REACH_W * self._reachability(ci, seat)
            self._pot_cache[key] = v
        return v

    def _delta_take(self, ci: int, seat: int, bcol: int) -> float:
        """take-value uplift a +1 `bcol` bonus gives card ci: potential(ci) * the convexity gap
        1/(1+cost') - 1/(1+cost). >= 0 (a +1 in a needed color never raises cost). The convexity
        auto-weights a near-affordable discount (2->1) above a far one (6->5) with no extra knob."""
        c0 = self._cost_scalar(ci, seat)
        c1 = self._cost_scalar(ci, seat, extra_bcol=bcol)
        return self.potential_value(ci, seat) * (1.0 / (1.0 + c1) - 1.0 / (1.0 + c0))

    def board_scarcity(self, seat: int) -> float:
        """How scarce efficient high-point targets are on the board, in [0, 1] (high = scarce).

        The strategy model: noble value scales INVERSELY with board efficiency. When the board has
        an efficient high-point L2/L3 card to race (good points-per-effective-gem), nobles are noise;
        when it doesn't, the only way to afford the inefficient point cards is a wide L1 engine, and
        breadth delivers nobles for free -- so nobles are worth more. Scarcity = how far the board's
        BEST L2/L3 deal falls below EFF_REF. Cached per seat (state-wide, not per-card)."""
        c = self._scarcity_cache.get(seat)
        if c is not None:
            return c
        s = self.s
        best = 0.0
        for slot in range(12):
            ci = s.board[slot]
            if ci < 0 or E.LEVEL_OF[ci] < 2:      # L2/L3 are the point-racing cards
                continue
            e = self.efficiency(ci, seat)         # PTS / (total_effective_cost + 1)
            if e > best:
                best = e
        v = 1.0 - best / EFF_REF
        v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
        self._scarcity_cache[seat] = v
        return v

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
