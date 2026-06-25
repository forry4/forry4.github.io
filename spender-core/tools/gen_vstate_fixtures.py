"""Layer-D leaf parity: v_state.value (the actual variant-S search leaf) + its component breakdown.

This is the FULL leaf-parity gate. Dumps value(s,0)/value(s,1) and the components() dict; Rust
recomputes and asserts within 1e-9.

Run:  python spender-core/tools/gen_vstate_fixtures.py
Writes: spender-core/tests/vstate_fixtures.json
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
from games.spender.ai.az import v_state as VS      # noqa: E402


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


fixtures = []
states_target = 80
g = 0
while len(fixtures) < states_target:
    wp = 21 if g % 4 == 0 else 15
    s = E.new_game(random.Random(13000 + g), win_points=wp)
    mv = random.Random(17_000_000 + g)
    ply = 0
    while s.phase != E.OVER and ply < 400:
        if s.phase == E.PLAY and ply % 3 == 0:
            comp = VS.components(s, 0)
            fixtures.append({
                "state": dump(s),
                "value0": VS.value(s, 0),
                "value1": VS.value(s, 1),
                "comp": {k: comp[k] for k in (
                    "points_me", "points_opp", "engine_me", "engine_opp",
                    "progress_me", "progress_opp", "noble_me", "noble_opp",
                    "econ_me", "econ_opp", "stand_me", "stand_opp", "value")},
            })
            if len(fixtures) >= states_target:
                break
        E.apply(s, mv.choice(E.legal_actions(s)))
        ply += 1
    g += 1

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "vstate_fixtures.json"))
with open(dst, "w", encoding="utf-8") as f:
    json.dump(fixtures, f)
print(f"wrote {dst}: {len(fixtures)} states")
