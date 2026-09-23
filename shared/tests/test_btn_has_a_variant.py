"""`.btn` is GEOMETRY ONLY. A button that names it and nothing else is unstyled.

`shared/theme.base-css.css` gives `.btn` padding, radius, font, letter-spacing
and `border:none` -- and deliberately no background and no colour, because the
paint comes from a variant: `btn-gold`, `btn-outline`, `btn-ghost`, `btn-danger`,
or a game's own (`dis-gobtn`, `dis-kontrabtn`). That split is fine right up until
someone writes `className="btn"` on its own, at which point the browser paints
its DEFAULT button face -- `rgba(239,239,239,.3)` on `rgba(16,16,16,.3)`,
measured -- which on any of this repo's dark boards is a white chip with grey
text sitting in the middle of the theme.

IT FAILS SILENTLY, like every other bug this directory guards. Nothing throws,
nothing logs, the button works perfectly, and the class name reads as if it were
finished. Dissonance shipped NINE of them -- Bid, Start, Swap, Look, Next round,
Back to lobby among them -- and was the only file in the repo that did; every
other game names a variant on every button. It survived `smoke`, `screens` and
the whole Python suite, because all three ask whether a thing renders and none
asks what colour it came out.

Read as TEXT, like `test_lobby_kit.py` and `test_css_tokens.py` next door: a
button with no variant is a static fact about the source. `screens.mjs` covers
what a board LOOKS like; only this covers whether a button was ever dressed.

WHAT THIS DOES NOT CLAIM: that a variant is the RIGHT one. `btn btn-gold` on a
green board passes here and is still the wrong colour -- that is a judgement, and
judgements do not belong in a text scan.
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
