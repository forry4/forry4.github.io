"""Turn an equal-TIME arena report into the fixed-simulation flags that match it.

Equal time is the campaign's ship criterion, but an equal-time arena is
load-dependent: its wall clock is set by decisions x budget, so extra load does
not slow it down, it silently starves every decision of simulations. That is how
a contended 2026-09-11 pool came back at 6,482 simulations per decision without
anything in the report saying so, and it is why a screen wants the deterministic
form instead.

The naive deterministic form is wrong for this question. Giving both seats the
same count measures equal-SIMS, which the campaign already settled. At equal
TIME the two sides do markedly different amounts of work, so each seat is
calibrated to what it actually achieved at serving shape and the counts come out
ASYMMETRIC by design.

The direction of that asymmetry was a surprise, and it is worth stating because
an earlier draft of this file asserted the opposite. Measured over pools 5-6 of
the 2026-09-11 serving check, the COHERENT search completes about 10,900
simulations per decision against per-simulation determinization's 14,200 -- a
ratio of 0.767, consistently 0.765-0.769 across pools. Coherence is roughly a
QUARTER SLOWER per decision, because reusing the tree means descending it: the
audit measured mean depth 4.2 plies under coherence against 2.4 under
resampling, and a deeper descent costs more node lookups and more applied moves
per simulation. The opponent-reply cache (1.38-1.66x) offsets part of that cost;
it does not reverse it.

Which makes the arena result stronger than it first looked: coherent wins 0.62
while doing fewer simulations. The advantage is the quality of the search, not
its quantity. The result approximates equal time rather than being it --
the cache's hit rate grows with tree size, so the ratio is not constant across a
game -- which makes this an excellent screen and a poor final ship gate.

Two details are easy to get wrong and are handled here:

* ``simulations_by_seat`` is indexed by SEAT, but the candidate swaps seats every
  other game for common random numbers. Pooling by seat rather than by ROLE
  averages the two players together and produces two identical, meaningless
  numbers.
* ``--simulations`` is PER WORKER. The arena asserts the realised total equals
  ``n * actor_pool``, and ``actor_pool`` is the worker pool only when the search
  runs ``--via-observation``; otherwise it is 1 however many workers were asked
  for.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def actor_pool(report: dict) -> int:
    """Workers that actually run per decision, mirroring the native arena."""

    return int(report["workers"]) if report.get("via_observation") else 1


def tally(reports: list[tuple[Path, dict]]) -> dict:
    roles = {"candidate": [0, 0], "opponent": [0, 0]}  # [simulations, searches]
    pools: set[int] = set()
    games = 0
    for path, report in reports:
        if report.get("fixed_simulations") is not None:
            raise ValueError(f"{path.name} is already a fixed-simulation run; "
                             "calibrate from an equal-TIME report")
        pools.add(actor_pool(report))
        for row in report["games"]:
            if "simulations_by_seat" not in row:
                raise ValueError(
                    f"{path.name} predates per-seat counters, so its simulation total is a "
                    "blend of both players and cannot be split. Re-run the arena.")
            seat = int(row["candidate"])
            for role, index in (("candidate", seat), ("opponent", 1 - seat)):
                roles[role][0] += int(row["simulations_by_seat"][index])
                roles[role][1] += int(row["searches_by_seat"][index])
            games += 1
    if len(pools) != 1:
        raise ValueError(f"Reports disagree on the worker pool: {sorted(pools)}")
    pool = pools.pop()
    out = {"games": games, "actor_pool": pool, "reports": [p.name for p, _ in reports]}
    for role, (simulations, searches) in roles.items():
        if not searches:
            raise ValueError(f"No searched decisions recorded for the {role}")
        per_decision = simulations / searches
        per_worker = round(per_decision / pool)
        if not 1 <= per_worker <= 10000:
            raise ValueError(
                f"{role} calibrates to {per_worker} simulations per worker, outside the "
                "arena's 1..10000 range; screen at a shorter budget or a wider pool")
        out[role] = {"searched_decisions": searches, "simulations": simulations,
                     "per_decision": round(per_decision, 1), "per_worker": per_worker}
    out["throughput_ratio"] = round(
        out["candidate"]["per_decision"] / out["opponent"]["per_decision"], 3)
    out["flags"] = (f"--simulations {out['candidate']['per_worker']} "
                    f"--opponent-simulations {out['opponent']['per_worker']}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", type=Path, nargs="+", help="Equal-time arena reports")
    args = parser.parse_args()
    loaded = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("complete"):
            raise SystemExit(f"{path.name} is not a complete report; calibrating from a "
                             "partial run would encode whatever load killed it")
        loaded.append((path, report))
    json.dump(tally(loaded), sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
