"""Dissonance room server — mounted at /dissonance.

Same scaffolding as the other five games: an in-memory ``ROOMS`` dict under a
single lock, WebSocket per room+player, and every rule delegated to
``engine.py``. The generic half of that scaffolding lives in ``core/rooms.py``
and is aliased below under the historical private names.

Two things here are load-bearing and were expensive to learn elsewhere:

* **Seat identity is bound.** The ``player`` path segment is client-supplied
  and every pid is broadcast in the public players map, so a socket must PROVE
  it owns its pid before it can act as that seat or receive that seat's view.
  ``authed`` flips true only via create / join-as-a-new-seat / join-with-a-
  matching-session-token / reconnect-with-the-room-token / auth_reconnect.
* **Broadcasts are redacted per recipient.** ``mk_room_state`` rebuilds the
  game through ``engine.player_view`` for each socket's own pid, so the
  opponent's hand, the covered side-pile bottoms and the out-of-play pair
  never reach a wire that should not see them.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import random
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

from . import bot
from . import engine
from . import persist

LOG = logging.getLogger("dissonance")

TABLE = "dissonance_games"
#: The name this game's table had while it was called Oddtrick. Live rows sit in
#: it on prod, so the rename ADOPTS the table (see `dissonance_init_db`) instead
#: of creating an empty one beside it and orphaning every saved game.
LEGACY_TABLE = "oddtrick_games"
AI_PID = "bot"
DIFFICULTIES = ("easy", "normal", "hard", "expert")
DEFAULT_DIFFICULTY = "normal"

#: Tiers whose card play is searched in the PLAYER'S BROWSER (`rust-cores/
#: dissonance-core` compiled to WASM). The search is an EXACT double-dummy solve
#: per sampled world -- ~70ms for one world at trick 1 on a dev box -- so it can
#: never run on Render's free tier, where one uvicorn process serves five games
#: at ~0.1 CPU. It is safe because the server still validates every move through
#: `engine.apply_move`: a tampered client only weakens its own opponent.
#:
#: Easy and Normal stay server-side ON PURPOSE. Their strength is the shipped
#: ladder, and handing a one-trick-deep policy a solver is a strength change
#: dressed up as a serving one.
CLIENT_AI_TIERS = ("hard", "expert")

#: Tiers whose AUCTION is a MINIMAX over the bidding tree rather than a price
#: list. `engine.auction_search_payload` rides along on the armed request and
#: `auc_search.rs` values each option by what the auction is worth AFTER the
#: opponent answers it.
#:
#: **HARD IS IN THIS LIST SINCE 2026-08-14.** The whole ladder moved up a rung:
#: the tree was Expert's defining feature and measured +1.19 +- 0.32 over the
#: worlds-matched price list, so it became the Hard tier, and Expert took the
#: soft-opponent model below. What Hard used to be -- `bid::price`, the myopic
#: option list -- is no longer any tier's auction; it survives as the pricing
#: for `declare`/`kontra`/`re`/`double`, which have no reply after them and so
#: are already exactly right that way, and as the tie-break inside the tree.
#:
#: The other client-searched phases are deliberately NOT in this: a tree over
#: them would be one node deep, per the paragraph above.
SEARCH_AUCTION_TIERS = ("hard", "expert")

#: EXPERT'S EDGE OVER HARD, and the whole of it (2026-08-14): the tree's
#: modelled opponent is good rather than CLAIRVOYANT. The search runs from our
#: information set, so at every MIN node the opponent chooses knowing our exact
#: hand and always finds the punishing reply -- against that phantom aggression
#: is worthless, so the tree shades our every line down. `OppModel::Soft`
#: replaces the exact min with a softmax over their replies at this temperature
#: (per-world payoff points), pricing "they usually find the best answer, but
#: not when it is barely better than the others".
#:
#: MEASURED +0.957 +- 0.454 payoff/round, 95% CI [+0.07, +1.85], over 1550
#: CRN-paired dd-resolved deals against the same tier without it -- three
#: disjoint samples (+1.07 at n=150, +1.02 at n=900, +0.82 at n=500). For
#: scale that is the size of the tree's own gain over the price list.
#:
#: IT COSTS NOTHING AT SERVING TIME. A MIN node already evaluates every child
#: to take the min, and `bid::Solved` is cached per hand, so the tier is the
#: same solves in the same time -- only the aggregation differs. That is also
#: why it could ship on a one-sigma-ish result without a latency argument
#: against it.
#:
#: 5 was picked from a 3-point sweep (2 / 5 / 12 at n=150 each: -0.36 / +1.07 /
#: +0.99). 2 is too cold to change anything and measured negative; 12 is nearly
#: as good as 5 and the two are indistinguishable at that n, so treat this as
#: "somewhere around 5-12" rather than a tuned optimum.
#:
#: **0 IS EXACTLY THE OLD TREE**, in the Rust and end to end (the arena's null
#: control reads +0.0000), which is what made the A/B unconfoundable.
#:
#: AUDITED 2026-08-16 against the re-pricing, and it needs NOTHING -- recorded
#: because the units make it look like it should. This is in per-world payoff
#: points, the same units as DOUBLE_MARGIN, which the re-pricing turned into a
#: live bug: the softmin computes `exp(-(v/k)/temp)`, so temp divides a payoff
#: exactly as that margin is compared against one. The difference is WHERE in
#: the distribution it acts. A margin is a threshold in the TAIL, so a modest
#: shift makes it reject everything; a temperature is a scale over the BULK, so
#: it degrades proportionally. Measured, the bulk barely moved: payoff sd ratio
#: 0.907, make/set gap ratio 0.725. Rescaling the fitted band by those gives
#: 4.5-10.9 or 3.6-8.7, and 5.0 is inside both -- still in the band it was
#: fitted in. (The fit was loose to begin with, so a re-fit would measure noise
#: unless the whole sweep is rebuilt; not worth arena hours while it is in band.)
EXPERT_OPP_TEMP = 5.0

#: Phases beyond `play` whose decision the browser searches. The talon and the
#: swap are deliberately absent: they are choices about INFORMATION, and what
#: declining to look is worth depends on a game that has not been named yet, so
#: there is no contract for the solver to price them against.
CLIENT_AI_PHASES = ("auction", "declare", "kontra", "re", "double")

#: How long the room waits for the browser to answer one decision before the
#: server bot finishes it. Generous: the whole point of the tier is that the
#: search takes real time, and the fallback costs strength, not correctness.
CLIENT_AI_TIMEOUT = 12.0
#: What the client is asked to spend. Sampling saturates at ~8 worlds
#: (CAMPAIGN.md), and the pool is per-worker, so the cap is the real bound and
#: the millisecond budget is only there so a slow phone still answers.
CLIENT_AI_BUDGET_MS = 2500
CLIENT_AI_MAX_WORLDS = 8

#: ...and fewer for an AUCTION decision, because a world costs a different
#: amount there: a card decision solves the deal ONCE, an auction decision in
#: every denomination (417ms native against 74ms).
#:
#: 8, RAISED FROM 3 (2026-08-08), because the world count turned out to be the
#: lever the whole opponent-model campaign was looking for. Measured, all
#: CRN-paired, resolved by exact double-dummy, classic:
#:
#:   hard   k=8 vs hard k=3    +0.86 +- 0.49  payoff/round
#:   expert k=8 vs hard k=3    +1.36 +- 0.48  CI [+0.43, +2.29]
#:   expert k=3 vs hard k=3    -0.28 +- 0.33  (the tree alone bought nothing)
#:
#: Hard's pricing is LINEAR in the worlds, so the browser pool splitting this
#: cap four ways and summing (4 x 2 worlds, ~850ms a bid) computes exactly the
#: single k=8 answer that was measured. Note the old "3" was a fiction anyway:
#: perWorker = ceil(3/4) = 1 across four workers, so deployed Hard was really
#: k=4 all along.
CLIENT_AI_AUCTION_WORLDS = 8

#: EXPERT's auction runs the SAME k=8 but as ONE TREE IN ONE WORKER, and that
#: serving shape is load-bearing, not a style choice. A minimax tree is not
#: linear in its worlds: four 2-world trees summed were MEASURED weaker than
#: one 8-world tree over the same total (pooled 4x2 vs deployed hard: +0.14 +-
#: 0.45; one tree: +1.36 +- 0.48 vs hard k=3, +0.40 +- 0.45 vs hard at its
#: real k=4). The client reads `auction.search` and sends the whole budget to
#: one worker (~3.4s for the FIRST decision of a hand, ~0 after -- the Solved
#: cache); the card play still fans out. The tree's marginal over
#: worlds-matched Hard is ~+0.5 and not yet resolved past noise, but its
#: point estimate is positive at this shape and the tree is what plays the
#: capping/underbidding style the tier exists for.
CLIENT_AI_AUCTION_WORLDS_EXPERT = 8

#: THE DOUBLING THRESHOLD, in per-world payoff points (2026-08-14). Charged to
#: the doubled branch before the searcher's argmax -- see `bid::price_exact` and
#: `wire`'s double branch.
#:
#: WHY A BARE ARGMAX IS NOT ENOUGH: taking the better of two estimates is a
#: SELECTION, and the branch that wins is partly the one whose noise favoured
#: it. Measured over 500 self-play deals with the search's own numbers recorded
#: (`tools/dblsweep.py`, so every threshold is priced off ONE run rather than a
#: run per value), the search's confidence is well ORDERED but mis-calibrated:
#: contracts it was barely confident about (edge 0-5/world) really made 65.4% of
#: the time, against a break-even near 40%.
#:
#: 20 WAS the measured optimum under the pre-2026-08-16 prices, on two agreeing
#: routes (the calibration crossing break-even, and the swept defender gain
#: peaking), taking the Double from a losing bet to a paying one: gain/round
#: -0.53 -> +2.25, double rate 59.0% -> 31.7%.
#:
#: 20 SURVIVED A RE-FIT ATTEMPT ON 2026-08-16, and the attempt is worth keeping
#: written down because it SHIPPED A REGRESSION for about two hours first.
#:
#: The claim was that the re-pricing had turned 20 into a bug -- 4.6% doubling
#: at +0.2 discrimination -- and that 4 restored it. Both numbers came from
#: `dblsweep.py` run over data recorded while 20 was live, read as though its
#: `margin` column were ABSOLUTE. It is not: `wire.rs` does
#: `sums[esc] += margin * deals.len()`, so the recorded sums already carry the
#: live margin and a swept threshold is a DELTA on top of it. Column 4 of that
#: run was really margin 24; the "4.6% at +0.2" row was really margin 40.
#:
#: Shipping `4` therefore shipped 4 for real, and it is far too loose: measured
#: at 49.4% of contracts doubled, against 22.7% under 20 and an equilibrium that
#: wants ~15%. That is most of the way back to the 59% the knob exists to fix.
#:
#: WHAT PINNED IT: column 0 of a sweep must reproduce the directly measured
#: doubling rate of its own dataset, and it does -- 23.1% against 22.7% measured
#: at live 20, 47.2% against 49.4% measured at live 4. Two datasets recorded at
#: different live margins now agree once both are read as absolute (margin 20
#: reads 23.1% and 26.1%). `dblsweep.py` requires `--live` and refuses to guess.
#:
#: SO 20 STANDS, on 322 recorded doubles under the NEW prices: 26.1% of
#: contracts doubled, discrimination +30.4 (failures 46.3%, makes 15.9%),
#: defender gain +2.00/round. Healthy on every column, and it is the value the
#: paired arena actually measured (+1.889 +- 1.032 for this knob alone).
#:
#: NOT SETTLED, and deliberately not acted on here: the same sweep says margins
#: 6-12 discriminate BETTER (+44 to +52) and pay the defender more (+2.7 to
#: +2.85 against 20's +2.00), at 35-45% doubling. That is plausible -- the
#: belief prior arrived after 20 was fitted and does some of the same work -- but
#: it rests on the PAYOFF columns, which are the noisy ones, and it wants a
#: doubling rate three times the equilibrium's. Moving it needs a paired arena,
#: not another read of this table.
#:
#: CLASSIC ONLY, and per-mode because the units are payoff points: minor's
#: payoffs run about a quarter of classic's, so this dose would be enormous
#: there. Minor's own sweep has not been run, and 0 is exactly today.
#: RE-FITTED TO 12 (2026-08-16) when the Double's shape changed to base x1 /
#: jump x2. That shrank the doubled branch, so the old 20 was cutting a smaller
#: edge distribution and had become over-tight. Swept off a 192-round recording
#: made at LIVE MARGIN 0 -- deliberately, because the sweep can only price
#: UPWARD from the margin a run was recorded under, and the whole question was
#: whether to go lower:
#:
#:   margin   dbl%   on FAIL  on MADE   disc   precision
#:        6  40.6%    81.2%    20.3%   +60.9     66.7%
#:       10  32.3%    65.6%    15.6%   +50.0     67.7%
#:       12  29.2%    59.4%    14.1%   +45.3     67.9%   <- shipped
#:       20  19.8%    37.5%    10.9%   +26.6     63.2%   <- the old value
#:       24  16.7%    28.1%    10.9%   +17.2     56.2%
#:
#: 12 is the peak of BOTH precision and defender gain, and it lands the quality
#: of the previous scoring at a lower rate: the old uniform Double at margin 20
#: measured 41.7% doubling at discrimination +44.3 and precision 65.0%, against
#: 29.2% / +45.3 / 67.9% here. Same discrimination, better precision, 30% fewer
#: doubles.
#:
#: DO NOT COMPARE THE `defender gain` COLUMN ACROSS SCORINGS. Under base x1 a
#: double is a smaller bet by construction, so its gain per round is smaller
#: without being worse. The comparable columns are the rate and the
#: discrimination/precision pair.
DOUBLE_MARGIN = {"classic": 12.0, "minor": 0.0, "skat": 0.0, "dummy": 0.0}

#: Minimum wall-clock a bot move takes, so the board does not jump.
BOT_FLOOR_SECONDS = 0.45


def _valid_difficulty(value) -> str:
    return value if value in DIFFICULTIES else DEFAULT_DIFFICULTY


def _valid_mode(value) -> str:
    """Skat mode is a ROOM FLAG, not a second game: one table, one route, one
    lobby. The mode lives on the room (an open room has no game dict yet) and
    is copied into the game dict at the deal."""
    return value if value in engine.MODES else engine.DEFAULT_MODE


dissonance_app = FastAPI(title="Dissonance API")
dissonance_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
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


def dissonance_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    # ADOPT the Oddtrick-era table rather than starting a fresh one beside it.
    # Guarded on the old name existing AND the new one not, so it fires exactly
    # once, is a no-op on a fresh checkout, and can never clobber a real table.
    # It must run BEFORE the CREATE below, or that would mint the empty table
    # this is trying to avoid and the rename would then never apply.
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
                (LEGACY_TABLE, TABLE))
    present = {row[0] for row in cur.fetchall()}
    if LEGACY_TABLE in present and TABLE not in present:
        cur.execute(f"ALTER TABLE {LEGACY_TABLE} RENAME TO {TABLE}")
        conn.commit()
        LOG.info("adopted %s as %s (the Oddtrick rename)", LEGACY_TABLE, TABLE)
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


dissonance_init_db()
try:
    # Retention: guest 24h / registered 30d / open lobbies 48h, by last
    # activity. Guarded because
    # this runs at IMPORT time and joins `users` — in a fresh checkout that
    # table may not exist yet, and a retention sweep must never stop the module
    # (or every test that imports it) from loading.
    cleanup_stale_games(TABLE)
except Exception as _cleanup_err:  # pragma: no cover - environment-dependent
    LOG.warning("dissonance retention sweep skipped at import: %s", _cleanup_err)


# ── Persistence ──────────────────────────────────────────────────────────────
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="dissonance-db-write")
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
        LOG.warning("dissonance save failed for %s; dropping connection",
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
    """The ONLY read path out of state_json. Every reader must funnel through
    here, offline tools included, or a compacted blob reaches code expecting
    the verbose shape."""
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
        "mode": room.get("mode", engine.DEFAULT_MODE),
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
    # AN UNPLAYABLE SAVE IS DELETED, not resurrected as a corpse. Two kinds
    # cannot be resumed by this engine:
    #   * a save from before the v2 rules release, whose card indices mean
    #     different cards under the current deck;
    #   * a round dealt before its mode's current LAYOUT -- a dummy round dealt
    #     at ten cards a seat against today's thirteen. That one plays fine to
    #     trick 10 and then jams with no legal move: a hung room with nothing
    #     red anywhere.
    #
    # These used to be VOIDED in place (phase="over", no result), which was
    # worse than it sounds. The row still said `playing`, so the game sat in the
    # player's Active list forever, re-voiding on every open; the lobby's cancel
    # only removes `status='open'` rows, so there was no way to be rid of it;
    # and a closed round with no result row blanked the board outright until the
    # panel grew a branch for it. Nothing about the game is recoverable -- it
    # cannot be played, continued or scored -- so keeping the row served nobody.
    #
    # DELETING IS SAFE BECAUSE THE PREDICATE IS EXACT, which is the only reason
    # this is a delete and not a flag: every card sits in exactly one of hands /
    # piles / out / played at every moment of a round (`expand_state` rebuilds
    # `played` from `history`, so it is never merely absent), so the union IS
    # the deck and `deal_is_current` is arithmetic rather than a heuristic. A
    # predicate that could be WRONG must never drive an irreversible delete.
    g = state.get("game")
    if _unplayable(g):
        LOG.info("dropping unplayable save %s (v=%s, mode=%s)",
                 room_id, g.get("v"), g.get("mode"))
        delete_game(room_id)
        ROOMS.pop(room_id, None)
        return False
    ROOMS[room_id] = {
        "players": state.get("players", {}),
        "host": state.get("host"),
        "status": state.get("status", "open"),
        "game": state.get("game"),
        "meta": state.get("meta", {}),
        "vs_ai": state.get("vs_ai", False),
        "ai_player": state.get("ai_player"),
        # Persisted so a vs-bot game reconnected after a redeploy keeps the
        # tier it was created with instead of silently reverting to default.
        "ai_difficulty": _valid_difficulty(state.get("ai_difficulty")),
        # Rows written before skat mode existed have no `mode`; they resume as
        # classic, which is what their game dict already is.
        "mode": _valid_mode(state.get("mode")),
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
             "player_ids": _rooms.state_seat_ids(_safe_state(r["state_json"])),
             # TWO SEATS, ALWAYS, and it is stated rather than implied: the
             # frontend's "full" answer needs a cap, and a 2p game that leaves it
             # out reads as uncapped and offers Join to a third player.
             "max_players": 2,
             "host_name": r["player1_name"], "created_at": r["created_at"],
             # An open room has no game dict yet, so the mode has to come off
             # the room state -- the lobby badge says which auction you'd join.
             "mode": _row_mode(r["state_json"])}
            for r in rows]


def _row_mode(blob) -> str:
    """The room's auction mode, off a stored blob. Never raises: an unreadable
    row is a lobby badge, not a reason to 500 the list."""
    try:
        state = _decode_state(blob)
        if not isinstance(state, dict):
            return engine.DEFAULT_MODE
        g = state.get("game")
        if isinstance(g, dict) and g.get("mode"):
            return _valid_mode(g.get("mode"))
        return _valid_mode(state.get("mode"))
    except Exception:
        return engine.DEFAULT_MODE


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
        # `may_act`, not `turn_pid`: a match sitting between rounds has nobody on
        # turn and is waiting on EITHER player to deal the next one. Keyed on the
        # turn alone it would sit in Active with no prompt on either side, which
        # is exactly how a match gets forgotten.
        # ...AND THE LOBBY IS WHERE AN UNPLAYABLE SAVE ACTUALLY GETS DROPPED.
        # The load path deletes one too, but a room is only loaded when someone
        # OPENS it, so a game nobody clicks sits in Active forever — which is
        # precisely the complaint, and the first fix missed it. The decode above
        # is already paid for, so the check is free here.
        if _unplayable(g):
            LOG.info("dropping unplayable save %s from the lobby", r["id"])
            delete_game(r["id"])
            ROOMS.pop(normalize_room(r["id"]), None)
            continue
        your_turn = bool(g) and engine.may_act(g, user_id)
        out.append({
            "id": r["id"], "status": r["status"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": r["player1_id"] == user_id, "your_turn": your_turn,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "mode": _valid_mode(g.get("mode")) if g else _row_mode(r["state_json"]),
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
        res = (g or {}).get("result")
        if not res:
            continue
        seat = engine.seat_of(g, user_id)
        if seat is None:
            continue
        is_p1 = r["player1_id"] == user_id
        opp_name = (r["player2_name"] if is_p1 else r["player1_name"]) or "Opponent"
        # THE MATCH STANDING, not the last round's score. A game is rounds
        # played to a target, so the round that happened to end it says nothing
        # about who won -- a 100-84 match whose final deal was a 9-point make
        # was listed in History as "Won 9-0", and one ended by the OPPONENT
        # crossing the line first was listed as a loss on a round the reader
        # had no way to tell apart from the whole game. `scores` is the
        # fallback for a row written before matches existed, which really is
        # one round and really is the whole game.
        scores = res.get("match_scores") or res.get("scores") or [0, 0]
        rounds = int(res.get("round") or 1)
        # WHO WON IS ON THE ROW, not inferred from the numbers beside it.
        # A forfeit is a loss at any standing, so a player who walked out while
        # ahead used to be filed under Won. `match_winner` is absent on a row
        # written before it existed and on a one-round game with no match, and
        # the score comparison is right in both of those.
        mw = res.get("match_winner")
        won = (mw == seat) if mw is not None else scores[seat] > scores[1 - seat]
        tie = (mw == -1) if mw is not None else scores[seat] == scores[1 - seat]
        out.append({
            "id": r["id"], "opp_name": opp_name,
            "your_score": scores[seat], "opp_score": scores[1 - seat],
            "you_won": won,
            "tie": tie,
            "ai_difficulty": _rooms.state_ai_tier(state),
            "mode": engine.mode_of(g),
            # How many deals it took, and what it was played to -- the two
            # numbers that make the score above legible.
            "rounds": rounds,
            "target": res.get("match_target"),
            "abandoned": res.get("abandoned_by") is not None,
            # The LAST round's contract. Worth showing for a one-round game,
            # which is what the whole result is; the frontend drops it for a
            # match, where it is one deal in ten and reads as the headline.
            "contract": {"level": res.get("level"), "denom": res.get("denom"),
                         "made": res.get("made"),
                         "value": res.get("value"), "mult": res.get("mult"),
                         "you_declared": res.get("declarer") == seat},
            "updated_at": r["updated_at"],
        })
    return out


def _standings(state: dict) -> dict | None:
    """Who won a finished game, for the profile (core.results). The same reading
    as the History row above: the MATCH standing, and `match_winner` when the row
    has it (a forfeit is a loss at any score; -1 is a tie)."""
    g = state.get("game") or {}
    res = g.get("result") if isinstance(g, dict) else None
    seats = g.get("seats") if isinstance(g, dict) else None
    if not res or not seats or len(seats) != 2:
        return None
    scores = res.get("match_scores") or res.get("scores") or [0, 0]
    mw = res.get("match_winner")
    if mw is None:
        mw = 0 if scores[0] > scores[1] else 1 if scores[1] > scores[0] else -1
    return _results.standings(state, seats, [] if mw == -1 else [seats[mw]], draw=mw == -1,
                              scores={seats[0]: scores[0], seats[1]: scores[1]},
                              mode=engine.mode_of(g))


_results.register("dissonance", TABLE, decode=_decode_state, standings=_standings)


def _unplayable(g) -> bool:
    """Is this saved round one this engine cannot resume?

    ONE predicate, read by BOTH the load path and the lobby list, because two
    copies of "can this be played" would drift and the first symptom would be a
    game that vanishes from one and not the other.

    FAILS SAFE ON ABSENCE OF EVIDENCE, which matters more here than anywhere
    else in this file: the answer drives an irreversible DELETE, and
    `list_user_games` hands over `{}` when a row's `state_json` will not decode.
    Treating "I cannot tell" as "unplayable" would turn one transient decode
    error into destroyed games, so a dict without a deal in it is left alone.
    """
    if not isinstance(g, dict) or not g.get("hands"):
        return False
    if g.get("phase") == "over":
        return False
    return g.get("v", 1) < engine.VERSION or not engine.deal_is_current(g)


def delete_game(game_id: str) -> None:
    """Delete a row outright, whatever its status and whoever owns it.

    NOT the lobby's cancel -- that one is `delete_open_game`, which is scoped to
    an OPEN room the asking user hosts because it is a user action. This is the
    server disposing of a save it has proved unplayable, so there is no owner to
    check and no status to respect: a `playing` row is exactly the case that
    needs it.
    """
    conn = _db()
    try:
        conn.execute(f"DELETE FROM {TABLE} WHERE id=?", (game_id,))
        conn.commit()
    finally:
        conn.close()


def delete_open_game(game_id: str, user_id: str) -> bool:
    """SELECT-then-DELETE lives in core.rooms — never cursor.rowcount, which
    the libsql wrapper does not expose (it 500'd the cancel endpoint in prod)."""
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
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "mode": room.get("mode", engine.DEFAULT_MODE),
        # Scoped to the recipient: a room-wide token map would hand every
        # socket the other seat's reconnect credential.
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }
    # The bot decision currently waiting on the browser's search. It lives in
    # ROOM STATE rather than a one-shot message so every re-broadcast and every
    # reconnect re-ships it -- the same durability rule the engine's pending
    # sub-decisions follow, and the reason a dropped frame cannot strand a turn.
    # Only ever armed on a vs-AI room, which is what keeps the BOT'S OWN VIEW
    # (its hand) from reaching a human opponent.
    if room.get("_ai_search"):
        state["ai_search"] = room["_ai_search"]
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


