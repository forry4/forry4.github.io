"""Pin every port's printed numbers to its PUBLISHED rules, game by game.

WHY THIS FILE EXISTS
--------------------
Black Castle accumulated four rules errors that shared one root: a question the box
already answers was asked of a corpus of game logs instead. A deleted 2-player rule, a
starting-resource card deleted because 20 logs never dealt it, two component counts
inferred from sightings, and a whole mechanic skipped. Every one of them would have been
caught by reading the rulebook.

So on 2026-09-21 the other nine games were audited the same way -- their setup counts,
supply sizes and scoring tables checked against the published rules rather than against
their own tests. Eight came back clean, and that has a cause rather than being luck:
they were built FROM rulebooks, while Black Castle shipped as an explicit placeholder
port whose own manifest said `"bga_parity": "planned after launch"`.

**The ninth did not, and it was the one this file had written off.** Orbit was recorded
here as an original design with no rulebook to check against. It is a port of Zenith.
Auditing it properly found a real divergence -- a planet could be captured a fifth time
though the box holds only four of its discs, and in every random game where that came up
it was the WINNING capture. So the audit's own summary reproduced the bug it was written
to prevent: "I could not find a source" became "there is no source".

This file is what remains of that audit. Each number below was verified against the source
named in its test, so the audit does not have to be repeated -- and so a later "tidy-up"
that changes one of them fails here instead of silently changing the game.

WHAT THIS FILE IS NOT
---------------------
It is not a rules test. Each game's own suite covers its behaviour; this covers the
COUNTS and TABLES, which is the class of thing that was wrong in Black Castle and the
class a reader can check against a published source in seconds. It deliberately does not
try to cover 368 Dominion cards or every Castles of Burgundy tile.
"""
from __future__ import annotations


def test_spender_matches_splendor():
    # Source: Splendor rulebook (Space Cowboys).
    from games.spender import cards, engine
    assert (len(cards.LEVEL1), len(cards.LEVEL2), len(cards.LEVEL3)) == (40, 30, 20)
    assert len(cards.ALL_NOBLES) == 10          # 10 in the box, players + 1 dealt
    assert cards._BANK_PER_COLOR == {2: 4, 3: 5, 4: 7}
    assert engine.TOKEN_CAP == 10               # hand limit
    assert engine.RESERVE_CAP == 3
    assert engine.win_points({}) == 15          # 15 prestige triggers the final round


def test_spender_duel_matches_splendor_duel():
    # Source: Splendor Duel rulebook + Dized component list.
    import collections

    from games.spender_duel import cards, engine
    bag = collections.Counter(cards.TOKEN_BAG)
    assert len(cards.TOKEN_BAG) == 25           # the 5x5 board is filled exactly
    assert all(bag[c] == 4 for c in cards.COLORS)
    assert (bag["pearl"], bag["gold"]) == (2, 3)
    assert cards.DECK_SIZES == {1: 30, 2: 24, 3: 13}
    assert cards.PYRAMID_SIZES == {1: 5, 2: 4, 3: 3}
    assert len(cards.ROYALS) == 4
    assert engine.CROWN_THRESHOLDS == (3, 6)    # royals are claimed at 3 and 6 crowns
    assert (engine.WIN_POINTS, engine.WIN_CROWNS, engine.WIN_COLOR_POINTS) == (20, 10, 10)
    assert (engine.MAX_TOKENS, engine.MAX_RESERVED) == (10, 3)


def test_wherewolf_matches_one_night_ultimate_werewolf():
    # Source: One Night Ultimate Werewolf rulebook (Bezier Games).
    from games.wherewolf import roles
    assert roles.DECK_COUNTS == {
        "villager": 3, "werewolf": 2, "seer": 1, "robber": 1, "troublemaker": 1,
        "tanner": 1, "drunk": 1, "hunter": 1, "mason": 2, "insomniac": 1,
        "minion": 1, "doppelganger": 1,
    }
    assert sum(roles.DECK_COUNTS.values()) == 16
    # The printed night order. Doppelganger leads it in the box and is data-only here,
    # which is why it is absent rather than misplaced.
    assert roles.NIGHT_ORDER == ("werewolves", "minion", "masons", "seer", "robber",
                                 "troublemaker", "drunk", "insomniac")


def test_secretnames_matches_codenames_duet():
    # Source: Codenames Duet rulebook (CGE).
    from games.secretnames import engine
    assert engine.TOTAL_AGENTS == 15            # NOT 9 + 9; the sides overlap
    assert engine.DEFAULT_TURNS == 9            # 9 timer tokens
    comp = dict(engine.KEY_COMPOSITION)
    assert sum(comp.values()) == 25
    # The published pair distribution. Generating the two sides independently and hoping
    # the union lands on 15 agents is the obvious wrong implementation.
    assert comp[(engine.AGENT, engine.AGENT)] == 3
    assert comp[(engine.ASSASSIN, engine.ASSASSIN)] == 1
    for side in (0, 1):
        agents = sum(n for pair, n in engine.KEY_COMPOSITION if pair[side] == engine.AGENT)
        assassins = sum(n for pair, n in engine.KEY_COMPOSITION
                        if pair[side] == engine.ASSASSIN)
        assert (agents, assassins) == (9, 3), side
    unique = sum(n for pair, n in engine.KEY_COMPOSITION if engine.AGENT in pair)
    assert unique == engine.TOTAL_AGENTS


