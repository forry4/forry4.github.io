"""Pinch room server, mounted by the composition root at ``/pinch``."""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import logging
import time

from fastapi import Depends, FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core import rooms as _rooms
from core import results as _results
from core.auth import get_user_by_session
from core.build_info import build_info
from core.config import cors_allowed_origins
from core.db import cleanup_stale_games, maybe_cleanup_games

from . import bot, engine, persist

LOG = logging.getLogger("pinch")
TABLE = "pinch_games"
AI_PID = "pinch-easy-bot"
DEFAULT_DIFFICULTY = "easy"
AI_DIFFICULTIES = ("easy",)

pinch_app = FastAPI(title="Pinch API")
pinch_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Room-Token"],
)

ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()
normalize_room = _rooms.normalize_room
_gen_token = _rooms.gen_room_token
_db = _rooms.db_conn
_send = _rooms.send_json


def _init_db() -> None:
    conn = _db()
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        id TEXT PRIMARY KEY, status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        host_id TEXT, state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


_init_db()
try:
    cleanup_stale_games(TABLE)
except Exception:  # pragma: no cover - defensive boot cleanup
    LOG.warning("pinch retention sweep skipped", exc_info=True)

_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="pinch-db-write")
_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="pinch-bot")
_save_conn = None


def _encode_state(state: dict) -> str:
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    return persist.expand_state(_rooms.decode_state(blob))


