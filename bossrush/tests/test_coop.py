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
        self.stalled = False                    # True: a socket that stops reading (sends hang)
        never = asyncio.Event()

        class FakeWebSocket:
            client = SimpleNamespace(host="127.0.0.1")
            headers = {}
            path_params = {"room": room, "player": player}
            async def accept(self): pass
            async def send_text(self, text):
                if session.stalled:
                    await never.wait()
                session.outbox.put_nowait(text)
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

    def receive_json(self, timeout=5):
        return json.loads(asyncio.run_coroutine_threadsafe(asyncio.wait_for(self.outbox.get(), timeout), self.loop).result(timeout + 1))

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
            if not session.stalled:
                session.close()

        async def cancel_rest():                # grace timers, stalled writers
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()
        asyncio.run_coroutine_threadsafe(cancel_rest(), loop).result(5)
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
    host.send_json({"action": "create", "name": "Guest1001", "build": "b1"})
    assert recv(host, "seat")["seat"] == 0
    guest = server.open(f"/bossrush/coop/{code}/guest-2")
    guest.send_json({"action": "join", "name": "Guest1002", "build": "b1"})
    seat = recv(guest, "seat")
    assert seat["seat"] == 1 and seat["token"]
    host.send_json({"action": "pick", "character": "ninja"})
    guest.send_json({"action": "pick", "character": "paladin"})
    for _ in range(20):          # the two picks travel on two sockets: wait until the host sees both
        room = recv(host, "room")["room"]
        if all(seat["character"] for seat in room["seats"] if seat):
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


def test_the_prediction_window_covers_the_round_trip():
    assert coop.prediction_window([None, None]) == coop.prediction_window([150, 150])
    assert coop.prediction_window([10, 10]) == 16
    assert coop.prediction_window([4000, 4000]) == 48
    assert coop.prediction_window([200, 240]) > coop.prediction_window([20, 20])


@pytest.mark.parametrize("set_id,first", [("rift-trio", "ashen"), ("crypt-trio", "orrery-hall")])
def test_two_players_start_one_run_and_their_controls_reach_each_other(server, set_id, first):
    host, guest = seated(server)
    host.send_json({"action": "set", "set_id": set_id, "first": first})
    guest.send_json({"action": "start"})
    assert "host starts" in recv(guest, "error")["message"]
    host.send_json({"action": "start"})
    a, b = recv(host, "run")["run"], recv(guest, "run")["run"]
    assert a == b, "both browsers get the same run: the same arenas, order and delay"
    assert a["characters"] == ["ninja", "paladin"] and a["names"] == ["Guest1001", "Guest1002"]
    assert len(a["stages"]) == 3 and 16 <= a["prediction_window"] <= 48
    assert a["stages"][0]["id"] == first
    row = [1, 0, 0.5, -0.25, 1, 0, 0, 0]
    packet = {"action": "in", "run_id": a["run_id"], "stage": 0, "from": 0, "rows": [row]}
    host.send_json(packet)
    host.send_json({"action": "ping"})
    recv(host, "pong")  # early input was processed before either seat readied
    ready(host, guest, a)
    finish(host, a, 0, "advance")
    host.send_json({**packet, "rows": [row, row], "fp": [60, 123]})
    assert recv(guest, "in") == {**{k: v for k, v in packet.items() if k != "action"},
                                "type": "in", "rows": [row, row], "fp": [60, 123]}
    guest.send_json({"action": "need_input", "run_id": a["run_id"], "stage": 0, "from": 0})
    assert recv(host, "need_input") == {"type": "need_input", "run_id": a["run_id"], "stage": 0, "from": 0}
    guest.send_json({**packet, "run_id": "someone-elses"})
    guest.send_json({**packet, "rows": [[1, 2]]})
    guest.send_json({**packet, "rows": [[1, 0, float("nan"), 1, 0, 0, 0, 0]]})
    guest.send_json({**packet, "stage": 1})
    guest.send_json({**packet, "from": 1})
    assert recv(host, "in")["from"] == 1
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
        row = conn.execute("SELECT set_id, mode, player_name, character, player_name2, character2, player_id, player_id2 "
                           "FROM boss_rush_runs WHERE run_id=?", (a["run_id"],)).fetchone()
    assert row == (set_id, "coop", "Guest1001", "ninja", "Guest1002", "paladin", "g:host-1", "g:guest-2")


