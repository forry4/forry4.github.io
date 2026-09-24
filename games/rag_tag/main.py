"""Rag Tag room server — mounted at /ragtag.

The same scaffolding as the other six games: an in-memory ``ROOMS`` dict under a
single lock, one WebSocket per room+player, and every rule delegated to
``engine.py``. The generic half lives in ``core/rooms.py`` and is aliased below
under the historical private names.

Two things here are load-bearing and were expensive to learn elsewhere:

* **Seat identity is bound.** The ``player`` path segment is client-supplied and
  every pid is broadcast in the public players map, so a socket must PROVE it
  owns its pid before it can act as that seat or receive that seat's view.
  ``authed`` flips true only via create / join-as-a-new-seat / join-with-a-
  matching-session-token / reconnect-with-the-room-token / auth_reconnect, and
  NOTHING registers the socket in ``room["sockets"]`` before that handshake.
* **Broadcasts are redacted per recipient.** ``mk_room_state`` rebuilds the game
  through ``engine.player_view`` for each socket's own pid, so the opponent's
  Fight Deck ORDER -- which in this game is very nearly the whole of the hidden
  information -- and both Build Decks never reach a wire that should not see them.

WHAT IS DIFFERENT HERE. Rag Tag is SIMULTANEOUS: both players submit at once and
the phase advances when both are in. So there is no single seat on turn, and the
server asks ``engine.may_act`` rather than comparing against a turn pid. The bot
is scheduled off the same question, in a loop, because it can owe a move at the
same moment the human does.
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
from core import results as _results
from core.auth import get_user_by_session
from core.build_info import build_info
from core.config import cors_allowed_origins
from core.db import cleanup_stale_games, get_db_conn, maybe_cleanup_games

from . import bot, engine, persist
from .fighters import FIGHTERS, ROSTER

LOG = logging.getLogger("ragtag")

TABLE = "ragtag_games"
AI_PID = "bot"

#: A floor on how fast the bot answers. Without it a vs-bot game resolves the
#: whole simultaneous submission the instant you click, which reads as a bug.
BOT_FLOOR_SECONDS = 0.45

ragtag_app = FastAPI(title="Rag Tag API")
ragtag_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Room-Token"],
)

ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()

# ── Shared room-server primitives (core/rooms.py) ────────────────────────────
normalize_room = _rooms.normalize_room
_gen_token = _rooms.gen_room_token
_db = _rooms.db_conn
_send = _rooms.send_json


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def ragtag_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        id TEXT PRIMARY KEY,
        status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


ragtag_init_db()
try:
    # Retention: guest 24h / registered 30d / open lobbies 48h, by last activity.
    # Guarded because this runs at IMPORT time and joins `users` — in a fresh
    # checkout that table may not exist yet, and a retention sweep must never
    # stop the module (or every test that imports it) from loading.
    cleanup_stale_games(TABLE)
except Exception as _cleanup_err:  # pragma: no cover - environment-dependent
    LOG.warning("ragtag retention sweep skipped at import: %s", _cleanup_err)


# ── Persistence ──────────────────────────────────────────────────────────────
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="ragtag-db-write")
_save_conn = None  # only ever touched by the write-executor thread


def _persist_row(room_id, status, p1id, p1name, p2id, p2name, host,
                 state_json, now, created_at) -> None:
    global _save_conn
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        cur.execute(f"SELECT id FROM {TABLE} WHERE id=?", (room_id,))
        if cur.fetchone() is not None:
            cur.execute(f"""UPDATE {TABLE} SET status=?, player2_id=?, player2_name=?,
                            state_json=?, updated_at=? WHERE id=?""",
                        (status, p2id, p2name, state_json, now, room_id))
        else:
            cur.execute(f"""INSERT INTO {TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 host_id,state_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, p1id, p1name, p2id, p2name, host,
                         state_json, created_at, now))
        _save_conn.commit()
    except Exception:  # noqa: BLE001 — a save must never crash the room
        LOG.warning("ragtag save failed for %s; dropping connection",
                    room_id, exc_info=True)
        try:
            if _save_conn is not None:
                _save_conn.close()
        except Exception:
            pass
        _save_conn = None


