"""Path-C distillation PROTOTYPE (offline scratch) — the measure-gate before any real Path-C build.

The three-way diagnostic said the search-backed value beats the static leaf and the gap GROWS with
depth, so distilling V+search into a cheap net (→ far more sims at the same budget) is the lever. The
open risk: V's strength is `engine_value`, a cross-card term the docs flag as "the one an MLP can't
assemble from a flat feature vector" — the wall that left variant Z behind. So before building the
pipeline, this checks the ONE thing that decides it:

  Can a model on the cheap 305-feature encoder learn the search-backed value (V_search) well enough
  to reach its discrimination, or does it cap at the static-leaf plateau?

Method: play S-vs-S (search-driven); at every PLAY snapshot record (features.encode(s), V_static,
V_search, eventual outcome) from the mover's perspective. Split BY GAME (snapshots in a game share an
outcome). Train two models to predict V_search from features — a numpy ridge (linear ceiling) and a
torch MLP (the capacity test) — then measure each model's STATIC AUC vs outcome on the held-out games,
against two bars computed on the SAME test set:
    ~0.64  leaf floor   -> the features wall bit; cheap-feature distillation STALLS (pivot to richer
                           features / accept the leaf ceiling).
    ~0.70  search target -> the net captured what search knows -> Path C VALIDATED (build the
                           distill -> deeper-search pipeline).

torch is imported lazily (after the pool) so harvest workers stay torch-free. Run on a QUIET box.

Usage:
  python -m games.spender.ai.az.vsearch_distill --games 400 --sims 384 --workers 12 --epochs 60
"""
from __future__ import annotations

import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")   # single-thread BLAS in spawned workers (documented caveat)

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
from . import v_state              # noqa: E402
from . import vsearch              # noqa: E402
from .mcts import Search           # noqa: E402

from .distill_features import ENRICHED_F, feat_enriched as _feat_enriched  # noqa: E402 (single source)


def _harvest_chunk(args):
    """Play S-vs-S games [lo, hi); return (X[n,F], v_static[n], v_search[n], won[n], gid[n])."""
    seed_base, lo, hi, sims, enriched = args
    feat = _feat_enriched if enriched else (lambda st, seat: F.encode(st).astype(np.float32))
    X, vst, vse = [], [], []
    won, gid = [], []
    for i in range(lo, hi):
        s = E.new_game(random.Random(seed_base + i))
        recs = []
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
                    tot = sum(search.root.N)
                    v_search = (sum(search.root.W) / tot) if tot else 0.0
                    recs.append((feat(s, seat), v_state.value(s, seat), v_search, seat))
                    E.apply(s, max(legal, key=lambda a: search.root.N[a]))
                    steps += 1
                    continue
            E.apply(s, vsearch.choose_action(s, s.turn, sims=sims))
            steps += 1
        if s.phase == E.OVER and s.winner != E.WIN_DRAW:
            for fvec, v_static, v_search, seat in recs:
                X.append(fvec)
                vst.append(v_static)
                vse.append(v_search)
                won.append(1.0 if s.winner == seat else 0.0)
                gid.append(i)
    if not X:
        w = ENRICHED_F if enriched else F.N_FEATURES
        return (np.zeros((0, w), np.float32), np.zeros(0, np.float32),
                np.zeros(0, np.float32), np.zeros(0, np.float32), np.zeros(0, np.int32))
    return (np.asarray(X, np.float32), np.asarray(vst, np.float32), np.asarray(vse, np.float32),
            np.asarray(won, np.float32), np.asarray(gid, np.int32))


