"""Every module the backend imports must be able to deploy the backend.

`deploy-render.yml` carries a hand-curated path list, and the failure mode is
SILENCE: a file the server imports but the filter misses simply never ships, and
prod keeps serving whatever an unrelated deploy happened to carry. That is not
hypothetical — Orbit shipped with no entry at all and ran a build 22 commits
stale, and the entry that fixed it then negated `games/orbit/ai/**` on the stated
premise that `main.py` imports only `bot/engine/persist/cards/boards/effects`.
It does not: it imports `ai.serving` and `ai.state` directly, and `bot.py`'s
Hard/Expert watchdog fallback is `ai.serving` too. Three server modules were
excluded again, by a comment nobody had reason to doubt.

So the roster is DERIVED, never written down: this walks the real import graph
from each mounted game's `main.py` and asserts the filter's own verdict on every
file it reaches. It parses the AST rather than importing anything — `core` may
not depend on a feature, and that holds for its tests (the same reason
`test_history_limit.py` reads the JSX as text).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/deploy-render.yml"

# Each mounted feature's server entry point. `app.py` is the composition root, so
# a game that is served but absent here is the original Orbit bug in miniature —
# `test_every_mounted_game_is_audited` derives the roster from `app.py` instead
# of trusting this list.
ENTRY_POINTS = {
    "games.spender": "games/spender/main.py",
    "games.castles_of_crimson": "games/castles_of_crimson/main.py",
    "games.wherewolf": "games/wherewolf/main.py",
    "games.spender_duel": "games/spender_duel/main.py",
    "games.dontminion": "games/dontminion/main.py",
    "games.dissonance": "games/dissonance/main.py",
    "games.rag_tag": "games/rag_tag/main.py",
    "games.orbit": "games/orbit/main.py",
}


def _import_closure(entry: Path) -> set[Path]:
    """Every in-repo module reachable from ``entry`` by a static import."""

    seen: set[Path] = set()
    stack = [entry]
    while stack:
        path = stack.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            targets: list[Path] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    if node.module:
                        base = base / node.module.replace(".", "/")
                else:
                    if "/".join((node.module or "").split(".")[:1]) not in {"core", "games", "books"}:
                        continue
                    base = ROOT / (node.module or "").replace(".", "/")
                # `from .ai import serving` reaches a package AND a submodule of
                # it; `from .ai.state import observation` reaches only a module.
                targets.append(base)
                targets.extend(base / alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                targets.extend(
                    ROOT / alias.name.replace(".", "/") for alias in node.names
                    if alias.name.split(".")[0] in {"core", "games", "books"})
            for target in targets:
                for candidate in (target.with_suffix(".py"), target / "__init__.py"):
                    if candidate.is_file():
                        stack.append(candidate)
    return seen


def _to_regex(pattern: str) -> re.Pattern[str]:
    """GitHub path-filter glob: `**` crosses `/`, a single `*` does not."""

    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def _rules() -> list[tuple[bool, re.Pattern[str]]]:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("paths:", 1)[1].split("workflow_dispatch:", 1)[0]
    patterns = [match.group(1) for match in re.finditer(r"^\s*-\s*'([^']+)'", block, re.M)]
    assert patterns, "could not read the deploy filter's path list"
    return [(pattern.startswith("!"), _to_regex(pattern.lstrip("!"))) for pattern in patterns]


def _deploys(rules, rel: str) -> bool:
    """GitHub applies every pattern in order; the LAST match decides."""

    verdict = False
    for negated, matcher in rules:
        if matcher.match(rel):
            verdict = not negated
    return verdict


@pytest.mark.parametrize("package", sorted(ENTRY_POINTS))
def test_every_module_the_server_imports_can_deploy_it(package):
    rules = _rules()
    closure = _import_closure(ROOT / ENTRY_POINTS[package])
    assert len(closure) > 3, f"{package}: the import walk found almost nothing"
    missing = sorted(
        str(path.relative_to(ROOT)) for path in closure
        if not _deploys(rules, str(path.relative_to(ROOT))))
    assert not missing, (
        f"{package} imports these at serve time, but a push touching them deploys "
        f"NOTHING — prod would keep the old code with no failing run to show it: "
        f"{missing}")


def test_offline_halves_still_do_not_restart_prod():
    """The other half of the trade: a restart costs ~3 minutes of real downtime.

    Scoped to the two directories that carry the negations, so adding a new
    server module never fails this side by accident.
    """

    rules = _rules()
    served = set()
    for entry in ENTRY_POINTS.values():
        served |= _import_closure(ROOT / entry)
    offline = [
        path for pattern in ("games/orbit/ai", "games/orbit/tools", "games/spender/ai/offline")
        for path in (ROOT / pattern).rglob("*.py")
        if path not in served and "tests" not in path.parts
    ]
    assert offline, "the offline roster is empty — the walk or the paths are wrong"
    triggers = sorted(
        str(path.relative_to(ROOT)) for path in offline
        if _deploys(rules, str(path.relative_to(ROOT))))
    assert not triggers, (
        "these never reach the server but would rebuild the image and restart "
        f"prod: {triggers}")


def test_every_mounted_game_is_audited():
    """A game wired into `app.py` but absent above would be unchecked here —
    which is exactly how Orbit went missing from the deploy filter itself."""

    source = (ROOT / "app.py").read_text(encoding="utf-8")
    mounted = set(re.findall(r"from\s+(games\.[a-z_]+)[\s.]", source))
    mounted |= set(re.findall(r"import\s+(games\.[a-z_]+)", source))
    unaudited = sorted(mounted - set(ENTRY_POINTS))
    assert not unaudited, f"mounted in app.py but not audited here: {unaudited}"
