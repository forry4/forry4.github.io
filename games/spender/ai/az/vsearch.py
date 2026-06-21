"""vsearch.py — variant "S": determinized PUCT search with a V(state) leaf + an H3 policy prior.

Gives the strong static evaluator (`v_state.value`) LOOKAHEAD — the project's documented #1 remaining
lever. Reuses `az/mcts.Search` UNCHANGED for the hard parts (ISMCTS determinization of hidden info;
correct non-alternating-turn backups), via its new `leaf_state=True` mode which hands the leaf State
to our evaluator instead of packing 305 net features.

Two probe findings shaped this:
  * a static value-leaf beats a rollout leaf (H3L static 0.58 panel vs rollout 0.28) AND is far
    faster — so the leaf VALUE is `v_state.value_with`, never a playout;
  * a single-sample determinization (h3_lookahead) is noisy — PUCT AVERAGES the leaf over many
    determinized sims, which is the fix.

The leaf needs a POLICY too (mcts PUCT priors). v_state has no policy head, so we supply a heuristic
prior: a softmax over per-action H3 scores (buys/reserves by `take_value`, takes by need-vector
alignment). One `Valuation` is built per leaf and SHARED between the value and the policy.

Contract mirrors the H-family: ``choose_action(s, seat) -> legal action index``; ``card_values`` for
the admin overlay.
"""
from __future__ import annotations

import logging
import math
import random
import time

import numpy as np

_LOG = logging.getLogger("games.spender")   # share the prod log stream (Render captures it)

from . import distill_features as DF
from . import engine as E
from . import heuristic3 as H3
from . import v_state
from . import valuation3 as V
from .mcts import Search

# ─── tunables (the autotuner sweeps these on the panel-average objective) ─────────────────────
SIMS = 200            # MCTS simulations per PLAY decision (serving uses a wall-clock budget instead)
C_PUCT = 1.5          # PUCT exploration constant; maximin-tuned (was 2.0)
BACKUP_LAMBDA = 0.0   # mixmax selection-Q blend (0 = pure averaging, byte-identical). TESTED & REJECTED
                      # (see mcts.Search.backup_lambda): monotonic degradation vs frozen-S; parked off.
POLICY_TEMP = 0.7     # softmax temperature on the H3 action-score prior (lower = sharper toward H3)
RESERVE_PRIOR_W = 0.5 # reserve actions get this fraction of the card's take_value as their prior score
TAKE_PRIOR_W = 1.0    # scale on the (normalized) need-vector alignment score for take actions
PRIOR_UNIFORM = 0.0   # mix this much uniform mass into the prior: P=(1-u)*softmax + u/n. A real
                      # exploration floor. Default 0 = byte-identical.
                      # TESTED & REJECTED (June 2026, do not relitigate): self-gate vs frozen-S at
                      # sims=200 — PRIOR_UNIFORM 0.1/0.25 screened 0.546/0.538 but 0.1 fell to 0.494 on
                      # FRESH disjoint seeds (regression to mean); POLICY_TEMP=1.0 was 0.496; panel a
                      # slight wash. No gain because mcts._select's _EPS_PRIOR floor + PUCT's sqrt(N)
                      # term ALREADY visit every legal move — dark moves aren't starved, just correctly
                      # not preferred at this search depth. The lever is depth/eval, not breadth.
H3_PICK_W = 1.5       # prior bonus on H3's own greedy choice (PUCT expands it first; 0 disables)
SERVE_TIME = 4.5      # serving wall-clock budget (s); leaves margin under the 5s thread-pool slot
SERVE_MIN_SIMS = 32   # always run at least this many sims before the clock may stop the search
SERVE_MAX_SIMS = 6000 # hard cap so a fast box can't spin unboundedly inside the budget

# ─── endgame deeper search (Gap B) ───────────────────────────────────────────────────────────
# The decisive finish (final round / near-win) is a small, short tree — the cheapest place to search
# deeper, and where reaching real terminals matters most (terminals are exactly tiebreak-aware). Spend
# more there: offline a sim MULTIPLIER, serving a (longer) endgame wall-clock budget. Defaults = no-op.
ENDGAME_NEAR = 3          # "endgame" = final round triggered OR a seat within this many pts of the win
ENDGAME_SIM_MULT = 1.0    # multiply the (offline/fixed) sim budget for an endgame root. 1 = byte-identical
ENDGAME_SERVE_TIME = 4.5  # serving wall-clock for endgame moves (>= SERVE_TIME). == SERVE_TIME = no change


