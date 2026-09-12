"""Every lobby with a bot prints WHICH bot on its Active and History rows.

`LobbyBotTier` in `shared/lobby.jsx` is the one renderer, fed by
`core.rooms.state_ai_tier` on the server. A game opts in with one line per
column — and forgetting it renders a completely normal-looking lobby, which is
why this exists at all: the row is not wrong, it is just missing the half of
"who did I play" that says how strong they were.

Read as TEXT, like `test_ai_difficulty_memory.py` and `test_lobby_kit.py` next
door: CI has no browser here, and "this column renders the chip" and "this
endpoint sends the field" are static facts about the source. `screens.mjs`
covers the end-to-end in a real browser — it finishes a real vs-bot Orbit game
and reads the tier back off the History row it lands in. Neither subsumes the
other: a lobby can render the chip against a backend that never sends a tier,
and the chip renders nothing at all in that case, so the browser check on one
game cannot tell you the other five are wired.

THE ROSTER IS DERIVED, never hardcoded. A game with a bot but no ladder drops
out on its own (Rag Tag: one bot, no tiers — there is no difficulty to print),
and so does a game with no bot at all (Where Wolf?). That is the same test the
difficulty-memory roster uses, for the same reason: a hardcoded list only ever
guards the tree SHRINKING, and the next game with a bot would join unguarded.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOBBY = ROOT / "shared" / "lobby.jsx"
SHARED = ROOT / "shared"

# `<LobbyBotTier tier={g.ai_difficulty} labels={SOME_MAP} />`
CHIP = re.compile(r"<LobbyBotTier\s+tier=\{([^}]+)\}\s+labels=\{(\w+)\}\s*/>")


def _ai_games() -> list[pathlib.Path]:
    """Every game screen that starts a game against a bot with a chooseable tier."""
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if re.search(r"\bai_difficulty\b|\bai_variant\b", p.read_text(encoding="utf-8"))]
    assert len(out) >= 5, f"expected the games with bot ladders, found {[p.name for p in out]}"
    return out


def _column(text: str, cls: str) -> str:
    """The source of one lobby column, from its class to the next column's.

    Sliced rather than parsed: the six lobbies build these columns six ways
    (inline JSX, an extracted `const activeCol =`, an IIFE that sorts first),
    and a regex pinned to one shape fails the others for no reason.
    """
    start = text.find(cls)
    assert start != -1, f"no .{cls} in this lobby"
    rest = [text.find(other, start + len(cls))
            for other in ("lby-col-open", "lby-col-active", "lby-col-history")]
    ends = [i for i in rest if i != -1]
    return text[start:min(ends)] if ends else text[start:]


def test_the_shared_component_is_the_one_implementation():
    text = LOBBY.read_text(encoding="utf-8")
    assert "export function LobbyBotTier(" in text, \
        "shared/lobby.jsx no longer exports LobbyBotTier"
    body = text[text.index("export function LobbyBotTier("):]
    body = body[:body.index("\n}\n") + 3]
    # A human game must render NOTHING. Without the guard every row in every
    # lobby carries a chip, and for a vs-friend game it names a bot that was
    # never at the table.
    assert "if (!tier) return null;" in body, \
        "LobbyBotTier must render nothing when there is no bot tier"
    # The separator is the component's, so no lobby can leave one out and none
    # can leave a dangling middot behind an absent chip.
    assert '" · "' in body, \
        "LobbyBotTier no longer owns its separator — six lobbies would each spell it"


def test_the_chip_is_styled_by_the_shared_sheet():
    """A class with no rule renders unstyled while looking deliberate in the
    JSX — the exact state `test_lobby_kit.py` was written for."""
    css = "\n".join(p.read_text(encoding="utf-8") for p in sorted(SHARED.glob("*.css")))
    assert re.search(r"\.lby-bot-tier\s*\{[^}]", css), \
        "shared/*.css defines no rule for .lby-bot-tier"


def test_every_lobby_with_a_bot_names_the_tier_in_both_columns():
    missing: dict[str, list[str]] = {}
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        for cls in ("lby-col-active", "lby-col-history"):
            if not CHIP.search(_column(text, cls)):
                missing.setdefault(jsx.name, []).append(cls)
    assert not missing, (
        "these lobby columns do not say which bot the game was played against, "
        f"so a vs-Expert row and a vs-Easy row read identically: {missing}")


def test_the_chip_reads_the_field_the_server_actually_sends():
    """One wire name. The server emits `ai_difficulty` from
    `core.rooms.state_ai_tier` in every game — including Spender, whose tier is
    a variant CODE internally — so a lobby reaching for `g.ai_variant` or
    `g.difficulty` gets `undefined`, and `undefined` renders nothing at all.
    That is the silent half of this feature and the only way to ship it broken
    while every test that renders passes."""
    wrong = {}
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        for m in CHIP.finditer(text):
            expr = m.group(1).strip()
            if not expr.endswith(".ai_difficulty"):
                wrong.setdefault(jsx.name, set()).add(expr)
    assert not wrong, (
        "these read a tier field the list endpoints do not send, which renders "
        f"an empty chip rather than failing: {wrong}")


def test_each_lobby_labels_the_tier_from_the_list_its_picker_renders():
    """The words come from the game, and there must be only one copy of them.

    A tier id is the server's (`easy`, `bmplus`, `N`); what a player reads is
    the game's own name for it, and every one of these lobbies already had that
    mapping in the list its create modal is built from. Three of them ALSO kept
    a second hand-written copy for the create summary, which is the shape that
    lets a new tier arrive named in one place and unnamed in the other — the
    same drift `test_ai_difficulty_memory` catches on the id list. The map the
    chip reads must therefore be DERIVED from the option list, not typed again.
    """
    for jsx in _ai_games():
        text = jsx.read_text(encoding="utf-8")
        name = CHIP.search(text).group(2)
        decl = re.search(rf"const {name} = ([\s\S]{{0,200}}?);\n", text)
        assert decl, f"{jsx.name}: cannot find where `{name}` is declared"
        assert ".map(" in decl.group(1), (
            f"{jsx.name} hand-writes `{name}` as a second copy of its tier "
            "labels; derive it from the option list the picker renders so a new "
            "tier cannot arrive named in one place and unnamed in the other")


def test_every_bot_games_list_endpoint_sends_the_tier():
    """Both halves, in every game — and via the shared reader.

    A lobby that renders the chip against a payload without the field shows
    nothing, forever, and looks finished. `state_ai_tier` is also the only place
    that knows a stored tier does NOT mean a bot was seated (every game's
    `save_game` defaults it), so a game that reads `state["ai_difficulty"]`
    straight out of the blob labels its human games too.
    """
    lists = ("list_user_games", "list_user_history", "list_active_games")
    problems: dict[str, list[str]] = {}
    for jsx in _ai_games():
        main = jsx.parent / "main.py"
        text = main.read_text(encoding="utf-8")
        for fn in lists:
            m = re.search(rf"\ndef {fn}\(([\s\S]*?)\n\ndef ", text)
            if not m:
                continue        # not every game has every member of the family
            body = m.group(1)
            if '"ai_difficulty": _rooms.state_ai_tier(' not in body:
                problems.setdefault(str(main.relative_to(ROOT)), []).append(fn)
    assert not problems, (
        "these lobby list endpoints do not report which bot the game was "
        f"played against via core.rooms.state_ai_tier: {problems}")
