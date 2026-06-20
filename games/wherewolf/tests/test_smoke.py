"""Full random games (3..10 players) driven through every phase at the engine
level — no crash, valid winner, player_view never throws."""
import random

from games.wherewolf import engine
from .conftest import make_game


def _first_with_role(g, role):
    return next((p for p in g["order"] if g["players"][p]["dealt_role"] == role), None)


def _drive_night(g, rng):
    engine.start_night(g)
    engine.set_step(g, engine.STEP_WOLVES)

    engine.set_step(g, engine.STEP_SEER)
    seer = _first_with_role(g, "seer")
    if seer:
        engine.apply_move(g, seer, {"type": "seer_peek_center", "indices": [0, 1]})

    engine.set_step(g, engine.STEP_ROBBER)
    robber = _first_with_role(g, "robber")
    if robber:
        others = [p for p in g["order"] if p != robber]
        engine.apply_move(g, robber, {"type": "robber_swap", "target": rng.choice(others)})

    engine.set_step(g, engine.STEP_TMAKER)
    tm = _first_with_role(g, "troublemaker")
    if tm:
        others = [p for p in g["order"] if p != tm]
        if len(others) >= 2:
            a, b = rng.sample(others, 2)
            engine.apply_move(g, tm, {"type": "troublemaker_swap", "a": a, "b": b})


def test_full_games_all_sizes():
    rng = random.Random(7)
    for n in range(3, 11):
        g = make_game([f"p{i}" for i in range(n)], seed=n)
        for p in g["order"]:
            assert engine.apply_move(g, p, {"type": "ready"})[0]
        assert engine.all_ready(g)

        _drive_night(g, rng)

        engine.begin_day(g, deadline=None)
        for p in g["order"]:
            engine.apply_move(g, p, {"type": "vote", "target": rng.choice(g["order"])})
            engine.apply_move(g, p, {"type": "lock_vote"})
        assert engine.all_locked(g)

        engine.resolve_votes(g)
        assert engine.is_over(g)
        assert g["winner"] in ("villagers", "wolves")

        # Every player's end-of-game view is well-formed and reveals all cards.
        for p in g["order"]:
            v = engine.player_view(g, p)
            assert v["phase"] == engine.OVER
            assert all(pd["card"] is not None for pd in v["players"].values())
