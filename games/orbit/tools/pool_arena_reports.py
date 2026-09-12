"""Pool independent arena reports into one paired estimate.

A 16-pair pool resolves about +/-0.22, which is far too coarse to decide
anything -- the 2026-09-11 serving check read 0.5000, 0.5625 and 0.6875 across
three pools of the SAME comparison. Pools are run separately only so a crash
costs one pool instead of the night; the estimate that means anything is the
pooled one.

Pair scores are reconstructed from the raw game rows rather than averaging the
per-pool summaries. Averaging summaries is right only when every pool has the
same pair count, and silently wrong when one is short -- which is exactly what a
resumed or interrupted run produces.

The bar this reports against is the league's own: `pair_ci95` lower bound above
0.50, at `--accept-pairs` (128) pairs.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import statistics
import sys


def pair_scores(report: dict) -> list[float]:
    """Fold a report's games into per-pair scores.

    A pair is one deal played from BOTH seats (common random numbers), so its
    score is the candidate's mean result over the two games: 1.0, 0.5 or 0.0.
    An incomplete pair is dropped rather than counted as a half -- a single
    game's result is not a paired observation and would understate the variance.
    """

    pairs: dict[int, list[float]] = {}
    for row in report["games"]:
        if row.get("error") or row.get("censored"):
            continue
        pairs.setdefault(row["index"] // 2, []).append(
            1.0 if row["winner"] == row["candidate"] else 0.0)
    return [statistics.mean(v) for _, v in sorted(pairs.items()) if len(v) == 2]


def pool(reports: list[tuple[str, dict]], *, accept_pairs: int, lower: float,
         resamples: int = 20000, seed: int = 7) -> dict:
    scores: list[float] = []
    per_pool = []
    for name, report in reports:
        own = pair_scores(report)
        if not own:
            raise ValueError(f"{name} contributed no complete pairs")
        per_pool.append({"report": name, "pairs": len(own),
                         "pair_score": round(statistics.mean(own), 4)})
        scores.extend(own)
    count = len(scores)
    mean = statistics.mean(scores)
    if count < 2:
        raise ValueError("Pooling needs at least two pairs")
    deviation = statistics.stdev(scores)
    error = deviation / math.sqrt(count)
    generator = random.Random(seed)
    boots = sorted(statistics.mean(generator.choices(scores, k=count))
                   for _ in range(resamples))
    interval = [boots[int(resamples * 0.025)], boots[int(resamples * 0.975)]]
    return {
        "pools": per_pool,
        "pairs": count,
        "pair_score": round(mean, 4),
        "pair_sd": round(deviation, 4),
        "pair_se": round(error, 4),
        "normal_ci95": [round(mean - 1.96 * error, 4), round(mean + 1.96 * error, 4)],
        "bootstrap_ci95": [round(interval[0], 4), round(interval[1], 4)],
        "outcomes": {"losses": scores.count(0.0), "splits": scores.count(0.5),
                     "wins": scores.count(1.0)},
        # Sized from the MEASURED spread, not a guess, so "run more pools" is a
        # number rather than an instinct.
        "pairs_needed_for_0.03": math.ceil((1.96 * deviation / 0.03) ** 2),
        "pairs_needed_for_this_effect":
            math.ceil((1.96 * deviation / abs(mean - 0.5)) ** 2) if mean != 0.5 else None,
        "accept_pairs": accept_pairs,
        "accept_lower": lower,
        "accepted": count >= accept_pairs and interval[0] > lower,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--accept-pairs", type=int, default=128)
    parser.add_argument("--accept-lower", type=float, default=0.50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    loaded = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("complete"):
            print(f"skipping {path.name}: not a complete report", file=sys.stderr)
            continue
        loaded.append((path.name, report))
    if not loaded:
        raise SystemExit("No complete reports to pool")
    result = pool(loaded, accept_pairs=args.accept_pairs, lower=args.accept_lower)
    if args.output:
        args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    json.dump(result, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
