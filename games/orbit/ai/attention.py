"""Offline PyTorch value model over the audited tensor representation.

Requires the optional training environment. No imports from serving code.
This first model attends to all semantic tokens; compact entity pooling and
native inference must earn their place through profiling and parity checks.
"""
from dataclasses import asdict, dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F

from .tensors import GROUPS, KINDS, TensorEncoder, Vocabulary

MODEL_VERSION = "orbit-attention-value-v4"


@dataclass(frozen=True)
class ModelConfig:
    width: int = 64
    heads: int = 4
    layers: int = 2
    feedforward: int = 128
    indexed_features: bool = False
    # OFF by default so every existing checkpoint keeps loading strict=True:
    # a model saved without the head has no `policy.*` parameters, and
    # `ModelConfig(**checkpoint["config"])` defaults this back to False.
    policy_head: bool = False

    def __post_init__(self):
        if min(self.width, self.heads, self.layers, self.feedforward) < 1 or self.width % self.heads:
            raise ValueError("Invalid attention dimensions")


class AttentionValue(nn.Module):
    def __init__(self, vocabulary: Vocabulary, config: ModelConfig = ModelConfig()):
        super().__init__()
        self.vocabulary = Vocabulary.from_dict(vocabulary.as_dict())
        self.encoder = TensorEncoder(self.vocabulary)
        self.config = config
        d = config.width
        self.embeddings = nn.ModuleDict({
            "group": nn.Embedding(len(GROUPS) + 1, d, padding_idx=0),
            "kind": nn.Embedding(len(KINDS) + 1, d, padding_idx=0),
            "path": nn.Embedding(len(vocabulary.paths) + 1, d, padding_idx=0),
            "category": nn.Embedding(len(vocabulary.categories) + 1, d, padding_idx=0),
        })
        if config.indexed_features:
            from .tensors import CARD_IDS
            self.embeddings["card"] = nn.Embedding(len(CARD_IDS)+1,d,padding_idx=0)
            self.embeddings["role"] = nn.Embedding(4,d,padding_idx=0)
        self.number = nn.Linear(1, d, bias=False)
        # Depth identifies which array index this is (seat, column, card, event).
        # No bounded position-embedding table can silently truncate long histories.
        self.position = nn.Sequential(nn.Linear(2, d), nn.GELU(), nn.Linear(d, d))
        self.pool = nn.Sequential(nn.Linear(d, d), nn.GELU())
        self.pool_count = nn.Linear(1, d, bias=False)
        self.summary = nn.Parameter(torch.zeros(1, 1, d))
        self.blocks = nn.ModuleList([
            nn.TransformerEncoderLayer(d, config.heads, config.feedforward,
                                       dropout=0.0, activation="gelu", batch_first=True,
                                       norm_first=True)
            for _ in range(config.layers)
        ])
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, 1)
        # One logit per LEGAL-ACTION entity. `tensors.entity_key` already gives
        # every legal move its own entity, so this needs no new pooling -- the
        # transformer has been building a row per action all along and only the
        # value head ever read anything (the summary token).
        #
        # This is the lever the campaign never had: Orbit's PUCT prior is the
        # frozen hand-written `action_score`, which the search then agrees with
        # a majority of the time, so the network could only ever influence the
        # leaf. Spender measured its learned prior at +0.58 over its heuristic
        # prior at a matched value head.
        self.policy = nn.Linear(d, 1) if config.policy_head else None

    def forward(self, batch):
        mask = batch["mask"]
        if not batch.get("validated",False) and (mask.ndim != 2 or mask.shape[1] == 0 or not bool(mask.any(dim=1).all())):
            raise ValueError("Every position requires at least one feature token")
        x = sum(embedding(batch[key]) for key, embedding in self.embeddings.items())
        x = x + self.number(batch["number"].unsqueeze(-1))
        positions = batch["positions"].to(x.dtype)
        if positions.shape[-1]:
            depth = torch.arange(positions.shape[-1], device=x.device, dtype=x.dtype)
            depth = depth.expand_as(positions)
            p = self.position(torch.stack((positions / 32, depth / 8), dim=-1))
            x = x + (p * batch["position_mask"].unsqueeze(-1)).sum(dim=-2)
        x = self.pool(x).masked_fill(~mask.unsqueeze(-1), 0)
        entity = batch["entity"]
        count = batch["entity_count"] if "entity_count" in batch else int(entity.max()) + 1
        pooled = x.new_zeros((x.shape[0], count, x.shape[-1]))
        pooled.scatter_add_(1, entity.unsqueeze(-1).expand_as(x), x)
        sizes = x.new_zeros((x.shape[0], count, 1))
        sizes.scatter_add_(1, entity.unsqueeze(-1), mask.unsqueeze(-1).to(x.dtype))
        x = pooled[:, 1:] / sizes[:, 1:].clamp_min(1).sqrt()
        x = x + self.pool_count(sizes[:, 1:] / 32)
        mask = sizes[:, 1:, 0] > 0
        x = torch.cat((self.summary.expand(x.shape[0], -1, -1), x), dim=1)
        padding = torch.cat((torch.zeros((mask.shape[0], 1), dtype=torch.bool,
                                        device=mask.device), ~mask), dim=1)
        for block in self.blocks:
            x = block(x, src_key_padding_mask=padding)
        normed = self.norm(x)
        value = self.head(normed[:, 0]).squeeze(-1)
        if self.policy is None:
            return value
        # Row `e` of `normed` is entity id `e`: `pooled` is scatter-indexed by
        # entity id, `pooled[:, 1:]` drops the padding id, and the summary token
        # is prepended, which puts entity `e` back at position `e`.
        logits = self.policy(normed).squeeze(-1)
        index = batch["action_entity"]
        policy = logits.gather(1, index.clamp(min=0))
        return value, policy.masked_fill(~batch["action_mask"], float("-inf"))

    def tensor_batch(self, examples):
        device = next(self.parameters()).device
        arrays = self.encoder.batch(examples)
        if arrays["mask"].shape[1] == 0 or not arrays["mask"].any(axis=1).all():
            raise ValueError("Every position requires at least one feature token")
        result = {key: torch.as_tensor(value, device=device) for key,value in arrays.items()}
        result["entity_count"] = int(arrays["entity"].max()) + 1
        result["validated"] = True
        return result

    @torch.no_grad()
    def predict(self, examples):
        was_training = self.training
        self.eval()
        try:
            output = self(self.tensor_batch(examples))
            value = output[0] if isinstance(output, tuple) else output
            return value.sigmoid().cpu().tolist()
        finally:
            self.train(was_training)