def _is_endgame(s: E.State) -> bool:
    """True once the game is in its decisive finish: the final round has triggered, or either seat is
    within ENDGAME_NEAR points of the win threshold (so the next buy could trigger it)."""
    return s.final_trigger >= 0 or max(s.points[0], s.points[1]) >= s.win_points - ENDGAME_NEAR

_RNG = random.Random(0x5EA5C4)   # determinization shuffle (process-local; advanced across calls)

# ─── leaf-evaluator swap (experiment): "vstate" = the deployed v_state V(state); "distill" = the
# ridge-on-enriched-features model distilled toward V_search (leaf_model.npz). Tests whether a
# SHARPER static leaf -> stronger S at equal sims. Default "vstate" = byte-identical to production.
LEAF_MODE = "vstate"
_LEAF_MODEL = None


def _load_leaf_model():
    global _LEAF_MODEL
    if _LEAF_MODEL is None:
        import os
        d = np.load(os.path.join(os.path.dirname(__file__), "leaf_model.npz"))
        _LEAF_MODEL = (d["w"].astype(np.float64), d["mu"].astype(np.float64), d["sd"].astype(np.float64))
    return _LEAF_MODEL


def _distill_value(leaf_s) -> float:
    """Distilled-leaf value for the player to move at leaf_s, clipped to [-1, 1] (the MCTS range)."""
    w, mu, sd = _load_leaf_model()
    f = DF.feat_enriched(leaf_s, leaf_s.turn).astype(np.float64)
    pred = ((f - mu) / sd) @ w[:-1] + w[-1]
    return -1.0 if pred < -1.0 else (1.0 if pred > 1.0 else float(pred))


def _card_for_action(s, seat: int, a: int) -> int:
    """Card id a buy/reserve-from-board action targets, or -1 (deck reserve / non-card action)."""
    if E.A_BUY_BOARD <= a < E.A_BUY_BOARD + 12:
        return s.board[a - E.A_BUY_BOARD]
    if E.A_BUY_RESV <= a < E.A_BUY_RESV + 3:
        ri = a - E.A_BUY_RESV
        return s.reserved[seat][ri] if ri < len(s.reserved[seat]) else -1
    if E.A_RES_BOARD <= a < E.A_RES_BOARD + 12:
        return s.board[a - E.A_RES_BOARD]
    return -1


def _action_scores(val: V.Valuation, s, seat: int, legal) -> dict:
    """Heuristic score per legal action (pre-softmax), all on a COMPARABLE scale so no class
    dominates the prior: buys by take_value (~1-3), reserves at a discount, takes by their colors'
    share of the top targets' demand (NORMALIZED to ~[0,1] — the raw need-vector sums ran ~5-45 and
    swamped buys, collapsing the prior onto 'always take gems'), everything else the base floor.
    H3's own greedy pick gets a bonus so PUCT expands it first (the policy-improvement anchor)."""
    targets = H3._targets(val, s, seat)
    need = H3._need_vector(s, seat, targets)
    need_tot = sum(need) or 1.0
    scores = {}
    for a in legal:
        if E.A_BUY_BOARD <= a < E.A_BUY_RESV + 3:                 # buys (board + reserved)
            ci = _card_for_action(s, seat, a)
            scores[a] = H3.take_value(val, ci, seat) if ci >= 0 else 0.0
        elif E.A_RES_BOARD <= a < E.A_RES_DECK + 3:               # reserves (board + deck)
            ci = _card_for_action(s, seat, a)
            tv = H3.take_value(val, ci, seat) if ci >= 0 else 0.0
            scores[a] = RESERVE_PRIOR_W * tv
        elif E.A_TAKE3 <= a < E.A_PASS:                           # gem takes (normalized demand)
            colors = H3._take_colors(a)
            scores[a] = TAKE_PRIOR_W * (sum(need[c] for c in colors) / need_tot if colors else 0.0)
        else:                                                     # pass / discard / noble
            scores[a] = 0.0
    if H3_PICK_W > 0.0:                                           # policy-improvement anchor on H3's move
        a_star = H3.choose_action(s, seat, val=val)               # reuse the leaf's val (no 2nd build; warm cache)
        if a_star in scores:
            scores[a_star] += H3_PICK_W
    return scores


def _policy_prior(val: V.Valuation, s, seat: int, legal) -> np.ndarray:
    """Softmax of `_action_scores` over the legal actions -> prior probs [N_ACTIONS] (0 on illegal)."""
    probs = np.zeros(E.N_ACTIONS, dtype=np.float64)
    if not legal:
        return probs
    scores = _action_scores(val, s, seat, legal)
    mx = max(scores[a] for a in legal)
    tot = 0.0
    for a in legal:
        e = math.exp((scores[a] - mx) / POLICY_TEMP)
        probs[a] = e
        tot += e
    if tot > 0.0:
        probs /= tot
    if PRIOR_UNIFORM > 0.0:                       # mix in uniform mass over legal moves (real floor)
        u = PRIOR_UNIFORM / len(legal)
        keep = 1.0 - PRIOR_UNIFORM
        for a in legal:
            probs[a] = keep * probs[a] + u
    return probs


