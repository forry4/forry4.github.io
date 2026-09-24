"""Game results (core/results.py): the table behind a player's profile.

Driven through a FAKE game registered against a real sqlite file, so every
test exercises the real sync — the id-only scan, the "already recorded" diff,
the batched blob fetch and the INSERT OR IGNORE — without importing a game
(core's tests may not import a feature). Each game's own reader is covered in
shared/tests/test_profile_results.py, against its real engine.
"""
import json
import sqlite3
import time

import pytest
from fastapi import FastAPI, HTTPException

import core.db
from core import results
from core.db import _Conn

# Real clock times: the global sync looks back RECORDED_WINDOW from now.
NOW = int(time.time())


def _fake_standings(state):
    if state.get("winner") == "void":
        return None
    order = list(state["players"])
    if state.get("winner") == "draw":
        return results.standings(state, order, draw=True)
    return results.standings(state, order, [state["winner"]], scores=state.get("scores"))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A sqlite file holding `users` and one fake game table, with only the fake
    game registered and a decoder that counts its calls."""
    path = str(tmp_path / "results.db")
    connect = lambda: _Conn(sqlite3.connect(path, check_same_thread=False))  # noqa: E731
    monkeypatch.setattr(core.db, "get_db_conn", connect)
    conn = connect()
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("""CREATE TABLE fake_games (id TEXT PRIMARY KEY, status TEXT, player1_id TEXT,
                    player2_id TEXT, state_json TEXT, updated_at INTEGER)""")
    conn.commit()
    decoded = []

    def decode(blob):
        state = json.loads(blob)
        decoded.append(state.get("_id"))
        return state

    monkeypatch.setattr(results, "_SOURCES", {})
    monkeypatch.setattr(results, "_void", set())
    results.register("fake", "fake_games", decode=decode, standings=_fake_standings)

    class World:
        pass
    w = World()
    w.conn, w.connect, w.decoded = conn, connect, decoded

    def user(uid, name=None):
        conn.execute("INSERT INTO users (id, name) VALUES (?, ?)", (uid, name or uid))
        conn.commit()

    def game(gid, players, winner, *, status="over", updated_at=NOW, **extra):
        state = {"_id": gid, "players": players, "winner": winner, **extra}
        ids = list(players) + [None, None]
        conn.execute("INSERT INTO fake_games VALUES (?,?,?,?,?,?)",
                     (gid, status, ids[0], ids[1], json.dumps(state), updated_at))
        conn.commit()

    def rows(uid=None):
        cur = conn.cursor()
        cur.execute("SELECT game_id, user_id, outcome, score, vs_bot, ai_tier FROM game_results"
                    + (" WHERE user_id=?" if uid else "") + " ORDER BY game_id, user_id",
                    (uid,) if uid else ())
        return [tuple(r) for r in cur.fetchall()]

    w.user, w.game, w.rows = user, game, rows
    return w


def test_a_finished_game_gets_one_row_per_registered_player(world):
    world.user("ann"); world.user("bob")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "ann", scores={"ann": 15, "bob": 11})
    assert results.sync(world.conn) == 2
    assert world.rows() == [("G1", "ann", "win", 15.0, 0, None), ("G1", "bob", "loss", 11.0, 0, None)]


def test_guests_and_bots_get_no_rows(world):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "guest1": "Visitor"}, "guest1")
    world.game("G2", {"ann": "Ann", "bot": "Bot"}, "ann", ai_player="bot", ai_difficulty="hard")
    world.game("G3", {"guest1": "Visitor", "guest2": "Other"}, "guest1")
    results.sync(world.conn)
    assert world.rows() == [("G1", "ann", "loss", None, 0, None), ("G2", "ann", "win", None, 1, "hard")]
    assert "G3" not in world.decoded, "an all-guest game was decoded; the seat scan should skip it"


def test_games_still_in_play_are_left_alone(world):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, None, status="playing")
    assert results.sync(world.conn) == 0 and world.decoded == []


def test_a_rerun_writes_nothing_and_decodes_nothing(world):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "draw")
    assert results.sync(world.conn) == 1
    world.decoded.clear()
    assert results.sync(world.conn) == 0
    assert world.decoded == [], "an already-recorded game was decoded again"
    assert world.rows() == [("G1", "ann", "draw", None, 0, None)]


def test_a_game_with_no_result_is_decoded_once_per_process(world):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "void")
    results.sync(world.conn)
    results.sync(world.conn)
    assert world.decoded == ["G1"] and world.rows() == []


def test_the_first_recorded_finish_time_is_kept(world):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "ann", updated_at=NOW - 100)
    results.sync(world.conn)
    world.conn.execute("UPDATE fake_games SET updated_at=?", (NOW,))
    world.conn.commit()
    results.sync(world.conn, "ann")
    assert results.fetch_history(world.conn, "ann")["history"][0]["finished_at"] == NOW - 100


def test_one_players_sync_records_every_registered_seat(world):
    """Otherwise the global sync, which counts a game as done once ANY row for it
    exists, would never record the other player."""
    world.user("ann"); world.user("bob")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "bob")
    world.game("G2", {"carl": "Carl", "bob": "Bob"}, "bob")
    assert results.sync(world.conn, "ann") == 2
    assert world.rows() == [("G1", "ann", "loss", None, 0, None), ("G1", "bob", "win", None, 0, None)]
    assert results.sync(world.conn) == 1          # G2, for bob — G1 is already done
    assert [r[0] for r in world.rows("bob")] == ["G1", "G2"]


def test_a_guest_who_registers_later_picks_up_their_games(world):
    world.user("bob")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "ann")
    results.sync(world.conn)
    world.user("ann")
    results.sync(world.conn)                       # the global sync sees G1 as done
    assert world.rows("ann") == []
    results.sync(world.conn, "ann")                # her own sync does not
    assert world.rows("ann") == [("G1", "ann", "win", None, 0, None)]


def test_one_broken_game_does_not_stop_the_others(world, monkeypatch):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "ann")
    world.conn.execute("UPDATE fake_games SET state_json='not json' WHERE id='G1'")
    world.game("G2", {"ann": "Ann", "bob": "Bob"}, "bob")
    results.register("missing", "no_such_table", decode=json.loads, standings=_fake_standings)
    results.sync(world.conn)
    assert world.rows() == [("G2", "ann", "loss", None, 0, None)]


def test_blobs_are_fetched_in_batches(world, monkeypatch):
    monkeypatch.setattr(results, "SYNC_BATCH", 3)
    world.user("ann")
    for i in range(8):
        world.game(f"G{i}", {"ann": "Ann", "bob": "Bob"}, "ann")
    assert results.sync(world.conn) == 8


def test_a_tie_between_winners_is_a_draw_unless_the_win_is_shared():
    state = {"players": {"a": "A", "b": "B", "c": "C"}, "ai_player": "c"}
    tie = results.standings(state, ["a", "b", "c"], ["a", "b"])
    assert [(p["outcome"], p["bot"]) for p in tie["players"]] == [("draw", False), ("draw", False), ("loss", True)]
    team = results.standings(state, ["a", "b", "c"], ["a", "b"], shared_win_is_a_draw=False)
    assert [p["outcome"] for p in team["players"]] == ["win", "win", "loss"]
    assert [p["outcome"] for p in results.standings(state, ["a", "b"], draw=True)["players"]] == ["draw", "draw"]


def test_history_marks_you_and_carries_the_table(world):
    world.user("ann")
    world.game("G1", {"ann": "Ann", "bot": "Bot"}, "bot", ai_player="bot", ai_difficulty="expert",
               scores={"ann": 3, "bot": 9}, updated_at=NOW - 10)
    world.game("G2", {"ann": "Ann", "bob": "Bob"}, "ann", updated_at=NOW)
    results.sync(world.conn)
    h = results.fetch_history(world.conn, "ann")
    assert [g["id"] for g in h["history"]] == ["G2", "G1"] and h["truncated"] is False
    g1 = h["history"][1]
    assert (g1["game"], g1["outcome"], g1["vs_bot"], g1["ai_tier"], g1["score"]) == ("fake", "loss", True, "expert", 3)
    assert [(p["name"], p["you"], p["bot"]) for p in g1["players"]] == [("Ann", True, False), ("Bot", False, True)]


# ── the route ────────────────────────────────────────────────────────────────
# Called directly, like notes/tests: the repo has no httpx, so no TestClient.
def _route(world):
    """(the /profile handler, the auth dependency) off a fresh app."""
    app = FastAPI()
    users = {"tok-ann": {"id": "ann", "name": "Ann"}, "tok-bob": {"id": "bob", "name": "Bob"}}
    results.setup_profile(app, users.get)
    [route] = [r for r in app.routes if getattr(r, "path", "") == "/profile"]
    member = route.dependant.dependencies[0].call
    return route.endpoint, member


def test_the_profile_needs_a_signed_in_player(world):
    _, member = _route(world)
    for token in (None, "nope"):
        with pytest.raises(HTTPException) as e:
            member(token)
        assert e.value.status_code == 401
    assert member("tok-ann") == {"id": "ann", "name": "Ann"}


def test_the_profile_is_your_own_and_is_synced_on_open(world, monkeypatch):
    monkeypatch.setattr(results, "_profile_reads", results.SlidingWindowLimiter(30, 60))
    world.user("ann"); world.user("bob")
    world.game("G1", {"ann": "Ann", "bob": "Bob"}, "ann")
    world.game("G2", {"bob": "Bob", "carl": "Carl"}, "bob")
    profile, _ = _route(world)
    body = profile({"id": "ann", "name": "Ann"})
    assert body["user"] == {"id": "ann", "name": "Ann"}
    assert [(g["id"], g["outcome"]) for g in body["history"]] == [("G1", "win")]


def test_the_profile_is_rate_limited(world, monkeypatch):
    monkeypatch.setattr(results, "_profile_reads", results.SlidingWindowLimiter(2, 60))
    world.user("ann")
    profile, _ = _route(world)
    profile({"id": "ann", "name": "Ann"})
    profile({"id": "ann", "name": "Ann"})
    with pytest.raises(HTTPException) as e:
        profile({"id": "ann", "name": "Ann"})
    assert e.value.status_code == 429
