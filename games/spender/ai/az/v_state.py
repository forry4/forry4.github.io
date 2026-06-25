"""v_state.py — whole-position favorability V(state) for the side to move.

The H-family scores ACTIONS (the take_value of *acquiring* a card). This module scores a whole
POSITION: ``value(s, seat)`` returns a float in [-1, 1] = how favorable state ``s`` is for ``seat``
(defaults to the side to move). It is assembled from the proven H3 (``valuation3`` + ``heuristic3``)
primitives — engine value, the turns-remaining horizon, the noble time-gate — aggregated into a
per-seat STANDING and diffed zero-sum:

    V(s) = tanh( (STAND(s, me) - STAND(s, opp)) / SCALE )            # in [-1, 1]

    STAND(s, seat) = W_POINTS   * points_term       (realized VP + convex near-win kicker)
                   + W_ENGINE_STK* engine_stock      (held bonuses' FUTURE-deck value, horizon-gated)
                   + W_PROGRESS  * progress          (top-k take_value of reachable targets)
                   + W_NOBLE     * noble_stand        (closest completable noble, time-gated)
                   + W_ECON      * econ               (useful gold + anti-hoard — the over-reserve fix)

Because STAND is computed identically for both seats and subtracted, a search that backs up V gets
DENIAL/contention for free: a move that removes the opponent's best target lowers STAND(opp). No
contested-weight knob (the documented self-play blind spot is structurally cured here).

Hidden info: a card the OPPONENT reserved face-down (``reserved_blind``) is hidden from the
observer; V never reads its identity — it contributes ``BLIND_RESERVE_CONST`` to that opponent's
standing instead (mirrors ``features.encode`` zeroing blind-opp identity). A seat always sees its
OWN reserves. Inside a determinized search the blind cards are concretized by the sampler, but V
stays conservative (uses the constant) so it is identical and honest in and out of search.

The MCTS value convention (see ``mcts.py``) is exactly this: a leaf value in [-1, 1] from the
perspective of the player to move — so ``value`` drops straight in as a search leaf evaluator.

State source of truth: the internal helpers read the state from ``val.s`` (the Valuation owns it),
never a separately-passed state — so there is no way to score one state's cards against another's
caches. The public entry points ``value(s, …)`` / ``components(s, …)`` take the state only to BUILD
the Valuation; everything downstream flows through ``val``. (valuation3's freshness assert catches a
Valuation reused after its state mutates.)

Weights are module-level floats (not a dict) so the existing ``--set KEY=VAL`` harness override
routing (``hasattr``/``setattr`` on the module) reaches them, and the coordinate-descent autotuner
can sweep them.
"""
from __future__ import annotations

import math

from . import engine as E
from . import heuristic3 as H3
from . import valuation3 as V

# ─── tunable weights (panel-tuned later by vsearch_autotune) ─────────────────────────────────
W_POINTS = 1.0        # realized victory points (the hard currency)
W_ENGINE_STK = 0.4    # forward value of bonuses already held (future-deck coverage); maximin-tuned (was 0.8)
W_PROGRESS = 3.54     # imminent scoring strength: take_value of the best reachable targets. 1.5->2.5
                      # found by the self-gate (vs frozen-S) + confirmed at sims=400 (panel avg
                      # 0.8125->0.8262, min not worse); the weak panel's maximin tune had missed it.
                      # 2.5->3.54 (June 2026, "k6"): a BREADTH+magnitude change paired with PROGRESS_TOPK
                      # 2->6 -- the magnitude is over-matched to the wider mean. Real ~+4pp vs frozen-S,
                      # replicated on 3 disjoint seed bases (0.543/0.545/0.531); passed the H3 RPS panel
                      # (worst matchup +0.018) and the past-selves panel (>=0.5 vs all, min 0.500).
W_NOBLE = 0.6         # progress toward the closest completable noble (time-gated)
W_ECON = 0.3          # token economy: useful gold minus hoard pressure
SCALE = 8.0           # points-equivalent margin that maps to tanh(1) ≈ 0.76

