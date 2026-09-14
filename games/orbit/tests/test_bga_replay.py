"""The BGA replay DRIVER, held to games the engine itself produced.

`AGENTS.md` makes BGA replays Orbit's parity oracle. An oracle you have not calibrated
will blame the thing it is measuring: on Rag Tag, a per-turn comparison once accused every
card in the game of being wrong at 0.6-0.9, which was impossible next to 27 exact
reproductions, and the tool was wrong rather than the engine.

So this pins the half of the harness that has nothing to do with BGA. The intents here are
known-good by construction -- they came out of `legal_moves` -- so a failure is the
driver, never the rules and never the parse. When a real log eventually fails, that is
what makes "the parser or the rules" a sound conclusion instead of a guess.

No corpus is involved and none is needed, so this runs everywhere and always: the repo
bans a test that opts out of the state it means to exercise.
"""
import json
import random

from games.orbit import engine
from games.orbit.tools import bga_replay as replay
from games.orbit.tools import bga_table


def test_a_recorded_game_replays_to_an_identical_final_state():
    replay.selftest(12)


def test_it_replays_the_randomly_configured_boards_too():
    """The `sun` layout is one fixed configuration; `random` moves the board sides."""
    replay.selftest(12, configuration="random")


def test_the_driver_notices_when_a_replay_stops_short():
    """A replay that quietly consumed half its log would otherwise 'pass'."""
    played, intents = replay.record(3)
    fresh = engine.new_game(["A", "B"], seed=3, configuration="sun")
    used = replay.drive(fresh, intents[:-4])
    assert used == len(intents) - 4
    assert replay.fingerprint(fresh) != replay.fingerprint(played)


def test_an_intent_the_engine_never_offered_is_loud():
    """The whole point of matching against `legal_moves` rather than building a move."""
    game = engine.new_game(["A", "B"], seed=5, configuration="sun")
    try:
        replay.drive(game, [{"action": "recruit", "card_id": -1}])
    except LookupError as exc:
        assert "no legal move matches" in str(exc)
    else:
        raise AssertionError("a fabricated move was accepted")


def test_every_action_the_engine_can_offer_is_known_to_the_harness():
    """`as_intent` raises on an unknown action, so a new one cannot pass through silently.

    Derived from real play rather than a hand-written list -- a hardcoded roster only
    guards the vocabulary SHRINKING, which is the wrong direction.
    """
    seen = set()
    for seed in range(6):
        chooser = random.Random(seed)
        game = engine.new_game(["A", "B"], seed=seed, configuration="random")
        for _ in range(1500):
            if engine.is_over(game):
                break
            moves = engine.legal_moves(game, replay.whose_move(game))
            if not moves:
                break
            seen.update(m.get("action") for m in moves)
            engine.apply_move(game, replay.whose_move(game), chooser.choice(moves))
    assert seen, "no moves were generated at all"
    assert seen <= set(replay.ACTIONS), f"actions the harness does not know: {seen - set(replay.ACTIONS)}"


def test_the_bga_half_is_not_a_translate_once_parser():
    """`parse_actions` stays unwritten because that SHAPE is wrong, not just unfinished.

    A BGA log has no move list to translate ahead of time: a sub-decision is a private
    menu plus a consequence event, and which sub-decision is being answered depends on
    where the engine has got to. So the log is read BESIDE the engine. This keeps the
    placeholder from being quietly filled in with the wrong design.
    """
    try:
        replay.parse_actions([])
    except NotImplementedError as exc:
        assert "co-walk" in str(exc)
    else:
        raise AssertionError("parse_actions returned something -- update these tests")


# ── the forced setup ────────────────────────────────────────────────────────
#
# The corpus itself is a gitignored local directory, so nothing here touches it:
# a test that cannot reach its own state must fail, not opt out, and the repo bans
# the conditional skip that would otherwise paper over a fresh clone. The
# corpus-dependent checks live in the tool, behind `--verify`.

class _FakeTable:
    """The only two things `build_game` reads off a table."""

    def __init__(self, deck_ids):
        self.table_id = "fake"
        self.deck_ids = list(deck_ids)


