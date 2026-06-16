"""State -> feature vector for the policy/value net.

Perspective-relative: the side to move is always "me" (first player block).
Opponent blind-reserved cards are hidden — encoded as present+blind+level only,
with cost/points/bonus zeroed (their identity is part of the unseen pool that
mcts.determinize() shuffles).

Layout — a BASE raw-state block (unchanged from v3) + a v4 valuation block:

  BASE (_BASE_FEATURES = 305):
    12 board slots x 12: present, cost/7 (5), points/5, bonus one-hot (5)   = 144
    2 players x 64:                                                          = 128
        tokens/10 (6), bonuses/7 (5), points/15, purchased_n/20,
        3 reserved slots x 16: present, cost/7 (5), points/5,
                               bonus one-hot (5), blind, level one-hot (3),
        3 noble-progress values (1 - deficit/req_total; 0 for empty slots)
    bank/4 (6)                                                               = 6
    3 noble slots x 6: present, req/4 (5)                                    = 18
    phase one-hot (PLAY, DISCARD, NOBLE)                                     = 3
    final-trigger one-hot (none, mine, opponent's)                           = 3
    deck sizes /40 /30 /20                                                   = 3

  V4 valuation block (packs valuation.py's validated scalars — the SAME numbers
  the v4 heuristic plays on; see FEATURES_V4.md):
    15 candidate slots x _SLOT_F (=20): 12 board + my 3 reserved             = 300
        ME side (14): effective_cost/7 (5), gems_to_collect/10, gold/5,
            turns_to_afford/6, affordable_now, noble_progress, victory_closeness,
            engine_value/3, efficiency/1.5, cost_concentration/6
        OPP side (6, zeroed on my-reserved slots): opp gold/5, opp affordable_now,
            opp noble_progress, opp victory_closeness, opp engine_value/3
            (BOARD-ONLY — opp reserves hidden), opp turns_to_afford/6 (threat)
    globals (6): turns-remaining stage, board-color-demand vs my bonuses/20 (5)  = 6
    reserved zero-pad (future warm-startable features)                       = 16
"""
from __future__ import annotations

import numpy as np

from . import engine as E
from . import valuation as V

_CARD_F = 12
_RESV_F = 16
_PLAYER_F = 6 + 5 + 1 + 1 + 3 * _RESV_F + 3
_BASE_FEATURES = 12 * _CARD_F + 2 * _PLAYER_F + 6 + 18 + 3 + 3 + 3   # 305 (v3 layout)

# ── v4 valuation block ──
_SLOT_ME_F = 14
_SLOT_OPP_F = 6
_SLOT_F = _SLOT_ME_F + _SLOT_OPP_F   # 20 floats per candidate slot
_N_SLOTS = 15                        # 12 board + my 3 reserved
_GLOBAL_F = 6                        # stage + board-color-demand (5)
_PAD_F = 16                          # zero-padded, reserved for future features

_VAL_OFF = _BASE_FEATURES                       # v4 block starts here
_GLOBAL_OFF = _VAL_OFF + _N_SLOTS * _SLOT_F
_PAD_OFF = _GLOBAL_OFF + _GLOBAL_F
N_FEATURES = _PAD_OFF + _PAD_F                  # 305 + 300 + 6 + 16 = 627


def _write_card(out: np.ndarray, o: int, ci: int) -> None:
    out[o] = 1.0
    cost = E.COST[ci]
    for i in range(5):
        out[o + 1 + i] = cost[i] / 7.0
    out[o + 6] = E.PTS[ci] / 5.0
    out[o + 7 + E.BONUS[ci]] = 1.0


def _write_slot(out: np.ndarray, o: int, val: "V.Valuation",
                ci: int, me: int, opp: int, include_opp: bool) -> None:
    """Pack the 20-float v4 valuation block for candidate card `ci` at offset `o`.
    Empty slot (ci < 0) -> left all zero. `include_opp` False for my-reserved slots
    (the opponent can't buy them, so the denial/threat block is zeroed)."""
    if ci < 0:
        return
    # ME side (14) — the validated valuation.py scalars, normalized to ~[0,1].
    eff = val.effective_cost(ci, me)
    for i in range(5):
        out[o + i] = eff[i] / 7.0
    out[o + 5] = min(val.gems_to_collect(ci, me), 10) / 10.0
    out[o + 6] = min(val.gold_needed(ci, me), 5) / 5.0
    out[o + 7] = min(val.turns_to_afford(ci, me), 6) / 6.0
    out[o + 8] = 1.0 if val.affordable_now(ci, me) else 0.0
    out[o + 9] = val.noble_progress(ci, me)
    out[o + 10] = val.victory_closeness(ci, me, val.noble_completion_pts(ci, me))
    out[o + 11] = min(val.engine_value(ci, me), 3.0) / 3.0
    out[o + 12] = min(val.efficiency(ci, me), 1.5) / 1.5
    out[o + 13] = min(val.cost_concentration(ci, me), 6) / 6.0
    # OPP side (6) — denial / contest signals; engine value is BOARD-ONLY (opp
    # reserves are hidden from me — including them would leak through determinize).
    if include_opp:
        out[o + 14] = min(val.gold_needed(ci, opp), 5) / 5.0
        out[o + 15] = 1.0 if val.affordable_now(ci, opp) else 0.0
        out[o + 16] = val.noble_progress(ci, opp)
        out[o + 17] = val.victory_closeness(ci, opp, val.noble_completion_pts(ci, opp))
        out[o + 18] = min(val.engine_value(ci, opp, include_reserved=False), 3.0) / 3.0
        out[o + 19] = min(val.turns_to_afford(ci, opp), 6) / 6.0


