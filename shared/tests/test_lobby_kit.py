"""The shared lobby kit is a CONTRACT, and this is the only thing enforcing it.

`shared/lobby.jsx` + its stylesheet own the whole lobby: the column grid, the
card rows, the empty states, the phone tab bar. A game opts in by using the
kit's class names — and nothing checked that it actually did, so Dissonance
shipped a lobby using `lby-cardmain`, `lby-cardsub`, `lby-cardtitle`, `lby-col`
and `lby-history`, none of which exist in the shared sheet. Every one of those
rows rendered completely unstyled, and it looked like a theming problem rather
than five typos.

Read as TEXT, the way `core/tests/test_history_limit.py` reads the same file:
CI has no browser here, and a class name that is never defined is a static
fact about the source, not something that needs rendering to see.

`screens.mjs` covers what these files LOOK like; this covers whether a new game
is wired into the kit at all. Neither subsumes the other — a game can render a
perfectly fine-looking lobby out of its own private classes, which is exactly
what happened.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared"


def _shared_css() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted(SHARED.glob("*.css")))


def _lobby_games() -> list[pathlib.Path]:
    """Every game screen that renders the shared column grid."""
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "lby-cols" in p.read_text(encoding="utf-8")]
    # Derived from the tree, never hardcoded: a hardcoded roster is how the next
    # game gets added without anything noticing (the Dontminion lesson).
    assert len(out) >= 5, f"expected the lobby games, found {[p.name for p in out]}"
    return out


def _game_frontend(jsx: pathlib.Path) -> str:
    """Every JSX file a game ships, not just the one holding its lobby.

    The other checks here are lobby-file questions by construction — the roster
    IS "the file containing `lby-cols`". A contract about the game BOARD is not:
    Black Castle's redesign moved its header into a sibling `BoardView.jsx` and
    the menu check went red on a game that renders the menu correctly. A test
    that reads one file per game silently measures how a game chose to split its
    modules rather than what it renders.
    """
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted(jsx.parent.glob("*.jsx")))


def test_every_lby_class_a_game_uses_is_one_the_shared_sheet_defines():
    css = _shared_css()
    defined = set(re.findall(r"\.(lby-[a-z0-9-]+)", css))
    # Custom properties are used as `var(--lby-accent)`, not as classes.
    defined |= set(re.findall(r"--(lby-[a-z0-9-]+)", css))
    assert "lby-card-info" in defined and "lby-col-active" in defined, \
        "the stylesheet moved; this test is reading the wrong thing"

    problems: dict[str, set[str]] = {}
    for jsx in _lobby_games():
        used = set(re.findall(r"\b(lby-[a-z0-9-]+)", jsx.read_text(encoding="utf-8")))
        unknown = used - defined
        if unknown:
            problems[jsx.name] = unknown
    assert not problems, (
        "these lobby classes are not defined anywhere in shared/*.css, so they "
        f"render unstyled: {problems}")


def test_a_lobby_pins_every_column_it_has():
    """Grid auto-flow follows DOM order, so an unpinned column lands wherever the
    JSX happens to emit it — and the phone tab bar hides columns by these exact
    class names, so an unpinned one cannot be shown or hidden at all.

    Open and Active are universal. HISTORY IS NOT: Where Wolf has never had one
    (it is a one-night party game — there is nothing to review), and it opted in
    to the shared grid via the `.lby-cols-2` modifier, which is a real two-column
    lobby rather than a three-column one missing a piece. The exemption is a
    LIST, not a `if len(cols) == 2` shrug, and it is self-policing: a game on it
    that *starts* rendering a History column fails as STALE, so the row gets
    deleted rather than sitting here forever excusing something that no longer
    needs excusing. Same discipline as `ACCENT_AA_EXEMPT` and
    `core/tests/test_no_conditional_skips.py`.
    """
    no_history = {"WhereWolf.jsx": "a one-night party game: nothing to review afterwards"}
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        for cls in ("lby-col-open", "lby-col-active"):
            assert cls in text, f"{jsx.name} renders .lby-cols without .{cls}"
        if jsx.name in no_history:
            assert "lby-col-history" not in text, (
                f"{jsx.name} is listed as having no History ({no_history[jsx.name]}) "
                "but now renders one — delete its row from `no_history`")
            assert "lby-cols-2" in text, (
                f"{jsx.name} has no History column, so its grid must say so with the "
                "`lby-cols-2` modifier — a bare .lby-cols reserves a third track")
            continue
        assert "lby-col-history" in text, f"{jsx.name} renders .lby-cols without .lby-col-history"


def test_the_phone_tab_bar_is_wired_to_the_grid():
    """Two halves that must agree, and neither fails loudly on its own.

    `LobbyTabs` reads `t.key`; a game passing `id` renders a bar whose every
    click sets the tab to `undefined`. The grid hides columns off a `tab-<key>`
    CLASS; a game setting `data-tab` matches no rule, so nothing hides. Dissonance
    did both, and the result was a tab bar that looked right, changed nothing,
    and left all three sections stacked on a phone.
    """
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        if "LobbyTabs" not in text:
            continue
        # Read a window around the grid rather than one literal shape: the five
        # games spell the same className three different ways (template literal,
        # string concat, and with a game-specific class in front), and a regex
        # pinned to one of them fails the other two for no reason.
        near = [text[max(0, m.start() - 200):m.end() + 200]
                for m in re.finditer(r"lby-cols", text)]
        assert any("tab-" in w for w in near), \
            f"{jsx.name} must put a tab-<key> class on .lby-cols"
        # `data-tab=` with the equals, i.e. the ATTRIBUTE — the bare string also
        # appears in a comment explaining why not to use it, and a test that
        # cannot tell those apart makes the explanation unwritable.
        assert "data-tab=" not in text, \
            f"{jsx.name} sets data-tab; the CSS hides columns off a CLASS, so it matches no rule"
        tabs = re.search(r"<LobbyTabs[\s\S]{0,600}?/>", text)
        assert tabs, f"{jsx.name} renders LobbyTabs in a shape this test cannot read"
        assert "key:" in tabs.group(0), \
            f"{jsx.name} passes tabs without `key:` — LobbyTabs reads t.key, not t.id"


def test_each_lobby_sets_its_own_accent():
    """`--lby-accent` falls back to Spender's gold, so a game that forgets it
    wears another game's colour rather than rendering visibly wrong."""
    missing = []
    for jsx in _lobby_games():
        game_dir = jsx.parent
        sheets = "\n".join(p.read_text(encoding="utf-8") for p in game_dir.glob("*.css"))
        if "--lby-accent" not in sheets + jsx.read_text(encoding="utf-8"):
            missing.append(jsx.name)
    assert not missing, f"no --lby-accent, so these inherit the default gold: {missing}"


