"""Pure rules engine for Castles of Crimson.

No FastAPI / web dependency: the engine operates entirely on a plain ``game``
dict so it is deterministic (given a seed) and unit-testable in isolation, and
is the single contract used by the server, the bot, tests, and future AI.

Public API:
    new_game(player_ids, seed=None) -> game
    legal_moves(game, pid) -> list[move]
    apply_move(game, pid, move) -> (ok, error)
    is_over(game) -> bool
    final_scores(game) -> {pid: vp}
    winner(game) -> pid | [pids]

Randomness that must survive save/load (the dice rolls) is kept reproducible by
persisting the RNG state in ``game["rng_state"]``. The tile/goods supplies are
shuffled once at ``new_game`` and then drawn sequentially, so they need no
further randomness.
"""
from __future__ import annotations

import copy
import random
from typing import Any

from . import board
from . import tiles


# ── RNG persistence ─────────────────────────────────────────────────────────
def _make_rng(game: dict) -> random.Random:
    rng = random.Random()
    st = game.get("rng_state")
    if st is not None:
        rng.setstate((st[0], tuple(st[1]), st[2]))
    return rng


def _save_rng(game: dict, rng: random.Random) -> None:
    st = rng.getstate()
    game["rng_state"] = [st[0], list(st[1]), st[2]]


# ── Supply drawing ──────────────────────────────────────────────────────────
def _draw(pool: list[dict], n: int) -> list[dict]:
    """Pop up to n tiles off the end of a pre-shuffled pool."""
    out = []
    for _ in range(n):
        if not pool:
            break
        out.append(pool.pop())
    return out


def _draw_type(pool: list[dict], ttype: str) -> dict | None:
    """Pop the first tile of the given type from a pre-shuffled pool (or None)."""
    for i, t in enumerate(pool):
        if t["type"] == ttype:
            return pool.pop(i)
    return None


def _replenish_depots(game: dict) -> None:
    """Discard leftover hex tiles and refill each depot per the fixed DEPOT_PLAN.

    Each numbered depot gets exactly the two hex types listed for it in
    ``tiles.DEPOT_PLAN`` (drawn from the shuffled supply so the specific
    building/monastery/animal varies by seed). Goods already sitting on depots are
    NOT removed (they persist across phases).
    """
    for i in range(1, 7):
        d = game["depots"][str(i)]
        hexes = []
        for ttype in tiles.DEPOT_PLAN[i]:
            t = _draw_type(game["supply"], ttype)
            if t is not None:
                hexes.append(t)
        d["hexes"] = hexes
    game["black_depot"] = _draw(game["black_supply"], tiles.BLACK_FILL_2P)


def _refill_goods_queue(game: dict) -> None:
    """Stock the per-round goods tiles for the new phase."""
    game["goods_queue"] = _draw(game["goods_supply"], tiles.GOODS_PER_PHASE)


# ── Turn-order track (7 spaces, players stack; ships advance you forward) ─────
NUM_TRACK_SPACES = 7


def _track_order(game: dict) -> list:
    """Turn order, front-to-back: furthest-forward space first, top-of-stack first."""
    order = []
    for s in range(NUM_TRACK_SPACES - 1, -1, -1):
        for pid in reversed(game["track"][s]):   # top of stack acts before those beneath
            order.append(pid)
    return order


def _player_space(game: dict, pid: str) -> int:
    for s in range(NUM_TRACK_SPACES):
        if pid in game["track"][s]:
            return s
    return 0


def _advance_track(game: dict, pid: str, n: int = 1) -> None:
    """Move pid forward n spaces, landing on TOP of the destination stack."""
    if n <= 0:
        return
    cur = _player_space(game, pid)
    if pid in game["track"][cur]:
        game["track"][cur].remove(pid)
    dest = min(cur + n, NUM_TRACK_SPACES - 1)
    game["track"][dest].append(pid)


def _begin_round(game: dict) -> None:
    """Roll everyone's dice + the white die, and place this round's goods tile.

    Turn order for the round is read off the track (ships advance markers during
    play, changing future rounds); the front-most player is the start player and
    holds the white die.
    """
    game["round_order"] = _track_order(game)
    game["start_player"] = game["round_order"][0]

    rng = _make_rng(game)
    for pid in game["order"]:
        game["dice"][pid] = {"values": [rng.randint(1, 6), rng.randint(1, 6)], "used": [False, False]}
    game["white_die"] = rng.randint(1, 6)
    _save_rng(game, rng)

    # Start player places one goods tile on the depot matching the white die.
    if game["goods_queue"]:
        goods = game["goods_queue"].pop(0)
        game["depots"][str(game["white_die"])]["goods"].append(goods)

    game["turn"] = game["start_player"]
    game["black_depot_used_this_turn"] = False
    game["m6_used_this_turn"] = False
    game["ship_advance_pending"] = 0
    _snapshot_turn(game)


