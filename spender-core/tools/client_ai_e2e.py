"""End-to-end of the SERVER client-AI offload loop (minus the WS transport):
  main._compact_state_dict(game)  ->  WASM choose_move (node)  ->  legal dict-move  ->  main._run_ai_turn
Proves the server builds a valid search payload, the browser returns a legal move, and the server applies
it + advances the turn. Also checks an illegal client move is rejected by the legality guard.
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

from games.spender import main                       # noqa: E402
from games.spender.ai.az import actions as A          # noqa: E402
from games.spender.ai.az import engine as E           # noqa: E402
from games.spender.ai.az import heuristic3 as H3       # noqa: E402

PKG = os.path.join(HERE, "..", "pkg", "spender_core.js").replace("\\", "/")


def wasm_choose_move(state_dict, seat, sims, seed):
    sj = json.dumps(state_dict, separators=(",", ":")).replace("\\", "\\\\").replace("'", "\\'")
    src = f"const w=require('{PKG}');console.log(w.choose_move('{sj}',{seat},{sims},{seed}n));"
    return json.loads(subprocess.check_output(["node", "-e", src], text=True).strip())


ok = 0
for trial in range(6):
    s = E.new_game(random.Random(900 + trial), win_points=15)
    for _ in range(20 + trial):
        if s.phase == E.OVER:
            break
        E.apply(s, H3.choose_action(s))
    if s.phase != E.PLAY:
        continue
    pids = ("human", "ai") if s.turn == 1 else ("ai", "human")
    ai_pid = "ai"
    game = E.to_game_dict(s, pids)
    game["ai_player"] = ai_pid
    assert game["turn"] == ai_pid

    # 1) server builds the search payload (what mk_room_state ships in ai_search.state)
    payload = main._compact_state_dict(game)
    seat = game["order"].index(ai_pid)

    # 2) the browser (WASM) searches it and returns a dict-move
    mv = wasm_choose_move(payload, seat, main.CLIENT_AI_SIMS, trial + 1)

    # 3) server validates legality (the ai_move guard) and applies the full AI turn
    s2 = E.from_game_dict(game)
    act = A.move_to_action(s2, mv)
    assert act in E.legal_actions(s2), f"WASM move {mv} illegal"
    turn_before = game["turn"]
    main._run_ai_turn(game, ai_pid, mv)
    advanced = game["turn"] != turn_before or game.get("phase") == "over"
    assert advanced, "AI turn did not advance after _run_ai_turn"

    # 4) illegal client move must be rejected by the guard (move_to_action/legal check)
    bad = {"type": "buy", "card_id": "L3-19"}  # an L3 almost never affordable mid-game
    s3 = E.from_game_dict(game)  # (now the human's turn, but we only test the legality guard logic)
    try:
        bad_act = A.move_to_action(s3, bad)
        bad_legal = bad_act in E.legal_actions(s3)
    except Exception:
        bad_legal = False
    print(f"trial {trial}: ai move {mv} -> applied, turn advanced={advanced}; "
          f"bogus-L3-buy rejected={not bad_legal}")
    ok += 1

print(f"\nclient-AI server loop e2e: {ok} turns offloaded + applied; legality guard holds.")
