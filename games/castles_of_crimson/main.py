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
import concurrent.futures
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
from . import persist               # at-rest compaction for the state_json blob
from . import ai as coc_ai          # MCTS opponent (aliased: `ai` is used as a local for the bot pid)

# Expert-tier client-side AI (browser WASM): the compact projection + the
# compact-move bridge. Defensive import (same rationale as the /coc mount guard):
# if az/ is ever absent, expert rooms silently degrade to the hard server bot.
try:
    from .az import bridge as az_bridge, compact as az_compact
except Exception:                                        # pragma: no cover
    az_bridge = az_compact = None

from core.db import get_db_conn, cleanup_stale_games, maybe_cleanup_games
from core.auth import (
    gen_token, get_user_by_session, validate_reconnect_token, mark_reconnect_token_used,
)
from core.config import cors_allowed_origins
from core import rooms as _rooms
from core.build_info import build_info

LOG = logging.getLogger("games.castles_of_crimson")

# Valid AI difficulty levels; unknown values fall back to the default.
# The ladder was reshuffled 2026-07-09 (each tier took the one above's brain):
#   "easy"   = the MCTS-heuristic server bot at its strong config (the tier
#              formerly SERVED as "hard"; ai.play_turn_plan difficulty="hard").
#   "hard"   = the previous Expert: the first netval champion net, searched
#              CLIENT-side (browser WASM) from coc_pv_model_hard.bin.
#   "expert" = the r2 net (high-sims + PCR self-play lineage), client-side
#              from coc_pv_model.bin. Beats the hard-tier net 0.61 train /
#              0.53-0.55 serving config on fresh seeds.
# "normal" is LEGACY (pre-reshuffle saved rooms + old cached clients): kept
# valid so old games keep playing their original weaker server bot, but the
# lobby no longer offers it. Client-side tiers degrade per-decision to the
# hard SERVER bot on any client failure (watchdog), same as before.
AI_DIFFICULTIES = ("easy", "normal", "hard", "expert")
DEFAULT_DIFFICULTY = "hard"
# Tiers whose moves are searched client-side (browser WASM) + the model file
# tag the client should load for each (see coc-worker.js).
CLIENT_AI_TIERS = ("hard", "expert")
_CLIENT_AI_MODEL = {"hard": "coc_pv_model_hard.bin", "expert": "coc_pv_model.bin"}

# Expert client-search config. _EXPERT_MODE mirrors the offline gate verdict:
# "netval" = net policy prior + 30-step rollout (NETVAL_ROLLOUT_STEPS) + the net VALUE HEAD at the
# truncation. It beats the plain-"hybrid" (heuristic-truncation) leaf ~0.58-0.61,
# and the edge GROWS with sims (gated on two fresh seed bases + a scaffold
# yardstick jump 0.36->0.52) — the campaign's one genuine gain over the bootstrap.
# "pv" (pure static net leaf) and "hybrid" both LOSE to netval; kept as references.
_EXPERT_MODE = "netval"
_EXPERT_BUDGET_MS = 1500         # TOTAL per micro-decision; the client searches in
                                 # ~500ms slices with tree continuation and stops
                                 # early when the visit lead is uncatchable, so easy
                                 # decisions still resolve in ~500ms (sims ladder
                                 # 2026-07-10: strength climbs to a 4-8k sims knee,
                                 # so contested decisions earn the longer think)
_EXPERT_MAX_SIMS = 20000         # per worker (bounds browser-tab memory)
# Per-decision watchdog: if the client hasn't answered in this window, the server
# finishes the TURN with the hard bot (play_turn_plan) — same envelope as Spender.
CLIENT_AI_TIMEOUT = 8.0
# Pause between the bot's individual moves so the client animates each tile in turn
# (a whole-turn bulk update trips the flyer's catch-up guard and animates nothing).
# Slow enough to watch each move land on the opponent board (the flyer plays ~0.5s).
_BOT_MOVE_DELAY = 1.0
# A longer pause when a phase has just ended, so the phase-end overlay + the mine-income
# tokens (silver/workers) have time to show before the bot plays on into the new phase.
_PHASE_END_PAUSE = 2.6
# A short settle after the human ends their turn, before the bot acts + their board comes
# up — so finishing your turn isn't immediately steamrolled by the opponent view. Matches
# the client's board-open delay so the board is up before the bot's first move lands.
_POST_TURN_PAUSE = 1.0
# Floor before the bot's very first move when NO human turn preceded it (the bot is the
# start player) — an instant opening move feels robotic. The post-turn/phase pauses above
# already exceed this in every other case.
_MIN_BOT_THINK = 0.7


def _valid_difficulty(value) -> str:
    return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY

coc_app = FastAPI(title="Castles of Crimson API")
# Same pinned origins as the parent app (it overrides this layer when mounted, but
# keeping them aligned matters if coc_app is ever run standalone). See core.config.
coc_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Room-Token"],
)

# ── In-memory room state ──────────────────────────────────────────────────────
ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()
AI_PID = "bot"
MAX_PLAYERS = 4        # human-vs-human games seat 2-4 players (vs-bot stays 2)


