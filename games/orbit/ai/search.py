"""Offline information-set search and policy baselines for Orbit.

The search deliberately sits above the Python rules engine during this phase.
It samples hidden worlds from an observation (or a :class:`HistoryBelief`),
then runs a PUCT tree over the root player's information states.  Opponent
decisions are delegated to a frozen policy that receives that opponent's own
simulated view.  The evaluator only reads public state and the root player's
visible hand, so a true hidden hand cannot become a feature by accident.

This is a measured baseline, not a claim of equilibrium solving.  The same
``Decision`` object records root visit targets for Phase 3 training and keeps
the neural-guide boundary ready for a later Rust/WASM model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import json
import math
import random
import time
from typing import Any, Callable, Iterable, Protocol

from .. import engine
from ..cards import CARDS, FACTIONS, PLANETS
from .belief import HistoryBelief, sample_hidden
from .state import action_key, observation


class Policy(Protocol):
    """The small offline policy contract used by the arena.

    ``game`` is available to the offline simulator so it can validate and
    apply a returned move.  A policy implementation must restrict its own
    features to ``observation`` and ``history``; search uses ``game`` only to
    create determinized simulations.
    """

    name: str

    def choose(
        self,
        game: dict,
        pid: str,
        rng: random.Random,
        *,
        observation: dict | None = None,
        history: dict | None = None,
        time_budget: float | None = None,
        belief: HistoryBelief | None = None,
    ) -> "Decision | dict | None": ...


class Guide(Protocol):
    """Optional policy/value head consumed by PUCT.

    Guides are passed an allowlisted observation only.  Returning no prior for
    an action is legal; search supplies a small heuristic prior in that case.
    """

    def priors(self, observation: dict, legal_moves: list[dict], *, history: dict | None = None) -> dict[str, float]: ...

    def value(self, observation: dict, *, history: dict | None = None) -> float: ...


@dataclass
class Decision:
    move: dict | None
    stats: list[dict] = field(default_factory=list)
    root_value: float = 0.0
    simulations: int = 0
    elapsed: float = 0.0
    censored: bool = False

    def target(self) -> dict[str, float]:
        """Return visit-normalised search targets keyed by action identity."""

        total = sum(int(item.get("visits", 0)) for item in self.stats)
        if not total:
            return {item["key"]: 1.0 / len(self.stats) for item in self.stats} if self.stats else {}
        return {item["key"]: int(item.get("visits", 0)) / total for item in self.stats}


@dataclass(frozen=True)
class SearchConfig:
    simulations: int = 256
    time_limit: float | None = 0.25
    max_depth: int = 96
    exploration: float = 1.35
    particles: int = 1
    temperature: float = 0.0

    def as_dict(self) -> dict:
        return {
            "simulations": self.simulations,
            "time_limit": self.time_limit,
            "max_depth": self.max_depth,
            "exploration": self.exploration,
            "particles": self.particles,
            "temperature": self.temperature,
        }


@dataclass
class _Node:
    prior: float = 0.0
    visits: int = 0
    value_sum: float = 0.0
    children: dict[str, "_Node"] = field(default_factory=dict)
    moves: dict[str, dict] = field(default_factory=dict)

    @property
    def mean(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0


def _actor(game: dict) -> str | None:
    if engine.is_over(game):
        return None
    if game.get("pending"):
        return game.get("pending_pid")
    if game.get("phase") == "mulligan":
        return next((pid for pid in game["order"] if pid not in game["mulligan_done"]), None)
    return game.get("turn_pid")


def _save_private_rng(game: dict, seed: int) -> None:
    """Give a determinized world a fresh hidden shuffle stream."""

    local = random.Random(seed)
    state = local.getstate()
    game["rng_state"] = [state[0], list(state[1]), state[2]]


def determinize(
    game: dict,
    pid: str,
    rng: random.Random,
    belief: HistoryBelief | None = None,
) -> dict:
    """Create one feasible world without reading the true hidden pools.

    Public columns/discards and the root player's hand are copied from the
    current game.  The opponent hand, Agent deck, bonus deck and future shuffle
    stream are all replaced from a belief sample.  The source ``game`` is never
    mutated.
    """

    world = copy.deepcopy(game)
    obs = observation(game, pid)
    if belief is not None and int(belief.seat) != int(obs["seat"]):
        raise ValueError("Orbit determinization belief seat mismatch")
    hidden = belief.sample(rng) if belief is not None else sample_hidden(obs, rng)
    opponent = game["order"][1 - game["order"].index(pid)]
    world["players"][opponent]["hand"] = list(hidden["opponent_hand"])
    world["agent_deck"] = list(hidden["agent_deck"])
    world["bonus_deck"] = list(hidden["bonus_deck"])
    _save_private_rng(world, rng.getrandbits(64))
    return world


def _sig(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _clip(value: float, limit: float = 1.0) -> float:
    return max(-limit, min(limit, value))


def _progress(captured: list[str]) -> float:
    if not captured:
        return 0.0
    same = max(captured.count(planet) for planet in PLANETS)
    unique = len(set(captured))
    return max(same / 3.0, unique / 4.0, len(captured) / 5.0)


def state_value(game: dict, pid: str) -> float:
    """Public-state leaf value from ``pid``'s perspective.

    Victory is the only terminal reward.  Non-terminal terms are a stable
    search heuristic: capture progress dominates, while resources are bounded
    and technology/leader supply tempo.  Opponent hands and both deck orders
    are intentionally absent.
    """

    winner = engine.winner(game)
    if engine.is_over(game):
        if winner is None:
            return 0.0
        return 1.0 if winner == pid else -1.0
    other = game["order"][1 - game["order"].index(pid)]
    me = game["players"][pid]
    them = game["players"][other]
    direction = 1 if game["order"][0] == pid else -1

    # Capture progress is nonlinear: two discs from one planet are much more
    # useful than two scattered discs because the third step ends the game.
    # Influence receives the same urgency treatment, while terminal outcomes
    # remain the only hard reward.  Every term is public or seat-local.
    value = 1.4 * (_progress(me["captured"]) - _progress(them["captured"]))
    for position in game["influence"].values():
        if position is None:
            continue
        progress = position * direction
        value += 0.11 * progress + 0.06 * (progress ** 3) / 27.0
        if progress >= 2:
            value += 0.18
        elif progress <= -2:
            value -= 0.18
    value += 0.05 * (len(me["captured"]) - len(them["captured"]))
    value += 0.018 * (
        sum(me["technology"].get(faction, 0) for faction in FACTIONS)
        - sum(them["technology"].get(faction, 0) for faction in FACTIONS)
    )
    value += 0.03 * (len(me["row_bonuses"]) - len(them["row_bonuses"]))
    if game["leader"]["owner"] == pid:
        value += 0.09 + 0.035 * game["leader"]["level"]
    elif game["leader"]["owner"] == other:
        value -= 0.09 + 0.035 * game["leader"]["level"]
    value += 0.025 * (me["credits"] - them["credits"])
    value += 0.04 * (me["zenithium"] - them["zenithium"])
    own_cards = sum(CARDS[c]["cost"] for c in me["hand"])
    public_opp_cards = sum(CARDS[c]["cost"] for column in them["columns"].values() for c in column)
    value += 0.005 * (own_cards - public_opp_cards)
    return math.tanh(value)


def _action_score_world(game: dict, pid: str, move: dict) -> float:
    """One-ply score for a world that has already been determinized."""

    after = copy.deepcopy(game)
    before = state_value(game, pid)
    ok, _ = engine.apply_move(after, pid, move)
    if not ok:
        return -10.0
    delta = state_value(after, pid) - before
    if engine.is_over(after):
        return 5.0 if engine.winner(after) == pid else -5.0
    action = move.get("action")
    if action == "recruit":
        card = CARDS[int(move["card_id"])]
        # Cards that fill an empty planet and cards with immediate faction
        # development are useful tie-breakers after public outcome delta.
        delta += 0.004 * card["cost"]
    elif action == "technology":
        delta += 0.018
    elif action == "leader":
        delta += 0.012
    elif action == "mulligan":
        # Keep high-cost cards and mulligan low-cost cards in the opening hand;
        # the post-mulligan state already captures the resource-independent part.
        discarded = sum(CARDS[int(card)]["cost"] for card in move.get("card_ids", []))
        delta += 0.002 * discarded
    return delta


def action_score(game: dict, pid: str, move: dict) -> float:
    """One-ply public heuristic used for priors and the heuristic baseline.

    The sanitizing determinization is part of this public helper's contract;
    callers that already hold a sampled world should use the private
    ``_action_score_world`` to avoid paying for a second sample.
    """

    move_seed = int.from_bytes(hashlib.sha256(action_key(move).encode()).digest()[:8], "big")
    local = random.Random(0x0B17 ^ move_seed)
    world = determinize(game, pid, local)
    return _action_score_world(world, pid, move)


def _fast_action_score(game: dict, pid: str, move: dict) -> float:
    """Allocation-free public prior used inside every tree expansion.

    Full one-ply application is useful for diagnostics but too expensive to
    repeat for every sibling at every information node.  This scorer uses only
    the current observation: capture distance, printed cost/faction, visible
    resources and the shape of a pending choice.  The leaf value still comes
    from the complete engine transition, so this is a prior rather than a
    reward substitute.
    """

    action = move.get("action")
    direction = 1 if game["order"][0] == pid else -1
    score = 0.0
    player = game["players"][pid]
    if action in {"recruit", "technology", "leader"} and "card_id" in move:
        card = CARDS[int(move["card_id"])]
        position = game["influence"].get(card["planet"])
        progress = 0.0 if position is None else position * direction
        if action == "recruit":
            column = player["columns"][card["planet"]]
            cost = max(0, card["cost"] - len(column))
            score += 0.20 + 0.08 * progress - 0.01 * cost
            if progress >= 2:
                score += 0.30
            if progress >= 3:
                score += 1.50
        elif action == "technology":
            level = player["technology"][card["faction"]]
            score += 0.12 + 0.02 * (5 - level)
        else:
            score += 0.05
    if action == "mulligan":
        score += 0.01 * sum(5 - CARDS[int(card)]["cost"] for card in move.get("card_ids", []))
    planet = move.get("planet")
    if planet in game["influence"]:
        position = game["influence"][planet]
        progress = 0.0 if position is None else position * direction
        score += 0.25 * progress
        if progress >= 3:
            score += 1.20
    for planet in move.get("planets", []):
        position = game["influence"].get(planet)
        score += 0.20 * (0.0 if position is None else position * direction)
    if "tier" in move:
        score += 0.05 * int(move["tier"])
    if move.get("accept") is True:
        score += 0.10
    if "branch" in move:
        score += 0.02 * (1 - int(move["branch"]))
    return score


def _softmax(scores: Iterable[float], temperature: float = 1.0) -> list[float]:
    values = list(scores)
    if not values:
        return []
    if temperature <= 0:
        best = max(range(len(values)), key=lambda i: values[i])
        return [1.0 if i == best else 0.0 for i in range(len(values))]
    scale = max(1e-6, temperature)
    pivot = max(values)
    exps = [math.exp(max(-60.0, min(60.0, (value - pivot) / scale))) for value in values]
    total = sum(exps) or 1.0
    return [value / total for value in exps]


def _history_trace(history: dict | None) -> tuple[str, ...]:
    if not history:
        return ()
    events = history.get("events", [])
    trace: list[str] = []
    for event in events[-12:]:
        public = event.get("public_action")
        if public:
            trace.append(_sig({"actor": event.get("actor"), "public_action": public}))
        # Observation diffs can contain the root player's private hand and
        # legal choices.  They are useful to that seat's guide, but must never
        # become part of the public trace used to seed the simulated opponent.
    return tuple(trace)


def _trace_history(world: dict, pid: str, trace: tuple[str, ...]) -> dict:
    """Build a public-only synthetic history for a simulated seat.

    A determinized rollout starts from the current information state, so the
    real opponent history is not available to the root search.  Replaying the
    compact public trace gives that opponent the events it could actually have
    observed, while keeping the root player's private history out of it.
    """

    events = []
    for item in trace:
        try:
            payload = json.loads(item)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and "public_action" in payload:
            events.append({
                "actor": payload.get("actor"),
                "changes": {},
                "public_action": payload["public_action"],
            })
        else:
            events.append({"actor": None, "changes": {}, "public_action": payload})
    return {"initial": observation(world, pid), "events": events}


def _policy_move(
    policy: Policy,
    game: dict,
    pid: str,
    rng: random.Random,
    *,
    history: dict | None = None,
) -> dict | None:
    result = policy.choose(game, pid, rng, observation=observation(game, pid), history=history, belief=None)
    return result.move if isinstance(result, Decision) else result


class RandomPolicy:
    name = "random"

    def choose(self, game: dict, pid: str, rng: random.Random, *, observation=None, history=None, time_budget=None, belief=None):
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        return rng.choice(moves) if moves else None


class HeuristicPolicy:
    name = "heuristic"

    def __init__(self, *, temperature: float = 0.0):
        self.temperature = float(temperature)

    def choose(self, game: dict, pid: str, rng: random.Random, *, observation=None, history=None, time_budget=None, belief=None):
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        if not moves:
            return None
        # The baseline uses the allocation-free public prior; the search leaf
        # remains the full engine value.
        scores = [_fast_action_score(game, pid, move) for move in moves]
        if self.temperature > 0:
            probs = _softmax(scores, self.temperature)
            return rng.choices(moves, weights=probs, k=1)[0]
        best = max(scores)
        return moves[next(i for i, score in enumerate(scores) if score == best)]


class GuidePolicy:
    """Policy-only baseline for a future neural guide or a tabular guide."""

    def __init__(self, guide: Guide, *, name: str = "guide"):
        self.guide = guide
        self.name = name

    def choose(self, game: dict, pid: str, rng: random.Random, *, observation=None, history=None, time_budget=None, belief=None):
        obs = observation or globals()["observation"](game, pid)
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        if not moves:
            return None
        priors = self.guide.priors(obs, moves, history=history)
        scores = [float(priors.get(action_key(move), 0.0)) for move in moves]
        best = max(scores)
        candidates = [move for move, score in zip(moves, scores) if score == best]
        return rng.choice(candidates)


class InformationSetSearch:
    """PUCT over sampled hidden worlds with a frozen opponent model."""

    def __init__(
        self,
        config: SearchConfig | None = None,
        *,
        opponent: Policy | None = None,
        guide: Guide | None = None,
    ):
        self.config = config or SearchConfig()
        self.opponent = opponent or HeuristicPolicy()
        self.guide = guide

    def _priors(self, world: dict, pid: str, moves: list[dict], obs: dict, history: dict | None = None) -> list[float]:
        if self.guide is not None:
            supplied = self.guide.priors(obs, moves, history=history)
            raw = [max(0.0, float(supplied.get(action_key(move), 0.0))) for move in moves]
            if any(raw):
                total = sum(raw)
                return [value / total for value in raw]
        scores = [_fast_action_score(world, pid, move) for move in moves]
        # A non-zero floor prevents a heuristic outlier from permanently
        # hiding a novel action before a value sample has visited it.
        probs = _softmax(scores, 0.12)
        floor = 0.03 / len(probs)
        return [(1.0 - 0.03) * value + floor for value in probs]

    def _ensure(self, node: _Node, world: dict, pid: str, moves: list[dict], obs: dict, history: dict | None = None) -> None:
        if node.children:
            # A hidden draw can produce a different legal set at a later
            # information state.  Add only genuinely new actions.
            missing = [move for move in moves if action_key(move) not in node.children]
        else:
            missing = list(moves)
        if not missing:
            return
        priors = self._priors(world, pid, moves, obs, history)
        lookup = {action_key(move): prior for move, prior in zip(moves, priors)}
        for move in missing:
            key = action_key(move)
            node.children[key] = _Node(prior=lookup.get(key, 1.0 / len(moves)))
            node.moves[key] = copy.deepcopy(move)

    def _select(self, node: _Node) -> tuple[str, _Node]:
        parent_sqrt = math.sqrt(max(1, node.visits))
        best_key = None
        best_node = None
        best_score = -float("inf")
        for key in sorted(node.children):
            child = node.children[key]
            exploration = self.config.exploration * child.prior * parent_sqrt / (1 + child.visits)
            score = child.mean + exploration
            if score > best_score:
                best_key, best_node, best_score = key, child, score
        assert best_key is not None and best_node is not None
        return best_key, best_node

    def _info_key(self, world: dict, pid: str, trace: tuple[str, ...]) -> str:
        # Observation plus a compact public action trace is the information-set
        # identity.  Hidden card order and private pending queue entries are not
        # serialized by observation().
        return _sig({"observation": observation(world, pid), "trace": trace[-12:]})

    def _simulate(
        self,
        root: _Node,
        world: dict,
        pid: str,
        rng: random.Random,
        history_trace: tuple[str, ...],
        info_nodes: dict[str, _Node],
        history: dict | None = None,
    ) -> float:
        path = [root]
        trace = history_trace
        depth = 0
        at_root = True
        own_history = copy.deepcopy(history) if history is not None else {
            "initial": observation(world, pid), "events": []
        }
        own_history.setdefault("events", [])
        simulated_histories: dict[str, dict] = {
            actor: _trace_history(world, actor, trace)
            for actor in world["order"]
            if actor != pid
        }
        while not engine.is_over(world) and depth < self.config.max_depth:
            actor = _actor(world)
            if actor is None:
                break
            moves = sorted(engine.legal_moves(world, actor), key=action_key)
            if not moves:
                break
            if actor == pid:
                if at_root:
                    node = root
                else:
                    key = self._info_key(world, pid, trace)
                    node = info_nodes.setdefault(key, _Node())
                    self._ensure(node, world, pid, moves, observation(world, pid), own_history)
                move_key, child = self._select(node)
                move = node.moves[move_key]
                path.append(child)
                if not at_root:
                    path.insert(-1, node)
            else:
                actor_history = simulated_histories[actor]
                move = _policy_move(self.opponent, world, actor, rng, history=actor_history)
                if move not in moves:
                    move = moves[0]
            if move.get("action") in {"recruit", "technology", "leader", "mulligan"}:
                public_trace = move if move["action"] != "mulligan" else {
                    "action": "mulligan", "count": len(move.get("card_ids", []))
                }
                trace = (*trace, _sig({
                    "actor": world["order"].index(actor),
                    "public_action": public_trace,
                }))
            ok, _ = engine.apply_move(world, actor, move)
            if not ok:
                # A policy bug in an opponent must not poison the root.  The
                # engine remains the validator and the legal first move is a
                # deterministic recovery for this offline rollout.
                move = moves[0]
                engine.apply_move(world, actor, move)
            public_move = None
            if move.get("action") in {"recruit", "technology", "leader"}:
                public_move = copy.deepcopy(move)
            elif move.get("action") == "mulligan":
                public_move = {"action": "mulligan", "count": len(move.get("card_ids", []))}
            for viewer, viewer_history in simulated_histories.items():
                event = {"actor": world["order"].index(actor), "changes": {}}
                if public_move is not None:
                    event["public_action"] = copy.deepcopy(public_move)
                if viewer == actor:
                    event["own_action"] = copy.deepcopy(move)
                viewer_history["events"].append(event)
            own_event = {"actor": world["order"].index(actor), "changes": {}}
            if public_move is not None:
                own_event["public_action"] = copy.deepcopy(public_move)
            if actor == pid:
                own_event["own_action"] = copy.deepcopy(move)
            own_history["events"].append(own_event)
            depth += 1
            at_root = False
        if self.guide is not None and not engine.is_over(world):
            value = _clip(float(self.guide.value(observation(world, pid), history=own_history)))
        else:
            value = state_value(world, pid)
        for node in path:
            node.visits += 1
            node.value_sum += value
        return value

    def choose(
        self,
        game: dict,
        pid: str,
        rng: random.Random,
        *,
        observation=None,
        history=None,
        time_budget: float | None = None,
        belief: HistoryBelief | None = None,
    ) -> Decision:
        started = time.perf_counter()
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        if not moves:
            return Decision(None, elapsed=time.perf_counter() - started)
        budget = self.config.time_limit if time_budget is None else time_budget
        deadline = None if budget is None else started + max(0.0, budget)
        root = _Node()
        initial_world = determinize(game, pid, rng, belief)
        obs = observation or globals()["observation"](game, pid)
        self._ensure(root, initial_world, pid, moves, obs, history)
        trace = _history_trace(history)
        info_nodes: dict[str, _Node] = {}
        simulations = 0
        target = max(1, int(self.config.simulations))
        coherent_worlds = []
        if int(self.config.particles) > 1:
            coherent_worlds = [determinize(game, pid, rng, belief) for _ in range(int(self.config.particles))]
        while simulations < target and (deadline is None or simulations == 0 or time.perf_counter() < deadline):
            # ``particles`` controls coherent world reuse without allowing a
            # true hidden deck to enter the prior.  A new draw is made for each
            # simulation unless a caller explicitly requests a coherent batch.
            if coherent_worlds:
                world = copy.deepcopy(coherent_worlds[simulations % len(coherent_worlds)])
            else:
                world = determinize(game, pid, rng, belief)
            self._simulate(root, world, pid, rng, trace, info_nodes, history)
            simulations += 1
        stats = []
        for move in moves:
            key = action_key(move)
            child = root.children[key]
            stats.append({
                "key": key,
                "move": copy.deepcopy(move),
                "visits": child.visits,
                "value": child.mean,
                "prior": child.prior,
            })
        stats.sort(key=lambda item: (-item["visits"], -item["value"], item["key"]))
        chosen = stats[0]["move"]
        if self.config.temperature > 0 and len(stats) > 1:
            weights = [max(1e-9, item["visits"]) ** (1.0 / self.config.temperature) for item in stats]
            chosen = rng.choices([item["move"] for item in stats], weights=weights, k=1)[0]
        return Decision(
            move=chosen,
            stats=stats,
            root_value=root.mean,
            simulations=simulations,
            elapsed=time.perf_counter() - started,
            censored=simulations < target,
        )


class SearchPolicy:
    uses_belief = True

    def __init__(self, search: InformationSetSearch | None = None, *, name: str = "search"):
        self.search = search or InformationSetSearch()
        self.name = name

    def choose(self, game: dict, pid: str, rng: random.Random, *, observation=None, history=None, time_budget=None, belief=None):
        return self.search.choose(game, pid, rng, observation=observation, history=history, time_budget=time_budget, belief=belief)


def policy_fingerprint(policy: Policy) -> str:
    payload = {"name": getattr(policy, "name", policy.__class__.__name__)}
    if isinstance(policy, SearchPolicy):
        payload["search"] = policy.search.config.as_dict()
        payload["guide"] = policy.search.guide.__class__.__name__ if policy.search.guide else None
        if policy.search.guide is not None and hasattr(policy.search.guide,"as_dict"):
            payload["guide_digest"] = hashlib.sha256(_sig(policy.search.guide.as_dict()).encode()).hexdigest()
    if isinstance(policy, HeuristicPolicy):
        payload["temperature"] = policy.temperature
    for attribute in ("model", "guide"):
        artifact = getattr(policy, attribute, None)
        if artifact is not None:
            payload[attribute] = {
                "class": artifact.__class__.__name__,
                "rules": getattr(artifact, "rules", None),
                "schema": getattr(artifact, "schema", None),
                "encoder": getattr(artifact, "encoder", None),
                "version": getattr(artifact, "model_version", getattr(artifact, "VERSION", None)),
                "examples": getattr(artifact, "examples", None),
                "epochs": getattr(artifact, "epochs", None),
            }
            if hasattr(artifact, "as_dict"):
                payload[attribute]["digest"] = hashlib.sha256(
                    _sig(artifact.as_dict()).encode()
                ).hexdigest()[:16]
    return hashlib.sha256(_sig(payload).encode()).hexdigest()[:16]
