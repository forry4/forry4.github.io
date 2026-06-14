from __future__ import annotations

import asyncio
import copy
import json
import math
import random
import string
from itertools import combinations
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
    (0,"black",{"white":1,"blue":1,"green":1,"red":1}),(0,"black",{"green":2,"red":1}),
    (0,"black",{"white":2,"green":2}),(0,"black",{"green":1,"red":3,"black":1}),
    (0,"black",{"green":3}),(0,"black",{"white":1,"blue":2,"green":1,"red":1}),
    (0,"black",{"white":2,"blue":2,"red":1}),(1,"black",{"blue":4}),
    (0,"blue",{"white":1,"black":2}),(0,"blue",{"white":1,"green":1,"red":2,"black":1}),
    (0,"blue",{"white":1,"green":1,"red":1,"black":1}),(0,"blue",{"blue":1,"green":3,"red":1}),
    (0,"blue",{"black":3}),(0,"blue",{"white":1,"green":2,"red":2}),
    (0,"blue",{"green":2,"black":2}),(1,"blue",{"red":4}),
    (0,"green",{"white":2,"blue":1}),(0,"green",{"blue":2,"red":2}),
    (0,"green",{"white":1,"blue":3,"green":1}),(0,"green",{"white":1,"blue":1,"red":1,"black":1}),
    (0,"green",{"white":1,"blue":1,"red":1,"black":2}),(0,"green",{"blue":1,"red":2,"black":2}),
    (0,"green",{"red":3}),(1,"green",{"black":4}),
    (0,"red",{"white":3}),(0,"red",{"white":1,"red":1,"black":3}),
    (0,"red",{"blue":2,"green":1}),(0,"red",{"white":2,"green":1,"black":2}),
    (0,"red",{"white":2,"blue":1,"green":1,"black":1}),(0,"red",{"white":1,"blue":1,"green":1,"black":1}),
    (0,"red",{"white":2,"red":2}),(1,"red",{"white":4}),
    (0,"white",{"blue":2,"green":2,"black":1}),(0,"white",{"red":2,"black":1}),
    (0,"white",{"blue":1,"green":1,"red":1,"black":1}),(0,"white",{"blue":3}),
    (0,"white",{"blue":2,"green":2}),(0,"white",{"blue":1,"green":2,"red":1,"black":1}),
    (0,"white",{"white":3,"blue":1,"black":1}),(1,"white",{"green":4}),
]

LEVEL2: list[tuple] = [
    (1,"black",{"white":3,"blue":2,"green":2}),(1,"black",{"white":3,"green":3,"black":2}),
    (2,"black",{"blue":1,"green":4,"red":2}),(2,"black",{"white":5}),
    (2,"black",{"green":5,"red":3}),(3,"black",{"black":6}),
    (1,"blue",{"blue":2,"green":2,"red":3}),(1,"blue",{"blue":2,"green":3,"black":3}),
    (2,"blue",{"white":5,"blue":3}),(2,"blue",{"blue":5}),
    (2,"blue",{"white":2,"red":1,"black":4}),(3,"blue",{"blue":6}),
    (1,"green",{"white":3,"green":2,"red":3}),(1,"green",{"white":2,"blue":3,"black":2}),
    (2,"green",{"white":4,"blue":2,"black":1}),(2,"green",{"green":5}),
    (2,"green",{"blue":5,"green":3}),(3,"green",{"green":6}),
    (1,"red",{"blue":3,"red":2,"black":3}),(1,"red",{"white":2,"red":2,"black":3}),
    (2,"red",{"white":1,"blue":4,"green":2}),(2,"red",{"white":3,"black":5}),
    (2,"red",{"black":5}),(3,"red",{"red":6}),
    (1,"white",{"green":3,"red":2,"black":2}),(1,"white",{"white":2,"blue":3,"red":3}),
    (2,"white",{"green":1,"red":4,"black":2}),(2,"white",{"red":5}),
    (2,"white",{"red":5,"black":3}),(3,"white",{"white":6}),
]

LEVEL3: list[tuple] = [
    (3,"black",{"white":3,"blue":3,"green":5,"red":3}),(4,"black",{"red":7}),
    (4,"black",{"green":3,"red":6,"black":3}),(5,"black",{"red":7,"black":3}),
    (3,"blue",{"white":3,"green":3,"red":3,"black":5}),(4,"blue",{"white":7}),
    (4,"blue",{"white":6,"blue":3,"black":3}),(5,"blue",{"white":7,"blue":3}),
    (3,"green",{"white":5,"blue":3,"red":3,"black":3}),(4,"green",{"white":3,"blue":6,"green":3}),
    (4,"green",{"blue":7}),(5,"green",{"blue":7,"green":3}),
    (3,"red",{"white":3,"blue":5,"green":3,"black":3}),(4,"red",{"green":7}),
    (4,"red",{"blue":3,"green":6,"red":3}),(5,"red",{"green":7,"red":3}),
    (3,"white",{"blue":3,"green":3,"red":5,"black":3}),(4,"white",{"black":7}),
    (4,"white",{"white":3,"red":3,"black":6}),(5,"white",{"white":3,"black":7}),
]

