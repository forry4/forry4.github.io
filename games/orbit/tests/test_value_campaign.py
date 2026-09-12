"""Outcome data uses observer identity and preserves whole-game seed splits."""
import pytest

from games.orbit import engine
from games.orbit.ai.state import observation
from games.orbit.tools.value_campaign import samples,game_seed
from games.orbit.ai.search import SearchPolicy,InformationSetSearch,policy_fingerprint


def test_nonacting_seat_receives_its_own_outcome_and_no_other_hand():
    game=engine.new_game(["A","B"],seed=3)
    steps=[{"actor_seat":0,"observer_seat":seat,"observation":observation(game,pid)}
           for seat,pid in enumerate(game["order"])]
    inputs,labels=samples({"steps":steps,"censored":False,"winner":1},per_seat=1)
    assert labels==[0.0,1.0]
    assert len(inputs)==2
    for seat,tokens in enumerate(inputs):
        hands=[t for t in tokens if len(t.path)>=3 and t.path[:1]==("players",) and t.path[2]=="hand"]
        assert hands and all(t.path[1]==seat for t in hands)


def test_censored_game_never_creates_a_value_label():
    assert samples({"censored":True})==([],[])


def test_samples_root_value_blend_is_optional_and_actor_only():
    game=engine.new_game(["A","B"],seed=31)
    steps=[{"observation":observation(game,pid),
            "search_value":-1.0 if seat==0 else None}
           for seat,pid in enumerate(game["order"])]
    record={"steps":steps,"censored":False,"winner":0}
    _,outcome=samples(record,per_seat=1)
    _,blended=samples(record,per_seat=1,root_value_beta=0.25)
    assert outcome==[1.0,0.0]
    assert blended==[0.75,0.0]


def test_partitions_do_not_overlap_and_seed_is_repeatable():
    a={game_seed("train-native-v2",i) for i in range(100)}
    b={game_seed("development-native-v2",i) for i in range(100)}
    assert a.isdisjoint(b)
    assert game_seed("train-native-v2",10)==game_seed("train-native-v2",10)


def test_search_fingerprint_includes_leaf_checkpoint_identity():
    class Guide:
        def __init__(self,digest):self.digest=digest
        def as_dict(self):return {"digest":self.digest}
    a=SearchPolicy(InformationSetSearch(guide=Guide("weights-a")))
    b=SearchPolicy(InformationSetSearch(guide=Guide("weights-b")))
    assert policy_fingerprint(a)!=policy_fingerprint(b)


def test_direct_vocabulary_matches_semantic_reference(tmp_path):
    import hashlib,json
    from games.orbit.ai.features import encode_features
    from games.orbit.ai.tensors import Vocabulary
    from games.orbit.tools.value_campaign import fit_vocabulary
    game=engine.new_game(["A","B"],seed=9)
    obs=observation(game,game["order"][0])
    obs["players"][0]["columns"][0]=[obs["players"][0]["hand"].pop()]
    record={"censored":False,"steps":[{"observation":obs}]}
    raw=json.dumps(record);(tmp_path/"game.json").write_text(raw,encoding="utf-8")
    manifest={"games":[{"file":"game.json","sha256":hashlib.sha256(raw.encode()).hexdigest()}]}
    assert fit_vocabulary(tmp_path,manifest)==Vocabulary.fit([encode_features(obs)])


# --- 2026-09-11 audit: cross-game batching -----------------------------------


def _fake_game(index, winner):
    """One censorship-free game with the shape `samples()` expects."""
    steps = []
    for turn in range(6):
        for seat in (0, 1):
            steps.append({"actor_seat": seat, "observer_seat": seat,
                          "observation": {"seat": seat, "turn": turn, "game": index},
                          "search_value": None})
    return {"censored": False, "winner": winner, "steps": steps}


def test_a_single_games_rows_carry_one_outcome_per_seat(monkeypatch):
    # The defect, stated directly: batching by game means every batch is eight
    # rows labelled 1 and eight labelled 0, all from one trajectory.
    from games.orbit.tools import value_campaign

    monkeypatch.setattr(value_campaign, "encode_features", lambda obs: obs)
    inputs, labels = value_campaign.samples(_fake_game(0, 0), per_seat=4)
    assert len(inputs) == 8
    assert sorted(set(labels)) == [0.0, 1.0]
    assert labels.count(1.0) == labels.count(0.0) == 4
    assert {row["game"] for row in inputs} == {0}, "one game per batch is the defect"


def test_cross_game_batches_mix_many_games_and_both_labels(monkeypatch):
    from games.orbit.tools import value_campaign

    monkeypatch.setattr(value_campaign, "encode_features", lambda obs: obs)
    rows = []
    for index in range(16):
        inputs, labels = value_campaign.samples(_fake_game(index, index % 2), per_seat=4)
        rows.extend(zip(inputs, labels))
    import random as _random
    _random.Random(9400).shuffle(rows)
    batch = rows[:64]
    games = {row["game"] for row, _ in batch}
    assert len(games) >= 8, f"a 64-row batch should span many games, spanned {len(games)}"
    labels = [label for _, label in batch]
    assert 0.0 in labels and 1.0 in labels


