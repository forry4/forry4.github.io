"""Shared room-server primitives.

Every game's ``main.py`` reimplements the same scaffolding around an in-memory
``ROOMS`` dict. Most of that is genuinely game-specific (persistence columns,
broadcast redaction, bot scheduling), but a handful of pieces were BYTE-IDENTICAL
across all four games, and one of them encodes a footgun that has already cost a
production outage. Those live here.

WHY THIS MATTERS more than tidiness: a cross-cutting fix currently has to be
applied four times by hand, with no compiler help, and history shows that is not
what happens. The hidden-info broadcast leak had to be found and fixed three
separate times because three copies of ``mk_room_state`` each leaked differently,
and the WebSocket identity binding shipped in Where Wolf? months before the other
three games got it. One definition, four callers, is the point.

This module sits in ``core/`` and therefore imports NO game (the layering rule:
core -> features -> app). It knows about sockets and rooms in the abstract; it
does not know what a game is.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import time
import zlib
from collections import deque
from typing import Any, Callable

from core.auth import gen_token
from core.db import get_db_conn
from core.ratelimit import SlidingWindowLimiter

# The room dict shape every game shares:
#   {"players": {pid: name}, "sockets": {pid: ws}, "status": "open"|"playing"|"over",
#    "host": pid, "game": {...}|None, "meta": {pid: {"token": str, ...}}}
Room = dict[str, Any]
Rooms = dict[str, Room]


def normalize_room(rid: str) -> str:
    """Room codes are case-insensitive; the upper form is canonical (it is the dict
    key, the DB id, and the URL segment)."""
    return (rid or "").upper()


def gen_room_token(n: int = 12) -> str:
    """Per-seat reconnect token. Delegates to core.auth.gen_token, which is CSPRNG
    backed (`secrets`, never `random`) — these are credentials."""
    return gen_token(n)


def db_conn():
    """The shared dual sqlite/Turso connection. Not pooled: callers close it."""
    return get_db_conn()


# ── state_json codec (shared by all five games' save/load) ───────────────────
# Every game stores its whole room state as one JSON string in a `state_json`
# TEXT column, re-written on EVERY move. Those blobs are hugely repetitive (the
# verbose move log, plus the undo stack's near-duplicate snapshots), so they
# compress ~8-10x — measured on full Dontminion games: ~111 KB plain JSON ->
# ~11 KB zlib, and the log+undo that dominate the raw size all but vanish once
# compressed. This is pure at-rest encoding: player_view still ships plain JSON
# over the WebSocket, so nothing on the wire or in the client changes.
#
# base64-in-TEXT rather than a raw BLOB column keeps it DRIVER-AGNOSTIC — the
# dual sqlite/libsql wrapper can't be trusted to bind/return bytes identically
# (libsql can't be tested on this box), and base64 survives a plain SELECT and
# the libSQL HTTP JSON protocol unchanged. The ~33% base64 overhead still nets
# ~7-8x. The "z:" prefix is outside the base64 alphabet AND can't begin a JSON
# object ("{"), so decode_state can tell a compressed blob from a legacy one.
_STATE_PREFIX = "z:"


def encode_state(state: dict) -> str:
    """Serialize a room's full state for the `state_json` column: compact JSON,
    zlib-compressed, base64'd, and prefixed. Inverse of decode_state."""
    raw = json.dumps(state, separators=(",", ":")).encode("utf-8")
    return _STATE_PREFIX + base64.b64encode(zlib.compress(raw, 6)).decode("ascii")


def decode_state(blob) -> dict:
    """Inverse of encode_state, BACKWARD-COMPATIBLE with legacy plain-JSON blobs
    (which start with "{") so existing prod rows load with no migration — they
    re-encode compressed the next time the game saves. Empty/None -> {} (the
    `... or "{}"` read sites relied on that). A genuinely corrupt blob raises,
    exactly as json.loads did, so the try/except already around these reads
    still catches it."""
    if not blob:
        return {}
    if isinstance(blob, (bytes, bytearray)):
        blob = blob.decode("utf-8")
    if blob.startswith(_STATE_PREFIX):
        return json.loads(zlib.decompress(base64.b64decode(blob[len(_STATE_PREFIX):])))
    return json.loads(blob)


