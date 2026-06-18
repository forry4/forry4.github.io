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
W_ENGINE_STK = 0.8    # forward value of bonuses already held (future-deck coverage)
W_PROGRESS = 1.5      # imminent scoring strength: take_value of the best reachable targets
W_NOBLE = 0.6         # progress toward the closest completable noble (time-gated)
W_ECON = 0.3          # token economy: useful gold minus hoard pressure
SCALE = 8.0           # points-equivalent margin that maps to tanh(1) ≈ 0.76

WIN_CONVEX = 0.1      # convex kicker on points in the winning zone (>10): (p-10)^2 * WIN_CONVEX
NOBLE_TURN_W = 1.0    # noble time-gate fade speed (mirrors valuation3.NOBLE_TURN_W)
PROGRESS_TOPK = 2     # average the top-K target take_values for the progress term
TURNS_REF = 12.0      # horizon normalizer (estimated_turns_remaining ~ 1..12)
ENGINE_DR_EXP = 0.5   # diminishing-returns exponent on held bonuses per color (sqrt by default)
ECON_HOARD = 0.15     # penalty per token held above 8 (discourage hoarding / over-reserving)
ECON_GOLD = 0.2       # credit per gold that actually furthers the best target (gold_needed-capped)
BLIND_RESERVE_CONST = 0.5  # expected standing of one unknown opponent face-down reserve


def _points_term(val: V.Valuation, seat: int) -> float:
    """Realized VP plus a convex kicker in the winning zone (>10 pts), where each point is worth
    disproportionately more (the race-to-15 / final-round pressure the linear count misses)."""
    p = val.s.points[seat]
    over = p - 10
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
    """Imminent scoring strength: mean take_value of the top-`PROGRESS_TOPK` targets."""
    if not targets:
        return 0.0
    k = min(PROGRESS_TOPK, len(targets))
    return sum(targets[i][0] for i in range(k)) / k


def _noble_stand(val: V.Valuation, seat: int) -> float:
    """Closest completable visible noble for `seat`, time-gated. Per noble: VP * closeness *
    eff/(eff + NOBLE_TURN_W*deficit), eff = turns remaining, deficit = bonuses still needed — the
    same smooth fade as valuation3.noble_progress, but at the seat (position) level, taking the best
    noble. A far/unfinishable noble fades toward 0."""
    s = val.s
    bon = s.bonuses[seat]
    horizon = val.estimated_turns_remaining()
    best = 0.0
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
            best = max(best, float(E.NOBLE_PTS[ni]))
            continue
        close = 1.0 - deficit / total
        time_factor = horizon / (horizon + NOBLE_TURN_W * deficit)
        best = max(best, E.NOBLE_PTS[ni] * close * time_factor)
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
    if hide_blind:
        n_blind = sum(1 for b in val.s.reserved_blind[seat] if b)
        stand += BLIND_RESERVE_CONST * n_blind
    return stand


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
    out["stand_me"] = _stand(val, me, me)
    out["stand_opp"] = _stand(val, opp, me)
    out["value"] = math.tanh((out["stand_me"] - out["stand_opp"]) / SCALE)
    return out


def value_with(val: V.Valuation, seat: int) -> float:
    """V from a PREBUILT Valuation — so a search leaf can share ONE Valuation across the value and
    the policy prior (avoids building it twice per leaf). The state is `val.s`; assumes it is
    non-terminal (the MCTS leaf is never terminal: leaf_batch backs terminals up directly)."""
    me = seat
    return math.tanh((_stand(val, me, me) - _stand(val, 1 - me, me)) / SCALE)


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
