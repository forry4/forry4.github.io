"""Outcome data uses observer identity and preserves whole-game seed splits."""
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