# ── rng_state packing (used by every game's persist.py) ──────────────────────
# `random.getstate()` is (version, 625 words, gauss_next). Stored as a JSON list of
# ints that is ~6.7 KB of pure noise — zlib cannot touch it, so it survives the ~8x
# compression around it and ends up dominating the row: 27-34% of a Dontminion blob,
# 90% of a Where Wolf one (WW's answer was to stop persisting it — nothing read it).
# Packed little-endian into base64 it is ~3.3 KB. The words are 32-bit (624 state + 1
# index), so this is exact.
#
# THE RULE, learned the expensive way — PACK EVERY COPY IN THE BLOB OR NONE OF THEM.
# A game and its undo snapshot(s) hold near-identical rng_states, and zlib was already
# collapsing the duplicates to almost nothing. Packing only the live copy destroys that
# dedup, and the blob comes out BIGGER than if you had done nothing: measured on Duel,
# packing both copies is -15.2% and packing only the live one is **+49.5%**. Each
# game's persist.py must therefore reach every snapshot too (Duel `turn_undo`,
# Dontminion every entry of `undo_stack`).

def pack_rng(st):
    """[version, [625 ints], gauss] -> [version, {"b64": ...}, gauss]. Returns `st`
    unchanged if it is not the expected shape (already packed, None, legacy)."""
    if not (isinstance(st, list) and len(st) >= 2 and isinstance(st[1], list)):
        return st
    try:
        blob = b"".join(int(w).to_bytes(4, "little") for w in st[1])
    except (OverflowError, ValueError, TypeError):
        return st                       # not 32-bit words -> leave it verbatim
    return [st[0], {"b64": base64.b64encode(blob).decode("ascii")}] + list(st[2:])


def unpack_rng(st):
    """Inverse of pack_rng; passes an unpacked (legacy) value straight through."""
    if not (isinstance(st, list) and len(st) >= 2
            and isinstance(st[1], dict) and "b64" in st[1]):
        return st
    blob = base64.b64decode(st[1]["b64"])
    words = [int.from_bytes(blob[i:i + 4], "little") for i in range(0, len(blob), 4)]
    return [st[0], words] + list(st[2:])


# ── Reproducible deals, for the render gate only ─────────────────────────────
# Games deal from an unseeded RNG. That is correct in production and it was the
# single largest cause of failed Pages deploys: 11 of the 15 failures in the 500
# runs to 2026-08-28 were the `screens` gate, and the ones that turned out to be
# the HARNESS rather than the product were all one bug wearing four hats — an
# assertion that holds on SOME deals, written green locally and drawn red in CI.
# `807155f` says it outright ("an assertion that holds on SOME deals"); `d1bdc1e`
# is the Double prompt that only fires when the bot wins the auction ("real, just
# rare -- CI simply drew the rare deal twice"); `408bf9e` is a price row that
# populates depending on which seat opened; `8726c31a` is a regex that collided
# with the one fighter whose honest output happened to look like the bug. Four of
# those went red->green with the app code BYTE-IDENTICAL and only the harness
# changed, which is the tell: the gate was measuring the dice, not the product.
#
# `GAMES_DEAL_SEED` makes a deal a pure function of who is at the table, so the
# gate replays the same hand on every run and a check that passes locally cannot
# be drawn red later. Read PER CALL, never captured at import, so a test can set
# it around a single deal.
#
# The key is the sorted player ids plus the mode. Deliberately NOT the room id
# (generated per room, so it would feed the randomness straight back in) and
# deliberately NOT a global counter: screens.mjs runs its blocks in TWO LANES, so
# a global counter is handed out in interleaving order and the same block draws a
# different hand every run — precisely the property this exists to remove. Every
# screens block seeds its own stable guest id (`skat-harness`, `hard-harness`,
# ...), so keying on identity gives each block its own reproducible deal whatever
# lane it lands in. The per-key counter that rides along is what lets one block
# play two games and get two different — still reproducible — hands; it is
# per-key rather than global so that one block's second deal cannot depend on
# whether another block happened to run first.
#
# UNSET IN PRODUCTION. The unset path returns `random.Random()`, which is the
# expression each caller used before. This must never become client-settable: a
# seat that can pin the deal in a hidden-info game knows the deal.
_DEAL_COUNTERS: dict[str, int] = {}


def deal_rng(players=(), *, mode: str = "") -> random.Random:
    """The RNG a game deals from. Unseeded unless `GAMES_DEAL_SEED` is set."""
    seed = os.environ.get("GAMES_DEAL_SEED")
    if not seed:
        return random.Random()
    key = "|".join([seed, mode, *sorted(str(p) for p in players)])
    n = _DEAL_COUNTERS[key] = _DEAL_COUNTERS.get(key, -1) + 1
    return random.Random(
        int.from_bytes(hashlib.sha256(f"{key}|{n}".encode()).digest()[:8], "big"))


