"""Declarative effect programs for every Orbit base-game component.

The engine executes these small JSON-safe tasks and owns every choice.  The
browser only selects from the resulting legal moves, which keeps complicated
multi-step cards reconnect-safe and server-authoritative.
"""

from __future__ import annotations

from copy import deepcopy

from .cards import ALL_CARDS, CARDS, EXPANSION_CARDS, FACTIONS, PLANETS


def credits(amount: int, target: str = "self") -> dict:
    return {"type": "credits", "amount": amount, "target": target}


def zenithium(amount: int, target: str = "self") -> dict:
    return {"type": "zenithium", "amount": amount, "target": target}


def influence(
    amount: int,
    planet: str | None = None,
    *,
    exclude: str | None = None,
    restriction: str | None = None,
    target: str = "self",
) -> dict:
    task = {"type": "influence", "amount": amount, "target": target}
    if planet:
        task["planet"] = planet
    if exclude:
        task["exclude"] = exclude
    if restriction:
        task["restriction"] = restriction
    return task


def leader(level: int = 1) -> dict:
    return {"type": "leader", "level": level}


def optional(cost: dict, then: list[dict], label: str) -> dict:
    return {"type": "optional", "cost": cost, "then": then, "label": label}


def if_leader(then: list[dict], who: str = "self") -> dict:
    """Run ``then`` if ``who`` holds the Leader badge. ``who`` is "self" or "opponent"."""

    task = {"type": "if_leader", "then": then}
    if who != "self":
        task["who"] = who
    return task


def if_resource(resource: str, amount: int, then: list[dict], who: str = "self") -> dict:
    """Run ``then`` if ``who`` holds at least ``amount`` of ``resource``.

    The task type stays ``if_credits`` so that every save written before Zenithium
    and the opponent were reachable still decodes to the same program.
    """

    task = {"type": "if_credits", "amount": amount, "then": then}
    if resource != "credits":
        task["resource"] = resource
    if who != "self":
        task["who"] = who
    return task


def raise_to(resource: str, amount: int) -> dict:
    """Bring BOTH players up to ``amount`` of ``resource``. It never takes any away."""

    return {"type": "raise_to", "resource": resource, "amount": amount}


def give_leader(then: list[dict], label: str) -> dict:
    return {
        "type": "optional",
        "cost": {"resource": "leader", "amount": 1},
        "then": then,
        "label": label,
    }


def split_influence(*amounts: int) -> dict:
    return {"type": "split_influence", "amounts": list(amounts)}


def exile_tier(planet: str, reward: str) -> dict:
    return {"type": "exile_tier", "planet": planet, "reward": reward}


def transfer(count: int, **extra) -> dict:
    return {"type": "transfer", "count": count, **extra}


def exile(count: int, owner: str = "opponent", **extra) -> dict:
    return {"type": "exile", "count": count, "owner": owner, **extra}


def mobilize(count: int, *, influence_each: bool = False) -> dict:
    return {"type": "mobilize", "count": count, "influence_each": influence_each}


def develop(faction: str | None = None, discount: int = 0, lowest: bool = False) -> dict:
    return {
        "type": "develop",
        "faction": faction,
        "discount": discount,
        "lowest": lowest,
    }


def discard_hand(count: int | str, reward: str | None = None) -> dict:
    return {"type": "discard_hand", "count": count, "reward": reward}


def choose(label: str, branches: list[tuple[str, list[dict]]]) -> dict:
    return {
        "type": "choose_branch",
        "label": label,
        "branches": [{"label": branch_label, "tasks": tasks} for branch_label, tasks in branches],
    }


CARD_EFFECTS: dict[int, list[dict]] = {card_id: [] for card_id in ALL_CARDS}


def _set(card_id: int, *tasks: dict) -> None:
    CARD_EFFECTS[card_id] = list(tasks)