def _valid_board(board_id) -> str:
    """Coerce a client-supplied board id to a real one (default on anything bad)."""
    if isinstance(board_id, str) and board_id in board.BOARDS:
        return board_id
    return board.DEFAULT_BOARD_ID


def _valid_max_players(value) -> int:
    """Host-chosen seat cap for a VS-Friend game, clamped to 2..MAX_PLAYERS. A missing/invalid
    value defaults to MAX_PLAYERS (permissive) so a client that doesn't send it isn't capped at 2."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return MAX_PLAYERS
    return n if 2 <= n <= MAX_PLAYERS else MAX_PLAYERS


# ── Shared-identity / DB helpers (thin aliases over the shared core package) ──
# ── Shared room-server primitives (core/rooms.py) ─────────────────────────────
# These were byte-identical in all four games. Aliased under the historical private
# names so the rest of this module (and its tests) are unchanged.

normalize_room = _rooms.normalize_room
_gen_token = _rooms.gen_room_token
_db = _rooms.db_conn
_send = _rooms.send_json


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def coc_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS coc_games (
        id TEXT PRIMARY KEY,
        status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        player3_id TEXT, player3_name TEXT,
        player4_id TEXT, player4_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    # Tolerant ALTER for the pre-existing 2-player prod table (columns may already exist).
    for col in ("player3_id TEXT", "player3_name TEXT", "player4_id TEXT", "player4_name TEXT"):
        try:
            cur.execute(f"ALTER TABLE coc_games ADD COLUMN {col}")
        except Exception:  # noqa: BLE001 — column already present
            pass
    conn.commit()
    conn.close()


coc_init_db()
# Retention: same policy as Spender (guest 24h / registered 30d / open lobbies 48h, by last activity).
cleanup_stale_games("coc_games")


# ── Persistence ───────────────────────────────────────────────────────────────
# Persisting a room is a remote write (Turso/libSQL in prod): a fresh connection
# per save is a TLS+auth handshake, and running it on the event loop blocked every
# move for the round-trips. So writes go to a DEDICATED SINGLE-THREAD executor with
# its OWN persistent connection: (1) the connection is reused (no per-move
# handshake), (2) the event loop is never blocked, (3) a single worker keeps writes
# strictly in submission order (no interleaving/last-writer-loses race). save_game
# snapshots+serializes the row on the CALLING thread (fast, race-free vs ROOMS) then
# fires the write off; a failed write drops the connection so the next one reconnects.
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="coc-db-write")
_save_conn = None  # persistent write connection; ONLY ever touched by the _DB_WRITE_EXEC thread


def _persist_row(room_id, status, seats, host, state_json, now, created_at) -> None:
    """Upsert one coc_games row on the dedicated write thread using a reused connection.

    `seats` is a list of (player_id, player_name) in seat order (up to 4). The columns
    are a query index (the authoritative player list is in state_json); seats 2-4 can
    fill in after creation (late joiners), so UPDATE rewrites them all."""
    global _save_conn
    ids = [None, None, None, None]
    names = [None, None, None, None]
    for i, (pid, pname) in enumerate(seats[:4]):
        ids[i], names[i] = pid, pname
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        cur.execute("SELECT id FROM coc_games WHERE id=?", (room_id,))
        if cur.fetchone() is not None:
            cur.execute("""UPDATE coc_games SET status=?,
                             player2_id=?, player2_name=?, player3_id=?, player3_name=?,
                             player4_id=?, player4_name=?, state_json=?, updated_at=?
                           WHERE id=?""",
                        (status, ids[1], names[1], ids[2], names[2], ids[3], names[3],
                         state_json, now, room_id))
        else:
            cur.execute("""INSERT INTO coc_games
                           (id,status,player1_id,player1_name,player2_id,player2_name,
                            player3_id,player3_name,player4_id,player4_name,
                            host_id,state_json,created_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, ids[0], names[0], ids[1], names[1],
                         ids[2], names[2], ids[3], names[3], host, state_json, created_at, now))
        _save_conn.commit()
    except Exception:  # noqa: BLE001 — a save must never crash; drop the (maybe stale) conn so the next reconnects
        LOG.warning("coc save_game write failed for %s; dropping connection to reconnect next time", room_id,
                    exc_info=True)
        try:
            if _save_conn is not None:
                _save_conn.close()
        except Exception:
            pass
        _save_conn = None


def _encode_state(state: dict) -> str:
    """The ONLY write path into `state_json` — compact, then the shared zlib codec."""
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    """The ONLY read path out of `state_json`. Every read must funnel through here:
    a compacted blob reaching a caller that skipped `expand_state` would hand it
    `[id, shape]` pairs where it expects tiles. Rows written before compaction carry
    no marker and pass through untouched."""
    return persist.expand_state(_rooms.decode_state(blob))


def save_game(room_id: str) -> None:
    """Snapshot the room on the calling thread (fast, no I/O) then persist OFF the
    event loop via the single-thread write executor (fire-and-forget)."""
    room = ROOMS.get(room_id)
    if not room:
        return
    seats = list(room.get("players", {}).items())   # (id, name) in seat order, up to 4
    state = {
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "max_players": room.get("max_players"),
        "same_board": room.get("same_board", False),
        "boards": room.get("boards", {}),
    }
    now = int(time.time())
    _DB_WRITE_EXEC.submit(
        _persist_row, room_id, room.get("status", "open"), seats,
        room.get("host"), _encode_state(state), now, now,
    )