def _new_player(name: str, board_id: str = board.DEFAULT_BOARD_ID) -> dict:
    b = board.get_board(board_id)
    duchy = {sid: None for sid in b.SPACES}
    return {
        "name": name,
        "board_id": b.id,
        "castle_sid": None,                  # set when player picks their starting castle
        "duchy": duchy,
        "storage": [],                       # <=3 hex tiles awaiting placement
        "goods": {},                         # color -> count, <=3 colors
        "sold_goods": [],                    # colors sold (for endgame monasteries)
        "workers": tiles.START_WORKERS,
        "silver": tiles.START_SILVER,
        "vp": 0,
        "claimed_bonus": [],                 # [{"color","vp"}]
        "mines_count": 0,
        "buildings_placed": {bt: 0 for bt in tiles.BUILDING_TYPES},
        "livestock_types": [],               # distinct animals placed
        "monastery_effects": [],             # active effect_ids
        "town_buildings": {},                # town_key -> [building_type,...]
    }


def new_game(player_ids: list[str], names: dict[str, str] | None = None, seed: int | None = None,
             boards: dict[str, str] | None = None) -> dict:
    names = names or {}
    boards = boards or {}
    rng = random.Random(seed)

    non_black, black = tiles.build_supply()
    goods_pool = tiles.build_goods_pool()
    rng.shuffle(non_black)
    rng.shuffle(black)
    rng.shuffle(goods_pool)

    game: dict[str, Any] = {
        "num_players": len(player_ids),
        "phase_letter": "A",
        "round": 1,
        "round_in_game": 1,
        "phase": "setup",                    # "setup" | "playing" | "over"
        "winner": None,
        "order": list(player_ids),
        # Turn-order track: 7 spaces, each a stack of pids (bottom-to-top). All
        # players start stacked on space 0 with the first player on top.
        "track": [list(reversed(player_ids))] + [[] for _ in range(NUM_TRACK_SPACES - 1)],
        "round_order": list(player_ids),
        "ship_advance_pending": 0,
        "start_player": player_ids[0],
        "white_die": None,
        "dice": {},
        "turn": player_ids[0],
        "black_depot_used_this_turn": False,
        "m6_used_this_turn": False,
        "depots": {str(i): {"hexes": [], "goods": []} for i in range(1, 7)},
        "black_depot": [],
        "supply": non_black,
        "black_supply": black,
        "goods_supply": goods_pool,
        "goods_queue": [],
        "bonus_tiles": {c: [tiles.bonus_first(len(player_ids)), tiles.bonus_second(len(player_ids))] for c in board.COLORS},
        "players": {pid: _new_player(names.get(pid, pid), boards.get(pid, board.DEFAULT_BOARD_ID)) for pid in player_ids},
        "pending_pid": None,
        "pending_kind": None,
        "pending": None,
        "moves": [],
        "rng_state": None,
    }

    # Persist the RNG so subsequent dice rolls continue this stream deterministically.
    _save_rng(game, rng)

    # Starting resources for each player. Workers are seat-dependent per the
    # rulebook: the start player (seat 0) gets 1, the next gets 2, and so on,
    # compensating the start player for moving first.
    for seat, pid in enumerate(player_ids):
        p = game["players"][pid]
        p["workers"] = seat + 1
        for g in _draw(goods_pool, tiles.START_GOODS):
            p["goods"][g["color"]] = p["goods"].get(g["color"], 0) + 1

    _replenish_depots(game)
    _refill_goods_queue(game)
    # First move for each player: pick a starting castle space.
    # _begin_round is deferred until all players have placed their castle.
    return game


# ── Lifecycle queries ───────────────────────────────────────────────────────
def is_over(game: dict) -> bool:
    return game.get("phase") == "over"


def _endgame_monastery_vp(game: dict, pid: str) -> int:
    """End-of-game VP from monastery effects 15-26 the player owns."""
    p = game["players"][pid]
    eff = p["monastery_effects"]
    total = 0
    if 15 in eff:                                   # 2 VP per different sold goods type
        total += 2 * len(set(p["sold_goods"]))
    for eid, bt in tiles.MONASTERY_BUILDING_SCORING.items():   # 4 VP per building of a type
        if eid in eff:
            total += 4 * p["buildings_placed"].get(bt, 0)
    if 24 in eff:                                   # 4 VP per different livestock type
        total += 4 * len(set(p["livestock_types"]))
    if 25 in eff:                                   # 1 VP per goods tile sold
        total += len(p["sold_goods"])
    if 26 in eff:                                   # 3 VP per bonus tile owned
        total += 3 * len(p["claimed_bonus"])
    return total


def final_scores(game: dict) -> dict[str, int]:
    """Final VP per player: accumulated VP + leftover goods/silver/workers + monastery endgame."""
    scores: dict[str, int] = {}
    for pid, p in game["players"].items():
        s = p["vp"]
        s += sum(p["goods"].values())   # 1 VP per leftover goods tile
        s += p["silver"]                # 1 VP per silver
        s += p["workers"] // 2          # 1 VP per two workers
        s += _endgame_monastery_vp(game, pid)
        scores[pid] = s
    return scores


def winner(game: dict) -> str | list[str]:
    """Most VP wins; tiebreak: fewest empty duchy spaces, then furthest back on track."""
    scores = final_scores(game)
    best = max(scores.values())
    tied = [pid for pid, s in scores.items() if s == best]
    if len(tied) == 1:
        return tied[0]

    def empties(pid):
        return sum(1 for t in game["players"][pid]["duchy"].values() if t is None)

    fewest = min(empties(pid) for pid in tied)
    tied = [pid for pid in tied if empties(pid) == fewest]
    if len(tied) == 1:
        return tied[0]

    order = _track_order(game)
    tied.sort(key=lambda pid: order.index(pid), reverse=True)  # farthest back on the track wins
    return tied[0]


