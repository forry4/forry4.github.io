"""The policy head and its visit-count loss.

Orbit's PUCT prior has always been the frozen hand-written `action_score`, which
the audit measured deciding 50.5% of moves outright -- so the network could only
ever influence the leaf, never the shape of the tree. This covers the training
half of closing that gap: a head that produces one logit per legal action, and a
loss that teaches it the search's own root visit distribution.

Requires PyTorch, like every other test in this directory.
"""
import copy

import pytest
import torch

from games.orbit import engine
from games.orbit.ai.attention import (AttentionValue, ModelConfig, policy_loss,
                                      train_prepared)
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


def build(policy_head):
    torch.set_num_threads(1)
    torch.manual_seed(42)
    data = examples()
    model = AttentionValue(Vocabulary.fit(data), ModelConfig(policy_head=policy_head))
    return model, model.tensor_batch(data), data


def widths(batch):
    return [int(row.sum()) for row in batch["action_mask"]]


def test_every_legal_move_gets_its_own_action_slot():
    _, batch, _ = build(True)
    assert batch["action_mask"].shape[0] == 2
    for row, width in zip(batch["action_entity"], widths(batch)):
        assert width > 1, "fixture needs a real choice to supervise"
        assert len(set(row[:width].tolist())) == width, "actions must be distinct entities"


def test_zero_policy_weight_is_an_exact_control():
    """The value-only campaign must be unchanged, to the last bit."""
    plain, batch_plain, _ = build(False)
    loss_plain = train_prepared(plain, torch.optim.AdamW(plain.parameters(), lr=0.001),
                                batch_plain, [1.0, 0.0])
    headed, batch_headed, _ = build(True)
    loss_headed = train_prepared(headed, torch.optim.AdamW(headed.parameters(), lr=0.001),
                                 batch_headed, [1.0, 0.0])
    # Same seed, same value path; the untouched policy head cannot move the loss.
    assert loss_headed == pytest.approx(loss_plain, abs=1e-9)


def test_unsupervised_rows_contribute_nothing():
    """Rows with no recorded search must not be taught a uniform target."""
    model, batch, _ = build(True)
    logits, mask = torch.zeros(2, 4), torch.ones(2, 4, dtype=torch.bool)
    assert policy_loss(logits, mask, [None, None]) is None
    only_one = policy_loss(logits, mask, [None, [1.0, 0.0, 0.0, 0.0]])
    both = policy_loss(logits, mask, [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]])
    assert only_one == pytest.approx(both)  # the mean is over SUPERVISED rows only


def test_a_uniform_target_on_uniform_logits_is_the_entropy():
    """Anchors the loss to a number computable by hand: ln(4) for four actions."""
    import math
    logits, mask = torch.zeros(1, 4), torch.ones(1, 4, dtype=torch.bool)
    value = policy_loss(logits, mask, [[0.25] * 4])
    assert float(value) == pytest.approx(math.log(4), abs=1e-6)


def test_masked_actions_can_never_receive_probability():
    """A padded slot is -inf, so softmax gives it exactly zero -- before and after training."""
    logits = torch.tensor([[0.0, 0.0, float("-inf"), float("-inf")]])
    mask = torch.tensor([[True, True, False, False]])
    value = policy_loss(logits, mask, [[0.5, 0.5]])
    assert torch.isfinite(value), "0 * -inf must not reach the loss as NaN"
    assert float(value) == pytest.approx(torch.log(torch.tensor(2.0)).item(), abs=1e-6)


def test_the_head_learns_the_visit_distribution():
    model, batch, _ = build(True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    width = widths(batch)[0]
    # A peaked target on the LAST legal move, so agreement cannot come from a
    # prior that happens to favour the first.
    target = [0.0] * width
    target[-1] = 1.0
    policies = [target, None]

    def mass_on_the_taught_move():
        model.eval()
        with torch.no_grad():
            _, logits = model(batch)
        return float(torch.softmax(logits[0, :width], dim=-1)[-1])

    before = mass_on_the_taught_move()
    for _ in range(60):
        train_prepared(model, optimizer, batch, [1.0, 0.0], None, policies, 1.0)
    after = mass_on_the_taught_move()
    assert after > before + 0.2, f"policy did not move: {before:.3f} -> {after:.3f}"


def test_a_misaligned_target_raises_instead_of_training_quietly():
    """The failure this guard exists for is silent: mass on an illegal action."""
    logits = torch.zeros(1, 4)
    hole = torch.tensor([[True, False, True, False]])
    with pytest.raises(ValueError, match="not aligned"):
        policy_loss(logits, hole, [[0.5, 0.5]])
    trailing = torch.tensor([[True, True, True, False]])
    with pytest.raises(ValueError, match="not aligned"):
        policy_loss(logits, trailing, [[0.5, 0.5]])
    with pytest.raises(ValueError, match="wider than"):
        policy_loss(logits, torch.ones(1, 4, dtype=torch.bool), [[0.2] * 5])


@pytest.mark.parametrize("bad", [[0.5, 0.4], [1.5, -0.5], [float("nan"), 1.0]])
def test_a_target_that_is_not_a_distribution_raises(bad):
    logits, mask = torch.zeros(1, 2), torch.ones(1, 2, dtype=torch.bool)
    with pytest.raises(ValueError, match="must be a distribution"):
        policy_loss(logits, mask, [bad])


def test_policy_targets_on_a_headless_model_raise():
    model, batch, _ = build(False)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    with pytest.raises(ValueError, match="no policy head"):
        train_prepared(model, optimizer, batch, [1.0, 0.0], None, [[1.0], [1.0]], 1.0)


def test_one_policy_slot_per_row_is_required():
    model, batch, _ = build(True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    with pytest.raises(ValueError, match="one policy target slot per row"):
        train_prepared(model, optimizer, batch, [1.0, 0.0], None, [None], 1.0)


def test_predict_still_returns_values_on_a_policy_model():
    """`predict` reads the value head; a tuple return must not break serving paths."""
    model, _, data = build(True)
    values = model.predict(data)
    assert len(values) == 2 and all(0.0 <= v <= 1.0 for v in values)


def test_the_policy_head_changes_no_value_parameter_when_unused():
    model, batch, _ = build(True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    before = copy.deepcopy(model.state_dict())
    train_prepared(model, optimizer, batch, [1.0, 0.0])
    assert torch.equal(before["policy.weight"], model.state_dict()["policy.weight"]), \
        "an unsupervised policy head must not drift"
