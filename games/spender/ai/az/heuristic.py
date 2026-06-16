"""v4 heuristic bot — a greedy policy over the shared valuation core.

`choose_action(state, seat)` returns a legal engine action index, so the bot
plugs directly into the engine action space (no dict conversion, unlike the
A/B/C2 incumbents). Two roles for this bot:
  1. a *correctness test* of the v4 valuation model (if the model is sound, a
     greedy bot using it should match/beat C2 — the step-3 arena gate), and
  2. an anti-blind-spot *league sparring partner* for the v4 AZ retrain.

Policy (the user's stated strategy):
  - buy the highest-value affordable card (always grab a winning/noble buy),
  - reserve sparingly and with DISCIPLINE (see reserve gates below) — either to
    deny an opponent about to take a card, or to secure a uniquely good card;
    strictness rises as reserve slots fill, and opening tempo is protected,
  - otherwise take gems that best advance the top target cards.

Reserve discipline (deliberate — over-reserving is the weakness this models the
counter to):
  - value threshold escalates with slots already used (last slot is precious),
  - reserve only on a big value-gap to the next card OR an imminent opponent buy,
  - at most one reserve in the opening (s.ply < OPENING_PLY) — early tempo builds
    the engine.

Factor-combination weights are hand-set to "clearly competent", NOT tuned —
weight-tuning is the documented saturated path; the arena is the judge.

Deployed tuning lineage (each fix was playtest/diagnostic-driven): buy-livelock
fix -> weight rebalance (points/efficiency up, engine down) -> take-gems focus
(minimize one target's turns-to-afford) -> resource-aware stage (cards-bought)
+ engine diminishing-returns. vs greedy C2: 0.58 -> 0.69.
"""
from __future__ import annotations

from . import engine as E
from . import valuation as V

# ─── Hand-set weights (clearly-competent defaults; arena is the judge) ────────
W_POINTS = 2.0        # direct VP — points win the race (boosted late via stage)
W_EFFICIENCY = 5.0    # points per effective gem — the core "good deal" lever
W_ENGINE = 1.0        # cross-card synergy (decayed late via stage; was over-buying engine)
W_NOBLE = 3.0         # noble advancement (a noble is worth 3 pts)
W_TEMPO = 0.3         # tempo TIME-DISCOUNT rate: value /= (1 + W_TEMPO * turns-to-afford)
                      # -- a far-off card is worth proportionally less now, never < 0

BUY_FLOOR = 0.5       # don't bother buying a near-worthless affordable card

# ─── Structural feature toggle ────────────────────────────────────────────────
# noble-completion was the one validated structural win (+0.024, z=2.05 vs the
# A/B/C/C2 greedy mix, 600 fresh paired seeds). Three other structural ideas were
# tested and rejected on fresh paired seeds: a multiplicative tempo time-discount
# (wash), an opponent-contest/denial term (wash, confirmed at 2000 games), and
# target-focused backward planning (hurt -- the broad engine_value is load-bearing).
USE_NOBLE_COMPLETION = True   # value the immediate +VP a buy scores by triggering
                              # a noble, in card_value AND the winning-buy check
USE_REACH_TAKE = True         # don't orient gem-taking toward a card needing >= this
MIRAGE_STEEP = 5              # of a SINGLE color after bonuses -- the bank holds only
                              # 4/color, so it needs BONUSES not tokens; collect toward
                              # reachable cards (the lower cards that build that color)
USE_GOLD_CONSERVE = True      # among similar-value affordable buys, prefer the one that
W_GOLD_SPEND = 0.4            # spends less GOLD (wild tokens are scarce + flexible)
USE_ANTI_HOARD = True         # near the 10-token cap with no gate-passing buy, buy the
TOKEN_HOARD = 8              # best affordable card anyway -- a permanent bonus + freed
                             # token slots beat taking gems you'd just discard at the cap
NOBLE_CONTRIB = 0.35         # don't skip a 0-pt card that ADVANCES a close noble this
                             # much (noble_progress folds in closeness) -- progress
                             # toward a near noble can beat taking a flexible gem
USE_TEMPO_DISCOUNT = True    # tempo as a multiplicative time-discount (value never < 0)
                             # instead of a flat subtraction that can drive value negative
USE_ENDGAME_DEFENSE = True   # near the end: take a winning buy only if it's SECURE (a
                             # first player's 15 lets the opponent overtake on their final
                             # turn); else deny the opponent's overtaking/winning board card