# ── Small helpers ───────────────────────────────────────────────────────────
def _log(game: dict, pid: str, mtype: str, **kw) -> None:
    rec = {"pid": pid, "type": mtype}
    rec.update(kw)
    game["moves"].insert(0, rec)
    del game["moves"][50:]


def _free_storage(p: dict) -> bool:
    return len(p["storage"]) < 3


def _storage_tile(p: dict, tile_id: str) -> dict | None:
    for t in p["storage"]:
        if t["id"] == tile_id:
            return t
    return None


def _pboard(p: dict) -> board.Board:
    """The Board the given player state is playing on."""
    return board.get_board(p.get("board_id"))


def _has_placed_neighbor(game: dict, pid: str, sid: str) -> bool:
    p = game["players"][pid]
    duchy = p["duchy"]
    return any(duchy[nb] is not None for nb in _pboard(p).neighbors(sid))


def _adjust_cost(game: dict, pid: str, frm: int, to: int) -> int:
    """Workers needed to shift a die from `frm` to `to` (1<->6 wraps).

    Each worker shifts by 1 (or 2 with monastery effect 8)."""
    steps = min((to - frm) % 6, (frm - to) % 6)
    per_worker = 2 if 8 in game["players"][pid]["monastery_effects"] else 1
    return (steps + per_worker - 1) // per_worker


def _die(game: dict, pid: str, i: int):
    d = game["dice"].get(pid)
    if d is None or i not in (0, 1):
        return None
    return d


# ── Free die-shift monasteries (9-12) ─────────────────────────────────────────
def _free_shift_for_tile(p: dict, ttype: str) -> bool:
    eff = p["monastery_effects"]
    if ttype == "building" and 9 in eff:
        return True
    if ttype in ("ship", "livestock") and 10 in eff:
        return True
    if ttype in ("castle", "mine", "monastery") and 11 in eff:
        return True
    return False


def _allowed_values(v: int, free_shift: bool) -> set[int]:
    """The die value v, plus its 1<->6-wrapping neighbors when a free shift applies."""
    if not free_shift:
        return {v}
    return {v, v % 6 + 1, (v - 2) % 6 + 1}


def _building_town_ok(p: dict, tile: dict, sid: str) -> bool:
    """Whether placing `tile` on `sid` respects the one-building-per-town rule."""
    if tile["type"] != "building" or 1 in p["monastery_effects"]:
        return True
    return tile["building"] not in p["town_buildings"].get(_pboard(p).region_of(sid), [])


# ── Turn / round lifecycle ────────────────────────────────────────────────────
def _snapshot_turn(game: dict) -> None:
    """Snapshot the game at the start of the current player's turn (for undo).

    Skipped when ``game["_skip_undo"]`` is set — the AI search clones the game and
    steps it thousands of times and never needs undo, so it disables the per-turn
    deepcopy (a major hot-path cost). Real games never set the flag."""
    if game.get("_skip_undo"):
        return
    snap = {k: v for k, v in game.items() if k != "turn_undo"}
    game["turn_undo"] = copy.deepcopy(snap)


def _advance_turn(game: dict) -> None:
    order = game["round_order"]
    idx = order.index(game["turn"])
    if idx + 1 < len(order):
        game["turn"] = order[idx + 1]
        game["black_depot_used_this_turn"] = False
        game["m6_used_this_turn"] = False
        game["ship_advance_pending"] = 0
        _snapshot_turn(game)
    else:
        _advance_round(game)


def _advance_round(game: dict) -> None:
    if game["round"] < 5:
        game["round"] += 1
        game["round_in_game"] += 1
        _begin_round(game)
    else:
        _advance_phase(game)


def _end_of_phase(game: dict) -> None:
    """Award each player 1 silver per mine (and a worker per mine with effect 2)."""
    for p in game["players"].values():
        mines = p["mines_count"]
        p["silver"] += mines
        if 2 in p["monastery_effects"]:
            p["workers"] += mines


def _advance_phase(game: dict) -> None:
    _end_of_phase(game)
    cur = tiles.PHASES.index(game["phase_letter"])
    if cur + 1 < len(tiles.PHASES):
        game["phase_letter"] = tiles.PHASES[cur + 1]
        game["round"] = 1
        game["round_in_game"] += 1
        _replenish_depots(game)
        _refill_goods_queue(game)
        _begin_round(game)
    else:
        game["phase"] = "over"
        game["turn"] = None
        _finalize(game)


def _finalize(game: dict) -> None:
    """Compute final scores + winner when the game ends. (Detail filled in M8.)"""
    game["winner"] = winner(game)


# ── Placement effects hook (type-specific effects added in M6/M7) ─────────────
def _on_tile_placed(game: dict, pid: str, sid: str, tile: dict) -> None:
    p = game["players"][pid]
    t = tile["type"]
    if t == "mine":
        p["mines_count"] += 1
    elif t == "livestock":
        _score_livestock(game, pid, sid, tile)
    elif t == "building":
        _place_building_effect(game, pid, sid, tile)
    # Immediate area/color scoring happens for every placement.
    _score_area_and_bonus(game, pid, sid)
    # Effects that hand the player a sub-decision are queued LAST so the pending
    # state is the final result of this placement.
    if t == "ship":
        _place_ship_effect(game, pid, sid, tile)
    elif t == "castle":
        _place_castle_effect(game, pid, sid, tile)
    elif t == "monastery":
        _place_monastery_effect(game, pid, sid, tile)


