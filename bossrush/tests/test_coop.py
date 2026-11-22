"""Boss Rush co-op rooms: seats bound to their proof, one run for the pair, the input
relay, and a separate co-op leaderboard."""
import asyncio
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocketDisconnect

from bossrush import api, coop
from core import rooms as _rooms
from core.db import _Conn

_CLOSE = object()


class Session:
    """One client socket, driven from the test thread: the room's real handler runs on
    the fixture's event loop (one loop for every socket, as in production). No HTTP
    client involved — CI installs no httpx, which starlette's TestClient needs."""

    def __init__(self, loop, endpoint, path):
        _, _, _, room, player = path.split("/")
        self.loop, self.inbox, self.outbox = loop, None, None
        ready = threading.Event()

        def make():
            self.inbox, self.outbox = asyncio.Queue(), asyncio.Queue()
            ready.set()
        loop.call_soon_threadsafe(make)
        ready.wait(5)
        session = self

        class FakeWebSocket:
            client = SimpleNamespace(host="127.0.0.1")
            headers = {}
            path_params = {"room": room, "player": player}
            async def accept(self): pass
            async def send_text(self, text): session.outbox.put_nowait(text)
            async def receive_text(self):
                item = await session.inbox.get()
                if item is _CLOSE:
                    raise WebSocketDisconnect()
                return item
            async def close(self, code=1000): session.outbox.put_nowait(json.dumps({"type": "closed-by-server"}))

        self.task = asyncio.run_coroutine_threadsafe(endpoint(FakeWebSocket(), room, player), loop)

    def send_json(self, obj):
        if obj.get("action") in ("create", "join"):
            obj = {"protocol": coop.PROTOCOL, **obj}
        self.loop.call_soon_threadsafe(self.inbox.put_nowait, json.dumps(obj))

    def receive_json(self):
        return json.loads(asyncio.run_coroutine_threadsafe(asyncio.wait_for(self.outbox.get(), 5), self.loop).result(6))

    def close(self):
        if not self.task.done():
            self.loop.call_soon_threadsafe(self.inbox.put_nowait, _CLOSE)
            self.task.result(5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_starts", api.SlidingWindowLimiter(30, 60))
    monkeypatch.setattr(api, "_is_owner", lambda conn, user: False)
    monkeypatch.setattr(_rooms, "_ws_connect_limiter", _rooms.SlidingWindowLimiter(max_hits=1000, window_seconds=60))
    coop.COOP_ROOMS.clear()
    users = {"wren": {"id": "u7", "name": "Wren"}}
    app = FastAPI()
    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(tmp_path / "runs.db")),
                        lambda token: users.get(token), lambda: None)
    endpoints = {route.path: route.endpoint for route in app.routes if getattr(route, "path", "").startswith("/bossrush")}
    socket = endpoints["/bossrush/coop/{room}/{player}"]
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    opened = []

    def connect(path):
        return Session(loop, socket, path)

    def open_(path):
        opened.append(connect(path))
        return opened[-1]
    try:
        yield SimpleNamespace(endpoints=endpoints, db=tmp_path / "runs.db", open=open_, connect=connect)
    finally:
        for session in opened:
            session.close()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()
        coop.COOP_ROOMS.clear()


def recv(ws, kind):
    """The next message of `kind`, skipping room broadcasts and the like."""
    for _ in range(20):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
        assert msg["type"] != "error" or kind == "error", msg
    raise AssertionError(f"no {kind}")


def seated(server, code="ABCDEF"):
    """A host and a guest at one table, both picked. Returns the two sockets (open)."""
    host = server.open(f"/bossrush/coop/{code}/host-1")
    host.send_json({"action": "create", "name": "Ash", "build": "b1"})
    assert recv(host, "seat")["seat"] == 0
    guest = server.open(f"/bossrush/coop/{code}/guest-2")
    guest.send_json({"action": "join", "name": "Birch", "build": "b1"})
    seat = recv(guest, "seat")
    assert seat["seat"] == 1 and seat["token"]
    host.send_json({"action": "pick", "character": "ninja"})
    guest.send_json({"action": "pick", "character": "paladin"})
    for _ in range(20):          # the two picks travel on two sockets: wait until the host sees both
        room = recv(host, "room")["room"]
        if all(seat and seat["character"] for seat in room["seats"]):
            break
    return host, guest


