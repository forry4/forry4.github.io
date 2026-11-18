"""Halcyon Rift routes (halcyon/api.py), called as their registered endpoints
(the repo has no TestClient — the Box Puzzles / Notes pattern), on a real sqlite file."""
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from core.db import _Conn
from halcyon import api as A
from halcyon import store as S


@pytest.fixture()
def app(tmp_path):
    path = str(tmp_path / "h.db")
    users = {"tok": {"id": "u_acct", "name": "acct"}}
    a = FastAPI()
    A._guests_hour.reset()
    A._runs_hour.reset()
    A._events_minute.reset()
    A.setup_halcyon(a, lambda: _Conn(sqlite3.connect(path)), lambda t: users.get(t))
    a.state.connect = lambda: _Conn(sqlite3.connect(path))
    return a


def route(app, method, path):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in r.methods:
            return r.endpoint
    raise AssertionError(f"no route {method} {path}")


def owner_dep(app):
    """The `owner` dependency every authenticated route shares."""
    ep = route(app, "GET", "/halcyon/state")
    return ep.__defaults__[0].dependency


def _req(ip="1.2.3.4"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def test_a_guest_roster_is_minted_by_the_server_and_proved_by_its_secret(app):
    g = route(app, "POST", "/halcyon/guest")(_req())
    assert g["owner"].startswith("hg_") and g["secret"]
    who = owner_dep(app)
    assert who(token=None, x_halcyon_owner=g["owner"], x_halcyon_secret=g["secret"]) == g["owner"]
    for bad in ((g["owner"], "nope"), (g["owner"], None), (None, g["secret"]), ("u_acct", g["secret"])):
        with pytest.raises(HTTPException) as e:
            who(token=None, x_halcyon_owner=bad[0], x_halcyon_secret=bad[1])
        assert e.value.status_code == 401


def test_an_account_is_its_session(app):
    who = owner_dep(app)
    assert who(token="tok", x_halcyon_owner=None, x_halcyon_secret=None) == "u_acct"
    with pytest.raises(HTTPException):
        who(token="stale", x_halcyon_owner=None, x_halcyon_secret=None)


def test_guest_minting_is_rate_limited(app):
    mint = route(app, "POST", "/halcyon/guest")
    for _ in range(10):
        mint(_req("9.9.9.9"))
    with pytest.raises(HTTPException) as e:
        mint(_req("9.9.9.9"))
    assert e.value.status_code == 429
    mint(_req("8.8.8.8"))                            # per address


def test_the_whole_loop_through_the_routes(app):
    who = owner_dep(app)("tok", None, None)
    ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=0), who)
    state = route(app, "GET", "/halcyon/state")(who)
    gear = {i["equip_slot"]: i["base_id"] for i in state["items"] if i["loc"] == "equipped"}
    assert gear == {"weapon": "shortbow", "armor": "leather_vest", "ability": "volley_quiver"}
    assert [c["char_id"] for c in state["characters"]] == [ch["char_id"]]

    run = route(app, "POST", "/halcyon/runs")(A.RunIn(char_id=ch["char_id"]), who)
    d = run["dungeon"]
    assert d["tiles"] and d["enemies"]["boss"]["type"] == "boss"
    boss_drop = next(k for k, v in d["drops"].items() if v["enemy"] == "boss")
    out = route(app, "POST", "/halcyon/runs/{run_id}/events")(run["run_id"], A.EventsIn(events=[
        {"seq": 1, "type": "kill", "enemy": "boss"},
        {"seq": 2, "type": "pickup", "drop": boss_drop, "slot": 0},
        {"seq": 3, "type": "complete"}]), who)
    assert out == {"status": "completed", "last_seq": 3, "refused": []}
    state = route(app, "GET", "/halcyon/state")(who)
    loot = next(i for i in state["items"] if i["loc"] == "inventory")
    moved = route(app, "POST", "/halcyon/items/{item_id}/move")(
        loot["item_id"], A.MoveIn(to=["vault", 3], version=loot["version"]), who)
    assert (moved["loc"], moved["slot_index"]) == ("vault", 3)
    with pytest.raises(HTTPException) as e:                        # stale version
        route(app, "POST", "/halcyon/items/{item_id}/move")(
            loot["item_id"], A.MoveIn(to=["vault", 4], version=loot["version"]), who)
    assert e.value.status_code == 409


def test_refusals_are_409_with_a_readable_reason(app):
    who = owner_dep(app)("tok", None, None)
    create = route(app, "POST", "/halcyon/characters")
    create(A.CharacterIn(slot=0), who)
    with pytest.raises(HTTPException) as e:
        create(A.CharacterIn(slot=0), who)
    assert e.value.status_code == 409 and "already" in e.value.detail
    with pytest.raises(HTTPException) as e:
        route(app, "POST", "/halcyon/runs")(A.RunIn(char_id="nope"), who)
    assert e.value.status_code == 409


def test_a_wire_place_cannot_smuggle_a_bad_index(app):
    assert A._place(["vault", "3"]) == ("vault", -1)
    assert A._place(["inventory", "c", 2]) == ("inventory", "c", 2)
    assert A._place(["equipped", "c", "ring1"]) == ("equipped", "c", "ring1")
    assert A._place(["ground", "r"]) == ("nowhere",)
    with pytest.raises(S.HalcyonError):
        S._place_cols("o", A._place(["vault", "3"]))


def test_the_site_lets_a_browser_send_the_guest_headers():
    """A guest's two headers are custom, so a browser asks first (a CORS preflight).
    Unlisted, every guest request fails as "Failed to fetch" before reaching a route."""
    from starlette.middleware.cors import CORSMiddleware

    import app as root
    cors = next(m for m in root.app.user_middleware if m.cls is CORSMiddleware)
    allowed = {h.lower() for h in cors.kwargs["allow_headers"]}
    assert {"x-halcyon-owner", "x-halcyon-secret"} <= allowed