def _persist_row(room_id: str, status: str,
                 seats: list[tuple[str | None, str | None]], host: str | None,
                 state_json: str, now: int) -> None:
    global _save_conn
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        cur.execute(f"SELECT created_at FROM {TABLE} WHERE id=?", (room_id,))
        row = cur.fetchone()
        flat = [value for pair in seats for value in pair]
        if row is not None:
            cur.execute(f"""UPDATE {TABLE} SET status=?, player1_id=?, player1_name=?,
                player2_id=?, player2_name=?, host_id=?, state_json=?, updated_at=?
                WHERE id=?""", (status, *flat, host, state_json, now, room_id))
        else:
            cur.execute(f"""INSERT INTO {TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 host_id,state_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (room_id, status, *flat, host, state_json, now, now))
        _save_conn.commit()
    except Exception:
        LOG.exception("pinch save failed for %s", room_id)
        try:
            if _save_conn is not None:
                _save_conn.close()
        except Exception:
            pass
        _save_conn = None


def save_game(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    pids = list(room.get("players", {}))[:2]
    seats = [(pid, room["players"].get(pid)) for pid in pids]
    while len(seats) < 2:
        seats.append((None, None))
    state = {
        "players": room.get("players", {}),
        "status": room.get("status", "open"),
        "host": room.get("host"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "mode": room.get("mode", "standard"),
    }
    _DB_WRITE_EXEC.submit(
        _persist_row, room_id, room.get("status", "open"), seats,
        room.get("host"), _encode_state(state), int(time.time()))


def load_game_state(room_id: str) -> dict | None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"SELECT state_json FROM {TABLE} WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return _decode_state(row["state_json"])
    except Exception:
        LOG.warning("corrupt Pinch room %s", room_id, exc_info=True)
        return None


def load_game_to_memory(room_id: str) -> bool:
    state = load_game_state(room_id)
    if not state:
        return False
    game = state.get("game")
    if game:
        engine.validate_state(game)
    ROOMS[room_id] = {
        "players": state.get("players", {}),
        "sockets": {},
        "status": state.get("status", "open"),
        "host": state.get("host"),
        "game": game,
        "meta": state.get("meta", {}),
        "vs_ai": bool(state.get("vs_ai")),
        "ai_player": state.get("ai_player"),
        "ai_difficulty": state.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "mode": state.get("mode", (game or {}).get("mode", "standard")),
    }
    return True


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def _position_key(game: dict) -> str:
    position = {key: value for key, value in game.items() if key != "log"}
    return json.dumps(position, sort_keys=True, separators=(",", ":"))


def _start_new_game(room: dict) -> None:
    seats = list(room["players"])
    rng = _rooms.deal_rng(seats, mode=f"pinch:{room.get('mode', 'standard')}")
    room["game"] = engine.new_game(
        seats, names=room["players"], seed=rng.randrange(2 ** 31),
        mode=room.get("mode", "standard"))
    room["status"] = "playing"


def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict:
    room = ROOMS.get(room_id, {})
    meta = room.get("meta", {})
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "mode": room.get("mode", "standard"),
        "game": engine.player_view(room.get("game"), viewer_pid),
        "reconnect_tokens": ({viewer_pid: meta.get(viewer_pid, {}).get("token")}
                             if viewer_pid in meta else {}),
    }


async def broadcast_state(room_id: str, mtype: str = "room_update") -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    for pid, ws in list(room.get("sockets", {}).items()):
        try:
            await ws.send_text(json.dumps({"type": mtype,
                                           "room": mk_room_state(room_id, pid)}))
        except Exception:
            pass


def _bot_pid(room: dict) -> str | None:
    pid = room.get("ai_player")
    game = room.get("game")
    return pid if pid and game and not engine.is_over(game) and engine.legal_moves(game, pid) else None


def _choose_bot(snapshot: dict, pid: str, seed: int) -> dict | None:
    return bot.choose_move(snapshot, pid, seed)


async def _schedule_bot(room_id: str) -> None:
    loop = asyncio.get_running_loop()
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or room.get("_bot_running") or not _bot_pid(room):
            return
        room["_bot_running"] = True
    try:
        for _ in range(512):
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                pid = _bot_pid(room) if room else None
                if not pid:
                    return
                snapshot = copy.deepcopy(room["game"])
                key = _position_key(snapshot)
            move = await loop.run_in_executor(
                _BOT_EXEC, _choose_bot, snapshot, pid, _rooms.bot_seed(key, pid))
            if not move:
                return
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room or _bot_pid(room) != pid or _position_key(room["game"]) != key:
                    continue
                ok, error = engine.apply_move(room["game"], pid, move)
                if not ok:
                    LOG.warning("Pinch bot illegal move in %s: %s", room_id, error)
                    return
                if engine.is_over(room["game"]):
                    room["status"] = "over"
            save_game(room_id)
            await broadcast_state(room_id, "move")
            await asyncio.sleep(0.34)
    finally:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if room:
                room["_bot_running"] = False


def _release_socket(room_id: str, pid: str, websocket: WebSocket) -> None:
    _rooms.release_socket(ROOMS, room_id, pid, websocket)


@pinch_app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id, pid = normalize_room(room), player
    if await _rooms.reject_if_connecting_too_fast(websocket):
        return
    throttle = _rooms.MessageThrottle()
    authed = False
    try:
        while True:
            raw = await websocket.receive_text()
            if not throttle.allow():
                await websocket.close(code=1008)
                return
            try:
                msg = json.loads(raw)
            except Exception:
                await _send(websocket, {"type": "error", "message": "bad message"})
                continue
            action = msg.get("action")
            if action == "create":
                if not await _rooms.reject_room_create(websocket):
                    authed = await _handle_create(websocket, room_id, pid, msg) or authed
            elif action == "join":
                authed = await _handle_join(websocket, room_id, pid, msg) or authed
            elif action == "reconnect":
                authed = await _handle_reconnect(websocket, room_id, pid, msg) or authed
            elif action == "auth_reconnect":
                authed = await _handle_auth_reconnect(websocket, room_id, pid, msg) or authed
            elif action in {"start", "move", "abandon"}:
                if not authed:
                    await _send(websocket, {"type": "error", "message": "not authenticated for this seat"})
                    continue
                if action == "start":
                    await _handle_start(websocket, room_id, pid)
                elif action == "move":
                    await _handle_move(websocket, room_id, pid, msg)
                else:
                    await _handle_abandon(room_id, pid)
            else:
                await _send(websocket, {"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        _release_socket(room_id, pid, websocket)


async def _handle_create(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    name = str(msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    mode = str(msg.get("mode") or "standard").lower()
    if mode not in engine.MODES:
        mode = "standard"
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return False
        room = {
            "players": {pid: name}, "sockets": {pid: ws}, "status": "open",
            "host": pid, "game": None, "meta": {pid: {"token": _gen_token()}},
            "vs_ai": vs_ai, "ai_player": None,
            "ai_difficulty": DEFAULT_DIFFICULTY, "mode": mode,
        }
        ROOMS[room_id] = room
        if vs_ai:
            room["players"][AI_PID] = "Easy Bot"
            room["ai_player"] = AI_PID
            _start_new_game(room)
        save_game(room_id)
        bot_turn = bool(_bot_pid(room))
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bot(room_id))
    return True


async def _handle_join(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    name = str(msg.get("name") or "Player").strip()[:24] or "Player"
    sess = msg.get("session_token")
    session_uid = (get_user_by_session(sess) or {}).get("id") if sess else None
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        if pid in room["players"]:
            if session_uid != pid:
                await _send(ws, {"type": "error", "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            if room.get("status") != "open" or room.get("vs_ai") or len(room["players"]) >= 2:
                await _send(ws, {"type": "error", "message": "room is full or already started"})
                return False
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room.setdefault("sockets", {})[pid] = ws
        save_game(room_id)
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
    await broadcast_state(room_id)
    return True


async def _handle_start(ws: WebSocket, room_id: str, pid: str) -> None:
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        if len(room.get("players", {})) != 2:
            await _send(ws, {"type": "error", "message": "need two seats"})
            return
        if room.get("game"):
            await _send(ws, {"type": "error", "message": "already started"})
            return
        _start_new_game(room)
        save_game(room_id)
        bot_turn = bool(_bot_pid(room))
    await broadcast_state(room_id, "started")
    if bot_turn:
        asyncio.create_task(_schedule_bot(room_id))


async def _handle_move(ws: WebSocket, room_id: str, pid: str, msg: dict) -> None:
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            await _send(ws, {"type": "error", "message": "game not started"})
            return
        ok, error = engine.apply_move(room["game"], pid, msg.get("move") or {})
        if not ok:
            await _send(ws, {"type": "error", "message": error or "illegal move"})
            return
        if engine.is_over(room["game"]):
            room["status"] = "over"
        save_game(room_id)
        bot_turn = bool(_bot_pid(room))
    await broadcast_state(room_id, "move")
    if bot_turn:
        asyncio.create_task(_schedule_bot(room_id))


async def _handle_reconnect(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        token = room.get("meta", {}).get(pid, {}).get("token") if room else None
        if not room or not token or msg.get("token") != token:
            await _send(ws, {"type": "error", "message": "bad reconnect token"})
            return False
        room.setdefault("sockets", {})[pid] = ws
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
    await broadcast_state(room_id)
    asyncio.create_task(_schedule_bot(room_id))
    return True


async def _handle_auth_reconnect(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    user = get_user_by_session(msg.get("session_token")) if msg.get("session_token") else None
    if not user or user.get("id") != pid:
        await _send(ws, {"type": "error", "message": "bad session"})
        return False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "no such seat"})
            return False
        room.setdefault("sockets", {})[pid] = ws
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
    await broadcast_state(room_id)
    asyncio.create_task(_schedule_bot(room_id))
    return True


async def _handle_abandon(room_id: str, pid: str) -> None:
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            return
        engine.concede(room["game"], pid)
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


def _safe_state(blob) -> dict:
    try:
        state = _decode_state(blob)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def list_open_games() -> list[dict]:
    maybe_cleanup_games(TABLE, background=True)
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id,host_id,player1_name,player2_name,state_json,updated_at
                    FROM {TABLE} WHERE status='open'
                    ORDER BY updated_at DESC LIMIT 50""")
    rows = cur.fetchall(); conn.close()
    result = []
    for row in rows:
        state = _safe_state(row["state_json"])
        if not state:
            continue
        result.append({
            "id": row["id"], "host_id": row["host_id"],
            "player1_name": row["player1_name"], "player2_name": row["player2_name"],
            "player_ids": _rooms.state_seat_ids(state), "max_players": 2,
            "mode": state.get("mode", "standard"), "updated_at": row["updated_at"],
        })
    return result


