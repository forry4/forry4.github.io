"""Strong opponent for Castles of Crimson — determinized MCTS (Normal / Hard).

The trivial ``bot.py`` plays random legal moves; this module plays a real game via
Monte-Carlo Tree Search with a heuristic leaf evaluation. It reuses the engine's
``legal_moves``/``apply_move``/``final_scores`` contract and never imports any web
or training dependency (pure Python, deterministic given an explicit ``rng``).

Key facts that shape the design:
  * CoC has very limited interaction (separate duchies; shared depots/track/dice),
    so a strong single-seat optimizer with a good position eval is most of the
    strength. MCTS adds the lookahead/tempo the static eval can't see.
  * The ONLY hidden information is the *undrawn* supply order + *future* dice rolls
    (both in ``game["supply"]``/``black_supply``/``goods_supply`` + ``rng_state``).
    Everything else — depots, both players' boards/storage/goods, current dice — is
    public. So determinization is just: per MCTS iteration, reshuffle the undrawn
    supply (canonicalized so the search can't depend on the hidden order) and reseed
    the future RNG. Depots/duchies are left TRUE (they are visible).
  * Strength lever = the leaf eval (Spender's hard-won lesson). Rollouts are short
    and end in ``_evaluate``; full random rollouts would be too noisy.

Public API:
  choose_move(game, pid, *, time_limit, max_iters, temperature, rng, rollout_depth) -> move
  play_turn_plan(game, pid, *, difficulty="hard", rng=None) -> [move, ...]
  DIFFICULTY  — per-level search budgets
"""
from __future__ import annotations

import math
import random
import time

from . import engine
from . import board
from . import tiles
from . import bot

PHASES = tiles.PHASES                      # ["A","B","C","D","E"]
_UCB_C = 1.4                               # exploration constant
_MAX_TREE_DEPTH = 8                        # plies kept in-tree before truncating to rollout
_SQUASH = 12.0                             # point-margin -> tanh reward scale

# Per-difficulty search budgets. time_limit/max_iters are PER decision point; a
# turn issues several decisions, so a turn costs roughly (#decisions x time_limit).
# temperature>0 makes the move a visit-count sample (beatable blunders).
DIFFICULTY = {
    "normal": {"time_limit": 0.25, "max_iters": 500,  "temperature": 0.6, "rollout_depth": 6},
    "hard":   {"time_limit": 0.55, "max_iters": 2000, "temperature": 0.0, "rollout_depth": 8},
}

# Heuristic eval weights (VP-ish units). Hand-tuned; tunable via ai_selfplay.
WEIGHTS = {
    "mine_future": 0.9,    # each placed mine ~ this much silver/worker per remaining phase
    "area_prox":   1.0,    # (filled/size)^2 * (AREA_SCORE + PHASE_BONUS) for partial regions
    "color_prox":  1.0,    # (filled/total)^2 * bonus-tile value for partial colors
    "storage":     0.35,   # small credit per stored tile (future placement)
    "mon_cont":    0.45,   # per continuous monastery effect, per remaining phase
    "empty_pen":   0.14,   # penalty per empty duchy space (completion + tiebreak)
}