WIN_CONVEX = 0.1      # convex kicker on points in the winning zone (>10): (p-10)^2 * WIN_CONVEX
NOBLE_TURN_W = 1.0    # noble time-gate fade speed (mirrors valuation3.NOBLE_TURN_W)
NOBLE_MULTI_W = 0.0   # credit toward SECONDARY nobles at the POSITION level. _noble_stand normally
                      # counts only the single best noble (max); with W>0 it adds W * (sum of the other
                      # nobles' gated standings), so a position progressing toward 2-3 nobles outscores
                      # one toward 1 (you may claim several; breadth is also more robust to denial).
                      # Default 0 = max-only = byte-identical. (Per-card noble_progress already rewards
                      # multi-noble cards via its n-normalized sum; this is the position-eval counterpart.)
PROGRESS_TOPK = 6     # how many top targets feed the progress term. 2->6 ("k6", June 2026): a wider
                      # mean of reachable targets (rewards optionality/denial-robustness), paired with
                      # W_PROGRESS 2.5->3.54 to over-match the magnitude. See W_PROGRESS for the evidence.
PROGRESS_DECAY = 1.0  # geometric decay across the top-K take_values: weight_i = DECAY**i. 1.0 = equal
                      # weight -> plain mean (byte-identical at TOPK=2). <1 emphasizes the best target
                      # and tapers down the bench. NORMALIZED by the weight sum so progress stays a
                      # weighted MEAN (same scale) -- tests breadth/shape, NOT a stealth W_PROGRESS bump.
TURNS_REF = 12.0      # horizon normalizer (estimated_turns_remaining ~ 1..12)
ENGINE_DR_EXP = 0.5   # diminishing-returns exponent on held bonuses per color (sqrt by default)
ECON_HOARD = 0.15     # penalty per token held above 8 (discourage hoarding / over-reserving)
ECON_GOLD = 0.2       # credit per gold that actually furthers the best target (gold_needed-capped)
BLIND_RESERVE_CONST = 0.5  # expected standing of one unknown opponent face-down reserve
RESERVE_PENALTY = 0.0  # tempo/waste cost subtracted per RESERVED card a seat holds. The static eval
                       # otherwise rewards reserving (gold bank + the card stays a `progress` target)
                       # with no cost for the turn it spends -> the measured OVER-RESERVE (S reserves
                       # ~4x H3, ~56% never bought). Default 0 = byte-identical; swept by the fix expt.

# ─── endgame fewest-cards tiebreak (Gap A) ───────────────────────────────────────────────────
# The win is decided by points, then FEWEST purchased cards. STAND scores raw points and is blind to
# the card count, so two positions with equal points but different card counts evaluate identically —
# the leaf can't tell that an extra 0-point card LOSES the tiebreak. (A non-terminal leaf only; at a
# true terminal `value` already returns the engine's exact tiebreak-aware win/loss.) This term, gated
# tightly to the endgame, nudges the side-to-move diff toward holding fewer cards when the tiebreak is
# actually live. Default W=0 = byte-identical.
ENDGAME_TIEBREAK_W = 0.0   # points-equivalent value of a 1-card tiebreak advantage, at full gate
ENDGAME_TIE_ZONE = 5.0     # ramps in over the last N points before the win (matches the convex zone)
ENDGAME_TIE_GAP = 3.0      # fades to 0 as the point gap exceeds this (the tiebreak only decides near-ties)


def _points_term(val: V.Valuation, seat: int) -> float:
    """Realized VP plus a convex kicker in the winning zone (>10 pts), where each point is worth
    disproportionately more (the race-to-15 / final-round pressure the linear count misses)."""
    p = val.s.points[seat]
    over = p - (val.s.win_points - 5)        # convex kicker in the last 5 points (->10 at 15, ->16 at 21)
    return p + (WIN_CONVEX * over * over if over > 0 else 0.0)


def _engine_stock(val: V.Valuation, seat: int) -> float:
    """Forward value of the bonuses `seat` ALREADY holds — distinct from `progress` (which scores
    the current board): a held bonus keeps discounting cards not yet revealed, in proportion to how
    much the remaining DECK demands that color, scaled by the turns left to cash it in.

    Reuses `valuation3.Valuation.deck_color_demand` (share of undealt deck cost per color) and
    `estimated_turns_remaining()` (the H3 horizon clock). Diminishing returns per color via
    `ENGINE_DR_EXP` — the first bonus in a color matters most. ~0 late game (no turns to compound)."""
    bon = val.s.bonuses[seat]
    horizon = val.estimated_turns_remaining()
    cover = 0.0
    for c in range(5):
        b = bon[c]
        if b > 0:
            cover += val.deck_color_demand[c] * (b ** ENGINE_DR_EXP)
    return cover * (horizon / TURNS_REF)


