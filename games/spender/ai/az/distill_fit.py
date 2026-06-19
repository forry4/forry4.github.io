"""Fit + SAVE the distilled leaf model (ridge -> V_search on enriched features) for the leaf-swap A/B.

The pre-check (vsearch_distill) trained a ridge on enriched features that reached AUC ~0.694 vs the
static leaf's ~0.670 -- but discarded the weights. This refits that ridge on the cached enriched
snapshots and SAVES (w, mu, sd) to leaf_model.npz so vsearch can use it as the value leaf
(LEAF_MODE="distill") and we can A/B whether a smarter leaf -> stronger S at equal sims (the decisive
"does better-fitting convert to strength" test, given the turns-saga lesson that it often doesn't).

It (1) reports a by-game held-out AUC as a sanity check that the saved model reproduces the pre-check,
then (2) refits on ALL snapshots and saves that model (more data = best leaf).

Usage:
  python -m games.spender.ai.az.distill_fit --cache games/spender/ai/az/distill_cache_enriched.npz \
      --lam 10.0 --out games/spender/ai/az/leaf_model.npz
"""
from __future__ import annotations

import argparse
import os

import numpy as np

from .distill_features import ENRICHED_F


def _auc(scores, labels):
    order = np.argsort(scores, kind="mergesort")
    s, l = scores[order], labels[order]
    n = len(scores)
    ranks = np.empty(n)
    i = 0
    while i < n:
        j = i
        while j < n and s[j] == s[i]:
            j += 1
        ranks[i:j] = (i + j - 1) / 2.0 + 1.0
        i = j
    npos = float(l.sum())
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return 0.5
    return (ranks[l > 0.5].sum() - npos * (npos + 1) / 2.0) / (npos * nneg)


def _fit_ridge(X, y, mu, sd, lam):
    """Standardize with (mu,sd), bias-augment, closed-form ridge. Returns w (len F+1)."""
    Xs = (X - mu) / sd
    A = np.concatenate([Xs, np.ones((len(Xs), 1))], 1).astype(np.float64)
    M = A.T @ A + lam * np.eye(A.shape[1])
    return np.linalg.solve(M, A.T @ y.astype(np.float64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="games/spender/ai/az/distill_cache_enriched.npz")
    ap.add_argument("--lam", type=float, default=10.0)
    ap.add_argument("--out", default="games/spender/ai/az/leaf_model.npz")
    ap.add_argument("--test-frac", type=float, default=0.2)
    args = ap.parse_args()

    d = np.load(args.cache)
    X, vse, won, gid = d["X"].astype(np.float64), d["vse"], d["won"], d["gid"]
    assert X.shape[1] == ENRICHED_F, f"cache feature dim {X.shape[1]} != ENRICHED_F {ENRICHED_F}"
    print(f"[fit] {len(X)} snapshots, {X.shape[1]} features; target=V_search", flush=True)

    # by-game held-out AUC sanity (no leakage)
    games = np.unique(gid)
    rng = np.random.default_rng(0)
    rng.shuffle(games)
    nte = max(1, int(len(games) * args.test_frac))
    test = set(games[:nte].tolist())
    te = np.array([g in test for g in gid])
    tr = ~te
    mu_tr, sd_tr = X[tr].mean(0), X[tr].std(0) + 1e-6
    w_tr = _fit_ridge(X[tr], vse[tr], mu_tr, sd_tr, args.lam)
    pred_te = ((X[te] - mu_tr) / sd_tr) @ w_tr[:-1] + w_tr[-1]
    auc_model = _auc(pred_te, won[te])
    auc_leaf = _auc(vse[te], won[te])   # note: vse IS the search value (the train target), upper-ish bar
    print(f"[fit] held-out AUC vs outcome: distilled-ridge {auc_model:.4f}  (V_search target on test "
          f"{auc_leaf:.4f}; pre-check leaf bar ~0.670)", flush=True)

    # final model on ALL data
    mu, sd = X.mean(0), X.std(0) + 1e-6
    w = _fit_ridge(X, vse, mu, sd, args.lam)
    np.savez(args.out, w=w, mu=mu, sd=sd, lam=np.float64(args.lam),
             enriched_f=np.int64(ENRICHED_F))
    print(f"[fit] saved leaf model -> {args.out}  (w {w.shape}, fit on all {len(X)})", flush=True)


if __name__ == "__main__":
    main()