def load_game_state(room_id: str) -> dict | None:
    """Raw persisted room state (players/game/…) from the DB, without touching ROOMS.
    Used by the read-only finished-game review endpoint."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM coc_games WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return None
    try:
        return _decode_state(row["state_json"])
    except Exception:
        return None


def load_game_to_memory(room_id: str) -> bool:
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM coc_games WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return False
    try:
        state = _decode_state(row["state_json"])
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
        "max_players": state.get("max_players"),
        "same_board": state.get("same_board", False),
        "boards": state.get("boards", {}),
        "sockets": {},
    }
    return True


def _parse_state(row) -> dict:
    try:
        return _decode_state(row["state_json"])
    except Exception:
        return {}


def _ordered_players(state: dict) -> list[dict]:
    """[{id, name}] in seat order for a parsed room state (2-4 players). Uses the game's
    seat order once dealt, else the pre-start room player list."""
    g = state.get("game") if isinstance(state, dict) else None
    names = (state.get("players") if isinstance(state, dict) else None) or {}
    if isinstance(g, dict) and g.get("order"):
        gp = g.get("players") or {}
        return [{"id": pid, "name": (gp.get(pid) or {}).get("name") or names.get(pid) or "Player"}
                for pid in g["order"]]
    return [{"id": pid, "name": nm} for pid, nm in names.items()]


def list_open_games() -> list[dict]:
    maybe_cleanup_games("coc_games", background=True)  # throttled (<=1/h), non-blocking: prune stale games during long-awake periods
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, state_json, created_at FROM coc_games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        state = _parse_state(r)
        players = _ordered_players(state)
        host_board = (state.get("boards") or {}).get(state.get("host"))
        out.append({"id": r["id"], "host_id": r["player1_id"], "host_name": r["player1_name"],
                    "player_count": len(players) or 1,
                    # WHO IS ALREADY SEATED. Every lobby's Open row asked only
                    # `host_id == myId`, so a player who joined someone ELSE'S
                    # table and then went back to the lobby was offered Join on a
                    # seat they already held — which the WS correctly refuses as a
                    # takeover. `seatStateOf` in shared/lobby.jsx turns these ids
                    # into the fourth answer that row needs: Return.
                    "player_ids": _rooms.state_seat_ids(state),
                    "max_players": _valid_max_players(state.get("max_players")),
                    "same_board": bool(state.get("same_board")),
                    "host_board": host_board,
                    "created_at": r["created_at"]})
    return out


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, status, player1_id, player1_name, player2_id, player2_name,
                          state_json, created_at, updated_at
                   FROM coc_games
                   WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                         AND status != 'over'
                   ORDER BY updated_at DESC""", (user_id,) * 4)
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        state = _parse_state(r)
        g = state.get("game") or {}
        players = _ordered_players(state)
        is_p1 = r["player1_id"] == user_id
        your_turn = isinstance(g, dict) and g.get("turn") == user_id
        out.append({
            "id": r["id"], "status": r["status"],
            "players": [{**p, "is_you": p["id"] == user_id} for p in players],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],  # legacy 2p fields
            "you_are_p1": is_p1, "your_turn": your_turn,
            "ai_difficulty": _rooms.state_ai_tier(state),
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
        state = _parse_state(r)
        g = state.get("game") or {}
        out.append({
            "id": r["id"],
            "players": _ordered_players(state),
            "player1_id": r["player1_id"], "player1_name": r["player1_name"],  # legacy 2p fields
            "player2_id": r["player2_id"], "player2_name": r["player2_name"],
            "turn": g.get("turn") if isinstance(g, dict) else None,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    """The user's FINISHED games (newest first) for the lobby History column: opponent,
    final scores, and whether they won — each reviewable via /games/{id}/review."""
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, player2_id, player2_name,
                          state_json, updated_at
                   FROM coc_games
                   WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                         AND status='over'
                   ORDER BY updated_at DESC LIMIT ?""",
                (user_id,) * 4 + (_rooms.HISTORY_LIMIT,))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        state = _parse_state(r)
        g = state.get("game") or {}
        if not isinstance(g, dict) or not g.get("players"):
            continue
        try:
            scores = engine.final_scores(g)
        except Exception:
            scores = {}
        win = g.get("winner")
        players = _ordered_players(state)
        opps = [p for p in players if p["id"] != user_id]
        opp_name = ", ".join(p["name"] for p in opps) if opps else "Opponent"
        top_opp = max(opps, key=lambda p: scores.get(p["id"], 0), default=None)  # best opponent, for the 2-num display
        you_won = (win == user_id) or (isinstance(win, list) and user_id in win)
        out.append({
            "id": r["id"], "opp_name": opp_name,
            "players": [{**p, "is_you": p["id"] == user_id, "score": scores.get(p["id"])} for p in players],
            "your_score": scores.get(user_id),
            "opp_score": scores.get(top_opp["id"]) if top_opp else None,
            "you_won": you_won, "tie": isinstance(win, list),
            "ai_difficulty": _rooms.state_ai_tier(state),
            "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    """Cancel an open game this user hosts. SELECT-then-DELETE lives in
    core.rooms — never cursor.rowcount (absent on libsql; it 500'd prod)."""
    return _rooms.delete_open_game("coc_games", "player1_id", game_id, user_id)


# ── Room helpers ──────────────────────────────────────────────────────────────
async def broadcast_room(room_id: str, msg: dict[str, Any]) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    meta = room.get("meta", {})
    # Scope the reconnect token per recipient: the caller builds one consistent room
    # snapshot (no token), and each socket gets ONLY its own token injected — never
    # other seats'. Non-"room" messages fan out flat.
    room_state = msg.get("room") if isinstance(msg.get("room"), dict) else None
    flat = json.dumps(msg) if room_state is None else None
    for pid, ws in list(room.get("sockets", {}).items()):
        if room_state is not None:
            tok = meta.get(pid, {}).get("token")
            m = dict(msg)
            m["room"] = {**room_state, "reconnect_tokens": {pid: tok} if tok else {}}
            data = json.dumps(m)
        else:
            data = flat
        try:
            await ws.send_text(data)
        except Exception:
            pass


def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    g = room.get("game")
    if isinstance(g, dict):
        # Hidden-info redaction for the wire (mirrors Spender/Duel): the ordered draw piles are
        # future depot tiles, and rng_state lets a client reconstruct every future die for BOTH
        # players — both hidden in real Castles of Burgundy. The frontend reads none of them (the
        # visible depots live in `depots`/`boards`). Shallow-copy so the live game dict is untouched.
        #
        # `turn_undo` MUST be in this list. It is a whole-game snapshot, so it carries its own
        # copies of all four keys above and shipping it defeated every one of them — measured at
        # 100 ordered supply tiles plus rng_state reaching the client on a mid-game broadcast.
        # This is the same leak class as the 2026-07 audit (Spender `decks`, WW `deck`, the CoC
        # supplies): redacting a field is not enough while something else nests a copy of it.
        # The frontend never reads it — the Undo button's enabled state is derived client-side
        # from whether you have acted this turn (`actedThisTurn`), not from the snapshot.
        _HIDE = ("supply", "black_supply", "goods_supply", "rng_state", "turn_undo")
        if any(k in g for k in _HIDE):
            g = {k: v for k, v in g.items() if k not in _HIDE}
    state = {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": g,
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "max_players": room.get("max_players") or MAX_PLAYERS,
        "same_board": room.get("same_board", False),
        "boards": room.get("boards", {}),
        # Only the recipient's OWN reconnect token. Direct replies pass viewer_pid=pid;
        # broadcast_room injects each recipient's token per socket. (Was: every seat's
        # token to everyone — a needless secret leak.)
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }
    # Ship the itemized VP breakdown + (projected) final scores so the review can show
    # exactly where each player's points came from and on which turn. Computed every
    # update (cheap — a move-log scan) so it's viewable mid-game too; during play the
    # end-of-game items are a projection the frontend fades until the game is actually
    # over. Only present once a game is under way (has players).
    if g and isinstance(g, dict) and g.get("players"):
        state["final_scores"] = engine.final_scores(g)
        state["vp_breakdown"] = {pid: engine.vp_breakdown(g, pid) for pid in g["players"]}
    # Expert tier: the bot decision currently awaiting the client's WASM search.
    # Living in room state (not a one-shot message) means reconnects/re-broadcasts
    # re-ship it — the same durability rule as the engine's pending sub-decisions.
    if room.get("_ai_search"):
        state["ai_search"] = room["_ai_search"]
    return state


def _sync_status_from_game(room: dict) -> None:
    g = room.get("game")
    if g and engine.is_over(g):
        room["status"] = "over"


# ── Opponent (bot) turn scheduler ─────────────────────────────────────────────
async def _client_bot_turn(room_id: str) -> None:
    """Expert tier: drive the bot's turn one ENGINE-MOVE DECISION at a time through
    the human's browser (WASM search). Each searched decision ships via `ai_search`
    in room state; the `ai_move` handler validates + BUFFERS the returned move (it no
    longer applies it) and wakes us. We ship the NEXT decision's `ai_search` BEFORE
    awaiting the CURRENT move's animation pause, so the client searches the next move
    WHILE this one animates — the ~900ms search hides under the ~1s pace instead of
    adding to it. Single-legal decisions are applied server-side without a
    round-trip. Returns when the bot's turn is over, or on any timeout/error — the
    caller's server path then finishes the turn, so degradation is per-turn, never a
    deadlock."""
    pause_task = None                            # the PREVIOUS move's animation pause (overlaps the next search)
    try:
        for _ in range(60):                      # decision guard (a turn is a handful of moves)
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room:
                    return
                game = room.get("game")
                ai_pid = room.get("ai_player")
                if not _bot_should_act(room):
                    return                       # turn over — done
                if not room.get("client_ai"):
                    return                       # no armed client — server path
                legal = engine.legal_moves(game, ai_pid)
                if not legal:
                    return                       # engine contract violation — server path
                forced_move = None
                evt = None
                search_state = None
                if len(legal) == 1:
                    forced_move = legal[0]       # apply below (after the prev pause) — no round-trip
                else:
                    seq = room["_ai_decision_seq"] = room.get("_ai_decision_seq", 0) + 1
                    proj = az_compact.project(game)
                    # Canonicalize the undrawn pools (search determinization re-sorts
                    # them per sim anyway — this just avoids shipping the true order).
                    for k in ("supply", "black_supply", "goods_supply"):
                        proj[k] = sorted(proj[k])
                    room["_ai_search"] = {
                        "decision": seq,
                        "seat": game["order"].index(ai_pid),
                        "mode": _EXPERT_MODE,
                        "model": _CLIENT_AI_MODEL.get(
                            _valid_difficulty(room.get("ai_difficulty")),
                            _CLIENT_AI_MODEL["expert"],
                        ),
                        "budget_ms": _EXPERT_BUDGET_MS,
                        "max_sims": _EXPERT_MAX_SIMS,
                        "state": proj,
                    }
                    room["_ai_pending_move"] = None
                    evt = room["_ai_move_evt"] = asyncio.Event()
                    search_state = mk_room_state(room_id)
            # Ship the search request NOW so the client searches DURING the pause below.
            if search_state is not None:
                await broadcast_room(room_id, {"type": "room_update", "room": search_state})
            # Let the PREVIOUS move finish animating (overlaps the client's search above).
            if pause_task is not None:
                await pause_task
                pause_task = None
            # Resolve the move: forced -> local; searched -> the client's buffered move.
            if evt is None:
                move = forced_move
            else:
                try:
                    await asyncio.wait_for(evt.wait(), CLIENT_AI_TIMEOUT)
                except asyncio.TimeoutError:
                    async with ROOM_LOCK:
                        r = ROOMS.get(room_id)
                        if r:
                            r["_ai_search"] = None       # a late reply is ignored (stale decision)
                            r["_ai_pending_move"] = None
                    LOG.info("CoC client AI timed out; server finishes the turn (room %s)", room_id)
                    return
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    move = r.pop("_ai_pending_move", None) if r else None
                if move is None:
                    return                       # stale/invalid submit — server finishes the turn
            # Apply the move, broadcast it (this is the move landing on the board), persist.
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room:
                    return
                game = room.get("game")
                ai_pid = room.get("ai_player")
                if not game or not ai_pid or not _bot_should_act(room):
                    return
                phase_before = game.get("phase_letter")
                ok, _err = engine.apply_move(game, ai_pid, move)
                if not ok:
                    return                       # unexpected drift — server finishes the turn
                phase_changed = game.get("phase_letter") != phase_before
                room["_bot_last_phase"] = game.get("phase_letter")
                room["_ai_search"] = None
                _sync_status_from_game(room)
                done = not _bot_should_act(room)
                state = mk_room_state(room_id)
            await broadcast_room(room_id, {"type": "room_update", "room": state})
            save_game(room_id)
            if done:
                return                           # turn over — no trailing pause needed
            # Start THIS move's animation pause; the next iteration ships its search while it runs.
            pause_task = asyncio.create_task(
                asyncio.sleep(_PHASE_END_PAUSE if phase_changed else _BOT_MOVE_DELAY)
            )
    finally:
        if pause_task is not None and not pause_task.done():
            pause_task.cancel()
            try:
                await pause_task
            except asyncio.CancelledError:
                pass


async def _schedule_bot_turn(room_id: str) -> None:
    """Drive the AI opponent's whole turn.

    Expert rooms with an armed WASM client first try the per-decision client path
    (`_client_bot_turn`); any shortfall falls through to the server path below.
    The server MCTS is heavy, so it plans the turn on a snapshot **in a thread
    pool** (mirrors Spender's `_schedule_ai_turn`) and the planned move sequence is
    applied back under the lock. A trivial-bot finisher guarantees the turn always
    ends, so the game can never deadlock even if planning fails or the state
    drifts."""
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
        if room.get("_bot_running"):             # another bot-turn coroutine is already active
            return
        room["_bot_running"] = True              # guard: only one bot turn at a time (we release
                                                 # the lock between moves for per-move animation)
        difficulty = _valid_difficulty(room.get("ai_difficulty"))
        # Settle before the bot's first move. If a phase advanced (e.g. the human ended it),
        # use the longer pause so the phase overlay + income are seen first; otherwise a short
        # post-turn settle so finishing your turn isn't immediately steamrolled by the bot +
        # its board. Skip during setup (the bot-as-start-player case, no human turn preceded).
        phase_now = game.get("phase_letter")
        prev_bot_phase = room.get("_bot_last_phase")
        room["_bot_last_phase"] = phase_now
        if prev_bot_phase is not None and prev_bot_phase != phase_now:
            first_pause = _PHASE_END_PAUSE
        elif game.get("phase") == "playing":
            first_pause = _POST_TURN_PAUSE
        else:
            first_pause = _MIN_BOT_THINK   # bot-as-start-player (setup): still not instant

    try:
        if first_pause:
            await asyncio.sleep(first_pause)

        if difficulty in CLIENT_AI_TIERS and az_compact is not None:
            await _client_bot_turn(room_id)

        # Server path (easy/normal, and the hard/expert fallback). Snapshot AFTER
        # the client attempt — the client may have applied part of the turn.
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room:
                return
            need_server = _bot_should_act(room)
            snapshot = coc_ai._clone_game(room["game"]) if need_server else None
        # "easy" (and the client tiers' fallback) run the server bot at its
        # STRONG config — ai.py only knows normal/hard; legacy "normal" keeps
        # its original weaker config.
        plan_diff = "normal" if difficulty == "normal" else "hard"

        seq = None
        if need_server:
            # Plan the bot's turn off the event loop (MCTS may take a couple seconds).
            loop = asyncio.get_event_loop()
            try:
                seq = await loop.run_in_executor(
                    None,
                    lambda: coc_ai.play_turn_plan(snapshot, ai_pid, difficulty=plan_diff, rng=random.Random()),
                )
            except Exception:
                LOG.exception("CoC AI planning failed; finishing with the trivial bot")
                seq = None

        # Apply the planned sequence ONE MOVE AT A TIME, broadcasting after each so the
        # client animates the bot's tiles individually (a single bulk update trips the
        # flyer's adv>6 catch-up guard and animates nothing). We release the lock and
        # pause between moves; the _bot_running guard prevents a concurrent scheduler
        # (e.g. from a reconnect) from double-applying while the lock is free.
        for mv in (seq or []):
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room:
                    return
                game = room.get("game")
                ai_pid = room.get("ai_player")
                if not game or not ai_pid or engine.is_over(game):
                    break
                if (game.get("pending_pid") or game.get("turn")) != ai_pid:
                    break
                phase_before = game.get("phase_letter")
                ok, _ = engine.apply_move(game, ai_pid, mv)
                if not ok:
                    break
                phase_changed = game.get("phase_letter") != phase_before   # this move ended a phase
                room["_bot_last_phase"] = game.get("phase_letter")
                _sync_status_from_game(room)
                over = engine.is_over(game)
                still_bot = (game.get("pending_pid") or game.get("turn")) == ai_pid
                state = mk_room_state(room_id)
            await broadcast_room(room_id, {"type": "room_update", "room": state})
            if over or not still_bot:
                break                             # turn ended — stop pacing
            # A phase-ending move gets the longer pause so the overlay + income land first.
            await asyncio.sleep(_PHASE_END_PAUSE if phase_changed else _BOT_MOVE_DELAY)

        # Finisher: ensure the bot's turn actually ended (empty/failed plan or drift).
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room:
                return
            game = room.get("game")
            ai_pid = room.get("ai_player")
            if game and ai_pid and not engine.is_over(game):
                rng = random.Random()
                guard = 0
                while (not engine.is_over(game)
                       and (game.get("pending_pid") or game.get("turn")) == ai_pid
                       and guard < 200):
                    guard += 1
                    bot.play_turn(game, ai_pid, rng)
            _sync_status_from_game(room)
            final_state = mk_room_state(room_id)
        await broadcast_room(room_id, {"type": "room_update", "room": final_state})
        save_game(room_id)
    finally:
        async with ROOM_LOCK:
            r = ROOMS.get(room_id)
            if r:
                r["_bot_running"] = False
                r["_ai_search"] = None           # never leave a stale client decision armed
                r["_ai_pending_move"] = None     # nor a buffered move the turn never applied


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
    # Abuse throttles (core.rooms): cap connects per IP and messages per socket.
    if await _rooms.reject_if_connecting_too_fast(websocket):
        return
    _msg_throttle = _rooms.MessageThrottle()
    # The `player` path segment is CLIENT-SUPPLIED and NOT trusted: every pid in a room
    # is broadcast in the public players map, so anyone who can see a game can open a
    # socket claiming another seat's pid — and then move on its turn (`_handle_move`
    # only checks whose turn it is) or silently reassign its board (`_handle_join`
    # rewrites `boards[pid]` on every join). `authed` flips true only via a handshake
    # that proves ownership: create (minted the seat), join as a brand-new seat, join to
    # an existing seat with a matching session token, reconnect with the per-seat room
    # token, or auth_reconnect with a valid server token. Mirrors Where Wolf?'s binding.
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
                await websocket.send_text(json.dumps({"type": "error", "message": "bad message"}))
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
            elif action in ("start", "move", "abandon", "client_ai_ready", "ai_move"):
                # Privileged: only a socket that has PROVEN it owns `pid` may act as it.
                # (`start`/`move` also check host/turn, but pid alone is spoofable — this
                # is what makes those checks mean anything.)
                if not authed:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "message": "not authenticated for this seat"}))
                    continue
                if action == "start":
                    await _handle_start(websocket, room_id, pid)
                elif action == "move":
                    await _handle_move(websocket, room_id, pid, msg)
                elif action == "abandon":
                    await _handle_abandon(websocket, room_id, pid)
                elif action == "client_ai_ready":
                    await _handle_client_ai_ready(websocket, room_id, pid, msg)
                else:
                    await _handle_ai_move(websocket, room_id, pid, msg)
            else:
                await websocket.send_text(json.dumps({"type": "error", "message": "unknown action"}))
    except WebSocketDisconnect:
        pass
    finally:
        # Stale-socket guard + client-AI disarm + empty-room cleanup: core/rooms.py.
        _rooms.release_socket(ROOMS, room_id, pid, websocket, disarm_client_ai=True)


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    my_board = _valid_board(msg.get("board_id"))
    opp_board = _valid_board(msg.get("opp_board_id"))
    difficulty = _valid_difficulty(msg.get("ai_difficulty"))
    max_players = _valid_max_players(msg.get("max_players"))   # host-chosen seat cap (2-4; vs-AI is 2)
    same_board = bool(msg.get("same_board"))                   # force everyone onto the host's board
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
            "ai_difficulty": difficulty,
            "max_players": 2 if vs_ai else max_players,
            "same_board": same_board,
            "boards": {pid: my_board},
        }
        ROOMS[room_id] = room
        if vs_ai:
            room["players"][AI_PID] = "Bot"
            room["ai_player"] = AI_PID
            room["status"] = "playing"
            room["boards"][AI_PID] = opp_board
            seats = [pid, AI_PID]
            random.shuffle(seats)                     # randomize who takes the first turn
            room["game"] = engine.new_game(seats, names={pid: name, AI_PID: "Bot"},
                                           boards=room["boards"])
        save_game(room_id)
        bot_turn = vs_ai and _bot_should_act(room)
    await _send(ws, {"type": "created", "room_id": room_id, "room": mk_room_state(room_id, viewer_pid=pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))
    return True   # the creator minted this seat → owns it


async def _handle_join(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    # A logged-in user re-entering a seat they ALREADY hold (new device / cleared
    # storage → no per-seat room token) proves ownership with their session token:
    # pid == their account id, which an attacker can't forge. Resolved before the lock
    # (a DB read; mirrors _handle_auth_reconnect validating before ROOM_LOCK).
    sess = msg.get("session_token")
    session_uid = (get_user_by_session(sess) or {}).get("id") if sess else None
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        if pid in room["players"]:
            # Re-entry to an EXISTING seat. Identity MUST be proven: unproven, this
            # would rewrite that seat's `boards[pid]` below (changing someone else's
            # duchy mid-lobby) and hand the socket their view. `join` carries no room
            # token (that's `reconnect`), so a matching session is the only proof.
            if session_uid != pid:
                await _send(ws, {"type": "error",
                                 "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            cap = int(room.get("max_players") or MAX_PLAYERS)
            if room.get("vs_ai") or room.get("status") != "open" \
                    or len([p for p in room["players"] if p != AI_PID]) >= cap:
                await _send(ws, {"type": "error", "message": "room is full"})
                return False
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room.setdefault("boards", {})[pid] = _valid_board(msg.get("board_id"))
        room["sockets"][pid] = ws
        save_game(room_id)
    # Reply gets the joiner's own token; the broadcast base carries none (broadcast_room
    # injects each recipient's token per socket).
    await _send(ws, {"type": "joined", "room_id": room_id, "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})
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
        humans = [p for p in room["players"]]
        if not 2 <= len(humans) <= MAX_PLAYERS:
            await _send(ws, {"type": "error", "message": "need 2-4 players"})
            return
        if room.get("status") != "open":
            await _send(ws, {"type": "error", "message": "already started"})
            return
        room["status"] = "playing"
        boards = {p: _valid_board(room.get("boards", {}).get(p)) for p in humans}
        if room.get("same_board"):
            host_board = boards.get(room.get("host")) or _valid_board(None)   # everyone on the host's board
            boards = {p: host_board for p in humans}
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
        bot_turn = _bot_should_act(room)
    # Broadcast the new state FIRST so the client sees its move immediately, THEN
    # persist. The save is a remote (Turso) write; running it off the event loop
    # (see save_game) keeps it from blocking the broadcast/flush. This cut the
    # per-move round-trip from ~300-1600ms to ~90ms in production (the fresh
    # per-save connection handshake was the lag; save_game now reuses one).
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})
    save_game(room_id)
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_client_ai_ready(ws, room_id, pid, msg):
    """The client's WASM worker pool is up — arm the room for client-side expert
    search. Kicks the scheduler in case the bot is already waiting on a decision."""
    bot_turn = False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            return
        room["client_ai"] = True
        bot_turn = _bot_should_act(room) and not room.get("_bot_running")
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_ai_move(ws, room_id, pid, msg):
    """Validate the client's searched bot move (expert tier) and BUFFER it for
    `_client_bot_turn` to apply after the current animation pause — it no longer
    applies the move here, which lets the bot's NEXT search overlap that pause. The
    move arrives as the compact dict-move JSON (bridge.py shape) tagged with the
    decision seq; it is resolved via the bridge and validated by MEMBERSHIP in
    engine.legal_moves before buffering. A stale/illegal submission is LOGGED and
    dropped, never errored to the user (the watchdog fallback guarantees the turn
    advances — the Spender 'not the AI's turn' toast lesson)."""
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            return
        game = room.get("game")
        ai_pid = room.get("ai_player")
        pend = room.get("_ai_search")
        if not (game and ai_pid and pend) or msg.get("decision") != pend.get("decision"):
            LOG.info("stale/unexpected ai_move ignored (room %s)", room_id)
            return
        if az_bridge is None or not _bot_should_act(room):
            return
        compact_mv = msg.get("move")
        if isinstance(compact_mv, str):
            try:
                compact_mv = json.loads(compact_mv)
            except Exception:
                compact_mv = None
        try:
            mv = az_bridge.compact_to_move(game, ai_pid, compact_mv or {})
        except Exception:
            LOG.warning("ai_move bridge resolution failed (room %s)", room_id, exc_info=True)
            mv = None
        if mv is None or mv not in engine.legal_moves(game, ai_pid):
            LOG.warning("client ai_move not legal; leaving to the watchdog (room %s)", room_id)
            return
        # Buffer the resolved move + consume the request; _client_bot_turn applies it
        # once the previous move's animation pause elapses (see that fn for the overlap).
        room["_ai_pending_move"] = mv
        room["_ai_search"] = None
        evt = room.get("_ai_move_evt")
    if evt:
        evt.set()                                # wake the waiting _client_bot_turn


async def _handle_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "invalid token"})
            return False
        if room.get("meta", {}).get(pid, {}).get("token") != token:
            await _send(ws, {"type": "error", "message": "invalid token"})
            return False
        room["sockets"][pid] = ws
        bot_turn = _bot_should_act(room)
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id, viewer_pid=pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))
    return True   # per-seat room token proves ownership


