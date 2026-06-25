"""v4 heuristic bot — H3 SANDBOX (copy of H2's `take_value` model, for value experiments).

A from-scratch valuation paired with `valuation3.py` — a sandbox fork of H2 (`heuristic2.py`
+ `valuation2.py`) so values can be tuned here WITHOUT touching the deployed H2. See H2.md
(this directory) for the full write-up of the model below.

Model — every card gets a single scalar:

    take_value = (engine_value + point_value) / (1 + total_cost)

    total_cost  = W_TEMPO*tempo + W_GEM*gem + W_GOLD*gold        (importance tempo > gem > gold)
    point_value = stage * (PTS + NOBLE_SCALE*noble_progress) + noble_completion
    engine_value = valuation2.engine_value (undiscounted -- realized + compounding on purchase)

All cost terms are post-cost-reduction (minus owned-card bonuses), never base cost. `tempo`
and `gold` are on REMAINING need (also minus held tokens); `gem` is the post-bonus sticker
price. No take-2 is assumed (1 gem of a color per turn). `tempo` lives ONLY in `total_cost`
-- it is collection EFFORT (a cost), not a devaluation of a card's points/engine.

POINT STAGING (replaces the old per-card tempo-discount): the *future* points
(PTS + noble_progress) are scaled by a global game STAGE -- low early, ramping to 1 -- so the
bot builds its engine first and values points as the game develops; the +3 from
noble_completion is realized immediately, so it is NOT staged.
  stage = floor + (1-floor) * min(1, max(cards_bought/STAGE_K, leader_points/15))
Being a global multiplier (same for every card), a 2-pt card's point_value is exactly 2x a
1-pt card's at the same stage. This beats H ~0.62 (vs 0.485 for the old tempo-discount).

Policy (`choose_action`): winning buy (secure) > winning-via-RESERVE > endgame denial >
token-cap anti-hoard > buy the top-take_value card if affordable, else take gems toward it
(spare picks to the next-best). Far cards self-deprioritize via their large total_cost.

Reserving: only the WINNING-reserve is on -- a winning card blocked solely by an out-of-bank
gem is reserved to bank the gold and win next turn (a free win, costs nothing otherwise).
Speculative acquisition/gold reserves are implemented but OFF (USE_SPECULATIVE_RESERVE):
measured as a pure tempo drag, and H itself gains ~0 from reserving. NOT used: stage ramp,
eng_decay, mirage/reachability gate, the points-per-gem efficiency term, the buy-floor.
"""
from __future__ import annotations

from . import engine as E
from . import valuation3 as V

# ─── Tuned config (offline search; beats H ~0.62) ────────────────────────────────────
W_TEMPO = 0.1      # cost: turns to collect. TUNED for the turns_remaining model (was 0.5): with
                   # engine now scaled by compounding turns, low tempo-cost plays best. Part of the
                   # validated package {W_TEMPO=0.1, NOBLE_CLOSE_FLOOR=0.3, W_ENGINE=0.15}.
W_GEM = 0.3        # cost: total post-bonus gems to pay. TUNED for H3 (H2 uses 0.2): the gain is
                   # COUPLED to the new engine (valuation3 measures discounts in this currency) --
                   # raising it with the engine OFF is neutral vs H2 (~0.497). Set back to 0.2 to
                   # recover the exact-H2 baseline (with valuation3.USE_POTENTIAL_ENGINE=False).
W_GOLD = 0.4       # cost: estimated gold coins needed (bottleneck color vs the bank)
W_SHORTFALL = 0.0  # cost: gems the bank CANNOT supply across ALL needed colors (gold_shortfall).
                   # gold_cost only sees the bottleneck color, so a card blocked on a NON-bottleneck
                   # color isn't demoted and the bot stalls collecting toward an un-completable card
                   # (~14.9% of take-turns). This term penalizes ALL bank-blocked colors so the
                   # ranking pivots to an attainable card. TESTED at 0.2: cuts stalls 14.9%->11.6%
                   # and leans +0.006 win rate (6/8 disjoint seeds positive) but below significance
                   # -- a marginal correctness fix, left OFF (0.0). Flip to ~0.2 to re-enable.
