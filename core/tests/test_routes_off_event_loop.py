"""No `async def` HTTP route may make a blocking database call on the event loop.

The whole site is ONE uvicorn process with ONE event loop, and every game's
WebSockets run on it. A synchronous database call inside an `async def` route
blocks that loop for the whole round trip — on Turso that is a network request
per statement — so every live game on the site pauses while a lobby list loads,
someone signs in (200k PBKDF2 iterations, twice on register) or Books opens.
It is the small version of the CoC outage (heavy sync work on the loop).

A route either:
  * is a plain `def`, which FastAPI runs on its thread pool (the lobby lists,
    auth, Books), or
  * stays `async` because it needs the loop — it takes ROOM_LOCK or reads a
    live room — and moves each blocking call onto a thread with
    `await asyncio.to_thread(fn, ...)`, which passes the function rather than
    calling it, so this test does not see a call.

The roster is DERIVED: every route in every file that registers routes, so a new
game or feature joins it on its own. Nested functions are skipped (they are the
thing handed to `to_thread`).
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Functions that open a connection or run queries/password hashing when called.
BLOCKING = {
    "get_db_conn", "db_conn", "_db",
    "get_user_by_session", "authenticate_user", "create_user", "end_session",
    "create_reconnect_token", "delete_open_game",
    "list_open_games", "list_user_games", "list_user_history", "list_active_games",
}
_ROUTE = (".get(", ".post(", ".put(", ".delete(", ".patch(")


def _route_files():
    patterns = ("app.py", "core/*.py", "games/*/main.py", "games/*/*/serve.py",
                "books/*.py", "notes/*.py")
    return sorted({p for pat in patterns for p in REPO.glob(pat)})


def _calls_outside_nested_defs(fn):
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _name(func) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _offenders(source: str, label: str):
    routes, bad = 0, []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(any(m in ast.unparse(d) for m in _ROUTE) for d in node.decorator_list):
            continue
        routes += 1
        if isinstance(node, ast.AsyncFunctionDef):
            for call in _calls_outside_nested_defs(node):
                if _name(call.func) in BLOCKING:
                    bad.append(f"{label}:{call.lineno} {node.name}() calls {_name(call.func)}() on the event loop")
    return routes, bad


def test_async_routes_make_no_blocking_calls():
    total, bad = 0, []
    for path in _route_files():
        n, b = _offenders(path.read_text(encoding="utf-8"), str(path.relative_to(REPO)))
        total += n
        bad += b
    # The roster is derived, so a broken walk would find nothing and pass. There
    # are ~100 routes; far fewer means the walk, not the code, is wrong.
    assert total > 80, f"found only {total} routes"
    assert not bad, ("Make these routes plain `def`, or wrap the call in "
                     "`await asyncio.to_thread(fn, ...)` if the route needs the loop:\n  "
                     + "\n  ".join(bad))


def test_the_check_is_not_vacuous():
    src = '''
@app.get("/a")
async def a(token):
    return get_user_by_session(token)

@app.get("/b")
async def b(token):
    return await asyncio.to_thread(get_user_by_session, token)

@app.get("/c")
def c(token):
    return list_open_games()

@app.get("/d")
async def d():
    def work():
        return get_db_conn()
    return await asyncio.to_thread(work)
'''
    routes, bad = _offenders(src, "x")
    assert routes == 4
    assert bad == ["x:4 a() calls get_user_by_session() on the event loop"]
