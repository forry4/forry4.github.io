"""Pure, server-authoritative rules engine for Orbit (Zenith, 2025).

The state is a plain JSON-safe dictionary.  Every forced or optional sub-choice
is persisted in ``pending`` and exposed only as validated legal moves; clients
render the game but never calculate outcomes.
"""

from __future__ import annotations

import copy
import itertools
import random
from typing import Iterable

from .boards import SUN_CONFIGURATION, board_reference, random_configuration
from .cards import (ALL_CARDS, BONUS_POOL, BONUS_TYPES, CARDS, EXPANSION_CARDS,
                    FACTIONS, PLANETS, public_card)
from .effects import bonus_effects, card_effects, technology_effects


STARTING_CREDITS = 12
STARTING_ZENITHIUM = 1
BASE_HAND_LIMIT = 4
CONTROL_POSITION = 4


def _make_rng(game: dict) -> random.Random:
    rng = random.Random()
    state = game.get("rng_state")
    if state is not None:
        rng.setstate((state[0], tuple(state[1]), state[2]))
    return rng


def _save_rng(game: dict, rng: random.Random) -> None:
    state = rng.getstate()
    game["rng_state"] = [state[0], list(state[1]), state[2]]


def _opponent(game: dict, pid: str) -> str:
    first, second = game["order"]
    return second if pid == first else first


def _player(game: dict, pid: str) -> dict:
    return game["players"][pid]


# ── The display log ─────────────────────────────────────────────────────────
# THE LOG IS THE ONLY PLACE A PLAYER CAN READ WHAT ACTUALLY HAPPENED, so every
# mutation below writes one.  An entry is a list of PARTS: a plain string is
# literal text and a dict is a token the client renders as a pressable chip —
# `{"c": id}` an Agent, `{"p": name}` a planet, `{"b": type}` a bonus token,
# `{"f": faction, "l": level}` a technology space.  Each token carries its own
# label in `v`, so the log stays readable before the catalog fetch lands and in
# a raw database dump.  The flat sentence is derived by the reader, never stored
# beside the parts: one fact, one copy.
LOG_CAP = 400

RESOURCE_LABEL = {"credits": "Credits", "zenithium": "Zenithium"}
# Zenithium is a mass noun; Credits are countable, so "1 Credits" is wrong.
RESOURCE_ONE = {"credits": "Credit", "zenithium": "Zenithium"}


LEADER_SIDES = {1: "Silver", 2: "Gold"}
# Named for the log's "nothing happened, and here is why" lines.  An effect that
# silently evaporates is the single most common thing a player asks about.
TASK_LABEL = {
    "influence": "influence",
    "influence_other": "influence on another planet",
    "influence_split": "split influence",
    "split_influence": "split influence",
    "exile": "exile",
    "exile_for_matching": "exile",
    "exile_tier": "exile",
    "transfer": "transfer",
    "discard_hand": "discard",
    "develop": "develop",
    "reset_planet": "disc reset",
    "take_board_bonus": "bonus claim",
    "spend_tier": "spend",
    "optional_exile_each": "exile",
    "two_adjacent": "influence",
    "adjacent_three": "influence",
}


def _resource_label(resource: str, amount: int) -> str:
    return RESOURCE_ONE[resource] if amount == 1 else RESOURCE_LABEL[resource]


def _tok_card(card_id: int) -> dict:
    return {"c": int(card_id), "v": ALL_CARDS[int(card_id)]["name"]}


def _tok_planet(planet: str) -> dict:
    return {"p": planet, "v": planet}


def _tok_bonus(token_type: int) -> dict:
    return {"b": int(token_type), "v": BONUS_TYPES[int(token_type)]["description"]}


def _tok_tech(faction: str, level: int) -> dict:
    return {"f": faction, "l": int(level), "v": f"{faction.title()} level {level}"}


def _log(game: dict, *parts, **data) -> None:
    game["log"].append({"turn": game["turn_number"], "parts": list(parts), **data})
    if len(game["log"]) > LOG_CAP:
        del game["log"][:-LOG_CAP]


def _who(game: dict, pid: str) -> str:
    return game["names"].get(pid, pid)


def _possessive(game: dict, actor: str, owner: str) -> str:
    return "their own" if owner == actor else f"{_who(game, owner)}’s"


def _gain_resource(game: dict, pid: str, resource: str, amount: int, note: str = "") -> None:
    player = _player(game, pid)
    suffix = f" {note}" if note else ""
    if amount <= 0:
        if note:
            _log(game, f"{_who(game, pid)} gains no {RESOURCE_LABEL[resource]}{suffix}.", pid=pid)
        return
    player[resource] += amount
    _log(game, f"{_who(game, pid)} gains {amount} {_resource_label(resource, amount)}"
               f"{suffix} (now {player[resource]}).", pid=pid)


def _spend_resource(game: dict, pid: str, resource: str, amount: int,
                    verb: str = "pays", note: str = "") -> None:
    player = _player(game, pid)
    player[resource] -= amount
    if amount <= 0:
        return
    suffix = f" {note}" if note else ""
    _log(game, f"{_who(game, pid)} {verb} {amount} {_resource_label(resource, amount)}"
               f"{suffix} (now {player[resource]}).", pid=pid)


def _give_resource(game: dict, pid: str, resource: str, amount: int) -> None:
    other = _opponent(game, pid)
    _player(game, pid)[resource] -= amount
    _player(game, other)[resource] += amount
    _log(game, f"{_who(game, pid)} gives {amount} {_resource_label(resource, amount)} to "
               f"{_who(game, other)} ({_who(game, pid)} {_player(game, pid)[resource]}, "
               f"{_who(game, other)} {_player(game, other)[resource]}).", pid=pid)


def _draw_agent(game: dict) -> int | None:
    if not game["agent_deck"]:
        if not game["agent_discard"]:
            return None
        rng = _make_rng(game)
        rng.shuffle(game["agent_discard"])
        game["agent_deck"] = game["agent_discard"]
        game["agent_discard"] = []
        _save_rng(game, rng)
    return game["agent_deck"].pop()


def _draw_to(game: dict, pid: str, limit: int) -> int:
    """Refill toward ``limit`` and report how many Agents were actually drawn."""

    hand = _player(game, pid)["hand"]
    drawn = 0
    while len(hand) < limit:
        card_id = _draw_agent(game)
        if card_id is None:
            return drawn
        hand.append(card_id)
        drawn += 1
    return drawn


def _leader_limit(game: dict, pid: str) -> int:
    leader = game["leader"]
    if leader["owner"] != pid:
        return BASE_HAND_LIMIT
    return 6 if leader["level"] >= 2 else 5


def _gain_leader(game: dict, pid: str, requested_level: int = 1) -> None:
    badge = game["leader"]
    if requested_level >= 2:
        badge.update(owner=pid, level=2)
    elif badge["owner"] == pid:
        badge["level"] = min(2, badge["level"] + 1)
    else:
        badge.update(owner=pid, level=1)
    side = LEADER_SIDES[badge["level"]]
    _log(game, f"{_who(game, pid)} takes the {side} Leader badge — their hand limit "
               f"is now {_leader_limit(game, pid)}.", pid=pid)