# ── Fast state clone (tiles are immutable post-creation, so share them) ───────────
def _clone(node):
    """Generic structural copy that SHARES immutable tile dicts (used for small
    sub-structures like ``pending``). For whole games use ``_clone_game``."""
    if isinstance(node, dict):
        if node.get("kind") in ("hex", "goods"):
            return node
        return {k: _clone(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_clone(v) for v in node]
    return node


def _clone_game(g):
    """Explicit shallow clone of a game for search — copies every container the
    engine mutates while SHARING immutable tiles, the (wholesale-replaced)
    ``rng_state``, and dropping the move log. Sets ``_skip_undo`` so the engine
    won't deepcopy a turn-undo snapshot on every simulated turn. ~10x faster than
    a generic deepcopy and the dominant per-iteration cost, so it's worth the
    verbosity."""
    players = {}
    for pid, p in g["players"].items():
        players[pid] = {
            "name": p["name"], "board_id": p["board_id"], "castle_sid": p["castle_sid"],
            "duchy": dict(p["duchy"]),
            "storage": list(p["storage"]),
            "goods": dict(p["goods"]),
            "sold_goods": list(p["sold_goods"]),
            "workers": p["workers"], "silver": p["silver"], "vp": p["vp"],
            "claimed_bonus": [dict(b) for b in p["claimed_bonus"]],
            "mines_count": p["mines_count"],
            "buildings_placed": dict(p["buildings_placed"]),
            "livestock_types": list(p["livestock_types"]),
            "monastery_effects": list(p["monastery_effects"]),
            "town_buildings": {k: list(v) for k, v in p["town_buildings"].items()},
        }
    return {
        "num_players": g["num_players"], "phase_letter": g["phase_letter"],
        "round": g["round"], "round_in_game": g["round_in_game"], "phase": g["phase"],
        "winner": g["winner"], "order": list(g["order"]),
        "track": [list(s) for s in g["track"]], "round_order": list(g["round_order"]),
        "ship_advance_pending": g.get("ship_advance_pending", 0),
        "start_player": g["start_player"], "white_die": g["white_die"],
        "dice": {pid: {"values": list(dv["values"]), "used": list(dv["used"])}
                 for pid, dv in g["dice"].items()},
        "turn": g["turn"],
        "black_depot_used_this_turn": g["black_depot_used_this_turn"],
        "m6_used_this_turn": g["m6_used_this_turn"],
        "depots": {k: {"hexes": list(d["hexes"]), "goods": list(d["goods"])}
                   for k, d in g["depots"].items()},
        "black_depot": list(g["black_depot"]),
        "supply": list(g["supply"]), "black_supply": list(g["black_supply"]),
        "goods_supply": list(g["goods_supply"]), "goods_queue": list(g["goods_queue"]),
        "bonus_tiles": {col: list(v) for col, v in g["bonus_tiles"].items()},
        "players": players,
        "pending_pid": g["pending_pid"], "pending_kind": g["pending_kind"],
        "pending": _clone(g["pending"]) if g.get("pending") else None,
        "moves": [],
        "rng_state": g["rng_state"],     # shared; engine/_determinize REPLACE it wholesale
        "_skip_undo": True,
    }


def _actor(state):
    return state.get("pending_pid") or state.get("turn")


def _opponent(game, pid):
    for p in game["players"]:
        if p != pid:
            return p
    return pid


# ── Determinization: reshuffle only the UNDRAWN supply, reseed the future RNG ─────
def _determinize(state, rng):
    """Sample a plausible hidden future. Canonicalize (sort by tile id) before the
    shuffle so the result depends only on the *set* of undrawn tiles + ``rng`` —
    never on the hidden true order (this is what makes the AI provably fair)."""
    for key in ("supply", "black_supply", "goods_supply"):
        pool = state.get(key)
        if pool:
            pool.sort(key=lambda t: t["id"])
            rng.shuffle(pool)
    r = random.Random(rng.randrange(1 << 30))
    st = r.getstate()
    state["rng_state"] = [st[0], list(st[1]), st[2]]


# ── Legal-move helper: don't waste a die by ending early (matches the UI rule) ────
def _legal(state, pid):
    moves = engine.legal_moves(state, pid)
    d = state["dice"].get(pid)
    if d is not None and not (d["used"][0] and d["used"][1]):
        non_end = [m for m in moves if m.get("type") != "end_turn"]
        if non_end:
            return non_end
    return moves


# ── Heuristic position evaluation (the strength lever) ────────────────────────────
def _value(game, pid, w=WEIGHTS):
    """Estimate player ``pid``'s eventual score: realized 'score if game ended now'
    plus weighted potential (engine value not yet banked)."""
    p = game["players"][pid]
    b = board.get_board(p.get("board_id"))
    duchy = p["duchy"]

    base = (p["vp"] + sum(p["goods"].values()) + p["silver"] + p["workers"] // 2
            + engine._endgame_monastery_vp(game, pid))

    phase_idx = PHASES.index(game["phase_letter"]) if game["phase_letter"] in PHASES else 0
    remaining = len(PHASES) - phase_idx          # phase-ends still ahead (incl. current)
    val = float(base)

    # future mine income (silver -> VP, + workers via monastery 2)
    val += p["mines_count"] * remaining * w["mine_future"]

    # area-completion proximity for partially-filled regions (completed ones already banked)
    pbonus = tiles.PHASE_BONUS.get(game["phase_letter"], 6)
    for reg in b.REGIONS.values():
        size = reg["size"]
        filled = sum(1 for s in reg["spaces"] if duchy.get(s) is not None)
        if 0 < filled < size:
            frac = filled / size
            val += (tiles.AREA_SCORE[size - 1] + pbonus) * frac * frac * w["area_prox"]

    # color-bonus proximity
    for color, spaces in b.SPACES_BY_COLOR.items():
        total = len(spaces)
        if not total:
            continue
        filled = sum(1 for s in spaces if duchy.get(s) is not None)
        if 0 < filled < total:
            remaining_bonus = game["bonus_tiles"].get(color, [])
            bval = remaining_bonus[0] if remaining_bonus else 0
            frac = filled / total
            val += bval * frac * frac * w["color_prox"]

    val += len(p["storage"]) * w["storage"]
    val += sum(1 for e in p["monastery_effects"] if e <= 14) * remaining * w["mon_cont"]
    val -= sum(1 for t in duchy.values() if t is None) * w["empty_pen"]
    return val


def _squash(x):
    return math.tanh(x / _SQUASH)


def _terminal_reward(state, ai_pid):
    scores = engine.final_scores(state)
    opp = _opponent(state, ai_pid)
    return _squash(scores[ai_pid] - scores.get(opp, 0))


def _eval_reward(state, ai_pid):
    opp = _opponent(state, ai_pid)
    return _squash(_value(state, ai_pid) - _value(state, opp))


# ── Rollout policy: cheap type-priority bias toward productive moves ──────────────
_ROLLOUT_PRIORITY = {
    "place_tile": 5, "townhall_place": 5, "extra_action": 4, "building_take_choice": 4,
    "ship_take_goods": 4, "ship_adjacent_take": 3, "take_hex": 3, "sell_goods": 3,
    "warehouse_sell": 3, "buy_black": 2, "monastery6_take": 2, "adjust_die": 1,
    "take_workers": 1, "discard_storage": 0, "skip_pending": 0, "end_turn": 0,
}


def _rollout_policy(state, pid, rng):
    moves = _legal(state, pid)
    if not moves:
        return {"type": "end_turn"}
    best = max(_ROLLOUT_PRIORITY.get(m.get("type"), 1) for m in moves)
    top = [m for m in moves if _ROLLOUT_PRIORITY.get(m.get("type"), 1) == best]
    return rng.choice(top)


def _rollout(state, ai_pid, rng, depth):
    steps = 0
    while not engine.is_over(state) and steps < depth:
        actor = _actor(state)
        if actor is None:
            break
        mv = _rollout_policy(state, actor, rng)
        ok, _ = engine.apply_move(state, actor, mv)
        if not ok:
            ok, _ = engine.apply_move(state, actor, {"type": "end_turn"})
            if not ok:
                break
        steps += 1
    if engine.is_over(state):
        return _terminal_reward(state, ai_pid)
    return _eval_reward(state, ai_pid)


# ── MCTS tree ─────────────────────────────────────────────────────────────────────
class _Node:
    __slots__ = ("move", "parent", "actor", "untried", "children", "visits", "value")

    def __init__(self, move=None, parent=None):
        self.move = move          # the move that leads INTO this node (None at root)
        self.parent = parent
        self.actor = None         # player to act AT this node (set lazily)
        self.untried = None       # list[move] not yet expanded (lazy)
        self.children = {}        # move_key -> _Node
        self.visits = 0
        self.value = 0.0          # sum of rewards, AI perspective


def _move_key(m):
    if isinstance(m, dict):
        return tuple(sorted((k, _move_key(v)) for k, v in m.items()))
    if isinstance(m, list):
        return tuple(_move_key(v) for v in m)
    return m


def _select_child(node, ai_pid):
    """UCB1; exploit term from the perspective of the player acting at ``node``
    (negated for the opponent so the tree models a real adversary)."""
    sign = 1.0 if node.actor == ai_pid else -1.0
    log_n = math.log(node.visits + 1.0)
    best, best_score = None, -1e18
    for ch in node.children.values():
        if ch.visits == 0:
            score = 1e17
        else:
            score = sign * (ch.value / ch.visits) + _UCB_C * math.sqrt(log_n / ch.visits)
        if score > best_score:
            best, best_score = ch, score
    return best


def _iterate(root, state, ai_pid, rng, rollout_depth):
    node = root
    path = [node]
    depth = 0
    # SELECTION — descend fully-expanded nodes (re-simulating on this determinization)
    while True:
        if node.untried is None:
            node.actor = _actor(state)
            node.untried = list(_legal(state, node.actor)) if node.actor is not None else []
        if engine.is_over(state) or node.actor is None:
            break
        if node.untried or depth >= _MAX_TREE_DEPTH or not node.children:
            break
        child = _select_child(node, ai_pid)
        ok, _ = engine.apply_move(state, node.actor, child.move)
        if not ok:                      # this determinization made the edge illegal
            break
        node, depth = child, depth + 1
        path.append(node)
    # EXPANSION
    if (not engine.is_over(state)) and node.actor is not None and node.untried and depth < _MAX_TREE_DEPTH:
        mv = node.untried.pop(rng.randrange(len(node.untried)))
        ok, _ = engine.apply_move(state, node.actor, mv)
        if ok:
            child = _Node(move=mv, parent=node)
            node.children[_move_key(mv)] = child
            node, depth = child, depth + 1
            path.append(node)
    # SIMULATION + BACKPROP
    reward = _rollout(state, ai_pid, rng, rollout_depth)
    for n in path:
        n.visits += 1
        n.value += reward


# ── Setup-phase heuristic (no search needed) ──────────────────────────────────────
def _setup_move(game, pid):
    moves = engine.legal_moves(game, pid)
    if not moves:
        return {"type": "end_turn"}
    b = board.get_board(game["players"][pid].get("board_id"))

    def score(m):
        nbrs = b.neighbors(m["space_id"])
        return (len(nbrs), len({b.SPACES[n]["color"] for n in nbrs}))

    return max(moves, key=score)


# ── Public: choose one move at the current decision point ─────────────────────────
def choose_move(game, pid, *, time_limit=0.8, max_iters=2500, temperature=0.0,
                rng=None, rollout_depth=14):
    rng = rng or random.Random()
    if game.get("phase") == "setup":
        return _setup_move(game, pid)

    root_actor = _actor(game)
    root_legal = _legal(game, root_actor)
    if len(root_legal) <= 1:
        return root_legal[0] if root_legal else {"type": "end_turn"}

    root = _Node()
    start = time.monotonic()
    it = 0
    while it < max_iters and (time.monotonic() - start) < time_limit:
        it += 1
        state = _clone_game(game)
        _determinize(state, rng)
        _iterate(root, state, pid, rng, rollout_depth)

    if not root.children:
        return rng.choice(root_legal)

    kids = list(root.children.values())
    if temperature and temperature > 0:
        weights = [max(k.visits, 1) ** (1.0 / temperature) for k in kids]
        return rng.choices(kids, weights=weights, k=1)[0].move
    return max(kids, key=lambda k: k.visits).move


# ── Public: plan the bot's WHOLE turn (one executor call) ─────────────────────────
def play_turn_plan(game, pid, *, difficulty="hard", rng=None, turn_budget=6.0):
    """Return the ordered list of moves the bot makes this turn (up to & incl.
    end_turn). Runs entirely on a private clone — does NOT mutate ``game`` — so the
    server can re-apply the returned sequence to the real game under its lock.

    Never deadlocks: a step/time guard + a trivial-bot fallback on any apply
    failure always reaches end_turn."""
    rng = rng or random.Random()
    cfg = DIFFICULTY.get(difficulty, DIFFICULTY["hard"])
    work = _clone_game(game)
    seq = []
    start = time.monotonic()
    steps = 0
    while not engine.is_over(work) and _actor(work) == pid and steps < 80:
        steps += 1
        over_budget = (time.monotonic() - start) > turn_budget
        if over_budget:
            mv = bot.choose(work, pid, rng)          # finish fast if we've spent the budget
        else:
            mv = choose_move(work, pid, time_limit=cfg["time_limit"], max_iters=cfg["max_iters"],
                             temperature=cfg["temperature"], rng=rng, rollout_depth=cfg["rollout_depth"])
        if mv is None:
            break
        ok, _ = engine.apply_move(work, pid, mv)
        if not ok:
            mv = bot.choose(work, pid, rng)
            if mv is None:
                break
            ok, _ = engine.apply_move(work, pid, mv)
            if not ok:
                break
        seq.append(mv)
        if mv.get("type") == "end_turn":
            break
    return seq
