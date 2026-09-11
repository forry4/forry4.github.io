"""Measure the fast native arena proxy against a frozen set of checkpoints.

The calibration uses one fixed development pool for every row, so every
budget/worker profile sees the same paired deals and board assignments.  It is
an ordering and throughput diagnostic, not a promotion gate: a fast profile
can select candidates, while the rare serving-shaped check remains the final
compatibility test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[3]
# Campaign artifacts live under the game, like every other game's AI data
# (`games/spender/ai/offline/...`). They used to be ~40 `.orbit-*` directories in
# the REPO ROOT holding 5.8 GB, most of it dead cargo build output.
ORBIT_RUNS = REPO_ROOT / "games" / "orbit" / "ai" / "runs"
_PORTABLE_BINARY = REPO_ROOT / "rust-cores" / "orbit-core" / "target" / "release" / "neural_arena.exe"
_NATIVE_BINARY = ORBIT_RUNS / "target-native" / "release" / "neural_arena.exe"
DEFAULT_BINARY = _NATIVE_BINARY if _NATIVE_BINARY.is_file() else _PORTABLE_BINARY


def _ints(raw: str, *, name: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
    except ValueError as error:
        raise ValueError(f"{name} must be comma-separated integers") from error
    if not values or any(value < 1 for value in values):
        raise ValueError(f"{name} must contain positive integers")
    return sorted(set(values))


def _split_budget(budget: int) -> tuple[int, int]:
    """Keep the serving 60/40 main/follow-up allocation at any proxy budget."""

    main = max(1, round(budget * 0.60))
    followup = max(1, budget - main)
    return main, followup


def _run_one(args: argparse.Namespace, checkpoint: Path, report: Path,
             *, budget: int, workers: int, game_workers: int) -> dict:
    main, followup = _split_budget(budget)
    command = [
        sys.executable,
        "-m",
        "games.orbit.tools.native_search_arena",
        str(checkpoint),
        str(report),
        "--pairs", str(args.pairs),
        "--budget-ms", str(budget),
        "--main-action-ms", str(main),
        "--followup-ms", str(followup),
        "--workers", str(workers),
        "--via-observation",
        "--pool", args.pool,
        "--binary", str(args.binary.resolve()),
        "--opponent-expert",
    ]
    if game_workers > 1:
        command.extend(["--game-workers", str(game_workers)])
    print(json.dumps({"start": "calibration", "checkpoint": str(checkpoint),
                      "budget_ms": budget, "workers": workers, "command": command}), flush=True)
    started = time.perf_counter()
    subprocess.run(command, cwd=str(REPO_ROOT), check=True)
    elapsed = time.perf_counter() - started
    payload = json.loads(report.read_text(encoding="utf-8"))
    arena = payload.get("arena") or {}
    if not payload.get("complete") or not arena:
        raise RuntimeError(f"incomplete calibration report: {report}")
    row = {
        "checkpoint": str(checkpoint),
        "budget_ms": budget,
        "main_action_ms": main,
        "followup_ms": followup,
        "workers": workers,
        "game_workers": game_workers,
        "score": float(arena.get("score", 0.5)),
        "pair_score": float(arena.get("pair_score", 0.5)),
        "pair_ci95": list(arena.get("pair_ci95", [0.5, 0.5])),
        "pairs": int(arena.get("pairs", 0)),
        "complete_pairs": int(arena.get("complete_pairs", 0)),
        "censored": int(arena.get("censored", 0)),
        "simulations": sum(int(item.get("simulations", 0)) for item in payload.get("games", [])),
        "decisions": sum(int(item.get("decisions", 0)) for item in payload.get("games", [])),
        "seconds": float(payload.get("seconds", elapsed)),
        "report": str(report.resolve()),
    }
    print(json.dumps({"complete": "calibration", **{key: row[key] for key in
        ("budget_ms", "workers", "game_workers", "pair_score", "pair_ci95", "seconds")}}), flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="JSON calibration summary directory or file")
    parser.add_argument("checkpoints", type=Path, nargs="+",
                        help="Frozen candidate checkpoints to compare")
    parser.add_argument("--pairs", type=int, default=8,
                        help="Paired games per checkpoint/profile; use a larger value for final calibration")
    parser.add_argument("--budgets", default="500,1000,2000",
                        help="Proxy whole-turn budgets in milliseconds")
    parser.add_argument("--workers", default=str(max(1, min((os.cpu_count() or 1) - 1, 16))),
                        help="Comma-separated native worker counts")
    parser.add_argument("--game-workers", default="auto",
                        help="Independent games per row; auto fills the host for each root width")
    parser.add_argument("--include-serving", action="store_true",
                        help="Also measure the actual 5000 ms / 3000+2000 serving profile")
    parser.add_argument("--pool", default="development-orbit-calibration-v1",
                        help="One fixed pool name shared by every matrix row (CRN)")
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    args = parser.parse_args()
    if args.pairs < 8 or args.pairs % 8:
        parser.error("--pairs must be a positive multiple of eight")
    try:
        budgets = _ints(args.budgets, name="--budgets")
        workers = _ints(args.workers, name="--workers")
    except ValueError as error:
        parser.error(str(error))
    try:
        game_workers_arg = str(args.game_workers).strip().lower()
        game_workers_fixed = None if game_workers_arg == "auto" else int(game_workers_arg)
    except ValueError as error:
        parser.error("--game-workers must be a positive integer or auto")
    if game_workers_fixed is not None and not 1 <= game_workers_fixed <= 16:
        parser.error("--game-workers must be in 1..16")
    if any(budget < 100 for budget in budgets):
        parser.error("calibration budgets must be at least 100 ms")
    if any(worker > 16 for worker in workers):
        parser.error("native worker counts must be in 1..16")
    def profiles_for_budget(budget: int) -> list[tuple[int, int, int]]:
        # The actual browser row is deliberately serial at its four-tree
        # serving shape.  Proxy rows may spend the same native budget on
        # unrelated games, which is the throughput path Spender uses.
        if budget >= 5000 and args.include_serving:
            return [(budget, 4, 1)]
        result = []
        for worker in workers:
            games = game_workers_fixed if game_workers_fixed is not None else max(
                1, min(16, (os.cpu_count() or 1) // worker))
            if worker * games > 16:
                parser.error("workers*game-workers must be <=16")
            result.append((budget, worker, games))
        return result
    for checkpoint in args.checkpoints:
        if not checkpoint.is_file():
            parser.error(f"checkpoint not found: {checkpoint}")
    args.binary = args.binary.resolve()
    if not args.binary.is_file():
        parser.error(f"arena binary not found: {args.binary}")
    output = args.output
    if output.suffix.lower() == ".json":
        summary_path = output
        output_dir = output.parent / (output.stem + "-reports")
    else:
        output_dir = output
        summary_path = output / "calibration.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for checkpoint in args.checkpoints:
        checkpoint = checkpoint.resolve()
        stem = checkpoint.stem.replace(" ", "_")
        for budget in budgets:
            for _, worker, game_workers in profiles_for_budget(budget):
                report = output_dir / stem / f"{budget}ms-w{worker}-g{game_workers}.json"
                legacy_report = output_dir / stem / f"{budget}ms-w{worker}.json"
                if not report.exists() and game_workers == 1 and legacy_report.exists():
                    report = legacy_report
                if report.exists():
                    payload = json.loads(report.read_text(encoding="utf-8"))
                    arena = payload.get("arena") or {}
                    if payload.get("complete") and arena:
                        rows.append({
                            "checkpoint": str(checkpoint),
                            "budget_ms": budget,
                            "main_action_ms": _split_budget(budget)[0],
                            "followup_ms": _split_budget(budget)[1],
                            "workers": worker,
                            "game_workers": int(payload.get("game_workers", game_workers)),
                            "score": float(arena.get("score", 0.5)),
                            "pair_score": float(arena.get("pair_score", 0.5)),
                            "pair_ci95": list(arena.get("pair_ci95", [0.5, 0.5])),
                            "pairs": int(arena.get("pairs", 0)),
                            "complete_pairs": int(arena.get("complete_pairs", 0)),
                            "censored": int(arena.get("censored", 0)),
                            "simulations": sum(int(item.get("simulations", 0)) for item in payload.get("games", [])),
                            "decisions": sum(int(item.get("decisions", 0)) for item in payload.get("games", [])),
                            "seconds": float(payload.get("seconds", 0.0)),
                            "report": str(report.resolve()),
                        })
                        continue
                rows.append(_run_one(args, checkpoint, report, budget=budget,
                                     workers=worker, game_workers=game_workers))
    summary = {
        "schema": 1,
        "purpose": "calibration only; proxy rows select, serving row validates",
        "pool": args.pool,
        "pairs": args.pairs,
        "budgets_ms": budgets,
        "workers": workers,
        "game_workers": args.game_workers,
        "same_crn_pool": True,
        "rows": rows,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = summary_path.with_name(summary_path.name + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    temporary.replace(summary_path)
    print(json.dumps({"complete": "calibration-summary", "rows": len(rows),
                      "summary": str(summary_path.resolve())}), flush=True)


if __name__ == "__main__":
    main()
