"""AlphaZero training loop: self-play -> train -> gate -> promote.

Usage:
    python -m games.spender.ai.az.train_az --iters 30 --games 400 --sims 128

Each iteration:
  1. Self-play `--games` games with the current best net (PUCT + root noise).
  2. Push (features, visit-dist, outcome) into the replay buffer.
  3. Train a candidate (copy of best) on sampled minibatches.
  4. Gate: candidate vs best over `--gate-games` (no noise, temp 0).
     Promote if score >= --gate-threshold; promoted nets are checkpointed to
     az_best.pt and auto-exported to az_model.npz (numpy inference format).
az_last.pt + buffer are saved every iteration, so --resume continues cleanly.
"""
from __future__ import annotations

import argparse
import copy
import os
import pickle
import time
from collections import deque

import numpy as np
import torch

from . import selfplay
from .export import export_npz
from .net import SpenderNet, make_evaluator

DEF_DIR = os.path.join(os.path.dirname(__file__), "checkpoints")


def _train_candidate(net, buffer, steps, batch_size, lr, device):
    feats = np.stack([b[0] for b in buffer])
    pis = np.stack([b[1] for b in buffer])
    zs = np.asarray([b[2] for b in buffer], dtype=np.float32)
    n = len(buffer)
    net.train()
    net.to(device)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    p_loss_t = v_loss_t = 0.0
    for _ in range(steps):
        idx = np.random.randint(0, n, size=min(batch_size, n))
        x = torch.from_numpy(feats[idx]).to(device)
        pi = torch.from_numpy(pis[idx]).to(device)
        z = torch.from_numpy(zs[idx]).to(device)
        logits, v = net(x)
        p_loss = -(pi * torch.log_softmax(logits, dim=1)).sum(dim=1).mean()
        v_loss = torch.nn.functional.mse_loss(v, z)
        loss = p_loss + v_loss
        opt.zero_grad()
        loss.backward()
        opt.step()
        p_loss_t += p_loss.item()
        v_loss_t += v_loss.item()
    return p_loss_t / steps, v_loss_t / steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--games", type=int, default=400, help="self-play games per iteration")
    ap.add_argument("--sims", type=int, default=128, help="MCTS sims per move (self-play)")
    ap.add_argument("--parallel", type=int, default=128)
    ap.add_argument("--train-steps", type=int, default=600)
    ap.add_argument("--batch-size", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--buffer", type=int, default=300_000)
    ap.add_argument("--gate-games", type=int, default=60)
    ap.add_argument("--gate-sims", type=int, default=96)
    ap.add_argument("--gate-threshold", type=float, default=0.55)
    ap.add_argument("--temp-moves", type=int, default=10)
    ap.add_argument("--out", default=DEF_DIR)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    best_path = os.path.join(args.out, "az_best.pt")
    last_path = os.path.join(args.out, "az_last.pt")
    buf_path = os.path.join(args.out, "buffer.pkl")
    npz_path = os.path.join(args.out, "az_model.npz")

    best = SpenderNet()
    buffer: deque = deque(maxlen=args.buffer)
    start_iter = 0
    promotions = 0
    if args.resume and os.path.exists(last_path):
        ck = torch.load(last_path, map_location="cpu", weights_only=False)
        best.load_state_dict(ck["best"])
        start_iter = ck["iter"] + 1
        promotions = ck.get("promotions", 0)
        if os.path.exists(buf_path):
            with open(buf_path, "rb") as f:
                buffer = pickle.load(f)
            buffer = deque(buffer, maxlen=args.buffer)
        print(f"[resume] iter {start_iter}, buffer {len(buffer)}, promotions {promotions}",
              flush=True)

    print(f"[train_az] device={args.device} sims={args.sims} games/iter={args.games} "
          f"parallel={args.parallel}", flush=True)

    for it in range(start_iter, args.iters):
        t0 = time.time()
        evaluate = make_evaluator(best, args.device)
        (feats, pis, zs), st = selfplay.run_games(
            args.games, evaluate, n_sims=args.sims, max_parallel=args.parallel,
            temp_moves=args.temp_moves, seed=1000 + it)
        for k in range(len(zs)):
            buffer.append((feats[k], pis[k], zs[k]))
        print(f"[iter {it}] selfplay: {st['games']} games, {len(zs)} positions, "
              f"avg {st['avg_plies']:.1f} plies, {st['secs']:.0f}s "
              f"({st['games']/st['secs']:.2f} games/s) | buffer {len(buffer)}", flush=True)

        candidate = copy.deepcopy(best)
        p_l, v_l = _train_candidate(candidate, buffer, args.train_steps,
                                    args.batch_size, args.lr, args.device)
        print(f"[iter {it}] train: policy_loss {p_l:.3f} value_loss {v_l:.3f}", flush=True)

        _, gate = selfplay.run_games(
            args.gate_games, make_evaluator(candidate, args.device),
            make_evaluator(best, args.device), n_sims=args.gate_sims,
            max_parallel=args.gate_games, add_noise=False, temperature=0.0,
            record=False, seed=9000 + it)
        promoted = gate["score_a"] >= args.gate_threshold
        if promoted:
            best = candidate
            promotions += 1
            torch.save({"best": best.state_dict(), "iter": it,
                        "promotions": promotions}, best_path)
            export_npz(best, npz_path)
        print(f"[iter {it}] gate: candidate {gate['score_a']:.3f} vs best "
              f"({gate['games']} games) -> {'PROMOTED' if promoted else 'rejected'} "
              f"| total {time.time()-t0:.0f}s", flush=True)

        torch.save({"best": best.state_dict(), "iter": it,
                    "promotions": promotions}, last_path)
        with open(buf_path, "wb") as f:
            pickle.dump(buffer, f)

    print(f"[train_az] done: {promotions} promotions", flush=True)


if __name__ == "__main__":
    main()
