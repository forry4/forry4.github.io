"""Games package registry.

Each game package should expose a `register_routes(app)` function and optional metadata.
This module can be expanded to auto-register games into the FastAPI app later.
"""

from importlib import import_module

def list_games():
    # naive: look for installed game packages under the games namespace
    # For now, return a static list
    return ["spender"]

def load_game(name: str):
    mod = import_module(f"games.{name}")
    return mod