def ready(host, guest, run, stage=0):
    for seat in (host, guest):
        seat.send_json({"action": "ready", "run_id": run["run_id"], "stage": stage})
    for seat in (host, guest):
        assert recv(seat, "ready")["stage"] == stage


def finish(seat, run, stage, reason, stamp=123):
    seat.send_json({"action": "finish", "run_id": run["run_id"], "stage": stage,
                    "reason": reason, "tick": 60, "hash": stamp})


def test_the_input_delay_covers_the_round_trip():
    assert coop.input_delay([None, None]) == coop.input_delay([150, 150])
    assert coop.input_delay([10, 10]) == 6, "never under six ticks"
    assert coop.input_delay([4000, 4000]) == 30, "never over half a second"
    assert coop.input_delay([100, 140]) > coop.input_delay([20, 20])


def test_two_players_start_one_run_and_their_controls_reach_each_other(server):
    host, guest = seated(server)
    guest.send_json({"action": "start"})
    assert "host starts" in recv(guest, "error")["message"]
    host.send_json({"action": "start"})
    a, b = recv(host, "run")["run"], recv(guest, "run")["run"]
    assert a == b, "both browsers get the same run: the same arenas, order and delay"
    assert a["characters"] == ["ninja", "paladin"] and a["names"] == ["Ash", "Birch"]
    assert len(a["stages"]) == 3 and 6 <= a["delay"] <= 30
    row = [1, 0, 0.5, -0.25, 1, 0, 0, 0]
    packet = {"action": "in", "run_id": a["run_id"], "stage": 0, "from": a["delay"], "rows": [row]}
    host.send_json(packet)
    host.send_json({"action": "ping"})
    recv(host, "pong")  # early input was processed before either seat readied
    ready(host, guest, a)
    finish(host, a, 0, "advance")
    host.send_json({**packet, "rows": [row, row], "fp": [60, 123]})
    assert recv(guest, "in") == {**{k: v for k, v in packet.items() if k != "action"},
                                "type": "in", "rows": [row, row], "fp": [60, 123]}
    guest.send_json({**packet, "run_id": "someone-elses"})
    guest.send_json({**packet, "rows": [[1, 2]]})
    guest.send_json({**packet, "rows": [[1, 0, float("nan"), 1, 0, 0, 0, 0]]})
    guest.send_json({**packet, "stage": 1})
    guest.send_json({**packet, "from": a["delay"] + 1})
    assert recv(host, "in")["from"] == a["delay"] + 1
    finish(guest, a, 0, "advance")
    assert recv(guest, "settled")["reason"] == recv(host, "settled")["reason"] == "advance"
    # The host moves both on to the next boss; then the guest starts the next run.
    host.send_json({"action": "stage", "run_id": a["run_id"], "stage": 1})
    assert recv(guest, "stage")["stage"] == 1 and recv(host, "stage")["stage"] == 1
    guest.send_json({"action": "start", "run_id": a["run_id"]})
    again = recv(host, "run")["run"]
    assert again["run_id"] != a["run_id"] and recv(guest, "run")["run"] == again
    host.send_json({"action": "start", "run_id": a["run_id"]})
    host.send_json({"action": "ping"})
    while (message := host.receive_json())["type"] != "pong":
        assert message["type"] != "run"
    # The run row is a co-op one with both seats in it.
    with sqlite3.connect(server.db) as conn:
        row = conn.execute("SELECT mode, player_name, character, player_name2, character2, player_id, player_id2 "
                           "FROM boss_rush_runs WHERE run_id=?", (a["run_id"],)).fetchone()
    assert row == ("coop", "Ash", "ninja", "Birch", "paladin", "g:host-1", "g:guest-2")


def test_a_seat_is_only_reentered_with_its_proof(server):
    host, guest = seated(server, "SEATS1")
    token = coop.COOP_ROOMS["SEATS1"]["meta"]["guest-2"]["token"]
    with server.connect("/bossrush/coop/SEATS1/guest-2") as thief:
        thief.send_json({"action": "join", "name": "Thief"})
        assert recv(thief, "error")["message"] == "That seat is taken."
        thief.send_json({"action": "in", "run_id": "x", "stage": 0, "from": 0, "rows": []})
        assert recv(thief, "error")["message"] == "not seated in this room"
    with server.connect("/bossrush/coop/SEATS1/third-3") as third:
        third.send_json({"action": "join", "name": "Cedar"})
        assert recv(third, "error")["message"] == "This room is full."
    with server.connect("/bossrush/coop/SEATS1/guest-2") as back:
        back.send_json({"action": "join", "name": "Birch", "token": token, "build": "b1"})
        assert recv(back, "seat")["seat"] == 1
    # An account's seat is its id, and its session proves it.
    with server.connect("/bossrush/coop/ACCT01/someone-else") as liar:
        liar.send_json({"action": "create", "session_token": "wren"})
        assert recv(liar, "error")["message"] == "That seat is not yours."


