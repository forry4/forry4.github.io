"""M9: full random-vs-random games via the engine + bot (no server).

Proves the engine is internally complete: it always terminates, never deadlocks
on a pending sub-decision, and declares a winner with sane scores.
"""
import random

import pytest

from games.castles_of_crimson import engine, bot, board
from .conftest import complete_setup


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 42, 99, 123, 2024])
def test_random_game_completes(seed):
    g = engine.new_game(["p1", "p2"], names={"p1": "Bot1", "p2": "Bot2"}, seed=seed)
    complete_setup(g)   # deterministic castle placement; preserves rng below
    rng = random.Random(seed * 7 + 1)
    guard = 0
    while not engine.is_over(g) and guard < 50000:
        guard += 1
        actor = g.get("pending_pid") or g.get("turn")
        move = bot.choose(g, actor, rng)
        assert move is not None, "no legal move available (deadlock)"
        ok, err = engine.apply_move(g, actor, move)
        assert ok, f"bot produced an illegal move {move}: {err}"
    assert engine.is_over(g), "game did not terminate within the guard limit"

    scores = engine.final_scores(g)
    assert set(scores) == {"p1", "p2"}
    assert all(v >= 0 for v in scores.values())
    assert g["winner"] in ("p1", "p2") or isinstance(g["winner"], list)

    # The bots actually played: more tiles on the board than just the two castles.
    placed = sum(
        1
        for pid in ("p1", "p2")
        for t in g["players"][pid]["duchy"].values()
        if t is not None
    )
    assert placed > 2


@pytest.mark.parametrize("b1,b2,seed", [
    ("2", "6", 11), ("3", "8", 22), ("5", "9", 33), ("7", "4", 44), ("1", "5", 55),
])
def test_random_game_completes_on_different_boards(b1, b2, seed):
    """Each player on a different board: per-duchy placement/scoring must run to
    completion with no cross-board interaction or deadlock."""
    g = engine.new_game(["p1", "p2"], names={"p1": "A", "p2": "B"}, seed=seed,
                        boards={"p1": b1, "p2": b2})
    assert g["players"]["p1"]["board_id"] == b1
    assert g["players"]["p2"]["board_id"] == b2
    complete_setup(g)
    rng = random.Random(seed * 13 + 5)
    guard = 0
    while not engine.is_over(g) and guard < 50000:
        guard += 1
        actor = g.get("pending_pid") or g.get("turn")
        move = bot.choose(g, actor, rng)
        assert move is not None, "no legal move available (deadlock)"
        ok, err = engine.apply_move(g, actor, move)
        assert ok, f"bot produced an illegal move {move}: {err}"
    assert engine.is_over(g)
    scores = engine.final_scores(g)
    assert set(scores) == {"p1", "p2"} and all(v >= 0 for v in scores.values())
    # Each player only ever placed on their own board's spaces.
    for pid, bid in (("p1", b1), ("p2", b2)):
        own_spaces = set(board.BOARDS[bid].SPACES)
        assert set(g["players"][pid]["duchy"]) == own_spaces


def test_play_turn_helper_advances_turn():
    g = engine.new_game(["p1", "p2"], seed=5)
    rng = random.Random(0)
    start_round = g["round"]
    # Drive whoever is the current actor for one full turn.
    actor = g["turn"]
    bot.play_turn(g, actor, rng)
    # Either the turn passed to the other player, or the round advanced.
    assert g["turn"] != actor or g["round"] != start_round or engine.is_over(g)
