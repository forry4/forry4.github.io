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
    "validate_reconnect_token", "mark_reconnect_token_used", "consume_reconnect_token",
    "load_game_state",
    # Not I/O but the same stall: a finished game REPLAYED move by move to build a
    # review (Spender 30-250ms with the values overlay, Duel ~50ms, on a dev box).
    # Both ran inside `async def` review routes, on the loop, until 2026-11-09.
    "_build_review_snapshots", "review_payload",
}

# The account and token lookups a WebSocket handler makes on join/reconnect. Every
# `async def` in a game server is held to these, not just the routes: the handlers
# are not routes, so the test above never saw them, and a slow Turso there stalled
# every game on the site (2026-10-08).
#
# Room LOADING is in it too (2026-11-12): the first touch of a room after a
# restart reads its row, and that read ran synchronously under ROOM_LOCK on the
# loop in every game. A handler now enters `async with _locked_room(rid) as room:`
# (core.rooms.locked_room), which reads on a thread with the lock released and
# re-checks before installing. `_read_room` is handed to it, never called, so a
# CALL to any of these inside an `async def` is the old blocking shape.
ROOM_LOAD = {
    "load_game_to_memory", "_read_room", "load_into",
    "ensure_room_loaded", "_ensure_room_loaded",
}
WS_BLOCKING = {
    "get_user_by_session", "authenticate_user",
    "validate_reconnect_token", "mark_reconnect_token_used", "consume_reconnect_token",
    "create_reconnect_token", "load_game_state",
} | ROOM_LOAD
_ROUTE = (".get(", ".post(", ".put(", ".delete(", ".patch(")


def _route_files():
    patterns = ("app.py", "core/*.py", "games/*/main.py", "games/*/*/serve.py",
                "books/*.py", "notes/*.py", "boxpuzzles/*.py", "steamfilter/*.py")
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


def _async_offenders(source: str, label: str, names=WS_BLOCKING):
    fns, bad = 0, []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        fns += 1
        for call in _calls_outside_nested_defs(node):
            if _name(call.func) in names:
                bad.append(f"{label}:{call.lineno} {node.name}() calls {_name(call.func)}() on the event loop")
    return fns, bad


def test_game_ws_handlers_make_no_blocking_auth_calls():
    total, bad = 0, []
    for path in sorted(REPO.glob("games/*/main.py")):
        n, b = _async_offenders(path.read_text(encoding="utf-8"), str(path.relative_to(REPO)))
        total += n
        bad += b
    # Derived roster: eleven game servers with a dozen-plus async handlers each.
    assert total > 150, f"found only {total} async functions"
    assert not bad, ("Wrap the call in `await asyncio.to_thread(fn, ...)` -- and validate "
                     "plus mark a reconnect token together, through consume_reconnect_token:\n  "
                     + "\n  ".join(bad))


def test_the_ws_check_is_not_vacuous():
    src = '''
async def join(ws, msg):
    return get_user_by_session(msg["s"])

async def rejoin(ws, msg):
    return await asyncio.to_thread(consume_reconnect_token, msg["t"], lambda i: True)

def lobby(token):
    return get_user_by_session(token)
'''
    fns, bad = _async_offenders(src, "x")
    assert fns == 2
    assert bad == ["x:3 join() calls get_user_by_session() on the event loop"]


def test_every_game_loads_rooms_through_the_shared_loader():
    """The other half of the room-load check: refusing the blocking call proves
    nothing if a game simply has no loader to call. Every game server must define
    the thread-side `_read_room` and enter `_locked_room` from its handlers. The
    roster is the tree, so a new game is held to it the day it ships."""
    mains = sorted(REPO.glob("games/*/main.py"))
    assert len(mains) >= 12, [str(m) for m in mains]
    missing = []
    for path in mains:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        entered = sum(1 for n in ast.walk(tree) if isinstance(n, ast.AsyncWith)
                      for item in n.items
                      if isinstance(item.context_expr, ast.Call)
                      and _name(item.context_expr.func) == "_locked_room")
        if "_read_room" not in defs or "_locked_room" not in defs or entered < 3:
            missing.append(f"{path.relative_to(REPO)}: _read_room={'_read_room' in defs} "
                           f"_locked_room={'_locked_room' in defs} entered={entered}")
    assert not missing, "\n  ".join(["games not on core.rooms.locked_room:", *missing])


def test_the_room_load_check_is_not_vacuous():
    src = '''
async def join(ws, rid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(rid)

async def leave(rid):
    async with ROOM_LOCK:
        if rid not in ROOMS:
            load_game_to_memory(rid)

async def start(ws, rid):
    async with _locked_room(rid) as room:
        return room

def _locked_room(rid):
    return _rooms.locked_room(ROOMS, ROOM_LOCK, rid, _read_room)
'''
    fns, bad = _async_offenders(src, "x")
    assert fns == 3
    assert bad == ["x:4 join() calls _ensure_room_loaded() on the event loop",
                   "x:9 leave() calls load_game_to_memory() on the event loop"]
