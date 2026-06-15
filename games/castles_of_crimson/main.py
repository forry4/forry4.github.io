"""FastAPI sub-application for Castles of Crimson.

Exposes ``coc_app`` which ``games.spender.main`` mounts under ``/coc`` so the
whole site runs as one backend service. WebSocket lives at
``/coc/ws/{room}/{player}`` and REST under ``/coc/...``.

This layer is intentionally thin: it manages rooms, sockets, persistence and the
WebSocket protocol, and delegates ALL game rules to ``engine``. It mirrors the
proven patterns in ``games.spender.main`` (in-memory ``ROOMS`` under a single
``asyncio.Lock``, SQLite persistence, the stale-socket disconnect guard, and the
async opponent-turn scheduler).

Site identity (users/sessions) is shared with Spender: the auth helpers are
imported lazily from ``games.spender.main`` inside the functions that use them,
which avoids an import-time circular dependency (Spender imports ``coc_app`` at
the very end of its module). Room persistence uses a separate ``coc_games``
table in the shared ``users.db``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from . import board
from . import tiles
from . import bot

LOG = logging.getLogger("games.castles_of_crimson")

coc_app = FastAPI(title="Castles of Crimson API")
coc_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory room state ──────────────────────────────────────────────────────
ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()
AI_PID = "bot"


def _valid_board(board_id) -> str:
    """Coerce a client-supplied board id to a real one (default on anything bad)."""
    if isinstance(board_id, str) and board_id in board.BOARDS:
        return board_id
    return board.DEFAULT_BOARD_ID


# ── Shared-identity / DB helpers (lazy imports avoid a circular dependency) ───
def _db():
    from games.spender.main import get_db_conn
    return get_db_conn()


def _gen_token(n: int = 12) -> str:
    from games.spender.main import gen_token
    return gen_token(n)


def normalize_room(rid: str) -> str:
    return (rid or "").upper()


def coc_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS coc_games (
        id TEXT PRIMARY KEY,
        status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


coc_init_db()


# ── Persistence ───────────────────────────────────────────────────────────────
def save_game(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    pids = list(room.get("players", {}).keys())
    names = list(room.get("players", {}).values())
    state = {
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "boards": room.get("boards", {}),
    }
    now = int(time.time())
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM coc_games WHERE id=?", (room_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("""UPDATE coc_games SET status=?, player2_id=?, player2_name=?, state_json=?, updated_at=?
                       WHERE id=?""",
                    (room.get("status"),
                     pids[1] if len(pids) > 1 else None,
                     names[1] if len(names) > 1 else None,
                     json.dumps(state), now, room_id))
    else:
        cur.execute("""INSERT INTO coc_games
                       (id,status,player1_id,player1_name,player2_id,player2_name,host_id,state_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (room_id, room.get("status", "open"),
                     pids[0] if pids else None, names[0] if names else None,
                     pids[1] if len(pids) > 1 else None, names[1] if len(names) > 1 else None,
                     room.get("host"), json.dumps(state), now, now))
    conn.commit()
    conn.close()


def load_game_to_memory(room_id: str) -> bool:
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM coc_games WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return False
    try:
        state = json.loads(row["state_json"])
    except Exception:
        return False
    ROOMS[room_id] = {
        "players": state.get("players", {}),
        "host": state.get("host"),
        "status": state.get("status", "open"),
        "game": state.get("game"),
        "meta": state.get("meta", {}),
        "vs_ai": state.get("vs_ai", False),
        "ai_player": state.get("ai_player"),
        "boards": state.get("boards", {}),
        "sockets": {},
    }
    return True


