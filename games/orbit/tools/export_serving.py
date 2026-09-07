"""Generate Orbit's versioned browser serving asset.

This is intentionally separate from the native mechanical export.  It writes
the compatibility envelope and card vocabulary consumed by
``webapp/public/wasm/orbit-worker.js``; a promoted model can replace the same
asset only after the Phase 4 gate has accepted matching metadata.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..ai.serving import write_model_asset


DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "webapp/public/wasm/orbit-model.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = write_model_asset(args.out)
    print(f"Orbit serving asset: {args.out} (rules={payload['rules']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
