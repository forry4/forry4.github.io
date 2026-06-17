"""Joint GRID search over the three take_value COST weights (W_TEMPO, W_GEM, W_GOLD).

The autotuner does coordinate descent (one knob at a time) and can miss joint optima -- these three
all sit in the SAME denominator (1 + W_TEMPO*tempo + W_GEM*gem + W_GOLD*gold), so both their ratios
AND their absolute scale (vs the +1 and the unscaled-points numerator) matter. This sweeps the full
product grid vs H2 on a tuning seed (CRN -- same boards across combos), then CONFIRMS the top few on
a FRESH DISJOINT seed vs BOTH H2 and H (the guard against the documented W_TEMPO/W_GEM seed-overfit).

Baseline = the current committed H3 (reserve finisher ON). Reuses h3_autotune's parallel score().
Never edits source. Run:  python -m games.spender.ai.az.h3_cost_grid --screen-n 1500 --confirm-n 5000
"""
from __future__ import annotations

import argparse
import multiprocessing as mp

from . import h3_autotune as AT

W_TEMPO_GRID = [0.1, 0.2, 0.3, 0.4, 0.5]
W_GEM_GRID = [0.1, 0.2, 0.3, 0.4]
W_GOLD_GRID = [0.2, 0.3, 0.4, 0.5, 0.6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen-n", type=int, default=1500)
    ap.add_argument("--confirm-n", type=int, default=5000)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--screen-seed", type=int, default=2000)
    ap.add_argument("--confirm-seed-h2", type=int, default=6_000_000)
    ap.add_argument("--confirm-seed-h", type=int, default=6_200_000)
    ap.add_argument("--h-floor", type=float, default=0.69)
    args = ap.parse_args()

    AT._WORKERS = max(1, args.workers)
    if AT._WORKERS > 1:
        AT._POOL = mp.Pool(processes=AT._WORKERS)

    base = AT.read_current()
    combos = [(t, g, ld) for t in W_TEMPO_GRID for g in W_GEM_GRID for ld in W_GOLD_GRID]
    print(f"[grid] {len(combos)} combos  screen N={args.screen_n} seed={args.screen_seed}  "
          f"(baseline W_TEMPO={base['W_TEMPO']} W_GEM={base['W_GEM']} W_GOLD={base['W_GOLD']}, "
          f"reserve={base.get('USE_FINISH_RESERVE')})", flush=True)

    # ── screen every combo vs H2 (CRN) ──
    scored = []
    for i, (t, g, ld) in enumerate(combos):
        cfg = {**base, "W_TEMPO": t, "W_GEM": g, "W_GOLD": ld}
        s2 = AT.score(cfg, "H2", args.screen_n, args.screen_seed)
        scored.append((s2, t, g, ld))
        if (i + 1) % 10 == 0:
            print(f"  ...screened {i + 1}/{len(combos)}", flush=True)
    scored.sort(reverse=True)

    base_screen = AT.score(base, "H2", args.screen_n, args.screen_seed)
    print(f"\n[grid] baseline ({base['W_TEMPO']}/{base['W_GEM']}/{base['W_GOLD']}) "
          f"screen vs H2 = {base_screen:.4f}")
    print(f"[grid] top {args.top} combos by screen vs H2:")
    for s2, t, g, ld in scored[:args.top]:
        print(f"   W_TEMPO={t} W_GEM={g} W_GOLD={ld}: screen vs H2 {s2:.4f}", flush=True)

    # ── confirm top combos (+ baseline reference) on FRESH disjoint seeds vs BOTH H2 and H ──
    print(f"\n[grid] CONFIRM on fresh seeds H2={args.confirm_seed_h2} H={args.confirm_seed_h} "
          f"N={args.confirm_n}:", flush=True)
    rows = [("baseline", base["W_TEMPO"], base["W_GEM"], base["W_GOLD"])]
    rows += [(f"#{i + 1}", t, g, ld) for i, (_s, t, g, ld) in enumerate(scored[:args.top])]
    for name, t, g, ld in rows:
        cfg = {**base, "W_TEMPO": t, "W_GEM": g, "W_GOLD": ld}
        h2 = AT.score(cfg, "H2", args.confirm_n, args.confirm_seed_h2)
        h = AT.score(cfg, "H", args.confirm_n, args.confirm_seed_h)
        flag = "" if h >= args.h_floor else "  <-- vs-H BELOW FLOOR"
        print(f"   {name:<9} W_TEMPO={t} W_GEM={g} W_GOLD={ld}: "
              f"vs H2 {h2:.4f}  vs H {h:.4f}{flag}", flush=True)

    if AT._POOL is not None:
        AT._POOL.close()
        AT._POOL.join()


if __name__ == "__main__":
    main()
