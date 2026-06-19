"""Shared enriched-feature builder for the leaf-distillation experiment (single source of truth).

The leaf model is trained on these features (distill_fit.py) and served on them (vsearch LEAF_MODE
"distill"), so train and serve MUST use the identical builder -- hence one module. Imports only the
low-level eval pieces (features/valuation3/heuristic3/v_state), never vsearch, so there is no cycle.

ENRICHED = base 305 encoder + the LEAF's derived terms the encoder omits: per board card the H3
(take, engine, point, cost), the v_state component breakdown for both seats, and the turns horizon.
This is the exact set the distillation pre-check found lifts a linear model past the static leaf
(ridge 0.694 vs leaf 0.670 AUC vs outcome).
"""
from __future__ import annotations

import numpy as np

from . import features as F
from . import heuristic3 as H3
from . import v_state
from . import valuation3 as V3

_GLOB_KEYS = ("points_me", "engine_me", "progress_me", "noble_me", "econ_me",
              "points_opp", "engine_opp", "progress_opp", "noble_opp", "econ_opp",
              "stand_me", "stand_opp")
ENRICHED_F = F.N_FEATURES + 12 * 4 + len(_GLOB_KEYS) + 1   # base + per-card TEPC + globals + turns


def feat_enriched(s, seat):
    """Base 305 features + per-card H3 (take,engine,point,cost) + v_state components + turns horizon."""
    base = F.encode(s)
    val = V3.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    pc = []
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            t, e, p, c = H3.components(val, ci, seat)
            pc.extend((t, e, p, c))
        else:
            pc.extend((0.0, 0.0, 0.0, 0.0))
    turns = val.estimated_turns_remaining()
    comp = v_state.components(s, seat)
    glob = [comp[k] for k in _GLOB_KEYS]
    return np.concatenate([base, np.asarray(pc, np.float32),
                           np.asarray(glob, np.float32),
                           np.asarray([turns], np.float32)]).astype(np.float32)