def test_castles_of_crimson_matches_castles_of_burgundy():
    # Source: Castles of Burgundy rulebook (alea).
    from games.castles_of_crimson import tiles
    assert tiles.AREA_SCORE == [1, 3, 6, 10, 15, 21, 28, 36]   # region bonus by size
    assert tiles.PHASE_BONUS == {"A": 10, "B": 8, "C": 6, "D": 4, "E": 2}
    assert len(tiles.PHASES) == 5
    assert len(tiles.BUILDING_TYPES) == 8
    assert len(tiles.LIVESTOCK_KINDS) == 12     # 4 animals x values 2/3/4


def test_dontminion_matches_dominion():
    # Source: Dominion 2E rulebook. The supply is the half a reader can check at a
    # glance, and it scales three different ways at once.
    from games.dontminion import engine
    for seats, copper, victory, curses in ((2, 46, 8, 10), (3, 39, 12, 20), (4, 32, 12, 30)):
        game = engine.new_game([f"p{i}" for i in range(seats)], ["base"], seed=5)
        supply = game["supply"]
        assert supply["Copper"] == copper, seats      # 60 in the box, minus 7 per player
        assert supply["Silver"] == 40
        assert supply["Gold"] == 30
        for card in ("Estate", "Duchy", "Province"):
            assert supply[card] == victory, (seats, card)
        assert supply["Curse"] == curses, seats       # 10 per opponent
        kingdom = [k for k in supply if k not in (
            "Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse",
            "Platinum", "Colony", "Potion")]
        assert len(kingdom) == 10


def test_pinch_matches_yinsh():
    # Source: YINSH rulebook (Don & Co / Rio Grande).
    from games.pinch import engine
    assert len(engine.NODES) == 85              # radius-5 hex, six corners removed
    assert engine.RING_COUNT == 5               # rings per player
    assert engine.MARKER_COUNT == 51
    assert engine.WIN_ROWS == {"standard": 3, "blitz": 1}
    assert len(engine.DIRECTIONS) == 6
    assert len(engine.ROW_DIRECTIONS) == 3      # a row is checked on 3 axes, not 6


def test_black_castle_matches_the_publishers_component_list():
    # Source: devir.world/thewhitecastle/components_ENG.html. The game this whole file
    # exists because of -- its own suite pins the rest.
    import json
    import os

    from games import black_castle
    path = os.path.join(os.path.dirname(black_castle.__file__),
                        "data", "base_game_manifest.json")
    components = json.load(open(path, encoding="utf-8"))["components"]
    assert components["steward_cards"] == 15
    assert components["diplomat_cards"] == 12
    assert components["daimyo_cards"] == 9
    assert components["starting_resource_cards"] == 9
    assert components["starting_action_cards"] == 6      # 6 cards over 3 designs
    assert components["die_tiles"] == 15


def test_orbit_matches_zenith():
    """Source: Zenith rulebook + BGA's Gamehelpzenith.

    **This entry began as a mistake worth leaving recorded.** The first version of this
    file asserted Orbit was an ORIGINAL design with no rulebook to check it against. It is
    a Zenith port, and auditing it properly then found a real rules divergence -- see
    `DISCS_PER_PLANET`. "I could not find a source" was filed as "there is no source",
    which is the same error this whole file exists to catch, committed inside the file
    that catches it.
    """
    from games.orbit import cards, engine
    assert engine.STARTING_CREDITS == 12
    assert engine.STARTING_ZENITHIUM == 1
    assert engine.BASE_HAND_LIMIT == 4          # 5 with the silver badge, 6 with gold
    assert engine.CONTROL_POSITION == 4         # a 9-space track, centred on the planet
    assert engine.DISCS_PER_PLANET == 4         # 20 discs, four in each planet's colour
    assert len(cards.CARDS) == 90               # Agent cards
    assert len(cards.BONUS_POOL) == 16
    assert len(cards.PLANETS) == 5
    assert len(cards.FACTIONS) == 3             # Humans, Robots, Animods
    assert len(cards.TECHNOLOGIES) == 30


def test_the_games_with_no_rulebook_are_named_rather_than_forgotten():
    """Dissonance is an ORIGINAL design, not a port.

    There is no published rulebook to audit it against, so its reference is its own Rust
    core plus the parity gate. Naming it here is the point: a later reader counting the
    entries above should not conclude it was simply missed -- and should be suspicious of
    that claim, because it was made about Orbit too and was wrong.

    Rag Tag is a port and is absent for the opposite reason: it has something stronger
    than a rulebook check, a full replay gate against 40 real BGA games at 4103/4103.
    Orbit has one too, against 189 archived Zenith tables.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for game in ("dissonance", "rag_tag", "orbit"):
        assert os.path.isdir(os.path.join(root, "games", game)), game