def _expand(search) -> None:
    """Run one simulation: select a leaf, evaluate it (V leaf + H3 policy prior), back up. A None
    leaf means the sim hit a terminal and was already backed up internally — nothing more to do.
    One Valuation is built per leaf and SHARED between the value and the policy prior."""
    req = search.leaf_batch()
    if req is None:
        return
    leaf_s, mask = req
    legal = [a for a in range(E.N_ACTIONS) if mask[a]]
    val = V.Valuation(leaf_s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    value = _distill_value(leaf_s) if LEAF_MODE == "distill" else v_state.value_with(val, leaf_s.turn)
    probs = _policy_prior(val, leaf_s, leaf_s.turn, legal)
    search.apply_evals(probs, value)


def _run_search(s, seat: int, sims: int):
    """Fixed-iteration search (offline A/B + tuning). Returns root visit counts."""
    search = Search(s, _RNG, c_puct=C_PUCT, add_noise=False, leaf_state=True,
                    backup_lambda=BACKUP_LAMBDA)
    for _ in range(sims):
        _expand(search)
    return search.root.N


def _run_search_timed(s, seat: int, time_limit: float):
    """Wall-clock-budgeted search (serving): sims until the deadline, with a min floor + hard cap."""
    search = Search(s, _RNG, c_puct=C_PUCT, add_noise=False, leaf_state=True,
                    backup_lambda=BACKUP_LAMBDA)
    t0 = time.time()
    deadline = t0 + time_limit
    done = 0
    while done < SERVE_MAX_SIMS:
        _expand(search)
        done += 1
        if done >= SERVE_MIN_SIMS and time.time() >= deadline:
            break
    dt = time.time() - t0
    # diagnostic: how much search did this serving decision actually get? On a fast box ~thousands; on
    # Render's free shared CPU likely far fewer (the suspected cause of weak deployed play). One line/move.
    _LOG.info("[S] serving search: %d sims in %.2fs (%.0f sims/s; budget %.1fs, cap %d)",
              done, dt, done / dt if dt > 0 else 0.0, time_limit, SERVE_MAX_SIMS)
    return search.root.N


def choose_action(s: E.State, seat: int | None = None, *, sims: int | None = None,
                  time_limit: float | None = None) -> int:
    """Return a legal engine action index for `seat` (defaults to side to move).

    PLAY decisions are searched (determinized PUCT, V leaf). DISCARD/NOBLE sub-decisions defer to
    greedy H3 — they are minor and forced-ish, and H3 already resolves them well (the search still
    plays through them INTERNALLY at every node via the engine, so lines are evaluated correctly).

    Pass `time_limit` (serving) for a wall-clock budget, else `sims` (offline) for fixed iterations."""
    if seat is None:
        seat = s.turn
    legal = E.legal_actions(s)
    if not legal:
        return E.A_PASS
    if s.phase != E.PLAY or len(legal) == 1:
        return H3.choose_action(s, seat)
    if time_limit is not None:
        if ENDGAME_SERVE_TIME > time_limit and _is_endgame(s):   # spend longer on the decisive finish
            time_limit = ENDGAME_SERVE_TIME
        visits = _run_search_timed(s, seat, time_limit)
    else:
        n = SIMS if sims is None else sims
        if ENDGAME_SIM_MULT != 1.0 and _is_endgame(s):           # deeper offline search in the endgame
            n = int(round(n * ENDGAME_SIM_MULT))
        visits = _run_search(s, seat, n)
    return max(legal, key=lambda a: visits[a])


def card_values(s: E.State, seat: int | None = None) -> dict:
    """Admin-overlay per-card components, delegating to H3 (the variant's eval basis). Keyed by board
    slot and reserved index; each value is H3's (take, engine, point, cost). Plus the position value."""
    if seat is None:
        seat = s.turn
    val = V.Valuation(s, H3.W_TEMPO, H3.W_GEM, H3.W_GOLD)
    out = {"position_value": v_state.value(s, seat)}
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            t, e, p, c = H3.components(val, ci, seat)
            out[f"board:{slot}"] = {"t": t, "e": e, "p": p, "c": c}
    for ri, ci in enumerate(s.reserved[seat]):
        t, e, p, c = H3.components(val, ci, seat)
        out[f"resv:{ri}"] = {"t": t, "e": e, "p": p, "c": c}
    return out