def _score_area_and_bonus(game: dict, pid: str, sid: str) -> None:
    """After a placement on `sid`, score a newly-completed area and/or color bonus."""
    p = game["players"][pid]
    b = _pboard(p)
    duchy = p["duchy"]
    color = b.SPACES[sid]["color"]

    # Area completion: the region containing this space is now fully covered.
    region = b.REGIONS[b.region_of(sid)]
    if all(duchy[s] is not None for s in region["spaces"]):
        size = region["size"]
        vp = tiles.AREA_SCORE[size - 1] + tiles.PHASE_BONUS[game["phase_letter"]]
        p["vp"] += vp
        _log(game, pid, "area_complete", region=region["id"], size=size, vp=vp)

    # Color bonus: first/second player to fully cover every space of this color.
    if all(duchy[s] is not None for s in b.SPACES_BY_COLOR[color]):
        remaining = game["bonus_tiles"].get(color, [])
        if remaining:
            val = remaining.pop(0)
            p["claimed_bonus"].append({"color": color, "vp": val})
            p["vp"] += val
            _log(game, pid, "bonus_tile", color=color, vp=val)


# ── Pending sub-decision helpers ──────────────────────────────────────────────
def _set_pending(game: dict, pid: str, kind: str, ctx: dict) -> None:
    game["pending_pid"] = pid
    game["pending_kind"] = kind
    game["pending"] = {"pid": pid, "kind": kind, "ctx": ctx}


def _clear_pending(game: dict) -> None:
    game["pending_pid"] = None
    game["pending_kind"] = None
    game["pending"] = None


# ── Placement effects (M6) ────────────────────────────────────────────────────
def _score_livestock(game: dict, pid: str, sid: str, tile: dict) -> None:
    p = game["players"][pid]
    animal = tile["animal"]
    b = _pboard(p)
    pasture = b.REGIONS[b.region_of(sid)]["spaces"]
    same = [s for s in pasture if p["duchy"][s] is not None and p["duchy"][s].get("animal") == animal]
    total = sum(p["duchy"][s]["count"] for s in same)
    p["vp"] += total
    if 7 in p["monastery_effects"]:
        p["vp"] += len(same)          # +1 VP per scoring livestock tile
    if animal not in p["livestock_types"]:
        p["livestock_types"].append(animal)
    _log(game, pid, "livestock_score", animal=animal, vp=total)


def _building_take_pending(game: dict, pid: str, bt: str, types: tuple) -> None:
    """Set a pending 'take a tile of one of `types` from a numbered depot' choice."""
    p = game["players"][pid]
    if not _free_storage(p):
        return
    cand = [t["id"] for d in range(1, 7) for t in game["depots"][str(d)]["hexes"] if t["type"] in types]
    if cand:
        _set_pending(game, pid, "building_take_choice", {"building": bt, "types": list(types), "candidates": cand})


def _place_building_effect(game: dict, pid: str, sid: str, tile: dict) -> None:
    p = game["players"][pid]
    bt = tile["building"]
    p["buildings_placed"][bt] += 1
    p["town_buildings"].setdefault(_pboard(p).region_of(sid), []).append(bt)
    if bt == "boarding":
        p["workers"] += 4
    elif bt == "bank":
        p["silver"] += 2
    elif bt == "watchtower":
        p["vp"] += 4
    elif bt == "market":
        _building_take_pending(game, pid, bt, ("ship", "livestock"))
    elif bt == "carpenter":
        _building_take_pending(game, pid, bt, ("building",))
    elif bt == "church":
        _building_take_pending(game, pid, bt, ("mine", "monastery", "castle"))
    elif bt == "warehouse":
        if p["goods"]:
            _set_pending(game, pid, "warehouse_sell", {"building": bt})
    elif bt == "townhall":
        if p["storage"]:
            _set_pending(game, pid, "townhall_place", {"building": bt})
    _log(game, pid, "building_effect", building=bt)


def _take_all_goods_from_depot(game: dict, pid: str, depot: int) -> None:
    p = game["players"][pid]
    d = game["depots"][str(depot)]
    remaining = []
    for g in d["goods"]:
        if g["color"] in p["goods"] or len(p["goods"]) < 3:   # store <=3 distinct types
            p["goods"][g["color"]] = p["goods"].get(g["color"], 0) + 1
        else:
            remaining.append(g)
    d["goods"] = remaining


def _place_ship_effect(game: dict, pid: str, sid: str, tile: dict) -> None:
    # Each ship advances your track marker one space when you end your turn.
    game["ship_advance_pending"] = game.get("ship_advance_pending", 0) + 1
    # Plus you immediately take all goods from a depot of your choice (if any exist).
    total_goods = sum(len(game["depots"][str(d)]["goods"]) for d in range(1, 7))
    if total_goods > 0:
        _set_pending(game, pid, "ship_choose_depot", {})


