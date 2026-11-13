"""Retired Spender AI variants that must still SERVE.

The lobby offers four personas — H2 (Henry), H3 (Herald), S (Steve), N (Nina).
Everything else is retired: no UI can create a game with it. But retired is not
dead, and this module exists because of exactly that distinction:

    `ai_variant` is PERSISTED with the game and restored on load.

A game created months ago against variant Z or H is still resumable, and dropping
its chooser would downgrade or break that game on the next AI turn. So these
cannot be deleted, and they cannot move to `ai/offline/` either — that package is
never imported by the server, which is the whole point of it. They belong here:
in the serving stack, but out of `main.py`, which was carrying the deployed rules,
every DB query, the room server, AND the retired brains in one 3,400-line module.

WHAT'S HERE
  Z  — the AlphaZero net (PUCT + numpy inference, no torch in prod), loaded on
       first use by `az_evaluator()`. Enabled only when ai/models/az_model.npz is
       present; absent, the evaluator stays None and
       `_ai_variant_valid` rejects "Z", so a fresh game can never select it.
  H  — the v4 valuation heuristic: 1-ply greedy argmax over the shared card model,
       no search. Plus its card-value transparency overlay.

Weight variants A/B/C/C2 are also retired but are pure DATA (weights*.json) fed to
the still-live `_mcts_choose_move`, so there is no code to move for them.

Behaviour here is byte-identical to what main.py ran before the move.
"""
from __future__ import annotations

import logging
import os
import random
import threading
import time

LOG = logging.getLogger("games.spender")

_MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")

# ─── Variant Z — AlphaZero net ───────────────────────────────────────────────

AZ_MODEL_PATH = os.environ.get("SPENDER_AZ_MODEL") or os.path.join(_MODELS_DIR, "az_model.npz")
AZ_EVALUATE = None

# LOADED ON FIRST USE, not at import. Z is retired: only an old saved game against
# it ever asks, and loading it at boot pulled numpy in (the only thing at import
# that did) plus the .npz, on every Render cold start. `az_evaluator()` is the one
# way in; `_AZ_TRIED` makes a missing or broken model cost one attempt, not one per
# call. Threaded: the AI runs in a thread pool, so two first calls can race.
_AZ_LOCK = threading.Lock()
_AZ_TRIED = False


def az_evaluator():
    """The variant-Z evaluator, loading it on the first call; None when absent."""
    if AZ_EVALUATE is None and not _AZ_TRIED:
        with _AZ_LOCK:
            if not _AZ_TRIED:
                load_az_model()
    return AZ_EVALUATE


def load_az_model() -> None:
    """Load the exported AZ net for variant Z. Never raises."""
    global AZ_EVALUATE, _AZ_TRIED
    _AZ_TRIED = True
    AZ_EVALUATE = None
    if os.environ.get("SPENDER_AZ_MODEL") == "none":
        return
    try:
        if os.path.exists(AZ_MODEL_PATH):
            from games.spender.ai.serving.infer_np import load_evaluator
            AZ_EVALUATE = load_evaluator(AZ_MODEL_PATH)
            LOG.info("loaded AZ model from %s (AI variant Z enabled)", AZ_MODEL_PATH)
    except Exception as e:
        LOG.warning("could not load AZ model from %s: %s", AZ_MODEL_PATH, e)


def az_choose_move(game: dict, ai_pid: str, time_limit: float = 5.0) -> dict:
    """Variant-Z move selection: time-budgeted PUCT over the fast az engine.
    Returns an incumbent dict-move; post-move discard/noble sub-decisions are
    resolved by _run_ai_turn's heuristics, same as the other variants."""
    from games.spender.ai.serving import actions as _aza
    from games.spender.ai.serving import engine as _aze
    from games.spender.ai.serving.mcts import Search

    s = _aze.from_game_dict(game)
    legal = _aze.legal_actions(s)
    if len(legal) == 1:
        return _aza.action_to_move(s, legal[0])
    evaluate = az_evaluator()
    search = Search(s, random.Random(), add_noise=False)
    deadline = time.time() + time_limit
    while time.time() < deadline:
        for _ in range(32):  # check the clock every 32 simulations
            req = search.leaf_batch()
            if req is None:
                continue
            feats, mask = req
            p, v = evaluate(feats[None, :], mask[None, :])
            search.apply_evals(p[0], float(v[0]))
    visits = search.root.N
    return _aza.action_to_move(s, max(range(len(visits)), key=visits.__getitem__))


# ─── Variant H — the v4 valuation heuristic ──────────────────────────────────

def v4_choose_move(game: dict, ai_pid: str) -> dict:
    """Variant-H move selection: the v4 valuation heuristic — a 1-ply greedy
    argmax over the shared card-valuation model (no search). Returns an
    incumbent dict-move; post-move discard/noble sub-decisions are resolved by
    _run_ai_turn, same as the other variants. Fast (no model file, no MCTS)."""
    from games.spender.ai.serving import actions as _aza
    from games.spender.ai.serving import engine as _aze
    from games.spender.ai.serving import heuristic as _azh

    s = _aze.from_game_dict(game)
    a = _azh.choose_action(s, s.turn)
    return _aza.action_to_move(s, a)


def v4_card_values(game: dict, seat_pid: str) -> dict:
    """The v4 heuristic's card_value for every visible board card + that seat's own
    reserved cards, from seat_pid's perspective (whoever's turn it is) — a transparency
    overlay for variant-H games (so a human can see what each card is worth to the player
    on the move: their own values on their turn, the bot's on its turn). Keyed by card id
    (CARD_NAME[ci]) so the frontend can show it per card. Cheap; recomputed per
    broadcast. Wrapped by callers in try/except so it can never break a room update."""
    from games.spender.ai.serving import engine as _aze
    from games.spender.ai.serving import valuation as _azv
    from games.spender.ai.serving import heuristic as _azh

    try:
        seat = game["order"].index(seat_pid)
    except (KeyError, ValueError):
        return {}
    s = _aze.from_game_dict(game)
    val = _azv.Valuation(s)
    out: dict[str, float] = {}
    for slot in range(12):
        ci = s.board[slot]
        if ci >= 0:
            out[_aze.CARD_NAME[ci]] = round(_azh.card_value(val, s, ci, seat), 1)
    for ci in s.reserved[seat]:
        out[_aze.CARD_NAME[ci]] = round(_azh.card_value(val, s, ci, seat), 1)
    return out


# variant Z loads on first use: see az_evaluator().
