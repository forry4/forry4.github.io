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
                    STEWARDS, TRAINING_YARDS, WELL_DIE_TILES, WORKERS, clone,
                    make_die_tiles)

RULESET = "base-2023"
ROUND_COUNT = 3
TURNS_PER_ROUND = 3
MAX_RESOURCE = 7
MAX_SEALS = 5
# The Passage of Time runs 0-20: three seasons of 6/5/4 spaces and then the fourth,
# whose six spaces are the only ones with a printed score. See `_influence_points`.
MAX_INFLUENCE = 20
# The three season gates on the printed Passage of Time track. A marker may
# cross a gate only after paying the corresponding Daimyo Seal cost. The keys are the
# space being ENTERED. Read straight off the corpus: a marker that does not pay stops
# dead on 5, 10 or 14 (BGA sends the move with `steps: 0`), and the crossings that did
# happen paid 1, 2 and 3 seals respectively.
CHECKPOINT_COSTS = {6: 1, 11: 2, 15: 3}
#: Dice one castle room or Outside the Walls space accepts, by seat count. A room takes
#: two at three or four players -- but "in a 1- or 2-player game, dice cannot be stacked
#: on top of other dice in ANY part of the game", so every such space takes one instead.
#: The corpus cannot see this (it has no 2-player games) and an earlier pass "fixed" the
#: seat-count check away on the reasoning that board printing does not shrink. It is not
#: the printing that shrinks; it is a separate 2-player rule.
CASTLE_ROOM_DICE = 2
SOLO_OR_DUEL_DICE = 1

#: Which worker each Outside the Walls space offers, beside the Courtier action both
#: carry. "Perform 1 of the 2 actions indicated by the space it is placed in."
OUTSIDE_WORKERS = ("gardeners", "warriors")
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
    """Advance the Passage of Time marker, paying its checkpoint seals.

    A marker that moves lands ON TOP of whatever is already on its new space, and that
    height decides turn order when two clans tie -- so every move stamps a rising counter
    onto the mover. The counter is game state rather than a derived value because the
    stack is not recoverable from the positions alone.
    """
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
    if moved:
        game["influence_seq"] = int(game.get("influence_seq", 0)) + 1
        p["influence_stack"] = game["influence_seq"]
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


#: The castle, bottom to top. The index is the floor, which is what a climb is priced on.
CASTLE_FLOORS = ("gate", "floor1", "floor2", "daimyo")

#: Mother-of-pearl to move a courtier up, by how many floors it climbs. One printed pair
#: of costs for the whole castle -- not a per-room price -- so floor2 -> daimyo costs the
#: same 2 as gate -> floor1, and floor1 -> daimyo costs the same 5 as gate -> floor2.
CLIMB_COSTS = {1: 2, 2: 5}


def _move_courtier(game: dict, pid: str, source: str, destination: str) -> bool:
    p = _player(game, pid)
    c = p["workers"]["courtiers"]
    if source not in CASTLE_FLOORS or destination not in CASTLE_FLOORS:
        return False
    if CASTLE_FLOORS.index(destination) <= CASTLE_FLOORS.index(source):
        return False
    if c.get(source, 0) <= 0:
        return False
    c[source] -= 1
    c[destination] = c.get(destination, 0) + 1
    return True


#: Which castle rooms stand on which floor. Rooms 0-2 are the Steward rooms on the first
#: floor and 3-4 the Diplomat rooms on the second; the Daimyo hall has no room card.
FLOOR_ROOMS = {"floor1": (0, 1, 2), "floor2": (3, 4)}


def _rooms_on(game: dict, floor: str) -> list[int]:
    return [i for i in FLOOR_ROOMS.get(floor, ())
            if i < len(game.get("castle", {}).get("rooms", []))
            and (game["castle"]["rooms"][i] or {}).get("card")]


def _climb_moves(game: dict, pid: str) -> list[dict]:
    """Every social climb this clan could pay for right now.

    The SOURCE is named in the move rather than inferred, because one destination can be
    reached from two floors at two different prices -- a courtier at the gate pays 5 to
    reach the second floor while one already on the first pays 2 -- and picking the lowest
    occupied floor for the player would quietly spend the wrong courtier and the wrong
    price.

    The ROOM is named too, because climbing INTO a room takes that room's card. The
    corpus is unambiguous about it: across 414 climbs where both were observable, the card
    gained was the card standing in the room climbed into, every single time.
    """
    p = _player(game, pid)
    c = p["workers"]["courtiers"]
    pearl = p["resources"].get("pearl", 0)
    moves = []
    for i, source in enumerate(CASTLE_FLOORS[:-1]):
        if c.get(source, 0) <= 0:
            continue
        for levels, cost in sorted(CLIMB_COSTS.items()):
            j = i + levels
            if j >= len(CASTLE_FLOORS) or pearl < cost:
                continue
            destination = CASTLE_FLOORS[j]
            rooms = _rooms_on(game, destination)
            if rooms:
                moves.extend({"type": "courtier_destination", "from": source,
                              "to": destination, "cost": cost, "room": room}
                             for room in rooms)
            else:
                # The Daimyo hall is a floor without room cards.
                moves.append({"type": "courtier_destination", "from": source,
                              "to": destination, "cost": cost})
    return moves