# late-game tempo scaling (EXPERIMENT, default OFF). A turn is more precious late (few turns left),
# so the tempo COST weight should rise as the MEASURED turns_remaining shrinks. The crude ply/cards
# "stage" form of this was tested and hurt (-0.02); this uses turns_remaining (board-conditional)
# and only the cost denominator (the engine term already discounts by turns_remaining). Effective:
#     W_TEMPO_eff = W_TEMPO * (1 + TEMPO_TURNS_SCALE * max(0, 1 - turns_remaining / TEMPO_TURNS_T0))
# 0.0 = OFF (byte-identical). Feeds H3 take_value -> S's policy prior + leaf progress term.
TEMPO_TURNS_SCALE = 0.0  # strength k: late W_TEMPO peaks at W_TEMPO*(1+k) as turns_remaining -> 0
TEMPO_TURNS_T0 = 20.0    # horizon at/above which no scaling applies (early-game turns_remaining ~26)
NOBLE_SCALE = 3.0  # noble-progress contribution, scaled toward a noble's VP. Retuned 5.0->3.5->3.0
                   # (June 2026). Affects BOTH H3 and S (S reads it via prior + leaf).
                   # (Prior note: 3.0->5.0 was +0.0073 avg(H2,H2R), now superseded.)
NOBLE_SCARCITY = 0.0  # board-conditional noble boost: noble term *= (1 + NOBLE_SCARCITY*board_scarcity).
                      # Per the strategy model nobles matter MORE when the board lacks efficient
                      # high-point cards to race (go wide for nobles). H2 loses the noble race in its
                      # losses (0.48 vs opp 1.27 nobles) with a FLAT noble weight; this gates it on the
                      # board. 0.0 = OFF (flat, no change); tuned below.

# point staging: future points scaled by a global game stage (low early -> 1 late)
STAGE_K = 8        # cards-bought for a full engine-stage; stage = max(cards/STAGE_K, leader_pts/15)
STAGE_FLOOR = 0.25  # early floor: fraction of point value still counted at game start
# NEW stage model (STAGE_BLEND): instead of stage = max(YOUR cards/STAGE_K, LEADER points/15),
# blend BOTH players' totals into each term, weighting your own above the opponent's:
#   cards_term  = (your_cards  + STAGE_CARD_OPP_W * opp_cards)  / STAGE_K
#   points_term = (your_points + STAGE_PTS_OPP_W  * opp_points) / WIN_POINTS
#   stage       = max(cards_term, points_term)            # capped at 1
# So total board progress (both players' cards) AND total points advance the stage, but yours count
# more. STAGE_CARD_OPP_W = STAGE_PTS_OPP_W = 0 recovers the old "yours-cards / leader-points" behavior
# only if you also revert the points term to max(); the flag toggles the whole new form vs the old.
STAGE_BLEND = True       # use the blended stage above (False = legacy max(your_cards, leader_points))
STAGE_CARD_OPP_W = 0.5   # weight on the OPPONENT's purchased cards in the stage cards term (yours = 1.0)
STAGE_PTS_OPP_W = 0.5    # weight on the OPPONENT's points in the stage points term (yours = 1.0)

# engine horizon-decay (the MIRROR of point staging): an engine card built late has few
# remaining buys to pay off, so engine value should fall as we accumulate cards. Scales engine
# by (1 - ENG_DECAY * own), own = min(1, cards_we_own/STAGE_K). 0.0 = OFF (flat engine value).
# 0.3 (tuned): engine fades to ~70% of early value by ~8 cards bought -- a gentle fade, not a
# collapse. The ROBUST value: positive on all 6 fresh holdout seed sets (11/12 over both rounds).
# Higher over-corrected (0.5 had a real -0.025 downside seed; 1.0 was -0.045); lower (0.1) was a
# no-op (~0.000).
#   CAVEAT: the effect is MINIMAL -- only ~+0.011 win rate vs H (the big lever was ENG_DECK_W +
#   NOBLE_SCALE, ~+0.06). Worth keeping for correctness (it's the conceptual mirror of the point
#   stage), but it is NOT a major strength driver. It also reuses `own = cards/STAGE_K` -- exactly
#   the quantity behind the point `stage` -- so a future cleanup could FOLD this into the stage
#   machinery (one shared game-progress signal driving points up AND engine down) instead of
#   carrying ENG_DECAY as a separate knob.
ENG_DECAY = 0.3    # SUPERSEDED by the turns_remaining engine model (W_ENGINE) -- no longer read.

# ─── turns_remaining engine model (replaces point-staging + ENG_DECAY) ───────────────────────
# Points are no longer stage-scaled (full value always). Instead, engine value is multiplied by the
# turns it will actually COMPOUND: W_ENGINE * max(0, turns_remaining - tempo), where turns_remaining
# is the estimated future main turns (valuation3 turns_table) and tempo is the card's acquisition
# cost in turns. So a card you can't finish before the game ends contributes ~0 engine value, and an
# engine acquired early (many turns left) is worth proportionally more. W_ENGINE keeps the (now
# turns-scaled, so much larger) engine term balanced against unscaled points; tune it.
W_ENGINE = 0.15   # TUNED: clean peak on two disjoint seed ranges (0.533/0.542 vs H2; 0.10 starves
                  # the engine, 0.25+ over-feeds it). Balances the turns-scaled engine vs unscaled points.

