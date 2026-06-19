"""Translate a 'spendee' (mattle) game position into our engine and ask variant S.

The friend's card/noble tables (wwsd_defs.json, pulled from the site's client) are the canonical
90-card Splendor deck in the SAME colour order as our engine (verified: identity matches 89/90
cards; our Spender deck deviates on exactly one card). We REBUILD the engine's card/noble tables
directly from THEIRS so we analyse their exact game — their card index then IS the engine card id
(0-39 L1, 40-69 L2, 70-89 L3) and their colour order is ours.

IMPORTANT: the rebuild happens in `prepare()`, NOT at import. Importing this module must never
mutate the shared `engine` globals — otherwise a stray import inside the live game backend would
corrupt its AI. The dedicated WWSD service calls `prepare()` once at startup; `analyze()` also
calls it lazily (idempotent).
"""
from __future__ import annotations
import json
import os
import time

from games.spender.ai.az import engine as E
from games.spender.ai.az import mcts as _mcts
from games.spender.ai.az import vsearch as VS

CLR = E.GEM_COLORS                                   # [white, blue, green, red, black]
_HERE = os.path.dirname(__file__)
_DEFS = json.load(open(os.path.join(_HERE, "wwsd_defs.json"), encoding="utf-8"))
_CONST = _DEFS["/games/spendee/imports/api/utils/constants.js"]["default"]
THEIR_CARDS = sorted(_CONST["cards"], key=lambda c: c["index"])   # {index, level0..2, costs[5], discount, score}
THEIR_NOBLES = sorted(_CONST["nobles"], key=lambda n: n["index"]) # {index, costs[5], score}

_PREPARED = False


def override_engine() -> None:
    """Replace the engine's deck/noble tables with the friend's deck (same colour order as ours)."""
    cost, pts, bonus, level, name = [], [], [], [], []
    for c in THEIR_CARDS:
        cost.append(tuple(c["costs"])); pts.append(c["score"]); bonus.append(c["discount"])
        lvl = c["level"] + 1; level.append(lvl)
        name.append(f"#{c['index']}/L{lvl}/{CLR[c['discount']][:3]}/{c['score']}p")
    E.COST, E.PTS, E.BONUS, E.LEVEL_OF, E.CARD_NAME = map(tuple, (cost, pts, bonus, level, name))
    E.CARD_ID_BY_NAME = {n: i for i, n in enumerate(E.CARD_NAME)}
    E.NOBLE_REQ = tuple(tuple(n["costs"]) for n in THEIR_NOBLES)
    E.NOBLE_PTS = tuple(n["score"] for n in THEIR_NOBLES)


def prepare() -> None:
    """Idempotently install the friend's deck into the engine. Call once at service startup."""
    global _PREPARED
    if not _PREPARED:
        override_engine()
        _PREPARED = True


def set_target(t) -> None:
    """Their game can be to 15 or 21; align the engine win threshold (heuristics read E.WIN_POINTS).
    NB: H3's turns_table.json is measured from 15-pt games, so 21 is best-effort, not exact."""
    E.WIN_POINTS = int(t)


def to_state(d):
    """Build an engine State from a 'spendee' live `data` snapshot (identity card ids & colours)."""
    bank, players = d["bank"], d["players"]
    s = E.State.__new__(E.State)
    s.bank = list(bank["chips"]) + [bank.get("goldChips", 0)]
    tok, bon, pts, pn, pur, res, resb, nob = [None, None], [None, None], [0, 0], [0, 0], \
        [None, None], [None, None], [None, None], [None, None]
    for seat in (0, 1):
        p = players[seat]
        tok[seat] = list(p["chips"]) + [p.get("goldChips", 0)]
        b = [0] * 5
        for ci in p["purchasedCards"]:
            b[E.BONUS[ci]] += 1
        bon[seat] = b
        pts[seat] = sum(E.PTS[ci] for ci in p["purchasedCards"]) + sum(E.NOBLE_PTS[i] for i in p["nobles"])
        pn[seat] = len(p["purchasedCards"])
        pur[seat] = list(p["purchasedCards"])
        res[seat] = list(p["reservedCards"])
        resb[seat] = [False] * len(p["reservedCards"])
        nob[seat] = list(p["nobles"])
    s.tokens = (tok[0], tok[1]); s.bonuses = (bon[0], bon[1]); s.points = pts
    s.purchased_n = pn; s.purchased = (pur[0], pur[1])
    s.reserved = (res[0], res[1]); s.reserved_blind = (resb[0], resb[1])
    s.nobles_won = (nob[0], nob[1])
    board = []
    for lvl in range(3):
        for slot in bank["showedCards"][lvl]:
            board.append(-1 if slot is None else slot)
    s.board = board
    s.decks = tuple(list(bank["hiddenCards"][lvl]) for lvl in range(3))
    s.nobles = (list(bank["nobles"]) + [-1, -1, -1])[:3]
    cpi = d["state"]["currentPlayerIndex"]
    s.turn = cpi if cpi is not None else 0
    s.phase = E.PLAY
    s.pending_nobles = []; s.final_trigger = -1; s.winner = E.WIN_NONE; s.ply = 0
    return s


