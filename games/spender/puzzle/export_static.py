"""Write the puzzle bank as ONE static file the frontend fetches from Pages.

    python -m games.spender.puzzle.export_static      (from the repo root)

WHY STATIC. Puzzle mode needs no engine at play time — every puzzle is a scripted
line with a snapshot per step and the one correct move (see serve.py), so the
answer is a comparison, not a search. Serving it from Render meant the mode
needed a warm backend, and could not work offline at all: the service worker
caches the site's own files, never the backend's replies. As a file beside the
bundle it loads from the CDN, and the offline hub's download keeps it.

THE LISTING IS serve.py's OWN. `list_puzzles()` derives difficulty, answer type
and hero-move count; this writes exactly what it returns rather than a second
copy of those rules, so the two cannot drift. `test_puzzle_static.py` fails when
the committed file no longer matches the bank — re-run this after changing any
puzzle.
"""
from __future__ import annotations

import json
from pathlib import Path

from games.spender.puzzle.serve import get_puzzle, list_puzzles

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "webapp" / "public" / "data" / "puzzles.json"


def payload() -> dict:
    listing = list_puzzles()
    return {"puzzles": listing, "bank": {p["id"]: get_puzzle(p["id"]) for p in listing}}


def render() -> str:
    # Compact and key-sorted, so the committed file is a pure function of the bank.
    return json.dumps(payload(), separators=(",", ":"), sort_keys=True)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size / 1e6:.2f} MB, {len(payload()['puzzles'])} puzzles)")


if __name__ == "__main__":
    main()
