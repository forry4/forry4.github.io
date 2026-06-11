import pytest

from games.spender import main


def test_can_afford_exact_tokens():
    cost = {"blue": 2, "red": 1}
    tokens = {"blue": 2, "red": 1, "gold": 0}
    bonuses = {c: 0 for c in main.GEM_COLORS}
    assert main.can_afford(cost, tokens, bonuses)


def test_can_afford_with_gold():
    cost = {"blue": 3}
    tokens = {"blue": 1, "gold": 2}
    bonuses = {c: 0 for c in main.GEM_COLORS}
    assert main.can_afford(cost, tokens, bonuses)


def test_calc_spend_uses_gold_for_gap():
    cost = {"blue": 3}
    tokens = {"blue": 1, "gold": 2}
    bonuses = {c: 0 for c in main.GEM_COLORS}
    spend = main.calc_spend(cost, tokens, bonuses)
    assert spend["blue"] == 1
    assert spend["gold"] == 2