def _place_castle_effect(game: dict, pid: str, sid: str, tile: dict) -> None:
    # Placing a castle grants an immediate extra action with a die of your choice.
    _set_pending(game, pid, "extra_action", {"source": "castle"})


def _place_monastery_effect(game: dict, pid: str, sid: str, tile: dict) -> None:
    eid = tile["effect_id"]
    p = game["players"][pid]
    if eid not in p["monastery_effects"]:
        p["monastery_effects"].append(eid)
    _log(game, pid, "monastery_placed", effect_id=eid)
    _monastery_on_place(game, pid, sid, tile)   # immediate effects (M7)


def _monastery_on_place(game: dict, pid: str, sid: str, tile: dict) -> None:
    """Immediate on-place monastery effects. Base-game monasteries are all
    continuous or end-of-game, so this is a no-op for now (kept as the hook for M7)."""
    return None


# ── Action cores (shared by die-actions and pending resolvers) ────────────────
def _do_take_hex(game, pid, value, depot, tile_id):
    p = game["players"][pid]
    if not _free_storage(p):
        return False, "storage full"
    # Monastery 12 lets you take from a depot adjacent to the die value.
    if depot not in _allowed_values(value, 12 in p["monastery_effects"]):
        return False, "depot does not match die"
    d = game["depots"][str(depot)]
    tile = next((t for t in d["hexes"] if t["id"] == tile_id), None)
    if tile is None:
        return False, "tile not in matching depot"
    d["hexes"].remove(tile)
    p["storage"].append(tile)
    _log(game, pid, "take_hex", tile=tile, depot=depot)
    return True, None


def _do_place_tile(game, pid, value, tile_id, sid, ignore_number=False):
    p = game["players"][pid]
    tile = _storage_tile(p, tile_id)
    if tile is None:
        return False, "tile not in storage"
    info = _pboard(p).SPACES.get(sid)
    if info is None:
        return False, "no such space"
    if p["duchy"][sid] is not None:
        return False, "space already filled"
    if info["color"] != tile["color"]:
        return False, "tile color does not match space"
    if not ignore_number and info["number"] not in _allowed_values(value, _free_shift_for_tile(p, tile["type"])):
        return False, "die does not match space number"
    if not _has_placed_neighbor(game, pid, sid):
        return False, "must be adjacent to a placed tile"
    if not _building_town_ok(p, tile, sid):
        return False, "already have that building in this town"
    p["storage"].remove(tile)
    p["duchy"][sid] = tile
    _log(game, pid, "place_tile", tile=tile, space_id=sid)
    _on_tile_placed(game, pid, sid, tile)
    return True, None


def _sell_color(game, pid, color, count):
    p = game["players"][pid]
    p["silver"] += 2 if 3 in p["monastery_effects"] else tiles.SELL_SILVER
    vp = tiles.sell_vp_per_tile(game["num_players"]) * count
    p["vp"] += vp
    if 4 in p["monastery_effects"]:
        p["workers"] += 1
    del p["goods"][color]
    p["sold_goods"].extend([color] * count)
    _log(game, pid, "sell_goods", color=color, count=count, vp=vp)


def _do_sell_goods(game, pid, value):
    p = game["players"][pid]
    color = tiles.goods_color_for_die(value)
    count = p["goods"].get(color, 0)
    if count <= 0:
        return False, "no goods of that color to sell"
    _sell_color(game, pid, color, count)
    return True, None


def _do_take_workers(game, pid):
    p = game["players"][pid]
    p["workers"] += 4 if 14 in p["monastery_effects"] else 2
    if 13 in p["monastery_effects"]:
        p["silver"] += 1
    _log(game, pid, "take_workers")
    return True, None


# ── Die-action handlers (read/spend a die, then call the shared core) ─────────
def _die_action(core):
    def handler(game, pid, move):
        i = move.get("die_index")
        if i not in (0, 1):
            return False, "bad die_index"
        if game["dice"][pid]["used"][i]:
            return False, "die already used"
        v = game["dice"][pid]["values"][i]
        ok, err = core(game, pid, v, move)
        if ok:
            game["dice"][pid]["used"][i] = True
        return ok, err
    return handler


_h_take_hex = _die_action(lambda g, p, v, m: _do_take_hex(g, p, v, m.get("depot", v), m.get("tile_id")))
_h_place_tile = _die_action(lambda g, p, v, m: _do_place_tile(g, p, v, m.get("tile_id"), m.get("space_id")))
_h_sell_goods = _die_action(lambda g, p, v, m: _do_sell_goods(g, p, v))
_h_take_workers = _die_action(lambda g, p, v, m: _do_take_workers(g, p))


def _h_buy_black(game, pid, move):
    p = game["players"][pid]
    if game["black_depot_used_this_turn"]:
        return False, "already bought from the black depot this turn"
    if p["silver"] < 2:
        return False, "need 2 silver"
    if not _free_storage(p):
        return False, "storage full"
    tile = next((t for t in game["black_depot"] if t["id"] == move.get("tile_id")), None)
    if tile is None:
        return False, "tile not in black depot"
    p["silver"] -= 2
    game["black_depot"].remove(tile)
    p["storage"].append(tile)
    game["black_depot_used_this_turn"] = True
    _log(game, pid, "buy_black", tile=tile)
    return True, None


