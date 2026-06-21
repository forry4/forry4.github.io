"""Three v4 playstyles for league diversity: balanced / points-rusher / engine-builder.

Same strong v4 valuation core, three weight presets that shift STYLE (not strength
-- re-weighting is saturated for win rate but changes behavior a lot). Goal: give
the net diverse-but-competent sparring partners and break single-strategy collapse.

Measures three things:
  1. COMPETENCE  -- each preset's win rate vs the greedy A/B/C/C2 mix (>=~0.55 ok).
  2. DISTINCTNESS -- behavioral stats per preset (final points, cards bought, nobles
     won, reserves made, and buy mix: point-cards PTS>=3 vs engine-cards PTS==0).
  3. INTERACTION -- head-to-head 3x3 win matrix (non-transitivity = real diversity).

Presets are applied to H's module globals per-mover (single-threaded per worker, so
two presets can play each other in one game). ASCII output. Touches nothing deployed.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import random
from concurrent.futures import ProcessPoolExecutor

OPP_NAMES = ["A", "B", "C", "C2"]

# full set of style knobs so a preset fully defines behavior (no leakage on swap)
PRESETS = {
    "balanced": dict(W_POINTS=2.0, W_EFFICIENCY=5.0, W_ENGINE=1.0, W_NOBLE=3.0,
                     BUY_FLOOR=0.5, PTS_STAGE_GAIN=0.5, ENG_STAGE_DECAY=0.7,
                     ENG_DECAY_RATE=0.5, W_TEMPO=0.3),
    "points":   dict(W_POINTS=3.0, W_EFFICIENCY=7.0, W_ENGINE=0.9, W_NOBLE=0.7,
                     BUY_FLOOR=0.5, PTS_STAGE_GAIN=0.9, ENG_STAGE_DECAY=0.85,
                     ENG_DECAY_RATE=0.7, W_TEMPO=0.3),
    "engine":   dict(W_POINTS=1.3, W_EFFICIENCY=3.5, W_ENGINE=2.0, W_NOBLE=5.5,
                     BUY_FLOOR=0.2, PTS_STAGE_GAIN=0.25, ENG_STAGE_DECAY=0.4,
                     ENG_DECAY_RATE=0.3, W_TEMPO=0.3),
}


def _apply(H, preset):
    for k, v in preset.items():
        setattr(H, k, v)
    H.USE_NOBLE_COMPLETION = True


def _classify(s, a, mover, E):
    """Return 'pt'/'eng'/'mid' for a buy, 'res' for a reserve, else None.
    Read the card BEFORE the move is applied."""
    if E.A_BUY_BOARD <= a < E.A_BUY_RESV:
        ci = s.board[a - E.A_BUY_BOARD]
    elif E.A_BUY_RESV <= a < E.A_DISCARD:
        idx = a - E.A_BUY_RESV
        ci = s.reserved[mover][idx] if idx < len(s.reserved[mover]) else -1
    elif E.A_RES_BOARD <= a < E.A_BUY_BOARD:
        return "res"
    else:
        return None
    if ci < 0:
        return None
    p = E.PTS[ci]
    return "pt" if p >= 3 else ("eng" if p == 0 else "mid")


def vs_mix_job(job):
    name, seeds = job
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    from games.spender.ai.az.arena import _heuristic_action, _load_opp_weights
    inc.USE_VALUE_LEAF = False
    opps = {n: _load_opp_weights(n) for n in OPP_NAMES}
    preset = PRESETS[name]
    w = d = 0
    st = dict(pts=0, opp_pts=0, cards=0, nobles=0, res=0, b_pt=0, b_eng=0, b_mid=0, n=0)
    for g in seeds:
        random.seed(g * 7919 + 13)
        on = OPP_NAMES[g % len(OPP_NAMES)]
        s = E.new_game(random.Random(g))
        me = g % 2
        while s.phase != E.OVER and s.ply < 400:
            if s.turn == me:
                _apply(H, preset)
                a = H.choose_action(s, s.turn)
                cl = _classify(s, a, me, E)
                if cl == "res":
                    st["res"] += 1
                elif cl == "pt":
                    st["b_pt"] += 1
                elif cl == "eng":
                    st["b_eng"] += 1
                elif cl == "mid":
                    st["b_mid"] += 1
            else:
                a = _heuristic_action(s, opps[on], 1)
            E.apply(s, a)
        st["pts"] += s.points[me]
        st["opp_pts"] += s.points[1 - me]
        st["cards"] += s.purchased_n[me]
        st["nobles"] += len(s.nobles_won[me])
        st["n"] += 1
        if s.winner == me:
            w += 1
        elif s.winner == E.WIN_DRAW:
            d += 1
    return ("mix", name, (w + 0.5 * d), len(seeds), st)


def h2h_job(job):
    a_name, b_name, seeds = job
    from games.spender import main as inc
    from games.spender.ai.az import engine as E
    from games.spender.ai.az import heuristic as H
    inc.USE_VALUE_LEAF = False
    pa, pb = PRESETS[a_name], PRESETS[b_name]
    w = d = 0
    for g in seeds:
        random.seed(g * 7919 + 13)
        s = E.new_game(random.Random(g))
        a_side = g % 2
        while s.phase != E.OVER and s.ply < 400:
            _apply(H, pa if s.turn == a_side else pb)
            a = H.choose_action(s, s.turn)
            E.apply(s, a)
        if s.winner == a_side:
            w += 1
        elif s.winner == E.WIN_DRAW:
            d += 1
    return ("h2h", a_name, b_name, (w + 0.5 * d), len(seeds))


if __name__ == "__main__":
    MIX_SEEDS = list(range(30000, 30200))       # 200 vs-mix games / preset
    H2H_SEEDS = list(range(31000, 31100))       # 100 games / ordered pair
    NSH = 8
    msh = [MIX_SEEDS[i::NSH] for i in range(NSH)]
    hsh = [H2H_SEEDS[i::NSH] for i in range(NSH)]

    jobs = [(n, sh) for n in PRESETS for sh in msh]
    h2h_jobs = [(a, b, sh) for a in PRESETS for b in PRESETS if a != b for sh in hsh]

    mix = {n: [0.0, 0, {}] for n in PRESETS}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for _t, name, sc, n, st in ex.map(vs_mix_job, jobs):
            mix[name][0] += sc
            mix[name][1] += n
            for k, v in st.items():
                mix[name][2][k] = mix[name][2].get(k, 0) + v

    print("=== COMPETENCE + STYLE (vs greedy A/B/C/C2 mix, 200 games each) ===",
          flush=True)
    print(f"  {'preset':9s} {'win':>5s}  {'pts':>5s} {'oppP':>5s} {'cards':>5s} "
          f"{'nobl':>5s} {'resv':>5s}  {'buy% pt/eng/mid':>16s}", flush=True)
    for name in PRESETS:
        sc, n, st = mix[name]
        g = st["n"]
        tb = st["b_pt"] + st["b_eng"] + st["b_mid"] or 1
        print(f"  {name:9s} {sc/n:.3f}  {st['pts']/g:5.1f} {st['opp_pts']/g:5.1f} "
              f"{st['cards']/g:5.1f} {st['nobles']/g:5.2f} {st['res']/g:5.2f}  "
              f"{100*st['b_pt']/tb:4.0f}/{100*st['b_eng']/tb:3.0f}/"
              f"{100*st['b_mid']/tb:3.0f}", flush=True)

    h2h = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for _t, a, b, sc, n in ex.map(h2h_job, h2h_jobs):
            k = (a, b)
            s0, n0 = h2h.get(k, (0.0, 0))
            h2h[k] = (s0 + sc, n0 + n)

    print("\n=== HEAD-TO-HEAD (row vs col win rate; non-transitivity = diversity) ===",
          flush=True)
    names = list(PRESETS)
    print("           " + "  ".join(f"{c:>8s}" for c in names), flush=True)
    for a in names:
        row = f"  {a:9s}"
        for b in names:
            if a == b:
                row += f"  {'-':>8s}"
            else:
                sc, n = h2h[(a, b)]
                row += f"  {sc/n:8.3f}"
        print(row, flush=True)