def test_every_game_uses_the_shared_in_game_menu():
    """At a board, the header is ONE hamburger, never a row of buttons.

    Dissonance was the last game still showing Back + Rules in its in-game header
    while the other five used `GameMenu` — and it already imported `GameMenu`
    without ever rendering it, which is the shape this catches. `LobbyHeader`
    takes a `menu` node for exactly this; `onBack`/`onRules` stay for the lobby,
    where a plain Back is right.

    Read across the game's WHOLE frontend (see `_game_frontend`): a board lives
    wherever the game puts it, and this asks whether the menu is rendered, not
    which file renders it.
    """
    missing = [jsx.name for jsx in _lobby_games()
               if "<GameMenu" not in _game_frontend(jsx)]
    assert not missing, (
        "these render a game board without the shared ☰ menu: " f"{missing}")


# WHAT THE MENU CONTAINS MOVED TO shared/tests/test_game_menu_kit.py, because the
# menu now builds its own rows instead of taking an `items` array — so the question
# changed from "did this game type the right three rows?" to "did this game hand the
# rows over at all?", and the answer is a property of `shared/lobby.jsx`.
#
# The guard that used to live here is worth remembering as a lesson rather than as
# code. It read `Return to (menu|lobby)` and `"rules" in body.lower()` — an
# alternation and a case-fold, written wide enough to accept whatever each game
# happened to say. So when Orbit shipped "How to play" above "Return to lobby" with
# `?` and `×` for icons, this passed: the guard had been relaxed to fit the drift it
# existed to catch. A test that accepts two spellings of one label is not enforcing
# one label. The rule is enforceable now because there is only one spelling to
# enforce, and it is in one file.
# (`test_every_game_board_has_the_shared_menu` above still holds, and is the half
# this file is the right home for: whether a game mounts the kit at all.)


def test_a_row_action_uses_the_shared_button():
    """One Resume button, one look. The five lobbies had drifted to FOUR styles
    for the same action — `btn`, `btn btn-gold`, `btn btn-outline` and
    `btn btn-outline btn-sm` — because each game wrote its own class string.
    `LobbyAction` is that string, once."""
    bad = {}
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        # A row action is a button inside .lby-card-actions; a raw <button
        # className="btn…"> there is one that skipped the kit.
        for m in re.finditer(r'lby-card-actions"?>([\s\S]{0,400}?)</div>', text):
            raw = re.findall(r'<button[^>]*className="(btn[^"]*)"', m.group(1))
            if raw:
                bad.setdefault(jsx.name, set()).update(raw)
    assert not bad, (
        "these lobby row actions bypass LobbyAction, so their styling is "
        f"per-game rather than shared: {bad}")


