"""Fast compact-state Spender simulator for AlphaZero self-play.

Rule-parity target: games/spender/main.py (the incumbent engine). Card/noble
data is imported from main at module load — never duplicated. State is plain
int lists behind __slots__; the hot path uses no dicts and no string keys.

Color order everywhere: white=0, blue=1, green=2, red=3, black=4, gold=5.
Card ids are global ints: 0..39 = L1, 40..69 = L2, 70..89 = L3.
2-player only. Seats are 0 and 1.

Semantics matched to the incumbent (see plan / CLAUDE.md):
- Gold counts toward the 10-token cap; overfilling enters a DISCARD phase.
- Nobles are checked only after a buy; exactly-one claimable auto-claims,
  two-plus enters a NOBLE phase (a real decision for the policy to learn).
- Final round: when a player ends their action with >=15 points the trigger is
  set; the game resolves when the turn would return to (or pass) the trigger
  seat, so both seats get equal turns.
- Winner: most points, then fewest purchased cards, then shared (draw).
- take-2-same requires bank >= 4 of that color; every taken color needs >= 1.
- Reserve cap 3; reserving grants 1 gold only if the bank has gold; deck-top
  (blind) reserves pop the same end of the deck list as board refills.
"""
from __future__ import annotations

import random
from itertools import combinations

from games.spender.main import ALL_NOBLES, GEM_COLORS, LEVEL1, LEVEL2, LEVEL3

# ─── Static card tables (built once from main's data) ────────────────────────

_CIDX = {c: i for i, c in enumerate(GEM_COLORS)}  # white..black -> 0..4
N_CARDS = len(LEVEL1) + len(LEVEL2) + len(LEVEL3)  # 90
N_NOBLES = len(ALL_NOBLES)                         # 10

_L1_OFF, _L2_OFF, _L3_OFF = 0, len(LEVEL1), len(LEVEL1) + len(LEVEL2)


def _build_tables():
    cost, pts, bonus, level, name = [], [], [], [], []
    for lvl, data, off in ((1, LEVEL1, _L1_OFF), (2, LEVEL2, _L2_OFF), (3, LEVEL3, _L3_OFF)):
        for i, (p, b, c) in enumerate(data):
            row = [0, 0, 0, 0, 0]
            for col, n in c.items():
                row[_CIDX[col]] = n
            cost.append(tuple(row))
            pts.append(p)
            bonus.append(_CIDX[b])
            level.append(lvl)
            name.append(f"L{lvl}-{i}")
    return tuple(cost), tuple(pts), tuple(bonus), tuple(level), tuple(name)


COST, PTS, BONUS, LEVEL_OF, CARD_NAME = _build_tables()
CARD_ID_BY_NAME = {n: i for i, n in enumerate(CARD_NAME)}

NOBLE_REQ = tuple(
    tuple(n["req"].get(c, 0) for c in GEM_COLORS) for n in ALL_NOBLES
)
NOBLE_PTS = tuple(n["points"] for n in ALL_NOBLES)
NOBLE_NAME = tuple(n["id"] for n in ALL_NOBLES)
NOBLE_ID_BY_NAME = {n: i for i, n in enumerate(NOBLE_NAME)}

# ─── Phases / constants ──────────────────────────────────────────────────────

PLAY, DISCARD, NOBLE, OVER = 0, 1, 2, 3
WIN_NONE, WIN_DRAW = -1, 2
TOKEN_CAP = 10
WIN_POINTS = 15
BANK_INIT = (4, 4, 4, 4, 4, 5)  # 2-player: 4 per color, 5 gold


