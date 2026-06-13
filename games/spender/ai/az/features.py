"""State -> feature vector for the policy/value net.

Perspective-relative: the side to move is always "me" (first player block).
Opponent blind-reserved cards are hidden — encoded as present+blind+level only,
with cost/points/bonus zeroed (their identity is part of the unseen pool that
mcts.determinize() shuffles).

Layout (N_FEATURES = 305):
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
"""
from __future__ import annotations

import numpy as np

from . import engine as E

_CARD_F = 12
_RESV_F = 16
_PLAYER_F = 6 + 5 + 1 + 1 + 3 * _RESV_F + 3
N_FEATURES = 12 * _CARD_F + 2 * _PLAYER_F + 6 + 18 + 3 + 3 + 3


def _write_card(out: np.ndarray, o: int, ci: int) -> None:
    out[o] = 1.0
    cost = E.COST[ci]
    for i in range(5):
        out[o + 1 + i] = cost[i] / 7.0
    out[o + 6] = E.PTS[ci] / 5.0
    out[o + 7 + E.BONUS[ci]] = 1.0


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

    return out
