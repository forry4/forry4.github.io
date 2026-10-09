from __future__ import annotations

import copy
import json
import random

from games.orbit import engine as E
from games.orbit.ai.belief import HistoryBelief
from games.orbit.ai.history import Session
from games.orbit.ai.league import League, TabularModel, TabularPolicy, train_candidate
from games.orbit.ai.neural import (
    ACTION_SIZE,
    ENCODER_VERSION,
    HIDDEN_SIZE,
    OBS_SIZE,
    NeuralGuide,
    NeuralPolicy,
    encode_action,
    encode_observation,
)
from games.orbit.ai.search import (
    HeuristicPolicy,
    InformationSetSearch,
    RandomPolicy,
    SearchConfig,
    SearchPolicy,
)
from games.orbit.ai.selfplay import board_configurations, compare_algorithms, mirror_sanity, play_game, read_episodes, run_arena, write_episodes
from games.orbit.ai.state import observation


def finish_mulligan(game):
    for pid in list(game["order"]):
        assert E.apply_move(game, pid, {"action": "mulligan", "card_ids": []})[0]


class _HistoryProbe:
    name = "history-probe"

    def __init__(self):
        self.seat = None
        self.histories = []

    def choose(self, game, pid, rng, *, observation=None, history=None, time_budget=None, belief=None):
        self.seat = game["order"].index(pid)
        self.histories.append(copy.deepcopy(history))
        return sorted(E.legal_moves(game, pid), key=lambda move: json.dumps(move, sort_keys=True))[0]


def test_all_eight_board_configurations_are_balanced_and_stable():
    boards = board_configurations()
    assert len(boards) == 8
    assert len({tuple(board[f] for f in ("robot", "human", "animod")) for board in boards}) == 8
    assert all(set(board) == {"robot", "human", "animod"} for board in boards)
    assert all(set(board.values()) == {1, 2} or len(set(board.values())) == 1 for board in boards)


def test_search_uses_root_visits_and_returns_legal_move():
    game = E.new_game(["A", "B"], seed=12)
    finish_mulligan(game)
    pid = game["turn_pid"]
    policy = SearchPolicy(InformationSetSearch(SearchConfig(simulations=12, time_limit=None, max_depth=20)))
    decision = policy.choose(game, pid, random.Random(7))
    assert decision.move in E.legal_moves(game, pid)
    assert decision.simulations == 12
    assert sum(item["visits"] for item in decision.stats) == 12
    assert abs(sum(decision.target().values()) - 1.0) < 1e-9


def test_neural_encoder_and_json_model_are_versioned_and_observation_only():
    game = E.new_game(["A", "B"], seed=8)
    obs = observation(game, "A")
    assert len(encode_observation(obs)) == OBS_SIZE
    assert len(encode_action(obs, obs["legal_moves"][0])) == ACTION_SIZE
    guide = NeuralGuide.random(seed=5)
    assert guide.hidden == HIDDEN_SIZE and guide.encoder == ENCODER_VERSION
    restored = NeuralGuide.from_dict(json.loads(json.dumps(guide.as_dict())))
    assert restored.priors(obs, obs["legal_moves"]) == guide.priors(obs, obs["legal_moves"])
    policy = NeuralPolicy(restored, epsilon=0.0)
    assert policy.choose(game, "A", random.Random(3)) in obs["legal_moves"]
    episode = play_game((RandomPolicy(), RandomPolicy()), seed=9, max_decisions=300)
    if not episode.censored:
        assert guide.fit([episode], epochs=1, learning_rate=0.001) == len(episode.steps)
        assert guide.examples == len(episode.steps)


def test_search_is_invariant_to_equivalent_true_hidden_worlds():
    game = E.new_game(["A", "B"], seed=19)
    finish_mulligan(game)
    pid = game["turn_pid"]
    other = game["order"][1 - game["order"].index(pid)]
    equivalent = copy.deepcopy(game)
    equivalent["players"][other]["hand"][0], equivalent["agent_deck"][0] = (
        equivalent["agent_deck"][0], equivalent["players"][other]["hand"][0]
    )
    equivalent["agent_deck"].reverse()
    equivalent["bonus_deck"].reverse()
    equivalent["rng_state"] = ["private"]
    policy = SearchPolicy(InformationSetSearch(SearchConfig(simulations=8, time_limit=None, max_depth=14)))
    assert observation(game, pid) == observation(equivalent, pid)
    assert policy.choose(game, pid, random.Random(44)).move == policy.choose(equivalent, pid, random.Random(44)).move


def test_simulated_opponent_history_contains_public_events_only():
    game = E.new_game(["A", "B"], seed=23)
    finish_mulligan(game)
    pid = game["turn_pid"]
    probe = _HistoryProbe()
    search = InformationSetSearch(
        SearchConfig(simulations=4, time_limit=None, max_depth=8), opponent=probe
    )
    search.choose(game, pid, random.Random(5))
    assert probe.histories
    for history in probe.histories:
        for event in history["events"]:
            assert event.get("changes") == {}
            if event.get("actor") != probe.seat:
                assert "own_action" not in event