#: The resource a player may pick when a card says "gain a resource" without naming one.
ANY_RESOURCE = "any"


def _queue_resource_choice(game: dict, pid: str, amount: int, source: str) -> None:
    """A card that grants ANY resource asks the player, it does not pick for them.

    Ten of the sixty-eight cards say `Gain <resource> N` with no resource named, and the
    generator keeps that as `resource: "any"` precisely so it cannot be quietly resolved
    into food every time. Each unit is queued as its own choice: "gain 3 resources" is
    three separate picks, because nothing says they have to match.
    """
    queue = game.setdefault("choice_queue", [])
    for _ in range(max(0, int(amount))):
        queue.append({"pid": pid, "source": source})


def _promote_choice(game: dict, pid: str) -> bool:
    """Turn the next queued resource choice into the live pending, if there is one.

    Called wherever an action finishes. A queued choice outranks `end_turn` -- a player
    must spend what a card gave them before the turn can close -- but it never displaces
    a pending that is already mid-decision.
    """
    queue = game.get("choice_queue") or []
    if not queue:
        return False
    pending = game.get("pending")
    if pending and pending.get("kind") not in ("end_turn", "choose_resource"):
        return False
    head = queue[0]
    game["pending"] = {"pid": head.get("pid", pid), "kind": "choose_resource",
                       "source": head.get("source", "action")}
    return True


def _apply_effects(game: dict, pid: str, effects: list[dict], *, source: str = "action") -> None:
    for effect in effects or []:
        op = effect.get("op")
        if op == "gain":
            resource = effect.get("resource")
            if resource == ANY_RESOURCE:
                _queue_resource_choice(game, pid, int(effect.get("amount", 1)), source)
                continue
            _gain(game, pid, resource=resource,
                  amount=int(effect.get("amount", 1)) if resource else 0,
                  coins=int(effect.get("coins", 0)), seals=int(effect.get("seals", 0)),
                  points=int(effect.get("points", 0)), influence=int(effect.get("influence", 0)),
                  note=source)
        elif op == "passage":
            # BGA's "Passage of Time" IS our influence track -- one name for one track.
            _gain(game, pid, influence=int(effect.get("steps", 1)), note=source)
        elif op == "lantern_rewards":
            _resolve_lantern(game, pid)
        elif op == "well_action":
            _gain(game, pid, seals=1, note=source)
            _well_bonus(game, pid)
        elif op == "decree":
            # A decree card carries no action block at all: it is a pure Lantern reward,
            # one each of coin / seal / vp, which is exactly the three icons the printed
            # `Gain <icon> Decree Card` texts name.
            icon = str(effect.get("icon", "coin"))
            game["players"][pid]["lantern"].append({"icon": icon, "amount": 1, "card": "decree"})
            _log(game, f"{_name(game, pid)} takes the {icon} Decree card.", pid=pid)
        elif op == "worker_action":
            _perform_worker_action(game, pid, effect, source)
        elif op in ("domain_action", "main_board_action"):
            # Yard-tile vocabulary. No tile resolves through here yet, so reaching this
            # branch means a tile action was wired up without its implementation -- say so
            # rather than silently doing nothing.
            _log(game, f"{_name(game, pid)} has a tile action that is not implemented "
                       f"({op}).", pid=pid)
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
            elif worker == "courtiers" and destination in CASTLE_FLOORS:
                target = CASTLE_FLOORS.index(destination)
                source = next((place for place in CASTLE_FLOORS[:target]
                               if _player(game, pid)["workers"]["courtiers"].get(place, 0) > 0), None)
                moved = bool(source) and _move_courtier(game, pid, source, destination)
            elif worker in WORKERS and destination:
                moved = _move_worker(game, pid, worker, destination)
            if moved:
                _log(game, f"{_name(game, pid)} moves a {worker[:-1]} to {destination}.", pid=pid)
        elif op == "pay_seal_for_worker":
            # The pre-catalogue spelling, kept so a game saved before 2026-09-20 still
            # resolves its cards. New data never emits it.
            _perform_worker_action(
                game, pid, {"worker": effect.get("worker", "courtiers"),
                            "cost": {"seals": 1}}, source)
        elif op == "lantern":
            icon = effect.get("icon", "coin")
            game["players"][pid]["lantern"].append({"icon": icon, "amount": int(effect.get("amount", 1))})
        elif op == "well_bonus":
            _well_bonus(game, pid)


#: Where each worker goes when its action is performed. Warriors and gardeners land in a
#: short-lived pool until the player picks the actual yard or garden card.
_WORKER_DESTINATION = {"courtiers": "gate", "warriors": "yard_pool",
                       "gardeners": "garden_pool"}