USE_FORCED_L1_OPENING = True   # engine-first opening: until the FIRST card is bought, the
                               # bot may only pursue L1 0-point cards -- buy the best
                               # affordable one, else take gems toward the best such target
                               # (no reserving). Starts the engine with cheap point-less
                               # bonuses before normal logic resumes. VALIDATED: +0.052
                               # (z=3.13) @1000 and +0.0435 (z=3.59) on a disjoint 2000-seed
                               # set vs the A/B/C/C2 mix -- one of the two biggest wins, on
                               # par with end-game defense.
W_COST = 0.4                 # cheapness discount for 0-POINT cards only -- card_value /=
                             # (1 + W_COST * total_eff_cost). efficiency = pts/(cost+1) is 0 for
                             # point-less cards, so cost is invisible there and two same-bonus 0-pt
                             # cards tie regardless of price (engine/noble key only on bonus color);
                             # this prices the cheaper one higher (less invested for the same engine
                             # benefit -> more leftover gems). Gated to PTS==0 so point cards (priced
                             # by efficiency) aren't double-penalized. VALIDATED: +0.028 (z=2.87) vs
                             # all-off over 2000 paired seeds. (A parallel L1 cost-spread discount,
                             # W_SPREAD, was tested alongside it and WASHED at 2000 seeds -- dropped.)
# (engine_value now also counts a bonus's discount to your own RESERVED cards, at a
# slight per-card premium -- see valuation.RESERVED_ENGINE_W. This is correct: a card
# you reserved is one you intend to buy. If it dents win rate, the cause is reserving
# bad cards, not the valuation -- the fix is the reserve decision, not ignoring reserves.)

# Reserve gates (strictness rises with slots used; opening tempo protected).
RESERVE_BASE = 4.0        # min target value to reserve with 0 slots used...
RESERVE_STEP = 1.5        # ...+this per slot already reserved (last slot precious)
RESERVE_GAP = 2.0         # value gap to the next-best card that justifies securing it
OPENING_PLY = 8           # within the first ~4 turns each, cap at one reserve
MIN_BUILD_PATH = 3        # a steep card needs >= this many lower-level same-color cards
                          # on the board before reserving it (else it's a mirage)

# Stage / tempo coefficients (exposed as constants so they're tunable).
PTS_STAGE_GAIN = 0.5      # points weight grows by this * stage
ENG_STAGE_DECAY = 0.9     # engine weight shrinks by this * stage (tuned 0.7->0.9: +0.013, z~2.05 over two disjoint 2k-seed runs)
ENGINE_STAGE_DIV = 10.0   # cards-bought / this = engine-size component of stage
ENG_DECAY_RATE = 0.5      # engine value decays by 1/(1 + rate * bonuses-held-in-color)
TAKE_TEMPO = 0.6          # take-target value penalty per estimated turn-to-afford


def card_value(val: V.Valuation, s: E.State, ci: int, seat: int) -> float:
    """Single scalar worth of card `ci` to `seat`, combining the valuation
    factors with a game-stage modulation (engine matters early, points late)."""
    pts = E.PTS[ci]
    eff = val.efficiency(ci, seat)
    eng = val.engine_value(ci, seat)
    nob = val.noble_progress(ci, seat)
    tta = val.turns_to_afford(ci, seat)
    # Immediate VP this buy scores by triggering a noble (+3). A real point gain,
    # so it rides the same stage-ramped points weight as the card's own points --
    # NOT the soft noble_progress nudge, which only credits incremental advance.
    nc = val.noble_completion_pts(ci, seat) if USE_NOBLE_COMPLETION else 0

    # Stage ramps engine->points. Key it on points AND engine size (cards
    # bought): "0 points but 8 cards" means the game is near its end (engine
    # nearly complete, point-surge imminent), which a points-only stage misses,
    # leaving engine over-weighted so the bot pivots to points too late.
    # Efficient turns (buys) advance the stage; wasted gem-takes don't.
    point_stage = max(s.points[0], s.points[1]) / E.WIN_POINTS
    engine_stage = s.purchased_n[seat] / ENGINE_STAGE_DIV
    stage = point_stage if point_stage > engine_stage else engine_stage
    if stage > 1.0:
        stage = 1.0
    pts_w = W_POINTS * (1.0 + PTS_STAGE_GAIN * stage)   # points matter more late
    eng_w = W_ENGINE * (1.0 - ENG_STAGE_DECAY * stage)  # engine matters less late

    # Diminishing returns: the Nth bonus in a color you already hold a lot of is
    # worth less (fewer remaining cards need that color from you, and stacking
    # one color is wasteful). Decays engine value by bonuses already held.
    eng_decay = 1.0 / (1.0 + ENG_DECAY_RATE * s.bonuses[seat][E.BONUS[ci]])

    base = (pts_w * (pts + nc)        # all four terms are >= 0, so base >= 0
            + W_EFFICIENCY * eff
            + eng_w * eng * eng_decay
            + W_NOBLE * nob)
    # Tempo as a TIME-DISCOUNT, not a subtraction: a card you can't afford for a while
    # is worth proportionally less NOW, but never < 0 (worst case = a useless card = 0).
    # The old `- W_TEMPO*tta` could drive value negative (the -0.4 seen in the overlay),
    # which is nonsensical -- a card can't be worth less than nothing.
    if USE_TEMPO_DISCOUNT:
        v = base / (1.0 + W_TEMPO * tta)
    else:
        v = base - W_TEMPO * tta
    # 0-point cards: efficiency can't see cost, so price the cheaper one higher.
    if W_COST and E.PTS[ci] == 0:
        v = v / (1.0 + W_COST * val.total_effective_cost(ci, seat))
    return v


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