def _encode_state(state: dict) -> str:
    """The ONLY write path into state_json — compact, then the shared codec."""
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    """The ONLY read path out of state_json. Every reader funnels through here,
    offline tools included, or a compacted blob reaches code expecting the
    verbose shape."""
    return persist.expand_state(_rooms.decode_state(blob))


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
    }
    now = int(time.time())
    _DB_WRITE_EXEC.submit(
        _persist_row, room_id, room.get("status", "open"),
        pids[0] if pids else None, names[0] if names else None,
        pids[1] if len(pids) > 1 else None, names[1] if len(names) > 1 else None,
        room.get("host"), _encode_state(state), now, now,
    )


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
        return None


def load_game_to_memory(room_id: str) -> bool:
    state = load_game_state(room_id)
    if not state:
        return False
    ROOMS[room_id] = {
        "players": state.get("players", {}),
        "host": state.get("host"),
        "status": state.get("status", "open"),
        "game": state.get("game"),
        "meta": state.get("meta", {}),
        "vs_ai": state.get("vs_ai", False),
        "ai_player": state.get("ai_player"),
        "sockets": {},
    }
    return True


def _safe_state(blob) -> dict:
    """A stored room blob, or `{}` — never a raise.

    The lobby lists are the one place a single corrupt row must not take the
    whole list down with it, so every read here wants the same "read what you
    can" behaviour the rest of this file already open-codes per call site.
    """
    try:
        state = _decode_state(blob)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def list_open_games() -> list[dict]:
    maybe_cleanup_games(TABLE, background=True)
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, player1_id, player1_name, state_json, created_at
                    FROM {TABLE}
                    WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "host_id": r["player1_id"],
             # WHO IS ALREADY SEATED, which is what makes the Open row able to
             # say "Return" rather than "Join" to somebody who is in this room
             # already — the state that used to strand a guest who backed out to
             # the lobby (the WS refuses a `join` onto an occupied seat, rightly).
             # `state_json` joins the SELECT for this: it is a never-started room,
             # so the blob is the seat list and almost nothing else.
             "player_ids": _rooms.state_seat_ids(_safe_state(r["state_json"])),
             # TWO SEATS, ALWAYS, and it is stated rather than implied: the
             # frontend's "full" answer needs a cap, and a 2p game that leaves it
             # out reads as uncapped and offers Join to a third player.
             "max_players": 2,
             "host_name": r["player1_name"], "created_at": r["created_at"]}
            for r in rows]


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, status, player1_id, player1_name, player2_id,
                           player2_name, state_json, created_at, updated_at
                    FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=?) AND status != 'over'
                    ORDER BY updated_at DESC""", (user_id, user_id))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            g = (_decode_state(r["state_json"]).get("game") or {})
        except Exception:
            g = {}
        # `may_act`, not a turn comparison: both seats can owe a submission at
        # once, and a simultaneous game with nobody "on turn" would otherwise
        # sit in Active with no prompt on either side, which is how a game gets
        # forgotten.
        out.append({
            "id": r["id"], "status": r["status"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": r["player1_id"] == user_id,
            "your_turn": bool(g) and engine.may_act(g, user_id),
            "round": g.get("round") if g else None,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, player1_id, player1_name, player2_id, player2_name,
                           state_json, updated_at
                    FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=?) AND status='over'
                    ORDER BY updated_at DESC LIMIT ?""",
                (user_id, user_id, _rooms.HISTORY_LIMIT))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            g = (_decode_state(r["state_json"]).get("game") or {})
        except Exception:
            g = {}
        seat = 0 if r["player1_id"] == user_id else 1
        winner = g.get("winner")
        if winner == "draw":
            outcome = "draw"
        elif winner is None:
            outcome = "unfinished"
        else:
            outcome = "won" if winner == seat else "lost"
        out.append({
            "id": r["id"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": seat == 0,
            "outcome": outcome,
            "rounds": g.get("round"),
            "your_team": (g.get("teams") or [[], []])[seat],
            "their_team": (g.get("teams") or [[], []])[1 - seat],
            "updated_at": r["updated_at"],
        })
    return out


def _standings(state: dict) -> dict | None:
    """Who won a finished game, for the profile (core.results). `winner` is a
    seat index, or "draw"."""
    g = state.get("game") or {}
    seats = g.get("seats") if isinstance(g, dict) else None
    winner = g.get("winner") if isinstance(g, dict) else None
    if not seats or winner is None:
        return None
    if winner == "draw":
        return _results.standings(state, seats, draw=True)
    return _results.standings(state, seats, [seats[winner]])


_results.register("ragtag", TABLE, decode=_decode_state, standings=_standings)


def delete_game(game_id: str) -> None:
    conn = _db()
    try:
        conn.execute(f"DELETE FROM {TABLE} WHERE id=?", (game_id,))
        conn.commit()
    finally:
        conn.close()


def delete_open_game(game_id: str, user_id: str) -> bool:
    """SELECT-then-DELETE lives in core.rooms — never cursor.rowcount, which the
    libsql wrapper does not expose (it 500'd the cancel endpoint in prod)."""
    return _rooms.delete_open_game(TABLE, "player1_id", game_id, user_id)


# ── Room state / broadcast (PER-RECIPIENT redaction) ─────────────────────────
def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    g = room.get("game")
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        # Rebuilt for THIS recipient. Never ship `room["game"]` raw.
        "game": engine.player_view(g, viewer_pid) if g else None,
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        # Scoped to the recipient: a room-wide token map would hand every socket
        # the other seat's reconnect credential.
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }


