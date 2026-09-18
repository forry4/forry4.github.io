"""FastAPI sub-application for Spender Duel.

Exposes ``duel_app`` which the composition-root ``app.py`` mounts under
``/duel``. WebSocket lives at ``/duel/ws/{room}/{player}`` and REST under
``/duel/...``.

Thin layer over the pure ``engine``: rooms, sockets, persistence, WS protocol,
and the bot scheduler. Mirrors the proven Castles-of-Crimson patterns
(in-memory ``ROOMS`` under one asyncio.Lock, the dedicated single-thread DB
write executor, the stale-socket disconnect guard).

ONE structural difference from CoC: Spender Duel has hidden information
(secret reserves, the bag, the decks), so room state is built PER RECIPIENT
via ``engine.player_view`` — see ``broadcast_state`` — instead of one shared
snapshot. Persistence stores the FULL game; redaction happens on send.
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
from . import bot
from . import cards
from . import compact
from . import persist          # at-rest compaction for the state_json blob
from . import replay
# `ai` is used as a local name for the bot pid in places, so alias the module
# (the same collision CoC hit — see its `coc_ai` import).
from . import ai as duel_ai

from core.db import get_db_conn, cleanup_stale_games, maybe_cleanup_games
from core.auth import (
    gen_token, get_user_by_session, validate_reconnect_token, mark_reconnect_token_used,
)
from core.config import cors_allowed_origins
from core import rooms as _rooms
from core.build_info import build_info

LOG = logging.getLogger("games.spender_duel")

# Pause between the bot's individual moves so the client animates each one.
_BOT_MOVE_DELAY = 0.9
# A bot's FIRST move of a turn never lands sooner than this after the turn became
# the bot's — an instant reply (easy random bot, or a forced single-legal move)
# feels robotic. A floor, not an added delay: real search time counts toward it, so
# the heavy MCTS tiers (already > 0.7s) are unaffected.
_MIN_BOT_THINK = 0.7


async def _floor_bot_move(t0: float) -> None:
    """Sleep so the bot's first move isn't shown before _MIN_BOT_THINK from turn start.
    Idempotent — a no-op once that long has elapsed, so later (already-paced) moves pass through."""
    remaining = _MIN_BOT_THINK - (time.monotonic() - t0)
    if remaining > 0:
        await asyncio.sleep(remaining)

# Opponent tiers. "easy" = the trivial tiered random-legal bot (no search);
# "normal"/"hard" = determinized MCTS (ai.DIFFICULTY), planned in a thread pool.
AI_DIFFICULTIES = ("easy", "normal", "hard", "expert")
DEFAULT_DIFFICULTY = "hard"

# ── Client-side (WASM) search ────────────────────────────────────────────────
# The bot's search runs in the player's browser (duel-core -> wasm) instead of on
# Render's free tier, where it gets ~410 sims across ~76 root moves — about 5 sims per
# move, barely above random. Same bot, same leaf, same rules: only the sim count changes.
#
# "hard" ONLY, deliberately. "easy" has no search to move. "normal" is CALIBRATED to be
# beatable (small budget + temperature sampling, measured hard >> normal >> easy), so
# handing it ~100x the sims would quietly break the ladder — that is a strength change,
# and this is a serving change.
CLIENT_AI_TIERS = ("hard", "expert")
# The whole degradation story: no valid client move inside this and the SERVER plays the
# move itself with the existing Python bot. Per-decision, so a flaky client costs sims,
# never a stuck game.
CLIENT_AI_TIMEOUT = 8.0
# Per-DECISION budget: 3.5s wall-clock OR the aggregate sim cap across the worker pool, whichever
# comes FIRST. The pool splits the sim cap evenly (perWorker = max_sims / nworkers) and SUMS the
# workers' root stats; each worker stops on its own time OR sim bound. The attention-net leaf
# (Hard) is slow per sim, so on a phone the 3.5s clock usually binds first, while a fast desktop
# used to hit the sim cap. Both bounds sit under the 8s client watchdog (CLIENT_AI_TIMEOUT).
#
# RAISED 10k -> 20k (2026-07-27): the 10k cap was set at the then-measured saturation (~4-8k), but
# that was measured under PER-SIM determinization + max-max selection, where a marginal sim bought
# mostly cross-world noise. COHERENT + MINIMAX search makes each sim a real deepening of one sound
# world, which pushes saturation outward. At ~1420 sims/s/core (simd wasm) 3.5s allows ~5k/worker
# ~= 20k aggregate at the 4-worker pool cap, so the TIME bound now governs on desktop too (the sim
# cap stops being the binding constraint rather than being replaced by a bigger arbitrary one).
# Trade-off: a fast desktop now searches the full 3.5s instead of finishing early -> stronger, but
# moves visibly take longer. The saturation ladder under the new search is still pending.
_CLIENT_AI_BUDGET_MS = 3500
_CLIENT_AI_MAX_SIMS = 20000


def _valid_difficulty(value) -> str:
    """Coerce a client-supplied difficulty to a real tier (default on anything bad)."""
    return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY

duel_app = FastAPI(title="Spender Duel API")
duel_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── In-memory room state ──────────────────────────────────────────────────────
ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()
AI_PID = "bot"


# ── Shared room-server primitives (core/rooms.py) ─────────────────────────────
# These were byte-identical in all four games. Aliased under the historical private
# names so the rest of this module (and its tests) are unchanged.

normalize_room = _rooms.normalize_room
_gen_token = _rooms.gen_room_token
_db = _rooms.db_conn
_send = _rooms.send_json


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def duel_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS duel_games (
        id TEXT PRIMARY KEY,
        status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


duel_init_db()
# Retention: same policy as Spender/CoC (guest 24h / registered 30d / open lobbies 48h, by last activity).
cleanup_stale_games("duel_games")


# ── Persistence (single-thread write executor with a reused connection) ──────
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="duel-db-write")
_save_conn = None  # only ever touched by the _DB_WRITE_EXEC thread


def _persist_row(room_id, status, p1id, p1name, p2id, p2name, host, state_json, now, created_at) -> None:
    global _save_conn
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        cur.execute("SELECT id FROM duel_games WHERE id=?", (room_id,))
        if cur.fetchone() is not None:
            cur.execute("""UPDATE duel_games SET status=?, player2_id=?, player2_name=?, state_json=?, updated_at=?
                           WHERE id=?""",
                        (status, p2id, p2name, state_json, now, room_id))
        else:
            cur.execute("""INSERT INTO duel_games
                           (id,status,player1_id,player1_name,player2_id,player2_name,host_id,state_json,created_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, p1id, p1name, p2id, p2name, host, state_json, created_at, now))
        _save_conn.commit()
    except Exception:  # noqa: BLE001 — a save must never crash; reconnect next time
        LOG.warning("duel save_game write failed for %s; dropping connection", room_id, exc_info=True)
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
    """The ONLY read path out of `state_json`. Every read must funnel through here: a
    compacted blob reaching a caller that skipped `expand_state` would hand it a packed
    rng_state where it expects a list of ints. Rows written before compaction carry no
    marker and pass through untouched."""
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
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
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
    cur.execute("SELECT state_json FROM duel_games WHERE id=?", (room_id,))
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
        # Persisted so a vs-bot game reconnected after a redeploy (which wipes the
        # in-memory ROOMS) keeps the tier it was created with, instead of silently
        # falling back to the default — the bug Spender hit with ai_variant.
        "ai_difficulty": _valid_difficulty(state.get("ai_difficulty")),
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
    maybe_cleanup_games("duel_games", background=True)  # throttled (<=1/h), non-blocking
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, state_json, created_at FROM duel_games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "host_id": r["player1_id"], "host_name": r["player1_name"],
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
             "created_at": r["created_at"]} for r in rows]


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, status, player1_id, player1_name, player2_id, player2_name,
                          state_json, created_at, updated_at
                   FROM duel_games
                   WHERE (player1_id=? OR player2_id=?) AND status != 'over'
                   ORDER BY updated_at DESC""", (user_id, user_id))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            state = _decode_state(r["state_json"])
        except Exception:
            state = {}
        g = state.get("game") or {}
        your_turn = isinstance(g, dict) and (g.get("pending_pid") or g.get("turn")) == user_id
        out.append({
            "id": r["id"], "status": r["status"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": r["player1_id"] == user_id, "your_turn": your_turn,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, player2_id, player2_name,
                          state_json, updated_at
                   FROM duel_games
                   WHERE (player1_id=? OR player2_id=?) AND status='over'
                   ORDER BY updated_at DESC LIMIT ?""",
                (user_id, user_id, _rooms.HISTORY_LIMIT))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            state = _decode_state(r["state_json"])
        except Exception:
            state = {}
        g = state.get("game") or {}
        if not isinstance(g, dict) or not g.get("players"):
            continue
        is_p1 = r["player1_id"] == user_id
        opp_id = r["player2_id"] if is_p1 else r["player1_id"]
        opp_name = (r["player2_name"] if is_p1 else r["player1_name"]) or "Opponent"
        try:
            your_score = engine.points_of(g["players"][user_id]) if user_id in g["players"] else None
            opp_score = engine.points_of(g["players"][opp_id]) if opp_id in g["players"] else None
        except Exception:
            your_score = opp_score = None
        out.append({
            "id": r["id"], "opp_name": opp_name,
            "your_score": your_score, "opp_score": opp_score,
            "you_won": g.get("winner") == user_id,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "win_condition": g.get("win_condition"),
            "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    """Cancel an open game this user hosts. SELECT-then-DELETE lives in
    core.rooms — never cursor.rowcount (absent on libsql; it 500'd prod)."""
    return _rooms.delete_open_game("duel_games", "player1_id", game_id, user_id)


# ── Room state / broadcast (PER-RECIPIENT redaction) ─────────────────────────
def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    """Room snapshot AS SEEN BY viewer_pid: the game passes through
    engine.player_view so the bag, deck order, and the opponent's reserved-card
    identities never reach the wire. viewer_pid=None -> spectator redaction."""
    room = ROOMS.get(room_id, {})
    g = room.get("game")
    state = {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": engine.player_view(g, viewer_pid) if g else None,
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }
    # The bot decision currently awaiting the client's WASM search. It lives in ROOM
    # STATE rather than a one-shot message so every re-broadcast and reconnect re-ships
    # it — the same durability rule the engine's pending sub-decisions follow. Only ever
    # set on a vs-AI room (see _handle_client_ai_ready), which is what keeps the bot's
    # own view from reaching a human OPPONENT.
    if room.get("_ai_search"):
        state["ai_search"] = room["_ai_search"]
    return state


async def broadcast_state(room_id: str, mtype: str = "room_update") -> None:
    """Send each connected socket ITS OWN redacted view of the room."""
    room = ROOMS.get(room_id)
    if not room:
        return
    for pid, ws in list(room.get("sockets", {}).items()):
        try:
            await ws.send_text(json.dumps({"type": mtype, "room": mk_room_state(room_id, viewer_pid=pid)}))
        except Exception:
            pass


def _sync_status_from_game(room: dict) -> None:
    g = room.get("game")
    if g and engine.is_over(g):
        room["status"] = "over"


def _bot_should_act(room: dict) -> bool:
    game = room.get("game")
    ai = room.get("ai_player")
    return bool(game and ai and not engine.is_over(game)
                and (game.get("pending_pid") or game.get("turn")) == ai)


# ── Bot turn scheduler ────────────────────────────────────────────────────────
async def _client_bot_turn(room_id: str, t0: float) -> None:
    """Play the bot's turn one DECISION at a time through the human's browser.

    A Duel turn is several decisions (optional privilege/replenish -> the mandatory
    action -> ability pendings -> an AGAIN chain), so this loops: ship `ai_search`,
    wait for the client's `ai_move`, apply it, pace, repeat — until the turn passes.
    Unlike CoC there is no prefix protocol, because `engine.legal_moves` already hands
    back whole engine moves.

    Returns as soon as anything is off — turn over, timeout, drift, an unarmed client —
    and the caller's server path picks up from wherever we got to. So degradation is
    per-DECISION and a deadlock is impossible: the trivial-bot finisher still guarantees
    the turn ends.
    """
    for _ in range(60):                      # decision guard (a turn is a handful of moves)
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return                       # turn over — done
            if not room.get("client_ai"):
                return                       # no armed client — server path
            game = room["game"]
            legal = engine.legal_moves(game, AI_PID)
            if not legal:
                return                       # engine contract violation — server path
            if len(legal) == 1:
                # Nothing to decide: applying it here saves a pointless round-trip and
                # a full search budget, and it is trivially the move the search returns.
                forced, evt = legal[0], None
            else:
                forced = None
                seq = room["_ai_decision_seq"] = room.get("_ai_decision_seq", 0) + 1
                room["_ai_search"] = {
                    # The staleness key. A monotonic per-room counter rather than `ply`
                    # (= len(log)): every move type happens to log exactly one record
                    # today, so ply would work, but nothing ENFORCES that — a future
                    # silent handler would make two decisions share a key and a stale
                    # reply indistinguishable from a fresh one. `ply` rides along for the
                    # client's dispatch guard and logs.
                    "decision": seq,
                    "ply": len(game.get("log", [])),
                    "seat": game["order"].index(AI_PID),
                    "budget_ms": _CLIENT_AI_BUDGET_MS,
                    "max_sims": _CLIENT_AI_MAX_SIMS,
                    "state": compact.project(game, AI_PID),
                }
                room["_ai_pending_move"] = None
                evt = room["_ai_move_evt"] = asyncio.Event()

        if evt is None:
            move = forced
        else:
            await broadcast_state(room_id)   # ship the request
            try:
                await asyncio.wait_for(evt.wait(), CLIENT_AI_TIMEOUT)
            except asyncio.TimeoutError:
                async with ROOM_LOCK:
                    r = ROOMS.get(room_id)
                    if r:
                        r["_ai_search"] = None       # a late reply is ignored (stale decision)
                        r["_ai_pending_move"] = None
                LOG.info("duel client AI timed out; server finishes the turn (room %s)", room_id)
                return
            async with ROOM_LOCK:
                r = ROOMS.get(room_id)
                move = r.pop("_ai_pending_move", None) if r else None
            if move is None:
                return                       # stale/invalid submit — server finishes the turn

        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            ok, err = engine.apply_move(room["game"], AI_PID, move)
            if not ok:
                # Validated legal moments ago under this same lock, so this is drift, not
                # a bad client. Hand back to the server path rather than retry.
                LOG.info("duel client move no longer legal (%s): %s", room_id, err)
                return
            room["_ai_search"] = None
            _sync_status_from_game(room)
            more = _bot_should_act(room)
        await _floor_bot_move(t0)            # never show the turn's first move before the floor
        await broadcast_state(room_id)
        save_game(room_id)
        if not more:
            return                           # turn over — no trailing pause
        await asyncio.sleep(_BOT_MOVE_DELAY)


def _new_rng() -> random.Random:
    """Fresh entropy in production; a seam tests pin for DETERMINISTIC games.

    EVERY source of game entropy goes through here — the deck seed, the first-player
    shuffle, and the bot's move choices — because a test can otherwise only HOPE the game
    exercises the path it asserts on. That is exactly how the vs-AI wire-redaction test
    became flaky (~1/14: some deals simply never had the bot reserve, so its "a reserve
    actually happened" check failed on luck alone). A deploy gate must not be a coin flip.
    Production passes no seed, so play stays properly random.
    """
    return random.Random()


async def _schedule_bot_turn(room_id: str) -> None:
    """Drive the bot's whole turn, one move at a time with pacing so the client
    animates each move.

    A "hard" room with an armed WASM client tries the per-decision client path first
    (`_client_bot_turn`); any shortfall falls through to the server path below.

    The MCTS tiers are HEAVY (seconds per turn), so the search runs on a snapshot
    in a THREAD POOL and the planned sequence is applied back under the lock — the
    lock is never held across a search. (Running heavy engine work under ROOM_LOCK
    on the event-loop thread is what once took the CoC backend down; don't inline
    it here.) A trivial-bot finisher guarantees the turn always ends, so a failed
    or stale plan can never deadlock the game.
    """
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or room.get("_bot_running") or not _bot_should_act(room):
            return
        room["_bot_running"] = True
        difficulty = _valid_difficulty(room.get("ai_difficulty"))
        use_client = difficulty in CLIENT_AI_TIERS and bool(room.get("client_ai"))
    t0 = time.monotonic()                    # turn start — the first-move floor measures from here
    try:
        rng = _new_rng()
        if use_client:
            await _client_bot_turn(room_id, t0)

        # Server path (easy/normal, and the client tiers' fallback). Snapshot AFTER the
        # client attempt — it may have played part of the turn already.
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            snapshot = duel_ai._clone_game(room["game"]) if difficulty != "easy" else None

        seq = []
        if snapshot is not None:
            loop = asyncio.get_event_loop()
            try:
                seq = await loop.run_in_executor(
                    None,
                    lambda: duel_ai.play_turn_plan(snapshot, AI_PID, difficulty=difficulty,
                                                   rng=_new_rng()),
                )
            except Exception:
                LOG.exception("duel AI planning failed; finishing with the trivial bot")
                seq = []

        # Apply the plan move-by-move, re-validating each against the LIVE game (it
        # may have drifted — e.g. a reconnect re-triggered the scheduler).
        for mv in seq:
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room or not _bot_should_act(room):
                    return
                ok, err = engine.apply_move(room["game"], AI_PID, mv)
                if not ok:
                    LOG.info("duel planned move no longer legal (%s): %s", room_id, err)
                    break
                _sync_status_from_game(room)
                more = _bot_should_act(room)
            await _floor_bot_move(t0)
            await broadcast_state(room_id)
            save_game(room_id)
            if not more:
                return
            await asyncio.sleep(_BOT_MOVE_DELAY)

        # Finisher: guarantee the turn ends (empty/failed plan, drift, or "easy").
        for _ in range(80):
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room or not _bot_should_act(room):
                    return
                mv = bot.choose(room["game"], AI_PID, rng)
                if mv is None:
                    return
                ok, err = engine.apply_move(room["game"], AI_PID, mv)
                if not ok:
                    LOG.warning("duel bot move rejected (%s): %s", room_id, err)
                    return
                _sync_status_from_game(room)
                more = _bot_should_act(room)
            await _floor_bot_move(t0)
            await broadcast_state(room_id)
            save_game(room_id)
            if not more:
                return
            await asyncio.sleep(_BOT_MOVE_DELAY)
    finally:
        async with ROOM_LOCK:
            r = ROOMS.get(room_id)
            if r:
                r["_bot_running"] = False
                r["_ai_search"] = None       # never leave a stale client decision armed
                r["_ai_pending_move"] = None  # nor a buffered move the turn never applied


# ── WebSocket protocol ────────────────────────────────────────────────────────
@duel_app.websocket("/ws/{room}/{player}")
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
    # socket claiming the OPPONENT's pid. Duel's state is per-recipient redacted by
    # `viewer_pid`, so an unproven socket would otherwise be handed that seat's secret
    # reserves — and could submit moves on its turn (`_handle_move` only checks whose
    # turn it is). `authed` flips true only via a handshake that proves ownership:
    # create (minted the seat), join as a brand-new seat, join to an existing seat with
    # a matching session token, reconnect with the per-seat room token, or
    # auth_reconnect with a valid server-issued token. Mirrors Where Wolf?'s binding.
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
                # is what makes those checks mean anything. `client_ai_ready`/`ai_move`
                # are gated too: arming the client AI hands out the bot's search view.)
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
    difficulty = _valid_difficulty(msg.get("ai_difficulty"))
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
        }
        ROOMS[room_id] = room
        if vs_ai:
            room["players"][AI_PID] = "Bot"
            room["ai_player"] = AI_PID
            room["status"] = "playing"
            seats = [pid, AI_PID]
            _r = _new_rng()
            _r.shuffle(seats)  # randomize the first player (seat 1 gets the setup privilege)
            room["game"] = engine.new_game(seats, names={pid: name, AI_PID: "Bot"},
                                           seed=_r.randrange(2**31))
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
            # Re-entry to an EXISTING seat. Identity MUST be proven or the "joined"
            # reply below would hand a stranger this seat's redacted-for-them view —
            # which reveals their own secret reserves. `join` carries no room token
            # (that's `reconnect`), so the only proof here is a matching session.
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
    await _send(ws, {"type": "joined", "room_id": room_id, "room": mk_room_state(room_id, viewer_pid=pid)})
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
        humans = list(room["players"])
        if len(humans) != 2:
            await _send(ws, {"type": "error", "message": "need two players"})
            return
        if room.get("status") != "open":
            await _send(ws, {"type": "error", "message": "already started"})
            return
        room["status"] = "playing"
        _r = _new_rng()
        _r.shuffle(humans)  # random first player
        room["game"] = engine.new_game(humans, names=dict(room["players"]),
                                       seed=_r.randrange(2**31))
        save_game(room_id)
    await broadcast_state(room_id)


async def _handle_move(ws, room_id, pid, msg):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            await _send(ws, {"type": "error", "message": "game not started"})
            return
        game = room["game"]
        ok, err = engine.apply_move(game, pid, msg.get("move") or {})
        if not ok:
            await _send(ws, {"type": "error", "message": err or "illegal move"})
            return
        _sync_status_from_game(room)
        bot_turn = _bot_should_act(room)
    await broadcast_state(room_id)
    save_game(room_id)
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_client_ai_ready(ws, room_id, pid, msg):
    """The client's WASM worker pool is up — arm the room for client-side search. Kicks
    the scheduler in case the bot is already waiting on a decision.

    vs-AI ROOMS ONLY, and that is a security boundary, not a tidiness one: `ai_search`
    carries the BOT's view, including the bot's own blind reserves (the search can buy
    them, so they cannot be redacted). Between two humans that would be handing one
    player the other's face-down cards. Against the bot it is cheating at solitaire.
    """
    bot_turn = False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            return
        if not room.get("ai_player"):
            return
        room["client_ai"] = True
        bot_turn = _bot_should_act(room) and not room.get("_bot_running")
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_ai_move(ws, room_id, pid, msg):
    """Validate the client's searched bot move and BUFFER it for `_client_bot_turn`.

    THE SERVER STAYS AUTHORITATIVE: the move is decoded from the wire encoding and then
    validated by MEMBERSHIP in `engine.legal_moves`, so a tampered client can only ever
    play a move the bot was entitled to play — i.e. weaken its own opponent.

    A stale or illegal submission is LOGGED and DROPPED, never errored back to the user:
    a late reply is a normal race (the watchdog already covered it), not the player's
    fault — the Spender "not the AI's turn" toast lesson. Note an illegal move
    deliberately does NOT consume `_ai_search`, so the decision stays armed for the
    watchdog rather than falling through on a garbage submit.
    """
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            return
        game = room.get("game")
        pend = room.get("_ai_search")
        if not (game and room.get("ai_player") and pend):
            LOG.info("duel: unexpected ai_move with no decision armed (room %s)", room_id)
            return
        if msg.get("decision") != pend.get("decision"):
            LOG.info("duel: stale ai_move ignored (room %s)", room_id)
            return
        if not _bot_should_act(room):
            return
        raw = msg.get("move")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = None
        mv = compact.decode_move(raw)
        if mv is None or mv not in engine.legal_moves(game, AI_PID):
            LOG.warning("duel: client ai_move not legal; leaving it to the watchdog (room %s)", room_id)
            return
        room["_ai_pending_move"] = mv
        room["_ai_search"] = None
        evt = room.get("_ai_move_evt")
    if evt:
        evt.set()                            # wake the waiting _client_bot_turn


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
    await broadcast_state(room_id)


# ── REST ──────────────────────────────────────────────────────────────────────
@duel_app.get("/health")
async def health():
    return {"status": "ok", "service": "spender_duel", "version": "1.0", **build_info()}


@duel_app.get("/catalog")
async def catalog():
    """Static card/royal catalog + board constants (single source for the frontend)."""
    return {
        "ok": True,
        "cards": cards.CARDS,
        "royals": cards.ROYALS,
        "colors": cards.COLORS,
        "spiral": cards.SPIRAL_ORDER,
        "pyramid_sizes": cards.PYRAMID_SIZES,
    }


@duel_app.get("/games")
async def games_open():
    return {"ok": True, "games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return token


@duel_app.get("/games/mine")
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


@duel_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_history(user["id"])}


@duel_app.get("/games/{game_id}/review")
async def games_review(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None):
    """Read-only review of a FINISHED game, restricted to a participant.

    Returns the final board plus `snapshots` — one rebuilt board per move, for
    turn-by-turn rewind (replay.reconstruct, exact from the persisted seed + log).
    `snapshots` is None when a game can't be reconstructed (a pre-seed save, or log
    drift): the review still shows the final board, just without the rewind."""
    game_id = normalize_room(game_id)
    room = ROOMS.get(game_id)
    if room and room.get("game"):
        g, players = room["game"], room.get("players", {})
    else:
        state = load_game_state(game_id)
        if not state:
            return {"ok": False, "message": "not found"}
        g, players = state.get("game"), state.get("players", {})
    # Participation FIRST: a non-participant must not learn even whether the game exists/finished.
    # (player_id is the guest identity — same bearer model as reconnect tokens — so it's kept.)
    user = get_user_by_session(token) if token else None
    requester = (user or {}).get("id") or player_id
    if not requester or requester not in players:
        return {"ok": False, "message": "not your game"}
    if not isinstance(g, dict) or not g.get("players") or g.get("phase") != "over":
        return {"ok": False, "message": "game not finished"}
    return {
        "ok": True, "game": engine.player_view(g, requester), "players": players,
        "winner": g.get("winner"), "win_condition": g.get("win_condition"),
        "win_color": g.get("win_color"),
        "scores": {pid: engine.points_of(p) for pid, p in g["players"].items()},
        "snapshots": replay.review_payload(g),
    }


@duel_app.post("/games/{game_id}/cancel")
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
