"""Lossless semantic feature contract for the next Orbit learner.

This is the auditable input representation, not a tensor layout or a model.
Paths identify roles/positions; categorical values need embeddings in the
trainer. Container lengths preserve empty/absent distinctions. No sequence is
truncated and no number is clipped. The legacy guide/serving ABI is unchanged.
Only observation() and the matching seat-local Session history belong here.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Iterable

from ..cards import CARDS
from .state import SCHEMA_VERSION, TASK_FIELDS

ENCODER_VERSION = "orbit-semantic-v1"
GROUP_FIELDS = {
    "turn": ("schema", "seat", "phase", "turn_pid", "turn_number", "mulligan_done", "winner"),
    "captures": ("influence", "captured_this_turn"),
    "technology": ("board_sides",),
    "bonuses": ("planet_bonus", "technology_bonus", "bonus_discard", "bonus_deck_count"),
    "leader": ("leader",),
    "public_cards": ("agent_discard", "agent_deck_count"),
    "pending": ("pending", "pending_pid"),
    "legal_actions": ("legal_moves",),
}
PLAYER_GROUPS = {
    "resources": ("credits", "zenithium", "hand_count"),
    "tableau": ("columns",),
    "technology": ("technology",),
    "bonuses": ("row_bonuses",),
    "captures": ("captured",),
    "own_hand": ("hand",),
}
FEATURE_GROUPS = frozenset((*GROUP_FIELDS, *PLAYER_GROUPS, "history"))


@dataclass(frozen=True)
class FeatureToken:
    group: str
    path: tuple[str | int, ...]
    kind: str
    value: str | float | int | bool | None


def _keys(value: dict, allowed: Iterable[str], where: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    extra = value.keys() - set(allowed)
    if extra:
        raise ValueError(f"Unreviewed {where} fields: {sorted(extra)}")


def validate_observation(obs: dict) -> None:
    """Fail closed on schema drift or a privileged native-state input."""
    allowed = {key for fields in GROUP_FIELDS.values() for key in fields} | {"players"}
    _keys(obs, allowed, "observation")
    if obs.keys() != allowed:
        raise ValueError("Incomplete observation")
    if obs["schema"] != SCHEMA_VERSION or obs["seat"] not in (0, 1):
        raise ValueError("Observation schema/seat mismatch")
    if len(obs["players"]) != 2:
        raise ValueError("Expected two players")
    fields = {key for keys in PLAYER_GROUPS.values() for key in keys}
    for seat, player in enumerate(obs["players"]):
        expected = fields if seat == obs["seat"] else fields - {"hand"}
        _keys(player, expected, "player")
        if player.keys() != expected:
            raise ValueError("Incomplete player observation")
    _keys(obs["leader"], ("owner", "level"), "leader")
    pending = obs["pending"]
    if pending is not None:
        _keys(pending, ("source", "task", "last_planet", "waiting"), "pending")
        if "task" in pending:
            if obs["pending_pid"] != obs["seat"]:
                raise ValueError("Opposing private pending task")
            _keys(pending["task"], TASK_FIELDS, "pending task")


def _walk(group: str, path: tuple, value):
    if isinstance(value, dict):
        yield FeatureToken(group, path, "object", len(value))
        for key in sorted(value):
            yield from _walk(group, (*path, key), value[key])
    elif isinstance(value, list):
        yield FeatureToken(group, path, "sequence", len(value))
        for index, item in enumerate(value):
            yield from _walk(group, (*path, index), item)
    elif value is None:
        yield FeatureToken(group, path, "missing", None)
    elif isinstance(value, bool):
        yield FeatureToken(group, path, "boolean", value)
    elif isinstance(value, (float, int)):
        if not math.isfinite(value):
            raise ValueError("Non-finite observation feature")
        yield FeatureToken(group, path, "number", value)
    elif isinstance(value, str):
        yield FeatureToken(group, path, "category", value)
    else:
        raise ValueError(f"Unsupported feature at {path}")


def _card_attributes(group: str, path: tuple, cards: list):
    for index, card_id in enumerate(cards):
        card = CARDS[card_id]
        yield from _walk(group, (*path, index, "attributes"), {
            key: card[key] for key in ("id", "cost", "planet", "faction")
        })


def encode_features(obs: dict, history: dict | None = None, *,
                    omit: Iterable[str] = ()) -> tuple[FeatureToken, ...]:
    """Encode complete reviewed inputs; explicit group omission enables ablations.

    Omissions remove representation groups, not all correlated information:
    e.g. history/legal actions can also reveal resources. Report them as such.
    Validation runs BEFORE omission so an ablation cannot bypass the boundary.
    """
    validate_observation(obs)
    omitted = frozenset(omit)
    if omitted - FEATURE_GROUPS:
        raise ValueError(f"Unknown feature groups: {sorted(omitted - FEATURE_GROUPS)}")
    tokens = []
    for group, fields in GROUP_FIELDS.items():
        for key in fields:
            tokens.extend(_walk(group, (key,), obs[key]))
    for seat, player in enumerate(obs["players"]):
        for group, fields in PLAYER_GROUPS.items():
            for key in fields:
                if key in player:
                    path = ("players", seat, key)
                    tokens.extend(_walk(group, path, player[key]))
                    if key == "hand":
                        tokens.extend(_card_attributes(group, path, player[key]))
                    elif key == "columns":
                        for index, column in enumerate(player[key]):
                            tokens.extend(_card_attributes(group, (*path, index), column))
    if history is not None:
        _keys(history, ("initial", "events"), "history")
        current = copy.deepcopy(history["initial"])
        validate_observation(current)
        if current["seat"] != obs["seat"]:
            raise ValueError("History seat mismatch")
        for event in history["events"]:
            _keys(event, ("actor", "changes", "public_action", "own_action"), "history event")
            if "own_action" in event and event["actor"] != obs["seat"]:
                raise ValueError("Opposing private history action")
            current.update(copy.deepcopy(event["changes"]))
            validate_observation(current)
            if current["seat"] != obs["seat"]:
                raise ValueError("History seat mismatch")
        if current != obs:
            raise ValueError("History does not reconstruct observation")
        tokens.extend(_walk("history", ("history",), history))
    return tuple(token for token in tokens if token.group not in omitted)
