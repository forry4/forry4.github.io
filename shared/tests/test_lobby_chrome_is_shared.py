"""A game may theme its ROWS. It may not re-skin the kit's CHROME.

CHROME is what the site owns and keeps identical in every lobby: the header bar,
the identity band, the section headers, the row actions, the create row, the
phone tab bar and the two shared modals' panels. A game's MATERIAL — the card
ground, the page ground and the words — is deliberately not protected.

Only APPEARANCE properties are refused; a game may still position, layer, space
or size these elements. Using the kit's class names and then repainting them
from a game sheet passes `test_lobby_kit.py`, which is why this file exists
(Black Castle did it with 22 rules; see the root CLAUDE.md).

WHAT THIS CANNOT SEE: game sheets are concatenated after the shared one, so a
rule that never names a kit class can still out-specify one (e.g.
`.blackcastle button{font-family:inherit}` at (0,1,1) against `.lby-cta` at
(0,1,0)). Only a rendered page sees that, which is `lobbyChrome` in
`webapp/test/screens.mjs`.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

# The furniture the site owns. Grouped the way a reader thinks about the page,
# because the value of this list is that someone can check it against the screen.
CHROME = (
    # the top bar
    "lby-header", "lby-title", "lby-back", "lby-headbtn", "lby-head-name",
    "lby-head-left", "lby-head-right", "lby-ident", "lby-ident-kind",
    # the identity band
    "lby-hero", "lby-hero-id", "lby-hero-emblem", "lby-hero-name",
    "lby-hero-seats", "lby-hero-text", "lby-hero-actions",
    # the column headers
    "lby-section-hd", "lby-section-title", "lby-section-note",
    # the row actions and the create row
    "lby-act", "lby-act-primary", "lby-act-secondary", "lby-act-danger",
    "lby-cta", "lby-join-btn", "lby-rules", "lby-refresh", "lby-extra",
    "lby-create-row", "lby-code",
    # the phone tab bar
    "lby-tabs", "lby-tab",
    # the waiting room — the screen between the lobby and the board, and the one
    # the whole invite flow happens on. Nine hand-built copies of it is what
    # `WaitingRoom` replaced; a game repainting these is the same thing again,
    # one stylesheet further down. `.wr-extra` is deliberately absent: it is the
    # children slot, and what a game puts in it is the game's.
    "wr-panel", "wr-id", "wr-emblem", "wr-name", "wr-kicker",
    "wr-invite", "wr-invite-btn", "wr-invite-label", "wr-invite-url", "wr-invite-hint",
    "wr-code-row", "wr-code-lbl", "wr-code-btn",
    "wr-count", "wr-seats", "wr-seat", "wr-start", "wr-status",
    # the two shared modals
    "cm-panel", "cm-title", "cm-create", "cm-seg", "cm-seg-btn", "cm-summary",
    "cm-label", "cm-row", "cm-x",
    "rl-panel", "rl-head", "rl-title", "rl-title-ic", "rl-x", "rl-foot", "rl-done",
)

# Repaint or re-letter. Anything not here — position, z-index, display, flex,
# margin, width, transition, opacity — is a game's own business.
REFUSED = re.compile(
    r"^(color|background|font|letter-spacing|text-transform|text-shadow"
    r"|box-shadow|border|min-height|padding)(-[a-z-]+)?$")

# SELF-POLICING, like `ACCENT_AA_EXEMPT` in shared/accents.js and the `no_history`
# row in test_lobby_kit.py: a row that stops being needed fails as STALE, so it
# gets deleted instead of sitting here excusing something that no longer exists.
# Keyed on the exact selector, so widening the selector re-opens the question.
SANCTIONED = {
    ".or-game .lby-header": (
        "Orbit's IN-GAME header (.or-game, not the lobby): it floats over the "
        "board as a translucent sticky bar, which is a board decision. The lobby "
        "header in the same sheet is untouched."),
}


def _rules() -> list[tuple[pathlib.Path, str, set[str]]]:
    """(sheet, selector, declared properties) for every rule in every game sheet.

    Comments are stripped FIRST. These sheets carry long prose explaining which
    kit rules not to fight, and a scan that reads those explanations as code
    makes the explanation unwritable — the same trap `test_no_conditional_skips`
    hit with a regex and fixed by parsing.
    """
    out = []
    for css in sorted((ROOT / "games").glob("*/*.css")):
        text = re.sub(r"/\*.*?\*/", "", css.read_text(encoding="utf-8"), flags=re.S)
        for m in re.finditer(r"([^{}]*)\{([^}]*)\}", text):
            sel = " ".join(m.group(1).split())
            props = {p.strip() for p in re.findall(r"(?:^|;)\s*([a-z-]+)\s*:", m.group(2))}
            out.append((css, sel, props))
    assert len(out) > 500, f"only {len(out)} rules parsed — this is reading the wrong files"
    return out


def _chrome_hits(sel: str) -> list[str]:
    # `(?![\w-])` and not `\b`: a hyphen is a non-word character, so `\b` after
    # "lby-hero" matches inside ".lby-hero-name" and every longer class would be
    # reported as its own prefix. Harmless while both names are in CHROME and
    # quietly wrong the moment one of them is not.
    return [c for c in CHROME if re.search(r"\.%s(?![\w-])" % re.escape(c), sel)]


def test_no_game_repaints_the_shared_lobby_chrome():
    problems: dict[str, set[str]] = {}
    for css, sel, props in _rules():
        if not _chrome_hits(sel) or sel in SANCTIONED:
            continue
        bad = {p for p in props if REFUSED.match(p)}
        if bad:
            problems[f"{css.parent.name}/{css.name}  {sel}"] = bad
    assert not problems, (
        "these game sheets repaint chrome the shared kit owns, so that game's "
        "lobby stops looking like the other eight. Theme the rows, the empty "
        "states and the create modal's CONTENT instead — or, if the kit itself "
        "is wrong, fix it in shared/ where every game gets it: "
        + " | ".join(f"{k} -> {sorted(v)}" for k, v in sorted(problems.items())))


def test_every_sanctioned_override_is_still_there():
    """A whitelist nothing checks is a hole. If Orbit's board header stops
    restyling `.lby-header`, this row must go rather than stand as permission
    for a rule that no longer exists."""
    live = {sel for _, sel, props in _rules()
            if _chrome_hits(sel) and any(REFUSED.match(p) for p in props)}
    stale = sorted(set(SANCTIONED) - live)
    assert not stale, (
        "these SANCTIONED rows no longer describe anything in the tree — delete "
        f"them: {stale}")


def test_the_scan_can_actually_see_a_repaint():
    """Non-vacuity, because every check in this file is an absence.

    A typo in CHROME, a regex that stopped matching, or a comment-stripping pass
    that ate the whole file would all make the test above pass while proving
    nothing. This asserts the machinery reacts to a rule known to be a repaint.
    """
    assert _chrome_hits(".blackcastle .lby-hero-name") == ["lby-hero-name"]
    assert REFUSED.match("font-family") and REFUSED.match("background-image")
    assert REFUSED.match("border-radius") and REFUSED.match("color")
    # ...and does NOT react to the things a game may legitimately do.
    assert not REFUSED.match("position") and not REFUSED.match("z-index")
    assert not REFUSED.match("width") and not REFUSED.match("transition")
    assert not _chrome_hits(".blackcastle .lby-card-meta"), \
        "the card ROW is a game's own material and must not be in CHROME"