def test_a_run_needs_both_picks_one_build_and_ends_for_both_when_one_leaves(server):
    host = server.open("/bossrush/coop/LEAVE1/host-1")
    host.send_json({"action": "create", "name": "Ash", "build": "b1"})
    recv(host, "seat")
    host.send_json({"action": "start"})
    assert recv(host, "error")["message"] == "Waiting for a second player."
    leaving = server.connect("/bossrush/coop/LEAVE1/guest-2")
    guest = leaving.__enter__()
    guest.send_json({"action": "join", "name": "Birch", "build": "b2"})
    recv(guest, "seat")
    host.send_json({"action": "pick", "character": "ranger"})
    host.send_json({"action": "start"})
    assert "pick a character" in recv(host, "error")["message"]
    guest.send_json({"action": "pick", "character": "simon"})
    host.send_json({"action": "start"})
    assert "different versions" in recv(host, "error")["message"]
    coop.COOP_ROOMS["LEAVE1"]["builds"]["guest-2"] = "b1"
    host.send_json({"action": "start"})
    run = recv(host, "run")["run"]
    recv(guest, "run")
    leaving.__exit__(None, None, None)        # the guest's tab closes mid-fight
    end = recv(host, "end")
    assert end["run_id"] == run["run_id"] and end["reason"] == "left"
    host.send_json({"action": "remove_offline"})
    new = server.open("/bossrush/coop/LEAVE1/new-guest")
    # Wait for the host's action to complete before trying the open seat.
    while recv(host, "room")["room"]["seats"][1] is not None:
        pass
    new.send_json({"action": "join", "name": "Cedar", "build": "b1"})
    assert recv(new, "seat")["seat"] == 1


def test_disagreeing_outcomes_end_the_run_for_both(server):
    host, guest = seated(server)
    host.send_json({"action": "start"})
    run = recv(host, "run")["run"]
    recv(guest, "run")
    ready(host, guest, run)
    finish(host, run, 0, "advance")
    finish(guest, run, 0, "advance", stamp=456)
    assert recv(host, "end")["reason"] == recv(guest, "end")["reason"] == "desync"


def test_outdated_client_gets_refresh_prompt(server):
    host = server.open("/bossrush/coop/OLDAPP/host-1")
    host.send_json({"action": "create", "protocol": 1})
    assert "Refresh" in recv(host, "closed")["message"]
    assert "OLDAPP" not in coop.COOP_ROOMS


def test_the_coop_board_is_its_own(server):
    clear = server.endpoints["/bossrush/runs/{run_id}/clears/{stage}"]
    enter = server.endpoints["/bossrush/runs/{run_id}/entries/{stage}"]
    board = server.endpoints["/bossrush/leaderboard"]
    host, guest = seated(server, "BOARD1")
    host.send_json({"action": "start"})
    run = recv(host, "run")["run"]
    for stage in (1, 2, 3):
        enter(run["run_id"], stage)
        result = clear(run["run_id"], stage, taken=5)
    assert result["film_wanted"], "the co-op board's five best keep films too"
    solo = board(set_id="rift-trio", token=None)
    assert solo == {"entries": []}, "a co-op time is not on the solo board"
    entries = board(set_id="rift-trio", mode="coop", token=None)["entries"]
    assert [(e["name"], e["character"], e["name2"], e["character2"]) for e in entries] == [("Ash", "ninja", "Birch", "paladin")]
    assert board(set_id="rift-trio", mode="coop", character="paladin", token=None)["entries"], "either player's character"
    assert not board(set_id="rift-trio", mode="coop", character="ranger", token=None)["entries"]
    mine = board(set_id="rift-trio", mode="coop", mine=True, guest="guest-2", token=None)["entries"]
    assert len(mine) == 1, "My best finds a co-op run from either seat"
