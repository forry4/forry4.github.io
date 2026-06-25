"""Policy-tree parity: heuristic3.choose_action (the greedy H3 move, deterministic). Covers PLAY,
DISCARD, and NOBLE phases. Rust must return the SAME action index (exact — take_value already matches
bit-for-bit, so the deterministic dispatch can't diverge).

Run:  python spender-core/tools/gen_policy_fixtures.py
Writes: spender-core/tests/policy_fixtures.json
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
os.environ.setdefault("SPENDER_AZ_MODEL", "none")

from games.spender.ai.az import engine as E       # noqa: E402
from games.spender.ai.az import heuristic3 as H3   # noqa: E402


def dump(s):
    return {
        "bank": list(s.bank),
        "tokens": [list(s.tokens[0]), list(s.tokens[1])],
        "bonuses": [list(s.bonuses[0]), list(s.bonuses[1])],
        "points": list(s.points),
        "purchased_n": list(s.purchased_n),
        "purchased": [list(s.purchased[0]), list(s.purchased[1])],
        "reserved": [list(s.reserved[0]), list(s.reserved[1])],
        "reserved_blind": [[bool(x) for x in s.reserved_blind[0]], [bool(x) for x in s.reserved_blind[1]]],
        "nobles_won": [list(s.nobles_won[0]), list(s.nobles_won[1])],
        "board": list(s.board),
        "decks": [list(s.decks[0]), list(s.decks[1]), list(s.decks[2])],
        "nobles": list(s.nobles),
        "turn": s.turn, "phase": s.phase, "pending_nobles": list(s.pending_nobles),
        "final_trigger": s.final_trigger, "winner": s.winner, "ply": s.ply, "win_points": s.win_points,
    }


cases = []
phase_counts = {0: 0, 1: 0, 2: 0}
g = 0
target = 800
while len(cases) < target:
    wp = 21 if g % 4 == 0 else 15
    s = E.new_game(random.Random(23000 + g), win_points=wp)
    ply = 0
    while s.phase != E.OVER and ply < 400:
        a = H3.choose_action(s)                 # greedy action for s.turn
        cases.append({"state": dump(s), "seat": s.turn, "action": a})
        phase_counts[s.phase] = phase_counts.get(s.phase, 0) + 1
        # play the H3 move sometimes, random otherwise, to reach varied (incl. DISCARD/NOBLE) states
        mv = a if (ply % 2 == 0) else random.Random(29_000_000 + g * 997 + ply).choice(E.legal_actions(s))
        E.apply(s, mv)
        ply += 1
        if len(cases) >= target:
            break
    g += 1

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "policy_fixtures.json"))
with open(dst, "w", encoding="utf-8") as f:
    json.dump(cases, f)
print(f"wrote {dst}: {len(cases)} cases  (PLAY {phase_counts.get(0,0)}, DISCARD {phase_counts.get(1,0)}, NOBLE {phase_counts.get(2,0)})")
