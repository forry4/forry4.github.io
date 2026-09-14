"""Measure an offline policy head on parity-verified Zenith demonstrations.

The archived BGA tables are useful now that the co-walk reproduces every
watched event, but they are still demonstrations, not a promotion gate.  This
tool keeps the experiment cheap and honest:

* extraction accepts only a complete mirror walk with the logged winner;
* the split is by whole table, never by shuffled decision rows;
* the acting seat receives only :func:`observation` and the legal action list;
* the current serving ranker and a small ``NeuralGuide`` policy head are scored
  on the same held-out decisions;
* no server or browser asset is changed.

The output is an ``Episode`` JSONL file so the same rules/schema fingerprint
and trajectory readers used by generated self-play apply here.  The resulting
model is diagnostic until it clears the normal fresh-deal arena and promotion
gates; fitting expert demonstrations alone is not a strength claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from games.orbit import engine
from games.orbit.ai.neural import ENCODER_VERSION, NeuralGuide, NeuralPolicy
from games.orbit.ai.selfplay import Episode, EpisodeStep, read_episodes, run_arena, write_episodes
from games.orbit.ai.serving import _score, choose_move
from games.orbit.ai.state import SCHEMA_VERSION, action_key, observation as policy_observation, rules_fingerprint
from games.orbit.tools import bga_replay as replay
from games.orbit.tools import bga_table as table_io
from games.orbit.tools.bga_cowalk import best_run


def _stable_seed(table_id: str) -> int:
    return int.from_bytes(hashlib.sha256(str(table_id).encode("utf-8")).digest()[:8], "big")


def _is_complete(table_id: str, result: dict, *, corpus: str = table_io.CORPUS) -> bool:
    walk = result.get("walk")
    if result.get("status") != "done" or walk is None:
        return False
    table = table_io.load(table_id, corpus)
    return (
        walk.pos == len(walk.events)
        and str(engine.winner(walk.game)) == str(table.winner_seat)
    )


def episode_from_walk(table_id: str, result: dict, *, corpus: str = table_io.CORPUS) -> Episode:
    """Convert one complete ``best_run`` result into policy-safe steps."""

    walk = result.get("walk")
    if walk is None or not _is_complete(table_id, result, corpus=corpus):
        raise ValueError(f"{table_id}: refusing an incomplete parity walk")
    winner = engine.winner(walk.game)
    winner_seat = walk.game["order"].index(winner) if winner is not None else None
    steps: list[EpisodeStep] = []
    for record in walk.trajectory:
        legal = list(record["legal_moves"])
        action = dict(record["action"])
        chosen = action_key(action)
        legal_keys = {action_key(move) for move in legal}
        if chosen not in legal_keys:
            raise ValueError(f"{table_id}: trajectory action is not legal")
        steps.append(EpisodeStep(
            actor_seat=int(record["actor_seat"]),
            observation=record["observation"],
            history=None,
            legal_moves=legal,
            action=action,
            target={action_key(move): float(action_key(move) == chosen) for move in legal},
        ))
    return Episode(
        seed=_stable_seed(table_id),
        configuration={key: int(value) for key, value in result["sides"].items()},
        policy_names=("bga-expert", "bga-expert"),
        steps=steps,
        winner_seat=winner_seat,
        censored=False,
        decisions=len(steps),
        metadata={
            "source": "bga-rich-parity",
            "table_id": str(table_id),
            "board_sides": dict(result["sides"]),
            "parity_event_count": len(walk.events),
            "parity_decisions": int(walk.decisions),
            "undo_count": int(table_io.load(table_id, corpus).undos),
        },
    )


def extract(
    *,
    corpus: str = table_io.CORPUS,
    table_ids: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[Episode]:
    """Run the parity co-walk and keep only complete expert trajectories."""

    ids = list(table_ids or replay.rich_tables(corpus))
    if limit is not None:
        ids = ids[: max(0, int(limit))]
    episodes: list[Episode] = []
    failures: list[dict[str, str]] = []
    for table_id in ids:
        result = best_run(table_id, corpus=corpus)
        if result.get("status") == "done":
            episode = episode_from_walk(table_id, result, corpus=corpus)
            episodes.append(episode)
            print(f"{table_id}: {len(episode.steps)} parity steps", flush=True)
        else:
            failures.append({"table_id": str(table_id), "status": str(result.get("status"))})
            print(f"{table_id}: {result.get('status')}", flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} BGA tables failed parity: {failures[:3]}")
    return episodes


def table_split(episodes: Sequence[Episode], holdout: int) -> tuple[list[Episode], list[Episode]]:
    """Return a deterministic whole-table train/holdout split."""

    ordered = sorted(
        episodes,
        key=lambda episode: hashlib.sha256(
            str(episode.metadata.get("table_id", episode.seed)).encode("utf-8")
        ).digest(),
    )
    count = max(0, min(int(holdout), len(ordered)))
    holdout_episodes = ordered[:count]
    train_episodes = ordered[count:]
    if not train_episodes:
        raise ValueError("whole-table holdout leaves no training games")
    return train_episodes, holdout_episodes


def _rows(episodes: Iterable[Episode]):
    for episode in episodes:
        for step in episode.steps:
            yield step


def _metrics(rows: Iterable[EpisodeStep], picker) -> dict[str, float | int]:
    total = top1 = top3 = 0
    reciprocal = cross_entropy = 0.0
    for step in rows:
        legal = list(step.legal_moves)
        target = action_key(step.action)
        ranking, probabilities = picker(step.observation, legal)
        keys = [action_key(move) for move in ranking]
        if target not in keys:
            raise ValueError("policy returned an action outside the legal set")
        rank = keys.index(target) + 1
        total += 1
        top1 += rank == 1
        top3 += rank <= 3
        reciprocal += 1.0 / rank
        cross_entropy -= math.log(max(1e-12, float(probabilities.get(target, 0.0))))
    return {
        "rows": total,
        "top1": top1 / total if total else 0.0,
        "top3": top3 / total if total else 0.0,
        "mean_reciprocal_rank": reciprocal / total if total else 0.0,
        "cross_entropy": cross_entropy / total if total else 0.0,
    }


def evaluate(
    episodes: Sequence[Episode],
    *,
    holdout: int = 8,
    seed: int = 0,
    epochs: int = 1,
    learning_rate: float = 0.01,
) -> dict:
    """Fit a policy-only demonstration guide and score it against Hard v2."""

    train, test = table_split(episodes, holdout)
    guide = NeuralGuide.random(seed)
    guide.fit(train, epochs=epochs, learning_rate=learning_rate)

    def incumbent(obs, legal):
        result = choose_move(obs, legal, None, 5_000, 0)
        scores = [float(_score(obs, move)) for move in legal]
        pivot = max(scores) if scores else 0.0
        # A soft distribution makes cross-entropy comparable to the learned
        # guide while the explicit first slot preserves the serving ranker's
        # deterministic tie break for top-k accuracy.
        temperature = 0.25
        weights = [math.exp(max(-60.0, min(60.0, (score - pivot) / temperature))) for score in scores]
        total = sum(weights) or 1.0
        probabilities = {action_key(move): weight / total for move, weight in zip(legal, weights)}
        chosen_key = action_key(result.move) if result.move else None
        ranking = ([result.move] if result.move else []) + sorted(
            [move for move in legal if action_key(move) != chosen_key],
            key=lambda move: (-probabilities[action_key(move)], action_key(move)),
        )
        return ranking, probabilities

    def candidate(obs, legal):
        probabilities = guide.priors(obs, legal)
        ranking = sorted(legal, key=lambda move: (-probabilities.get(action_key(move), 0.0), action_key(move)))
        return ranking, probabilities

    train_ids = sorted(str(e.metadata.get("table_id")) for e in train)
    test_ids = sorted(str(e.metadata.get("table_id")) for e in test)
    return {
        "rules": rules_fingerprint(),
        "schema": SCHEMA_VERSION,
        "encoder": ENCODER_VERSION,
        "train_tables": train_ids,
        "holdout_tables": test_ids,
        "train_games": len(train),
        "holdout_games": len(test),
        "train_metrics": {
            "incumbent": _metrics(_rows(train), incumbent),
            "demonstration_policy": _metrics(_rows(train), candidate),
        },
        "holdout_metrics": {
            "incumbent": _metrics(_rows(test), incumbent),
            "demonstration_policy": _metrics(_rows(test), candidate),
        },
        "model": {
            "hidden": guide.hidden,
            "examples": guide.examples,
            "epochs": guide.epochs,
            "seed": int(seed),
            "learning_rate": float(learning_rate),
        },
    }


class ServingPolicy:
    """Offline adapter for the current Hard v2 serving ranker."""

    name = "hard-v2-serving"

    def choose(self, game, pid, rng, *, observation=None, history=None,
               time_budget=None, belief=None):
        obs = observation or policy_observation(game, pid)
        legal = sorted(engine.legal_moves(game, pid), key=action_key)
        return choose_move(obs, legal, None, 5_000, rng.getrandbits(32)).move


def arena_probe(
    episodes: Sequence[Episode],
    *,
    holdout: int = 8,
    seed: int = 0,
    epochs: int = 2,
    learning_rate: float = 0.01,
    pairs: int = 8,
    max_decisions: int = 600,
) -> dict:
    """Run a cheap fresh-deal CRN screen after the holdout measurement."""

    train, _test = table_split(episodes, holdout)
    guide = NeuralGuide.random(seed)
    guide.fit(train, epochs=epochs, learning_rate=learning_rate)
    candidate = NeuralPolicy(guide, epsilon=0.0, name="bga-demo-policy")
    result = run_arena(
        candidate,
        ServingPolicy(),
        pairs=pairs,
        seed=seed + 1717,
        max_decisions=max_decisions,
    )
    return {
        "rules": rules_fingerprint(),
        "schema": SCHEMA_VERSION,
        "encoder": ENCODER_VERSION,
        "training_tables": sorted(str(e.metadata.get("table_id")) for e in train),
        "settings": {
            "holdout": int(holdout),
            "seed": int(seed),
            "epochs": int(epochs),
            "learning_rate": float(learning_rate),
            "pairs": int(pairs),
            "max_decisions": int(max_decisions),
        },
        "arena": result.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    extract_parser = sub.add_parser("extract", help="co-walk complete BGA tables into JSONL")
    extract_parser.add_argument("--corpus", default=table_io.CORPUS)
    extract_parser.add_argument("--out", type=Path, required=True)
    extract_parser.add_argument("--limit", type=int)
    extract_parser.add_argument("--table", action="append", dest="table_ids")

    evaluate_parser = sub.add_parser("evaluate", help="whole-table holdout policy probe")
    evaluate_parser.add_argument("--episodes", type=Path, required=True)
    evaluate_parser.add_argument("--out", type=Path, required=True)
    evaluate_parser.add_argument("--holdout", type=int, default=8)
    evaluate_parser.add_argument("--seed", type=int, default=0)
    evaluate_parser.add_argument("--epochs", type=int, default=1)
    evaluate_parser.add_argument("--learning-rate", type=float, default=0.01)

    arena_parser = sub.add_parser("arena", help="cheap fresh-deal screen versus Hard v2")
    arena_parser.add_argument("--episodes", type=Path, required=True)
    arena_parser.add_argument("--out", type=Path, required=True)
    arena_parser.add_argument("--holdout", type=int, default=8)
    arena_parser.add_argument("--seed", type=int, default=0)
    arena_parser.add_argument("--epochs", type=int, default=2)
    arena_parser.add_argument("--learning-rate", type=float, default=0.01)
    arena_parser.add_argument("--pairs", type=int, default=8)
    arena_parser.add_argument("--max-decisions", type=int, default=600)

    args = parser.parse_args(argv)
    if args.command == "extract":
        episodes = extract(corpus=args.corpus, table_ids=args.table_ids, limit=args.limit)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        count = write_episodes(args.out, episodes)
        print(json.dumps({"rules": rules_fingerprint(), "episodes": count, "out": str(args.out)}, sort_keys=True))
        return 0

    episodes = read_episodes(args.episodes, require_rules=rules_fingerprint())
    if args.command == "arena":
        report = arena_probe(
            episodes,
            holdout=args.holdout,
            seed=args.seed,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            pairs=args.pairs,
            max_decisions=args.max_decisions,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    report = evaluate(
        episodes,
        holdout=args.holdout,
        seed=args.seed,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
