"""Shared test helpers for the CoC engine tests."""
from games.castles_of_crimson import engine

# Board 1 has burgundy at (0,0) — use as the default starting-castle choice in tests.
DEFAULT_CASTLE = "0,0"


def complete_setup(g, castle_sids=None):
    """Advance through the setup phase (each player picks a starting castle).

    castle_sids: optional {pid: space_id} override; defaults to DEFAULT_CASTLE.
    After this call g["phase"] == "playing" and dice are rolled for round 1.
    """
    overrides = castle_sids or {}
    while g["phase"] == "setup":
        pid = g["turn"]
        legal = {m["space_id"] for m in engine.legal_moves(g, pid)
                 if m["type"] == "place_starting_castle"}
        if pid in overrides:
            sid = overrides[pid]
        elif DEFAULT_CASTLE in legal:
            # Board 1 (default) has burgundy at (0,0); board-1 tests rely on this.
            sid = DEFAULT_CASTLE
        else:
            # Other boards: pick any legal burgundy space deterministically.
            sid = sorted(legal)[0]
        ok, err = engine.apply_move(g, pid, {"type": "place_starting_castle", "space_id": sid})
        assert ok, f"complete_setup failed for {pid} at {sid}: {err}"
    return g
