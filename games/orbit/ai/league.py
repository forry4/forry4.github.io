"""Population self-play and outcome-only policy learning for Orbit.

The first learned artifact is intentionally a dependency-free tabular guide.
It is useful for validating trajectory contracts and league pressure on this
machine before introducing a neural training dependency.  It learns policy
targets from search visits and values from completed-game win/draw/loss only;
censored episodes never become artificial draws.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
import math
import random
from typing import Iterable, Mapping

from .search import (
    Guide,
    HeuristicPolicy,
    InformationSetSearch,
    Policy,
    RandomPolicy,
    SearchConfig,
    SearchPolicy,
    policy_fingerprint,
)
from .neural import NeuralGuide, NeuralPolicy
from .selfplay import Episode, ArenaResult, board_configurations, play_game, run_arena
from .state import SCHEMA_VERSION, action_key, rules_fingerprint
from .. import engine


def observation_key(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass
class TabularModel(Guide):
    """Search-target policy table plus terminal-outcome value table."""

    VERSION = 1

    rules: str = field(default_factory=rules_fingerprint)
    schema: int = SCHEMA_VERSION
    policy_counts: dict[str, dict[str, float]] = field(default_factory=dict)
    value_sum: dict[str, float] = field(default_factory=dict)
    value_count: dict[str, float] = field(default_factory=dict)
    examples: int = 0
    episodes: int = 0
    censored_episodes: int = 0
    include_censored: bool = False

    def _check(self, obs: dict) -> str:
        if int(obs.get("schema", self.schema)) != self.schema:
            raise ValueError("Orbit model observation schema mismatch")
        return observation_key(obs)

    def fit(self, episodes: Iterable[Episode], *, include_censored: bool = False) -> int:
        """Fit policy targets and terminal values from an episode iterable."""

        added = 0
        for episode in episodes:
            if episode.rules != self.rules:
                raise ValueError("Orbit trajectory rules fingerprint mismatch")
            if int(getattr(episode, "schema", -1)) != self.schema:
                raise ValueError("Orbit trajectory schema mismatch")
            if episode.censored:
                self.censored_episodes += 1
            if episode.censored and not include_censored:
                continue
            outcomes = episode.outcomes() if not episode.censored else None
            for step in episode.steps:
                key = self._check(step.observation)
                bucket = self.policy_counts.setdefault(key, {})
                target = step.target or {action_key(step.action): 1.0}
                for move_key, probability in target.items():
                    if probability > 0:
                        bucket[move_key] = bucket.get(move_key, 0.0) + float(probability)
                # An explicitly included censored episode can contribute policy
                # targets, but it never manufactures a draw/value label.
                if outcomes is not None:
                    self.value_sum[key] = self.value_sum.get(key, 0.0) + (2.0 * outcomes[step.actor_seat] - 1.0)
                    self.value_count[key] = self.value_count.get(key, 0.0) + 1.0
                self.examples += 1
                added += 1
            self.episodes += 1
        self.include_censored = bool(include_censored)
        return added

    def priors(self, obs: dict, legal_moves: list[dict], *, history: dict | None = None) -> dict[str, float]:
        key = self._check(obs)
        counts = self.policy_counts.get(key, {})
        # Dirichlet-like floor keeps an unseen legal action discoverable after
        # a rules or encoder change while preserving learned search visits.
        values = {action_key(move): counts.get(action_key(move), 0.0) + 0.25 for move in legal_moves}
        total = sum(values.values()) or 1.0
        return {move_key: value / total for move_key, value in values.items()}

    def value(self, obs: dict, *, history: dict | None = None) -> float:
        key = self._check(obs)
        count = self.value_count.get(key, 0.0)
        return max(-1.0, min(1.0, self.value_sum.get(key, 0.0) / count)) if count else 0.0

    def action_score(self, obs: dict, move: dict) -> float:
        key = self._check(obs)
        count = self.policy_counts.get(key, {}).get(action_key(move), 0.0)
        return math.log1p(max(0.0, count))

    def as_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "schema": self.schema,
            "rules": self.rules,
            "policy_counts": copy.deepcopy(self.policy_counts),
            "value_sum": dict(self.value_sum),
            "value_count": dict(self.value_count),
            "examples": self.examples,
            "episodes": self.episodes,
            "censored_episodes": self.censored_episodes,
            "include_censored": self.include_censored,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "TabularModel":
        if int(value.get("version", -1)) != cls.VERSION:
            raise ValueError("Orbit tabular model version mismatch")
        if value.get("rules") != rules_fingerprint() or int(value.get("schema", -1)) != SCHEMA_VERSION:
            raise ValueError("Orbit tabular model rules/schema mismatch")
        return cls(
            rules=value["rules"],
            schema=int(value["schema"]),
            policy_counts={str(k): {str(a): float(n) for a, n in bucket.items()} for k, bucket in value["policy_counts"].items()},
            value_sum={str(k): float(v) for k, v in value["value_sum"].items()},
            value_count={str(k): float(v) for k, v in value["value_count"].items()},
            examples=int(value.get("examples", 0)),
            episodes=int(value.get("episodes", 0)),
            censored_episodes=int(value.get("censored_episodes", 0)),
            include_censored=bool(value.get("include_censored", False)),
        )


class TabularPolicy:
    """A policy-only guide with deterministic legal-action validation."""

    def __init__(self, model: TabularModel, *, epsilon: float = 0.04, name: str = "learner"):
        self.model = model
        self.epsilon = float(epsilon)
        self.name = name

    def choose(self, game: dict, pid: str, rng: random.Random, *, observation=None, history=None, time_budget=None, belief=None):
        obs = observation or globals()["observation"](game, pid)
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        if not moves:
            return None
        if self.epsilon > 0 and rng.random() < self.epsilon:
            return rng.choice(moves)
        scores = [self.model.action_score(obs, move) for move in moves]
        best = max(scores)
        return moves[next(index for index, score in enumerate(scores) if score == best)]


@dataclass
class Member:
    member_id: str
    category: str
    policy_name: str
    parent_id: str | None = None
    seed: int = 0
    generation: int = 0
    active: bool = True
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "member_id": self.member_id,
            "category": self.category,
            "policy_name": self.policy_name,
            "parent_id": self.parent_id,
            "seed": self.seed,
            "generation": self.generation,
            "active": self.active,
            "metadata": copy.deepcopy(self.metadata),
        }


class League:
    """Historical population plus empirical game-theoretic opponent mix."""

    CATEGORIES = frozenset({"champion", "learner", "specialist", "exploiter"})

    def __init__(self, *, rules: str | None = None, schema: int = SCHEMA_VERSION):
        self.rules = rules or rules_fingerprint()
        self.schema = int(schema)
        if self.rules != rules_fingerprint() or self.schema != SCHEMA_VERSION:
            raise ValueError("Orbit league rules/schema mismatch")
        self.members: dict[str, Member] = {}
        self.matchups: list[dict] = []
        self.generation = 0

    def add_member(
        self,
        member_id: str,
        policy: Policy,
        *,
        category: str = "learner",
        parent_id: str | None = None,
        seed: int = 0,
        metadata: dict | None = None,
    ) -> Member:
        if category not in self.CATEGORIES:
            raise ValueError(f"unknown Orbit league category: {category}")
        if member_id in self.members:
            raise ValueError(f"duplicate Orbit league member: {member_id}")
        member = Member(
            member_id=member_id,
            category=category,
            policy_name=getattr(policy, "name", policy.__class__.__name__),
            parent_id=parent_id,
            seed=int(seed),
            generation=self.generation,
            metadata={"fingerprint": policy_fingerprint(policy), **(metadata or {})},
        )
        self.members[member_id] = member
        return member

    def retain(self, member_id: str, active: bool = True) -> None:
        self.members[member_id].active = bool(active)

    def record_match(self, candidate: str, opponent: str, result: ArenaResult) -> None:
        if candidate not in self.members or opponent not in self.members:
            raise ValueError("Orbit matchup must reference retained members")
        if result.rules != self.rules:
            raise ValueError("Orbit matchup rules fingerprint mismatch")
        if int(result.schema) != self.schema:
            raise ValueError("Orbit matchup schema mismatch")
        self.matchups.append({
            "candidate": candidate,
            "opponent": opponent,
            "score": result.pair_score,
            "games": result.games,
            "censored": result.censored,
            "by_board": copy.deepcopy(result.by_board),
        })

    def _eligible(self, exclude: str | None = None) -> list[Member]:
        return [member for member in self.members.values() if member.active and member.member_id != exclude]

    def _egt_weights(self, eligible: list[Member]) -> list[float]:
        """Regret-matching weights from recorded, completed matchups.

        A member receives weight for positive empirical regret: how much a
        hypothetical best response has outscored the population against that
        member.  With no evidence every retained member is uniform.
        """

        ids = {member.member_id for member in eligible}
        payoffs: dict[tuple[str, str], list[float]] = {}
        for match in self.matchups:
            if match["candidate"] in ids and match["opponent"] in ids:
                payoffs.setdefault((match["candidate"], match["opponent"]), []).append(float(match["score"]))
        weights = []
        for member in eligible:
            against = [
                statistics_mean(values)
                for (candidate, opponent), values in payoffs.items()
                if opponent == member.member_id
            ]
            baseline = statistics_mean(against) if against else 0.5
            best = max(against, default=baseline)
            weights.append(max(0.01, 1.0 + 2.0 * max(0.0, best - baseline)))
        total = sum(weights) or 1.0
        return [weight / total for weight in weights]

    def sample_opponent(self, rng: random.Random, *, exclude: str | None = None) -> tuple[str, str]:
        eligible = self._eligible(exclude)
        if not eligible:
            raise ValueError("Orbit league has no eligible opponents")
        buckets = {
            "egt": [member for member in eligible if member.active],
            "diverse": list(eligible),
            "exploiter": [member for member in eligible if member.category == "exploiter"],
        }
        requested = [("egt", 0.50), ("diverse", 0.25), ("exploiter", 0.25)]
        available = [(name, weight) for name, weight in requested if buckets[name]]
        total = sum(weight for _, weight in available) or 1.0
        bucket = rng.choices([name for name, _ in available], weights=[weight / total for _, weight in available], k=1)[0]
        candidates = buckets[bucket]
        if bucket == "egt":
            weights = self._egt_weights(candidates)
            chosen = rng.choices(candidates, weights=weights, k=1)[0]
        else:
            chosen = rng.choice(candidates)
        return chosen.member_id, bucket

    def as_dict(self) -> dict:
        return {
            "version": 1,
            "rules": self.rules,
            "schema": self.schema,
            "generation": self.generation,
            "members": [member.as_dict() for member in self.members.values()],
            "matchups": copy.deepcopy(self.matchups),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "League":
        if int(value.get("version", -1)) != 1:
            raise ValueError("Orbit league version mismatch")
        result = cls(rules=value.get("rules"), schema=int(value.get("schema", -1)))
        result.generation = int(value.get("generation", 0))
        for raw in value.get("members", []):
            member = Member(
                member_id=raw["member_id"], category=raw["category"], policy_name=raw["policy_name"],
                parent_id=raw.get("parent_id"), seed=int(raw.get("seed", 0)),
                generation=int(raw.get("generation", 0)), active=bool(raw.get("active", True)),
                metadata=copy.deepcopy(raw.get("metadata", {})),
            )
            if member.category not in result.CATEGORIES:
                raise ValueError("unknown Orbit league category")
            result.members[member.member_id] = member
        result.matchups = copy.deepcopy(value.get("matchups", []))
        return result


def statistics_mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.5


def generate_bootstrap(
    *,
    games: int = 64,
    seed: int = 0,
    search_config: SearchConfig | None = None,
    max_decisions: int = 1600,
) -> list[Episode]:
    """Generate baseline/search games for the first population model."""

    config = search_config or SearchConfig(simulations=64, time_limit=0.05)
    search = SearchPolicy(InformationSetSearch(config), name="search-bootstrap")
    heuristic = HeuristicPolicy()
    random_policy = RandomPolicy()
    result = []
    for index in range(max(0, games)):
        # Search examples dominate the bootstrap, but random and heuristic play
        # keep the table from collapsing onto one narrow style.
        mode = index % 4
        if mode == 0:
            policies = (search, heuristic)
        elif mode == 1:
            policies = (heuristic, search)
        elif mode == 2:
            policies = (search, random_policy)
        else:
            policies = (heuristic, random_policy)
        config_board = board_configurations()[index % 8]
        result.append(play_game(policies, seed=seed + index * 7919, configuration=config_board, max_decisions=max_decisions))
    return result


def train_candidate(
    episodes: Iterable[Episode],
    *,
    name: str = "learner",
    epsilon: float = 0.04,
) -> TabularPolicy:
    model = TabularModel()
    model.fit(episodes)
    return TabularPolicy(model, epsilon=epsilon, name=name)


def train_neural_candidate(
    episodes: Iterable[Episode],
    *,
    seed: int = 0,
    epochs: int = 1,
    learning_rate: float = 0.01,
    epsilon: float = 0.04,
    name: str = "neural",
) -> NeuralPolicy:
    """Train the fixed 128-wide guide from completed search episodes."""

    guide = NeuralGuide.random(seed)
    guide.fit(episodes, epochs=epochs, learning_rate=learning_rate)
    return NeuralPolicy(guide, epsilon=epsilon, name=name)


@dataclass
class CycleReport:
    generation: int
    candidate_id: str
    training_episodes: int
    training_examples: int
    censored_episodes: int
    opponent_buckets: dict[str, int]
    evaluations: dict[str, dict]

    def as_dict(self) -> dict:
        return {
            "generation": self.generation,
            "candidate_id": self.candidate_id,
            "training_episodes": self.training_episodes,
            "training_examples": self.training_examples,
            "censored_episodes": self.censored_episodes,
            "opponent_buckets": dict(self.opponent_buckets),
            "evaluations": copy.deepcopy(self.evaluations),
        }


def run_population_cycle(
    league: League,
    policies: Mapping[str, Policy],
    *,
    parent_id: str,
    data_policy: Policy | None = None,
    episodes: int = 32,
    seed: int = 0,
    max_decisions: int = 1600,
    eval_pairs: int = 0,
) -> tuple[TabularPolicy, CycleReport]:
    """Train one learner against the 50/25/25 league mixture.

    ``data_policy`` is normally the current search champion.  The candidate is
    trained from its visit targets, while opponents are sampled from the
    empirical game-theoretic, diverse and exploiter buckets.  Promotion is a
    later gate; this function records evaluations but never silently replaces a
    champion.
    """

    if parent_id not in league.members or parent_id not in policies:
        raise ValueError("Orbit cycle parent must be a retained policy")
    trainer = data_policy or policies[parent_id]
    rng = random.Random(seed)
    collected: list[Episode] = []
    buckets = {"egt": 0, "diverse": 0, "exploiter": 0}
    for index in range(max(0, episodes)):
        opponent_id, bucket = league.sample_opponent(rng, exclude=parent_id)
        buckets[bucket] += 1
        opponent = policies[opponent_id]
        board = board_configurations()[index % 8]
        assignment = (trainer, opponent) if index % 2 == 0 else (opponent, trainer)
        collected.append(play_game(
            assignment,
            seed=seed + index * 104729,
            configuration=board,
            max_decisions=max_decisions,
        ))
    candidate = train_candidate(collected, name=f"learner-g{league.generation + 1}")
    candidate_id = f"learner-{league.generation + 1}-{seed}"
    league.generation += 1
    league.add_member(candidate_id, candidate, category="learner", parent_id=parent_id, seed=seed, metadata={"training_episodes": len(collected)})
    policies[candidate_id] = candidate
    evaluations: dict[str, dict] = {}
    if eval_pairs:
        for opponent_id in sorted(league.members):
            if opponent_id == candidate_id or opponent_id not in policies:
                continue
            result = run_arena(candidate, policies[opponent_id], pairs=eval_pairs, seed=seed, max_decisions=max_decisions)
            league.record_match(candidate_id, opponent_id, result)
            evaluations[opponent_id] = result.as_dict()
    return candidate, CycleReport(
        generation=league.generation,
        candidate_id=candidate_id,
        training_episodes=len(collected),
        training_examples=sum(len(episode.steps) for episode in collected if not episode.censored),
        censored_episodes=sum(1 for episode in collected if episode.censored),
        opponent_buckets=buckets,
        evaluations=evaluations,
    )
