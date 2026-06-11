from __future__ import annotations

import asyncio
import json
import random
import string
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import logging

app = FastAPI(title="Spender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Simple health check used by platforms and load balancers."""
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
    random.shuffle(l1)
    random.shuffle(l2)
    random.shuffle(l3)
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
        gap = need - have
        spend["gold"] = spend.get("gold", 0) + gap
    return spend


# ─── Minimal WebSocket / room manager (in-memory, single-process) ──────────
ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()
LOG = logging.getLogger("games.spender")
logging.basicConfig(level=logging.INFO)


def normalize_room(rid: str) -> str:
    return (rid or "").upper()


async def broadcast_room(room_id: str, msg: dict[str, Any]):
    room = ROOMS.get(room_id)
    if not room:
        return
    websockets = list(room.get("sockets", {}).values())
    data = json.dumps(msg)
    for ws in websockets:
        try:
            await ws.send_text(data)
        except Exception:
            # ignore send errors; cleanup happens on disconnect
            pass


def mk_room_state(room_id: str) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "status": room.get("status", "waiting"),
        "game": room.get("game"),
        "reconnect_tokens": {p: info.get("token") for p, info in room.get("meta", {}).items()} if room.get("meta") else {}
    }


@app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id = normalize_room(room)
    pid = player
    LOG.info("ws connect room=%s player=%s", room_id, pid)
    async with ROOM_LOCK:
        r = ROOMS.setdefault(room_id, {"players": {}, "sockets": {}, "status": "waiting", "game": None})
        # attach socket immediately (may be replaced by a later join with name)
        r["sockets"][pid] = websocket
        # ensure meta block for tokens/players
        r.setdefault("meta", {})
    try:
        # initial send: advertise current room state
        await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "invalid json"}))
                continue

            action = msg.get("action")
            if action == "create":
                name = msg.get("name") or pid
                async with ROOM_LOCK:
                    r = ROOMS.setdefault(room_id, {"players": {}, "sockets": {}, "status": "waiting", "game": None})
                    r["players"][pid] = name
                    # create minimal game state
                    r["game"] = {"bank": {c:4 for c in GEM_COLORS}, "deck": build_deck(), "players_state": {}, "turn": None}
                    # assign initial tokens and metadata
                    r["meta"][pid] = {"token": ''.join(random.choices(string.ascii_letters+string.digits, k=6))}
                    r["game"]["players_state"][pid] = {"tokens": empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                await websocket.send_text(json.dumps({"type": "created", "room_id": room_id, "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "reconnect":
                token = msg.get("token")
                async with ROOM_LOCK:
                    meta = r.setdefault("meta", {})
                    info = meta.get(pid)
                    if not info or info.get("token") != token:
                        await websocket.send_text(json.dumps({"type": "error", "message": "invalid token"}))
                        continue
                    # swap socket
                    r["sockets"][pid] = websocket
                LOG.info("player %s reconnected to room %s", pid, room_id)
                await websocket.send_text(json.dumps({"type": "reconnected", "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "join":
                name = msg.get("name") or pid
                async with ROOM_LOCK:
                    if room_id not in ROOMS:
                        await websocket.send_text(json.dumps({"type": "error", "message": "room not found"}))
                        continue
                    r = ROOMS[room_id]
                    r["players"][pid] = name
                    r["sockets"][pid] = websocket
                    # assign reconnect token and player state if missing
                    r.setdefault("meta", {})
                    if pid not in r["meta"]:
                        r["meta"][pid] = {"token": ''.join(random.choices(string.ascii_letters+string.digits, k=6))}
                    if r.get("game") and pid not in r["game"]["players_state"]:
                        r["game"]["players_state"][pid] = {"tokens": empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                await websocket.send_text(json.dumps({"type": "joined", "room_id": room_id, "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "reconnect":
                token = msg.get("token")
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if not r:
                        await websocket.send_text(json.dumps({"type":"error","message":"room not found"}))
                        continue
                    meta = r.setdefault("meta", {})
                    info = meta.get(pid)
                    if not info or info.get("token") != token:
                        await websocket.send_text(json.dumps({"type":"error","message":"invalid token"}))
                        continue
                    r["sockets"][pid] = websocket
                LOG.info("player %s reconnected (base handler) to room %s", pid, room_id)
                await websocket.send_text(json.dumps({"type":"reconnected","room":mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type":"room_update","room":mk_room_state(room_id)})

            elif action == "reconnect":
                token = msg.get("token")
                async with ROOM_LOCK:
                    meta = r.setdefault("meta", {})
                    info = meta.get(pid)
                    if not info or info.get("token") != token:
                        await websocket.send_text(json.dumps({"type": "error", "message": "invalid token"}))
                        continue
                    r["sockets"][pid] = websocket
                LOG.info("player %s reconnected (join handler) to room %s", pid, room_id)
                await websocket.send_text(json.dumps({"type": "reconnected", "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "start":
                # validate enough players and initialize turn order
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if r and len(r["players"])>=2:
                        r["status"] = "playing"
                        # set starting turn (first player key)
                        first = next(iter(r["players"].keys()))
                        if r.get("game"):
                            r["game"]["turn"] = first
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "move":
                mv = msg.get("move") or {}
                # basic validation: must be playing
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if not r or r.get("status")!="playing":
                        await websocket.send_text(json.dumps({"type":"error","message":"game not started"}))
                        continue
                    # simple move types handled: take_gems (colors), buy (card_id)
                    if mv.get("type")=="take_gems":
                        colors = mv.get("colors", [])
                        # naive: decrement bank and add to player's tokens
                        ok = True
                        for c in colors:
                            if r["game"]["bank"].get(c,0)<=0:
                                ok = False
                        if not ok:
                            await websocket.send_text(json.dumps({"type":"error","message":"not enough gems in bank"}))
                            continue
                        for c in colors:
                            r["game"]["bank"][c] -= 1
                            r["game"]["players_state"][pid]["tokens"][c] = r["game"]["players_state"][pid]["tokens"].get(c,0)+1
                        await broadcast_room(room_id, {"type":"room_update","room":mk_room_state(room_id)})
                    elif mv.get("type")=="buy":
                        # minimal: just broadcast buy attempt; full buy logic is out of scope for now
                        await broadcast_room(room_id, {"type":"move","from":pid,"move":mv})
                    else:
                        await websocket.send_text(json.dumps({"type":"error","message":"unknown move type"}))
                        continue

            else:
                await websocket.send_text(json.dumps({"type": "error", "message": "unknown action"}))

    except WebSocketDisconnect:
        LOG.info("ws disconnected room=%s player=%s", room_id, pid)
    finally:
        # cleanup
        async with ROOM_LOCK:
            r = ROOMS.get(room_id)
            if r:
                r["sockets"].pop(pid, None)
                # keep player name in players mapping for persistence until explicitly removed
                if not r["sockets"]:
                    # no connected sockets left; remove room
                    ROOMS.pop(room_id, None)
                else:
                    # notify remaining
                    asyncio.create_task(broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)}))


@app.websocket("/ws/{player}")
async def ws_player_base(websocket: WebSocket, player: str):
    # legacy single-socket-per-client handler: treats incoming messages that include room_id
    await websocket.accept()
    pid = player
    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "invalid json"}))
                continue
            action = msg.get("action")
            room_id = normalize_room(msg.get("room_id") or "")
            if not room_id:
                await websocket.send_text(json.dumps({"type": "error", "message": "room_id required"}))
                continue

            # ensure room exists for join/create
            if action == "create":
                name = msg.get("name") or pid
                async with ROOM_LOCK:
                    r = ROOMS.setdefault(room_id, {"players": {}, "sockets": {}, "status": "waiting", "game": None})
                    r["players"][pid] = name
                    r["sockets"][pid] = websocket
                await websocket.send_text(json.dumps({"type": "created", "room_id": room_id, "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "join":
                name = msg.get("name") or pid
                async with ROOM_LOCK:
                    if room_id not in ROOMS:
                        await websocket.send_text(json.dumps({"type": "error", "message": "room not found"}))
                        continue
                    r = ROOMS[room_id]
                    r["players"][pid] = name
                    r["sockets"][pid] = websocket
                await websocket.send_text(json.dumps({"type": "joined", "room_id": room_id, "room": mk_room_state(room_id)}))
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "start":
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if r:
                        r["status"] = "playing"
                await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})

            elif action == "move":
                await broadcast_room(room_id, {"type": "move", "from": pid, "move": msg.get("move")})

            else:
                await websocket.send_text(json.dumps({"type": "error", "message": "unknown action"}))

    except WebSocketDisconnect:
        # remove socket from any rooms where it was registered
        async with ROOM_LOCK:
            for rid, r in list(ROOMS.items()):
                if r.get("sockets", {}).get(pid) is websocket:
                    r["sockets"].pop(pid, None)
                    if not r["sockets"]:
                        ROOMS.pop(rid, None)
                    else:
                        asyncio.create_task(broadcast_room(rid, {"type": "room_update", "room": mk_room_state(rid)}))
        return

# ... (omitted rest for brevity in patch) ...