def _perform_worker_action(game: dict, pid: str, effect: dict, source: str) -> None:
    """Deploy one worker, paying the card's price first if it names one.

    THE PRICE IS A CURRENCY, NOT A NUMBER. A castle card charges SEALS to repeat a worker
    action and a yard tile charges COINS, and both arrive in BGA's payload as the same
    `qty` beside an icon -- so the catalogue keeps `cost` as {currency: amount} and this
    pays whatever it names. Flattening the two would bill a tile's 3 coins to the seal
    track, which a player would feel and no test would obviously catch.
    """
    worker = effect.get("worker", "courtiers")
    destination = _WORKER_DESTINATION.get(worker, "gate")
    p = game.get("players", {}).get(pid)
    if not p or p.get("workers", {}).get(worker, {}).get("domain", 0) <= 0:
        return
    cost = effect.get("cost") or {}
    coins, seals = int(cost.get("coins", 0)), int(cost.get("seals", 0))
    if (coins or seals) and not _pay(game, pid, coins=coins, seals=seals):
        _log(game, f"{_name(game, pid)} cannot afford the {worker[:-1]} action.", pid=pid)
        return
    if not _move_worker(game, pid, worker, destination):
        return
    price = " for ".join(
        bit for bit in (
            f"{coins} coin" + ("s" if coins != 1 else "") if coins else "",
            f"{seals} seal" + ("s" if seals != 1 else "") if seals else "") if bit)
    _log(game, f"{_name(game, pid)} deploys a {worker[:-1]}"
               + (f" for {price}" if price else "") + ".", pid=pid)


def _well_bonus(game: dict, pid: str) -> None:
    """Resolve the Well's own two tiles.

    The Well's reward is PUBLIC AND FIXED, not a draw. At setup the two leftover die
    tiles are laid at the Well dice-side DOWN, so their benefit side faces up and stays
    face up all game: every visit to the Well pays 1 Daimyo Seal plus those same two
    benefits. The corpus shows exactly that -- four visits in one game all paid
    `iron +1, pearl +1, seal +1`, and no game ever paid two different things.

    This used to reveal two random hidden tiles instead, which made the Well a lottery,
    made the reward secret, consumed the tiles so later visits paid less, and needed an
    invented "revealing locks undo" rule to stay honest about it. None of that is the
    game: with nothing hidden there is nothing to lock.
    """
    for tile in game.get("well_tiles") or ():
        reward = tile.get("reward")
        if reward == "coin":
            _gain(game, pid, coins=2, note="well tile")
        elif reward == "seal":
            _gain(game, pid, seals=1, note="well tile")
        elif reward == "influence":
            _gain(game, pid, influence=1, note="well tile")
        elif reward == "vp":
            _gain(game, pid, points=1, note="well tile")
        elif reward in RESOURCES:
            _gain(game, pid, resource=reward, amount=1, note="well tile")


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
        # Where this clan's Passage of Time marker sits in its space's pile. Set up so
        # the starting player is on TOP, which is how the printed setup stacks them.
        "color": None, "heron_order": 0, "influence_stack": 0,
    }


def _die(rng, color: str) -> dict:
    return {"id": f"{color}-{rng.randrange(1000000):06d}", "color": color,
            "value": rng.randint(1, 6)}


def _rolled_bridge(rng, color: str, count: int) -> list[dict]:
    """Roll a bridge and lay its dice left-to-right in ascending order."""
    return sorted((_die(rng, color) for _ in range(count)),
                  key=lambda die: int(die["value"]))


#: How many Die tiles each castle room holds -- which is ONE PER ACTION BLOCK of the card
#: that stands there. Every printed Steward card has exactly 3 blocks and every Diplomat
#: exactly 2, and the corpus independently puts 3 tiles in a steward room and 2 in a
#: diplomat room (see `bga_parity.die_tile_bag`). Two derivations, different evidence,
#: same geometry: 3*3 + 2*2 = 13 in the castle and the last 2 at the Well.
ROOM_TILE_COUNT = (3, 3, 3, 2, 2)