def _seat_targets(val: V.Valuation, seat: int, hide_blind: bool):
    """(take_value, ci) for every card `seat` could pursue — board + own reserved — best first.
    When `hide_blind`, skip `seat`'s face-down reserves (the observer can't see their identity)."""
    s = val.s
    out = []
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            out.append((H3.take_value(val, ci, seat), ci))
    for ri, ci in enumerate(s.reserved[seat]):
        if hide_blind and s.reserved_blind[seat][ri]:
            continue
        out.append((H3.take_value(val, ci, seat), ci))
    out.sort(reverse=True, key=lambda t: t[0])
    return out


def _progress(targets) -> float:
    """Imminent scoring strength: cascade-weighted mean of the top-`PROGRESS_TOPK` target take_values.
    Weights decay geometrically (weight_i = PROGRESS_DECAY**i) and are normalized by their sum, so the
    result stays a weighted MEAN on the same scale as the old top-2 mean (DECAY=1.0, TOPK=2 reproduces
    it exactly). DECAY<1 emphasizes the best target while letting the bench contribute a little —
    rewarding optionality/denial-robustness without inflating progress's magnitude."""
    if not targets:
        return 0.0
    k = min(PROGRESS_TOPK, len(targets))
    if PROGRESS_DECAY == 1.0:
        return sum(targets[i][0] for i in range(k)) / k
    num = 0.0
    den = 0.0
    w = 1.0
    for i in range(k):
        num += w * targets[i][0]
        den += w
        w *= PROGRESS_DECAY
    return num / den


def _noble_stand(val: V.Valuation, seat: int) -> float:
    """Closest completable visible noble for `seat`, time-gated. Per noble: VP * closeness *
    eff/(eff + NOBLE_TURN_W*deficit), eff = turns remaining, deficit = bonuses still needed — the
    same smooth fade as valuation3.noble_progress, but at the seat (position) level, taking the best
    noble. A far/unfinishable noble fades toward 0.

    When NOBLE_RACE_W > 0 the per-noble standing becomes the EXPECTED noble VP = VP * P_win, where
    P_win = P(beat the opponent) * P(finish in time) (valuation3._noble_winprob) — so a noble the
    opponent will claim first contributes little even when this seat is close. Best noble + the
    NOBLE_MULTI_W tail, as before."""
    s = val.s
    bon = s.bonuses[seat]
    horizon = val.estimated_turns_remaining()
    race_on = V.NOBLE_RACE_W != 0.0            # standing = expected noble VP (claim odds vs the opponent)
    opp = s.bonuses[1 - seat] if race_on else None
    vals = []
    for slot in range(3):
        ni = s.nobles[slot]
        if ni < 0:
            continue
        req = E.NOBLE_REQ[ni]
        total = sum(req)
        if not total:
            continue
        deficit = sum(req[c] - bon[c] for c in range(5) if req[c] > bon[c])
        if deficit == 0:                       # already qualifies (engine normally auto-claims)
            vals.append(float(E.NOBLE_PTS[ni]))
            continue
        if race_on:                            # expected VP = VP * P_win (beat-opponent * finish-in-time)
            d_op = sum(req[c] - opp[c] for c in range(5) if req[c] > opp[c])
            vals.append(E.NOBLE_PTS[ni] * val._noble_winprob(deficit, d_op, horizon))
        else:
            close = 1.0 - deficit / total
            time_factor = horizon / (horizon + NOBLE_TURN_W * deficit)
            vals.append(E.NOBLE_PTS[ni] * close * time_factor)
    if not vals:
        return 0.0
    best = max(vals)
    if NOBLE_MULTI_W:                          # also credit progress toward the OTHER nobles, not just the best
        return best + NOBLE_MULTI_W * (sum(vals) - best)
    return best


def _econ(val: V.Valuation, seat: int, targets) -> float:
    """Token economy — the lever that targets the documented OVER-RESERVE / gold-hoard weakness.
    Gold is credited ONLY up to what the seat's best target actually needs (a hoard furthering no
    plan is worth ~0), minus a penalty for sitting near the 10-token cap."""
    tok = val.s.tokens[seat]
    gold = tok[5]
    ntok = sum(tok)
    useful_gold = 0.0
    if targets:
        best_ci = targets[0][1]
        useful_gold = min(gold, val.gold_needed(best_ci, seat))
    over = ntok - 8
    return ECON_GOLD * useful_gold - (ECON_HOARD * over if over > 0 else 0.0)


