"""H3L = H3 + shallow lookahead: a 2-ply determinized search on top of H3's greedy eval.

The project's documented lever ("the remaining lever is SEARCH, not evaluation"): greedy H3 picks
the single best take_value move and is blind to the OPPONENT's reply (denial, tempo races). H3L
searches one ply deeper:

  for each of my candidate moves a:
      apply a, then let greedy H3 resolve my sub-decisions AND play the OPPONENT'S full reply turn,
      then score the resulting position (back at my turn) with a static position eval.
  play the move whose resulting position is best.

So H3L SEES the opponent's response that 1-ply H3 cannot. The opponent replies via greedy H3
("near-perfect by H3's lights"). Determinized: the search uses the state's own RNG (single sample).

Position eval (valuation3 primitives): realized point margin + development (cards) + each side's
best-available-card take_value (imminent scoring strength) + noble proximity. Weights are tunable.
"""
from __future__ import annotations

import random

from . import engine as E
from . import heuristic3 as H3
from . import valuation3 as V

_RNG = random.Random(0xC0FFEE)   # determinization shuffle (process-local)

# ── leaf evaluation ──
USE_ROLLOUT = True   # True: greedy-H3 rollout to the end (policy improvement, no hand-tuned eval).
                     # False: the static position_value below (a truncation fallback only).
DETERMINIZE = True   # shuffle the unseen decks before rolling out so the search can't exploit the
                     # real future draw order (the engine's only hidden info) -- a LEGITIMATE,
                     # non-clairvoyant searcher. False == clairvoyant (sees the true draws; cheating).
N_DET = 24           # determinizations averaged per candidate (expectimax over hidden futures). One
                     # sample is far too noisy (overfits the move to a single fake future); averaging
                     # estimates Q^H3(s,a) so the 1-step-improved policy is >= greedy H3.
ROLLOUT_MAX = 160    # ply cap on a rollout (games finish in ~50-70; this just bounds pathologies)
WIN_BONUS = 100.0    # rollout score = (win/loss bonus) + final point margin, from my perspective
# ── static position-eval weights (used only when USE_ROLLOUT=False / rollout truncates) ──
EV_POINTS = 1.0      # realized victory-point margin
EV_CARDS = 0.4       # development / engine-size margin
EV_BEST = 1.5        # best-available-card take_value margin (imminent scoring strength)
EV_NOBLE = 0.6       # noble-proximity margin
# ── search shape ──
CAND_CAP = 5         # max candidate moves searched per decision (fewer == less optimizer's curse)
MARGIN = 8.0         # only DEVIATE from H3's own move if a candidate's mean rollout value beats
                     # H3's-move value by this much (in WIN_BONUS=100 units, so ~one determinization
                     # of win-rate edge). Defaulting to the base policy guarantees H3L >= H3 minus
                     # noise -- the cure for the optimizer's curse over noisy Q estimates.

_WIN = 1e6


def _best_take(val, s, seat) -> float:
    """take_value of `seat`'s best available card (board + own reserved) -- imminent strength."""
    best = 0.0
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            tv = H3.take_value(val, ci, seat)
            if tv > best:
                best = tv
    for ci in s.reserved[seat]:
        tv = H3.take_value(val, ci, seat)
        if tv > best:
            best = tv
    return best


def _noble_prox(s, seat) -> float:
    """How close `seat` is to its nearest unclaimed noble (fraction of requirements met), 0..1."""
    best = 0.0
    bon = s.bonuses[seat]
    for slot in range(3):
        ni = s.nobles[slot]
        if ni >= 0:
            req = E.NOBLE_REQ[ni]
            total = sum(req)
            if total:
                have = sum(min(bon[i], req[i]) for i in range(5))
                p = have / total
                if p > best:
                    best = p
    return best