# Mercury
_set(101, credits(4), optional({"resource": "zenithium_to_opponent", "amount": 1}, [influence(2, "terra")], "Give 1 Zenithium for +2 Terra influence"))
_set(102, exile(2, "self", exclude="mercury", reward={"resource": "credits", "amount": 10}, require_full=True))
_set(103, exile_tier("mercury", "zenithium"))
_set(104, influence(1, "mars"), leader())
_set(105, influence(1), if_leader([credits(3)]))
_set(106, zenithium(3))
_set(107, {"type": "draw_bonus"}, give_leader([credits(7)], "Give the Leader for 7 Credits"))
_set(108, credits(5), if_leader([{"type": "draw_bonus"}]))
_set(109, influence(2), optional({"resource": "zenithium_to_opponent", "amount": 1}, [{"type": "influence_other", "amount": 2, "different_from_previous": True}], "Give 1 Zenithium for +2 on a different planet"))
_set(110, split_influence(1, 1), {"type": "transfer_each", "planets": list(PLANETS)})
_set(111, zenithium(2), give_leader([zenithium(2)], "Give the Leader for 2 Zenithium"))
_set(112, influence(2), give_leader([{"type": "influence_other", "amount": 2, "different_from_previous": True}], "Give the Leader for +2 on a different planet"))
_set(113, mobilize(2), give_leader([mobilize(3)], "Give the Leader to mobilize 3 more cards"))
_set(114, optional({"resource": "credits_to_opponent", "amount": 3}, [influence(2, exclude="mercury")], "Give 3 Credits for +2 influence"))
_set(115, exile_tier("mercury", "influence"))
_set(116, if_leader([influence(1, "mercury")]))
_set(117, discard_hand(1), leader())
_set(118, discard_hand("all"), influence(2))

# Venus
_set(201, credits(4), optional({"resource": "zenithium_to_opponent", "amount": 1}, [influence(2, "mars")], "Give 1 Zenithium for +2 Mars influence"))
_set(202, {"type": "per_tech_first", "resource": "zenithium", "amount": 1})
_set(203, exile_tier("venus", "zenithium"))
_set(204, influence(1, "jupiter"), leader())
_set(205, exile(2), zenithium(2))
_set(206, zenithium(1, "opponent"), zenithium(3))
_set(207, zenithium(4))
_set(208, develop(discount=2))
_set(209, credits(6))
_set(210, develop("human", 1))
_set(211, develop("robot", 1))
_set(212, develop("animod", 1))
_set(213, {"type": "per_tech_first", "resource": "credits", "amount": 4})
_set(214, develop(discount=99, lowest=True))
_set(215, exile_tier("venus", "influence"))
_set(216, if_leader([influence(1, "venus")]))
_set(217, {"type": "per_nonempty", "owner": "self", "amount": 2})
_set(218, {"type": "spend_tier", "resource": "zenithium", "tiers": [[1, 1], [2, 2], [4, 3]], "exclude": "venus"})

# Terra
_set(301, credits(4), optional({"resource": "zenithium_to_opponent", "amount": 1}, [influence(2, restriction="middle")], "Give 1 Zenithium for +2 influence on a middle track"))
_set(302, credits(2, "opponent"), credits(8))
_set(303, exile_tier("terra", "zenithium"))
_set(304, influence(1, restriction="dominated"), leader())
_set(305, discard_hand(1), zenithium(1))
_set(306, zenithium(1))
_set(307, influence(1, exclude="terra", target="opponent"), zenithium(3))
_set(308, {"type": "reset_planet"})
_set(309, split_influence(1, 1, 1))
_set(310, {"type": "optional_exile_each", "planets": ["mercury", "venus", "mars", "jupiter"], "reward": "influence"})
_set(311, influence(2, exclude="terra"))
_set(312, influence(2), influence(2, restriction="opponent_side"))
_set(313, split_influence(1, 1))
_set(314, {"type": "adjacent_three", "center": 2, "neighbor": 1})
_set(315, exile_tier("terra", "influence"))
_set(316, if_leader([influence(1, "terra")]))
_set(317, {"type": "optional_exile_each", "planets": ["mercury", "venus", "mars", "jupiter"], "reward": "zenithium"})
_set(318, discard_hand(1, "matching_influence"))

