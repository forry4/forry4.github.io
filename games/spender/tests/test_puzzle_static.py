"""The static puzzle file the frontend loads must be the bank, exactly.

Puzzle mode reads `webapp/public/data/puzzles.json` (see
games/spender/puzzle/export_static.py), so a puzzle added or edited under
`puzzle/puzzles/` reaches players only when that file is regenerated. Forgetting
compiles, deploys and plays the OLD bank without a sound — this is the only thing
that notices.
"""
import json

from games.spender.puzzle import export_static
from games.spender.puzzle.serve import list_puzzles


def test_the_committed_file_matches_the_bank():
    assert export_static.OUT.exists(), "run: python -m games.spender.puzzle.export_static"
    committed = export_static.OUT.read_text(encoding="utf-8")
    assert committed == export_static.render(), (
        "webapp/public/data/puzzles.json is stale — run: python -m games.spender.puzzle.export_static")


def test_every_listed_puzzle_is_in_the_bank_with_its_steps():
    data = json.loads(export_static.OUT.read_text(encoding="utf-8"))
    listing = data["puzzles"]
    assert listing == list_puzzles() and len(listing) > 50
    for meta in listing:
        puz = data["bank"][meta["id"]]
        assert puz["steps"] and puz["steps"][0]["snapshot"], meta["id"]
