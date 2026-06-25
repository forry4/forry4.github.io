"""Layer-A leaf parity fixtures: the stateless per-card/seat scalars in valuation3.

Plays random games, samples states, and for each (state, card on board/reserved, seat) records every
stateless scalar. The Rust test recomputes them and asserts equality (ints exact, floats within 1e-9).

Run:  python spender-core/tools/gen_scalar_fixtures.py
Writes: spender-core/tests/scalar_fixtures.json
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
from games.spender.ai.az import valuation3 as V3  # noqa: E402


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


def case(s, ci, seat):
    return {
        "ci": ci, "seat": seat,
        "eff": list(V3.effective_cost(s, ci, seat)),
        "tec": V3.total_effective_cost(s, ci, seat),
        "conc": V3.cost_concentration(s, ci, seat),
        "gn": V3.gold_needed(s, ci, seat),
        "cdef": list(V3._color_deficits(s, ci, seat)),
        "gtc": V3.gems_to_collect(s, ci, seat),
        "tta": V3.turns_to_afford(s, ci, seat),
        "tempo": V3.tempo(s, ci, seat),
        "gemc": V3.gem_cost(s, ci, seat),
        "goldc": V3.gold_cost(s, ci, seat),
        "gshort": V3.gold_shortfall(s, ci, seat),
        "nprog": V3.noble_progress(s, ci, seat),
        "ncomp": V3.noble_completion_pts(s, ci, seat),
        "effi": V3.efficiency(s, ci, seat),
        "vclose": V3.victory_closeness(s, ci, seat),
    }


fixtures = []
states_target = 60
g = 0
while len(fixtures) < states_target:
    wp = 21 if g % 4 == 0 else 15
    s = E.new_game(random.Random(5000 + g), win_points=wp)
    mv = random.Random(9_000_000 + g)
    ply = 0
    while s.phase != E.OVER and ply < 400:
        if s.phase == E.PLAY and ply % 4 == 0:
            cards = [ci for ci in s.board if ci >= 0]
            for seat in (0, 1):
                cards_seat = cards + list(s.reserved[seat])
                cases = [case(s, ci, seat) for ci in cards_seat]
                if cases:
                    fixtures.append({"state": dump(s), "cases": cases})
            if len(fixtures) >= states_target:
                break
        legal = E.legal_actions(s)
        E.apply(s, mv.choice(legal))
        ply += 1
    g += 1

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "scalar_fixtures.json"))
with open(dst, "w", encoding="utf-8") as f:
    json.dump(fixtures, f)
n_cases = sum(len(fx["cases"]) for fx in fixtures)
print(f"wrote {dst}: {len(fixtures)} states, {n_cases} cases")
