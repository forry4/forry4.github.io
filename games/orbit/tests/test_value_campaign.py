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
