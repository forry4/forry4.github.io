"""The five best times per character keep a film; nothing else does."""
import gzip
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from bossrush import api
from core.db import _Conn


def film_of(character, stages=3):
    return gzip.compress(json.dumps({"v": 1, "character": character, "stages": [{}] * stages}).encode())


@pytest.fixture
def rush(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(api, "time", type("Clock", (), {"time": lambda: clock[0]}))
    monkeypatch.setattr(api, "_starts", api.SlidingWindowLimiter(1000, 60))
    monkeypatch.setattr(api, "_film_uploads", api.SlidingWindowLimiter(1000, 3600))
    app = FastAPI()
    api.setup_boss_rush(app, lambda: _Conn(sqlite3.connect(tmp_path / "runs.db")), lambda token: None, lambda: None)
    ep = {route.path: route.endpoint for route in app.routes if route.path.startswith("/bossrush")}
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    def finish(character, seconds):
        run = ep["/bossrush/runs"](api.StartIn(character=character), request, None)
        for stage in (1, 2):
            ep["/bossrush/runs/{run_id}/clears/{stage}"](run["run_id"], stage)
        clock[0] += seconds
        return run["run_id"], ep["/bossrush/runs/{run_id}/clears/{stage}"](run["run_id"], 3)

    return SimpleNamespace(
        finish=finish, clock=clock,
        upload=lambda run_id, data: ep["/bossrush/runs/{run_id}/film"](run_id, request, data),
        get=ep["/bossrush/films/{film_id}"], board=ep["/bossrush/leaderboard"])


def test_only_the_top_five_per_character_keep_films_and_one_falls_off_when_beaten(rush):
    films = {}
    for seconds in (50, 40, 60, 30, 70):          # five ninja times: all ask for a film
        run_id, result = rush.finish("ninja", seconds)
        assert result["film_wanted"] is True
        films[seconds] = (run_id, rush.upload(run_id, film_of("ninja"))["film_id"])
    slow, result = rush.finish("ninja", 80)       # sixth and slowest: not asked, and refused
    assert result["film_wanted"] is False
    with pytest.raises(HTTPException) as refused:
        rush.upload(slow, film_of("ninja"))
    assert refused.value.status_code == 409
    other, result = rush.finish("paladin", 99)    # another character has its own five
    assert result["film_wanted"] is True

    by_time = {e["elapsed_ms"] // 1000: e["film_id"] for e in rush.board(character="ninja")["entries"]}
    assert by_time == {30: films[30][1], 40: films[40][1], 50: films[50][1], 60: films[60][1], 70: films[70][1], 80: None}
    body = rush.get(films[30][1]).body
    assert json.loads(gzip.decompress(body))["character"] == "ninja"

    fast, result = rush.finish("ninja", 20)       # a new best pushes the 70 off the top five
    assert result["film_wanted"] is True
    with pytest.raises(HTTPException) as gone:
        rush.get(films[70][1])
    assert gone.value.status_code == 404
    assert rush.board(character="ninja")["entries"][5]["film_id"] is None
    # Uploading twice keeps the first film.
    first = rush.upload(fast, film_of("ninja"))["film_id"]
    assert rush.upload(fast, film_of("ninja"))["film_id"] == first


def test_a_film_must_be_a_film_of_that_run(rush):
    run_id, _ = rush.finish("ranger", 30)
    for bad in (b"not gzip", gzip.compress(b"[1, 2]"), film_of("paladin"), film_of("ranger", stages=2),
                gzip.compress(b"{" * 10)):
        with pytest.raises(HTTPException) as refused:
            rush.upload(run_id, bad)
        assert refused.value.status_code == 422
    with pytest.raises(HTTPException) as huge:
        rush.upload(run_id, b"x" * (api.FILM_MAX_BYTES + 1))
    assert huge.value.status_code == 413
    bomb = gzip.compress(b" " * (api.FILM_MAX_RAW + 10))   # small on the wire, enormous unpacked
    assert len(bomb) < api.FILM_MAX_BYTES
    with pytest.raises(HTTPException) as unpacked:
        rush.upload(run_id, bomb)
    assert unpacked.value.status_code == 422
    with pytest.raises(HTTPException) as unfinished:
        rush.upload("x" * 32, film_of("ranger"))
    assert unfinished.value.status_code == 404
    assert rush.upload(run_id, film_of("ranger"))["film_id"]