def encode(s: E.State, out: np.ndarray | None = None) -> np.ndarray:
    """Encode for the side to move. Pass a preallocated zeroed array to avoid
    allocation in hot loops (it is NOT re-zeroed here if reused — pass fresh)."""
    if out is None:
        out = np.zeros(N_FEATURES, dtype=np.float32)
    me = s.turn
    opp = 1 - me

    o = 0
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            _write_card(out, o, ci)
        o += _CARD_F

    for seat in (me, opp):
        tok = s.tokens[seat]
        for i in range(6):
            out[o + i] = tok[i] / 10.0
        o += 6
        bon = s.bonuses[seat]
        for i in range(5):
            out[o + i] = bon[i] / 7.0
        o += 5
        out[o] = s.points[seat] / 15.0
        out[o + 1] = s.purchased_n[seat] / 20.0
        o += 2
        for ri in range(3):
            if ri < len(s.reserved[seat]):
                ci = s.reserved[seat][ri]
                blind = s.reserved_blind[seat][ri]
                if seat == opp and blind:
                    out[o] = 1.0                      # present, identity hidden
                    out[o + 12] = 1.0                 # blind flag
                else:
                    _write_card(out, o, ci)
                    if blind:
                        out[o + 12] = 1.0
                out[o + 13 + (E.LEVEL_OF[ci] - 1)] = 1.0
            o += _RESV_F
        bon = s.bonuses[seat]
        for slot in range(3):
            ni = s.nobles[slot]
            if ni >= 0:
                req = E.NOBLE_REQ[ni]
                total = 0
                deficit = 0
                for i in range(5):
                    total += req[i]
                    d = req[i] - bon[i]
                    if d > 0:
                        deficit += d
                out[o + slot] = 1.0 - deficit / total
        o += 3

    for i in range(6):
        out[o + i] = s.bank[i] / 4.0
    o += 6

    for slot in range(3):
        ni = s.nobles[slot]
        if ni >= 0:
            out[o] = 1.0
            req = E.NOBLE_REQ[ni]
            for i in range(5):
                out[o + 1 + i] = req[i] / 4.0
        o += 6

    if s.phase < 3:  # terminal states are never evaluated by the net
        out[o + s.phase] = 1.0
    o += 3

    if s.final_trigger < 0:
        out[o] = 1.0
    elif s.final_trigger == me:
        out[o + 1] = 1.0
    else:
        out[o + 2] = 1.0
    o += 3

    out[o] = len(s.decks[0]) / 40.0
    out[o + 1] = len(s.decks[1]) / 30.0
    out[o + 2] = len(s.decks[2]) / 20.0
    o += 3  # == _BASE_FEATURES

    # ── v4 valuation block ──────────────────────────────────────────────────
    # One Valuation context per encode precomputes deck_color_demand once and is
    # reused across all 15 candidate slots and both seats (O(cards), not O(cards^2)).
    val = V.Valuation(s)
    for slot in range(12):                     # 12 board candidates (me + opp blocks)
        _write_slot(out, o, val, s.board[slot], me, opp, include_opp=True)
        o += _SLOT_F
    for ri in range(3):                        # my 3 reserved candidates (me block only)
        ci = s.reserved[me][ri] if ri < len(s.reserved[me]) else -1
        _write_slot(out, o, val, ci, me, opp, include_opp=False)
        o += _SLOT_F

    # globals: turns-remaining stage (0 once the final round is triggered) ...
    if s.final_trigger < 0:
        out[o] = (E.WIN_POINTS - max(s.points[0], s.points[1])) / E.WIN_POINTS
        if out[o] < 0.0:
            out[o] = 0.0
    # ... and board color demand vs MY bonuses (a color the board no longer wants
    # is a weak bonus target).
    bon_me = s.bonuses[me]
    demand = [0, 0, 0, 0, 0]
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            cost = E.COST[ci]
            for i in range(5):
                d = cost[i] - bon_me[i]
                if d > 0:
                    demand[i] += d
    for i in range(5):
        out[o + 1 + i] = min(demand[i], 20) / 20.0
    o += _GLOBAL_F

    # 16 zero-padded slots reserved for future features (warm-startable add). o
    # advances past them implicitly; they stay 0.
    return out