def test_a_seat_is_only_reentered_with_its_proof(server):
    host, guest = seated(server, "SEATS1")
    token = coop.COOP_ROOMS["SEATS1"]["meta"]["guest-2"]["token"]
    with server.connect("/bossrush/coop/SEATS1/guest-2") as thief:
        thief.send_json({"action": "join", "name": "Thief"})
        assert recv(thief, "error")["message"] == coop.SEAT_HELD   # says what to do
        thief.send_json({"action": "in", "run_id": "x", "stage": 0, "from": 0, "rows": []})
        assert recv(thief, "error")["message"] == "not seated in this room"
    with server.connect("/bossrush/coop/SEATS1/third-3") as third:
        third.send_json({"action": "join", "name": "Guest1003"})
        assert recv(third, "seat")["seat"] == 2
        third.send_json({"action": "leave"})
    with server.connect("/bossrush/coop/SEATS1/guest-2") as back:
        back.send_json({"action": "join", "name": "Guest1002", "token": token, "build": "b1"})
        assert recv(back, "seat")["seat"] == 1
    # An account's seat is its id, and its session proves it.
    with server.connect("/bossrush/coop/ACCT01/someone-else") as liar:
        liar.send_json({"action": "create", "session_token": "wren"})
        assert recv(liar, "error")["message"] == "That seat is not yours."


def test_a_guest_cannot_name_itself_on_the_board(server):
    """A guest is the site's Guest####, as solo records "Guest": a name a browser makes up
    (anyone's, the owner's included) never reaches the room or the co-op board."""
    host = server.open("/bossrush/coop/NAMES1/host-1")
    host.send_json({"action": "create", "name": "Forrest", "build": "b1"})
    recv(host, "seat")
    with server.connect("/bossrush/coop/NAMES1/u7") as wren:
        wren.send_json({"action": "join", "name": "Somebody", "session_token": "wren", "build": "b1"})
        recv(wren, "seat")
        with server.connect("/bossrush/coop/NAMES1/guest-3") as guest:
            guest.send_json({"action": "join", "name": "Guest4321", "build": "b1"})
            recv(guest, "seat")
            names = coop.COOP_ROOMS["NAMES1"]["names"]
            assert names == {"host-1": "Guest", "u7": "Wren", "guest-3": "Guest4321"}


def test_a_run_needs_both_picks_one_build_and_ends_for_both_when_one_leaves(server, monkeypatch):
    monkeypatch.setattr(coop, "GRACE_S", 0.2)
    host = server.open("/bossrush/coop/LEAVE1/host-1")
    host.send_json({"action": "create", "name": "Guest1001", "build": "b1"})
    recv(host, "seat")
    host.send_json({"action": "start"})
    assert recv(host, "error")["message"] == "Waiting for a second player."
    leaving = server.connect("/bossrush/coop/LEAVE1/guest-2")
    guest = leaving.__enter__()
    guest.send_json({"action": "join", "name": "Guest1002", "build": "b2"})
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
    away = recv(host, "away")                  # the fight waits for them, a while
    assert away["seat"] == 1 and away["grace"] == 0.2
    end = recv(host, "end")                    # and ends when they do not come back
    assert end["run_id"] == run["run_id"] and end["reason"] == "left"
    host.send_json({"action": "remove_offline"})
    new = server.open("/bossrush/coop/LEAVE1/new-guest")
    # Wait for the host's action to complete before trying the open seat.
    while recv(host, "room")["room"]["seats"][1] is not None:
        pass
    new.send_json({"action": "join", "name": "Guest1003", "build": "b1"})
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
    assert [(e["name"], e["character"], e["name2"], e["character2"]) for e in entries] == [("Guest1001", "ninja", "Guest1002", "paladin")]
    assert board(set_id="rift-trio", mode="coop", character="paladin", token=None)["entries"], "either player's character"
    assert not board(set_id="rift-trio", mode="coop", character="ranger", token=None)["entries"]
    mine = board(set_id="rift-trio", mode="coop", mine=True, guest="guest-2", token=None)["entries"]
    assert len(mine) == 1, "My best finds a co-op run from either seat"


