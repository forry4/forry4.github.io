"""The MIRROR the BGA co-walk converges against.

The co-walk decides which move a human made by trying every legal move and
keeping the one whose result BGA's own reported state can reach. That makes the
mirror the load-bearing piece: anything it cannot see is a distinction the walk
cannot make, so it guesses and then diverges several turns later, far from the
cause. Every field it tracks is here because its absence cost exactly that.

Two of these pin calibrations that were measured the WRONG way round first, and
both were expensive:

  * the control space is +/-4, not +/-3 -- guessing 3 halved the walk's reach;
  * a candidate that explains more of the log wins -- without it, declining an
    optional (which consumes no events) beat accepting it every time.

No corpus is involved and none is needed: the corpus is a gitignored local
directory, and the repo bans the conditional skip that would otherwise turn a
fresh clone into a green tick over a check that never ran. The corpus-dependent
reach number lives in the tool, behind `bga_replay --cowalk`.
"""

from __future__ import annotations

from games.orbit import engine
from games.orbit.tools import bga_cowalk as cowalk


class _FakeTable:
    """Just the card_id -> card_num map the mirror reads."""

    def __init__(self, card_num=None):
        self.table_id = "fake"
        self.card_num = dict(card_num or {})


def _mirror(card_num=None):
    return cowalk.Mirror(_FakeTable(card_num))


def test_the_mirror_starts_where_the_engine_starts():
    """Same opening position, or nothing downstream can be compared at all."""

    mirror = _mirror()
    game = engine.new_game(["1", "2"], seed=3, secret_agents=True)
    game["order"] = ["1", "2"]
    assert mirror.influence == game["influence"]
    assert mirror.credits == {"1": engine.STARTING_CREDITS, "2": engine.STARTING_CREDITS}
    assert mirror.zenithium == {"1": engine.STARTING_ZENITHIUM,
                                "2": engine.STARTING_ZENITHIUM}


def test_influence_signs_are_inverted():
    """BGA counts toward seat 1 as negative; Orbit counts toward order[0] as positive."""

    mirror = _mirror()
    mirror.consume("movePlanet", {"planet": 1, "position": -1})
    assert mirror.influence["mercury"] == 1
    mirror.consume("movePlanet", {"planet": 5, "position": 2})
    assert mirror.influence["jupiter"] == -2


def test_the_control_space_is_four_and_a_disc_that_reaches_it_is_captured():
    """`engine.CONTROL_POSITION` is 4, and the corpus agrees: positions run -4..+4
    and every capture is at +/-4.

    Orbit stores None the instant a disc arrives there, so a raw position would
    disagree on exactly the captures. Guessed as 3 first, which cut the walk's
    reach from 436 decisions to 214.
    """

    assert engine.CONTROL_POSITION == 4
    mirror = _mirror()
    mirror.consume("movePlanet", {"planet": 4, "position": 3})
    assert mirror.influence["mars"] == -3, "three is an ordinary space"
    mirror.consume("movePlanet", {"planet": 4, "position": 4})
    assert mirror.influence["mars"] is None, "four is the control space"

    mirror.consume("movePlanet", {"planet": 2, "position": -4})
    assert mirror.influence["venus"] is None
    mirror.consume("resetPlanet", {"planet": 2})
    assert mirror.influence["venus"] == 0


def test_resources_follow_bga_s_two_different_sign_conventions():
    """`deltaCredits` carries the signed change in `nb`; `deltaSolium` in `delta`.

    Reading either from the wrong field drifts the mirror permanently, after which
    NOTHING converges -- so this is pinned rather than trusted.
    """

    mirror = _mirror()
    mirror.consume("deltaCredits", {"player_no": "1", "cost": -3, "nb": 3})
    assert mirror.credits["1"] == engine.STARTING_CREDITS + 3
    mirror.consume("deltaCredits", {"player_no": "1", "cost": 7, "nb": -7})
    assert mirror.credits["1"] == engine.STARTING_CREDITS - 4

    mirror.consume("deltaSolium", {"player_no": "2", "nb": 3, "delta": 3})
    assert mirror.zenithium["2"] == engine.STARTING_ZENITHIUM + 3
    mirror.consume("deltaSolium", {"player_no": "2", "nb": 1, "delta": -1})
    assert mirror.zenithium["2"] == engine.STARTING_ZENITHIUM + 2