def test_an_active_list_built_from_games_mine_filters_out_waiting_rooms():
    """A room you are in but which has not STARTED is waiting, not active — it
    is already in Open, with a Cancel if you host it. Only Duel filtered; the
    others listed waiting rooms as in-progress and offered a Resume that just
    dropped you back into the waiting room.

    Games whose Active column browses `/games/active` (Spender, CoC) are
    already in-progress-only server-side and are correctly exempt.
    """
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        if "/games/mine" not in text:
            continue
        near = text[max(0, text.find("lby-col-active") - 400):
                    text.find("lby-col-active") + 1200]
        assert "notWaiting" in near or "notWaiting" in text, (
            f"{jsx.name} builds its Active column from /games/mine without "
            "notWaiting(), so rooms still waiting for a player show as active")


def test_the_create_button_says_the_same_thing_in_every_lobby():
    """`+ Create Game`, everywhere. Two lobbies had themed the label to their own
    vocabulary — Rag Tag `+ Create Fight`, Orbit `+ Create Orbit` — which is a
    defensible instinct (every OTHER string in those lobbies says fight/orbit) and
    still the wrong place for it: this is the same control, in the same corner, on
    eight pages, and a player moving between them was re-reading a button they had
    already learned. The theming belongs on the rows, the empty states and the
    create modal, which are actually about the game.

    Enforced rather than remembered because the label is a PROP with a default: a
    new game gets this right by writing nothing at all, and gets it wrong by
    writing one plausible-looking line that nothing else in the repo contradicts.
    """
    themed = {}
    for jsx in _lobby_games():
        for m in re.finditer(r'createLabel=(?:"([^"]*)"|\{[^}]*\})',
                             jsx.read_text(encoding="utf-8")):
            themed[jsx.name] = m.group(1) or "<expression>"
    assert not themed, (
        "these lobbies override the shared create-button label; delete the prop "
        f"and take the default: {themed}")


def test_an_active_game_names_the_seat_you_are_sitting_in():
    """Your own name goes in your own Active row, via the kit's `LobbyMatchup`.

    Five lobbies printed the OPPONENT alone, on the reasoning that one of the two
    seats in a `/games/mine` list is always you. It is not noise: with a few games
    on the go the Active column is the only place the seat you hold is written
    down, and Spender and Castles of Crimson — whose Active columns are PUBLIC, so
    they never had the option — had been showing the full matchup all along. Two
    treatments of the same row, decided by which endpoint a game happened to have.

    The check is for the shared COMPONENT, not for the string: a game that
    hand-rolls "(you)" into its own markup is exactly the drift this kit exists to
    stop, and it is how the `.lby-vs` lead came to be set two different ways.
    """
    # Self-policing, like the History exemption above: a game listed here that
    # STARTS rendering a matchup fails as stale, so the row gets deleted rather
    # than excusing something that no longer needs excusing.
    no_names = {"WhereWolf.jsx": "hidden-role party game: /games/mine carries no "
                                 "opponent names, so the room code is the title"}
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        has = re.search(r"<LobbyMatchup[ />]", text) is not None
        if jsx.name in no_names:
            assert not has, (
                f"{jsx.name} now renders a matchup — delete its row from "
                f"`no_names` ({no_names[jsx.name]})")
            continue
        assert has, (
            f"{jsx.name}'s Active column does not use LobbyMatchup, so it either "
            "hides your own seat or spells it out per-game")


def test_no_game_restyles_the_shared_actions_rail():
    """The rail — the row's buttons with the turn pill UNDER them — is a GRID, and
    a game sheet can silently undo it.

    `.lby-card-actions` lays its children out with `grid-auto-flow:column` plus an
    explicit row for the pill. Six of the seven game sheets are concatenated AFTER
    the shared one, so a per-game `display:flex` on the same class out-orders it at
    equal specificity and the pill goes back beside the button — in one game, on
    one page, looking like a bug in that game rather than a stylesheet ordering
    accident. Same rule, and the same reason, as the lobby GRID one in CLAUDE.md.

    Only the layout properties are refused. A game may still tune the rail's
    spacing or margins (Duel's phone block does).
    """
    layout = re.compile(r"(display|grid-auto-flow|grid-template|flex-direction|flex-flow)\s*:")
    bad = {}
    for css in sorted((ROOT / "games").glob("*/*.css")):
        text = css.read_text(encoding="utf-8")
        for m in re.finditer(r"[^{}]*\.lby-card-actions[^{}]*\{([^}]*)\}", text):
            hits = set(layout.findall(m.group(1)))
            if hits:
                bad.setdefault(css.name, set()).update(hits)
    assert not bad, (
        "these game sheets re-lay-out the shared actions rail, which breaks the "
        f"pill-under-the-button placement in that game only: {bad}")