def policy_loss(logits, mask, policies):
    """Cross-entropy against the root visit distribution, over LEGAL actions only.

    ``policies`` carries one entry per row: a distribution aligned to that row's
    legal moves, or None where the row has no recorded search -- observer views,
    non-searching opponent families, and every shard generated before
    2026-09-11. An unsupervised row contributes nothing, rather than being
    taught a uniform target nothing ever demonstrated.

    The alignment is checked rather than assumed. A target is accepted only if
    the row's real action slots are exactly its first ``len(distribution)``
    entries, because a hole in the mask would silently place visit mass on an
    action the model is forbidden to predict -- a misaligned prior that trains
    quietly and reads as a plain accuracy loss.
    """

    target = torch.zeros_like(logits)
    supervised = torch.zeros(logits.shape[0], dtype=torch.bool, device=logits.device)
    for row, distribution in enumerate(policies):
        if distribution is None:
            continue
        width = len(distribution)
        if width == 0 or width > logits.shape[1]:
            raise ValueError("Policy target is wider than the batch's action slots")
        if int(mask[row, :width].sum()) != width or bool(mask[row, width:].any()):
            raise ValueError("Policy target is not aligned to the row's legal moves")
        total = float(sum(distribution))
        if not math.isfinite(total) or abs(total - 1.0) > 1e-5 or any(p < 0 for p in distribution):
            raise ValueError("Policy target must be a distribution over the legal moves")
        target[row, :width] = torch.as_tensor(distribution, dtype=logits.dtype,
                                              device=logits.device)
        supervised[row] = True
    if not bool(supervised.any()):
        return None
    log_probs = F.log_softmax(logits, dim=-1)
    # Masked slots hold -inf and their target is exactly zero; replace them
    # before the multiply so 0 * -inf cannot produce a NaN.
    per_row = -(target * log_probs.masked_fill(~mask, 0.0)).sum(dim=-1)
    return per_row[supervised].mean()


def train_batch(model, optimizer, examples, outcomes, weights=None, policies=None, policy_weight=0.0):
    """One terminal-outcome update. Caller excludes censored trajectories."""
    batch = model.tensor_batch(examples)
    return train_prepared(model,optimizer,batch,outcomes,weights,policies,policy_weight)


