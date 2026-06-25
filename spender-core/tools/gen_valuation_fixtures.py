"""Layer-B leaf parity fixtures: the Valuation context + engine_value chain + turns + noble time-gate.

Builds a Valuation exactly as the leaf does (H3 weights) and dumps state-level aggregates + per-(card,
seat) engine_value/eng_base/potential/cost_scalar/noble_progress. Rust recomputes; asserts within 1e-9.

Run:  python spender-core/tools/gen_valuation_fixtures.py
Writes: spender-core/tests/valuation_fixtures.json
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
from games.spender.ai.az import valuation3 as V3  # noqa: E402
from games.spender.ai.az import heuristic3 as H3   # noqa: E402

WT, WG, WGO = H3.W_TEMPO, H3.W_GEM, H3.W_GOLD


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
states_target = 60
g = 0
while len(fixtures) < states_target:
    wp = 21 if g % 4 == 0 else 15
    s = E.new_game(random.Random(7000 + g), win_points=wp)
    mv = random.Random(11_000_000 + g)
    ply = 0
    while s.phase != E.OVER and ply < 400:
        if s.phase == E.PLAY and ply % 4 == 0:
            cards = [ci for ci in s.board if ci >= 0]
            val = V3.Valuation(s, WT, WG, WGO)
            fx = {
                "state": dump(s), "wt": WT, "wg": WG, "wgo": WGO,
                "turns": val.estimated_turns_remaining(),
                "dcd": list(val.deck_color_demand),
                "dds0": list(val._deck_demand_seat(0)),
                "dds1": list(val._deck_demand_seat(1)),
                "cases": [],
            }
            for seat in (0, 1):
                for ci in cards + list(s.reserved[seat]):
                    tk, eng, pt, cst = H3.components(val, ci, seat)
                    fx["cases"].append({
                        "ci": ci, "seat": seat,
                        "cs": val._cost_scalar(ci, seat),
                        "eb": val._eng_base(ci, seat),
                        "pot": val.potential_value(ci, seat),
                        "ev": val.engine_value(ci, seat),
                        "np": val.noble_progress(ci, seat),
                        "take": tk, "tk_eng": eng, "tk_pt": pt, "tk_cost": cst,
                    })
            if fx["cases"]:
                fixtures.append(fx)
            if len(fixtures) >= states_target:
                break
        E.apply(s, mv.choice(E.legal_actions(s)))
        ply += 1
    g += 1

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "valuation_fixtures.json"))
with open(dst, "w", encoding="utf-8") as f:
    json.dump(fixtures, f)
n = sum(len(fx["cases"]) for fx in fixtures)
print(f"wrote {dst}: {len(fixtures)} states, {n} cases (weights {WT}/{WG}/{WGO})")
