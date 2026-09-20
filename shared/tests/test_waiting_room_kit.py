"""The waiting room is ONE screen, and this is the only thing enforcing it.

`WaitingRoom` in `shared/lobby.jsx` is the page between "I made a table" and
"we are playing" — the one screen in the product whose entire job is to get a
second person to the same URL. All nine games built their own, and the nine of
them had drifted exactly the way the lobby card row and the ☰ menu did before
they were extracted:

  * the way out read "← Back to Menu", "Leave", "← Back to lobby", "Back to
    lobby", lived inside a ☰, was the header's own Back — and in Black Castle
    did not exist at all;
  * the room code was click-to-copy in two games, inert text in six, and the
    page's `<h1>` in two;
  * four games printed a static "Waiting for the host to start…" with nothing
    moving on the screen.

And the thing all nine of them were FOR was missing from all nine: what you
could copy was the room CODE, so inviting somebody meant sending six letters
plus instructions for where to type them. The site has had room URLs since the
router landed and every game already enters a room from one.

WHAT THIS FILE HOLDS, and what it deliberately does not. It holds the boundary:
that every game mounts the kit, that the words live in one file, and that no
game grows its own copy-the-code control again. It does not hold what the screen
LOOKS like — that is `waitingRoom` in `webapp/test/screens.mjs`, which drives two
real clients through a real room. Neither subsumes the other: a game can render
a perfectly reasonable waiting room out of its own markup, which is precisely
what nine of them did.

Read as TEXT, like `test_lobby_kit.py` and `test_game_menu_kit.py` beside it —
CI has no browser here, and "does this game mount the kit" is a static fact.

THE ROSTER IS DERIVED FROM THE TREE, never hardcoded. A hardcoded list only ever
guards the set SHRINKING; the tenth game would join unguarded, which is the
shape of every drift this directory exists to catch.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
KIT = ROOT / "shared" / "lobby.jsx"
KIT_CSS = ROOT / "shared" / "lobby.waiting-room-css.css"

# The words a waiting room is made of. Every one of these was a per-game literal
# before, and each is a thing a tenth game would otherwise re-type slightly
# differently. They may appear in `shared/lobby.jsx` and nowhere else.
KIT_WORDS = (
    "← Back to lobby",
    "Waiting for the host to start…",
    "Waiting room",
    "Invite link",
    "Room code",
    "Open seat",
)

# "Start Game" is NOT in the list above, and the reason is worth stating so it is
# not "fixed" back in: it is the kit's default label, and it is also what the
# OFFLINE hub's create button says on a different screen entirely. Policing it as
# a bare string would fail a correct, unrelated call site — the shape of gate that
# gets relaxed until it enforces nothing. What actually matters is narrower and is
# asserted directly below: no game passes the default back in as its own.
DEFAULT_START = "Start Game"


def _lobby_games() -> list[pathlib.Path]:
    """Every game screen that renders the shared column grid.

    A game with a lobby has a waiting room — the lobby's Create button is what
    makes one — so this is the same derivation `test_lobby_kit.py` uses, and it
    is the roster that grows on its own when a tenth game lands.
    """
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "lby-cols" in p.read_text(encoding="utf-8")]
    assert len(out) >= 9, f"expected every game's lobby, found {[p.name for p in out]}"
    return out


def _strip_comments(text: str) -> str:
    """Block comments, and whole lines that are nothing but a line comment.

    Half of this file's job is to refuse a word outside the kit, and the other
    half is these files EXPLAINING which words are the kit's — so a scan that
    reads the explanation as code makes the explanation unwritable. That is the
    same trap `test_lobby_chrome_is_shared` and `test_no_conditional_skips` both
    hit. Line comments are matched anchored to the line so a `https://` inside a
    string is not mistaken for one.
    """
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return "\n".join(l for l in text.split("\n")
                     if not re.match(r"\s*(//|\*)", l))


def _mounts(text: str) -> list[str]:
    """Every `<WaitingRoom …>` opening tag in a file, whole.

    Scanned by BRACE DEPTH rather than matched by a regex: a prop value is
    arbitrary JSX, and Dontminion's `note=` alone contains two arrow functions
    and three `>` characters. A non-greedy `.*?>` stops at the first of them and
    reports every prop after it as missing — a gate that fails on a correct call
    site and passes on nothing in particular.
    """
    out = []
    for m in re.finditer(r"<WaitingRoom\b", text):
        depth = 0
        i = m.end()
        while i < len(text):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == ">" and depth == 0:
                break
            i += 1
        out.append(text[m.start():i + 1])
    return out


def test_every_game_mounts_the_shared_waiting_room():
    # `\b`, not a bare substring: "<WaitingRoom" is a prefix of every longer name a
    # game could give its own component, so the bare form passes on a game that
    # renders `<WaitingRoomPanel>` of its own — which is exactly the opt-out this
    # is here to refuse.
    missing = [p.name for p in _lobby_games()
               if not re.search(r"<WaitingRoom\b", p.read_text(encoding="utf-8"))]
    assert not missing, (
        f"these games still build their own waiting room: {missing}. It is "
        f"`WaitingRoom` in shared/lobby.jsx — a game passes its accent, its own "
        f"word for Start, and any setup of its own in the children slot.")


def test_every_waiting_room_can_be_invited_to_and_left():
    """The four props without which the screen does not do its job.

    React drops nothing and throws nothing for a missing prop, so a game that
    forgets `roomId` renders a perfectly normal-looking panel whose invite link
    points at the lobby, a game that forgets `onLeave` renders one with no way
    out — the state Black Castle actually shipped in — and a game that forgets
    `onStart` hands its HOST a button that does nothing when pressed.
    """
    gaps: dict[str, list[str]] = {}
    for jsx in _lobby_games():
        for mount in _mounts(jsx.read_text(encoding="utf-8")):
            for prop in ("game=", "roomId=", "players=", "onLeave=", "onStart="):
                if prop not in mount:
                    gaps.setdefault(jsx.name, []).append(prop)
    assert not gaps, f"waiting rooms missing load-bearing props: {gaps}"


def test_the_screens_words_live_in_exactly_one_file():
    kit = KIT.read_text(encoding="utf-8")
    for word in KIT_WORDS:
        assert word in kit, f"{word!r} is not in the kit; this test is reading the wrong file"

    problems: dict[str, list[str]] = {}
    for jsx in _lobby_games():
        # Plain substring, not the quoted literal: three of these are JSX TEXT
        # in the kit ("Waiting room", "Room code", "Open seat") and a game that
        # re-typed one would write it as text too. Comments are stripped first,
        # so the note beside each converted screen can still name what it gave up.
        text = _strip_comments(jsx.read_text(encoding="utf-8"))
        hits = [w for w in KIT_WORDS if w in text]
        if hits:
            problems[jsx.name] = hits
    assert not problems, (
        f"waiting-room words re-typed outside the kit: {problems}. They belong to "
        f"`WaitingRoom` in shared/lobby.jsx so nine screens cannot drift apart.")


def test_no_game_rolls_its_own_copy_to_clipboard():
    """The copy control is the kit's, because the thing worth copying changed.

    Spender and CoC each had `navigator.clipboard?.writeText(roomId)` wired to
    their own `setToast` — two implementations of one control, both copying the
    wrong thing. A game that adds a third is opting out of the invite LINK
    without anything saying so.
    """
    offenders = [p.name for p in _lobby_games()
                 if "clipboard" in _strip_comments(p.read_text(encoding="utf-8"))]
    assert not offenders, (
        f"{offenders} copy to the clipboard themselves; `InviteLink` in "
        f"shared/lobby.jsx owns that, and it copies the room URL, not the code.")


def test_the_invite_link_is_built_from_the_router():
    """A URL assembled by hand is a URL that is wrong for one game.

    `buildPath` owns the path grammar AND the VITE_BASE sub-path, and the
    catalogue id is NOT the path segment for Where Wolf (`wherewolf` vs
    `werewolf`) — so a game concatenating its own would deep-link to a 404 on
    exactly one of the nine.
    """
    kit = KIT.read_text(encoding="utf-8")
    assert "buildPath" in kit and "inviteUrl" in kit, \
        "the kit no longer builds the invite URL through the router"
    assert re.search(r"GAME_INFO\[game\]\?\.screen", kit), (
        "inviteUrl no longer reads the catalogue's `screen` for the path segment, "
        "so Where Wolf's /werewolf link is back to being a guess")
    hand_rolled = [p.name for p in _lobby_games()
                   if re.search(r"location\.origin\s*\+", _strip_comments(p.read_text(encoding="utf-8")))]
    assert not hand_rolled, f"{hand_rolled} assemble a room URL by hand: {hand_rolled}"


def test_the_kit_still_owns_the_screen():
    """Non-vacuity: everything above is worthless if the component stopped
    rendering the parts the games handed over."""
    kit = KIT.read_text(encoding="utf-8")
    assert re.search(r"export function WaitingRoom\(\{[^}]*onLeave", kit, re.S), \
        "WaitingRoom no longer takes onLeave — the rest of this file measures nothing"
    css = KIT_CSS.read_text(encoding="utf-8")
    for cls in (".wr-panel", ".wr-invite-btn", ".wr-code-btn", ".wr-seat", ".wr-start"):
        assert cls in css, f"{cls} is gone from the shared sheet; the screen is unstyled"


def test_open_seat_chips_use_table_capacity_not_start_threshold():
    """A 4-seat table must advertise all of its remaining seats.

    `min` answers whether the host may deal; `max` answers how many seats are
    still available. Reusing `min - seated` for both made a four-player room
    with one host render only one open seat, and the same error affected every
    other lobby with a capacity above its minimum.
    """
    kit = KIT.read_text(encoding="utf-8")
    assert "const short = Math.max(0, min - seated);" in kit
    assert "const openSeats =" in kit
    assert "seatCapacity - seated" in kit
    assert "Array.from({ length: openSeats }" in kit


def test_the_clipboard_has_a_fallback_and_says_when_it_fails():
    """`navigator.clipboard` is undefined outside a secure context and rejects
    when the document is not focused, and both look identical to the caller:
    nothing copied, nothing said. A copy button that silently does nothing is
    worse than no copy button, because the player walks away believing they
    have the link."""
    kit = KIT.read_text(encoding="utf-8")
    assert "execCommand" in kit, "the clipboard fallback is gone"
    assert "Could not copy" in kit, \
        "a failed copy no longer announces itself, so it is indistinguishable from a successful one"


def test_no_game_passes_the_default_start_label_back_in():
    """Three games said "Start", "Start game" and "Start Game (2 players)" for the
    one act the kit already names — which is the same drift as five spellings of
    the Back button, in the one control the screen exists to offer. A game keeps
    its own word only where the ACT differs ("Deal & Start", "Start the fight");
    re-typing the default is how a label changes in one place and not the others.
    """
    offenders = {}
    for jsx in _lobby_games():
        for mount in _mounts(jsx.read_text(encoding="utf-8")):
            m = re.search(r'startLabel=(?:"([^"]*)"|\{`([^`]*)`\})', mount)
            said = (m.group(1) or m.group(2)) if m else None
            if said and said.strip().lower().startswith(DEFAULT_START.lower()):
                offenders[jsx.name] = said
    assert not offenders, (
        f"these re-type the kit's default Start label: {offenders}. Drop the prop "
        f"and take the shared one.")
