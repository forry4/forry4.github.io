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


# ── recommended_deck / validate_deck (host role picker) ───────────────────────
def test_recommended_deck_shape_and_valid():
    for n in range(3, 11):
        d = roles.recommended_deck(n)
        assert len(d) == n + 3
        ok, err = roles.validate_deck(d, n)
        assert ok, (n, err)


def test_validate_deck_rejects_wrong_count():
    assert not roles.validate_deck(["villager"] * 6, 4)[0]   # need 7, has 6
    assert not roles.validate_deck(["villager"] * 8, 4)[0]   # need 7, has 8


def test_validate_deck_partial_skips_count_but_keeps_caps():
    # partial=True (host still editing) accepts any count so the in-progress deck
    # can be broadcast, but still enforces copy caps / known roles / player range.
    assert roles.validate_deck(["seer", "robber", "troublemaker"], 4, partial=True)[0]  # 3 cards, need 7 — OK
    assert roles.validate_deck([], 4, partial=True)[0]                 # empty OK
    assert not roles.validate_deck(["werewolf"] * 3, 4, partial=True)[0]  # cap still enforced
    assert not roles.validate_deck(["villager"], 2, partial=True)[0]      # player range still enforced


def test_validate_deck_copy_limits():
    assert not roles.validate_deck(["werewolf"] * 3 + ["villager"] * 3, 3)[0]  # 3 werewolves
    assert not roles.validate_deck(["villager"] * 4 + ["werewolf", "seer"], 3)[0]  # 4 villagers
    assert not roles.validate_deck(["mason"] * 3 + ["villager"] * 3, 3)[0]     # 3 masons


def test_validate_deck_rejects_doppelganger_and_unknown():
    assert not roles.validate_deck(["doppelganger"] + ["villager"] * 5, 3)[0]
    assert not roles.validate_deck(["wizard"] + ["villager"] * 5, 3)[0]


def test_validate_deck_allows_no_werewolf_and_single_mason():
    ok, _ = roles.validate_deck(["seer", "robber", "troublemaker", "villager", "villager", "mason"], 3)
    assert ok          # no werewolf + a lone mason are both allowed
