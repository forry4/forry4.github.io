"""Pure rules engine for The Black Castle (base game).

The state returned by this module is ordinary JSON data.  A move is accepted
only when it appears in ``legal_moves`` for the acting seat, so the same code
drives human clients, the Easy bot, replays, and the later BGA parity harness.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from .cards import (COLORS, DAIMYO, DECREE_CARDS, DIPLOMATS, GARDENS,
                    RESOURCES, STARTING_ACTION_CARDS, STARTING_RESOURCE_CARDS,
                    STEWARDS, TRAINING_YARDS, WORKERS, clone, make_die_tiles)

RULESET = "base-2023"
ROUND_COUNT = 3
TURNS_PER_ROUND = 3
MAX_RESOURCE = 7
MAX_SEALS = 5
MAX_INFLUENCE = 15
# The three season gates on the printed Passage of Time track. A marker may
# cross a gate only after paying the corresponding Daimyo Seal cost.
CHECKPOINT_COSTS = {6: 1, 10: 2, 11: 3}
BRIDGE_ORDER = ("coral", "black", "white")
DOMAIN_WORKER = {"coral": "courtiers", "black": "gardeners", "white": "warriors"}
RESOURCE_FOR_COLOR = {"coral": "food", "black": "iron", "white": "pearl"}


def _rng(game: dict) -> random.Random:
    rng = random.Random()
    state = game.get("rng_state")
    if state:
        try:
            rng.setstate((int(state[0]), tuple(state[1]), state[2]))
        except (TypeError, ValueError, IndexError):
            pass
    return rng


def _save_rng(game: dict, rng: random.Random) -> None:
    state = rng.getstate()
    game["rng_state"] = [state[0], list(state[1]), state[2]]


def _log(game: dict, message: str, *, pid: str | None = None, kind: str = "info") -> None:
    seq = int(game.get("log_seq", 0)) + 1
    game["log_seq"] = seq
    game.setdefault("log", []).append({
        "turn": int(game.get("turn_number", 0)), "message": message,
        "pid": pid, "kind": kind, "seq": seq,
    })
    if len(game["log"]) > 300:
        del game["log"][:-300]


def _player(game: dict, pid: str) -> dict:
    return game["players"][pid]


def _name(game: dict, pid: str) -> str:
    return game.get("names", {}).get(pid, pid)


def _advance_influence(game: dict, pid: str, amount: int) -> int:
    """Advance the Passage of Time marker, paying its checkpoint seals."""
    p = _player(game, pid)
    moved = 0
    for _ in range(max(0, int(amount))):
        current = int(p.get("influence", 0))
        if current >= MAX_INFLUENCE:
            break
        cost = CHECKPOINT_COSTS.get(current + 1, 0)
        if cost and not _pay(game, pid, seals=cost):
            break
        p["influence"] = current + 1
        moved += 1
    return moved


def _gain(game: dict, pid: str, *, coins: int = 0, seals: int = 0,
          points: int = 0, resource: str | None = None,
          amount: int = 0, influence: int = 0, note: str = "") -> None:
    p = _player(game, pid)
    resource_amount = int(amount)
    if coins:
        coin_delta = int(coins)
        p["coins"] = max(0, p.get("coins", 0) + coin_delta)
        common = game.setdefault("common", {})
        # The printed game uses a common reserve.  Keep the counters useful for
        # replay/debugging while allowing a generous reserve in old saves.
        if coin_delta > 0:
            common["coins"] = max(0, int(common.get("coins", 0)) - coin_delta)
        elif coin_delta < 0:
            common["coins"] = int(common.get("coins", 0)) + (-coin_delta)
    if seals:
        seal_delta = int(seals)
        p["seals"] = max(0, min(MAX_SEALS, p.get("seals", 0) + seal_delta))
        common = game.setdefault("common", {})
        if seal_delta > 0:
            common["seals"] = max(0, int(common.get("seals", 0)) - seal_delta)
        elif seal_delta < 0:
            common["seals"] = int(common.get("seals", 0)) + (-seal_delta)
    if points:
        p["points"] = p.get("points", 0) + int(points)
    if resource:
        p["resources"][resource] = max(0, min(MAX_RESOURCE,
                                                p["resources"].get(resource, 0) + resource_amount))
    moved_influence = _advance_influence(game, pid, influence) if influence > 0 else 0
    bits = []
    if coins:
        bits.append(f"{coins:+d} coin" + ("s" if abs(coins) != 1 else ""))
    if seals:
        bits.append(f"{seals:+d} seal" + ("s" if abs(seals) != 1 else ""))
    if points:
        bits.append(f"{points:+d} point" + ("s" if abs(points) != 1 else ""))
    if resource and resource_amount:
        bits.append(f"{resource_amount:+d} {resource}")
    if moved_influence:
        bits.append(f"{moved_influence:+d} influence")
    if bits:
        _log(game, f"{_name(game, pid)} gains {', '.join(bits)}" + (f" ({note})" if note else ""), pid=pid)
    # Keep the +40/+80 fan tiles explicit.  The UI can show the live total,
    # while the tile count is what a physical player would place beside their
    # domain board.
    if points:
        p["fan_tiles"] = max(int(p.get("fan_tiles", 0)), int(p.get("points", 0)) // 40)


def _pay(game: dict, pid: str, *, coins: int = 0, seals: int = 0,
         resource: str | None = None, amount: int = 0) -> bool:
    p = _player(game, pid)
    if coins and p.get("coins", 0) < coins:
        return False
    if seals and p.get("seals", 0) < seals:
        return False
    if resource and p["resources"].get(resource, 0) < amount:
        return False
    if coins:
        p["coins"] -= coins
        game.setdefault("common", {})["coins"] = int(game["common"].get("coins", 0)) + coins
    if seals:
        p["seals"] -= seals
        game.setdefault("common", {})["seals"] = int(game["common"].get("seals", 0)) + seals
    if resource:
        p["resources"][resource] -= amount
    return True


def _move_worker(game: dict, pid: str, worker: str, destination: str) -> bool:
    p = _player(game, pid)
    counts = p["workers"]
    if counts.get(worker, {}).get("domain", 0) <= 0:
        return False
    # Card text names these destinations after the physical board spaces. The
    # live state keeps a short-lived pool key until the player chooses the
    # actual yard or garden card, so normalize the public vocabulary here.
    if worker == "warriors" and destination == "yard":
        destination = "yard_pool"
    elif worker == "gardeners" and destination == "garden":
        destination = "garden_pool"
    counts[worker]["domain"] -= 1
    counts[worker][destination] = counts[worker].get(destination, 0) + 1
    return True


def _move_courtier(game: dict, pid: str, destination: str, *, cost: int = 0) -> bool:
    p = _player(game, pid)
    c = p["workers"]["courtiers"]
    order = ("gate", "floor1", "floor2", "daimyo")
    if destination not in order:
        return False
    target_index = order.index(destination)
    source = next((place for place in order[:target_index]
                   if c.get(place, 0) > 0), None)
    if source is None or (cost and not _pay(game, pid, coins=cost)):
        return False
    c[source] -= 1
    c[destination] = c.get(destination, 0) + 1
    return True


def _apply_effects(game: dict, pid: str, effects: list[dict], *, source: str = "action") -> None:
    for effect in effects or []:
        op = effect.get("op")
        if op == "gain":
            _gain(game, pid, resource=effect.get("resource"),
                  amount=int(effect.get("amount", 1)) if effect.get("resource") else 0,
                  coins=int(effect.get("coins", 0)), seals=int(effect.get("seals", 0)),
                  points=int(effect.get("points", 0)), influence=int(effect.get("influence", 0)),
                  note=source)
        elif op == "coins":
            _gain(game, pid, coins=int(effect.get("amount", 0)), note=source)
        elif op == "seals":
            _gain(game, pid, seals=int(effect.get("amount", 0)), note=source)
        elif op == "points":
            _gain(game, pid, points=int(effect.get("amount", 0)), note=source)
        elif op == "influence":
            _gain(game, pid, influence=int(effect.get("amount", 0)), note=source)
        elif op == "move":
            worker = effect.get("worker")
            destination = effect.get("to") or effect.get("destination")
            moved = False
            if worker in WORKERS and effect.get("from") == "domain" and destination:
                moved = _move_worker(game, pid, worker, destination)
            elif worker == "courtiers" and destination in {"gate", "floor1", "floor2", "daimyo"}:
                moved = _move_courtier(game, pid, destination, cost=0)
            elif worker in WORKERS and destination:
                moved = _move_worker(game, pid, worker, destination)
            if moved:
                _log(game, f"{_name(game, pid)} moves a {worker[:-1]} to {destination}.", pid=pid)
        elif op == "pay_seal_for_worker":
            worker = effect.get("worker", "courtiers")
            destination = "gate" if worker == "courtiers" else (
                "yard_pool" if worker == "warriors" else "garden_pool")
            if p := game.get("players", {}).get(pid):
                can_move = p.get("workers", {}).get(worker, {}).get("domain", 0) > 0
            else:
                can_move = False
            if can_move and _pay(game, pid, seals=1) and _move_worker(game, pid, worker, destination):
                _log(game, f"{_name(game, pid)} spends a seal to deploy a {worker[:-1]}.", pid=pid)
            elif can_move:
                _log(game, f"{_name(game, pid)} cannot afford the seal action.", pid=pid)
        elif op == "lantern":
            icon = effect.get("icon", "coin")
            game["players"][pid]["lantern"].append({"icon": icon, "amount": int(effect.get("amount", 1))})
        elif op == "well_bonus":
            _well_bonus(game, pid)
            if isinstance(game.get("turn_undo"), dict):
                game["turn_undo"]["revealed"] = True


def _well_bonus(game: dict, pid: str) -> None:
    hidden = [t for t in game.get("die_tiles", []) if not t.get("revealed")]
    if not hidden:
        return
    rng = _rng(game)
    # The Well resolves the benefits on the two tiles it covers.  A compact
    # representation keeps those tiles hidden until this action, while still
    # making the result deterministic across reconnects and saves.
    for tile in rng.sample(hidden, min(2, len(hidden))):
        tile["revealed"] = True
        tile["location"] = "well"
        back = tile.get("back")
        if back == "coin":
            _gain(game, pid, coins=2, note="well tile")
        elif back == "seal":
            _gain(game, pid, seals=1, note="well tile")
        elif back == "influence":
            _gain(game, pid, influence=1, note="well tile")
        elif back == "vp":
            _gain(game, pid, points=1, note="well tile")
        elif back in RESOURCES:
            _gain(game, pid, resource=back, amount=1, note="well tile")
        else:
            _gain(game, pid, coins=1, note="well tile")
    _save_rng(game, rng)


def _player_template() -> dict:
    return {
        "coins": 0, "seals": 0, "points": 0, "influence": 0,
        "fan_tiles": 0,
        "resources": {r: 0 for r in RESOURCES},
        "workers": {
            "courtiers": {"domain": 5, "gate": 0, "floor1": 0, "floor2": 0, "daimyo": 0},
            "warriors": {"domain": 5, "yard_pool": 0, "yard": 0},
            "gardeners": {"domain": 5, "garden_pool": 0, "garden": 0},
        },
        "domain": {c: {"die": None, "uses": 0, "card": None} for c in COLORS},
        "lantern": [], "yards": [], "gardens": [],
        "color": None, "heron_order": 0,
    }


def _die(rng, color: str) -> dict:
    return {"id": f"{color}-{rng.randrange(1000000):06d}", "color": color,
            "value": rng.randint(1, 6)}


def _rolled_bridge(rng, color: str, count: int) -> list[dict]:
    """Roll a bridge and lay its dice left-to-right in ascending order."""
    return sorted((_die(rng, color) for _ in range(count)),
                  key=lambda die: int(die["value"]))


def new_game(players: list[str], *, names: dict[str, str] | None = None,
             seed: int | None = None, max_players: int | None = None) -> dict:
    """Create a standard base-game table.

    Starting pairs are drafted through a persisted ``phase='draft'`` decision,
    which is why a newly-created room is immediately playable by a human or bot
    without a separate setup message.
    """
    seats = list(players)
    if not 2 <= len(seats) <= 4:
        raise ValueError("The Black Castle supports 2–4 seats")
    rng = random.Random(seed)
    turn_order = seats[:]
    rng.shuffle(turn_order)
    names = {pid: (names or {}).get(pid, pid) for pid in seats}
    for i, pid in enumerate(turn_order):
        names.setdefault(pid, pid)

    bridge_count = len(seats) + 1
    bridges = {color: _rolled_bridge(rng, color, bridge_count) for color in BRIDGE_ORDER}
    tiles = make_die_tiles(rng)

    steward_deck = [clone(c) for c in STEWARDS]
    diplomat_deck = [clone(c) for c in DIPLOMATS]
    daimyo_deck = [clone(c) for c in DAIMYO]
    garden_deck = [clone(c) for c in GARDENS]
    yard_deck = copy.deepcopy(TRAINING_YARDS)
    for deck in (steward_deck, diplomat_deck, daimyo_deck, garden_deck, yard_deck):
        rng.shuffle(deck)
    castle = {
        "rooms": [{"id": i, "floor": 1 if i < 3 else 2,
                   "card": (steward_deck.pop() if i < 3 else diplomat_deck.pop()),
                   "dice": []} for i in range(5)],
        "daimyo": daimyo_deck.pop(),
    }
    gardens = [{"id": i, "bridge": BRIDGE_ORDER[i],
                "plant": garden_deck.pop(), "stone": garden_deck.pop(),
                "occupants": []} for i in range(3)]
    players_state = {}
    clan_colors = ("coral", "black", "white", "gold")
    for i, pid in enumerate(seats):
        p = _player_template()
        p["color"] = clan_colors[i]
        p["heron_order"] = turn_order.index(pid)
        players_state[pid] = p

    resource_options = [clone(c) for c in STARTING_RESOURCE_CARDS]
    action_options = [clone(c) for c in STARTING_ACTION_CARDS]
    rng.shuffle(resource_options)
    rng.shuffle(action_options)
    option_count = len(seats) + 1
    draft_options = [{"resource": resource_options[i], "action": action_options[i % len(action_options)]}
                     for i in range(option_count)]
    game = {
        "schema": 1, "ruleset": RULESET, "phase": "draft", "round": 1,
        "turn_number": 0, "turn_in_round": 0, "turn_index": 0,
        "turn_pid": None, "turn_order": turn_order, "players": players_state,
        "names": names, "bridges": bridges, "die_tiles": tiles,
        "castle": castle, "outside": {}, "gardens": gardens,
        "yards": [yard_deck.pop() for _ in range(4)],
        "yard_deck": yard_deck, "garden_deck": garden_deck,
        "steward_deck": steward_deck, "diplomat_deck": diplomat_deck,
        "daimyo_deck": daimyo_deck,
        "common": {"coins": 32, "seals": 20},
        "draft_options": draft_options, "draft_queue": list(reversed(turn_order)),
        "draft_picks": {}, "pending": None, "turn_undo": None,
        "last_move": None, "log": [], "winner": None, "scores": {},
        "log_seq": 0, "rng_state": None, "max_players": max_players or len(seats),
    }
    _save_rng(game, rng)
    _log(game, f"The Black Castle opens for {len(seats)} clans.")
    _log(game, "Starting pairs are ready; choose one resource and action card.")
    return game


def is_over(game: dict | None) -> bool:
    return not game or game.get("phase") == "over"


def _end_round(game: dict) -> None:
    # The player furthest along the Passage of Time track leads the next
    # round; a marker on top of another marker breaks the tie.  Influence is
    # advanced by card/lantern actions, and checkpoint seals are paid when the
    # marker crosses a checkpoint rather than automatically at round end.
    order_index = {pid: i for i, pid in enumerate(game["turn_order"])}
    game["turn_order"] = sorted(
        game["turn_order"],
        key=lambda pid: (int(_player(game, pid).get("influence", 0)),
                         -int(_player(game, pid).get("heron_order", order_index[pid]))),
        reverse=True,
    )
    for index, pid in enumerate(game["turn_order"]):
        _player(game, pid)["heron_order"] = index
    # The garden step happens after rounds one and two. A garden card beside a
    # bridge that still has a die activates once for each clan gardener there;
    # the third round goes straight to final scoring after turn order is updated.
    if game["round"] < ROUND_COUNT:
        for occupant in game["turn_order"]:
            for garden in game["gardens"]:
                if (occupant not in garden.get("occupants", []) or
                        not game["bridges"].get(garden.get("bridge"))):
                    continue
                card = garden.get("plant") or garden.get("stone") or {}
                _apply_effects(game, occupant, card.get("light", []),
                               source=f"{card.get('name', 'garden')} round action")
    if game["round"] >= ROUND_COUNT:
        _score_game(game)
        return
    game["round"] += 1
    game["turn_in_round"] = 0
    game["turn_index"] = 0
    game["turn_pid"] = game["turn_order"][0]
    game["pending"] = None
    game["turn_undo"] = None
    rng = _rng(game)
    count = len(game["turn_order"]) + 1
    for color in BRIDGE_ORDER:
        game["bridges"][color] = _rolled_bridge(rng, color, count)
    _save_rng(game, rng)
    _log(game, f"Round {game['round']} begins; the bridges are rerolled.")


def _score_game(game: dict) -> None:
    scores = {}
    for pid, p in game["players"].items():
        score = int(p.get("points", 0))
        score += (p.get("coins", 0) + p.get("seals", 0)) // 5
        for value in p["resources"].values():
            score += 2 if value >= 7 else (1 if value >= 3 else 0)
        influence = int(p.get("influence", 0))
        # The four seasons on the printed track award 0/3/6 points, then the
        # value printed on the final-season space (10–15).  The digital track
        # stores the marker position directly, so this remains deterministic
        # even when a card moves it more than one step.
        if influence >= 11:
            score += min(15, influence)
        elif influence >= 10:
            score += 6
        elif influence >= 6:
            score += 3
        c = p["workers"]["courtiers"]
        score += c.get("gate", 0) + 3 * c.get("floor1", 0) + 6 * c.get("floor2", 0) + 10 * c.get("daimyo", 0)
        castle_courtiers = (c.get("floor1", 0) + c.get("floor2", 0) +
                            c.get("daimyo", 0))
        # Every warrior scores the value printed on its yard, multiplied by
        # the number of that clan's courtiers inside the castle (not at the
        # gate).  ``yards`` stores one card per placed warrior.
        if castle_courtiers and p.get("yards"):
            score += sum(int(y.get("vp", 0)) for y in p["yards"]) * castle_courtiers
        score += sum(int(g.get("vp", 0)) for g in p.get("gardens", []))
        scores[pid] = score
        p["final_score"] = score
    game["scores"] = scores
    best = max(scores.values()) if scores else 0
    winners = [pid for pid, score in scores.items() if score == best]
    winners.sort(key=lambda pid: game["turn_order"].index(pid))
    game["winner"] = winners[0] if winners else None
    game["phase"] = "over"
    game["pending"] = None
    game["turn_pid"] = None
    _log(game, f"The castle is scored: {best} points wins.", kind="score")


def final_scores(game: dict) -> dict[str, int]:
    """Return the final score map, or the score currently visible to a replay."""
    if isinstance(game.get("scores"), dict) and game.get("scores"):
        return {str(pid): int(score) for pid, score in game["scores"].items()}
    probe = copy.deepcopy(game)
    _score_game(probe)
    return {str(pid): int(score) for pid, score in probe.get("scores", {}).items()}


def winner(game: dict) -> str | None:
    """Return the winning seat, using turn order as the tie breaker."""
    if game.get("winner") in game.get("players", {}):
        return game.get("winner")
    scores = final_scores(game)
    if not scores:
        return None
    best = max(scores.values())
    for pid in game.get("turn_order", []):
        if scores.get(pid) == best:
            return pid
    return next(iter(scores), None)


def validate_state(game: dict) -> None:
    """Assert the invariants needed by save/load, bots, and browser views."""
    if not isinstance(game, dict):
        raise AssertionError("game must be a dict")
    players = game.get("players", {})
    if not 2 <= len(players) <= 4:
        raise AssertionError("Black Castle has 2–4 seats")
    if set(game.get("turn_order", [])) != set(players):
        raise AssertionError("turn order must contain every seat exactly once")
    if game.get("phase") not in {"draft", "play", "over"}:
        raise AssertionError("unknown game phase")
    for pid, player in players.items():
        if not 0 <= int(player.get("coins", 0)):
            raise AssertionError(f"negative coins for {pid}")
        if not 0 <= int(player.get("seals", 0)) <= MAX_SEALS:
            raise AssertionError(f"invalid seals for {pid}")
        if not 0 <= int(player.get("influence", 0)) <= MAX_INFLUENCE:
            raise AssertionError(f"invalid influence for {pid}")
        for resource in RESOURCES:
            if not 0 <= int(player.get("resources", {}).get(resource, 0)) <= MAX_RESOURCE:
                raise AssertionError(f"invalid {resource} for {pid}")
        for worker, places in player.get("workers", {}).items():
            if worker not in WORKERS:
                raise AssertionError(f"unknown worker type {worker}")
            if any(int(value) < 0 for value in places.values()):
                raise AssertionError(f"negative {worker} count for {pid}")
            if sum(int(value) for value in places.values()) != 5:
                raise AssertionError(f"worker count drift for {pid}/{worker}")
    pending = game.get("pending")
    if pending is not None and pending.get("pid") not in players:
        raise AssertionError("pending choice belongs to an unknown seat")


def _draft_moves(game: dict, pid: str) -> list[dict]:
    if not game.get("draft_queue") or game["draft_queue"][0] != pid:
        return []
    return [{"type": "draft", "index": i} for i in range(len(game.get("draft_options", [])))]


def _space_moves(game: dict, pid: str, die: dict) -> list[dict]:
    p = _player(game, pid)
    value = int(die.get("value", 0))
    moves: list[dict] = []
    def add(space: str) -> None:
        target = _die_value_target(game, space)
        if value >= target or p.get("coins", 0) >= target - value:
            moves.append({"type": "place_die", "space": space})
    # Castle rooms: one die in 2p, one die plus a stack in 3/4p.
    for room in game["castle"]["rooms"]:
        occupied = room.get("dice", [])
        if len(occupied) < (1 if len(game["players"]) <= 2 else 2):
            add(f"castle:{room['id']}")
    for i in range(2):
        if not game.get("outside", {}).get(str(i)):
            add(f"outside:{i}")
    add("well")
    for color in COLORS:
        slot = p["domain"][color]
        if slot.get("die") is None and slot.get("uses", 0) == 0:
            add(f"domain:{color}")
    # Training yards and gardens are reached by their worker actions, not by
    # placing a die directly.  A high die can always use the main board; its
    # value is compared to the printed value by _place_die.
    return moves


def _convert_moves(game: dict, pid: str) -> list[dict]:
    p = _player(game, pid)
    return ([{"type": "convert", "from": r, "to": "coin"}
             for r in RESOURCES if p["resources"].get(r, 0) >= 2]
            + ([{"type": "convert", "from": "seal", "to": "coin"}]
               if p.get("seals", 0) else [])
            + ([{"type": "convert", "from": "seals", "to": r}
                for r in RESOURCES if p.get("seals", 0) >= 2]))


def _worker_destination_moves(game: dict, pid: str, worker: str) -> list[dict]:
    p = _player(game, pid)
    if worker == "warriors":
        return [{"type": "worker_destination", "worker": worker, "index": i}
                for i, yard in enumerate(game.get("yards", []))
                if p["resources"].get("iron", 0) >= int(yard.get("cost", 0))]
    if worker == "gardeners":
        return [{"type": "worker_destination", "worker": worker, "index": i}
                for i, garden in enumerate(game.get("gardens", []))
                if (garden.get("plant") or garden.get("stone")) and
                pid not in garden.get("occupants", []) and
                p["resources"].get("food", 0) >= int((garden.get("plant") or garden.get("stone")).get("cost", 0))]
    return []


def legal_moves(game: dict | None, pid: str) -> list[dict]:
    if not game or pid not in game.get("players", {}) or is_over(game):
        return []
    pending = game.get("pending")
    if game.get("phase") == "draft":
        return _draft_moves(game, pid)
    if pending:
        if pending.get("pid") != pid:
            return []
        kind = pending.get("kind")
        if kind == "place_die":
            return _space_moves(game, pid, pending["die"])
        if kind == "outside_worker":
            p = _player(game, pid)
            choices = []
            for worker in ("warriors", "gardeners"):
                if (p["workers"][worker].get("domain", 0) > 0 and
                        _worker_destination_moves(game, pid, worker)):
                    choices.append({"type": "outside_worker", "worker": worker})
            if p["workers"]["courtiers"].get("domain", 0) > 0:
                if p.get("coins", 0) >= 2:
                    choices.append({"type": "outside_worker", "worker": "courtiers", "action": "audience"})
                if legal_moves({**game, "pending": {"pid": pid, "kind": "courtier_destination"}}, pid):
                    choices.append({"type": "outside_worker", "worker": "courtiers", "action": "climb"})
            return choices
        if kind == "worker_destination":
            return _worker_destination_moves(game, pid, pending.get("worker", ""))
        if kind == "courtier_destination":
            p = _player(game, pid)
            choices = []
            if p["workers"]["courtiers"].get("gate", 0) and p["resources"].get("pearl", 0) >= 2:
                choices.append({"type": "courtier_destination", "to": "floor1", "cost": 2})
                if p["resources"].get("pearl", 0) >= 5:
                    choices.append({"type": "courtier_destination", "to": "floor2", "cost": 5})
            if p["workers"]["courtiers"].get("floor1", 0) and p["resources"].get("pearl", 0) >= 2:
                choices.append({"type": "courtier_destination", "to": "floor2", "cost": 2})
            if p["workers"]["courtiers"].get("floor2", 0) and p["resources"].get("pearl", 0) >= 5:
                choices.append({"type": "courtier_destination", "to": "daimyo", "cost": 5})
            return choices
        if kind == "end_turn":
            return [{"type": "end_turn"}] + _convert_moves(game, pid)
        if kind == "convert":
            return _convert_moves(game, pid)
        return []
    if game.get("turn_pid") != pid:
        return []
    return [{"type": "take_die", "bridge": color, "side": side}
            for color in BRIDGE_ORDER for side in ("left", "right")
            if game["bridges"].get(color)] + (
                _convert_moves(game, pid)
            )


def _begin_turn(game: dict, pid: str) -> None:
    p = _player(game, pid)
    for slot in p["domain"].values():
        slot["uses"] = 0
        # Domain dice are action markers for the current turn.  They return to
        # the bridge at the end of the action, as in the physical board.
        slot["die"] = None
    game["turn_undo"] = {
        # The move log can be capped for the wire, so keep a monotonic position
        # instead of duplicating the entire log inside every undo snapshot.
        "pid": pid,
        "state": copy.deepcopy({k: v for k, v in game.items()
                                if k not in {"turn_undo", "log"}}),
        "log_pos": int(game.get("log_seq", 0)), "revealed": False,
    }


def _die_value_target(game: dict, space: str) -> int:
    if space.startswith("castle:"):
        idx = int(space.split(":")[1])
        room = game["castle"]["rooms"][idx]
        return 3 if room["floor"] == 1 else 4
    if space.startswith("outside:"):
        return 5
    if space == "well":
        return 1
    if space.startswith("domain:"):
        return 6
    if space.startswith("yard:") or space.startswith("garden:"):
        return 5
    return 0


def _settle_die_value(game: dict, pid: str, die: dict, space: str) -> bool:
    target = _die_value_target(game, space)
    delta = int(die.get("value", 0)) - target
    if delta < 0 and not _pay(game, pid, coins=-delta):
        return False
    if delta > 0:
        _gain(game, pid, coins=delta, note="die value")
    return True


def _resolve_castle(game: dict, pid: str, room_index: int, die: dict) -> None:
    room = game["castle"]["rooms"][room_index]
    card = room.get("card") or {}
    mode = "light" if (int(die.get("value", 0)) + room_index) % 2 == 0 else "dark"
    effects = card.get(mode, [])
    _apply_effects(game, pid, effects, source=f"{card.get('name', 'castle')} {mode} action")
    game["last_move"]["card"] = card.get("id")


def _resolve_domain(game: dict, pid: str, color: str) -> None:
    p = _player(game, pid)
    slot = p["domain"][color]
    slot["uses"] = 1
    _gain(game, pid, resource=RESOURCE_FOR_COLOR[color], amount=1, note="personal domain")
    # The drafted action card remains in the domain until a courtier moves it
    # into the Lantern Area. Its light-side action is therefore available each
    # time the matching personal-domain row is activated.
    action_card = p.get("action_card")
    if action_card:
        _apply_effects(game, pid, action_card.get("light", []),
                       source=f"{action_card.get('name', 'domain')} action")
    _log(game, f"{_name(game, pid)} activates the {color} domain row.", pid=pid)


def _resolve_lantern(game: dict, pid: str) -> None:
    p = _player(game, pid)
    if not p.get("lantern"):
        return
    for reward in p["lantern"]:
        icon, amount = reward.get("icon"), int(reward.get("amount", 1))
        if icon == "coin":
            _gain(game, pid, coins=amount, note="lantern")
        elif icon == "vp":
            _gain(game, pid, points=amount, note="lantern")
        elif icon == "seal":
            _gain(game, pid, seals=amount, note="lantern")
        elif icon == "influence":
            _gain(game, pid, influence=amount, note="lantern")
        elif icon in RESOURCES:
            _gain(game, pid, resource=icon, amount=amount, note="lantern")


def _place_die(game: dict, pid: str, space: str) -> tuple[bool, str | None]:
    pending = game.get("pending") or {}
    die = pending.get("die")
    if not isinstance(die, dict):
        return False, "no die is waiting to be placed"
    legal = _space_moves(game, pid, die)
    if {"type": "place_die", "space": space} not in legal:
        return False, "that destination is not legal"
    if not _settle_die_value(game, pid, die, space):
        return False, "not enough coins to pay the die value"
    game["last_move"] = {"type": "place_die", "space": space,
                          "die": copy.deepcopy(die), "pid": pid}
    game["pending"] = None
    if pending.get("side") == "left":
        _resolve_lantern(game, pid)
    if space.startswith("castle:"):
        idx = int(space.split(":")[1])
        game["castle"]["rooms"][idx].setdefault("dice", []).append(die)
        _resolve_castle(game, pid, idx, die)
    elif space.startswith("outside:"):
        game.setdefault("outside", {})[space.split(":")[1]] = {"pid": pid, "die": die}
        choices = legal_moves({**game, "pending": {"pid": pid, "kind": "outside_worker"}}, pid)
        if choices:
            game["pending"] = {"pid": pid, "kind": "outside_worker", "space": space}
    elif space == "well":
        _gain(game, pid, seals=1, note="well")
        _well_bonus(game, pid)
        game["turn_undo"]["revealed"] = True
    elif space.startswith("domain:"):
        color = space.split(":")[1]
        _player(game, pid)["domain"][color]["die"] = copy.deepcopy(die)
        _resolve_domain(game, pid, color)
    if not game.get("pending"):
        game["pending"] = {"pid": pid, "kind": "end_turn"}
    return True, None


def _finish_draft(game: dict) -> None:
    game["phase"] = "play"
    game["round"] = 1
    game["turn_in_round"] = 0
    game["turn_index"] = 0
    game["turn_pid"] = game["turn_order"][0]
    game["turn_number"] = 1
    game["draft_options"] = []
    game["draft_queue"] = []
    _log(game, f"Round 1 begins. {_name(game, game['turn_pid'])} has the first turn.")


def _apply_draft(game: dict, pid: str, index: int) -> tuple[bool, str | None]:
    moves = _draft_moves(game, pid)
    move = {"type": "draft", "index": index}
    if move not in moves:
        return False, "choose one of the face-up starting pairs"
    option = game["draft_options"][index]
    p = _player(game, pid)
    p["starting_pair"] = {"resource": option["resource"]["id"], "action": option["action"]["id"]}
    p["action_card"] = clone(option["action"])
    _apply_effects(game, pid, option["resource"].get("light", []), source="starting resource")
    # The resource card is turned over into the Lantern Area.  Its back is the
    # first visible lantern reward; the action card remains on the personal
    # Domain until a later action activates it.
    back = option["resource"].get("back")
    if back in RESOURCES or back in {"coin", "seal", "influence", "vp"}:
        p["lantern"].append({"icon": back, "amount": 1, "card": option["resource"]["id"]})
    else:
        p["lantern"].append({"icon": "coin", "amount": 1, "card": option["resource"]["id"]})
    game["draft_picks"][pid] = index
    # A starting pair is drafted from the shared face-up row. Remove it before
    # the next seat acts so two clans can never take the same pair. The final
    # unchosen pair is discarded when the draft closes.
    game["draft_options"].pop(index)
    game["draft_queue"].pop(0)
    _log(game, f"{_name(game, pid)} drafts {option['resource']['name']} + {option['action']['name']}.", pid=pid)
    if not game["draft_queue"]:
        _finish_draft(game)
    return True, None


def _undo(game: dict, pid: str) -> tuple[bool, str | None]:
    turn_undo = game.get("turn_undo")
    if not turn_undo or turn_undo.get("pid") != pid or turn_undo.get("revealed"):
        return False, "undo is unavailable after a hidden well benefit"
    snapshot = copy.deepcopy(turn_undo.get("state"))
    if not isinstance(snapshot, dict):
        return False, "undo snapshot is unavailable"
    if "log" not in snapshot:
        log_pos = int(turn_undo.get("log_pos", 0))
        snapshot["log"] = [copy.deepcopy(entry) for entry in game.get("log", [])
                            if int(entry.get("seq", 0)) <= log_pos]
    else:
        # Compatibility for pre-position snapshots written by an early build.
        log_len = int(turn_undo.get("log_len", len(snapshot.get("log", []))))
        snapshot["log"] = snapshot.get("log", [])[:log_len]
    game.clear()
    game.update(snapshot)
    game["turn_undo"] = None
    return True, None


def _end_turn(game: dict, pid: str) -> tuple[bool, str | None]:
    if game.get("pending", {}).get("kind") != "end_turn" or game.get("pending", {}).get("pid") != pid:
        return False, "finish the current action first"
    game["pending"] = None
    game["turn_undo"] = None
    game["turn_in_round"] += 1
    game["turn_number"] += 1
    if game["turn_in_round"] >= len(game["turn_order"]) * TURNS_PER_ROUND:
        _end_round(game)
        return True, None
    game["turn_index"] = (game["turn_index"] + 1) % len(game["turn_order"])
    game["turn_pid"] = game["turn_order"][game["turn_index"]]
    return True, None


def _convert(game: dict, pid: str, source: str, target: str = "coin") -> tuple[bool, str | None]:
    p = _player(game, pid)
    if source == "seal":
        if p.get("seals", 0) < 1:
            return False, "you have no seal to trade"
        p["seals"] -= 1
        _gain(game, pid, coins=1, note="seal trade")
        return True, None
    if source == "seals":
        if target not in RESOURCES or p.get("seals", 0) < 2:
            return False, "two Daimyo Seals are required for that trade"
        p["seals"] -= 2
        _gain(game, pid, resource=target, amount=1, note="seal trade")
        return True, None
    if source not in RESOURCES or p["resources"].get(source, 0) < 2:
        return False, "two resources are required for that trade"
    p["resources"][source] -= 2
    _gain(game, pid, coins=1, note=f"{source} trade")
    return True, None


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    """Validate and apply one move. Returns ``(ok, error)``."""
    if not isinstance(move, dict) or pid not in game.get("players", {}):
        return False, "invalid move"
    kind = move.get("type")
    if kind == "undo":
        return _undo(game, pid)
    if game.get("phase") == "draft":
        if kind != "draft":
            return False, "choose a starting pair first"
        try:
            index = int(move.get("index"))
        except (TypeError, ValueError):
            return False, "invalid starting pair"
        return _apply_draft(game, pid, index)
    if is_over(game):
        return False, "the game is over"
    if kind == "take_die":
        if game.get("pending") or game.get("turn_pid") != pid:
            return False, "it is not time to take a die"
        color = move.get("bridge")
        side = move.get("side")
        if color not in BRIDGE_ORDER or side not in {"left", "right"} or not game["bridges"].get(color):
            return False, "choose an end die on a bridge"
        _begin_turn(game, pid)
        bridge = game["bridges"][color]
        die = bridge.pop(0 if side == "left" else -1)
        game["pending"] = {"pid": pid, "kind": "place_die", "die": die,
                           "bridge": color, "side": side}
        _log(game, f"{_name(game, pid)} takes the {die['value']} {color} die.", pid=pid, kind="die")
        return True, None
    if kind == "place_die":
        if game.get("pending", {}).get("pid") != pid or game.get("pending", {}).get("kind") != "place_die":
            return False, "choose a die before placing it"
        return _place_die(game, pid, str(move.get("space", "")))
    if kind == "outside_worker":
        pending = game.get("pending") or {}
        if pending.get("pid") != pid or pending.get("kind") != "outside_worker":
            return False, "choose a worker for the outside space"
        worker = move.get("worker")
        if worker not in {"warriors", "gardeners", "courtiers"}:
            return False, "choose a courtier, gardener, or warrior"
        p = _player(game, pid)
        if p["workers"][worker].get("domain", 0) <= 0:
            return False, "that worker is not in your domain"
        if worker == "courtiers":
            action = move.get("action")
            if action == "audience":
                if not _pay(game, pid, coins=2):
                    return False, "an audience costs 2 coins"
                _move_worker(game, pid, worker, "gate")
                _log(game, f"{_name(game, pid)} requests an audience at the gate.", pid=pid)
                game["pending"] = {"pid": pid, "kind": "end_turn"}
            elif action == "climb":
                destinations = legal_moves({**game, "pending": {"pid": pid, "kind": "courtier_destination"}}, pid)
                if not destinations:
                    return False, "no courtier can climb yet"
                game["pending"] = {"pid": pid, "kind": "courtier_destination", "space": pending.get("space")}
            else:
                return False, "choose an audience or a social climb"
        else:
            destination = "yard_pool" if worker == "warriors" else "garden_pool"
            _move_worker(game, pid, worker, destination)
            _log(game, f"{_name(game, pid)} sends a {worker[:-1]} outside the walls.", pid=pid)
            game["pending"] = {"pid": pid, "kind": "worker_destination", "worker": worker,
                                "space": pending.get("space")}
        return True, None
    if kind == "worker_destination":
        pending = game.get("pending") or {}
        if pending.get("pid") != pid or pending.get("kind") != "worker_destination":
            return False, "choose a worker destination"
        worker = pending.get("worker")
        try:
            index = int(move.get("index"))
        except (TypeError, ValueError):
            return False, "invalid worker destination"
        if {"type": "worker_destination", "worker": worker, "index": index} not in _worker_destination_moves(game, pid, worker):
            return False, "that worker destination is not legal"
        p = _player(game, pid)
        if worker == "warriors":
            yard = game["yards"][index]
            _pay(game, pid, resource="iron", amount=int(yard.get("cost", 0)))
            p["workers"][worker]["yard_pool"] -= 1
            p["workers"][worker]["yard"] += 1
            p["yards"].append(copy.deepcopy(yard))
            _apply_effects(game, pid, yard.get("effect", []), source="training yard")
        elif worker == "gardeners":
            garden = game["gardens"][index]
            card = garden.get("plant") or garden.get("stone")
            _pay(game, pid, resource="food", amount=int(card.get("cost", 0)))
            p["workers"][worker]["garden_pool"] -= 1
            p["workers"][worker]["garden"] += 1
            garden.setdefault("occupants", []).append(pid)
            p["gardens"].append(copy.deepcopy(card))
            _apply_effects(game, pid, card.get("light", []), source=card.get("name", "garden"))
        game["pending"] = {"pid": pid, "kind": "end_turn"}
        return True, None
    if kind == "courtier_destination":
        pending = game.get("pending") or {}
        if pending.get("pid") != pid or pending.get("kind") != "courtier_destination":
            return False, "choose a courtier destination"
        to = str(move.get("to"))
        try:
            cost = int(move.get("cost", 0))
        except (TypeError, ValueError):
            return False, "invalid courtier cost"
        if move not in legal_moves(game, pid):
            return False, "that social climb is not legal"
        if not _pay(game, pid, resource="pearl", amount=cost):
            return False, "not enough mother-of-pearl"
        if not _move_courtier(game, pid, to):
            return False, "no courtier can make that climb"
        _log(game, f"{_name(game, pid)} climbs to the {to}.", pid=pid)
        game["pending"] = {"pid": pid, "kind": "end_turn"}
        return True, None
    if kind == "convert":
        if game.get("pending"):
            pending = game["pending"]
            if pending.get("pid") != pid:
                return False, "it is not your turn"
            if pending.get("kind") not in {"end_turn", "convert"}:
                return False, "finish the current action first"
        elif game.get("turn_pid") != pid:
            return False, "it is not your turn"
        return _convert(game, pid, str(move.get("from")), str(move.get("to", "coin")))
    if kind == "end_turn":
        return _end_turn(game, pid)
    return False, "unknown move"


def player_view(game: dict | None, viewer_pid: str | None) -> dict | None:
    """Return a recipient-safe state snapshot with legal moves for one seat."""
    if game is None:
        return None
    view = copy.deepcopy(game)
    view.pop("rng_state", None)
    view.pop("turn_undo", None)
    view.pop("steward_deck", None)
    view.pop("diplomat_deck", None)
    view.pop("daimyo_deck", None)
    view.pop("garden_deck", None)
    view.pop("yard_deck", None)
    # Die tiles are face-down in the Well until a player resolves that space.
    # Their backs are a private future reward and must not travel over the
    # websocket to another seat.
    view["die_tiles"] = []
    for tile in game.get("die_tiles", []):
        public_tile = copy.deepcopy(tile)
        if not tile.get("revealed"):
            public_tile["back"] = None
            public_tile["id"] = None
            public_tile["number"] = None
        view["die_tiles"].append(public_tile)
    view["decks"] = {
        "steward": len(game.get("steward_deck", [])),
        "diplomat": len(game.get("diplomat_deck", [])),
        "daimyo": len(game.get("daimyo_deck", [])),
        "garden": len(game.get("garden_deck", [])),
        "yard": len(game.get("yard_deck", [])),
    }
    view["viewer"] = viewer_pid
    view["legal_moves"] = legal_moves(game, viewer_pid) if viewer_pid else []
    view["can_undo"] = bool(game.get("turn_undo") and game["turn_undo"].get("pid") == viewer_pid
                             and not game["turn_undo"].get("revealed"))
    pending = game.get("pending")
    if pending and pending.get("pid") != viewer_pid:
        view["pending"] = {"pid": pending.get("pid"), "kind": pending.get("kind")}
    return view
