"""Author + verify HAND-CRAFTED puzzles.

The reliable path when the generator can't surface a rare strict puzzle: design the
position by hand, and let the SOLVER guarantee it's a unique forced win where every
deviation loses — or pinpoint exactly which move/deviation breaks it.

Workflow:
    s = build_state(win_points=15, bank=..., hero=..., opp=..., board=[...], nobles=[...])
    print(report_str(verify(s, solver.h3_opponent())))     # check it's STRICT
    emit(s, solver.h3_opponent(), "puzzles/handcrafted_01.json", title="...")

`hero` is the side to move (seat 0). Cards are engine names ("L3-0") or ids (0-89);
nobles are names ("n5") or ids. Tokens/bank are color dicts ({"white":2,"gold":1}).
Bonuses/points are DERIVED from each player's `purchased` cards (so list real cards
that give the bonuses/points you want — `cards_for` helps pick them).
"""
from __future__ import annotations

from games.spender.main import GEM_COLORS

from games.spender.ai.az import actions as A
from games.spender.ai.az import engine as E
from . import schema, solver

_C = {c: i for i, c in enumerate(GEM_COLORS)}


def _tok6(d) -> list:
    if isinstance(d, (list, tuple)):
        return list(d) + [0] * (6 - len(d))
    out = [0] * 6
    for c, n in (d or {}).items():
        out[5 if c == "gold" else _C[c]] = n
    return out


def _cid(x) -> int:
    return x if isinstance(x, int) else E.CARD_ID_BY_NAME[x]


def _nid(x) -> int:
    return x if isinstance(x, int) else E.NOBLE_ID_BY_NAME[x]


def cards_for(bonuses: dict, points: int = 0, exclude=()) -> list:
    """Pick real card ids whose bonus colors match `bonuses` (color->count) and whose
    points sum to `points` (best-effort), avoiding any id in `exclude`. Use the result
    as a player's `purchased`. Pass the hero's picks as `exclude` for the opponent
    (and both, plus board, for further picks) so nothing is double-owned."""
    ex = set(exclude)
    by_color = {c: sorted((ci for ci in range(E.N_CARDS)
                           if E.BONUS[ci] == _C[c] and ci not in ex),
                          key=lambda ci: E.PTS[ci]) for c in GEM_COLORS}
    picks = []
    for c, n in bonuses.items():
        picks.extend(by_color[c][:n])                 # cheapest (low-point) first
    cur = sum(E.PTS[ci] for ci in picks)
    i = 0
    while cur < points and i < len(picks):
        ci = picks[i]
        col = E.BONUS[ci]
        better = [d for d in range(E.N_CARDS)
                  if E.BONUS[d] == col and d not in picks and d not in ex and E.PTS[d] > E.PTS[ci]]
        if better:
            best = min(better, key=lambda d: abs((cur - E.PTS[ci] + E.PTS[d]) - points))
            if E.PTS[best] > E.PTS[ci]:
                cur += E.PTS[best] - E.PTS[ci]
                picks[i] = best
        i += 1
    return picks


