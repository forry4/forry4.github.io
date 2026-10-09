"""`.btn` is GEOMETRY ONLY. A button that names it and nothing else is unstyled.

`shared/theme.base-css.css` gives `.btn` padding, radius and font but no
background or colour — the paint comes from a variant (`btn-gold`,
`btn-outline`, `btn-ghost`, `btn-danger`, or a game's own). A bare
`className="btn"` renders the browser's default button face, a white chip on a
dark board. Nothing throws and the button works, so no render gate notices.

WHAT THIS DOES NOT CLAIM: that a variant is the RIGHT one — that is a judgement,
not a text scan.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Modifiers that, like `btn` itself, only change GEOMETRY. Carrying one of
#: these is not being dressed, so they do not satisfy the rule.
GEOMETRY_ONLY = {"btn", "btn-sm", "btn-full"}

BTN_CLASS = re.compile(r'className="([^"{]*\bbtn\b[^"]*)"')


def _jsx_files():
    """Every hand-written JSX in the repo. `webapp/` is build output plus the
    test harnesses, and `docs/` is the published bundle -- neither is source."""
    for d in ("games", "shared", "books", "notes", "wwsd"):
        yield from (ROOT / d).rglob("*.jsx")


def test_every_btn_names_a_variant_that_paints_it():
    bare = []
    for path in _jsx_files():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            for classes in BTN_CLASS.findall(line):
                names = set(classes.split())
                if not names & {"btn"}:
                    continue
                if not (names - GEOMETRY_ONLY):
                    bare.append(f"{path.relative_to(ROOT)}:{i}  className=\"{classes}\"")
    assert not bare, (
        "these buttons name `btn` and no painting variant, so they render as the "
        "browser's default button face on a dark board:\n  " + "\n  ".join(bare))


def test_the_scan_can_actually_see_a_bare_button():
    """Non-vacuity, and it is not paranoia: the assertion above passes just as
    happily when the regex matches nothing at all, which is what a renamed prop
    or a switch to `class=` would look like."""
    found = [c for p in _jsx_files() for c in BTN_CLASS.findall(p.read_text(encoding="utf-8"))]
    assert len(found) > 50, f"only {len(found)} btn usages seen — the scan is not reading the JSX"
    assert any("btn-ghost" in c for c in found), "no variant seen at all; the regex is wrong"