def _bot_should_act(room: dict) -> bool:
    g = room.get("game")
    ai = room.get("ai_player")
    return bool(g and ai and not engine.is_over(g) and engine.turn_pid(g) == ai)


# ── Bot scheduler ────────────────────────────────────────────────────────────
# Heavy work never runs under ROOM_LOCK on the event-loop thread: snapshot under
# the lock, compute off it, re-lock, RE-VALIDATE that the turn is still the
# bot's, then apply. A rewrite that looped synchronous engine work under the
# lock took prod down once.
_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="dissonance-bot")


def _position_key(g: dict) -> tuple:
    """Everything a bot move was computed against.

    Two schedulers can be in flight at once (``_handle_move`` starts one, and
    so does every reconnect), so a move is only applied if the position has not
    moved underneath it. EVERY state-advancing action must show up here or the
    duplicate applies its stale move on top:

    * ``redeals`` — a skat hand thrown in resets phase/trick/history/log to
      their opening values, so without it a redeal reads as "nothing moved";
    * ``looked``/``swapped`` — the talon steps change none of the other
      components, which is exactly how a doubled scheduler managed to send
      ``look`` twice and have the second rejected as illegal.
    """
    return (g["phase"], g["trick"], len(g["history"]), len(g["auction"]["log"]),
            g.get("redeals", 0), bool(g.get("looked")), g.get("swapped"))


