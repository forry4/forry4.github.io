"""The game kit owns the MATERIALS of every game screen; a game picks its COLORS.

`shared/theme.game-kit.css` is the house look written once: the text face, the
panel construction, the label, the log row, the buttons and the in-game top bar.
A game varies it by setting four tokens on its `fg-table` root (`--g-ground`,
`--g-accent`, `--g-ink`, `--g-label`), and by nothing else.

Two ways to break that, two tests:

1. **Wear a kit class and then repaint it from the game sheet.** Every game sheet
   is concatenated AFTER the kit (CoC's is the exception), so `.pi-player{border-
   radius:6px}` on an element that also wears `fg-panel` silently wins. This test
   reads the JSX for every element wearing a kit class, collects its CO-classes,
   and refuses the kit's own properties on any rule whose last compound selector
   names one of them. It is the lobby chrome gate's idea one level down: there the
   kit's class IS the selector; here the game's class is, so the JSX has to be read
   to know which game classes are kit-dressed.

2. **Set a typeface the site does not use.** One text face was the biggest single
   difference between the games (a system sans in two, Inter + Georgia headings in
   a third), so a game or Extras sheet may name only the house faces, `inherit`, a
   kit variable, a monospace stack for codes, or a face SANCTIONED below as a game's
   own material.

WHAT THIS CANNOT SEE: a rule that names neither a kit class nor a co-class can still
out-specify the kit (`.blackcastle button{...}`). `gameKit` in `webapp/test/screens.mjs`
reads the COMPUTED kit styles on real boards, which is the half that catches that.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Every game screen. Derived, so a new game joins on its first commit.
GAME_DIRS = sorted(p for p in (ROOT / "games").iterdir()
                   if p.is_dir() and any(p.glob("[A-Z]*.jsx")))
EXTRA_DIRS = [ROOT / d for d in ("books", "notes", "boxpuzzles", "bggfilter", "steamfilter",
                                 "animefilter", "lolstats", "astralguide")]

_BTN = ("background", "border", "box-shadow", "color", "font", "letter-spacing",
        "text-transform")
# kit class -> the property families it owns.
OWNS: dict[str, tuple[str, ...]] = {
    # the FACE, not the size: a game's base text size is part of its layout
    "fg-table": ("font=", "font-family"),
    "fg-panel": ("background", "border", "box-shadow"),
    "fg-label": ("font", "letter-spacing", "text-transform", "color"),
    "fg-log-row": ("font", "color", "border", "padding", "line-height"),
    "btn-gold": _BTN,
    "btn-outline": _BTN,
    "btn-ghost": _BTN,
}
# classes that are the kit's own and never a co-class
KIT_CLASSES = set(OWNS) | {"fg-lit", "fg-log-head", "fg-log-quiet", "fg-label-soft", "btn", "btn-sm", "btn-full", "btn-danger"}

# (sheet stem, at-rule, selector) -> why. The at-rule is the enclosing @media text
# ("" at top level), so sanctioning a phone layout never sanctions the desktop rule
# with the same selector. A row that stops matching fails as STALE.
SANCTIONED: dict[tuple[str, str, str], str] = {
    ("PipMarket", "@media(max-width:1180px)", ".pm-actions"):
        "on a phone the action panel is a sheet docked to the bottom edge: square "
        "bottom corners and a shadow cast UP, which no free-standing panel has",
    ("SecretNames", "@media(max-width:760px)", ".sn-console"):
        "the same docked sheet: on a phone the clue console sticks to the bottom edge",
}

# Faces a game may set because they are its MATERIAL, not its chrome.
SANCTIONED_FACES = {
    "orbit": {
        "Chakra Petch": "the instrument face on Orbit's gauges and counters",
        "Cormorant Garamond": "the agent cards' own face, printed on the card art",
    },
}
HOUSE_FACES = {"Cinzel", "Cinzel Fallback", "Crimson Pro", "Crimson Fallback", "Georgia",
               "serif", "inherit", "monospace", "ui-monospace", "SFMono-Regular", "Menlo",
               "Consolas", "initial", "unset"}


# ── a small CSS reader ──────────────────────────────────────────────────────
def _parse(text: str) -> list[tuple[str, dict[str, str], str]]:
    """(selector, {prop: value}) for every style rule, descending into @media /
    @supports / @container. Comments are stripped first: these sheets carry long
    prose about which rules not to write, and a scan that reads the prose as code
    makes the prose unwritable."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out: list[tuple[str, dict[str, str], str]] = []

    def block(s: str, at: str = "") -> None:
        i = 0
        while i < len(s):
            j = s.find("{", i)
            if j < 0:
                return
            head = s[i:j].strip()
            depth, k = 1, j + 1
            while k < len(s) and depth:
                if s[k] == "{":
                    depth += 1
                elif s[k] == "}":
                    depth -= 1
                k += 1
            body = s[j + 1:k - 1]
            if head.startswith("@"):
                if re.match(r"@(media|supports|container|layer)\b", head):
                    block(body, " ".join(head.split()).replace(" (", "(").replace(": ", ":"))
            elif "{" not in body:
                decls = {}
                for d in body.split(";"):
                    if ":" in d:
                        p, v = d.split(":", 1)
                        decls[p.strip().lower()] = v.strip()
                out.append((" ".join(head.split()), decls, at))
            i = k
    block(text)
    return out