# token-cap anti-hoard: near the 10-cap, buy the best affordable instead of taking gems
CAP9_BUY_ABOVE = 0.5    # at 9 tokens, buy the best affordable card if its take_value exceeds this
CAP8_BUY_ABOVE = 0.8    # at 8 tokens, likewise (buy more readily as you approach 10)
GOLD_TIEBREAK = 0.2     # small penalty per gold a buy spends; reorders near-ties among buys

# reserve toggles
USE_RESERVE = True               # WINNING-reserve (a winning card blocked by an out-of-bank gem) -- on
USE_SPECULATIVE_RESERVE = False  # acquisition + gold-necessary reserves: OFF -- a measured tempo drag
                                 # (H gains ~0 from reserving too). Kept behind the flag for A/B.
RESERVE_GAP = 0.5                # acquisition (speculative only): reserve the top unaffordable board
                                 # card when its take_value exceeds the next board card's by >= this.
WIN_RESERVE_MAX_TEMPO = 4        # winning-reserve only fires when the winning card is < this many turns
                                 # (tempo) from collectable. Without it the bot would lock a "win" it
                                 # can't complete soon -- a far gold-blocked card (e.g. tempo 6) got
                                 # reserved over building the reachable top card. >= 99 disables it.

# take-2-same: the model otherwise assumes <=1 gem/color/turn, so the bot never takes 2 of one
# color. _bottleneck_take2 implements the one defensible exception -- take 2 to finish a card we
# have RESERVED that is waiting on a SINGLE remaining color (>= TAKE2_MIN_STEEP) the bank is full
# of. RESERVED-only is the conceptually-right form: a reserved card is locked (opponent can't take
# it, board can't churn it away), so committing 2 gems to its one remaining color has none of the
# option-value cost that made take-2 toward a BOARD card a measured wash (-0.006) / the naive
# any-card version an outright loss (-0.03).
#   MEASURED ~NEUTRAL (slightly -0.003), but only because it almost never fires (0.27%): H2's only
#   reserves are WINNING reserves, which are gold-necessary (blocked by a gem the bank CAN'T
#   supply) -- the opposite of take-2's "bank full of it", so the two conditions rarely co-occur.
#   To make this matter, the bot would need to SPECULATIVELY reserve deep single-color cards and
#   then take-2 to finish them (an untested combined experiment). Kept behind the flag, default OFF.
USE_TAKE2 = False
TAKE2_MIN_STEEP = 2              # min remaining need in the bottleneck color to fire the take-2

# opponent-snipe pivot: if your top take_value target is unaffordable to YOU but affordable to the
# OPPONENT, assume they buy it -> don't waste tempo collecting toward a card you'll lose; pivot
# gem-taking to your next-best attainable target. SNIPE_REQUIRE_OPP_TOP only pivots when the card
# is ALSO the opponent's highest take_value pick (high-confidence they actually take it).
# TESTED, left OFF: ungated (any opp-affordable) was clearly NEGATIVE (all 3 seeds, -0.003..-0.012);
# gated (opp-top) was a high-variance WASH (mean ~+0.003 over 5 disjoint seeds but two -0.013 seeds).
# Matches the documented "contention/denial is a 1-ply greedy wash" -- a NET-feature candidate (opp
# affordability + contention), not a greedy-H2 lever. Flip to True (+ keep the gate) to re-enable.
USE_OPP_SNIPE = False
SNIPE_REQUIRE_OPP_TOP = True

# 2-turn endgame denial: deny a board card the opponent can't afford NOW but could after
# getting 1 gold from reserving it, when buying it next turn would win the game.
# Exactly the IYGWJQ blind spot (opponent reserves then buys a winning card in 2 turns).
USE_DENY2 = True

# ─── slot-pressure reserve finisher ──────────────────────────────────────────────────────────
# Near the token cap the spread take-1/take-3 path can STALL: it grabs 1 gem/turn toward a single-
# color bottleneck, climbs to 8-10 tokens, then take-and-discard churns without ever finishing the
# card (observed: bot 2 white short of its top card at 8/10 slots, never closing it). Fix: when the
# TOP take_value target is one good turn from done, RESERVE it -- this locks it from the opponent /
# board churn AND banks a gold that covers the remaining need.
#   Validated +0.011..+0.014 vs H2 and +0.013..+0.016 vs H over two disjoint seed sets (N=4-6k).
# (A companion take-2 finisher was tested and SCRAPPED: even restricted to a single remaining color
#  it was a wash vs H2 / slight drag vs H, and hurt the win rate when combined with this reserve.)
USE_FINISH_RESERVE = True   # at 8 tokens & exactly 2-of-one-color away, or 9 tokens & 1 gem away,
                            # reserve the top board card (free reserve slot + bank gold required)


