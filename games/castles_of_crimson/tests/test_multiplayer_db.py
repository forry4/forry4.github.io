"""4-player persistence: the coc_games row indexes up to 4 seats so every player
(including seats 3 & 4) finds their game in the lobby lists, and the returned
`players` arrays are seat-ordered. The authoritative player list lives in state_json;
these columns are just the query index."""
import json
import time

import core.db as coredb
from games.castles_of_crimson import main, engine


def _seed_db(tmp_path, monkeypatch):
    monkeypatch.setattr(coredb, "DB_PATH", str(tmp_path / "coc_test.db"))
    main.STORE.reset_writer()
    main.coc_init_db()


def _persist(rid, pids, status="playing", winner=None, seed=1):
    g = engine.new_game(pids, names={p: p.upper() for p in pids}, seed=seed)
    if winner is not None:
        g["phase"] = "over"
        g["winner"] = winner
    state = {"players": {p: p.upper() for p in pids}, "host": pids[0], "status": status, "game": g}
    now = int(time.time())
    main._persist_row(rid, status, [(p, p.upper()) for p in pids], pids[0], json.dumps(state), now, now)


def test_four_player_row_indexed_for_all_seats(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    try:
        pids = ["a", "b", "c", "d"]
        _persist("R4", pids, status="playing")
        # every seat — including 3 & 4 — finds the game in their in-progress list
        for p in pids:
            ids = [x["id"] for x in main.list_user_games(p)]
            assert "R4" in ids, p
        # active-games list carries all four players, seat-ordered
        act = next(x for x in main.list_active_games() if x["id"] == "R4")
        assert [pl["id"] for pl in act["players"]] == pids
        # open-games player_count reflects the seats
        _persist("ROPEN", ["x", "y", "z"], status="open")
        og = next(x for x in main.list_open_games() if x["id"] == "ROPEN")
        assert og["player_count"] == 3 and og["max_players"] == main.MAX_PLAYERS
    finally:
        main.STORE.reset_writer()


def test_four_player_history_lists_all_opponents(tmp_path, monkeypatch):
    _seed_db(tmp_path, monkeypatch)
    try:
        pids = ["a", "b", "c", "d"]
        _persist("RH", pids, status="over", winner="a")
        # seat 4 sees the finished game with all three opponents named
        hist = next(x for x in main.list_user_history("d") if x["id"] == "RH")
        assert set(hist["opp_name"].split(", ")) == {"A", "B", "C"}
        assert {pl["id"] for pl in hist["players"]} == set(pids)
        assert any(pl["is_you"] for pl in hist["players"])
        # the winner won; a non-winner didn't
        assert next(x for x in main.list_user_history("a") if x["id"] == "RH")["you_won"] is True
        assert hist["you_won"] is False
    finally:
        main.STORE.reset_writer()