def _describe_move(s, a) -> str:
    """Human, on-screen-actionable description of an engine action for the side to move."""
    G = CLR
    if a < E.A_TAKE2D:   return "TAKE 3 gems: " + ", ".join(G[i] for i in E.TAKE3[a - E.A_TAKE3])
    if a < E.A_TAKE1:    return "TAKE 2 gems: " + ", ".join(G[i] for i in E.TAKE2D[a - E.A_TAKE2D])
    if a < E.A_TAKE2S:   return "TAKE 1 gem: " + G[a - E.A_TAKE1]
    if a < E.A_PASS:     return "TAKE 2 of the same gem: " + G[a - E.A_TAKE2S]
    if a == E.A_PASS:    return "PASS"

    def card(ci):
        cost = ", ".join(f"{n} {G[k]}" for k, n in enumerate(E.COST[ci]) if n)
        return f"L{E.LEVEL_OF[ci]} {G[E.BONUS[ci]]} card worth {E.PTS[ci]}pt (cost: {cost})"

    if a < E.A_RES_DECK:
        slot = a - E.A_RES_BOARD; lvl, col = slot // 4 + 1, slot % 4 + 1
        return f"RESERVE the L{lvl} board card in position {col}: {card(s.board[slot])}"
    if a < E.A_BUY_BOARD: return f"RESERVE blind from the L{a - E.A_RES_DECK + 1} deck"
    if a < E.A_BUY_RESV:
        slot = a - E.A_BUY_BOARD; lvl, col = slot // 4 + 1, slot % 4 + 1
        return f"BUY the L{lvl} board card in position {col}: {card(s.board[slot])}"
    ri = a - E.A_BUY_RESV; return f"BUY your reserved card: {card(s.reserved[s.turn][ri])}"


def _search_with_eval(s, seat, time_limit):
    """Run variant S's search and return (root visit counts, root value in [-1,1] for the side to
    move). Mirrors vsearch._run_search_timed but also reads the root's averaged value (sum W / sum N)
    so we can surface S's POST-search assessment of the position next to its chosen move. Kept here
    (not in vsearch) so the deployed game backend's az modules stay untouched."""
    search = _mcts.Search(s, VS._RNG, c_puct=VS.C_PUCT, add_noise=False, leaf_state=True)
    deadline = time.time() + time_limit
    done = 0
    while done < VS.SERVE_MAX_SIMS:
        VS._expand(search)
        done += 1
        if done >= VS.SERVE_MIN_SIMS and time.time() >= deadline:
            break
    root = search.root
    tot = sum(root.N)
    root_val = (sum(root.W) / tot) if tot else 0.0    # root.W is from root.to_play (= side to move)
    return root.N[:], root_val


def analyze(doc, time_limit=None) -> dict:
    """Take a dumped 'games' collection doc (or a single game doc) and return what variant S would
    do, as a structured dict. Never raises on game content."""
    prepare()
    if time_limit is None:
        time_limit = VS.SERVE_TIME
    game = doc["games"][0] if isinstance(doc, dict) and "games" in doc else doc
    data = game["data"]
    target = int((game.get("settings") or {}).get("targetScore") or data.get("targetScore") or 15)
    set_target(target)
    st = data["state"]; seat = st.get("currentPlayerIndex"); job = st.get("currentJob")
    names = [p.get("name", f"P{i}") for i, p in enumerate(game.get("players", [{}, {}]))]
    out = {"ok": False, "target": target, "status": game.get("status"), "job": job,
           "turn_seat": seat, "turn_name": (names[seat] if seat is not None else None), "names": names}
    if seat is None or game.get("status") == "FINISHED":
        out["message"] = "This game is finished — nothing for S to decide."
        return out
    s = to_state(data)
    out["scores"] = [{"name": names[i], "pts": s.points[i]} for i in (0, 1)]
    out["gold_bank"] = s.bank[5]
    legal = E.legal_actions(s)
    if not legal:
        out["message"] = "No legal moves in this position."
        return out
    visits, root_val = _search_with_eval(s.clone(), seat, time_limit)
    order = sorted([a for a in legal if visits[a] > 0], key=lambda a: -visits[a]) or list(legal)
    tv = sum(visits) or 1
    out.update(ok=True, sims=int(sum(visits)), eval=round(root_val, 3),
               recommendation=_describe_move(s, order[0]),
               alternatives=[{"pct": round(100 * visits[a] / tv, 1), "text": _describe_move(s, a)}
                             for a in order[1:6]])
    if job not in ("SPENDEE_REGULAR", None):
        out["note"] = ("Pending '%s' sub-decision — S gives the main move; "
                       "noble/discard sub-decisions fall back to greedy H3." % job)
    return out
