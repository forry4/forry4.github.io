"""Deck composition per player count + token letters."""
import random
from collections import Counter

import pytest

from games.wherewolf import roles


def deck(n, seed=0):
    return roles.build_deck(n, random.Random(seed))


def test_three_player_base():
    assert Counter(deck(3)) == Counter(
        ["werewolf", "werewolf", "seer", "robber", "troublemaker", "villager"])


def test_total_is_players_plus_three():
    for n in range(3, 11):
        assert len(deck(n, seed=n)) == n + 3


def test_four_adds_a_second_villager():
    c = Counter(deck(4, seed=4))
    assert c["villager"] == 2
    assert c["werewolf"] == 2 and c["seer"] == 1 and c["robber"] == 1 and c["troublemaker"] == 1


def test_five_uses_all_three_villagers():
    assert Counter(deck(5, seed=5))["villager"] == 3


def test_six_plus_extras_are_dormant_only():
    # The base set + 3 villagers consume every active role and all villagers, so the
    # random extras at 6+ can only ever be dormant roles (never a duplicate active role).
    for n in range(6, 11):
        c = Counter(deck(n, seed=n * 7))
        assert c["werewolf"] == 2
        assert c["seer"] == 1 and c["robber"] == 1 and c["troublemaker"] == 1
        assert c["villager"] == 3


def test_copy_limits_never_exceeded():
    for n in range(3, 11):
        c = Counter(deck(n, seed=n))
        for role, total in roles.DECK_COUNTS.items():
            assert c[role] <= total, (role, n)


def test_player_count_guards():
    with pytest.raises(ValueError):
        deck(2)
    with pytest.raises(ValueError):
        deck(11)


def test_token_letters():
    assert roles.TOKEN_LETTERS["mason"] == "MA"
    assert roles.TOKEN_LETTERS["werewolf"] == "W"
    assert roles.TOKEN_LETTERS["seer"] == "S"
    # Mason ("MA") must not collide with minion ("M").
    assert roles.TOKEN_LETTERS["mason"] != roles.TOKEN_LETTERS["minion"]


def test_determinism():
    assert deck(7, seed=123) == deck(7, seed=123)