def build_state(*, win_points: int = 15, bank, hero: dict, opp: dict,
                board: list, nobles: list, phase: int = E.PLAY) -> E.State:
    """Construct a valid engine State (hero = seat 0, to move). Decks auto-fill with
    every card not visible/owned, so board refills work during the solution."""
    s = E.State.__new__(E.State)
    s.bank = _tok6(bank)
    s.tokens = (_tok6(hero.get("tokens", {})), _tok6(opp.get("tokens", {})))
    s.purchased = ([_cid(x) for x in hero.get("purchased", [])],
                   [_cid(x) for x in opp.get("purchased", [])])
    s.reserved = ([_cid(x) for x in hero.get("reserved", [])],
                  [_cid(x) for x in opp.get("reserved", [])])
    s.reserved_blind = ([False] * len(s.reserved[0]), [False] * len(s.reserved[1]))
    s.nobles_won = ([_nid(x) for x in hero.get("nobles_won", [])],
                    [_nid(x) for x in opp.get("nobles_won", [])])
    s.bonuses = ([0] * 5, [0] * 5)
    s.points = [0, 0]
    s.purchased_n = [0, 0]
    for seat in (0, 1):
        for ci in s.purchased[seat]:
            s.bonuses[seat][E.BONUS[ci]] += 1
            s.points[seat] += E.PTS[ci]
            s.purchased_n[seat] += 1
        for ni in s.nobles_won[seat]:
            s.points[seat] += E.NOBLE_PTS[ni]
    # Board: place the caller's cards into their OWN level's row (L1=slots 0-3,
    # L2=4-7, L3=8-11), then fill each row's remaining slots with cards UNAFFORDABLE
    # to BOTH players — so the board looks like a real Splendor board (right level per
    # row) without introducing any alternative buy line. (Filler in a wrong-level slot
    # was the "L1 cards in every section" bug.)
    placed = [_cid(x) for x in (board or []) if x not in (None, -1)]
    owned = set(s.purchased[0] + s.purchased[1] + s.reserved[0] + s.reserved[1] + placed)
    rows = {1: [], 2: [], 3: []}
    for ci in placed:
        rows[E.LEVEL_OF[ci]].append(ci)

    def _affordable(ci, seat):
        return E._gold_needed(E.COST[ci], s.tokens[seat], s.bonuses[seat]) <= s.tokens[seat][5]

    for lvl in (1, 2, 3):
        cands = sorted((ci for ci in range(E.N_CARDS)
                        if E.LEVEL_OF[ci] == lvl and ci not in owned
                        and not _affordable(ci, 0) and not _affordable(ci, 1)),
                       key=lambda ci: E.PTS[ci])   # dullest (low-point) filler first
        for ci in cands:
            if len(rows[lvl]) >= 4:
                break
            rows[lvl].append(ci)
            owned.add(ci)
    s.board = []
    for lvl in (1, 2, 3):
        s.board += (rows[lvl] + [-1, -1, -1, -1])[:4]
    s.nobles = [_nid(x) for x in nobles]
    while len(s.nobles) < 3:
        s.nobles.append(-1)
    used = set(s.purchased[0] + s.purchased[1] + s.reserved[0] + s.reserved[1]
               + [c for c in s.board if c >= 0])
    decks = ([], [], [])
    for ci in range(E.N_CARDS):
        if ci not in used:
            decks[E.LEVEL_OF[ci] - 1].append(ci)
    s.decks = decks
    s.turn = 0
    s.phase = phase
    s.pending_nobles = []
    s.final_trigger = -1
    s.winner = E.WIN_NONE
    s.ply = 0
    s.win_points = win_points
    return s


def _minimal_win(s: E.State, opp, max_k: int):
    hero = s.turn
    for k in range(1, max_k + 1):
        sol = solver.solve(s, hero, k, opp)
        if sol is not None:
            return k, sol
    return None, None


def verify(s: E.State, opp, max_k: int = 4, slack: int = 2) -> dict:
    """Solve the position and report: is it a forced win, in how few moves, is the
    line UNIQUE, and is it STRICT (every deviation loses)? Plus the move line."""
    hero = s.turn
    r = {"hero": hero, "hero_points": s.points[hero], "opp_points": s.points[1 - hero]}
    k, sol = _minimal_win(s, opp, max_k)
    if sol is None:
        r.update(winnable=False, verdict=f"NOT winnable — no forced win within {max_k} moves.")
        return r
    strict = solver.every_deviation_loses(s, hero, sol.line, opp, slack) if sol.unique else False
    r.update(
        winnable=True, k=k, unique=sol.unique, strict=strict, sol=sol,
        line=[("YOU" if seat == hero else "opp", A.action_name(a)) for (seat, a, _ph) in sol.line],
        verdict=("STRICT " if strict else ("unique " if sol.unique else "NON-unique ")) + f"{k}-move forced win",
    )
    return r


def report_str(r: dict) -> str:
    if not r.get("winnable"):
        return f"[{r['hero_points']}-{r['opp_points']}]  {r['verdict']}"
    lines = [f"[{r['hero_points']}-{r['opp_points']}]  {r['verdict']}  "
             f"(unique={r['unique']}, strict={r['strict']})"]
    for who, name in r["line"]:
        lines.append(f"    {who:3}  {name}")
    return "\n".join(lines)


def emit(s: E.State, opp, path: str, *, opp_name: str = "S", title=None,
         max_k: int = 4, require_strict: bool = True) -> dict:
    """Verify, then write the bank-ready puzzle file. Raises if not a unique forced
    win (or, with require_strict, not strict)."""
    r = verify(s, opp, max_k=max_k)
    if not r.get("winnable") or not r["unique"]:
        raise ValueError(f"refusing to emit: {r['verdict']}")
    if require_strict and not r["strict"]:
        raise ValueError("refusing to emit: not strict (some deviation does not lose)")
    meta = {"title": title, "hand_crafted": True, "strict": r["strict"],
            "difficulty": "Hard", "solution_len_hero": sum(1 for x in r["line"] if x[0] == "YOU")}
    puz = schema.build_puzzle(s, r["sol"], opponent=opp_name, meta=meta)
    schema.save(puz, path)
    return puz
