"""Hold the native policy head to the PyTorch head it was ported from.

The policy head is the lever this campaign never had: Orbit's PUCT prior is the
frozen hand-written `action_score`, which the 2026-09-11 audit measured deciding
50.5% of moves outright, so the network could only ever move the leaf. A learned
prior only helps if the NATIVE forward agrees with the trained one -- the browser
and every offline tool run the Rust build, exactly as they did when a silently
truncated leaf produced an entire campaign of numbers.

What makes this worth writing rather than assuming: the head is a GATHER. Each
logit is read out of the row belonging to that move's entity, and entity ids are
handed out in token order by two independent implementations. A mismatch does
not crash and does not look wrong -- it silently scores move 3 with move 5's
logit, and then trains and serves a prior that is merely shuffled.

`--fresh` checks the port before any policy model exists, which is when it is
cheapest to be wrong. A random head is as good a port check as a trained one and
has no chance of being accidentally degenerate.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

from ..ai.search import _actor
from ..ai.selfplay import board_configurations
from ..ai.state import observation
from .. import engine


REPO_ROOT = Path(__file__).resolve().parents[3]
# The PORTABLE build, like `leaf_parity`: this checks the arithmetic that ships
# to the browser, not a `-C target-cpu=native --features chunked-dot` binary
# whose whole purpose is to reassociate float reductions.
DEFAULT_BINARY = REPO_ROOT / "rust-cores" / "orbit-core" / "target" / "release" / "attention_bridge.exe"
# The value head's own parity harness uses 1e-4 on the logit, and a policy logit
# is the same depth of float32 forward through the same blocks.
TOLERANCE = 1e-4


def positions(games, seed):
    """The deterministic walk that BOTH the vocabulary fit and the comparison use.

    Fitting on exactly the positions that will be compared is what makes
    `--fresh` reliable. A vocabulary fitted on a shorter or different line hits
    an unseen category part-way through the walk, and that is a harness failure
    wearing a parity failure's costume.
    """

    boards = board_configurations()
    for index in range(games):
        board = boards[index % len(boards)]
        game = engine.new_game(["p%da" % index, "p%db" % index], seed=seed + index,
                               configuration=board)
        for _ in range(1600):
            if engine.is_over(game):
                break
            pid = _actor(game)
            if pid is None:
                break
            moves = engine.legal_moves(game, pid)
            if not moves:
                break
            yield index, game["turn_number"], observation(game, pid)
            engine.apply_move(game, pid, moves[0])


def dataset_positions(pool):
    """Observations from a generated pool, for checking a TRAINED checkpoint.

    A checkpoint's vocabulary covers the data it was fitted on and nothing else,
    so walking freshly generated games raises on the first unseen category --
    which is a coverage gap, not a parity failure. Mirrors
    `attention_parity --development`.
    """

    from .value_campaign import load_manifest, read_game

    manifest = load_manifest(pool)
    for item in manifest["games"][:32]:
        for step in read_game(pool, item)["steps"]:
            observation = step["observation"]
            if len(observation.get("legal_moves") or []) > 1:
                yield pool.name, observation.get("turn", 0), observation


def softmax(values):
    top = max(values)
    weights = [math.exp(value - top) for value in values]
    total = sum(weights)
    return [weight / total for weight in weights]


def walk(model, source, binary):
    import torch

    from ..ai.attention import export_model
    from ..ai.features import encode_features

    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8", bufsize=1)

    def call(payload):
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        reply = json.loads(process.stdout.readline())
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply

    compared = 0
    worst_logit = 0.0
    worst_prior = 0.0
    worst_at = None
    widest = 0
    try:
        if not call({"model": export_model(model)})["loaded"]:
            raise RuntimeError("bridge refused the model")
        model.eval()
        with torch.no_grad():
            for index, turn, obs in source:
                value, logits = model(model.tensor_batch([encode_features(obs)]))
                width = len(obs["legal_moves"])
                widest = max(widest, width)
                expected = logits[0, :width].tolist()
                if not all(math.isfinite(x) for x in expected):
                    raise RuntimeError("A legal move was masked out of the torch head")
                native = call({"observation": obs, "policy": True})
                actual = native["policy"]
                if len(actual) != width:
                    raise RuntimeError("native returned %d logits for %d legal moves"
                                       % (len(actual), width))
                if abs(float(value[0]) - native["logit"]) > TOLERANCE:
                    raise RuntimeError("Value head disagrees; the policy result is moot")
                delta = max(abs(a - b) for a, b in zip(actual, expected))
                if delta > worst_logit:
                    worst_logit = delta
                    worst_at = {"game": index, "turn": turn,
                                "moves": width, "python": expected, "rust": actual}
                # The PRIOR is checked as well as the logits. A constant shift
                # leaves the softmax identical and is not a defect; a
                # PERMUTATION leaves neither identical, so comparing the
                # distribution is what actually catches a bad gather.
                worst_prior = max(worst_prior, max(
                    abs(a - b) for a, b in zip(softmax(actual), softmax(expected))))
                compared += 1
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait(timeout=30)
    return {"positions": compared, "widest_move_list": widest,
            "max_abs_logit_delta": worst_logit, "max_abs_prior_delta": worst_prior,
            "worst": worst_at, "tolerance": TOLERANCE,
            "passed": compared > 0 and worst_logit <= TOLERANCE}


def fresh_model(games, seed):
    """An untrained policy head, fitted to exactly the positions it will be checked on.

    Parity is a property of the PORT, not of the weights, so this needs no
    trained artifact and can therefore run before one exists.
    """

    import torch

    from ..ai.attention import AttentionValue, ModelConfig
    from ..ai.features import encode_features
    from ..ai.tensors import Vocabulary

    torch.manual_seed(seed)
    fitting = [encode_features(obs) for _, _, obs in positions(games, seed)]
    if not fitting:
        raise ValueError("No positions to fit a vocabulary on")
    return AttentionValue(Vocabulary.fit(fitting), ModelConfig(policy_head=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("checkpoint", type=Path, nargs="?",
                        help="A policy-head checkpoint; omit when using --fresh")
    parser.add_argument("--fresh", action="store_true",
                        help="Build an untrained policy head instead of loading one")
    parser.add_argument("--games", type=int, default=4)
    parser.add_argument("--development", type=Path,
                        help="Walk a generated pool instead of fresh games. Give the pool "
                             "the model's vocabulary was FITTED on (the training pool): a "
                             "vocabulary is training-only by design, so a development pool "
                             "can legitimately contain categories it has never seen")
    parser.add_argument("--seed", type=int, default=9300)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    args = parser.parse_args()
    if args.games < 1:
        parser.error("--games must be positive")
    if bool(args.checkpoint) == bool(args.fresh):
        parser.error("give a checkpoint or --fresh, not both")

    import torch

    torch.set_num_threads(1)
    if args.fresh:
        model = fresh_model(args.games, args.seed)
    else:
        from ..ai.attention import load_checkpoint
        model, _, _, _ = load_checkpoint(args.checkpoint)
        if model.policy is None:
            raise SystemExit("That checkpoint has no policy head")
    source = (dataset_positions(args.development) if args.development
              else positions(args.games, args.seed))
    try:
        report = walk(model, source, args.binary)
    except ValueError as error:
        # A checkpoint's vocabulary covers only the data it was fitted on.
        raise SystemExit(
            f"{error}\n\nIf that names an unseen token, the checkpoint's vocabulary "
            "does not cover these positions, which is a coverage gap rather than a "
            "parity failure. Pass --development pointing at the pool the model was "
            "TRAINED on, or use --fresh, which fits on exactly what it walks.") from None
    json.dump(report, sys.stdout, indent=1)
    sys.stdout.write("\n")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