def test_history_belief_conditions_on_public_opponent_card_and_restores():
    session = Session(E.new_game(["A", "B"], seed=22))
    for pid in session.game["order"]:
        assert session.step(pid, {"action": "mulligan", "card_ids": []})[0]
    viewer = session.game["order"][1]
    opponent = session.game["turn_pid"]
    belief = HistoryBelief(observation(session.game, viewer), particles=96, seed=4)
    card_id = session.game["players"][opponent]["hand"][0]
    move = {"action": "leader", "card_id": card_id}
    assert move in E.legal_moves(session.game, opponent)
    assert session.step(opponent, move)[0]
    event = session.policy_input(viewer)["history"]["events"][-1]
    belief.update(observation(session.game, viewer), event)
    assert all(card_id not in particle["opponent_hand"] for particle in belief.distribution())
    restored = HistoryBelief.restore(json.loads(json.dumps(belief.archive())))
    assert restored.distribution() == belief.distribution()
    assert restored.sample(random.Random(13)) == belief.sample(random.Random(13))
    assert restored.sample() == belief.sample()


def test_censored_episodes_are_not_labeled_as_draws_in_model():
    episode = play_game((RandomPolicy(), RandomPolicy()), seed=3, max_decisions=1)
    assert episode.censored
    assert episode.outcomes() is None
    model = TabularModel()
    assert model.fit([episode]) == 0
    assert model.episodes == 0
    candidate = train_candidate([episode])
    assert isinstance(candidate, TabularPolicy)


def test_random_board_is_recorded_and_censored_arena_score_is_excluded():
    episode = play_game((RandomPolicy(), RandomPolicy()), seed=31, configuration="random", max_decisions=0)
    assert set(episode.configuration) == {"robot", "human", "animod"}
    assert set(episode.configuration.values()) <= {1, 2}
    assert episode.censored
    result = run_arena(RandomPolicy(), RandomPolicy(), pairs=1, seed=31, max_decisions=1)
    assert result.censored == result.games and result.score == 0.5
    assert result.as_dict()["scored_games"] == 0
    assert all(board["score"] == 0.5 for board in result.by_board.values() if board["pairs"])


def test_episode_jsonl_carries_rules_seeds_and_policy_metadata(tmp_path):
    episode = play_game((RandomPolicy(), RandomPolicy()), seed=18, max_decisions=300)
    path = tmp_path / "orbit.jsonl"
    assert write_episodes(path, [episode]) == 1
    loaded = read_episodes(path)
    assert loaded[0].as_dict() == episode.as_dict()
    assert loaded[0].metadata["policy_fingerprints"]


def test_paired_arena_and_mirror_sanity():
    mirror = mirror_sanity(HeuristicPolicy(), pairs=2, seed=9, max_decisions=300)
    assert mirror["exact_half"]
    result = run_arena(HeuristicPolicy(), RandomPolicy(), pairs=2, seed=9, max_decisions=300)
    assert result.games == 4
    assert result.pairs == 2
    assert sum(result.by_board[key]["pairs"] for key in result.by_board) == 2
    assert result.rules


def test_algorithm_comparison_is_a_matrix_with_mirrors():
    report = compare_algorithms(
        {"h": HeuristicPolicy(), "r": RandomPolicy()},
        pairs=1,
        seed=13,
        max_decisions=250,
    )
    assert set(report["matrix"]) == {"h", "r"}
    assert "r" in report["matrix"]["h"] and "h" in report["matrix"]["r"]
    assert report["mirrors"]["h"]["exact_half"]


def test_league_mix_redistributes_missing_exploiters_and_roundtrips():
    league = League()
    policies = {name: HeuristicPolicy() for name in ("champion", "a", "b")}
    league.add_member("champion", policies["champion"], category="champion")
    league.add_member("a", policies["a"], category="learner")
    league.add_member("b", policies["b"], category="specialist")
    rng = random.Random(2)
    buckets = {"egt": 0, "diverse": 0, "exploiter": 0}
    for _ in range(200):
        _, bucket = league.sample_opponent(rng, exclude="champion")
        buckets[bucket] += 1
    assert buckets["exploiter"] == 0
    assert buckets["egt"] > 0 and buckets["diverse"] > 0
    restored = League.from_dict(json.loads(json.dumps(league.as_dict())))
    assert set(restored.members) == set(league.members)
    assert restored.rules == league.rules


def test_native_arena_rows_pair_by_seat_and_score_draws_as_half():
    from games.orbit.ai.selfplay import board_configurations
    from games.orbit.tools.native_search_arena import summarise

    boards = board_configurations()

    def row(candidate, winner, *, censored=False, error=None):
        return {"candidate": candidate, "winner": winner, "censored": censored, "error": error}

    # Pair 0: candidate wins from both seats.  Pair 1: a deck-exhaustion draw
    # from each seat, which is 0.5 for the candidate rather than a loss.
    # Pair 2: one censored game invalidates the whole pair.
    rows = [
        row(0, 0), row(1, 1),
        row(0, None), row(1, None),
        row(0, 0), row(1, 0, censored=True),
    ]
    result = summarise(rows, pairs=3, boards=boards, candidate="c", opponent="o", settings={})
    assert result.pair_scores == [1.0, 0.5]
    assert result.pair_scores_by_index == [1.0, 0.5, None]
    assert (result.wins, result.losses, result.draws, result.censored) == (3, 0, 2, 1)
    assert result.score == 4.0 / 5.0
    assert result.pair_score == 0.75
    assert [result.by_board[k]["pairs"] for k in sorted(result.by_board)].count(1) == 3
