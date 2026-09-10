"""The bot scheduler must never lose a wake-up.

`_bot_running` makes every other `_schedule_bot_turn` call a no-op, so the moment
the running scheduler decides to stop is the moment a concurrent wake-up can go
missing.  It used to decide that from a reading taken BEFORE an await — and the
human seat is live inside every one of those awaits — which left rooms sitting on
"Resolving…" with the bot owing a move and nothing driving it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from games.orbit import engine
from games.orbit import main as m


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    yield
    loop.close()


def _room(room_id="sched-room", seed=7):
    game = engine.new_game(["human", "bot"], names={"human": "Human", "bot": "Bot"},
                           seed=seed)
    # The bot plays turn 1, so the hand-off out of the mulligan is its wake-up.
    game["order"] = ["bot", "human"]
    room = {
        "players": {"human": "Human", "bot": "Bot"}, "sockets": {}, "status": "playing",
        "host": "human", "game": game, "meta": {}, "vs_ai": True, "ai_player": "bot",
        "ai_difficulty": "easy", "seat_histories": m._new_live_histories(game),
        "ai_memory": {}, "ai_budget_remaining_ms": None, "ai_turn_started_at": None,
        "ai_decisions_this_turn": 0, "client_ai": False,
        "_ai_search": None, "_ai_pending_move": None, "_ai_pending_sent_at": None,
    }
    m.ROOMS[room_id] = room
    return room


def _played_a_card(game):
    """A card play is the only log entry that carries an `action`."""
    return any(isinstance(entry, dict) and entry.get("action") for entry in game["log"])


def test_a_human_move_inside_the_schedulers_own_await_is_not_lost(monkeypatch):
    """Both seats mulligan at once, so this interleaving is the OPENING of a
    vs-bot game, not a corner case.

    The scheduler applies the bot's mulligan, reads "the bot owes nothing more"
    (the human has not replaced yet), and then awaits its broadcast.  The human's
    mulligan lands inside that await on its own socket task, finishes the phase
    and hands turn 1 to the bot — and the wake-up it schedules finds
    `_bot_running` still set and returns.  The scheduler then exits on its stale
    reading and the room is left with "Turn 1 — Bot to play." and no bot.
    """

    room = _room()
    parked = asyncio.Event()
    released = asyncio.Event()
    state = {"parked": False}

    async def broadcast(room_id, mtype="room_update"):
        # Park in the one broadcast the scheduler makes after the bot's mulligan,
        # which is where a real socket write yields to the event loop anyway.
        if not state["parked"] and room["game"]["phase"] == "mulligan":
            state["parked"] = True
            parked.set()
            await released.wait()

    monkeypatch.setattr(m, "broadcast_state", broadcast)

    async def human():
        await parked.wait()
        await m._handle_move(None, "sched-room", "human",
                             {"move": {"action": "mulligan", "card_ids": []}})
        # The handler's wake-up is a task: let it actually RUN while the
        # scheduler is still parked, exactly as a separate socket task would.
        for _ in range(5):
            await asyncio.sleep(0)
        released.set()

    async def drive():
        asyncio.ensure_future(m._schedule_bot_turn("sched-room"))
        asyncio.ensure_future(human())
        for _ in range(400):
            await asyncio.sleep(0.01)
            if _played_a_card(room["game"]):
                return True
        return False

    assert asyncio.get_event_loop().run_until_complete(drive()), (
        "the bot never took turn 1: phase=%s turn_pid=%s pending_pid=%s "
        "bot_legal=%d _bot_running=%s" % (
            room["game"]["phase"], room["game"]["turn_pid"], room["game"]["pending_pid"],
            len(engine.legal_moves(room["game"], "bot")), room.get("_bot_running")))
    assert not room.get("_bot_running")


def test_the_scheduler_re_drives_only_while_the_position_keeps_moving(monkeypatch):
    """The re-check must not become a spin.

    A pass that cannot act — the bot search raised, or the engine rejected its
    move — leaves the position untouched, and re-driving it forever would peg the
    event loop on an unplayable room.  One retry, then stop.
    """

    room = _room()
    engine.apply_move(room["game"], "human", {"action": "mulligan", "card_ids": []})
    engine.apply_move(room["game"], "bot", {"action": "mulligan", "card_ids": []})
    assert m._bot_should_act(room), "the bot must owe a move for the guard to matter"

    passes = {"n": 0}

    async def dead_pass(room_id):
        passes["n"] += 1

    monkeypatch.setattr(m, "_drive_bot_turn", dead_pass)
    asyncio.get_event_loop().run_until_complete(
        asyncio.wait_for(m._schedule_bot_turn("sched-room"), 5))
    assert passes["n"] == 2, "expected one drive plus exactly one retry"
    assert not room.get("_bot_running")


def test_a_wake_up_arriving_mid_resolution_still_finishes_the_bots_turn(monkeypatch):
    """The same loss, mid-turn instead of at the opening.

    Cards 307 and 402 hand the OPPONENT a choice during the bot's own turn, so a
    bot resolution can genuinely read [bot choice, human choice, bot choice].  The
    scheduler answers the first, stops on the second (not its seat), and awaits its
    broadcast — and the frontend auto-sends a forced single choice the instant it
    arrives, so the human's answer lands inside that await rather than seconds
    later.  The third task is then the bot's again, with the wake-up swallowed.
    """

    room = _room()
    game = room["game"]
    for pid in ("human", "bot"):
        engine.apply_move(game, pid, {"action": "mulligan", "card_ids": []})
    assert game["turn_pid"] == "bot"
    engine._begin_resolution(game, "bot", [{"type": "influence", "amount": 1}], "probe")
    engine._queue_tasks(game, [{"type": "influence", "amount": 1}], "human", front=False)
    engine._queue_tasks(game, [{"type": "influence", "amount": 2}], "bot", front=False)
    assert game["pending_pid"] == "bot" and m._bot_should_act(room)

    parked = asyncio.Event()
    released = asyncio.Event()
    state = {"parked": False}

    async def broadcast(room_id, mtype="room_update"):
        # Park once the queue has reached the human's task, which is where the
        # scheduler reads "not my seat" and gives up for good.
        if not state["parked"] and game.get("pending_pid") == "human":
            state["parked"] = True
            parked.set()
            await released.wait()

    monkeypatch.setattr(m, "broadcast_state", broadcast)

    async def human():
        await parked.wait()
        mine = engine.legal_moves(game, "human")
        await m._handle_move(None, "sched-room", "human", {"move": mine[0]})
        for _ in range(5):
            await asyncio.sleep(0)
        released.set()

    async def drive():
        asyncio.ensure_future(m._schedule_bot_turn("sched-room"))
        asyncio.ensure_future(human())
        for _ in range(400):
            await asyncio.sleep(0.01)
            if game["turn_pid"] != "bot" or engine.is_over(game):
                return True
        return False

    assert asyncio.get_event_loop().run_until_complete(drive()), (
        "the bot never finished its turn: %s"
        % json.dumps({"turn_pid": game["turn_pid"], "pending_pid": game["pending_pid"],
                      "queue": len(game.get("pending", {}).get("queue", [])),
                      "_bot_running": room.get("_bot_running")}))