class State:
    """Mutable compact game state. clone() before speculative apply()."""

    __slots__ = (
        "bank",            # list[6]
        "tokens",          # (list[6], list[6]) per seat
        "bonuses",         # (list[5], list[5]) per seat
        "points",          # list[2]
        "purchased_n",     # list[2] (fewest-cards tiebreak)
        "purchased",       # (list[int], list[int]) card ids (conversion/debug)
        "reserved",        # (list[int], list[int]) card ids, <=3 each
        "reserved_blind",  # (list[bool], list[bool]) parallel to reserved
        "nobles_won",      # (list[int], list[int]) noble ids per seat
        "board",           # list[12] card ids, -1 empty (slot = (lvl-1)*4 + i)
        "decks",           # (list[int], list[int], list[int]) pop() from end
        "nobles",          # list[3] noble ids, -1 once claimed
        "turn",            # 0 | 1
        "phase",           # PLAY | DISCARD | NOBLE | OVER
        "pending_nobles",  # list of noble-slot indices when phase == NOBLE
        "final_trigger",   # -1 or seat that hit 15
        "winner",          # WIN_NONE | 0 | 1 | WIN_DRAW
        "ply",             # half-move counter (turn-cap safety in self-play)
    )

    def clone(self) -> "State":
        s = State.__new__(State)
        s.bank = self.bank[:]
        s.tokens = (self.tokens[0][:], self.tokens[1][:])
        s.bonuses = (self.bonuses[0][:], self.bonuses[1][:])
        s.points = self.points[:]
        s.purchased_n = self.purchased_n[:]
        s.purchased = (self.purchased[0][:], self.purchased[1][:])
        s.reserved = (self.reserved[0][:], self.reserved[1][:])
        s.reserved_blind = (self.reserved_blind[0][:], self.reserved_blind[1][:])
        s.nobles_won = (self.nobles_won[0][:], self.nobles_won[1][:])
        s.board = self.board[:]
        s.decks = (self.decks[0][:], self.decks[1][:], self.decks[2][:])
        s.nobles = self.nobles[:]
        s.turn = self.turn
        s.phase = self.phase
        s.pending_nobles = self.pending_nobles[:]
        s.final_trigger = self.final_trigger
        s.winner = self.winner
        s.ply = self.ply
        return s


def new_game(rng: random.Random | None = None) -> State:
    rng = rng or random
    s = State.__new__(State)
    s.bank = list(BANK_INIT)
    s.tokens = ([0] * 6, [0] * 6)
    s.bonuses = ([0] * 5, [0] * 5)
    s.points = [0, 0]
    s.purchased_n = [0, 0]
    s.purchased = ([], [])
    s.reserved = ([], [])
    s.reserved_blind = ([], [])
    s.nobles_won = ([], [])
    d1 = list(range(_L1_OFF, _L2_OFF))
    d2 = list(range(_L2_OFF, _L3_OFF))
    d3 = list(range(_L3_OFF, N_CARDS))
    rng.shuffle(d1)
    rng.shuffle(d2)
    rng.shuffle(d3)
    s.decks = (d1, d2, d3)
    # Board refills use .pop() (end of list) — deal the same way.
    s.board = []
    for d in (d1, d2, d3):
        for _ in range(4):
            s.board.append(d.pop() if d else -1)
    noble_ids = list(range(N_NOBLES))
    rng.shuffle(noble_ids)
    s.nobles = noble_ids[:3]
    s.turn = 0
    s.phase = PLAY
    s.pending_nobles = []
    s.final_trigger = -1
    s.winner = WIN_NONE
    s.ply = 0
    return s


# ─── Action space (fixed indices, ~70 actions) ───────────────────────────────

TAKE3 = tuple(combinations(range(5), 3))        # 10
TAKE2D = tuple(combinations(range(5), 2))       # 10
A_TAKE3 = 0                                     # 0..9
A_TAKE2D = A_TAKE3 + len(TAKE3)                 # 10..19
A_TAKE1 = A_TAKE2D + len(TAKE2D)                # 20..24
A_TAKE2S = A_TAKE1 + 5                          # 25..29
A_PASS = A_TAKE2S + 5                           # 30
A_RES_BOARD = A_PASS + 1                        # 31..42 (slot order)
A_RES_DECK = A_RES_BOARD + 12                   # 43..45 (level-1)
A_BUY_BOARD = A_RES_DECK + 3                    # 46..57 (slot order)
A_BUY_RESV = A_BUY_BOARD + 12                   # 58..60 (reserved index)
A_DISCARD = A_BUY_RESV + 3                      # 61..66 (color, incl. gold)
A_NOBLE = A_DISCARD + 6                         # 67..69 (pending_nobles index)
N_ACTIONS = A_NOBLE + 3                         # 70


def _gold_needed(cost: tuple, tokens: list, bonuses: list) -> int:
    """Gold required to buy; affordable iff result <= tokens[5]."""
    gn = 0
    for i in range(5):
        need = cost[i] - bonuses[i]
        if need > 0:
            short = need - tokens[i]
            if short > 0:
                gn += short
    return gn


