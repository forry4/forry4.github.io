"""Pip Market room server, mounted by the composition root at ``/pipmarket``.

Two to four seats, any of which (bar the host's) may be a bot. A table whose
seats are all filled at create — the host plus its bots — deals at once; one
with seats left for friends waits in the lobby until the host starts it, and
any seat still empty then is simply not dealt in.
"""

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
from core import results as _results
from core.auth import get_user_by_session
from core.build_info import build_info
from core.config import cors_allowed_origins
from core.db import cleanup_stale_games, maybe_cleanup_games

from . import bot, engine, persist

LOG = logging.getLogger("pipmarket")
TABLE = "pipmarket_games"
DEFAULT_DIFFICULTY = "normal"
AI_DIFFICULTIES = ("normal",)
# A bot pauses this long before each move so every die can be watched landing.
BOT_THINK = 0.85

pipmarket_app = FastAPI(title="Pip Market API")
pipmarket_app.add_middleware(
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
        player3_id TEXT, player3_name TEXT,
        player4_id TEXT, player4_name TEXT,
        max_players INTEGER DEFAULT 4,
        host_id TEXT, state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


_init_db()
try:
    cleanup_stale_games(TABLE)
except Exception:  # pragma: no cover - defensive boot cleanup
    LOG.warning("pipmarket retention sweep skipped", exc_info=True)

_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="pipmarket-db-write")
_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="pipmarket-bot")
_save_conn = None


def _encode_state(state: dict) -> str:
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    return persist.expand_state(_rooms.decode_state(blob))


def _valid_max_players(value) -> int:
    try:
        return max(engine.MIN_PLAYERS, min(engine.MAX_PLAYERS, int(value)))
    except (TypeError, ValueError):
        return engine.MAX_PLAYERS


def _persist_row(room_id: str, status: str, seats: list[tuple[str | None, str | None]],
                 max_players: int, host: str | None, state_json: str, now: int) -> None:
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
                max_players=?, host_id=?, state_json=?, updated_at=? WHERE id=?""",
                        (status, *flat, max_players, host, state_json, now, room_id))
        else:
            cur.execute(f"""INSERT INTO {TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 player3_id,player3_name,player4_id,player4_name,max_players,
                 host_id,state_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, *flat, max_players, host, state_json, now, now))
        _save_conn.commit()
    except Exception:
        LOG.exception("pipmarket save failed for %s", room_id)
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
        "players": players,
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "max_players": room.get("max_players", 4),
        "ai_players": room.get("ai_players", []),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
    }
    _DB_WRITE_EXEC.submit(
        _persist_row, room_id, room.get("status", "open"), seats,
        room.get("max_players", 4), room.get("host"), _encode_state(state), int(time.time()))


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
        LOG.warning("corrupt Pip Market room %s", room_id, exc_info=True)
        return None