def position_value(s, me: int) -> float:
    """Static value of state `s` from `me`'s perspective (higher = better for me)."""
    if s.phase == E.OVER:
        if s.winner == me:
            return _WIN
        if s.winner == 1 - me:
            return -_WIN
        return 0.0
    opp = 1 - me
    val = V.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    return (EV_POINTS * (s.points[me] - s.points[opp])
            + EV_CARDS * (s.purchased_n[me] - s.purchased_n[opp])
            + EV_BEST * (_best_take(val, s, me) - _best_take(val, s, opp))
            + EV_NOBLE * (_noble_prox(s, me) - _noble_prox(s, opp)))


def _candidates(s, seat, legal, h3_a):
    """Bounded candidate set, priority-ordered so the cap keeps the consequential moves: H3's own
    pick FIRST (the always-evaluated baseline), then every BUY, then board/deck RESERVES, then pass."""
    out = [h3_a] if h3_a in legal else []
    for a in legal:                                    # buys (46..60)
        if E.A_BUY_BOARD <= a < E.A_DISCARD and a not in out:
            out.append(a)
    for a in legal:                                    # reserves (31..45)
        if E.A_RES_BOARD <= a < E.A_BUY_BOARD and a not in out:
            out.append(a)
    if E.A_PASS in legal and E.A_PASS not in out:
        out.append(E.A_PASS)
    return out[:CAND_CAP]


def _determinize(s) -> None:
    """Shuffle the unseen decks so the rollout can't exploit the real future draw order -- the only
    hidden info the compact engine exposes (draws .pop() from these lists). Done ONCE per decision
    and shared across candidates (CRN), so candidate comparison is clean."""
    for d in s.decks:
        _RNG.shuffle(d)


def _rollout_value(s, me: int) -> float:
    """Play the game out from `s` with greedy H3 for BOTH sides; return a score from `me`'s view:
    a WIN_BONUS-signed terminal plus the final point margin (a smooth tiebreak). A rare truncation
    falls back to the static position_value."""
    steps = 0
    while s.phase != E.OVER and steps < ROLLOUT_MAX:
        E.apply(s, H3.choose_action(s, s.turn))
        steps += 1
    if s.phase != E.OVER:
        return position_value(s, me)
    margin = s.points[me] - s.points[1 - me]
    if s.winner == me:
        return WIN_BONUS + margin
    if s.winner == 1 - me:
        return -WIN_BONUS + margin
    return margin                                   # draw


def _static_value(s, me: int) -> float:
    """Advance one opponent reply via greedy H3, then score with the static position eval."""
    steps = 0
    while s.phase != E.OVER and not (s.turn == me and s.phase == E.PLAY) and steps < 16:
        E.apply(s, H3.choose_action(s, s.turn))
        steps += 1
    return position_value(s, me)


def choose_action(s: E.State, seat: int | None = None) -> int:
    if seat is None:
        seat = s.turn
    legal = E.legal_actions(s)
    if len(legal) <= 1:
        return legal[0] if legal else E.A_PASS
    if s.phase != E.PLAY:               # discard / noble sub-decisions: defer to H3
        return H3.choose_action(s, seat)
    h3_a = H3.choose_action(s, seat)            # the base move; H3L only deviates if clearly better
    cands = _candidates(s, seat, legal, h3_a)
    if len(cands) == 1:
        return cands[0]
    det = USE_ROLLOUT and DETERMINIZE
    n = N_DET if det else 1
    bases = []                                  # n determinized base states, SHARED (CRN)
    for _ in range(n):
        sd = s.clone()
        if det:
            _determinize(sd)
        bases.append(sd)

    def q(a):
        tot = 0.0
        for sd in bases:
            s2 = sd.clone()
            E.apply(s2, a)
            tot += _rollout_value(s2, seat) if USE_ROLLOUT else _static_value(s2, seat)
        return tot / n

    base_q = q(h3_a)                            # default to H3's move
    best_a, best_dev = h3_a, base_q + MARGIN    # a deviation must clear base_q + MARGIN
    for a in cands:
        if a == h3_a:
            continue
        v = q(a)
        if v > best_dev:
            best_dev, best_a = v, a
    return best_a
