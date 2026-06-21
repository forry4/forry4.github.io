"""Full games across several explicit decks (the host role picker) driven through
every phase at the engine level — every present night action, vote, resolve; no
crash, valid outcome, player_view never throws."""
import random

from games.wherewolf import engine, roles

DECKS = [
    # all-roles 8-player
    ["werewolf", "werewolf", "seer", "robber", "troublemaker",
     "minion", "mason", "mason", "drunk", "insomniac", "hunter"],
    # no-werewolf 4-player
    ["seer", "robber", "troublemaker", "villager", "villager", "mason", "mason"],
    # 2-mason 5-player
    ["werewolf", "mason", "mason", "seer", "villager", "villager", "villager", "robber"],
    # tanner + hunter + minion 6-player
    ["werewolf", "werewolf", "tanner", "hunter", "minion",
     "seer", "villager", "villager", "robber"],
]


def _first(g, role):
    return next((p for p in g["order"] if g["players"][p]["dealt_role"] == role), None)


def _drive_night(g, rng):
    engine.start_night(g)
    for step in roles.NIGHT_ORDER:
        role = roles.STEP_ROLE[step]
        if role not in g["deck"]:
            continue
        engine.set_step(g, step)
        actor = _first(g, role)
        if actor is None:
            continue                              # role is in the center → no one acts
        others = [p for p in g["order"] if p != actor]
        if step == "seer":
            engine.apply_move(g, actor, {"type": "seer_peek_center", "indices": [0, 1]})
        elif step == "robber":
            engine.apply_move(g, actor, {"type": "robber_swap", "target": rng.choice(others)})
        elif step == "troublemaker" and len(others) >= 2:
            a, b = rng.sample(others, 2)
            engine.apply_move(g, actor, {"type": "troublemaker_swap", "a": a, "b": b})
        elif step == "drunk":
            engine.apply_move(g, actor, {"type": "drunk_swap", "center_index": rng.randint(0, 2)})
        elif step == "werewolves" and len(g["wolf_pids"]) == 1:
            engine.apply_move(g, actor, {"type": "wolf_peek_center", "index": 0})


def test_full_games_custom_decks():
    rng = random.Random(11)
    for di, deck in enumerate(DECKS):
        n = len(deck) - 3
        players = [f"p{i}" for i in range(n)]
        g = engine.new_game(players, names={p: p for p in players}, seed=di, deck=deck)
        assert g["phase"] == engine.DEALING and len(g["center"]) == 3
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
        assert isinstance(g["headline"], str) and g["headline"]
        assert set(g["winners"]) <= set(g["order"])
        assert set(g["deaths"]) <= set(g["order"])

        for p in g["order"]:
            v = engine.player_view(g, p)
            assert v["phase"] == engine.OVER
            assert all(pd["card"] is not None for pd in v["players"].values())
            assert all(c is not None for c in v["center"])