ALL_NOBLES = [
    {"id":"n1","points":3,"req":{"red":4,"green":4}},
    {"id":"n2","points":3,"req":{"blue":4,"green":4}},
    {"id":"n3","points":3,"req":{"blue":4,"white":4}},
    {"id":"n4","points":3,"req":{"white":4,"black":4}},
    {"id":"n5","points":3,"req":{"black":4,"red":4}},
    {"id":"n6","points":3,"req":{"black":3,"red":3,"green":3}},
    {"id":"n7","points":3,"req":{"black":3,"red":3,"white":3}},
    {"id":"n8","points":3,"req":{"black":3,"blue":3,"white":3}},
    {"id":"n9","points":3,"req":{"green":3,"blue":3,"red":3}},
    {"id":"n10","points":3,"req":{"green":3,"blue":3,"white":3}},
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
    cur.execute("""SELECT id, player1_id, player1_name, created_at FROM games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "host_id": r["player1_id"], "host_name": r["player1_name"],
             "created_at": r["created_at"]} for r in rows]


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
            "player1_name": r["player1_name"],   # full matchup, perspective-independent
            "player2_name": r["player2_name"],
            "you_are_p1": is_p1,
            "your_turn": your_turn,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return result


def delete_open_game(game_id: str, user_id: str) -> bool:
    """Delete an OPEN game the user hosts (browser 'cancel'). Returns True if a
    row was removed. Only open games can be cancelled this way."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM games WHERE id=? AND player1_id=? AND status='open'",
                (game_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


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
    state = {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "reconnect_tokens": {p: info.get("token") for p, info in room.get("meta", {}).items()} if room.get("meta") else {},
    }
    if room.get("ai_variant"):
        state["ai_variant"] = room["ai_variant"]
    return state


def _deal_board(decks: dict) -> dict:
    return {lk: [decks[lk].pop() if decks[lk] else None for _ in range(4)] for lk in ["L1", "L2", "L3"]}


def _check_nobles(game: dict, pid: str) -> list:
    bonuses = bonuses_from(game["players"][pid]["purchased"])
    return [n for n in game["nobles"] if all(bonuses.get(c, 0) >= v for c, v in n["req"].items())]


def _ai_pick_noble(claimable: list, game: dict, ai_pid: str) -> dict:
    """Pick the claimable noble the opponent is closest to obtaining (maximizes denial)."""
    if len(claimable) == 1:
        return claimable[0]
    opp_pid = next((p for p in game["order"] if p != ai_pid), None)
    if not opp_pid:
        return claimable[0]
    opp_bonuses = bonuses_from(game["players"][opp_pid]["purchased"])
    def opp_deficit(n: dict) -> int:
        return sum(max(0, need - opp_bonuses.get(c, 0)) for c, need in n["req"].items())
    return min(claimable, key=opp_deficit)


def _advance_turn(game: dict) -> str:
    order = game["order"]
    return order[(order.index(game["turn"]) + 1) % len(order)]


def _calc_points(ps: dict) -> int:
    return sum(c["points"] for c in ps["purchased"]) + sum(n["points"] for n in ps["nobles"])


def _resolve_winner(game: dict) -> None:
    """End the game: pick winner(s) via tiebreakers — most pts → fewest purchased → shared."""
    def score_key(pid):
        ps = game["players"][pid]
        return (_calc_points(ps), -len(ps["purchased"]))

    scores = {pid: score_key(pid) for pid in game["order"]}
    best = max(scores.values())
    winners = [pid for pid, s in scores.items() if s == best]
    game["phase"] = "over"
    game["winner"] = winners[0] if len(winners) == 1 else winners


def _finish_turn(game: dict, pid: str) -> None:
    """Advance turn after pid's action; start final-round countdown if pid hit 15+; end game when round completes."""
    if _calc_points(game["players"][pid]) >= 15 and "final_round_trigger" not in game:
        game["final_round_trigger"] = pid

    new_turn = _advance_turn(game)
    game["turn"] = new_turn

    if "final_round_trigger" in game:
        trigger_idx = game["order"].index(game["final_round_trigger"])
        if game["order"].index(new_turn) <= trigger_idx:
            _resolve_winner(game)


def _check_winner(game: dict) -> str | None:
    for pid in game["order"]:
        if _calc_points(game["players"][pid]) >= 15:
            return pid
    return None


def _log_move(game: dict, pid: str, mv_type: str, **details) -> None:
    """Prepend a move record to game['moves']; keep the most recent 50 (the
    end-game Review screen shows this log)."""
    entry: dict = {"pid": pid, "type": mv_type}
    entry.update({k: v for k, v in details.items() if v is not None})
    game.setdefault("moves", []).insert(0, entry)
    game["moves"] = game["moves"][:50]


# ─── AI tunable weights ─────────────────────────────────────────────────────
# These constants drive the heuristic the AI uses both as a standalone greedy
# policy and as the rollout/position-evaluator inside MCTS. They were originally
# hand-tuned; train.py can learn better values via self-play and write them to
# weights.json, which is loaded at import time below. Defaults here are the
# original hand-tuned values, so production behaviour is unchanged until a
# weights.json is present.

DEFAULT_WEIGHTS: dict[str, float] = {
    # _ai_score_card — card purchase valuation
    "point_urgency_mult": 4.0,     # how much late-game urgency amplifies raw points
    "efficiency_weight": 0.0,      # reward for a card's points-per-gem (good-deal) value
    "bonus_l1": 0.2,               # value of a bonus toward affording L1 cards
    "bonus_l2": 0.45,              # ... L2 cards
    "bonus_l3": 0.75,              # ... L3 cards
    "bonus_reserved": 0.5,         # value of a bonus toward our reserved cards
    "bonus_target_pts": 0.0,       # how much a bonus's value scales with the POINTS of cards it unlocks
    "bonus_urgency_decay": 0.8,    # how fast bonus utility fades as the game ends
    "noble_card": 0.6,             # partial credit for advancing a noble
    "noble_scarcity": 0.0,         # how much board scarcity upweights noble card-credit
    "noble_race_weight": 0.0,      # boost a noble's card-credit when the OPPONENT is also closing on it (race to claim it first; 0 = off)
    "contested_weight": 0.0,       # boost cards the opponent is also close to affording (prefer shared-good cards; all cards, not just point cards)
    "access_base": 0.3,            # base gem-distance penalty slope
    "access_urgency": 0.4,         # extra distance penalty slope in late game
    # _fast_rollout_move — rollout policy
    "rollout_reserve_threshold": 5.0,  # min score before the rollout reserves a card
    "block_urgency_gate": 1.1,     # urgency at/above which the rollout blocks (1.1 = off; lower to enable)
    "block_efficiency_weight": 0.0,  # how much a block target's points-per-gem deal upweights it (block the cheap high-point cards, not any 3-pointer). 0 = original raw-points ranking.
    "block_noble_weight": 0.0,     # how much a block target's noble-enabling value counts (deny cards that hand the opponent a noble they're close to). 0 = original points-only blocking. Both block_* extras hand-tuned: NOT in train.py CARD_KEYS, self-play can't judge blocking.
    "lose_prevention": 0.0,        # 1 = if we can't win this turn but the opponent can buy a board card next turn to reach 15, buy/reserve that card to deny the loss. 0 = off. Hand-tuned safety net.
    "gold_reserve": 0.0,           # 1 = reserve a steep single-colour high-value target to bank a gold (wild) that helps fill the hard-to-accumulate colour. 0 = off. Hand-tuned.
    # _pos_score — truncated-position evaluator (TD-learned)
    "pos_points": 1.0,             # weight on realised points
    "pos_buyable": 0.5,            # weight on immediately-buyable points (momentum)
    "pos_noble": 0.3,             # weight on noble proximity
    "pos_bonus_count": 0.0,        # weight on total bonus count (starts neutral)
    "pos_noble_scarcity": 0.0,     # weight on scarcity-gated noble proximity (starts neutral)
}

WEIGHTS: dict[str, float] = dict(DEFAULT_WEIGHTS)

# AI data files (weight sets + value model) live in the ai/ subpackage.
_AI_DIR = os.path.join(os.path.dirname(__file__), "ai")

# Path can be overridden for playtesting (e.g. SPENDER_WEIGHTS=weights.candidate.json,
# or a nonexistent path to force the original defaults).
WEIGHTS_PATH = os.environ.get("SPENDER_WEIGHTS") or os.path.join(_AI_DIR, "weights.json")

# Named weight variants available for per-game selection. "A" is the default
# deployed weights (env-overridable for playtest scripts); the rest load from the
# files below at startup, each falling back to A if its file is absent. Populated
# by load_weights().
WEIGHT_VARIANTS: dict[str, dict[str, float]] = {}
VARIANT_FILES: dict[str, str] = {
    "B": "weights.tactics.json",
    "C": "weights.tactics_c.json",
    "C2": "weights.c2.json",   # B + noble_scarcity 2.5 + pos_noble_scarcity 0.5 (0.583 vs B confirm)
}


def _merge_weights_file(path: str, fallback: dict[str, float]) -> dict[str, float]:
    """Merge a weights JSON over `fallback`. Unknown keys ignored, missing keys
    keep the fallback value; a missing or malformed file returns a copy of
    fallback. Never raises."""
    merged = dict(fallback)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                if k in DEFAULT_WEIGHTS and isinstance(v, (int, float)):
                    merged[k] = float(v)
            LOG.info("loaded AI weights from %s", path)
    except FileNotFoundError:
        return dict(fallback)
    except Exception as e:  # malformed file — fall back
        LOG.warning("could not load weights from %s: %s", path, e)
        return dict(fallback)
    return merged


def load_weights(path: str | None = None) -> dict[str, float]:
    """Load the deployed weights into the global WEIGHTS (variant A) and load every
    named variant in VARIANT_FILES. Safe to call at import; never raises."""
    global WEIGHTS
    WEIGHTS = _merge_weights_file(path or WEIGHTS_PATH, DEFAULT_WEIGHTS)
    WEIGHT_VARIANTS.clear()
    WEIGHT_VARIANTS["A"] = WEIGHTS
    for name, fname in VARIANT_FILES.items():
        WEIGHT_VARIANTS[name] = _merge_weights_file(os.path.join(_AI_DIR, fname), WEIGHTS)
    return WEIGHTS


load_weights()


# ─── AlphaZero variant ("Z") ──────────────────────────────────────────────────
# When an exported az_model.npz is present, an AlphaZero-trained net becomes
# selectable as AI variant "Z" (PUCT search + numpy inference — no torch in
# production). Absent → AZ_EVALUATE stays None and nothing changes.

AZ_MODEL_PATH = os.environ.get("SPENDER_AZ_MODEL") or os.path.join(_AI_DIR, "az_model.npz")
AZ_EVALUATE = None


def load_az_model() -> None:
    """Load the exported AZ net for variant Z. Safe at import; never raises."""
    global AZ_EVALUATE
    AZ_EVALUATE = None
    if os.environ.get("SPENDER_AZ_MODEL") == "none":
        return
    try:
        if os.path.exists(AZ_MODEL_PATH):
            from games.spender.ai.az.infer_np import load_evaluator
            AZ_EVALUATE = load_evaluator(AZ_MODEL_PATH)
            LOG.info("loaded AZ model from %s (AI variant Z enabled)", AZ_MODEL_PATH)
    except Exception as e:
        LOG.warning("could not load AZ model from %s: %s", AZ_MODEL_PATH, e)


load_az_model()  # loads ai/az_model.npz → variant Z


def _ai_variant_valid(variant: str) -> bool:
    return variant in WEIGHT_VARIANTS or (variant == "Z" and AZ_EVALUATE is not None)


def _az_choose_move(game: dict, ai_pid: str, time_limit: float = 5.0) -> dict:
    """Variant-Z move selection: time-budgeted PUCT over the fast az engine.
    Returns an incumbent dict-move; post-move discard/noble sub-decisions are
    resolved by _run_ai_turn's heuristics, same as the other variants."""
    from games.spender.ai.az import actions as _aza
    from games.spender.ai.az import engine as _aze
    from games.spender.ai.az.mcts import Search

    s = _aze.from_game_dict(game)
    legal = _aze.legal_actions(s)
    if len(legal) == 1:
        return _aza.action_to_move(s, legal[0])
    search = Search(s, random.Random(), add_noise=False)
    deadline = time.time() + time_limit
    while time.time() < deadline:
        for _ in range(32):  # check the clock every 32 simulations
            req = search.leaf_batch()
            if req is None:
                continue
            feats, mask = req
            p, v = AZ_EVALUATE(feats[None, :], mask[None, :])
            search.apply_evals(p[0], float(v[0]))
    visits = search.root.N
    return _aza.action_to_move(s, max(range(len(visits)), key=visits.__getitem__))


# ─── AI Player ────────────────────────────────────────────────────────────────

def _game_urgency(game: dict) -> float:
    """0 = early game, 1.0 = someone has reached the 15-pt threshold."""
    pts = [_calc_points(game["players"][pid]) for pid in game["order"]]
    return min(1.0, max(pts) / 15.0)


# Structural constants for "a card worth racing toward" — a good-value, high-point
# card. These define the *shape* of the target concept; the WEIGHTS control how
# strongly that concept influences decisions (so they stay fixed; only weights tune).
_TARGET_MIN_POINTS = 3        # only 3+ point cards count as race targets
_TARGET_MIN_EFFICIENCY = 0.4  # points per gem of raw cost to qualify as efficient
_GOLD_RESERVE_MIN_DEFICIT = 3  # a single-colour token shortfall this large is "steep"
                               # (slow to fill from the bank → reserve to bank gold)


def _card_efficiency(card: dict) -> float:
    """Points per gem of raw (pre-bonus) cost. 0 for free or point-less cards.
    This is the human 'is this card a good deal?' signal — 5pts/8 (0.63) beats
    5pts/10 (0.50)."""
    total = sum(v for c, v in card.get("cost", {}).items() if c in GEM_COLORS)
    pts = card.get("points", 0)
    if total <= 0 or pts <= 0:
        return 0.0
    return pts / total


def _board_scarcity(game: dict) -> float:
    """1.0 when the board has no efficient high-point L2/L3 card to race toward,
    falling toward 0 as more such targets appear. The signal behind 'no good race
    target → go wide on L1, and nobles come for free'."""
    richness = sum(
        1 for lk in ("L2", "L3")
        for c in (game["board"].get(lk) or [])
        if c and c.get("points", 0) >= _TARGET_MIN_POINTS
        and _card_efficiency(c) >= _TARGET_MIN_EFFICIENCY
    )
    return 1.0 / (1.0 + richness)


# ─── Learned value model (Stage 1: NNUE-style leaf evaluation) ────────────────
# A logistic value function V(s) = sigmoid(w·φ(s) + b) estimating P(order[0] wins).
# When a value_model.json is present, MCTS evaluates leaf nodes with this instead
# of playing a greedy rollout — a lower-variance, much faster estimate (no playout
# → far more iterations in the same time budget). Absent → MCTS falls back to the
# greedy rollout exactly as before (no behaviour change until a model is trained).

# Override for playtesting: SPENDER_VALUE_MODEL=value_model.candidate.json to try a
# candidate, or =none (a nonexistent path) to force the rollout MCTS.
VALUE_MODEL_PATH = os.environ.get("SPENDER_VALUE_MODEL") or os.path.join(_AI_DIR, "value_model.json")
_VALUE_MODEL: dict | None = None
USE_VALUE_LEAF: bool = False
# Human-readable feature order (for the trainer / introspection); MUST match
# _value_features below.
# Per-player feature names (all p0-minus-p1 diffs except the final shared "turn").
# NOTE: Stage 1c tried a richer representation (per-colour bonuses/tokens +
# per-card reachability/threat signals). It did NOT improve held-out accuracy
# (~0.64 either way) and is slower, so it was reverted. Conclusion: static-eval
# accuracy plateaus ~0.65 regardless of model/features — the remaining lever is
# search, not evaluation. Do not re-litigate richer eval features without a new
# idea about *what information* a static eval is missing.
VALUE_FEATURES = [
    "points", "buyable_pts", "noble_prox", "bonus_count", "scarce_noble",
    "total_tokens", "gold", "reserved", "purchased",  # these 9 are p0-minus-p1 diffs
    "turn",                                            # +1 if it is order[0]'s move else -1
]


def _value_player_feats(game: dict, pid: str, scarcity: float) -> list[float]:
    ps = game["players"][pid]
    bonuses = bonuses_from(ps["purchased"])
    pts = _calc_points(ps)
    buyable = sum(
        c["points"] for lk in ["L3", "L2", "L1"]
        for c in (game["board"].get(lk) or [])
        if c and can_afford(c["cost"], ps["tokens"], bonuses)
    ) + sum(
        c["points"] for c in ps["reserved"] if can_afford(c["cost"], ps["tokens"], bonuses)
    )
    noble_prox = sum(
        n["points"] / (sum(max(0, need - bonuses.get(c, 0))
                           for c, need in n["req"].items()) + 1)
        for n in (game.get("nobles") or [])
    )
    bonus_count = sum(bonuses.get(c, 0) for c in GEM_COLORS)
    return [
        float(pts), float(buyable), float(noble_prox), float(bonus_count),
        float(noble_prox * scarcity), float(sum(ps["tokens"].values())),
        float(ps["tokens"].get("gold", 0)), float(len(ps["reserved"])),
        float(len(ps["purchased"])),
    ]


def _value_features(game: dict) -> list[float]:
    """Perspective-independent state vector: order[0]-minus-order[1] feature diffs
    plus a turn-to-move indicator. Used by the learned value model."""
    order = game["order"]
    scarcity = _board_scarcity(game)
    a = _value_player_feats(game, order[0], scarcity)
    b = _value_player_feats(game, order[1], scarcity)
    diff = [x - y for x, y in zip(a, b)]
    diff.append(1.0 if game.get("turn") == order[0] else -1.0)
    return diff


def _value_logit(m: dict, phi: list[float]) -> float:
    """Raw logit for P(order[0] wins). Supports a linear model ({"w","b"}) or a
    one-hidden-layer tanh MLP ({"mean","std","W1","b1","W2","b2"}). MLP inference
    is pure-Python (no numpy) so production carries no ML dependency."""
    if "W1" in m:
        mean, std = m["mean"], m["std"]
        x = [(phi[j] - mean[j]) / std[j] for j in range(len(phi))]
        W1, b1, W2 = m["W1"], m["b1"], m["W2"]
        z = m["b2"]
        for k in range(len(b1)):
            wk = W1[k]
            a = b1[k]
            for j in range(len(x)):
                a += wk[j] * x[j]
            z += W2[k] * math.tanh(a)
        return z
    return m["b"] + sum(w * x for w, x in zip(m["w"], phi))


def _value_estimate(game: dict, ai_pid: str) -> float:
    """P(ai_pid wins) in [0,1] from the learned value model. Assumes a model is
    loaded (callers guard on USE_VALUE_LEAF)."""
    z = max(-30.0, min(30.0, _value_logit(_VALUE_MODEL, _value_features(game))))  # type: ignore[arg-type]
    p0 = 1.0 / (1.0 + math.exp(-z))            # P(order[0] wins)
    return p0 if ai_pid == game["order"][0] else 1.0 - p0


def load_value_model(path: str | None = None) -> dict | None:
    """Load value_model.json into _VALUE_MODEL and switch USE_VALUE_LEAF on. Safe
    to call at import; a missing/malformed file leaves the model off (rollouts).
    Accepts a linear ({"w","b"}) or MLP ({"W1",...}) model."""
    global _VALUE_MODEL, USE_VALUE_LEAF
    p = path or VALUE_MODEL_PATH
    try:
        with open(p, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and (("w" in data and "b" in data) or "W1" in data):
            expected = len(VALUE_FEATURES)
            dim = len(data["W1"][0]) if "W1" in data else len(data["w"])
            if dim != expected:
                LOG.warning("value model at %s has %d features, expected %d — "
                            "ignoring it (falling back to rollout MCTS)", p, dim, expected)
                return _VALUE_MODEL
            _VALUE_MODEL = data
            USE_VALUE_LEAF = True
            kind = "mlp" if "W1" in data else "linear"
            LOG.info("loaded %s value model from %s (%d features)", kind, p, dim)
    except FileNotFoundError:
        pass
    except Exception as e:
        LOG.warning("could not load value model from %s: %s", p, e)
    return _VALUE_MODEL


load_value_model()


def _opp_reach(game: dict, ai_pid: str, card: dict) -> float:
    """How close the opponent is to affording `card`: 1/(deficit+1), so 1.0 means
    they can buy it now, decaying toward 0 as it gets further away. 0 if there is
    no opponent. Drives the 'a card good for both players is worth more' signal."""
    opp_pid = next((p for p in game["order"] if p != ai_pid), None)
    if not opp_pid:
        return 0.0
    opp = game["players"][opp_pid]
    opp_bonuses = bonuses_from(opp["purchased"])
    deficit = 0
    for color, cost in card["cost"].items():
        if color == "gold":
            continue
        effective = max(0, cost - opp_bonuses.get(color, 0))
        deficit += max(0, effective - opp["tokens"].get(color, 0))
    deficit = max(0, deficit - opp["tokens"].get("gold", 0))
    return 1.0 / (deficit + 1.0)


def _ai_score_card(card: dict, game: dict, ai_pid: str, urgency: float) -> float:
    """Score a card for purchase. Points weighted heavily in late game;
    bonus utility and noble progress weighted in early/mid game;
    accessibility penalty discounts cards that are many gems away."""
    ps = game["players"][ai_pid]
    bonuses = bonuses_from(ps["purchased"])
    bonus_color = card.get("bonus")
    pts = card["points"]

    # Points become up to 5× more valuable as the game approaches its end. The
    # efficiency term rewards good points-per-gem deals among equal-point cards
    # (the human "race the cost-effective high-point cards" signal).
    point_score = (pts * (1.0 + urgency * WEIGHTS["point_urgency_mult"])
                   + _card_efficiency(card) * WEIGHTS["efficiency_weight"])

    # Bonus utility: how many future gem-saves does this card's bonus provide?
    # Target-directed — a bonus that unlocks a high-*point* card is worth more
    # than one that only helps point-less filler (bonus_target_pts scales this).
    bonus_score = 0.0
    if bonus_color:
        level_mult = {"L1": WEIGHTS["bonus_l1"], "L2": WEIGHTS["bonus_l2"], "L3": WEIGHTS["bonus_l3"]}
        for lk in ["L1", "L2", "L3"]:
            for c in (game["board"].get(lk) or []):
                if c and bonus_color in c.get("cost", {}):
                    target_mult = 1.0 + c.get("points", 0) * WEIGHTS["bonus_target_pts"]
                    bonus_score += c["cost"][bonus_color] * level_mult[lk] * target_mult
        for c in ps["reserved"]:
            if bonus_color in c.get("cost", {}):
                target_mult = 1.0 + c.get("points", 0) * WEIGHTS["bonus_target_pts"]
                bonus_score += c["cost"][bonus_color] * WEIGHTS["bonus_reserved"] * target_mult
        # Bonus utility matters less as the game nears its end
        bonus_score *= (1.0 - urgency * WEIGHTS["bonus_urgency_decay"])

    # Noble contribution: partial credit toward each noble this bonus advances.
    # Scarcity-gated — nobles matter more when the board lacks efficient high-point
    # cards to race (forcing a wide L1 engine that delivers nobles anyway).
    noble_score = 0.0
    if bonus_color:
        noble_gate = 1.0 + _board_scarcity(game) * WEIGHTS["noble_scarcity"]
        # Only resolve the opponent when racing is enabled (keeps this hot path free
        # when noble_race_weight is off).
        race_opp = (next((p for p in game["order"] if p != ai_pid), None)
                    if WEIGHTS["noble_race_weight"] else None)
        for noble in (game.get("nobles") or []):
            req = noble.get("req", {})
            if bonus_color in req:
                current = bonuses.get(bonus_color, 0)
                needed = req[bonus_color]
                if current < needed:
                    progress = current / needed
                    credit = noble["points"] * (1.0 - progress) * WEIGHTS["noble_card"] * noble_gate
                    # Contested noble: if the opponent is also closing on this same
                    # noble, racing to claim it first matters (only one player gets
                    # it). Boost credit by how close they are.
                    if race_opp:
                        credit *= 1.0 + _opp_noble_progress(game, race_opp, noble) * WEIGHTS["noble_race_weight"]
                    noble_score += credit

    # Accessibility: discount cards that are many gems away. The penalty steepens
    # in late game so the AI doesn't chase distant cards when it needs points now.
    raw_short = sum(
        max(0, max(0, cost - bonuses.get(color, 0)) - ps["tokens"].get(color, 0))
        for color, cost in card["cost"].items() if color in GEM_COLORS
    )
    deficit = max(0, raw_short - ps["tokens"].get("gold", 0))
    accessibility = 1.0 / (deficit * (WEIGHTS["access_base"] + urgency * WEIGHTS["access_urgency"]) + 1.0)

    # Contested value: a card the opponent is also close to affording is worth
    # grabbing first. NOT framed as "denial" (the self-play opponent never threatens
    # coherently, so denial never trains in) but as "prefer the shared-good card":
    # a card that's cheap/efficient *for them* — low post-bonus deficit, so high
    # _opp_reach — is one they'll also race for, so contesting it is good tempo.
    # Unlike the old version this fires for cheap 0-point cards too (the canonical
    # "we both have 2 red and a 2-red card is on the board, take it" case); point
    # cards just add denial value on top via the (1 + pts) factor.
    contested_score = 0.0
    if WEIGHTS["contested_weight"]:
        contested_score = (1.0 + pts) * _opp_reach(game, ai_pid, card) * WEIGHTS["contested_weight"]

    return (point_score + bonus_score + noble_score + contested_score) * accessibility



def _opp_winning_buys(game: dict, opp_pid: str) -> list[dict]:
    """Board cards the opponent could buy on their next turn to reach 15+ and win,
    given their current tokens/bonuses (highest-point first). These are the cards we
    can deny by buying or reserving them. A winning card already in their reserved
    hand is unblockable and is not returned. (Noble-assisted wins are not modelled —
    this is a conservative safety net that prefers under- to over-triggering.)"""
    opp = game["players"][opp_pid]
    opp_pts = _calc_points(opp)
    opp_bonuses = bonuses_from(opp["purchased"])
    winners = []
    for lk in ("L1", "L2", "L3"):
        for card in (game["board"].get(lk) or []):
            if not card:
                continue
            if (card.get("points", 0) and opp_pts + card["points"] >= 15
                    and can_afford(card["cost"], opp["tokens"], opp_bonuses)):
                winners.append(card)
    winners.sort(key=lambda c: -c["points"])
    return winners


def _lose_prevention_move(game: dict, ai_pid: str) -> dict | None:
    """If the opponent can win next turn by buying a board card and we can't win this
    turn (the caller checks that), return a move that denies it: buy the card if we
    can afford it (denies + scores), else reserve it. None if nothing to deny or no
    reserve slot. Only the single most valuable threat is denied — if there are
    several distinct winning cards we cannot stop them all."""
    opp_pid = next((p for p in game["order"] if p != ai_pid), None)
    if not opp_pid:
        return None
    winners = _opp_winning_buys(game, opp_pid)
    if not winners:
        return None
    ps = game["players"][ai_pid]
    bonuses = bonuses_from(ps["purchased"])
    for card in winners:  # prefer buying a threat (denies AND scores) over reserving
        if can_afford(card["cost"], ps["tokens"], bonuses):
            return {"type": "buy", "card_id": card["id"]}
    if len(ps["reserved"]) < 3:
        return {"type": "reserve", "card_id": winners[0]["id"]}
    return None


def _ai_discard_one(game: dict, ai_pid: str) -> None:
    ps = game["players"][ai_pid]
    bonuses = bonuses_from(ps["purchased"])
    need: dict[str, float] = {c: 0.0 for c in GEM_COLORS}
    for lk in ["L1", "L2", "L3"]:
        for card in (game["board"].get(lk) or []):
            if not card:
                continue
            for color, cost in card["cost"].items():
                if color in need:
                    effective = max(0, cost - bonuses.get(color, 0))
                    need[color] += max(0, effective - ps["tokens"].get(color, 0))
    held = [(c, ps["tokens"].get(c, 0)) for c in GEM_COLORS + ["gold"] if ps["tokens"].get(c, 0) > 0]
    if not held:
        return
    # Non-gold least-needed first; keep gold for last
    worst = min(held, key=lambda x: (1 if x[0] == "gold" else 0, need.get(x[0], 0.0)))
    ps["tokens"][worst[0]] -= 1
    game["bank"][worst[0]] = game["bank"].get(worst[0], 0) + 1


def _opp_noble_progress(game: dict, opp_pid: str, noble: dict) -> float:
    """A player's fractional progress (0..1) toward an (unclaimed) noble — the sum
    of their qualifying bonuses over the noble's total requirement."""
    opp_bonuses = bonuses_from(game["players"][opp_pid]["purchased"])
    req = noble.get("req", {})
    req_total = sum(req.values())
    if not req_total:
        return 0.0
    return sum(min(opp_bonuses.get(c, 0), n) for c, n in req.items()) / req_total


def _opp_color_outlets(game: dict, opp_pid: str, color: str, max_deficit: int = 3) -> int:
    """How many board cards grant `color` as a bonus that the opponent is within
    `max_deficit` gems of affording. Used to tell whether denying one such card
    actually blocks a noble: if the opponent has several outlets for the colour they
    still need, reserving one is futile (the white-card example)."""
    opp = game["players"][opp_pid]
    opp_bonuses = bonuses_from(opp["purchased"])
    count = 0
    for lk in ("L1", "L2", "L3"):
        for card in (game["board"].get(lk) or []):
            if not card or card.get("bonus") != color:
                continue
            deficit = 0
            for c, cost in card["cost"].items():
                if c == "gold":
                    continue
                effective = max(0, cost - opp_bonuses.get(c, 0))
                deficit += max(0, effective - opp["tokens"].get(c, 0))
            deficit = max(0, deficit - opp["tokens"].get("gold", 0))
            if deficit <= max_deficit:
                count += 1
    return count


def _opp_noble_value(game: dict, opp_pid: str, card: dict) -> float:
    """Noble points the opponent gains from this card's bonus, weighted by how close
    they already are to that noble. A card that hands a near-complete noble (≈3 free
    points) is worth denying even if the card itself is worth few points; a card
    advancing only a distant noble is not. Denial is only credited when this card is
    the opponent's *only* close source of the needed colour — if other board cards
    grant it, blocking one does not stop them, so it earns nothing."""
    bonus_color = card.get("bonus")
    if not bonus_color:
        return 0.0
    opp_bonuses = bonuses_from(game["players"][opp_pid]["purchased"])
    total = 0.0
    for noble in (game.get("nobles") or []):
        req = noble.get("req", {})
        need = req.get(bonus_color, 0)
        if need and opp_bonuses.get(bonus_color, 0) < need:
            # Only worth blocking if this is their lone close outlet for the colour.
            if _opp_color_outlets(game, opp_pid, bonus_color) <= 1:
                total += noble["points"] * _opp_noble_progress(game, opp_pid, noble)
    return total


def _ai_find_block(game: dict, ai_pid: str, opp_pid: str, urgency: float) -> dict | None:
    """Return a board card to reserve in order to deny it to the opponent, or None.
    A card is worth denying only if it actually advances the opponent: real points
    or progress toward a noble they're close to. Cheapness (efficiency) decides how
    *soon* they can take it and amplifies an already-valuable card, but it never
    substitutes for value — a cheap card worth few points that advances no noble is
    NOT blocked, however affordable it is. Among block-worthy cards the opponent is
    one or two buys from, the cheap high-value ones (what a good player races for)
    win out (block_efficiency_weight scales the deal-quality bonus)."""
    opp = game["players"][opp_pid]
    opp_bonuses = bonuses_from(opp["purchased"])
    best: dict | None = None
    best_score = 0.0
    for lk in ["L3", "L2", "L1"]:
        for card in (game["board"].get(lk) or []):
            if not card:
                continue
            # Worth to the opponent: its own points plus any noble it advances. Skip
            # low-point cards that advance no noble — not worth a block, cheap or not.
            noble_value = (_opp_noble_value(game, opp_pid, card) * WEIGHTS["block_noble_weight"]
                           if WEIGHTS["block_noble_weight"] else 0.0)
            if card["points"] < 3 and noble_value <= 0:
                continue
            deficit = 0
            for color, cost in card["cost"].items():
                if color == "gold":
                    continue
                effective = max(0, cost - opp_bonuses.get(color, 0))
                deficit += max(0, effective - opp["tokens"].get(color, 0))
            gold = opp["tokens"].get("gold", 0)
            deficit = max(0, deficit - gold)
            if deficit <= 2:
                # Value = points + noble progress, amplified by how good a deal it is
                # (points-per-gem). Cheapness only scales an already-valuable card.
                value = (card["points"] + noble_value) * (1.0 + _card_efficiency(card) * WEIGHTS["block_efficiency_weight"])
                score = value * urgency / max(1.0, float(deficit))
                if score > best_score:
                    best_score = score
                    best = card
    return best if best_score >= 2.0 else None


def _ai_find_reserve_target(game: dict, ai_pid: str, urgency: float) -> dict | None:
    """Return a high-value board card worth reserving for ourselves, or None."""
    ps = game["players"][ai_pid]
    bonuses = bonuses_from(ps["purchased"])
    already = {c["id"] for c in ps["reserved"]}
    best: dict | None = None
    best_score = -1.0
    for lk in ["L3", "L2"]:
        lw = 1.5 if lk == "L3" else 1.0
        for card in (game["board"].get(lk) or []):
            if not card or card["id"] in already or card["points"] < 3:
                continue
            # Accessibility penalty is already baked into _ai_score_card; just
            # hard-skip cards that are totally out of reach (raw deficit, pre-gold).
            raw_deficit = sum(
                max(0, max(0, cost - bonuses.get(color, 0)) - ps["tokens"].get(color, 0))
                for color, cost in card["cost"].items() if color in GEM_COLORS
            )
            if raw_deficit > 7:
                continue
            score = _ai_score_card(card, game, ai_pid, urgency) * lw
            if score > best_score:
                best_score = score
                best = card
    return best if best_score > 4.0 else None


def _ai_find_gold_reserve(game: dict, ai_pid: str) -> dict | None:
    """A high-value target whose cost is concentrated in one colour we're badly short
    on: reserving it banks a gold (wild) that helps fill that hard-to-accumulate gap
    (you can only pull two of a colour per turn, and the bank runs dry). Returns the
    best such board card to reserve, or None. Only fires when one colour is the
    bottleneck (the rest of the cost is nearly covered) and we still lack the gold to
    bridge it — otherwise plain gem-taking is better. Gated by the gold_reserve weight."""
    ps = game["players"][ai_pid]
    if len(ps["reserved"]) >= 3 or game["bank"].get("gold", 0) <= 0:
        return None  # no reserve slot, or reserving would yield no gold
    bonuses = bonuses_from(ps["purchased"])
    gold = ps["tokens"].get("gold", 0)
    already = {c["id"] for c in ps["reserved"]}
    best: dict | None = None
    best_score = 0.0
    for lk in ("L3", "L2"):
        for card in (game["board"].get(lk) or []):
            if not card or card.get("points", 0) < _TARGET_MIN_POINTS or card["id"] in already:
                continue
            max_color_short = 0
            total_short = 0
            for color, cost in card["cost"].items():
                if color not in GEM_COLORS:
                    continue
                eff = max(0, cost - bonuses.get(color, 0))
                short = max(0, eff - ps["tokens"].get(color, 0))
                total_short += short
                if short > max_color_short:
                    max_color_short = short
            # One steep colour is the bottleneck (others nearly covered) and we still
            # lack the gold to bridge it — exactly when banking a wild beats taking gems.
            if (max_color_short >= _GOLD_RESERVE_MIN_DEFICIT
                    and total_short - max_color_short <= 2
                    and gold < max_color_short):
                score = card["points"] * max_color_short
                if score > best_score:
                    best_score = score
                    best = card
    return best


# ─── MCTS ─────────────────────────────────────────────────────────────────────

def _get_all_moves(game: dict, pid: str) -> list[dict]:
    """Enumerate candidate moves for MCTS: all buys, pruned gem combos, top reserves."""
    ps = game["players"][pid]
    bonuses = bonuses_from(ps["purchased"])
    moves: list[dict] = []

    for lk in ["L3", "L2", "L1"]:
        for card in (game["board"].get(lk) or []):
            if card and can_afford(card["cost"], ps["tokens"], bonuses):
                moves.append({"type": "buy", "card_id": card["id"]})
    for card in ps["reserved"]:
        if can_afford(card["cost"], ps["tokens"], bonuses):
            moves.append({"type": "buy", "card_id": card["id"]})

    token_total = sum(ps["tokens"].values())
    max_take = min(3, 10 - token_total)
    if max_take > 0:
        need: dict[str, float] = {c: 0.0 for c in GEM_COLORS}
        for lk in ["L1", "L2", "L3"]:
            for card in (game["board"].get(lk) or []):
                if card:
                    for color, cost in card["cost"].items():
                        if color in need:
                            eff = max(0, cost - bonuses.get(color, 0))
                            need[color] += max(0, eff - ps["tokens"].get(color, 0))
        available = [c for c in GEM_COLORS if game["bank"].get(c, 0) > 0]
        by_need = sorted(available, key=lambda c: -need[c])
        seen: set[tuple] = set()
        # 3-color combos from top 4 most-needed colors
        for combo in combinations(by_need[:4], min(3, max_take, len(by_need[:4]))):
            key = tuple(sorted(combo))
            if key not in seen:
                moves.append({"type": "take_gems", "colors": list(combo)})
                seen.add(key)
        # Double-take best needed color
        for c in by_need:
            if game["bank"].get(c, 0) >= 4 and max_take >= 2:
                key = (c, c)
                if key not in seen:
                    moves.append({"type": "take_gems", "colors": [c, c]})
                    seen.add(key)
                break

    if len(ps["reserved"]) < 3:
        urgency = _game_urgency(game)
        opp_pid = next((p for p in game["order"] if p != pid), None)
        reserve_ids: set[str] = set()
        target = _ai_find_reserve_target(game, pid, urgency)
        if target:
            moves.append({"type": "reserve", "card_id": target["id"]})
            reserve_ids.add(target["id"])
        if opp_pid and urgency >= 0.4:
            block = _ai_find_block(game, pid, opp_pid, urgency)
            if block and block["id"] not in reserve_ids:
                moves.append({"type": "reserve", "card_id": block["id"]})
        if WEIGHTS["gold_reserve"]:
            gold_target = _ai_find_gold_reserve(game, pid)
            if gold_target and gold_target["id"] not in reserve_ids:
                moves.append({"type": "reserve", "card_id": gold_target["id"]})
                reserve_ids.add(gold_target["id"])

    return moves or [{"type": "take_gems", "colors": []}]


def _sim_apply_move(game: dict, pid: str, mv: dict) -> None:
    """Apply any move in-place for MCTS simulation. Calls _finish_turn; never calls _post_turn."""
    ps = game["players"][pid]
    bonuses = bonuses_from(ps["purchased"])

    if mv["type"] == "buy":
        card_id = mv["card_id"]
        card: dict | None = None
        source: tuple | None = None
        for lk in ["L1", "L2", "L3"]:
            for i, c in enumerate(game["board"][lk]):
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
        if card and source:
            spend = calc_spend(card["cost"], ps["tokens"], bonuses)
            for c2, n in spend.items():
                ps["tokens"][c2] = ps["tokens"].get(c2, 0) - n
                game["bank"][c2] = game["bank"].get(c2, 0) + n
            ps["purchased"].append(card)
            if source[0] == "board":
                lk2 = source[1]
                game["board"][lk2][source[2]] = game["decks"][lk2].pop() if game["decks"][lk2] else None
            else:
                ps["reserved"].pop(source[1])
            claimable = _check_nobles(game, pid)
            if claimable:
                noble = _ai_pick_noble(claimable, game, pid)
                ps["nobles"].append(noble)
                game["nobles"] = [x for x in game["nobles"] if x["id"] != noble["id"]]

    elif mv["type"] == "take_gems":
        for c2 in mv["colors"]:
            if game["bank"].get(c2, 0) > 0:
                game["bank"][c2] -= 1
                ps["tokens"][c2] = ps["tokens"].get(c2, 0) + 1
        while sum(ps["tokens"].values()) > 10:
            _ai_discard_one(game, pid)

    elif mv["type"] == "reserve":
        card_id = mv.get("card_id")
        card = None
        if card_id:
            for lk in ["L1", "L2", "L3"]:
                for i, c in enumerate(game["board"][lk]):
                    if c and c["id"] == card_id:
                        card = c
                        game["board"][lk][i] = game["decks"][lk].pop() if game["decks"][lk] else None
                        break
                if card:
                    break
        if card:
            ps["reserved"].append(card)
            if game["bank"].get("gold", 0) > 0:
                game["bank"]["gold"] -= 1
                ps["tokens"]["gold"] = ps["tokens"].get("gold", 0) + 1
            while sum(ps["tokens"].values()) > 10:
                _ai_discard_one(game, pid)

    _finish_turn(game, pid)


def _fast_rollout_move(game: dict, pid: str) -> dict:
    """Rollout policy: buy best card, or reserve a high-value near-affordable card, else take needed gems."""
    ps = game["players"][pid]
    bonuses = bonuses_from(ps["purchased"])
    urgency = _game_urgency(game)

    # 1. Buy best affordable card
    best_card: dict | None = None
    best_score = -1.0
    for lk in ["L3", "L2", "L1"]:
        for card in (game["board"].get(lk) or []):
            if card and can_afford(card["cost"], ps["tokens"], bonuses):
                s = _ai_score_card(card, game, pid, urgency)
                if s > best_score:
                    best_card, best_score = card, s
    for card in ps["reserved"]:
        if can_afford(card["cost"], ps["tokens"], bonuses):
            s = _ai_score_card(card, game, pid, urgency)
            if s > best_score:
                best_card, best_score = card, s
    if best_card:
        return {"type": "buy", "card_id": best_card["id"]}

    # 1b. Block: if the opponent is about to grab a key card, reserve it to deny.
    # Gated by block_urgency_gate (default 1.1 > max urgency = off); training lowers
    # it to switch blocking on, which lets MCTS see — and value — denial lines.
    if urgency >= WEIGHTS["block_urgency_gate"] and len(ps["reserved"]) < 3:
        opp_pid = next((p for p in game["order"] if p != pid), None)
        if opp_pid:
            block = _ai_find_block(game, pid, opp_pid, urgency)
            if block and block["id"] not in {c["id"] for c in ps["reserved"]}:
                return {"type": "reserve", "card_id": block["id"]}

    # 2. Reserve a high-value card that is close to affordable (secures it + earns gold token)
    if len(ps["reserved"]) < 3:
        already_reserved = {c["id"] for c in ps["reserved"]}
        best_reserve: dict | None = None
        best_reserve_score = 0.0
        for lk in ["L3", "L2"]:
            lw = 1.4 if lk == "L3" else 1.0
            for card in (game["board"].get(lk) or []):
                if not card or card["id"] in already_reserved:
                    continue
                deficit = sum(
                    max(0, max(0, cost - bonuses.get(color, 0)) - ps["tokens"].get(color, 0))
                    for color, cost in card["cost"].items() if color in GEM_COLORS
                )
                if deficit > 5:
                    continue
                s = _ai_score_card(card, game, pid, urgency) * lw
                if s > best_reserve_score:
                    best_reserve_score = s
                    best_reserve = card
        if best_reserve and best_reserve_score > WEIGHTS["rollout_reserve_threshold"]:
            return {"type": "reserve", "card_id": best_reserve["id"]}

    # 2b. Reserve a steep single-colour target to bank gold instead of slowly taking
    # gems toward it (the hard-to-accumulate colour the wild gold helps bridge).
    if WEIGHTS["gold_reserve"] and len(ps["reserved"]) < 3:
        gold_target = _ai_find_gold_reserve(game, pid)
        if gold_target:
            return {"type": "reserve", "card_id": gold_target["id"]}

    # 3. Take most-needed gems
    token_total = sum(ps["tokens"].values())
    max_take = min(3, 10 - token_total)
    if max_take > 0:
        need: dict[str, float] = {c: 0.0 for c in GEM_COLORS}
        for lk in ["L1", "L2", "L3"]:
            for card in (game["board"].get(lk) or []):
                if card:
                    pts = card["points"]
                    if urgency > 0.65 and pts == 0:
                        continue
                    for color, cost in card["cost"].items():
                        if color in need:
                            eff = max(0, cost - bonuses.get(color, 0))
                            deficit = max(0, eff - ps["tokens"].get(color, 0))
                            need[color] += deficit * (pts + 1) * (1.0 + urgency * pts * 0.3)
        available = sorted([c for c in GEM_COLORS if game["bank"].get(c, 0) > 0], key=lambda c: -need[c])
        if available:
            return {"type": "take_gems", "colors": available[:max_take]}

    return {"type": "take_gems", "colors": []}


def _sim_rollout(game: dict, max_turns: int = 25) -> str | list | None:
    """Play out a simulation to terminal or max_turns using fast heuristic for both players."""
    for _ in range(max_turns):
        if game.get("phase") != "playing":
            break
        pid = game["turn"]
        mv = _fast_rollout_move(game, pid)
        _sim_apply_move(game, pid, mv)

    if game.get("phase") == "over":
        return game.get("winner")

    # Hit turn limit — evaluate position: points + immediately buyable points (momentum)
    # + light noble-proximity signal. Avoids over-committing to noble paths.
    scarcity = _board_scarcity(game)  # board-level, shared by both players

    def _pos_score(pid: str) -> float:
        ps = game["players"][pid]
        bonuses = bonuses_from(ps["purchased"])
        pts = _calc_points(ps)
        buyable = sum(
            c["points"]
            for lk in ["L3", "L2", "L1"]
            for c in (game["board"].get(lk) or [])
            if c and can_afford(c["cost"], ps["tokens"], bonuses)
        ) + sum(
            c["points"] for c in ps["reserved"]
            if can_afford(c["cost"], ps["tokens"], bonuses)
        )
        noble_proximity = sum(
            n["points"] / (sum(max(0, need - bonuses.get(c, 0))
                               for c, need in n["req"].items()) + 1)
            for n in (game.get("nobles") or [])
        )
        bonus_count = sum(bonuses.get(c, 0) for c in GEM_COLORS)
        # Scarcity-gated noble proximity: noble closeness matters more when the
        # board offers no efficient race target (kept as a separate linear term so
        # the TD learner can weight it independently of base noble proximity).
        scarce_noble = noble_proximity * scarcity
        return (pts * WEIGHTS["pos_points"]
                + buyable * WEIGHTS["pos_buyable"]
                + noble_proximity * WEIGHTS["pos_noble"]
                + bonus_count * WEIGHTS["pos_bonus_count"]
                + scarce_noble * WEIGHTS["pos_noble_scarcity"])

    scores = {pid: _pos_score(pid) for pid in game["order"]}
    best = max(scores.values())
    leaders = [pid for pid, s in scores.items() if s == best]
    return leaders[0] if len(leaders) == 1 else leaders


class _MCTSNode:
    """Node in the MCTS search tree. ai_wins always counts wins from the AI's perspective."""
    __slots__ = ("move", "state", "parent", "children", "_untried", "visits", "ai_wins")

    def __init__(self, state: dict, parent=None, move: dict | None = None):
        self.state = state
        self.parent = parent
        self.move = move
        self.children: list = []
        self._untried: list | None = None
        self.visits = 0
        self.ai_wins = 0.0

    def _ensure_untried(self) -> list:
        if self._untried is None:
            if self.state.get("phase") == "over":
                self._untried = []
            else:
                moves = _get_all_moves(self.state, self.state["turn"])
                # Reverse so pop() tries buys first (generated first), then
                # gem-takes, then reserves — matching priority order.
                moves.reverse()
                self._untried = moves
        return self._untried

    def is_terminal(self) -> bool:
        return self.state.get("phase") == "over"

    def is_fully_expanded(self) -> bool:
        return len(self._ensure_untried()) == 0

    def select_child(self, ai_pid: str) -> "_MCTSNode":
        """UCB1 child selection. AI maximizes win rate; opponent minimizes it."""
        log_n = math.log(self.visits)
        maximizing = self.state["turn"] == ai_pid
        def ucb(c: "_MCTSNode") -> float:
            if c.visits == 0:
                return float("inf")
            exploit = c.ai_wins / c.visits
            explore = 1.414 * math.sqrt(log_n / c.visits)
            return (exploit if maximizing else -exploit) + explore
        return max(self.children, key=ucb)

    def expand(self) -> "_MCTSNode":
        move = self._ensure_untried().pop()
        g = copy.deepcopy(self.state)
        _sim_apply_move(g, self.state["turn"], move)
        child = _MCTSNode(g, parent=self, move=move)
        self.children.append(child)
        return child

    def backprop_reward(self, reward: float) -> None:
        """Propagate a [0,1] reward (AI's perspective) up to the root."""
        node = self
        while node is not None:
            node.visits += 1
            node.ai_wins += reward
            node = node.parent


def _mcts_choose_move(game: dict, ai_pid: str, time_limit: float = 5.0,
                      max_iters: int | None = None,
                      weights: dict | None = None) -> dict:
    """UCB1 tree MCTS: select → expand → simulate → backprop.

    Stops at whichever of ``time_limit`` (wall-clock) or ``max_iters`` (iteration
    count) is hit first. Training passes a small ``max_iters`` for fast,
    wall-clock-independent self-play; production leaves it None and uses the 5s
    budget.

    ``weights`` overrides the global WEIGHTS for this call (used to run a
    specific AI variant per room). The swap is scoped to this call and is safe
    because _mcts_choose_move is synchronous and runs in a dedicated executor
    thread — no other coroutine touches WEIGHTS during play."""
    global WEIGHTS
    _saved_weights = WEIGHTS
    if weights is not None:
        WEIGHTS = weights
    try:
        return _mcts_choose_move_impl(game, ai_pid, time_limit, max_iters)
    finally:
        WEIGHTS = _saved_weights


def _mcts_choose_move_impl(game: dict, ai_pid: str, time_limit: float,
                           max_iters: int | None) -> dict:
    candidates = _get_all_moves(game, ai_pid)
    if len(candidates) == 1:
        return candidates[0]

    # Grab any immediately winning move before building the tree
    for mv in candidates:
        g = copy.deepcopy(game)
        _sim_apply_move(g, ai_pid, mv)
        if g.get("phase") == "over":
            w = g.get("winner")
            if w == ai_pid or (isinstance(w, list) and ai_pid in w):
                return mv

    # We can't win this turn (no winning move above). If the opponent could win on
    # their next turn by buying a board card, deny it (buy or reserve) — losing is
    # worse than any line MCTS would otherwise explore.
    if WEIGHTS["lose_prevention"]:
        deny = _lose_prevention_move(game, ai_pid)
        if deny is not None:
            return deny

    root = _MCTSNode(copy.deepcopy(game))
    deadline = time.time() + time_limit
    iters = 0

    while time.time() < deadline and (max_iters is None or iters < max_iters):
        iters += 1
        # 1. Selection: walk down via UCB1 until reaching an unexpanded or terminal node
        node = root
        while node.is_fully_expanded() and not node.is_terminal():
            node = node.select_child(ai_pid)

        # 2. Expansion: add one new child for an untried move
        if not node.is_terminal():
            node = node.expand()

        # 3. Evaluate the leaf. Terminal → real result. Otherwise use the learned
        #    value model (Stage 1, NNUE-style: fast, low-variance, no playout) when
        #    one is loaded; else fall back to a greedy rollout.
        if node.is_terminal():
            w = node.state.get("winner")
            reward = 1.0 if w == ai_pid else (0.5 if isinstance(w, list) and ai_pid in w else 0.0)
        elif USE_VALUE_LEAF and _VALUE_MODEL is not None:
            reward = _value_estimate(node.state, ai_pid)
        else:
            g_sim = copy.deepcopy(node.state)
            w = _sim_rollout(g_sim)
            reward = 1.0 if w == ai_pid else (0.5 if isinstance(w, list) and ai_pid in w else 0.0)

        # 4. Backpropagation: update visits and reward all the way to the root
        node.backprop_reward(reward)

    if not root.children:
        return candidates[0]
    # Most-visited child is the most reliable (UCB1 concentrates budget on good moves)
    return max(root.children, key=lambda c: c.visits).move


def _run_ai_turn(game: dict, ai_pid: str, mv: dict | None = None) -> None:
    ps = game["players"][ai_pid]
    bonuses = bonuses_from(ps["purchased"])
    if mv is None:
        mv = _mcts_choose_move(game, ai_pid)

    if mv["type"] == "buy":
        card_id = mv["card_id"]
        card: dict | None = None
        source: tuple | None = None
        for lk in ["L1", "L2", "L3"]:
            for i, c in enumerate(game["board"][lk]):
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
        if card and source:
            spend = calc_spend(card["cost"], ps["tokens"], bonuses)
            for c, n in spend.items():
                ps["tokens"][c] = ps["tokens"].get(c, 0) - n
                game["bank"][c] = game["bank"].get(c, 0) + n
            ps["purchased"].append(card)
            if source[0] == "board":
                game["board"][source[1]][source[2]] = game["decks"][source[1]].pop() if game["decks"][source[1]] else None
            else:
                ps["reserved"].pop(source[1])
            _log_move(game, ai_pid, "buy", card={"id": card["id"], "bonus": card["bonus"], "color": card["bonus"], "points": card["points"], "cost": card["cost"], "level": card.get("level")})
            claimable = _check_nobles(game, ai_pid)
            if claimable:
                n = _ai_pick_noble(claimable, game, ai_pid)
                ps["nobles"].append(n)
                game["nobles"] = [x for x in game["nobles"] if x["id"] != n["id"]]
                _log_move(game, ai_pid, "noble", pts=n["points"])

    elif mv["type"] == "take_gems":
        for c in mv["colors"]:
            if game["bank"].get(c, 0) > 0:
                game["bank"][c] -= 1
                ps["tokens"][c] = ps["tokens"].get(c, 0) + 1
        while sum(ps["tokens"].values()) > 10:
            _ai_discard_one(game, ai_pid)
        _log_move(game, ai_pid, "take_gems", colors=mv["colors"])

    elif mv["type"] == "reserve":
        card_id = mv.get("card_id")
        card = None
        if card_id:
            for lk in ["L1", "L2", "L3"]:
                for i, c in enumerate(game["board"][lk]):
                    if c and c["id"] == card_id:
                        card = c
                        game["board"][lk][i] = game["decks"][lk].pop() if game["decks"][lk] else None
                        break
                if card:
                    break
        if card:
            ps["reserved"].append(card)
            if game["bank"].get("gold", 0) > 0:
                game["bank"]["gold"] -= 1
                ps["tokens"]["gold"] = ps["tokens"].get("gold", 0) + 1
            while sum(ps["tokens"].values()) > 10:
                _ai_discard_one(game, ai_pid)
            _log_move(game, ai_pid, "reserve", card={"id": card["id"], "bonus": card["bonus"], "color": card["bonus"], "points": card["points"], "cost": card["cost"], "level": card.get("level")})

    _finish_turn(game, ai_pid)


def _post_turn(game: dict, r: dict) -> None:
    """After _finish_turn: sync room status. AI move is run async via _schedule_ai_turn."""
    if game.get("phase") == "over":
        r["status"] = "over"


async def _schedule_ai_turn(room_id: str) -> None:
    """Broadcast the post-human-move state immediately, then run MCTS in a thread pool
    (non-blocking) and broadcast the AI's move when it finishes."""
    async with ROOM_LOCK:
        r = ROOMS.get(room_id)
        if not r:
            return
        g = r.get("game")
        if not g:
            return
        ai_pid = g.get("ai_player")
        if not ai_pid or g.get("turn") != ai_pid or g.get("phase") != "playing":
            return
        game_snapshot = copy.deepcopy(g)
        variant = r.get("ai_variant", "A")

    # MCTS runs in a thread pool so the event loop stays free during the 5s compute
    loop = asyncio.get_running_loop()
    if variant == "Z" and AZ_EVALUATE is not None:
        mv = await loop.run_in_executor(None, _az_choose_move, game_snapshot, ai_pid, 5.0)
    else:
        ai_weights = WEIGHT_VARIANTS.get(variant, WEIGHTS)
        mv = await loop.run_in_executor(
            None, _mcts_choose_move, game_snapshot, ai_pid, 5.0, None, ai_weights
        )

    async with ROOM_LOCK:
        r = ROOMS.get(room_id)
        if not r:
            return
        g = r.get("game")
        if not g or g.get("turn") != ai_pid or g.get("phase") != "playing":
            return  # game changed while AI was thinking (e.g. abandoned)
        _run_ai_turn(g, ai_pid, mv)
        if g.get("phase") == "over":
            r["status"] = "over"

    save_game(room_id)
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})


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
                vs_ai = bool(msg.get("vs_ai"))
                ai_variant = msg.get("ai_variant", "A") if vs_ai else None
                if vs_ai and not _ai_variant_valid(ai_variant):
                    ai_variant = "A"
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
                        "moves": [],
                    }
                    r["meta"][pid] = {"token": gen_token(6)}
                    r["game"]["players"][pid] = {"tokens": empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                    if vs_ai:
                        ai_pid = "ai"
                        r["players"][ai_pid] = f"AI ({ai_variant})"
                        r["ai_variant"] = ai_variant
                        g = r["game"]
                        g["players"][ai_pid] = {"tokens": empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                        g["ai_player"] = ai_pid
                        order = [pid, ai_pid]
                        random.shuffle(order)
                        g["order"] = order
                        g["turn"] = order[0]
                        g["phase"] = "playing"
                        g["board"] = _deal_board(g["decks"])
                        nobles_pool = list(ALL_NOBLES)
                        random.shuffle(nobles_pool)
                        g["nobles"] = nobles_pool[:3]
                        r["status"] = "playing"
                save_game(room_id)
                await websocket.send_text(json.dumps({"type": "created", "room_id": room_id, "room": mk_room_state(room_id)}))
                if vs_ai:
                    asyncio.create_task(_schedule_ai_turn(room_id))

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
                asyncio.create_task(_schedule_ai_turn(room_id))

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
                asyncio.create_task(_schedule_ai_turn(room_id))

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
                _noble_choice_pid: str | None = None

                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if not r:
                        _err = "game not started"
                    elif r.get("status") == "over":
                        _err = "game is over"
                    elif r.get("status") != "playing":
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

                            if g.get("pending_noble_pid") == pid and move_type != "pick_noble":
                                _err = "must choose a noble first"
                            elif g.get("pending_discard_pid") == pid and move_type not in ("discard", "undo_discard"):
                                _err = "must discard down to 10 gems first"
                            elif move_type == "take_gems":
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
                                            _pre = copy.deepcopy(g)  # for undo if this overfills
                                            for c in colors:
                                                g["bank"][c] -= 1
                                                ps["tokens"][c] = ps["tokens"].get(c, 0) + 1
                                            _log_move(g, pid, "take_gems", colors=colors)
                                            _did_change = True
                                            if sum(ps["tokens"].values()) > 10:
                                                _discard_pid = pid
                                                g["pending_discard_pid"] = pid
                                                g["pre_discard_snapshot"] = _pre
                                            else:
                                                g.pop("pending_discard_pid", None)
                                                _finish_turn(g, pid)
                                                _post_turn(g, r)

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
                                        g["pending_discard_pid"] = pid
                                    else:
                                        g.pop("pending_discard_pid", None)
                                        g.pop("pre_discard_snapshot", None)
                                        _finish_turn(g, pid)
                                        _post_turn(g, r)

                            elif move_type == "undo_discard":
                                # Revert the whole over-filling action (take/reserve) and any
                                # discards made since, restoring the pre-action snapshot.
                                snap = g.get("pre_discard_snapshot")
                                if g.get("pending_discard_pid") != pid or not snap:
                                    _err = "nothing to undo"
                                else:
                                    r["game"] = copy.deepcopy(snap)  # snapshot has no pending/snapshot keys
                                    g = r["game"]
                                    _did_change = True

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
                                        _log_move(g, pid, "buy", card={"id": card["id"], "bonus": card["bonus"], "color": card["bonus"], "points": card["points"], "cost": card["cost"], "level": card.get("level")})
                                        claimable = _check_nobles(g, pid)
                                        if len(claimable) > 1:
                                            g["pending_noble_choice"] = [n["id"] for n in claimable]
                                            g["pending_noble_pid"] = pid
                                            _noble_choice_pid = pid
                                        elif claimable:
                                            n = claimable[0]
                                            ps["nobles"].append(n)
                                            g["nobles"] = [x for x in g["nobles"] if x["id"] != n["id"]]
                                            _log_move(g, pid, "noble", pts=n["points"])
                                            _finish_turn(g, pid)
                                            _post_turn(g, r)
                                        else:
                                            _finish_turn(g, pid)
                                            _post_turn(g, r)
                                        _did_change = True

                            elif move_type == "reserve":
                                if len(ps["reserved"]) >= 3:
                                    _err = "already have 3 reserved"
                                else:
                                    _pre = copy.deepcopy(g)  # for undo if this overfills
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
                                        _log_move(g, pid, "reserve", card={"id": card["id"], "bonus": card["bonus"], "color": card["bonus"], "points": card["points"], "cost": card["cost"], "level": card.get("level")})
                                        _did_change = True
                                        if sum(ps["tokens"].values()) > 10:
                                            _discard_pid = pid
                                            g["pending_discard_pid"] = pid
                                            g["pre_discard_snapshot"] = _pre
                                        else:
                                            g.pop("pending_discard_pid", None)
                                            _finish_turn(g, pid)
                                            _post_turn(g, r)
                            elif move_type == "pick_noble":
                                noble_id = mv.get("noble_id")
                                pending = g.get("pending_noble_choice") or []
                                if g.get("pending_noble_pid") != pid or noble_id not in pending:
                                    _err = "no noble choice pending"
                                else:
                                    noble = next((n for n in g["nobles"] if n["id"] == noble_id), None)
                                    if not noble:
                                        _err = "noble not found"
                                    else:
                                        ps["nobles"].append(noble)
                                        g["nobles"] = [x for x in g["nobles"] if x["id"] != noble_id]
                                        _log_move(g, pid, "noble", pts=noble["points"])
                                        g.pop("pending_noble_choice", None)
                                        g.pop("pending_noble_pid", None)
                                        _finish_turn(g, pid)
                                        _post_turn(g, r)
                                        _did_change = True
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
                    if _noble_choice_pid:
                        msg_out["needs_noble_choice"] = _noble_choice_pid
                    await broadcast_room(room_id, msg_out)
                    # If no pending human action remains, check whether it's now the AI's turn
                    if not _discard_pid and not _noble_choice_pid:
                        asyncio.create_task(_schedule_ai_turn(room_id))

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
                # Only clean up if our socket hasn't been replaced by a reconnect.
                # If it has, the new socket is already registered; removing it would
                # delete the room and cause "game not started" on the next move.
                if r["sockets"].get(pid) is websocket:
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


@app.post("/games/{game_id}/cancel")
async def cancel_open_game(game_id: str, token: str | None = None,
                           player_id: str | None = None):
    # An open game is just a public waiting room (host_id is listed in /games).
    # Authorize by a live session OR by the host's player_id, so cancelling still
    # works after the session token expires (which otherwise breaks it silently).
    user = get_user_by_session(token)
    owner = user["id"] if user else (player_id or None)
    if not owner:
        return {"ok": False, "message": "missing identity"}
    room_id = normalize_room(game_id)
    deleted = delete_open_game(room_id, owner)
    if deleted:
        async with ROOM_LOCK:
            ROOMS.pop(room_id, None)
    return {"ok": deleted, "message": None if deleted else "not your open game"}


@app.post("/me/session-token")
async def session_token(token: str | None = None, room_id: str | None = None, player_id: str | None = None):
    user = get_user_by_session(token)
    if not user:
        return {"ok": False, "message": "unauthenticated"}
    if not room_id or not player_id:
        return {"ok": False, "message": "room_id and player_id required"}
    rt = create_reconnect_token(user["id"], normalize_room(room_id), player_id, ttl=120)
    return {"ok": True, "reconnect_token": rt}


# ── Castles of Crimson ──────────────────────────────────────────────────────
# Second game in the Forrest Games collection. Its self-contained FastAPI
# sub-app is mounted under /coc so the whole site runs as one backend service
# (WS = /coc/ws/{room}/{player}, REST = /coc/...). This import is at the very
# end of the module on purpose: coc.main lazily imports Spender's auth helpers,
# and by the time this line runs every name coc needs is already defined above.
from games.castles_of_crimson.main import coc_app  # noqa: E402

app.mount("/coc", coc_app)
