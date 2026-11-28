"""Boss Rush CO-OP rooms (owner's ask, 2026-11-22): two players, two browsers, one fight.

The fight is a deterministic simulation (bossrush/sim.js) and the server never runs
it. Each browser sends its inputs as it samples them. Both browsers confirm the same
ticks after receiving both seats' inputs, and may render ahead locally while waiting.

What the server does own:
  - the room: two seats, bound to whoever proved them (the seat token minted on
    create/join, or the session of the account the seat belongs to);
  - the run: it opens the run row itself (`create_run`, the same as `POST /runs`) once
    both players have picked, so the boss order and the arenas reach both browsers in
    one message, and either player may start the next run (Play again, hold R);
  - how far the clients may predict, from the round trips both browsers measured;
  - the version check: two different builds would simulate two different fights.

Like the solo run, the outcome is the browser's report (the HOST posts the entries and
clears over HTTP) and the time is the server's. Rooms live in memory only: a room is a
waiting room plus a live fight, and neither can be resumed after a restart.

A DROPPED SEAT CAN COME BACK (2026-11-28). The server keeps every input row it relays,
per stage and seat, as compact JSON. A seat whose socket closes mid-fight is AWAY for
`GRACE_S`; the others stall (they cannot confirm a tick without its row) and are told
why. A browser that rejoins in that time gets the stored rows (`resume`), replays the
fight to where it was and carries on from the first row it had not sent. That only
works if every live peer holds exactly the rows the server stored, so a seat whose
rows were relayed past a gap, or a run past `RESUME_MAX_BYTES`, ends as before.

SENDS NEVER WAIT (2026-11-28). Each socket has its own outbound queue and writer task,
so the room lock and the input relay never wait on a slow or half-dead connection
(a 3 s send timeout under the one lock used to hold up every room).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time

from fastapi import WebSocket, WebSocketDisconnect

from core import rooms as _rooms

CHARACTERS = {"ranger", "paladin", "diviner", "ninja", "simon"}
ROWS_PER_MESSAGE = 30            # a message carries a few ticks of controls; a burst after a stall, more
ROW_LEN = 8                      # replay.js recordInput: [mx, my, ax, ay, fire, ability, enter, auto]
PROTOCOL = 4
LEGACY_PROTOCOL = 3
MAX_SEATS = 4
STEP_MS = 1000 / 60
# The relay carries up to ~60 messages a second from each seat, far above the shared game
# budget (`WS_MESSAGES_PER_MIN`, a turn-based game's), so the socket has its own.
COOP_MESSAGES_PER_MIN = 6000
GRACE_S = 30                     # how long a dropped seat's fight waits for it
RESUME_MAX_BYTES = 6_000_000     # stored input per run; past it, a dropped seat ends the run
OUT_QUEUE_MAX = 2000             # messages waiting for one socket before it is given up on
SEND_TIMEOUT_S = 10

COOP_ROOMS: dict[str, dict] = {}
# Your seat, from a browser that cannot prove it (another device, or cleared site data).
SEAT_HELD = ("That seat is held by another browser. Ask the host to free your seat "
             "in the room, then open the link again.")
log = logging.getLogger(__name__)


def prediction_window(rtts) -> int:
    """Max unconfirmed ticks. Cover both half round trips, scheduling skew and jitter."""
    estimates = [r if isinstance(r, (int, float)) and 0 < r < 5000 else 150 for r in rtts]
    rtt = sum(sorted(estimates)[-2:]) / min(2, len(estimates)) if estimates else 150
    return max(16, min(48, math.ceil((rtt + 150) / STEP_MS)))


def _public(room: dict, viewer: str | None) -> dict:
    seats = []
    for i, pid in enumerate(room["seats"]):
        if pid is None:
            seats.append(None)
            continue
        seats.append({"id": pid, "name": room["names"][pid], "character": room["chars"].get(pid),
                      "online": pid in room["sockets"], "host": i == 0, "you": pid == viewer})
    run = room.get("run")
    return {"code": room["code"], "seats": seats, "set_id": room["set_id"], "first": room["first"],
            "run_id": run["run_id"] if run and not run.get("over") else None,
            "last_run_id": run["run_id"] if run else None,
            "same_build": len({room["builds"].get(p) for p in room["seats"] if p}) <= 1}


def _open_outbox(ws) -> asyncio.Task:
    """Give `ws` an outbound queue and the one task that writes it, in order."""
    queue: asyncio.Queue = asyncio.Queue()
    ws._coop_out = queue

    async def writer():
        while True:
            text = await queue.get()
            if text is None:
                return
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=SEND_TIMEOUT_S)
            except Exception:
                ws._coop_out = None              # gone: drop what follows, and end its handler
                try:
                    await ws.close(code=1011)
                except Exception:
                    pass
                return
    return asyncio.create_task(writer())


def _close_outbox(ws) -> None:
    queue = getattr(ws, "_coop_out", None)
    if queue is not None:
        ws._coop_out = None
        queue.put_nowait(None)


async def _send(ws, payload) -> None:
    """Queue a message for `ws` and return at once; a str is sent as it is (pre-encoded)."""
    queue = getattr(ws, "_coop_out", None)
    if queue is None:
        return
    if queue.qsize() >= OUT_QUEUE_MAX:          # it has stopped reading: let it go
        _close_outbox(ws)
        asyncio.ensure_future(ws.close(code=1011))
        return
    queue.put_nowait(payload if isinstance(payload, str) else json.dumps(payload))


async def _broadcast(room: dict, payload=None) -> None:
    for pid, ws in list(room["sockets"].items()):
        await _send(ws, payload if payload is not None else {"type": "room", "room": _public(room, pid)})


def setup_coop(app, connect, user_by_session, create_run, playable) -> None:
    """`create_run(set_id, first, seats)` opens a run row (bossrush/api.py);
    `playable(set_id, user)` says whether that player may open a run on the set."""
    COOP_LOCK = asyncio.Lock()           # one per app: a test's app runs on a loop of its own

    async def open_run(room: dict) -> dict | str:
        """Both seated, both picked, one build: a new run for the pair. A string is why not."""
        seats = [pid for pid in room["seats"] if pid is not None]
        if len(seats) < 2:
            return "Waiting for a second player."
        if room["set_id"] == "lantern-trio" and len(seats) > 2:
            return "The Lantern Trio supports two players."
        if room["set_id"] == "crypt-trio" and room["protocol"] == LEGACY_PROTOCOL:
            return "Refresh Boss Rush to play Crypt Trio co-op."
        if any(not room["chars"].get(pid) for pid in seats):
            return "Everyone needs to pick a character."
        if any(pid not in room["sockets"] for pid in seats):
            return "A player is not connected."
        if len({room["builds"].get(pid) for pid in seats}) > 1:
            return "You are on different versions of the site. Both of you refresh the page."
        players = [{"name": room["names"][pid], "character": room["chars"][pid],
                    "player_id": f"u:{room['users'][pid]['id']}" if room["users"].get(pid) else f"g:{pid}"}
                   for pid in seats]
        try:
            host = room["users"].get(seats[0])
            if not await asyncio.to_thread(playable, room["set_id"], host):
                return "That boss set cannot be played."
            run = await asyncio.to_thread(create_run, room["set_id"], room["first"], players)
        except ValueError as exc:
            return str(exc)
        except Exception:
            log.exception("Could not open a Boss Rush co-op run")
            return "Could not start the run. Try again."
        return {**run, "characters": [room["chars"][pid] for pid in seats],
                "names": [room["names"][pid] for pid in seats],
                "slots": [room["seats"].index(pid) for pid in seats],
                "analog_movement": room["protocol"] == PROTOCOL,
                "prediction_window": prediction_window([room["rtt"].get(pid) for pid in seats]), "protocol": room["protocol"]}

    @app.websocket("/bossrush/coop/{room}/{player}")
    async def coop_socket(websocket: WebSocket, room: str, player: str):
        await websocket.accept()
        code, pid = _rooms.normalize_room(room), player
        if await _rooms.reject_if_connecting_too_fast(websocket):
            return
        writer = _open_outbox(websocket)
        throttle = _rooms.MessageThrottle(COOP_MESSAGES_PER_MIN)
        # SEAT IDENTITY IS BOUND BEFORE ANYTHING ELSE: `player` is the client's own
        # word, so until create/join proves the seat this socket is not in the room.
        authed = False
        try:
            while True:
                raw = await websocket.receive_text()
                if not throttle.allow():
                    await websocket.close(code=1008)
                    return
                try:
                    msg = json.loads(raw)
                except Exception:
                    msg = None
                if not isinstance(msg, dict):
                    await _send(websocket, {"type": "error", "message": "bad message"})
                    continue
                action = msg.get("action")
                if action in ("create", "join") and not authed:
                    if action == "create" and await _rooms.reject_room_create(websocket):
                        continue
                    authed = await seat(websocket, code, pid, msg, create=action == "create") or authed
                elif not authed:
                    await _send(websocket, {"type": "error", "message": "not seated in this room"})
                elif action in ("in", "need_input"):
                    await relay(websocket, code, pid, msg)
                elif action == "ping":
                    await _send(websocket, {"type": "pong", "t": msg.get("t")})
                else:
                    await act(websocket, code, pid, action, msg)
        except WebSocketDisconnect:
            pass
        finally:
            await release(code, pid, websocket)
            _close_outbox(websocket)
            try:
                await asyncio.wait_for(writer, timeout=1)   # flush what was queued, briefly
            except Exception:
                writer.cancel()

    async def seat(ws, code, pid, msg, create) -> bool:
        protocol = msg.get("protocol")
        if protocol not in (LEGACY_PROTOCOL, PROTOCOL):
            await _send(ws, {"type": "closed", "message": "Refresh Boss Rush to join this co-op room."})
            return False
        session = msg.get("session_token")
        user = await asyncio.to_thread(user_by_session, session) if isinstance(session, str) and session else None
        if session and user is None:
            await _send(ws, {"type": "error", "message": "Your session expired. Sign in again."})
            return False
        if user and str(user["id"]) != pid:
            await _send(ws, {"type": "error", "message": "That seat is not yours."})
            return False
        name = (user["name"] if user else str(msg.get("name") or "Guest").strip()[:16]) or "Guest"
        build = str(msg.get("build") or "")[:64]
        async with COOP_LOCK:
            room = COOP_ROOMS.get(code)
            if create:
                if room is not None:
                    await _send(ws, {"type": "error", "message": "That room already exists."})
                    return False
                room = COOP_ROOMS[code] = {
                    "code": code, "protocol": protocol, "seats": [pid] + [None] * (MAX_SEATS - 1 if protocol == PROTOCOL else 1),
                    "names": {}, "users": {}, "chars": {}, "builds": {},
                    "rtt": {}, "meta": {}, "sockets": {}, "set_id": "rift-trio", "first": None, "run": None,
                    "created": time.time(),
                }
            elif room is None:
                await _send(ws, {"type": "error", "message": "This co-op room is closed. Ask for a new link."})
                return False
            elif protocol != room["protocol"]:
                await _send(ws, {"type": "closed", "message": "Use the same version of Boss Rush as the host."})
                return False
            if pid in room["seats"]:
                # Back in a seat you hold: proved by its token or by your session.
                if not create and not _rooms.seat_proof_matches(room, pid, room_token=msg.get("token"),
                                                                 session_uid=str(user["id"]) if user else None):
                    await _send(ws, {"type": "error", "message": SEAT_HELD})
                    return False
            elif room.get("run") and not room["run"].get("over"):
                await _send(ws, {"type": "error", "message": "The room is in a fight. Try again after the run."})
                return False
            elif None in room["seats"]:
                room["seats"][room["seats"].index(None)] = pid
            else:
                await _send(ws, {"type": "error", "message": "This room is full."})
                return False
            meta = room["meta"].setdefault(pid, {"token": _rooms.gen_room_token()})
            old = room["sockets"].get(pid)
            room["sockets"][pid] = ws
            room["names"][pid], room["users"][pid], room["builds"][pid] = name, user, build
            if old is not None and old is not ws:
                await _send(old, {"type": "closed", "message": "This seat was opened in another tab."})
            run = room.get("run")
            resume = None
            if run and not run.get("over") and pid in _fighters(room, run):
                if _resumable(run, _sim_seat(room, run, pid)):
                    run["away"].pop(pid, None)
                    resume = _resume_text(room, run, pid)
                else:                              # this seat cannot be caught up: start again
                    run["over"] = True
                    await _broadcast(room, {"type": "end", "run_id": run["run_id"], "reason": "rejoined"})
            await _send(ws, {"type": "seat", "seat": room["seats"].index(pid), "token": meta["token"], "protocol": protocol,
                             "resume": resume is not None})
            if resume is not None:
                await _send(ws, resume)
                await _broadcast_others(room, pid, {"type": "back", "run_id": run["run_id"], "seat": _sim_seat(room, run, pid)})
            await _broadcast(room)
        return True

    async def act(ws, code, pid, action, msg) -> None:
        async with COOP_LOCK:
            room = COOP_ROOMS.get(code)
            if room is None or pid not in room["seats"] or room["sockets"].get(pid) is not ws:
                await _send(ws, {"type": "error", "message": "not seated in this room"})
                return
            host = room["seats"][0] == pid
            run = room.get("run")
            live = bool(run and not run.get("over"))
            if action == "pick":
                if live:
                    return
                character = msg.get("character")
                if not isinstance(character, str) or character not in CHARACTERS:
                    await _send(ws, {"type": "error", "message": "Pick one of the characters."})
                    return
                room["chars"][pid] = character
            elif action == "set":
                if not host or live:
                    return
                if isinstance(msg.get("set_id"), str) and len(msg["set_id"]) <= 40:
                    room["set_id"] = msg["set_id"]
                first = msg.get("first")
                room["first"] = first if isinstance(first, str) and len(first) <= 40 else None
            elif action == "rtt":
                value = msg.get("ms")
                if isinstance(value, (int, float)) and 0 < value < 5000:
                    room["rtt"][pid] = float(value)
                return
            elif action == "start":
                # The host starts the first run; after that either player may start the
                # next one (Play again, or holding R mid-fight).
                if not host and not room.get("ran"):
                    await _send(ws, {"type": "error", "message": "The host starts the first run."})
                    return
                if msg.get("run_id") != (run["run_id"] if run else None):
                    return    # a second restart click for the previous run
                opened = await open_run(room)
                if isinstance(opened, str):
                    await _send(ws, {"type": "error", "message": opened})
                    return
                room["run"], room["ran"] = {**opened, "public": opened, "stage": 0, "ready": set(), "finishes": {},
                                            "log": {}, "bytes": 0, "away": {}}, True
                await _broadcast(room, {"type": "run", "run": opened})
            elif action == "ready":
                if not live or msg.get("run_id") != run["run_id"] or msg.get("stage") != run["stage"]:
                    return
                if pid not in run["ready"]:
                    run["ready"].add(pid)
                    if len(run["ready"]) == len(run["slots"]):
                        await _broadcast(room, {"type": "ready", "run_id": run["run_id"], "stage": run["stage"]})
                return
            elif action == "finish":
                if not live or msg.get("run_id") != run["run_id"] or msg.get("stage") != run["stage"] or len(run["ready"]) != len(run["slots"]):
                    return
                reason, tick, stamp = msg.get("reason"), msg.get("tick"), msg.get("hash")
                last = run["stage"] == len(run["stages"]) - 1
                if reason not in ("dead", "won" if last else "advance") or type(tick) is not int or tick <= 0 or not _is_hash(stamp):
                    return
                if pid in run["finishes"]:
                    return
                finish = (reason, tick, stamp)
                run["finishes"][pid] = finish
                if len(run["finishes"]) == len(run["slots"]):
                    if any(other != finish for other in run["finishes"].values()):
                        run["over"] = True
                        await _broadcast(room, {"type": "end", "run_id": run["run_id"], "reason": "desync"})
                        await _broadcast(room)
                        return
                    run["outcome"] = reason
                    run["over"] = reason != "advance"
                    await _broadcast(room, {"type": "settled", "run_id": run["run_id"], "stage": run["stage"], "reason": reason})
                    await _broadcast(room)
                return
            elif action == "stage":
                if not host or not live or msg.get("run_id") != run["run_id"] or run.get("outcome") != "advance":
                    return
                stage = msg.get("stage")
                if type(stage) is not int or stage != run["stage"] + 1 or stage >= len(run["stages"]):
                    return
                run.update(stage=stage, ready=set(), finishes={}, outcome=None)
                await _broadcast(room, {"type": "stage", "run_id": run["run_id"], "stage": stage})
                return
            elif action == "result":
                elapsed = msg.get("elapsed_ms")
                if host and run and msg.get("run_id") == run["run_id"] and run.get("outcome") == "won" and type(elapsed) is int and elapsed > 0:
                    await _broadcast(room, {"type": "result", "run_id": run["run_id"], "elapsed_ms": elapsed})
                return
            elif action == "save_delayed":
                if (host and run and msg.get("run_id") == run["run_id"] and msg.get("stage") == run["stage"]
                        and run.get("outcome") in ("advance", "won")):
                    await _broadcast(room, {"type": "save_delayed", "run_id": run["run_id"], "stage": run["stage"]})
                return
            elif action == "end":
                if not live or msg.get("run_id") != run["run_id"]:
                    return
                run["over"] = True
                reason = msg.get("reason") if msg.get("reason") in ("desync", "timeout") else "ended"
                await _broadcast(room, {"type": "end", "run_id": run["run_id"], "reason": reason, "by": room["seats"].index(pid)})
            elif action == "hidden":
                # A player switched away from the tab: the others stop counting down
                # their stall limit, and say why the fight is waiting.
                if live and msg.get("run_id") == run["run_id"] and pid in _fighters(room, run):
                    await _broadcast_others(room, pid, {"type": "hidden", "run_id": run["run_id"],
                                                        "seat": _sim_seat(room, run, pid), "hidden": bool(msg.get("hidden"))})
                return
            elif action == "remove_offline":
                slot = msg.get("slot", 1)
                guest = room["seats"][slot] if type(slot) is int and 0 < slot < len(room["seats"]) else None
                if host and not live and guest and guest not in room["sockets"]:
                    await leave(room, guest)
                return
            elif action == "leave":
                await leave(room, pid)
                return
            else:
                await _send(ws, {"type": "error", "message": "unknown action"})
                return
            await _broadcast(room)

    async def relay(sender, code, pid, msg) -> None:
        """One seat's controls for a few ticks, to the other seat. Only the shape is
        checked here: the fight itself is the browsers'."""
        room = COOP_ROOMS.get(code)
        run = room and room.get("run")
        if (not run or run.get("over") or msg.get("run_id") != run["run_id"]
                or room["sockets"].get(pid) is not sender or len(run["ready"]) != len(run["slots"])):
            return
        stage, start = msg.get("stage"), msg.get("from")
        if not (type(stage) is int and stage == run["stage"] and type(start) is int and 0 <= start <= 2**31 - 1):
            return
        out = {"type": msg["action"], "run_id": run["run_id"], "stage": stage, "from": start}
        slots = run["slots"]
        seat = slots.index(room["seats"].index(pid))
        if len(slots) > 2:
            out["seat"] = seat
        if msg["action"] == "in":
            rows = msg.get("rows")
            if not (isinstance(rows, list) and 0 < len(rows) <= ROWS_PER_MESSAGE
                    and all(_valid_row(r, run["analog_movement"]) for r in rows)):
                return
            out["rows"] = rows
            _remember(run, stage, seat, start, rows, broadcast=msg.get("to") is None)
            fp = msg.get("fp")
            if isinstance(fp, list) and len(fp) == 2 and type(fp[0]) is int and fp[0] > 0 and _is_hash(fp[1]):
                out["fp"] = fp
        to = msg.get("to")
        if to is None and msg["action"] == "need_input" and len(slots) != 2:
            return
        if to is not None and (type(to) is not int or not 0 <= to < len(slots) or to == seat):
            return
        peers = (room["sockets"].get(room["seats"][slot]) for i, slot in enumerate(slots)
                 if i != seat and (to is None or i == to))
        await asyncio.gather(*(_send(ws, out) for ws in peers if ws is not None))

    async def leave(room, pid) -> None:
        """A player leaves for good: the guest's seat opens again; the host closes the room."""
        run = room.get("run")
        if run and not run.get("over"):
            run["over"] = True
            await _broadcast(room, {"type": "end", "run_id": run["run_id"], "reason": "left"})
        if room["seats"][0] == pid:
            for other, ws in list(room["sockets"].items()):
                if other != pid:
                    await _send(ws, {"type": "closed", "message": "The host closed the room."})
            COOP_ROOMS.pop(room["code"], None)
            room["sockets"].clear()
            return
        room["seats"][room["seats"].index(pid)] = None
        for key in ("names", "users", "chars", "builds", "rtt", "meta", "sockets"):
            room[key].pop(pid, None)
        await _broadcast(room)

    async def release(code, pid, ws) -> None:
        async with COOP_LOCK:
            room = COOP_ROOMS.get(code)
            if room is None or room["sockets"].get(pid) is not ws:   # a newer socket holds the seat
                return
            del room["sockets"][pid]
            run = room.get("run")
            if run and not run.get("over"):
                seat_index = _sim_seat(room, run, pid)
                if seat_index is not None and _resumable(run, seat_index):
                    # Away: the fight waits GRACE_S for this seat to come back.
                    run["away"][pid] = time.time() + GRACE_S
                    await _broadcast(room, {"type": "away", "run_id": run["run_id"], "seat": seat_index, "grace": GRACE_S})
                    asyncio.ensure_future(expire(code, pid, run["run_id"]))
                    await _broadcast(room)
                    return
                run["over"] = True
                await _broadcast(room, {"type": "end", "run_id": run["run_id"], "reason": "left"})
            if not room["sockets"]:
                COOP_ROOMS.pop(code, None)
                return
            await _broadcast(room)

    async def expire(code, pid, run_id) -> None:
        """A dropped seat that did not come back in time ends the fight for everyone."""
        await asyncio.sleep(GRACE_S)
        async with COOP_LOCK:
            room = COOP_ROOMS.get(code)
            run = room and room.get("run")
            if not run or run["run_id"] != run_id or run.get("over") or pid not in run["away"]:
                return
            if run["away"][pid] > time.time() + 0.5:   # dropped again since: a later timer owns it
                return
            run["over"] = True
            await _broadcast(room, {"type": "end", "run_id": run_id, "reason": "left"})
            if not room["sockets"]:
                COOP_ROOMS.pop(code, None)
                return
            await _broadcast(room)


