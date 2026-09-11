"""Hold the Rust leaf evaluator to the Python reference it was ported from.

`rust-cores/orbit-core/src/search.rs` originally shipped a leaf that was only
the FIRST TERM of `games/orbit/ai/search.py::state_value` -- capture progress,
with neither the 1.4 weight nor influence proximity, technology, leader,
economy or hand terms. Measured over 19,034 real positions that reduced leaf
took 25 distinct values in an entire game, was exactly 0.0 on 35% of positions
and flat for the first 26%. The Rust search is the one that runs offline and in
the browser, so every campaign number to 2026-09-11 was produced by it.

This walks real games and compares the two implementations position by
position. It is the same shape as the existing native/tensor/attention parity
harnesses, and it exists because the defect it guards against was invisible:
a leaf that silently drops terms still returns a plausible number.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from ..ai.search import _actor, state_value
from ..ai.state import native_state
from ..ai.selfplay import board_configurations
from .. import engine


REPO_ROOT = Path(__file__).resolve().parents[3]
# Campaign artifacts live under the game, like every other game's AI data
# (`games/spender/ai/offline/...`). They used to be ~40 `.orbit-*` directories in
# the REPO ROOT holding 5.8 GB, most of it dead cargo build output.
ORBIT_RUNS = REPO_ROOT / "games" / "orbit" / "ai" / "runs"
_PORTABLE_BINARY = REPO_ROOT / "rust-cores" / "orbit-core" / "target" / "release" / "bridge.exe"
_NATIVE_BINARY = ORBIT_RUNS / "target-native" / "release" / "bridge.exe"
# Deliberately the PORTABLE build, unlike the campaign tools. A parity harness
# should measure the arithmetic that ships (the browser/WASM build compiles from
# this same portable configuration), not a `-C target-cpu=native --features
# chunked-dot` binary whose whole purpose is to reassociate float reductions.
# It also avoids reading a stale `runs/target-native` and reporting the old
# leaf as a parity failure.
DEFAULT_BINARY = _PORTABLE_BINARY
# float64 both sides through a JSON round trip and a tanh; the observed maximum
# over 8 games was ~1e-15, so this is loose by many orders of magnitude and
# still tight enough to catch a dropped or reweighted term.
TOLERANCE = 1e-9


def walk(games: int, seed: int, binary: Path) -> dict:
    boards = board_configurations()
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, bufsize=1)
    compared = 0
    worst = 0.0
    worst_at: dict | None = None
    try:
        for index in range(games):
            board = boards[index % len(boards)]
            game = engine.new_game([f"p{index}a", f"p{index}b"],
                                   seed=seed + index, configuration=board)
            for _ in range(1600):
                if engine.is_over(game):
                    break
                pid = _actor(game)
                if pid is None:
                    break
                moves = engine.legal_moves(game, pid)
                if not moves:
                    break
                request = {"state": native_state(game), "seat": game["order"].index(pid),
                           "move": moves[0], "shuffles": [], "leaf_only": True}
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                reply = json.loads(process.stdout.readline())
                if "bridge_error" in reply:
                    raise RuntimeError(f"bridge refused a position: {reply['bridge_error']}")
                for seat, native in enumerate(reply["state_value"]):
                    reference = state_value(game, game["order"][seat])
                    delta = abs(float(native) - float(reference))
                    compared += 1
                    if delta > worst:
                        worst, worst_at = delta, {"game": index, "seat": seat,
                                                   "turn": game["turn_number"],
                                                   "python": reference, "rust": native}
                engine.apply_move(game, pid, moves[0])
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    return {"positions": compared, "max_abs_delta": worst, "worst": worst_at,
            "tolerance": TOLERANCE, "passed": compared > 0 and worst <= TOLERANCE}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=8)
    parser.add_argument("--seed", type=int, default=9300)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    args = parser.parse_args()
    if args.games < 1:
        parser.error("--games must be positive")
    report = walk(args.games, args.seed, args.binary)
    json.dump(report, sys.stdout, indent=1)
    sys.stdout.write("\n")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
