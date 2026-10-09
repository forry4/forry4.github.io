from games.orbit.ai.selfplay import Episode
from games.orbit.ai.neural import encode_action, encode_observation
from games.orbit.tools.bga_policy_probe import table_split
from games.orbit import engine
from games.orbit.ai.state import observation
from games.orbit.cards import EXPANSION_CARDS


def _episode(table_id: str, seed: int) -> Episode:
    return Episode(
        seed=seed,
        configuration={"robot": 1, "human": 1, "animod": 1},
        policy_names=("fixture", "fixture"),
        steps=[],
        winner_seat=None,
        censored=False,
        decisions=0,
        metadata={"table_id": table_id},
    )


def test_holdout_split_keeps_whole_tables_disjoint():
    episodes = [_episode(str(index), index) for index in range(6)]
    train, holdout = table_split(episodes, 2)
    assert {episode.metadata["table_id"] for episode in train}.isdisjoint(
        episode.metadata["table_id"] for episode in holdout
    )
    assert len(train) == 4 and len(holdout) == 2


def test_neural_encoder_accepts_a_parity_game_expansion_card():
    game = engine.new_game(["A", "B"], seed=5, secret_agents=True)
    pid = game["order"][0]
    # Put a known expansion card in a public column.  This keeps the test
    # independent of which random opening hand the fixture happens to deal.
    expansion = next(iter(EXPANSION_CARDS))
    game["players"][pid]["columns"]["mercury"].append(expansion)
    obs = observation(game, pid)
    assert len(encode_observation(obs)) == 288
    assert len(encode_action(obs, {"action": "recruit", "card_id": expansion})) == 40