def _give_up_leader(game: dict, pid: str) -> None:
    if game["leader"]["owner"] == pid:
        # BGA's "give the Leadership" cost hands the badge to the opponent.
        # The old implementation dropped it on the table instead.  That looked
        # harmless while only checking the effect's immediate reward, but it
        # changed the recipient's hand limit at the next turn boundary and made
        # every subsequent scripted draw belong to the wrong seat.
        other = _opponent(game, pid)
        # BGA re-deals the badge on its Silver side when it is offered as a
        # payment, even when the giver held Gold.  The public pair is recipient
        # limit 5 followed by former-owner limit 4; preserving level 2 would
        # advertise a Gold badge the log never had and shifts the next refill.
        game["leader"] = {"owner": other, "level": 1}
        _log(game, f"{_who(game, pid)} gives the Leader badge to {_who(game, other)} — "
                   f"their hand limit is now {_leader_limit(game, other)}.", pid=pid)


def _winner_pid(game: dict) -> str | None:
    for pid, player in game["players"].items():
        captured = player["captured"]
        if any(captured.count(planet) >= 3 for planet in PLANETS):
            return pid
        if len(set(captured)) >= 4:
            return pid
        if len(captured) >= 5:
            return pid
    return None


def _check_victory(game: dict) -> bool:
    victor = _winner_pid(game)
    if victor is None:
        return False
    game["phase"] = "over"
    game["winner"] = victor
    game["pending"] = None
    game["pending_pid"] = None
    captured = _player(game, victor)["captured"]
    if any(captured.count(planet) >= 3 for planet in PLANETS):
        how = "an Absolute majority — three discs from one planet"
    elif len(set(captured)) >= 4:
        how = "a Democratic majority — four different planets"
    else:
        how = "a Popular majority — five discs in all"
    _log(game, f"{_who(game, victor)} wins Orbit with {how}.", pid=victor)
    return True


def _queue_tasks(game: dict, tasks: Iterable[dict], actor: str, *, front: bool = True) -> None:
    prepared = []
    for raw in copy.deepcopy(list(tasks)):
        raw.setdefault("actor", actor)
        prepared.append(raw)
    if not prepared:
        return
    queue = game["pending"]["queue"]
    if front:
        queue[0:0] = prepared
    else:
        queue.extend(prepared)


def _draw_bonus_type(game: dict) -> int | None:
    if not game["bonus_deck"]:
        if not game["bonus_discard"]:
            return None
        rng = _make_rng(game)
        rng.shuffle(game["bonus_discard"])
        game["bonus_deck"] = game["bonus_discard"]
        game["bonus_discard"] = []
        _save_rng(game, rng)
    return game["bonus_deck"].pop()


def _award_bonus(game: dict, pid: str, token_type: int, source: str = "") -> None:
    game["bonus_discard"].append(token_type)
    origin = f" from the {source}" if source else ""
    _log(game, f"{_who(game, pid)} claims a bonus token{origin}: ",
         _tok_bonus(token_type), ".", pid=pid)
    _queue_tasks(game, [{**task, "_bonus": True} for task in bonus_effects(token_type)], pid)


def _capture_summary(player: dict) -> str:
    captured = player["captured"]
    planets = len(set(captured))
    return (f"{len(captured)} disc{'' if len(captured) == 1 else 's'} "
            f"from {planets} planet{'' if planets == 1 else 's'}")


def _capture(game: dict, pid: str, planet: str) -> list[dict]:
    player = _player(game, pid)
    player["captured"].append(planet)
    game["captured_this_turn"].append(planet)
    game["influence"][planet] = None
    _log(game, f"{_who(game, pid)} CAPTURES the ", _tok_planet(planet),
         f" disc — they now hold {_capture_summary(player)}.", pid=pid)
    # BGA finishes the current effect queue before declaring a win.  A direct
    # engine call has no queue to drain, so preserve its immediate victory;
    # normal card resolution reaches ``_finish_turn`` below instead.
    if _winner_pid(game) is not None and game.get("pending") is None:
        _check_victory(game)
        return []
    token = game["planet_bonus"].get(planet)
    if token is None:
        _log(game, "The ", _tok_planet(planet),
             " bonus token was already taken, so the capture pays nothing extra.", pid=pid)
        return []
    game["planet_bonus"][planet] = None
    game["bonus_discard"].append(token)
    _log(game, f"{_who(game, pid)} takes the ", _tok_planet(planet), " bonus token: ",
         _tok_bonus(token), ".", pid=pid)
    return [{**task, "_bonus": True} for task in bonus_effects(token)]


def _gain_influence(game: dict, pid: str, planet: str, amount: int) -> list[dict]:
    """Move one disc step at a time and return any immediate bonus tasks."""

    if amount <= 0:
        return []
    if game["influence"][planet] is None:
        _log(game, f"{_who(game, pid)} gains {amount} influence on ", _tok_planet(planet),
             ", but that disc was captured this turn — the movement is lost.", pid=pid)
        return []
    direction = 1 if pid == game["order"][0] else -1
    moved = 0
    captured = False
    for _ in range(amount):
        game["influence"][planet] += direction
        moved += 1
        if abs(game["influence"][planet]) >= CONTROL_POSITION:
            captured = True
            break
    step = "space" if moved == 1 else "spaces"
    if captured:
        lost = amount - moved
        wasted = "" if not lost else f" The other {lost} {'is' if lost == 1 else 'are'} lost."
        _log(game, f"{_who(game, pid)} gains {amount} influence on ", _tok_planet(planet),
             f" — the disc moves {moved} {step} into their control zone.{wasted}", pid=pid)
    else:
        remaining = CONTROL_POSITION - game["influence"][planet] * direction
        _log(game, f"{_who(game, pid)} gains {amount} influence on ", _tok_planet(planet),
             f" — the disc moves {moved} {step} their way, {remaining} from capture.", pid=pid)
    return _capture(game, pid, planet) if captured else []


def _columns(game: dict, pid: str) -> dict[str, list[int]]:
    return _player(game, pid)["columns"]


def _top_candidates(
    game: dict,
    pid: str,
    owner: str,
    *,
    exclude: str | None = None,
    allowed: list[str] | None = None,
    used: list[str] | None = None,
) -> list[str]:
    target_pid = pid if owner == "self" else _opponent(game, pid)
    columns = _columns(game, target_pid)
    return [
        planet
        for planet in PLANETS
        if columns[planet]
        and planet != exclude
        and (allowed is None or planet in allowed)
        and (used is None or planet not in used)
    ]


