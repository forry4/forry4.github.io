"""THE DEPLOY FILTER MUST COVER EVERYTHING THAT SERVES.

`deploy-render.yml` carries a hand-curated `paths:` list, and a backend file
missing from it is served in prod off whatever code an unrelated deploy
happened to carry.  **The symptom is silence, not a red run** -- no workflow
fires at all, so every gate passes and nothing ships.

This has now happened twice, at two different depths:

  * 2026-09-05: Orbit was absent from the list entirely.  Prod was running a
    build from the previous day with 22 commits since, and a rewrite of the
    server-authoritative `engine.py` would never have reached the server.
  * 2026-09-13: the `!games/orbit/ai/**` negation added by that fix excluded
    `ai/serving.py` and `ai/state.py`, which `main.py` and `bot.py` both
    import.  A commit touching only the served policy shipped nothing.

The second one is the reason this file exists rather than another careful
comment.  The negation carried a comment asserting that `main.py` imports only
`bot/engine/persist/cards/boards/effects` -- true when written, false once the
Expert shipped -- and a stale comment that reads as a checked fact is worse
than no comment, because it answers the question a reviewer came to ask.  The
package docstring said the same thing.  Prose cannot hold this invariant: the
import graph moves, and nothing makes the filter move with it.

So the roster is DERIVED, never listed here.  We walk what `app.py` actually
imports, transitively, and fail on anything the filter would not deploy.  A new
game, a new serving module, or a new import inside an existing one joins the
check by existing.  This is the same shape as `test_lobby_kit` and
`test_no_conditional_skips`: a hand-written list only ever guards the tree
SHRINKING, and the thing that bites is the tree GROWING.

Layering: `core` may not import a feature, and that holds for its tests.  This
reads `app.py` and the game modules as TEXT and parses them with `ast` -- it
imports nothing under `games/`, exactly as `test_history_limit.py` reads the
lobby JSX as text.
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/deploy-render.yml"


# --------------------------------------------------------------------------
# GitHub Actions path-filter globs.
#
# `*` and `?` do not cross a `/`; `**` does.  Patterns are applied IN ORDER and
# the last one to match wins, which is what makes a `!` negation narrow the
# pattern above it -- and what makes a re-inclusion below a negation work.
# --------------------------------------------------------------------------
def _segment(seg: str) -> str:
    out = []
    for ch in seg:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _glob_re(pattern: str) -> re.Pattern:
    segs = pattern.split("/")
    parts = []
    for i, seg in enumerate(segs):
        last = i == len(segs) - 1
        if seg == "**":
            # Trailing `**` takes the rest of the path; an interior one takes
            # zero or more whole directories, so `a/**/b` still matches `a/b`.
            parts.append(".*" if last else "(?:[^/]+/)*")
        else:
            parts.append(_segment(seg) + ("" if last else "/"))
    return re.compile("^" + "".join(parts) + "$")


def _list_entry(stripped: str) -> str | None:
    """Pull the quoted value out of a `- 'pattern'   # comment` line."""
    if not stripped.startswith("-"):
        return None
    body = stripped[1:].strip()
    if not body or body[0] not in ("'", '"'):
        return None
    quote = body[0]
    end = body.find(quote, 1)
    if end < 0:
        return None
    return body[1:end]


def deploy_patterns() -> list[str]:
    patterns: list[str] = []
    in_paths = False
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "paths:":
            in_paths = True
            continue
        if not in_paths:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        entry = _list_entry(stripped)
        if entry is None:
            break  # end of the paths: block
        patterns.append(entry)
    return patterns


def deploys(path: str, patterns: list[str]) -> bool:
    hit = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        if _glob_re(pattern[1:] if negated else pattern).match(path):
            hit = not negated
    return hit


# --------------------------------------------------------------------------
# What does app.py actually pull in?
# --------------------------------------------------------------------------
def _module_files(module: str) -> list[pathlib.Path]:
    base = REPO / module.replace(".", "/")
    found = []
    if (base / "__init__.py").is_file():
        found.append(base / "__init__.py")
    flat = base.with_suffix(".py")
    if flat.is_file():
        found.append(flat)
    return found


def _package_of(path: pathlib.Path) -> str:
    return ".".join(list(path.relative_to(REPO).parts)[:-1])


def _imported_modules(path: pathlib.Path, tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = _package_of(path).split(".") if _package_of(path) else []
                up = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join(up + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if not base:
                continue
            modules.add(base)
            # `from x import y` may name a submodule rather than an attribute.
            for alias in node.names:
                modules.add(base + "." + alias.name)
    return modules


def serving_closure() -> dict[str, set[str]]:
    """Every first-party module reachable from app.py -> who imports it.

    Imports nested inside functions count.  A deferred import still serves, and
    several of the mounts in `app.py` are deliberately inside a try/except.
    """
    start = REPO / "app.py"
    reached: dict[str, set[str]] = {start.relative_to(REPO).as_posix(): set()}
    queue = [start]
    while queue:
        current = queue.pop()
        key = current.relative_to(REPO).as_posix()
        try:
            tree = ast.parse(current.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - a parse failure is its own bug
            continue
        for module in _imported_modules(current, tree):
            for target in _module_files(module):
                target_key = target.relative_to(REPO).as_posix()
                if target_key not in reached:
                    reached[target_key] = set()
                    queue.append(target)
                reached[target_key].add(key)
    return reached


def test_every_module_that_serves_is_on_the_deploy_path():
    patterns = deploy_patterns()
    reached = serving_closure()

    missing = sorted(path for path in reached if not deploys(path, patterns))
    detail = "\n".join(
        f"  {path}\n      imported by: {', '.join(sorted(reached[path])[:4])}"
        for path in missing
    )
    assert not missing, (
        "These modules are imported (transitively) by app.py but would NOT "
        "trigger a Render deploy, so a commit touching only them passes every "
        "gate and never reaches prod:\n"
        f"{detail}\n\n"
        "Fix .github/workflows/deploy-render.yml, not this test. Negations "
        "narrow the pattern above them and a later pattern wins, so a "
        "re-inclusion goes AFTER the '!' line that excludes it."
    )


def test_the_rules_fingerprint_sources_are_on_the_deploy_path():
    """Orbit hashes its rules over files the *.py-scoped triggers can miss.

    `rules_fingerprint()` digests four modules and a JSON data file.  Every
    deploy trigger is `*.py`-scoped, so the JSON could change the fingerprint
    the server computes without the new bytes ever shipping.  The list is read
    out of the function rather than copied, so adding a source to it fails here
    until the filter covers it too.
    """
    state = REPO / "games/orbit/ai/state.py"
    tree = ast.parse(state.read_text(encoding="utf-8"))

    sources: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "rules_fingerprint":
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Tuple, ast.List)) and inner.elts:
                    values = [
                        e.value for e in inner.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                    if len(values) == len(inner.elts):
                        sources.extend(values)

    assert sources, (
        "Could not read the fingerprint source list out of "
        "games/orbit/ai/state.py::rules_fingerprint -- if it was restructured, "
        "update this test rather than deleting it: a walk that finds nothing "
        "would otherwise pass silently."
    )

    patterns = deploy_patterns()
    undeployed = sorted(
        name for name in sources
        if not deploys(f"games/orbit/{name}", patterns)
    )
    assert not undeployed, (
        "rules_fingerprint() hashes these files, but editing them would not "
        f"trigger a deploy: {undeployed}. The server would compute a "
        "fingerprint from bytes that never shipped."
    )


# --------------------------------------------------------------------------
# Non-vacuity. A walk that reached nothing, or a matcher that said yes to
# everything, would pass both tests above while checking nothing at all --
# which is the exact failure mode this file was written to end.
# --------------------------------------------------------------------------
def test_the_walk_actually_reaches_the_serving_tree():
    reached = serving_closure()
    expected = {
        "app.py",
        "core/db.py",
        "core/auth.py",
        "core/rooms.py",
        "games/orbit/main.py",
        "games/orbit/ai/serving.py",  # the module the 2026-09-13 gap excluded
        "games/orbit/ai/state.py",
        "games/spender/main.py",
        "games/spender/ai/serving/vsearch.py",  # reached only via a deep chain
    }
    assert expected <= set(reached), (
        f"the import walk did not reach {sorted(expected - set(reached))} -- "
        "it is not proving what it claims to prove"
    )
    assert len(reached) > 80, f"only {len(reached)} modules reached; expected the whole backend"


def test_the_matcher_still_says_no_to_things_that_do_not_deploy():
    patterns = deploy_patterns()

    assert deploys("app.py", patterns)
    assert deploys("core/db.py", patterns)
    assert deploys("games/orbit/main.py", patterns)
    assert deploys("games/orbit/ai/serving.py", patterns)
    assert deploys("games/orbit/data/bga_reference.json", patterns)

    # Excluded on purpose: offline halves, docs and tests must NOT restart prod.
    assert not deploys("games/orbit/tools/import_bga.py", patterns)
    assert not deploys("games/orbit/ai/league.py", patterns)
    assert not deploys("games/spender/ai/offline/train_az.py", patterns)
    assert not deploys("books/CLAUDE.md", patterns)
    assert not deploys("core/tests/test_db.py", patterns)

    # `*` must not cross a `/`, or `games/spender/*.py` would swallow ai/offline.
    assert not deploys("games/spender/ai/offline/net.py", patterns)
