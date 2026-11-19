"""Halcyon Rift routes (halcyon/api.py), called as their registered endpoints
(the repo has no TestClient — the Box Puzzles / Notes pattern), on a real sqlite file."""
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from core.db import _Conn
from halcyon import api as A
from halcyon import content as C
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
    assert [c["id"] for c in state["classes"]] == ["ranger", "paladin", "diviner", "ninja"]
    gear = {i["equip_slot"]: i["base_id"] for i in state["items"] if i["loc"] == "equipped"}
    assert gear == {"weapon": "longbow", "armor": "leather_vest", "ability": "volley_quiver"}
    assert [c["char_id"] for c in state["characters"]] == [ch["char_id"]]
    assert state["levels"][:3] == [0, 120, 280] and state["characters"][0]["level"] == 1

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
    assert state["characters"][0]["xp"] == d["enemies"]["boss"]["xp"] + d["complete_xp"]
    loot = next(i for i in state["items"] if i["loc"] == "inventory")
    moved = route(app, "POST", "/halcyon/items/{item_id}/move")(
        loot["item_id"], A.MoveIn(to=["vault", 3], version=loot["version"]), who)
    assert (moved["loc"], moved["slot_index"]) == ("vault", 3)
    with pytest.raises(HTTPException) as e:                        # stale version
        route(app, "POST", "/halcyon/items/{item_id}/move")(
            loot["item_id"], A.MoveIn(to=["vault", 4], version=loot["version"]), who)
    assert e.value.status_code == 409


def test_going_deeper_through_the_routes(app):
    who = owner_dep(app)("tok", None, None)
    ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=0), who)
    run = route(app, "POST", "/halcyon/runs")(A.RunIn(char_id=ch["char_id"], mods=["brutal"]), who)
    d, rid = run["dungeon"], run["run_id"]
    assert d["level"] == 1 and len(d["offers"]) == 3 and "brutal" not in d["offers"]
    descend = route(app, "POST", "/halcyon/runs/{run_id}/descend")
    with pytest.raises(HTTPException) as e:                        # the boss still stands
        descend(rid, A.DescendIn(mod=d["offers"][0], from_level=1), who)
    assert e.value.status_code == 409
    route(app, "POST", "/halcyon/runs/{run_id}/events")(rid, A.EventsIn(events=[
        {"seq": 1, "type": "kill", "enemy": "boss"}]), who)
    two = descend(rid, A.DescendIn(mod=d["offers"][0], from_level=1), who)["dungeon"]
    assert two["level"] == 2 and sorted(two["mods"]) == sorted(["brutal", d["offers"][0]])
    assert two["tiles"] and two["boss"] == "L2-boss" and set(two["offers"]).isdisjoint(two["mods"])
    out = route(app, "POST", "/halcyon/runs/{run_id}/events")(rid, A.EventsIn(events=[
        {"seq": 2, "type": "kill", "enemy": "L2-boss"}, {"seq": 3, "type": "complete"}]), who)
    assert out == {"status": "completed", "last_seq": 3, "refused": []}


def test_character_menu_starts_class_specific_practice_runs(app):
    who = owner_dep(app)("tok", None, None)
    ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=0, class_id="paladin"), who)
    state = route(app, "GET", "/halcyon/state")(who)
    gear = {i["equip_slot"]: i["base_id"] for i in state["items"] if i["loc"] == "equipped"}
    assert gear == {"weapon": "mace", "armor": "plate_armor", "ability": "stillness_orb"}
    assert {i["tier"] for i in state["items"] if i["loc"] == "equipped"} == {0}, "starter gear is tier 0"
    with pytest.raises(HTTPException) as e:
        route(app, "POST", "/halcyon/runs")(A.RunIn(char_id=ch["char_id"], practice=True), who)
    assert e.value.status_code == 409 and "Dream Key" in e.value.detail
    S.grant_item(app.state.connect, who, {"base_id": "dream_key", "tier": 1, "slot_count": 0, "enchants": []},
                 ("inventory", ch["char_id"], 0))
    run = route(app, "POST", "/halcyon/runs")(A.RunIn(char_id=ch["char_id"], practice=True), who)
    assert run["practice"] is True and run["class_id"] == "paladin" and run["dungeon"]["class_id"] == "paladin"


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