def _eligible_planets(game: dict, pid: str, task: dict) -> list[str]:
    choices = [
        planet
        for planet in PLANETS
        if planet != task.get("exclude") and game["influence"][planet] is not None
    ]
    restriction = task.get("restriction")
    if restriction == "middle":
        choices = [planet for planet in choices if game["influence"][planet] == 0]
    elif restriction in ("opponent_side", "dominated"):
        direction = 1 if pid == game["order"][0] else -1
        choices = [
            planet
            for planet in choices
            if game["influence"][planet] is not None
            and game["influence"][planet] * direction < 0
        ]
    if task.get("distinct_from"):
        choices = [p for p in choices if p not in task["distinct_from"]]
    return choices


def _pay_cost(game: dict, pid: str, cost: dict) -> bool:
    player = _player(game, pid)
    resource = cost["resource"]
    amount = int(cost.get("amount", 1))
    if resource == "leader":
        if game["leader"]["owner"] != pid:
            return False
        _give_up_leader(game, pid)
        return True
    if resource in ("credits_to_opponent", "zenithium_to_opponent"):
        held = "credits" if resource == "credits_to_opponent" else "zenithium"
        if player[held] < amount:
            return False
        _give_resource(game, pid, held, amount)
        return True
    if player[resource] < amount:
        return False
    _spend_resource(game, pid, resource, amount)
    return True


def _can_pay(game: dict, pid: str, cost: dict) -> bool:
    resource = cost["resource"]
    amount = int(cost.get("amount", 1))
    if resource == "leader":
        return game["leader"]["owner"] == pid
    if resource == "credits_to_opponent":
        resource = "credits"
    elif resource == "zenithium_to_opponent":
        resource = "zenithium"
    return _player(game, pid).get(resource, 0) >= amount


def _develop_tasks(game: dict, pid: str, faction: str) -> list[dict]:
    player = _player(game, pid)
    level = player["technology"][faction]
    side = game["board_sides"][faction]
    tasks: list[dict] = []
    for resolved_level in range(level, 0, -1):
        tasks.extend(technology_effects(faction, side, resolved_level))
        if resolved_level == 2 and game["technology_bonus"].get(faction) is not None:
            tasks.append({"type": "fixed_bonus", "faction": faction})
    tasks.append({"type": "row_bonus_check"})
    return tasks


def _advance_technology(game: dict, pid: str, faction: str, discount: int = 0) -> bool:
    player = _player(game, pid)
    old_level = player["technology"][faction]
    if old_level >= 5:
        return False
    cost = max(0, old_level + 1 - discount)
    if player["zenithium"] < cost:
        return False
    player["zenithium"] -= cost
    player["technology"][faction] = old_level + 1
    new_level = old_level + 1
    price = (f"for {cost} Zenithium (now {player['zenithium']})" if cost
             else "for free" if discount else "at no cost")
    if discount and cost:
        price += f", discounted by {discount}"
    cascade = (f" Levels {new_level} down to 1 resolve in turn." if new_level > 1
               else " Level 1 resolves.")
    _log(game, f"{_who(game, pid)} develops ", _tok_tech(faction, new_level),
         f" {price}.{cascade}", pid=pid)
    _queue_tasks(game, _develop_tasks(game, pid, faction), pid)
    return True


def _discard_top(game: dict, actor_pid: str, owner_pid: str, planet: str) -> int:
    """Exile the top Agent of a column.  Logging lives HERE, not at each caller:
    `exile`, `exile_tier` and `optional_exile_each` all end up here, and three of
    the four used to move a card with nothing written down."""

    column = _columns(game, owner_pid)[planet]
    card_id = column.pop()
    game["agent_discard"].append(card_id)
    _log(game, f"{_who(game, actor_pid)} exiles ", _tok_card(card_id), " from ",
         f"{_possessive(game, actor_pid, owner_pid)} ", _tok_planet(planet),
         f" column to the discard pile ({len(column)} left there).", pid=actor_pid)
    return card_id


def _transfer_top(game: dict, pid: str, planet: str) -> int:
    other = _opponent(game, pid)
    card_id = _columns(game, other)[planet].pop()
    _columns(game, pid)[planet].append(card_id)
    _log(game, f"{_who(game, pid)} transfers ", _tok_card(card_id),
         f" out of {_who(game, other)}’s ", _tok_planet(planet),
         f" column into their own ({len(_columns(game, pid)[planet])} there now).", pid=pid)
    return card_id


def _task_possible(game: dict, pid: str, task: dict) -> bool:
    kind = task["type"]
    if kind == "transfer":
        return bool(_top_candidates(game, pid, "opponent"))
    if kind in ("influence", "influence_other"):
        if task.get("planet"):
            return game["influence"][task["planet"]] is not None
        probe = task
        if kind == "influence_other":
            previous = (game["pending"]["context"].get("last_nonbonus_planet")
                        if task.get("different_from_previous")
                        else game["pending"]["context"].get("last_planet"))
            probe = {**task, "distinct_from": [previous]}
        return bool(_eligible_planets(game, pid, probe))
    return True


def _choice_moves(game: dict, task: dict) -> list[dict]:
    pid = task["actor"]
    kind = task["type"]
    if kind in ("influence", "influence_other"):
        probe = task
        if kind == "influence_other":
            previous = (game["pending"]["context"].get("last_nonbonus_planet")
                        if task.get("different_from_previous")
                        else game["pending"]["context"].get("last_planet"))
            probe = {**task, "distinct_from": [previous]}
        return [{"action": "choose", "planet": planet} for planet in _eligible_planets(game, pid, probe)]
    if kind == "split_influence":
        selected = task.get("selected", [])
        return [
            {"action": "choose", "planet": planet}
            for planet in PLANETS
            if planet not in selected
        ]
    if kind == "optional":
        moves = [{"action": "choose", "accept": False}]
        if not task.get("then") or _task_possible(game, pid, task["then"][0]):
            moves.append({"action": "choose", "accept": True})
        return moves
    if kind == "choose_branch":
        options = [
            index
            for index, branch in enumerate(task["branches"])
            if not branch["tasks"] or _task_possible(game, pid, branch["tasks"][0])
        ]
        if not options:
            options = list(range(len(task["branches"])))
        return [{"action": "choose", "branch": index} for index in options]
    if kind in ("exile", "exile_for_matching"):
        owner = task.get("owner", "self" if kind == "exile_for_matching" else "opponent")
        candidates = _top_candidates(
            game,
            pid,
            owner,
            exclude=task.get("exclude"),
            used=task.get("used") if task.get("distinct") else None,
        )
        return [{"action": "choose", "planet": planet} for planet in candidates]
    if kind == "transfer":
        return [
            {"action": "choose", "planet": planet}
            for planet in _top_candidates(game, pid, "opponent")
        ]
    if kind == "discard_hand":
        return [
            {"action": "choose", "card_id": card_id}
            for card_id in _player(game, pid)["hand"]
        ]
    if kind == "develop":
        player = _player(game, pid)
        factions = [task["faction"]] if task.get("faction") else list(FACTIONS)
        if task.get("lowest"):
            lowest = min(player["technology"].values())
            factions = [f for f in factions if player["technology"][f] == lowest]
        factions = [
            faction
            for faction in factions
            if player["technology"][faction] < 5
            and player["zenithium"] >= max(0, player["technology"][faction] + 1 - task.get("discount", 0))
        ]
        return [{"action": "choose", "faction": faction} for faction in factions]
    if kind == "exile_tier":
        size = len(_columns(game, pid)[task["planet"]])
        choices = [
            {"action": "choose", "tier": threshold}
            for threshold in (2, 4, 7)
            if size >= threshold
        ]
        return choices or [{"action": "choose", "tier": 0}]
    if kind == "spend_tier":
        amount = _player(game, pid)[task["resource"]]
        return [
            {"action": "choose", "cost": cost, "amount": reward}
            for cost, reward in task["tiers"]
            if amount >= cost
        ] + [{"action": "choose", "cost": 0, "amount": 0}]
    if kind == "reset_planet":
        return [
            {"action": "choose", "planet": planet}
            for planet in PLANETS
            if game["influence"][planet] not in (None, 0)
        ]
    if kind == "take_board_bonus":
        moves = [
            {"action": "choose", "bonus_area": "planet", "slot": planet}
            for planet, token in game["planet_bonus"].items()
            if token is not None
        ]
        moves += [
            {"action": "choose", "bonus_area": "technology", "slot": faction}
            for faction, token in game["technology_bonus"].items()
            if token is not None
        ]
        return moves
    if kind == "optional_exile_each":
        planet = task["planets"][task.get("index", 0)]
        moves = [{"action": "choose", "accept": False}]
        if _columns(game, pid)[planet]:
            moves.append({"action": "choose", "accept": True})
        return moves
    if kind == "two_adjacent":
        # BGA asks for the two planets sequentially.  The order is observable
        # when the first movement captures a planet and inserts its bonus
        # effect before the second movement, so preserve both orientations of
        # every adjacent pair rather than canonicalising the pair.
        moves = []
        for i in range(4):
            for pair in ((PLANETS[i], PLANETS[i + 1]),
                         (PLANETS[i + 1], PLANETS[i])):
                moves.append({"action": "choose", "planets": list(pair)})
        return moves
    if kind == "adjacent_three":
        return [
            {"action": "choose", "planet": PLANETS[i]}
            for i in range(1, 4)
        ]
    raise ValueError(f"Unknown Orbit choice task: {kind}")


