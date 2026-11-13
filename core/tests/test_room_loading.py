"""Room LOADING is off the event loop, shared, and never overwrites a live room.

The first touch of a room after a restart reads its row from the database. That
read used to run synchronously on the event loop under the game's ROOM_LOCK (on
Turso a network round trip, so one cold room paused every socket on the site).
`core.rooms.locked_room` now reads on a thread with the lock RELEASED, and the two
ways that goes wrong are what these tests pin:

  * the race: a read is in flight, the room goes live meanwhile (a create, or a
    second touch) and is played on, then the stale copy lands. The RE-CHECK under
    the lock is what keeps the live room. Verified non-vacuous: with the re-check
    removed from `_load_once`, `test_a_room_that_went_live_during_the_read_is_kept`
    goes red (the live move is overwritten by the DB copy).
  * the stall: a slow read of room A must not hold the lock, so a handler for an
    already-live room B in the same game proceeds while A is still loading.
    On the old shape (sync read under the lock, on the loop) B could not even
    START until A's read returned.
"""
import asyncio
import threading
import time

from core import rooms


def _reader(rows, gate=None, calls=None):
    """A `read(room_id)` over `rows`, optionally blocking on `gate` (a
    threading.Event), counting calls. It runs on a worker thread."""
    def read(rid):
        if calls is not None:
            calls.append(rid)
        if gate is not None:
            assert gate.wait(10), "test gate never opened"
        row = rows.get(rid)
        return None if row is None else {**row, "sockets": {}}
    return read


def test_a_cold_room_is_loaded_and_held_under_the_lock():
    async def go():
        store, lock = {}, asyncio.Lock()
        async with rooms.locked_room(store, lock, "R", _reader({"R": {"v": 1}})) as room:
            assert lock.locked()
            assert room is store["R"] and room["v"] == 1
        assert not lock.locked()
        async with rooms.locked_room(store, lock, "NOPE", _reader({})) as room:
            assert room is None
        assert "NOPE" not in store
    asyncio.run(go())


def test_a_live_room_is_not_read_again():
    async def go():
        calls = []
        store, lock = {"R": {"live": True}}, asyncio.Lock()
        async with rooms.locked_room(store, lock, "R", _reader({"R": {}}, calls=calls)) as room:
            assert room == {"live": True}
        assert calls == []
    asyncio.run(go())


def test_two_concurrent_first_touches_share_one_read():
    async def go():
        gate, calls = threading.Event(), []
        store, lock = {}, asyncio.Lock()
        read = _reader({"R": {"v": 1}}, gate=gate, calls=calls)
        seen = []

        async def touch():
            async with rooms.locked_room(store, lock, "R", read) as room:
                seen.append(room)

        tasks = [asyncio.create_task(touch()) for _ in range(5)]
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.gather(*tasks)
        assert calls == ["R"], f"expected one shared read, got {calls}"
        assert len(seen) == 5 and all(r is store["R"] for r in seen)
        assert rooms._LOADS == {}, "a finished load must not stay registered"
    asyncio.run(go())


def test_a_room_that_went_live_during_the_read_is_kept():
    """THE RACE. The DB row says v=1. While that read is in flight, the room is
    created/loaded by another path and a move makes it v=2. When the stale read
    lands it must be discarded, not installed over the live room."""
    async def go():
        gate = threading.Event()
        store, lock = {}, asyncio.Lock()
        loader = asyncio.create_task(rooms.load_room(store, lock, "R", _reader({"R": {"v": 1}}, gate=gate)))
        await asyncio.sleep(0.05)               # the read is now parked on its thread
        async with lock:                        # e.g. a create, which installs directly
            live = store["R"] = {"v": 1, "sockets": {}}
        live["v"] = 2                           # ...and a move is played on it
        gate.set()
        assert await loader is True
        assert store["R"] is live and store["R"]["v"] == 2, (
            "a stale DB copy overwrote a live room")
    asyncio.run(go())


def test_a_room_dropped_between_load_and_lock_is_reloaded():
    """The read happens before the lock is taken, so another handler can drop the
    room from memory in between (Spender drops an empty room). The old code
    reloaded under the lock; this must too, not answer 'no such room'."""
    async def go():
        calls = []
        store = {}

        class DropOnce(asyncio.Lock):
            """Drops the room the first time anyone takes the lock while it is
            live -- i.e. in the gap after the load installed it and before
            locked_room's own acquire."""
            armed = True

            async def acquire(self):
                if self.armed and "R" in store:
                    self.armed = False
                    store.pop("R")
                return await super().acquire()

        lock = DropOnce()
        async with rooms.locked_room(store, lock, "R", _reader({"R": {"v": 1}}, calls=calls)) as room:
            assert room is not None and room is store["R"], "the dropped room was not reloaded"
        assert not lock.armed, "the drop never happened, so this proved nothing"
        assert calls == ["R", "R"]
    asyncio.run(go())


def test_a_cancelled_waiter_does_not_cancel_the_shared_load():
    async def go():
        gate = threading.Event()
        store, lock = {}, asyncio.Lock()
        read = _reader({"R": {"v": 1}}, gate=gate)
        first = asyncio.create_task(rooms.load_room(store, lock, "R", read))
        second = asyncio.create_task(rooms.load_room(store, lock, "R", read))
        await asyncio.sleep(0.05)
        first.cancel()                          # its socket closed mid-load
        gate.set()
        assert await second is True
        assert store["R"]["v"] == 1
    asyncio.run(go())


def test_a_stalled_load_of_one_room_does_not_block_a_live_room():
    """THE STALL. Room A's read hangs (a slow Turso call). A handler for room B,
    already live in the same game, must take the lock and finish meanwhile."""
    async def go():
        gate = threading.Event()
        store, lock = {"B": {"v": 0, "sockets": {}}}, asyncio.Lock()
        read = _reader({"A": {"v": 1}}, gate=gate)

        async def handler(rid):
            async with rooms.locked_room(store, lock, rid, read) as room:
                room["v"] += 1
                return time.monotonic()

        a = asyncio.create_task(handler("A"))
        await asyncio.sleep(0.05)               # A is now parked in its read
        b_done = await asyncio.wait_for(handler("B"), timeout=2)
        assert not a.done(), "A should still be loading"
        released = time.monotonic()
        gate.set()
        a_done = await asyncio.wait_for(a, timeout=5)
        assert b_done < released <= a_done
        assert store["A"]["v"] == 2 and store["B"]["v"] == 1
    asyncio.run(go())
