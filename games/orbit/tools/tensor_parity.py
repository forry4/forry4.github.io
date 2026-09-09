"""Compare Python/Rust numeric adapters on all-board random observations.

This checks semantic-to-tensor parity only, NOT native observation extraction
or model inference. Vocabulary fitting here is a parity fixture, not training.
"""
import argparse
import itertools
import json
from pathlib import Path
import random
import subprocess

from .. import engine
from ..ai.features import encode_features
from ..ai.history import Session
from ..ai.state import observation
from ..ai.tensors import TensorEncoder, Vocabulary, native_request
from ..cards import FACTIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path(__file__).resolve().parents[3] /
                        "rust-cores/orbit-core/target/release/tensor_bridge.exe")
    parser.add_argument("--seed", type=int, default=9200)
    args = parser.parse_args()
    examples, requests, completed = [], [], 0
    for index, sides in enumerate(itertools.product((1, 2), repeat=3)):
        game = engine.new_game(["A", "B"], seed=args.seed + index,
                               configuration=dict(zip(FACTIONS, sides)))
        rng = random.Random(args.seed + index)
        for _ in range(1600):
            for pid in game["order"]:
                obs = observation(game, pid)
                examples.append(encode_features(obs))
                requests.append({"observation":obs})
            if game["phase"] == "over":
                completed += 1
                break
            pid = next(p for p in game["order"] if engine.legal_moves(game, p))
            ok, error = engine.apply_move(game, pid, rng.choice(engine.legal_moves(game, pid)))
            if not ok:
                raise AssertionError(error)
    if completed != 8:
        raise AssertionError("Censored parity games")
    session = Session(engine.new_game(["A", "B"], seed=args.seed))
    for _ in range(16):
        for pid in session.game["order"]:
            inputs = session.policy_input(pid)
            examples.append(encode_features(inputs["observation"], inputs["history"]))
            requests.append({"observation":inputs["observation"], "history":inputs["history"]})
        pid = next(p for p in session.game["order"] if engine.legal_moves(session.game,p))
        assert session.step(pid,engine.legal_moves(session.game,pid)[0])[0]
    vocabulary = Vocabulary.fit(examples)
    encoder = TensorEncoder(vocabulary)
    process = subprocess.Popen([str(args.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8")
    try:
        for index, (tokens, request) in enumerate(zip(examples,requests)):
            process.stdin.write(json.dumps({"vocabulary":vocabulary.as_dict(), **request}) + "\n")
            process.stdin.flush()
            actual = json.loads(process.stdout.readline())
            expected = encoder.encode(tokens)
            if actual != expected:
                raise AssertionError(f"Tensor parity mismatch at observation {index}: {str(actual)[:200]}")
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait(timeout=10)
    if process.returncode:
        raise AssertionError(f"Native bridge exited {process.returncode}")
    print(json.dumps({"games": completed, "observations": len(examples),
                      "paths": len(vocabulary.paths), "categories": len(vocabulary.categories),
                      "parity": "exact", "scope": "native observation-to-tensor; includes 32 history views"}))


if __name__ == "__main__":
    main()
