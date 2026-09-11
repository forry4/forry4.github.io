"""Self-play episodes and common-random-number Orbit arenas.

The harness is deliberately offline.  It records policy observations and
search visit targets, never true hidden state.  Arenas play each deal twice
with the policy assignments swapped, and score the pair as the statistical
unit.  All eight technology-board configurations are scheduled evenly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
import math
import random
import statistics
from typing import Iterable, Sequence

from .. import engine
from ..boards import SUN_CONFIGURATION
from ..cards import FACTIONS
from .history import Session
from .belief import HistoryBelief
from .search import Decision, HeuristicPolicy, Policy, RandomPolicy, _actor, policy_fingerprint
from .state import SCHEMA_VERSION, action_key, observation, rules_fingerprint


def board_configurations() -> list[dict[str, int]]:
    """Return the eight base-game technology sides in stable order."""

    return [
        {faction: (mask >> index) & 1 or 2 for index, faction in enumerate(FACTIONS)}
        for mask in range(8)
    ]


def board_key(configuration: dict[str, int]) -> str:
    return "/".join(f"{faction[:1]}{configuration[faction]}" for faction in FACTIONS)


@dataclass
class EpisodeStep:
    actor_seat: int
    observation: dict
    history: dict | None
    legal_moves: list[dict]
    action: dict
    target: dict[str, float]
    root_value: float | None = None
    simulations: int = 0

    def as_dict(self) -> dict:
        return {
            "actor_seat": self.actor_seat,
            "observation": copy.deepcopy(self.observation),
            "history": copy.deepcopy(self.history),
            "legal_moves": copy.deepcopy(self.legal_moves),
            "action": copy.deepcopy(self.action),
            "target": dict(self.target),
            "root_value": self.root_value,
            "simulations": self.simulations,
        }


@dataclass
class Episode:
    seed: int
    configuration: dict[str, int]
    policy_names: tuple[str, str]
    steps: list[EpisodeStep]
    winner_seat: int | None
    censored: bool
    decisions: int
    rules: str = field(default_factory=rules_fingerprint)
    schema: int = SCHEMA_VERSION
    metadata: dict = field(default_factory=dict)

    def outcomes(self) -> tuple[float, float] | None:
        if self.censored:
            # A decision cap is right-censoring, not a draw.  Callers that
            # train terminal values must explicitly skip this episode.
            return None
        if self.winner_seat is None:
            return (0.5, 0.5)
        return tuple(1.0 if seat == self.winner_seat else 0.0 for seat in (0, 1))

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "rules": self.rules,
            "seed": self.seed,
            "configuration": dict(self.configuration),
            "policy_names": list(self.policy_names),
            "winner_seat": self.winner_seat,
            "censored": self.censored,
            "decisions": self.decisions,
            "steps": [step.as_dict() for step in self.steps],
            "metadata": copy.deepcopy(self.metadata),
        }


def _policy_name(policy: Policy) -> str:
    return str(getattr(policy, "name", policy.__class__.__name__.lower()))


def _decision(
    policy: Policy,
    game: dict,
    pid: str,
    rng: random.Random,
    history: dict,
    time_budget: float | None,
    belief: HistoryBelief | None,
) -> Decision:
    obs = observation(game, pid)
    result = policy.choose(
        game,
        pid,
        rng,
        observation=obs,
        history=history,
        time_budget=time_budget,
        belief=belief,
    )
    if isinstance(result, Decision):
        return result
    legal = sorted(engine.legal_moves(game, pid), key=action_key)
    move = result if isinstance(result, dict) else (legal[0] if legal else None)
    target = {action_key(candidate): (1.0 if candidate == move else 0.0) for candidate in legal}
    return Decision(move=move, stats=[{"key": key, "visits": int(value)} for key, value in target.items()])


def play_game(
    policies: Sequence[Policy],
    *,
    seed: int = 0,
    configuration: str | dict[str, int] = "sun",
    max_decisions: int = 1600,
    turn_budget: float | None = None,
) -> Episode:
    """Play one complete offline game and return policy-safe trajectory data."""

    if len(policies) != 2:
        raise ValueError("Orbit self-play requires two policies")
    if configuration == "sun":
        config: str | dict[str, int] = dict(SUN_CONFIGURATION)
    elif configuration == "random":
        config = "random"
    elif isinstance(configuration, dict):
        config = dict(configuration)
    else:
        raise ValueError("configuration must be 'sun', 'random', or a side map")
    game = engine.new_game(["seat0", "seat1"], seed=seed, configuration=config)
    episode_configuration = dict(game["board_sides"])
    session = Session(game)
    policy_rng = [random.Random(seed ^ 0xA51CE + index * 0x9E3779B9) for index in range(2)]
    needs_belief = any(getattr(policy, "uses_belief", False) for policy in policies)
    beliefs = {
        pid: HistoryBelief(observation(session.game, pid), particles=32, seed=seed ^ (index + 1) * 0xA5A5A5A5)
        for index, pid in enumerate(session.game["order"])
    } if needs_belief else {}
    steps: list[EpisodeStep] = []
    fallback_moves = 0
    censored = True
    for _ in range(max(0, int(max_decisions))):
        if engine.is_over(session.game):
            censored = False
            break
        pid = _actor(session.game)
        if pid is None:
            break
        seat = session.game["order"].index(pid)
        policy = policies[seat]
        policy_input = session.policy_input(pid)
        obs = copy.deepcopy(policy_input["observation"])
        legal = sorted(engine.legal_moves(session.game, pid), key=action_key)
        decision = _decision(
            policy,
            session.game,
            pid,
            policy_rng[seat],
            policy_input["history"],
            turn_budget,
            beliefs.get(pid),
        )
        move = decision.move
        if move not in legal:
            # The engine remains the sole legality authority.  A bad offline
            # policy cannot create a training transition; record the legal
            # deterministic fallback and continue so the episode is useful for
            # diagnosing that policy.
            fallback_moves += 1
            move = legal[0] if legal else None
        if move is None:
            break
        legal_keys = {action_key(candidate) for candidate in legal}
        raw_target = decision.target()
        target = {
            key: max(0.0, float(probability))
            for key, probability in raw_target.items()
            if key in legal_keys
        }
        target_total = sum(target.values())
        if target_total > 0:
            target = {key: probability / target_total for key, probability in target.items()}
        else:
            target = {action_key(candidate): (1.0 if candidate == move else 0.0) for candidate in legal}
        steps.append(EpisodeStep(
            actor_seat=seat,
            observation=obs,
            history=copy.deepcopy(policy_input["history"]),
            legal_moves=copy.deepcopy(legal),
            action=copy.deepcopy(move),
            target=target,
            root_value=decision.root_value,
            simulations=decision.simulations,
        ))
        ok, error = session.step(pid, move)
        if not ok:
            raise RuntimeError(f"Orbit policy produced an invalid move: {error}")
        # Condition each seat's particle population on the newly observed
        # public event.  A search policy consumes the corresponding belief on
        # its next decision; the other policies still advance it so trajectories
        # can be replayed with any policy assignment.
        if beliefs:
            for viewer in session.game["order"]:
                history_after = session.policy_input(viewer)["history"]
                event = history_after["events"][-1]
                beliefs[viewer].update(observation(session.game, viewer), event)
    else:
        censored = not engine.is_over(session.game)
    winner = engine.winner(session.game)
    winner_seat = session.game["order"].index(winner) if winner is not None else None
    return Episode(
        seed=int(seed),
        configuration=episode_configuration,
        policy_names=(_policy_name(policies[0]), _policy_name(policies[1])),
        steps=steps,
        winner_seat=winner_seat,
        censored=censored,
        decisions=len(steps),
        metadata={
            "policy_fingerprints": [policy_fingerprint(policy) for policy in policies],
            "max_decisions": int(max_decisions),
            "turn_budget": turn_budget,
            "belief_particles": 32,
            "fallback_moves": fallback_moves,
        },
    )


def write_episodes(path, episodes: Iterable[Episode]) -> int:
    """Write JSONL trajectories with one complete episode per line."""

    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for episode in episodes:
            handle.write(json.dumps(episode.as_dict(), sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def read_episodes(path, *, require_rules: str | None = None) -> list[Episode]:
    result: list[Episode] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if require_rules is not None and value.get("rules") != require_rules:
                raise ValueError("Orbit trajectory rules fingerprint mismatch")
            if int(value.get("schema", -1)) != SCHEMA_VERSION:
                raise ValueError("Orbit trajectory schema mismatch")
            steps = [EpisodeStep(**{"history": None, **step}) for step in value["steps"]]
            result.append(Episode(
                seed=int(value["seed"]),
                configuration={k: int(v) for k, v in value["configuration"].items()},
                policy_names=tuple(value["policy_names"]),
                steps=steps,
                winner_seat=value.get("winner_seat"),
                censored=bool(value["censored"]),
                decisions=int(value["decisions"]),
                rules=value["rules"],
                schema=int(value["schema"]),
                metadata=copy.deepcopy(value.get("metadata", {})),
            ))
    return result


@dataclass
class ArenaResult:
    candidate: str
    opponent: str
    games: int
    pairs: int
    wins: int
    losses: int
    draws: int
    censored: int
    score_sum: float
    pair_scores: list[float]
    by_board: dict[str, dict]
    rules: str = field(default_factory=rules_fingerprint)
    schema: int = SCHEMA_VERSION
    settings: dict = field(default_factory=dict)
    # One entry per scheduled pair.  ``None`` marks a pair with at least one
    # censored game.  The public ``pair_scores`` list remains the compact list
    # of complete pairs used by existing callers; this aligned form lets the
    # Phase 4 gate resample CRN candidate/incumbent differences correctly.
    pair_scores_by_index: list[float | None] = field(default_factory=list)

    @property
    def score(self) -> float:
        scored_games = self.wins + self.losses + self.draws
        return self.score_sum / scored_games if scored_games else 0.5

    @property
    def pair_score(self) -> float:
        return statistics.fmean(self.pair_scores) if self.pair_scores else 0.5

    def bootstrap_ci(self, *, samples: int = 2000, seed: int = 0) -> tuple[float, float]:
        if len(self.pair_scores) < 2:
            return (self.pair_score, self.pair_score)
        rng = random.Random(seed)
        means = []
        for _ in range(max(1, samples)):
            means.append(statistics.fmean(rng.choices(self.pair_scores, k=len(self.pair_scores))))
        means.sort()
        return means[int(0.025 * (len(means) - 1))], means[int(0.975 * (len(means) - 1))]

    @property
    def pair_sd(self) -> float:
        """Standard deviation of the complete pair scores.

        This is the number that sizes every future screen, so it is recorded
        with the result rather than re-derived later.  The 2026-09-11 audit
        measured ~0.31 between near-peer Orbit bots, which makes an eight-pair
        screen +/-0.21 and puts a +0.03 effect ~400 pairs away.  A report that
        does not carry its own variance invites exactly the argmax-over-noise
        selection that stalled the first twelve league generations.
        """
        return statistics.stdev(self.pair_scores) if len(self.pair_scores) > 1 else 0.0

    def pairs_needed(self, effect: float) -> int:
        """Complete pairs needed to resolve ``effect`` at 95% on this variance."""
        if effect <= 0 or self.pair_sd <= 0:
            return 0
        return math.ceil((1.96 * self.pair_sd / effect) ** 2)

    def as_dict(self) -> dict:
        low, high = self.bootstrap_ci()
        complete = len(self.pair_scores)
        return {
            "schema": self.schema,
            "rules": self.rules,
            "candidate": self.candidate,
            "opponent": self.opponent,
            "games": self.games,
            "scored_games": self.wins + self.losses + self.draws,
            "pairs": self.pairs,
            "complete_pairs": len(self.pair_scores),
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "censored": self.censored,
            "score": self.score,
            "pair_score": self.pair_score,
            "pair_ci95": [low, high],
            "pair_sd": self.pair_sd,
            "pair_se": self.pair_sd / math.sqrt(complete) if complete else 0.0,
            "pairs_needed_for_0.03": self.pairs_needed(0.03),
            "pairs_needed_for_0.05": self.pairs_needed(0.05),
            "by_board": copy.deepcopy(self.by_board),
            "balanced_boards": bool(self.settings.get("balanced_boards", False)),
            "settings": copy.deepcopy(self.settings),
        }


def run_arena(
    candidate: Policy,
    opponent: Policy,
    *,
    pairs: int = 32,
    seed: int = 0,
    max_decisions: int = 1600,
    turn_budget: float | None = None,
    configurations: Sequence[dict[str, int]] | None = None,
) -> ArenaResult:
    """Run paired CRN matches with balanced board coverage."""

    if pairs < 1:
        raise ValueError("pairs must be positive")
    boards = list(board_configurations() if configurations is None else configurations)
    if not boards:
        raise ValueError("at least one board configuration is required")
    wins = losses = draws = censored = 0
    score_sum = 0.0
    pair_scores: list[float] = []
    pair_scores_by_index: list[float | None] = []
    by_board: dict[str, dict] = {
        board_key(config): {"pairs": 0, "wins": 0, "losses": 0, "draws": 0, "censored": 0, "score": 0.0}
        for config in boards
    }
    for index in range(pairs):
        config = boards[index % len(boards)]
        key = board_key(config)
        pair = 0.0
        pair_valid = True
        for swap in (0, 1):
            assignment = (candidate, opponent) if swap == 0 else (opponent, candidate)
            episode = play_game(
                assignment,
                seed=seed + index * 104729,
                configuration=config,
                max_decisions=max_decisions,
                turn_budget=turn_budget,
            )
            if episode.censored:
                censored += 1
                by_board[key]["censored"] += 1
                pair_valid = False
                continue
            candidate_seat = 0 if swap == 0 else 1
            if episode.winner_seat is None:
                outcome = 0.5
                draws += 1
                by_board[key]["draws"] += 1
            elif episode.winner_seat == candidate_seat:
                outcome = 1.0
                wins += 1
                by_board[key]["wins"] += 1
            else:
                outcome = 0.0
                losses += 1
                by_board[key]["losses"] += 1
            score_sum += outcome
            by_board[key]["score"] += outcome
            pair += outcome
        by_board[key]["pairs"] += 1
        if pair_valid:
            pair_scores.append(pair / 2.0)
            pair_scores_by_index.append(pair / 2.0)
        else:
            pair_scores_by_index.append(None)
    games = wins + losses + draws + censored
    for stats in by_board.values():
        denominator = 2 * stats["pairs"] - stats["censored"]
        stats["scored_games"] = denominator
        stats["score"] = stats["score"] / denominator if denominator else 0.5
    return ArenaResult(
        candidate=_policy_name(candidate),
        opponent=_policy_name(opponent),
        games=games,
        pairs=pairs,
        wins=wins,
        losses=losses,
        draws=draws,
        censored=censored,
        score_sum=score_sum,
        pair_scores=pair_scores,
        by_board=by_board,
        pair_scores_by_index=pair_scores_by_index,
        settings={
            "pairs": pairs,
            "seed": seed,
            "max_decisions": max_decisions,
            "turn_budget": turn_budget,
            "boards": [dict(config) for config in boards],
            "policy_fingerprints": [policy_fingerprint(candidate), policy_fingerprint(opponent)],
            "balanced_boards": pairs % len(boards) == 0,
        },
    )


def mirror_sanity(
    policy: Policy,
    *,
    pairs: int = 16,
    seed: int = 0,
    max_decisions: int = 1600,
    turn_budget: float | None = None,
) -> dict:
    """Run a policy against itself; a deterministic paired harness should read 0.5."""

    result = run_arena(
        policy,
        policy,
        pairs=pairs,
        seed=seed,
        max_decisions=max_decisions,
        turn_budget=turn_budget,
    )
    return {
        "score": result.pair_score,
        "games": result.games,
        "censored": result.censored,
        "exact_half": result.pair_score == 0.5,
        "report": result.as_dict(),
    }


def compare_algorithms(
    policies: dict[str, Policy],
    *,
    pairs: int = 32,
    seed: int = 0,
    max_decisions: int = 1600,
    turn_budget: float | None = None,
) -> dict:
    """Compare a policy set under identical board/deal scheduling.

    Every unordered pair receives the same seed base and equal per-turn budget.
    The report is intentionally a matrix of pair scores rather than an Elo
    ranking, so a candidate cannot look strong merely by avoiding one opponent
    family.
    """

    names = list(policies)
    matrix: dict[str, dict[str, dict]] = {name: {} for name in names}
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            result = run_arena(
                policies[left],
                policies[right],
                pairs=pairs,
                seed=seed,
                max_decisions=max_decisions,
                turn_budget=turn_budget,
            )
            report = result.as_dict()
            matrix[left][right] = report
            reversed_board = {}
            for board, values in report["by_board"].items():
                reversed_board[board] = {
                    **values,
                    "wins": values["losses"],
                    "losses": values["wins"],
                    "score": 1.0 - values["score"],
                }
            matrix[right][left] = {
                "candidate": right,
                "opponent": left,
                "score": 1.0 - report["score"],
                "pair_score": 1.0 - report["pair_score"],
                "games": report["games"],
                "scored_games": report.get("scored_games", report["wins"] + report["losses"] + report["draws"]),
                "pairs": report["pairs"],
                "wins": report["losses"],
                "losses": report["wins"],
                "draws": report["draws"],
                "censored": report["censored"],
                "pair_ci95": [1.0 - report["pair_ci95"][1], 1.0 - report["pair_ci95"][0]],
                "by_board": reversed_board,
                "rules": report["rules"],
                "settings": report["settings"],
            }
    mirrors = {
        name: mirror_sanity(
            policies[name],
            pairs=max(1, min(8, pairs // 2 or 1)),
            seed=seed,
            max_decisions=max_decisions,
            turn_budget=turn_budget,
        )
        for name in names
    }
    return {"rules": rules_fingerprint(), "pairs": pairs, "seed": seed, "matrix": matrix, "mirrors": mirrors}


def baseline(name: str) -> Policy:
    """Construct a named Phase 2 baseline for CLI tools and manifests."""

    if name == "random":
        return RandomPolicy()
    if name == "heuristic":
        return HeuristicPolicy()
    if name == "search":
        from .search import InformationSetSearch, SearchConfig, SearchPolicy

        return SearchPolicy(InformationSetSearch(SearchConfig(simulations=128, time_limit=0.1)))
    raise ValueError(f"unknown Orbit baseline: {name}")
