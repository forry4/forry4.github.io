"""Black Castle room server, mounted by the composition root at ``/blackcastle``."""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import hashlib
import json
import logging
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core import rooms as _rooms
from core.auth import get_user_by_session
from core.build_info import build_info
from core.config import cors_allowed_origins
from core.db import cleanup_stale_games, maybe_cleanup_games

from . import bot, cards, engine, persist

LOG = logging.getLogger("blackcastle")
TABLE = "blackcastle_games"
DEFAULT_DIFFICULTY = "easy"
AI_DIFFICULTIES = ("easy",)

blackcastle_app = FastAPI(title="Black Castle API")
blackcastle_app.add_middleware(
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
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        id TEXT PRIMARY KEY, status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        player3_id TEXT, player3_name TEXT,
        player4_id TEXT, player4_name TEXT,
        max_players INTEGER DEFAULT 4,
        host_id TEXT, state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    # Development databases can contain a table created by an earlier build of
    # this package. Keep the migration additive so a restart never turns the
    # open-game list into a 500.
    cur.execute(f"PRAGMA table_info({TABLE})")
    columns = {row[1] for row in cur.fetchall()}
    if "max_players" not in columns:
        cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN max_players INTEGER DEFAULT 4")
    conn.commit()
    conn.close()


_init_db()
try:
    cleanup_stale_games(TABLE)
except Exception:  # pragma: no cover - defensive import-time cleanup
    LOG.warning("blackcastle retention sweep skipped", exc_info=True)

_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="blackcastle-db-write")
_save_conn = None


def _encode_state(state: dict) -> str:
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    return persist.expand_state(_rooms.decode_state(blob))