def test_four_players_share_inputs_and_are_listed_on_the_board(server):
    host, guest = seated(server, "PARTY4")
    extra = []
    for pid, name, character in (("third", "Guest1003", "diviner"), ("fourth", "Guest1004", "simon")):
        ws = server.open(f"/bossrush/coop/PARTY4/{pid}")
        ws.send_json({"action": "join", "name": name, "build": "b1"})
        assert recv(ws, "seat")["seat"] == len(extra) + 2
        ws.send_json({"action": "pick", "character": character})
        extra.append(ws)
    with server.connect("/bossrush/coop/PARTY4/fifth") as fifth:
        fifth.send_json({"action": "join", "name": "Fifth", "build": "b1"})
        assert "full" in recv(fifth, "error")["message"]
    for _ in range(20):
        if all(s and s["character"] for s in recv(host, "room")["room"]["seats"]):
            break
    seats = [host, guest, *extra]
    host.send_json({"action": "set", "set_id": "crypt-trio", "first": "hush-vault"})
    host.send_json({"action": "start"})
    runs = [recv(ws, "run")["run"] for ws in seats]
    run = runs[0]
    assert all(r == run for r in runs)
    assert run["slots"] == [0, 1, 2, 3]
    assert run["stages"][0]["id"] == "hush-vault"
    assert run["analog_movement"] is True
    packet = {"run_id": run["run_id"], "stage": 0}
    for ws in seats[:3]:
        ws.send_json({"action": "ready", **packet})
        ws.send_json({"action": "ping"})
        recv(ws, "pong")
    assert coop.COOP_ROOMS["PARTY4"]["run"]["ready"] == {"host-1", "guest-2", "third"}
    seats[3].send_json({"action": "ready", **packet})
    for ws in seats:
        assert recv(ws, "ready")["stage"] == 0
    row = [0.8, 0.6, 1, 0, 1, 0, 0, 0]
    seats[3].send_json({"action": "in", **packet, "from": 0, "rows": [[1.01, *row[1:]]]})
    seats[3].send_json({"action": "in", **packet, "from": 0, "rows": [row]})
    for ws in seats[:3]:
        msg = recv(ws, "in")
        assert msg["seat"] == 3 and msg["rows"] == [row]
    seats[2].send_json({"action": "need_input", **packet, "from": 0, "to": 3})
    assert recv(seats[3], "need_input")["seat"] == 2
    for ws in seats:
        finish(ws, run, 0, "advance")
    for ws in seats:
        assert recv(ws, "settled")["reason"] == "advance"
    enter = server.endpoints["/bossrush/runs/{run_id}/entries/{stage}"]
    clear = server.endpoints["/bossrush/runs/{run_id}/clears/{stage}"]
    for stage in (1, 2, 3):
        enter(run["run_id"], stage)
        clear(run["run_id"], stage)
    board = server.endpoints["/bossrush/leaderboard"]
    rows = board(set_id="crypt-trio", mode="coop", character="simon", mine=True, guest="fourth", token=None)["entries"]
    assert len(rows) == 1
    assert [p["name"] for p in rows[0]["players"]] == ["Guest1001", "Guest1002", "Guest1003", "Guest1004"]


def started_run(server, code):
    host, guest = seated(server, code)
    host.send_json({"action": "start"})
    run = recv(host, "run")["run"]
    recv(guest, "run")
    ready(host, guest, run)
    return host, guest, run


def rows_of(n, mx):
    return [[mx, 0, 1, 0, 1, 0, 0, 0]] * n


