from __future__ import annotations

import asyncio
import json
import random
import string
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import sqlite3
import os
import time

app = FastAPI(title="Spender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "spender", "version": "1.0"}


# ─── Types ─────────────────────────────────────────────────────────────────

GEM_COLORS = ["white", "blue", "green", "red", "black"]


def empty_gems() -> dict[str, int]:
    return {c: 0 for c in GEM_COLORS + ["gold"]}


# ─── Card / Noble data ──────────────────────────────────────────────────────

LEVEL1: list[tuple] = [
    (0,"black",{"blue":1,"green":1,"red":1,"white":1}),(0,"black",{"blue":1,"green":2,"red":1}),
    (0,"black",{"green":3}),(0,"black",{"red":2,"white":1}),(0,"black",{"blue":2,"green":2}),
    (0,"black",{"green":1,"red":1,"white":2}),(0,"black",{"green":2,"blue":1}),(0,"black",{"green":1,"white":2,"blue":1}),
    (0,"blue",{"white":1,"green":1,"red":1,"black":1}),(0,"blue",{"white":1,"red":1,"black":2}),
    (0,"blue",{"red":2,"black":2}),(0,"blue",{"black":3}),(0,"blue",{"white":1,"green":2,"red":1}),
    (0,"blue",{"white":2,"red":2}),(0,"blue",{"white":1,"black":2}),(0,"blue",{"black":2,"red":1}),
    (0,"green",{"blue":1,"red":1,"black":1,"white":1}),(0,"green",{"blue":1,"black":1,"white":2}),
    (0,"green",{"blue":3}),(0,"green",{"white":2,"blue":1}),(0,"green",{"blue":2,"black":2}),
    (0,"green",{"blue":1,"red":2,"black":1}),(0,"green",{"blue":2,"white":1}),(0,"green",{"blue":1,"white":1,"black":2}),
    (0,"red",{"white":1,"blue":1,"green":1,"black":1}),(0,"red",{"white":2,"blue":1,"black":1}),
    (0,"red",{"white":3}),(0,"red",{"blue":2,"green":1}),(0,"red",{"white":2,"green":2}),
    (0,"red",{"white":1,"blue":1,"green":2}),(0,"red",{"white":2,"black":1}),(0,"red",{"white":1,"green":1,"black":2}),
    (0,"white",{"blue":1,"green":1,"red":1,"black":1}),(0,"white",{"green":1,"red":2,"black":1}),
    (0,"white",{"red":3}),(0,"white",{"green":2,"black":1}),(0,"white",{"red":2,"green":2}),
    (0,"white",{"red":1,"green":1,"blue":2}),(0,"white",{"red":2,"black":1}),(0,"white",{"red":1,"black":1,"green":2}),
]

LEVEL2: list[tuple] = [
    (1,"black",{"white":3,"blue":2,"green":2}),(1,"black",{"blue":3,"green":2,"red":3}),
    (2,"black",{"blue":3,"green":3,"red":5}),(2,"black",{"red":5,"white":3}),
    (2,"black",{"green":5}),(3,"black",{"black":6}),
    (1,"blue",{"white":2,"green":3,"red":3}),(1,"blue",{"white":3,"red":2,"black":3}),
    (2,"blue",{"white":3,"black":3,"red":5}),(2,"blue",{"white":5,"black":3}),
    (2,"blue",{"white":5}),(3,"blue",{"blue":6}),
    (1,"green",{"blue":2,"red":3,"black":3}),(1,"green",{"blue":3,"white":2,"black":2}),
    (2,"green",{"white":3,"blue":5,"black":3}),(2,"green",{"red":5,"blue":3}),
    (2,"green",{"blue":5}),(3,"green",{"green":6}),
    (1,"red",{"white":2,"blue":3,"black":3}),(1,"red",{"white":3,"blue":2,"green":3}),
    (2,"red",{"white":3,"green":5,"blue":3}),(2,"red",{"green":5,"white":3}),
    (2,"red",{"black":5}),(3,"red",{"red":6}),
    (1,"white",{"green":2,"red":3,"black":3}),(1,"white",{"red":3,"green":2,"black":3}),
    (2,"white",{"blue":3,"red":5,"black":3}),(2,"white",{"black":5,"green":3}),
    (2,"white",{"red":5}),(3,"white",{"white":6}),
]

LEVEL3: list[tuple] = [
    (3,"black",{"white":3,"blue":3,"green":3,"red":5}),(4,"black",{"white":7}),
    (4,"black",{"white":3,"black":7}),(5,"black",{"black":7,"white":3}),
    (3,"blue",{"white":3,"green":3,"red":3,"black":5}),(4,"blue",{"blue":7}),
    (4,"blue",{"blue":3,"white":7}),(5,"blue",{"blue":7,"black":3}),
    (3,"green",{"white":3,"blue":3,"red":3,"black":5}),(4,"green",{"green":7}),
    (4,"green",{"green":3,"blue":7}),(5,"green",{"green":7,"red":3}),
    (3,"red",{"white":3,"blue":3,"green":5,"black":3}),(4,"red",{"red":7}),
    (4,"red",{"red":3,"green":7}),(5,"red",{"red":7,"green":3}),
    (3,"white",{"blue":3,"green":3,"red":3,"black":5}),(4,"white",{"white":7}),
    (4,"white",{"white":3,"red":7}),(5,"white",{"white":7,"blue":3}),
]

ALL_NOBLES = [
    {"id":"n1","points":3,"req":{"white":4,"green":4}},
    {"id":"n2","points":3,"req":{"white":3,"blue":3,"black":3}},
    {"id":"n3","points":3,"req":{"white":3,"red":3,"green":3}},
    {"id":"n4","points":3,"req":{"blue":4,"green":4}},
    {"id":"n5","points":3,"req":{"blue":4,"black":4}},
    {"id":"n6","points":3,"req":{"green":4,"red":4}},
    {"id":"n7","points":3,"req":{"red":4,"black":4}},
    {"id":"n8","points":3,"req":{"white":4,"blue":4}},
    {"id":"n9","points":3,"req":{"white":4,"red":4}},
    {"id":"n10","points":3,"req":{"black":3,"red":3,"blue":3}},
]


# ─── Game logic ─────────────────────────────────────────────────────────────

def make_card(level: int, data: tuple, idx: int) -> dict:
    pts, bonus, cost = data
    return {"id": f"L{level}-{idx}", "level": level, "points": pts, "bonus": bonus, "cost": cost}


def build_deck() -> dict:
    l1 = [make_card(1, d, i) for i, d in enumerate(LEVEL1)]
    l2 = [make_card(2, d, i) for i, d in enumerate(LEVEL2)]
    l3 = [make_card(3, d, i) for i, d in enumerate(LEVEL3)]
    random.shuffle(l1); random.shuffle(l2); random.shuffle(l3)
    return {"L1": l1, "L2": l2, "L3": l3}


def bonuses_from(purchased: list[dict]) -> dict[str, int]:
    b = empty_gems()
    for card in purchased:
        b[card["bonus"]] = b.get(card["bonus"], 0) + 1
    return b


def can_afford(cost: dict, tokens: dict, bonuses: dict) -> bool:
    gold_needed = 0
    for c in GEM_COLORS:
        need = max(0, cost.get(c, 0) - bonuses.get(c, 0))
        have = tokens.get(c, 0)
        if have < need:
            gold_needed += need - have
    return gold_needed <= tokens.get("gold", 0)


def calc_spend(cost: dict, tokens: dict, bonuses: dict) -> dict[str, int]:
    spend = empty_gems()
    for c in GEM_COLORS:
        need = max(0, cost.get(c, 0) - bonuses.get(c, 0))
        have = min(tokens.get(c, 0), need)
        spend[c] = have
        spend["gold"] = spend.get("gold", 0) + (need - have)
    return spend


# ─── Room manager ────────────────────────────────────────────────────────────

ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()
LOG = logging.getLogger("games.spender")
logging.basicConfig(level=logging.INFO)


def normalize_room(rid: str) -> str:
    return (rid or "").upper()


# ─── Database ────────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT,
        password_hash TEXT,
        session_token TEXT,
        session_expiry INTEGER
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reconnect_tokens (
        token TEXT PRIMARY KEY,
        user_id TEXT,
        room_id TEXT,
        player_id TEXT,
        expires_at INTEGER,
        used INTEGER DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'open',
        player1_id TEXT,
        player1_name TEXT,
        player2_id TEXT,
        player2_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER,
        updated_at INTEGER
    )""")
    conn.commit()
    conn.close()


def gen_token(n=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def create_user(name: str, password: str) -> dict | None:
    import hashlib
    uid = gen_token(10)
    salt = gen_token(6)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (id,name,password_hash) VALUES (?,?,?)", (uid, name, f"{salt}${h}"))
        conn.commit()
    except Exception:
        conn.close()
        return None
    conn.close()
    return {"id": uid, "name": name}


def authenticate_user(name: str, password: str) -> dict | None:
    import hashlib
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = ?", (name,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    try:
        salt, h = row["password_hash"].split("$")
    except Exception:
        conn.close()
        return None
    if hashlib.sha256((salt + password).encode()).hexdigest() != h:
        conn.close()
        return None
    token = gen_token(32)
    expiry = int(time.time()) + 7 * 24 * 3600
    cur.execute("UPDATE users SET session_token=?, session_expiry=? WHERE id=?", (token, expiry, row["id"]))
    conn.commit()
    conn.close()
    return {"id": row["id"], "name": row["name"], "session_token": token}


def get_user_by_session(token: str) -> dict | None:
    if not token:
        return None
    conn = get_db_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT * FROM users WHERE session_token=? AND session_expiry>?", (token, now))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"]}


def create_reconnect_token(user_id: str, room_id: str, player_id: str, ttl: int = 120) -> str:
    token = gen_token(12)
    expires_at = int(time.time()) + ttl
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO reconnect_tokens (token,user_id,room_id,player_id,expires_at,used) VALUES (?,?,?,?,?,0)",
                (token, user_id, room_id, player_id, expires_at))
    conn.commit()
    conn.close()
    return token


def validate_reconnect_token(token: str) -> dict | None:
    conn = get_db_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("SELECT * FROM reconnect_tokens WHERE token=? AND expires_at>? AND used=0", (token, now))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"token": row["token"], "user_id": row["user_id"], "room_id": row["room_id"], "player_id": row["player_id"]}


def mark_reconnect_token_used(token: str):
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE reconnect_tokens SET used=1 WHERE token=?", (token,))
    conn.commit()
    conn.close()


# ─── Game persistence helpers ─────────────────────────────────────────────────

def save_game(room_id: str) -> None:
    """Upsert the current in-memory room state to the games table."""
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
    }
    now = int(time.time())
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM games WHERE id=?", (room_id,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute("""UPDATE games SET status=?, player2_id=?, player2_name=?, state_json=?, updated_at=?
                       WHERE id=?""",
                    (room.get("status"),
                     pids[1] if len(pids) > 1 else None,
                     names[1] if len(names) > 1 else None,
                     json.dumps(state), now, room_id))
    else:
        cur.execute("""INSERT INTO games
                       (id,status,player1_id,player1_name,player2_id,player2_name,host_id,state_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (room_id, room.get("status", "open"),
                     pids[0] if pids else None, names[0] if names else None,
                     pids[1] if len(pids) > 1 else None, names[1] if len(names) > 1 else None,
                     room.get("host"), json.dumps(state), now, now))
    conn.commit()
    conn.close()


def load_game_to_memory(room_id: str) -> bool:
    """Load a persisted game from DB into ROOMS. Returns True if found."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM games WHERE id=?", (room_id,))
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
        "sockets": {},
    }
    LOG.info("loaded game %s from DB", room_id)
    return True


def list_open_games() -> list[dict]:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_name, created_at FROM games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "host_name": r["player1_name"], "created_at": r["created_at"]} for r in rows]


def list_user_games(user_id: str) -> list[dict]:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""SELECT id, status, player1_id, player1_name, player2_id, player2_name,
                          state_json, created_at, updated_at
                   FROM games
                   WHERE (player1_id=? OR player2_id=?) AND status != 'over'
                   ORDER BY updated_at DESC""", (user_id, user_id))
    rows = cur.fetchall()
    conn.close()
    result = []
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            state = {}
        g = state.get("game") or {}
        is_p1 = r["player1_id"] == user_id
        opponent = r["player2_name"] if is_p1 else r["player1_name"]
        your_turn = isinstance(g, dict) and g.get("turn") == user_id
        result.append({
            "id": r["id"],
            "status": r["status"],
            "opponent_name": opponent,
            "your_turn": your_turn,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return result


init_db()


# ─── Room helpers ─────────────────────────────────────────────────────────────

async def broadcast_room(room_id: str, msg: dict[str, Any]):
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
        "reconnect_tokens": {p: info.get("token") for p, info in room.get("meta", {}).items()} if room.get("meta") else {},
    }


def _deal_board(decks: dict) -> dict:
    return {lk: [decks[lk].pop() if decks[lk] else None for _ in range(4)] for lk in ["L1", "L2", "L3"]}


def _check_nobles(game: dict, pid: str) -> list:
    bonuses = bonuses_from(game["players"][pid]["purchased"])
    return [n for n in game["nobles"] if all(bonuses.get(c, 0) >= v for c, v in n["req"].items())]


def _advance_turn(game: dict) -> str:
    order = game["order"]
    return order[(order.index(game["turn"]) + 1) % len(order)]


def _check_winner(game: dict) -> str | None:
    for pid in game["order"]:
        ps = game["players"][pid]
        pts = sum(c["points"] for c in ps["purchased"]) + sum(n["points"] for n in ps["nobles"])
        if pts >= 15:
            return pid
    return None


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id = normalize_room(room)
    pid = player
    LOG.info("ws connect room=%s player=%s", room_id, pid)

    async with ROOM_LOCK:
        if room_id not in ROOMS:
            load_game_to_memory(room_id)
        r = ROOMS.setdefault(room_id, {"players": {}, "sockets": {}, "status": "open", "game": None, "host": None})
        r["sockets"][pid] = websocket
        r.setdefault("meta", {})

    try:
        await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "invalid json"}))
                continue

            action = msg.get("action")

            # ── create ──────────────────────────────────────────────────────
            if action == "create":
                name = msg.get("name") or pid
                async with ROOM_LOCK:
                    r = ROOMS.setdefault(room_id, {"players": {}, "sockets": {}, "status": "open", "game": None, "host": None})
                    r["players"][pid] = name
                    r["host"] = pid
                    r["status"] = "open"
                    bank = {c: 4 for c in GEM_COLORS}
                    bank["gold"] = 5
                    r["game"] = {
                        "bank": bank, "decks": build_deck(), "board": None, "nobles": None,
                        "players": {}, "turn": None, "order": [], "phase": "waiting", "winner": None,
                    }
                    r["meta"][pid] = {"token": gen_token(6)}
                    r["game"]["players"][pid] = {"tokens": empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                save_game(room_id)
                await websocket.send_text(json.dumps({"type": "created", "room_id": room_id, "room": mk_room_state(room_id)}))

            # ── reconnect ───────────────────────────────────────────────────
            elif action == "reconnect":
                token = msg.get("token")
                async with ROOM_LOCK:
                    info = r.setdefault("meta", {}).get(pid)
                    if not info or info.get("token") != token:
                        await websocket.send_text(json.dumps({"type": "error", "message": "invalid token"}))
                        continue
                    r["sockets"][pid] = websocket
                LOG.info("player %s reconnected to room %s", pid, room_id)
                await websocket.send_text(json.dumps({"type": "reconnected", "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            # ── join ────────────────────────────────────────────────────────
            elif action == "join":
                name = msg.get("name") or pid
                async with ROOM_LOCK:
                    if room_id not in ROOMS:
                        await websocket.send_text(json.dumps({"type": "error", "message": "room not found"}))
                        continue
                    r = ROOMS[room_id]
                    if len(r["players"]) >= 2 and pid not in r["players"]:
                        await websocket.send_text(json.dumps({"type": "error", "message": "room full"}))
                        continue
                    r["players"][pid] = name
                    r["sockets"][pid] = websocket
                    r.setdefault("meta", {})
                    if pid not in r["meta"]:
                        r["meta"][pid] = {"token": gen_token(6)}
                    if r.get("game") and pid not in r["game"]["players"]:
                        r["game"]["players"][pid] = {"tokens": empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                save_game(room_id)
                await websocket.send_text(json.dumps({"type": "joined", "room_id": room_id, "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            # ── auth_reconnect ──────────────────────────────────────────────
            elif action == "auth_reconnect":
                token = msg.get("token")
                info = validate_reconnect_token(token)
                if not info:
                    await websocket.send_text(json.dumps({"type": "error", "message": "invalid or expired reconnect token"}))
                    continue
                if normalize_room(info.get("room_id") or "") != room_id or info.get("player_id") != pid:
                    await websocket.send_text(json.dumps({"type": "error", "message": "token mismatch"}))
                    continue
                async with ROOM_LOCK:
                    r = ROOMS.setdefault(room_id, {"players": {}, "sockets": {}, "status": "open", "game": None, "host": None})
                    r.setdefault("meta", {})
                    r["sockets"][pid] = websocket
                    r["meta"].setdefault(pid, {})["user_id"] = info.get("user_id")
                mark_reconnect_token_used(token)
                await websocket.send_text(json.dumps({"type": "reconnected", "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            # ── start ───────────────────────────────────────────────────────
            elif action == "start":
                _err: str | None = None
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if not r or r.get("host") != pid:
                        _err = "only the host can start"
                    elif len(r["players"]) < 2:
                        _err = "need 2 players to start"
                    else:
                        r["status"] = "playing"
                        g = r["game"]
                        order = list(r["players"].keys())
                        random.shuffle(order)
                        g["order"] = order
                        g["turn"] = order[0]
                        g["phase"] = "playing"
                        g["board"] = _deal_board(g["decks"])
                        nobles_pool = list(ALL_NOBLES)
                        random.shuffle(nobles_pool)
                        g["nobles"] = nobles_pool[:len(order) + 1]
                if _err:
                    await websocket.send_text(json.dumps({"type": "error", "message": _err}))
                else:
                    save_game(room_id)
                    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            # ── move ────────────────────────────────────────────────────────
            elif action == "move":
                mv = msg.get("move") or {}
                _err = None
                _did_change = False
                _discard_pid: str | None = None

                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if not r or r.get("status") != "playing":
                        _err = "game not started"
                    else:
                        g = r["game"]
                        if g.get("phase") == "over":
                            _err = "game is over"
                        elif g.get("turn") != pid:
                            _err = "not your turn"
                        else:
                            ps = g["players"][pid]
                            move_type = mv.get("type")

                            if move_type == "take_gems":
                                colors = mv.get("colors", [])
                                if not colors or len(colors) > 3:
                                    _err = "take 1-3 gems"
                                else:
                                    freq: dict[str, int] = {}
                                    for c in colors:
                                        freq[c] = freq.get(c, 0) + 1
                                    doubles = [c for c, n in freq.items() if n == 2]
                                    if any(n > 2 for n in freq.values()) or len(doubles) > 1:
                                        _err = "invalid gem selection"
                                    elif doubles and (len(colors) != 2 or len(freq) != 1):
                                        _err = "double take must be exactly 2 of one color"
                                    elif doubles and g["bank"].get(doubles[0], 0) < 4:
                                        _err = "need >= 4 in bank for double take"
                                    else:
                                        for c in colors:
                                            if g["bank"].get(c, 0) <= 0:
                                                _err = f"no {c} in bank"
                                                break
                                        else:
                                            for c in colors:
                                                g["bank"][c] -= 1
                                                ps["tokens"][c] = ps["tokens"].get(c, 0) + 1
                                            _did_change = True
                                            if sum(ps["tokens"].values()) > 10:
                                                _discard_pid = pid
                                            else:
                                                g["turn"] = _advance_turn(g)

                            elif move_type == "discard":
                                color = mv.get("color")
                                if not color or ps["tokens"].get(color, 0) <= 0:
                                    _err = "can't discard that"
                                else:
                                    ps["tokens"][color] -= 1
                                    g["bank"][color] = g["bank"].get(color, 0) + 1
                                    _did_change = True
                                    if sum(ps["tokens"].values()) > 10:
                                        _discard_pid = pid
                                    else:
                                        g["turn"] = _advance_turn(g)

                            elif move_type == "buy":
                                card_id = mv.get("card_id")
                                card: dict | None = None
                                source: tuple | None = None
                                for lk in ["L1", "L2", "L3"]:
                                    for i, c in enumerate(g["board"][lk]):
                                        if c and c["id"] == card_id:
                                            card, source = c, ("board", lk, i)
                                            break
                                    if card:
                                        break
                                if not card:
                                    for i, c in enumerate(ps["reserved"]):
                                        if c["id"] == card_id:
                                            card, source = c, ("reserved", i)
                                            break
                                if not card:
                                    _err = "card not found"
                                else:
                                    bonuses = bonuses_from(ps["purchased"])
                                    if not can_afford(card["cost"], ps["tokens"], bonuses):
                                        _err = "can't afford"
                                    else:
                                        spend = calc_spend(card["cost"], ps["tokens"], bonuses)
                                        for c, n in spend.items():
                                            ps["tokens"][c] = ps["tokens"].get(c, 0) - n
                                            g["bank"][c] = g["bank"].get(c, 0) + n
                                        ps["purchased"].append(card)
                                        if source[0] == "board":  # type: ignore[index]
                                            lk, idx = source[1], source[2]  # type: ignore[misc]
                                            g["board"][lk][idx] = g["decks"][lk].pop() if g["decks"][lk] else None
                                        else:
                                            ps["reserved"].pop(source[1])  # type: ignore[index]
                                        claimable = _check_nobles(g, pid)
                                        if claimable:
                                            n = claimable[0]
                                            ps["nobles"].append(n)
                                            g["nobles"] = [x for x in g["nobles"] if x["id"] != n["id"]]
                                        winner = _check_winner(g)
                                        if winner:
                                            g["phase"] = "over"
                                            g["winner"] = winner
                                            r["status"] = "over"
                                        else:
                                            g["turn"] = _advance_turn(g)
                                        _did_change = True

                            elif move_type == "reserve":
                                if len(ps["reserved"]) >= 3:
                                    _err = "already have 3 reserved"
                                else:
                                    card_id = mv.get("card_id")
                                    deck_level = mv.get("deck_level")
                                    card = None
                                    if card_id:
                                        for lk in ["L1", "L2", "L3"]:
                                            for i, c in enumerate(g["board"][lk]):
                                                if c and c["id"] == card_id:
                                                    card = c
                                                    g["board"][lk][i] = g["decks"][lk].pop() if g["decks"][lk] else None
                                                    break
                                            if card:
                                                break
                                    elif deck_level:
                                        lk = f"L{deck_level}"
                                        if g["decks"][lk]:
                                            card = g["decks"][lk].pop()
                                    if not card:
                                        _err = "card not found"
                                    else:
                                        ps["reserved"].append(card)
                                        if g["bank"].get("gold", 0) > 0:
                                            g["bank"]["gold"] -= 1
                                            ps["tokens"]["gold"] = ps["tokens"].get("gold", 0) + 1
                                        _did_change = True
                                        if sum(ps["tokens"].values()) > 10:
                                            _discard_pid = pid
                                        else:
                                            g["turn"] = _advance_turn(g)
                            else:
                                _err = "unknown move type"

                if _err:
                    await websocket.send_text(json.dumps({"type": "error", "message": _err}))
                elif _did_change:
                    save_game(room_id)
                    room_state = mk_room_state(room_id)
                    msg_out: dict[str, Any] = {"type": "room_update", "room": room_state}
                    if _discard_pid:
                        msg_out["needs_discard"] = _discard_pid
                    await broadcast_room(room_id, msg_out)

            # ── abandon ─────────────────────────────────────────────────────
            elif action == "abandon":
                _err = None
                _did_change = False
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if not r or r.get("status") != "playing":
                        _err = "no active game to abandon"
                    else:
                        g = r["game"]
                        if g.get("phase") == "over":
                            _err = "game already over"
                        else:
                            other = next((p for p in g.get("order", []) if p != pid), None)
                            if not other:
                                _err = "no opponent found"
                            else:
                                g["phase"] = "over"
                                g["winner"] = other
                                r["status"] = "over"
                                _did_change = True
                if _err:
                    await websocket.send_text(json.dumps({"type": "error", "message": _err}))
                elif _did_change:
                    save_game(room_id)
                    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            else:
                await websocket.send_text(json.dumps({"type": "error", "message": "unknown action"}))

    except WebSocketDisconnect:
        LOG.info("ws disconnected room=%s player=%s", room_id, pid)
    finally:
        async with ROOM_LOCK:
            r = ROOMS.get(room_id)
            if r:
                r["sockets"].pop(pid, None)
                if not r["sockets"]:
                    ROOMS.pop(room_id, None)
                else:
                    asyncio.create_task(broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)}))


# ─── HTTP endpoints ───────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    name: str
    password: str


class LoginBody(BaseModel):
    name: str
    password: str


@app.post("/auth/register")
async def auth_register(body: RegisterBody):
    user = create_user(body.name, body.password)
    if not user:
        return {"ok": False, "message": "name already taken"}
    return {"ok": True, "user": user}


@app.post("/auth/login")
async def auth_login(body: LoginBody):
    u = authenticate_user(body.name, body.password)
    if not u:
        return {"ok": False, "message": "invalid name or password"}
    return {"ok": True, "user": {"id": u["id"], "name": u["name"]}, "session_token": u["session_token"]}


@app.get("/games")
async def get_open_games():
    return {"ok": True, "games": list_open_games()}


@app.get("/games/mine")
async def get_my_games(token: str | None = None):
    user = get_user_by_session(token)
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_games(user["id"])}


@app.post("/me/session-token")
async def session_token(token: str | None = None, room_id: str | None = None, player_id: str | None = None):
    user = get_user_by_session(token)
    if not user:
        return {"ok": False, "message": "unauthenticated"}
    if not room_id or not player_id:
        return {"ok": False, "message": "room_id and player_id required"}
    rt = create_reconnect_token(user["id"], normalize_room(room_id), player_id, ttl=120)
    return {"ok": True, "reconnect_token": rt}