async def _handle_auth_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    info = validate_reconnect_token(token)
    if not info or info.get("room_id") != room_id or info.get("player_id") != pid:
        await _send(ws, {"type": "error", "message": "invalid token"})
        return False
    mark_reconnect_token_used(token)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        room["sockets"][pid] = ws
        # refresh this player's room reconnect token
        room.setdefault("meta", {}).setdefault(pid, {})["token"] = _gen_token()
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id, viewer_pid=pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))
    return True   # server-issued reconnect token, scoped to (room_id, pid)


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
    return {"status": "ok", "service": "castles_of_crimson", "version": "1.0", **build_info()}


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
async def games_mine(token: str | None = Depends(_bearer_token),
                     player_id: str | None = None):
    # A GUEST HAS NO SESSION, and Active is the only list a STARTED game lands
    # in — so a friend invited by link, who backed out to the lobby to wait,
    # had no row anywhere once the host dealt. `lobby_viewer_id` in
    # core/rooms.py carries the reasoning and states exactly what the guest
    # fallback exposes; a real session always wins over the parameter.
    viewer = _rooms.lobby_viewer_id(get_user_by_session(token) if token else None, player_id)
    if not viewer:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_games(viewer)}


@coc_app.get("/games/active")
async def games_active():
    # Public: all in-progress games (yours + others'). Frontend pins yours on top.
    return {"ok": True, "games": list_active_games()}


