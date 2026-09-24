"""Orbit room server — mounted at /orbit.

The same scaffolding as the other games: an in-memory ``ROOMS`` dict under a
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
  through ``engine.player_view`` for each socket's own pid, so the opposing hand,
  both deck orders, RNG state, and private decisions never reach the wrong wire.

Orbit alternates turns after the simultaneous opening mulligan. The random bot
and the two browser-served tiers use the exact same ``legal_moves`` /
``apply_move`` boundary; a missing browser answer always falls back server-side.

Hard RANKS the position; Expert SEARCHES it, rebuilding a world from the seat's
own observation because the worker never receives privileged state. Expert
cannot rebuild a pending chain -- the observation redacts the queue to its first
task -- so it ranks those decisions instead, and a room degrades per DECISION
rather than per game. Both tiers spend a per-decision ``budget_ms`` split from
the whole turn, and every reply is re-validated here before it is applied.
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
from core.db import cleanup_stale_games, get_db_conn, maybe_cleanup_games

from . import bot, engine, persist
from .ai import serving
from .ai.state import TASK_FIELDS, observation, pending_chain
from .cards import BONUS_TYPES, CARDS, FACTIONS, PLANETS, public_card

LOG = logging.getLogger("orbit")

TABLE = "orbit_games"
AI_PID = "bot"

# The ladder shifted down a peg on 2026-09-11 to make room at the top for the
# coherent-determinization search. Each NAME now points one rung stronger than
# it used to, and the random opponent left the product ladder entirely:
#
#   easy    the original public-information ranker   (was normal)
#   normal  the effect-aware ranker                  (was hard)
#   hard    the search, per-simulation worlds        (was expert)
#   expert  the search, one COHERENT world           (new)
#
# `bot.choose_move` -- the random opponent -- is deliberately kept even though
# no tier serves it: it is the correctness baseline the offline arenas and the
# engine tests measure against, not just the weakest menu row.
AI_DIFFICULTIES = ("easy", "normal", "hard", "expert")
# Rooms persist this name, so a room saved BEFORE the shift means one rung
# weaker than the same name means now. `AI_TIER_GENERATION` stamps rooms saved
# after it; a room without the stamp is remapped on load so a game in progress
# keeps the opponent it was actually started against.
AI_TIER_GENERATION = 2
_PRE_SHIFT_DIFFICULTY = {"easy": "easy", "normal": "easy", "hard": "normal", "expert": "hard"}
# Both browser tiers SEARCH through the same versioned boundary and share the
# same validated server fallback, and the tier travels on the wire because the
# worker needs it to pick which search to run.
#
# HARD is determinized MCTS, drawing a fresh world every simulation.
#
# EXPERT IS DEPTH-FIRST as of 2026-09-13: iterative-deepening alpha-beta with
# `state_value` at the leaf and `action_score` ordering the moves. The four
# browser workers each reconstruct their OWN world from the same observation and
# vote, which makes the pool a K=4 PIMC with every world getting the whole turn
# budget. Measured natively at 0.6172 against the coherent MCTS it replaces
# (64 CRN pairs, serving shape, mean depth 7.77 against the MCTS's 4.2), and the
# same depth is reached in wasm.
#
# `CLIENT_AI_DETERMINIZATION` below is still sent and still means what it says --
# it is what Hard uses, and it is what an OLDER cached wasm falls back to for
# Expert, which is the coherent MCTS: the previous Expert, not a broken room.
CLIENT_AI_TIERS = ("hard", "expert")
# Simulations per determinization, sent to the worker. 0 asks for one coherent
# world for the whole decision.
CLIENT_AI_DETERMINIZATION = {"hard": 1, "expert": 0}
DEFAULT_DIFFICULTY = "easy"
CLIENT_AI_WIRE = serving.SERVING_ABI_VERSION
CLIENT_AI_MODEL_VERSION = serving.MODEL_VERSION
CLIENT_AI_ENCODER = serving.ENCODER_VERSION
CLIENT_AI_SCHEMA = serving.SCHEMA_VERSION
CLIENT_AI_RULES = serving.rules_fingerprint()
CLIENT_AI_TIMEOUT = 6.25
CLIENT_AI_TURN_BUDGET_MS = serving.TURN_BUDGET_MS
CLIENT_AI_MAIN_ACTION_MS = serving.MAIN_ACTION_BUDGET_MS
CLIENT_AI_FOLLOWUP_RESERVE_MS = serving.FOLLOWUP_RESERVE_MS

#: A floor on how fast the bot answers. Orbit's board needs time to show the
#: last move and let its disc/resource cues finish before the next decision.
BOT_FLOOR_SECONDS = 1.00

orbit_app = FastAPI(title="Orbit API")
orbit_app.add_middleware(
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


def orbit_init_db() -> None:
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


orbit_init_db()
try:
    # Retention: guest 24h / registered 30d / open lobbies 48h, by last activity.
    # Guarded because this runs at IMPORT time and joins `users` — in a fresh
    # checkout that table may not exist yet, and a retention sweep must never
    # stop the module (or every test that imports it) from loading.
    cleanup_stale_games(TABLE)
except Exception as _cleanup_err:  # pragma: no cover - environment-dependent
    LOG.warning("orbit retention sweep skipped at import: %s", _cleanup_err)


# ── Persistence ──────────────────────────────────────────────────────────────
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="orbit-db-write")
_save_conn = None  # only ever touched by the write-executor thread


def _valid_difficulty(value) -> str:
    value = str(value or DEFAULT_DIFFICULTY).lower()
    # ``random`` was the old wire value for Easy. Normalize it as rooms are
    # loaded so persisted games remain playable after the tier rename.
    if value == "random":
        return "easy"
    return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY


def _loaded_difficulty(state) -> str:
    """Read a persisted tier, remapping rooms saved before the ladder shifted.

    The 2026-09-11 shift moved every NAME one rung stronger. A room saved before
    it therefore means something weaker by the same name, and reading it
    literally would hand a game in progress a stronger opponent than the one it
    was started against -- mid-game, without the player choosing it. Rooms saved
    since carry `ai_tier_generation`; anything without it is pre-shift and is
    mapped back to the tier that plays the same bot.
    """

    difficulty = _valid_difficulty(state.get("ai_difficulty"))
    if int(state.get("ai_tier_generation") or 0) >= AI_TIER_GENERATION:
        return difficulty
    return _PRE_SHIFT_DIFFICULTY.get(difficulty, difficulty)


def _requested_difficulty(value) -> str:
    """A tier this build does not know means a NEWER client, not a bad one.

    ``_valid_difficulty`` coerces the unknown to ``DEFAULT_DIFFICULTY`` because it
    also loads PERSISTED rooms, where an unrecognised value is a retired tier and
    the weakest bot is a safe reading. At room CREATION the same value means the
    opposite: the bundle is ahead of this server. That is not exotic -- Pages and
    Render deploy independently, so every coupled release has a window where it is
    true, and Orbit shipped exactly that window: the picker offered Expert while
    this file had never heard of it, and every Expert game silently got the RANDOM
    bot. Someone asking for the strongest tier should never be handed the weakest,
    so clamp UP to the strongest tier this build actually has.
    """

    raw = str(value or "").lower()
    if raw and raw != "random" and raw not in AI_DIFFICULTIES:
        return AI_DIFFICULTIES[-1]
    return _valid_difficulty(value)


def _loaded_ai_memory(raw, players) -> dict[str, dict]:
    """Restore only bounded, versioned serving memory for known seats."""

    if not isinstance(raw, dict):
        return {}
    result = {}
    for pid in players or []:
        value = raw.get(pid)
        if isinstance(value, dict):
            result[pid] = serving.normalise_memory(value)
    return result


def _loaded_budget(value) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


_OBS_KEYS = frozenset((
    "schema", "phase", "turn_pid", "turn_number", "influence",
    "captured_this_turn", "leader", "board_sides", "planet_bonus",
    "technology_bonus", "agent_discard", "bonus_discard", "mulligan_done",
    "pending_pid", "winner", "seat", "players", "agent_deck_count",
    "bonus_deck_count", "pending", "legal_moves",
))
_OBS_PLAYER_KEYS = frozenset((
    "credits", "zenithium", "columns", "technology", "row_bonuses",
    "captured", "hand_count", "hand",
))
_HISTORY_MOVE_KEYS = frozenset((
    "action", "card_id", "card_ids", "planet", "planets", "faction",
    "tier", "cost", "amount", "count", "accept", "branch", "bonus_area", "slot",
))


def _history_action_valid(value) -> bool:
    """Validate a recorded action without accepting arbitrary nested data."""

    return (isinstance(value, dict)
            and not (set(value) - _HISTORY_MOVE_KEYS)
            and isinstance(value.get("action"), str)
            and all(not isinstance(item, (dict, list))
                    for key, item in value.items()
                    if key not in {"card_ids", "planets"})
            and isinstance(value.get("card_ids", []), list)
            and isinstance(value.get("planets", []), list)
            and all(not isinstance(item, (dict, list))
                    and isinstance(item, int) and not isinstance(item, bool)
                    for item in value.get("card_ids", []))
            and all(not isinstance(item, (dict, list))
                    and isinstance(item, str)
                    for item in value.get("planets", [])))


def _history_task_valid(value) -> bool:
    if not isinstance(value, dict) or set(value) - TASK_FIELDS:
        return False
    options = value.get("options")
    if options is not None and (
            not isinstance(options, list)
            or any(not _history_action_valid(move) for move in options)):
        return False
    return True


def _history_players_valid(players, seat: int) -> bool:
    if not isinstance(players, list) or len(players) != 2:
        return False
    for index, player in enumerate(players):
        if not isinstance(player, dict) or set(player) - _OBS_PLAYER_KEYS:
            return False
        if index == seat:
            if "hand" not in player or not isinstance(player["hand"], list):
                return False
        elif "hand" in player:
            return False
        columns = player.get("columns")
        tech = player.get("technology")
        if (not isinstance(columns, list) or len(columns) != 5
                or any(not isinstance(column, list) for column in columns)
                or not isinstance(tech, list) or len(tech) != 3):
            return False
        for field in ("credits", "zenithium", "hand_count"):
            if (field in player
                    and (isinstance(player[field], bool)
                         or not isinstance(player[field], int))):
                return False
        if any(isinstance(card, bool) or not isinstance(card, int)
               for column in columns for card in column):
            return False
        if any(isinstance(level, bool) or not isinstance(level, int)
               for level in tech):
            return False
        for field in ("row_bonuses", "captured"):
            if field in player and (
                    not isinstance(player[field], list)
                    or any(isinstance(item, bool) or not isinstance(item, int)
                           for item in player[field])):
                return False
        if "hand" in player and any(
                isinstance(card, bool) or not isinstance(card, int)
                for card in player["hand"]):
            return False
    return True


def _history_pending_valid(pending) -> bool:
    if pending is None:
        return True
    if not isinstance(pending, dict) or set(pending) - {"source", "task", "waiting", "last_planet"}:
        return False
    if "source" in pending and not isinstance(pending["source"], str):
        return False
    if "waiting" in pending and not isinstance(pending["waiting"], bool):
        return False
    if "last_planet" in pending and pending["last_planet"] is not None \
            and not isinstance(pending["last_planet"], str):
        return False
    task = pending.get("task")
    return task is None or _history_task_valid(task)


def _history_observation_valid(value, seat: int) -> bool:
    """Check the structural allowlist without requiring the old position."""

    if not isinstance(value, dict) or set(value) != _OBS_KEYS:
        return False
    if value.get("schema") != serving.SCHEMA_VERSION or value.get("seat") != seat:
        return False
    if not _history_players_valid(value.get("players"), seat):
        return False
    if not _history_pending_valid(value.get("pending")):
        return False
    return all(_history_action_valid(move) for move in value.get("legal_moves", []))


def _history_changes_valid(value, seat: int) -> bool:
    """Validate event deltas so a hand-edited row cannot smuggle hidden data."""

    if not isinstance(value, dict) or set(value) - _OBS_KEYS:
        return False
    list_fields = {"influence", "captured_this_turn", "board_sides",
                   "planet_bonus", "technology_bonus", "mulligan_done",
                   "legal_moves"}
    for key, item in value.items():
        if key == "players" and not _history_players_valid(item, seat):
            return False
        if key == "pending" and not _history_pending_valid(item):
            return False
        if key == "legal_moves" and (
                not isinstance(item, list)
                or any(not _history_action_valid(move) for move in item)):
            return False
        if key == "leader" and (
                not isinstance(item, dict) or set(item) - {"owner", "level"}):
            return False
        if key in list_fields and not isinstance(item, list):
            return False
        if key in list_fields - {"legal_moves"} and any(
                isinstance(value, (dict, list)) for value in item):
            return False
        if key not in {"players", "pending", "legal_moves", "leader"} | list_fields \
                and isinstance(item, (dict, list)):
            return False
    return True


def _new_live_histories(game: dict) -> dict[str, dict]:
    """Create seat-local policy histories without consulting the display log."""

    return {
        pid: {
            "schema": serving.SCHEMA_VERSION,
            "rules": serving.rules_fingerprint(),
            "initial": observation(game, pid),
            "latest": observation(game, pid),
            "events": [],
        }
        for pid in game.get("order", [])
    }


def _loaded_histories(game: dict | None, raw) -> dict[str, dict]:
    """Restore structured histories, handling pre-Phase-5 saves conservatively.

    A legacy blob has no trustworthy policy history.  Start a fresh history at
    its current allowlisted observation; never rebuild private events from the
    raw game or display log.
    """

    if not isinstance(game, dict) or not game.get("order"):
        return {}
    if not isinstance(raw, dict) or set(raw) != set(game["order"]):
        return _new_live_histories(game)
    result = {}
    try:
        for pid in game["order"]:
            item = raw[pid]
            if (not isinstance(item, dict)
                    or item.get("schema") != serving.SCHEMA_VERSION
                    or item.get("rules") != serving.rules_fingerprint()):
                raise ValueError("history rules")
            initial = item.get("initial")
            events = item.get("events")
            if not isinstance(initial, dict) or not isinstance(events, list):
                raise ValueError("history shape")
            seat_index = game["order"].index(pid)
            if not _history_observation_valid(initial, seat_index):
                raise ValueError("history observation")
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("history event")
                if event.get("actor") not in (0, 1):
                    raise ValueError("history actor")
                changes = event.get("changes", {})
                if not _history_changes_valid(changes, seat_index):
                    raise ValueError("history changes")
                for field in ("public_action", "own_action"):
                    action = event.get(field)
                    if action is not None and not _history_action_valid(action):
                        raise ValueError("history action")
            latest = item.get("latest")
            if not isinstance(latest, dict):
                latest = copy.deepcopy(initial)
                for event in events:
                    if isinstance(event, dict) and isinstance(event.get("changes"), dict):
                        latest.update(copy.deepcopy(event["changes"]))
            # A history is seat-local and must still describe this seat's
            # current public view.  If an old schema is encountered, reset it
            # rather than attempting to infer hidden events.
            if int(latest.get("schema", -1)) != serving.SCHEMA_VERSION:
                raise ValueError("history schema")
            if not _history_observation_valid(latest, seat_index):
                raise ValueError("history latest")
            if latest != observation(game, pid):
                raise ValueError("history current observation")
            result[pid] = {
                "schema": serving.SCHEMA_VERSION,
                "rules": serving.rules_fingerprint(),
                "initial": copy.deepcopy(initial),
                "latest": copy.deepcopy(latest),
                # A legacy or hand-edited row must not make policy memory grow
                # without bound.  Events are already redacted on write;
                # retain only the bounded tail on restore as well.
                "events": copy.deepcopy(events[-512:]),
            }
    except (KeyError, TypeError, ValueError):
        return _new_live_histories(game)
    return result


def _live_observations(game: dict) -> dict[str, dict]:
    return {pid: observation(game, pid) for pid in game.get("order", [])}


def _record_history(room: dict, actor_pid: str, move: dict,
                    before: dict[str, dict] | None = None) -> None:
    """Append one redacted event per seat after a validated live move."""

    game = room.get("game")
    if not isinstance(game, dict):
        return
    histories = room.setdefault("seat_histories", _new_live_histories(game))
    if set(histories) != set(game.get("order", [])):
        histories.clear()
        histories.update(_new_live_histories(game))
    before = before or {pid: item.get("latest") for pid, item in histories.items()}
    for viewer in game.get("order", []):
        after = observation(game, viewer)
        previous = before.get(viewer) or histories[viewer].get("latest") or {}
        event = {
            "actor": game["order"].index(actor_pid),
            "changes": {
                key: copy.deepcopy(value)
                for key, value in after.items()
                if value != previous.get(key)
            },
        }
        action = move.get("action") if isinstance(move, dict) else None
        if action in ("recruit", "technology", "leader"):
            event["public_action"] = copy.deepcopy(move)
        elif action == "mulligan":
            event["public_action"] = {
                "action": "mulligan",
                "count": len(move.get("card_ids", [])),
            }
        if viewer == actor_pid:
            event["own_action"] = copy.deepcopy(move)
        histories[viewer].setdefault("events", []).append(event)
        histories[viewer]["latest"] = after
        # Keep persistent policy memory bounded independently of the display log.
        if len(histories[viewer]["events"]) > 512:
            histories[viewer]["events"] = histories[viewer]["events"][-512:]


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
        LOG.warning("orbit save failed for %s; dropping connection",
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
        "ai_difficulty": _valid_difficulty(room.get("ai_difficulty")),
        # Stamp which ladder these tier names belong to, so a room saved before
        # the 2026-09-11 shift stays readable as the bot it was started against.
        "ai_tier_generation": AI_TIER_GENERATION,
        "seat_histories": room.get("seat_histories", {}),
        "ai_memory": room.get("ai_memory", {}),
        # Wall-clock time survives a reconnect or a process reload.  It is
        # cleared at the next turn boundary; no private game state is encoded.
        "ai_turn_started_at": room.get("ai_turn_started_at"),
        "ai_budget_remaining_ms": room.get("ai_budget_remaining_ms"),
        "ai_decisions_this_turn": room.get("ai_decisions_this_turn", 0),
        "configuration": room.get("configuration", "sun"),
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
    game = state.get("game")
    histories = _loaded_histories(game, state.get("seat_histories"))
    ROOMS[room_id] = {
        "players": state.get("players", {}),
        "host": state.get("host"),
        "status": state.get("status", "open"),
        "game": game,
        "meta": state.get("meta", {}),
        "vs_ai": state.get("vs_ai", False),
        "ai_player": state.get("ai_player"),
        "ai_difficulty": _loaded_difficulty(state),
        "seat_histories": histories,
        "ai_memory": _loaded_ai_memory(state.get("ai_memory"), (game or {}).get("order", [])),
        "ai_turn_started_at": state.get("ai_turn_started_at"),
        "ai_budget_remaining_ms": _loaded_budget(state.get("ai_budget_remaining_ms")),
        "ai_decisions_this_turn": _loaded_budget(state.get("ai_decisions_this_turn", 0)) or 0,
        "client_ai": False,
        "_ai_search": None,
        "_ai_pending_move": None,
        "_ai_pending_sent_at": None,
        "configuration": state.get("configuration", "sun"),
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
            state = _decode_state(r["state_json"])
        except Exception:
            state = {}
        g = state.get("game") or {}
        out.append({
            "id": r["id"], "status": r["status"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": r["player1_id"] == user_id,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "your_turn": bool(g) and bool(engine.legal_moves(g, user_id)),
            "turn": g.get("turn_number") if g else None,
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
            state = _decode_state(r["state_json"])
        except Exception:
            state = {}
        g = state.get("game") or {}
        winner = g.get("winner")
        outcome = "draw" if winner is None else ("won" if winner == user_id else "lost")
        out.append({
            "id": r["id"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": r["player1_id"] == user_id,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "outcome": outcome,
            "turns": g.get("turn_number"),
            "updated_at": r["updated_at"],
        })
    return out


def _standings(state: dict) -> dict | None:
    """Who won a finished game, for the profile (core.results). No winner is a draw."""
    g = state.get("game") or {}
    if not isinstance(g, dict) or not engine.is_over(g):
        return None
    order = [p for p in (state.get("players") or {}) if p in (g.get("players") or {})]
    winner = g.get("winner")
    return _results.standings(state, order, [winner] if winner else [], draw=winner is None)


_results.register("orbit", TABLE, decode=_decode_state, standings=_standings)


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
    state = {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        # Rebuilt for THIS recipient. Never ship `room["game"]` raw.
        "game": engine.player_view(g, viewer_pid) if g else None,
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": _valid_difficulty(room.get("ai_difficulty")),
        # Scoped to the recipient: a room-wide token map would hand every socket
        # the other seat's reconnect credential.
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }
    # The armed request is scoped to the human opponent.  It contains the bot
    # seat's policy observation (including that seat's hand), so it must never
    # be copied into a room-wide public payload or sent to another human seat.
    armed = room.get("_ai_search")
    if (armed and viewer_pid in room.get("players", {})
            and viewer_pid != room.get("ai_player")
            and room.get("client_ai") and room.get("ai_player")):
        state["ai_search"] = copy.deepcopy(armed)
    return state


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
        room["ai_turn_started_at"] = None
        room["_ai_search"] = None
        room["_ai_pending_move"] = None
        room["_ai_pending_sent_at"] = None


def _bot_should_act(room: dict) -> bool:
    g = room.get("game")
    ai = room.get("ai_player")
    return bool(g and ai and not engine.is_over(g) and engine.legal_moves(g, ai))


# ── Bot scheduler ────────────────────────────────────────────────────────────
# Heavy work never runs under ROOM_LOCK on the event-loop thread: snapshot under
# the lock, compute off it, re-lock, RE-VALIDATE that the bot still owes a move,
# then apply. A rewrite elsewhere that looped synchronous engine work under the
# lock took prod down once, and the rule is cheap to keep even for a bot this
# small.
_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="orbit-bot")


def _position_key(g: dict) -> str:
    """Digest the whole position so overlapping schedulers cannot double-move.

    Most Orbit effect choices do not append to the public log.  A key made only
    from turn/pending metadata therefore remains unchanged while a multi-step
    effect advances, allowing two reconnect-triggered bot schedulers to apply a
    move selected for the previous task.  The persisted game is already JSON-
    safe, so hashing its canonical form is both simpler and exhaustive.
    """
    payload = json.dumps(g, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bot_move_sync(g: dict, pid: str, seed: int, difficulty: str = "easy"):
    # Both search tiers fall back to the effect-aware ranker server-side: the
    # search lives in the browser worker, and the server's job here is a fast
    # validated answer, not a second search on the event loop.
    if difficulty in ("hard", "expert", "normal"):
        return bot.choose_fallback_move(g, pid, seed)
    # Easy is now the original public-information ranker. The random opponent
    # is no longer served; it remains in `bot` as the offline baseline.
    return bot.choose_normal_fallback_move(g, pid, seed)


def _bot_turn_active(room: dict) -> bool:
    """Whether the current turn still belongs to the bot (possibly awaiting a
    human's resolution of an effect).  Waiting on the human must not burn the
    five-second search budget."""

    game = room.get("game")
    ai = room.get("ai_player")
    return bool(game and ai and not engine.is_over(game)
                and game.get("turn_pid") == ai)


def _ai_memory_for(room: dict, ai: str) -> dict:
    memory = serving.normalise_memory(room.setdefault("ai_memory", {}).get(ai))
    history = room.get("seat_histories", {}).get(ai)
    if isinstance(history, dict):
        memory["history"] = copy.deepcopy(history)
    # Attaching the seat-local trace can push an otherwise small branch cache
    # over the wire/persistence cap.  Normalize a second time so a long game
    # cannot grow the armed request beyond the same bound as client replies.
    return serving.normalise_memory(memory)


def _apply_live_move(room: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    """Apply a validated move and append redacted per-seat policy history."""

    game = room.get("game")
    if not isinstance(game, dict):
        return False, "no game"
    before = _live_observations(game)
    ok, error = engine.apply_move(game, pid, move)
    if ok:
        _record_history(room, pid, move, before)
        _sync_status_from_game(room)
    return ok, error


async def _client_bot_turn(room_id: str) -> bool:
    """Serve a hard bot turn through the human's browser, one decision at a time.

    Returns ``True`` when the bot no longer owes a move and ``False`` when the
    caller should continue with its server fallback.  The request is stored in
    room state so a re-broadcast/reconnect can ship it again; a socket drop
    clears it and wakes the waiter through ``_release_orbit_socket``.
    """

    for _ in range(96):
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return not (room and _bot_turn_active(room))
            if not room.get("client_ai"):
                return False
            ai = room["ai_player"]
            remaining = int(max(0, room.get("ai_budget_remaining_ms")
                                if room.get("ai_budget_remaining_ms") is not None
                                else CLIENT_AI_TURN_BUDGET_MS))
            if remaining <= 0:
                room["_ai_search"] = None
                room["_ai_pending_move"] = None
                room["_ai_pending_sent_at"] = None
                return False
            game = room["game"]
            legal = engine.legal_moves(game, ai)
            if not legal:
                return False
            if len(legal) == 1:
                forced, event = legal[0], None
            else:
                forced = None
                decision = room["_ai_decision_seq"] = room.get("_ai_decision_seq", 0) + 1
                request_budget = min(
                    remaining,
                    CLIENT_AI_MAIN_ACTION_MS
                    if int(room.get("ai_decisions_this_turn", 0)) == 0
                    else CLIENT_AI_FOLLOWUP_RESERVE_MS,
                )
                obs = observation(game, ai)
                memory = _ai_memory_for(room, ai)
                position = serving.position_key(obs, legal)
                room["_ai_search"] = {
                    "protocol": CLIENT_AI_WIRE,
                    "decision": decision,
                    "position": position,
                    "seat": ai,
                    "schema": serving.SCHEMA_VERSION,
                    "encoder": serving.ENCODER_VERSION,
                    "rules": CLIENT_AI_RULES,
                    "observation": obs,
                    # ALONGSIDE the observation, never inside it. `obs` is the
                    # frozen policy input -- its key set is asserted in
                    # `_OBS_KEYS` and in `serving`, it is stored in game history
                    # and compared for equality, and it feeds the encoder.
                    # Without this the client search REFUSES every
                    # effect-resolution decision and falls back to the 1-ply
                    # ranker, which is 45.0% of all decisions with a real
                    # choice. A client that ignores the field gets exactly that
                    # old behaviour, so the two sides deploy in either order.
                    "pending_chain": pending_chain(game),
                    "legal_moves": copy.deepcopy(legal),
                    "memory": memory,
                    "remaining_turn_budget": remaining,
                    "budget_ms": request_budget,
                    "main_action_budget_ms": CLIENT_AI_MAIN_ACTION_MS,
                    "followup_reserve_ms": CLIENT_AI_FOLLOWUP_RESERVE_MS,
                    "model_version": CLIENT_AI_MODEL_VERSION,
                    "tier": _valid_difficulty(room.get("ai_difficulty")),
                    "turn_started_at": room.get("ai_turn_started_at"),
                }
                room["_ai_search"]["sent_at"] = time.time()
                room["_ai_pending_move"] = None
                room["_ai_pending_sent_at"] = None
                event = room["_ai_move_evt"] = asyncio.Event()

        if event is None:
            move = forced
            sent_at = None
        else:
            await broadcast_state(room_id)
            try:
                await asyncio.wait_for(event.wait(), CLIENT_AI_TIMEOUT)
            except asyncio.TimeoutError:
                async with ROOM_LOCK:
                    current = ROOMS.get(room_id)
                    if current:
                        current["ai_budget_remaining_ms"] = 0
                        current["_ai_search"] = None
                        current["_ai_pending_move"] = None
                        current["_ai_pending_sent_at"] = None
                LOG.info("orbit client AI timed out; server fallback (%s)", room_id)
                return False
            async with ROOM_LOCK:
                current = ROOMS.get(room_id)
                move = current.pop("_ai_pending_move", None) if current else None
                sent_at = current.pop("_ai_pending_sent_at", None) if current else None
            if move is None:
                # A simultaneous human action (the opening mulligan is the
                # normal case) can invalidate the armed position.  Re-arm a
                # fresh request while the browser is still eligible; a socket
                # drop or an explicit disarm takes the server fallback path.
                if current and current.get("client_ai") and _bot_should_act(current):
                    continue
                return False

        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return not (room and _bot_turn_active(room))
            ok, error = _apply_live_move(room, room["ai_player"], move)
            if not ok:
                LOG.info("orbit client move no longer legal (%s): %s", room_id, error)
                return False
            if sent_at is not None:
                spent = max(0, int((time.time() - sent_at) * 1000))
                room["ai_budget_remaining_ms"] = max(
                    0, int(room.get("ai_budget_remaining_ms", CLIENT_AI_TURN_BUDGET_MS)) - spent)
            room["ai_decisions_this_turn"] = int(room.get("ai_decisions_this_turn", 0)) + 1
            room["_ai_search"] = None
            more = _bot_should_act(room)
            if not more and not _bot_turn_active(room):
                room["ai_budget_remaining_ms"] = None
                room["ai_turn_started_at"] = None
                room["ai_decisions_this_turn"] = 0
        await broadcast_state(room_id)
        save_game(room_id)
        if not more:
            return not _bot_turn_active(ROOMS.get(room_id, {}))
        # Show the resolved move first; the pacing pause belongs between
        # decisions so the player can read the log and watch the board cues.
        await asyncio.sleep(max(0, BOT_FLOOR_SECONDS))
    return False


async def _schedule_bot_turn(room_id: str) -> None:
    """Drive a bot turn without holding ``ROOM_LOCK`` across search work."""
    loop = asyncio.get_running_loop()
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or room.get("_bot_running") or not _bot_should_act(room):
            return
        room["_bot_running"] = True
        difficulty = _valid_difficulty(room.get("ai_difficulty"))
        use_client = difficulty in CLIENT_AI_TIERS and bool(room.get("client_ai"))
        if room.get("ai_budget_remaining_ms") is None:
            room["ai_budget_remaining_ms"] = CLIENT_AI_TURN_BUDGET_MS
            room["ai_turn_started_at"] = time.time()
            room["ai_decisions_this_turn"] = 0
    try:
        if use_client:
            await _client_bot_turn(room_id)

        # The server fallback is deliberately cheap and validated.  Search is
        # performed on a detached snapshot in the executor, never under the
        # event-loop lock; a changed position simply causes a fresh decision.
        while True:
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room or not _bot_should_act(room):
                    return
                game = room["game"]
                ai = room["ai_player"]
                snapshot = json.loads(json.dumps(game))
                position_before = _position_key(game)
            started = time.monotonic()
            try:
                move = await loop.run_in_executor(
                    _BOT_EXEC, _bot_move_sync, snapshot, ai,
                    _rooms.bot_seed(position_before, ai), difficulty)
            except Exception:
                LOG.warning("orbit bot failed in %s", room_id, exc_info=True)
                return
            if move is None:
                return
            delay = BOT_FLOOR_SECONDS - (time.monotonic() - started)
            if delay > 0:
                await asyncio.sleep(delay)
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room or not _bot_should_act(room):
                    return
                if _position_key(room["game"]) != position_before:
                    continue
                ok, error = _apply_live_move(room, ai, move)
                if not ok:
                    LOG.warning("orbit bot produced an illegal move in %s: %s", room_id, error)
                    return
                more = _bot_should_act(room)
                if not more and not _bot_turn_active(room):
                    room["ai_budget_remaining_ms"] = None
                    room["ai_turn_started_at"] = None
                    room["ai_decisions_this_turn"] = 0
            await broadcast_state(room_id)
            save_game(room_id)
            if not more:
                return
    finally:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if room:
                room["_bot_running"] = False
                room["_ai_search"] = None
                room["_ai_pending_move"] = None
                room["_ai_pending_sent_at"] = None
                if not _bot_turn_active(room):
                    room["ai_budget_remaining_ms"] = None
                    room["ai_turn_started_at"] = None
                    room["ai_decisions_this_turn"] = 0


def _start_new_game(room: dict, room_id: str) -> None:
    seats = list(room["players"].keys())
    rng = _rooms.deal_rng(seats, mode="orbit")
    room["game"] = engine.new_game(
        seats,
        names=room["players"],
        seed=rng.randrange(2 ** 31),
        configuration=room.get("configuration", "sun"),
    )
    room["status"] = "playing"
    room["seat_histories"] = _new_live_histories(room["game"])
    room["ai_memory"] = {}
    room["ai_turn_started_at"] = None
    room["_ai_search"] = None
    room["_ai_pending_move"] = None
    room["_ai_pending_sent_at"] = None


def _release_orbit_socket(room_id: str, pid: str, websocket) -> None:
    """Release a socket and invalidate any in-flight browser decision.

    The identity check mirrors ``core.rooms.release_socket``.  A stale handler
    from an old connection must never clear the live socket's client-AI opt-in
    or its request.
    """

    room = ROOMS.get(room_id)
    owned = bool(room and room.get("sockets", {}).get(pid) is websocket)
    _rooms.release_socket(ROOMS, room_id, pid, websocket, disarm_client_ai=True)
    # `release_socket` is synchronous, so no event-loop task can interleave
    # between this re-check and the cleanup.  A reconnect that won the race is
    # visible as a different socket and must retain its live request/opt-in.
    still_ours = bool(room and room.get("sockets", {}).get(pid) is websocket)
    socket_gone = bool(room and room.get("sockets", {}).get(pid) is None)
    if owned and room and (still_ours or socket_gone):
        room["_ai_search"] = None
        room["_ai_pending_move"] = None
        room["_ai_pending_sent_at"] = None
        event = room.get("_ai_move_evt")
        if event:
            event.set()


# ── WebSocket ────────────────────────────────────────────────────────────────
@orbit_app.websocket("/ws/{room}/{player}")
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
            elif action in ("start", "move", "abandon", "client_ai_ready", "ai_move"):
                if not authed:
                    await _send(websocket, {
                        "type": "error",
                        "message": "not authenticated for this seat"})
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
                await _send(websocket, {"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        _release_orbit_socket(room_id, pid, websocket)


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    difficulty = _requested_difficulty(msg.get("ai_difficulty"))
    # New rooms always use a random technology board.  Keep this server-side so
    # an older cached client cannot quietly create the retired S.U.N. variant.
    configuration = "random"
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
            "seat_histories": {},
            "ai_memory": {},
            "ai_budget_remaining_ms": None,
            "ai_turn_started_at": None,
            "ai_decisions_this_turn": 0,
            "client_ai": False,
            "_ai_search": None,
            "_ai_pending_move": None,
            "_ai_pending_sent_at": None,
            "configuration": configuration,
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
            # stranger that seat's private hand and pending choices.
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
            await _send(ws, {"type": "error", "message": "the game is over"})
            return
        move = msg.get("move") or {}
        ok, error = _apply_live_move(room, pid, move)
        if not ok:
            await _send(ws, {"type": "error", "message": error or "illegal move"})
            return
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await broadcast_state(room_id)
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_client_ai_ready(ws, room_id, pid, msg):
    """Arm the browser worker for a hard vs-AI room.

    Compatibility metadata is checked before the room ever ships a bot
    observation.  A cached legacy bundle has no complete version declaration
    and therefore stays on the server path; a declared mismatch is rejected so
    a cached worker cannot silently search a different rules build.
    """

    bot_turn = False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if (not room or pid not in room.get("players", {})
                or pid == room.get("ai_player")):
            return
        if msg.get("ready") is False:
            room["client_ai"] = False
            room["_ai_search"] = None
            room["_ai_pending_move"] = None
            room["_ai_pending_sent_at"] = None
            event = room.get("_ai_move_evt")
            if event:
                event.set()
            return
        if not room.get("ai_player") or _valid_difficulty(room.get("ai_difficulty")) not in CLIENT_AI_TIERS:
            return
        wire = msg.get("wire", msg.get("abi_version"))
        model = msg.get("model_version")
        schema = msg.get("schema")
        encoder = msg.get("encoder")
        rules = msg.get("rules")
        try:
            wire_value = None if wire is None else int(wire)
            model_value = None if model is None else int(model)
            schema_value = None if schema is None else int(schema)
        except (TypeError, ValueError):
            return
        # This is the compatibility boundary.  Do not arm a worker that cannot
        # prove which protocol/model it implements.
        if (wire_value is None or model_value is None or schema_value is None
                or encoder is None or rules is None):
            return
        if wire_value is not None and wire_value != CLIENT_AI_WIRE:
            LOG.info("orbit client AI wire mismatch in %s", room_id)
            return
        if model_value is not None and model_value != CLIENT_AI_MODEL_VERSION:
            LOG.info("orbit client AI model mismatch in %s", room_id)
            return
        if schema_value != CLIENT_AI_SCHEMA:
            LOG.info("orbit client AI schema mismatch in %s", room_id)
            return
        if encoder != CLIENT_AI_ENCODER:
            LOG.info("orbit client AI encoder mismatch in %s", room_id)
            return
        if rules != CLIENT_AI_RULES:
            LOG.info("orbit client AI rules mismatch in %s", room_id)
            return
        room["client_ai"] = True
        bot_turn = _bot_should_act(room) and not room.get("_bot_running")
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_ai_move(ws, room_id, pid, msg):
    """Accept one browser decision only when it matches the armed position."""

    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if (not room or pid not in room.get("players", {})
                or pid == room.get("ai_player")):
            return
        game = room.get("game")
        armed = room.get("_ai_search")
        if not (game and room.get("ai_player") and room.get("client_ai") and armed):
            return
        if msg.get("decision") != armed.get("decision"):
            LOG.info("orbit stale client AI decision ignored (%s)", room_id)
            return
        if msg.get("position") != armed.get("position"):
            LOG.info("orbit stale client AI position ignored (%s)", room_id)
            return
        live_legal = engine.legal_moves(game, room["ai_player"])
        live_position = serving.position_key(observation(game, room["ai_player"]), live_legal)
        if live_position != armed.get("position"):
            LOG.info("orbit client AI position changed before reply (%s)", room_id)
            room["_ai_search"] = None
            room["_ai_pending_move"] = None
            room["_ai_pending_sent_at"] = None
            event = room.get("_ai_move_evt")
            # Wake the serving loop so it can arm the current position instead
            # of waiting out a request that can no longer be correct.
            if event:
                event.set()
            return
        try:
            protocol = int(msg.get("protocol", CLIENT_AI_WIRE))
        except (TypeError, ValueError):
            return
        if protocol != CLIENT_AI_WIRE:
            return
        # A ready worker is required to advertise the full compatibility
        # envelope.  Replies from an older cached bundle may omit these fields,
        # so they remain optional for wire compatibility; whenever present they
        # must agree with the armed request and current rules build.
        try:
            reply_wire = msg.get("wire")
            if reply_wire is not None and int(reply_wire) != CLIENT_AI_WIRE:
                return
            reply_model = msg.get("model_version")
            if reply_model is not None and int(reply_model) != armed.get("model_version"):
                return
            reply_schema = msg.get("schema")
            if reply_schema is not None and int(reply_schema) != armed.get("schema"):
                return
        except (TypeError, ValueError, OverflowError):
            return
        for field in ("encoder", "rules"):
            if msg.get(field) is not None and msg.get(field) != armed.get(field):
                return
        raw = msg.get("move")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = None
        if not isinstance(raw, dict) or raw not in live_legal:
            # Keep the request armed so the watchdog, rather than a malformed
            # client reply, owns the fallback transition.
            LOG.info("orbit illegal client AI move dropped (%s)", room_id)
            return
        room["_ai_pending_move"] = copy.deepcopy(raw)
        room["_ai_pending_sent_at"] = armed.get("sent_at")
        room["_ai_search"] = None
        previous_memory = room.setdefault("ai_memory", {}).get(room["ai_player"])
        room["ai_memory"][room["ai_player"]] = serving.normalise_memory(
            msg["memory"] if "memory" in msg else previous_memory)
        event = room.get("_ai_move_evt")
    if event:
        event.set()


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
            if pid in g.get("players", {}):
                g["winner"] = next(other for other in g["players"] if other != pid)
                g["phase"] = "over"
                g["pending_pid"] = g["pending"] = None
                g["log"].append({"turn": g.get("turn_number", 0), "message": "Game over (abandoned)."})
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


# ── REST ─────────────────────────────────────────────────────────────────────
@orbit_app.get("/health")
async def health():
    return {"ok": True, "game": "orbit", **build_info()}


@orbit_app.get("/catalog")
async def catalog():
    """Static, public mechanical data rendered by the Orbit client."""
    return {
        "planets": list(PLANETS),
        "factions": list(FACTIONS),
        "cards": {str(cid): public_card(cid) for cid in CARDS},
        "bonuses": BONUS_TYPES,
    }


@orbit_app.get("/games")
async def games_open():
    return {"games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@orbit_app.get("/games/mine")
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


@orbit_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"games": []}
    return {"games": list_user_history(user["id"])}


@orbit_app.post("/games/{game_id}/leave")
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


@orbit_app.delete("/games/{game_id}")
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