def load_game_to_memory(room_id: str) -> bool:
    state = load_game_state(room_id)
    if not isinstance(state, dict):
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
        "max_players": _valid_max_players(state.get("max_players")),
        "ai_players": list(state.get("ai_players", [])),
        "ai_difficulty": (state.get("ai_difficulty")
                          if state.get("ai_difficulty") in AI_DIFFICULTIES
                          else DEFAULT_DIFFICULTY),
        "_bot_running": False,
    }
    return True


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def _position_key(game: dict) -> str:
    position = {key: value for key, value in game.items() if key != "log"}
    return hashlib.sha256(json.dumps(position, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _start_new_game(room: dict) -> None:
    seats = list(room["players"])
    rng = _rooms.deal_rng(seats, mode="pipmarket")
    room["game"] = engine.new_game(seats, names=room["players"],
                                   seed=rng.randrange(2 ** 31))
    room["status"] = "playing"


def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    meta = room.get("meta", {})
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
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
    pid = engine.to_act(room.get("game"))
    return pid if pid and pid in (room.get("ai_players") or ()) else None


def _choose_bot(snapshot: dict, pid: str, seed: int) -> dict | None:
    return bot.choose_move(snapshot, pid, seed)


async def _schedule_bots(room_id: str) -> None:
    loop = asyncio.get_running_loop()
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or room.get("_bot_running") or not _bot_pid(room):
            return
        room["_bot_running"] = True
    try:
        for _ in range(1024):
            await asyncio.sleep(BOT_THINK)
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
                    LOG.warning("Pip Market bot illegal move in %s: %s", room_id, error)
                    return
                if engine.is_over(room["game"]):
                    room["status"] = "over"
            # Persistence and fan-out stay outside ROOM_LOCK.
            save_game(room_id)
            await broadcast_state(room_id, "move")
    finally:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if room:
                room["_bot_running"] = False


def _release_socket(room_id: str, pid: str, websocket: WebSocket) -> None:
    _rooms.release_socket(ROOMS, room_id, pid, websocket)


@pipmarket_app.websocket("/ws/{room}/{player}")
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
    max_players = _valid_max_players(msg.get("max_players", 2))
    try:
        num_bots = max(0, min(max_players - 1, int(msg.get("num_bots", 0))))
    except (TypeError, ValueError):
        num_bots = 0
    difficulty = str(msg.get("ai_difficulty") or DEFAULT_DIFFICULTY).lower()
    if difficulty not in AI_DIFFICULTIES:
        difficulty = DEFAULT_DIFFICULTY
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return False
        players = {pid: name}
        ai_players = []
        for index in range(num_bots):
            bot_pid = f"pm-bot-{index + 1}"
            players[bot_pid] = "Bot" if num_bots == 1 else f"Bot {index + 1}"
            ai_players.append(bot_pid)
        room = {
            "players": players, "sockets": {pid: ws}, "status": "open",
            "host": pid, "game": None, "meta": {pid: {"token": _gen_token()}},
            "max_players": max_players, "ai_players": ai_players,
            "ai_difficulty": difficulty, "_bot_running": False,
        }
        ROOMS[room_id] = room
        if len(players) >= max_players:
            _start_new_game(room)
        save_game(room_id)
        bot_turn = bool(_bot_pid(room))
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bots(room_id))
    return True


async def _handle_join(ws: WebSocket, room_id: str, pid: str, msg: dict) -> bool:
    name = str(msg.get("name") or "Player").strip()[:24] or "Player"
    sess = msg.get("session_token")
    session_uid = ((await asyncio.to_thread(get_user_by_session, sess)) or {}).get("id") if sess else None
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        if pid in room["players"]:
            if pid in (room.get("ai_players") or ()) or session_uid != pid:
                await _send(ws, {"type": "error", "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            if room.get("status") != "open" or len(room["players"]) >= room.get("max_players", 4):
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
        if len(room.get("players", {})) < engine.MIN_PLAYERS:
            await _send(ws, {"type": "error", "message": "need at least two players"})
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
    user = (await asyncio.to_thread(get_user_by_session, msg.get("session_token"))) if msg.get("session_token") else None
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
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            return
        engine.concede(room["game"], pid)
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


def _safe_state(blob) -> dict:
    """A stored room blob, or `{}` — never a raise: one corrupt row must not take
    a whole lobby list down with it."""
    try:
        state = _decode_state(blob)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def _seats(state: dict, user_id: str | None) -> list[dict]:
    return [{"name": name, "you": pid == user_id}
            for pid, name in (state.get("players") or {}).items()]


def list_open_games() -> list[dict]:
    maybe_cleanup_games(TABLE, background=True)
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id, host_id, player1_name, state_json, updated_at
                    FROM {TABLE} WHERE status='open'
                    ORDER BY updated_at DESC LIMIT 50""")
    rows = cur.fetchall(); conn.close()
    out = []
    for row in rows:
        state = _safe_state(row["state_json"])
        if not state:
            continue
        out.append({
            "id": row["id"], "host_id": row["host_id"], "host_name": row["player1_name"],
            "player_count": len(state.get("players") or {}) or 1,
            "player_ids": _rooms.state_seat_ids(state),
            "max_players": _valid_max_players(state.get("max_players")),
            "bots": len(state.get("ai_players") or []),
            "updated_at": row["updated_at"],
        })
    return out


def list_user_games(user_id: str) -> list[dict]:
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id, status, state_json, created_at, updated_at FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                    AND status != 'over' ORDER BY updated_at DESC LIMIT 50""", (user_id,) * 4)
    rows = cur.fetchall(); conn.close()
    out = []
    for row in rows:
        state = _safe_state(row["state_json"])
        if not state:
            continue
        game = state.get("game") or {}
        out.append({
            "id": row["id"], "status": row["status"],
            "seats": _seats(state, user_id),
            "ai_difficulty": _rooms.state_ai_tier(state),
            "round": game.get("round"),
            "phase": game.get("phase"),
            "your_turn": engine.to_act(game) == user_id if game else False,
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db(); cur = conn.cursor()
    cur.execute(f"""SELECT id, state_json, updated_at FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                    AND status='over' ORDER BY updated_at DESC LIMIT ?""",
                (user_id,) * 4 + (_rooms.HISTORY_LIMIT,))
    rows = cur.fetchall(); conn.close()
    out = []
    for row in rows:
        state = _safe_state(row["state_json"])
        game = state.get("game") if state else None
        if not isinstance(game, dict) or not game.get("players"):
            continue
        names = state.get("players") or {}
        winners = game.get("winners") or []
        final = game.get("final") or {}
        if user_id in winners:
            outcome = "won" if len(winners) == 1 else "tied"
        else:
            outcome = "lost"
        out.append({
            "id": row["id"], "status": "over", "outcome": outcome,
            "standings": sorted(
                ({"name": names.get(p, p), "score": final.get(p), "you": p == user_id,
                  "won": p in winners} for p in game.get("players", [])),
                key=lambda s: not s["you"]),
            "rounds": game.get("round"),
            "ai_difficulty": _rooms.state_ai_tier(state),
            "updated_at": row["updated_at"],
        })
    return out


def _standings(state: dict) -> dict | None:
    """Who won a finished game, for the profile (core.results). A shared top
    score is a draw between the players who share it."""
    game = state.get("game") or {}
    if not isinstance(game, dict) or not game.get("players") or not engine.is_over(game):
        return None
    return _results.standings(state, list(game["players"]), game.get("winners") or [],
                              scores=game.get("final") or {})


_results.register("pipmarket", TABLE, decode=_decode_state, standings=_standings,
                  seat_cols=("player1_id", "player2_id", "player3_id", "player4_id"))


def delete_open_game(game_id: str, user_id: str) -> bool:
    return _rooms.delete_open_game(TABLE, "player1_id", normalize_room(game_id), user_id)


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@pipmarket_app.get("/health")
async def health():
    return {"ok": True, "game": "pipmarket", **build_info()}


@pipmarket_app.get("/games")
def games_open():
    return {"games": list_open_games()}


@pipmarket_app.get("/games/mine")
def games_mine(token: str | None = Depends(_bearer_token),
               player_id: str | None = None):
    viewer = _rooms.lobby_viewer_id(get_user_by_session(token) if token else None, player_id)
    return {"games": list_user_games(viewer)} if viewer else {"games": []}


@pipmarket_app.get("/games/history")
def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    return {"games": list_user_history(user["id"])} if user else {"games": []}


@pipmarket_app.post("/games/{game_id}/leave")
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


@pipmarket_app.delete("/games/{game_id}")
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
