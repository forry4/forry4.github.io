"""The research tiers stay unreachable from a client.

`strategist`, `champion` and the retired `bigmoney` live in `bot.py` as the
arena's harness; the champion's own search tests are in
`research_tests/test_bot_champion.py`.
"""

import random

from games.dontminion import bot, engine, main as m


def test_the_unshipped_tiers_are_not_offered_and_coerce_to_the_default():
    """They lose to bmplus, so a room must never be able to select one. The
    coercion that lets the ladder grow without a migration is also what keeps
    a research tier out of production.

    `bigmoney` is in this list for a different reason from the rest: it is not
    a failed experiment but a RETIRED one, a strict subset of bmplus (same buy
    ladder, no terminal / Colony rungs / endgame) that bmplus beats 0.77. It
    stays reachable in code as the arena's reference rung, and unreachable
    from a client for the same reason as the others."""
    for tier in (bot.BIG_MONEY, "strategist", "champion", "strategist:engine"):
        assert tier not in m.AI_DIFFICULTIES
        assert m._valid_difficulty(tier) == m.DEFAULT_DIFFICULTY
    assert m.DEFAULT_DIFFICULTY == bot.BM_PLUS


def test_bigmoney_is_still_dispatchable_for_the_arena():
    """Unreachable from a client is NOT the same as deleted. Every bmplus gate
    and pace anchor is measured against plain money, so `bot.choose` must keep
    routing the string — and route it to the LADDER, not fall through to the
    random bot, which would turn the reference rung into noise and make every
    number measured against it meaningless."""
    g = engine.new_game(["a", "b"], ["base"], seed=7)
    pid = g["turn"]
    g["phase"] = "buy"
    g["seats"][pid]["hand"] = []      # nothing left to play — read the ladder
    g["coins"] = 9                    # past the $8 "really early" exception

    assert bot.choose(g, pid, random.Random(0), bot.BIG_MONEY) \
        == bot.choose_big_money(g, pid, random.Random(0)), \
        "the bigmoney string no longer routes to choose_big_money"
    assert bot.choose(g, pid, random.Random(0), bot.BIG_MONEY) \
        == {"type": "buy", "card": "Province"}, (
            "bigmoney no longer reaches the buy ladder — if it fell through "
            "to choose_random the arena's baseline is now a coin flip")
