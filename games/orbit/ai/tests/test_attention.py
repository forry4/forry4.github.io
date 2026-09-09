"""Optional training-environment tests; run explicitly (requires PyTorch)."""
import copy

import pytest
import torch

from games.orbit import engine
from games.orbit.ai.attention import AttentionValue, train_batch, train_prepared, save_checkpoint, load_checkpoint
from games.orbit.ai.features import encode_features
from games.orbit.ai.state import observation
from games.orbit.ai.tensors import Vocabulary


def examples():
    game = engine.new_game(["A", "B"], seed=33)
    obs = observation(game, game["order"][0])
    a = encode_features(obs)
    obs["players"][0]["credits"] += 10
    b = encode_features(obs)
    return [a, b]


def test_padding_does_not_change_prediction():
    torch.set_num_threads(1)
    torch.manual_seed(42)
    data = examples()
    short = data[0][:20]
    model = AttentionValue(Vocabulary.fit(data)).eval()
    single = model.predict([short])[0]
    padded = model.predict([short, data[1]])[0]
    assert single == pytest.approx(padded, abs=1e-6)


def test_checkpoint_resumes_the_same_update(tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(42)
    data = examples()
    model = AttentionValue(Vocabulary.fit(data))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    before = copy.deepcopy(model.state_dict())
    loss = train_batch(model, optimizer, data, [1, 0])
    assert 0 < loss < 10
    assert any(not torch.equal(before[k], v) for k, v in model.state_dict().items())
    path = tmp_path / "model.pt"
    save_checkpoint(path, model, optimizer, step=1, metadata={"fixture": True})
    restored, opt, step, metadata = load_checkpoint(path)
    assert step == 1 and metadata == {"fixture": True}
    assert model.predict(data) == restored.predict(data)
    train_batch(model, optimizer, data, [1, 0])
    train_batch(restored, opt, data, [1, 0])
    for key, value in model.state_dict().items():
        torch.testing.assert_close(value, restored.state_dict()[key], rtol=0, atol=0)


def test_invalid_targets_do_not_update_parameters():
    torch.set_num_threads(1)
    data = examples()
    model = AttentionValue(Vocabulary.fit(data))
    optimizer = torch.optim.AdamW(model.parameters())
    before = copy.deepcopy(model.state_dict())
    with pytest.raises(ValueError, match="outcomes"):
        train_batch(model, optimizer, data, [float("nan"), 0])
    for key, value in model.state_dict().items():
        assert torch.equal(value, before[key])


def test_cached_batch_is_exactly_the_same_cpu_update():
    torch.set_num_threads(1)
    torch.manual_seed(88)
    data=examples()
    a=AttentionValue(Vocabulary.fit(data));b=copy.deepcopy(a)
    oa=torch.optim.AdamW(a.parameters(),lr=0.001)
    ob=torch.optim.AdamW(b.parameters(),lr=0.001)
    cached=b.tensor_batch(data)
    for _ in range(3):
        assert train_batch(a,oa,data,[1,0])==train_prepared(b,ob,cached,[1,0])
    for key,value in a.state_dict().items():
        torch.testing.assert_close(value,b.state_dict()[key],rtol=0,atol=0)
