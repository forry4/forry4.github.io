"""v4 heuristic bot — H2 (the `take_value` model). Served as website variant "H2".

A from-scratch valuation paired with `valuation2.py`, separate from the stable variant H
(`heuristic.py` + `valuation.py`). See H2.md (this directory) for the full write-up.

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
from . import valuation2 as V

# ─── Tuned config (offline search; beats H ~0.62) ────────────────────────────────────
W_TEMPO = 0.5      # cost: turns to collect
W_GEM = 0.2        # cost: total post-bonus gems to pay
W_GOLD = 0.4       # cost: estimated gold coins needed
NOBLE_SCALE = 3.0  # noble-progress contribution, scaled toward a noble's VP

# ── Noble-aggressiveness league variants (H2N noble / H2R rusher) ──────────────
# A single knob `noble_aggr` scales ONLY the staged noble_progress term (never
# noble_completion, a real +3 VP both variants always grab -> both stay competent).
# noble_aggr=1.0 = base H2 byte-identical. Mirrors heuristic.py's HN/HR for the
# stronger take_value bot, so the league keeps noble-style diversity at H2 strength.
# Calibrated vs base H2 by heuristic_variants_arena (win rate + nobles/game).
NOBLE_AGGR_H2N = 2.5   # noble variant: moderate noble lean (+0.34 nobles/game, 0.465 win vs
                       # base H2). 4.0 went too hard (+0.53); 2.5 = a clear-but-measured bias.
NOBLE_AGGR_H2R = 0.4   # rusher variant: de-emphasizes nobles, races points (-0.47 nobles, 0.51)

# point staging: future points scaled by a global game stage (low early -> 1 late)
STAGE_K = 8        # cards-bought for a full engine-stage; stage = max(cards/STAGE_K, leader_pts/15)
STAGE_FLOOR = 0.25  # early floor: fraction of point value still counted at game start

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
ENG_DECAY = 0.3

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


def components(val: V.Valuation, s: E.State, ci: int, seat: int,
               noble_aggr: float = 1.0):
    """The take_value pieces for `ci` from `seat`: (take, engine, point, cost).
    One source of truth for both the policy and the on-card transparency overlay.
    `noble_aggr` scales the staged noble_progress term (1.0 = base H2)."""
    cost = (W_TEMPO * val.tempo(ci, seat)
            + W_GEM * val.gem_cost(ci, seat)
            + W_GOLD * val.gold_cost(ci, seat))
    engine = val.engine_value(ci, seat)
    if ENG_DECAY:  # horizon-decay engine as we own more cards (few remaining buys to pay off)
        own = s.purchased_n[seat] / STAGE_K
        engine *= 1.0 - ENG_DECAY * (own if own < 1.0 else 1.0)
    stage = max(s.purchased_n[seat] / STAGE_K, max(s.points[0], s.points[1]) / E.WIN_POINTS)
    if stage > 1.0:
        stage = 1.0
    stage_factor = STAGE_FLOOR + (1.0 - STAGE_FLOOR) * stage
    # future points are staged (engine-first early); noble_completion is realized now, un-staged
    point = (stage_factor * (E.PTS[ci] + NOBLE_SCALE * noble_aggr * val.noble_progress(ci, seat))
             + val.noble_completion_pts(ci, seat))
    take = (engine + point) / (1.0 + cost)
    return take, engine, point, cost


def take_value(val: V.Valuation, s: E.State, ci: int, seat: int,
               noble_aggr: float = 1.0) -> float:
    """Single scalar worth of card `ci` to `seat`: benefit (engine + distance-
    discounted points) over (1 + total cost). See the module docstring."""
    return components(val, s, ci, seat, noble_aggr)[0]


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


def _targets(val, s, seat, noble_aggr: float = 1.0):
    """All board + own-reserved cards as (take_value, ci, index, kind), best first."""
    out = []
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            out.append((take_value(val, s, ci, seat, noble_aggr), ci, slot, "board"))
    for ri, ci in enumerate(s.reserved[seat]):
        out.append((take_value(val, s, ci, seat, noble_aggr), ci, ri, "resv"))
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
        if s.points[seat] + E.PTS[ci] + val.noble_completion_pts(ci, seat) < E.WIN_POINTS:
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


def choose_action(s: E.State, seat: int | None = None, *,
                  noble_aggr: float = 1.0) -> int:
    """Return a legal engine action index for `seat` (defaults to side to move).
    `noble_aggr` picks the noble style: 1.0 = base H2, NOBLE_AGGR_H2N (>1) = the
    noble variant, NOBLE_AGGR_H2R (<1) = the rusher. It scales the take_value noble
    term; there is no separate noble policy gate (ranking is purely take_value)."""
    if seat is None:
        seat = s.turn
    legal = E.legal_actions(s)
    if not legal:
        return E.A_PASS
    legal_set = set(legal)

    val = V.Valuation(s)

    if s.phase == E.DISCARD:
        return _choose_discard(s, seat, legal, _targets(val, s, seat, noble_aggr))
    if s.phase == E.NOBLE:
        return legal[0]  # all nobles worth 3 — any claimable is equal

    opp = 1 - seat
    targets = _targets(val, s, seat, noble_aggr)

    # Affordable buys (board + own reserved), ranked by take_value with a small
    # gold-spend tiebreaker (prefer spending less of the scarce wild on near-ties).
    buys = []  # (take_value, action, ci)
    for slot in range(12):
        ci = s.board[slot]
        a = E.A_BUY_BOARD + slot
        if ci >= 0 and a in legal_set:
            buys.append((take_value(val, s, ci, seat, noble_aggr), a, ci))
    for ri, ci in enumerate(s.reserved[seat]):
        a = E.A_BUY_RESV + ri
        if a in legal_set:
            buys.append((take_value(val, s, ci, seat, noble_aggr), a, ci))
    buys.sort(reverse=True,
              key=lambda b: b[0] - GOLD_TIEBREAK * V.gold_needed(s, b[2], seat))

    # 1) Winning buy — taken only if SECURE; else deny the opponent's overtaking card.
    if buys:
        winning = []
        for _v, a, ci in buys:
            gain = E.PTS[ci] + V.noble_completion_pts(s, ci, seat)
            if s.points[seat] + gain >= E.WIN_POINTS:
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
    if oslot >= 0 and s.points[opp] + og >= E.WIN_POINTS:
        da = _deny(s, seat, oslot, oci, val, legal_set)
        if da is not None:
            return da

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
        # bar not met (or nothing affordable): take gems
        a = _choose_take(s, seat, val, targets, legal)
        return a if a is not None else legal[0]

    # 4) Otherwise (< 8 tokens): buy the highest-take_value card if affordable, else
    #    take gems toward it (a legal buy action implies the engine deemed it affordable).
    if targets:
        _tv, top_ci, top_idx, top_kind = targets[0]
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

    a = _choose_take(s, seat, val, targets, legal)
    if a is not None:
        return a
    return legal[0]