def components(val: V.Valuation, ci: int, seat: int):
    """The take_value pieces for `ci` from `seat`: (take, engine, point, cost).
    One source of truth for both the policy and the on-card transparency overlay.
    The state is `val.s` (the Valuation owns it) — no separate state arg to pass wrongly.

    Cached per (ci, seat) on the Valuation: the same card is scored repeatedly within a leaf (the H3
    policy-anchor's `_targets` re-sweep + the `_seat_targets`/buy overlap), so this dedupes the WHOLE
    components computation. Guard-safe: a cache hit still calls `estimated_turns_remaining()` (cheap,
    `_turns_cache`-backed) so the freshness assert fires on EVERY components call, hit or miss."""
    cache = val._comp_cache
    ck = (ci, seat)
    hit = cache.get(ck)
    if hit is not None:
        val.estimated_turns_remaining()   # fire the freshness guard (+ catch stale reuse) on cache hits
        return hit
    w_tempo = W_TEMPO
    if TEMPO_TURNS_SCALE:  # late-game tempo weight rises as measured turns_remaining shrinks
        tr = val.estimated_turns_remaining()
        if tr < TEMPO_TURNS_T0:
            w_tempo = W_TEMPO * (1.0 + TEMPO_TURNS_SCALE * (1.0 - tr / TEMPO_TURNS_T0))
    cost = (w_tempo * val.tempo(ci, seat)
            + W_GEM * val.gem_cost(ci, seat)
            + W_GOLD * val.gold_cost(ci, seat))
    if W_SHORTFALL:  # penalize bank-uncollectable gems (all colors) -> demote un-completable cards
        cost += W_SHORTFALL * val.gold_shortfall(ci, seat)
    # engine value is multiplied by the turns it will COMPOUND: max(0, turns_remaining - tempo).
    # A card that can't be finished before the game ends contributes ~0 engine; an engine acquired
    # with many turns left is worth proportionally more. Replaces point-staging + ENG_DECAY.
    engine = val.engine_value(ci, seat)
    compound_turns = val.estimated_turns_remaining() - val.tempo(ci, seat)
    engine *= W_ENGINE * (compound_turns if compound_turns > 0.0 else 0.0)
    # points are NOT staged -- full value always.
    if V.NOBLE_RACE_W:  # marginal win-probability model -> noble_progress returns dP_win; NOBLE_RACE_W weights it
        noble_scale = V.NOBLE_RACE_W
    else:
        noble_scale = NOBLE_SCALE
        if NOBLE_SCARCITY:  # board-conditional: weight nobles more when efficient point cards are scarce
            noble_scale *= 1.0 + NOBLE_SCARCITY * val.board_scarcity(seat)
    point = E.PTS[ci] + noble_scale * val.noble_progress(ci, seat) + val.noble_completion_pts(ci, seat)
    take = (engine + point) / (1.0 + cost)
    result = (take, engine, point, cost)
    cache[ck] = result
    return result


def take_value(val: V.Valuation, ci: int, seat: int) -> float:
    """Single scalar worth of card `ci` to `seat`: benefit (engine + distance-
    discounted points) over (1 + total cost). See the module docstring."""
    return components(val, ci, seat)[0]


def _take_colors(a: int):
    """Color tuple a take action grabs, or None if `a` is not a take."""
    if E.A_TAKE3 <= a < E.A_TAKE2D:
        return E.TAKE3[a - E.A_TAKE3]
    if E.A_TAKE2D <= a < E.A_TAKE1:
        return E.TAKE2D[a - E.A_TAKE2D]
    if E.A_TAKE1 <= a < E.A_TAKE2S:
        return (a - E.A_TAKE1,)
    if E.A_TAKE2S <= a < E.A_PASS:
        c = a - E.A_TAKE2S
        return (c, c)
    return None


def _is_take2s(a: int) -> bool:
    """True if `a` is a take-2-of-one-color action (excluded under the no-take-2 rule)."""
    return E.A_TAKE2S <= a < E.A_PASS


def _need_vector(s, seat, targets) -> list[float]:
    """Color demand summed over the top take_value cards, weighted by value and
    per-color remaining deficit — which gems move us toward cards we actually want."""
    need = [0.0] * 5
    for tv, ci, _idx, _kind in targets[:3]:
        if tv <= 0:
            continue
        d = V._color_deficits(s, ci, seat)
        for i in range(5):
            need[i] += tv * d[i]
    return need


