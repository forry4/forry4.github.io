"""action_to_move parity: for sampled states, dump the COMPACT dict-move json for EVERY legal action.
Rust action_to_move_json must produce the byte-identical string (the move bridge the browser forwards).

Run:  python spender-core/tools/gen_actionmove_fixtures.py
Writes: spender-core/tests/actionmove_fixtures.json
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
os.environ.setdefault("SPENDER_AZ_MODEL", "none")

from games.spender.ai.az import actions as A   # noqa: E402
from games.spender.ai.az import engine as E     # noqa: E402


def dump(s):
    return {
        "bank": list(s.bank), "tokens": [list(s.tokens[0]), list(s.tokens[1])],
        "bonuses": [list(s.bonuses[0]), list(s.bonuses[1])], "points": list(s.points),
        "purchased_n": list(s.purchased_n),
        "purchased": [list(s.purchased[0]), list(s.purchased[1])],
        "reserved": [list(s.reserved[0]), list(s.reserved[1])],
        "reserved_blind": [[bool(x) for x in s.reserved_blind[0]], [bool(x) for x in s.reserved_blind[1]]],
        "nobles_won": [list(s.nobles_won[0]), list(s.nobles_won[1])],
        "board": list(s.board), "decks": [list(s.decks[0]), list(s.decks[1]), list(s.decks[2])],
        "nobles": list(s.nobles), "turn": s.turn, "phase": s.phase,
        "pending_nobles": list(s.pending_nobles), "final_trigger": s.final_trigger,
        "winner": s.winner, "ply": s.ply, "win_points": s.win_points,
    }


cases = []
g = 0
while len(cases) < 500:
    s = E.new_game(random.Random(41000 + g), win_points=(21 if g % 4 == 0 else 15))
    ply = 0
    while s.phase != E.OVER and ply < 400:
        legal = E.legal_actions(s)
        moves = {a: json.dumps(A.action_to_move(s, a), separators=(",", ":")) for a in legal}
        cases.append({"state": dump(s), "moves": moves})
        E.apply(s, random.Random(53_000_000 + g * 911 + ply).choice(legal))
        ply += 1
        if len(cases) >= 500:
            break
    g += 1

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "actionmove_fixtures.json"))
with open(dst, "w", encoding="utf-8") as f:
    json.dump(cases, f)
print(f"wrote {dst}: {len(cases)} states, {sum(len(c['moves']) for c in cases)} (state,action) moves")
