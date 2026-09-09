"""Orbit's versioned browser-serving policy boundary.

The offline search stack has access to a privileged simulator so it can sample
hidden worlds.  A serving policy never does: this module accepts only the
allowlisted seat observation, the server's legal-move list, and a small
serializable memory object.  The same contract is mirrored by
``webapp/public/wasm/orbit-worker.js``.  A trained guide can replace the cheap
ranker later without changing the room protocol.

The function deliberately returns a legal move from the supplied list.  The
server still validates that move against the live engine; the return contract
is a strength boundary, not an authorization boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable

from ..cards import CARDS, FACTIONS, PLANETS
from ..effects import CARD_EFFECTS
from .state import TASK_FIELDS, SCHEMA_VERSION, action_key, rules_fingerprint


SERVING_ABI_VERSION = 1
MODEL_VERSION = 2
ENCODER_VERSION = "orbit-observation-v1"
MODEL_ID = "orbit-hard-v2"
TURN_BUDGET_MS = 5_000
MAIN_ACTION_BUDGET_MS = 3_000
FOLLOWUP_RESERVE_MS = TURN_BUDGET_MS - MAIN_ACTION_BUDGET_MS
MAX_MEMORY_BYTES = 64 * 1024
MAX_BRANCHES = 32
OBSERVATION_KEYS = frozenset((
    "schema", "phase", "turn_pid", "turn_number", "influence",
    "captured_this_turn", "leader", "board_sides", "planet_bonus",
    "technology_bonus", "agent_discard", "bonus_discard", "mulligan_done",
    "pending_pid", "winner", "seat", "players", "agent_deck_count",
    "bonus_deck_count", "pending", "legal_moves",
))

# The shipped Hard policy is intentionally a small, auditable ranker rather
# than a hidden-state model.  These values were selected offline with paired
# self-play and are kept in one map so the Python fallback, browser worker and
# native serving export can be checked against the same policy version.
POLICY_WEIGHTS = {
    "recruit": 0.55,
    "progress": 0.08,
    "cost": 0.0749,
    "column": 0.03,
    "effect": 0.6941,
    "capture": 2.0,
    "near_capture": 0.2,
    "technology": 0.1945,
    "technology_level": 0.0016,
    "leader": 0.0457,
    "leader_animod": 0.05,
    "leader_owned": 0.1,
    "mulligan": 0.01,
    "choice": 0.4,
    "choice_opponent": 0.1,
    "deny": 0.2,
    "choice_capture": 2.0,
    "accept": 0.2,
    "decline": -0.02,
    "tier": 0.059,
    "faction": 0.1,
    "branch_influence": 0.2,
    "branch_resource": 0.1,
    "bonus": 0.1,
    "discard": 0.02,
}
BONUS_POLICY_VALUES = {1: 1.0, 2: 1.2, 3: 4.0, 4: 2.0,
                       5: 1.5, 6: 2.0, 7: 2.0, 8: 2.0}
OBSERVATION_PLAYER_KEYS = frozenset((
    "credits", "zenithium", "columns", "technology", "row_bonuses",
    "captured", "hand_count", "hand",
))


@dataclass
class ServingResult:
    """Result of one bounded policy decision.

    ``__iter__`` keeps the boundary pleasant for small harnesses that prefer
    ``move, memory, diagnostics = choose_move(...)`` while named attributes
    make the network adapter self-documenting.
    """

    move: dict | None
    memory: dict
    diagnostics: dict[str, Any]

    def __iter__(self):
        yield self.move
        yield self.memory
        yield self.diagnostics

    def as_dict(self) -> dict[str, Any]:
        return {
            "move": copy.deepcopy(self.move),
            "memory": copy.deepcopy(self.memory),
            "diagnostics": copy.deepcopy(self.diagnostics),
        }


def serving_manifest() -> dict[str, Any]:
    """Return the compatibility metadata shipped beside the browser worker."""

    return {
        "abi_version": SERVING_ABI_VERSION,
        "model_version": MODEL_VERSION,
        "model_id": MODEL_ID,
        "encoder": ENCODER_VERSION,
        "schema": SCHEMA_VERSION,
        "rules": rules_fingerprint(),
        "turn_budget_ms": TURN_BUDGET_MS,
        "main_action_budget_ms": MAIN_ACTION_BUDGET_MS,
        "followup_reserve_ms": FOLLOWUP_RESERVE_MS,
    }


def model_asset() -> dict[str, Any]:
    """Return the browser asset envelope, including the mechanical card map.

    The card attributes are the stable input vocabulary for both the JS and
    Rust fallbacks.  A future promoted guide can add its weights under the
    same versioned envelope without changing the room protocol.
    """

    payload = serving_manifest()
    payload["cards"] = {
        str(card_id): {
            "cost": int(card["cost"]),
            "planet": card["planet"],
            "faction": card["faction"],
        }
        for card_id, card in sorted(CARDS.items())
    }
    # Effect programs are public card text in structured form.  Shipping them
    # beside the attributes lets the JS fallback rank a card's actual tempo
    # instead of pretending every recruit is interchangeable.
    payload["card_effects"] = {
        str(card_id): copy.deepcopy(CARD_EFFECTS[card_id])
        for card_id in sorted(CARD_EFFECTS)
    }
    payload["policy"] = copy.deepcopy(POLICY_WEIGHTS)
    payload["bonus_policy_values"] = {
        str(token): value for token, value in sorted(BONUS_POLICY_VALUES.items())
    }
    return payload


def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when a cached model/worker belongs to another rules build."""

    if not isinstance(value, dict):
        raise ValueError("Orbit serving manifest must be an object")
    expected = serving_manifest()
    for key in ("abi_version", "model_version", "encoder", "schema", "rules"):
        if value.get(key) != expected[key]:
            raise ValueError(f"Orbit serving manifest {key} mismatch")
    return copy.deepcopy(value)


