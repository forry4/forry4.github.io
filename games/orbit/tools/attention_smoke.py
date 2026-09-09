"""Bounded outcome-training/GPU timing smoke test, not a strength campaign.

Uses eight complete random games and four evenly spaced observations per seat
per game. This is explicitly an observation-only ablation: full history is not
fed to the model. No held-out accuracy or playing-strength claim is produced.
"""
import argparse
import itertools
import json
from pathlib import Path
import random
import time

import torch

from .. import engine
from ..ai.attention import AttentionValue, train_batch, save_checkpoint, load_checkpoint
from ..ai.features import encode_features
from ..ai.state import observation
from ..ai.tensors import Vocabulary
from ..cards import FACTIONS


def collect_examples(seed=9300):
    data, targets = [], []
    for index, sides in enumerate(itertools.product((1, 2), repeat=3)):
        game = engine.new_game(["A", "B"], seed=seed + index,
                               configuration=dict(zip(FACTIONS, sides)))
        rng = random.Random(seed + index)
        seats = [[], []]
        for _ in range(1600):
            if game["phase"] == "over":
                break
            pid = next(p for p in game["order"] if engine.legal_moves(game, p))
            seat = game["order"].index(pid)
            obs = observation(game, pid)
            seats[seat].append(obs)
            ok, error = engine.apply_move(game, pid, rng.choice(obs["legal_moves"]))
            if not ok:
                raise AssertionError(error)
        if game["phase"] != "over":
            raise AssertionError("Censored smoke game; no outcome labels generated")
        for seat, views in enumerate(seats):
            for n in range(4):
                obs = views[n * (len(views) - 1) // 3]
                data.append(encode_features(obs))
                targets.append(float(game["winner"] == game["order"][seat]))
    return data, targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=9300)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("steps must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    data, targets = collect_examples(args.seed)
    model = AttentionValue(Vocabulary.fit(data)).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0003)
    losses = []
    started = time.perf_counter()
    for step in range(args.steps):
        start = (step % 8) * 8
        indices = [start + n for n in (0, 3, 4, 7)]
        losses.append(train_batch(model, optimizer, [data[i] for i in indices],
                                  [targets[i] for i in indices]))
    if args.device == "cuda":
        torch.cuda.synchronize()
    training_seconds = time.perf_counter() - started
    checkpoint = args.output / "smoke.pt"
    save_checkpoint(checkpoint, model, optimizer, step=args.steps,
                    metadata={"seed": args.seed, "purpose": "smoke-only", "history": "omitted-ablation"})
    restored, _, _, _ = load_checkpoint(checkpoint, device=args.device)
    expected = model.predict(data[:4])
    actual = restored.predict(data[:4])
    if max(abs(a-b) for a, b in zip(expected, actual)) > 1e-7:
        raise AssertionError("Checkpoint prediction mismatch")
    model.eval()
    batch = model.tensor_batch([max(data, key=len)])
    with torch.no_grad():
        for _ in range(3):
            model(batch)
        if args.device == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        for _ in range(20):
            model(batch)
        if args.device == "cuda":
            torch.cuda.synchronize()
    report = {"purpose": "training plumbing, not strength evidence", "games": 8,
              "examples": len(data), "steps": args.steps, "seed": args.seed,
              "device": args.device, "history": "omitted-ablation",
              "parameters": sum(p.numel() for p in model.parameters()),
              "max_tokens": max(map(len, data)), "losses": losses,
              "training_seconds": training_seconds,
              "forward_ms": (time.perf_counter() - started) * 1000 / 20,
              "timing_scope": "warm PyTorch forward only; excludes encoding; not WASM",
              "checkpoint_roundtrip": "passed"}
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