# --- policy targets (the prerequisite for a policy head) ---------------------
# Orbit recorded no policy target at all before 2026-09-11, which is why its
# PUCT prior is still the frozen hand-written `action_score`. These pin the
# target's shape and, more importantly, how it aligns to the legal moves.


def _step(moves, visits):
    return ({"visits": [{"move": m, "visits": v, "prior": 0.0}
                        for m, v in zip(moves, visits)]},
            {"legal_moves": list(moves)})


def test_policy_target_is_a_normalized_visit_distribution():
    from games.orbit.tools.value_campaign import policy_target

    step, obs = _step([{"a": 1}, {"a": 2}, {"a": 3}], [1, 3, 0])
    target = policy_target(step, obs)
    assert target == pytest.approx([0.25, 0.75, 0.0])
    assert sum(target) == pytest.approx(1.0)


def test_policy_target_aligns_by_move_identity_not_position():
    # The recorded stats come from the search's own deterministic move sort;
    # nothing guarantees that matches the observation's order. Aligning by
    # index would silently train the head on permuted labels -- a defect that
    # produces a plausible-looking loss curve and a useless prior.
    from games.orbit.tools.value_campaign import policy_target

    moves = [{"a": 1}, {"a": 2}, {"a": 3}]
    step, obs = _step(moves, [1, 3, 0])
    shuffled = {"visits": list(reversed(step["visits"]))}
    assert policy_target(shuffled, obs) == policy_target(step, obs)


def test_policy_target_is_absent_rather_than_wrong():
    # A row with no search (observer views, non-searching families, older
    # shards) must return None and go unsupervised, never a fabricated uniform.
    from games.orbit.tools.value_campaign import policy_target

    obs = {"legal_moves": [{"a": 1}, {"a": 2}]}
    assert policy_target({}, obs) is None
    assert policy_target({"visits": []}, obs) is None
    assert policy_target({"visits": [{"move": {"a": 1}, "visits": 0}]}, obs) is None
    assert policy_target({"visits": [{"move": {"a": 1}, "visits": -1}]}, obs) is None
    assert policy_target({"visits": [{"move": {"a": 1}, "visits": True}]}, obs) is None


def test_a_move_the_search_never_visited_scores_zero_not_missing():
    from games.orbit.tools.value_campaign import policy_target

    step = {"visits": [{"move": {"a": 1}, "visits": 4}]}
    obs = {"legal_moves": [{"a": 1}, {"a": 2}]}
    target = policy_target(step, obs)
    assert target == pytest.approx([1.0, 0.0])
    assert len(target) == len(obs["legal_moves"])


def _searched_game(index, winner, *, visited=True):
    """A game whose steps carry a recorded root visit distribution.

    Mirrors what `--record-policy` writes: the searched ACTOR rows carry
    `visits`, and the observer view of the same decision does not, so a real
    dataset always mixes supervised and unsupervised rows.
    """
    moves = [{"kind": "a"}, {"kind": "b"}, {"kind": "c"}]
    steps = []
    for turn in range(6):
        for seat in (0, 1):
            step = {"actor_seat": seat, "observer_seat": seat,
                    "observation": {"seat": seat, "turn": turn, "game": index,
                                    "legal_moves": moves},
                    "search_value": None}
            if visited:
                step["visits"] = [{"move": m, "visits": v, "prior": 0.0}
                                  for m, v in zip(moves, (1, 2, 5))]
            steps.append(step)
    return {"censored": False, "winner": winner, "steps": steps}


def test_policy_samples_keep_one_slot_per_input_row(monkeypatch):
    """Arity is what lets a mixed batch be built with a single zip."""
    from games.orbit.tools import value_campaign

    monkeypatch.setattr(value_campaign, "encode_features", lambda obs: obs)
    inputs, labels, policies = value_campaign.samples(_searched_game(0, 0), per_seat=4,
                                                      with_policy=True)
    assert len(inputs) == len(labels) == len(policies) == 8
    assert all(p == [0.125, 0.25, 0.625] for p in policies)


def test_rows_without_a_recorded_search_get_a_slot_but_no_target(monkeypatch):
    """Older shards and non-searching families must train value only, not a guess."""
    from games.orbit.tools import value_campaign

    monkeypatch.setattr(value_campaign, "encode_features", lambda obs: obs)
    inputs, _, policies = value_campaign.samples(_searched_game(0, 0, visited=False),
                                                 per_seat=4, with_policy=True)
    assert len(policies) == len(inputs)
    assert policies == [None] * len(inputs)


def test_a_censored_game_yields_three_empty_lists(monkeypatch):
    """The unpacking must not change shape on the path that produces nothing."""
    from games.orbit.tools import value_campaign

    monkeypatch.setattr(value_campaign, "encode_features", lambda obs: obs)
    assert value_campaign.samples({"censored": True}, with_policy=True) == ([], [], [])
    assert value_campaign.samples({"censored": True}) == ([], [])
