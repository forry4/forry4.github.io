"""Architecture PRE-CHECK for the AlphaZero retrain (offline scratch).

THE go/no-go before committing days to the retrain: can a CARD-SET ATTENTION net distill the
search-backed value (V_search) past the flat-MLP wall? Runs purely on the cached snapshots from
`vsearch_distill` (no re-harvest) — minutes, not days.

`features.encode`'s 305 vector is already 12 board-card blocks (12 feats each: present, cost/7,
points/5, bonus one-hot) + 161 global feats. We reshape the card blocks into a SET and run
self-attention over them — the operation whose native shape IS engine_value's pairwise cross-card
sum, the thing a flat MLP provably can't assemble. Card features are fed RAW (already ~[0,1], and
standardizing would destroy the present=0 pooling mask); the ridge baseline uses standardized feats.

Read: if card-attention reaches ~the V_search target (~0.74) where the flat MLP capped ~0.66, the
retrain architecture is validated. If it also stalls ~the leaf, rethink features/arch FIRST.

Usage: python -m games.spender.ai.az.attn_distill --cache games/spender/ai/az/distill_cache.npz
"""
from __future__ import annotations

import argparse
import copy

import numpy as np
import torch
import torch.nn as nn

from .features import _CARD_F
from .vsearch_distill import _auc, _corr, _ridge

N_CARDS = 12
CARD_BLOCK = N_CARDS * _CARD_F          # 144
N_FEAT = 305
# the mover's tokens (6) + bonuses (5) live at 144..154; engine_value/effective-cost need them
# attached to EACH card token (the cross-card cost-reduction is conditioned on my bonuses).
CTX = slice(144, 155)
CTX_F = 11


class AttnNet(nn.Module):
    """Self-attention over the 12 board-card tokens (each augmented with the mover's tokens+bonuses
    so it can compute effective cost / engine_value) + a global-state branch -> value (tanh)."""

    def __init__(self, d=64, heads=4, layers=2, kind="value", dropout=0.1):
        super().__init__()
        self.card_embed = nn.Linear(_CARD_F + CTX_F, d)
        enc = nn.TransformerEncoderLayer(d, heads, dim_feedforward=2 * d, dropout=dropout,
                                         batch_first=True)
        self.attn = nn.TransformerEncoder(enc, layers)
        self.glob = nn.Sequential(nn.Linear(N_FEAT - CARD_BLOCK, d), nn.ReLU(), nn.Dropout(dropout))
        self.head = nn.Sequential(nn.Linear(2 * d, d), nn.ReLU(), nn.Dropout(dropout),
                                  nn.Linear(d, 1), nn.Tanh() if kind == "value" else nn.Sigmoid())

    def forward(self, x):
        b = x.shape[0]
        cards = x[:, :CARD_BLOCK].reshape(b, N_CARDS, _CARD_F)
        present = cards[:, :, :1]                       # (B,N,1) the present flag (raw 0/1)
        ctx = x[:, CTX].unsqueeze(1).expand(b, N_CARDS, CTX_F)   # mover bonuses+tokens per card
        tok = torch.cat([cards, ctx], -1)              # (B,N,_CARD_F+CTX_F)
        h = self.attn(self.card_embed(tok))            # (B,N,d) — cross-card interactions
        pooled = (h * present).sum(1) / present.sum(1).clamp(min=1.0)   # present-weighted mean
        g = self.glob(x[:, CARD_BLOCK:])
        return self.head(torch.cat([pooled, g], -1))


