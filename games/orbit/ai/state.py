"""Versioned native-state bridge and allowlisted, seat-local observations.

`native_state` is privileged simulator input. `observation` is the ONLY input
for a policy/belief. They deliberately have different schemas.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .. import engine
from ..cards import FACTIONS, PLANETS

SCHEMA_VERSION = 1
TASK_FIELDS = frozenset((
    "type", "amount", "target", "planet", "exclude", "restriction", "distinct_from",
    "selected", "amounts", "label", "cost", "count", "done", "used", "owner", "distinct",
    "reward", "faction", "discount", "lowest", "tiers", "planets", "index", "center",
    "neighbor", "influence_each", "require_full", "one_at_a_time", "options", "branch_labels",
))


def rules_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in ("engine.py", "effects.py", "cards.py", "boards.py", "data/bga_reference.json"):
        digest.update(name.encode())
        digest.update(root.joinpath(name).read_text(encoding="utf-8").replace("\r\n", "\n").encode())
    return digest.hexdigest()


def _with_seat_actors(value, order: list[str]):
    """Rewrite every ``actor`` pid to its seat index, recursively.

    Shared by `native_state` and `pending_chain` deliberately: they describe the
    same structure to the same Rust reader, and a second copy of this walk is a
    second thing to keep in step.
    """

    if isinstance(value, list):
        return [_with_seat_actors(item, order) for item in value]
    if isinstance(value, dict):
        return {
            key: (order.index(item) if item is not None else None) if key == "actor"
            else _with_seat_actors(item, order)
            for key, item in value.items()
        }
    return value


def pending_chain(game: dict) -> dict | None:
    """The whole pending chain, as data a client-side search can rebuild from.

    WHY THIS IS SENT AT ALL.  `State::from_observation` refuses any position with
    a pending chain, because `observation()` redacts the effect queue to its
    FIRST task -- so the served Expert could not rebuild an effect-resolution
    position and handed every one of them to the 1-ply ranker instead of
    searching it.  That is 45.0% of all decisions with a real choice (10,537 of
    23,394 over 300 games).  This is the missing half.

    WHY IT IS NOT A LEAK.  Every task is generated from the played card's STATIC
    effect program, which is public card text in structured form and already
    ships to the browser inside `orbit-model.json`.  The only fields a task
    accumulates while resolving are planets (`selected`, `used`), counters
    (`done`, `index`, `count`) and `options`, which is the legal-move list the
    client is handed anyway; `context` holds exactly one key, `last_planet`,
    which the redacted observation already exposes.  The Rust gate
    `the_pending_chain_carries_no_hidden_cards` holds that to real positions
    rather than to this docstring.

    WHY IT IS SEPARATE FROM `observation`.  That projection is the frozen policy
    input: its key set is asserted in `main._OBS_KEYS` and `serving`, it is
    stored in game history and compared for equality, and it feeds the encoder.
    Adding a key there is a schema change with a migration.  This rides
    ALONGSIDE the observation instead, and a client that ignores it gets exactly
    today's behaviour -- so the two sides can deploy in either order.
    """

    if not game.get("pending"):
        return None
    return copy.deepcopy(_with_seat_actors(game["pending"], game["order"]))


def native_state(game: dict) -> dict:
    """Lossless mechanical state except presentation and implementation-specific RNG.

    The caller supplies shuffle outcomes separately when doing parity. Native
    simulation has its own RNG; neither RNG is a policy input.
    """
    order = game["order"]
    seat = lambda pid: order.index(pid) if pid is not None else None
    actors = lambda value: _with_seat_actors(value, order)

    players = []
    for pid in order:
        p = game["players"][pid]
        players.append({
            "credits": p["credits"], "zenithium": p["zenithium"],
            "hand": list(p["hand"]), "columns": [list(p["columns"][k]) for k in PLANETS],
            "technology": [p["technology"][k] for k in FACTIONS],
            "row_bonuses": list(p["row_bonuses"]),
            "captured": [PLANETS.index(k) for k in p["captured"]],
        })
    return {
        "schema": SCHEMA_VERSION, "phase": game["phase"], "players": players,
        "turn_pid": seat(game["turn_pid"]), "turn_number": game["turn_number"],
        "influence": [game["influence"][k] for k in PLANETS],
        "captured_this_turn": [PLANETS.index(k) for k in game["captured_this_turn"]],
        "leader": {"owner": seat(game["leader"]["owner"]), "level": game["leader"]["level"]},
        "board_sides": [game["board_sides"][k] for k in FACTIONS],
        "planet_bonus": [game["planet_bonus"][k] for k in PLANETS],
        "technology_bonus": [game["technology_bonus"][k] for k in FACTIONS],
        **{k: list(game[k]) for k in ("agent_deck", "agent_discard", "bonus_deck", "bonus_discard")},
        "mulligan_done": [seat(pid) for pid in game["mulligan_done"]],
        "pending": actors(game["pending"]), "pending_pid": seat(game["pending_pid"]),
        "winner": seat(game["winner"]),
    }


def observation(game: dict, pid: str) -> dict:
    """Explicit policy schema. No logs, names, deck order, RNG, or opposing hand.

    Even terminal observations keep the opponent hand hidden: a terminal reveal
    must not accidentally become a recurrent input preceding the final decision.
    """
    me = game["order"].index(pid)
    state = native_state(game)
    keys = ("schema", "phase", "turn_pid", "turn_number", "influence", "captured_this_turn",
            "leader", "board_sides", "planet_bonus", "technology_bonus", "agent_discard",
            "bonus_discard", "mulligan_done", "pending_pid", "winner")
    result = {k: state[k] for k in keys}
    result["seat"] = me
    result["players"] = []
    for index, player in enumerate(state["players"]):
        visible = {k: player[k] for k in ("credits", "zenithium", "columns", "technology", "row_bonuses", "captured")}
        visible["hand_count"] = len(player["hand"])
        if index == me:
            visible["hand"] = sorted(player["hand"])
        result["players"].append(visible)
    result["agent_deck_count"] = len(state["agent_deck"])
    result["bonus_deck_count"] = len(state["bonus_deck"])
    # Narrow the existing recipient-specific task view again: a future internal
    # engine field must not silently become a policy feature.
    pending = engine.player_view(game, pid)["pending"]
    result["pending"] = None
    if pending:
        result["pending"] = {"source": pending["source"]}
        if game["pending_pid"] == pid:
            result["pending"]["task"] = {k: v for k, v in pending["task"].items() if k in TASK_FIELDS}
            result["pending"]["last_planet"] = game["pending"]["context"].get("last_planet")
        else:
            result["pending"]["waiting"] = True
    result["legal_moves"] = sorted(engine.legal_moves(game, pid), key=action_key)
    return copy.deepcopy(result)


def action_key(move: dict) -> str:
    """All fields participate: `choose` has many unrelated payload shapes."""
    return json.dumps(move, sort_keys=True, separators=(",", ":"))
