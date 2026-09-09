"""Float inference parity on a trained smoke checkpoint and its real positions."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess

import torch

from ..ai.attention import export_model, load_checkpoint
from ..ai.tensors import TensorEncoder
from .attention_smoke import collect_examples


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkpoint", type=Path)
    p.add_argument("--development", type=Path, help="Validate complete observation-to-value inference on a development pool")
    p.add_argument("--output", type=Path, help="Separate report for an experimental binary")
    p.add_argument("--binary", type=Path, default=Path(__file__).resolve().parents[3] /
                   "rust-cores/orbit-core/target/release/attention_bridge.exe")
    args = p.parse_args()
    torch.set_num_threads(1)
    model, _, _, metadata = load_checkpoint(args.checkpoint)
    model.eval()
    observations = None
    if args.development:
        from .value_campaign import load_manifest, read_game
        from ..ai.features import encode_features
        manifest = load_manifest(args.development)
        if not manifest["namespace"].startswith("development-"):
            raise ValueError("Expected development pool")
        observations = [step["observation"] for item in manifest["games"][:32]
                        for step in read_game(args.development, item)["steps"]]
        data = [encode_features(obs) for obs in observations]
    else:
        data, _ = collect_examples(metadata["seed"])
    encoder = TensorEncoder(model.vocabulary)
    process = subprocess.Popen([str(args.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8")
    def call(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()
        result = json.loads(process.stdout.readline())
        if "error" in result:
            raise AssertionError(result["error"])
        return result
    errors, times = [], []
    try:
        assert call({"model": export_model(model)})["loaded"]
        with torch.no_grad():
            for index, tokens in enumerate(data):
                expected = float(model(model.tensor_batch([tokens]))[0])
                actual = call({"observation": observations[index]} if observations is not None
                              else {"rows": encoder.encode(tokens)})
                error = abs(actual["logit"] - expected)
                if error > 1e-4:
                    raise AssertionError(f"Float inference parity: {error} > 1e-4")
                errors.append(error)
                times.append(actual["elapsed_ms"])
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait(timeout=10)
    report = {"positions": len(data), "max_logit_error": max(errors),
              "native_median_ms": statistics.median(times), "native_max_ms": max(times),
              "scope": ("observation extraction, encoding and float forward; IPC excluded; not WASM"
                        if observations is not None else
                        "float forward, semantic extraction/encoding and IPC excluded; not WASM")}
    (args.output or args.checkpoint.parent / "native-parity.json").write_text(json.dumps(report,indent=2), encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
