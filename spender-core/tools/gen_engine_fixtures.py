"""Generate engine differential-parity fixtures for the Rust port.

Plays random legal games through the PYTHON engine and dumps, per game, the initial State plus each
step's (legal_actions-before, action-taken, resulting State). The Rust test replays the same actions
from the same states and must reproduce both legal_actions and the full integer state exactly.

Run:  python spender-core/tools/gen_engine_fixtures.py [n_games]
Writes: spender-core/tests/engine_fixtures.json
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
os.environ.setdefault("SPENDER_AZ_MODEL", "none")

from games.spender.ai.az import engine as E  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120


def dump(s):
    return {
        "bank": list(s.bank),
        "tokens": [list(s.tokens[0]), list(s.tokens[1])],
        "bonuses": [list(s.bonuses[0]), list(s.bonuses[1])],
        "points": list(s.points),
        "purchased_n": list(s.purchased_n),
        "purchased": [list(s.purchased[0]), list(s.purchased[1])],
        "reserved": [list(s.reserved[0]), list(s.reserved[1])],
        "reserved_blind": [[bool(x) for x in s.reserved_blind[0]],
                           [bool(x) for x in s.reserved_blind[1]]],
        "nobles_won": [list(s.nobles_won[0]), list(s.nobles_won[1])],
        "board": list(s.board),
        "decks": [list(s.decks[0]), list(s.decks[1]), list(s.decks[2])],
        "nobles": list(s.nobles),
        "turn": s.turn,
        "phase": s.phase,
        "pending_nobles": list(s.pending_nobles),
        "final_trigger": s.final_trigger,
        "winner": s.winner,
        "ply": s.ply,
        "win_points": s.win_points,
    }


games = []
for g in range(N):
    wp = 21 if g % 4 == 0 else 15
    s = E.new_game(random.Random(g), win_points=wp)
    mv = random.Random(1_000_000 + g)
    fixture = {"init": dump(s), "steps": []}
    for _ in range(400):
        if s.phase == E.OVER:
            break
        legal = sorted(E.legal_actions(s))
        a = mv.choice(legal)
        E.apply(s, a)
        fixture["steps"].append({"legal": legal, "a": a, "after": dump(s)})
    games.append(fixture)

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "engine_fixtures.json"))
os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, "w", encoding="utf-8") as f:
    json.dump(games, f)
total_steps = sum(len(g["steps"]) for g in games)
finished = sum(1 for g in games if g["steps"] and g["steps"][-1]["after"]["phase"] == E.OVER)
print(f"wrote {dst}: {N} games, {total_steps} steps, {finished} finished")
