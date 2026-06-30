"""Offline test: does a STRUCTURED (per-card) policy head break the slot->action wall?

The enriched flat MLP predicts S's move only 0.52 top-1 (vs the H3 prior's 0.86) DESPITE having H3's
per-card (T,E,P,C) as inputs -- a flat net can't learn which card-slot feature block drives which
action logit. A structured head applies a SHARED small MLP to each board slot's TEPC block to produce
THAT slot's buy/reserve logits (slot i -> actions BUY_BOARD+i / RES_BOARD+i), with a global head for
the non-card actions. This is the minimal architecture matched to the action structure.

Trains a flat baseline AND the structured head on the SAME enriched cache + split, reports top-1 match
to S's most-visited move + cross-entropy on held-out games. Decision:
  structured top-1 ~>= 0.80  -> wall broken; worth the full structured net + self-play build.
  structured ~= flat (~0.52) -> architecture isn't it either; the net path is dead.

Policy-only (no value head) -- isolates the policy-architecture question. CPU (nets are tiny).

Usage:
  python -m games.spender.ai.az.policy_arch_test --cache games/spender/ai/az/bootstrap_cache_enriched.npz
"""
from __future__ import annotations

import argparse
import copy

import numpy as np
import torch
import torch.nn as nn

from . import engine as E

TEPC_OFF, TEPC_N = 305, 48          # enriched layout: 12 board slots x (take,engine,point,cost)
GLOB_OFF = TEPC_OFF + TEPC_N        # 353: 12 v_state comps + 1 turn = 13
BUY_BOARD, RES_BOARD = E.A_BUY_BOARD, E.A_RES_BOARD
NA = E.N_ACTIONS


class FlatPolicy(nn.Module):
    def __init__(self, d, h=512):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d, h), nn.ReLU(), nn.Linear(h, h), nn.ReLU(),
                                 nn.Linear(h, NA))

    def forward(self, x):
        return self.net(x)


class StructuredPolicy(nn.Module):
    """Global head for all actions + a SHARED per-card head overriding the 24 board buy/reserve logits."""
    def __init__(self, d, ctx=256, ph=64):
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(d, ctx), nn.ReLU(), nn.Linear(ctx, ctx), nn.ReLU())
        self.glob = nn.Linear(ctx, NA)
        self.card = nn.Sequential(nn.Linear(4 + ctx, ph), nn.ReLU(), nn.Linear(ph, 2))  # ->(buy,reserve)

    def forward(self, x):
        c = self.trunk(x)
        logits = self.glob(c)                                  # [B, NA]
        tepc = x[:, TEPC_OFF:TEPC_OFF + TEPC_N].reshape(-1, 12, 4)
        cc = c.unsqueeze(1).expand(-1, 12, -1)                 # [B,12,ctx]
        card = self.card(torch.cat([tepc, cc], dim=2))         # [B,12,2]
        logits = logits.clone()
        logits[:, BUY_BOARD:BUY_BOARD + 12] = card[:, :, 0]
        logits[:, RES_BOARD:RES_BOARD + 12] = card[:, :, 1]
        return logits


def _train(model, Xtr, PItr, Mtr, Xva, PIva, Mva, epochs, lr, batch, patience=12):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    n = len(Xtr)
    best, best_state, bad = float("inf"), None, 0

    def ce(idx_x, idx_pi, idx_m):
        logits = model(idx_x).masked_fill(~idx_m, -1e30)
        return -(idx_pi * torch.log_softmax(logits, 1)).sum(1).mean()

    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        for b in range(0, n, batch):
            j = perm[b:b + batch]
            opt.zero_grad()
            ce(Xtr[j], PItr[j], Mtr[j]).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            v = float(ce(Xva, PIva, Mva))
        if v < best - 1e-5:
            best, best_state, bad = v, copy.deepcopy(model.state_dict()), 0
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        logits = model(Xva).masked_fill(~Mva, -1e30)
        top1 = (logits.argmax(1) == PIva.argmax(1)).float().mean().item()
        cev = float(-(PIva * torch.log_softmax(logits, 1)).sum(1).mean())
    return top1, cev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="games/spender/ai/az/bootstrap_cache_enriched.npz")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--val-frac", type=float, default=0.1)
    args = ap.parse_args()

    d = np.load(args.cache)
    X, PI, MASK, GID = d["X"], d["PI"], d["MASK"], d["GID"]
    assert X.shape[1] == 366, f"expected enriched 366, got {X.shape[1]}"
    games = np.unique(GID)
    rng = np.random.default_rng(0)
    rng.shuffle(games)
    nval = max(1, int(len(games) * args.val_frac))
    val = set(games[:nval].tolist())
    va = np.array([g in val for g in GID])
    tr = ~va

    Xt = torch.from_numpy(X).float()
    PIt = torch.from_numpy(PI).float()
    Mt = torch.from_numpy(MASK)
    Xtr, PItr, Mtr = Xt[tr], PIt[tr], Mt[tr]
    Xva, PIva, Mva = Xt[va], PIt[va], Mt[va]
    print(f"[policy-arch] train {tr.sum()} / val {va.sum()}  (enriched 366)", flush=True)

    f1, fce = _train(FlatPolicy(366), Xtr, PItr, Mtr, Xva, PIva, Mva, args.epochs, args.lr, args.batch)
    print(f"  FLAT       top-1 {f1:.3f}  CE {fce:.3f}", flush=True)
    s1, sce = _train(StructuredPolicy(366), Xtr, PItr, Mtr, Xva, PIva, Mva, args.epochs, args.lr, args.batch)
    print(f"  STRUCTURED top-1 {s1:.3f}  CE {sce:.3f}", flush=True)
    print("  (H3 prior matches S ~0.86; flat enriched net earlier ~0.52)", flush=True)
    if s1 >= 0.80:
        print(f"  VERDICT: structured BREAKS the wall ({s1:.3f}) -> worth the full structured-net build.", flush=True)
    elif s1 >= f1 + 0.10:
        print(f"  VERDICT: structured clearly helps (+{s1-f1:.3f}) but short of H3 -> partial; weigh effort.", flush=True)
    else:
        print("  VERDICT: structured ~= flat -> architecture isn't the fix; net path is dead.", flush=True)


if __name__ == "__main__":
    main()
