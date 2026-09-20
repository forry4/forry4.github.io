"""Base-game card and tile catalogue for The Black Castle.

The physical game has a deliberately small vocabulary of effects.  Definitions
live here as data rather than being scattered through the engine, which makes
the later BGA validation pass a catalogue diff instead of a rules rewrite.
The numeric card ids and counts mirror the 2023 base box; the illustrations are
owned by the publisher and are not bundled in this open-source client.
"""

from __future__ import annotations

import copy

COLORS = ("coral", "black", "white")
RESOURCES = ("food", "iron", "pearl")
WORKERS = ("courtiers", "warriors", "gardeners")


def _effect(*ops: dict) -> list[dict]:
    return [dict(op) for op in ops]


def _card(cid: str, kind: str, name: str, *, level: int = 0,
          back: str = "coin", light: list[dict] | None = None,
          dark: list[dict] | None = None, cost: int = 0, vp: int = 0,
          color: str | None = None, icon: str | None = None,
          diamond: bool = False) -> dict:
    return {
        "id": cid, "kind": kind, "name": name, "level": level,
        "back": back, "light": copy.deepcopy(light or []),
        "dark": copy.deepcopy(dark or []), "cost": int(cost), "vp": int(vp),
        "color": color, "icon": icon, "diamond": bool(diamond),
    }


#: Cards marked with a diamond in the lower-left corner, which "stay in the box" in a
#: 2-player game -- so a duel plays with 9 stewards and 9 diplomats rather than 15 and 12.
#: These are the printed cards' own numbers, taken from the corpus, where `diamond` is a
#: stable property of every sighting of a card. They are laid over OUR placeholder cards
#: by position, so the COUNT a duel removes is right even though the card faces are not.
DIAMOND_STEWARDS = (1, 3, 6, 8, 11, 14)
DIAMOND_DIPLOMATS = (1, 9, 12)


# Starting resource cards are drafted as one of player-count + 1 face-up
# options. The printed backs are represented by the resource they award.
STARTING_RESOURCE_CARDS = [
    _card("resource-01", "starting_resource", "Rice stores", back="iron",
          light=_effect({"op": "gain", "resource": "food", "amount": 2},
                        {"op": "gain", "coins": 3})),
    _card("resource-02", "starting_resource", "Forge allotment", back="food",
          light=_effect({"op": "gain", "resource": "iron", "amount": 2},
                        {"op": "gain", "coins": 2})),
    _card("resource-03", "starting_resource", "Pearl tribute", back="pearl",
          light=_effect({"op": "gain", "resource": "pearl", "amount": 2},
                        {"op": "gain", "coins": 1})),
    _card("resource-04", "starting_resource", "Market charter", back="coin",
          light=_effect({"op": "gain", "coins": 5},
                        {"op": "gain", "resource": "food", "amount": 1})),
    _card("resource-05", "starting_resource", "Storehouse key", back="resource",
          light=_effect({"op": "gain", "resource": "food", "amount": 1},
                        {"op": "gain", "resource": "iron", "amount": 1},
                        {"op": "gain", "resource": "pearl", "amount": 1})),
    _card("resource-06", "starting_resource", "Harbor toll", back="coin",
          light=_effect({"op": "gain", "coins": 3},
                        {"op": "gain", "seals": 1})),
    _card("resource-07", "starting_resource", "Clan treasury", back="coin",
          light=_effect({"op": "gain", "coins": 4},
                        {"op": "gain", "resource": "food", "amount": 1})),
    _card("resource-08", "starting_resource", "Foundry contract", back="iron",
          light=_effect({"op": "gain", "resource": "iron", "amount": 1},
                        {"op": "gain", "seals": 1},
                        {"op": "gain", "coins": 2})),
]


STARTING_ACTION_CARDS = [
    _card("action-01", "starting_action", "Morning audience", back="lantern",
          light=_effect({"op": "move", "worker": "courtiers", "from": "domain", "to": "gate"})),
    _card("action-02", "starting_action", "Drill the guard", back="warrior",
          light=_effect({"op": "move", "worker": "warriors", "from": "domain", "to": "yard"})),
    _card("action-03", "starting_action", "Tend the moss", back="garden",
          light=_effect({"op": "move", "worker": "gardeners", "from": "domain", "to": "garden"})),
    _card("action-04", "starting_action", "Lantern maker", back="coin",
          light=_effect({"op": "gain", "coins": 2}, {"op": "lantern", "icon": "coin", "amount": 1})),
    _card("action-05", "starting_action", "Seal the decree", back="seal",
          light=_effect({"op": "gain", "seals": 1}, {"op": "lantern", "icon": "vp", "amount": 1})),
    _card("action-06", "starting_action", "Pearl etiquette", back="pearl",
          light=_effect({"op": "gain", "resource": "pearl", "amount": 1},
                        {"op": "lantern", "icon": "influence", "amount": 1})),
]


