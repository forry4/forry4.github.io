"""Every game with an AI opponent defaults its create modal to the LAST tier
that player actually played — and, for a player who has never played it vs the
AI, to the EASIEST tier that game offers.

`useLastDifficulty` in `shared/lobby.jsx` is the one implementation; a game opts
in by holding its difficulty state in it and calling the `remember` it hands
back where the vs-AI game is created. Nothing else can check that a game opted
in — the old `useState("hard")` compiles and renders a perfectly normal-looking
picker, it just forgets, which is the exact failure this is here to catch when
the next game with a bot lands.

The EASIEST half is the same shape of silent failure wearing different clothes:
every one of these defaulted to its strongest or near-strongest tier (Nina,
Expert, Hard, Money+), which reads as a confident choice in the diff and is a
first-time player losing their first game to a neural net before they know the
rules. A first-time default is an answer to a question the player has not been
asked yet, so it is the bottom rung; the moment they answer it by playing, that
answer wins forever.

Read as TEXT, like `test_lobby_kit.py` next door and
`core/tests/test_history_limit.py`: CI has no browser here, and "this file still
holds its difficulty in a bare useState" is a static fact about the source.

`screens.mjs` covers the behaviour end-to-end in a real browser (a fresh player
gets Easy, pick a tier, create, reload, the modal comes back on it). This covers
whether each game is wired in at all — neither subsumes the other.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOBBY = ROOT / "shared" / "lobby.jsx"

# `const [x, setX, rememberX] = useLastDifficulty("ns", scope, OFFERED, FALLBACK)`
# — \s spans newlines on purpose, the call sites wrap after the `=`.
#
# FALLBACK is either a quoted id or `OFFERED[0]`, and the second form is the
# reason this reads an expression rather than a string: "the easiest tier" is a
# fact about the list, so spelling it as the list's own head cannot drift when a
# game adds a rung below its current bottom one.
CALL = re.compile(
    r"const \[\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\]\s*=\s*"
    r"useLastDifficulty\(\s*\"([a-z_]+)\"\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*"
    r"(\"[^\"]+\"|\w+\[0\])\s*\)"
)

# The site SHELL, and the one file allowed to remember for more than one game:
# it owns the /offline hub, which creates local games for four of them. Every
# other screen speaks for itself alone.
SHELL = "Spender.jsx"


def _ai_games() -> list[pathlib.Path]:
    """Every game screen that starts a game against a bot.

    Derived from the tree by the wire field the create message carries, never
    hardcoded — a hardcoded roster is how the next game gets added without
    anything noticing. Where Wolf? has no AI and drops out on its own; Rag Tag
    has a bot but no tiers to pick between, so it carries no difficulty at all.
    """
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if re.search(r"\bai_difficulty\b|\bai_variant\b", p.read_text(encoding="utf-8"))]
    assert len(out) >= 6, f"expected the games with bots, found {[p.name for p in out]}"
    return out


def _call_sites() -> list[tuple[pathlib.Path, re.Match]]:
    """EVERY opt-in, not one per file.

    A game can hold difficulty in more than one place — the shell's offline hub
    is a second create screen for four games — and a second surface that forgets
    is exactly as broken as a first one that does. Checking only the first match
    per file is how the hub sat on a hardcoded `useState("expert")` while this
    file reported every game wired in.
    """
    return [(p, m) for p in _ai_games()
            for m in CALL.finditer(p.read_text(encoding="utf-8"))]


def _offered_ids(text: str, name: str) -> list[str]:
    """Resolve the const naming the tiers the picker OFFERS, in picker order.

    Two shapes in the tree: a bare id list (Spender's variant codes) and a
    `.map()` over the tier objects the modal renders (everyone else). Resolving
    the second is the point — it is what ties the validated list to the list the
    player can actually see. Orbit is why: its bare list had drifted from its
    picker and was missing Expert, so the one tier a player had to go out of
    their way to choose was the one the modal refused to remember.
    """
    direct = re.search(rf"const {name} = \[([^\]]*)\];", text)
    if direct and "{" not in direct.group(1):
        return re.findall(r'"([^"]+)"', direct.group(1))
    derived = re.search(rf"const {name} = (\w+)\.map\(\([^)]*\) => \w+\.(\w+)\)", text)
    assert derived, f"cannot resolve `{name}` — it is neither an id list nor a .map over one"
    src, key = derived.group(1), derived.group(2)
    body = re.search(rf"const {src} = \[([\s\S]*?)\n\];", text)
    assert body, f"cannot find the `{src}` the offered ids are mapped from"
    return re.findall(rf'{key}: "([^"]+)"', body.group(1))


def test_the_shared_helper_is_the_one_implementation():
    text = LOBBY.read_text(encoding="utf-8")
    for name in ("readLastDifficulty", "writeLastDifficulty", "useLastDifficulty"):
        assert f"export function {name}(" in text, f"shared/lobby.jsx no longer exports {name}"
    # A stored tier that the game has since retired must not restore as a live
    # selection: the server coerces an id it doesn't know to its own default, so
    # the modal would name one bot and seat another.
    read = text[text.index("export function readLastDifficulty("):
                text.index("export function writeLastDifficulty(")]
    assert "offered.includes(" in read, \
        "readLastDifficulty no longer validates the stored id against the offered tiers"


def test_every_game_with_a_bot_remembers_the_last_tier_played():
    missing = [p.name for p in _ai_games() if not CALL.search(p.read_text(encoding="utf-8"))]
    assert not missing, (
        "these start games against a bot but hold their difficulty in plain "
        f"state, so the picker forgets what the player last played: {missing}")


def test_nothing_opts_in_outside_the_games_this_file_checks():
    """The roster is derived from a wire field, so a screen that picks tiers
    under some other field name would opt in and never be checked. Find the
    opt-ins directly and require the two views to agree."""
    users = sorted(p for p in [*ROOT.glob("games/**/*.jsx"), *ROOT.glob("shared/**/*.jsx")]
                   if "useLastDifficulty(" in p.read_text(encoding="utf-8")
                   and p != LOBBY)
    assert users == _ai_games(), (
        "these hold a difficulty in the shared helper but are not in the roster "
        f"this file derives: {[p.name for p in users if p not in _ai_games()]}")


def test_the_remembered_tier_is_written_where_the_game_is_created():
    """`remember` is what makes it stick, and a game can destructure it and
    never call it — which reads as working (the default restores) right up until
    the player picks something else.

    It must also not be the picker's onChange: the contract is "last PLAYED", so
    browsing the tiers and backing out leaves the remembered one alone.
    """
    for jsx, m in _call_sites():
        text = jsx.read_text(encoding="utf-8")
        remember = m.group(3)
        calls = [ln for ln in text.splitlines()
                 if f"{remember}(" in ln and "useLastDifficulty" not in ln]
        assert calls, f"{jsx.name} destructures {remember} and never calls it"
        assert not any("onChange" in ln for ln in calls), (
            f"{jsx.name} writes the tier from the picker's onChange — that stores "
            "what the player merely LOOKED at, not what they played")


def test_the_picker_still_drives_the_state_it_reads():
    """The setter has to reach the picker or the row goes read-only — the one
    way this refactor can visibly break a modal."""
    for jsx, m in _call_sites():
        text = jsx.read_text(encoding="utf-8")
        value, setter = m.group(1), m.group(2)
        assert re.search(rf"onChange=\{{{setter}\}}|{setter}\(", text), \
            f"{jsx.name} never hands {setter} to its difficulty picker"
        assert re.search(rf"\b{value}\b", text[m.end():]), \
            f"{jsx.name} never reads {value} after declaring it"


def test_each_game_remembers_under_its_own_namespace():
    """ONE key per game, and a second create screen for a game REUSES that key.

    Both directions are the same count. A key shared by two games would make
    picking Expert in one silently re-default the other (the ids collide —
    'easy'/'hard' are four games' tiers); a second key invented for a second
    screen splits one player's answer in two, so the offline hub would hand a
    CoC regular the bottom rung the first time they play on a plane. Either
    shows up as the namespaces no longer numbering exactly one per game.
    """
    per_file = {p: [m.group(4) for m in CALL.finditer(p.read_text(encoding="utf-8"))]
                for p in _ai_games()}
    used = {ns for names in per_file.values() for ns in names}
    assert len(used) == len(per_file), (
        f"{len(used)} namespaces {sorted(used)} across {len(per_file)} games with "
        "bots — a key is either shared by two games or invented for a second screen")
    multi = sorted(p.name for p, names in per_file.items() if len(set(names)) > 1)
    assert multi in ([], [SHELL]), (
        f"{multi} remember for more than one game. Only {SHELL} may: it owns the "
        "/offline hub, which is a second create screen for four of them")


def test_it_is_remembered_per_identity():
    """Scoped like the lobby cache next to it: two accounts on one device must
    not inherit each other's difficulty."""
    for jsx, m in _call_sites():
        assert m.group(5) == "myId", \
            f"{jsx.name} scopes its remembered tier on `{m.group(5)}`, not the player id"


def test_the_first_game_default_is_the_easiest_tier_the_picker_offers():
    """What a player with NO history gets, on every screen that can start a
    vs-AI game.

    Two things at once. The tier must be one the picker offers, or the modal
    opens with nothing selected and the create button still sends it, so the
    server quietly seats its own default instead. And it must be the EASIEST
    one: a first-time default is a guess, and the cheap guess to be wrong about
    is the one the player beats.
    """
    for jsx, m in _call_sites():
        text = jsx.read_text(encoding="utf-8")
        offered_name, expr = m.group(6), m.group(7)
        offered = _offered_ids(text, offered_name)
        assert offered, f"{jsx.name}: `{offered_name}` resolved to no tiers at all"
        if expr.startswith('"'):
            fallback = expr.strip('"')
            assert fallback in offered, (
                f"{jsx.name} defaults to '{fallback}', which its picker does not "
                f"offer: {offered}")
            assert fallback == offered[0], (
                f"{jsx.name} defaults a first-time player to '{fallback}' when the "
                f"easiest tier it offers is '{offered[0]}': {offered}")
        else:
            assert expr == f"{offered_name}[0]", (
                f"{jsx.name} defaults to `{expr}`, which is not the head of the "
                f"tiers it validates against (`{offered_name}`)")
