"""Every socket game must retry a dropped socket through ONE implementation.

`shared/useAutoReconnect.js` is the retry loop. CoC, Duel, Dontminion and
Dissonance each carried an inline copy of it until 2026-09-22, and the copies
had drifted: three nudged on tab focus and one (Dissonance) did not, so on iOS,
which kills a backgrounded socket without firing `onclose`, a Dissonance game
sat frozen until a reload. And all four copies, like the hook itself, bailed out
of that focus nudge on a stale `connected === true`, which is exactly the state
iOS leaves behind. The fix had to land once; this keeps it landed once.

Two games are exempt, each with its own model rather than a stale copy:
Spender's socket hook reconnects from `onclose` and on focus by readyState, and
Where Wolf? retries a bounded few times and then offers a manual button (no bot
waits on it).

Read as TEXT, like the rest of `shared/tests/`.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOK = ROOT / "shared" / "useAutoReconnect.js"

# Game screens with their own reconnect model (see the module docstring).
EXEMPT = {"Spender.jsx", "WhereWolf.jsx"}


def _socket_games() -> list[pathlib.Path]:
    """Every game screen that opens a WebSocket — derived from the tree, so the
    next game joins the roster on its own (the `range(13)` lesson)."""
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "new WebSocket(" in p.read_text(encoding="utf-8")]
    assert len(out) >= 11, f"expected the socket games, found {[p.name for p in out]}"
    return out


def test_every_socket_game_uses_the_shared_hook():
    missing, inline = [], []
    for p in _socket_games():
        if p.name in EXEMPT:
            continue
        src = p.read_text(encoding="utf-8")
        if "useAutoReconnect(" not in src:
            missing.append(p.name)
        if "attemptReconnect" in src or "reconnTries" in src:
            inline.append(p.name)
    assert not missing, (
        f"these games open a socket but never retry it: {missing}. "
        "Wire useAutoReconnect from shared/useAutoReconnect.js.")
    assert not inline, (
        f"these games carry an inline copy of the retry loop: {inline}. "
        "Use the shared hook so a fix lands in every game at once.")


def test_the_exemptions_are_still_socket_games():
    names = {p.name for p in _socket_games()}
    assert EXEMPT <= names, f"stale EXEMPT entries: {EXEMPT - names}"


def test_a_replaced_socket_cannot_flip_connected():
    """`connect()` closes the old socket before opening the new one, and the
    old one's `onclose` can land AFTER the new one opened. Unguarded, it sets
    `connected` false over a live socket: the banner says Reconnecting… and the
    retry loop polls a healthy socket forever."""
    bad = []
    for p in _socket_games():
        if p.name in EXEMPT:
            continue
        for m in re.finditer(r"ws\.onclose\s*=\s*\(\)\s*=>\s*([^\n]*)", p.read_text(encoding="utf-8")):
            if "wsRef.current === ws" not in m.group(1) and "wsRef.current !== ws" not in m.group(1):
                bad.append(f"{p.name}: {m.group(0).strip()}")
    assert not bad, "unguarded onclose handlers:\n" + "\n".join(bad)


def test_the_focus_nudge_does_not_trust_a_stale_connected_flag():
    """The visibility handler exists for the socket iOS killed silently, which
    leaves `connected` true. Returning early on `connected` makes it a no-op in
    precisely that case; it must consult the socket's readyState instead."""
    src = HOOK.read_text(encoding="utf-8")
    m = re.search(r"const onVis = \(\) => \{(.*?)\n    \};", src, re.S)
    assert m, "could not find the hook's visibility handler; this test is stale"
    body = m.group(1)
    assert "|| connected ||" not in body and "|| connected)" not in body, body
    assert "readyRef.current()" in body, body
