"""Policy-head pre-check for variant S (offline scratch).

Everything so far has studied the VALUE leaf; the POLICY prior (which moves PUCT searches) is still
the hand H3 anchor. This asks: can a learned policy predict the SEARCH's move distribution better
than the H3 prior? If yes, a learned policy is a fresh lever (better moves / sim) orthogonal to the
value-eval wall; if no (H3 already matches the search), it's cheaply ruled out.

Harvest: play S-vs-S; at each PLAY decision record (features.encode(s), search visit-distribution pi
over the 70 actions, legal mask, the H3-prior probs). Train a small policy MLP (features -> masked
softmax) to match pi (KL). Compare on held-out GAMES:
  * top-1 match to the search's most-visited move   (H3 prior vs learned net)
  * cross-entropy / KL to pi                          (lower = closer to the search policy)

torch lazy-imported (workers stay torch-free). Usage:
  python -m games.spender.ai.az.policy_precheck --games 200 --sims 256 --epochs 40 --workers 6 \
      --cache games/spender/ai/az/policy_cache.npz
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import logging
import math
import multiprocessing as mp
import random
import time

import numpy as np

logging.getLogger("games.spender").setLevel(logging.ERROR)

from . import engine as E          # noqa: E402
from . import features as F        # noqa: E402
from . import heuristic3 as H3     # noqa: E402
from . import valuation3 as V3     # noqa: E402
from . import vsearch              # noqa: E402
from .mcts import Search           # noqa: E402

NA = E.N_ACTIONS


def _h3_prior(s, seat):
    """The H3 policy prior probs over actions (the same softmax vsearch uses as the PUCT prior)."""
    legal = E.legal_actions(s)
    val = V3.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    return vsearch._policy_prior(val, s, seat, legal)


def _chunk(args):
    seed_base, lo, hi, sims = args
    X, PI, H3P, MASK = [], [], [], []
    for i in range(lo, hi):
        s = E.new_game(random.Random(seed_base + i))
        steps = 0
        while s.phase != E.OVER and steps < 400:
            if s.phase == E.PLAY:
                legal = E.legal_actions(s)
                if len(legal) > 1:
                    seat = s.turn
                    search = Search(s, vsearch._RNG, c_puct=vsearch.C_PUCT,
                                    add_noise=False, leaf_state=True)
                    for _ in range(sims):
                        vsearch._expand(search)
                    n = np.asarray(search.root.N, dtype=np.float64)
                    tot = n.sum()
                    if tot > 0:
                        pi = (n / tot).astype(np.float32)
                        mask = np.zeros(NA, dtype=np.float32)
                        for a in legal:
                            mask[a] = 1.0
                        X.append(F.encode(s).astype(np.float32))
                        PI.append(pi)
                        H3P.append(_h3_prior(s, seat).astype(np.float32))
                        MASK.append(mask)
                    E.apply(s, max(legal, key=lambda a: search.root.N[a]))
                    steps += 1
                    continue
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
            steps += 1
    return (np.asarray(X, np.float32), np.asarray(PI, np.float32),
            np.asarray(H3P, np.float32), np.asarray(MASK, np.float32))


def _top1(probs, pi):
    """Fraction of rows where argmax(probs) == argmax(pi) (the search's most-visited move)."""
    return float((probs.argmax(1) == pi.argmax(1)).mean())


def _xent(probs, pi):
    """Mean cross-entropy H(pi, probs) = -sum pi*log(probs)."""
    p = np.clip(probs, 1e-9, 1.0)
    return float((-(pi * np.log(p)).sum(1)).mean())


def _train_policy(Xtr, PItr, MASKtr, Xte, MASKte, hidden, epochs, lr, batch):
    import copy
    import torch
    import torch.nn as nn
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = nn.Sequential(nn.Linear(Xtr.shape[1], hidden), nn.ReLU(), nn.Dropout(0.2),
                        nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.2),
                        nn.Linear(hidden, NA)).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-5)
    xt = torch.from_numpy(Xtr).to(dev)
    pit = torch.from_numpy(PItr).to(dev)
    mkt = torch.from_numpy(MASKtr).to(dev)
    n = len(Xtr)
    nval = max(512, int(0.12 * n))
    idx = np.random.default_rng(0).permutation(n)
    vi, ti = idx[:nval], idx[nval:]

    def masked_logp(logits, mask):
        logits = logits.masked_fill(mask < 0.5, -1e9)
        return torch.log_softmax(logits, dim=1)

    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        net.train()
        perm = ti[np.random.default_rng(ep).permutation(len(ti))]
        for b in range(0, len(ti), batch):
            j = perm[b:b + batch]
            opt.zero_grad()
            lp = masked_logp(net(xt[j]), mkt[j])
            loss = -(pit[j] * lp).sum(1).mean()      # cross-entropy to pi
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            lp = masked_logp(net(xt[torch.from_numpy(vi).to(dev)]), mkt[torch.from_numpy(vi).to(dev)])
            vl = float(-(pit[torch.from_numpy(vi).to(dev)] * lp).sum(1).mean())
        if vl < best - 1e-5:
            best, best_state, bad = vl, copy.deepcopy(net.state_dict()), 0
        else:
            bad += 1
            if bad >= 12:
                break
    if best_state:
        net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        lg = net(torch.from_numpy(Xte).to(dev))
        lg = lg.masked_fill(torch.from_numpy(MASKte).to(dev) < 0.5, -1e9)
        return torch.softmax(lg, dim=1).cpu().numpy(), dev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--sims", type=int, default=256)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seed0", type=int, default=95_000_000)
    ap.add_argument("--test-frac", type=float, default=0.25)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--cache", default="")
    args = ap.parse_args()

    t0 = time.time()
    if args.cache and os.path.exists(args.cache):
        d = np.load(args.cache)
        X, PI, H3P, MASK, gid = d["X"], d["PI"], d["H3P"], d["MASK"], d["gid"]
        print(f"[policy] loaded {len(X)} cached rows from {args.cache}")
    else:
        workers = max(1, args.workers)
        pool = mp.Pool(workers) if workers > 1 else None
        step = math.ceil(args.games / workers)
        tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims)
                 for lo in range(0, args.games, step)]
        parts = pool.map(_chunk, tasks) if pool else [_chunk(t) for t in tasks]
        if pool:
            pool.close(); pool.join()
        X = np.concatenate([p[0] for p in parts])
        PI = np.concatenate([p[1] for p in parts])
        H3P = np.concatenate([p[2] for p in parts])
        MASK = np.concatenate([p[3] for p in parts])
        gid = np.concatenate([np.full(len(p[0]), k) for k, p in enumerate(parts)])  # chunk = game-group
        print(f"[policy] {len(X)} PLAY rows from {args.games} games @ sims={args.sims} "
              f"({time.time()-t0:.0f}s harvest)")
        if args.cache:
            np.savez(args.cache, X=X, PI=PI, H3P=H3P, MASK=MASK, gid=gid)

    groups = np.unique(gid)
    np.random.default_rng(0).shuffle(groups)
    nt = max(1, int(len(groups) * args.test_frac))
    test = set(groups[:nt].tolist())
    te = np.array([g in test for g in gid])
    tr = ~te

    net_probs, dev = _train_policy(X[tr], PI[tr], MASK[tr], X[te], MASK[te],
                                   args.hidden, args.epochs, args.lr, args.batch)
    h3_te, pi_te = H3P[te], PI[te]

    print(f"[policy] train {tr.sum()} / test {te.sum()} rows  dev={dev}")
    print(f"  {'policy':20} {'top-1 match to search':>22} {'xent to pi':>13}")
    print(f"  {'H3 prior (current)':20} {_top1(h3_te, pi_te):>22.4f} {_xent(h3_te, pi_te):>13.4f}")
    print(f"  {'learned net':20} {_top1(net_probs, pi_te):>22.4f} {_xent(net_probs, pi_te):>13.4f}")
    d_top1 = _top1(net_probs, pi_te) - _top1(h3_te, pi_te)
    if d_top1 > 0.03:
        v = f"learned policy beats H3 prior by {d_top1:+.3f} top-1 -> a learned POLICY HEAD is a real lever."
    elif d_top1 > 0.0:
        v = f"learned policy marginally above H3 ({d_top1:+.3f}) -> small room; weigh vs effort."
    else:
        v = "learned policy <= H3 prior -> H3 is already near-optimal as the policy; ruled out."
    print(f"  VERDICT: {v}")


if __name__ == "__main__":
    main()
