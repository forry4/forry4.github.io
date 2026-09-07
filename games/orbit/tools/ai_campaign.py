"""Command-line entry points for Orbit offline AI experiments.

Examples (run from the repository root)::

    python -m games.orbit.tools.ai_campaign arena --candidate search --opponent heuristic --pairs 32
    python -m games.orbit.tools.ai_campaign bootstrap --games 128 --out build/orbit/bootstrap.jsonl
    python -m games.orbit.tools.ai_campaign cycle --episodes 64 --model-out build/orbit/model.json
    python -m games.orbit.tools.ai_campaign gate --candidate search --incumbent heuristic --turn-budget 3

The tool is offline-only.  It writes explicit rules fingerprints and settings
with every artifact; it does not alter the server bot or browser bundle.  A
gate report is advisory until a human reviews the full matrix and a calibrated
serving/WASM timing manifest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..ai.league import League, generate_bootstrap, run_population_cycle, train_neural_candidate
from ..ai.neural import NeuralGuide, NeuralPolicy
from ..ai.promotion import GateConfig, run_promotion_gate
from ..ai.search import HeuristicPolicy, InformationSetSearch, RandomPolicy, SearchConfig, SearchPolicy
from ..ai.selfplay import compare_algorithms, read_episodes, run_arena, write_episodes
from ..ai.state import rules_fingerprint


def _policy(name: str, args, *, model_path: Path | None = None):
    if name == "random":
        return RandomPolicy()
    if name == "heuristic":
        return HeuristicPolicy()
    if name == "search":
        return SearchPolicy(InformationSetSearch(SearchConfig(
            simulations=args.simulations,
            time_limit=args.time_limit,
            max_depth=args.max_depth,
        )))
    if name == "neural":
        model = model_path or getattr(args, "model", None)
        if not model:
            raise ValueError("--model is required for the neural policy")
        guide = NeuralGuide.from_dict(json.loads(Path(model).read_text(encoding="utf-8")))
        return NeuralPolicy(guide)
    raise ValueError(f"unknown Orbit policy: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    arena = sub.add_parser("arena", help="run a paired arena")
    arena.add_argument("--candidate", choices=("random", "heuristic", "search", "neural"), default="search")
    arena.add_argument("--opponent", choices=("random", "heuristic", "search", "neural"), default="heuristic")
    arena.add_argument("--pairs", type=int, default=32)
    arena.add_argument("--seed", type=int, default=0)
    arena.add_argument("--max-decisions", type=int, default=1600)
    arena.add_argument("--turn-budget", type=float)
    arena.add_argument("--time-limit", type=float, default=0.10)
    arena.add_argument("--simulations", type=int, default=128)
    arena.add_argument("--max-depth", type=int, default=96)
    arena.add_argument("--model", type=Path, help="JSON neural model for a neural side")

    compare = sub.add_parser("compare", help="compare random, heuristic and search policies")
    compare.add_argument("--pairs", type=int, default=16)
    compare.add_argument("--seed", type=int, default=0)
    compare.add_argument("--max-decisions", type=int, default=1600)
    compare.add_argument("--turn-budget", type=float)
    compare.add_argument("--time-limit", type=float, default=0.10)
    compare.add_argument("--simulations", type=int, default=128)
    compare.add_argument("--max-depth", type=int, default=96)

    boot = sub.add_parser("bootstrap", help="generate search/baseline JSONL episodes")
    boot.add_argument("--games", type=int, default=64)
    boot.add_argument("--seed", type=int, default=0)
    boot.add_argument("--out", type=Path, required=True)
    boot.add_argument("--max-decisions", type=int, default=1600)
    boot.add_argument("--time-limit", type=float, default=0.05)
    boot.add_argument("--simulations", type=int, default=64)

    train = sub.add_parser("train-neural", help="fit the fixed 128-wide policy/value guide")
    train.add_argument("--episodes", type=Path, required=True)
    train.add_argument("--out", type=Path, required=True)
    train.add_argument("--seed", type=int, default=0)
    train.add_argument("--epochs", type=int, default=1)
    train.add_argument("--learning-rate", type=float, default=0.01)

    cycle = sub.add_parser("cycle", help="train one tabular league learner")
    cycle.add_argument("--episodes", type=int, default=32)
    cycle.add_argument("--seed", type=int, default=0)
    cycle.add_argument("--max-decisions", type=int, default=1600)
    cycle.add_argument("--eval-pairs", type=int, default=0)
    cycle.add_argument("--model-out", type=Path, required=True)
    cycle.add_argument("--league-out", type=Path)
    cycle.add_argument("--time-limit", type=float, default=0.05)
    cycle.add_argument("--simulations", type=int, default=64)
    cycle.add_argument("--max-depth", type=int, default=96)

    gate = sub.add_parser("gate", help="run the Phase 4 promotion and holdout gates")
    gate.add_argument("--candidate", choices=("random", "heuristic", "search", "neural"), default="search")
    gate.add_argument("--incumbent", choices=("random", "heuristic", "search", "neural"), default="heuristic")
    gate.add_argument(
        "--opponent-family",
        action="append",
        metavar="NAME=POLICY",
        help="held-out family (repeatable; defaults to random, heuristic and search)",
    )
    gate.add_argument("--screening-pairs", type=int, default=128)
    gate.add_argument("--confirmation-pairs", type=int, default=512)
    gate.add_argument("--max-confirmation-pairs", type=int, default=2048)
    gate.add_argument("--seed", type=int, default=0)
    gate.add_argument("--max-decisions", type=int, default=1600)
    gate.add_argument("--turn-budget", type=float)
    gate.add_argument("--time-limit", type=float, default=0.10)
    gate.add_argument("--simulations", type=int, default=128)
    gate.add_argument("--max-depth", type=int, default=96)
    gate.add_argument("--model", type=Path, help="JSON neural model used by each neural policy")
    gate.add_argument("--candidate-model", type=Path, help="JSON model for a neural candidate")
    gate.add_argument("--incumbent-model", type=Path, help="JSON model for a neural incumbent")
    gate.add_argument("--opponent-model", type=Path, help="JSON model for neural opponent families")
    gate.add_argument("--bootstrap-samples", type=int, default=2000)
    gate.add_argument("--regression-limit", type=float, default=0.05)
    gate.add_argument("--information-trials", type=int, default=8)
    gate.add_argument("--correctness-pairs", type=int, default=8)
    gate.add_argument("--timing-trials", type=int, default=8)
    gate.add_argument("--timing-limit", type=float, default=5.0)
    gate.add_argument("--timing-calibrated", action="store_true")
    gate.add_argument("--timing-source", default="unverified")
    gate.add_argument("--serving-workers", type=int)
    gate.add_argument("--serving-profile", default="unverified")
    gate.add_argument("--timing-evidence", type=Path, help="JSON WASM timing manifest with candidate/incumbent p95 metrics")
    gate.add_argument("--allow-censored", action="store_true")
    gate.add_argument("--training-manifest", type=Path, help="JSON manifest with seeds/fingerprints/opponent_families")
    gate.add_argument("--training-episodes", type=Path, help="JSONL episodes from training; derives the holdout manifest")
    gate.add_argument("--out", type=Path, help="write the complete gate report as JSON")
    gate.add_argument("--fail-on-reject", action="store_true", help="return status 2 when the gate rejects/inconclusive")

    args = parser.parse_args(argv)
    if args.command == "arena":
        result = run_arena(
            _policy(args.candidate, args),
            _policy(args.opponent, args),
            pairs=args.pairs,
            seed=args.seed,
            max_decisions=args.max_decisions,
            turn_budget=args.turn_budget,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "compare":
        policies = {
            "random": RandomPolicy(),
            "heuristic": HeuristicPolicy(),
            "search": SearchPolicy(InformationSetSearch(SearchConfig(
                simulations=args.simulations,
                time_limit=args.time_limit,
                max_depth=args.max_depth,
            ))),
        }
        print(json.dumps(compare_algorithms(
            policies,
            pairs=args.pairs,
            seed=args.seed,
            max_decisions=args.max_decisions,
            turn_budget=args.turn_budget,
        ), indent=2, sort_keys=True))
        return 0
    if args.command == "bootstrap":
        episodes = generate_bootstrap(
            games=args.games,
            seed=args.seed,
            search_config=SearchConfig(simulations=args.simulations, time_limit=args.time_limit),
            max_decisions=args.max_decisions,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        count = write_episodes(args.out, episodes)
        print(json.dumps({"rules": rules_fingerprint(), "episodes": count, "out": str(args.out)}, sort_keys=True))
        return 0
    if args.command == "train-neural":
        episodes = read_episodes(args.episodes, require_rules=rules_fingerprint())
        policy = train_neural_candidate(
            episodes,
            seed=args.seed,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(policy.guide.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"rules": rules_fingerprint(), "episodes": len(episodes), "examples": policy.guide.examples, "out": str(args.out)}, sort_keys=True))
        return 0

    if args.command == "gate":
        family_specs = args.opponent_family or ["random=random", "heuristic=heuristic", "search=search"]
        families = {}
        for spec in family_specs:
            if "=" in spec:
                family_name, policy_name = spec.split("=", 1)
            else:
                family_name = spec
                policy_name = spec
            family_name = family_name.strip()
            policy_name = policy_name.strip()
            if not family_name or not policy_name:
                raise ValueError("--opponent-family must be NAME=POLICY")
            if family_name in families:
                raise ValueError(f"duplicate Orbit opponent family: {family_name}")
            families[family_name] = _policy(policy_name, args, model_path=args.opponent_model)

        manifest = {}
        if args.training_manifest:
            manifest = json.loads(args.training_manifest.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("Orbit training manifest must be a JSON object")
        if args.training_episodes:
            episodes = read_episodes(args.training_episodes, require_rules=rules_fingerprint())
            episode_seeds = {int(episode.seed) for episode in episodes}
            episode_fingerprints = {
                str(value)
                for episode in episodes
                for value in episode.metadata.get("policy_fingerprints", [])
            }
            episode_families = {
                str(value)
                for episode in episodes
                for value in episode.policy_names
            }
            manifest["seeds"] = sorted({
                *manifest.get("seeds", ()),
                *manifest.get("deal_seeds", ()),
                *manifest.get("training_seeds", ()),
                *episode_seeds,
            })
            manifest["policy_fingerprints"] = sorted({
                *manifest.get("policy_fingerprints", ()),
                *manifest.get("training_policy_fingerprints", ()),
                *episode_fingerprints,
            })
            manifest["opponent_families"] = sorted({
                *manifest.get("opponent_families", ()),
                *manifest.get("training_opponent_families", ()),
                *episode_families,
            })
        timing_evidence = None
        if args.timing_evidence:
            timing_evidence = json.loads(args.timing_evidence.read_text(encoding="utf-8"))
            if not isinstance(timing_evidence, dict):
                raise ValueError("Orbit timing evidence must be a JSON object")
        training_seeds = manifest.get("seeds", manifest.get("deal_seeds", manifest.get("training_seeds", ())))
        training_fingerprints = manifest.get(
            "policy_fingerprints",
            manifest.get("training_policy_fingerprints", ()),
        )
        training_families = manifest.get(
            "opponent_families",
            manifest.get("training_opponent_families", ()),
        )
        training_runs = manifest.get(
            "run_ids",
            manifest.get("training_run_ids", ()),
        )
        config = GateConfig(
            screening_pairs=args.screening_pairs,
            confirmation_pairs=args.confirmation_pairs,
            max_confirmation_pairs=args.max_confirmation_pairs,
            max_decisions=args.max_decisions,
            turn_budget=args.turn_budget,
            bootstrap_samples=args.bootstrap_samples,
            regression_limit=args.regression_limit,
            information_trials=args.information_trials,
            correctness_pairs=args.correctness_pairs,
            timing_trials=args.timing_trials,
            timing_limit=args.timing_limit,
            timing_calibrated=args.timing_calibrated,
            timing_source=args.timing_source,
            serving_workers=args.serving_workers,
            serving_profile=args.serving_profile,
            require_no_censoring=not args.allow_censored,
        )
        result = run_promotion_gate(
            _policy(args.candidate, args, model_path=args.candidate_model),
            _policy(args.incumbent, args, model_path=args.incumbent_model),
            families,
            config=config,
            seed=args.seed,
            training_seeds=training_seeds,
            training_policy_fingerprints=training_fingerprints,
            training_family_names=training_families,
            training_run_ids=training_runs,
            timing_evidence=timing_evidence,
        )
        payload = result.as_dict()
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.fail_on_reject and result.status != "promote":
            return 2
        return 0

    # A cycle starts from a search champion and keeps that champion in the
    # league.  Promotion remains an explicit Phase 4 decision.
    champion = SearchPolicy(InformationSetSearch(SearchConfig(
        simulations=args.simulations,
        time_limit=args.time_limit,
        max_depth=args.max_depth,
    )), name="champion")
    random_policy = RandomPolicy()
    heuristic = HeuristicPolicy()
    league = League()
    policies = {"champion": champion, "random": random_policy, "heuristic": heuristic}
    league.add_member("champion", champion, category="champion")
    league.add_member("random", random_policy, category="specialist")
    league.add_member("heuristic", heuristic, category="specialist")
    _, report = run_population_cycle(
        league,
        policies,
        parent_id="champion",
        data_policy=champion,
        episodes=args.episodes,
        seed=args.seed,
        max_decisions=args.max_decisions,
        eval_pairs=args.eval_pairs,
    )
    candidate_id = report.candidate_id
    candidate = policies[candidate_id]
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    args.model_out.write_text(json.dumps(candidate.model.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    if args.league_out:
        args.league_out.parent.mkdir(parents=True, exist_ok=True)
        args.league_out.write_text(json.dumps(league.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"rules": rules_fingerprint(), "report": report.as_dict(), "model": str(args.model_out)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
