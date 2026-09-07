"""Command-line entry points for Orbit Phase 2/3 experiments.

Examples (run from the repository root)::

    python -m games.orbit.tools.ai_campaign arena --candidate search --opponent heuristic --pairs 32
    python -m games.orbit.tools.ai_campaign bootstrap --games 128 --out build/orbit/bootstrap.jsonl
    python -m games.orbit.tools.ai_campaign cycle --episodes 64 --model-out build/orbit/model.json

The tool is offline-only.  It writes explicit rules fingerprints and settings
with every artifact; it does not alter the server bot or browser bundle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..ai.league import League, generate_bootstrap, run_population_cycle, train_neural_candidate
from ..ai.neural import NeuralGuide, NeuralPolicy
from ..ai.search import HeuristicPolicy, InformationSetSearch, RandomPolicy, SearchConfig, SearchPolicy
from ..ai.selfplay import compare_algorithms, read_episodes, run_arena, write_episodes
from ..ai.state import rules_fingerprint


def _policy(name: str, args):
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
        if not getattr(args, "model", None):
            raise ValueError("--model is required for the neural policy")
        guide = NeuralGuide.from_dict(json.loads(Path(args.model).read_text(encoding="utf-8")))
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