def train_prepared(model,optimizer,batch,outcomes,weights=None,policies=None,policy_weight=0.0):
    """Same update on an immutable pre-encoded batch; no sampling change.

    Returns the TOTAL loss. ``policy_weight`` defaults to zero so the value-only
    campaign stays an exact control: with no policy targets this is the update
    it always was.
    """
    model.train()
    # Dataset labels originate on the CPU. Validate there before transfer so
    # each small predicate does not force a CUDA stream synchronization.
    targets = torch.as_tensor(outcomes, dtype=torch.float32)
    if targets.shape != (batch["mask"].shape[0],) or not bool(torch.isfinite(targets).all()) or not bool(((targets >= 0) & (targets <= 1)).all()):
        raise ValueError("Expected finite terminal outcomes in [0,1]")
    w = torch.ones_like(targets) if weights is None else torch.as_tensor(weights, device=targets.device, dtype=targets.dtype)
    if w.shape != targets.shape or not bool(torch.isfinite(w).all()) or not bool((w >= 0).all()) or w.sum() <= 0:
        raise ValueError("Invalid example weights")
    targets = targets.to(batch["number"].device)
    w = w.to(batch["number"].device)
    if policies is not None and len(policies) != targets.shape[0]:
        raise ValueError("Expected one policy target slot per row")
    optimizer.zero_grad(set_to_none=True)
    output = model(batch)
    predictions, logits = output if isinstance(output, tuple) else (output, None)
    if policies is not None and logits is None:
        raise ValueError("Policy targets supplied to a model with no policy head")
    loss = (F.binary_cross_entropy_with_logits(predictions, targets, reduction="none") * w).sum() / w.sum()
    if policies is not None and policy_weight:
        component = policy_loss(logits, batch["action_mask"], policies)
        if component is not None:
            loss = loss + policy_weight * component
    if not bool(torch.isfinite(loss)):
        raise ValueError("Non-finite training loss")
    loss.backward()
    nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
    optimizer.step()
    return float(loss.detach())


def save_checkpoint(path, model, optimizer, *, step, metadata=None):
    torch.save({"version": MODEL_VERSION, "vocabulary": model.vocabulary.as_dict(),
                "config": asdict(model.config), "model": model.state_dict(),
                "optimizer": optimizer.state_dict(), "step": step,
                "metadata": metadata or {}, "torch_rng": torch.get_rng_state(),
                "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}, path)


def load_checkpoint(path, *, device="cpu", fused_adam=False):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint["version"] not in ("orbit-attention-value-v2",
                                    "orbit-attention-value-v3", MODEL_VERSION):
        raise ValueError("Attention checkpoint version mismatch")
    model = AttentionValue(Vocabulary.from_dict(checkpoint["vocabulary"]),
                           ModelConfig(**checkpoint["config"])).to(device)
    model.load_state_dict(checkpoint["model"], strict=True)
    # Keep the historical unfused default for exact checkpoint continuation;
    # callers may opt into the faster fused kernel after a strength A/B.
    optimizer = torch.optim.AdamW(model.parameters(), fused=fused_adam)
    optimizer.load_state_dict(checkpoint["optimizer"])
    # ``load_state_dict`` restores the serialized param-group options too.  A
    # checkpoint made by an unfused run therefore silently turns a requested
    # fused resume back off (and vice versa).  Re-apply the explicit caller
    # choice after loading the moments; the model/RNG state is unchanged.
    for group in optimizer.param_groups:
        group["fused"] = bool(fused_adam)
    if fused_adam:
        # Fused CUDA AdamW requires its scalar step tensors on the same
        # device as the parameters; the portable checkpoint stores optimizer
        # state on CPU.  Move only this opt-in path so the historical regular
        # resume remains byte-for-byte compatible.
        for state in optimizer.state.values():
            for key, value in list(state.items()):
                if torch.is_tensor(value):
                    state[key] = value.to(device)
    torch.set_rng_state(checkpoint["torch_rng"])
    if checkpoint["cuda_rng"] and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(checkpoint["cuda_rng"])
    return model, optimizer, checkpoint["step"], checkpoint["metadata"]


def export_model(model):
    """Portable float artifact. Optimizer/RNG never enter serving assets."""
    return {"version": MODEL_VERSION, "vocabulary": model.vocabulary.as_dict(),
            "config": asdict(model.config),
            "weights": {key: {"shape": list(value.shape),
                              "data": value.detach().cpu().flatten().tolist()}
                        for key, value in model.state_dict().items()}}
