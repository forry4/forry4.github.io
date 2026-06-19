"""Policy+value MLP (PyTorch). Offline training only — production inference
uses the exported .npz via infer_np.py."""
from __future__ import annotations

import torch
import torch.nn as nn

from . import engine as E
from . import features as F

HIDDEN = (512, 512, 256)


class SpenderNet(nn.Module):
    def __init__(self, in_features: int = F.N_FEATURES):
        super().__init__()
        dims = (in_features,) + HIDDEN
        self.trunk = nn.Sequential(
            *[m for i in range(len(HIDDEN))
              for m in (nn.Linear(dims[i], dims[i + 1]), nn.ReLU())]
        )
        self.policy = nn.Linear(HIDDEN[-1], E.N_ACTIONS)
        self.value = nn.Linear(HIDDEN[-1], 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Returns (policy_logits [B, N_ACTIONS], value [B] in (-1, 1))."""
        h = self.trunk(x)
        return self.policy(h), torch.tanh(self.value(h)).squeeze(-1)


def make_evaluator(net: SpenderNet, device: str = "cpu"):
    """Batched evaluator: (features [B, F] float32 np, masks [B, A] bool np)
    -> (probs [B, A] np over legal actions, values [B] np). Used by MCTS."""
    import numpy as np

    net.eval()
    net.to(device)

    @torch.no_grad()
    def evaluate(feats, masks):
        x = torch.from_numpy(np.ascontiguousarray(feats)).to(device)
        logits, values = net(x)
        logits = logits.cpu().numpy()
        logits[~masks] = -1e30
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p[~masks] = 0.0
        p /= p.sum(axis=1, keepdims=True)
        return p, values.cpu().numpy()

    return evaluate
