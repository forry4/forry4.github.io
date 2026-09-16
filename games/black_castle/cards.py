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
          color: str | None = None, icon: str | None = None) -> dict:
    return {
        "id": cid, "kind": kind, "name": name, "level": level,
        "back": back, "light": copy.deepcopy(light or []),
        "dark": copy.deepcopy(dark or []), "cost": int(cost), "vp": int(vp),
        "color": color, "icon": icon,
    }


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
    _card("resource-09", "starting_resource", "Daimyo stipend", back="pearl",
          light=_effect({"op": "gain", "resource": "pearl", "amount": 1},
                        {"op": "gain", "coins": 2},
                        {"op": "gain", "seals": 1})),
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
                         back="coin", light=light, dark=dark))
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
                         back="vp", light=light, dark=dark))
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


def _garden_defaults() -> list[dict]:
    out = []
    for i in range(1, 6):
        out.append(_card(f"plant-{i:02d}", "garden", f"Plant Garden {i}",
                         back="food", cost=2 + (i % 3), vp=4 + i,
                         icon="plant", color=COLORS[(i - 1) % 3],
                         light=_effect({"op": "gain", "coins": i}),
                         dark=_effect({"op": "gain", "resource": "food", "amount": 1})))
    for i in range(1, 6):
        out.append(_card(f"stone-{i:02d}", "garden", f"Stone Garden {i}",
                         back="iron", cost=1 + (i % 3), vp=1 + i,
                         icon="stone", color=COLORS[(i - 1) % 3],
                         light=_effect({"op": "gain", "seals": 1}),
                         dark=_effect({"op": "gain", "coins": 2})))
    return out


def _yard_defaults() -> list[dict]:
    out = []
    for i in range(1, 9):
        out.append({
            "id": f"yard-{i:02d}", "name": f"Training Yard {i}",
            "cost": 1 + (i % 5), "vp": 2 + (i % 4),
            "effect": _effect({"op": "gain", "resource": "iron", "amount": 1 if i % 2 else 2}),
        })
    return out


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
    "starting_resource": 9,
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


def make_die_tiles(rng) -> list[dict]:
    backs = ("coin", "resource", "food", "iron", "pearl", "seal", "influence", "vp")
    tiles = []
    for i in range(15):
        tiles.append({"id": i + 1, "color": COLORS[i % 3], "number": i + 1,
                      "back": backs[i % len(backs)], "revealed": False,
                      "location": "bag"})
    rng.shuffle(tiles)
    return tiles
