import copy

import pytest

from games.orbit import engine
from games.orbit.ai.features import FeatureToken, encode_features
from games.orbit.ai.state import observation
from games.orbit.ai.tensors import TensorEncoder, Vocabulary


def sample():
    game = engine.new_game(["A", "B"], seed=32)
    return encode_features(observation(game, game["order"][0]))


def test_vocabulary_is_deterministic_and_export_roundtrips():
    tokens = sample()
    vocab = Vocabulary.fit([tokens])
    assert vocab == Vocabulary.fit([reversed(tokens), tokens])
    assert Vocabulary.from_dict(vocab.as_dict()) == vocab
    assert TensorEncoder(vocab).encode(tokens) == TensorEncoder(Vocabulary.from_dict(vocab.as_dict())).encode(tokens)


def test_longer_sequences_need_no_new_vocabulary_and_positions_do_not_collide():
    a = FeatureToken("history", ("events", 0, "actor"), "number", 0)
    b = FeatureToken("history", ("events", 900, "actor"), "number", 0)
    rows = TensorEncoder(Vocabulary.fit([[a]])).encode([a, b])
    assert rows[0]["path"] == rows[1]["path"]
    assert rows[0]["positions"] == [0] and rows[1]["positions"] == [900]


def test_unknown_categories_and_paths_fail_instead_of_colliding():
    a = FeatureToken("pending", ("type",), "category", "exile")
    encoder = TensorEncoder(Vocabulary.fit([[a]]))
    for b in [FeatureToken("pending", ("type",), "category", "transfer"),
              FeatureToken("pending", ("target",), "category", "exile")]:
        with pytest.raises(ValueError, match="Unseen"):
            encoder.encode([b])


def test_padding_cannot_confuse_real_zero_or_absent_position():
    a = FeatureToken("resources", ("players", 0, "credits"), "number", 0)
    b = FeatureToken("turn", ("winner",), "missing", None)
    batch = TensorEncoder(Vocabulary.fit([[a, b]])).batch([[a, b], [a]])
    assert batch["mask"].tolist() == [[True, True], [True, False]]
    assert batch["position_mask"].tolist() == [[[True], [False]], [[True], [False]]]
    assert batch["positions"].tolist() == [[[0], [0]], [[0], [0]]]
    assert batch["kind"][0, 0] != batch["kind"][0, 1]
    assert batch["kind"][1, 1] == 0


def test_unclipped_resources_and_precision_guard():
    tokens = [FeatureToken("resources", ("credits",), "number", n) for n in (31, 40, 1000)]
    encoder = TensorEncoder(Vocabulary.fit([tokens]))
    assert [r["number"] * 32 for r in encoder.encode(tokens)] == [31, 40, 1000]
    with pytest.raises(ValueError, match="exactly"):
        encoder.encode([FeatureToken("resources", ("credits",), "number", 2**24 + 1)])


def test_stale_or_ambiguous_vocabularies_are_rejected():
    value = Vocabulary.fit([sample()]).as_dict()
    for key, replacement in [("rules", "stale"), ("numeric_scale", 16),
                             ("paths", ["same", "same"])]:
        corrupt = copy.deepcopy(value)
        corrupt[key] = replacement
        with pytest.raises(ValueError):
            Vocabulary.from_dict(corrupt)


def test_card_ids_and_owner_roles_are_explicit_and_seat_relative():
    from games.orbit.ai.tensors import CARD_IDS
    game=engine.new_game(["A","B"],seed=32)
    obs=observation(game,game["order"][1]);tokens=encode_features(obs)
    rows=TensorEncoder(Vocabulary.fit([tokens])).encode(tokens)
    for token,row in zip(tokens,rows):
        if token.path[:1]==("players",):
            assert row["role"]==(2 if token.path[1]==1 else 3)
        if len(token.path)==4 and token.path[:3]==("players",1,"hand"):
            assert row["card"]==CARD_IDS[token.value]