def _steward_defaults() -> list[dict]:
    out = []
    resources = ("food", "iron", "pearl")
    for i in range(1, 16):
        resource = resources[(i - 1) % len(resources)]
        light = _effect({"op": "gain", "resource": resource, "amount": 1 + (i % 2)})
        dark = _effect({"op": "gain", "coins": 1 + (i % 3)})
        if i % 4 == 0:
            light.append({"op": "gain", "seals": 1})
        if i % 5 == 0:
            dark.append({"op": "influence", "amount": 1})
        out.append(_card(f"steward-{i:02d}", "steward", f"Steward {i}", level=1,
                         back="coin", light=light, dark=dark,
                         diamond=i in DIAMOND_STEWARDS))
    # A few face-up examples from the official/BGA reference are kept explicit
    # so the first games already feel like the printed set.
    out[1]["light"] = _effect({"op": "gain", "resource": "iron", "amount": 2})
    out[1]["dark"] = _effect({"op": "pay_seal_for_worker", "worker": "courtiers"})
    out[3]["light"] = _effect({"op": "pay_seal_for_worker", "worker": "warriors"})
    out[3]["dark"] = _effect({"op": "gain", "coins": 1}, {"op": "well_bonus"})
    out[9]["light"] = _effect({"op": "gain", "seals": 1}, {"op": "gain", "resource": "food", "amount": 1})
    out[9]["dark"] = _effect({"op": "pay_seal_for_worker", "worker": "courtiers"})
    return out


def _diplomat_defaults() -> list[dict]:
    out = []
    for i in range(1, 13):
        light = _effect({"op": "gain", "coins": 2}, {"op": "lantern", "icon": "coin", "amount": 1})
        dark = _effect({"op": "move", "worker": "courtiers", "from": "gate", "to": "floor2"})
        if i % 3 == 0:
            light.append({"op": "influence", "amount": 1})
        if i % 4 == 0:
            dark = _effect({"op": "gain", "seals": 1}, {"op": "lantern", "icon": "vp", "amount": 1})
        out.append(_card(f"diplomat-{i:02d}", "diplomat", f"Diplomat {i}", level=2,
                         back="vp", light=light, dark=dark,
                         diamond=i in DIAMOND_DIPLOMATS))
    out[1]["light"] = _effect({"op": "influence", "amount": 2})
    out[1]["dark"] = _effect({"op": "move", "worker": "courtiers", "from": "gate", "to": "floor2"})
    out[9]["light"] = _effect({"op": "gain", "coins": 2}, {"op": "lantern", "icon": "coin", "amount": 1})
    return out


def _daimyo_defaults() -> list[dict]:
    out = []
    for i in range(1, 10):
        out.append(_card(
            f"daimyo-{i:02d}", "daimyo", f"Daimyo {i}", level=3,
            back="vp", vp=8 + i,
            light=_effect({"op": "gain", "resource": ("food", "iron", "pearl")[i % 3], "amount": 2}),
            dark=_effect({"op": "gain", "seals": 1}, {"op": "influence", "amount": 1}),
        ))
    return out


# A garden's PRICE AND PAYOUT ARE NOT PLACEHOLDER: they are the printed ladder, read off
# the BGA corpus by `tools/bga_parity.py` and recorded in `data/bga_ground_truth.json`.
# Food cost c always pays 2c-1 points, five Stone (rock) gardens run 1/1, 1/1, 2/3, 2/3,
# 3/5 and five Plant gardens run 3/5, 4/7, 4/7, 4/7, 5/9. Six of the ten are dealt each
# game, one Plant and one Stone beside each bridge. The ACTIONS below are still ours.
STONE_GARDEN_PRICES = ((1, 1), (1, 1), (2, 3), (2, 3), (3, 5))
PLANT_GARDEN_PRICES = ((3, 5), (4, 7), (4, 7), (4, 7), (5, 9))

#: The three Training Yards, in board order. Fixed printing, not a deal: the iron a
#: warrior costs and the points it is worth are (5 -> 2), (3 -> 1), (1 -> 1), which the
#: corpus shows without a single exception over 285 warrior placements.
TRAINING_YARD_PRICES = ((5, 2), (3, 1), (1, 1))


