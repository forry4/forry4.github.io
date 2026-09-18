"""At-rest compaction is a boundary, not a rewrite — and it must be reversible.

The size guard here is on RAW bytes, deliberately. A stored ratio's denominator
is the compressor, not the codec: the repo has measured the same blobs at 0.660
and 0.755 across zlib levels, Python 3.14 ships zlib-ng, and four games' ratio
guards were red on dev boxes while green in CI for exactly that reason. The
structural round-trip below is what no compressor can move.
"""
from __future__ import annotations

import json
import random

from core import rooms as _rooms
from games.secretnames import engine as E
from games.secretnames import persist


def _state(seed: int = 3) -> dict:
    game = E.new_game(["pa", "pb"], {"pa": "Ann", "pb": "Bo"}, rng=random.Random(seed))
    for _ in range(6):
        if E.is_over(game):
            break
        seat = game["clue_giver"]
        E.apply_move(game, game["seats"][seat], {"type": "clue", "word": "SIGNAL", "number": 2})
        free = [i for i in range(25) if i not in set(game["found"])]
        E.apply_move(game, game["seats"][E.guesser(game)], {"type": "guess", "pos": free[0]})
        if game["phase"] == "guess":
            E.apply_move(game, game["seats"][E.guesser(game)], {"type": "end_turn"})
    return {"players": {"pa": "Ann", "pb": "Bo"}, "host": "pa", "status": "playing",
            "game": game, "meta": {"pa": {"token": "t"}}, "turns": 9}


def test_compaction_round_trips_the_whole_state():
    state = _state()
    back = persist.expand_state(persist.compact_state(json.loads(json.dumps(state))))
    assert back == state


def test_the_packed_keys_are_still_two_twenty_five_role_lists():
    """The compaction that matters is the key vocabulary, so check it did in
    fact happen rather than only that the round trip is clean — a no-op
    compact/expand pair passes the test above perfectly."""
    packed = persist.compact_state(_state())
    assert isinstance(packed["game"]["keys"][0], str)
    assert len(packed["game"]["keys"][0]) == 25
    assert set(packed["game"]["keys"][0]) <= set("abx")
    back = persist.expand_state(packed)
    for side in back["game"]["keys"]:
        assert len(side) == 25
        assert set(side) <= {E.AGENT, E.BYSTANDER, E.ASSASSIN}


def test_compaction_actually_shrinks_the_raw_blob():
    state = _state()
    plain = len(json.dumps(state, separators=(",", ":")))
    small = len(json.dumps(persist.compact_state(state), separators=(",", ":")))
    assert small < plain, (plain, small)


def test_a_pre_compaction_row_loads_untouched():
    """Blobs carry a `_c` marker, so existing rows need no migration."""
    state = _state()
    assert persist.expand_state(json.loads(json.dumps(state))) == state


def test_expanding_twice_is_a_no_op_and_so_is_compacting_twice():
    state = _state()
    once = persist.compact_state(state)
    assert persist.compact_state(once) == once
    back = persist.expand_state(once)
    assert persist.expand_state(back) == back == state


def test_the_room_codec_survives_the_full_encode_decode_path():
    state = _state()
    blob = _rooms.encode_state(persist.compact_state(state))
    assert persist.expand_state(_rooms.decode_state(blob)) == state


def test_a_saved_state_carries_no_rng_state_at_all():
    """SecretNames spends every draw in the deal, so there is nothing to persist
    — and 625 words of incompressible Mersenne noise per save would have been
    the single largest item in the row. See the engine's header."""
    blob = json.dumps(persist.compact_state(_state()))
    assert "rng_state" not in blob


def test_a_junk_shaped_key_is_left_verbatim_rather_than_corrupted():
    state = _state()
    state["game"]["keys"] = [["agent"] * 25, ["mystery"] * 25]
    packed = persist.compact_state(state)
    assert packed["game"]["keys"][1] == ["mystery"] * 25
    assert persist.expand_state(packed)["game"]["keys"][1] == ["mystery"] * 25