def _choose_take(s, seat, val, targets, legal):
    """Take the gems (1 per color; never take-2-same) that bring the top take_value
    card closest to affordable — minimize its tempo, then its remaining gems, then
    break ties by usefulness to the next targets. Spare picks thus spill to the
    next-best card via the need vector."""
    target = targets[0][1] if targets else None
    if target is not None:
        need = _need_vector(s, seat, targets)
        tok = s.tokens[seat]
        best_a, best_key = None, None
        for a in legal:
            colors = _take_colors(a)
            if colors is None or _is_take2s(a):
                continue
            for c in colors:          # simulate taking these gems...
                tok[c] += 1
            key = (val.tempo(target, seat),
                   sum(V._color_deficits(s, target, seat)),
                   -sum(need[c] for c in colors))
            for c in colors:          # ...then restore
                tok[c] -= 1
            if best_key is None or key < best_key:
                best_key, best_a = key, a
        if best_a is not None:
            return best_a
    # Fallback: a generically useful take-3, then any non-take-2-same take.
    for a in legal:
        if E.A_TAKE3 <= a < E.A_TAKE2D:
            return a
    for a in legal:
        if _take_colors(a) is not None and not _is_take2s(a):
            return a
    return None


def _bottleneck_take2(s, seat, val, legal_set):
    """Take-2 of a single-color bottleneck, but ONLY to finish a card we have RESERVED.

    Reserved cards are LOCKED (the opponent can't take them, the board can't churn them away) and
    are typically the deep single-color L2/L3s you commit to -- so pouring 2 gems into a reserved
    card's one remaining color has none of the option-value cost that made take-2 toward a BOARD
    card a wash (a board card can vanish or be out-raced; a reserved one is already yours, just
    complete it). The "2 white when you also need red" trap is excluded by requiring a SINGLE
    remaining color. Fires for the reserved card closest to done that qualifies:
      - reserved + unaffordable now,
      - exactly ONE color still needed, >= TAKE2_MIN_STEEP of it,
      - the take-2 action for that color is legal (engine requires bank[color] >= 4 == full).
    Returns the take-2 action, or None.
    """
    best = None
    for ci in s.reserved[seat]:
        if val.affordable_now(ci, seat):
            continue
        d = V._color_deficits(s, ci, seat)
        needed = [c for c in range(5) if d[c] > 0]
        if len(needed) != 1:                  # single remaining color (excludes the multi-color trap)
            continue
        col = needed[0]
        if d[col] < TAKE2_MIN_STEEP:          # need 2+ of it for a take-2 to beat a take-1
            continue
        a = E.A_TAKE2S + col
        if a in legal_set and (best is None or d[col] < best[1]):   # closest reserved card to done
            best = (a, d[col])
    return best[0] if best else None


def _choose_discard(s, seat, legal, targets):
    """Discard the token least useful to the top targets; never gold unless only gold."""
    need = _need_vector(s, seat, targets)
    best_a, best_key = None, None
    for a in legal:
        c = a - E.A_DISCARD
        is_gold = c == 5
        need_c = float("inf") if is_gold else need[c]
        # prefer: non-gold, then low need, then dump the color we hold most of
        key = (is_gold, need_c, -s.tokens[seat][c])
        if best_key is None or key < best_key:
            best_key, best_a = key, a
    return best_a


def _targets(val, s, seat):
    """All board + own-reserved cards as (take_value, ci, index, kind), best first."""
    out = []
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            out.append((take_value(val, ci, seat), ci, slot, "board"))
    for ri, ci in enumerate(s.reserved[seat]):
        out.append((take_value(val, ci, seat), ci, ri, "resv"))
    out.sort(reverse=True, key=lambda t: t[0])
    return out


def _opp_best_buy(s, opp, val):
    """The opponent's best single buy on their NEXT turn: over board + their own
    reserved cards they can afford NOW, the one maximizing points + any noble it
    triggers. Returns (gain, ci, slot) — slot is the board slot (>=0, deniable) or
    -1 (their own reserved card, not deniable)."""
    best_gain, best_ci, best_slot = 0, -1, -1
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0 and val.affordable_now(ci, opp):
            gain = E.PTS[ci] + val.noble_completion_pts(ci, opp)
            if gain > best_gain:
                best_gain, best_ci, best_slot = gain, ci, slot
    for ci in s.reserved[opp]:
        if val.affordable_now(ci, opp):
            gain = E.PTS[ci] + val.noble_completion_pts(ci, opp)
            if gain > best_gain:
                best_gain, best_ci, best_slot = gain, ci, -1
    return best_gain, best_ci, best_slot


