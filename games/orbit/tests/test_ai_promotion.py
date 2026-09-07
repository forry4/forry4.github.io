from __future__ import annotations

import json

from games.orbit.ai.promotion import (
    GateCheck,
    GateConfig,
    PoolSpec,
    _external_timing_check,
    _holdout_check,
    _interval_check,
    _regression_check,
    run_promotion_gate,
)
from games.orbit.ai.search import HeuristicPolicy, RandomPolicy


def test_gate_config_requires_timing_provenance_when_calibrated():
    try:
        GateConfig(timing_calibrated=True)
    except ValueError as error:
        assert "provenance" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("an unverified timing gate must not be calibrated")


def test_external_timing_manifest_must_match_wasm_worker_shape():
    config = GateConfig(
        timing_calibrated=True,
        timing_source="browser smoke",
        serving_workers=4,
        serving_profile="wasm-release",
    )
    evidence = {
        "backend": "wasm",
        "workers": 4,
        "candidate": {"p95_seconds": 2.1},
        "incumbent": {"p95_seconds": 2.4},
    }
    assert _external_timing_check(evidence, config).passed
    evidence["workers"] = 2
    assert _external_timing_check(evidence, config).state == "fail"


def test_policy_contract_rejects_stale_rules_artifacts():
    stale = HeuristicPolicy()
    stale.rules = "old-rules"
    config = GateConfig(
        screening_pairs=1,
        confirmation_pairs=1,
        max_confirmation_pairs=1,
        max_decisions=1,
        bootstrap_samples=1,
        information_trials=1,
        correctness_pairs=1,
        timing_trials=1,
    )
    result = run_promotion_gate(
        stale,
        HeuristicPolicy(),
        {"random": RandomPolicy()},
        config=config,
        seed=7,
    )
    assert result.checks["policy_contract"].state == "fail"


def test_pool_namespaces_and_holdout_manifest_are_auditable():
    development = PoolSpec("development", 11, 4, False)
    confirmation = PoolSpec("confirmation", 11, 4, True)
    dev_seeds = {
        development.pair_seed("random", 0, index)
        for index in range(development.pairs)
    }
    confirm_seeds = {
        confirmation.pair_seed("random", 0, index)
        for index in range(confirmation.pairs)
    }
    assert dev_seeds.isdisjoint(confirm_seeds)
    check = _holdout_check(
        {"random": [RandomPolicy()]},
        [development, confirmation],
        training_seeds={next(iter(dev_seeds))},
        training_policy_fingerprints=set(),
        training_family_names=set(),
    )
    assert check.state != "pass"
    assert check.observed["overlapping_deal_seeds"]
    run_check = _holdout_check(
        {"random": [RandomPolicy()]},
        [development, confirmation],
        training_seeds=set(),
        training_policy_fingerprints=set(),
        training_family_names=set(),
        training_run_ids={f"development:{development.root_seed}"},
    )
    assert run_check.state != "pass"


def test_interval_and_regression_checks_distinguish_uncertainty():
    assert _interval_check("x", [0.01, 0.04], threshold=0.0, direction="above").passed
    assert _interval_check("x", [-0.04, 0.04], threshold=0.0, direction="above").inconclusive
    assert _interval_check("x", [0.0, 0.0], threshold=0.0, direction="above", sample_count=0).inconclusive
    assert _regression_check(
        {
            "paired_pairs": 2,
            "paired_censored": 0,
            "family_delta_ci95": {"f": [-0.04, 0.01]},
            "board_delta_ci95": {},
            "family_deltas": {"f": -0.01},
            "board_deltas": {},
            "matrix": {},
        },
        0.05,
    ).passed
    assert _regression_check(
        {
            "paired_pairs": 2,
            "paired_censored": 0,
            "family_delta_ci95": {"f": [-0.10, -0.06]},
            "board_delta_ci95": {},
            "family_deltas": {"f": -0.08},
            "board_deltas": {},
            "matrix": {},
        },
        0.05,
    ).state == "fail"


def test_phase4_gate_writes_full_report_without_promoting_identical_policies():
    config = GateConfig(
        screening_pairs=1,
        confirmation_pairs=1,
        max_confirmation_pairs=1,
        max_decisions=220,
        bootstrap_samples=12,
        information_trials=1,
        correctness_pairs=1,
        timing_trials=1,
        turn_budget=0.2,
        boards=({"robot": 2, "human": 2, "animod": 2},),
    )
    result = run_promotion_gate(
        HeuristicPolicy(),
        HeuristicPolicy(),
        {"random": RandomPolicy()},
        config=config,
        seed=91,
    )
    payload = result.as_dict()
    assert result.status == "reject"
    assert not result.promoted
    assert payload["rules"]
    assert payload["confirmation_cycles"]
    assert payload["confirmation"]["matrix"]["random"]
    assert payload["confirmation"]["paired_pairs"] == 1
    assert payload["training_manifest"]["seed_count"] == 0
    assert set(payload["checks"]) >= {
        "rules_schema",
        "holdout_separation",
        "pool_separation",
        "balanced_pool",
        "supported_balanced_improvement",
        "positive_incumbent_matchup",
        "no_confirmed_regression",
        "correctness",
        "information_invariance",
        "timing_calibration",
        "equal_time_budget",
    }
    # The report is JSON-safe, including GateCheck observed data and cycles.
    json.dumps(payload)