def _apply_task_choice(game: dict, task: dict, move: dict) -> None:
    pid = task["actor"]
    queue = game["pending"]["queue"]
    kind = task["type"]
    if kind in ("influence", "influence_other"):
        queue.pop(0)
        planet = move["planet"]
        game["pending"]["context"]["last_planet"] = planet
        if not task.get("_bonus"):
            game["pending"]["context"]["last_nonbonus_planet"] = planet
        bonus = _gain_influence(game, pid if task.get("target") != "opponent" else _opponent(game, pid), planet, task["amount"])
        _queue_tasks(game, bonus, pid if task.get("target") != "opponent" else _opponent(game, pid))
        # When a level-1 influence captures the penultimate space while a
        # cumulative Human cascade still has its adjacent-three effect ahead,
        # BGA completes that already-open cascade before presenting the
        # capture token.  The ordinary rule is an immediate bonus (and remains
        # so for every other task); this is the one observable queue shape in
        # the archived client where the token is appended behind the pending
        # adjacent/steal/mobilize work.
        if (bonus and not task.get("_bonus") and task.get("amount") == 1
                and game.get("pending", {}).get("queue")
                and game["pending"]["queue"][0].get("_bonus")
                and any(item.get("type") == "adjacent_three"
                        for item in game["pending"]["queue"][1:])):
            pending_queue = game["pending"]["queue"]
            deferred = pending_queue[:len(bonus)]
            del pending_queue[:len(bonus)]
            pending_queue.extend(deferred)
        # BGA's cumulative technology resolver has one observable edge case:
        # when the level-5 single-track influence leaves a disc one space from
        # control, it presents the level-1 single-track choice before the
        # intervening adjacent-three level.  Keep the ordinary descending
        # ladder for every other position; this narrow promotion mirrors the
        # archived event order without changing the live effect vocabulary.
        if (not task.get("_bonus") and task.get("amount") == 2
                and game.get("pending", {}).get("queue")
                and game["pending"]["queue"][0].get("type") == "adjacent_three"
                and game["influence"].get(planet) is not None
                and abs(game["influence"][planet]) == CONTROL_POSITION - 1):
            pending_queue = game["pending"]["queue"]
            for index in range(1, len(pending_queue)):
                candidate = pending_queue[index]
                if (candidate.get("type") == "influence"
                        and candidate.get("amount") == 1
                        and not candidate.get("_bonus")
                        and not candidate.get("planet")):
                    pending_queue.insert(0, pending_queue.pop(index))
                    break
    elif kind == "split_influence":
        selected = task.setdefault("selected", [])
        index = len(selected)
        planet = move["planet"]
        selected.append(planet)
        game["pending"]["context"]["last_planet"] = planet
        if not task.get("_bonus"):
            game["pending"]["context"]["last_nonbonus_planet"] = planet
        bonus = _gain_influence(game, pid, planet, task["amounts"][index])
        if len(selected) >= len(task["amounts"]):
            queue.pop(0)
        _queue_tasks(game, bonus, pid)
    elif kind == "optional":
        queue.pop(0)
        label = task.get("label", "the optional effect")
        if not move["accept"]:
            _log(game, f"{_who(game, pid)} declines: {label}.", pid=pid)
        else:
            _log(game, f"{_who(game, pid)} accepts: {label}.", pid=pid)
            if _pay_cost(game, pid, task["cost"]):
                _queue_tasks(game, task["then"], pid)
    elif kind == "choose_branch":
        queue.pop(0)
        _log(game, f"{_who(game, pid)} chooses: "
                   f"{task['branches'][move['branch']]['label']}.", pid=pid)
        _queue_tasks(game, task["branches"][move["branch"]]["tasks"], pid)
    elif kind in ("exile", "exile_for_matching"):
        owner = task.get("owner", "self" if kind == "exile_for_matching" else "opponent")
        owner_pid = pid if owner == "self" else _opponent(game, pid)
        planet = move["planet"]
        card_id = _discard_top(game, pid, owner_pid, planet)
        task["done"] = task.get("done", 0) + 1
        task.setdefault("used", []).append(planet)
        reward = task.get("reward")
        if reward == "matching_influence" or kind == "exile_for_matching":
            _queue_tasks(game, [{"type": "influence", "planet": planet, "amount": task.get("amount", 1)}], pid)
        elif reward == "card_cost":
            _queue_tasks(game, [{"type": "credits", "amount": ALL_CARDS[card_id]["cost"], "target": "self"}], pid)
        target = task.get("count", 1)
        if task["done"] >= target:
            queue.remove(task)
            if isinstance(reward, dict):
                _queue_tasks(game, [{"type": reward["resource"], "amount": reward["amount"], "target": "self"}], pid)
    elif kind == "transfer":
        planet = move["planet"]
        card_id = _transfer_top(game, pid, planet)
        task["done"] = task.get("done", 0) + 1
        reward = task.get("reward")
        if reward == "matching_influence":
            _queue_tasks(game, [influence_task(planet, 1)], pid)
        elif reward == "card_cost":
            _queue_tasks(game, [{"type": "credits", "amount": ALL_CARDS[card_id]["cost"], "target": "self"}], pid)
        if task["done"] >= task["count"]:
            queue.remove(task)
    elif kind == "discard_hand":
        card_id = move["card_id"]
        hand = _player(game, pid)["hand"]
        hand.remove(card_id)
        game["agent_discard"].append(card_id)
        _log(game, f"{_who(game, pid)} discards ", _tok_card(card_id),
             f" from hand ({len(hand)} card{'' if len(hand) == 1 else 's'} left).", pid=pid)
        reward = task.get("reward")
        if reward == "matching_influence":
            _queue_tasks(game, [influence_task(ALL_CARDS[card_id]["planet"], 1)], pid)
        elif reward == "card_cost":
            _queue_tasks(game, [{"type": "credits", "amount": ALL_CARDS[card_id]["cost"], "target": "self"}], pid)
        if task["count"] == "all":
            if not _player(game, pid)["hand"]:
                queue.remove(task)
        else:
            task["done"] = task.get("done", 0) + 1
            if task["done"] >= int(task["count"]):
                queue.remove(task)
    elif kind == "develop":
        queue.pop(0)
        _advance_technology(game, pid, move["faction"], task.get("discount", 0))
    elif kind == "exile_tier":
        queue.pop(0)
        threshold = move["tier"]
        # Archived BGA turns contain a prompt that is sometimes a no-op after
        # the planet was captured.  In that branch there are no discard or
        # reward packets at all; the replay hint is deliberately kept private
        # to the co-walk, so do not invent the influence/Zenithium payout that
        # the ordinary live rule would attach to a selected tier.
        bga_exile = task.get("_bga_exile") if "_bga_exile" in task else None
        if bga_exile is False:
            _log(game, f"{_who(game, pid)}'s tier-exile prompt resolves as a no-op.", pid=pid)
            return
        if not threshold:
            _log(game, f"{_who(game, pid)} exiles nothing from their ",
                 _tok_planet(task["planet"]), " column.", pid=pid)
        else:
            _log(game, f"{_who(game, pid)} exiles {threshold} Agents from their ",
                 _tok_planet(task["planet"]), " column.", pid=pid)
            # A captured planet normally has no usable disc, but archived BGA
            # turns contain both shapes: some branches still emit the exile
            # packets and some resolve the prompt as a no-op.  The co-walk can
            # attach ``_bga_exile`` when those packets are visible; ordinary
            # server games retain the rule implied by the live influence state.
            if (bga_exile if bga_exile is not None
                    else game["influence"][task["planet"]] is not None):
                for _ in range(threshold):
                    _discard_top(game, pid, pid, task["planet"])
            reward_amount = {2: 2, 4: 4, 7: 7}[threshold] if task["reward"] == "zenithium" else {2: 1, 4: 2, 7: 3}[threshold]
            reward = {"type": task["reward"], "amount": reward_amount, "target": "self"}
            if task["reward"] == "influence":
                reward["planet"] = task["planet"]
            _queue_tasks(game, [reward], pid)
    elif kind == "spend_tier":
        queue.pop(0)
        cost = move["cost"]
        if not cost:
            _log(game, f"{_who(game, pid)} spends nothing and gains no influence.", pid=pid)
        else:
            _spend_resource(game, pid, task["resource"], cost,
                            verb="spends", note=f"for {move['amount']} influence")
            _queue_tasks(game, [{"type": "influence", "amount": move["amount"], "exclude": task["exclude"]}], pid)
    elif kind == "reset_planet":
        queue.pop(0)
        game["influence"][move["planet"]] = 0
        _log(game, f"{_who(game, pid)} returns the ", _tok_planet(move["planet"]),
             " disc to the centre space.", pid=pid)
    elif kind == "take_board_bonus":
        queue.pop(0)
        area = move["bonus_area"]
        slot = move["slot"]
        board = game["planet_bonus"] if area == "planet" else game["technology_bonus"]
        token = board[slot]
        board[slot] = None
        _award_bonus(game, pid, token,
                     f"{slot} planet" if area == "planet" else f"{slot} technology track")
    elif kind == "optional_exile_each":
        index = task.get("index", 0)
        planet = task["planets"][index]
        if not move["accept"] and _columns(game, pid)[planet]:
            # Only a real choice is worth a line: this task walks FOUR planets,
            # and logging every empty column would bury the turn in "nothing".
            _log(game, f"{_who(game, pid)} declines to exile from their ",
                 _tok_planet(planet), " column.", pid=pid)
        if move["accept"] and _columns(game, pid)[planet]:
            _discard_top(game, pid, pid, planet)
            reward = task["reward"]
            if reward == "influence":
                _queue_tasks(game, [influence_task(planet, 1)], pid)
            else:
                _queue_tasks(game, [{"type": "zenithium", "amount": 1, "target": "self"}], pid)
        task["index"] = index + 1
        if task["index"] >= len(task["planets"]):
            queue.remove(task)
    elif kind == "two_adjacent":
        queue.pop(0)
        tasks = [influence_task(planet, task["amount"]) for planet in move["planets"]]
        _queue_tasks(game, tasks, pid)
    elif kind == "adjacent_three":
        queue.pop(0)
        index = PLANETS.index(move["planet"])
        _queue_tasks(
            game,
            [
                influence_task(PLANETS[index], task["center"]),
                influence_task(PLANETS[index - 1], task["neighbor"]),
                influence_task(PLANETS[index + 1], task["neighbor"]),
            ],
            pid,
        )