def _opp_best_reserve_buy(s, opp, val):
    """Opponent's best 2-turn sequence: reserve a board card now (gaining 1 gold) then buy it
    next turn to win. Only fires when the card is unaffordable NOW but affordable after +1 gold,
    the opponent has a free reserve slot, and the bank has gold. Returns (gain, ci, slot) where
    slot >= 0 is deniable, or (0, -1, -1) if no such 2-turn threat exists."""
    if s.bank[5] <= 0 or len(s.reserved[opp]) >= 3:
        return 0, -1, -1
    opp_gold = s.tokens[opp][5]
    best_gain, best_ci, best_slot = 0, -1, -1
    for slot in range(12):
        ci = s.board[slot]
        if ci < 0:
            continue
        if val.affordable_now(ci, opp):
            continue                                    # already a 1-turn threat, caught by _opp_best_buy
        if val.gold_needed(ci, opp) != opp_gold + 1:   # exactly 1 gold short (reserve gives exactly that)
            continue
        gain = E.PTS[ci] + val.noble_completion_pts(ci, opp)
        if gain > best_gain:
            best_gain, best_ci, best_slot = gain, ci, slot
    return best_gain, best_ci, best_slot


def _secure_win(s, seat, p_win, cards_win, val):
    """Would reaching `p_win` points (with `cards_win` purchased cards) actually WIN,
    given the final-round rule? Seat 1 — or the bot already on the final turn — wins
    immediately. Seat 0 hands the opponent one final turn, so it's secure only if they
    cannot overtake with their best buy (tiebreak: most points, then FEWEST cards)."""
    opp = 1 - seat
    if seat == 1 or s.final_trigger == opp:
        return True
    gain, _ci, _slot = _opp_best_buy(s, opp, val)
    opp_pts = s.points[opp] + gain
    opp_cards = s.purchased_n[opp] + (1 if gain > 0 else 0)
    overtakes = opp_pts > p_win or (opp_pts == p_win and opp_cards < cards_win)
    return not overtakes


def _deny(s, seat, slot, ci, val, legal_set):
    """Minimal denial-only reserve: deny the opponent a board card by reserving it (a
    free slot) else buying it (if affordable). Returns a legal action, or None."""
    if len(s.reserved[seat]) < 3:
        a = E.A_RES_BOARD + slot
        if a in legal_set:
            return a
    if val.affordable_now(ci, seat):
        a = E.A_BUY_BOARD + slot
        if a in legal_set:
            return a
    return None


def _reservable(s, seat, ci, slot, val, legal_set):
    """A legal reserve action for ci iff it is gold-NECESSARY (its remaining cost includes
    gems the bank can't supply, beyond the gold you hold) AND reserving can bank enough gold
    to cover that (one gold per reserve, within the free slots). Else None."""
    short = val.gold_shortfall(ci, seat)
    held = s.tokens[seat][5]
    free = 3 - len(s.reserved[seat])
    if held < short <= held + free:
        a = E.A_RES_BOARD + slot
        if a in legal_set:
            return a
    return None


def _winning_reserve(s, seat, val, legal_set):
    """Reserve a board card that would WIN but is unaffordable now only because a needed gem
    isn't in the bank -- reserving banks the gold to complete it next turn AND locks it from
    the opponent. The clearest case where reserving is the best move. Highest-point first."""
    if len(s.reserved[seat]) >= 3 or s.bank[5] <= 0:
        return None
    best = None
    for slot in range(12):
        ci = s.board[slot]
        if ci < 0 or val.affordable_now(ci, seat):
            continue
        if s.points[seat] + E.PTS[ci] + val.noble_completion_pts(ci, seat) < s.win_points:
            continue
        if val.tempo(ci, seat) >= WIN_RESERVE_MAX_TEMPO:   # too far to be a real near-term win
            continue
        a = _reservable(s, seat, ci, slot, val, legal_set)
        if a is not None and (best is None or E.PTS[ci] > best[1]):
            best = (a, E.PTS[ci])
    return best[0] if best else None


def _maybe_reserve(s, seat, val, targets, legal_set):
    """Disciplined reserve (one speculative reserve at a time -- avoids the over-reserve
    failure mode). On the top take_value BOARD card you can't afford, two principled triggers:
      (a) ACQUISITION -- it is significantly stronger than the next board card (take_value gap
          >= RESERVE_GAP): lock this uniquely-good card in (and bank a gold). Mirrors H's
          big-value-gap acquisition reserve.
      (b) GOLD-necessary -- a needed gem isn't in the bank, so the reserve's gold is the only
          way to finish it.
    (Winning reserves are handled earlier in choose_action, with priority.)"""
    if len(s.reserved[seat]) != 0:
        return None
    board = [(tv, ci, idx) for tv, ci, idx, kind in targets if kind == "board"]
    if not board:
        return None
    top_tv, top_ci, top_idx = board[0]
    if val.affordable_now(top_ci, seat):
        return None
    a = E.A_RES_BOARD + top_idx
    if a not in legal_set:
        return None
    second_tv = board[1][0] if len(board) > 1 else 0.0
    if top_tv - second_tv >= RESERVE_GAP:                       # (a) uniquely strong -> secure it
        return a
    if s.bank[5] > 0 and _reservable(s, seat, top_ci, top_idx, val, legal_set) is not None:
        return a                                               # (b) gold-necessary
    return None