def _need_vector(s: E.State, seat: int, targets) -> list[float]:
    """Color demand summed over the top target cards, weighted by their value
    and per-color deficit — 'which gems move me toward cards I actually want'."""
    need = [0.0] * 5
    for tv, ci, _idx, _kind in targets[:3]:
        if tv <= 0:
            continue
        if USE_REACH_TAKE and V.single_color_mirage(s, ci, seat, MIRAGE_STEEP):
            continue
        d = V._color_deficits(s, ci, seat)
        for i in range(5):
            need[i] += tv * d[i]
    return need


def _take_target(val, s, seat, targets):
    """The single card to actively collect toward. The highest-value card that is
    actually reachable soon (value penalized by turns-to-afford). Focusing on ONE
    target — rather than blending several — is what lets the bot take the RIGHT
    gems turn 1 and afford the card in the fewest turns."""
    best = None
    for tv, ci, _idx, _kind in targets:
        if tv <= 0:
            continue
        # Reachability: a steep single-color card with no build path is a mirage --
        # collecting toward it just hoards one color for a card you can't afford.
        if USE_REACH_TAKE and V.single_color_mirage(s, ci, seat, MIRAGE_STEEP):
            continue
        score = tv - TAKE_TEMPO * val.turns_to_afford(ci, seat)
        if best is None or score > best[0]:
            best = (score, ci)
    return best[1] if best else None


def _choose_take(s, seat, val, targets, legal):
    """Take the gems that bring the focus target closest to affordable: minimize
    its turns-to-afford, then its remaining deficit, then break ties by usefulness
    to the other top targets. This one-step plan toward a specific card avoids
    the dilution of spreading gems across several targets (which wastes tempo and
    misses take-2-same when a single color is the bottleneck)."""
    target = _take_target(val, s, seat, targets)
    if target is not None:
        need = _need_vector(s, seat, targets)
        tok = s.tokens[seat]
        best_a, best_key = None, None
        for a in legal:
            colors = _take_colors(a)
            if colors is None:
                continue
            for c in colors:          # simulate taking these gems...
                tok[c] += 1
            key = (val.turns_to_afford(target, seat),
                   val.gems_to_collect(target, seat),
                   -sum(need[c] for c in colors))
            for c in colors:          # ...then restore
                tok[c] -= 1
            if best_key is None or key < best_key:
                best_key, best_a = key, a
        if best_a is not None:
            return best_a
    # Fallback: a generically useful take-3, then any take.
    for a in legal:
        if E.A_TAKE3 <= a < E.A_TAKE2D:
            return a
    for a in legal:
        if _take_colors(a) is not None:
            return a
    return None


def _choose_discard(s, seat, legal, targets):
    """Discard the least-needed token; never gold unless only gold remains."""
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
    """All board + own-reserved cards as (value, ci, index, kind), best first."""
    out = []
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            out.append((card_value(val, s, ci, seat), ci, slot, "board"))
    for ri, ci in enumerate(s.reserved[seat]):
        out.append((card_value(val, s, ci, seat), ci, ri, "resv"))
    out.sort(reverse=True, key=lambda t: t[0])
    return out