def _garden_defaults() -> list[dict]:
    out = []
    for i, (cost, vp) in enumerate(PLANT_GARDEN_PRICES, start=1):
        out.append(_card(f"plant-{i:02d}", "garden", f"Plant Garden {i}",
                         back="food", cost=cost, vp=vp,
                         icon="plant", color=COLORS[(i - 1) % 3],
                         light=_effect({"op": "gain", "coins": i}),
                         dark=_effect({"op": "gain", "resource": "food", "amount": 1})))
    for i, (cost, vp) in enumerate(STONE_GARDEN_PRICES, start=1):
        out.append(_card(f"stone-{i:02d}", "garden", f"Stone Garden {i}",
                         back="iron", cost=cost, vp=vp,
                         icon="stone", color=COLORS[(i - 1) % 3],
                         light=_effect({"op": "gain", "seals": 1}),
                         dark=_effect({"op": "gain", "coins": 2})))
    return out


def _yard_defaults() -> list[dict]:
    names = ("Outer Training Yard", "Middle Training Yard", "Inner Training Yard")
    return [{
        "id": f"yard-{i:02d}", "name": names[i - 1],
        "cost": cost, "vp": vp,
        "effect": _effect({"op": "gain", "resource": "iron", "amount": 1 if i % 2 else 2}),
    } for i, (cost, vp) in enumerate(TRAINING_YARD_PRICES, start=1)]


STEWARDS = _steward_defaults()
DIPLOMATS = _diplomat_defaults()
DAIMYO = _daimyo_defaults()
GARDENS = _garden_defaults()
TRAINING_YARDS = _yard_defaults()
DECREE_CARDS = [
    _card("decree-01", "decree", "Rice decree", back="food", light=_effect({"op": "gain", "resource": "food", "amount": 2})),
    _card("decree-02", "decree", "Iron decree", back="iron", light=_effect({"op": "gain", "resource": "iron", "amount": 2})),
    _card("decree-03", "decree", "Pearl decree", back="pearl", light=_effect({"op": "gain", "resource": "pearl", "amount": 2})),
]

CARD_COUNTS = {
    "starting_action": 6,
    # EIGHT, not nine. The corpus deals starting-resource card ids 31-38 across 20 games
    # and never a ninth, and keying on `typeArg` -- the printed card rather than the copy
    # dealt into this game -- lands on exactly eight distinct definitions.
    "starting_resource": 8,
    "decree": 3,
    "steward": 15,
    "diplomat": 12,
    "daimyo": 9,
    "plant_garden": 5,
    "stone_garden": 5,
}

ALL_CARDS = {
    c["id"]: c for c in STARTING_RESOURCE_CARDS + STARTING_ACTION_CARDS
    + STEWARDS + DIPLOMATS + DAIMYO + GARDENS + DECREE_CARDS
}


def clone(card: dict) -> dict:
    return copy.deepcopy(card)


def card_by_id(card_id: str) -> dict | None:
    card = ALL_CARDS.get(str(card_id))
    return clone(card) if card else None


def public_card(card: dict | None) -> dict | None:
    if not card:
        return None
    result = {k: copy.deepcopy(v) for k, v in card.items() if k not in {"light", "dark"}}
    result["light"] = copy.deepcopy(card.get("light", []))
    result["dark"] = copy.deepcopy(card.get("dark", []))
    return result


def public_catalog() -> dict:
    return {
        "colors": list(COLORS), "resources": list(RESOURCES), "workers": list(WORKERS),
        "cards": {k: public_card(v) for k, v in ALL_CARDS.items()},
        "training_yards": copy.deepcopy(TRAINING_YARDS),
        "card_counts": copy.deepcopy(CARD_COUNTS),
    }


#: The 15 Die tiles are DOUBLE-SIDED: a die colour on one face, a reward on the other.
#: Thirteen go into the castle colour-side up (3 into the diamond-marked spaces, one of
#: each colour, then the numbered spaces 1-10 in order, with the constraint that no room
#: may end up all one colour); the last TWO are laid at the Well dice-side DOWN, so their
#: rewards face up and stay face up all game.
#:
#: The split and the double-sidedness are the printed rule. The colour distribution below
#: is a MODEL -- neither the rulebook text we have nor the BGA logs state the bag, and the
#: logs rule out a flat 5/5/5 under a 3-tiles-per-room reading. The rewards are ours.
DIE_TILE_REWARDS = ("coin", "resource", "food", "iron", "pearl", "seal", "influence", "vp")
CASTLE_DIE_TILES = 13
WELL_DIE_TILES = 2


def make_die_tiles(rng) -> list[dict]:
    tiles = [{"id": i + 1, "color": COLORS[i % 3], "number": i + 1,
              "reward": DIE_TILE_REWARDS[i % len(DIE_TILE_REWARDS)],
              "location": "bag"}
             for i in range(CASTLE_DIE_TILES + WELL_DIE_TILES)]
    rng.shuffle(tiles)
    return tiles
