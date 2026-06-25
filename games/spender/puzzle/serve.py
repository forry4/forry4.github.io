"""Serving for Puzzle mode — static, zero AI compute at runtime.

The bank is committed JSON under ``puzzles/``. Each puzzle is a fully-scripted
walkthrough with embedded per-step snapshots, so serving is trivial: list the bank,
return a puzzle file. No DB, no auth, no engine — public read-only content. (The
hard work lives entirely offline in the generator.)
"""
from __future__ import annotations

import glob
import json
import os

from fastapi import HTTPException

_DIR = os.path.join(os.path.dirname(__file__), "puzzles")


def _load_bank() -> dict:
    bank: dict = {}
    for path in sorted(glob.glob(os.path.join(_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                puz = json.load(f)
        except Exception:
            continue
        pid = puz.get("id") or os.path.splitext(os.path.basename(path))[0]
        puz["id"] = pid
        bank[pid] = puz
    return bank


_BANK = _load_bank()


def _difficulty(k: int) -> str:
    """A coarse difficulty label from the horizon K (turns-to-win)."""
    return "Easy" if k <= 2 else "Tricky" if k == 3 else "Hard"


def _meta(puz: dict) -> dict:
    """The lightweight listing entry (no embedded snapshots)."""
    m = puz.get("meta", {})
    return {
        "id": puz["id"],
        "title": m.get("title"),   # null -> the frontend names it "Puzzle N"
        "win_points": puz["win_points"],
        "K": puz["K"],
        "n_hero_moves": sum(1 for st in puz["steps"] if st.get("is_hero")),
        "difficulty": m.get("difficulty") or _difficulty(puz.get("K", 2)),
    }


def list_puzzles() -> list:
    return [_meta(_BANK[pid]) for pid in sorted(_BANK)]


def get_puzzle(pid: str):
    return _BANK.get(pid)


def setup_puzzles(app) -> None:
    """Wire the two read-only puzzle routes onto the composition-root app."""

    @app.get("/puzzles")
    def _list_puzzles():            # noqa: ANN202 - FastAPI handler
        return {"puzzles": list_puzzles()}

    @app.get("/puzzles/{pid}")
    def _get_puzzle(pid: str):      # noqa: ANN202 - FastAPI handler
        puz = get_puzzle(pid)
        if puz is None:
            raise HTTPException(status_code=404, detail="no such puzzle")
        return puz