def legal_actions(s: State) -> list[int]:
    """All legal action indices for the side to move (s.turn)."""
    if s.phase == OVER:
        return []
    me = s.turn
    tok = s.tokens[me]

    if s.phase == DISCARD:
        return [A_DISCARD + i for i in range(6) if tok[i] > 0]

    if s.phase == NOBLE:
        return [A_NOBLE + i for i in range(len(s.pending_nobles))]

    acts: list[int] = []
    bank = s.bank
    bon = s.bonuses[me]

    # Takes (allowed even at 10 tokens — discard phase handles overflow,
    # matching the incumbent human flow).
    for k, combo in enumerate(TAKE3):
        if bank[combo[0]] > 0 and bank[combo[1]] > 0 and bank[combo[2]] > 0:
            acts.append(A_TAKE3 + k)
    for k, combo in enumerate(TAKE2D):
        if bank[combo[0]] > 0 and bank[combo[1]] > 0:
            acts.append(A_TAKE2D + k)
    for c in range(5):
        if bank[c] > 0:
            acts.append(A_TAKE1 + c)
        if bank[c] >= 4:
            acts.append(A_TAKE2S + c)

    # Reserves
    if len(s.reserved[me]) < 3:
        for slot in range(12):
            if s.board[slot] >= 0:
                acts.append(A_RES_BOARD + slot)
        for lvl in range(3):
            if s.decks[lvl]:
                acts.append(A_RES_DECK + lvl)

    # Buys
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0 and _gold_needed(COST[ci], tok, bon) <= tok[5]:
            acts.append(A_BUY_BOARD + slot)
    for ri, ci in enumerate(s.reserved[me]):
        if _gold_needed(COST[ci], tok, bon) <= tok[5]:
            acts.append(A_BUY_RESV + ri)

    return acts or [A_PASS]


# ─── Apply ────────────────────────────────────────────────────────────────────

def _finish_turn(s: State, seat: int) -> None:
    if s.points[seat] >= WIN_POINTS and s.final_trigger < 0:
        s.final_trigger = seat
    s.turn = 1 - s.turn
    s.ply += 1
    if s.final_trigger >= 0 and s.turn <= s.final_trigger:
        _resolve_winner(s)


def _resolve_winner(s: State) -> None:
    s.phase = OVER
    k0 = (s.points[0], -s.purchased_n[0])
    k1 = (s.points[1], -s.purchased_n[1])
    s.winner = 0 if k0 > k1 else 1 if k1 > k0 else WIN_DRAW


def _maybe_enter_discard(s: State, seat: int) -> bool:
    """True if over the cap (phase set to DISCARD, turn NOT finished)."""
    if sum(s.tokens[seat]) > TOKEN_CAP:
        s.phase = DISCARD
        return True
    return False


def _after_buy_nobles(s: State, seat: int) -> bool:
    """Claim/queue nobles after a buy. True if a NOBLE decision is pending."""
    bon = s.bonuses[seat]
    claimable = []
    for slot, ni in enumerate(s.nobles):
        if ni >= 0:
            req = NOBLE_REQ[ni]
            if (bon[0] >= req[0] and bon[1] >= req[1] and bon[2] >= req[2]
                    and bon[3] >= req[3] and bon[4] >= req[4]):
                claimable.append(slot)
    if not claimable:
        return False
    if len(claimable) == 1:
        _claim_noble(s, seat, claimable[0])
        return False
    s.pending_nobles = claimable
    s.phase = NOBLE
    return True


def _claim_noble(s: State, seat: int, slot: int) -> None:
    ni = s.nobles[slot]
    s.nobles_won[seat].append(ni)
    s.points[seat] += NOBLE_PTS[ni]
    s.nobles[slot] = -1


