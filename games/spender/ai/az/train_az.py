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

import os

# Single-threaded BLAS/OMP, set BEFORE numpy/torch import so it sticks (and is
# inherited by spawned self-play workers). Each parallel worker does its own CPU
# numpy inference; without this every worker's BLAS spins one thread PER CORE, so
# N workers x ~ncores threads thrash the box (10 workers once hung for 30 min+
# producing nothing). GPU training in the parent is unaffected (CUDA, not BLAS).
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import argparse
import copy
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


def _opp_spec(args, v):
    """Spec for one opponent variant. 'S' -> variant S (vsearch); else a weight-set heuristic."""
    if v.upper() == "S":
        return {"kind": "s", "opp_sims": args.opp_s_sims, "label": "S"}
    return {"kind": "heur", "variant": v, "opp_iters": args.opp_iters}


def _heur_assignments(args, n_total):
    """Even (spec, n_games) split of n_total across the heuristic variants (S allowed)."""
    variants = [v.strip() for v in args.heur_variants.split(",") if v.strip()]
    per = n_total // max(1, len(variants))
    return [(_opp_spec(args, v), per) for v in variants if per > 0]


def _league_assignments(args, pool_files):
    """(spec, n_games) list for the heuristic + past-AZ fractions of one iter."""
    assignments = _heur_assignments(args, int(round(args.games * args.heur_frac)))
    n_league = int(round(args.games * args.league_frac))
    if n_league > 0 and pool_files:
        sel = pool_files[-args.pool_size:]
        per = max(1, n_league // len(sel))
        for f in sel:
            assignments.append(({"kind": "az", "npz": f, "label": "past",
                                 "opp_sims": args.opp_sims}, per))
    return assignments


def _curr_specs(args, curr_p, n_total):
    """Eps-opponent specs (one per heuristic variant) sharing n_total games,
    all labeled 'cur' so their net win rate aggregates as the difficulty signal."""
    variants = [v.strip() for v in args.heur_variants.split(",") if v.strip()]
    per = max(1, n_total // len(variants))
    # 'S' is the hard target, not part of the eps difficulty ramp -> always a full-strength S opponent.
    return [(({"kind": "s", "opp_sims": args.opp_s_sims, "label": "S"} if v.upper() == "S"
              else {"kind": "eps", "variant": v, "p": curr_p,
                    "opp_iters": args.curr_opp_iters, "label": "cur"}), per)
            for v in variants]


def _curriculum_assignments(args, curr_p, pool_files):
    """Heuristic fraction -> eps-opponent at curr_p; plus the past-AZ fraction."""
    assignments = _curr_specs(args, curr_p, int(round(args.games * args.heur_frac)))
    n_league = int(round(args.games * args.league_frac))
    if n_league > 0 and pool_files:
        sel = pool_files[-args.pool_size:]
        per = max(1, n_league // len(sel))
        for f in sel:
            assignments.append(({"kind": "az", "npz": f, "label": "past",
                                 "opp_sims": args.opp_sims}, per))
    return assignments


def _curriculum_gate(pool, league, args, cand_npz, best_npz, curr_p, it):
    """Gate at the current difficulty p: candidate vs best, greedy."""
    assigns = _curr_specs(args, curr_p, args.gate_games)
    _, cand_scores, _ = league.run_league_games(
        pool, cand_npz, assigns, n_sims=args.gate_sims, temperature=0.0,
        temp_moves=0, add_noise=False, reward_shaping=0.0, seed=9000 + it)
    _, best_scores, _ = league.run_league_games(
        pool, best_npz, assigns, n_sims=args.gate_sims, temperature=0.0,
        temp_moves=0, add_noise=False, reward_shaping=0.0, seed=9000 + it)
    return cand_scores.get("cur", 0.0), best_scores.get("cur", 0.0)


def _league_gate(pool, league, args, cand_npz, best_npz, it):
    """Promotion gate for league mode: candidate vs best on the SAME heuristic
    set, greedy. Returns (cand_score, best_score, cand_per_opponent)."""
    assigns = _heur_assignments(args, args.gate_games)
    _, cand_scores, _ = league.run_league_games(
        pool, cand_npz, assigns, n_sims=args.gate_sims, temperature=0.0,
        temp_moves=0, add_noise=False, reward_shaping=0.0, seed=9000 + it)
    _, best_scores, _ = league.run_league_games(
        pool, best_npz, assigns, n_sims=args.gate_sims, temperature=0.0,
        temp_moves=0, add_noise=False, reward_shaping=0.0, seed=9000 + it)
    cand = sum(cand_scores.values()) / max(1, len(cand_scores))
    best = sum(best_scores.values()) / max(1, len(best_scores))
    return cand, best, cand_scores


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
    ap.add_argument("--temperature", type=float, default=1.0,
                    help="self-play action-selection temperature for first temp-moves")
    ap.add_argument("--temp-moves", type=int, default=10,
                    help="number of opening moves played at --temperature before going greedy")
    ap.add_argument("--dirichlet-eps", type=float, default=0.25,
                    help="root Dirichlet noise fraction (higher = more exploration)")
    ap.add_argument("--reward-shaping", type=float, default=0.0,
                    help="0..1 blend of point-margin into the value target (breaks the "
                         "0-0 fewest-cards self-play equilibrium); 0 = pure win/loss")
    ap.add_argument("--shaping-scale", type=float, default=6.0,
                    help="point-margin divisor for reward shaping (use ~15 for linear)")
    ap.add_argument("--shaping-mode", default="tanh", choices=["tanh", "linear"],
                    help="tanh saturates at large deficits (gradient dies); linear keeps a "
                         "constant per-point gradient — better when the net loses most games")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel CPU self-play worker processes "
                         "(1 = single-process torch path; >1 fans games across cores)")
    ap.add_argument("--worker-parallel", type=int, default=None,
                    help="games batched per worker for the numpy forward (default = chunk size)")
    # League: train against a pool of opponents, not only self (the strength
    # lever once pure self-play plateaus vs the heuristics). Requires workers>1.
    ap.add_argument("--league", action="store_true",
                    help="mix in recorded games vs heuristics + past AZ checkpoints")
    ap.add_argument("--self-frac", type=float, default=0.4, help="fraction of games via self-play")
    ap.add_argument("--heur-frac", type=float, default=0.4,
                    help="fraction vs heuristics (split across --heur-variants)")
    ap.add_argument("--league-frac", type=float, default=0.2,
                    help="fraction vs sampled past AZ checkpoints (folds into self when pool empty)")
    ap.add_argument("--heur-variants", default="A,B,C2",
                    help="comma-list of opponents; 'S' = variant S (vsearch), the real bar to beat")
    ap.add_argument("--opp-s-sims", type=int, default=128,
                    help="search budget for an 'S' (vsearch) league/gate opponent")
    ap.add_argument("--opp-iters", type=int, default=120, help="heuristic opponent MCTS iters")
    ap.add_argument("--opp-sims", type=int, default=96, help="past-AZ opponent PUCT sims")
    ap.add_argument("--pool-size", type=int, default=6, help="max past-AZ checkpoints kept in the league pool")
    # Curriculum: replace the fixed-strength heuristic fraction with an
    # epsilon-mixed opponent (heuristic move w.p. p, else random) whose p
    # auto-climbs as the net masters the current difficulty. p is a TEMPO knob:
    # p=0 is a non-racing random player the net can beat; p=1 is the full racer.
    # This lets the net cross the loss-minimizing -> winning fitness valley.
    ap.add_argument("--curriculum", action="store_true",
                    help="adaptive epsilon-opponent curriculum for the heuristic fraction")
    ap.add_argument("--curr-p", type=float, default=0.4, help="starting heuristic-move probability")
    ap.add_argument("--curr-target", type=float, default=0.55, help="net win-rate the curriculum holds")
    ap.add_argument("--curr-step", type=float, default=0.05, help="p adjustment per iteration")
    ap.add_argument("--curr-opp-iters", type=int, default=30, help="heuristic strength when the eps-opponent acts")
    ap.add_argument("--out", default=DEF_DIR)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    if args.curriculum:
        args.league = True   # curriculum runs inside the league generation/gate path

    os.makedirs(args.out, exist_ok=True)
    best_path = os.path.join(args.out, "az_best.pt")
    last_path = os.path.join(args.out, "az_last.pt")
    buf_path = os.path.join(args.out, "buffer.pkl")
    npz_path = os.path.join(args.out, "az_model.npz")
    work_best = os.path.join(args.out, "_work_best.npz")   # current-best snapshot for CPU workers
    work_cand = os.path.join(args.out, "_work_cand.npz")   # candidate snapshot for the gate
    pool_dir = os.path.join(args.out, "league_pool")       # frozen past-AZ opponents

    league = pool_files = None
    if args.league:
        from . import league                               # imports arena/incumbent; lazy
        os.makedirs(pool_dir, exist_ok=True)
        pool_files = sorted(os.path.join(pool_dir, f) for f in os.listdir(pool_dir)
                            if f.endswith(".npz"))

    best = SpenderNet()
    buffer: deque = deque(maxlen=args.buffer)
    start_iter = 0
    promotions = 0
    curr_p = args.curr_p            # current curriculum difficulty (adaptive)
    if args.resume and os.path.exists(last_path):
        ck = torch.load(last_path, map_location="cpu", weights_only=False)
        best.load_state_dict(ck["best"])
        start_iter = ck["iter"] + 1
        promotions = ck.get("promotions", 0)
        curr_p = ck.get("curr_p", curr_p)
        if os.path.exists(buf_path):
            with open(buf_path, "rb") as f:
                buffer = pickle.load(f)
            buffer = deque(buffer, maxlen=args.buffer)
        print(f"[resume] iter {start_iter}, buffer {len(buffer)}, promotions {promotions}"
              + (f", curr_p {curr_p:.2f}" if args.curriculum else ""), flush=True)

    if args.league and args.workers <= 1:
        raise SystemExit("--league requires --workers > 1 (opponent games run in worker processes)")

    pool = None
    if args.workers > 1:
        import multiprocessing as mp
        pool = mp.Pool(args.workers)

    league_msg = ""
    if args.curriculum:
        league_msg = (f" | CURRICULUM p={curr_p:.2f}->1.0 target={args.curr_target} "
                      f"opp_iters={args.curr_opp_iters} self={args.self_frac} "
                      f"heur={args.heur_frac} past={args.league_frac} pool={len(pool_files)}")
    elif args.league:
        league_msg = (f" | LEAGUE self={args.self_frac} heur={args.heur_frac}"
                      f"({args.heur_variants}) past={args.league_frac} "
                      f"pool={len(pool_files)} opp_iters={args.opp_iters}")
    print(f"[train_az] device={args.device} sims={args.sims} games/iter={args.games} "
          f"parallel={args.parallel} workers={args.workers} | shaping={args.reward_shaping} "
          f"({args.shaping_mode} scale={args.shaping_scale}) temp={args.temperature}x{args.temp_moves} "
          f"dir_eps={args.dirichlet_eps}{league_msg}", flush=True)

    for it in range(start_iter, args.iters):
        t0 = time.time()
        if args.league:
            export_npz(best, work_best)
            assignments = (_curriculum_assignments(args, curr_p, pool_files)
                           if args.curriculum else _league_assignments(args, pool_files))
            n_assigned = sum(c for _, c in assignments)
            n_self = max(0, args.games - n_assigned)
            parts_f, parts_p, parts_z = [], [], []
            winpts = 0.0
            if n_self > 0:
                (sf, sp, sz), st = selfplay.run_games_parallel(
                    pool, args.workers, work_best, n_self, n_sims=args.sims,
                    worker_parallel=args.worker_parallel, temperature=args.temperature,
                    temp_moves=args.temp_moves, dirichlet_eps=args.dirichlet_eps,
                    reward_shaping=args.reward_shaping, shaping_scale=args.shaping_scale,
                    shaping_mode=args.shaping_mode, seed=1000 + it)
                parts_f.append(sf); parts_p.append(sp); parts_z.append(sz)
                winpts = st["avg_winpts"]
            scores = {}
            if assignments:
                (lf, lp, lz), scores, _ = league.run_league_games(
                    pool, work_best, assignments, n_sims=args.sims,
                    temperature=args.temperature, temp_moves=args.temp_moves,
                    dirichlet_eps=args.dirichlet_eps, reward_shaping=args.reward_shaping,
                    shaping_scale=args.shaping_scale, shaping_mode=args.shaping_mode,
                    seed=5000 + it)
                parts_f.append(lf); parts_p.append(lp); parts_z.append(lz)
            feats = np.concatenate(parts_f)
            pis = np.concatenate(parts_p)
            zs = np.concatenate(parts_z)
            for k in range(len(zs)):
                buffer.append((feats[k], pis[k], zs[k]))
            ptag = f"p={curr_p:.2f} " if args.curriculum else ""  # p adapts after the (greedy) gate
            sstr = " ".join(f"{k} {v:.2f}" for k, v in sorted(scores.items()))
            print(f"[iter {it}] league: {ptag}{len(zs)} pos (self {n_self} winpts {winpts:.1f}) "
                  f"| net-vs: {sstr} | buffer {len(buffer)}", flush=True)
        else:
            if pool is not None:
                export_npz(best, work_best)   # snapshot current best for the CPU workers
                (feats, pis, zs), st = selfplay.run_games_parallel(
                    pool, args.workers, work_best, args.games, n_sims=args.sims,
                    worker_parallel=args.worker_parallel,
                    temperature=args.temperature, temp_moves=args.temp_moves,
                    dirichlet_eps=args.dirichlet_eps, reward_shaping=args.reward_shaping,
                    shaping_scale=args.shaping_scale, shaping_mode=args.shaping_mode,
                    seed=1000 + it)
            else:
                evaluate = make_evaluator(best, args.device)
                (feats, pis, zs), st = selfplay.run_games(
                    args.games, evaluate, n_sims=args.sims, max_parallel=args.parallel,
                    temperature=args.temperature, temp_moves=args.temp_moves,
                    dirichlet_eps=args.dirichlet_eps, reward_shaping=args.reward_shaping,
                    shaping_scale=args.shaping_scale, shaping_mode=args.shaping_mode,
                    seed=1000 + it)
            for k in range(len(zs)):
                buffer.append((feats[k], pis[k], zs[k]))
            print(f"[iter {it}] selfplay: {st['games']} games, {len(zs)} positions, "
                  f"avg {st['avg_plies']:.1f} plies, winpts {st['avg_winpts']:.1f} "
                  f"(combined {st['avg_points']:.1f}), {st['secs']:.0f}s "
                  f"({st['games']/st['secs']:.2f} games/s) | buffer {len(buffer)}", flush=True)

        candidate = copy.deepcopy(best)
        p_l, v_l = _train_candidate(candidate, buffer, args.train_steps,
                                    args.batch_size, args.lr, args.device)
        print(f"[iter {it}] train: policy_loss {p_l:.3f} value_loss {v_l:.3f}", flush=True)

        if args.curriculum:
            export_npz(candidate, work_cand)
            export_npz(best, work_best)
            cand_s, best_s = _curriculum_gate(
                pool, league, args, work_cand, work_best, curr_p, it)
            promoted = cand_s >= best_s
            # Adapt difficulty from the GREEDY gate score of whichever net is now
            # best (cleaner signal than the exploratory generation win rate).
            ability = cand_s if promoted else best_s
            new_p = curr_p
            if ability >= args.curr_target + 0.05:
                new_p = min(1.0, curr_p + args.curr_step)
            elif ability <= args.curr_target - 0.10:
                new_p = max(0.0, curr_p - args.curr_step)
            gate_msg = (f"gate(curr p={curr_p:.2f}->{new_p:.2f}): "
                        f"cand {cand_s:.3f} vs best {best_s:.3f}")
            curr_p = new_p
        elif args.league:
            export_npz(candidate, work_cand)
            export_npz(best, work_best)
            cand_s, best_s, cand_scores = _league_gate(
                pool, league, args, work_cand, work_best, it)
            promoted = cand_s >= best_s
            sstr = " ".join(f"{k} {v:.2f}" for k, v in sorted(cand_scores.items()))
            gate_msg = f"gate(league): cand {cand_s:.3f} vs best {best_s:.3f} [{sstr}]"
        elif pool is not None:
            export_npz(candidate, work_cand)
            export_npz(best, work_best)
            _, gate = selfplay.run_games_parallel(
                pool, args.workers, work_cand, args.gate_games, npz_b=work_best,
                n_sims=args.gate_sims, worker_parallel=args.worker_parallel,
                add_noise=False, temperature=0.0, record=False, seed=9000 + it)
            promoted = gate["score_a"] >= args.gate_threshold
            gate_msg = f"gate: candidate {gate['score_a']:.3f} vs best ({gate['games']} games)"
        else:
            _, gate = selfplay.run_games(
                args.gate_games, make_evaluator(candidate, args.device),
                make_evaluator(best, args.device), n_sims=args.gate_sims,
                max_parallel=args.gate_games, add_noise=False, temperature=0.0,
                record=False, seed=9000 + it)
            promoted = gate["score_a"] >= args.gate_threshold
            gate_msg = f"gate: candidate {gate['score_a']:.3f} vs best ({gate['games']} games)"

        if promoted:
            best = candidate
            promotions += 1
            torch.save({"best": best.state_dict(), "iter": it,
                        "promotions": promotions, "curr_p": curr_p}, best_path)
            export_npz(best, npz_path)
            if args.league:
                snap = os.path.join(pool_dir, f"az_iter{it}.npz")
                export_npz(best, snap)
                pool_files.append(snap)
                if len(pool_files) > args.pool_size:
                    pool_files = pool_files[-args.pool_size:]
        print(f"[iter {it}] {gate_msg} -> {'PROMOTED' if promoted else 'rejected'} "
              f"| total {time.time()-t0:.0f}s", flush=True)

        torch.save({"best": best.state_dict(), "iter": it,
                    "promotions": promotions, "curr_p": curr_p}, last_path)
        with open(buf_path, "wb") as f:
            pickle.dump(buffer, f)

    if pool is not None:
        pool.close()
        pool.join()
    print(f"[train_az] done: {promotions} promotions", flush=True)


if __name__ == "__main__":
    main()
