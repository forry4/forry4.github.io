"""Prove two arena binaries are the SAME experiment before pooling their results.

A campaign that changes the search crate mid-run silently stops comparing like
with like: pools measured on an old binary and pools measured on a new one are
two experiments wearing one name, and nothing in either report says so. This is
the gate that makes a refactor safe to land in the middle of a measurement.

It is deliberately narrow. It compares only the DETERMINISTIC fields, because
those are the ones a semantics-preserving change must not move: the winner, the
simulation and decision counts, the seeds, and the censoring. Wall-clock fields
are excluded -- they differ run to run on the same binary, so including them
would make the gate cry wolf and get ignored, which is worse than not having it.

Requires FIXED SIMULATIONS on both sides. An equal-time arena cannot reproduce
itself even on one binary, so it can never prove anything here; the tool refuses
rather than reporting a difference it cannot attribute.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


# What a semantics-preserving change must hold constant, per game.
COMPARED = ("index", "seed", "candidate", "winner", "simulations", "decisions",
            "censored", "error")
# Settings that must match, or the two runs are not the same experiment to begin
# with and any agreement would be luck.
SETTINGS = ("pool", "fixed_simulations", "fixed_opponent_simulations", "workers",
            "game_workers", "via_observation", "leaf", "opponent_leaf",
            "determinization_period", "opponent_determinization_period",
            "checkpoint", "opponent")


def compare(reference: dict, candidate: dict) -> dict:
    if reference.get("fixed_simulations") is None:
        raise ValueError("Equivalence needs fixed simulations; an equal-time arena "
                         "does not reproduce itself even on one binary")
    settings = [key for key in SETTINGS if reference.get(key) != candidate.get(key)]
    if settings:
        raise ValueError(f"These runs are not the same experiment: {settings} differ")
    left, right = reference["games"], candidate["games"]
    if len(left) != len(right):
        return {"identical": False, "games": min(len(left), len(right)),
                "differences": [{"reason": "game count",
                                 "reference": len(left), "candidate": len(right)}]}
    differences = []
    for a, b in zip(sorted(left, key=lambda r: r["index"]),
                    sorted(right, key=lambda r: r["index"])):
        for key in COMPARED:
            if a.get(key) != b.get(key):
                differences.append({"index": a.get("index"), "field": key,
                                    "reference": a.get(key), "candidate": b.get(key)})
    return {"identical": not differences, "games": len(left),
            "compared_fields": list(COMPARED),
            "differences": differences[:20],
            "difference_count": len(differences)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        report = compare(json.loads(args.reference.read_text(encoding="utf-8")),
                         json.loads(args.candidate.read_text(encoding="utf-8")))
    except ValueError as error:
        # A traceback in an unattended chain is a worse signal than a sentence.
        print(f"cannot compare: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    json.dump(report, sys.stdout, indent=1)
    sys.stdout.write("\n")
    if not report["identical"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