def _opp_top_board_ci(s, val, opp):
    """The opponent's highest-take_value BOARD card (the card they're most likely to buy/aim at)."""
    best, bc = -1.0, -1
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            v = take_value(val, ci, opp)
            if v > best:
                best, bc = v, ci
    return bc


def _take_targets(s, seat, val, targets):
    """`targets` with leading cards the opponent will likely SNIPE removed (the user's pivot): a card
    we can't afford but the opponent CAN (and, if SNIPE_REQUIRE_OPP_TOP, is their own top pick) is
    assumed gone -- don't burn tempo collecting toward it; aim at the next attainable target. Never
    returns empty (if every target is sniped, fall back to the original list)."""
    if not USE_OPP_SNIPE or len(targets) <= 1:
        return targets
    opp = 1 - seat
    opp_top = _opp_top_board_ci(s, val, opp) if SNIPE_REQUIRE_OPP_TOP else -1
    kept = []
    for t in targets:
        ci = t[1]
        sniped = (not val.affordable_now(ci, seat)         # we can't buy it now
                  and val.affordable_now(ci, opp)          # but they can
                  and (not SNIPE_REQUIRE_OPP_TOP or ci == opp_top))
        if not sniped:
            kept.append(t)
    return kept if kept else targets


def _finish_reserve(s, seat, val, targets, legal_set):
    """Slot-pressure reserve: when near the cap and the TOP take_value target is a board card one
    good turn from done, RESERVE it instead of take-and-discarding. Reserving banks a gold (covers a
    remaining gem) and LOCKS the card from the opponent / board churn. Two triggers, on the post-bonus
    / post-token color deficits:
      - 8 tokens & exactly 2 of a SINGLE color away  -> reserve (gold + one take finishes it)
      - 9 tokens & exactly 1 gem away                -> reserve (the banked gold finishes it next turn)
    Requires a free reserve slot and gold in the bank. Returns the reserve action, or None."""
    if not targets or len(s.reserved[seat]) >= 3 or s.bank[5] <= 0:
        return None
    _tv, ci, idx, kind = targets[0]
    if kind != "board" or val.affordable_now(ci, seat):
        return None
    a = E.A_RES_BOARD + idx
    if a not in legal_set:
        return None
    n_tokens = sum(s.tokens[seat])
    d = V._color_deficits(s, ci, seat)
    total = sum(d)
    if n_tokens == 8 and total == 2 and max(d) == 2:   # 2 of one color away
        return a
    if n_tokens == 9 and total == 1:                   # 1 gem away
        return a
    return None


