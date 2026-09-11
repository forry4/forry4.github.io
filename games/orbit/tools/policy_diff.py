"""Measure how often two checkpoints choose a different move.

This is the cheapest useful question in the campaign and it runs before any
arena. The 2026-09-11 audit measured two league checkpoints agreeing on 63.4% of
decisions in SELF-PLAY (60.7% where more than one move is legal), with the frozen
hand-written prior deciding 50.5% of them. Quote the self-play figure: the same
pair reads 77.9% agreement on a search-versus-random trajectory, because a random
opponent manufactures positions where most moves are obvious, and an arena samples
self-play. A generation whose candidate simply plays the incumbent's moves should
be recognised as a no-op in seconds rather than bought an arena.

Agreement is a diagnostic, never a strength claim: a candidate that disagrees a
lot may be worse. It answers "is there anything here to measure", not "is it
better".
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
# Campaign artifacts live under the game, like every other game's AI data
# (`games/spender/ai/offline/...`). They used to be ~40 `.orbit-*` directories in
# the REPO ROOT holding 5.8 GB, most of it dead cargo build output.
ORBIT_RUNS = REPO_ROOT / "games" / "orbit" / "ai" / "runs"
_PORTABLE_BINARY = REPO_ROOT / "rust-cores" / "orbit-core" / "target" / "release" / "policy_diff.exe"
_NATIVE_BINARY = ORBIT_RUNS / "target-native" / "release" / "policy_diff.exe"
DEFAULT_BINARY = _NATIVE_BINARY if _NATIVE_BINARY.is_file() else _PORTABLE_BINARY


def measure(reference: Path | None, other: Path | None, *, games: int, simulations: int,
            seed: int, binary: Path) -> dict:
    """Run the native probe. ``None`` for either side means the heuristic leaf."""

    from ..ai.attention import export_model, load_checkpoint

    def artifact(path: Path | None):
        if path is None:
            return None
        return export_model(load_checkpoint(path)[0])

    request = {
        "model": artifact(reference),
        "other_model": artifact(other),
        "games": int(games),
        "simulations": int(simulations),
        "seed": int(seed),
    }
    process = subprocess.run([str(binary)], input=json.dumps(request), text=True,
                             capture_output=True, check=True)
    report = json.loads(process.stdout.strip().splitlines()[-1])
    report["reference"] = str(reference) if reference else "heuristic"
    report["other"] = str(other) if other else "heuristic"
    return report


def worth_an_arena(report: dict, *, ceiling: float) -> bool:
    """Is there enough policy difference here for an arena to see anything?

    ``ceiling`` is an agreement percentage, not a win rate. Above it the two
    players make the same moves often enough that their game outcomes will be
    near-identical on most deals, so the arena spends hours to return its own
    noise.
    """

    if not report.get("complete"):
        return True  # a broken probe must never silently skip the measurement
    return float(report["agree_pct_where_more_than_one_legal_move"]) < ceiling


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="Checkpoint, or 'heuristic'")
    parser.add_argument("other", type=Path, help="Checkpoint, or 'heuristic'")
    parser.add_argument("--games", type=int, default=8)
    parser.add_argument("--simulations", type=int, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--agreement-ceiling", type=float, default=97.0)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.games < 1 or not 1 <= args.simulations <= 10000:
        parser.error("games must be positive and simulations 1..10000")
    if not 0.0 < args.agreement_ceiling <= 100.0:
        parser.error("--agreement-ceiling is a percentage in (0, 100]")

    def resolve(value: Path) -> Path | None:
        return None if str(value) == "heuristic" else value

    report = measure(resolve(args.reference), resolve(args.other), games=args.games,
                     simulations=args.simulations, seed=args.seed, binary=args.binary)
    report["agreement_ceiling"] = args.agreement_ceiling
    report["worth_an_arena"] = worth_an_arena(report, ceiling=args.agreement_ceiling)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    json.dump(report, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
