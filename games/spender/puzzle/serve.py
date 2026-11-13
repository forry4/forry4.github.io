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
import threading

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


# LOADED ON FIRST REQUEST, not at import: 83 files / ~5MB of JSON that only the
# puzzle routes read, parsed on every Render cold start before anything could be
# served. `_bank()` is the one way in; the lock makes two first requests (the
# routes run on FastAPI's thread pool) parse it once. The bank is committed data,
# so loading later serves exactly what loading at boot did.
_BANK: dict | None = None
_BANK_LOCK = threading.Lock()


def _bank() -> dict:
    global _BANK
    if _BANK is None:
        with _BANK_LOCK:
            if _BANK is None:
                _BANK = _load_bank()
    return _BANK


def _difficulty(k: int) -> str:
    """A coarse difficulty label from the horizon K (turns-to-win)."""
    return "Easy" if k <= 2 else "Tricky" if k == 3 else "Hard"


def _answer_type(puz: dict) -> str:
    """The hero's first move type coarsened to buy | reserve | take — lets the frontend
    weight the one-at-a-time draw toward a target answer-type mix without fetching each file."""
    t = ((puz.get("steps") or [{}])[0].get("move") or {}).get("type", "")
    return "take" if "take" in t else ("reserve" if t == "reserve" else "buy")


def _meta(puz: dict) -> dict:
    """The lightweight listing entry (no embedded snapshots)."""
    m = puz.get("meta", {})
    return {
        "id": puz["id"],
        "title": m.get("title"),   # null -> the frontend names it "Puzzle N"
        "kind": puz.get("kind", "win"),   # "win" | "advantage" (single best move)
        "answer_type": _answer_type(puz),   # "buy" | "reserve" | "take" (advantage puzzles)
        "win_points": puz["win_points"],
        "K": puz["K"],
        "n_hero_moves": sum(1 for st in puz["steps"] if st.get("is_hero")),
        "difficulty": m.get("difficulty") or _difficulty(puz.get("K", 2)),
    }


def list_puzzles() -> list:
    bank = _bank()
    return [_meta(bank[pid]) for pid in sorted(bank)]


def get_puzzle(pid: str):
    return _bank().get(pid)


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