def _h_monastery6_take(game, pid, move):
    """Monastery 6: once per turn, spend 2 workers to take a building tile to storage."""
    p = game["players"][pid]
    if 6 not in p["monastery_effects"]:
        return False, "no monastery for this action"
    if game["m6_used_this_turn"]:
        return False, "already used this turn"
    if p["workers"] < 2:
        return False, "need 2 workers"
    if not _free_storage(p):
        return False, "storage full"
    tid = move.get("tile_id")
    for d in range(1, 7):
        depot = game["depots"][str(d)]
        t = next((x for x in depot["hexes"] if x["id"] == tid and x["type"] == "building"), None)
        if t is not None:
            depot["hexes"].remove(t)
            p["storage"].append(t)
            p["workers"] -= 2
            game["m6_used_this_turn"] = True
            _log(game, pid, "monastery6_take", tile=t)
            return True, None
    return False, "no such building tile in a depot"


def _h_adjust_die(game, pid, move):
    p = game["players"][pid]
    i = move.get("die_index")
    if i not in (0, 1):
        return False, "bad die_index"
    if game["dice"][pid]["used"][i]:
        return False, "die already used"
    to = move.get("to")
    if to not in (1, 2, 3, 4, 5, 6):
        return False, "bad target value"
    frm = game["dice"][pid]["values"][i]
    if to == frm:
        return False, "die already shows that value"
    cost = _adjust_cost(game, pid, frm, to)
    if p["workers"] < cost:
        return False, "not enough workers"
    p["workers"] -= cost
    game["dice"][pid]["values"][i] = to
    _log(game, pid, "adjust_die", die_index=i, to=to, workers=cost)
    return True, None


def _h_discard_storage(game, pid, move):
    """Discard a tile from full storage (back to the box) to make room.

    Per the rulebook, when you take a hex tile but have no empty key space, you
    must first create room by discarding a stored tile. Only offered when
    storage is full, so it is never a pointless move.
    """
    p = game["players"][pid]
    if _free_storage(p):
        return False, "storage is not full"
    tile = _storage_tile(p, move.get("tile_id"))
    if tile is None:
        return False, "tile not in storage"
    p["storage"].remove(tile)
    _log(game, pid, "discard_storage", tile=tile)
    return True, None


def _h_end_turn(game, pid, move):
    # Apply this turn's queued ship advances to the track (each ship = 1 space).
    n = game.get("ship_advance_pending", 0)
    if n > 0:
        _advance_track(game, pid, n)
        _log(game, pid, "track_advance", spaces=n)
    _log(game, pid, "end_turn")
    _advance_turn(game)
    return True, None


def _h_place_starting_castle(game, pid, move):
    if game["phase"] != "setup":
        return False, "not in setup phase"
    sid = move.get("space_id")
    p = game["players"][pid]
    b = _pboard(p)
    if sid not in b.SPACES:
        return False, "invalid space"
    if b.SPACES[sid]["color"] != "burgundy":
        return False, "starting castle must be placed on a burgundy space"
    if p["duchy"][sid] is not None:
        return False, "space already occupied"
    p["duchy"][sid] = tiles.starting_castle_tile()
    p["castle_sid"] = sid
    _log(game, pid, "place_starting_castle", space_id=sid)
    # Advance to next player who hasn't placed yet.
    remaining = [p2 for p2 in game["order"] if game["players"][p2]["castle_sid"] is None]
    if remaining:
        game["turn"] = remaining[0]
    else:
        game["phase"] = "playing"
        _begin_round(game)
    return True, None


_HANDLERS = {
    "place_starting_castle": _h_place_starting_castle,
    "take_hex": _h_take_hex,
    "place_tile": _h_place_tile,
    "sell_goods": _h_sell_goods,
    "take_workers": _h_take_workers,
    "buy_black": _h_buy_black,
    "monastery6_take": _h_monastery6_take,
    "adjust_die": _h_adjust_die,
    "discard_storage": _h_discard_storage,
    "end_turn": _h_end_turn,
}


# ── Pending resolvers ─────────────────────────────────────────────────────────
def _r_extra_action(game, pid, move):
    v = move.get("value")
    if v not in (1, 2, 3, 4, 5, 6):
        return False, "choose a die value 1-6"
    sub = move.get("sub") or {}
    st = sub.get("type")
    _clear_pending(game)                      # cleared first; the sub may set a new pending
    if st == "take_hex":
        ok, err = _do_take_hex(game, pid, v, sub.get("depot", v), sub.get("tile_id"))
    elif st == "place_tile":
        ok, err = _do_place_tile(game, pid, v, sub.get("tile_id"), sub.get("space_id"))
    elif st == "sell_goods":
        ok, err = _do_sell_goods(game, pid, v)
    elif st == "take_workers":
        ok, err = _do_take_workers(game, pid)
    else:
        ok, err = False, "bad extra action"
    if not ok:
        _set_pending(game, pid, "extra_action", {"source": "castle"})
        return False, err
    return True, None