def test_a_dropped_seat_rejoins_the_fight_with_every_row_it_missed(server):
    """A guest whose connection drops is AWAY, not gone: on rejoining (with its seat
    token) it gets the run and every row the server relayed, and the host is told."""
    host, guest, run = started_run(server, "BACK01")
    token = coop.COOP_ROOMS["BACK01"]["meta"]["guest-2"]["token"]
    packet = {"action": "in", "run_id": run["run_id"], "stage": 0}
    host.send_json({**packet, "from": 0, "rows": rows_of(10, 1)})
    guest.send_json({**packet, "from": 0, "rows": rows_of(4, -1)})
    guest.send_json({**packet, "from": 4, "rows": rows_of(2, 0)})
    assert recv(guest, "in")["from"] == 0 and recv(host, "in")["from"] == 0
    assert recv(host, "in")["from"] == 4
    guest.close()                                       # the guest's wifi drops
    assert recv(host, "away") == {"type": "away", "run_id": run["run_id"], "seat": 1, "grace": coop.GRACE_S}
    host.send_json({**packet, "from": 10, "rows": rows_of(5, 1)})   # the host plays on, and is stored
    host.send_json({"action": "ping"})
    recv(host, "pong")
    back = server.open("/bossrush/coop/BACK01/guest-2")
    back.send_json({"action": "join", "name": "Guest1002", "build": "b1", "token": token})
    seat = recv(back, "seat")
    assert seat["seat"] == 1 and seat["resume"] is True
    resume = recv(back, "resume")
    assert resume["run"] == run and resume["stage"] == 0 and resume["started"] is True
    assert resume["outcome"] is None and resume["finished"] is False
    got = {}
    for stage, seat_index, start, rows in resume["chunks"]:
        assert stage == 0
        got.setdefault(seat_index, []).extend((start + i, row) for i, row in enumerate(rows))
    assert [t for t, _ in got[0]] == list(range(15)) and [t for t, _ in got[1]] == list(range(6))
    assert [r[0] for _, r in got[1]] == [-1] * 4 + [0] * 2, "the guest's own rows, as it sent them"
    assert recv(host, "back") == {"type": "back", "run_id": run["run_id"], "seat": 1}
    # The fight carries on: the guest's next row reaches the host.
    back.send_json({**packet, "from": 6, "rows": rows_of(1, 0)})
    assert recv(host, "in")["from"] == 6


def test_a_seat_that_cannot_be_caught_up_ends_the_run(server):
    """Rows relayed past a gap were seen by the others but not stored: a browser that
    rejoined would send different ones, so that seat's drop ends the run as before."""
    host, guest, run = started_run(server, "GAP001")
    packet = {"action": "in", "run_id": run["run_id"], "stage": 0}
    guest.send_json({**packet, "from": 0, "rows": rows_of(3, 0)})
    guest.send_json({**packet, "from": 5, "rows": rows_of(1, 0)})   # ticks 3 and 4 never came
    assert recv(host, "in")["from"] == 0 and recv(host, "in")["from"] == 5
    guest.close()
    assert recv(host, "end")["reason"] == "left"


def test_a_hidden_tab_tells_the_others_why_the_fight_waits(server):
    host, guest, run = started_run(server, "HIDE01")
    guest.send_json({"action": "hidden", "run_id": run["run_id"], "hidden": True})
    assert recv(host, "hidden") == {"type": "hidden", "run_id": run["run_id"], "seat": 1, "hidden": True}
    guest.send_json({"action": "hidden", "run_id": run["run_id"], "hidden": False})
    assert recv(host, "hidden")["hidden"] is False


def test_a_socket_that_stops_reading_holds_up_nobody(server):
    """Sends are queued per socket. A host whose connection stops reading used to hold
    the room lock for 3 s per message; now the guest is answered at once."""
    host, guest = seated(server, "SLOW01")
    host.stalled = True
    for character in ("ranger", "simon", "ninja"):
        guest.send_json({"action": "pick", "character": character})
        # Every reply has to arrive inside half a second (the old 3 s timeout would not).
        while recv_within(guest, "room", 0.5)["room"]["seats"][1]["character"] != character:
            pass


def recv_within(ws, kind, seconds):
    for _ in range(20):
        msg = ws.receive_json(timeout=seconds)
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind}")