def test_every_class_starts_with_its_own_kit(app):
    """One standard ability per class (2026-11-18): the Paladin's field, the Diviner's
    stars, the Ninja's counter; every starter item is one that class can wear."""
    who = owner_dep(app)("tok", None, None)
    want = {"ranger": "volley_quiver", "paladin": "stillness_orb", "diviner": "star_tome", "ninja": "mirror_charm"}
    for slot, (cls, ability) in enumerate(want.items()):
        ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=slot, class_id=cls), who)
        state = route(app, "GET", "/halcyon/state")(who)
        gear = [i for i in state["items"] if i["loc"] == "equipped" and i["char_id"] == ch["char_id"]]
        assert {i["equip_slot"]: i["base_id"] for i in gear}["ability"] == ability
        assert all(C.usable_by(i["base_id"], cls) for i in gear)
        assert not any(C.BASE_ITEMS[i["base_id"]].get("retired") for i in gear)


def test_lock_and_the_graveyard_through_the_routes(app):
    who = owner_dep(app)("tok", None, None)
    ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=0), who)
    state = route(app, "GET", "/halcyon/state")(who)
    bow = next(i for i in state["items"] if i["equip_slot"] == "weapon")
    out = route(app, "POST", "/halcyon/items/{item_id}/lock")(bow["item_id"], A.LockIn(locked=True), who)
    assert out["locked"] is True
    state = route(app, "GET", "/halcyon/state")(who)
    assert next(i for i in state["items"] if i["item_id"] == bow["item_id"])["locked"] is True
    assert state["best_level"] == 1 and state["fallen"] == [] and state["fallen_count"] == 0
    run = route(app, "POST", "/halcyon/runs")(A.RunIn(char_id=ch["char_id"]), who)
    assert run["dungeon"]["boss_name"]
    route(app, "POST", "/halcyon/runs/{run_id}/events")(run["run_id"], A.EventsIn(events=[
        {"seq": 1, "type": "death", "summary": {"src": "radial:ring", "hit": 12}}]), who)
    state = route(app, "GET", "/halcyon/state")(who)
    grave = state["fallen"][0]["death_summary"]
    assert grave["src"] == "radial:ring" and grave["dungeon_name"] == run["dungeon"]["name"]
    assert {i["base_id"] for i in grave["items"]} >= {bow["base_id"]}


def test_a_boss_rush_run_through_the_route_is_only_the_boss_at_every_level(app):
    who = owner_dep(app)("tok", None, None)
    ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=0), who)
    start = route(app, "POST", "/halcyon/runs")
    with pytest.raises(HTTPException) as e:
        start(A.RunIn(char_id=ch["char_id"], boss_rush=True), who)
    assert "Boss Rush key" in e.value.detail
    S.grant_item(app.state.connect, who, {"base_id": "boss_rush_key", "tier": 1, "slot_count": 0, "enchants": []},
                 ("inventory", ch["char_id"], 0))
    run = start(A.RunIn(char_id=ch["char_id"], boss_rush=True), who)
    d = run["dungeon"]
    assert d["boss_rush"] and [r["kind"] for r in d["rooms"]] == ["entrance", "boss"]
    assert all(e["type"] == "boss" for e in d["enemies"].values())
    assert "boss_rush_key" not in {x["base_id"] for x in d["drops"].values()}
    route(app, "POST", "/halcyon/runs/{run_id}/events")(run["run_id"], A.EventsIn(events=[
        {"seq": 1, "type": "kill", "enemy": d["boss"], "elapsed_ticks": 500}]), who)
    deeper = route(app, "POST", "/halcyon/runs/{run_id}/descend")(run["run_id"], A.DescendIn(
        mod=d["offers"][0], from_level=1), who)["dungeon"]
    assert deeper["boss_rush"] and [r["kind"] for r in deeper["rooms"]] == ["entrance", "boss"]
    assert route(app, "GET", "/halcyon/state")(who)["leaderboards"] == {}


def test_the_town_ground_through_the_routes(app):
    who = owner_dep(app)("tok", None, None)
    ch = route(app, "POST", "/halcyon/characters")(A.CharacterIn(slot=0), who)
    state = route(app, "GET", "/halcyon/state")(who)
    vest = next(i for i in state["items"] if i["base_id"] == "leather_vest")
    out = route(app, "POST", "/halcyon/items/{item_id}/move")(vest["item_id"], A.MoveIn(to=["floor", ch["char_id"]]), who)
    assert out["loc"] == "ground" and out["run_id"] == "town:" + ch["char_id"]
    assert route(app, "POST", "/halcyon/characters/{char_id}/leave")(ch["char_id"], who) == {"ok": True}
    assert vest["item_id"] not in {i["item_id"] for i in route(app, "GET", "/halcyon/state")(who)["items"]}