def _deal_room_tiles(rng, tiles: list[dict], rooms: list[dict]) -> list[dict]:
    """Lay the 13 castle tiles out, one per action block, NO ROOM ALL ONE COLOUR.

    That constraint is the point, and it earns its keep: a monochrome room would be a
    DEAD room, because two of the three die colours would resolve nothing in it at all.
    The printed setup reaches it by moving a tile on to the next room whenever one would
    end up single-coloured; the corpus shows the consequence exactly -- a diplomat room
    displayed two distinct colours 40 times out of 40, and a steward room two or three
    but never one.

    What is reproduced here is that CONSTRAINT, by re-laying the tiles until it holds,
    rather than the printed shuffling procedure itself. The two differ only in the
    distribution over layouts, which nothing in the corpus can distinguish -- and a
    re-lay is checkable at a glance, where the push-a-tile-on version was not: the first
    draft of it passed a hand-traced example and still produced a monochrome room in 21
    of 1200 deals, because the repair pass could re-break a room it had already walked.
    """
    pool = list(tiles)
    spread = None
    for _ in range(200):
        rng.shuffle(pool)
        laid, index = [], 0
        for size in ROOM_TILE_COUNT:
            laid.append(pool[index:index + size])
            index += size
        if all(len({t["color"] for t in group}) > 1 for group in laid):
            spread = laid
            break
    if spread is None:       # pragma: no cover - needs a bag that cannot satisfy it
        spread = laid
    for i, room in enumerate(rooms):
        room["tiles"] = [dict(t, location=f"castle:{room['id']}", slot=n)
                         for n, t in enumerate(spread[i])]
    return [t for group in spread for t in group]


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
    # The last two tiles go to the Well dice-side down: their rewards are face up for the
    # whole game and every visit pays the same thing. The other thirteen belong in the
    # castle rooms colour-side up, which is the rule the engine does not yet enforce --
    # see AGENTS.md. They are kept in `die_tiles` until it does.
    well_tiles = [dict(t, location="well") for t in tiles[-WELL_DIE_TILES:]]
    castle_tiles = [dict(t, location="castle") for t in tiles[:-WELL_DIE_TILES]]

    # A 2-player game leaves the diamond-marked Steward and Diplomat cards in the box:
    # 9 of each instead of 15 and 12. Nothing in the corpus shows this -- it has no
    # 2-player games -- it is the printed 2-player setup.
    duel = len(seats) <= 2
    steward_deck = [clone(c) for c in STEWARDS if not (duel and c.get("diamond"))]
    diplomat_deck = [clone(c) for c in DIPLOMATS if not (duel and c.get("diamond"))]
    daimyo_deck = [clone(c) for c in DAIMYO]
    garden_deck = [clone(c) for c in GARDENS]
    # The three Training Yards are PRINTED ON THE BOARD, all three in play every game, in
    # board order -- they are not a deck and they are not dealt, so they are not shuffled.
    yards = copy.deepcopy(TRAINING_YARDS)
    for deck in (steward_deck, diplomat_deck, daimyo_deck, garden_deck):
        rng.shuffle(deck)
    castle = {
        "rooms": [{"id": i, "floor": 1 if i < 3 else 2,
                   "card": (steward_deck.pop() if i < 3 else diplomat_deck.pop()),
                   "dice": []} for i in range(5)],
        "daimyo": daimyo_deck.pop(),
    }
    # One tile per action block, colour side up. This is what decides which rows of a
    # room's card a die resolves.
    castle_tiles = _deal_room_tiles(rng, castle_tiles, castle["rooms"])
    tiles = castle_tiles
    # Six garden cards are dealt, one Plant AND one Stone beside each bridge, and each is
    # its own plot with its own gardeners -- hence one occupant list per plot. Dealing off
    # a single shuffled pile handed some bridges two Plants, which the printed setup never
    # does: the two halves of the deck are dealt separately.
    plant_pile = [c for c in garden_deck if c.get("icon") == "plant"]
    stone_pile = [c for c in garden_deck if c.get("icon") == "stone"]
    garden_deck = plant_pile[3:] + stone_pile[3:]
    gardens = [{"id": i, "bridge": BRIDGE_ORDER[i],
                "plant": plant_pile[i], "stone": stone_pile[i],
                "occupants": {"plant": [], "stone": []}} for i in range(3)]
    players_state = {}
    clan_colors = ("coral", "black", "white", "gold")
    for i, pid in enumerate(seats):
        p = _player_template()
        p["color"] = clan_colors[i]
        p["heron_order"] = turn_order.index(pid)
        p["influence_stack"] = len(turn_order) - turn_order.index(pid)
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
        "names": names, "bridges": bridges, "die_tiles": tiles, "well_tiles": well_tiles,
        "castle": castle, "outside": {}, "gardens": gardens,
        "yards": yards, "yard_deck": [], "garden_deck": garden_deck,
        "steward_deck": steward_deck, "diplomat_deck": diplomat_deck,
        "daimyo_deck": daimyo_deck,
        "common": {"coins": 32, "seals": 20},
        "draft_options": draft_options, "draft_queue": list(reversed(turn_order)),
        "draft_picks": {}, "pending": None, "turn_undo": None,
        "last_move": None, "log": [], "winner": None, "scores": {},
        "log_seq": 0, "rng_state": None, "max_players": max_players or len(seats),
        "influence_seq": len(turn_order),
    }
    _save_rng(game, rng)
    _log(game, f"The Black Castle opens for {len(seats)} clans.")
    _log(game, "Starting pairs are ready; choose one resource and action card.")
    return game


def is_over(game: dict | None) -> bool:
    return not game or game.get("phase") == "over"