def choose_action(s: E.State, seat: int | None = None, *, val: V.Valuation | None = None) -> int:
    """Return a legal engine action index for `seat` (defaults to side to move).

    `val`: an optional pre-built Valuation on `s` to REUSE — variant S's search passes the leaf's
    own val, which avoids a duplicate build AND warms the take_value caches (so the anchor sweep is
    mostly cache hits). It MUST be a Valuation of `s` with H3's W_TEMPO/W_GEM/W_GOLD weights, so the
    result is identical to building it here; `None` builds fresh (every other caller's behavior)."""
    if seat is None:
        seat = s.turn
    legal = E.legal_actions(s)
    if not legal:
        return E.A_PASS
    legal_set = set(legal)

    if val is None:
        val = V.Valuation(s, W_TEMPO, W_GEM, W_GOLD)  # weights feed the H3 potential/engine model

    if s.phase == E.DISCARD:
        return _choose_discard(s, seat, legal, _targets(val, s, seat))
    if s.phase == E.NOBLE:
        return legal[0]  # all nobles worth 3 — any claimable is equal

    opp = 1 - seat
    targets = _targets(val, s, seat)

    # Affordable buys (board + own reserved), ranked by take_value with a small
    # gold-spend tiebreaker (prefer spending less of the scarce wild on near-ties).
    buys = []  # (take_value, action, ci)
    for slot in range(12):
        ci = s.board[slot]
        a = E.A_BUY_BOARD + slot
        if ci >= 0 and a in legal_set:
            buys.append((take_value(val, ci, seat), a, ci))
    for ri, ci in enumerate(s.reserved[seat]):
        a = E.A_BUY_RESV + ri
        if a in legal_set:
            buys.append((take_value(val, ci, seat), a, ci))
    buys.sort(reverse=True,
              key=lambda b: b[0] - GOLD_TIEBREAK * V.gold_needed(s, b[2], seat))

    # 1) Winning buy — taken only if SECURE; else deny the opponent's overtaking card.
    if buys:
        winning = []
        for _v, a, ci in buys:
            gain = E.PTS[ci] + V.noble_completion_pts(s, ci, seat)
            if s.points[seat] + gain >= s.win_points:
                winning.append((gain, a))
        if winning:
            winning.sort(reverse=True)
            w_gain, w_a = winning[0]
            if _secure_win(s, seat, s.points[seat] + w_gain,
                           s.purchased_n[seat] + 1, val):
                return w_a
            og, oci, oslot = _opp_best_buy(s, opp, val)
            if oslot >= 0:
                da = _deny(s, seat, oslot, oci, val, legal_set)
                if da is not None:
                    return da
            return w_a

    # 1b) Winning via reserve: a card that WINS but is unaffordable now only because a needed
    #     gem isn't in the bank -- reserve it to bank the gold and win next turn (and lock it).
    if USE_RESERVE:
        wr = _winning_reserve(s, seat, val, legal_set)
        if wr is not None:
            return wr

    # 2) Endgame denial — we can't win now, but the opponent can next turn off the board.
    og, oci, oslot = _opp_best_buy(s, opp, val)
    if oslot >= 0 and s.points[opp] + og >= s.win_points:
        da = _deny(s, seat, oslot, oci, val, legal_set)
        if da is not None:
            return da

    # 2b) 2-turn endgame denial — opponent can't buy now but could reserve then buy to win.
    if USE_DENY2:
        og2, oci2, oslot2 = _opp_best_reserve_buy(s, opp, val)
        if oslot2 >= 0 and s.points[opp] + og2 >= s.win_points:
            da2 = _deny(s, seat, oslot2, oci2, val, legal_set)
            if da2 is not None:
                return da2

    # Take-path target list: drop leading cards the opponent will likely snipe (the pivot). No-op
    # unless USE_OPP_SNIPE. Winning/denial above still use the full `targets`/`buys`.
    take_targets = _take_targets(s, seat, val, targets)

    # 3) Token-cap anti-hoard: near the 10-cap, cash in a buy rather than take-and-discard.
    #    The more tokens, the lower the bar to buy (9 < 8 threshold; 10 always buys).
    n_tokens = sum(s.tokens[seat])
    if n_tokens >= 8:
        if buys:
            best_tv, best_a = buys[0][0], buys[0][1]
            if n_tokens >= 10:
                return best_a
            if n_tokens == 9 and best_tv > CAP9_BUY_ABOVE:
                return best_a
            if n_tokens == 8 and best_tv > CAP8_BUY_ABOVE:
                return best_a
        # bar not met (or nothing affordable): reserve a near top board card, else take gems.
        if USE_FINISH_RESERVE:
            a = _finish_reserve(s, seat, val, take_targets, legal_set)
            if a is not None:
                return a
        a = _choose_take(s, seat, val, take_targets, legal)
        return a if a is not None else legal[0]

    # 4) Otherwise (< 8 tokens): buy the highest-take_value card if affordable, else
    #    take gems toward it (a legal buy action implies the engine deemed it affordable).
    if take_targets:
        _tv, top_ci, top_idx, top_kind = take_targets[0]
        top_a = (E.A_BUY_BOARD + top_idx) if top_kind == "board" else (E.A_BUY_RESV + top_idx)
        if top_a in legal_set:
            return top_a

    # 4b) Take-2-same to FINISH a RESERVED card waiting on a single color the bank is full of.
    #     Reserved = locked, so committing 2 gems to its bottleneck has no option-value cost.
    #     n_tokens < 8 here, so take-2 -> <= 9 (never trips the cap).
    if USE_TAKE2:
        a = _bottleneck_take2(s, seat, val, legal_set)
        if a is not None:
            return a

    # 5) Speculative reserve (acquisition + gold-necessary). OFF by default -- a measured
    #    tempo drag; the winning-reserve above is the only reserve on by default.
    if USE_RESERVE and USE_SPECULATIVE_RESERVE:
        a = _maybe_reserve(s, seat, val, targets, legal_set)
        if a is not None:
            return a

    a = _choose_take(s, seat, val, take_targets, legal)
    if a is not None:
        return a
    return legal[0]
