"""The site no longer waits for the server before drawing — so what needs it must ride the wake.

The shell used to gate EVERY screen on a backend ping, so by the time any lobby,
socket or sign-in ran, the server was known to be up. That gate is gone
(shared/backend.js, and the boot effect in games/spender/Spender.jsx): Home and
sign-in paint from local state, and a lobby can be open while a cold Render
instance is still ~30s from answering. Two opt-ins carry the rest, and both are
the kind that compiles and renders perfectly when forgotten:

  * a game socket opened with `new WebSocket` instead of `openSocket` works on a
    warm server and, on a cold one, dies on the 503 with nobody retrying it — a
    table created during the wake spins forever;
  * a lobby without `useOnBackendAwake(<its list fetch>)` keeps its cached rows
    (or nothing) after a list fetch the wake refused, until a manual refresh.

Read as TEXT, like the rest of `shared/tests/`; rosters derived from the tree.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIRS = ("games", "shared", "books", "notes", "boxpuzzles", "steamfilter",
                 "bggfilter", "astralguide", "animefilter", "lolstats", "webapp")


def _sources() -> list[pathlib.Path]:
    out = []
    for d in FRONTEND_DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix in (".js", ".jsx", ".mjs") and "node_modules" not in p.parts \
                    and "dist" not in p.parts and "test" not in p.parts and "tests" not in p.parts:
                out.append(p)
    return out


def test_no_game_constructs_a_websocket_directly():
    offenders = []
    for p in _sources():
        if p == ROOT / "shared" / "backend.js":
            continue   # the one place a real WebSocket is made
        src = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"new\s+WebSocket\s*\(", src):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, (
        "these files open a socket with `new WebSocket(...)`; use `openSocket(url)` from "
        f"shared/backend.js so a socket opened while the server wakes is retried: {offenders}")


def _lobby_games() -> list[pathlib.Path]:
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "<LobbyCreateRow" in p.read_text(encoding="utf-8")]
    assert len(out) >= 12, f"expected every game's lobby, found {[p.name for p in out]}"
    return out


def test_every_socket_game_uses_open_socket():
    """The other half of the test above: the roster is not vacuous."""
    users = [p.name for p in _lobby_games() if "openSocket(" in p.read_text(encoding="utf-8")]
    assert len(users) >= 12, users


def test_every_lobby_refetches_when_the_server_answers():
    missing = []
    for p in _lobby_games():
        src = p.read_text(encoding="utf-8")
        if not re.search(r"useOnBackendAwake\(", src):
            missing.append(p.name)
    assert not missing, (
        "these lobbies never re-fetch their lists when a waking server answers, so a "
        f"list refused during the wake stays empty or stale until a manual refresh: {missing}. "
        "Add useOnBackendAwake(<the lobby's list fetch>) from shared/lobby.jsx.")


def test_the_boot_does_not_wait_for_the_server():
    """The regression this whole change exists to prevent: a ping in front of the landing."""
    src = (ROOT / "games" / "spender" / "Spender.jsx").read_text(encoding="utf-8")
    boot = src[src.index("// ── Boot: land from LOCAL state"):src.index("const checkStoredSession")]
    boot = "\n".join(l for l in boot.splitlines() if not l.strip().startswith("//"))
    assert "landAt(" in boot
    for gate in ("fetch(", "whenBackendAwake", "/health", "/games"):
        assert gate not in boot, f"the boot effect waits on the server again ({gate!r})"
