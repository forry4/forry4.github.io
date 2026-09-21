"""Base-game card and tile catalogue for The Black Castle.

**The castle cards, the starting cards and the decrees are the REAL ones**, generated
into `catalogue.py` from 26 BGA games by `tools/build_catalogue.py` and re-exported here.
They were placeholder until 2026-09-20 -- stewards and diplomats built in loops keyed on
`i % 3`, with invented effects -- which meant the port diverged from the printed game in
the one place that decides every turn: what a card DOES when a die lands on it.

What is still ours rather than the printed game's, and says so below:

* **DAIMYO** -- the 3 Daimyo's Favor cards appear NOWHERE in the corpus (a courtier has to
  reach the third floor for BGA to ship one), so these 9 are still generated.
* **The die tiles' reward faces** -- 13 of the 15 stay face-down all game and are never
  observable. Their COLOUR bag is solved (5/5/5); the rewards are not.

What was never placeholder: a garden's price and payout, which are the printed ladder
read off the corpus, and the training yards.

The illustrations are owned by the publisher and are not bundled in this open-source
client.
"""

from __future__ import annotations

import copy

from .catalogue import DECREE_CARDS as _REAL_DECREES
from .catalogue import DIPLOMATS as _REAL_DIPLOMATS
from .catalogue import STARTING_ACTION_CARDS as _REAL_ACTIONS
from .catalogue import STARTING_RESOURCE_CARDS as _REAL_RESOURCES
from .catalogue import STEWARDS as _REAL_STEWARDS
from .catalogue import YARD_TILE_FACES  # noqa: F401  (data for the tile pass)

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
#: DERIVED from the real cards now rather than listed beside them: `diamond` is a stable
#: property of every sighting in the corpus, and the card carries its own. Typing the
#: numbers a second time is how the list and the cards drift apart.
DIAMOND_STEWARDS = tuple(int(c["id"].split("-")[1]) for c in _REAL_STEWARDS if c["diamond"])
DIAMOND_DIPLOMATS = tuple(int(c["id"].split("-")[1]) for c in _REAL_DIPLOMATS if c["diamond"])


#: THE NINE starting resource cards, three backed with each of pearl / iron / food. One
#: is drafted per player from player-count + 1 face-up options.
#:
#: It was EIGHT here until 2026-09-20, and the reasoning for that is worth keeping because
#: it was the same mistake twice: the 20-log corpus showed eight distinct cards and never a
#: ninth, so the ninth was deleted. It exists -- typeArg 3 is simply the rarest, at 8
#: sightings against the commonest's 34, and six more games turned it up. "The data does
#: not show it" is not "it is not there", which is exactly what the deleted 2-player dice
#: rule taught, and this code did not learn it.
STARTING_RESOURCE_CARDS = [copy.deepcopy(c) for c in _REAL_RESOURCES]

#: THE THREE starting action cards -- one per worker (courtier / warrior / gardener),
#: each carrying a Passage of Time step as its lantern reward. Six were generated here
#: before; the corpus shows three, across 444 sightings in 26 games.
STARTING_ACTION_CARDS = [copy.deepcopy(c) for c in _REAL_ACTIONS]


#: The fifteen stewards and twelve diplomats as BGA deals them, each carrying its
#: `blocks` (light/dark, and WHICH ROWS each covers) beside the flattened `light`/`dark`
#: the engine resolves today.
def _steward_defaults() -> list[dict]:
    return [copy.deepcopy(c) for c in _REAL_STEWARDS]


def _diplomat_defaults() -> list[dict]:
    return [copy.deepcopy(c) for c in _REAL_DIPLOMATS]


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
#: The three decrees. They carry NO action blocks at all -- a decree is a pure Lantern
#: reward, one each of coin / seal / vp, which is also why the catalogue's three
#: `Gain <icon> Decree Card` operands are exactly those three icons.
DECREE_CARDS = [copy.deepcopy(c) for c in _REAL_DECREES]

#: DERIVED from the catalogue, not typed beside it -- a count that is written twice is a
#: count that eventually disagrees with itself, which is how `starting_resource` sat at 8
#: while nine cards existed.
CARD_COUNTS = {
    "starting_action": len(STARTING_ACTION_CARDS),
    "starting_resource": len(STARTING_RESOURCE_CARDS),
    "decree": len(DECREE_CARDS),
    "steward": len(STEWARDS),
    "diplomat": len(DIPLOMATS),
    "daimyo": len(DAIMYO),
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
#: The split and the double-sidedness are the printed rule, and the colour bag below is
#: DERIVED, not chosen: five of each. No rules text states it and no single game comes
#: close to fixing it -- the most informative one alone leaves six candidates -- but the
#: intersection over the corpus is a single bag. `tools/bga_parity.py:die_tile_bag()`
#: solves it and shows the working. The REWARD faces are still ours; only the two that
#: land at the Well are ever read, so they are the only ones worth deriving next.
DIE_TILE_REWARDS = ("coin", "resource", "food", "iron", "pearl", "seal", "influence", "vp")
CASTLE_DIE_TILES = 13
WELL_DIE_TILES = 2


def make_die_tiles(rng) -> list[dict]:
    tiles = [{"id": i + 1, "color": COLORS[i % len(COLORS)], "number": i + 1,
              "reward": DIE_TILE_REWARDS[i % len(DIE_TILE_REWARDS)],
              "location": "bag"}
             for i in range(CASTLE_DIE_TILES + WELL_DIE_TILES)]
    rng.shuffle(tiles)
    return tiles
