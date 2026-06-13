"""Action-space helpers around engine.py's fixed 70-action indexing.

engine.py owns legality and apply; this module provides the NN-facing mask,
debug names, and conversion to the incumbent main.py dict-move format (used by
the parity tests and, later, the serving bridge).
"""
from __future__ import annotations

from games.spender.main import GEM_COLORS

from . import engine as E

COLOR_NAMES = list(GEM_COLORS) + ["gold"]


def legal_mask(s: E.State) -> list[bool]:
    """Boolean mask over the full action space (for masked policy softmax)."""
    mask = [False] * E.N_ACTIONS
    for a in E.legal_actions(s):
        mask[a] = True
    return mask


_ABBR = "wbgrk"  # white blue green red blacK (distinct letters)


def action_name(a: int) -> str:
    if a < E.A_TAKE2D:
        return "take3:" + "".join(_ABBR[c] for c in E.TAKE3[a - E.A_TAKE3])
    if a < E.A_TAKE1:
        return "take2:" + "".join(_ABBR[c] for c in E.TAKE2D[a - E.A_TAKE2D])
    if a < E.A_TAKE2S:
        return "take1:" + _ABBR[a - E.A_TAKE1]
    if a < E.A_PASS:
        return "take2same:" + _ABBR[a - E.A_TAKE2S]
    if a == E.A_PASS:
        return "pass"
    if a < E.A_RES_DECK:
        slot = a - E.A_RES_BOARD
        return f"reserve:L{slot // 4 + 1}#{slot % 4}"
    if a < E.A_BUY_BOARD:
        return f"reserve_deck:L{a - E.A_RES_DECK + 1}"
    if a < E.A_BUY_RESV:
        slot = a - E.A_BUY_BOARD
        return f"buy:L{slot // 4 + 1}#{slot % 4}"
    if a < E.A_DISCARD:
        return f"buy_reserved:#{a - E.A_BUY_RESV}"
    if a < E.A_NOBLE:
        return "discard:" + COLOR_NAMES[a - E.A_DISCARD]
    return f"noble:#{a - E.A_NOBLE}"


def action_to_move(s: E.State, a: int) -> dict:
    """Convert an action to the incumbent dict-move format, evaluated against
    the CURRENT state (board slots/reserved indices resolve to card ids, so
    call before apply())."""
    me = s.turn
    if a < E.A_PASS:
        if a < E.A_TAKE2D:
            colors = E.TAKE3[a - E.A_TAKE3]
        elif a < E.A_TAKE1:
            colors = E.TAKE2D[a - E.A_TAKE2D]
        elif a < E.A_TAKE2S:
            colors = (a - E.A_TAKE1,)
        else:
            c = a - E.A_TAKE2S
            colors = (c, c)
        return {"type": "take_gems", "colors": [GEM_COLORS[c] for c in colors]}
    if a == E.A_PASS:
        return {"type": "take_gems", "colors": []}
    if a < E.A_RES_DECK:
        return {"type": "reserve", "card_id": E.CARD_NAME[s.board[a - E.A_RES_BOARD]]}
    if a < E.A_BUY_BOARD:
        return {"type": "reserve", "deck_level": a - E.A_RES_DECK + 1}
    if a < E.A_BUY_RESV:
        return {"type": "buy", "card_id": E.CARD_NAME[s.board[a - E.A_BUY_BOARD]]}
    if a < E.A_DISCARD:
        return {"type": "buy", "card_id": E.CARD_NAME[s.reserved[me][a - E.A_BUY_RESV]]}
    if a < E.A_NOBLE:
        return {"type": "discard", "color": COLOR_NAMES[a - E.A_DISCARD]}
    return {"type": "pick_noble", "noble_id": E.NOBLE_NAME[s.nobles[s.pending_nobles[a - E.A_NOBLE]]]}


_CIDX = {c: i for i, c in enumerate(COLOR_NAMES)}
_TAKE3_IDX = {combo: E.A_TAKE3 + k for k, combo in enumerate(E.TAKE3)}
_TAKE2D_IDX = {combo: E.A_TAKE2D + k for k, combo in enumerate(E.TAKE2D)}


def move_to_action(s: E.State, mv: dict) -> int:
    """Inverse of action_to_move: map an incumbent dict-move (e.g. produced by
    main's heuristic MCTS) to an action index against the current state."""
    t = mv["type"]
    if t == "take_gems":
        cols = sorted(_CIDX[c] for c in mv.get("colors", []))
        if not cols:
            return E.A_PASS
        if len(cols) == 1:
            return E.A_TAKE1 + cols[0]
        if len(cols) == 2:
            if cols[0] == cols[1]:
                return E.A_TAKE2S + cols[0]
            return _TAKE2D_IDX[tuple(cols)]
        return _TAKE3_IDX[tuple(cols)]
    if t == "reserve":
        if mv.get("card_id"):
            ci = E.CARD_ID_BY_NAME[mv["card_id"]]
            return E.A_RES_BOARD + s.board.index(ci)
        return E.A_RES_DECK + int(mv["deck_level"]) - 1
    if t == "buy":
        ci = E.CARD_ID_BY_NAME[mv["card_id"]]
        if ci in s.board:
            return E.A_BUY_BOARD + s.board.index(ci)
        return E.A_BUY_RESV + s.reserved[s.turn].index(ci)
    if t == "discard":
        return E.A_DISCARD + _CIDX[mv["color"]]
    if t == "pick_noble":
        ni = E.NOBLE_ID_BY_NAME[mv["noble_id"]]
        return E.A_NOBLE + next(k for k, slot in enumerate(s.pending_nobles)
                                if s.nobles[slot] == ni)
    raise ValueError(f"unknown move type: {t}")