# Mars
_set(401, credits(4), optional({"resource": "zenithium_to_opponent", "amount": 1}, [influence(2, "mercury")], "Give 1 Zenithium for +2 Mercury influence"))
_set(402, influence(1, exclude="mars", target="opponent"), credits(10))
_set(403, exile_tier("mars", "zenithium"))
_set(404, influence(1, "venus"), leader())
_set(405, choose("Choose Caesar's reward", [("Gain 1 Zenithium", [zenithium(1)]), ("Gain 7 Credits", [credits(7)])]))
_set(406, zenithium(2))
_set(407, choose("Choose V4NC3's effect", [("Transfer 1 card", [transfer(1)]), ("Gain 1 Zenithium", [zenithium(1)])]))
_set(408, choose("Choose Ramses's effect", [("Transfer 2 cards", [transfer(2)]), ("Gain 8 Credits", [credits(8)])]))
_set(409, influence(2, restriction="middle"))
_set(410, mobilize(1), credits(5))
_set(411, transfer(1, reward="matching_influence"))
_set(412, mobilize(1), transfer(1), exile(1))
_set(413, exile(3, reward="matching_influence", one_at_a_time=True))
_set(414, influence(1, exclude="mars"))
_set(415, exile_tier("mars", "influence"))
_set(416, if_leader([influence(1, "mars")]))
_set(417, {"type": "take_board_bonus"})
_set(418, mobilize(3, influence_each=True))

# Jupiter
_set(501, credits(4), optional({"resource": "zenithium_to_opponent", "amount": 1}, [influence(2, "venus")], "Give 1 Zenithium for +2 Venus influence"))
_set(502, influence(2), zenithium(2), leader(2))
_set(503, exile_tier("jupiter", "zenithium"))
_set(504, choose("Choose Geta's reward", [("Take the gold Leader", [leader(2)]), ("Gain 8 Credits", [credits(8)])]))
_set(505, transfer(1, reward="card_cost"))
_set(506, credits(3, "opponent"), zenithium(2))
_set(507, influence(1, "terra"), leader())
_set(508, influence(1), if_leader([zenithium(1)]))
_set(509, zenithium(3), if_leader([zenithium(1)]))
_set(510, exile(1, reward="card_cost"))
_set(511, influence(2), {"type": "if_credits", "amount": 6, "then": [{"type": "influence_other", "amount": 1, "different_from_previous": True}]})
_set(512, credits(5), give_leader([credits(7)], "Give the Leader for 7 Credits"))
_set(513, {"type": "per_nonempty", "owner": "opponent", "amount": 2})
_set(514, transfer(2), give_leader([transfer(2)], "Give the Leader to transfer 2 more cards"))
_set(515, exile_tier("jupiter", "influence"))
_set(516, if_leader([influence(1, "jupiter")]))
_set(517, discard_hand(1, "card_cost"))
_set(518, {"type": "spend_tier", "resource": "credits", "tiers": [[3, 1], [7, 2], [12, 3]], "exclude": "jupiter"})

# ── Secret Agents ────────────────────────────────────────────────────────────
# The mini-expansion, transcribed from the same `rule`/`desc` rows in
# data/bga_reference.json as everything above. These are only ever dealt when a
# game is built with `secret_agents=True`; serving never does. Seven of the ten
# needed no new vocabulary at all -- 219 is the `opponent_side` restriction card
# 312 already uses, 319 is the `lowest=True` develop of card 214, 519 is the
# discard-hand of card 118 -- which is the check that they belong to the same
# game rather than a bolted-on subsystem.
_set(119, raise_to("credits", 8))
_set(120, if_leader([{"type": "two_adjacent", "amount": 1}], who="opponent"))
_set(219, influence(1, restriction="opponent_side"))
_set(220, influence(1), if_resource("credits", 15, [influence(1)], who="opponent"))
_set(319, develop(lowest=True))
_set(320, choose("Choose Mungo's pair", [
    ("Mercury and Venus", [influence(1, "mercury"), influence(1, "venus")]),
    ("Mars and Jupiter", [influence(1, "mars"), influence(1, "jupiter")]),
]))
_set(419, raise_to("zenithium", 2))
_set(420, influence(2, exclude="mars", target="opponent"),
          {"type": "influence_other", "amount": 2, "different_from_previous": True}, leader(2))