def bot_seed(*parts) -> int:
    """The seed a bot's move draws from. Random unless `GAMES_DEAL_SEED` is set.

    Pinning the DEAL is only half of a reproducible game: every bot move draws
    its own `random.randrange(2 ** 31)`, so a seeded deal still branches the
    moment the bot chooses. That is not a hypothetical — `d1bdc1e` is exactly
    it: "the Double prompt only fires when the bot wins the auction ... real,
    just rare", two Pages deploys red on a decision no deal seed would have
    fixed.

    Pass the POSITION the move is computed from (each game already builds a
    `_position_key` for its stale-move guard). Seeding off the position rather
    than a move counter means a re-entered scheduler for the same position asks
    the same question and gets the same answer — the reproducibility survives
    the retries and reconnects that make a move counter drift.

    Unset in production, where the bot must stay unpredictable: a bot that
    answers every identical position identically is a bot you can learn by rote.
    """
    seed = os.environ.get("GAMES_DEAL_SEED")
    if not seed:
        return random.randrange(2 ** 31)
    key = "|".join([seed, *(str(p) for p in parts)])
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big")


def ensure_room_loaded(rooms: Rooms, room_id: str,
                       loader: Callable[[str], Any]) -> Room | None:
    """Return the live room, hydrating it from the DB on first touch.

    `loader` is the game's `load_game_to_memory`, which inserts into `rooms` as a
    side effect — hence the re-read rather than using its return value.
    """
    if room_id not in rooms:
        loader(room_id)
    return rooms.get(room_id)


async def send_json(ws, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


def delete_open_game(table: str, host_col: str, game_id: str, user_id: str) -> bool:
    """Delete an OPEN game the user hosts (the lobby 'cancel'). True if a row went.

    SELECT-then-DELETE, never ``cursor.rowcount``. The driver-agnostic core.db
    wrapper does not expose rowcount, and on the prod Turso/libsql backend reading
    it RAISED — which 500'd the cancel endpoint in production. Every affected-row
    count in this codebase must be an existence SELECT for the same reason.

    `table` and `host_col` are interpolated into SQL, so they must be trusted
    literals from the calling module — never user input. Asserted below.
    """
    assert table.isidentifier() and host_col.isidentifier(), \
        "table/host_col are SQL identifiers, not user input"
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {table} WHERE id=? AND {host_col}=? AND status='open'",
            (game_id, user_id))
        existed = cur.fetchone() is not None
        if existed:
            conn.execute(
                f"DELETE FROM {table} WHERE id=? AND {host_col}=? AND status='open'",
                (game_id, user_id))
            conn.commit()
        return existed
    finally:
        conn.close()


def release_socket(rooms: Rooms, room_id: str, pid: str, websocket,
                   *, disarm_client_ai: bool = False,
                   drop_empty_open_only: bool = True) -> bool:
    """The WebSocket `finally` cleanup. Returns True if the room was dropped.

    THE STALE-SOCKET GUARD IS LOAD-BEARING: only act if `websocket` is the exact
    object still registered for `pid`. During a reconnect race (WS1 dropping while
    WS2 is already live) the departing handler would otherwise remove the NEW
    socket and delete a room that is actively being played.

    Flags capture the deliberate per-game differences:
      - `disarm_client_ai`: clear the room's client-AI opt-in when the tab goes, so
        the bot's next decision takes the server path instead of waiting out the
        per-decision watchdog. A reconnecting client re-arms itself.
      - `drop_empty_open_only`: keep playing/over games resident when the last
        socket leaves (they are resumable); drop only never-started open lobbies.
        Spender passes False — it drops any empty room.

    PHANTOM ROOMS are collected regardless of who owned the socket. Spender's WS
    handler `setdefault`s a room shell on CONNECT so it has something to hold
    `meta`, but the socket is no longer registered until a handshake proves
    identity — so the ownership check below can never match for a client that
    connects and leaves without handshaking, and the empty shell would leak
    FOREVER. Unauthenticated and trivially repeatable: opening sockets to random
    room codes grew `ROOMS` without bound on a 512MB instance. A room with no
    sockets, no players and no game is unambiguously garbage whoever is leaving.
    """
    room = rooms.get(room_id)
    if not room:
        return False

    if room.get("sockets", {}).get(pid) is websocket:
        room["sockets"].pop(pid, None)
        if disarm_client_ai:
            room["client_ai"] = False

    if room.get("sockets"):
        return False
    if not room.get("players") and room.get("game") is None:
        rooms.pop(room_id, None)     # never-used shell — see PHANTOM ROOMS above
        return True
    if drop_empty_open_only and not (room.get("status") == "open" and room.get("game") is None):
        return False
    rooms.pop(room_id, None)
    return True


