from games.pinch import engine, persist


def test_persistence_round_trip_preserves_pending_state():
    game = engine.new_game(["a", "b"], seed=1)
    state = {"game": game, "players": {"a": "A", "b": "B"}}
    packed = persist.compact_state(state)
    assert packed is not state and packed["_c"] == 1
    assert persist.expand_state(packed) == state