_set(519, discard_hand("all"), credits(5))
_set(520, influence(1),
          if_resource("zenithium", 3, [{"type": "influence_other", "amount": 1, "different_from_previous": True}],
                      who="opponent"))


TECH_EFFECTS: dict[tuple[str, int, int], list[dict]] = {
    ("robot", 1, 1): [transfer(1)],
    ("robot", 1, 2): [leader()],
    ("robot", 1, 3): [split_influence(2, 1)],
    ("robot", 1, 4): [credits(20)],
    ("robot", 1, 5): [influence(2)],
    ("human", 1, 1): [{"type": "draw_bonus"}],
    ("human", 1, 2): [{"type": "steal", "resource": "zenithium", "amount": 1}],
    ("human", 1, 3): [mobilize(3)],
    ("human", 1, 4): [{"type": "two_adjacent", "amount": 2}],
    ("human", 1, 5): [influence(2)],
    ("animod", 1, 1): [exile(1)],
    ("animod", 1, 2): [credits(5)],
    ("animod", 1, 3): [{"type": "draw_bonus"}, influence(1)],
    ("animod", 1, 4): [{"type": "all_planets", "amount": 1}],
    ("animod", 1, 5): [influence(2)],
    ("robot", 2, 1): [mobilize(1)],
    ("robot", 2, 2): [mobilize(1), exile(1), transfer(1)],
    ("robot", 2, 3): [credits(10)],
    ("robot", 2, 4): [{"type": "exile_for_matching", "count": 2, "amount": 2, "distinct": True}],
    ("robot", 2, 5): [influence(2)],
    ("human", 2, 1): [influence(1)],
    ("human", 2, 2): [mobilize(2)],
    ("human", 2, 3): [{"type": "steal", "resource": "credits", "amount": 3}],
    ("human", 2, 4): [{"type": "adjacent_three", "center": 1, "neighbor": 1}],
    ("human", 2, 5): [influence(2)],
    ("animod", 2, 1): [credits(2)],
    ("animod", 2, 2): [{"type": "two_adjacent", "amount": 1}],
    ("animod", 2, 3): [transfer(3)],
    ("animod", 2, 4): [mobilize(3, influence_each=True)],
    ("animod", 2, 5): [influence(2)],
}


BONUS_EFFECTS: dict[int, list[dict]] = {
    1: [credits(3)],
    2: [credits(4)],
    3: [influence(1)],
    4: [leader()],
    5: [zenithium(1)],
    6: [mobilize(2)],
    7: [exile(2)],
    8: [transfer(1)],
}


def card_effects(card_id: int) -> list[dict]:
    return deepcopy(CARD_EFFECTS[int(card_id)])


def technology_effects(faction: str, side: int, level: int) -> list[dict]:
    return deepcopy(TECH_EFFECTS[(faction, int(side), int(level))])


def bonus_effects(token_type: int) -> list[dict]:
    return deepcopy(BONUS_EFFECTS[int(token_type)])


if set(CARD_EFFECTS) != set(ALL_CARDS):
    raise ValueError("Every Orbit card must have an effect program")
if any(not CARD_EFFECTS[card_id] for card_id in EXPANSION_CARDS):
    raise ValueError("Every Secret Agents card must have a non-empty effect program")
if len(TECH_EFFECTS) != len(FACTIONS) * 2 * 5:
    raise ValueError("Every Orbit technology space must have an effect program")