async def broadcast_state(room_id: str, mtype: str = "room_update") -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    for pid, ws in list(room.get("sockets", {}).items()):
        try:
            await ws.send_text(json.dumps(
                {"type": mtype, "room": mk_room_state(room_id, viewer_pid=pid)}))
        except Exception:
            pass


def _sync_status_from_game(room: dict) -> None:
    if engine.is_over(room.get("game")):
        room["status"] = "over"


def _bot_should_act(room: dict) -> bool:
    g = room.get("game")
    ai = room.get("ai_player")
    return bool(g and ai and not engine.is_over(g) and engine.may_act(g, ai))


# ── Bot scheduler ────────────────────────────────────────────────────────────
# Heavy work never runs under ROOM_LOCK on the event-loop thread: snapshot under
# the lock, compute off it, re-lock, RE-VALIDATE that the bot still owes a move,
# then apply. A rewrite elsewhere that looped synchronous engine work under the
# lock took prod down once, and the rule is cheap to keep even for a bot this
# small.
_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="ragtag-bot")


def _position_key(g: dict) -> tuple:
    """Everything the bot's move was computed against.

    Simultaneous submissions mean the human can move WHILE the bot is thinking
    without any phase changing, so the key has to include who has already
    submitted -- a phase-and-round key would call that unchanged and let a stale
    move through.
    """
    return (g.get("phase"), g.get("round"), g.get("turn"), g.get("draft_round"),
            tuple(len(p) for p in g.get("draft_picks", [[], []])),
            tuple(c is not None for c in g.get("build_choice", [None, None])),
            tuple(c is not None for c in g.get("order_choice", [None, None])),
            g.get("pending_pid"))


def _bot_move_sync(g: dict, seat: int, seed: int):
    return bot.choose_move(g, seat, seed)


async def _schedule_bot_turn(room_id: str) -> None:
    """Safe to call at any time; no-ops when the bot owes nothing."""
    loop = asyncio.get_running_loop()
    while True:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            g = room["game"]
            ai = room["ai_player"]
            seat = engine.seat_of(g, ai)
            snapshot = json.loads(json.dumps(g))
            position_before = _position_key(g)

        t0 = time.monotonic()
        try:
            move = await loop.run_in_executor(
                _BOT_EXEC, _bot_move_sync, snapshot, seat,
                _rooms.bot_seed(position_before, seat))
        except Exception:
            LOG.warning("ragtag bot failed in %s", room_id, exc_info=True)
            return
        if move is None:
            return
        delay = BOT_FLOOR_SECONDS - (time.monotonic() - t0)
        if delay > 0:
            await asyncio.sleep(delay)

        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            g = room["game"]
            if _position_key(g) != position_before:
                continue                       # the human moved; think again
            try:
                engine.apply_move(g, ai, move)
            except ValueError:
                LOG.warning("ragtag bot produced an illegal move in %s", room_id)
                return
            _sync_status_from_game(room)
            save_game(room_id)
        await broadcast_state(room_id)


def _start_new_game(room: dict, room_id: str) -> None:
    seats = list(room["players"].keys())
    # ONE rng for both halves, so a seeded run reproduces the seating and the
    # draft together rather than half of each. Unseeded in production — see
    # core.rooms.deal_rng.
    rng = _rooms.deal_rng(seats, mode="ragtag")
    rng.shuffle(seats)
    room["game"] = engine.new_game(seats, seed=rng.randrange(2 ** 31))
    room["status"] = "playing"