def _maybe_reserve(s, seat, val, targets, legal_set):
    """Disciplined reserve. Returns an action or None.

    Gates (all must hold): a free slot; not in the opening with one already
    reserved; the best board target is high-value (threshold RISES with slots
    used) and unaffordable now; and EITHER it is far better than the next card
    (a unique opportunity) OR an opponent is about to take it (denial)."""
    n_res = len(s.reserved[seat])
    if n_res >= 3 or not targets:
        return None
    if s.ply < OPENING_PLY and n_res >= 1:        # opening tempo cap: <=1 reserve
        return None

    tv, ci, idx, kind = targets[0]
    if kind != "board":
        return None
    a = E.A_RES_BOARD + idx
    if a not in legal_set:
        return None
    if val.affordable_now(ci, seat):              # if we can just buy it, don't reserve
        return None

    threshold = RESERVE_BASE + n_res * RESERVE_STEP   # last slot is precious
    if tv < threshold:
        return None

    second = targets[1][0] if len(targets) > 1 else 0.0
    # Acquisition reserve (secure a uniquely good card) needs a real build path:
    # a steep single-color card is only worth tying up a slot for if the board
    # has >= MIN_BUILD_PATH lower-level cards of that color to build toward it.
    # 1-2 such cards yields ~1-2 bonuses -> still 5-6 gems short -> a speculative
    # reserve that mostly goes unused (the diagnostic's 78%-unused finding).
    # Spread-cost cards aren't steep and don't need a path.
    buildable = (not V.is_steep(s, ci, seat)
                 or V.build_path_count(s, ci, seat) >= MIN_BUILD_PATH)
    big_gap = (tv - second) >= RESERVE_GAP and buildable
    opp = 1 - seat
    opp_threat = val.affordable_now(ci, opp) or val.turns_to_afford(ci, opp) <= 1
    return a if (big_gap or opp_threat) else None


