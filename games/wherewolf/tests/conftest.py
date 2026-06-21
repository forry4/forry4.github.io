"""Shared test helpers for the Where Wolf? engine tests."""
from games.wherewolf import engine


def make_game(player_ids, seed=0):
    ids = list(player_ids)
    return engine.new_game(ids, names={p: p for p in ids}, seed=seed)


def force_roles(game, mapping):
    """Deterministically override dealt_role+card for specific players (and recompute
    the wolf/mason/minion groupings). Used to set up reproducible night/vote scenarios
    without fishing for a seed that deals the role we want."""
    for pid, role in mapping.items():
        game["players"][pid]["dealt_role"] = role
        game["players"][pid]["card"] = role
    dealt = lambda p: game["players"][p]["dealt_role"]
    game["wolf_pids"] = [p for p in game["order"] if dealt(p) == "werewolf"]
    game["mason_pids"] = [p for p in game["order"] if dealt(p) == "mason"]
    game["minion_pids"] = [p for p in game["order"] if dealt(p) == "minion"]


def at_step(game, step, role_map=None):
    """Put a freshly-dealt game into NIGHT at a given step, optionally forcing roles."""
    if role_map:
        force_roles(game, role_map)
    engine.start_night(game)
    engine.set_step(game, step)
    return game