def write_manifest(path: str | Path) -> dict[str, Any]:
    """Write a deterministic manifest for release tooling and return it."""

    target = Path(path)
    payload = serving_manifest()
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_model_asset(path: str | Path) -> dict[str, Any]:
    """Write the deterministic browser model/fallback asset."""

    target = Path(path)
    payload = model_asset()
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def position_key(observation: dict, legal_moves: Iterable[dict] | None = None) -> str:
    """Hash only policy-visible state and legal actions for stale-reply checks."""

    payload = {
        "observation": observation,
        "legal_moves": list(legal_moves if legal_moves is not None else observation.get("legal_moves", [])),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _default_memory() -> dict[str, Any]:
    return {"version": SERVING_ABI_VERSION, "branches": {}, "history": {"events": []}}


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    except (TypeError, ValueError):
        return MAX_MEMORY_BYTES + 1


def _memory(value: Any) -> dict[str, Any]:
    """Copy and bound client memory; it is a strength hint, never authority."""

    if not isinstance(value, dict):
        return _default_memory()
    result = copy.deepcopy(value)
    try:
        version = int(result.get("version", SERVING_ABI_VERSION))
    except (TypeError, ValueError, OverflowError):
        version = -1
    if version != SERVING_ABI_VERSION:
        result = _default_memory()
    result["version"] = SERVING_ABI_VERSION
    if not isinstance(result.get("branches"), dict):
        result["branches"] = {}
    if not isinstance(result.get("history"), dict):
        result["history"] = {"events": []}
    # Branch entries are a cache, so dropping the oldest ones is always safe.
    branches = result["branches"]
    if len(branches) > MAX_BRANCHES:
        result["branches"] = dict(list(branches.items())[-MAX_BRANCHES:])
    if _json_size(result) <= MAX_MEMORY_BYTES:
        return result
    # A malformed/oversized reply must not grow a persisted room indefinitely.
    history = result.get("history")
    if isinstance(history, dict) and isinstance(history.get("events"), list):
        history["events"] = history["events"][-16:]
    result["branches"] = dict(list(result["branches"].items())[-8:])
    return result if _json_size(result) <= MAX_MEMORY_BYTES else _default_memory()


# Public spelling used by the room adapter.  Keeping the implementation in one
# place prevents a browser-provided memory reply from bypassing the size cap.
normalise_memory = _memory


def _validate_observation(observation: dict, legal_moves: list[dict]) -> None:
    if not isinstance(observation, dict):
        raise ValueError("Orbit serving observation must be an object")
    if set(observation) != OBSERVATION_KEYS:
        raise ValueError("Orbit serving observation fields mismatch")
    if int(observation.get("schema", -1)) != SCHEMA_VERSION:
        raise ValueError("Orbit serving observation schema mismatch")
    seat = observation.get("seat")
    if isinstance(seat, bool) or seat not in (0, 1):
        raise ValueError("Orbit serving observation seat mismatch")
    players = observation.get("players")
    if not isinstance(players, list) or len(players) != 2:
        raise ValueError("Orbit serving observation player shape mismatch")
    for index, player in enumerate(players):
        if not isinstance(player, dict) or set(player) - OBSERVATION_PLAYER_KEYS:
            raise ValueError("Orbit serving observation player fields mismatch")
        if index == seat:
            if "hand" not in player or not isinstance(player["hand"], list):
                raise ValueError("Orbit serving observation own hand mismatch")
        elif "hand" in player:
            raise ValueError("Orbit serving observation opponent hand leaked")
        columns = player.get("columns")
        technology = player.get("technology")
        if (not isinstance(columns, list) or len(columns) != 5
                or any(not isinstance(column, list) for column in columns)
                or not isinstance(technology, list) or len(technology) != 3):
            raise ValueError("Orbit serving observation player shape mismatch")
    pending = observation.get("pending")
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) - {"source", "task", "waiting", "last_planet"}:
            raise ValueError("Orbit serving pending fields mismatch")
        task = pending.get("task")
        if task is not None and (not isinstance(task, dict) or set(task) - TASK_FIELDS):
            raise ValueError("Orbit serving pending task mismatch")
    if not isinstance(legal_moves, list) or any(not isinstance(move, dict) for move in legal_moves):
        raise ValueError("Orbit serving legal moves must be objects")
    advertised = observation.get("legal_moves")
    if advertised is not None:
        if not isinstance(advertised, list) or any(not isinstance(move, dict) for move in advertised):
            raise ValueError("Orbit serving advertised legal moves must be objects")
        expected = sorted(action_key(move) for move in legal_moves)
        actual = sorted(action_key(move) for move in advertised)
        if expected != actual:
            raise ValueError("Orbit serving legal-move list mismatch")