def _opp_best_buy(s, opp, val):
    """The opponent's best single buy on their NEXT turn: over board + their own
    reserved cards they can afford NOW, the one maximizing points + any noble it
    triggers. Returns (gain, ci, slot) -- slot is the board slot (>=0, deniable) or
    -1 (their own reserved card, not deniable). 'Afford now' is exact for their next
    move: nothing we do this turn changes the tokens they already hold."""
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
    given the final-round rule (engine._finish_turn)? Seat 1 -- or the bot already on
    the final turn (final_trigger is the opponent) -- wins immediately. Seat 0 hands
    the opponent one final turn, so it's secure only if they cannot overtake with
    their best buy (tiebreak: most points, then FEWEST cards)."""
    opp = 1 - seat
    if seat == 1 or s.final_trigger == opp:
        return True
    gain, _ci, _slot = _opp_best_buy(s, opp, val)
    opp_pts = s.points[opp] + gain
    opp_cards = s.purchased_n[opp] + (1 if gain > 0 else 0)
    overtakes = opp_pts > p_win or (opp_pts == p_win and opp_cards < cards_win)
    return not overtakes


def _deny(s, seat, slot, ci, val, legal_set):
    """Deny the opponent a board card: reserve it (a free slot) else buy it (if we can
    afford it). Returns a legal action, or None if neither is possible."""
    if len(s.reserved[seat]) < 3:
        a = E.A_RES_BOARD + slot
        if a in legal_set:
            return a
    if val.affordable_now(ci, seat):
        a = E.A_BUY_BOARD + slot
        if a in legal_set:
            return a
    return None


def choose_action(s: E.State, seat: int | None = None) -> int:
    """Return a legal engine action index for `seat` (defaults to side to move)."""
    if seat is None:
        seat = s.turn
    legal = E.legal_actions(s)
    if not legal:
        return E.A_PASS
    legal_set = set(legal)

    val = V.Valuation(s)
    targets = _targets(val, s, seat)

    if s.phase == E.DISCARD:
        return _choose_discard(s, seat, legal, targets)
    if s.phase == E.NOBLE:
        return legal[0]  # nobles are all worth 3 — any claimable is equal

    # Forced engine-first opening: until the bot buys its FIRST card, it may ONLY
    # pursue L1 0-point cards -- buy the best affordable one, else take gems toward
    # the best such target (no reserving). L1 0-pt cards never need >=5 of a color,
    # so they're always reachable; only the (vanishingly rare) all-1-point-L1 board
    # falls through to normal logic to avoid a deadlock.
    if USE_FORCED_L1_OPENING and s.purchased_n[seat] == 0:
        l1z = [t for t in targets if E.LEVEL_OF[t[1]] == 1 and E.PTS[t[1]] == 0]
        if l1z:
            best_buy = None
            for tv, ci, idx, kind in l1z:
                a = (E.A_BUY_BOARD + idx) if kind == "board" else (E.A_BUY_RESV + idx)
                if a in legal_set and val.affordable_now(ci, seat):
                    if best_buy is None or tv > best_buy[0]:
                        best_buy = (tv, a)
            if best_buy is not None:
                return best_buy[1]
            a = _choose_take(s, seat, val, l1z, legal)
            if a is not None:
                return a

    # Affordable buys (board + reserved), by value.
    buys = []  # (value, action, ci)
    for slot in range(12):
        ci = s.board[slot]
        a = E.A_BUY_BOARD + slot
        if ci >= 0 and a in legal_set:
            buys.append((card_value(val, s, ci, seat), a, ci))
    for ri, ci in enumerate(s.reserved[seat]):
        a = E.A_BUY_RESV + ri
        if a in legal_set:
            buys.append((card_value(val, s, ci, seat), a, ci))

    opp = 1 - seat

    if buys:
        # Rank by value, but conserve gold: subtract a small penalty per gold token
        # the buy would spend, so a similar-value card buyable WITHOUT gold outranks
        # one that burns a flexible wild. b[0] stays raw card_value for the BUY_FLOOR
        # check below (the penalty only reorders near-ties, never lowers the floor).
        buys.sort(reverse=True, key=lambda b: b[0] - (
            W_GOLD_SPEND * V.gold_needed(s, b[2], seat) if USE_GOLD_CONSERVE else 0.0))
        # 1a) Winning buy: the best affordable buy that reaches 15 (incl. noble VP --
        #     a card that wins VIA a noble was previously invisible to this check).
        winning = []
        for _v, a, ci in buys:
            gain = E.PTS[ci]
            if USE_NOBLE_COMPLETION:
                gain += V.noble_completion_pts(s, ci, seat)
            if s.points[seat] + gain >= E.WIN_POINTS:
                winning.append((gain, a))
        if winning:
            winning.sort(reverse=True)
            w_gain, w_a = winning[0]
            # Take the win only if it is SECURE: as first player, reaching 15 gives the
            # opponent a final turn to overtake (16+, or tie + fewest cards). If insecure,
            # deny their overtaking card first (we then win securely next turn); if we
            # can't deny it, grab 15 and hope they miss it.
            if not USE_ENDGAME_DEFENSE or _secure_win(
                    s, seat, s.points[seat] + w_gain, s.purchased_n[seat] + 1, val):
                return w_a
            og, oci, oslot = _opp_best_buy(s, opp, val)
            if oslot >= 0:
                da = _deny(s, seat, oslot, oci, val, legal_set)
                if da is not None:
                    return da
            return w_a

    # 1.5) End-game defense: we can't win this turn -- if the opponent can win on THEIR
    #      next turn via a board card, deny it (reserve, else buy) rather than develop.
    if USE_ENDGAME_DEFENSE:
        og, oci, oslot = _opp_best_buy(s, opp, val)
        if oslot >= 0 and s.points[opp] + og >= E.WIN_POINTS:
            da = _deny(s, seat, oslot, oci, val, legal_set)
            if da is not None:
                return da

    if buys:
        # 1b) Buy the best affordable card worth more than a GEM. Iterate by
        #     value and skip a card that scores 0 points, doesn't help a noble,
        #     AND would discount <=1 other board card: its permanent bonus is
        #     barely better than a single token, so taking a gem (flexible, no
        #     tiebreak cost, doesn't spend gems for nothing) dominates buying it.
        #     Strong Splendor play still buys nearly every turn it CAN do good.
        for bv, ba, bci in buys:
            if val.noble_progress(bci, seat) > 0.5:
                return ba
            if (E.PTS[bci] == 0 and V.discount_count(s, bci, seat) <= 1
                    and not (USE_NOBLE_COMPLETION
                             and V.noble_completion_pts(s, bci, seat) > 0)
                    and val.noble_progress(bci, seat) < NOBLE_CONTRIB):
                continue            # worthless vs a gem -> skip, prefer taking a gem
                                    # (but never skip a 0-pt card that CLAIMS a noble
                                    #  or meaningfully advances a CLOSE one)
            if bv > BUY_FLOOR:
                return ba
        # Anti-hoard: nothing passed the gate, but we're token-rich -- buy the best
        # affordable card (a permanent bonus + freed token slots) rather than take gems
        # we'd just discard at the 10-cap. Breaks the cap deadlock (steep targets are
        # skipped as un-collectable, leaving only gate-skipped cheap cards to buy).
        if USE_ANTI_HOARD and sum(s.tokens[seat]) >= TOKEN_HOARD:
            return buys[0][1]

    # 2) Disciplined reserve (deny or secure a uniquely good card).
    a = _maybe_reserve(s, seat, val, targets, legal_set)
    if a is not None:
        return a

    # 3) Take gems toward the top targets.
    a = _choose_take(s, seat, val, targets, legal)
    if a is not None:
        return a

    # 4) Last resort: any legal action (PASS if that is all there is).
    return legal[0]