def influence_task(planet: str, amount: int, target: str = "self") -> dict:
    return {"type": "influence", "planet": planet, "amount": amount, "target": target}


def _drain_pending(game: dict) -> None:
    while game.get("pending") and game["pending"]["queue"] and game["phase"] != "over":
        task = game["pending"]["queue"][0]
        pid = task["actor"]
        game["pending_pid"] = pid
        kind = task["type"]

        # Choice tasks remain at the front until the owning player responds.
        if kind == "optional" and not _can_pay(game, pid, task["cost"]):
            game["pending"]["queue"].pop(0)
            _log(game, f"{_who(game, pid)} cannot pay for: "
                       f"{task.get('label', 'the optional effect')}.", pid=pid)
            continue
        if kind in {
            "influence",
            "influence_other",
            "split_influence",
            "optional",
            "choose_branch",
            "exile",
            "exile_for_matching",
            "transfer",
            "discard_hand",
            "develop",
            "exile_tier",
            "spend_tier",
            "reset_planet",
            "take_board_bonus",
            "optional_exile_each",
            "two_adjacent",
            "adjacent_three",
        }:
            if kind == "exile" and task.get("require_full") and not task.get("done"):
                owner_pid = pid if task.get("owner") == "self" else _opponent(game, pid)
                available = sum(
                    len(cards)
                    for planet, cards in _columns(game, owner_pid).items()
                    if planet != task.get("exclude")
                )
                if available < task["count"]:
                    game["pending"]["queue"].pop(0)
                    _log(game, f"{_who(game, owner_pid)} has fewer than {task['count']} "
                               f"Agents to exile, so the effect and its reward are skipped.",
                         pid=pid)
                    continue
            if kind == "influence" and task.get("planet"):
                game["pending"]["queue"].pop(0)
                target_pid = pid if task.get("target") != "opponent" else _opponent(game, pid)
                if not task.get("_bonus"):
                    game["pending"]["context"]["last_nonbonus_planet"] = task["planet"]
                game["pending"]["context"]["last_planet"] = task["planet"]
                bonus = _gain_influence(game, target_pid, task["planet"], task["amount"])
                _queue_tasks(game, bonus, target_pid)
                continue
            moves = _choice_moves(game, task)
            if moves:
                task["options"] = moves
                return
            # Unavailable effects are ignored.  A full exile cost does not pay
            # its reward unless the required number of cards existed.  SAY SO:
            # an effect that evaporates with nothing written down is the thing
            # players ask about most.
            game["pending"]["queue"].pop(0)
            _log(game, f"{_who(game, pid)} has no legal target for the "
                       f"{TASK_LABEL.get(kind, kind)} effect, so it is skipped.", pid=pid)
            continue

        game["pending"]["queue"].pop(0)
        player = _player(game, pid)
        if kind in ("credits", "zenithium"):
            target_pid = pid if task.get("target", "self") == "self" else _opponent(game, pid)
            _gain_resource(game, target_pid, kind, task["amount"])
        elif kind == "leader":
            _gain_leader(game, pid, task.get("level", 1))
        elif kind == "if_leader":
            # `who` is absent on every base-game program, and absent means self.
            who = pid if task.get("who", "self") == "self" else _opponent(game, pid)
            if game["leader"]["owner"] == who:
                _queue_tasks(game, task["then"], pid)
            else:
                _log(game, f"{_who(game, who)} does not hold the Leader badge, "
                           f"so the conditional part of this effect is skipped.", pid=pid)
        elif kind == "if_credits":
            # Named for the only resource and the only holder it could once check.
            resource = task.get("resource", "credits")
            who = pid if task.get("who", "self") == "self" else _opponent(game, pid)
            held = _player(game, who)[resource]
            if held >= task["amount"]:
                _queue_tasks(game, task["then"], pid)
            else:
                _log(game, f"{_who(game, who)} holds {held} "
                           f"{_resource_label(resource, held)}, short of the "
                           f"{task['amount']} this effect needs — it is skipped.", pid=pid)
        elif kind == "raise_to":
            # "The 2 players go UP TO n": a floor for both, never a reduction.
            resource, floor = task.get("resource", "credits"), int(task["amount"])
            for target_pid in game["order"]:
                short = floor - _player(game, target_pid)[resource]
                if short > 0:
                    _gain_resource(game, target_pid, resource, short)
                else:
                    _log(game, f"{_who(game, target_pid)} already holds "
                               f"{_player(game, target_pid)[resource]} "
                               f"{_resource_label(resource, floor)}, so this effect "
                               f"adds nothing for them.", pid=target_pid)
        elif kind == "draw_bonus":
            token = _draw_bonus_type(game)
            if token is not None:
                _award_bonus(game, pid, token, "face-down reserve")
            else:
                _log(game, "The bonus reserve is empty, so no token is drawn.", pid=pid)
        elif kind == "fixed_bonus":
            token = game["technology_bonus"].get(task["faction"])
            if token is not None:
                game["technology_bonus"][task["faction"]] = None
                _award_bonus(game, pid, token, f"{task['faction']} technology track")
        elif kind == "mobilize":
            draw_count = 1 if task.get("influence_each") else task["count"]
            for _ in range(draw_count):
                card_id = _draw_agent(game)
                if card_id is None:
                    _log(game, "The Agent deck is empty, so nothing is mobilized.", pid=pid)
                    break
                planet = ALL_CARDS[card_id]["planet"]
                _columns(game, pid)[planet].append(card_id)
                _log(game, f"{_who(game, pid)} mobilizes ", _tok_card(card_id),
                     " off the deck into their ", _tok_planet(planet),
                     " column, unresolved.", pid=pid)
                if task.get("influence_each"):
                    followups = [influence_task(planet, 1)]
                    if task["count"] > 1:
                        followups.append({**task, "count": task["count"] - 1})
                    _queue_tasks(game, followups, pid)
        elif kind == "transfer_each":
            moved = False
            for planet in task["planets"]:
                if _columns(game, _opponent(game, pid))[planet]:
                    _transfer_top(game, pid, planet)
                    moved = True
            if not moved:
                _log(game, f"{_who(game, _opponent(game, pid))} has no Agents to transfer.",
                     pid=pid)
        elif kind == "steal":
            other_pid = _opponent(game, pid)
            opponent = _player(game, other_pid)
            amount = min(task["amount"], opponent[task["resource"]])
            if amount <= 0:
                _log(game, f"{_who(game, other_pid)} has no "
                           f"{RESOURCE_LABEL[task['resource']]} to steal.", pid=pid)
            else:
                opponent[task["resource"]] -= amount
                player[task["resource"]] += amount
                _log(game, f"{_who(game, pid)} steals {amount} "
                           f"{_resource_label(task['resource'], amount)} from "
                           f"{_who(game, other_pid)} ({_who(game, pid)} {player[task['resource']]}, "
                           f"{_who(game, other_pid)} {opponent[task['resource']]}).", pid=pid)
        elif kind == "per_tech_first":
            count = sum(level >= 1 for level in player["technology"].values())
            _gain_resource(game, pid, task["resource"], count * task["amount"],
                           f"for {count} developed technology track{'' if count == 1 else 's'}")
        elif kind == "per_nonempty":
            owner_pid = pid if task["owner"] == "self" else _opponent(game, pid)
            count = sum(bool(column) for column in _columns(game, owner_pid).values())
            whose = "their own" if owner_pid == pid else f"{_who(game, owner_pid)}’s"
            _gain_resource(game, pid, "credits", count * task["amount"],
                           f"for {count} occupied column{'' if count == 1 else 's'} in "
                           f"{whose} board")
        elif kind == "all_planets":
            _queue_tasks(
                game,
                # BGA resolves the board from Jupiter back toward Mercury.
                # Keeping that order matters when the first movement reaches
                # the control space: a capture bonus is inserted into the
                # effect queue, so a forward iteration would pause before the
                # remaining planets and produce a different public event
                # sequence.
                [influence_task(planet, task["amount"]) for planet in reversed(PLANETS)],
                pid,
            )
        elif kind == "row_bonus_check":
            newly = []
            for level in (1, 2, 3):
                if level not in player["row_bonuses"] and all(value >= level for value in player["technology"].values()):
                    player["row_bonuses"].append(level)
                    _log(game, f"{_who(game, pid)} now has all three technology tracks at "
                               f"level {level} — the row bonus grants {level} influence.", pid=pid)
                    newly.append(influence_task("", level))
            for reward in newly:
                reward.pop("planet")
            _queue_tasks(game, newly, pid)
        else:
            raise ValueError(f"Unknown Orbit task: {kind}")

    if game.get("pending") and not game["pending"]["queue"] and game["phase"] != "over":
        _finish_turn(game)