def _card(observation: dict, move: dict) -> tuple[dict | None, dict | None]:
    card_id = move.get("card_id")
    if card_id is None:
        return None, None
    try:
        card = CARDS[int(card_id)]
    except (KeyError, TypeError, ValueError):
        return None, None
    player = observation.get("players", [])[int(observation.get("seat", 0))]
    columns = player.get("columns", [])
    return card, {"player": player, "columns": columns}


def _position(observation: dict, planet: str) -> float:
    """Return public progress toward this seat's side of a planet track."""

    try:
        value = observation.get("influence", [])[PLANETS.index(planet)]
    except (IndexError, TypeError, ValueError):
        return 0.0
    if value is None:
        return 0.0
    try:
        return float(value) * (1.0 if int(observation.get("seat", 0)) == 0 else -1.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _effect_value(tasks: Any, observation: dict, me: dict, them: dict) -> float:
    """Estimate the public tempo of a declarative card effect.

    This is a policy feature, not an engine interpreter.  It deliberately
    reads only public columns/resources and the current seat's own state; the
    server still applies the real effect and validates every follow-up choice.
    Keeping the recursive shape aligned with ``CARD_EFFECTS`` lets a single
    exported card program drive the Python and browser fallbacks.
    """

    if not isinstance(tasks, list):
        return 0.0
    total = 0.0
    leader_owner = (observation.get("leader") or {}).get("owner")
    seat = observation.get("seat")
    for task in tasks:
        if not isinstance(task, dict):
            continue
        kind = task.get("type")
        try:
            amount = float(task.get("amount", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            amount = 0.0
        if kind == "influence":
            planet = task.get("planet")
            total += (0.42 * amount * (1.0 + 0.14 * _position(observation, planet))
                      if planet in PLANETS else 0.48 * amount)
        elif kind == "influence_other":
            total += 0.45 * amount
        elif kind == "split_influence":
            try:
                total += 0.44 * sum(float(value) for value in task.get("amounts", []))
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "adjacent_three":
            try:
                total += 0.42 * (
                    float(task.get("center", 0) or 0)
                    + 2.0 * float(task.get("neighbor", 0) or 0)
                )
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "two_adjacent":
            total += 0.42 * 2.0 * amount
        elif kind == "all_planets":
            total += 0.38 * 5.0 * amount
        elif kind in {"credits", "zenithium"}:
            total += (0.028 if kind == "credits" else 0.09) * amount
        elif kind == "per_tech_first":
            try:
                developed = sum(int(value) >= 1 for value in me.get("technology", []))
                total += 0.055 * developed * amount
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "per_nonempty":
            owner = me if task.get("owner") == "self" else them
            total += 0.025 * sum(bool(column) for column in owner.get("columns", [])) * amount
        elif kind == "mobilize":
            try:
                total += 0.10 * float(task.get("count", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "transfer":
            try:
                total += 0.25 * float(task.get("count", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "exile":
            try:
                total += 0.20 * float(task.get("count", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "exile_tier":
            total += 0.28
        elif kind == "exile_for_matching":
            try:
                total += 0.28 * float(task.get("count", 1) or 1)
            except (TypeError, ValueError, OverflowError):
                pass
        elif kind == "optional_exile_each":
            total += 0.15 * len(task.get("planets", []))
        elif kind == "draw_bonus":
            total += 0.16
        elif kind == "develop":
            total += 0.18
        elif kind == "leader":
            total += 0.28 + (0.08 if (task.get("level", 1) or 1) >= 2 else 0.0)
        elif kind == "take_board_bonus":
            total += 0.20
        elif kind == "spend_tier":
            total += 0.50
        elif kind == "discard_hand":
            total += 0.08
        elif kind == "reset_planet":
            # Resetting a disc creates a fresh race on that planet.  It is a
            # smaller tempo swing than direct influence, but it is still a
            # meaningful card effect and is part of the public card program.
            total += 0.20
        elif kind == "choose_branch":
            branches = task.get("branches", [])
            values = [
                _effect_value(branch.get("tasks", []), observation, me, them)
                for branch in branches if isinstance(branch, dict)
            ]
            total += max(values, default=0.0)
        elif kind == "optional":
            total += 0.75 * _effect_value(task.get("then", []), observation, me, them)
        elif kind == "if_leader":
            factor = 1.0 if leader_owner == seat else 0.2
            total += factor * _effect_value(task.get("then", []), observation, me, them)
        elif kind == "if_credits":
            try:
                factor = 1.0 if float(me.get("credits", 0) or 0) >= float(task.get("amount", 0) or 0) else 0.0
            except (TypeError, ValueError, OverflowError):
                factor = 0.0
            total += factor * _effect_value(task.get("then", []), observation, me, them)
        elif kind == "transfer_each":
            total += 0.25 * sum(bool(column) for column in them.get("columns", []))
    return total


def _effect_score(observation: dict, card_id: int, me: dict, them: dict) -> float:
    try:
        tasks = CARD_EFFECTS.get(int(card_id), [])
    except (TypeError, ValueError, OverflowError):
        tasks = []
    return _effect_value(tasks, observation, me, them)


def _score(observation: dict, move: dict) -> float:
    """A deterministic, public-observation-only Hard policy score."""

    action = move.get("action")
    weights = POLICY_WEIGHTS
    score = 0.0
    seat = int(observation.get("seat", 0))
    players = observation.get("players", [{}, {}])
    me = players[seat] if seat < len(players) else {}
    them = players[1 - seat] if len(players) == 2 else {}
    card, ctx = _card(observation, move)
    pending = observation.get("pending") or {}
    task = pending.get("task") or {}
    task_type = task.get("type")

    if card and ctx:
        columns = ctx["columns"]
        planet = card["planet"]
        try:
            planet_index = PLANETS.index(planet)
            column_len = len(columns[planet_index])
        except (ValueError, IndexError, TypeError):
            column_len = 0
            planet_index = 0
        progress = _position(observation, planet)
        if action == "recruit":
            cost = max(0, int(card["cost"]) - column_len)
            score += (
                weights["recruit"]
                + weights["progress"] * progress
                - weights["cost"] * cost
                + weights["column"] * bool(column_len)
                + weights["effect"] * _effect_score(observation, card["id"], me, them)
            )
            if progress >= 3:
                score += weights["capture"]
            elif progress >= 2:
                score += weights["near_capture"]
        elif action == "technology":
            try:
                level = int(me.get("technology", [0, 0, 0])[FACTIONS.index(card["faction"])])
            except (ValueError, IndexError, TypeError, OverflowError):
                level = 0
            score += weights["technology"] + weights["technology_level"] * (5 - level)
        elif action == "leader":
            score += weights["leader"]
            score += weights["leader_animod"] * (card["faction"] == "animod")
            score += weights["leader_owned"] * ((observation.get("leader") or {}).get("owner") == seat)
    elif action == "mulligan":
        try:
            score += weights["mulligan"] * sum(
                5 - int(CARDS.get(int(card_id), {}).get("cost", 5))
                for card_id in move.get("card_ids", [])
            )
        except (TypeError, ValueError, OverflowError):
            pass

    if move.get("planet") in PLANETS:
        progress = _position(observation, move["planet"])
        score += weights["choice"] * progress
        if task_type in {"transfer", "exile", "exile_for_matching"}:
            try:
                opponent_column = len(them.get("columns", [])[PLANETS.index(move["planet"])])
            except (IndexError, TypeError, ValueError):
                opponent_column = 0
            score += weights["deny"] * opponent_column - weights["choice_opponent"] * progress
        if task_type in {"influence", "influence_other", "split_influence"}:
            try:
                amount = float(task.get("amount", 1) or 1)
            except (TypeError, ValueError, OverflowError):
                amount = 1.0
            if progress + amount >= 4:
                score += weights["choice_capture"]
    if isinstance(move.get("planets"), list):
        score += weights["choice"] * sum(_position(observation, planet) for planet in move["planets"])
    if move.get("accept") is True:
        score += weights["accept"]
    elif move.get("accept") is False:
        score += weights["decline"]
    if "tier" in move:
        try:
            score += weights["tier"] * int(move.get("tier") or 0)
        except (TypeError, ValueError, OverflowError):
            pass
    if move.get("faction") in FACTIONS:
        try:
            score += weights["faction"] * (5 - int(me.get("technology", [0, 0, 0])[FACTIONS.index(move["faction"])]))
        except (IndexError, TypeError, ValueError, OverflowError):
            pass
    if "branch" in move:
        try:
            branch = int(move.get("branch") or 0)
        except (TypeError, ValueError, OverflowError):
            branch = 0
        labels = task.get("branch_labels", []) if isinstance(task, dict) else []
        label = str(labels[branch]).lower() if 0 <= branch < len(labels) else ""
        score += weights["branch_influence"] if any(
            word in label for word in ("influence", "transfer")
        ) else weights["branch_resource"]
    if "bonus_area" in move:
        values = observation.get("planet_bonus", []) if move.get("bonus_area") == "planet" else observation.get("technology_bonus", [])
        labels = PLANETS if move.get("bonus_area") == "planet" else FACTIONS
        try:
            token = values[labels.index(move.get("slot"))]
            score += weights["bonus"] * BONUS_POLICY_VALUES.get(int(token), 0.0)
        except (IndexError, TypeError, ValueError, OverflowError):
            pass
    if "card_id" in move and action == "choose":
        try:
            score -= weights["discard"] * int(CARDS[int(move["card_id"])] ["cost"])
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    return float(score)


def _seeded_tie_index(seed: int, count: int) -> int:
    """Reproduce the incumbent v1 tie stream in offline arena tooling."""

    state = ((int(seed) & 0xFFFFFFFF) ^ 0x9E3779B9) & 0xFFFFFFFF
    state = (state * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
    return state % max(1, int(count))


def choose_move(
    observation: dict,
    legal_moves: list[dict],
    memory: dict | None,
    remaining_turn_budget: int | float,
    seed: int,
) -> ServingResult:
    """Choose one legal move within the versioned browser contract.

    ``remaining_turn_budget`` is in milliseconds.  The ranker itself is
    sub-millisecond on normal positions; the explicit budget is still carried
    through diagnostics and memory so a neural/WASM implementation can spend
    the same five-second total turn budget without changing the protocol.
    """

    started = time.perf_counter()
    moves = [copy.deepcopy(move) for move in (legal_moves or [])]
    _validate_observation(observation, moves)
    budget = max(0.0, float(remaining_turn_budget))
    result_memory = _memory(memory)
    key = position_key(observation, moves)
    action_map = {action_key(move): move for move in moves}
    cached = result_memory.get("branches", {}).get(key)
    reused = False
    chosen: dict | None = None
    if isinstance(cached, dict):
        candidate = cached.get("move")
        if isinstance(candidate, dict) and action_key(candidate) in action_map:
            chosen = action_map[action_key(candidate)]
            reused = True

    if chosen is None and moves:
        scores = [(float(_score(observation, move)), action_key(move), move) for move in moves]
        best = max(item[0] for item in scores)
        ties = [item for item in scores if math.isclose(item[0], best, rel_tol=0.0, abs_tol=1e-12)]
        # All browser workers see the same public position.  A stable final
        # tie-break keeps their vote from turning a tactical tie into a random
        # move, while the seed remains in diagnostics for replay accounting.
        ordered = [item[2] for item in sorted(ties, key=lambda item: item[1])]
        chosen = ordered[-1]

    if chosen is not None:
        branches = result_memory.setdefault("branches", {})
        branches[key] = {"move": copy.deepcopy(chosen), "model": MODEL_ID}
        if len(branches) > MAX_BRANCHES:
            result_memory["branches"] = dict(list(branches.items())[-MAX_BRANCHES:])

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    diagnostics = {
        "abi_version": SERVING_ABI_VERSION,
        "model_version": MODEL_VERSION,
        "model_id": MODEL_ID,
        "encoder": ENCODER_VERSION,
        "schema": SCHEMA_VERSION,
        "rules": rules_fingerprint(),
        "backend": "python-fallback",
        "legal_count": len(moves),
        "position": key,
        "seed": int(seed),
        "elapsed_ms": round(elapsed_ms, 3),
        "remaining_turn_budget": budget,
        "budget_exhausted": budget <= 0,
        "reused_branch": reused,
        "fallback": True,
    }
    return ServingResult(chosen, result_memory, diagnostics)