def _end_round(game: dict) -> None:
    # The player furthest along the Passage of Time track leads the next round, and a tie
    # is broken by which marker is ON TOP of the pile -- that is, whoever arrived on the
    # space most recently, which `influence_stack` records. It is NOT the previous round's
    # order: tying by stepping onto a space someone already occupies OVERTAKES them, and
    # ranking the old leader first instead reverses the outcome of the one manoeuvre the
    # tie-break exists to reward. Checked against every turn-order change in the corpus:
    # 60 of 60, with no other rule fitting all of them.
    order_index = {pid: i for i, pid in enumerate(game["turn_order"])}
    game["turn_order"] = sorted(
        game["turn_order"],
        key=lambda pid: (int(_player(game, pid).get("influence", 0)),
                         int(_player(game, pid).get("influence_stack",
                                                    -order_index[pid]))),
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
                if not game["bridges"].get(garden.get("bridge")):
                    continue
                for kind in ("plant", "stone"):
                    if occupant not in _garden_occupants(garden, kind):
                        continue
                    card = garden.get(kind) or {}
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


def _influence_points(influence: int) -> int:
    """Clan Points for a Passage of Time marker resting on ``influence``.

    The four seasons award 0 / 3 / 6, and then the fourth season's spaces carry a printed
    value running 10 to 15.  The season boundaries are the checkpoints, which is why they
    are the same numbers as ``CHECKPOINT_COSTS``: a marker only enters 6, 11 or 15 by
    paying for it.  The corpus pins 0-5 -> 0, 6-10 -> 3, 11-14 -> 6 and 15 -> 10 against
    real scoreboards; the rest of the fourth season is the rulebook's own "between 10 and
    15", laid over its six spaces, and is the one row here no logged game reaches.
    """
    if influence >= 15:
        return min(15, 10 + influence - 15)
    if influence >= 11:
        return 6
    if influence >= 6:
        return 3
    return 0


def _score_game(game: dict) -> None:
    scores = {}
    for pid, p in game["players"].items():
        score = int(p.get("points", 0))
        score += (p.get("coins", 0) + p.get("seals", 0)) // 5
        for value in p["resources"].values():
            score += 2 if value >= 7 else (1 if value >= 3 else 0)
        score += _influence_points(int(p.get("influence", 0)))
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
    capacity = _dice_per_space(game)
    for room in game["castle"]["rooms"]:
        if len(room.get("dice", [])) >= capacity:
            continue
        # A die may only enter a room one of whose Die tiles shows its colour. Without
        # this a die could be placed where it resolves nothing, which is not a move the
        # printed game offers. Rooms on a pre-tile save have no tiles and stay open.
        colours = _room_tile_colors(game, room)
        if colours and die.get("color") not in colours:
            continue
        add(f"castle:{room['id']}")
    for i in range(2):
        if len(_outside_dice(game, i)) < capacity:
            add(f"outside:{i}")
    add("well")
    for color in COLORS:
        slot = p["domain"][color]
        # A personal-domain row TAKES ONLY ITS OWN COLOUR: the coral row is the
        # courtiers', black the gardeners', white the warriors', and a die of the wrong
        # colour may not be placed there at all. Without this the domain was three
        # interchangeable 6-value spaces, and the colour of the die you took off a bridge
        # -- which is half of what makes the choice a choice -- meant nothing.
        if die.get("color") != color:
            continue
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
        # SIX plots, not three. Each bridge carries a Plant garden AND a Stone garden and
        # they are separate places a gardener can stand, at separate prices for separate
        # points -- the move therefore names the `kind` as well as the bridge. Offering
        # only `plant or stone` made half the garden deck unreachable, and made every
        # Plant garden mandatory over the cheaper Stone one beside it.
        return [{"type": "worker_destination", "worker": worker, "index": i, "kind": kind}
                for i, garden in enumerate(game.get("gardens", []))
                for kind in ("plant", "stone")
                if garden.get(kind) and
                pid not in _garden_occupants(garden, kind) and
                p["resources"].get("food", 0) >= int(garden[kind].get("cost", 0))]
    return []


def _garden_occupants(garden: dict, kind: str) -> list[str]:
    """Who is standing on ONE garden card. A clan may hold at most one gardener per card.

    `occupants` used to be a single list per bridge, which read as "one gardener per
    bridge" -- two plots away from the rule. Old saves carry that flat list, so it is
    taken as the Plant plot's, which is the card those saves could actually reach.
    """
    seats = garden.get("occupants")
    if isinstance(seats, dict):
        return list(seats.get(kind) or ())
    return list(seats or ()) if kind == "plant" else []


def legal_moves(game: dict | None, pid: str) -> list[dict]:
    if not game or pid not in game.get("players", {}) or is_over(game):
        return []
    pending = game.get("pending")
    if pending and pending.get("kind") == "choose_resource":
        if pending.get("pid") != pid:
            return []
        return [{"type": "choose_resource", "resource": r} for r in RESOURCES]
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
            # "Perform 1 of the 2 actions indicated by the SPACE it is placed in" -- the
            # left space offers Gardener or Courtier, the right one Warrior or Courtier.
            # Offering all three from either space made the two spaces interchangeable and
            # the die's destination free of consequence.
            for worker in _outside_offer(game, pending.get("space")):
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
            return _climb_moves(game, pid)
        if kind == "card_action":
            return _card_action_moves(game, pid)
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


def _outside_offer(game: dict, space: str | None) -> tuple[str, ...]:
    """The worker an Outside the Walls space offers. Courtiers are on both and are added
    by the caller; an unknown space falls back to both, which is what a save written
    before the pending choice carried its space looks like."""
    try:
        return (OUTSIDE_WORKERS[int(str(space).split(":")[1])],)
    except (AttributeError, IndexError, ValueError):
        return OUTSIDE_WORKERS


def _dice_per_space(game: dict) -> int:
    return SOLO_OR_DUEL_DICE if len(game.get("players", {})) <= 2 else CASTLE_ROOM_DICE


def _outside_dice(game: dict, index: str | int) -> list[dict]:
    """The dice on one Outside the Walls space.

    Stored as a LIST because the space holds two of them at three or four players -- it
    used to hold a single ``{pid, die}``, which made the second half of a two-die space
    unreachable all game. A pre-list save carries the lone dict and is read as one die.
    """
    row = (game.get("outside") or {}).get(str(index))
    if row is None:
        return []
    return list(row) if isinstance(row, list) else [row]


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


def _room_tile_colors(game: dict, room: dict) -> list[str]:
    return [str(t.get("color")) for t in room.get("tiles") or ()]


def _fired_blocks(room: dict, die: dict) -> list[dict]:
    """The action blocks a die resolves: every block whose Die tile matches its colour.

    THIS IS THE RULE, and it is worth stating plainly because the engine used to pick
    `light` or `dark` from `(die value + room index) % 2`, which is not a rule in this
    game -- it made the die's COLOUR meaningless in the castle and its VALUE decide the
    action, when the printed game is the other way round.

    A colour can appear on two tiles in one room, and then a die of that colour performs
    BOTH of those blocks. That is not a special case bolted on: it falls out of matching
    every tile, and the corpus shows it happening -- 13 rooms fired two slots for one
    colour, always a room whose tiles showed only two distinct colours.
    """
    blocks = (room.get("card") or {}).get("blocks") or []
    tiles = room.get("tiles") or []
    colour = die.get("color")
    return [block for i, block in enumerate(blocks)
            if i < len(tiles) and tiles[i].get("color") == colour]


def _resolve_castle(game: dict, pid: str, room_index: int, die: dict) -> None:
    room = game["castle"]["rooms"][room_index]
    card = room.get("card") or {}
    if room.get("tiles") and card.get("blocks"):
        fired = _fired_blocks(room, die)
        for block in fired:
            _apply_effects(game, pid, block.get("effects") or [],
                           source=f"{card.get('name', 'castle')} {block.get('type', '')} row")
        if not fired:
            _log(game, f"{_name(game, pid)} places a die on a row no tile matches.", pid=pid)
    else:
        # A game saved before the tiles existed, or a card without blocks (the Daimyo
        # cards are still ours). Resolve it the old way rather than doing nothing.
        mode = "light" if (int(die.get("value", 0)) + room_index) % 2 == 0 else "dark"
        _apply_effects(game, pid, card.get(mode, []),
                       source=f"{card.get('name', 'castle')} {mode} action")
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


def _lantern_entry(card: dict) -> dict | None:
    """The Lantern reward a card contributes once it reaches the Lantern Area.

    Every card carries its own `lantern` line -- BGA's `lanternDescription` -- which the
    catalogue already translates into one of our ops. The Lantern Area stores the older
    `{icon, amount}` shape that `_resolve_lantern` reads, so map onto that rather than
    teach the resolver a second vocabulary.
    """
    lantern = (card or {}).get("lantern")
    if not isinstance(lantern, dict):
        return None
    if lantern.get("op") == "gain":
        for field, icon in (("coins", "coin"), ("seals", "seal"),
                            ("points", "vp"), ("influence", "influence")):
            if lantern.get(field):
                return {"icon": icon, "amount": int(lantern[field]), "card": card.get("id")}
        resource = lantern.get("resource")
        if resource and resource != ANY_RESOURCE:
            return {"icon": resource, "amount": int(lantern.get("amount", 1)),
                    "card": card.get("id")}
    if lantern.get("op") == "passage":
        return {"icon": "influence", "amount": int(lantern.get("steps", 1)),
                "card": card.get("id")}
    return None


def _take_room_card(game: dict, pid: str, room_index: int) -> None:
    """A courtier climbing INTO a room takes that room's card.

    This is the loop that fills the Lantern Area, and the engine did not have it at all:
    room cards were resolved by DICE and never handed to anyone, so the Lantern -- which
    the left end of every bridge pays out -- only ever held the card drafted at setup.

    The card becomes the clan's new action card on its personal Domain, the one it
    replaces goes to the Lantern Area, and the room is refilled from its deck.
    """
    rooms = game.get("castle", {}).get("rooms", [])
    if not 0 <= room_index < len(rooms):
        return
    room = rooms[room_index]
    taken = room.get("card")
    if not taken:
        return
    p = _player(game, pid)
    deck = game.get("diplomat_deck" if room.get("floor") == 2 else "steward_deck") or []
    if not deck:
        # "If the card cannot be replaced, you still carry out the light-background action
        # but you do not take the card and the rest of the steps are ignored." Unreachable
        # in practice -- neither deck emptied in 120 simulated games -- so this is the
        # rulebook's word, not the corpus's.
        _log(game, f"{_name(game, pid)} cannot take {taken.get('name', 'the card')}: "
                   f"there is none to replace it.", pid=pid)
        _offer_card_action(game, pid, taken)
        return
    previous = p.get("action_card")
    entry = _lantern_entry(previous) if previous else None
    if entry:
        p["lantern"].append(entry)
    p["action_card"] = copy.deepcopy(taken)
    room["card"] = deck.pop()
    _log(game, f"{_name(game, pid)} takes {taken.get('name', 'the room card')} "
               f"into their Domain.", pid=pid)
    _offer_card_action(game, pid, taken)


def _light_blocks(card: dict) -> list[dict]:
    return [b for b in (card or {}).get("blocks") or () if b.get("type") == "light"]


def _offer_card_action(game: dict, pid: str, card: dict) -> None:
    """Taking a room card also PERFORMS one of its light-background actions.

    Straight from the rulebook -- "Place the card from the room that your Courtier just
    reached in the now-empty space of your Domain board **and carry out one of the
    light-background actions on that card**" -- and the engine did not do it at all: it
    handed the card over and resolved nothing.

    Confirmed against the corpus before being built. On climbs where the taken card's
    light and dark blocks are distinguishable, the gains that follow match a LIGHT block
    286 times and a dark one 4, i.e. 99%. The player CHOOSES which light action, so a card
    with more than one raises a decision rather than picking for them.
    """
    blocks = _light_blocks(card)
    if not blocks:
        return
    if len(blocks) == 1:
        _apply_effects(game, pid, blocks[0].get("effects") or [],
                       source=f"{card.get('name', 'card')} light action")
        return
    game["pending"] = {"pid": pid, "kind": "card_action", "card": card.get("id"),
                       "name": card.get("name"), "blocks": copy.deepcopy(card.get("blocks") or []),
                       "options": list(range(len(blocks)))}


def _card_action_moves(game: dict, pid: str) -> list[dict]:
    pending = game.get("pending") or {}
    if pending.get("kind") != "card_action" or pending.get("pid") != pid:
        return []
    # The card just taken IS the player's action card. The one exception is the
    # deck-empty path, where the card was not taken -- there the pending carries the
    # blocks it offered so the choice still resolves against the right card.
    card = _player(game, pid).get("action_card") or {}
    if card.get("id") != pending.get("card"):
        card = {"blocks": pending.get("blocks") or []}
    return [{"type": "card_action", "index": i}
            for i in range(len(_light_blocks(card)))]


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
        index = space.split(":")[1]
        game.setdefault("outside", {})[index] = _outside_dice(game, index) + [{"pid": pid, "die": die}]
        # THE PROBE MUST NAME THE SPACE. `_outside_offer` keys on it -- the left space
        # offers Gardener or Courtier, the right one Warrior or Courtier -- so asking
        # without it reports choices the real pending will not have, and the turn then
        # stops on a decision with no options. Found by a random-play plan deadlocking.
        probe = {"pid": pid, "kind": "outside_worker", "space": space}
        if legal_moves({**game, "pending": probe}, pid):
            game["pending"] = probe
    elif space == "well":
        _gain(game, pid, seals=1, note="well")
        _well_bonus(game, pid)
    elif space.startswith("domain:"):
        color = space.split(":")[1]
        _player(game, pid)["domain"][color]["die"] = copy.deepcopy(die)
        _resolve_domain(game, pid, color)
    if not _promote_choice(game, pid) and not game.get("pending"):
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


def _perform_card_action(game: dict, pid: str, index: int) -> tuple[bool, str | None]:
    """Carry out the light-background action chosen on a newly taken room card."""
    pending = game.get("pending") or {}
    if pending.get("kind") != "card_action" or pending.get("pid") != pid:
        return False, "you have no card action to choose"
    card = _player(game, pid).get("action_card") or {}
    if card.get("id") != pending.get("card"):
        card = {"blocks": pending.get("blocks") or [], "name": pending.get("name", "card")}
    blocks = _light_blocks(card)
    if not 0 <= index < len(blocks):
        return False, "choose one of the card's light actions"
    game["pending"] = None
    _apply_effects(game, pid, blocks[index].get("effects") or [],
                   source=f"{card.get('name', 'card')} light action")
    if not _promote_choice(game, pid) and game.get("turn_pid") == pid:
        game["pending"] = {"pid": pid, "kind": "end_turn"}
    return True, None


def _choose_resource(game: dict, pid: str, resource: str) -> tuple[bool, str | None]:
    """Take one of the three resources a card left to the player's choice."""
    pending = game.get("pending") or {}
    if pending.get("kind") != "choose_resource" or pending.get("pid") != pid:
        return False, "you have no resource to choose"
    if resource not in RESOURCES:
        return False, "choose food, iron or pearl"
    queue = game.get("choice_queue") or []
    head = queue.pop(0) if queue else {}
    _gain(game, pid, resource=resource, amount=1,
          note=head.get("source", "card"))
    game["pending"] = None
    if _promote_choice(game, pid):
        return True, None
    if game.get("phase") == "draft":
        # The draft was held open for this choice; close it now if nobody else is owed
        # a pick. Otherwise the next seat simply drafts.
        if not game.get("draft_queue"):
            _finish_draft(game)
        return True, None
    # Back to whatever the turn was doing -- but ONLY for the seat whose turn it is. A
    # choice can outlive the action that granted it, and handing `end_turn` to a seat
    # that is not mid-turn lets it end a turn it never took.
    if game.get("turn_pid") == pid:
        game["pending"] = {"pid": pid, "kind": "end_turn"}
    return True, None


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
    # A drafted card can itself grant "any resource", and that choice belongs to this
    # seat before the next one drafts.
    _promote_choice(game, pid)
    game["draft_picks"][pid] = index
    # A starting pair is drafted from the shared face-up row. Remove it before
    # the next seat acts so two clans can never take the same pair. The final
    # unchosen pair is discarded when the draft closes.
    game["draft_options"].pop(index)
    game["draft_queue"].pop(0)
    _log(game, f"{_name(game, pid)} drafts {option['resource']['name']} + {option['action']['name']}.", pid=pid)
    if not game["draft_queue"] and not game.get("choice_queue"):
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


def _widen(game: dict, pid: str, move: dict) -> dict:
    """Accept the pre-six-plots move shapes a CACHED BUNDLE still sends.

    Two moves grew a field on the same push that fixed the rules behind them: a social
    climb now names the floor it starts from (one destination, two prices), and a gardener
    now names which of a bridge's two plots it is standing on. Pages caches a bundle for
    about ten minutes, so for that window a browser will keep posting the old shape, and
    since every move is checked with `move in legal_moves(...)` the old shape is not
    slightly wrong -- it is rejected outright, and the player is told their own legal
    action is illegal. This is the expand half of expand/contract: fill the missing field
    in with the only thing the old client could have meant, and delete this once no
    bundle without it is in the wild.
    """
    if move.get("type") == "courtier_destination" and "from" not in move:
        to, cost = str(move.get("to")), int(move.get("cost", 0) or 0)
        options = [o for o in _climb_moves(game, pid) if o["to"] == to]
        # The old client's `cost` is the only thing that distinguishes two climbs to one
        # destination, so prefer it -- but it can also be a price this push corrected
        # (floor2 -> daimyo was 5 and is 2), and a stale price must not veto the move or
        # be charged. Fall back to the cheapest way there, which is the one the old
        # client was offering: it never listed more than one climb per destination.
        return next((o for o in options if o["cost"] == cost),
                    min(options, key=lambda o: o["cost"], default=move))
    if move.get("type") == "courtier_destination" and "room" not in move:
        # A climb now names the ROOM it enters, because entering one takes its card. An
        # old bundle cannot name it, so give it the first room on that floor that still
        # has a card -- the only thing a client that did not know about rooms could have
        # meant. A floor with no room cards (the Daimyo hall) is left alone.
        rooms = _rooms_on(game, str(move.get("to")))
        if rooms:
            return {**move, "room": rooms[0]}
    if move.get("type") == "worker_destination" and move.get("worker") == "gardeners" \
            and "kind" not in move:
        return {**move, "kind": "plant"}
    return move


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    """Validate and apply one move. Returns ``(ok, error)``."""
    if not isinstance(move, dict) or pid not in game.get("players", {}):
        return False, "invalid move"
    move = _widen(game, pid, move)
    kind = move.get("type")
    if kind == "undo":
        return _undo(game, pid)
    if game.get("phase") == "draft":
        # A drafted card can grant "any resource", and that pick has to be made DURING
        # the draft -- the draft is held open for it. So it is the one non-draft move the
        # draft accepts.
        if kind == "choose_resource":
            return _choose_resource(game, pid, str(move.get("resource", "")))
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
        if move not in _worker_destination_moves(game, pid, worker):
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
            plot = str(move.get("kind", "plant"))
            card = garden.get(plot)
            _pay(game, pid, resource="food", amount=int(card.get("cost", 0)))
            p["workers"][worker]["garden_pool"] -= 1
            p["workers"][worker]["garden"] += 1
            seats = garden.get("occupants")
            if not isinstance(seats, dict):
                seats = {"plant": list(seats or ()), "stone": []}
                garden["occupants"] = seats
            seats.setdefault(plot, []).append(pid)
            p["gardens"].append(copy.deepcopy(card))
            _apply_effects(game, pid, card.get("light", []), source=card.get("name", "garden"))
        game["pending"] = {"pid": pid, "kind": "end_turn"}
        return True, None
    if kind == "courtier_destination":
        pending = game.get("pending") or {}
        if pending.get("pid") != pid or pending.get("kind") != "courtier_destination":
            return False, "choose a courtier destination"
        if move not in legal_moves(game, pid):
            return False, "that social climb is not legal"
        source, to, cost = str(move["from"]), str(move["to"]), int(move["cost"])
        if not _pay(game, pid, resource="pearl", amount=cost):
            return False, "not enough mother-of-pearl"
        if not _move_courtier(game, pid, source, to):
            return False, "no courtier can make that climb"
        _log(game, f"{_name(game, pid)} climbs to the {to}.", pid=pid)
        if move.get("room") is not None:
            _take_room_card(game, pid, int(move["room"]))
        # `_take_room_card` may have raised its own decision (which light action to
        # perform), and that outranks closing the turn.
        if (game.get("pending") or {}).get("kind") != "card_action":
            if not _promote_choice(game, pid):
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
    if kind == "card_action":
        return _perform_card_action(game, pid, int(move.get("index", -1)))
    if kind == "choose_resource":
        return _choose_resource(game, pid, str(move.get("resource", "")))
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
    # A Die tile is DOUBLE-SIDED and exactly one face is up, so each list redacts the
    # opposite one. Castle tiles lie colour-side up: their colour is public board state
    # (it is what decides which dice may enter the room) and their reward is face down.
    # Well tiles lie the other way round -- reward up, dice side down -- which is why
    # every visit to the Well pays the same, visible thing.
    view["die_tiles"] = [dict(t, reward=None) for t in game.get("die_tiles", [])]
    view["well_tiles"] = [dict(t, color=None) for t in game.get("well_tiles", [])]
    # ...and the SAME tiles are now laid out inside the rooms, where the deep copy above
    # would ship their face-down reward to every client. A nested copy of hidden state is
    # exactly how the 2026-07 audit's redaction was defeated once already.
    for room in view.get("castle", {}).get("rooms", []) or []:
        room["tiles"] = [dict(t, reward=None) for t in room.get("tiles") or ()]
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
