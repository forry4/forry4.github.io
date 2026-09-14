"""Extract strategic signals from parity-verified BGA Orbit trajectories.

This is a diagnostic, not a promotion gate.  The input is the JSONL written by
``bga_policy_probe extract``.  It keeps the comparison paired within a table,
reports the opening and action-sequence signals that are cheap to test, and
does not turn winner correlations into claims about causality.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path
from typing import Iterable

from games.orbit.ai.serving import _score
from games.orbit.ai.state import action_key
from games.orbit.cards import CARDS

MAIN_ACTIONS = frozenset(("recruit", "technology", "leader"))


def _main_steps(episode: dict, seat: int) -> list[dict]:
    """Return that seat's main actions, excluding effect sub-decisions."""

    return [
        step for step in episode.get("steps", [])
        if step.get("actor_seat") == seat
        and step.get("observation", {}).get("phase") == "play"
        and step.get("observation", {}).get("pending") is None
        and step.get("action", {}).get("action") in MAIN_ACTIONS
    ]


def _mulligan(episode: dict, seat: int) -> dict | None:
    for step in episode.get("steps", []):
        if (step.get("actor_seat") == seat
                and step.get("action", {}).get("action") == "mulligan"):
            return step
    return None


def _tech_available(step: dict) -> bool:
    return any(move.get("action") == "technology"
               for move in step.get("legal_moves", []))


def _technology_choice_rate(steps: Iterable[dict]) -> tuple[int, int, float]:
    available = [step for step in steps if _tech_available(step)]
    chosen = sum(step.get("action", {}).get("action") == "technology"
                 for step in available)
    return chosen, len(available), chosen / len(available) if available else 0.0


def _ranker_metrics(steps: Iterable[dict]) -> dict[str, float | int]:
    """Score only base-card main actions; expansion cards are replay-only."""

    ranks: list[int] = []
    for step in steps:
        card_id = step.get("action", {}).get("card_id")
        action_moves = [
            move for move in step.get("legal_moves", [])
            if move.get("action") in MAIN_ACTIONS and move.get("card_id") is not None
        ]
        # The serving ranker intentionally ships only the 90-card base game.
        # A Secret Agents card anywhere in the hand makes this row an invalid
        # comparison, even when the demonstrated move itself is a base card.
        if (card_id not in CARDS
                or any(move.get("card_id") not in CARDS for move in action_moves)):
            continue
        scored = sorted(
            (
                float(_score(step["observation"], move)),
                action_key(move),
                move,
            )
            for move in step.get("legal_moves", [])
        )
        # ``sorted`` above is ascending; the serving ranker is descending with
        # the action key as its deterministic tie break.
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen = action_key(step["action"])
        rank = next((index + 1 for index, item in enumerate(scored)
                     if item[1] == chosen), None)
        if rank is not None:
            ranks.append(rank)
    return {
        "rows": len(ranks),
        "top1": sum(rank == 1 for rank in ranks) / len(ranks) if ranks else 0.0,
        "top3": sum(rank <= 3 for rank in ranks) / len(ranks) if ranks else 0.0,
    }


