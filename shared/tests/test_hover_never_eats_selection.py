"""A `:hover` fill must never out-specify the SELECTED state it sits next to.

`:not()` contributes its argument's specificity, so
`.dis-denoms button:hover:not(:disabled)` at (0,3,1) beats
`.dis-denoms button.on` at (0,2,1): the selected button repaints grey under
`.on`'s dark text. On a phone `:hover` latches to the last element tapped, so
the selection stays unreadable for the rest of the phase.

WHAT IT CHECKS: within one stylesheet, any `:hover` rule that sets `background`
and could also match an element carrying `.on` must exclude it with
`:not(.on)`. Static on purpose — the browser gate can only hover the families
on screen in the phase it reaches, and this covers all of them at once.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The selected-state class this repo uses for toggles/pickers.
SELECTED = ".on"


def _sheets():
    out = sorted((REPO / "games").rglob("*.css")) + sorted((REPO / "shared").rglob("*.css"))
    assert out, "no stylesheets found — this guard has rotted"
    return out


def _rules(css: str):
    """(selector, body) per rule. Comments are stripped FIRST — several sheets
    discuss `:hover` in prose, and this file does too."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _base(part: str) -> str:
    """The selector with its pseudo-classes stripped — what it matches BEFORE
    hovering. `.dis-denoms button:hover:not(:disabled)` -> `.dis-denoms button`."""
    return re.sub(r":(?:hover|not\([^()]*\)|active|focus(?:-visible)?)", "", part).strip()


def _offenders(css: str):
    """A hover rule is only an offender if the SAME sheet paints a background on
    the SELECTED version of the very same elements. Pairing on the base selector
    is what makes this precise: `.coc-btn.gold:hover` looks identical in shape but
    has no `.coc-btn.gold.on` anywhere, so demanding `:not(.on)` there would be a
    test inventing work. Only a real (hover, selected) pair on one base can
    conflict, and then the hover ALWAYS wins — it has strictly more
    pseudo-classes, hence strictly higher specificity."""
    painted_on = set()          # base selectors that have a `.on` background rule
    hovers = []                 # (base, full selector) for hover backgrounds
    for selector, body in _rules(css):
        if "background" not in body:
            continue
        for part in (p.strip() for p in selector.split(",")):
            if ":hover" in part:
                if SELECTED not in part:        # already excluded => safe
                    hovers.append((_base(part), part))
            elif part.endswith(SELECTED):
                painted_on.add(part[: -len(SELECTED)].strip())
    return [full for base, full in hovers if base in painted_on]


def test_no_hover_fill_can_override_a_selected_button():
    found = {}
    for sheet in _sheets():
        offenders = _offenders(sheet.read_text(encoding="utf-8"))
        if offenders:
            found[sheet.relative_to(REPO).as_posix()] = offenders
    assert not found, (
        "a :hover background can repaint a SELECTED button here:\n"
        + "\n".join(f"  {s}\n    " + "\n    ".join(sel for sel in sels) for s, sels in found.items())
        + "\n\nAdd `:not(.on)` to the hover selector. `:hover` latches to the last "
          "tapped element on touch, so this is a permanent wrong colour on a phone, "
          "not a transient one."
    )


def test_the_guard_actually_fires():
    """Anti-vacuity — the whole file passes just as happily if `_rules` stops
    parsing or the offender test inverts, and a green tick over nothing is the
    failure mode this repo keeps paying for."""
    broken = ".x button:hover:not(:disabled) { background: #fff; }\n.x button.on { background: red; }"
    assert _offenders(broken) == [".x button:hover:not(:disabled)"]

    fixed = ".x button:hover:not(:disabled):not(.on) { background: #fff; }\n.x button.on { background: red; }"
    assert _offenders(fixed) == []

    # A hover rule that paints nothing is not this test's business.
    assert _offenders(".x button:hover { transform: scale(1.1); }") == []
    # ...and prose about :hover must not register as a rule.
    assert _offenders("/* .x button:hover { background: #fff } */ .y { color: red }") == []