def _sheets(dirs) -> list[pathlib.Path]:
    return sorted(p for d in dirs for p in d.glob("*.css"))


def _last_compound(selector: str) -> str:
    return re.split(r"\s*[ >+~]\s*", selector.strip())[-1]


def _classes(compound: str) -> set[str]:
    # pseudo-ELEMENTS are a different box (a panel's ::before sheen is material)
    if "::" in compound or re.search(r":(before|after)\b", compound):
        return set()
    compound = re.sub(r":(not|is|where|has)\([^)]*\)", "", compound)
    return set(re.findall(r"\.([A-Za-z_][\w-]*)", compound))


# ── the JSX side: which game classes are kit-dressed ────────────────────────
_CLASSNAME = re.compile(r"className=(?:\"([^\"]*)\"|\{`([^`]*)`\}|\{\"([^\"]*)\"\})")


def _dressed(dirs) -> dict[str, set[str]]:
    """co-class -> the kit classes it is worn beside, over every .jsx in `dirs`."""
    out: dict[str, set[str]] = {}
    for d in dirs:
        for jsx in d.glob("*.jsx"):
            for m in _CLASSNAME.finditer(jsx.read_text(encoding="utf-8")):
                raw = next(g for g in m.groups() if g is not None)
                static = re.sub(r"\$\{[^}]*\}", " ", raw).split()
                kits = [c for c in static if c in OWNS]
                if not kits:
                    continue
                for c in static:
                    # a bare state word (`active`, `mine`) is never an anchor; the
                    # rule that matters names the prefixed class beside it
                    if c not in KIT_CLASSES and "-" in c:
                        out.setdefault(c, set()).update(kits)
    return out


def _owned(prop: str, families: tuple[str, ...]) -> bool:
    """`border` owns border-radius, border-top-color...; `font=` owns only `font`."""
    return any(prop == f[:-1] if f.endswith("=") else (prop == f or prop.startswith(f + "-"))
               for f in families)


_SANCTION_HITS: set[tuple[str, str, str]] = set()


def _violations(dirs) -> dict[str, list[str]]:
    dressed = _dressed(dirs)
    problems: dict[str, list[str]] = {}
    used = _SANCTION_HITS
    for css in _sheets(dirs):
        for sel, decls, at in _parse(css.read_text(encoding="utf-8")):
            for part in sel.split(","):
                part = part.strip()
                cls = _classes(_last_compound(part))
                # a co-class worn beside a kit class, or the kit class itself
                # (`.dis .btn-gold{...}` repaints the kit under a game scope)
                kits = set().union(*(dressed.get(c, set()) for c in cls)) if cls else set()
                kits |= cls & set(OWNS)
                if not kits:
                    continue
                if (css.stem, at, part) in SANCTIONED:
                    used.add((css.stem, at, part))
                    continue
                fams = tuple(f for k in kits for f in OWNS[k])
                bad = sorted(p for p in decls if not p.startswith("--") and _owned(p, fams))
                if bad:
                    problems.setdefault(f"{css.parent.name}/{css.name}", []).append(
                        f"{part} -> {bad} (worn with {sorted(kits)})")
    return problems


def test_no_game_repaints_a_kit_dressed_element():
    problems = _violations(GAME_DIRS + EXTRA_DIRS)
    assert not problems, (
        "these rules repaint an element that wears a kit class, so this screen stops "
        "sharing the site's materials. Delete the property (the kit already paints it), "
        "or set the game's TOKENS on its fg-table root instead: "
        + " || ".join(f"{k}: " + " | ".join(v) for k, v in sorted(problems.items())))


