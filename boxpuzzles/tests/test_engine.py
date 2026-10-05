"""Box Puzzles rules and bank.

THE RULES ARE HELD TO THE REFERENCE, not to a reading of them: fixtures/parity.json
is chandler.io's simulator answering for itself (tools/gen_parity_fixtures.mjs drives
its WASM). engine.js is held to the same file by the boxPuzzles block of
webapp/test/screens.mjs, so the two engines cannot drift apart while both stay green.
"""
import json
import pathlib

import pytest

from boxpuzzles.engine import COLORS, CORNERS, corners_match, press, replay, solve

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
FIX = json.loads((HERE / "fixtures" / "parity.json").read_text(encoding="utf-8"))
BANK = json.loads((PKG / "puzzles.json").read_text(encoding="utf-8"))
MINIMUMS = json.loads((PKG / "minimums.json").read_text(encoding="utf-8"))
BY_ID = {p["id"]: p for p in BANK}


def _board(s: str) -> tuple:
    return tuple(s[i:i + 2] for i in range(0, 18, 2))


def test_every_single_press_matches_the_reference():
    bad = [(b, i, a, "".join(press(_board(b), i)))
           for b, i, a in FIX["presses"] if "".join(press(_board(b), i)) != a]
    assert not bad, f"{len(bad)} of {len(FIX['presses'])} presses differ, e.g. {bad[:3]}"


def test_the_fixtures_cover_every_pressed_and_centre_colour_pair():
    """The first fuzz of these rules was vacuous for half the colours (a weak RNG kept
    five colours out of the centre), so the blue quirks went untested. Hold the
    fixtures to full coverage: a regenerated file that loses a pair fails here."""
    pairs = {(_board(b)[i], _board(b)[4]) for b, i, _ in FIX["presses"]}
    assert pairs == {(p, c) for p in COLORS for c in COLORS}


def test_the_blue_quirks_are_in_the_fixtures_and_hold():
    """Blue copying white toggles BLUE<->gray, and blue copying red turns black BLUE —
    four boxes cannot be opened without them. Named here so a 'simplification' of the
    white or red rule fails on a sentence rather than on a hash of boards."""
    assert press(("WH", "WH", "WH", "YE", "WH", "BK", "BU", "BU", "BU"), 8) == \
        ("WH", "WH", "WH", "YE", "WH", "BK", "BU", "GY", "GY")
    assert press(("BK", "BK", "BU", "BK", "RD", "GY", "BK", "GY", "BU"), 8) == \
        ("BU", "BU", "BU", "BU", "RD", "GY", "BU", "GY", "BU")
    quirky = [(b, i) for b, i, _ in FIX["presses"]
              if _board(b)[i] == "BU" and _board(b)[4] in ("WH", "RD")]
    assert len(quirky) >= 30


def test_whole_sequences_match_the_reference():
    """Tile presses along real boxes, with the reference's own resets (a wrong corner
    button) applied, so the engine is checked on reachable boards, not only random ones."""
    opened = 0
    for seq in FIX["sequences"]:
        start = tuple(BY_ID[seq["id"]]["tiles"])
        t = start
        for n, (mv, code, after, _lit) in enumerate(seq["steps"]):
            if mv[0] == "t":
                t = press(t, int(mv[1:]))
            elif code == 1:
                t = start
            assert "".join(t) == after, f"{seq['id']} step {n} ({mv})"
            if code == 2:
                opened += 1
                assert corners_match(t, BY_ID[seq["id"]]["target"])
    assert opened == len(BANK), "every box should have a recorded solve that opens it"


def test_the_bank_is_the_71_boxes_with_nothing_but_the_board():
    assert len(BANK) == 71
    assert len({p["id"] for p in BANK}) == 71
    for p in BANK:
        assert set(p) == {"id", "tiles", "target"}, "no names, no minimums in the shipped bank"
        assert len(p["tiles"]) == 9 and len(p["target"]) == len(CORNERS)
        assert set(p["tiles"]) | set(p["target"]) <= set(COLORS)
        assert p["id"] == "".join(p["tiles"]) + "-" + "".join(p["target"])


def test_minimums_cover_the_bank_and_rise_with_the_numbering():
    assert list(MINIMUMS) == [p["id"] for p in BANK]
    mins = list(MINIMUMS.values())
    assert mins == sorted(mins), "boxes are numbered easiest first"


@pytest.mark.parametrize("idx", range(71))
def test_each_minimum_is_the_true_shortest_solve(idx):
    p = BANK[idx]
    line = solve(p["tiles"], p["target"])
    assert line is not None
    assert len(line) == MINIMUMS[p["id"]]
    assert corners_match(replay(p["tiles"], line), p["target"])


def test_replay_refuses_what_is_not_a_tile():
    for bad in (9, -1, "3", 2.0, True, None):
        with pytest.raises(ValueError):
            replay(BANK[0]["tiles"], [bad])


def test_the_browser_never_imports_the_minimums():
    """Only the player who reached a box's minimum is told so; shipping minimums.json
    in the bundle would tell everyone."""
    for f in (f for f in PKG.iterdir() if f.suffix in (".js", ".jsx")):
        assert "minimums" not in f.read_text(encoding="utf-8"), f.name
