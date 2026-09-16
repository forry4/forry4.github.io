from games.black_castle import engine, persist


def test_legacy_unmarked_state_is_left_untouched():
    state = {"game": engine.new_game(["a", "b"], seed=11)}
    assert persist.expand_state(state) is state

