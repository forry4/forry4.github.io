"""SecretNames room server, mounted by the composition root at ``/secretnames``.

The same scaffolding every game's `main.py` builds — in-memory ``ROOMS`` under a
single ``ROOM_LOCK``, save/load, per-recipient broadcast, the stale-socket guard
— with the generic half taken from ``core.rooms``.

TWO SEATS AND NO BOT, and both are deliberate rather than unfinished:

  * SecretNames is a COOPERATIVE two-player game. There is no third seat to add
    and no winner to award, so `abandon` ends the run rather than conceding it.
  * A bot would have to give and read semantic clues over an arbitrary 25-word
    board, which is a word-association model, not a search. Where Wolf? is the
    existing precedent for a game that ships without one, and the shared AI
    rosters (`shared/tests/test_ai_difficulty_memory.py`,
    `test_lobby_bot_tier.py`) derive themselves from the tree, so this game
    drops out of both on its own and joins them the day it gains a ladder.

THE BROADCAST IS PER-RECIPIENT AND THAT IS THE WHOLE GAME. `broadcast_state`
rebuilds the payload for every socket keyed on that socket's pid, because
`engine.player_view` ships only the viewer's own key side. A single shared
payload would hand both key cards to both players and the game would still look
completely normal from either seat.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
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

from . import engine, persist

LOG = logging.getLogger("secretnames")
TABLE = "secretnames_games"

secretnames_app = FastAPI(title="SecretNames API")
secretnames_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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
        host_id TEXT, state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


_init_db()
try:
    cleanup_stale_games(TABLE)
except Exception:  # pragma: no cover - defensive import-time cleanup
    LOG.warning("secretnames retention sweep skipped", exc_info=True)

_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="secretnames-db-write")
_save_conn = None


def _encode_state(state: dict) -> str:
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    return persist.expand_state(_rooms.decode_state(blob))


def _persist_row(room_id: str, status: str, seats: list[tuple[str | None, str | None]],
                 host: str | None, state_json: str, now: int, created_at: int) -> None:
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
                state_json=?, updated_at=? WHERE id=?""",
                        (status, *flat, state_json, now, room_id))
        else:
            cur.execute(f"""INSERT INTO {TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 host_id,state_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, *flat, host, state_json, created_at, now))
        _save_conn.commit()
    except Exception:
        LOG.warning("secretnames save failed for %s", room_id, exc_info=True)
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
    seats = list(players.items())[:2]
    seats += [(None, None)] * (2 - len(seats))
    state = {
        "players": players, "host": room.get("host"),
        "status": room.get("status", "open"), "game": room.get("game"),
        "meta": room.get("meta", {}), "turns": room.get("turns", engine.DEFAULT_TURNS),
        "created_at": room.get("created_at"),
    }
    now = int(time.time())
    created = int(room.get("created_at") or now)
    _DB_WRITE_EXEC.submit(_persist_row, room_id, room.get("status", "open"),
                          seats, room.get("host"), _encode_state(state), now, created)


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
        LOG.warning("secretnames state decode failed for %s", room_id, exc_info=True)
        return None


def load_game_to_memory(room_id: str) -> bool:
    state = load_game_state(room_id)
    if not isinstance(state, dict):
        return False
    ROOMS[room_id] = {
        "players": state.get("players", {}), "host": state.get("host"),
        "status": state.get("status", "open"), "game": state.get("game"),
        "meta": state.get("meta", {}),
        "turns": int(state.get("turns") or engine.DEFAULT_TURNS),
        "created_at": state.get("created_at"), "sockets": {},
    }
    return True


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def _start_new_game(room: dict) -> None:
    seats = list(room["players"].keys())
    room["game"] = engine.new_game(
        seats, names=dict(room["players"]),
        rng=_rooms.deal_rng(seats, mode="secretnames"),
        turns=int(room.get("turns") or engine.DEFAULT_TURNS))
    room["status"] = "playing"


def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    """The payload ONE socket receives. Rebuilt per recipient — see the module
    docstring; a shared payload here hands both key cards to both players."""
    room = ROOMS.get(room_id, {})
    meta = room.get("meta", {})
    return {
        "room_id": room_id, "players": room.get("players", {}),
        "host": room.get("host"), "status": room.get("status", "open"),
        "turns": room.get("turns", engine.DEFAULT_TURNS),
        "game": engine.player_view(room.get("game"), viewer_pid),
        # Per-recipient, never the whole map: the token is a credential that
        # replays as `{"action":"reconnect"}` for a full seat takeover.
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


def _release_socket(room_id: str, pid: str, websocket: WebSocket) -> None:
    _rooms.release_socket(ROOMS, room_id, pid, websocket)


@secretnames_app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id, pid = normalize_room(room), player
    if await _rooms.reject_if_connecting_too_fast(websocket):
        return
    throttle = _rooms.MessageThrottle()
    # SEAT IDENTITY IS BOUND BEFORE ANY ACTION. `player` is a client-supplied
    # path segment and every pid is broadcast in the public players map, so a
    # socket must PROVE it owns its seat before it can act OR receive that
    # seat's view — which here is the seat's KEY CARD. The socket is also not
    # registered in `room["sockets"]` until that handshake, so merely opening
    # one claiming a victim's pid returns nothing.
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
                    await _send(websocket, {"type": "error",
                                            "message": "not authenticated for this seat"})
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
        turns = int(msg.get("turns", engine.DEFAULT_TURNS))
    except (TypeError, ValueError):
        turns = engine.DEFAULT_TURNS
    if turns not in engine.TURN_OPTIONS:
        turns = engine.DEFAULT_TURNS
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return False
        ROOMS[room_id] = {
            "players": {pid: name}, "sockets": {pid: ws}, "status": "open",
            "host": pid, "game": None, "meta": {pid: {"token": _gen_token()}},
            "turns": turns, "created_at": int(time.time()),
        }
        save_game(room_id)
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, pid)})
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
            # An existing seat may only be re-entered by its owner: a matching
            # session proves it. Anyone else is told to reconnect (which needs
            # the room token) rather than being handed the seat's key card.
            if session_uid != pid:
                await _send(ws, {"type": "error",
                                 "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            if room.get("status") != "open" or len(room["players"]) >= 2:
                await _send(ws, {"type": "error", "message": "this table is full"})
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
    """THE HOST DEALS, rather than the second seat dealing by arriving.

    The first version auto-started the moment the table filled, on the reasoning
    that a two-seat co-op has no host decision left to make. It does have one:
    the shared `WaitingRoom` is where a player reads the invite link, watches
    their partner actually arrive, and only then commits — and skipping it
    dropped whoever was already looking at that screen straight onto a live
    board. It is also the shape every other game on the site has, which is the
    stronger of the two arguments.
    """
    room_id = normalize_room(room_id)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        if room.get("game"):
            await _send(ws, {"type": "error", "message": "already started"})
            return
        if len(room.get("players", {})) < 2:
            await _send(ws, {"type": "error", "message": "SecretNames needs two players"})
            return
        _start_new_game(room)
        save_game(room_id)
    await broadcast_state(room_id, "started")


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
    await broadcast_state(room_id, "move")


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
    return True


async def _handle_abandon(room_id: str, pid: str) -> None:
    room_id = normalize_room(room_id)
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        game = room.get("game")
        if isinstance(game, dict) and not engine.is_over(game):
            engine.abandon(game, pid)
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


# ─── Lobby lists ─────────────────────────────────────────────────────────────
def _safe_state(blob) -> dict:
    """A stored room blob, or `{}` — never a raise. The lobby lists are the one
    place where a single unreadable row must not 500 the whole list."""
    try:
        state = _decode_state(blob)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def _row_summary(state: dict) -> dict:
    game = state.get("game") if isinstance(state, dict) else None
    if not isinstance(game, dict):
        return {"outcome": "unfinished", "found": 0, "turns_used": 0,
                "turns_max": engine.DEFAULT_TURNS, "loss_reason": None}
    turns_max = int(game.get("turns_max") or engine.DEFAULT_TURNS)
    return {
        "outcome": "won" if game.get("phase") == "won" else "lost",
        "found": len(game.get("found") or []),
        "turns_used": turns_max - int(game.get("turns_remaining") or 0),
        "turns_max": turns_max,
        "loss_reason": game.get("loss_reason"),
    }


def list_open_games() -> list[dict]:
    maybe_cleanup_games(TABLE, background=True)
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, player1_id, player1_name, player2_name, state_json, updated_at
                    FROM {TABLE} WHERE status='open'
                    ORDER BY updated_at DESC LIMIT 50""")
    rows = cur.fetchall()
    conn.close()
    out = []
    for row in rows:
        state = _safe_state(row["state_json"])
        out.append({"id": row["id"], "host_id": row["player1_id"],
                    "player1_name": row["player1_name"],
                    "player2_name": row["player2_name"],
                    # WHO IS ALREADY SEATED, which is what lets the Open row say
                    # "Return" to somebody who holds a seat in it rather than
                    # "Join". A join onto an occupied seat is a takeover and the
                    # WS rightly refuses it, so that row was otherwise the one
                    # row that could not carry them back in.
                    "player_ids": _rooms.state_seat_ids(state),
                    # TWO SEATS, ALWAYS, stated rather than implied: the
                    # frontend's "full" answer needs a cap to compare against.
                    "max_players": 2,
                    "turns": int(state.get("turns") or engine.DEFAULT_TURNS),
                    "updated_at": row["updated_at"]})
    return out


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, status, player1_id, player1_name, player2_name,
                       state_json, created_at, updated_at FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=?) AND status != 'over'
                    ORDER BY updated_at DESC LIMIT 50""", (user_id, user_id))
    rows = cur.fetchall()
    conn.close()
    out = []
    for row in rows:
        try:
            state = _decode_state(row["state_json"])
        except Exception:
            state = {}
        game = state.get("game") if isinstance(state, dict) else None
        out.append({
            "id": row["id"], "status": row["status"], "host_id": row["player1_id"],
            "player1_name": row["player1_name"], "player2_name": row["player2_name"],
            "you_are_host": row["player1_id"] == user_id,
            "turns": int(state.get("turns") or engine.DEFAULT_TURNS),
            "found": len((game or {}).get("found") or []),
            "turns_remaining": (game or {}).get("turns_remaining"),
            "updated_at": row["updated_at"], "created_at": row["created_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, status, player1_name, player2_name, state_json,
                       updated_at FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=?) AND status='over'
                    ORDER BY updated_at DESC LIMIT ?""",
                (user_id, user_id, _rooms.HISTORY_LIMIT))
    rows = cur.fetchall()
    conn.close()
    out = []
    for row in rows:
        try:
            state = _decode_state(row["state_json"])
        except Exception:
            state = {}
        summary = _row_summary(state)
        out.append({"id": row["id"], "status": row["status"],
                    "player1_name": row["player1_name"],
                    "player2_name": row["player2_name"],
                    "updated_at": row["updated_at"], **summary})
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    return _rooms.delete_open_game(TABLE, "player1_id", normalize_room(game_id), user_id)


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@secretnames_app.get("/health")
async def health():
    return {"ok": True, "game": "secretnames", **build_info()}


@secretnames_app.get("/games")
async def games_open():
    return {"games": list_open_games()}


@secretnames_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token),
                     player_id: str | None = None):
    # A GUEST HAS NO SESSION, and Active is the only list a STARTED game lands
    # in — so a partner invited by link, who backed out to the lobby to wait,
    # would have no row anywhere once the host dealt. `lobby_viewer_id` carries
    # the reasoning and states exactly what the guest fallback exposes; a real
    # session always wins over the parameter.
    viewer = _rooms.lobby_viewer_id(get_user_by_session(token) if token else None, player_id)
    return {"games": list_user_games(viewer)} if viewer else {"games": []}


@secretnames_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    return {"games": list_user_history(user["id"])} if user else {"games": []}


@secretnames_app.delete("/games/{game_id}")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "message": "not signed in"}
    ok = delete_open_game(game_id, user["id"])
    if ok:
        ROOMS.pop(normalize_room(game_id), None)
    return {"ok": ok}