def _is_hash(value):
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def _valid_row(row, analog):
    return (isinstance(row, list) and len(row) == ROW_LEN
            and all(type(v) in (int, float) and -1_000_000 <= v <= 1_000_000 for v in row)
            and all(-1 <= v <= 1 if analog else v in (-1, 0, 1) for v in row[:2])
            and all(v in (0, 1) for v in row[4:]))


async def _broadcast_others(room: dict, pid, payload) -> None:
    for other, ws in list(room["sockets"].items()):
        if other != pid:
            await _send(ws, payload)


def _fighters(room: dict, run: dict) -> list:
    """The pids in this run's fight, in simulation order."""
    return [room["seats"][slot] for slot in run["slots"]]


def _sim_seat(room: dict, run: dict, pid):
    try:
        return run["slots"].index(room["seats"].index(pid))
    except ValueError:
        return None


def _remember(run: dict, stage: int, seat: int, start: int, rows: list, broadcast: bool) -> None:
    """Keep the rows a seat sent, contiguous from tick 0, for a browser that rejoins.
    `relayed` is the furthest tick every live peer was sent: past `next` means a gap."""
    log = run.get("log")
    if log is None:
        return
    entry = log.setdefault(stage, {}).setdefault(seat, {"next": 0, "chunks": [], "relayed": 0})
    end = start + len(rows)
    if broadcast:
        entry["relayed"] = max(entry["relayed"], end)
    if start <= entry["next"] < end:
        text = json.dumps(rows[entry["next"] - start:], separators=(",", ":"))
        entry["chunks"].append((entry["next"], text))
        entry["next"] = end
        run["bytes"] += len(text)
        if run["bytes"] > RESUME_MAX_BYTES:
            run["log"] = None                    # too long a fight to keep: a drop ends it


def _resumable(run: dict, seat) -> bool:
    log = run.get("log")
    if seat is None or log is None:
        return False
    entry = log.get(run["stage"], {}).get(seat)
    return entry is None or entry["relayed"] <= entry["next"]


def _resume_text(room: dict, run: dict, pid) -> str:
    """The `resume` message, pre-encoded: the run, where it stands, and every stored row
    as [stage, seat, from, rows]."""
    head = json.dumps({
        "type": "resume", "run": run["public"], "stage": run["stage"],
        "started": len(run["ready"]) == len(run["slots"]), "outcome": run.get("outcome"),
        "finished": pid in run["finishes"],
    })
    chunks = ",".join(f"[{stage},{seat},{start},{text}]"
                      for stage, seats in sorted(run["log"].items())
                      for seat, entry in sorted(seats.items())
                      for start, text in entry["chunks"])
    return head[:-1] + ',"chunks":[' + chunks + "]}"