def _finish_turn(game: dict) -> None:
    pid = game["turn_pid"]
    # A final capture still lets the already queued card/bonus effects resolve,
    # but BGA does not refill the hand or start another turn after gameover.
    # Reset the captured tracks first so the serialized position matches the
    # gainPlanet/resetPlanet packets, then close the game without drawing.
    if _winner_pid(game) is not None:
        for planet in game["captured_this_turn"]:
            if game["influence"][planet] is None:
                game["influence"][planet] = 0
                _log(game, "A fresh ", _tok_planet(planet),
                     " disc appears on the centre space.")
        game["captured_this_turn"] = []
        _check_victory(game)
        return
    limit = _leader_limit(game, pid)
    drawn = _draw_to(game, pid, limit)
    held = len(_player(game, pid)["hand"])
    if drawn:
        _log(game, f"{_who(game, pid)} draws {drawn} Agent{'' if drawn == 1 else 's'} "
                   f"back up to their hand limit ({held} of {limit}).", pid=pid)
    elif held > limit:
        _log(game, f"{_who(game, pid)} keeps {held} Agents, over their limit of {limit} — "
                   f"a hand is never discarded down.", pid=pid)
    for planet in game["captured_this_turn"]:
        if game["influence"][planet] is None:
            game["influence"][planet] = 0
            _log(game, "A fresh ", _tok_planet(planet),
                 " disc appears on the centre space.")
    game["captured_this_turn"] = []
    game["pending"] = None
    game["pending_pid"] = None
    game["turn_number"] += 1
    game["turn_pid"] = _opponent(game, pid)
    # The published game assumes a card is available when a hand refills.  A
    # deliberately perverse random game can temporarily strand a player with
    # no hand while the opponent later creates a discard pile.  Recover at the
    # next turn boundary so the random opponent can never deadlock a room.
    if not _player(game, game["turn_pid"])["hand"]:
        _draw_to(game, game["turn_pid"], _leader_limit(game, game["turn_pid"]))
    if (
        not _player(game, game["turn_pid"])["hand"]
        and not game["agent_deck"]
        and not game["agent_discard"]
    ):
        game["phase"] = "over"
        game["winner"] = None
        _log(game, "The Agent supply is exhausted; the game ends in a draw.")
        return
    if game["phase"] != "over":
        _log(game, f"Turn {game['turn_number']} — {_who(game, game['turn_pid'])} to play.",
             pid=game["turn_pid"], turn_start=True)


