"""Role/deck data for Where Wolf? — the single source of truth for the deck
composition, token letters, the night-action roles, and the narration script.

Pure data + a deterministic deck builder; no web/engine deps, so the engine, the
server, and the tests all import from here.
"""
from __future__ import annotations

import random

# Full deck: role -> number of copies (One Night Ultimate Werewolf-style).
DECK_COUNTS = {
    "villager": 3,
    "werewolf": 2,
    "seer": 1,
    "robber": 1,
    "troublemaker": 1,
    "tanner": 1,
    "drunk": 1,
    "hunter": 1,
    "mason": 2,
    "insomniac": 1,
    "minion": 1,
    "doppelganger": 1,
}

# Token letter on the public token row: the uppercased first letter, except
# mason which is "MA" (so it doesn't collide with minion's "M").
TOKEN_LETTERS = {
    role: ("MA" if role == "mason" else role[0].upper()) for role in DECK_COUNTS
}

# Roles that perform a night action in v1 (everything else is dealt-but-dormant).
ACTIVE_ROLES = ("werewolf", "seer", "robber", "troublemaker")

# The order the night conductor narrates / awakens roles.
NIGHT_ORDER = ("werewolves", "seer", "robber", "troublemaker")

MIN_PLAYERS = 3
MAX_PLAYERS = 10

# Narration script — keyed beats so server, client, and tests share one source.
NARRATION = {
    "intro": "Everyone, close your eyes.",
    "werewolves": "Werewolves, wake up and look for other werewolves.",
    "seer": ("Werewolves, close your eyes. Seer, wake up. "
             "You may look at another player's card, or two of the center cards."),
    "robber": ("Seer, close your eyes. Robber, wake up. "
               "You may exchange your card with another player's card, and then view your new card."),
    "troublemaker": ("Robber, close your eyes. Troublemaker, wake up. "
                     "You may exchange cards between two other players."),
    "close_troublemaker": "Troublemaker, close your eyes.",
    "wakeup": "Everyone, wake up!",
}

# The fixed base set for 3 players; villagers are added at 4 and 5.
_BASE_3 = ["werewolf", "werewolf", "seer", "robber", "troublemaker", "villager"]


def _counts(cards: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cards:
        out[c] = out.get(c, 0) + 1
    return out


def build_deck(n_players: int, rng: random.Random) -> list[str]:
    """Return the exact, SHUFFLED list of ``n_players + 3`` cards in play.

    - 3 players: 2 werewolves, seer, robber, troublemaker, 1 villager (6 cards).
    - 4 players: + a 2nd villager.
    - 5 players: + a 3rd villager.
    - 6..10:     + one RANDOM card per extra player, drawn WITHOUT replacement
                 from the remaining deck. By construction the remaining deck only
                 holds the dormant roles (tanner/drunk/hunter/mason/insomniac/
                 minion/doppelganger) — the active roles and all 3 villagers are
                 already consumed — so a 6+ game can never duplicate an active role.

    The caller deals the first ``n_players`` cards and puts the last 3 in the center.
    """
    if not (MIN_PLAYERS <= n_players <= MAX_PLAYERS):
        raise ValueError(f"player count must be {MIN_PLAYERS}..{MAX_PLAYERS}, got {n_players}")

    cards = list(_BASE_3)
    if n_players >= 4:
        cards.append("villager")
    if n_players >= 5:
        cards.append("villager")

    # Whatever copies of the full deck are left after the base/villagers above.
    used = _counts(cards)
    remaining: list[str] = []
    for role, total in DECK_COUNTS.items():
        for _ in range(total - used.get(role, 0)):
            remaining.append(role)
    rng.shuffle(remaining)

    extra = max(0, n_players - 5)  # one random card per player beyond 5
    cards.extend(remaining[:extra])

    rng.shuffle(cards)
    assert len(cards) == n_players + 3, (n_players, len(cards))
    return cards