def _bot_move_sync(g: dict, seat: int, difficulty: str, seed: int):
    rng = random.Random(seed)
    # Easy blunders on purpose rather than searching worse — but only in the
    # two phases where a careless choice is still a LEGAL one. It used to
    # blunder in every non-play phase and reach for `opt["levels"]`, a key the
    # v2 auction stopped returning, so an Easy bot's first bid raised KeyError
    # and the scheduler gave up on the room.
    if difficulty == "easy" and rng.random() < 0.35:
        if g["phase"] == "play":
            return {"kind": "play", "card": rng.choice(engine.legal_moves(g, seat))}
        if g["phase"] == "auction":
            opt = engine.auction_options(g)
            if opt["may_pass"] and rng.random() < 0.5:
                return {"kind": "pass"}
            if engine.mode_of(g) == "skat":
                vals = opt["values"]
                return ({"kind": "bid", "value": rng.choice(vals[:4])} if vals
                        else {"kind": "pass"})
            # Never Null by accident: it is a contract, not a slip.
            bids = [b for b in opt["bids"] if b[1] != engine.NULL_DENOM]
            if bids:
                lvl, den = rng.choice(bids)
                return {"kind": "bid", "level": lvl, "denom": den}
            return {"kind": "pass"}
    kind, mv = bot.act(g, seat, rng)
    if kind == "move":
        return mv
    if kind == "play":
        return {"kind": "play", "card": mv}
    if kind == "swap":
        return {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
    if mv.get("pass"):
        return {"kind": "pass"}
    return {"kind": "bid", "level": mv["level"], "denom": mv["denom"]}


async def _ask_the_client(room_id: str, seat: int) -> dict | None:
    """Arm one card-play decision for the browser and wait for its answer.

    Returns the move, or None to mean "the server should do this one" -- an
    unarmed client, a timeout, a stale reply, or an answer the engine refuses.
    Degradation is therefore per-DECISION and deadlock is impossible: the caller
    always has the server bot behind it, so the turn ends either way.
    """
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or not room.get("client_ai"):
            return None
        g = room["game"]
        # The STALENESS KEY is a monotonic per-room counter, not the ply. Every
        # play happens to append exactly one history entry today, so a ply would
        # work -- but nothing ENFORCES that, and two decisions sharing a key make
        # a stale reply indistinguishable from a fresh one.
        seq = room["_ai_decision_seq"] = room.get("_ai_decision_seq", 0) + 1
        room["_ai_search"] = {
            "decision": seq,
            "seat": seat,
            "budget_ms": CLIENT_AI_BUDGET_MS,
            "max_worlds": (CLIENT_AI_MAX_WORLDS if g["phase"] == "play"
                           else CLIENT_AI_AUCTION_WORLDS_EXPERT
                           if _valid_difficulty(room.get("ai_difficulty"))
                           in SEARCH_AUCTION_TIERS
                           else CLIENT_AI_AUCTION_WORLDS),
            # The bot's OWN redacted view -- the same builder that feeds a human
            # seat, so there is no second projection to keep in step and the bot
            # provably searches only what its seat may know.
            "view": engine.view_for(g, seat),
        }
        if g["phase"] == "play":
            # The SCORING RULE, as numbers, straight from the function `_finish`
            # scores with. The search optimises the payoff this room will pay
            # rather than the trick points that merely measure it -- and shipping
            # the terms instead of reimplementing them in Rust is what keeps the
            # two from drifting. Public: it is derivable from the contract, which
            # both seats can already see. Only meaningful once a contract EXISTS,
            # which is why it is not on an auction request.
            room["_ai_search"]["payoff"] = engine.payoff_terms(g)
            # THE AUCTION AS EVIDENCE, for the card play as well as the Double.
            # The declarer won an auction, so the worlds the searcher samples
            # must not hand them an average hand -- and MEASURED
            # (`tools/decayprobe.py`, 200 rounds) that bias does NOT wash out as
            # the round reveals itself: the declarer's remaining holding sits at
            # the 0.769 percentile of a uniform resample at trick 1 and is still
            # 0.617 at trick 11 (0.775 over tricks 1-4 against 0.626 over 9-13).
            # So it applies at all THIRTEEN decisions, not just the one.
            # Optional on the wire; a cached wasm ignores it and samples
            # uniformly, exactly as before.
            if engine.mode_of(g) == "classic":
                prior = bot.bid_prior_terms(g)
                if prior:
                    room["_ai_search"]["bid_prior"] = prior
        else:
            # An AUCTION decision: every legal action, priced, each carrying its
            # own move. The browser ranks them and sends back one of the moves it
            # was handed, so no rule about what a bid IS crosses the wire.
            opts = engine.auction_payoff_options(g)
            room["_ai_search"]["auction"] = {
                "phase": g["phase"],
                # Whoever would be DECLARING under these options -- not always
                # the seat being asked. A defender weighing Kontra is pricing the
                # OPPONENT's contract; only the sign at the end is theirs.
                #
                # **DOUBLE BELONGS IN THIS LIST AND WAS MISSING** (fixed
                # 2026-08-14). Classic's Double is the defender's bet on the
                # DECLARER's settled contract, exactly as Kontra is -- but the
                # phase was absent here, so the request named the acting seat,
                # i.e. the DEFENDER, as declarer. The searcher then solved every
                # world with the wrong seat leading trick 1 and priced the
                # contract as one the defender was buying, and `sign` came out
                # +1 so the pick was not even negated back.
                #
                # It failed SILENTLY, in the way this tier always does: two legal
                # options, a plausible number on each, and a Double taken about
                # as often on contracts that made as on contracts that failed.
                # Measured against exact ground truth over 150 real rounds, the
                # searcher found 2 of the 13 contracts that deserved a Double;
                # with the phase in this list it finds 9 of 13.
                #
                # NOTE THIS FIXES A CACHED WASM TOO, which is why it needs no
                # expand/contract: `answer_auction` derives both the solve's
                # declarer and the answer's sign from this one field, so an
                # older artifact starts pricing the Double correctly the moment
                # the server stops lying to it.
                "declarer": (g["auction"]["declarer"]
                             if g["phase"] in ("double", "kontra", "re")
                             else seat),
                "options": opts,
                "pass": ({"kind": "pass"}
                         if g["phase"] == "auction"
                         and engine.auction_options(g)["may_pass"] else None),
            }
            # THE TALON MODEL (classic auctions only). The fitted swap weights
            # ride along so the leaf can give each determinized world's
            # prospective declarer its best exchange before solving -- without
            # this, winning an auction is priced without the ~+1.5 the swap is
            # now worth, a one-directional lean toward conceding. Optional on
            # the wire; an older wasm ignores it and prices the deal as dealt.
            # `!= "skat"`, not `== "classic"`: minor mode swaps exactly the way
            # classic does (contract settled, then the talon), so its auction
            # leaf wants the model too. The weights were FITTED on classic's
            # +2 parity -- an approximation in minor, but the shape they encode
            # (low cards are worth taking) holds under either even value, and
            # pricing the swap at zero is the measured ~1.5-point lean this
            # field exists to remove. Minor's own fit is a queued swaplab run.
            if g["phase"] == "auction" and engine.mode_of(g) != "skat":
                room["_ai_search"]["auction"]["swap"] = bot.swap_policy_terms()
            # THE DOUBLE: a settled contract, priced exactly, against a world
            # sample that CONDITIONS ON THE AUCTION and a threshold that stops
            # the argmax doubling coin flips. Both are optional on the wire and
            # both default to today's behaviour, so a cached wasm older than
            # this simply keeps the old Double -- the ordinary degradation.
            #
            # CLASSIC ONLY: the tilt map was fitted on classic levels and the
            # margin is in classic's payoff units. Minor runs the same phase and
            # deliberately gets neither until its own sweep exists.
            if g["phase"] == "double" and engine.mode_of(g) == "classic":
                prior = bot.bid_prior_terms(g)
                if prior:
                    room["_ai_search"]["auction"]["bid_prior"] = prior
                margin = DOUBLE_MARGIN.get(engine.mode_of(g), 0.0)
                if margin:
                    room["_ai_search"]["auction"]["double_margin"] = margin
            # EXPERT: the same options, valued by a tree instead of a price.
            # Optional on the wire and ignored by any wasm that predates it, so
            # the cached-bundle window degrades to Hard rather than to nothing.
            # THE EXACT LEAF -- an experiment, off unless `DIS_EXACT_LEAF` is
            # set (see `bot.exact_leaf`). It applies to the myopic pricer and
            # the tree alike, so it rides beside the options rather than inside
            # the Expert block, and it is optional on the wire: a wasm that
            # predates it prices the old way.
            if bot.exact_leaf():
                room["_ai_search"]["auction"]["exact_leaf"] = True
            # THE LEAF, CALIBRATED ON REAL PLAY -- an experiment, off unless
            # `DIS_PLAY_CAL` is set. It rides beside the options because it
            # corrects the POINTS every pricer reads, the myopic one and the
            # tree alike, and not any rule of the auction.
            cal = bot.play_calibration()
            if cal:
                room["_ai_search"]["auction"]["play_cal"] = cal
            tier = _valid_difficulty(room.get("ai_difficulty"))
            if tier in SEARCH_AUCTION_TIERS:
                search = engine.auction_search_payload(g)
                if search:
                    # EXPERT alone softens the modelled opponent -- see
                    # EXPERT_OPP_TEMP. Optional on the wire and defaulted to the
                    # exact minimax, so a wasm that predates it plays the Hard
                    # tree: the cached-bundle window degrades one rung, never
                    # to nothing.
                    if tier == "expert":
                        search["rules"]["opp_model"] = "soft"
                        search["rules"]["opp_temp"] = EXPERT_OPP_TEMP
                    # The experiment arms, from the one place both this and
                    # `tools/cfrlab.py` read them -- see the docstring there for
                    # why that is a function rather than two literals.
                    search["rules"].update(bot.search_rules_overrides())
                    # THE OPPONENT'S OWN UNCERTAINTY -- an experiment, 0 as
                    # shipped. It rides beside the options rather than inside
                    # `rules` because it buys SOLVES rather than describing the
                    # auction: `belief_worlds` is how many deals the modelled
                    # opponent chooses against, and `rules.opp_model` is what
                    # the tree then does with them. Asking for the model without
                    # funding the sample falls back to plain minimax.
                    if bot.belief_worlds() > 0:
                        room["_ai_search"]["auction"]["belief_worlds"] = \
                            bot.belief_worlds()
                        search["rules"]["opp_model"] = "belief"
                    room["_ai_search"]["auction"]["search"] = search
        room["_ai_pending_move"] = None
        evt = room["_ai_move_evt"] = asyncio.Event()
        mine = seq

    await broadcast_state(room_id)
    try:
        await asyncio.wait_for(evt.wait(), CLIENT_AI_TIMEOUT)
    except asyncio.TimeoutError:
        LOG.info("dissonance client AI timed out; the server finishes it (%s)", room_id)
        move = None
    else:
        async with ROOM_LOCK:
            r = ROOMS.get(room_id)
            move = r.get("_ai_pending_move") if r else None
    async with ROOM_LOCK:
        r = ROOMS.get(room_id)
        # Only tear down OUR decision. Two schedulers can be in flight at once
        # (`_handle_move` starts one and so does every reconnect), and a blind
        # clear here would disarm the other one's live request -- which does not
        # break anything, because the `_position_key` guard still stops a stale
        # move being applied, but it silently drops the room to the server bot.
        if r and (r.get("_ai_search") or {}).get("decision") == mine:
            r["_ai_search"] = None       # a late reply now reads as stale
            r["_ai_pending_move"] = None
            r["_ai_move_evt"] = None
    return move


async def _schedule_bot_turn(room_id: str) -> None:
    """Safe to call at any time; no-ops when it is not the bot's turn."""
    loop = asyncio.get_running_loop()
    while True:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            g = room["game"]
            ai = room["ai_player"]
            seat = engine.seat_of(g, ai)
            difficulty = _valid_difficulty(room.get("ai_difficulty"))
            snapshot = json.loads(json.dumps(g))
            position_before = _position_key(g)
            # Card play AND the auction now. The talon (look/Hand) and the swap
            # stay on the server: both are decisions about information rather
            # than about a contract, and neither has a payoff the solver can
            # price -- what Hand is worth depends on the game you have not named
            # yet. Everything else is armed if there is a real choice in it.
            phase = g["phase"]
            if phase == "play":
                choices = len(engine.legal_moves(g, seat))
            elif phase in CLIENT_AI_PHASES:
                opts = engine.auction_payoff_options(g)
                # Kontra ships one option and the decision is its SIGN, so a
                # single option is a real choice there and nowhere else.
                choices = len(opts) + (1 if phase in ("kontra", "re") else 0)
            else:
                choices = 0
            use_client = (difficulty in CLIENT_AI_TIERS
                          and bool(room.get("client_ai"))
                          and choices > 1)

        t0 = time.monotonic()
        move = None
        if use_client:
            asked = await _ask_the_client(room_id, seat)
            if asked is not None:
                move = asked
        if move is None:
            try:
                move = await loop.run_in_executor(
                    _BOT_EXEC, _bot_move_sync, snapshot, seat, difficulty,
                    _rooms.bot_seed(position_before, seat, difficulty))
            except Exception:
                LOG.warning("dissonance bot failed in %s", room_id, exc_info=True)
                return
        delay = BOT_FLOOR_SECONDS - (time.monotonic() - t0)
        if delay > 0:
            await asyncio.sleep(delay)

        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            g = room["game"]
            # Re-validate: the position must not have moved while we computed.
            if _position_key(g) != position_before:
                continue
            try:
                engine.apply_move(g, ai, move)
            except ValueError:
                LOG.warning("dissonance bot produced an illegal move in %s", room_id)
                return
            _sync_status_from_game(room)
            save_game(room_id)
        await broadcast_state(room_id)


def _new_rng(players=(), mode: str = "") -> random.Random:
    # The deal seam. Unseeded in production; `GAMES_DEAL_SEED` makes the hand a
    # function of who is at the table so the render gate replays it — see
    # core.rooms.deal_rng for why that env var exists.
    return _rooms.deal_rng(players, mode=mode)


def _start_new_game(room: dict, room_id: str) -> None:
    seats = [p for p in room["players"].keys()]
    mode = _valid_mode(room.get("mode"))
    rng = _new_rng(seats, mode)
    rng.shuffle(seats)   # who opens the auction is a real edge; randomise it
    room["game"] = engine.new_game(seats, rng, opener=0, mode=mode)
    room["status"] = "playing"


# ── WebSocket ────────────────────────────────────────────────────────────────
@dissonance_app.websocket("/ws/{room}/{player}")
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
            elif action in ("start", "move", "abandon",
                            "client_ai_ready", "ai_move"):
                if not authed:
                    await _send(websocket, {
                        "type": "error",
                        "message": "not authenticated for this seat"})
                    continue
                if action == "start":
                    await _handle_start(websocket, room_id, pid)
                elif action == "move":
                    await _handle_move(websocket, room_id, pid, msg)
                elif action == "client_ai_ready":
                    await _handle_client_ai_ready(websocket, room_id, pid, msg)
                elif action == "ai_move":
                    await _handle_ai_move(websocket, room_id, pid, msg)
                else:
                    await _handle_abandon(websocket, room_id, pid)
            else:
                await _send(websocket, {"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        # Stale-socket guard + client-AI disarm + empty-room cleanup, all in
        # core/rooms.py. Disarming matters: with the tab gone there is nobody to
        # answer, and every later decision would burn the whole watchdog before
        # the server took over.
        _rooms.release_socket(ROOMS, room_id, pid, websocket, disarm_client_ai=True)


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    difficulty = _valid_difficulty(msg.get("ai_difficulty"))
    mode = _valid_mode(msg.get("mode"))
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
            "mode": mode,
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
            # Re-entering an EXISTING seat: prove it, or the reply below hands
            # a stranger that seat's hand.
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
            await _send(ws, {"type": "error", "message": "game is over"})
            return
        # NOT `turn_pid(g) != pid`. A match sits between rounds with the round
        # scored and no seat on turn, and either player may deal the next one --
        # a question the single-seat turn model cannot answer, so the engine
        # owns it.
        if not engine.may_act(g, pid):
            await _send(ws, {"type": "error", "message": "not your turn"})
            return
        try:
            engine.apply_move(g, pid, msg.get("move") or {})
        except (ValueError, KeyError, TypeError) as exc:
            await _send(ws, {"type": "error", "message": str(exc) or "illegal move"})
            return
        if (msg.get("move") or {}).get("kind") == "next_round":
            # A new deal makes any armed search a question about a game that no
            # longer exists. Re-broadcasting it would hand the browser a view of
            # the previous round's cards; the answer would be re-validated and
            # thrown out, but the arming is what must not survive the deal.
            room["_ai_search"] = None
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
            seat = engine.seat_of(g, pid)
            if seat is not None:
                # Forfeit: the opponent takes the contract's value, in whichever
                # currency this room's mode scores in. The row is built in the
                # engine so it carries every key the result panel reads --
                # hand-rolling it here is how a skat forfeit came out as
                # "bought it at undefined".
                g["phase"] = "over"
                g["result"] = engine.abandon_result(g, seat)
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


async def _handle_client_ai_ready(ws, room_id, pid, msg):
    """The browser says it has the search core loaded and will answer.

    Opt-in per SOCKET, not per room: the flag is cleared when the tab goes
    (`release_socket(disarm_client_ai=True)`) and a reconnecting client re-arms
    itself, so a room can never sit waiting on a browser that is not there.
    Refused unless this really is a vs-AI room on a client tier -- the armed
    decision carries the BOT'S view, and a human opponent must never be handed a
    reason to receive it.
    """
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or not room.get("vs_ai") or pid not in room.get("players", {}):
            return
        if _valid_difficulty(room.get("ai_difficulty")) not in CLIENT_AI_TIERS:
            return
        # MINOR MODE NEEDS A CLIENT THAT SPEAKS even_val (`wire: 2`), and SKAT
        # MODE ONE THAT SPEAKS card_pts (`wire: 3`, card scoring 2026-08-09)
        # AND must_head (`wire: 4`, the legality rule of 2026-08-10). An older
        # cached bundle never sends the field, and its wasm would silently
        # search the wrong game -- classic trick values in a minor room, the
        # trick parity in a card-scored skat room, or (rung 4, the worst of the
        # three) a skat room WITHOUT must-head, where it answers with cards
        # this room calls illegal and the answers are dropped on the floor.
        # Refusing to arm keeps the honest degradation path: the room plays the
        # server bot, exactly as if the browser were absent. Classic rooms
        # accept any vintage, as before.
        #
        # The skat requirement is DERIVED from the room's own rules rather than
        # pinned at 4, so turning `MUST_HEAD` off puts skat back to rung 3 and
        # re-admits every cached bundle with no second edit here.
        mode = room.get("mode") or ""
        # A MODE THE SEARCH CORE CANNOT PLAY IS NEVER ARMED. Dummy mode deals
        # a third hand and the Rust core is two-seat to its bones, so an armed
        # client would answer with a card for the wrong hand, the engine would
        # refuse it, and the room would run on the server bot at full speed
        # while still calling itself Hard. The create modal does not offer the
        # searching tiers there either (`/catalog`'s `searchable_modes`), so
        # this is the second of two locks rather than the only one.
        if not engine.client_searchable(mode):
            return
        wire = int(msg.get("wire") or 1)
        need = 1
        if mode == "minor":
            need = 2
        elif engine.uses_card_points(mode):
            need = 4 if engine.must_head_mode(mode) else 3
        if wire < need:
            return
        room["client_ai"] = bool(msg.get("ready", True))
    # A decision may already be waiting: the room armed one, the tab reloaded,
    # and the reconnect's own broadcast carries `ai_search` -- so re-scheduling
    # here is what unsticks a room whose searcher went away mid-decision.
    asyncio.create_task(_schedule_bot_turn(room_id))


def _validated_bot_move(g, ai, move):
    """The browser's answer, or None to mean "the server should do this one".

    NOTHING about the shape is trusted. The auction has four move kinds across
    two modes and a client-side allowlist would be a second copy of the rules --
    so the check is the ENGINE itself, run against a throwaway copy of the game.
    A move that would raise there is treated exactly like silence.
    """
    if not g or not ai or not isinstance(move, dict):
        return None
    try:
        probe = json.loads(json.dumps(g))
        engine.apply_move(probe, ai, move)
    except Exception:
        return None
    return move


async def _handle_ai_move(ws, room_id, pid, msg):
    """The browser's answer to the armed decision.

    NOTHING here is trusted. The move is checked against the armed decision's
    key (so a late reply to a superseded decision is dropped rather than
    applied) and then against `engine.legal_moves` for the BOT's seat. An
    invalid answer is treated exactly like silence: the waiter is released with
    no move and the server bot plays the decision itself.
    """
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        armed = room.get("_ai_search")
        evt = room.get("_ai_move_evt")
        if not armed or evt is None:
            return
        if msg.get("decision") != armed.get("decision"):
            return                       # stale -- a superseded decision
        g = room.get("game")
        ai = room.get("ai_player")
        # `card` is the card-play shape and `move` the general one; a browser on
        # a cached bundle still speaks the first, so both are read.
        card = msg.get("card")
        proposed = msg.get("move")
        if proposed is None and isinstance(card, int):
            proposed = {"kind": "play", "card": card}
        move = _validated_bot_move(g, ai, proposed)
        if move is None:
            LOG.info("dissonance client AI answered with a move the engine "
                     "refuses; the server finishes it (%s)", room_id)
        room["_ai_pending_move"] = move
        evt.set()


# ── REST ─────────────────────────────────────────────────────────────────────
@dissonance_app.get("/health")
async def health():
    return {"ok": True, "game": "dissonance", **build_info()}


@dissonance_app.get("/catalog")
async def catalog():
    """Static rules data the client renders — kept server-side so the two can
    never disagree about what a trick is worth."""
    return {
        # Ten names: the base deck's eight plus the wide deck's 5 and 6, in
        # STRENGTH order, which is the order `engine.rank` indexes them in.
        "ranks": engine.RANK_NAMES,
        "suits": engine.SUIT_NAMES,
        "denoms": engine.DENOM_NAMES,
        "tricks": engine.NTRICKS,
        "pool": engine.POOL,
        "trick_values": [engine.trick_value(t) for t in range(engine.NTRICKS)],
        "min_level": engine.MIN_LEVEL,
        "max_level": engine.MAX_LEVEL,
        # The scalar is the CAPPED modes' number, kept for old bundles; the
        # per-mode caps are the truth since classic dropped its cap
        # (2026-08-13) -- classic's entry reads its own ceiling, i.e. uncapped.
        "max_raise": engine.MAX_RAISE,
        "max_raises": {mode: engine.raise_cap_for(mode)
                       for mode in engine.MODES},
        # Classic's replacement for the cap: +N per level the FINAL bid jumped,
        # to the defender, on a set. Served so the client renders the price
        # rather than hardcoding a 3.
        "jump_set_bonus": dict(engine.JUMP_SET_BONUS),
        "short_penalty": engine.SHORT_PENALTY,
        # v2: ranked denominations, the Null contract, and the declarer swap.
        "ranked_denoms": True,
        # Null is a CONSOLATION now, not a rung: no denomination, no level, no
        # set price. What a client still needs is what it pays; the skat side of
        # that already ships below with the rest of the price table.
        "null_make": engine.NULL_MAKE,
        "n_out": engine.N_OUT,
        "n_shown": engine.N_SHOWN,
        "difficulties": list(DIFFICULTIES),
        # Skat mode. The value ladder is DERIVED from the bases in engine.py and
        # served from here so the client never hardcodes it -- the two tables
        # cannot disagree about what a bid costs.
        "modes": list(engine.MODES),
        "default_mode": engine.DEFAULT_MODE,
        "skat_bases": list(engine.SKAT_BASE),
        "skat_values": list(engine.SKAT_VALUES),
        "skat_null_value": engine.SKAT_NULL_VALUE,
        "sharp_bonus": engine.SHARP_BONUS,
        # Per mode, because the shape is per mode even while both read 1.
        "over_bonus": dict(engine.OVER_BONUS),
        # Minor mode (2026-08-09): even tricks +1 over the classic auction.
        # Everything the client renders about it comes from here rather than
        # being hardcoded beside a "+2" somewhere.
        "even_value": dict(engine.EVEN_TRICK_VALUE),
        # Skat scores CARDS since 2026-08-09: per-rank worth, served so the
        # client renders the values off the wire instead of hardcoding the
        # table. Its `pools` entry is None -- a card-scored round's pool is a
        # property of the deal (`engine.played_pool`), not the mode.
        # The FULL ten-rank table, matching `ranks` above. The per-room wire
        # slices it to the deck that room deals (`engine.wire_card_values`);
        # this is the catalog, so it describes the whole game.
        "card_values": list(engine.CARD_VALUES),
        "card_modes": [m for m in engine.MODES if engine.uses_card_points(m)],
        # THE WIDE DECK (2026-08-10): dummy deals 40 cards -- the same 32 plus a
        # 5 and a 6 in each suit -- because three seats of thirteen do not come
        # out of 32. Per mode, so nothing has to infer it from a seat count.
        "deck_size": {m: engine.deck_size(m) for m in engine.MODES},
        # DUMMY mode (2026-08-10): a third hand, played by the declarer. The
        # client reads the shape from here rather than hardcoding a seat count
        # -- and `searchable_modes` is what stops the create modal offering
        # Hard/Expert in a room whose game the search core cannot play at all.
        "seats": {m: engine.layout_for(m)[0] for m in engine.MODES},
        # `tricks_by_mode`, NOT `tricks` -- that key is already a scalar above
        # and a duplicate in this literal would silently shadow it, handing
        # every existing reader a dict where it expects 13.
        "tricks_by_mode": {m: engine.layout_for(m)[3] for m in engine.MODES},
        "searchable_modes": [m for m in engine.MODES
                             if engine.client_searchable(m)],
        # QUARTET (2026-08-21): four hands, two players, and a BACKED bid -- a
        # denomination may only be named by a bidder holding this many of it
        # across their two hands. Served so the create modal and the rules
        # panel state the real number rather than a hardcoded 6, and so the
        # bid pad can say WHY a suit is greyed out.
        "quartet_backing": engine.QUARTET_BACKING,
        "quartet_hands": engine.QUARTET_HANDS,
        "pools": {m: engine.pool_for(m) for m in engine.MODES},
        "max_levels": {m: engine.max_level_for(m) for m in engine.MODES},
        "minor_null_make": engine.MINOR_NULL_MAKE,
        "minor_short_penalty": engine.MINOR_SHORT_PENALTY,
        "match_targets": dict(engine.MATCH_TARGET),
        # THE FLAT STAKE (2026-08-11): +-10 riding on classic's make and set
        # bases. Per-mode dicts like the targets, served so the client's
        # mid-round pricing (the Double prompt, the contract panel, the chip)
        # is the engine's own arithmetic and not a hardcoded 10.
        "flat_make_bonus": dict(engine.FLAT_MAKE_BONUS),
        "flat_set_penalty": dict(engine.FLAT_SET_PENALTY),
        # THE REST OF THE CLASSIC CURVE, so the auction panel can price a bid
        # BEFORE it is made -- "5D makes 29, goes down for 23" -- with the
        # engine's own numbers instead of a second copy of `L^2 + 4` and
        # `2L + 2` in the client. Per-mode dicts like the two above.
        "set_level_rate": dict(engine.SET_LEVEL_RATE),
        "linear_make_bonus": dict(engine.LINEAR_MAKE_BONUS),
        # CLASSIC'S OWN per-point set rate. `short_penalty` above is
        # `SHORT_PENALTY`, which classic STOPPED using on 2026-08-16 when
        # `CLASSIC_SHORT_PENALTY` was split out so classic and skat could move
        # independently. They are both 5 today, so a client reading the wrong
        # one is not visibly wrong yet -- which is exactly why it is served now,
        # before the two diverge and the panel quietly prices the wrong game.
        "classic_short_penalty": engine.CLASSIC_SHORT_PENALTY,
        # THE DOUBLE'S DIALS (2026-08-16), for the same reason as the curve
        # above: the Kontra prompt, the contract box and the result panel all
        # state what doubling costs, and every one of them was doing it with a
        # hardcoded x2 and a retired ramp long after the shipped rule became
        # "the leap and the shortfall double, the fixed stake does not".
        # Served as the engine's own dicts, ABSENCES INCLUDED -- a mode missing
        # from one of these means "the plain Double" in `_terms_for`, and the
        # client mirrors that default rather than being handed a filled-in copy
        # it could not tell apart from a deliberate 2.
        "double_make_mult": dict(engine.DOUBLE_MAKE_MULT),
        "double_base_mult": dict(engine.DOUBLE_BASE_MULT),
        "double_jump_mult": dict(engine.DOUBLE_JUMP_MULT),
        "jump_doubled": dict(engine.JUMP_DOUBLED),
        "doubled_short_penalty": dict(engine.DOUBLED_SHORT_PENALTY),
        "double_ramp": engine.DOUBLE_RAMP,
    }


@dissonance_app.get("/games")
def games_open():
    return {"games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@dissonance_app.get("/games/mine")
def games_mine(token: str | None = Depends(_bearer_token),
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


@dissonance_app.get("/games/history")
def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"games": []}
    return {"games": list_user_history(user["id"])}


@dissonance_app.post("/games/{game_id}/leave")
async def games_leave(game_id: str, token: str | None = Depends(_bearer_token),
                      player_id: str | None = None,
                      room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = (await asyncio.to_thread(get_user_by_session, token)) if token else None
    room_id = normalize_room(game_id)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        ok, message = _rooms.remove_open_seat(
            room or {}, player_id or "", room_token=room_token,
            session_uid=(user or {}).get("id"))
        if not ok:
            return {"ok": False, "message": message}
        save_game(room_id)
    await broadcast_state(room_id)
    return {"ok": True}


@dissonance_app.delete("/games/{game_id}")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None,
                       room_token: str | None = Header(default=None, alias="X-Room-Token")):
    user = (await asyncio.to_thread(get_user_by_session, token)) if token else None
    owner = (user or {}).get("id") or player_id
    if not owner:
        return {"ok": False, "message": "missing identity"}
    room_id = normalize_room(game_id)
    if not user:
        async with ROOM_LOCK:
            room = _ensure_room_loaded(room_id)
            if not _rooms.authorized_open_host(room or {}, owner, room_token=room_token):
                return {"ok": False, "message": "could not verify this seat"}
    ok = await asyncio.to_thread(delete_open_game, room_id, owner)
    if ok:
        ROOMS.pop(room_id, None)
    return {"ok": ok}
