"""Export a trained SpenderNet to .npz for dependency-light production inference."""
from __future__ import annotations

import numpy as np


def export_npz(net, path: str) -> None:
    """Save trunk/head weights as plain float32 arrays (W0,b0,W1,b1,...,Wp,bp,Wv,bv)."""
    sd = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in net.state_dict().items()}
    arrays = {}
    linear_keys = sorted(
        {k.rsplit(".", 1)[0] for k in sd if k.startswith("trunk.")},
        key=lambda k: int(k.split(".")[1]),
    )
    for i, base in enumerate(linear_keys):
        arrays[f"W{i}"] = sd[f"{base}.weight"]
        arrays[f"b{i}"] = sd[f"{base}.bias"]
    arrays["Wp"] = sd["policy.weight"]
    arrays["bp"] = sd["policy.bias"]
    arrays["Wv"] = sd["value.weight"]
    arrays["bv"] = sd["value.bias"]
    np.savez(path, **arrays)
