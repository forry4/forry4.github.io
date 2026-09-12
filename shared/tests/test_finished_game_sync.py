"""Every game with cached lobby lists must refresh them when a game ENDS.

The lobby renders its Open/Active/History columns from a localStorage cache
(`readLobbyCache`) and only rewrites it when the LOBBY fetches. So the cache a
player comes back to after finishing a game was written before that game
started: the finished row is still filed under Active, and still missing from
History, until the fetch lands — tens of seconds on a cold backend.

`useFinishedGameSync` in the shared kit closes that window, and a game opts in
with three lines. Forgetting them compiles, renders and plays perfectly — the
lobby is just wrong for a while — which is the exact shape of every other
opt-in the kit has had to grow a test for (the create-button label, the AI
difficulty memory, the lobby classes themselves).

Read as TEXT, like the rest of `shared/tests/` — a missing call is a static
fact about the source and CI has no browser here.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _cached_lobby_games() -> list[pathlib.Path]:
    """Every game screen that caches its lobby lists — derived from the tree.

    A hardcoded roster only ever guards the list SHRINKING, so the next game
    would join unwatched (the `range(13)` lesson).
    """
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "writeLobbyCache(" in p.read_text(encoding="utf-8")]
    assert len(out) >= 7, f"expected the lobby games, found {[p.name for p in out]}"
    return out


def test_every_cached_lobby_syncs_when_a_game_finishes():
    missing = [p.name for p in _cached_lobby_games()
               if "useFinishedGameSync(" not in p.read_text(encoding="utf-8")]
    assert not missing, (
        "these games cache their lobby lists but never refresh them when a game "
        f"ends, so Active keeps the finished game and History lacks it: {missing}. "
        "Wire useFinishedGameSync(over, roomId, cb) from shared/lobby.jsx.")


def test_the_dropped_list_is_one_the_game_actually_caches():
    """`dropLobbyGame(ns, id, key, ...)` must name a real cached list.

    A typo'd namespace or key writes a cache entry nothing ever reads: the
    removal silently does nothing and the stale Active row survives, which is
    indistinguishable from not having wired this up at all.
    """
    problems: dict[str, list[str]] = {}
    for jsx in _cached_lobby_games():
        src = jsx.read_text(encoding="utf-8")
        cached = set(re.findall(r"(?:read|write)LobbyCache\(\s*\"([a-z]+)\"\s*,[^,]+,\s*\"(\w+)\"", src))
        assert cached, f"{jsx.name}: could not read its cache keys; this test is stale"
        for ns, key in re.findall(r"dropLobbyGame\(\s*\"([a-z]+)\"\s*,[^,]+,\s*\"(\w+)\"", src):
            if (ns, key) not in cached:
                problems.setdefault(jsx.name, []).append(f"{ns}/{key}")
    assert not problems, f"dropLobbyGame names a list the game never caches: {problems}"