# ── WebSocket ────────────────────────────────────────────────────────────────
@ragtag_app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id = normalize_room(room)
    pid = player
    if await _rooms.reject_if_connecting_too_fast(websocket):
        return
    _msg_throttle = _rooms.MessageThrottle()
    # See the module docstring: the pid in the path is not trusted until a
    # handshake proves ownership. NOTHING registers this socket in
    # room["sockets"] before that.
    authed = False
    try:
        while True:
            raw = await websocket.receive_text()
            if not _msg_throttle.allow():
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
            elif action in ("start", "move", "abandon"):
                if not authed:
                    await _send(websocket, {
                        "type": "error",
                        "message": "not authenticated for this seat"})
                    continue
                if action == "start":
                    await _handle_start(websocket, room_id, pid)
                elif action == "move":
                    await _handle_move(websocket, room_id, pid, msg)
                else:
                    await _handle_abandon(websocket, room_id, pid)
            else:
                await _send(websocket, {"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        _rooms.release_socket(ROOMS, room_id, pid, websocket)


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return False
        room = {
            "players": {pid: name},
            "sockets": {pid: ws},
            "status": "open",
            "host": pid,
            "game": None,
            "meta": {pid: {"token": _gen_token()}},
            "vs_ai": vs_ai,
            "ai_player": None,
        }
        ROOMS[room_id] = room
        if vs_ai:
            room["players"][AI_PID] = "Bot"
            room["ai_player"] = AI_PID
            _start_new_game(room, room_id)
        save_game(room_id)
        bot_turn = vs_ai and _bot_should_act(room)
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))
    return True   # the creator minted this seat, so they own it