def _refill(s: State, slot: int) -> None:
    deck = s.decks[slot // 4]
    s.board[slot] = deck.pop() if deck else -1


def apply(s: State, a: int) -> None:
    """Apply action in-place. Caller guarantees a is legal (from legal_actions)."""
    me = s.turn
    tok = s.tokens[me]

    if s.phase == DISCARD:
        c = a - A_DISCARD
        tok[c] -= 1
        s.bank[c] += 1
        if sum(tok) <= TOKEN_CAP:
            s.phase = PLAY
            _finish_turn(s, me)
        return

    if s.phase == NOBLE:
        _claim_noble(s, me, s.pending_nobles[a - A_NOBLE])
        s.pending_nobles = []
        s.phase = PLAY
        _finish_turn(s, me)
        return

    if a < A_PASS:  # all take variants
        if a < A_TAKE2D:
            colors = TAKE3[a - A_TAKE3]
        elif a < A_TAKE1:
            colors = TAKE2D[a - A_TAKE2D]
        elif a < A_TAKE2S:
            colors = (a - A_TAKE1,)
        else:
            c = a - A_TAKE2S
            colors = (c, c)
        for c in colors:
            s.bank[c] -= 1
            tok[c] += 1
        if not _maybe_enter_discard(s, me):
            _finish_turn(s, me)
        return

    if a == A_PASS:
        _finish_turn(s, me)
        return

    if a < A_RES_DECK:  # reserve from board
        slot = a - A_RES_BOARD
        ci = s.board[slot]
        s.reserved[me].append(ci)
        s.reserved_blind[me].append(False)
        _refill(s, slot)
        if s.bank[5] > 0:
            s.bank[5] -= 1
            tok[5] += 1
        if not _maybe_enter_discard(s, me):
            _finish_turn(s, me)
        return

    if a < A_BUY_BOARD:  # reserve from deck top (blind)
        deck = s.decks[a - A_RES_DECK]
        s.reserved[me].append(deck.pop())
        s.reserved_blind[me].append(True)
        if s.bank[5] > 0:
            s.bank[5] -= 1
            tok[5] += 1
        if not _maybe_enter_discard(s, me):
            _finish_turn(s, me)
        return

    # Buys
    if a < A_BUY_RESV:
        slot = a - A_BUY_BOARD
        ci = s.board[slot]
        _refill(s, slot)
    else:
        ri = a - A_BUY_RESV
        ci = s.reserved[me].pop(ri)
        s.reserved_blind[me].pop(ri)

    cost = COST[ci]
    bon = s.bonuses[me]
    for i in range(5):
        need = cost[i] - bon[i]
        if need > 0:
            pay = tok[i] if tok[i] < need else need
            if pay:
                tok[i] -= pay
                s.bank[i] += pay
            short = need - pay
            if short:
                tok[5] -= short
                s.bank[5] += short
    s.bonuses[me][BONUS[ci]] += 1
    s.points[me] += PTS[ci]
    s.purchased_n[me] += 1
    s.purchased[me].append(ci)
    if not _after_buy_nobles(s, me):
        _finish_turn(s, me)


# ─── Conversion to/from the incumbent dict format ────────────────────────────

def _card_dict(ci: int) -> dict:
    lvl = LEVEL_OF[ci]
    data = (LEVEL1, LEVEL2, LEVEL3)[lvl - 1]
    off = (_L1_OFF, _L2_OFF, _L3_OFF)[lvl - 1]
    pts, bonus, cost = data[ci - off]
    return {"id": CARD_NAME[ci], "level": lvl, "points": pts, "bonus": bonus, "cost": cost}


def to_game_dict(s: State, pids: tuple[str, str] = ("p0", "p1")) -> dict:
    """Convert to the incumbent main.py game-dict format (for parity tests and
    later for serving integration)."""
    game: dict = {
        "bank": {c: s.bank[i] for i, c in enumerate(GEM_COLORS)} | {"gold": s.bank[5]},
        "decks": {f"L{lvl+1}": [_card_dict(ci) for ci in s.decks[lvl]] for lvl in range(3)},
        "board": {f"L{lvl+1}": [(_card_dict(s.board[lvl*4+i]) if s.board[lvl*4+i] >= 0 else None)
                                for i in range(4)] for lvl in range(3)},
        "nobles": [dict(ALL_NOBLES[ni]) for ni in s.nobles if ni >= 0],
        "players": {},
        "order": list(pids),
        "turn": pids[s.turn],
        "phase": "over" if s.phase == OVER else "playing",
        "winner": None,
        "moves": [],
    }
    if s.final_trigger >= 0:
        game["final_round_trigger"] = pids[s.final_trigger]
    if s.phase == OVER:
        game["winner"] = (pids[s.winner] if s.winner in (0, 1) else list(pids))
    if s.phase == DISCARD:
        game["pending_discard_pid"] = pids[s.turn]
    if s.phase == NOBLE:
        game["pending_noble_pid"] = pids[s.turn]
        game["pending_noble_choice"] = [NOBLE_NAME[s.nobles[slot]] for slot in s.pending_nobles]
    for seat, pid in enumerate(pids):
        game["players"][pid] = {
            "tokens": {c: s.tokens[seat][i] for i, c in enumerate(GEM_COLORS)} | {"gold": s.tokens[seat][5]},
            "purchased": [_card_dict(ci) for ci in s.purchased[seat]],
            "reserved": [({**_card_dict(ci), "from_deck": True} if s.reserved_blind[seat][ri]
                          else _card_dict(ci)) for ri, ci in enumerate(s.reserved[seat])],
            "nobles": [dict(ALL_NOBLES[ni]) for ni in s.nobles_won[seat]],
        }
    return game


def from_game_dict(game: dict) -> State:
    """Convert an incumbent game dict to a State. Seat order = game['order'].
    Purchased cards enter as bonuses/points/counts (exact card list isn't part
    of compact state)."""
    pids = game["order"]
    s = State.__new__(State)
    s.bank = [game["bank"].get(c, 0) for c in GEM_COLORS] + [game["bank"].get("gold", 0)]
    s.tokens = tuple([game["players"][pid]["tokens"].get(c, 0) for c in GEM_COLORS]
                     + [game["players"][pid]["tokens"].get("gold", 0)] for pid in pids)
    s.bonuses = ([0] * 5, [0] * 5)
    s.points = [0, 0]
    s.purchased_n = [0, 0]
    s.purchased = ([], [])
    s.reserved = ([], [])
    s.reserved_blind = ([], [])
    s.nobles_won = ([], [])
    for seat, pid in enumerate(pids):
        ps = game["players"][pid]
        for card in ps["purchased"]:
            s.bonuses[seat][_CIDX[card["bonus"]]] += 1
            s.points[seat] += card["points"]
            s.purchased_n[seat] += 1
            s.purchased[seat].append(CARD_ID_BY_NAME[card["id"]])
        for noble in ps["nobles"]:
            ni = NOBLE_ID_BY_NAME[noble["id"]]
            s.nobles_won[seat].append(ni)
            s.points[seat] += NOBLE_PTS[ni]
        for card in ps["reserved"]:
            s.reserved[seat].append(CARD_ID_BY_NAME[card["id"]])
            # a deck-top reserve is hidden info; determinization/features then hide an
            # opponent's blind reserve from the searching seat (no info-cheat).
            s.reserved_blind[seat].append(bool(card.get("from_deck")))
    s.board = []
    for lvl in range(3):
        row = game["board"][f"L{lvl+1}"]
        for i in range(4):
            c = row[i] if i < len(row) else None
            s.board.append(CARD_ID_BY_NAME[c["id"]] if c else -1)
    s.decks = tuple([CARD_ID_BY_NAME[c["id"]] for c in game["decks"][f"L{lvl+1}"]] for lvl in range(3))
    s.nobles = [NOBLE_ID_BY_NAME[n["id"]] for n in game["nobles"]]
    while len(s.nobles) < 3:
        s.nobles.append(-1)
    s.turn = pids.index(game["turn"])
    if game.get("phase") == "over":
        s.phase = OVER
    elif game.get("pending_discard_pid"):
        s.phase = DISCARD
    elif game.get("pending_noble_pid"):
        s.phase = NOBLE
    else:
        s.phase = PLAY
    s.pending_nobles = []
    if s.phase == NOBLE:
        choice = set(game.get("pending_noble_choice") or [])
        s.pending_nobles = [slot for slot, ni in enumerate(s.nobles)
                            if ni >= 0 and NOBLE_NAME[ni] in choice]
    trig = game.get("final_round_trigger")
    s.final_trigger = pids.index(trig) if trig in pids else -1
    w = game.get("winner")
    s.winner = (WIN_DRAW if isinstance(w, list) else pids.index(w)) if w else WIN_NONE
    s.ply = 0
    return s