@coc_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_history(user["id"])}


@coc_app.post("/games/{game_id}/leave")
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
    await broadcast_room(room_id, {"type": "room_update", "room": mk_room_state(room_id)})
    return {"ok": True}


@coc_app.get("/games/{game_id}/review")
async def games_review(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None):
    """Read-only review of a FINISHED game: final board + itemized VP breakdown +
    scores, for the lobby History 'Review' button. Restricted to over games so an
    in-progress game's full state isn't exposed here (resume it over WS instead), AND
    to a PARTICIPANT (mirrors Spender's /review): a logged-in player whose account id is
    in the game, or a guest presenting their in-game player_id — so an anonymous id-guess
    can't read another table's finished board."""
    game_id = normalize_room(game_id)
    room = ROOMS.get(game_id)
    if room and room.get("game"):
        g, players = room["game"], room.get("players", {})
    else:
        state = load_game_state(game_id)
        if not state:
            return {"ok": False, "message": "not found"}
        g, players = state.get("game"), state.get("players", {})
    if not isinstance(g, dict) or not g.get("players") or g.get("phase") != "over":
        return {"ok": False, "message": "game not finished"}
    user = get_user_by_session(token) if token else None
    requester = (user or {}).get("id") or player_id
    if not requester or requester not in players:
        return {"ok": False, "message": "not your game"}
    return {
        "ok": True, "game": g, "players": players, "winner": g.get("winner"),
        "final_scores": engine.final_scores(g),
        "vp_breakdown": {pid: engine.vp_breakdown(g, pid) for pid in g["players"]},
    }


@coc_app.post("/games/{game_id}/cancel")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None,
                       room_token: str | None = Header(default=None, alias="X-Room-Token")):
    game_id = normalize_room(game_id)
    owner = None
    user = get_user_by_session(token) if token else None
    if user:
        owner = user["id"]
    elif player_id:
        owner = player_id
    if not owner:
        return {"ok": False, "message": "unauthenticated"}
    if not user:
        async with ROOM_LOCK:
            room = _ensure_room_loaded(game_id)
            if not _rooms.authorized_open_host(room or {}, owner, room_token=room_token):
                return {"ok": False, "message": "could not verify this seat"}
    deleted = delete_open_game(game_id, owner)
    if deleted:
        async with ROOM_LOCK:
            ROOMS.pop(game_id, None)
    return {"ok": deleted, "message": None if deleted else "not your open game"}
