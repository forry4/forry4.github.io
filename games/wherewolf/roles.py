"""Role/deck data for Where Wolf? — the single source of truth for the deck
composition, token letters, teams, the night order, and the narration script.

Pure data + deterministic helpers; no web/engine deps, so the engine, the server,
and the tests all import from here.
"""
from __future__ import annotations

import random
from collections import Counter

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
    "doppelganger": 1,   # data only — excluded from the picker; no night logic yet
}

# Token letter on the public token row: the uppercased first letter, except mason
# which is "MA" (so it doesn't collide with minion's "M").
TOKEN_LETTERS = {
    role: ("MA" if role == "mason" else role[0].upper()) for role in DECK_COUNTS
}

# Final-card team membership. Tanner is its own "team" (wins only by dying).
TEAMS = {
    "villager": "village", "seer": "village", "robber": "village",
    "troublemaker": "village", "drunk": "village", "insomniac": "village",
    "mason": "village", "hunter": "village",
    "werewolf": "werewolf", "minion": "werewolf",
    "tanner": "tanner",
    "doppelganger": "village",
}


def team_of(role: str | None) -> str:
    return TEAMS.get(role, "village")


# ── Night structure (Doppelganger omitted this pass) ──────────────────────────
# Wake order. A step is narrated/opened only when its role is in the SELECTED deck
# (a role entirely in the center is still announced so silence can't leak info).
NIGHT_ORDER = ("werewolves", "minion", "masons", "seer", "robber",
               "troublemaker", "drunk", "insomniac")

# step -> the dealt_role that wakes in it.
STEP_ROLE = {
    "werewolves": "werewolf", "minion": "minion", "masons": "mason",
    "seer": "seer", "robber": "robber", "troublemaker": "troublemaker",
    "drunk": "drunk", "insomniac": "insomniac",
}

# Action steps take a real move (the actor acts within a fixed window). Info steps
# just look. (The werewolves step is info — multiple wolves see each other — but a
# LONE wolf may optionally peek a center card; that is handled in-engine.)
ACTION_STEPS = ("seer", "robber", "troublemaker", "drunk")
INFO_STEPS = ("werewolves", "minion", "masons", "insomniac")

# Roles that take a night MOVE in their own step (drives the view's `is_active`).
ACTIVE_ROLES = ("seer", "robber", "troublemaker", "drunk")

MIN_PLAYERS = 3
MAX_PLAYERS = 10

# Narration script — standalone per-step wake lines (each self-contained, since any
# role may be absent). The card flip is the visual "close your eyes".
NARRATION = {
    "intro": "Everyone, close your eyes.",
    "werewolves": "Werewolves, wake up and look for other werewolves.",
    "lone_wolf": "If you are the only werewolf, you may look at a card in the center.",
    "minion": "Minion, wake up and see who the werewolves are.",
    "masons": "Masons, wake up and look for other Masons.",
    "seer": "Seer, wake up. You may look at another player's card, or two of the center cards.",
    "robber": ("Robber, wake up. You may exchange your card with another player's card, "
               "and then view your new card."),
    "troublemaker": "Troublemaker, wake up. You may exchange cards between two other players.",
    "drunk": "Drunk, wake up and exchange your card with a card from the center.",
    "insomniac": "Insomniac, wake up and look at your card.",
    "wakeup": "Everyone, wake up!",
}

# The fixed base set for 3 players; villagers are added at 4 and 5.
_BASE_3 = ["werewolf", "werewolf", "seer", "robber", "troublemaker", "villager"]
# Always-present core + the order extra single-copy roles are added as the table grows.
_REC_BASE = ["werewolf", "werewolf", "seer", "robber", "troublemaker"]
_REC_PROGRESSION = ["villager", "villager", "villager",
                    "tanner", "hunter", "insomniac", "minion", "drunk"]


def _counts(cards: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cards:
        out[c] = out.get(c, 0) + 1
    return out


def build_deck(n_players: int, rng: random.Random) -> list[str]:
    """Return the SHUFFLED default deck of exactly ``n_players + 3`` cards (the
    pre-picker default; kept for back-compat + when no deck is chosen)."""
    if not (MIN_PLAYERS <= n_players <= MAX_PLAYERS):
        raise ValueError(f"player count must be {MIN_PLAYERS}-{MAX_PLAYERS}, got {n_players}")
    cards = list(_BASE_3)
    if n_players >= 4:
        cards.append("villager")
    if n_players >= 5:
        cards.append("villager")
    used = _counts(cards)
    remaining: list[str] = []
    for role, total in DECK_COUNTS.items():
        if role == "doppelganger":
            continue
        for _ in range(total - used.get(role, 0)):
            remaining.append(role)
    rng.shuffle(remaining)
    cards.extend(remaining[:max(0, n_players - 5)])
    rng.shuffle(cards)
    assert len(cards) == n_players + 3, (n_players, len(cards))
    return cards


def recommended_deck(n_players: int) -> list[str]:
    """A sensible default deck of exactly ``n_players + 3`` cards (UNSHUFFLED — the
    host can edit it before dealing). Always 2 werewolves + seer + robber +
    troublemaker, villagers to 5 players, then single-copy flavor roles. Masons are
    NOT in the default (they only make sense as a pair — the host adds them manually);
    every default stays within the copy caps."""
    if not (MIN_PLAYERS <= n_players <= MAX_PLAYERS):
        raise ValueError(f"player count must be {MIN_PLAYERS}-{MAX_PLAYERS}, got {n_players}")
    deck = list(_REC_BASE) + _REC_PROGRESSION[: n_players - 2]
    assert len(deck) == n_players + 3, (n_players, len(deck))
    return deck


def validate_deck(deck, n_players: int, partial: bool = False) -> tuple[bool, str | None]:
    """Validate a host-chosen deck: exact count (players+3), copy limits, known
    roles, no doppelganger. No-werewolf decks and a single mason are allowed.

    ``partial=True`` skips ONLY the exact-count requirement — used while the host is
    still editing the deck so the in-progress selection can be broadcast to the other
    players (the exact count is re-checked, fully, when the game is dealt)."""
    if not isinstance(deck, list) or not all(isinstance(r, str) for r in deck):
        return False, "bad deck"
    if not (MIN_PLAYERS <= n_players <= MAX_PLAYERS):
        return False, f"player count must be {MIN_PLAYERS}-{MAX_PLAYERS}"
    need = n_players + 3
    if not partial and len(deck) != need:
        return False, f"deck must have exactly {need} cards (players + 3), has {len(deck)}"
    for role, cnt in Counter(deck).items():
        if role == "doppelganger":
            return False, "the Doppelganger is not available yet"
        if role not in DECK_COUNTS:
            return False, f"unknown role {role!r}"
        if cnt > DECK_COUNTS[role]:
            return False, f"too many {role} (max {DECK_COUNTS[role]})"
    return True, None