def _r_ship_take_goods(game, pid, move):
    d = move.get("depot")
    if d not in (1, 2, 3, 4, 5, 6):
        return False, "choose a depot 1-6"
    _clear_pending(game)
    _take_all_goods_from_depot(game, pid, d)
    _log(game, pid, "ship_take_goods", depot=d)
    # Monastery 5: you may ALSO take all goods from one adjacent depot of your
    # choice. Offer it only when an adjacent depot actually holds goods.
    if 5 in game["players"][pid]["monastery_effects"]:
        adj = [x for x in (d - 1, d + 1)
               if 1 <= x <= 6 and game["depots"][str(x)]["goods"]]
        if adj:
            _set_pending(game, pid, "ship_adjacent_depot", {"candidates": adj})
    # (The ship's track advance was queued at placement and applies at end of turn.)
    return True, None


def _r_ship_adjacent_take(game, pid, move):
    """Monastery 5 follow-up: take all goods from one chosen adjacent depot."""
    ctx = game["pending"]["ctx"]
    d = move.get("depot")
    if d not in ctx.get("candidates", []):
        return False, "not an adjacent depot with goods"
    _clear_pending(game)
    _take_all_goods_from_depot(game, pid, d)
    _log(game, pid, "ship_adjacent_take", depot=d)
    return True, None


def _r_building_take(game, pid, move):
    ctx = game["pending"]["ctx"]
    tid = move.get("tile_id")
    if tid not in ctx.get("candidates", []):
        return False, "not an available tile"
    p = game["players"][pid]
    if not _free_storage(p):
        return False, "storage full"
    for d in range(1, 7):
        depot = game["depots"][str(d)]
        t = next((x for x in depot["hexes"] if x["id"] == tid), None)
        if t is not None:
            depot["hexes"].remove(t)
            p["storage"].append(t)
            _clear_pending(game)
            _log(game, pid, "building_take", tile=t)
            return True, None
    return False, "tile no longer available"


def _r_warehouse_sell(game, pid, move):
    color = move.get("color")
    count = game["players"][pid]["goods"].get(color, 0)
    if count <= 0:
        return False, "no goods of that color"
    _sell_color(game, pid, color, count)
    _clear_pending(game)
    return True, None


def _r_townhall_place(game, pid, move):
    _clear_pending(game)                      # cleared first; the placed tile may set a new pending
    ok, err = _do_place_tile(game, pid, None, move.get("tile_id"), move.get("space_id"), ignore_number=True)
    if not ok:
        _set_pending(game, pid, "townhall_place", {"building": "townhall"})
        return False, err
    return True, None


def _r_skip_pending(game, pid, move):
    kind = game["pending_kind"]
    # (A ship's track advance was already queued at placement; skipping the depot
    # choice just forgoes the goods.)
    _clear_pending(game)
    _log(game, pid, "skip_pending", kind=kind)
    return True, None


_RESOLVERS = {
    "extra_action": _r_extra_action,
    "ship_take_goods": _r_ship_take_goods,
    "ship_adjacent_take": _r_ship_adjacent_take,
    "building_take_choice": _r_building_take,
    "warehouse_sell": _r_warehouse_sell,
    "townhall_place": _r_townhall_place,
    "skip_pending": _r_skip_pending,
}
# Which resolver move types are allowed for each pending kind (skip always allowed).
RESOLVERS_FOR = {
    "extra_action": {"extra_action", "skip_pending"},
    "ship_choose_depot": {"ship_take_goods", "skip_pending"},
    "ship_adjacent_depot": {"ship_adjacent_take", "skip_pending"},
    "building_take_choice": {"building_take_choice", "skip_pending"},
    "warehouse_sell": {"warehouse_sell", "skip_pending"},
    "townhall_place": {"townhall_place", "skip_pending"},
}


def _legal_extra_actions(game, pid, v):
    """Sub-actions available for an extra action / castle, using die value v."""
    p = game["players"][pid]
    out = [{"type": "extra_action", "value": v, "sub": {"type": "take_workers"}}]
    if _free_storage(p):
        for depot in _allowed_values(v, 12 in p["monastery_effects"]):
            for t in game["depots"][str(depot)]["hexes"]:
                out.append({"type": "extra_action", "value": v, "sub": {"type": "take_hex", "depot": depot, "tile_id": t["id"]}})
    b = _pboard(p)
    for t in p["storage"]:
        allowed = _allowed_values(v, _free_shift_for_tile(p, t["type"]))
        for sid, info in b.SPACES.items():
            if (p["duchy"][sid] is None and info["color"] == t["color"] and info["number"] in allowed
                    and _has_placed_neighbor(game, pid, sid) and _building_town_ok(p, t, sid)):
                out.append({"type": "extra_action", "value": v, "sub": {"type": "place_tile", "tile_id": t["id"], "space_id": sid}})
    if p["goods"].get(tiles.goods_color_for_die(v), 0) > 0:
        out.append({"type": "extra_action", "value": v, "sub": {"type": "sell_goods"}})
    return out


