"""Compare native search builds on identical fixed-simulation positions."""
import argparse
import json
from pathlib import Path
import random

import torch

from .. import engine
from ..ai.attention import load_checkpoint, export_model
from ..ai.native_value import NativeValueGuide
from ..ai.state import native_state
from ..ai.selfplay import board_configurations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--simulations", type=int, default=64)
    args = parser.parse_args()
    torch.set_num_threads(1)
    model, _, _, _ = load_checkpoint(args.checkpoint)
    artifact = export_model(model)
    results = []
    with NativeValueGuide(artifact, binary=args.before.resolve()) as before, \
            NativeValueGuide(artifact, binary=args.after.resolve()) as after:
        for index, board in enumerate(board_configurations()):
            game = engine.new_game(["A", "B"], seed=96700 + index, configuration=board)
            rng = random.Random(96700 + index)
            for decision in range(32):
                if game["phase"] == "over":
                    break
                pid = next(p for p in game["order"] if engine.legal_moves(game, p))
                if decision in (8, 24):
                    request = {"search_state": native_state(game), "seat": game["order"].index(pid),
                               "seed": 98100 + index, "simulations": args.simulations,
                               "max_depth": 32, "budget_ms": 60000}
                    # Alternate order to reduce systematic warmup/thermal bias.
                    if index % 2:
                        b = after._call(request); a = before._call(request)
                    else:
                        a = before._call(request); b = after._call(request)
                    for key in ("move", "stats", "simulations", "nodes"):
                        if a[key] != b[key]:
                            raise AssertionError(f"Search changed: board {index}, decision {decision}, {key}")
                    results.append({"board": index, "decision": decision,
                                    "before_ms": a["elapsed_ms"], "after_ms": b["elapsed_ms"],
                                    "before_evaluations": a["evaluations"], "after_evaluations": b["evaluations"],
                                    "cache_hits": b.get("value_cache_hits", 0)})
                ok, error = engine.apply_move(game, pid, rng.choice(engine.legal_moves(game, pid)))
                if not ok:
                    raise AssertionError(error)
    report = {"positions": results, "fixed_simulations": args.simulations,
              "statistics_identical": True,
              "cache_hits": sum(r["cache_hits"] for r in results),
              "speedup": sum(r["before_ms"] for r in results) / sum(r["after_ms"] for r in results),
              "scope": "native fixed-simulation equivalence and timing; not browser strength"}
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "positions"}))


if __name__ == "__main__":
    main()
