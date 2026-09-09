"""Measure semantic feature coverage and legacy action collisions in real play.

Run: python -m games.orbit.tools.audit_features --games 8 --seed 9100
This random-play audit is correctness/shape evidence, never a strength arena.
It writes JSON to stdout and does not generate training episodes or ship assets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import itertools
import json
import random

from .. import engine
from ..ai.features import ENCODER_VERSION, encode_features
from ..ai.neural import encode_action
from ..ai.state import action_key, observation, rules_fingerprint
from ..cards import FACTIONS


def audit(*, games: int = 8, seed: int = 9100, max_decisions: int = 1600) -> dict:
    if games < 8 or games % 8:
        raise ValueError("Use a positive multiple of eight games for board coverage")
    if max_decisions < 1:
        raise ValueError("max_decisions must be positive")
    boards = [dict(zip(FACTIONS, sides)) for sides in itertools.product((1, 2), repeat=3)]
    counts = Counter()
    pending = Counter()
    actions = Counter()
    max_tokens = 0
    collisions = set()
    completed = 0
    decisions = 0
    for index in range(games):
        rng = random.Random(seed + index)
        game = engine.new_game(["A", "B"], seed=seed + index, configuration=boards[index % 8])
        for _ in range(max_decisions):
            for pid in game["order"]:
                obs = observation(game, pid)
                tokens = encode_features(obs)
                max_tokens = max(max_tokens, len(tokens))
                counts.update({token.group for token in tokens})
            if game["phase"] == "over":
                break
            pid = next((p for p in game["order"] if engine.legal_moves(game, p)), None)
            if pid is None:
                raise RuntimeError("Nonterminal position has no acting player")
            obs = observation(game, pid)
            moves = obs["legal_moves"]
            buckets = defaultdict(set)
            for move in moves:
                buckets[tuple(encode_action(obs, move))].add(action_key(move))
            for bucket in buckets.values():
                if len(bucket) > 1:
                    collisions.add(tuple(sorted(bucket)))
            if obs["pending"] and "task" in obs["pending"]:
                pending[obs["pending"]["task"]["type"]] += 1
            move = rng.choice(moves)
            actions[move["action"]] += 1
            ok, error = engine.apply_move(game, pid, move)
            if not ok:
                raise RuntimeError(error)
            decisions += 1
        completed += game["phase"] == "over"
    return {
        "encoder": ENCODER_VERSION, "rules": rules_fingerprint(), "seed": seed,
        "games": games, "completed": completed, "censored": games - completed,
        "decisions": decisions, "board_games": [games // 8] * 8,
        "max_observation_tokens": max_tokens, "group_observations": dict(counts),
        "pending_types": dict(pending), "actions": dict(actions),
        "legacy_action_collision_sets": len(collisions),
        "collision_examples": [list(bucket) for bucket in sorted(collisions)[:10]],
        "limitations": "Random coverage only; no history sizing, exhaustive effect coverage or strength claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=8)
    parser.add_argument("--seed", type=int, default=9100)
    parser.add_argument("--max-decisions", type=int, default=1600)
    args = parser.parse_args()
    print(json.dumps(audit(games=args.games, seed=args.seed, max_decisions=args.max_decisions), indent=2))


if __name__ == "__main__":
    main()
