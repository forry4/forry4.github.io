"""FastAPI sub-application for Where Wolf? — a One Night Werewolf-style party game.

Exposes ``werewolf_app`` which the composition root (top-level ``app.py``) mounts
under ``/werewolf`` so the whole site runs as one backend service. WebSocket lives
at ``/werewolf/ws/{room}/{player}`` and REST under ``/werewolf/...``.

It mirrors the proven Castles of Crimson patterns (in-memory ``ROOMS`` under one
``asyncio.Lock``, SQLite persistence in its own table, the stale-socket disconnect
guard) but with three differences this game needs:

  1. A server-driven, TIMED **night conductor** (``_run_night``) — an asyncio task
     that sleeps between narration beats and waits on per-step ``asyncio.Event``s
     for the seer/robber/troublemaker (with fallback timeouts). It is the only
     writer of the night step and never sleeps holding the lock.
  2. **Per-recipient redacted broadcasts** — ``broadcast_room`` sends every socket
     its OWN ``engine.player_view`` (hidden-information boundary), and narration is
     a separate ``{type:"narrate"}`` event via ``broadcast_narration``.
  3. **Restart recovery** — the conductor is in-memory, so a game reloaded from the
     DB mid-night is fast-forwarded into voting rather than left hung.

No bots — humans only (3..10 players). Site identity/DB come from the shared
``core`` package (no circular import — ``core`` depends on no game).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from . import roles

from core.db import get_db_conn, cleanup_stale_games, maybe_cleanup_games
from core.auth import (
    gen_token, get_user_by_session, validate_reconnect_token, mark_reconnect_token_used,
)
from core.config import cors_allowed_origins

LOG = logging.getLogger("games.wherewolf")

MIN_PLAYERS = roles.MIN_PLAYERS
MAX_PLAYERS = roles.MAX_PLAYERS

# ── Conductor timing (seconds; all tunable) ───────────────────────────────────
# Night windows are FIXED-DURATION (no early-advance): the conductor narrates a role
# then sleeps the window while the actor acts via the normal move handler. Uniform
# timing → no leak about whether a role is dealt vs in the center.
INTRO_PAUSE = 3.0           # after cards flip down → "Everyone, close your eyes."
EYES_CLOSED_PAUSE = 3.0     # → first role wakes
ACTION_WINDOW = 15.0        # seer / robber / troublemaker / drunk (+ lone-wolf peek)
INFO_WINDOW = 6.0           # werewolves / minion / masons / insomniac (look only)
PRE_WAKE_PAUSE = 3.0        # before "Everyone, wake up!"
DAY_SECONDS = 180.0         # 3-minute voting window

werewolf_app = FastAPI(title="Where Wolf? API")
werewolf_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── In-memory room state ──────────────────────────────────────────────────────
# Keys prefixed "_" are in-memory only (never persisted): sockets, the per-step
# night Events, and the conductor/timer bookkeeping flags.
ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()


def _db():
    return get_db_conn()


def _gen_token(n: int = 12) -> str:
    return gen_token(n)


def normalize_room(rid: str) -> str:
    return (rid or "").upper()


def ww_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    # player1_id/player2_id exist only so the shared core.cleanup_stale_games (which
    # keys on them to tell guest vs registered games apart) works unchanged; the
    # authoritative membership list is the player_ids JSON column.
    cur.execute("""CREATE TABLE IF NOT EXISTS werewolf_games (
        id TEXT PRIMARY KEY,
        status TEXT,
        host_id TEXT, host_name TEXT,
        player1_id TEXT, player2_id TEXT,
        player_ids TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


ww_init_db()
cleanup_stale_games("werewolf_games")   # cold-start prune


# ── Persistence ───────────────────────────────────────────────────────────────
def save_game(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    pids = list(room.get("players", {}).keys())
    state = {
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "deck": room.get("deck"),
    }
    now = int(time.time())
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM werewolf_games WHERE id=?", (room_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("""UPDATE werewolf_games SET status=?, player2_id=?, player_ids=?, state_json=?, updated_at=?
                       WHERE id=?""",
                    (room.get("status"),
                     pids[1] if len(pids) > 1 else None,
                     json.dumps(pids),
                     json.dumps(state), now, room_id))
    else:
        cur.execute("""INSERT INTO werewolf_games
                       (id,status,host_id,host_name,player1_id,player2_id,player_ids,state_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (room_id, room.get("status", "open"),
                     room.get("host"), room.get("players", {}).get(room.get("host")),
                     pids[0] if pids else None,
                     pids[1] if len(pids) > 1 else None,
                     json.dumps(pids), json.dumps(state), now, now))
    conn.commit()
    conn.close()


def delete_game(room_id: str) -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("DELETE FROM werewolf_games WHERE id=?", (room_id,))
    conn.commit()
    conn.close()


def load_game_to_memory(room_id: str) -> bool:
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM werewolf_games WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return False
    try:
        state = json.loads(row["state_json"])
    except Exception:
        return False
    room = {
        "players": state.get("players", {}),
        "host": state.get("host"),
        "status": state.get("status", "open"),
        "game": state.get("game"),
        "meta": state.get("meta", {}),
        "deck": state.get("deck"),
        "sockets": {},
        "_events": {},
    }
    g = room.get("game")
    # Restart recovery: the night conductor is in-memory, so a game reloaded
    # mid-night is fast-forwarded straight into a fresh voting window (swaps/peeks
    # already applied are preserved). A DAY game with a passed deadline resolves on
    # the first day-timer tick (delay clamps to 0).
    if g and g.get("phase") == engine.NIGHT:
        engine.begin_day(g, time.time() + DAY_SECONDS)
        room["status"] = "playing"
    ROOMS[room_id] = room
    return True


def list_open_games() -> list[dict]:
    maybe_cleanup_games("werewolf_games")   # throttled (<=1/h)
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, host_id, host_name, player_ids, created_at FROM werewolf_games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            n = len(json.loads(r["player_ids"] or "[]"))
        except Exception:
            n = 0
        out.append({"id": r["id"], "host_id": r["host_id"], "host_name": r["host_name"],
                    "players": n, "created_at": r["created_at"]})
    return out


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, status, host_id, host_name, player_ids, created_at, updated_at
                   FROM werewolf_games WHERE status != 'over' ORDER BY updated_at DESC LIMIT 100""")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            pids = json.loads(r["player_ids"] or "[]")
        except Exception:
            pids = []
        if user_id not in pids:
            continue
        out.append({
            "id": r["id"], "status": r["status"],
            "host_name": r["host_name"], "players": len(pids),
            "you_are_host": r["host_id"] == user_id,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    conn = _db()
    cur = conn.cursor()
    # Count first (the driver-agnostic cursor has no reliable rowcount on libsql).
    cur.execute("SELECT COUNT(*) FROM werewolf_games WHERE id=? AND host_id=? AND status='open'",
                (game_id, user_id))
    deleted = (cur.fetchone()[0] or 0) > 0
    if deleted:
        cur.execute("DELETE FROM werewolf_games WHERE id=? AND host_id=? AND status='open'", (game_id, user_id))
        conn.commit()
    conn.close()
    return deleted


# ── Broadcast (per-recipient redaction) ───────────────────────────────────────
def mk_room_state(room_id: str, pid: str) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    g = room.get("game")
    n = len(room.get("players", {}))
    return {
        "room_id": room_id,
        "players": room.get("players", {}),         # {pid: name} — public lobby names
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "max_players": MAX_PLAYERS,
        "min_players": MIN_PLAYERS,
        "game": engine.player_view(g, pid) if g else None,
        # Host's chosen deck (public — it's the upcoming token row) + a sensible default
        # for the current player count so the picker has something to seed from.
        "deck": room.get("deck"),
        "recommended_deck": roles.recommended_deck(n) if MIN_PLAYERS <= n <= MAX_PLAYERS else None,
        # Only the recipient's OWN reconnect token (never others').
        "reconnect_tokens": {pid: room.get("meta", {}).get(pid, {}).get("token")},
    }


async def broadcast_room(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    for pid, ws in list(room.get("sockets", {}).items()):
        try:
            await ws.send_text(json.dumps({"type": "room_update", "room": mk_room_state(room_id, pid)}))
        except Exception:
            pass


async def broadcast_narration(room_id: str, text: str, key: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    data = json.dumps({"type": "narrate", "text": text, "key": key})
    for ws in list(room.get("sockets", {}).values()):
        try:
            await ws.send_text(data)
        except Exception:
            pass


# ── Night conductor ───────────────────────────────────────────────────────────
def _game(room_id: str) -> dict | None:
    r = ROOMS.get(room_id)
    return r.get("game") if r else None


def _is_night(room_id: str) -> bool:
    g = _game(room_id)
    return bool(g and g.get("phase") == engine.NIGHT)


async def _set_night(room_id: str, step: str, deadline: float | None = None) -> bool:
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return False
        g = room.get("game")
        if not g or g.get("phase") != engine.NIGHT:
            return False
        engine.set_step(g, step, deadline)
        save_game(room_id)
    await broadcast_room(room_id)
    return True


async def _narrate(room_id: str, key: str) -> None:
    await broadcast_narration(room_id, roles.NARRATION.get(key, ""), key)


def _lone_wolf(room_id: str) -> bool:
    g = _game(room_id)
    return bool(g and len(g.get("wolf_pids", [])) == 1)


async def _begin_day(room_id: str) -> None:
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        g = room.get("game")
        if not g or g.get("phase") != engine.NIGHT:
            return
        engine.begin_day(g, time.time() + DAY_SECONDS)
        room["_day_armed"] = True
        save_game(room_id)
    await broadcast_room(room_id)
    asyncio.create_task(_run_day_timer(room_id))


async def _force_day(room_id: str) -> None:
    """Fallback used if the conductor crashes: dump everyone into voting."""
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        g = room.get("game")
        if not g or g.get("phase") != engine.NIGHT:
            return
        engine.begin_day(g, time.time() + DAY_SECONDS)
        room["_day_armed"] = True
        save_game(room_id)
    await broadcast_room(room_id)
    asyncio.create_task(_run_day_timer(room_id))


async def _run_night(room_id: str) -> None:
    """The timed narration sequence (fired once, when all players are ready).

    Data-driven over the SELECTED deck's night order with FIXED-DURATION windows:
    every role IN THE DECK is announced (even one entirely in the center) so silence
    can't leak which roles are out. Actions arrive via the normal move handler during
    the window; there is no early-advance, so timing stays uniform/leak-free."""
    try:
        # Cards have just flipped face-down (phase==NIGHT, step==intro).
        await asyncio.sleep(INTRO_PAUSE)
        if not _is_night(room_id):
            return
        await _narrate(room_id, "intro")
        await asyncio.sleep(EYES_CLOSED_PAUSE)

        g = _game(room_id)
        deck_roles = set(g.get("deck", [])) if g else set()

        for step in roles.NIGHT_ORDER:
            role = roles.STEP_ROLE[step]
            if role not in deck_roles:
                continue                          # role not in this game → skip silently
            window = ACTION_WINDOW if step in roles.ACTION_STEPS else INFO_WINDOW
            # The werewolves step is info, but a LONE wolf gets an action window to
            # optionally peek a center card.
            if step == engine.STEP_WOLVES and _lone_wolf(room_id):
                window = ACTION_WINDOW
            if not await _set_night(room_id, step, time.time() + window):
                return
            await _narrate(room_id, step)
            if step == engine.STEP_WOLVES and _lone_wolf(room_id):
                await _narrate(room_id, "lone_wolf")
            await asyncio.sleep(window)
            if not _is_night(room_id):
                return

        if not await _set_night(room_id, engine.STEP_WAKE):
            return
        await asyncio.sleep(PRE_WAKE_PAUSE)
        await _begin_day(room_id)
        await _narrate(room_id, "wakeup")
    except asyncio.CancelledError:
        raise
    except Exception:
        LOG.exception("night conductor crashed for room %s; forcing day", room_id)
        await _force_day(room_id)


async def _run_day_timer(room_id: str) -> None:
    g = _game(room_id)
    if not g or g.get("phase") != engine.DAY:
        return
    deadline = g.get("vote_deadline") or (time.time() + DAY_SECONDS)
    try:
        await asyncio.sleep(max(0.0, deadline - time.time()))
    except asyncio.CancelledError:
        return
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        g = room.get("game")
        if not g or g.get("phase") != engine.DAY:
            return
        engine.resolve_votes(g)
        room["status"] = "over"
        save_game(room_id)
    await broadcast_room(room_id)


def _ensure_day_timer(room_id: str) -> None:
    """Arm the day timer if the room is in DAY and has no live timer (e.g. after a
    reload/restart, where the in-memory timer was lost)."""
    room = ROOMS.get(room_id)
    if not room:
        return
    g = room.get("game")
    if g and g.get("phase") == engine.DAY and not room.get("_day_armed"):
        room["_day_armed"] = True
        asyncio.create_task(_run_day_timer(room_id))


# ── WebSocket protocol ────────────────────────────────────────────────────────
@werewolf_app.websocket("/ws/{room}/{player}")
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
            elif action == "set_roles":
                await _handle_set_roles(websocket, room_id, pid, msg)
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
        room = ROOMS.get(room_id)
        if room and room.get("sockets", {}).get(pid) is websocket:
            room["sockets"].pop(pid, None)
            # Drop only empty, not-yet-started open rooms; keep playing/over in memory.
            if not room["sockets"] and room.get("status") == "open" and room.get("game") is None:
                ROOMS.pop(room_id, None)


def _ensure_room_loaded(room_id: str) -> dict | None:
    if room_id not in ROOMS:
        load_game_to_memory(room_id)
    return ROOMS.get(room_id)


async def _send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return
        ROOMS[room_id] = {
            "players": {pid: name},
            "sockets": {pid: ws},
            "status": "open",
            "host": pid,
            "game": None,
            "deck": None,
            "meta": {pid: {"token": _gen_token()}},
            "_events": {},
        }
        save_game(room_id)
    await _send(ws, {"type": "created", "room_id": room_id, "room": mk_room_state(room_id, pid)})


async def _handle_join(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if pid not in room["players"]:
            if room.get("status") != "open":
                await _send(ws, {"type": "error", "message": "game already started"})
                return
            if len(room["players"]) >= MAX_PLAYERS:
                await _send(ws, {"type": "error", "message": "room is full"})
                return
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room["sockets"][pid] = ws
        save_game(room_id)
    await _send(ws, {"type": "joined", "room_id": room_id, "room": mk_room_state(room_id, pid)})
    await broadcast_room(room_id)
    _ensure_day_timer(room_id)


async def _handle_set_roles(ws, room_id, pid, msg):
    """Host picks the deck (a multiset of role names) before dealing. Lobby-only."""
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can choose roles"})
            return
        if room.get("status") != "open":
            await _send(ws, {"type": "error", "message": "game already started"})
            return
        deck = msg.get("deck")
        # partial=True: accept the in-progress selection (any count) so the other
        # players see exactly what the host has picked live; the exact count is
        # enforced when the game is dealt (_handle_start).
        ok, err = roles.validate_deck(deck, len(room["players"]), partial=True)
        if not ok:
            await _send(ws, {"type": "error", "message": err})
            return
        room["deck"] = list(deck)
        save_game(room_id)
    await broadcast_room(room_id)


async def _handle_start(ws, room_id, pid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        if room.get("status") != "open":
            await _send(ws, {"type": "error", "message": "already started"})
            return
        pids = list(room["players"].keys())
        if len(pids) < MIN_PLAYERS:
            await _send(ws, {"type": "error", "message": f"need at least {MIN_PLAYERS} players"})
            return
        if len(pids) > MAX_PLAYERS:
            await _send(ws, {"type": "error", "message": f"at most {MAX_PLAYERS} players"})
            return
        # Use the host's chosen deck; silently fall back to the recommended default
        # if it went stale (a player joined/left after it was set) or was never set.
        deck = room.get("deck")
        if deck is not None and not roles.validate_deck(deck, len(pids))[0]:
            deck = None
        room["status"] = "playing"
        room["game"] = engine.new_game(pids, names=dict(room["players"]),
                                       deck=deck or roles.recommended_deck(len(pids)))
        room["_night_started"] = False
        save_game(room_id)
    await broadcast_room(room_id)


async def _handle_move(ws, room_id, pid, msg):
    fire_night = False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            await _send(ws, {"type": "error", "message": "game not started"})
            return
        game = room["game"]
        move = msg.get("move") or {}
        mtype = move.get("type")
        ok, err = engine.apply_move(game, pid, move)
        if not ok:
            await _send(ws, {"type": "error", "message": err or "illegal move"})
            return
        # All ready → flip cards down and launch the night conductor (once). Night
        # actions just apply + broadcast — the conductor uses fixed windows, not Events.
        if mtype == "ready" and engine.all_ready(game) and not room.get("_night_started"):
            room["_night_started"] = True
            engine.start_night(game)
            fire_night = True
        # Day vote/lock → resolve early once everyone has locked.
        if game.get("phase") == engine.DAY and mtype in ("vote", "lock_vote", "unlock_vote"):
            if engine.all_locked(game):
                engine.resolve_votes(game)
                room["status"] = "over"
        save_game(room_id)
    await broadcast_room(room_id)
    if fire_night:
        asyncio.create_task(_run_night(room_id))


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
        save_game(room_id)
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id, pid)})
    _ensure_day_timer(room_id)


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
        room.setdefault("meta", {}).setdefault(pid, {})["token"] = _gen_token()
        save_game(room_id)
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id, pid)})
    _ensure_day_timer(room_id)


async def _handle_abandon(ws, room_id, pid):
    """Leave a not-yet-started lobby. Once a game is playing, abandon just drops the
    socket (the player can be voted in absentia)."""
    drop = False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            return
        if room.get("status") == "open":
            room["players"].pop(pid, None)
            room.get("meta", {}).pop(pid, None)
            room["sockets"].pop(pid, None)
            if not room["players"]:
                ROOMS.pop(room_id, None)
                delete_game(room_id)
                drop = True
            else:
                if room.get("host") == pid:
                    room["host"] = next(iter(room["players"]))
                save_game(room_id)
        else:
            room["sockets"].pop(pid, None)
    if not drop:
        await broadcast_room(room_id)


# ── REST ──────────────────────────────────────────────────────────────────────
@werewolf_app.get("/health")
async def health():
    return {"status": "ok", "service": "wherewolf", "version": "1.0"}


@werewolf_app.get("/games")
async def games_open():
    return {"ok": True, "games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    """Session token from `Authorization: Bearer` (keeping it out of URLs/logs),
    falling back to `?token=`. Local copy so this sub-app stays Spender-independent."""
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return token


@werewolf_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_games(user["id"])}


@werewolf_app.post("/games/{game_id}/cancel")
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
