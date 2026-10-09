"""Feature collisions and information boundaries for the new learner input."""
import copy

import pytest

from games.orbit import engine as E
from games.orbit.ai.features import encode_features, FEATURE_GROUPS
from games.orbit.ai.history import Session
from games.orbit.ai.neural import encode_observation
from games.orbit.ai.state import native_state, observation


def view():
    game = E.new_game(["A", "B"], seed=13)
    return game, observation(game, game["order"][0])


@pytest.mark.parametrize("case", ["resources", "bonus", "capture_flag", "captured_identity"])
def test_preserves_distinctions_lost_by_legacy_encoder(case):
    _, a = view()
    if case == "resources":
        a["players"][0]["credits"] = 31
    b = copy.deepcopy(a)
    if case == "resources":
        b["players"][0]["credits"] = 40
    elif case == "bonus":
        a["planet_bonus"][0], b["planet_bonus"][0] = 1, 2
    elif case == "capture_flag":
        a["captured_this_turn"], b["captured_this_turn"] = [0], [1]
    else:
        a["players"][0]["captured"], b["players"][0]["captured"] = [0], [1]
    assert encode_observation(a) == encode_observation(b), "Fixture must demonstrate a legacy collision"
    assert encode_features(a) != encode_features(b)


def test_column_order_and_all_legal_payload_fields_are_preserved():
    _, a = view()
    a["players"][0]["columns"][0] = [101, 102]
    b = copy.deepcopy(a)
    b["players"][0]["columns"][0].reverse()
    assert encode_observation(a) == encode_observation(b)
    assert encode_features(a) != encode_features(b)
    a["legal_moves"] = [{"action": "choose", "amounts": [1, 2, 0, 0, 0]}]
    b = copy.deepcopy(a)
    b["legal_moves"][0]["amounts"] = [2, 1, 0, 0, 0]
    assert encode_features(a) != encode_features(b)


def test_hidden_world_invariance_and_rejection_of_privileged_state():
    game, a = view()
    other = game["order"][1]
    game["players"][other]["hand"][0], game["agent_deck"][0] = (
        game["agent_deck"][0], game["players"][other]["hand"][0])
    game["agent_deck"].reverse()
    game["bonus_deck"].reverse()
    assert encode_features(a) == encode_features(observation(game, game["order"][0]))
    with pytest.raises(ValueError, match="Unreviewed observation"):
        encode_features(native_state(game))
    a["players"][1]["hand"] = [101]
    with pytest.raises(ValueError, match="Unreviewed player"):
        encode_features(a, omit=FEATURE_GROUPS)


def test_structured_history_roundtrip_without_truncation_or_mutation():
    game, _ = view()
    session = Session(game)
    for pid in game["order"]:
        assert session.step(pid, {"action": "mulligan", "card_ids": []})[0]
    data = session.policy_input(game["order"][0])
    before = copy.deepcopy(data)
    tokens = encode_features(data["observation"], data["history"])
    assert data == before
    restored = Session.restore(session.archive()).policy_input(game["order"][0])
    assert tokens == encode_features(restored["observation"], restored["history"])
    assert any(t.group == "history" and "public_action" in t.path for t in tokens)
    data["history"]["events"][1]["own_action"] = {"action": "mulligan", "card_ids": [101]}
    with pytest.raises(ValueError, match="Opposing private history"):
        encode_features(data["observation"], data["history"])


def test_ablations_are_explicit_and_history_must_match_current_view():
    game, obs = view()
    full = encode_features(obs)
    assert encode_features(obs, omit=["resources"]) == tuple(t for t in full if t.group != "resources")
    with pytest.raises(ValueError, match="Unknown feature"):
        encode_features(obs, omit=["typo"])
    history = Session(game).policy_input(game["order"][0])["history"]
    history["initial"]["turn_number"] += 1
    with pytest.raises(ValueError, match="does not reconstruct"):
        encode_features(obs, history)


def test_new_observation_field_requires_review():
    _, obs = view()
    obs["new_field"] = "secret or legitimate: review before training"
    with pytest.raises(ValueError, match="Unreviewed observation"):
        encode_features(obs)


def test_history_older_than_eight_events_is_preserved():
    game, obs = view()
    history = Session(game).policy_input(game["order"][0])["history"]
    # Repeated public observations are legitimate history inputs. A past public
    # play remains meaningful even after it leaves a bounded recent-event window.
    history["events"] = [{"actor": 0, "changes": {}} for _ in range(12)]
    other = copy.deepcopy(history)
    history["events"][0]["public_action"] = {"action": "leader", "card_id": 101}
    other["events"][0]["public_action"] = {"action": "leader", "card_id": 102}
    assert encode_observation(obs, history) == encode_observation(obs, other)
    assert encode_features(obs, history) != encode_features(obs, other)


def test_pending_task_context_and_private_owner_boundary():
    _, obs = view()
    obs["pending_pid"] = obs["seat"]
    obs["pending"] = {"source": "test", "last_planet": "mars",
                      "task": {"type": "exile", "target": "self", "count": 1}}
    other = copy.deepcopy(obs)
    other["pending"]["task"]["target"] = "opponent"
    assert encode_features(obs) != encode_features(other)
    other["pending_pid"] = 1 - obs["seat"]
    with pytest.raises(ValueError, match="Opposing private pending"):
        encode_features(other)