def _fit(net, Xtr, ytr, Xte, kind, epochs, lr, batch, wd, patience, dev):
    """Train with early stopping on an internal val split (last 12%), restore best."""
    net = net.to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=wd)
    lossf = nn.MSELoss() if kind == "value" else nn.BCELoss()
    nval = max(512, int(0.12 * len(Xtr)))
    xt = torch.from_numpy(Xtr[:-nval]).float().to(dev)
    yt = torch.from_numpy(ytr[:-nval]).float().to(dev).unsqueeze(1)
    xv = torch.from_numpy(Xtr[-nval:]).float().to(dev)
    yv = torch.from_numpy(ytr[-nval:]).float().to(dev).unsqueeze(1)
    n = xt.shape[0]
    best, best_state, bad = float("inf"), None, 0
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(n, device=dev)
        for b in range(0, n, batch):
            idx = perm[b:b + batch]
            opt.zero_grad()
            lossf(net(xt[idx]), yt[idx]).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            vl = float(lossf(net(xv), yv))
        if vl < best - 1e-5:
            best, best_state, bad = vl, copy.deepcopy(net.state_dict()), 0
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        return net(torch.from_numpy(Xte).float().to(dev)).squeeze(1).cpu().numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--d", type=int, default=64)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--target", choices=["search", "static"], default="search",
                    help="distill V_search (the search-backed value) or V_static (the leaf itself)")
    args = ap.parse_args()

    d = np.load(args.cache)
    X, vst, vse, won, gid = d["X"], d["vst"], d["vse"], d["won"], d["gid"]
    target = vst if args.target == "static" else vse   # what the models are trained to predict

    games = np.unique(gid)
    rng = np.random.default_rng(0)
    rng.shuffle(games)
    n_test = max(1, int(len(games) * args.test_frac))
    test_games = set(games[:n_test].tolist())
    te = np.array([g in test_games for g in gid])
    tr = ~te

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    won_te = won[te]

    # ridge baseline on standardized + bias (linear ceiling)
    mu = X[tr].mean(0)
    sd = X[tr].std(0) + 1e-6
    Xs = ((X - mu) / sd).astype(np.float32)
    Xtr_b = np.concatenate([Xs[tr], np.ones((tr.sum(), 1), np.float32)], 1).astype(np.float64)
    Xte_b = np.concatenate([Xs[te], np.ones((te.sum(), 1), np.float32)], 1).astype(np.float64)
    ridge_pred = _ridge(Xtr_b, target[tr].astype(np.float64), Xte_b, 10.0)

    # card-attention distillation on RAW features (preserves present-flag pooling)
    attn = AttnNet(args.d, args.heads, args.layers, "value")
    nparams = sum(p.numel() for p in attn.parameters())
    attn_pred = _fit(attn, X[tr], target[tr], X[te], "value", args.epochs, args.lr, args.batch,
                     1e-4, 25, dev)

    auc_leaf = _auc(vst[te], won_te)
    auc_search = _auc(vse[te], won_te)
    auc_ridge = _auc(ridge_pred, won_te)
    auc_attn = _auc(attn_pred.astype(np.float64), won_te)
    tname = f"V_{args.target}"

    print(f"[attn-distill] target={tname}  test {te.sum()} snapshots / {n_test} games  dev={dev}  "
          f"attn_params={nparams}  (d={args.d} heads={args.heads} layers={args.layers})")
    print(f"  {'model':28} {'AUC vs outcome':>15} {'corr to '+tname:>18}")
    print(f"  {'V_static (leaf bar)':28} {auc_leaf:>15.4f} {'-':>18}")
    print(f"  {'V_search (target bar)':28} {auc_search:>15.4f} {'-':>18}")
    print(f"  {'ridge (flat linear)':28} {auc_ridge:>15.4f} {_corr(ridge_pred, target[te]):>18.4f}")
    print(f"  {'card-attention':28} {auc_attn:>15.4f} "
          f"{_corr(attn_pred.astype(np.float64), target[te]):>18.4f}")
    gap = auc_search - auc_leaf
    capt = (auc_attn - auc_leaf) / gap if gap > 1e-6 else 0.0
    print(f"  search-vs-leaf gap = {gap:+.4f};  attention captured {capt*100:.0f}% of it "
          f"({'BEAT' if auc_attn > auc_leaf else 'below'} leaf)")
    if auc_attn >= auc_search - 0.015:
        v = "attention ~= search target -> ARCHITECTURE VALIDATED; the retrain can break the leaf wall."
    elif auc_attn <= auc_leaf + 0.01:
        v = "attention ~= leaf -> even attention stalls on these features; rethink features/arch FIRST."
    else:
        v = f"attention partway ({capt*100:.0f}% of the gap, above the leaf) -> promising; tune arch before committing."
    print(f"  VERDICT: {v}")


if __name__ == "__main__":
    main()