def list_user_games(user_id: str) -> list[dict]:
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id,status,player1_id,player1_name,player2_id,player2_name,state_json,created_at,updated_at
                    FROM {TABLE} WHERE (player1_id=? OR player2_id=?) AND status!='over'
                    ORDER BY updated_at DESC LIMIT 50""", (user_id, user_id))
    rows = cur.fetchall(); conn.close()
    result = []
    for row in rows:
        state = _safe_state(row["state_json"])
        if not state:
            continue
        game = state.get("game") or {}
        result.append({
            "id": row["id"], "status": row["status"],
            "you_are_p1": row["player1_id"] == user_id,
            "opponent": row["player2_name"] if row["player1_id"] == user_id else row["player1_name"],
            "player1_id": row["player1_id"], "player2_id": row["player2_id"],
            "player1_name": row["player1_name"], "player2_name": row["player2_name"],
            "ai_difficulty": _rooms.state_ai_tier(state),
            "mode": state.get("mode", game.get("mode", "standard")),
            "your_turn": bool(engine.legal_moves(game, user_id)) if game else False,
            "turn": game.get("turn_number"),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        })
    return result


def list_user_history(user_id: str) -> list[dict]:
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id,player1_id,player1_name,player2_id,player2_name,state_json,updated_at
                    FROM {TABLE} WHERE (player1_id=? OR player2_id=?) AND status='over'
                    ORDER BY updated_at DESC LIMIT ?""",
                (user_id, user_id, _rooms.HISTORY_LIMIT))
    rows = cur.fetchall(); conn.close()
    result = []
    for row in rows:
        state = _safe_state(row["state_json"])
        if not state or not state.get("game"):
            continue
        game = state["game"]
        win = game.get("winner")
        result.append({
            "id": row["id"], "status": "over",
            "you_are_p1": row["player1_id"] == user_id,
            "opponent": row["player2_name"] if row["player1_id"] == user_id else row["player1_name"],
            "player1_name": row["player1_name"], "player2_name": row["player2_name"],
            "mode": state.get("mode", game.get("mode", "standard")),
            "ai_difficulty": _rooms.state_ai_tier(state),
            "outcome": "draw" if win is None else ("won" if win == user_id else "lost"),
            "scores": game.get("removed", {}), "turns": game.get("turn_number", 0),
            "updated_at": row["updated_at"],
        })
    return result


