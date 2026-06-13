"""Pure-numpy inference for an exported SpenderNet (.npz). No torch dependency
— this is what production serving uses (same evaluator signature as
net.make_evaluator)."""
from __future__ import annotations

import numpy as np


def load_evaluator(path: str):
    """Returns evaluate(feats [B,F], masks [B,A]) -> (probs [B,A], values [B])."""
    z = np.load(path)
    trunk = []
    i = 0
    while f"W{i}" in z:
        trunk.append((z[f"W{i}"].T.copy(), z[f"b{i}"]))
        i += 1
    wp, bp = z["Wp"].T.copy(), z["bp"]
    wv, bv = z["Wv"].T.copy(), z["bv"]

    def evaluate(feats: np.ndarray, masks: np.ndarray):
        h = np.asarray(feats, dtype=np.float32)
        for w, b in trunk:
            h = np.maximum(h @ w + b, 0.0)
        logits = h @ wp + bp
        values = np.tanh(h @ wv + bv)[:, 0]
        logits = np.where(masks, logits, -1e30)
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p = np.where(masks, p, 0.0)
        p /= p.sum(axis=1, keepdims=True)
        return p, values

    return evaluate
