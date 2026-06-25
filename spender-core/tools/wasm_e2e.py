"""End-to-end check of the WASM serving entry: dump a real mid-game AI-turn state, run it through the
node WASM `choose_move`, and assert the returned dict-move is LEGAL in that state (and convertible back
via move_to_action). Proves the full browser path: state JSON -> WASM search -> main.py-shaped move dict.
"""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
os.environ.setdefault("SPENDER_AZ_MODEL", "none")

from games.spender.ai.az import actions as A     # noqa: E402
from games.spender.ai.az import engine as E       # noqa: E402
from games.spender.ai.az import heuristic3 as H3   # noqa: E402


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


pkg = os.path.join(HERE, "..", "pkg", "spender_core.js").replace("\\", "/")
ok = 0
for trial in range(6):
    s = E.new_game(random.Random(700 + trial), win_points=15)
    for _ in range(18 + trial):
        if s.phase == E.OVER:
            break
        E.apply(s, H3.choose_action(s))
    if s.phase != E.PLAY:
        continue
    state_json = json.dumps(dump(s), separators=(",", ":")).replace("\\", "\\\\").replace("'", "\\'")
    node_src = (
        f"const w=require('{pkg}');"
        f"const mv=w.choose_move('{state_json}',{s.turn},1500,{trial + 1}n);"
        f"console.log(mv);"
    )
    out = subprocess.check_output(["node", "-e", node_src], text=True).strip()
    mv = json.loads(out)
    act = A.move_to_action(s, mv)
    legal = act in E.legal_actions(s)
    assert legal, f"WASM returned ILLEGAL move {mv} (action {act}) at ply {s.ply}"
    print(f"trial {trial}: turn={s.turn} ply={s.ply} -> {mv}  (action {act}, legal={legal})")
    ok += 1

print(f"\nWASM choose_move e2e: {ok} positions, all returned LEGAL dict-moves.")
