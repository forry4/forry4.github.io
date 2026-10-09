"""Information-boundary, archive and generated-data gates (no Rust needed).

The offline sampler and history-archive tests live in
`research_tests/test_ai_history_and_belief.py`.

Native compilation and full transition parity run in rust-orbit.yml; this suite
always runs and never conditionally skips when a local toolchain is absent.
"""
import copy
import json
import random

import pytest

from games.orbit import engine as E
from games.orbit.ai.belief import sample_hidden
from games.orbit.ai.history import Session
from games.orbit.ai.state import action_key, native_state, observation, rules_fingerprint
from games.orbit.tools.export_native import OUTPUT, render
from games.orbit.tools.native_parity import first_difference


def test_generated_data_is_current_and_rule_changes_invalidate_artifacts():
    assert OUTPUT.read_text(encoding="utf-8") == render()
    assert json.loads(render())["rules"] == rules_fingerprint()
    session = Session(E.new_game(["A", "B"], seed=3))
    archive = session.archive()
    archive["rules"] = "old rules"
    with pytest.raises(ValueError, match="rules/schema"):
        Session.restore(archive)


def test_different_hidden_worlds_have_identical_policy_inputs_and_samples():
    g = E.new_game(["A", "B"], seed=5)
    me, other = g["order"]
    before = copy.deepcopy(g)
    equivalent = copy.deepcopy(g)
    equivalent["players"][other]["hand"][0], equivalent["agent_deck"][0] = (
        equivalent["agent_deck"][0], equivalent["players"][other]["hand"][0])
    equivalent["agent_deck"].reverse()
    equivalent["bonus_deck"].reverse()
    equivalent["rng_state"] = ["SECRET_RNG"]
    equivalent["log"] = [{"message": "SECRET_LOG"}]
    equivalent["future_secret"] = "SECRET_ADDED_FIELD"
    equivalent["players"][other]["future_secret"] = "SECRET_PLAYER_FIELD"
    a, z = observation(g, me), observation(equivalent, me)
    assert a == z
    assert sample_hidden(a, random.Random(4)) == sample_hidden(z, random.Random(4))
    assert "SECRET" not in json.dumps(z)
    assert g == before
    z["players"][0]["credits"] += 20
    assert g == before, "Policy input must not alias live state"


def test_private_pending_queue_is_not_a_policy_feature():
    g = E.new_game(["A", "B"], seed=3)
    for pid in g["order"]:
        E.apply_move(g, pid, {"action": "mulligan", "card_ids": []})
    me, other = g["order"]
    g["pending_pid"] = other
    g["pending"] = {"source": "test", "context": {"secret": "SECRET_CONTEXT"}, "queue": [
        {"type": "discard_hand", "actor": other, "count": 1, "secret": "SECRET_TASK"},
        {"type": "credits", "actor": other, "amount": 1, "secret": "SECRET_FUTURE"},
    ]}
    a = observation(g, me)
    assert a["pending"] == {"source": "test", "waiting": True}
    assert a["legal_moves"] == []
    assert "SECRET" not in json.dumps(a)
    own = observation(g, other)
    assert own["pending"]["task"]["type"] == "discard_hand"
    assert "SECRET" not in json.dumps(own)
    assert set(m["card_id"] for m in own["legal_moves"]) == set(g["players"][other]["hand"])


def test_terminal_observation_does_not_gain_opponent_private_information():
    g = E.new_game(["A", "B"], seed=17)
    me, other = g["order"]
    g["phase"] = "over"
    obs = observation(g, me)
    assert "hand" not in obs["players"][1]
    assert len(E.player_view(g, me)["players"][other]["hand"]) == 4
    assert obs["legal_moves"] == []


def test_move_identity_and_parity_comparator_are_not_vacuous():
    assert action_key({"action": "choose", "accept": True}) != action_key({"action": "choose", "accept": False})
    assert action_key({"action": "choose", "cost": 3, "amount": 1}) != action_key({"action": "choose", "cost": 7, "amount": 2})
    before = native_state(E.new_game(["A", "B"], seed=5))
    after = copy.deepcopy(before)
    assert first_difference(before, after) is None
    after["players"][0]["credits"] += 1
    assert "credits" in first_difference(before, after)
    after = copy.deepcopy(before)
    after["pending_pid"] = 1
    assert "pending_pid" in first_difference(before, after)