def test_taking_and_giving_move_both_seats():
    mirror = _mirror()
    mirror.consume("stealCredits", {"player_no": "1", "nb": "3"})
    assert mirror.credits["1"] == engine.STARTING_CREDITS + 3
    assert mirror.credits["2"] == engine.STARTING_CREDITS - 3

    mirror.consume("giveSolium", {"player_no": "1", "nb": 1})
    assert mirror.zenithium["1"] == engine.STARTING_ZENITHIUM - 1
    assert mirror.zenithium["2"] == engine.STARTING_ZENITHIUM + 1


def test_columns_are_tracked_so_that_exile_choices_are_visible():
    """Which card is exiled moves nothing else, so without columns every candidate
    converges and the walk picks one arbitrarily."""

    mirror = _mirror({"7": 216, "8": 106})
    mirror.consume("moveCard", {"card_id": 7, "player_no": 1, "location": "play"})
    assert mirror.columns[216] == ("1", "venus"), "a card lands in its own column"

    mirror.consume("mobilize", {"card_id": 8, "player_no": 2, "planet": "3"})
    assert mirror.columns[106] == ("2", "terra"), "a mobilize names the planet itself"

    mirror.consume("transfer", {"card_id": 7, "player_no": 2})
    assert mirror.columns[216] == ("2", "venus"), "a transfer moves it to the taker"

    mirror.consume("discardCard", {"card_id": 7, "planet_name": "Venus"})
    assert 216 not in mirror.columns


def test_a_discard_from_HAND_is_not_a_column_removal():
    """`discardCard` covers both; only the one naming a planet came off the board."""

    mirror = _mirror({"7": 216})
    mirror.consume("moveCard", {"card_id": 7, "player_no": 1, "location": "play"})
    mirror.consume("discardCard", {"card_id": 7})
    assert 216 in mirror.columns


def test_convergence_stops_at_the_first_agreement():
    """Events past the match belong to decisions the engine has not reached yet."""

    game = engine.new_game(["1", "2"], seed=3, secret_agents=True)
    game["order"] = ["1", "2"]
    events = [(1, "movePlanet", {"planet": 1, "position": -1}),
              (1, "movePlanet", {"planet": 2, "position": -1})]
    mirror = _mirror()
    got = cowalk.converge(mirror, events, 0, game)
    assert got and got[1] == 0, "already in agreement, so nothing is consumed"

    game["influence"]["mercury"] = 1
    got = cowalk.converge(_mirror(), events, 0, game)
    assert got and got[1] == 1, "one event explains it; the second is not consumed"


def test_convergence_reports_failure_rather_than_drifting():
    game = engine.new_game(["1", "2"], seed=3, secret_agents=True)
    game["order"] = ["1", "2"]
    game["influence"]["mercury"] = 3          # nothing in the log gets there
    events = [(1, "movePlanet", {"planet": 2, "position": -1})]
    assert cowalk.converge(_mirror(), events, 0, game) is None


def test_the_floor_forces_a_main_action_past_its_own_event():
    """A main action that changes nothing the mirror sees must still advance the
    cursor past its own `moveCard`, or the next step re-reads it forever."""

    game = engine.new_game(["1", "2"], seed=3, secret_agents=True)
    game["order"] = ["1", "2"]
    events = [(1, "moveCard", {"card_id": 1, "player_no": 1, "location": "play"}),
              (1, "setHandSize", {"player_no": 1, "nb": "4"})]
    got = cowalk.converge(_mirror(), events, 0, game, floor=0)
    assert got and got[1] == 0
    got = cowalk.converge(_mirror(), events, 0, game, floor=1)
    assert got and got[1] >= 1, "the floor drags the cursor past the action itself"


def test_all_eight_board_configurations_are_searched():
    """The sides are never announced, so a wrong one has to be found by diverging."""

    assert len(cowalk.ALL_SIDES) == 8
    assert {"robot": 1, "human": 1, "animod": 1} in cowalk.ALL_SIDES
    assert {"robot": 2, "human": 2, "animod": 2} in cowalk.ALL_SIDES
    assert len({tuple(sorted(s.items())) for s in cowalk.ALL_SIDES}) == 8


def test_the_scripted_bonus_pays_what_the_log_says_it_paid():
    """The eight face-up tokens are never announced at setup, so a seeded game hands
    out the wrong bonus and the wrong effect follows."""

    from games.orbit import effects

    scripted = cowalk.ScriptedBonus([4])          # 4 is the Leader badge token
    assert scripted(3) == effects.bonus_effects(4), "the log's token wins, not ours"
    assert scripted(3) == effects.bonus_effects(3), "exhausted: fall back, never invent"
    assert scripted.overrun == 1