def _pending_legal_moves(game: dict, pid: str) -> list[dict]:
    kind = game["pending_kind"]
    ctx = game["pending"]["ctx"] if game.get("pending") else {}
    p = game["players"][pid]
    moves: list[dict] = []
    if kind == "extra_action":
        for v in range(1, 7):
            moves.extend(_legal_extra_actions(game, pid, v))
    elif kind == "ship_choose_depot":
        for d in range(1, 7):
            moves.append({"type": "ship_take_goods", "depot": d})
    elif kind == "ship_adjacent_depot":
        for d in ctx.get("candidates", []):
            moves.append({"type": "ship_adjacent_take", "depot": d})
    elif kind == "building_take_choice":
        for tid in ctx.get("candidates", []):
            moves.append({"type": "building_take_choice", "tile_id": tid})
    elif kind == "warehouse_sell":
        for color in list(p["goods"].keys()):
            moves.append({"type": "warehouse_sell", "color": color})
    elif kind == "townhall_place":
        b = _pboard(p)
        for t in p["storage"]:
            for sid, info in b.SPACES.items():
                if (p["duchy"][sid] is None and info["color"] == t["color"]
                        and _has_placed_neighbor(game, pid, sid) and _building_town_ok(p, t, sid)):
                    moves.append({"type": "townhall_place", "tile_id": t["id"], "space_id": sid})
    moves.append({"type": "skip_pending"})
    return moves


# ── Public API ────────────────────────────────────────────────────────────────
def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if is_over(game):
        return False, "game is over"
    mt = move.get("type")
    if game["phase"] == "setup":
        if mt != "place_starting_castle":
            return False, "must place starting castle first"
        if pid != game["turn"]:
            return False, "not your turn"
        return _h_place_starting_castle(game, pid, move)
    # Undo the whole current turn (including any pending sub-decision). Restores
    # the snapshot taken when this player's turn began, dropping every action
    # logged this turn.
    if mt == "undo_turn":
        if game.get("turn") != pid:
            return False, "can only undo on your turn"
        snap = game.get("turn_undo")
        if not snap:
            return False, "nothing to undo"
        restored = copy.deepcopy(snap)
        game.clear()
        game.update(restored)
        _snapshot_turn(game)
        _log(game, pid, "undo_turn")
        return True, None
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return False, "not your turn"
        if mt not in RESOLVERS_FOR.get(game["pending_kind"], set()):
            return False, f"must resolve {game['pending_kind']} first"
        return _RESOLVERS[mt](game, pid, move)
    if pid != game["turn"]:
        return False, "not your turn"
    handler = _HANDLERS.get(mt)
    if handler is None:
        return False, f"unknown move: {mt}"
    return handler(game, pid, move)


def legal_moves(game: dict, pid: str) -> list[dict]:
    if is_over(game):
        return []
    if game["phase"] == "setup":
        if pid != game["turn"]:
            return []
        p = game["players"][pid]
        b = _pboard(p)
        return [{"type": "place_starting_castle", "space_id": sid}
                for sid in sorted(b.SPACES_BY_COLOR["burgundy"])
                if p["duchy"][sid] is None]
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return []
        return _pending_legal_moves(game, pid)
    if pid != game["turn"]:
        return []

    p = game["players"][pid]
    dice = game["dice"][pid]
    moves: list[dict] = [{"type": "end_turn"}]

    for i, (v, used) in enumerate(zip(dice["values"], dice["used"])):
        if used:
            continue
        # adjust_die to any reachable value
        for target in range(1, 7):
            if target == v:
                continue
            if _adjust_cost(game, pid, v, target) <= p["workers"]:
                moves.append({"type": "adjust_die", "die_index": i, "to": target})
        # take 2 workers (any value)
        moves.append({"type": "take_workers", "die_index": i})
        # sell goods of the color the die selects (if held)
        if p["goods"].get(tiles.goods_color_for_die(v), 0) > 0:
            moves.append({"type": "sell_goods", "die_index": i})
        # take a hex from a matching depot (monastery 12 widens to adjacent depots)
        if _free_storage(p):
            for depot in _allowed_values(v, 12 in p["monastery_effects"]):
                for t in game["depots"][str(depot)]["hexes"]:
                    moves.append({"type": "take_hex", "die_index": i, "depot": depot, "tile_id": t["id"]})
        # place a storage tile on a legal space (monasteries 9-11 widen the number)
        b = _pboard(p)
        for t in p["storage"]:
            allowed = _allowed_values(v, _free_shift_for_tile(p, t["type"]))
            for sid, info in b.SPACES.items():
                if p["duchy"][sid] is not None:
                    continue
                if info["color"] != t["color"] or info["number"] not in allowed:
                    continue
                if not _has_placed_neighbor(game, pid, sid):
                    continue
                if not _building_town_ok(p, t, sid):
                    continue
                moves.append({"type": "place_tile", "die_index": i, "tile_id": t["id"], "space_id": sid})

    if not game["black_depot_used_this_turn"] and p["silver"] >= 2 and _free_storage(p):
        for t in game["black_depot"]:
            moves.append({"type": "buy_black", "tile_id": t["id"]})

    # When storage is full, you may discard a stored tile to make room (e.g. so a
    # subsequent take-hex has a free key space).
    if not _free_storage(p):
        for t in p["storage"]:
            moves.append({"type": "discard_storage", "tile_id": t["id"]})

    # Monastery 6: spend 2 workers to take a building tile (once per turn).
    if 6 in p["monastery_effects"] and not game["m6_used_this_turn"] and p["workers"] >= 2 and _free_storage(p):
        for d in range(1, 7):
            for t in game["depots"][str(d)]["hexes"]:
                if t["type"] == "building":
                    moves.append({"type": "monastery6_take", "tile_id": t["id"]})

    return moves