def _stand(val: V.Valuation, seat: int, observer: int) -> float:
    """`seat`'s positional standing in points-equivalent units, from `observer`'s information.
    When seat != observer, hide seat's blind reserves and add a flat constant for each."""
    hide_blind = seat != observer
    targets = _seat_targets(val, seat, hide_blind)
    stand = (W_POINTS * _points_term(val, seat)
             + W_ENGINE_STK * _engine_stock(val, seat)
             + W_PROGRESS * _progress(targets)
             + W_NOBLE * _noble_stand(val, seat)
             + W_ECON * _econ(val, seat, targets))
    if RESERVE_PENALTY:
        stand -= RESERVE_PENALTY * len(val.s.reserved[seat])   # tempo cost of held reserves (both seats)
    if hide_blind:
        n_blind = sum(1 for b in val.s.reserved_blind[seat] if b)
        stand += BLIND_RESERVE_CONST * n_blind
    return stand


def _tiebreak_delta(val: V.Valuation, me: int, opp: int) -> float:
    """Endgame fewest-cards tiebreak as a points-equivalent bonus to `me`'s standing (a CROSS-seat
    term, so it lives in the diff, not in per-seat STAND). Zero unless the game is near the win
    (someone in the convex zone) AND the seats are near-tied on points — exactly when pts->fewest-cards
    actually decides. Rewards `me` for holding fewer purchased cards than `opp`."""
    if not ENDGAME_TIEBREAK_W:
        return 0.0
    s = val.s
    lead = s.points[me] if s.points[me] > s.points[opp] else s.points[opp]
    zone = (lead - (s.win_points - ENDGAME_TIE_ZONE)) / ENDGAME_TIE_ZONE
    if zone <= 0.0:
        return 0.0
    if zone > 1.0:
        zone = 1.0
    gap = s.points[me] - s.points[opp]
    if gap < 0:
        gap = -gap
    close = 1.0 - gap / ENDGAME_TIE_GAP
    if close <= 0.0:
        return 0.0
    return ENDGAME_TIEBREAK_W * zone * close * (s.purchased_n[opp] - s.purchased_n[me])


def components(s, seat: int | None = None) -> dict:
    """Per-component breakdown for both seats (sanity checks, the discrimination test, the overlay).
    Keys: points/engine/progress/noble/econ for me & opp, plus stand_me/stand_opp/value."""
    if seat is None:
        seat = s.turn
    me, opp = seat, 1 - seat
    val = V.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    out = {}
    for tag, st in (("me", me), ("opp", opp)):
        hb = st != me
        tg = _seat_targets(val, st, hb)
        out[f"points_{tag}"] = _points_term(val, st)
        out[f"engine_{tag}"] = _engine_stock(val, st)
        out[f"progress_{tag}"] = _progress(tg)
        out[f"noble_{tag}"] = _noble_stand(val, st)
        out[f"econ_{tag}"] = _econ(val, st, tg)
    tb = _tiebreak_delta(val, me, opp)
    out["stand_me"] = _stand(val, me, me)
    out["stand_opp"] = _stand(val, opp, me)
    out["tiebreak_me"] = tb
    out["value"] = math.tanh((out["stand_me"] + tb - out["stand_opp"]) / SCALE)
    return out


def value_with(val: V.Valuation, seat: int) -> float:
    """V from a PREBUILT Valuation — so a search leaf can share ONE Valuation across the value and
    the policy prior (avoids building it twice per leaf). The state is `val.s`; assumes it is
    non-terminal (the MCTS leaf is never terminal: leaf_batch backs terminals up directly)."""
    me = seat
    opp = 1 - me
    return math.tanh((_stand(val, me, me) - _stand(val, opp, me) + _tiebreak_delta(val, me, opp)) / SCALE)


def value(s, seat: int | None = None) -> float:
    """Favorability of state `s` for `seat` (default: side to move), in [-1, 1].
    Terminal states return the hard win/loss/draw value; otherwise the squashed standing diff."""
    if seat is None:
        seat = s.turn
    if s.phase == E.OVER:
        if s.winner == seat:
            return 1.0
        if s.winner == 1 - seat:
            return -1.0
        return 0.0
    return value_with(V.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD), seat)
