"""Small, dependency-free neural policy/value guide for Orbit.

The guide is intentionally plain Python so the Phase 2/3 contracts can be
tested in the repository's normal environment.  It has a 128-wide shared
representation, an action scorer and a scalar value head.  The representation
is built only from the allowlisted observation, a short seat-local recurrent
trace and the legal action, with explicit planet order and card identity;
arbitrary planet permutation is never applied.

This is a training and export boundary, not the final browser implementation.
The JSON layout is stable enough for a later Rust/WASM forward pass and carries
the same rules fingerprint/schema as every other offline artifact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import json
import math
import random
from typing import Iterable

from ..cards import ALL_CARDS, CARDS, FACTIONS, PLANETS
from .state import SCHEMA_VERSION, action_key, observation, rules_fingerprint


# v2 keeps the fixed-width observation contract but reads ALL_CARDS metadata
# for public columns/legal actions, so parity-verified Secret Agents examples
# can be audited without treating expansion cards as malformed input.
ENCODER_VERSION = "orbit-observation-v2"
MODEL_VERSION = 1
OBS_SIZE = 288
ACTION_SIZE = 40
HIDDEN_SIZE = 128


def _one_hot(values: list[float], index: int | None, width: int) -> None:
    for position in range(width):
        values.append(1.0 if index == position else 0.0)


def encode_history(history: dict | None) -> list[float]:
    """Encode a short seat-local recurrent trace without private state."""

    result: list[float] = []
    events = (history or {}).get("events", [])[-8:]
    for event in events:
        public = event.get("public_action")
        payload = json.dumps(public or event.get("changes", {}), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).digest()
        # Stable hash buckets retain sequence identity without leaking the raw
        # display log or any privileged state.
        result.extend(byte / 255.0 for byte in digest[:4])
    result.extend([0.0] * (32 - len(result)))
    return result[:32]


def encode_observation(obs: dict, history: dict | None = None) -> list[float]:
    """Encode the policy observation into a fixed-size float vector."""

    result: list[float] = []
    phase = {"mulligan": 0, "play": 1, "over": 2}.get(obs.get("phase"), 0)
    _one_hot(result, phase, 3)
    result.append(float(obs.get("seat", 0)))
    result.append(min(1.0, max(0.0, float(obs.get("turn_number", 0)) / 120.0)))
    turn = obs.get("turn_pid")
    _one_hot(result, int(turn) if isinstance(turn, int) else None, 2)
    for position in obs.get("influence", []):
        result.append(0.0 if position is None else max(-1.0, min(1.0, float(position) / 4.0)))
    for planet in PLANETS:
        result.append(1.0 if planet in obs.get("captured_this_turn", []) else 0.0)
    leader = obs.get("leader", {})
    _one_hot(result, leader.get("owner") if isinstance(leader.get("owner"), int) else None, 2)
    result.append(min(1.0, float(leader.get("level", 0)) / 2.0))
    for side in obs.get("board_sides", []):
        result.extend((1.0 if int(side) == 1 else 0.0, 1.0 if int(side) == 2 else 0.0))
    for token in list(obs.get("planet_bonus", [])) + list(obs.get("technology_bonus", [])):
        result.append(0.0 if token is None else 1.0)
    result.extend((min(1.0, float(obs.get("agent_deck_count", 0)) / 90.0),
                   min(1.0, float(obs.get("bonus_deck_count", 0)) / 16.0)))

    players = obs.get("players", [])
    for player in players[:2]:
        result.extend((min(1.0, float(player.get("credits", 0)) / 30.0),
                       min(1.0, float(player.get("zenithium", 0)) / 10.0),
                       min(1.0, float(player.get("hand_count", 0)) / 8.0)))
        result.extend(min(1.0, float(value) / 5.0) for value in player.get("technology", []))
        _one_hot(result, len(player.get("row_bonuses", [])), 4)
        result.append(min(1.0, float(len(player.get("captured", []))) / 5.0))
        result.extend(min(1.0, float(len(column)) / 8.0) for column in player.get("columns", []))

    # The root player's hand is the most important private feature.  It is
    # placed before padding and is never replaced by the opposing hand.
    me = int(obs.get("seat", 0))
    own_hand = set(players[me].get("hand", [])) if me < len(players) else set()
    result.extend(1.0 if card_id in own_hand else 0.0 for card_id in sorted(CARDS))

    # Public card attributes for both column boards preserve planet/faction
    # identity while remaining compact.  Counts are enough for the first guide;
    # the full card IDs remain available through the hand and legal action.
    for player in players[:2]:
        for column in player.get("columns", []):
            result.append(min(1.0, float(sum(ALL_CARDS[c]["cost"] for c in column)) / 30.0))
            for faction in FACTIONS:
                result.append(min(1.0, float(sum(ALL_CARDS[c]["faction"] == faction for c in column)) / 8.0))

    pending = obs.get("pending") or {}
    task = pending.get("task") or {}
    task_types = (
        "influence", "influence_other", "split_influence", "optional", "choose_branch",
        "exile", "transfer", "discard_hand", "develop", "exile_tier", "spend_tier",
        "reset_planet", "take_board_bonus", "optional_exile_each", "two_adjacent", "adjacent_three",
    )
    _one_hot(result, task_types.index(task.get("type")) if task.get("type") in task_types else None, len(task_types) + 1)
    result.append(1.0 if pending.get("waiting") else 0.0)
    result.append(min(1.0, float(task.get("amount", 0)) / 8.0))
    result.append(min(1.0, float(task.get("count", 0) if isinstance(task.get("count"), int) else 0) / 8.0))
    result.extend(encode_history(history))

    if len(result) > OBS_SIZE:
        raise ValueError(f"Orbit observation encoder overflow: {len(result)} > {OBS_SIZE}")
    result.extend([0.0] * (OBS_SIZE - len(result)))
    return result


def encode_action(obs: dict, move: dict) -> list[float]:
    """Encode one legal action without consulting hidden state."""

    result: list[float] = []
    actions = ("recruit", "technology", "leader", "mulligan", "choose")
    _one_hot(result, actions.index(move.get("action")) if move.get("action") in actions else None, len(actions) + 1)
    card_id = move.get("card_id")
    result.append(float(int(card_id)) / 600.0 if card_id is not None else 0.0)
    if card_id is not None and int(card_id) in ALL_CARDS:
        card = ALL_CARDS[int(card_id)]
        result.append(float(card["cost"]) / 10.0)
        _one_hot(result, PLANETS.index(card["planet"]), len(PLANETS))
        _one_hot(result, FACTIONS.index(card["faction"]), len(FACTIONS))
    else:
        result.extend([0.0] * (2 + len(PLANETS) + len(FACTIONS)))
    planet = move.get("planet")
    _one_hot(result, PLANETS.index(planet) if planet in PLANETS else None, len(PLANETS))
    selected = move.get("planets", [])
    result.extend(1.0 if p in selected else 0.0 for p in PLANETS)
    result.extend((min(1.0, float(move.get("tier", 0)) / 7.0),
                   min(1.0, float(move.get("cost", 0)) / 12.0),
                   min(1.0, float(move.get("amount", 0)) / 8.0),
                   1.0 if move.get("accept") is True else 0.0,
                   min(1.0, float(move.get("branch", 0)) / 4.0)))
    if len(result) > ACTION_SIZE:
        raise ValueError(f"Orbit action encoder overflow: {len(result)} > {ACTION_SIZE}")
    result.extend([0.0] * (ACTION_SIZE - len(result)))
    return result


def _relu(values: Iterable[float]) -> list[float]:
    return [max(0.0, value) for value in values]


def _dot(weights: list[float], values: list[float]) -> float:
    return sum(weight * value for weight, value in zip(weights, values))


@dataclass
class NeuralGuide:
    """A 128-wide shared policy/value guide with JSON export."""

    model_version = MODEL_VERSION

    rules: str = field(default_factory=rules_fingerprint)
    schema: int = SCHEMA_VERSION
    encoder: str = ENCODER_VERSION
    hidden: int = HIDDEN_SIZE
    obs_weights: list[list[float]] = field(default_factory=list)
    obs_bias: list[float] = field(default_factory=list)
    policy_weights: list[float] = field(default_factory=list)
    policy_bias: float = 0.0
    value_weights: list[float] = field(default_factory=list)
    value_bias: float = 0.0
    examples: int = 0
    epochs: int = 0

    @classmethod
    def random(cls, seed: int = 0) -> "NeuralGuide":
        rng = random.Random(seed)
        scale = 0.025
        return cls(
            obs_weights=[[rng.uniform(-scale, scale) for _ in range(OBS_SIZE)] for _ in range(HIDDEN_SIZE)],
            obs_bias=[0.0] * HIDDEN_SIZE,
            policy_weights=[rng.uniform(-scale, scale) for _ in range(HIDDEN_SIZE + ACTION_SIZE)],
            value_weights=[rng.uniform(-scale, scale) for _ in range(HIDDEN_SIZE)],
        )

    def _check(self, obs: dict) -> None:
        if int(obs.get("schema", self.schema)) != self.schema:
            raise ValueError("Orbit neural guide observation schema mismatch")
        if self.rules != rules_fingerprint() or self.encoder != ENCODER_VERSION or self.hidden != HIDDEN_SIZE:
            raise ValueError("Orbit neural guide rules/encoder mismatch")

    def _hidden(self, obs: dict, history: dict | None = None) -> list[float]:
        encoded = encode_observation(obs, history)
        return _relu([_dot(weights, encoded) + bias for weights, bias in zip(self.obs_weights, self.obs_bias)])

    def _logit(self, hidden: list[float], obs: dict, move: dict) -> float:
        features = hidden + encode_action(obs, move)
        return _dot(self.policy_weights, features) + self.policy_bias

    def priors(self, obs: dict, legal_moves: list[dict], *, history: dict | None = None) -> dict[str, float]:
        self._check(obs)
        if not legal_moves:
            return {}
        hidden = self._hidden(obs, history)
        logits = [self._logit(hidden, obs, move) for move in legal_moves]
        pivot = max(logits)
        values = [math.exp(max(-60.0, min(60.0, score - pivot))) for score in logits]
        total = sum(values) or 1.0
        return {action_key(move): value / total for move, value in zip(legal_moves, values)}

    def value(self, obs: dict, *, history: dict | None = None) -> float:
        self._check(obs)
        hidden = self._hidden(obs, history)
        return math.tanh(_dot(self.value_weights, hidden) + self.value_bias)

    def fit(self, episodes: Iterable, *, epochs: int = 1, learning_rate: float = 0.01) -> int:
        """Fit heads/trunk from search targets and terminal outcomes.

        Censored episodes are excluded entirely.  The value label is always the
        completed seat outcome transformed to [-1, 1]; no resource or short-game
        shaping enters this update.
        """

        rows = []
        for episode in episodes:
            if episode.rules != self.rules:
                raise ValueError("Orbit trajectory rules fingerprint mismatch")
            if int(getattr(episode, "schema", -1)) != self.schema:
                raise ValueError("Orbit trajectory schema mismatch")
            if episode.censored:
                continue
            outcomes = episode.outcomes()
            for step in episode.steps:
                rows.append((step, outcomes[step.actor_seat]))
        for _ in range(max(0, epochs)):
            for step, outcome in rows:
                obs = step.observation
                self._check(obs)
                encoded = encode_observation(obs, getattr(step, "history", None))
                pre = [_dot(weights, encoded) + bias for weights, bias in zip(self.obs_weights, self.obs_bias)]
                hidden = _relu(pre)
                moves = list(step.legal_moves)
                if not moves:
                    continue
                raw_target = step.target or {action_key(step.action): 1.0}
                target = {
                    action_key(move): max(0.0, float(raw_target.get(action_key(move), 0.0)))
                    for move in moves
                }
                target_total = sum(target.values())
                if target_total <= 0:
                    target = {
                        action_key(move): (1.0 if move == step.action else 0.0)
                        for move in moves
                    }
                else:
                    target = {key: value / target_total for key, value in target.items()}
                logits = [self._logit(hidden, obs, move) for move in moves]
                pivot = max(logits)
                exp_values = [math.exp(max(-60.0, min(60.0, value - pivot))) for value in logits]
                total = sum(exp_values) or 1.0
                probs = [value / total for value in exp_values]
                grad_hidden = [0.0] * HIDDEN_SIZE
                policy_hidden_weights = self.policy_weights[:HIDDEN_SIZE]
                grad_policy_bias = 0.0
                for move, probability in zip(moves, probs):
                    error = probability - float(target.get(action_key(move), 0.0))
                    grad_policy_bias += error
                    features = hidden + encode_action(obs, move)
                    for index, feature in enumerate(features):
                        self.policy_weights[index] -= learning_rate * error * feature
                    for index in range(HIDDEN_SIZE):
                        grad_hidden[index] += error * policy_hidden_weights[index]
                self.policy_bias -= learning_rate * grad_policy_bias
                prediction = math.tanh(_dot(self.value_weights, hidden) + self.value_bias)
                value_error = prediction - (2.0 * outcome - 1.0)
                value_gradient = value_error * (1.0 - prediction * prediction)
                value_hidden_weights = self.value_weights[:]
                for index, feature in enumerate(hidden):
                    self.value_weights[index] -= learning_rate * value_gradient * feature
                    grad_hidden[index] += value_gradient * value_hidden_weights[index]
                self.value_bias -= learning_rate * value_gradient
                for index, gradient in enumerate(grad_hidden):
                    if pre[index] > 0:
                        self.obs_bias[index] -= learning_rate * gradient
                        for feature_index, feature in enumerate(encoded):
                            self.obs_weights[index][feature_index] -= learning_rate * gradient * feature
                self.examples += 1
        self.epochs += max(0, epochs)
        return len(rows)

    def as_dict(self) -> dict:
        return {
            "version": MODEL_VERSION,
            "rules": self.rules,
            "schema": self.schema,
            "encoder": self.encoder,
            "hidden": self.hidden,
            "obs_size": OBS_SIZE,
            "action_size": ACTION_SIZE,
            "obs_weights": copy.deepcopy(self.obs_weights),
            "obs_bias": list(self.obs_bias),
            "policy_weights": list(self.policy_weights),
            "policy_bias": self.policy_bias,
            "value_weights": list(self.value_weights),
            "value_bias": self.value_bias,
            "examples": self.examples,
            "epochs": self.epochs,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "NeuralGuide":
        if int(value.get("version", -1)) != MODEL_VERSION:
            raise ValueError("Orbit neural guide version mismatch")
        if value.get("rules") != rules_fingerprint() or int(value.get("schema", -1)) != SCHEMA_VERSION:
            raise ValueError("Orbit neural guide rules/schema mismatch")
        if value.get("encoder") != ENCODER_VERSION or int(value.get("hidden", -1)) != HIDDEN_SIZE:
            raise ValueError("Orbit neural guide encoder mismatch")
        if int(value.get("obs_size", -1)) != OBS_SIZE or int(value.get("action_size", -1)) != ACTION_SIZE:
            raise ValueError("Orbit neural guide dimensions mismatch")
        result = cls(
            rules=value["rules"], schema=int(value["schema"]), encoder=value["encoder"], hidden=int(value["hidden"]),
            obs_weights=[[float(item) for item in row] for row in value["obs_weights"]],
            obs_bias=[float(item) for item in value["obs_bias"]],
            policy_weights=[float(item) for item in value["policy_weights"]], policy_bias=float(value["policy_bias"]),
            value_weights=[float(item) for item in value["value_weights"]], value_bias=float(value["value_bias"]),
            examples=int(value.get("examples", 0)), epochs=int(value.get("epochs", 0)),
        )
        if len(result.obs_weights) != HIDDEN_SIZE or any(len(row) != OBS_SIZE for row in result.obs_weights):
            raise ValueError("Orbit neural guide observation matrix shape mismatch")
        if len(result.obs_bias) != HIDDEN_SIZE:
            raise ValueError("Orbit neural guide observation bias shape mismatch")
        if len(result.policy_weights) != HIDDEN_SIZE + ACTION_SIZE or len(result.value_weights) != HIDDEN_SIZE:
            raise ValueError("Orbit neural guide head shape mismatch")
        return result


class NeuralPolicy:
    """Policy-only view of :class:`NeuralGuide` for algorithm comparisons."""

    def __init__(self, guide: NeuralGuide, *, epsilon: float = 0.04, name: str = "neural"):
        self.guide = guide
        self.epsilon = float(epsilon)
        self.name = name

    def choose(self, game: dict, pid: str, rng: random.Random, *, observation=None, history=None, time_budget=None, belief=None):
        from .. import engine

        obs = observation or globals()["observation"](game, pid)
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        if not moves:
            return None
        if self.epsilon > 0 and rng.random() < self.epsilon:
            return rng.choice(moves)
        priors = self.guide.priors(obs, moves, history=history)
        best = max(priors.values())
        candidates = [move for move in moves if priors[action_key(move)] == best]
        return rng.choice(candidates)
