"""Offline Phase 4 promotion gates for Orbit.

The gate is deliberately a report generator.  It compares a candidate with
the incumbent on namespaced development and confirmation deal pools, keeps
opponent families separate, and never changes the serving bot.  Confirmation
games are the statistical unit: a pair uses one deal seed twice with the
policy assignments swapped, and bootstrap intervals resample complete pairs.

The default timing gate is inconclusive until an external serving/WASM timing
calibration is declared.  This prevents a fast Python smoke test from being
mistaken for the browser deployment measurement required by the campaign.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import math
import random
import statistics
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .. import engine
from ..cards import FACTIONS
from .search import Decision, Policy, policy_fingerprint
from .selfplay import (
    ArenaResult,
    board_configurations,
    board_key,
    mirror_sanity,
    play_game,
    run_arena,
)
from .state import SCHEMA_VERSION, observation, rules_fingerprint


def _policy_name(policy: Policy) -> str:
    return str(getattr(policy, "name", policy.__class__.__name__.lower()))


def _sha_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


@dataclass(frozen=True)
class GateConfig:
    """Phase 4 resources and pass thresholds.

    The production campaign uses 128 paired screening matches and 512 paired
    confirmation matches, expanding to 2,048 when the interval is uncertain.
    Smaller values are useful for smoke tests but are reported as unbalanced
    or underpowered rather than silently treated as a promotion result.
    """

    screening_pairs: int = 128
    confirmation_pairs: int = 512
    max_confirmation_pairs: int = 2048
    max_decisions: int = 1600
    turn_budget: float | None = None
    boards: tuple[dict[str, int], ...] | None = None
    bootstrap_samples: int = 2000
    regression_limit: float = 0.05
    information_trials: int = 8
    correctness_pairs: int = 8
    timing_trials: int = 8
    timing_limit: float = 5.0
    timing_calibrated: bool = False
    timing_source: str = "unverified"
    serving_workers: int | None = None
    serving_profile: str = "unverified"
    require_no_censoring: bool = True

    def __post_init__(self) -> None:
        if self.screening_pairs < 1 or self.confirmation_pairs < 1:
            raise ValueError("Orbit gate pair counts must be positive")
        if self.max_confirmation_pairs < self.confirmation_pairs:
            raise ValueError("max_confirmation_pairs must cover confirmation_pairs")
        if self.max_decisions < 1:
            raise ValueError("max_decisions must be positive")
        if self.bootstrap_samples < 1:
            raise ValueError("bootstrap_samples must be positive")
        if self.regression_limit < 0:
            raise ValueError("regression_limit must be non-negative")
        if self.information_trials < 1 or self.correctness_pairs < 1 or self.timing_trials < 1:
            raise ValueError("Orbit gate trial counts must be positive")
        if self.timing_limit <= 0:
            raise ValueError("timing_limit must be positive")
        if not str(self.timing_source).strip():
            raise ValueError("timing_source must be a non-empty provenance label")
        if self.timing_calibrated and str(self.timing_source).strip().lower() in {"unverified", "unknown"}:
            raise ValueError("timing_calibrated requires a serving/WASM timing provenance")
        if self.serving_workers is not None and self.serving_workers < 1:
            raise ValueError("serving_workers must be positive when provided")
        if self.timing_calibrated and (
            self.serving_workers is None
            or str(self.serving_profile).strip().lower() in {"", "unverified", "unknown"}
        ):
            raise ValueError("timing_calibrated requires the serving worker profile")
        if self.boards is not None and not self.boards:
            raise ValueError("Orbit Phase 4 requires at least one board configuration")

    def board_list(self) -> list[dict[str, int]]:
        return [dict(board) for board in (self.boards or tuple(board_configurations()))]

    def as_dict(self) -> dict:
        return {
            "screening_pairs": self.screening_pairs,
            "confirmation_pairs": self.confirmation_pairs,
            "max_confirmation_pairs": self.max_confirmation_pairs,
            "max_decisions": self.max_decisions,
            "turn_budget": self.turn_budget,
            "boards": self.board_list(),
            "bootstrap_samples": self.bootstrap_samples,
            "regression_limit": self.regression_limit,
            "information_trials": self.information_trials,
            "correctness_pairs": self.correctness_pairs,
            "timing_trials": self.timing_trials,
            "timing_limit": self.timing_limit,
            "timing_calibrated": self.timing_calibrated,
            "timing_source": self.timing_source,
            "serving_workers": self.serving_workers,
            "serving_profile": self.serving_profile,
            "require_no_censoring": self.require_no_censoring,
        }


@dataclass(frozen=True)
class PoolSpec:
    """A namespaced, reproducible deal pool.

    Development and confirmation seeds differ by namespace even when the
    caller uses the same campaign seed.  ``training_seeds`` can therefore be
    checked against every pair seed without relying on an accidental numeric
    range separation.
    """

    name: str
    root_seed: int
    pairs: int
    sealed: bool

    def arena_seed(self, family: str, opponent_index: int) -> int:
        return _sha_seed("orbit-phase4", self.name, self.root_seed, family, opponent_index)

    def pair_seed(self, family: str, opponent_index: int, pair_index: int) -> int:
        return self.arena_seed(family, opponent_index) + pair_index * 104729

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "pool_id": f"{self.name}:{self.root_seed}",
            "root_seed": self.root_seed,
            "pairs": self.pairs,
            "sealed": self.sealed,
        }


@dataclass
class GateCheck:
    """One independently auditable gate result."""

    name: str
    state: str
    observed: Any = None
    threshold: Any = None
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.state == "pass"

    @property
    def inconclusive(self) -> bool:
        return self.state == "inconclusive"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "passed": self.passed,
            "observed": copy.deepcopy(self.observed),
            "threshold": copy.deepcopy(self.threshold),
            "details": copy.deepcopy(self.details),
        }


@dataclass
class _PolicyPool:
    policy: Policy
    report: dict
    family_pair_scores: dict[str, list[list[float]]]
    # Pair scores aligned by scheduled pair index.  A ``None`` entry is a
    # censored pair and is retained so two CRN evaluations can be differenced
    # only where both sides completed the same deal.
    family_pair_scores_by_index: dict[str, list[list[float | None]]]
    # Same aligned scores grouped by board.  Keeping this off the serialized
    # report avoids bloating artifacts while allowing paired board/family
    # regression intervals below.
    family_board_pair_scores_by_index: dict[str, list[dict[str, list[float | None]]]]


def _normalise_families(families: Mapping[str, Policy | Sequence[Policy]]) -> dict[str, list[Policy]]:
    if not isinstance(families, Mapping) or not families:
        raise ValueError("Orbit promotion requires at least one opponent family")
    result: dict[str, list[Policy]] = {}
    for raw_name, value in families.items():
        name = str(raw_name)
        if not name or name == "__incumbent__":
            raise ValueError("invalid or reserved Orbit opponent family name")
        if hasattr(value, "choose"):
            policies = [value]  # type: ignore[list-item]
        else:
            policies = list(value)
        if not policies:
            raise ValueError(f"Orbit opponent family {name!r} is empty")
        if any(not hasattr(policy, "choose") for policy in policies):
            raise TypeError(f"Orbit opponent family {name!r} contains a non-policy")
        result[name] = policies
    return result


def _opponent_key(policy: Policy) -> str:
    return f"{_policy_name(policy)}@{policy_fingerprint(policy)}"


def _policy_contract_check(candidate: Policy, incumbent: Policy) -> GateCheck:
    """Reject stale model artifacts before spending sealed-game compute."""

    records = []
    for role, policy in (("candidate", candidate), ("incumbent", incumbent)):
        artifacts = [
            getattr(policy, "model", None),
            getattr(policy, "guide", None),
            getattr(getattr(policy, "search", None), "guide", None),
            policy,
        ]
        for artifact in artifacts:
            if artifact is None:
                continue
            artifact_rules = getattr(artifact, "rules", None)
            artifact_schema = getattr(artifact, "schema", None)
            if artifact_rules is not None or artifact_schema is not None:
                records.append({
                    "role": role,
                    "artifact": artifact.__class__.__name__,
                    "rules": artifact_rules,
                    "schema": artifact_schema,
                    "rules_ok": artifact_rules in (None, rules_fingerprint()),
                    "schema_ok": artifact_schema in (None, SCHEMA_VERSION),
                })
    failures = [record for record in records if not record["rules_ok"] or not record["schema_ok"]]
    return GateCheck(
        "policy_contract",
        "fail" if failures else "pass",
        observed={"artifacts": records, "failures": failures},
        threshold={"rules": rules_fingerprint(), "schema": SCHEMA_VERSION},
    )


def _failed_arena(
    candidate: Policy,
    opponent: Policy,
    pool: PoolSpec,
    *,
    boards: list[dict[str, int]],
    max_decisions: int,
    turn_budget: float | None,
    error: Exception,
) -> ArenaResult:
    """Represent a policy exception as censored data for an auditable reject."""

    by_board = {
        board_key(board): {
            "pairs": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "censored": 0,
            "score": 0.0,
            "scored_games": 0,
        }
        for board in boards
    }
    for index in range(pool.pairs):
        stats = by_board[board_key(boards[index % len(boards)])]
        stats["pairs"] += 1
        stats["censored"] += 2
    for stats in by_board.values():
        stats["score"] = 0.5
    return ArenaResult(
        candidate=_policy_name(candidate),
        opponent=_policy_name(opponent),
        games=2 * pool.pairs,
        pairs=pool.pairs,
        wins=0,
        losses=0,
        draws=0,
        censored=2 * pool.pairs,
        score_sum=0.0,
        pair_scores=[],
        by_board=by_board,
        settings={
            "pairs": pool.pairs,
            "seed": pool.root_seed,
            "max_decisions": max_decisions,
            "turn_budget": turn_budget,
            "boards": [dict(board) for board in boards],
            "balanced_boards": pool.pairs % len(boards) == 0,
            "error": f"{type(error).__name__}: {error}",
        },
        pair_scores_by_index=[None] * pool.pairs,
    )


def _balanced_ci(
    family_pair_scores: Mapping[str, list[list[float]]],
    *,
    samples: int,
    seed: int,
    empty_value: float = 0.5,
) -> tuple[float, float]:
    """Bootstrap equal family and equal opponent weights.

    Each opponent contributes one mean of its complete pair scores; those
    opponent means are averaged within a family, then family means are
    averaged across the pool.  This prevents a family with more retained
    members from dominating the gate.
    """

    rng = random.Random(seed)
    family_names = sorted(family_pair_scores)
    if not family_names:
        return (empty_value, empty_value)
    draws: list[float] = []
    for _ in range(max(1, samples)):
        family_means = []
        for family in family_names:
            opponent_means = []
            for pair_scores in family_pair_scores[family]:
                if pair_scores:
                    opponent_means.append(statistics.fmean(rng.choices(pair_scores, k=len(pair_scores))))
                else:
                    opponent_means.append(empty_value)
            family_means.append(statistics.fmean(opponent_means) if opponent_means else empty_value)
        draws.append(statistics.fmean(family_means))
    draws.sort()
    return draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]


def _evaluate_policy(
    policy: Policy,
    families: Mapping[str, list[Policy]],
    pool: PoolSpec,
    *,
    boards: list[dict[str, int]],
    max_decisions: int,
    turn_budget: float | None,
    bootstrap_samples: int,
    seed_salt: int,
) -> _PolicyPool:
    family_reports: dict[str, dict] = {}
    family_pair_scores: dict[str, list[list[float]]] = {}
    family_pair_scores_by_index: dict[str, list[list[float | None]]] = {}
    family_board_pair_scores_by_index: dict[str, list[dict[str, list[float | None]]]] = {}
    family_board_scores: dict[str, dict[str, float]] = {}
    total_games = total_censored = 0
    all_balanced = True

    for family_name, opponents in families.items():
        opponent_reports: dict[str, dict] = {}
        pair_lists: list[list[float]] = []
        pair_lists_by_index: list[list[float | None]] = []
        pair_board_lists_by_index: list[dict[str, list[float | None]]] = []
        board_lists: dict[str, list[float]] = {board_key(board): [] for board in boards}
        family_censored = 0
        family_balanced = True
        for opponent_index, opponent in enumerate(opponents):
            try:
                arena = run_arena(
                    policy,
                    opponent,
                    pairs=pool.pairs,
                    seed=pool.arena_seed(family_name, opponent_index),
                    max_decisions=max_decisions,
                    turn_budget=turn_budget,
                    configurations=boards,
                )
            except Exception as error:  # pragma: no cover - exercised by gate users
                arena = _failed_arena(
                    policy,
                    opponent,
                    pool,
                    boards=boards,
                    max_decisions=max_decisions,
                    turn_budget=turn_budget,
                    error=error,
                )
            report = arena.as_dict()
            key = _opponent_key(opponent)
            # Duplicate fingerprints in a family are retained as separate
            # entries only when their policy names differ; otherwise reject the
            # ambiguity before a report can be misread.
            if key in opponent_reports:
                raise ValueError(f"duplicate policy in Orbit family {family_name!r}: {key}")
            opponent_reports[key] = report
            pair_lists.append(list(arena.pair_scores))
            pair_lists_by_index.append(list(arena.pair_scores_by_index))
            pair_board_lists_by_index.append({
                board_key(board): [
                    value if (pair_index % len(boards)) == board_index else None
                    for pair_index, value in enumerate(arena.pair_scores_by_index)
                ]
                for board_index, board in enumerate(boards)
            })
            family_censored += arena.censored
            family_balanced = family_balanced and bool(report.get("balanced_boards"))
            for board, board_report in arena.by_board.items():
                board_lists.setdefault(board, []).append(float(board_report["score"]))
            total_games += arena.games
            total_censored += arena.censored
        family_pair_scores[family_name] = pair_lists
        family_pair_scores_by_index[family_name] = pair_lists_by_index
        family_board_pair_scores_by_index[family_name] = pair_board_lists_by_index
        family_score = statistics.fmean([
            float(report["pair_score"]) for report in opponent_reports.values()
        ]) if opponent_reports else 0.5
        family_board = {
            board: statistics.fmean(values) if values else 0.5
            for board, values in board_lists.items()
        }
        family_board_scores[family_name] = family_board
        family_ci = _balanced_ci(
            {family_name: pair_lists},
            samples=bootstrap_samples,
            seed=_sha_seed(seed_salt, family_name),
        )
        family_reports[family_name] = {
            "score": family_score,
            "pair_ci95": list(family_ci),
            "opponents": opponent_reports,
            "games": sum(int(report["games"]) for report in opponent_reports.values()),
            "censored": family_censored,
            "balanced_boards": family_balanced,
        }
        all_balanced = all_balanced and family_balanced

    family_scores = [report["score"] for report in family_reports.values()]
    overall_score = statistics.fmean(family_scores) if family_scores else 0.5
    overall_ci = _balanced_ci(
        family_pair_scores,
        samples=bootstrap_samples,
        seed=_sha_seed(seed_salt, "overall"),
    )
    boards_report = {}
    for board in [board_key(board) for board in boards]:
        values = [family_board_scores[family].get(board, 0.5) for family in family_reports]
        board_family_pair_scores = {
            family: [
                pair_scores
                for opponent_board_scores in family_board_pair_scores_by_index.get(family, [])
                for pair_scores in [
                    [score for score in opponent_board_scores.get(board, []) if score is not None]
                ]
            ]
            for family in family_reports
        }
        # ``_balanced_ci`` expects one list per opponent.  The comprehension
        # above preserves that shape, including empty lists for censored
        # opponents.
        board_ci = _balanced_ci(
            board_family_pair_scores,
            samples=bootstrap_samples,
            seed=_sha_seed(seed_salt, "board", board),
        )
        boards_report[board] = {
            "score": statistics.fmean(values) if values else 0.5,
            "pair_ci95": list(board_ci),
            "pairs": sum(
                len(pair_scores)
                for opponent_board_scores in family_board_pair_scores_by_index.values()
                for opponent in opponent_board_scores
                for pair_scores in [[
                    score for score in opponent.get(board, []) if score is not None
                ]]
            ),
            "families": {
                family: family_board_scores[family].get(board, 0.5)
                for family in family_reports
            },
        }
    report = {
        "policy": _policy_name(policy),
        "policy_fingerprint": policy_fingerprint(policy),
        "pool": pool.as_dict(),
        "score": overall_score,
        "pair_ci95": list(overall_ci),
        "families": family_reports,
        "boards": boards_report,
        "games": total_games,
        "censored": total_censored,
        "balanced_boards": all_balanced,
        "pairs": pool.pairs,
    }
    return _PolicyPool(
        policy=policy,
        report=report,
        family_pair_scores=family_pair_scores,
        family_pair_scores_by_index=family_pair_scores_by_index,
        family_board_pair_scores_by_index=family_board_pair_scores_by_index,
    )


def _compare_pool(
    candidate: Policy,
    incumbent: Policy,
    families: Mapping[str, list[Policy]],
    pool: PoolSpec,
    *,
    boards: list[dict[str, int]],
    config: GateConfig,
) -> dict:
    candidate_eval = _evaluate_policy(
        candidate,
        families,
        pool,
        boards=boards,
        max_decisions=config.max_decisions,
        turn_budget=config.turn_budget,
        bootstrap_samples=config.bootstrap_samples,
        seed_salt=_sha_seed(pool.name, "candidate"),
    )
    incumbent_eval = _evaluate_policy(
        incumbent,
        families,
        pool,
        boards=boards,
        max_decisions=config.max_decisions,
        turn_budget=config.turn_budget,
        bootstrap_samples=config.bootstrap_samples,
        seed_salt=_sha_seed(pool.name, "incumbent"),
    )
    candidate_report = candidate_eval.report
    incumbent_report = incumbent_eval.report
    # The candidate and incumbent arenas use the same pool seeds.  Resample
    # their per-pair outcome *differences* rather than subtracting two
    # independent confidence intervals; this preserves the variance reduction
    # promised by the CRN assignment swap.  A pair is retained only when both
    # policy evaluations completed both games.
    paired_family_scores: dict[str, list[list[float]]] = {}
    paired_family_board_scores: dict[str, list[dict[str, list[float]]]] = {}
    paired_censored = 0
    paired_pairs = 0
    for family in families:
        candidate_lists = candidate_eval.family_pair_scores_by_index[family]
        incumbent_lists = incumbent_eval.family_pair_scores_by_index[family]
        candidate_board_lists = candidate_eval.family_board_pair_scores_by_index[family]
        incumbent_board_lists = incumbent_eval.family_board_pair_scores_by_index[family]
        if len(candidate_lists) != len(incumbent_lists):
            raise ValueError("Orbit candidate/incumbent pair matrix mismatch")
        paired_lists: list[list[float]] = []
        paired_board_lists: list[dict[str, list[float]]] = []
        opponent_keys = list(candidate_report["families"][family]["opponents"])
        if len(opponent_keys) != len(candidate_lists):
            raise ValueError("Orbit candidate/incumbent opponent matrix mismatch")
        for (
            candidate_pairs,
            incumbent_pairs,
            candidate_boards,
            incumbent_boards,
        ) in zip(candidate_lists, incumbent_lists, candidate_board_lists, incumbent_board_lists):
            if len(candidate_pairs) != len(incumbent_pairs):
                raise ValueError("Orbit candidate/incumbent pair schedule mismatch")
            complete_deltas: list[float] = []
            for candidate_score, incumbent_score in zip(candidate_pairs, incumbent_pairs):
                if candidate_score is None or incumbent_score is None:
                    paired_censored += 1
                    continue
                complete_deltas.append(float(candidate_score) - float(incumbent_score))
                paired_pairs += 1
            paired_lists.append(complete_deltas)
            board_deltas: dict[str, list[float]] = {}
            for board in [board_key(item) for item in boards]:
                candidate_board_pairs = candidate_boards.get(board, [])
                incumbent_board_pairs = incumbent_boards.get(board, [])
                if len(candidate_board_pairs) != len(incumbent_board_pairs):
                    raise ValueError("Orbit candidate/incumbent board schedule mismatch")
                board_deltas[board] = [
                    float(candidate_score) - float(incumbent_score)
                    for candidate_score, incumbent_score in zip(candidate_board_pairs, incumbent_board_pairs)
                    if candidate_score is not None and incumbent_score is not None
                ]
            paired_board_lists.append(board_deltas)
        paired_family_scores[family] = paired_lists
        paired_family_board_scores[family] = paired_board_lists
    delta_ci = _balanced_ci(
        paired_family_scores,
        samples=config.bootstrap_samples,
        seed=_sha_seed(pool.name, "paired-delta"),
        empty_value=0.0,
    )
    matrix: dict[str, dict[str, dict]] = {}
    for family in families:
        matrix[family] = {}
        candidate_opponents = candidate_report["families"][family]["opponents"]
        incumbent_opponents = incumbent_report["families"][family]["opponents"]
        if set(candidate_opponents) != set(incumbent_opponents):
            raise ValueError("Orbit candidate/incumbent opponent matrix mismatch")
        for opponent_index, opponent_key in enumerate(candidate_opponents):
            candidate_opponent = candidate_opponents[opponent_key]
            incumbent_opponent = incumbent_opponents[opponent_key]
            board_deltas = {}
            board_delta_cis = {}
            for board in candidate_opponent["by_board"]:
                board_deltas[board] = (
                    float(candidate_opponent["by_board"][board]["score"])
                    - float(incumbent_opponent["by_board"][board]["score"])
                )
                board_delta_cis[board] = list(_balanced_ci(
                    {family: [paired_family_board_scores[family][opponent_index].get(board, [])]},
                    samples=config.bootstrap_samples,
                    seed=_sha_seed(pool.name, "paired-delta", family, opponent_key, board),
                    empty_value=0.0,
                ))
            opponent_delta_ci = _balanced_ci(
                {family: [paired_family_scores[family][opponent_index]]},
                samples=config.bootstrap_samples,
                seed=_sha_seed(pool.name, "paired-delta", family, opponent_key),
                empty_value=0.0,
            )
            matrix[family][opponent_key] = {
                "candidate_score": float(candidate_opponent["pair_score"]),
                "incumbent_score": float(incumbent_opponent["pair_score"]),
                "delta": float(candidate_opponent["pair_score"])
                - float(incumbent_opponent["pair_score"]),
                "delta_ci95": list(opponent_delta_ci),
                "board_deltas": board_deltas,
                "board_delta_ci95": board_delta_cis,
                "candidate": candidate_opponent,
                "incumbent": incumbent_opponent,
            }
    family_deltas = {
        family: float(candidate_report["families"][family]["score"])
        - float(incumbent_report["families"][family]["score"])
        for family in families
    }
    family_delta_cis = {
        family: list(_balanced_ci(
            {family: paired_family_scores[family]},
            samples=config.bootstrap_samples,
            seed=_sha_seed(pool.name, "paired-delta", family),
            empty_value=0.0,
        ))
        for family in families
    }
    board_deltas = {
        board: float(candidate_report["boards"][board]["score"])
        - float(incumbent_report["boards"][board]["score"])
        for board in candidate_report["boards"]
    }
    board_delta_cis = {
        board: list(_balanced_ci(
            {
                family: [
                    opponent_board_scores.get(board, [])
                    for opponent_board_scores in paired_family_board_scores.get(family, [])
                ]
                for family in families
            },
            samples=config.bootstrap_samples,
            seed=_sha_seed(pool.name, "paired-delta", "board", board),
            empty_value=0.0,
        ))
        for board in board_deltas
    }
    return {
        "pool": pool.as_dict(),
        "candidate": candidate_report,
        "incumbent": incumbent_report,
        "score_delta": float(candidate_report["score"]) - float(incumbent_report["score"]),
        "delta_ci95": list(delta_ci),
        "paired_pairs": paired_pairs,
        "paired_censored": paired_censored,
        "family_deltas": family_deltas,
        "family_delta_ci95": family_delta_cis,
        "board_deltas": board_deltas,
        "board_delta_ci95": board_delta_cis,
        "matrix": matrix,
        "balanced_boards": bool(candidate_report["balanced_boards"] and incumbent_report["balanced_boards"]),
        "censored": int(candidate_report["censored"] + incumbent_report["censored"]),
    }


def _finish_mulligan(game: dict) -> None:
    for pid in list(game["order"]):
        ok, error = engine.apply_move(game, pid, {"action": "mulligan", "card_ids": []})
        if not ok:
            raise RuntimeError(f"Orbit gate setup failed: {error}")


def _move_from_result(result: Decision | dict | None) -> dict | None:
    return result.move if isinstance(result, Decision) else result


def _information_check(policy: Policy, *, trials: int, seed: int) -> dict:
    failures: list[dict] = []
    for index in range(trials):
        game = engine.new_game(["seat0", "seat1"], seed=_sha_seed(seed, index))
        try:
            _finish_mulligan(game)
        except Exception as error:  # pragma: no cover - surfaced in the report
            failures.append({"trial": index, "reason": f"setup exception: {type(error).__name__}"})
            continue
        pid = game["turn_pid"]
        if pid is None:
            failures.append({"trial": index, "reason": "no turn owner"})
            continue
        obs = observation(game, pid)
        equivalent = copy.deepcopy(game)
        opponent = game["order"][1 - game["order"].index(pid)]
        opponent_hand = equivalent["players"][opponent].get("hand", [])
        if not equivalent["agent_deck"] or not opponent_hand:
            failures.append({"trial": index, "reason": "empty hidden pool"})
            continue
        equivalent["players"][opponent]["hand"][0], equivalent["agent_deck"][0] = (
            equivalent["agent_deck"][0], equivalent["players"][opponent]["hand"][0]
        )
        equivalent["agent_deck"].reverse()
        equivalent["bonus_deck"].reverse()
        rng_state = random.Random(_sha_seed(seed, "rng", index)).getstate()
        equivalent["rng_state"] = [rng_state[0], list(rng_state[1]), rng_state[2]]
        if observation(equivalent, pid) != obs:
            failures.append({"trial": index, "reason": "observation changed"})
            continue
        history = {"initial": copy.deepcopy(obs), "events": []}
        try:
            first = _move_from_result(policy.choose(
                game,
                pid,
                random.Random(_sha_seed(seed, "policy", index)),
                observation=obs,
                history=history,
                belief=None,
            ))
            second = _move_from_result(policy.choose(
                equivalent,
                pid,
                random.Random(_sha_seed(seed, "policy", index)),
                observation=obs,
                history=history,
                belief=None,
            ))
        except Exception as error:  # pragma: no cover - surfaced in the report
            failures.append({"trial": index, "reason": f"policy exception: {type(error).__name__}"})
            continue
        legal = engine.legal_moves(game, pid)
        if first not in legal or second not in legal:
            failures.append({"trial": index, "reason": "illegal move"})
        elif first != second:
            failures.append({"trial": index, "reason": "hidden-world dependent move"})
    return {"trials": trials, "failures": failures, "passed": not failures}


def _correctness_check(
    policy: Policy,
    *,
    pairs: int,
    trials: int,
    seed: int,
    max_decisions: int,
    turn_budget: float | None = None,
) -> dict:
    try:
        mirror = mirror_sanity(
            policy,
            pairs=pairs,
            seed=_sha_seed(seed, "mirror"),
            max_decisions=max_decisions,
            turn_budget=turn_budget,
        )
    except Exception as error:  # pragma: no cover - surfaced in the report
        mirror = {
            "score": None,
            "games": 0,
            "censored": 2 * pairs,
            "exact_half": False,
            "error": f"{type(error).__name__}: {error}",
        }
    fallback_moves = 0
    censored = int(mirror["censored"])
    episode_failures = 0
    episodes = []
    boards = board_configurations()
    for index in range(trials):
        try:
            episode = play_game(
                (policy, policy),
                seed=_sha_seed(seed, "episode", index),
                configuration=boards[index % len(boards)],
                max_decisions=max_decisions,
                turn_budget=turn_budget,
            )
        except Exception as error:  # pragma: no cover - surfaced in the report
            episodes.append({
                "seed": _sha_seed(seed, "episode", index),
                "censored": True,
                "fallback_moves": 0,
                "error": f"{type(error).__name__}: {error}",
            })
            censored += 1
            episode_failures += 1
            continue
        episodes.append({
            "seed": episode.seed,
            "censored": episode.censored,
            "fallback_moves": int(episode.metadata.get("fallback_moves", 0)),
        })
        fallback_moves += int(episode.metadata.get("fallback_moves", 0))
        censored += int(episode.censored)
    # A capped game cannot certify a terminal outcome, but it is not evidence
    # of an illegal policy move either.  Keep this distinction explicit so a
    # deliberately tiny smoke gate is inconclusive rather than falsely
    # reported as a correctness failure; any fallback or mirror mismatch is a
    # hard failure.
    passed = bool(mirror["exact_half"] and fallback_moves == 0 and censored == 0)
    failed = bool(not mirror["exact_half"] or fallback_moves or episode_failures)
    return {
        "passed": passed,
        "failed": failed,
        "inconclusive": bool(not failed and censored),
        "mirror": mirror,
        "fallback_moves": fallback_moves,
        "episode_failures": episode_failures,
        "censored": censored,
        "episodes": episodes,
    }


def _timing_check(
    policy: Policy,
    *,
    trials: int,
    seed: int,
    limit: float,
    time_budget: float | None = None,
) -> dict:
    durations: list[float] = []
    failures: list[Any] = []
    for index in range(trials):
        game = engine.new_game(["seat0", "seat1"], seed=_sha_seed(seed, index))
        try:
            _finish_mulligan(game)
        except Exception as error:  # pragma: no cover - surfaced in the report
            failures.append({"trial": index, "reason": f"setup exception: {type(error).__name__}"})
            continue
        pid = game["turn_pid"]
        if pid is None:
            failures.append("no turn owner")
            continue
        obs = observation(game, pid)
        started = time.perf_counter()
        try:
            policy.choose(
                game,
                pid,
                random.Random(_sha_seed(seed, "policy", index)),
                observation=obs,
                history={"initial": copy.deepcopy(obs), "events": []},
                time_budget=time_budget,
                belief=None,
            )
        except Exception as error:  # pragma: no cover - surfaced in the report
            failures.append(type(error).__name__)
            continue
        durations.append(time.perf_counter() - started)
    ordered = sorted(durations)
    p50 = ordered[(len(ordered) - 1) // 2] if ordered else None
    p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))] if ordered else None
    return {
        "trials": trials,
        "durations_seconds": durations,
        "p50_seconds": p50,
        "p95_seconds": p95,
        "max_seconds": max(durations) if durations else None,
        "limit_seconds": limit,
        "time_budget_seconds": time_budget,
        "failures": failures,
        "within_limit": not failures and bool(durations) and p95 <= limit,
    }


def _external_timing_check(evidence: Mapping[str, Any] | None, config: GateConfig) -> GateCheck:
    """Validate a serving/WASM timing manifest supplied by the campaign.

    Python timings are retained as diagnostics, but they never satisfy the
    Phase 4 timing gate by themselves.  The manifest is intentionally small so
    a browser benchmark can be produced by a separate tool and reviewed with
    the same report.
    """

    if not isinstance(evidence, Mapping):
        return GateCheck(
            "serving_timing_manifest",
            "inconclusive",
            observed={"provided": False},
            threshold={"workers": config.serving_workers, "p95_seconds": config.timing_limit},
        )
    backend = str(evidence.get("backend", evidence.get("source", ""))).strip().lower()
    workers = evidence.get("workers", evidence.get("serving_workers"))
    candidate = evidence.get("candidate", {})
    incumbent = evidence.get("incumbent", {})
    if not isinstance(candidate, Mapping) or not isinstance(incumbent, Mapping):
        return GateCheck(
            "serving_timing_manifest",
            "fail",
            observed={"provided": True, "reason": "candidate/incumbent metrics missing"},
            threshold={"backend": "wasm", "workers": config.serving_workers},
        )
    try:
        candidate_p95 = float(candidate.get("p95_seconds"))
        incumbent_p95 = float(incumbent.get("p95_seconds"))
    except (TypeError, ValueError):
        return GateCheck(
            "serving_timing_manifest",
            "fail",
            observed={"provided": True, "reason": "p95_seconds missing or non-numeric"},
            threshold={"backend": "wasm", "workers": config.serving_workers},
        )
    if not all(math.isfinite(value) and value >= 0 for value in (candidate_p95, incumbent_p95)):
        return GateCheck(
            "serving_timing_manifest",
            "fail",
            observed={"provided": True, "reason": "p95_seconds must be finite and non-negative"},
            threshold={"backend": "wasm", "workers": config.serving_workers},
        )
    observed = {
        "provided": True,
        "backend": backend,
        "workers": workers,
        "candidate_p95_seconds": candidate_p95,
        "incumbent_p95_seconds": incumbent_p95,
    }
    threshold = {
        "backend": "wasm",
        "workers": config.serving_workers,
        "p95_seconds": config.timing_limit,
    }
    if backend not in {"wasm", "rust-wasm", "browser-wasm"}:
        return GateCheck("serving_timing_manifest", "fail", observed=observed, threshold=threshold)
    try:
        workers_match = config.serving_workers is not None and int(workers) == int(config.serving_workers)
    except (TypeError, ValueError):
        workers_match = False
    if not workers_match:
        return GateCheck("serving_timing_manifest", "fail", observed=observed, threshold=threshold)
    passed = candidate_p95 <= config.timing_limit and incumbent_p95 <= config.timing_limit
    return GateCheck(
        "serving_timing_manifest",
        "pass" if passed else "fail",
        observed=observed,
        threshold=threshold,
    )


def _holdout_check(
    families: Mapping[str, list[Policy]],
    pools: Sequence[PoolSpec],
    *,
    training_seeds: set[int],
    training_policy_fingerprints: set[str],
    training_family_names: set[str] = frozenset(),
    training_run_ids: set[str] = frozenset(),
) -> GateCheck:
    """Require a complete training manifest and prove it is disjoint."""
    family_fingerprints = {
        policy_fingerprint(policy)
        for policies in families.values()
        for policy in policies
    }
    fingerprint_overlap = sorted(family_fingerprints & training_policy_fingerprints)
    generated_seeds = set()
    family_names = set(families) | {"__incumbent__"}
    for pool in pools:
        for family in family_names:
            policies = families.get(family, [None])
            for opponent_index in range(len(policies)):
                generated_seeds.update(
                    pool.pair_seed(family, opponent_index, pair_index)
                    for pair_index in range(pool.pairs)
                )
    seed_overlap = sorted(generated_seeds & training_seeds)
    pool_ids = {
        f"{pool.name}:{pool.root_seed}"
        for pool in pools
    }
    run_overlap = sorted(pool_ids & training_run_ids)
    family_overlap = sorted(set(families) & training_family_names)
    manifest_provided = bool(
        training_seeds or training_policy_fingerprints or training_family_names or training_run_ids
    )
    missing_fields = [
        field
        for field, values in (
            ("deal_seeds", training_seeds),
            ("policy_fingerprints", training_policy_fingerprints),
            ("opponent_families", training_family_names),
        )
        if not values
    ]
    complete_manifest = not missing_fields
    passed = complete_manifest and not fingerprint_overlap and not seed_overlap and not family_overlap and not run_overlap
    state = "pass" if passed else "inconclusive" if not complete_manifest else "fail"
    return GateCheck(
        "holdout_separation",
        state,
        observed={
            "families": sorted(families),
            "opponent_fingerprints": sorted(family_fingerprints),
            "training_manifest_provided": manifest_provided,
            "overlapping_policy_fingerprints": fingerprint_overlap,
            "overlapping_deal_seeds": seed_overlap[:20],
            "overlapping_opponent_families": family_overlap,
            "overlapping_training_runs": run_overlap,
            "missing_manifest_fields": missing_fields,
        },
        details={
            "checked_deal_seeds": len(generated_seeds),
            "training_families_provided": bool(training_family_names),
            "training_runs_provided": bool(training_run_ids),
        },
    )


def _pool_separation_check(
    pools: Sequence[PoolSpec],
    families: Mapping[str, list[Policy]],
    *,
    include_incumbent_matchup: bool = True,
) -> GateCheck:
    seeds = []
    for pool in pools:
        sample = {
            pool.pair_seed(family, opponent_index, pair_index)
            for family, policies in (
                list(families.items())
                + ([ ("__incumbent__", [None]) ] if include_incumbent_matchup else [])
            )
            for opponent_index in range(len(policies))
            for pair_index in range(pool.pairs)
        }
        seeds.append(sample)
    overlaps = []
    for left_index, left in enumerate(seeds):
        for right in seeds[left_index + 1:]:
            overlaps.extend(left & right)
    return GateCheck(
        "pool_separation",
        "pass" if not overlaps else "fail",
        observed={"pools": [pool.name for pool in pools], "overlap_count": len(overlaps)},
    )


def _regression_check(comparison: dict, limit: float) -> GateCheck:
    # A point estimate below the five-point guard is only a possible
    # regression.  Fail this gate only when the paired 95% interval is wholly
    # below the guard; a broad interval remains inconclusive and therefore
    # cannot promote a candidate prematurely.
    if int(comparison.get("paired_pairs", 0)) == 0:
        return GateCheck(
            "no_confirmed_regression",
            "inconclusive",
            observed={"paired_pairs": 0, "paired_censored": comparison.get("paired_censored", 0)},
            threshold=-limit,
        )
    intervals: list[tuple[float, float, str, float]] = []
    for family, interval in comparison.get("family_delta_ci95", {}).items():
        intervals.append((float(interval[0]), float(interval[1]), f"family:{family}", comparison["family_deltas"].get(family, 0.0)))
    for board, interval in comparison.get("board_delta_ci95", {}).items():
        intervals.append((float(interval[0]), float(interval[1]), f"board:{board}", comparison["board_deltas"].get(board, 0.0)))
    for family, opponents in comparison["matrix"].items():
        for opponent, values in opponents.items():
            interval = values.get("delta_ci95", [0.0, 0.0])
            intervals.append((float(interval[0]), float(interval[1]), f"opponent:{family}/{opponent}", values["delta"]))
            for board, board_interval in values.get("board_delta_ci95", {}).items():
                intervals.append((
                    float(board_interval[0]),
                    float(board_interval[1]),
                    f"opponent-board:{family}/{opponent}/{board}",
                    values["board_deltas"].get(board, 0.0),
                ))
    if not intervals:
        return GateCheck("no_confirmed_regression", "inconclusive", observed=None, threshold=-limit)
    worst_point = min(intervals, key=lambda item: item[3])
    confirmed = [item for item in intervals if item[1] < -limit]
    possible = [item for item in intervals if item[0] < -limit]
    if confirmed:
        worst = min(confirmed, key=lambda item: item[1])
        state = "fail"
        observed = {
            "worst_delta": worst[3],
            "worst_ci95": [worst[0], worst[1]],
            "location": worst[2],
            "confirmed_count": len(confirmed),
        }
    elif possible:
        state = "inconclusive"
        observed = {
            "worst_delta": worst_point[3],
            "worst_ci95": [worst_point[0], worst_point[1]],
            "location": worst_point[2],
            "possible_count": len(possible),
        }
    else:
        state = "pass"
        observed = {
            "worst_delta": worst_point[3],
            "worst_ci95": [worst_point[0], worst_point[1]],
            "location": worst_point[2],
        }
    return GateCheck(
        "no_confirmed_regression",
        state,
        observed=observed,
        threshold=-limit,
    )


def _interval_check(
    name: str,
    interval: Sequence[float],
    *,
    threshold: float,
    direction: str,
    sample_count: int | None = None,
) -> GateCheck:
    low, high = float(interval[0]), float(interval[1])
    if sample_count is not None and sample_count <= 0:
        state = "inconclusive"
    elif direction == "above":
        state = "pass" if low > threshold else "fail" if high <= threshold else "inconclusive"
    else:
        state = "pass" if high < threshold else "fail" if low >= threshold else "inconclusive"
    observed = {"ci95": [low, high]}
    if sample_count is not None:
        observed["complete_samples"] = int(sample_count)
    return GateCheck(name, state, observed=observed, threshold=threshold)


@dataclass
class PromotionResult:
    """Complete Phase 4 report and decision."""

    status: str
    candidate: str
    incumbent: str
    seed: int
    config: dict
    pools: dict
    development: dict
    confirmation_cycles: list[dict]
    confirmation: dict
    incumbent_matchup: dict
    checks: dict[str, GateCheck]
    reasons: list[str]
    training_manifest: dict = field(default_factory=dict)
    timing_evidence: dict = field(default_factory=dict)
    rules: str = field(default_factory=rules_fingerprint)
    schema: int = SCHEMA_VERSION

    @property
    def promoted(self) -> bool:
        return self.status == "promote"

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "rules": self.rules,
            "status": self.status,
            "promoted": self.promoted,
            "candidate": self.candidate,
            "incumbent": self.incumbent,
            "seed": self.seed,
            "config": copy.deepcopy(self.config),
            "pools": copy.deepcopy(self.pools),
            "development": copy.deepcopy(self.development),
            "confirmation_cycles": copy.deepcopy(self.confirmation_cycles),
            "confirmation": copy.deepcopy(self.confirmation),
            "incumbent_matchup": copy.deepcopy(self.incumbent_matchup),
            "checks": {name: check.as_dict() for name, check in self.checks.items()},
            "reasons": list(self.reasons),
            "training_manifest": copy.deepcopy(self.training_manifest),
            "timing_evidence": copy.deepcopy(self.timing_evidence),
        }


def run_promotion_gate(
    candidate: Policy,
    incumbent: Policy,
    opponent_families: Mapping[str, Policy | Sequence[Policy]],
    *,
    config: GateConfig | None = None,
    seed: int = 0,
    training_seeds: Sequence[int] = (),
    training_policy_fingerprints: Sequence[str] = (),
    training_family_names: Sequence[str] = (),
    training_run_ids: Sequence[str] = (),
    timing_evidence: Mapping[str, Any] | None = None,
) -> PromotionResult:
    """Run screening, sealed confirmation and all Phase 4 gates.

    ``opponent_families`` is the held-out attack surface.  A value can be one
    policy or a sequence of retained specialists/exploiters; each family gets
    equal weight in the aggregate regardless of its member count.  The optional
    training manifest is checked against generated pair seeds, policy
    fingerprints and family names.  ``timing_evidence`` is a separate browser
    benchmark manifest; local Python timings remain diagnostics only.
    """

    config = config or GateConfig()
    families = _normalise_families(opponent_families)
    boards = config.board_list()
    if len(boards) != 8 and config.boards is None:
        raise ValueError("Orbit Phase 4 default pool must contain all eight boards")
    for board in boards:
        try:
            valid_board = set(board) == set(FACTIONS) and all(
                int(board[faction]) in (1, 2) for faction in FACTIONS
            )
        except (TypeError, ValueError):
            valid_board = False
        if not valid_board:
            raise ValueError("Orbit Phase 4 boards must map every faction to side 1 or 2")
    if len({board_key(board) for board in boards}) != len(boards):
        raise ValueError("Orbit Phase 4 boards must be unique")
    base_seed = int(seed)
    training_seed_values = sorted({int(value) for value in training_seeds})
    training_fingerprint_values = sorted({str(value) for value in training_policy_fingerprints})
    training_family_values = sorted({str(value) for value in training_family_names})
    training_run_values = sorted({str(value) for value in training_run_ids})
    development_pool = PoolSpec(
        "development",
        _sha_seed("orbit-phase4-root", base_seed, "development"),
        config.screening_pairs,
        sealed=False,
    )
    confirmation_pairs = config.confirmation_pairs
    confirmation_pool = PoolSpec(
        "confirmation",
        _sha_seed("orbit-phase4-root", base_seed, "confirmation"),
        confirmation_pairs,
        sealed=True,
    )
    development = _compare_pool(candidate, incumbent, families, development_pool, boards=boards, config=config)
    confirmation_cycles: list[dict] = []
    final_confirmation = None
    final_incumbent_matchup = None
    while True:
        confirmation_pool = PoolSpec(
            "confirmation",
            _sha_seed("orbit-phase4-root", base_seed, "confirmation"),
            confirmation_pairs,
            sealed=True,
        )
        comparison = _compare_pool(candidate, incumbent, families, confirmation_pool, boards=boards, config=config)
        try:
            incumbent_arena = run_arena(
                candidate,
                incumbent,
                pairs=confirmation_pairs,
                seed=confirmation_pool.arena_seed("__incumbent__", 0),
                max_decisions=config.max_decisions,
                turn_budget=config.turn_budget,
                configurations=boards,
            )
        except Exception as error:  # pragma: no cover - surfaced in the report
            incumbent_arena = _failed_arena(
                candidate,
                incumbent,
                confirmation_pool,
                boards=boards,
                max_decisions=config.max_decisions,
                turn_budget=config.turn_budget,
                error=error,
            )
        incumbent_report = incumbent_arena.as_dict()
        cycle = {
            "pairs": confirmation_pairs,
            "comparison": comparison,
            "incumbent_matchup": incumbent_report,
        }
        confirmation_cycles.append(cycle)
        final_confirmation = comparison
        final_incumbent_matchup = incumbent_report
        overall_supported = comparison["delta_ci95"][0] > 0
        matchup_supported = incumbent_report["pair_ci95"][0] > 0.5
        uncertain = not overall_supported and comparison["delta_ci95"][1] > 0
        uncertain = uncertain or (not matchup_supported and incumbent_report["pair_ci95"][1] > 0.5)
        if not uncertain or confirmation_pairs >= config.max_confirmation_pairs:
            break
        confirmation_pairs = min(config.max_confirmation_pairs, confirmation_pairs * 2)

    assert final_confirmation is not None and final_incumbent_matchup is not None
    # Rebuild the confirmation descriptor after any interval expansion so the
    # sealed/holdout checks cover every pair that was actually played.
    final_confirmation_pool = PoolSpec(
        "confirmation",
        _sha_seed("orbit-phase4-root", base_seed, "confirmation"),
        confirmation_pairs,
        sealed=True,
    )
    pools = [development_pool, final_confirmation_pool]
    holdout = _holdout_check(
        families,
        pools,
        training_seeds=set(training_seed_values),
        training_policy_fingerprints=set(training_fingerprint_values),
        training_family_names=set(training_family_values),
        training_run_ids=set(training_run_values),
    )
    pool_separation = _pool_separation_check(pools, families)
    checks: dict[str, GateCheck] = {
        "rules_schema": GateCheck(
            "rules_schema",
            "pass" if rules_fingerprint() and SCHEMA_VERSION > 0 else "fail",
            observed={"rules": rules_fingerprint(), "schema": SCHEMA_VERSION},
        ),
        "policy_contract": _policy_contract_check(candidate, incumbent),
        "holdout_separation": holdout,
        "pool_separation": pool_separation,
        "balanced_pool": GateCheck(
            "balanced_pool",
            "pass"
            if final_confirmation["balanced_boards"]
            and final_incumbent_matchup.get("balanced_boards", False)
            and (
                not config.require_no_censoring
                or (
                    final_confirmation["censored"] == 0
                    and final_incumbent_matchup.get("censored", 0) == 0
                )
            )
            else "inconclusive",
            observed={
                "candidate_incumbent_matrix_balanced": final_confirmation["balanced_boards"],
                "direct_matchup_balanced": final_incumbent_matchup.get("balanced_boards", False),
                "censored": final_confirmation["censored"] + final_incumbent_matchup.get("censored", 0),
            },
            threshold="all eight boards and configured censoring policy",
        ),
        "screening_signal": _interval_check(
            "screening_signal",
            development["delta_ci95"],
            threshold=0.0,
            direction="above",
            sample_count=development.get("paired_pairs", 0),
        ),
        "supported_balanced_improvement": _interval_check(
            "supported_balanced_improvement",
            final_confirmation["delta_ci95"],
            threshold=0.0,
            direction="above",
            sample_count=final_confirmation.get("paired_pairs", 0),
        ),
        "positive_incumbent_matchup": _interval_check(
            "positive_incumbent_matchup",
            final_incumbent_matchup["pair_ci95"],
            threshold=0.5,
            direction="above",
            sample_count=final_incumbent_matchup.get("complete_pairs", 0),
        ),
        "no_confirmed_regression": _regression_check(final_confirmation, config.regression_limit),
    }

    candidate_correctness = _correctness_check(
        candidate,
        pairs=config.correctness_pairs,
        trials=config.correctness_pairs,
        seed=_sha_seed(base_seed, "correctness", "candidate"),
        max_decisions=config.max_decisions,
        turn_budget=config.turn_budget,
    )
    incumbent_correctness = _correctness_check(
        incumbent,
        pairs=config.correctness_pairs,
        trials=config.correctness_pairs,
        seed=_sha_seed(base_seed, "correctness", "incumbent"),
        max_decisions=config.max_decisions,
        turn_budget=config.turn_budget,
    )
    checks["correctness"] = GateCheck(
        "correctness",
        (
            "fail"
            if candidate_correctness["failed"] or incumbent_correctness["failed"]
            else "pass"
            if candidate_correctness["passed"] and incumbent_correctness["passed"]
            else "inconclusive"
        ),
        observed={"candidate": candidate_correctness, "incumbent": incumbent_correctness},
        threshold="zero illegal fallbacks/censored games and exact mirror 0.5",
    )

    candidate_information = _information_check(
        candidate,
        trials=config.information_trials,
        seed=_sha_seed(base_seed, "information", "candidate"),
    )
    incumbent_information = _information_check(
        incumbent,
        trials=config.information_trials,
        seed=_sha_seed(base_seed, "information", "incumbent"),
    )
    checks["information_invariance"] = GateCheck(
        "information_invariance",
        "pass"
        if candidate_information["passed"] and incumbent_information["passed"]
        else "fail",
        observed={"candidate": candidate_information, "incumbent": incumbent_information},
        threshold="equivalent hidden worlds produce the same legal decision",
    )

    candidate_timing = _timing_check(
        candidate,
        trials=config.timing_trials,
        seed=_sha_seed(base_seed, "timing", "candidate"),
        limit=config.timing_limit,
        time_budget=config.turn_budget,
    )
    incumbent_timing = _timing_check(
        incumbent,
        trials=config.timing_trials,
        seed=_sha_seed(base_seed, "timing", "incumbent"),
        limit=config.timing_limit,
        time_budget=config.turn_budget,
    )
    timing_observed = {"candidate": candidate_timing, "incumbent": incumbent_timing}
    timing_manifest = _external_timing_check(timing_evidence, config)
    if candidate_timing["failures"] or incumbent_timing["failures"]:
        timing_state = "fail"
    elif not config.timing_calibrated:
        timing_state = "inconclusive"
    elif timing_manifest.passed:
        # The browser/WASM manifest is authoritative for promotion.  Local
        # Python timings remain diagnostics because their interpreter and
        # search implementation are not the serving path.
        timing_state = "pass"
    elif timing_manifest.inconclusive:
        timing_state = "inconclusive"
    else:
        timing_state = "fail"
    checks["timing_calibration"] = GateCheck(
        "timing_calibration",
        timing_state,
        observed={
            "source": config.timing_source,
            "serving_workers": config.serving_workers,
            "serving_profile": config.serving_profile,
            **timing_observed,
        },
        threshold=config.timing_limit,
    )
    checks["serving_timing_manifest"] = timing_manifest
    checks["equal_time_budget"] = GateCheck(
        "equal_time_budget",
        "pass"
        if config.turn_budget is not None and config.serving_workers is not None
        else "inconclusive",
        observed={
            "turn_budget": config.turn_budget,
            "serving_workers": config.serving_workers,
        },
        threshold="explicit shared turn budget and worker arrangement",
    )

    reasons = []
    hard_fail = False
    for name, check in checks.items():
        if check.state == "fail":
            hard_fail = True
            reasons.append(f"{name}: failed")
        elif check.state == "inconclusive":
            reasons.append(f"{name}: inconclusive")
    if hard_fail:
        status = "reject"
    elif all(check.passed for check in checks.values()):
        status = "promote"
    else:
        status = "inconclusive"
    return PromotionResult(
        status=status,
        candidate=_policy_name(candidate),
        incumbent=_policy_name(incumbent),
        seed=base_seed,
        config=config.as_dict(),
        pools={
            "training": {
                "name": "training",
                "sealed": False,
                "external_manifest": True,
                "seed_count": len(training_seed_values),
                "policy_fingerprint_count": len(training_fingerprint_values),
                "opponent_family_count": len(training_family_values),
                "run_count": len(training_run_values),
            },
            **{pool.name: pool.as_dict() for pool in pools},
        },
        development=development,
        confirmation_cycles=confirmation_cycles,
        confirmation=final_confirmation,
        incumbent_matchup=final_incumbent_matchup,
        checks=checks,
        reasons=reasons,
        training_manifest={
            "seed_count": len(training_seed_values),
            "seeds": training_seed_values,
            "policy_fingerprint_count": len(training_fingerprint_values),
            "policy_fingerprints": training_fingerprint_values,
            "opponent_families": training_family_values,
            "run_ids": training_run_values,
        },
        timing_evidence=copy.deepcopy(dict(timing_evidence)) if isinstance(timing_evidence, Mapping) else {},
    )


# A descriptive alias keeps callers free to use either name while the plan
# refers to these as promotion-gate settings.
PromotionConfig = GateConfig


__all__ = [
    "GateCheck",
    "GateConfig",
    "PoolSpec",
    "PromotionConfig",
    "PromotionResult",
    "run_promotion_gate",
]