def _standings(state: dict) -> dict | None:
    """Who won a finished game, for the profile (core.results). The score is rings
    removed; no winner is a draw."""
    game = state.get("game") or {}
    if not isinstance(game, dict) or not game.get("players") or not engine.is_over(game):
        return None
    order = [p for p in (state.get("players") or {}) if p in game["players"]]
    win = game.get("winner")
    return _results.standings(state, order, [win] if win else [], draw=win is None,
                              scores=game.get("removed") or {},
                              mode=state.get("mode", game.get("mode", "standard")))


_results.register("pinch", TABLE, decode=_decode_state, standings=_standings)


def delete_open_game(game_id: str, user_id: str) -> bool:
    return _rooms.delete_open_game(TABLE, "player1_id", normalize_room(game_id), user_id)


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@pinch_app.get("/health")
async def health():
    return {"ok": True, "game": "pinch", **build_info()}


@pinch_app.get("/games")
def games_open():
    return {"games": list_open_games()}


@pinch_app.get("/games/mine")
def games_mine(token: str | None = Depends(_bearer_token),
               player_id: str | None = None):
    viewer = _rooms.lobby_viewer_id(get_user_by_session(token) if token else None, player_id)
    return {"games": list_user_games(viewer)} if viewer else {"games": []}


@pinch_app.get("/games/history")
def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    return {"games": list_user_history(user["id"])} if user else {"games": []}


@pinch_app.post("/games/{game_id}/leave")
async def games_leave(game_id: str, token: str | None = Depends(_bearer_token),
                      player_id: str | None = None,
                      room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = (await asyncio.to_thread(get_user_by_session, token)) if token else None
    room_id = normalize_room(game_id)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        ok, message = _rooms.remove_open_seat(
            room or {}, player_id or "", room_token=room_token,
            session_uid=(user or {}).get("id"))
        if not ok:
            return {"ok": False, "message": message}
        save_game(room_id)
    await broadcast_state(room_id)
    return {"ok": True}


@pinch_app.delete("/games/{game_id}")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None,
                       room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = (await asyncio.to_thread(get_user_by_session, token)) if token else None
    owner = (user or {}).get("id") or player_id
    if not owner:
        return {"ok": False, "message": "missing identity"}
    room_id = normalize_room(game_id)
    if not user:
        async with ROOM_LOCK:
            room = _ensure_room_loaded(room_id)
            if not _rooms.authorized_open_host(room or {}, owner, room_token=room_token):
                return {"ok": False, "message": "could not verify this seat"}
    ok = await asyncio.to_thread(delete_open_game, room_id, owner)
    if ok:
        ROOMS.pop(room_id, None)
    return {"ok": ok}