async def _handle_join(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    sess = msg.get("session_token")
    session_uid = (get_user_by_session(sess) or {}).get("id") if sess else None
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        if pid in room["players"]:
            # Re-entering an EXISTING seat: prove it, or the reply below hands a
            # stranger that seat's Fight Deck.
            if session_uid != pid:
                await _send(ws, {"type": "error",
                                 "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            if room.get("status") != "open" or len(room["players"]) >= 2:
                await _send(ws, {"type": "error", "message": "room is full"})
                return False
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room["sockets"][pid] = ws
        save_game(room_id)
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
    return True


async def _handle_start(ws, room_id, pid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        if len(room["players"]) < 2:
            await _send(ws, {"type": "error", "message": "need two players"})
            return
        if room.get("game"):
            await _send(ws, {"type": "error", "message": "already started"})
            return
        _start_new_game(room, room_id)
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await broadcast_state(room_id, "started")
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_move(ws, room_id, pid, msg):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            await _send(ws, {"type": "error", "message": "no game"})
            return
        g = room["game"]
        if engine.is_over(g):
            await _send(ws, {"type": "error", "message": "the fight is over"})
            return
        if not engine.may_act(g, pid):
            await _send(ws, {"type": "error", "message": "nothing to submit"})
            return
        try:
            engine.apply_move(g, pid, msg.get("move") or {})
        except (ValueError, KeyError, TypeError) as exc:
            await _send(ws, {"type": "error", "message": str(exc) or "illegal move"})
            return
        _sync_status_from_game(room)
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await broadcast_state(room_id)
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        want = room.get("meta", {}).get(pid, {}).get("token")
        if not token or not want or token != want:
            await _send(ws, {"type": "error", "message": "bad reconnect token"})
            return False
        room["sockets"][pid] = ws
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
    # Deliberate: unsticks a vs-bot game whose scheduler died with the socket.
    asyncio.create_task(_schedule_bot_turn(room_id))
    return True


async def _handle_auth_reconnect(ws, room_id, pid, msg):
    sess = msg.get("session_token")
    user = get_user_by_session(sess) if sess else None
    if not user or user.get("id") != pid:
        await _send(ws, {"type": "error", "message": "bad session"})
        return False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "no such seat"})
            return False
        room["sockets"][pid] = ws
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
    asyncio.create_task(_schedule_bot_turn(room_id))
    return True


async def _handle_abandon(ws, room_id, pid):
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        g = room.get("game")
        if g and not engine.is_over(g):
            try:
                seat = engine.seat_of(g, pid)
            except engine.IllegalMove:
                seat = None
            if seat is not None:
                g["winner"] = engine.other_seat(seat)
                g["phase"] = "over"
                g["pending_pid"] = g["pending_kind"] = g["pending"] = None
                g["log"].append("game over (abandoned)")
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


# ── REST ─────────────────────────────────────────────────────────────────────
@ragtag_app.get("/health")
async def health():
    return {"ok": True, "game": "ragtag", **build_info()}


@ragtag_app.get("/catalog")
async def catalog():
    """The static tables the client renders from.

    Shipped rather than duplicated in the bundle: `fighters.py` is generated from
    the data, so a corrected import reaches the browser without a second
    transcription living in the frontend and drifting away from it.
    """
    return {
        "roster": list(ROSTER),
        "fighters": {
            fid: {
                "name": board["name"],
                "base_power": board["base_power"],
                "complexity": board["complexity"],
                "tags": board["tags"],
                "hp_track": board.get("hp_track"),
                "characters": board.get("characters"),
                "special_track": board.get("special_track"),
                "tokens": board.get("tokens", {}),
                "back": board.get("back"),
                # The board rules the printed board carries but the tracks do
                # not: an icon that fires before the first card, a token that
                # eats an Attack, the health a revive comes back on. The modal
                # had no way to say any of it, so it said nothing.
                # The Fighters' Guide profile: the epithet under the name, the
                # paragraph on how they play, and the five rating bars beside
                # the complexity dots.
                "title": board.get("title"),
                "profile": board.get("profile"),
                "rating": board.get("rating"),
                # The Fighters' Guide's own per-Fighter rules — the ones the
                # tracks and tokens cannot be read off.
                "guide": board.get("guide"),
                "note": board.get("note"),
                "setup_icons": board.get("setup_icons"),
                "absorbs_attack": board.get("absorbs_attack"),
                "revive_to_hp": board.get("revive_to_hp"),
            }
            for fid, board in FIGHTERS.items()
        },
        "cards": {
            str(cid): {"name": card["name"], "fighter": card["fighter"],
                       "copies": card["copies"], "starting": card.get("starting", False),
                       # The OPS, not a bool: the modal flagged that a card had
                       # an Instant Bonus and could not say what it was.
                       "instant_bonus": card.get("instant_bonus"),
                       "two_faced": bool(card.get("two_faced")),
                       "ops": card["ops"], "ops_back": card.get("ops_back"),
                       "note": card.get("note")}
            for cid, card in engine.CARDS.items()
        },
    }


@ragtag_app.get("/games")
async def games_open():
    return {"games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@ragtag_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token),
                     player_id: str | None = None):
    # A GUEST HAS NO SESSION, and Active is the only list a STARTED game lands
    # in — so a friend invited by link, who backed out to the lobby to wait,
    # had no row anywhere once the host dealt. `lobby_viewer_id` in
    # core/rooms.py carries the reasoning and states exactly what the guest
    # fallback exposes; a real session always wins over the parameter.
    viewer = _rooms.lobby_viewer_id(get_user_by_session(token) if token else None, player_id)
    if not viewer:
        return {"games": []}
    return {"games": list_user_games(viewer)}


@ragtag_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"games": []}
    return {"games": list_user_history(user["id"])}


@ragtag_app.post("/games/{game_id}/leave")
async def games_leave(game_id: str, token: str | None = Depends(_bearer_token),
                      player_id: str | None = None,
                      room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = get_user_by_session(token) if token else None
    room_id = normalize_room(game_id)
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if room is None:
            _ensure_room_loaded(room_id)
            room = ROOMS.get(room_id)
        ok, message = _rooms.remove_open_seat(
            room or {}, player_id or "", room_token=room_token,
            session_uid=(user or {}).get("id"))
        if not ok:
            return {"ok": False, "message": message}
        save_game(room_id)
    await broadcast_state(room_id)
    return {"ok": True}


@ragtag_app.delete("/games/{game_id}")
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
            room = ROOMS.get(room_id)
            if room is None:
                _ensure_room_loaded(room_id)
                room = ROOMS.get(room_id)
            if not _rooms.authorized_open_host(room or {}, owner, room_token=room_token):
                return {"ok": False, "message": "could not verify this seat"}
    ok = delete_open_game(room_id, owner)
    if ok:
        ROOMS.pop(room_id, None)
    return {"ok": ok}
