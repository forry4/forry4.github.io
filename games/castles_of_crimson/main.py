"""FastAPI sub-application for Castles of Crimson.

Exposes ``coc_app`` which ``games.spender.main`` mounts under ``/coc`` so the
whole site runs as one backend service. WebSocket lives at
``/coc/ws/{room}/{player}`` and REST under ``/coc/...``.

This layer is intentionally thin: it manages rooms, sockets, persistence and the
WebSocket protocol, and delegates ALL game rules to ``engine``. It mirrors the
proven patterns in ``games.spender.main`` (in-memory ``ROOMS`` under a single
``asyncio.Lock``, SQLite persistence, the stale-socket disconnect guard, and the
async opponent-turn scheduler).

Site identity (users/sessions) and the database connection are shared site-wide
via the ``core`` package (``core.db`` / ``core.auth``), imported directly at the
top — there is no circular dependency because ``core`` depends on no game. Room
persistence uses a separate ``coc_games`` table in the shared site database.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from . import board
from . import tiles
from . import bot
from . import ai as coc_ai          # MCTS opponent (aliased: `ai` is used as a local for the bot pid)

from core.db import get_db_conn, cleanup_stale_games, maybe_cleanup_games
from core.auth import (
    gen_token, get_user_by_session, validate_reconnect_token, mark_reconnect_token_used,
)
from core.config import cors_allowed_origins

LOG = logging.getLogger("games.castles_of_crimson")

# Valid AI difficulty levels; unknown values fall back to the default.
AI_DIFFICULTIES = ("normal", "hard")
DEFAULT_DIFFICULTY = "hard"


def _valid_difficulty(value) -> str:
    return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY

coc_app = FastAPI(title="Castles of Crimson API")
# Same pinned origins as the parent app (it overrides this layer when mounted, but
# keeping them aligned matters if coc_app is ever run standalone). See core.config.
coc_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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


# ── Shared-identity / DB helpers (thin aliases over the shared core package) ──
def _db():
    return get_db_conn()


def _gen_token(n: int = 12) -> str:
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
# Retention: same policy as Spender (guest 24h / registered 30d, by last activity).
cleanup_stale_games("coc_games")


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
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
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
        "ai_difficulty": state.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "boards": state.get("boards", {}),
        "sockets": {},
    }
    return True


def list_open_games() -> list[dict]:
    maybe_cleanup_games("coc_games")  # throttled (<=1/h): prune stale games during long-awake periods
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


def list_active_games() -> list[dict]:
    """All IN-PROGRESS games (any player, vs-bot or not) for the public "Active
    Games" lobby list. Public like list_open_games: the frontend pins the viewer's
    own games to the top (mine = a player id == myId) with a Resume button; others
    are read-only. Exposes player ids + whose turn (list_open_games already exposes
    host_id, so no new exposure)."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, player2_id, player2_name,
                          state_json, created_at, updated_at FROM coc_games
                   WHERE status='playing' ORDER BY updated_at DESC LIMIT 100""")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            g = (json.loads(r["state_json"] or "{}").get("game") or {})
        except Exception:
            g = {}
        out.append({
            "id": r["id"],
            "player1_id": r["player1_id"], "player1_name": r["player1_name"],
            "player2_id": r["player2_id"], "player2_name": r["player2_name"],
            "turn": g.get("turn") if isinstance(g, dict) else None,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    """Delete an OPEN game the user hosts (lobby 'cancel'). Returns True if a row
    was removed. Uses an existence check rather than cursor.rowcount: the
    driver-agnostic core.db wrapper (sqlite3 / libsql) doesn't expose rowcount,
    and libsql's rowcount semantics are unreliable -- on the prod Turso backend
    `cur.rowcount` raised, 500ing cancel. SELECT-then-DELETE is correct on both
    backends (mirrors Spender's delete_open_game)."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM coc_games WHERE id=? AND player1_id=? AND status='open'",
                (game_id, user_id))
    existed = cur.fetchone() is not None
    if existed:
        conn.execute("DELETE FROM coc_games WHERE id=? AND player1_id=? AND status='open'",
                     (game_id, user_id))
        conn.commit()
    conn.close()
    return existed


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
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "boards": room.get("boards", {}),
        "reconnect_tokens": {p: info.get("token") for p, info in room.get("meta", {}).items()} if room.get("meta") else {},
    }


def _sync_status_from_game(room: dict) -> None:
    g = room.get("game")
    if g and engine.is_over(g):
        room["status"] = "over"


# ── Opponent (bot) turn scheduler ─────────────────────────────────────────────
async def _schedule_bot_turn(room_id: str) -> None:
    """Drive the AI opponent's whole turn.

    The MCTS is heavy, so it plans the turn on a snapshot **in a thread pool**
    (mirrors Spender's `_schedule_ai_turn`) and the planned move sequence is applied
    back under the lock. A trivial-bot finisher guarantees the turn always ends, so
    the game can never deadlock even if planning fails or the state drifts."""
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        game = room.get("game")
        ai_pid = room.get("ai_player")
        if not game or not ai_pid or engine.is_over(game):
            return
        if (game.get("pending_pid") or game.get("turn")) != ai_pid:
            return
        difficulty = _valid_difficulty(room.get("ai_difficulty"))
        snapshot = coc_ai._clone_game(game)      # independent of the live game

    # Plan the bot's turn off the event loop (MCTS may take a couple seconds).
    loop = asyncio.get_event_loop()
    try:
        seq = await loop.run_in_executor(
            None,
            lambda: coc_ai.play_turn_plan(snapshot, ai_pid, difficulty=difficulty, rng=random.Random()),
        )
    except Exception:
        LOG.exception("CoC AI planning failed; finishing with the trivial bot")
        seq = None

    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        game = room.get("game")
        ai_pid = room.get("ai_player")
        if not game or not ai_pid or engine.is_over(game):
            return
        if (game.get("pending_pid") or game.get("turn")) != ai_pid:
            return
        # Apply the planned sequence to the live game (state is unchanged since the
        # snapshot — it is the bot's turn, so no human could have moved).
        if seq:
            for mv in seq:
                if engine.is_over(game) or (game.get("pending_pid") or game.get("turn")) != ai_pid:
                    break
                ok, _ = engine.apply_move(game, ai_pid, mv)
                if not ok:
                    break
        # Finisher: ensure the bot's turn actually ended (fallback / state drift).
        rng = random.Random()
        guard = 0
        while (not engine.is_over(game)
               and (game.get("pending_pid") or game.get("turn")) == ai_pid
               and guard < 200):
            guard += 1
            bot.play_turn(game, ai_pid, rng)
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
    difficulty = _valid_difficulty(msg.get("ai_difficulty"))
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
            "ai_difficulty": difficulty,
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


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    """Session token from the `Authorization: Bearer` header (keeping it out of URLs
    and logs), falling back to the legacy `?token=` query param. Mirrors the resolver
    in games.spender.main; kept local so this sub-app stays independent of Spender."""
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return token


@coc_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_games(user["id"])}


@coc_app.get("/games/active")
async def games_active():
    # Public: all in-progress games (yours + others'). Frontend pins yours on top.
    return {"ok": True, "games": list_active_games()}


@coc_app.post("/games/{game_id}/cancel")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None):
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