def _auc(scores, labels):
    """ROC-AUC of continuous scores vs binary labels (Mann-Whitney, tie-averaged ranks)."""
    order = np.argsort(scores, kind="mergesort")
    s_sorted = scores[order]
    l_sorted = labels[order]
    n = len(scores)
    ranks = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i
        while j < n and s_sorted[j] == s_sorted[i]:
            j += 1
        ranks[i:j] = (i + j - 1) / 2.0 + 1.0
        i = j
    n_pos = float(l_sorted.sum())
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    sum_pos = ranks[l_sorted > 0.5].sum()
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _corr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def _ridge(Xtr, ytr, Xte, lam):
    """Closed-form ridge on standardized+bias-augmented features. Returns test predictions."""
    d = Xtr.shape[1]
    A = Xtr.T @ Xtr + lam * np.eye(d, dtype=np.float64)
    w = np.linalg.solve(A, Xtr.T @ ytr)
    return Xte @ w


def _train_mlp(Xtr, ytr, Xte, hidden, epochs, lr, batch, kind="value",
               dropout=0.3, wd=1e-4, patience=20):
    """Small MLP (305->h->h->1) -> test predictions, with DROPOUT + EARLY STOPPING on an internal
    val split (last 12% of train, restore best). kind='value': tanh+MSE (distill V_search);
    kind='outcome': sigmoid+BCE (features' raw win-prediction CEILING). Lazy torch import."""
    import copy as _copy
    import torch
    import torch.nn as nn
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    head = nn.Tanh() if kind == "value" else nn.Sigmoid()
    net = nn.Sequential(
        nn.Linear(Xtr.shape[1], hidden), nn.ReLU(), nn.Dropout(dropout),
        nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(dropout),
        nn.Linear(hidden, 1), head,
    ).to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=wd)
    lossf = nn.MSELoss() if kind == "value" else nn.BCELoss()

    nval = max(512, int(0.12 * len(Xtr)))
    xt = torch.from_numpy(Xtr[:-nval]).float().to(dev)
    yt = torch.from_numpy(ytr[:-nval]).float().to(dev).unsqueeze(1)
    xv = torch.from_numpy(Xtr[-nval:]).float().to(dev)
    yv = torch.from_numpy(ytr[-nval:]).float().to(dev).unsqueeze(1)
    n = xt.shape[0]
    best_val, best_state, bad = float("inf"), None, 0
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
            vloss = float(lossf(net(xv), yv))
        if vloss < best_val - 1e-5:
            best_val, best_state, bad = vloss, _copy.deepcopy(net.state_dict()), 0
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        pred = net(torch.from_numpy(Xte).float().to(dev)).squeeze(1).cpu().numpy()
    return pred, dev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--sims", type=int, default=384)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed0", type=int, default=80_000_000)
    ap.add_argument("--test-frac", type=float, default=0.2)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--ridge-lambda", type=float, default=10.0)
    ap.add_argument("--cache", default="", help="npz path: load harvested arrays if present, else save")
    ap.add_argument("--enriched", action="store_true",
                    help="append the leaf's derived terms (per-card TEPC + v_state comps + turns)")
    args = ap.parse_args()

    t0 = time.time()
    if args.cache and os.path.exists(args.cache):
        d = np.load(args.cache)
        X, vst, vse, won, gid = d["X"], d["vst"], d["vse"], d["won"], d["gid"]
        print(f"[distill] loaded {len(X)} cached snapshots from {args.cache}", flush=True)
    else:
        workers = max(1, args.workers)
        pool = mp.Pool(workers) if workers > 1 else None
        step = math.ceil(args.games / workers)
        tasks = [(args.seed0, lo, min(lo + step, args.games), args.sims, args.enriched)
                 for lo in range(0, args.games, step)]
        try:
            parts = pool.map(_harvest_chunk, tasks) if pool else [_harvest_chunk(t) for t in tasks]
        finally:
            if pool is not None:
                pool.close()
                pool.join()
        X = np.concatenate([p[0] for p in parts])
        vst = np.concatenate([p[1] for p in parts])
        vse = np.concatenate([p[2] for p in parts])
        won = np.concatenate([p[3] for p in parts])
        gid = np.concatenate([p[4] for p in parts])
        print(f"[distill] {len(X)} snapshots from {args.games} S-vs-S games @ sims={args.sims} "
              f"({time.time()-t0:.0f}s harvest)", flush=True)
        if args.cache:
            np.savez(args.cache, X=X, vst=vst, vse=vse, won=won, gid=gid)
            print(f"[distill] cached -> {args.cache}", flush=True)

    # split BY GAME (snapshots in a game share an outcome -> no leakage)
    games = np.unique(gid)
    rng = np.random.default_rng(0)
    rng.shuffle(games)
    n_test = max(1, int(len(games) * args.test_frac))
    test_games = set(games[:n_test].tolist())
    te = np.array([g in test_games for g in gid])
    tr = ~te

    # standardize on train
    mu = X[tr].mean(0)
    sd = X[tr].std(0) + 1e-6
    Xs = (X - mu) / sd
    Xtr = np.concatenate([Xs[tr], np.ones((tr.sum(), 1), np.float32)], 1).astype(np.float64)
    Xte = np.concatenate([Xs[te], np.ones((te.sum(), 1), np.float32)], 1).astype(np.float64)

    won_te = won[te]
    ridge_pred = _ridge(Xtr, vse[tr].astype(np.float64), Xte, args.ridge_lambda)
    mlp_v, dev = _train_mlp(Xs[tr], vse[tr], Xs[te], args.hidden, args.epochs, args.lr, args.batch, "value")
    mlp_o, _ = _train_mlp(Xs[tr], won[tr], Xs[te], args.hidden, args.epochs, args.lr, args.batch, "outcome")

    auc_leaf = _auc(vst[te], won_te)         # bar 1: the static leaf, on this test set
    auc_search = _auc(vse[te], won_te)        # bar 2: the search target, on this test set
    auc_ridge = _auc(ridge_pred, won_te)
    auc_mlp_v = _auc(mlp_v.astype(np.float64), won_te)
    auc_mlp_o = _auc(mlp_o.astype(np.float64), won_te)

    print(f"[distill] train {tr.sum()} / test {te.sum()} snapshots "
          f"({len(games)-n_test}/{n_test} games)  mlp dev={dev}  epochs={args.epochs}", flush=True)
    print(f"  {'model':30} {'AUC vs outcome':>15} {'corr to V_search':>17}")
    print(f"  {'V_static (leaf bar)':30} {auc_leaf:>15.4f} {'-':>17}")
    print(f"  {'V_search (target bar)':30} {auc_search:>15.4f} {'-':>17}")
    print(f"  {'ridge -> V_search':30} {auc_ridge:>15.4f} {_corr(ridge_pred, vse[te]):>17.4f}")
    print(f"  {'MLP -> V_search (distill)':30} {auc_mlp_v:>15.4f} {_corr(mlp_v.astype(np.float64), vse[te]):>17.4f}")
    print(f"  {'MLP -> outcome (feat ceiling)':30} {auc_mlp_o:>15.4f} {'-':>17}")

    best_net = max(auc_ridge, auc_mlp_v, auc_mlp_o)
    gap = auc_search - auc_leaf
    capt = (best_net - auc_leaf) / gap if gap > 1e-6 else 0.0
    print(f"  search-vs-leaf gap = {gap:+.4f};  best net (={best_net:.4f}) captured {capt*100:.0f}% of it",
          flush=True)
    if best_net >= auc_search - 0.01:
        verdict = "best net ~= search target -> Path C VALIDATED (a feature net learns what search knows)."
    elif best_net <= auc_leaf + 0.01:
        verdict = ("best net <= leaf floor -> features WALL (engine_value not assemblable from the 305 "
                   "cheap features) -> Path C STALLS on cheap features. Even the outcome-trained ceiling "
                   "can't reach the search target -> the limit is the features, not the teacher.")
    else:
        verdict = f"best net partway ({capt*100:.0f}% of the gap) -> Path C helps but the features wall caps it."
    print(f"  VERDICT: {verdict}", flush=True)


if __name__ == "__main__":
    main()
