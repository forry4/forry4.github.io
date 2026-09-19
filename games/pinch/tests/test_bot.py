from games.pinch import bot, engine


def test_easy_bot_returns_a_legal_move_for_every_phase():
    game = engine.new_game(["a", "b"], seed=1)
    for step in range(40):
        if engine.is_over(game):
            break
        pid = game.get("pending_pid") or game.get("turn_pid")
        move = bot.choose_move(game, pid, seed=step)
        assert move in engine.legal_moves(game, pid)
        assert engine.apply_move(game, pid, move)[0]