def _persist_row(room_id: str, status: str, seats: list[tuple[str | None, str | None]],
                 max_players: int, host: str | None, state_json: str,
                 now: int, created_at: int) -> None:
    global _save_conn
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        flat = [value for pair in seats for value in pair]
        cur.execute(f"SELECT id FROM {TABLE} WHERE id=?", (room_id,))
        if cur.fetchone() is not None:
            cur.execute(f"""UPDATE {TABLE} SET status=?,
                player1_id=?, player1_name=?, player2_id=?, player2_name=?,
                player3_id=?, player3_name=?, player4_id=?, player4_name=?,
                max_players=?, state_json=?, updated_at=? WHERE id=?""",
                        (status, *flat, max_players, state_json, now, room_id))
        else:
            cur.execute(f"""INSERT INTO {TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 player3_id,player3_name,player4_id,player4_name,host_id,
                 max_players,state_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, *flat, host, max_players, state_json, created_at, now))
        _save_conn.commit()
    except Exception:
        LOG.warning("blackcastle save failed for %s", room_id, exc_info=True)
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
    players = room.get("players", {})
    seats = list(players.items())[:4]
    seats += [(None, None)] * (4 - len(seats))
    state = {
        "players": players, "host": room.get("host"),
        "status": room.get("status", "open"), "game": room.get("game"),
        "meta": room.get("meta", {}), "max_players": room.get("max_players", 4),
        "ai_players": room.get("ai_players", []),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "created_at": room.get("created_at"),
    }
    now = int(time.time())
    created = int(room.get("created_at") or now)
    _DB_WRITE_EXEC.submit(_persist_row, room_id, room.get("status", "open"),
                          seats, room.get("max_players", 4), room.get("host"),
                          _encode_state(state), now, created)


def load_game_state(room_id: str) -> dict | None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"SELECT state_json FROM {TABLE} WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return None
    try:
        return _decode_state(row["state_json"])
    except Exception:
        LOG.warning("blackcastle state decode failed for %s", room_id, exc_info=True)
        return None


def load_game_to_memory(room_id: str) -> bool:
    state = load_game_state(room_id)
    if not isinstance(state, dict):
        return False
    ROOMS[room_id] = {
        "players": state.get("players", {}), "host": state.get("host"),
        "status": state.get("status", "open"), "game": state.get("game"),
        "meta": state.get("meta", {}), "max_players": int(state.get("max_players", 4)),
        "ai_players": list(state.get("ai_players", [])),
        "ai_difficulty": (state.get("ai_difficulty")
                          if state.get("ai_difficulty") in AI_DIFFICULTIES
                          else DEFAULT_DIFFICULTY),
        "created_at": state.get("created_at"), "sockets": {},
        "_bot_running": False,
    }
    return True


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def _position_key(game: dict) -> str:
    return hashlib.sha256(json.dumps(game, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _new_room(room_id: str, pid: str, name: str, max_players: int,
              num_bots: int, difficulty: str, ws: WebSocket) -> dict:
    players = {pid: name}
    ai_players = []
    for index in range(num_bots):
        bot_pid = f"bot{index + 1}"
        players[bot_pid] = "Easy Bot" if num_bots == 1 else f"Easy Bot {index + 1}"
        ai_players.append(bot_pid)
    room = {
        "players": players, "sockets": {pid: ws}, "status": "open", "host": pid,
        "game": None, "meta": {pid: {"token": _gen_token()}},
        "max_players": max_players, "ai_players": ai_players,
        "ai_difficulty": difficulty, "created_at": int(time.time()),
        "_bot_running": False,
    }
    for bot_pid in ai_players:
        room["meta"][bot_pid] = {"token": _gen_token()}
    ROOMS[room_id] = room
    if ai_players:
        _start_new_game(room)
    return room


def _start_new_game(room: dict) -> None:
    seats = list(room["players"].keys())
    room["game"] = engine.new_game(seats, names=room["players"],
                                    seed=_rooms.deal_rng(seats, mode="blackcastle").randrange(2 ** 31),
                                    max_players=room.get("max_players"))
    room["status"] = "playing"


def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    meta = room.get("meta", {})
    return {
        "room_id": room_id, "players": room.get("players", {}),
        "host": room.get("host"), "status": room.get("status", "open"),
        "max_players": room.get("max_players", 4),
        "ai_players": room.get("ai_players", []),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
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
    game = room.get("game")
    if not isinstance(game, dict) or engine.is_over(game):
        return None
    for pid in room.get("ai_players", []):
        if engine.legal_moves(game, pid):
            return pid
    return None


_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="blackcastle-bot")


def _choose_bot(snapshot: dict, pid: str, seed: int) -> dict | None:
    return bot.choose_move(snapshot, pid, seed)


async def _schedule_bots(room_id: str) -> None:
    loop = asyncio.get_running_loop()
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or room.get("_bot_running"):
            return
        if not _bot_pid(room):
            return
        room["_bot_running"] = True
    try:
        for _ in range(512):
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                pid = _bot_pid(room) if room else None
                if not room or not pid:
                    return
                snapshot = copy.deepcopy(room["game"])
                key = _position_key(snapshot)
            seed = _rooms.bot_seed(key, pid)
            move = await loop.run_in_executor(_BOT_EXEC, _choose_bot, snapshot, pid, seed)
            if not move:
                return
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room or _bot_pid(room) != pid or _position_key(room["game"]) != key:
                    continue
                ok, error = engine.apply_move(room["game"], pid, move)
                if not ok:
                    LOG.warning("blackcastle bot illegal move in %s: %s", room_id, error)
                    return
            # Persistence and fan-out are deliberately outside ROOM_LOCK. The
            # engine move above is tiny; compaction/DB I/O and websocket sends
            # must never stall a human seat while a bot is thinking.
            save_game(room_id)
            await broadcast_state(room_id, "move")
            await asyncio.sleep(0.32)
    finally:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if room:
                room["_bot_running"] = False


def _release_socket(room_id: str, pid: str, websocket: WebSocket) -> None:
    _rooms.release_socket(ROOMS, room_id, pid, websocket)


@blackcastle_app.websocket("/ws/{room}/{player}")
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
    room_id = normalize_room(room_id)
    name = str(msg.get("name") or "Player").strip()[:24] or "Player"
    try:
        max_players = max(2, min(4, int(msg.get("max_players", msg.get("players", 4)))))
    except (TypeError, ValueError):
        max_players = 4
    try:
        num_bots = max(0, min(max_players - 1, int(msg.get("num_bots", 1 if msg.get("vs_ai") else 0))))
    except (TypeError, ValueError):
        num_bots = 0
    difficulty = DEFAULT_DIFFICULTY if str(msg.get("ai_difficulty", "easy")).lower() not in AI_DIFFICULTIES else str(msg.get("ai_difficulty")).lower()
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return False
        room = _new_room(room_id, pid, name, max_players, num_bots, difficulty, ws)
        save_game(room_id)
        bot_turn = bool(_bot_pid(room))
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bots(room_id))
    return True


async def _handle_join(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    room_id = normalize_room(room_id)
    name = str(msg.get("name") or "Player").strip()[:24] or "Player"
    session_uid = None
    if msg.get("session_token"):
        session_uid = (get_user_by_session(msg.get("session_token")) or {}).get("id")
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
            if room.get("status") != "open" or room.get("ai_players") or len(room["players"]) >= room.get("max_players", 4):
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
    room_id = normalize_room(room_id)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        if len(room.get("players", {})) < 2:
            await _send(ws, {"type": "error", "message": "need at least two seats"})
            return
        if room.get("game"):
            await _send(ws, {"type": "error", "message": "already started"})
            return
        _start_new_game(room)
        save_game(room_id)
        bot_turn = bool(_bot_pid(room))
    await broadcast_state(room_id, "started")
    if bot_turn:
        asyncio.create_task(_schedule_bots(room_id))


async def _handle_move(ws: WebSocket, room_id: str, pid: str, msg: dict) -> None:
    room_id = normalize_room(room_id)
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
        asyncio.create_task(_schedule_bots(room_id))


async def _handle_reconnect(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    room_id = normalize_room(room_id)
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
    asyncio.create_task(_schedule_bots(room_id))
    return True


async def _handle_auth_reconnect(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    room_id = normalize_room(room_id)
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
    asyncio.create_task(_schedule_bots(room_id))
    return True


async def _handle_abandon(room_id: str, pid: str) -> None:
    room_id = normalize_room(room_id)
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        game = room.get("game")
        if isinstance(game, dict) and not engine.is_over(game):
            game["phase"] = "over"
            game["winner"] = next((seat for seat in game["players"] if seat != pid), None)
            game["pending"] = None
            engine._log(game, f"{room['players'].get(pid, pid)} leaves the castle.", kind="score")
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


def _safe_state(blob) -> dict:
    """A stored room blob, or `{}` — never a raise. The lobby lists are the one
    place a single corrupt row must not take the whole list down with it."""
    try:
        state = _decode_state(blob)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def list_open_games() -> list[dict]:
    maybe_cleanup_games(TABLE, background=True)
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, host_id, player1_name, player2_name, player3_name,
                       player4_name, max_players, state_json, updated_at FROM {TABLE}
                       WHERE status='open' ORDER BY updated_at DESC LIMIT 50""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": row["id"], "player1_name": row["player1_name"],
             "player2_name": row["player2_name"], "player3_name": row["player3_name"],
             "player4_name": row["player4_name"], "max_players": row["max_players"] or 4,
             # THE HOST AND THE SEATED IDS, which this row never carried: it named
             # seats and nothing else, so the lobby could not tell a table you own
             # (or are already sitting at) from one to join, and offered Join on a
             # seat you held — which the WS refuses as a takeover. `seatStateOf` in
             # shared/lobby.jsx reads both.
             "host_id": row["host_id"],
             "player_ids": _rooms.state_seat_ids(_safe_state(row["state_json"])),
             "updated_at": row["updated_at"]} for row in rows]


def list_user_games(user_id: str) -> list[dict]:
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id, status, player1_name, player2_name, player3_name,
                       player4_name, state_json, created_at, updated_at FROM {TABLE}
                       WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                       AND status != 'over' ORDER BY updated_at DESC LIMIT 50""", (user_id,) * 4)
    rows = cur.fetchall(); conn.close()
    out = []
    for row in rows:
        try:
            state = _decode_state(row["state_json"])
        except Exception:
            state = {}
        out.append({"id": row["id"], "status": row["status"],
                    "player1_name": row["player1_name"], "player2_name": row["player2_name"],
                    "player3_name": row["player3_name"], "player4_name": row["player4_name"],
                    "ai_difficulty": _rooms.state_ai_tier(state),
                    "updated_at": row["updated_at"], "created_at": row["created_at"]})
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id, status, player1_name, player2_name, player3_name,
                       player4_name, state_json, updated_at FROM {TABLE}
                       WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                       AND status='over' ORDER BY updated_at DESC LIMIT ?""",
                (user_id,) * 4 + (_rooms.HISTORY_LIMIT,))
    rows = cur.fetchall(); conn.close()
    out = []
    for row in rows:
        try:
            state = _decode_state(row["state_json"])
        except Exception:
            state = {}
        game = state.get("game") if isinstance(state, dict) else {}
        winner = game.get("winner") if isinstance(game, dict) else None
        players = state.get("players", {}) if isinstance(state, dict) else {}
        names = [row["player1_name"], row["player2_name"], row["player3_name"], row["player4_name"]]
        out.append({"id": row["id"], "status": row["status"],
                    "player1_name": row["player1_name"], "player2_name": row["player2_name"],
                    "player3_name": row["player3_name"], "player4_name": row["player4_name"],
                    "outcome": "won" if winner == user_id else "lost",
                    "players": [n for n in names if n], "ai_difficulty": _rooms.state_ai_tier(state),
                    "scores": (game.get("scores", {}) if isinstance(game, dict) else {}),
                    "updated_at": row["updated_at"]})
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    return _rooms.delete_open_game(TABLE, "player1_id", normalize_room(game_id), user_id)


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@blackcastle_app.get("/health")
async def health():
    return {"ok": True, "game": "blackcastle", **build_info()}


@blackcastle_app.get("/catalog")
async def catalog():
    return cards.public_catalog()


@blackcastle_app.get("/games")
async def games_open():
    return {"games": list_open_games()}


@blackcastle_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token),
                     player_id: str | None = None):
    # A GUEST HAS NO SESSION, and Active is the only list a STARTED game lands
    # in — so a friend invited by link, who backed out to the lobby to wait,
    # had no row anywhere once the host dealt. `lobby_viewer_id` in
    # core/rooms.py carries the reasoning and states exactly what the guest
    # fallback exposes; a real session always wins over the parameter.
    viewer = _rooms.lobby_viewer_id(get_user_by_session(token) if token else None, player_id)
    return {"games": list_user_games(viewer)} if viewer else {"games": []}


@blackcastle_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    return {"games": list_user_history(user["id"])} if user else {"games": []}


@blackcastle_app.post("/games/{game_id}/leave")
async def games_leave(game_id: str, token: str | None = Depends(_bearer_token),
                      player_id: str | None = None,
                      room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = get_user_by_session(token) if token else None
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


@blackcastle_app.delete("/games/{game_id}")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None,
                       room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = get_user_by_session(token) if token else None
    owner = (user or {}).get("id") or player_id
    if not owner:
        return {"ok": False, "message": "missing identity"}
    room_id = normalize_room(game_id)
    if not user:
        async with ROOM_LOCK:
            room = _ensure_room_loaded(room_id)
            if not _rooms.authorized_open_host(room or {}, owner, room_token=room_token):
                return {"ok": False, "message": "could not verify this seat"}
    ok = delete_open_game(room_id, owner)
    if ok:
        ROOMS.pop(room_id, None)
    return {"ok": ok}
