"""Every game with an AI opponent defaults its create modal to the LAST tier
that player actually played.

`useLastDifficulty` in `shared/lobby.jsx` is the one implementation; a game opts
in by holding its difficulty state in it and calling the `remember` it hands
back where the vs-AI game is created. Nothing else can check that a game opted
in — the old `useState("hard")` compiles and renders a perfectly normal-looking
picker, it just forgets, which is the exact failure this is here to catch when
the next game with a bot lands.

Read as TEXT, like `test_lobby_kit.py` next door and
`core/tests/test_history_limit.py`: CI has no browser here, and "this file still
holds its difficulty in a bare useState" is a static fact about the source.

`screens.mjs` covers the behaviour end-to-end in a real browser (pick a tier,
create, reload, the modal comes back on it). This covers whether each game is
wired in at all — neither subsumes the other.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOBBY = ROOT / "shared" / "lobby.jsx"

# `const [x, setX, rememberX] = useLastDifficulty("ns", scope, OFFERED, "fallback")`
# — \s spans newlines on purpose, the call sites wrap after the `=`.
CALL = re.compile(
    r"const \[\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\]\s*=\s*"
    r"useLastDifficulty\(\s*\"([a-z_]+)\"\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*\"([^\"]+)\"\s*\)"
)


def _ai_games() -> list[pathlib.Path]:
    """Every game screen that starts a game against a bot.

    Derived from the tree by the wire field the create message carries, never
    hardcoded — a hardcoded roster is how the next game gets added without
    anything noticing. Where Wolf? has no AI and drops out on its own.
    """
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if re.search(r"\bai_difficulty\b|\bai_variant\b", p.read_text(encoding="utf-8"))]
    assert len(out) >= 5, f"expected the games with bots, found {[p.name for p in out]}"
    return out


def _offered_ids(text: str, name: str) -> list[str]:
    """Resolve the const naming the tiers the picker OFFERS.

    Two shapes in the tree: a bare id list (Spender's variant codes) and a
    `.map()` over the tier objects the modal renders (everyone else). Resolving
    the second is the point — it is what ties the validated list to the list the
    player can actually see.
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


def test_the_remembered_tier_is_written_where_the_game_is_created():
    """`remember` is what makes it stick, and a game can destructure it and
    never call it — which reads as working (the default restores) right up until
    the player picks something else.

    It must also not be the picker's onChange: the contract is "last PLAYED", so
    browsing the tiers and backing out leaves the remembered one alone.
    """
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        m = CALL.search(text)
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
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        m = CALL.search(text)
        value, setter = m.group(1), m.group(2)
        assert re.search(rf"onChange=\{{{setter}\}}|{setter}\(", text), \
            f"{jsx.name} never hands {setter} to its difficulty picker"
        assert re.search(rf"\b{value}\b", text[m.end():]), \
            f"{jsx.name} never reads {value} after declaring it"


def test_each_game_remembers_under_its_own_namespace():
    """One key per game. A shared namespace would make picking Expert in one
    game silently re-default another, and the ids do collide across games
    ('easy'/'hard' are three games' tiers)."""
    seen: dict[str, str] = {}
    for jsx in _ai_games():
        ns = CALL.search(jsx.read_text(encoding="utf-8")).group(4)
        assert ns not in seen, f"{jsx.name} and {seen[ns]} both remember under '{ns}'"
        seen[ns] = jsx.name


def test_it_is_remembered_per_identity():
    """Scoped like the lobby cache next to it: two accounts on one device must
    not inherit each other's difficulty."""
    for jsx in _ai_games():
        scope = CALL.search(jsx.read_text(encoding="utf-8")).group(5)
        assert scope == "myId", \
            f"{jsx.name} scopes its remembered tier on `{scope}`, not the player id"


def test_the_first_game_default_is_a_tier_the_picker_offers():
    """The fallback is what a player with no history gets. If it isn't in the
    offered list the modal opens with nothing selected — and the create button
    still sends it, so the server quietly seats its own default instead."""
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        m = CALL.search(text)
        offered, fallback = _offered_ids(text, m.group(6)), m.group(7)
        assert offered, f"{jsx.name}: `{m.group(6)}` resolved to no tiers at all"
        assert fallback in offered, (
            f"{jsx.name} defaults to '{fallback}', which its picker does not "
            f"offer: {offered}")


def test_the_validated_list_is_the_list_the_picker_renders():
    """The offered ids and the modal's options must be ONE list, not two that
    agree today.

    This is the failure it catches, from Orbit: the picker gained an Expert
    row and the hand-written id list beside it stayed `easy/normal/hard`, so
    choosing Expert was stored, failed validation on the next open, and the
    modal came back on Hard — a difficulty that silently forgets only the
    newest tier, which is the one most likely to be picked.

    Two shapes count as one list: the offered const is `.map`ped off the option
    objects the picker renders (most games), or it IS the const the picker maps
    over (Spender's variant codes).
    """
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        name = CALL.search(text).group(6)
        derived = re.search(rf"const {name} = (\w+)\.map\(", text)
        source = derived.group(1) if derived else name
        assert re.search(rf"options=\{{{source}\}}|\b{source}\.map\(", text), (
            f"{jsx.name} validates remembered tiers against `{name}`, but its "
            f"picker does not render from `{source}` — the two lists will drift "
            "and a tier in only one of them cannot be remembered")