def list_open_games() -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, created_at FROM coc_games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "host_id": r["player1_id"], "host_name": r["player1_name"],
             "created_at": r["created_at"]} for r in rows]


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, status, player1_id, player1_name, player2_id, player2_name,
                          state_json, created_at, updated_at
                   FROM coc_games
                   WHERE (player1_id=? OR player2_id=?) AND status != 'over'
                   ORDER BY updated_at DESC""", (user_id, user_id))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            state = {}
        g = state.get("game") or {}
        is_p1 = r["player1_id"] == user_id
        your_turn = isinstance(g, dict) and g.get("turn") == user_id
        out.append({
            "id": r["id"], "status": r["status"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": is_p1, "your_turn": your_turn,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    conn = _db()
    cur = conn.cursor()
    cur.execute("DELETE FROM coc_games WHERE id=? AND player1_id=? AND status='open'", (game_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ── Room helpers ──────────────────────────────────────────────────────────────
async def broadcast_room(room_id: str, msg: dict[str, Any]) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    data = json.dumps(msg)
    for ws in list(room.get("sockets", {}).values()):
        try:
            await ws.send_text(data)
        except Exception:
            pass


def mk_room_state(room_id: str) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "boards": room.get("boards", {}),
        "reconnect_tokens": {p: info.get("token") for p, info in room.get("meta", {}).items()} if room.get("meta") else {},
    }


def _sync_status_from_game(room: dict) -> None:
    g = room.get("game")
    if g and engine.is_over(g):
        room["status"] = "over"


# ── Opponent (bot) turn scheduler ─────────────────────────────────────────────
async def _schedule_bot_turn(room_id: str) -> None:
    """Run the placeholder bot while the active decision belongs to it.

    The trivial bot is instant, so it runs inline under the lock. (A future MCTS
    AI would compute in a thread-pool, mirroring Spender's _schedule_ai_turn.)
    """
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        game = room.get("game")
        ai = room.get("ai_player")
        if not game or not ai or engine.is_over(game):
            return
        if (game.get("pending_pid") or game.get("turn")) != ai:
            return
        rng = random.Random()
        guard = 0
        while not engine.is_over(game) and guard < 200:
            guard += 1
            if (game.get("pending_pid") or game.get("turn")) != ai:
                break
            bot.play_turn(game, ai, rng)
        _sync_status_from_game(room)
        save_game(room_id)
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})


def _bot_should_act(room: dict) -> bool:
    game = room.get("game")
    ai = room.get("ai_player")
    return bool(game and ai and not engine.is_over(game)
                and (game.get("pending_pid") or game.get("turn")) == ai)


# ── WebSocket protocol ────────────────────────────────────────────────────────
@coc_app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id = normalize_room(room)
    pid = player

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "bad message"}))
                continue
            action = msg.get("action")

            if action == "create":
                await _handle_create(websocket, room_id, pid, msg)
            elif action == "join":
                await _handle_join(websocket, room_id, pid, msg)
            elif action == "start":
                await _handle_start(websocket, room_id, pid)
            elif action == "move":
                await _handle_move(websocket, room_id, pid, msg)
            elif action == "reconnect":
                await _handle_reconnect(websocket, room_id, pid, msg)
            elif action == "auth_reconnect":
                await _handle_auth_reconnect(websocket, room_id, pid, msg)
            elif action == "abandon":
                await _handle_abandon(websocket, room_id, pid)
            else:
                await websocket.send_text(json.dumps({"type": "error", "message": "unknown action"}))
    except WebSocketDisconnect:
        pass
    finally:
        # Stale-socket guard: only remove if THIS socket is still registered.
        room = ROOMS.get(room_id)
        if room and room.get("sockets", {}).get(pid) is websocket:
            room["sockets"].pop(pid, None)
            if not room["sockets"] and room.get("status") != "playing":
                # keep playing/over games in memory; drop empty open rooms only
                if room.get("status") == "open" and room.get("game") is None:
                    ROOMS.pop(room_id, None)


def _ensure_room_loaded(room_id: str) -> dict | None:
    if room_id not in ROOMS:
        load_game_to_memory(room_id)
    return ROOMS.get(room_id)


async def _send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    my_board = _valid_board(msg.get("board_id"))
    opp_board = _valid_board(msg.get("opp_board_id"))
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return
        room = {
            "players": {pid: name},
            "sockets": {pid: ws},
            "status": "open",
            "host": pid,
            "game": None,
            "meta": {pid: {"token": _gen_token()}},
            "vs_ai": vs_ai,
            "ai_player": None,
            "boards": {pid: my_board},
        }
        ROOMS[room_id] = room
        if vs_ai:
            room["players"][AI_PID] = "Bot"
            room["ai_player"] = AI_PID
            room["status"] = "playing"
            room["boards"][AI_PID] = opp_board
            room["game"] = engine.new_game([pid, AI_PID], names={pid: name, AI_PID: "Bot"},
                                           boards=room["boards"])
        save_game(room_id)
        bot_turn = vs_ai and _bot_should_act(room)
    await _send(ws, {"type": "created", "room_id": room_id, "room": mk_room_state(room_id)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_join(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if pid not in room["players"]:
            if room.get("status") != "open" or len([p for p in room["players"] if p != AI_PID]) >= 2:
                await _send(ws, {"type": "error", "message": "room is full"})
                return
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room.setdefault("boards", {})[pid] = _valid_board(msg.get("board_id"))
        room["sockets"][pid] = ws
        save_game(room_id)
    await _send(ws, {"type": "joined", "room_id": room_id, "room": mk_room_state(room_id)})
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})


async def _handle_start(ws, room_id, pid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        humans = [p for p in room["players"]]
        if len(humans) < 2:
            await _send(ws, {"type": "error", "message": "need two players"})
            return
        if room.get("status") != "open":
            await _send(ws, {"type": "error", "message": "already started"})
            return
        room["status"] = "playing"
        boards = {p: _valid_board(room.get("boards", {}).get(p)) for p in humans}
        room["boards"] = boards
        room["game"] = engine.new_game(humans, names=dict(room["players"]), boards=boards)
        save_game(room_id)
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})


async def _handle_move(ws, room_id, pid, msg):
    bot_turn = False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "game not started"})
            return
        game = room.get("game")
        if not game:
            await _send(ws, {"type": "error", "message": "game not started"})
            return
        ok, err = engine.apply_move(game, pid, msg.get("move") or {})
        if not ok:
            await _send(ws, {"type": "error", "message": err or "illegal move"})
            return
        _sync_status_from_game(room)
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "invalid token"})
            return
        if room.get("meta", {}).get(pid, {}).get("token") != token:
            await _send(ws, {"type": "error", "message": "invalid token"})
            return
        room["sockets"][pid] = ws
        bot_turn = _bot_should_act(room)
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_auth_reconnect(ws, room_id, pid, msg):
    from games.spender.main import validate_reconnect_token, mark_reconnect_token_used
    token = msg.get("token")
    info = validate_reconnect_token(token)
    if not info or info.get("room_id") != room_id or info.get("player_id") != pid:
        await _send(ws, {"type": "error", "message": "invalid token"})
        return
    mark_reconnect_token_used(token)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        room["sockets"][pid] = ws
        # refresh this player's room reconnect token
        room.setdefault("meta", {}).setdefault(pid, {})["token"] = _gen_token()
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_abandon(ws, room_id, pid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            return
        game = room.get("game")
        room["status"] = "over"
        if game:
            others = [p for p in room["players"] if p != pid]
            game["phase"] = "over"
            game["winner"] = others[0] if others else None
        save_game(room_id)
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})


# ── REST ──────────────────────────────────────────────────────────────────────
@coc_app.get("/health")
async def health():
    return {"status": "ok", "service": "castles_of_crimson", "version": "1.0"}


@coc_app.get("/boards")
async def board_layouts():
    """Every selectable duchy layout (single source of truth for the frontend renderer)."""
    return {
        "ok": True,
        "boards": [
            {"id": b.id, "name": b.name, "spaces": b.SPACES}
            for b in board.BOARDS.values()
        ],
        "default_board": board.DEFAULT_BOARD_ID,
        "colors": board.COLORS,
        "color_types": tiles.COLOR_TO_TYPE,
        "goods_colors": tiles.GOODS_COLORS,
        "monastery_meta": {eid: m["desc"] for eid, m in tiles.MONASTERY_META.items()},
    }


@coc_app.get("/board")
async def board_layout():
    """Back-compat: the default board's layout."""
    return {
        "ok": True,
        "spaces": board.SPACES,
        "colors": board.COLORS,
        "color_types": tiles.COLOR_TO_TYPE,
        "goods_colors": tiles.GOODS_COLORS,
        "monastery_meta": {eid: m["desc"] for eid, m in tiles.MONASTERY_META.items()},
    }


@coc_app.get("/games")
async def games_open():
    return {"ok": True, "games": list_open_games()}


@coc_app.get("/games/mine")
async def games_mine(token: str | None = None):
    from games.spender.main import get_user_by_session
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_games(user["id"])}


@coc_app.post("/games/{game_id}/cancel")
async def games_cancel(game_id: str, token: str | None = None, player_id: str | None = None):
    from games.spender.main import get_user_by_session
    game_id = normalize_room(game_id)
    owner = None
    user = get_user_by_session(token) if token else None
    if user:
        owner = user["id"]
    elif player_id:
        owner = player_id
    if not owner:
        return {"ok": False, "message": "unauthenticated"}
    deleted = delete_open_game(game_id, owner)
    if deleted:
        async with ROOM_LOCK:
            ROOMS.pop(game_id, None)
    return {"ok": deleted, "message": None if deleted else "not your open game"}