def _role_summary(episodes: list[dict], winner: bool) -> dict:
    rows: list[dict] = []
    mulligans: list[int] = []
    for episode in episodes:
        winner_seat = episode.get("winner_seat")
        if winner_seat not in (0, 1):
            continue
        seat = winner_seat if winner else 1 - winner_seat
        steps = _main_steps(episode, seat)
        rows.extend(steps)
        mulligan = _mulligan(episode, seat)
        if mulligan is not None:
            mulligans.append(len(mulligan.get("action", {}).get("card_ids", [])))

    action_counts = collections.Counter(
        step.get("action", {}).get("action") for step in rows
    )
    first_four_counts = collections.Counter()
    early_tech_any = 0
    early_tech_chosen, early_tech_available = 0, 0
    first_six_tech_any = 0
    for episode in episodes:
        winner_seat = episode.get("winner_seat")
        if winner_seat not in (0, 1):
            continue
        seat = winner_seat if winner else 1 - winner_seat
        steps = _main_steps(episode, seat)
        first_four = steps[:4]
        first_six = steps[:6]
        first_four_counts.update(
            step.get("action", {}).get("action") for step in first_four
        )
        if any(step.get("action", {}).get("action") == "technology"
               for step in first_four):
            early_tech_any += 1
        chosen, available, _rate = _technology_choice_rate(first_four)
        early_tech_chosen += chosen
        early_tech_available += available
        if any(step.get("action", {}).get("action") == "technology"
               for step in first_six):
            first_six_tech_any += 1

    _chosen, _available, early_rate = _technology_choice_rate(
        [step for episode in episodes
         if episode.get("winner_seat") in (0, 1)
         for step in _main_steps(
             episode,
             episode["winner_seat"] if winner else 1 - episode["winner_seat"],
         )[:4]]
    )
    after_technology = collections.Counter()
    for episode in episodes:
        winner_seat = episode.get("winner_seat")
        if winner_seat not in (0, 1):
            continue
        steps = _main_steps(episode, winner_seat if winner else 1 - winner_seat)
        for current, following in zip(steps, steps[1:]):
            if current.get("action", {}).get("action") == "technology":
                after_technology[following.get("action", {}).get("action")] += 1
    after_total = sum(after_technology.values())
    return {
        "tables": sum(
            episode.get("winner_seat") in (0, 1) for episode in episodes
        ),
        "main_rows": len(rows),
        "action_counts": dict(action_counts),
        "action_rates": {
            action: action_counts[action] / len(rows) if rows else 0.0
            for action in sorted(MAIN_ACTIONS)
        },
        "mulligan": {
            "mean_discarded": statistics.mean(mulligans) if mulligans else 0.0,
            "distribution": dict(collections.Counter(mulligans)),
        },
        "first_four": {
            "action_counts": dict(first_four_counts),
            "tables_with_technology": early_tech_any,
            "technology_available": early_tech_available,
            "technology_chosen": early_tech_chosen,
            "technology_choice_rate": early_rate,
        },
        "first_six": {"tables_with_technology": first_six_tech_any},
        "after_technology": {
            "counts": dict(after_technology),
            "recruit_rate": after_technology["recruit"] / after_total
            if after_total else 0.0,
        },
        "ranker_on_base_cards": _ranker_metrics(rows),
    }


def audit(episodes: list[dict]) -> dict:
    """Return paired strategic summaries for a list of extracted episodes."""

    paired = []
    for episode in episodes:
        winner = episode.get("winner_seat")
        if winner not in (0, 1):
            continue
        winner_steps = _main_steps(episode, winner)
        loser_steps = _main_steps(episode, 1 - winner)
        winner_m = _mulligan(episode, winner)
        loser_m = _mulligan(episode, 1 - winner)
        paired.append({
            "table_id": episode.get("metadata", {}).get("table_id"),
            "winner_main_rows": len(winner_steps),
            "loser_main_rows": len(loser_steps),
            "winner_discarded": len(winner_m.get("action", {}).get("card_ids", []))
            if winner_m else None,
            "loser_discarded": len(loser_m.get("action", {}).get("card_ids", []))
            if loser_m else None,
            "winner_early_technology": any(
                step.get("action", {}).get("action") == "technology"
                for step in winner_steps[:4]
            ),
            "loser_early_technology": any(
                step.get("action", {}).get("action") == "technology"
                for step in loser_steps[:4]
            ),
        })
    return {
        "episodes": len(episodes),
        "decisions": sum(len(episode.get("steps", [])) for episode in episodes),
        "main_decisions": sum(
            len(_main_steps(episode, seat))
            for episode in episodes
            if episode.get("winner_seat") in (0, 1)
            for seat in (0, 1)
        ),
        "winner": _role_summary(episodes, True),
        "loser": _role_summary(episodes, False),
        "paired": paired,
    }


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit(_load(args.episodes))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