def _begin_resolution(game: dict, pid: str, tasks: list[dict], source: str) -> None:
    game["pending"] = {"source": source, "queue": [], "context": {}}
    game["pending_pid"] = pid
    _queue_tasks(game, tasks, pid, front=False)
    _drain_pending(game)


def _play_card_action(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    player = _player(game, pid)
    card_id = int(move["card_id"])
    card = ALL_CARDS[card_id]
    player["hand"].remove(card_id)
    action = move["action"]
    if action == "recruit":
        already = len(player["columns"][card["planet"]])
        cost = max(0, card["cost"] - already)
        player["credits"] -= cost
        player["columns"][card["planet"]].append(card_id)
        discount = (f" — printed {card['cost']}, reduced by the {already} Agent"
                    f"{'' if already == 1 else 's'} already there" if already else "")
        _log(game, f"{_who(game, pid)} recruits ", _tok_card(card_id), " into their ",
             _tok_planet(card["planet"]), f" column for {cost} Credits{discount} "
             f"(now {player['credits']}).", pid=pid, action=action)
        _begin_resolution(game, pid, [influence_task(card["planet"], 1), *card_effects(card_id)], card["name"])
    elif action == "technology":
        game["agent_discard"].append(card_id)
        faction = card["faction"]
        _log(game, f"{_who(game, pid)} discards ", _tok_card(card_id),
             f" to develop {faction.title()} technology.", pid=pid, action=action)
        game["pending"] = {"source": card["name"], "queue": [], "context": {}}
        game["pending_pid"] = pid
        if not _advance_technology(game, pid, faction):
            raise AssertionError("Validated technology action became illegal")
        _drain_pending(game)
    elif action == "leader":
        game["agent_discard"].append(card_id)
        faction = card["faction"]
        tasks = [{"type": "leader", "level": 1}]
        if faction == "robot":
            tasks.append({"type": "zenithium", "amount": 1, "target": "self"})
        elif faction == "human":
            tasks.append({"type": "credits", "amount": 3, "target": "self"})
        else:
            tasks.append({"type": "mobilize", "count": 2, "influence_each": False})
        _log(game, f"{_who(game, pid)} discards ", _tok_card(card_id),
             f" for the {faction.title()} Leader action.", pid=pid, action=action)
        _begin_resolution(game, pid, tasks, card["name"])
    return True, None


def deck_composition(game: dict) -> tuple[int, ...]:
    """The card ids this game was dealt from.

    Read it from the game rather than from ``CARDS`` so that conservation checks
    the deck a table actually has. ``expansion`` is absent from every save
    written before Secret Agents existed, and absent means the base 90.
    """

    if game.get("expansion"):
        return tuple(ALL_CARDS)
    return tuple(CARDS)


def new_game(
    player_ids: list[str],
    names: dict[str, str] | None = None,
    seed: int | None = None,
    configuration: str | dict[str, int] = "sun",
    secret_agents: bool = False,
) -> dict:
    if len(player_ids) != 2 or len(set(player_ids)) != 2:
        raise ValueError("Orbit requires exactly two distinct players")
    rng = random.Random(seed)
    order = list(player_ids)
    rng.shuffle(order)
    # OFF for every served game. It exists so that real BGA tables -- 88 of every
    # 100 of which run Secret Agents -- can be replayed at all.
    deck = list(ALL_CARDS) if secret_agents else list(CARDS)
    rng.shuffle(deck)
    bonuses = list(BONUS_POOL)
    rng.shuffle(bonuses)
    if configuration == "sun":
        board_sides = dict(SUN_CONFIGURATION)
    elif configuration == "random":
        board_sides = random_configuration(rng)
    elif isinstance(configuration, dict) and set(configuration) == set(FACTIONS) and all(v in (1, 2) for v in configuration.values()):
        board_sides = dict(configuration)
    else:
        raise ValueError("configuration must be 'sun', 'random', or a complete side map")
    game = {
        "version": 1,
        "phase": "mulligan",
        "expansion": bool(secret_agents),
        "order": order,
        "names": names or {pid: pid for pid in player_ids},
        "players": {
            pid: {
                "credits": STARTING_CREDITS,
                "zenithium": STARTING_ZENITHIUM,
                "hand": [],
                "columns": {planet: [] for planet in PLANETS},
                "technology": {faction: 0 for faction in FACTIONS},
                "row_bonuses": [],
                "captured": [],
            }
            for pid in player_ids
        },
        "turn_pid": None,
        "turn_number": 0,
        "influence": {planet: 0 for planet in PLANETS},
        "captured_this_turn": [],
        "leader": {"owner": None, "level": 0},
        "board_sides": board_sides,
        "planet_bonus": {},
        "technology_bonus": {},
        "agent_deck": deck,
        "agent_discard": [],
        "bonus_deck": bonuses,
        "bonus_discard": [],
        "mulligan_done": [],
        "pending": None,
        "pending_pid": None,
        "winner": None,
        "log": [],
        "rng_state": None,
    }
    for pid in order:
        _draw_to(game, pid, 4)
    for planet in PLANETS:
        game["planet_bonus"][planet] = game["bonus_deck"].pop()
    for faction in FACTIONS:
        game["technology_bonus"][faction] = game["bonus_deck"].pop()
    # The second player begins one step toward their Terra control zone.
    game["influence"]["terra"] = -1
    _log(game, f"Orbit begins. {_who(game, order[0])} plays first; "
               f"{_who(game, order[1])} starts with 1 ", _tok_planet("terra"),
         f" influence. Both hold {STARTING_CREDITS} Credits and "
         f"{STARTING_ZENITHIUM} Zenithium.")
    _save_rng(game, rng)
    return game


def legal_moves(game: dict, pid: str) -> list[dict]:
    if pid not in game["players"] or game["phase"] == "over":
        return []
    if game["phase"] == "mulligan":
        if pid in game["mulligan_done"]:
            return []
        hand = sorted(_player(game, pid)["hand"])
        return [
            {"action": "mulligan", "card_ids": list(combo)}
            for count in range(len(hand) + 1)
            for combo in itertools.combinations(hand, count)
        ]
    if game.get("pending"):
        if game["pending_pid"] != pid:
            return []
        task = game["pending"]["queue"][0]
        return copy.deepcopy(task.get("options") or _choice_moves(game, task))
    if game["turn_pid"] != pid:
        return []
    player = _player(game, pid)
    moves: list[dict] = []
    for card_id in player["hand"]:
        card = ALL_CARDS[card_id]
        recruit_cost = max(0, card["cost"] - len(player["columns"][card["planet"]]))
        if player["credits"] >= recruit_cost:
            moves.append({"action": "recruit", "card_id": card_id})
        next_level = player["technology"][card["faction"]] + 1
        if next_level <= 5 and player["zenithium"] >= next_level:
            moves.append({"action": "technology", "card_id": card_id})
        moves.append({"action": "leader", "card_id": card_id})
    return moves


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if move not in legal_moves(game, pid):
        return False, "Illegal move"
    if game["phase"] == "mulligan":
        selected = list(move["card_ids"])
        hand = _player(game, pid)["hand"]
        for card_id in selected:
            hand.remove(card_id)
            game["agent_discard"].append(card_id)
        _draw_to(game, pid, BASE_HAND_LIMIT)
        game["mulligan_done"].append(pid)
        _log(game, f"{_who(game, pid)} replaces {len(selected)} starting "
                   f"Agent{'' if len(selected) == 1 else 's'} and draws back to "
                   f"{BASE_HAND_LIMIT}.", pid=pid)
        if len(game["mulligan_done"]) == 2:
            game["phase"] = "play"
            game["turn_pid"] = game["order"][0]
            game["turn_number"] = 1
            _log(game, f"Turn 1 — {_who(game, game['turn_pid'])} to play.",
                 pid=game["turn_pid"], turn_start=True)
        return True, None
    if game.get("pending"):
        task = game["pending"]["queue"][0]
        task.pop("options", None)
        _apply_task_choice(game, task, move)
        if game["phase"] != "over":
            _drain_pending(game)
        return True, None
    return _play_card_action(game, pid, move)


def is_over(game: dict) -> bool:
    return game.get("phase") == "over"


def winner(game: dict) -> str | None:
    return game.get("winner")


def _public_player(player: dict, *, reveal_hand: bool) -> dict:
    result = copy.deepcopy(player)
    if reveal_hand:
        result["hand"] = [public_card(card_id) for card_id in player["hand"]]
    else:
        result["hand"] = [{"hidden": True} for _ in player["hand"]]
    result["columns"] = {
        planet: [public_card(card_id) for card_id in cards]
        for planet, cards in player["columns"].items()
    }
    return result


def player_view(game: dict, pid: str | None) -> dict:
    """Return a per-recipient view with all deck order and opposing hands hidden."""

    view = copy.deepcopy(game)
    view["players"] = {
        player_id: _public_player(player, reveal_hand=is_over(game) or player_id == pid)
        for player_id, player in game["players"].items()
    }
    view["agent_deck_count"] = len(view.pop("agent_deck"))
    view["agent_discard"] = [public_card(card_id) for card_id in view["agent_discard"]]
    view["bonus_deck_count"] = len(view.pop("bonus_deck"))
    view.pop("rng_state", None)
    view["board"] = board_reference(view["board_sides"])
    if view.get("pending"):
        current = view["pending"]["queue"][0] if view["pending"]["queue"] else None
        if current is None:
            view["pending"] = None
        elif view["pending_pid"] == pid:
            task_view = {
                key: value
                for key, value in current.items()
                if key not in {"actor", "then", "branches", "different_from_previous"}
                and not key.startswith("_")
            }
            if current.get("branches"):
                task_view["branch_labels"] = [branch["label"] for branch in current["branches"]]
            view["pending"] = {
                "source": view["pending"]["source"],
                "task": task_view,
            }
        else:
            view["pending"] = {"source": view["pending"]["source"], "waiting": True}
    view["legal_moves"] = legal_moves(game, pid) if pid else []
    return view


def validate_state(game: dict) -> None:
    """Raise on conservation, range, or turn-contract drift."""

    all_cards: list[int] = list(game["agent_deck"]) + list(game["agent_discard"])
    for player in game["players"].values():
        all_cards.extend(player["hand"])
        for column in player["columns"].values():
            all_cards.extend(column)
        if player["credits"] < 0 or player["zenithium"] < 0:
            raise AssertionError("Resources cannot be negative")
        if any(level < 0 or level > 5 for level in player["technology"].values()):
            raise AssertionError("Technology level out of range")
    if sorted(all_cards) != sorted(deck_composition(game)):
        raise AssertionError("Agent card conservation failed")
    all_bonuses = list(game["bonus_deck"]) + list(game["bonus_discard"])
    all_bonuses += [token for token in game["planet_bonus"].values() if token is not None]
    all_bonuses += [token for token in game["technology_bonus"].values() if token is not None]
    if sorted(all_bonuses) != sorted(BONUS_POOL):
        raise AssertionError("Bonus token conservation failed")
    for position in game["influence"].values():
        if position is not None and not -3 <= position <= 3:
            raise AssertionError("Influence position out of range")
