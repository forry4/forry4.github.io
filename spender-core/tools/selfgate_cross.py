"""Cross-impl strength self-gate: Rust-S vs Python-S, move-for-move, at matched sims.

The Rust search isn't bit-identical to Python (different determinization RNG), so we validate the
search STATISTICALLY: pit Rust-S against Python-S over paired games (each board played both
orientations to cancel the first-player edge). Rust win rate ~0.5 => the Rust search plays
equivalently to the reference.

Build the bin first:
  (cd spender-core && cargo build --release --features bridge --bin move_server)
Run:
  python spender-core/tools/selfgate_cross.py [n_base_seeds] [sims]
"""
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
os.environ.setdefault("SPENDER_AZ_MODEL", "none")

import random  # noqa: E402

from games.spender.ai.az import engine as E      # noqa: E402
from games.spender.ai.az import vsearch as PV     # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
SIMS = int(sys.argv[2]) if len(sys.argv) > 2 else 80
BIN = os.path.join(HERE, "..", "target", "release", "move_server.exe")
if not os.path.exists(BIN):
    BIN = os.path.join(HERE, "..", "target", "release", "move_server")


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


proc = subprocess.Popen([BIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)


def rust_move(s, seat, seed):
    req = {"state": dump(s), "seat": seat, "sims": SIMS, "seed": seed}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return int(proc.stdout.readline().strip())


def play(seed, rust_seat, wp):
    s = E.new_game(random.Random(seed), win_points=wp)
    ply = 0
    while s.phase != E.OVER and ply < 500:
        seat = s.turn
        if seat == rust_seat:
            a = rust_move(s, seat, seed * 100003 + ply)
        else:
            a = PV.choose_action(s, seat, sims=SIMS)
        E.apply(s, a)
        ply += 1
    if s.phase != E.OVER or s.winner == E.WIN_DRAW:
        return 0.5
    return 1.0 if s.winner == rust_seat else 0.0


score, games = 0.0, 0
for g in range(N):
    wp = 21 if g % 4 == 0 else 15
    seed = 31000 + g
    score += play(seed, 0, wp)   # Rust as seat 0
    score += play(seed, 1, wp)   # Rust as seat 1 (same board)
    games += 2
    if (g + 1) % 10 == 0:
        print(f"  ... {games} games, Rust win-rate {score/games:.4f}", flush=True)

proc.stdin.close()
proc.wait()
wr = score / games
se = math.sqrt(wr * (1 - wr) / games)
print(f"\nRust-S vs Python-S: {wr:.4f}  (+/-{1.96*se:.3f} 95% CI, {games} games @ sims={SIMS})")
print("~0.5 => the Rust search plays equivalently to the Python reference.")