# ─── WebSocket abuse throttles ───────────────────────────────────────────────
# `core.ratelimit` protected login/register, but WebSockets were completely
# unthrottled: a client could open sockets and push messages as fast as it liked.
# Both are cheap to abuse and expensive to serve — every message takes ROOM_LOCK,
# and every connect allocates a room shell. In-memory and per-process, like the
# auth limiters: the site runs one uvicorn process, and losing counters on restart
# is fine for abuse prevention.
#
# Limits are far above real play (a turn is a handful of messages; the client's
# reconnect backoff is 2s) and are about cutting floods to a trickle, not policing
# users. Both close with 1008 (policy violation) rather than erroring, so an
# abusive peer stops consuming a connection slot.

WS_CONNECTS_PER_MIN = 60
WS_MESSAGES_PER_MIN = 300

# How many finished games every game's `list_user_history` SQL may return. One
# definition, four callers — the four were independently 20/30/30/30, which is
# the exact drift this module exists to stop.
#
# **It is a CEILING that pairs with the client**, not a display count: the
# lobby's History list reveals `HISTORY_PAGE` (10) rows at a time as the reader
# scrolls to the end and stops at `HISTORY_MAX` in `shared/lobby.jsx`, which
# must equal this. Change one and change the other — they are the same number
# seen from the two ends, and the client can only ever page through what the
# query sent. Deploy order does not matter (an old cached bundle renders all 50
# at once; a new bundle against the old server just runs out of pages sooner),
# so this needs no expand/contract window.
HISTORY_LIMIT = 50

_ws_connect_limiter = SlidingWindowLimiter(max_hits=WS_CONNECTS_PER_MIN, window_seconds=60)


def client_ip(ws) -> str:
    """Best-effort peer IP for throttling. Render's proxy APPENDS the real peer to
    any client-supplied X-Forwarded-For, so the LAST hop is the trustworthy one —
    trusting the leftmost is the classic XFF bug (a peer rotating a spoofed header
    lands under a fresh key every time, defeating the throttle). Mirrors the HTTP
    `_client_ip` in games/spender/main.py."""
    xff = ws.headers.get("x-forwarded-for") if getattr(ws, "headers", None) else None
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    client = getattr(ws, "client", None)
    return getattr(client, "host", None) or "unknown"


async def reject_if_connecting_too_fast(ws) -> bool:
    """Record this connection and, if the peer is over the limit, close it.

    Returns True when the caller should ABORT (the socket is closed). Call right
    after `accept()`, before touching ROOMS.
    """
    ip = client_ip(ws)
    if _ws_connect_limiter.exceeded(ip):
        try:
            await ws.close(code=1008)
        except Exception:
            pass
        return True
    _ws_connect_limiter.record(ip)
    return False


class MessageThrottle:
    """Per-socket message budget. Deliberately per-INSTANCE (a plain deque, no
    shared dict) so it cannot leak: it dies with the connection."""

    def __init__(self, max_per_min: int = WS_MESSAGES_PER_MIN):
        self._max = max_per_min
        self._hits: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        cutoff = now - 60.0
        while self._hits and self._hits[0] < cutoff:
            self._hits.popleft()
        if len(self._hits) >= self._max:
            return False
        self._hits.append(now)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# WHICH BOT A SAVED ROOM WAS PLAYING
# ─────────────────────────────────────────────────────────────────────────────
def state_ai_tier(state) -> str | None:
    """The bot tier a saved room was playing against, or ``None`` for a human table.

    Reads only the blob every game's ``save_game`` already writes, so it is
    usable from the `list_user_games` / `list_user_history` / `list_active_games`
    family without loading the room or the engine.

    IT IS TWO FACTS, NOT ONE, and conflating them is the bug this exists to
    make unwriteable: a tier is stored on EVERY room, bot or not (each game
    writes ``room.get("ai_difficulty", DEFAULT_DIFFICULTY)``, which defaults),
    so the seat is what decides whether a bot is at the table and the tier only
    says which one. Reading the tier alone labels every human game "Normal AI".

    Both spellings of each are accepted because both exist in the tree, and
    neither is a legacy shape to migrate: ``ai_players`` is Dontminion's
    multi-bot LIST (one tier, several seats), and ``ai_variant`` is Spender's
    variant code, whose seat lives inside ``game`` rather than beside it.
    """
    if not isinstance(state, dict):
        return None
    game = state.get("game") if isinstance(state.get("game"), dict) else {}
    seated = (state.get("ai_player") or state.get("ai_players")
              or game.get("ai_player") or game.get("ai_players"))
    if not seated:
        return None
    tier = state.get("ai_difficulty") or state.get("ai_variant")
    return str(tier) if tier else None