def test_every_sanctioned_rule_is_still_needed():
    _SANCTION_HITS.clear()
    _violations(GAME_DIRS + EXTRA_DIRS)
    stale = set(SANCTIONED) - _SANCTION_HITS
    assert not stale, f"these SANCTIONED rows match no kit-dressed rule any more — delete them: {sorted(stale)}"


def _families(value: str) -> list[str]:
    v = re.sub(r"!important", "", value).strip()
    if v.startswith("var("):
        return []
    return [f.strip().strip("'\"") for f in v.split(",") if f.strip()]


def _shorthand_families(value: str) -> list[str]:
    """`font: 600 .9rem/1.2 'Cinzel', serif` -> ['Cinzel', 'serif']."""
    v = re.sub(r"!important", "", value).strip()
    m = re.search(r"(?:^|\s)[\d.]+(?:px|rem|em|%|pt|vw|vh)(?:/\S+)?\s+(.*)$", v)
    if not m:
        return []  # `font: inherit` or a var()
    return _families(m.group(1))


def test_every_screen_uses_the_site_typefaces():
    problems: list[str] = []
    for css in _sheets(GAME_DIRS + EXTRA_DIRS):
        allowed = HOUSE_FACES | set(SANCTIONED_FACES.get(css.parent.name, {}))
        for sel, decls, _at in _parse(css.read_text(encoding="utf-8")):
            fams = []
            if "font-family" in decls:
                fams = _families(decls["font-family"])
            elif "font" in decls:
                fams = _shorthand_families(decls["font"])
            if not fams:
                continue
            off = [f for f in fams if f not in allowed and not f.startswith("var(")]
            # Georgia is the METRIC FALLBACK under Crimson/Cinzel, never a face
            if fams[0] == "Georgia":
                off.append("Georgia as the primary face")
            if off:
                problems.append(f"{css.parent.name}/{css.name}  {sel} -> {off}")
    assert not problems, (
        "these rules set a typeface the site does not use. Body text is the kit's "
        "Crimson Pro (inherit it, or var(--g-serif)); labels and titles are Cinzel "
        "(var(--g-display)). A face that is a game's MATERIAL goes in SANCTIONED_FACES: "
        + " | ".join(problems))


def test_every_sanctioned_face_is_still_used():
    stale = []
    for game, faces in SANCTIONED_FACES.items():
        text = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "games" / game).glob("*.css"))
        stale += [f"{game}: {f}" for f in faces if f not in text]
    assert not stale, f"these SANCTIONED_FACES rows describe nothing any more — delete them: {stale}"


def test_every_game_screen_wears_the_kit_root():
    missing = [d.name for d in GAME_DIRS
               if not any("fg-table" in p.read_text(encoding="utf-8") for p in d.glob("*.jsx"))]
    assert not missing, f"these games never mount `fg-table`, so the kit is not theirs: {missing}"


def test_the_kit_is_loaded_by_every_game():
    """baseCss carries the kit; a game that mounts bare (CoC) must append it itself."""
    theme = (ROOT / "shared" / "theme.js").read_text(encoding="utf-8")
    assert "theme.game-kit.css" in theme and "_gameKitText" in theme
    bare = [d.name for d in GAME_DIRS
            if not any(re.search(r"\b(baseCss|gameKitCss)\b", p.read_text(encoding="utf-8"))
                       for p in d.glob("[A-Z]*.jsx"))]
    assert not bare, f"these games load neither baseCss nor gameKitCss: {bare}"


def test_the_scans_can_see_what_they_refuse():
    """Non-vacuity: every check above is an absence."""
    rules = _parse(".a{color:red}@media(max-width:9px){.b .c{border-radius:4px}}.d::before{x:y}")
    assert rules[1] == (".b .c", {"border-radius": "4px"}, "@media(max-width:9px)"), rules
    assert _classes(_last_compound(".b .c.active:hover")) == {"c", "active"}
    assert _classes(".d::before") == set()
    assert _shorthand_families("700 12px/1 ui-sans-serif,system-ui") == ["ui-sans-serif", "system-ui"]
    assert _families("'Cinzel','Cinzel Fallback',serif") == ["Cinzel", "Cinzel Fallback", "serif"]
    assert _owned("border-top-color", OWNS["fg-panel"]) and not _owned("width", OWNS["fg-panel"])
    assert _owned("font", OWNS["fg-table"]) and not _owned("font-size", OWNS["fg-table"])
    dressed = _dressed(GAME_DIRS)
    assert len(dressed) >= 12, f"only {len(dressed)} kit-dressed classes found — the JSX read is broken"
