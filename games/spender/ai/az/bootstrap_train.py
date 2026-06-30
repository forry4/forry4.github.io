"""Train SpenderNet to MIMIC S (value<-V_search, policy<-visit-pi) from the bootstrap harvest.

This is the bootstrap that starts the self-play net at ~S strength (vs variant-Z's from-scratch start).
Standard AZ losses: policy cross-entropy to S's visit distribution + MSE of the tanh value head to S's
search value. Features are RAW F.encode (no standardization -- matches net.make_evaluator / infer_np
serving). Saves a torch checkpoint AND exports the servable .npz (export_npz) for the net-vs-S arena.

Usage:
  python -m games.spender.ai.az.bootstrap_train --cache games/spender/ai/az/bootstrap_cache.npz \
      --epochs 60 --out games/spender/ai/az/checkpoints_bootstrap
"""
from __future__ import annotations

import argparse
import copy
import os

import numpy as np
import torch

from .export import export_npz
from .net import SpenderNet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="games/spender/ai/az/bootstrap_cache.npz")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--value-coef", type=float, default=1.0)
    ap.add_argument("--patience", type=int, default=12)
    ap.add_argument("--out", default="games/spender/ai/az/checkpoints_bootstrap")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    d = np.load(args.cache)
    X, V, PI, MASK, GID = d["X"], d["V"], d["PI"], d["MASK"], d["GID"]
    print(f"[btrain] {len(X)} positions, dev={args.device}", flush=True)

    games = np.unique(GID)
    rng = np.random.default_rng(0)
    rng.shuffle(games)
    nval = max(1, int(len(games) * args.val_frac))
    val_g = set(games[:nval].tolist())
    va = np.array([g in val_g for g in GID])
    tr = ~va

    dev = args.device
    Xt = torch.from_numpy(X).float()
    Vt = torch.from_numpy(V).float()
    PIt = torch.from_numpy(PI).float()
    Mt = torch.from_numpy(MASK)
    tr_i = torch.from_numpy(np.where(tr)[0])
    va_i = torch.from_numpy(np.where(va)[0]).to(dev)

    net = SpenderNet(in_features=X.shape[1]).to(dev)
    print(f"[btrain] net in_features={X.shape[1]} ({'enriched' if X.shape[1] != 305 else 'base'})", flush=True)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr, weight_decay=args.wd)

    def losses(idx):
        x = Xt[idx].to(dev)
        logits, value = net(x)
        m = Mt[idx].to(dev)
        logits = logits.masked_fill(~m, -1e30)
        logp = torch.log_softmax(logits, dim=1)
        pol = -(PIt[idx].to(dev) * logp).sum(1).mean()
        val = ((value - Vt[idx].to(dev)) ** 2).mean()
        return pol, val

    best, best_state, bad = float("inf"), None, 0
    n = len(tr_i)
    for ep in range(args.epochs):
        net.train()
        perm = tr_i[torch.randperm(n)]
        for b in range(0, n, args.batch):
            idx = perm[b:b + args.batch]
            opt.zero_grad()
            pol, val = losses(idx)
            (pol + args.value_coef * val).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            vp, vv = losses(va_i)
            vloss = float(vp + args.value_coef * vv)
        if vloss < best - 1e-5:
            best, best_state, bad = vloss, copy.deepcopy(net.state_dict()), 0
        else:
            bad += 1
            if bad >= args.patience:
                print(f"[btrain] early stop @ ep {ep}", flush=True)
                break
        if ep % 5 == 0 or bad == 0:
            print(f"  ep {ep:3d}  val pol {float(vp):.4f}  val mse {float(vv):.4f}  (best {best:.4f})", flush=True)

    if best_state is not None:
        net.load_state_dict(best_state)

    # policy-quality report on the val set: top-1 match to S's most-visited move + CE
    net.eval()
    with torch.no_grad():
        logits, _ = net(Xt[va_i].to(dev))
        m = Mt[va_i].to(dev)
        logits = logits.masked_fill(~m, -1e30)
        top1 = (logits.argmax(1) == PIt[va_i].to(dev).argmax(1)).float().mean().item()
        ce = -(PIt[va_i].to(dev) * torch.log_softmax(logits, 1)).sum(1).mean().item()
    print(f"[btrain] POLICY val: top-1 match to S {top1:.3f}, CE {ce:.3f}  "
          f"(base-feature net was ~uniform CE 2.67 / H3-prior matches S ~0.86)", flush=True)

    pt_path = os.path.join(args.out, "az_bootstrap.pt")
    npz_path = os.path.join(args.out, "az_bootstrap.npz")
    torch.save({"best": net.state_dict(), "iter": 0, "promotions": 0, "curr_p": 0.4}, pt_path)
    export_npz(net, npz_path)
    print(f"[btrain] best val {best:.4f}; saved {pt_path} + {npz_path}", flush=True)


if __name__ == "__main__":
    main()
