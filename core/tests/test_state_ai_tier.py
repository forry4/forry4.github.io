"""`state_ai_tier` reads a saved room's bot tier — and must not invent one.

The lobby's Active and History rows print the bot they were played against off
this one function, so the interesting failure is not "it returned the wrong
string": it is returning a string AT ALL for a human game. Every game's
`save_game` writes `room.get("ai_difficulty", DEFAULT_DIFFICULTY)`, which has a
default, so the tier is on the blob whether or not a bot ever sat down. A
version that read the tier alone labelled every human-vs-human row "Normal AI"
— which reads as a real fact and is unfalsifiable from the row.

It lives in core/tests because the function does, and it builds the blobs by
hand rather than importing a game: `core/` may not depend on a feature, and that
holds for its tests. The shapes below are the shapes in the tree — see the
roster check in `shared/tests/test_lobby_bot_tier.py`, which is what fails when
a game's `save_game` changes to a spelling this does not accept.
"""

from core import rooms as _rooms


def test_a_human_table_has_no_tier_even_though_the_blob_carries_one():
    # The exact shape `save_game` writes for a vs-friend room: an unset seat and
    # a difficulty that defaulted anyway.
    state = {"players": {"a": "Ada", "b": "Bo"}, "ai_player": None,
             "ai_difficulty": "normal", "game": {"turn": "a"}}
    assert _rooms.state_ai_tier(state) is None


def test_a_seated_bot_reports_its_tier():
    state = {"ai_player": "ai", "ai_difficulty": "expert", "game": {"turn": "ai"}}
    assert _rooms.state_ai_tier(state) == "expert"


def test_dontminions_multi_bot_list_counts_as_a_seat():
    """One tier, several seats — an empty list is a human table."""
    assert _rooms.state_ai_tier(
        {"ai_players": ["bot1", "bot2"], "ai_difficulty": "bmplus"}) == "bmplus"
    assert _rooms.state_ai_tier({"ai_players": [], "ai_difficulty": "bmplus"}) is None


def test_spenders_seat_lives_inside_the_game_and_its_tier_is_a_variant_code():
    """Spender is the one game whose bot seat is a key of `game` rather than a
    sibling of it, and whose tier is a variant letter under a different name.
    Both halves have to be read or Spender's rows are the only silent ones."""
    state = {"ai_variant": "N", "game": {"ai_player": "ai", "turn": "ai"}}
    assert _rooms.state_ai_tier(state) == "N"
    # A Spender game against a human: the variant is absent, not defaulted.
    assert _rooms.state_ai_tier({"game": {"turn": "a"}}) is None


def test_a_seated_bot_with_no_recorded_tier_reports_nothing_rather_than_a_guess():
    """Rag Tag has one bot and no ladder, so its blob has a seat and no tier.
    The row then prints no chip, which is correct — there is no difficulty to
    report — and it must not fall back to a plausible-looking default."""
    assert _rooms.state_ai_tier({"ai_player": "bot", "game": {}}) is None


def test_a_corrupt_or_missing_blob_is_not_a_bot_game():
    """These callers decode a row inside a try/except and pass on whatever they
    get, including `{}` for an unreadable blob."""
    for blob in ({}, None, "", [], {"game": "not-a-dict", "ai_player": "ai"}):
        assert _rooms.state_ai_tier(blob) is None