def test_a_scripted_deck_deals_the_log_s_cards_in_the_log_s_order():
    script = [305, 106, 214, 116, 317, 111, 213, 419]
    game, deck = replay.build_game(_FakeTable(script), {"robot": 1, "human": 1, "animod": 1})
    first, second = game["order"]
    assert game["players"][first]["hand"] == script[:4]
    assert game["players"][second]["hand"] == script[4:]
    assert deck.taken == 8 and deck.overrun == 0
    engine.validate_state(game)


def test_a_scripted_deck_survives_a_card_coming_back_through_a_reshuffle():
    """BGA gives a recycled card a NEW card_id, so a log can name one twice.

    Measured on 4 of the 40 archived tables. A pre-arranged deck cannot express it;
    taking the card from wherever the engine keeps it can.
    """
    script = [305, 106, 214, 116, 317, 111, 213, 419]
    game, deck = replay.build_game(_FakeTable(script), {"robot": 1, "human": 1, "animod": 1})
    game["agent_discard"].append(305)
    game["players"][game["order"][0]]["hand"].remove(305)
    engine._draw_agent = deck
    try:
        deck.script.append(305)
        assert deck(game) == 305
    finally:
        engine._draw_agent = replay._real_draw_agent
    assert 305 not in game["agent_discard"]
    game["players"][game["order"][0]]["hand"].append(305)   # a draw puts it somewhere
    engine.validate_state(game)


def test_a_scripted_deck_is_loud_when_the_draw_order_is_wrong():
    """A card already in play cannot be drawn; silently dealing a copy would break
    conservation far from the cause."""
    script = [305, 106, 214, 116, 317, 111, 213, 419]
    game, deck = replay.build_game(_FakeTable(script), {"robot": 1, "human": 1, "animod": 1})
    deck.script.append(305)          # already in a hand
    try:
        deck(game)
    except AssertionError as exc:
        assert "neither the deck nor the discard" in str(exc)
    else:
        raise AssertionError("a card already in play was dealt a second time")


def test_a_scripted_deck_falls_back_rather_than_fabricating_a_tail():
    """Most games end mid-deck, so the script runs out long before the cards do."""
    script = [305, 106, 214, 116, 317, 111, 213, 419]
    game, deck = replay.build_game(_FakeTable(script), {"robot": 1, "human": 1, "animod": 1})
    assert not deck.script
    engine._draw_agent = deck
    try:
        drawn = deck(game)
    finally:
        engine._draw_agent = replay._real_draw_agent
    assert drawn is not None and deck.overrun == 1
    game["players"][game["order"][0]]["hand"].append(drawn)
    engine.validate_state(game)


def test_a_forced_setup_is_an_expansion_game():
    """Every archived table runs Secret Agents, so the replay must deal 100 cards."""
    game, _ = replay.build_game(_FakeTable([305, 106, 214, 116, 317, 111, 213, 419]),
                                {"robot": 1, "human": 1, "animod": 1})
    assert game["expansion"] is True
    assert len(engine.deck_composition(game)) == 100


def test_bga_influence_signs_are_inverted():
    """BGA counts toward seat 1 as negative; Orbit counts toward order[0] as positive.

    Verified against real logs: seat 1's first Mercury gain reads position -1, and Terra
    -- which the second player starts one step toward -- begins at BGA +1 where Orbit
    stores -1.
    """
    assert bga_table.influence(-1) == 1
    assert bga_table.influence(3) == -3
    assert bga_table.influence(0) == 0
    assert bga_table.influence(None) is None


def test_a_move_is_identified_by_all_of_itself():
    """`choose` is polymorphic; keying it on one field matched the wrong pending decision.

    Caught by the selftest on its first run, and cheap to pin: two different `choose`
    payloads must not compare equal just because they share an action.
    """
    a = {"action": "choose", "planet": "mars"}
    b = {"action": "choose", "tier": 2}
    assert replay.as_intent(a) != replay.as_intent(b)
    assert replay.as_intent(a) == json.loads(json.dumps(a))
