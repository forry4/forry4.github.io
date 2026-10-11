"""Base-game card and tile catalogue for The Black Castle.

**The castle cards, the starting cards and the decrees are the REAL ones**, generated
into `catalogue.py` from 26 BGA games by `tools/build_catalogue.py` and re-exported here.
They were placeholder until 2026-09-20 -- stewards and diplomats built in loops keyed on
`i % 3`, with invented effects -- which meant the port diverged from the printed game in
the one place that decides every turn: what a card DOES when a die lands on it.

The garden cards and the yard tiles are real too (2026-10-10), and so are the nine
Daimyo's Favor cards -- rebuilt from what BGA logs when a courtier takes a slot, since it
never ships the card itself. One field of one of them is INFERRED rather than observed,
and says so where it is defined.

What is still ours rather than the printed game's:

* **The die tiles' reward faces** -- 13 of the 15 stay face-down all game and are never
  observable. Their COLOUR bag is solved (5/5/5); the rewards are not.

The illustrations are owned by the publisher and are not bundled in this open-source
client.
"""

from __future__ import annotations

import copy

from .catalogue import DECREE_CARDS as _REAL_DECREES
from .catalogue import DIPLOMATS as _REAL_DIPLOMATS
from .catalogue import GARDEN_CARDS as _REAL_GARDENS
from .catalogue import STARTING_ACTION_CARDS as _REAL_ACTIONS
from .catalogue import STARTING_RESOURCE_CARDS as _REAL_RESOURCES
from .catalogue import STEWARDS as _REAL_STEWARDS
from .catalogue import YARD_TILE_FACES

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


#: What each Daimyo slot can grant, as ops. Slot 1 is always an ACTION, slot 2 a pair of
#: one resource or Clan Points or two Passage of Time steps, slot 3 a payment.
_WELL = {"op": "well_action", "cost": {}}
_LANTERN = {"op": "lantern_rewards"}
_LIGHT_ACTION = {"op": "main_board_action", "die_tile": "action-light-background", "cost": {}}
_PASSAGE_2 = {"op": "passage", "steps": 2}


def _gain(**field) -> dict:
    (key, amount), = field.items()
    if key in RESOURCES:
        return {"op": "gain", "resource": key, "amount": amount}
    return {"op": "gain", key: amount}


#: THE NINE DAIMYO'S FAVOR CARDS. One is dealt to the third floor; a courtier arriving
#: there gains its owner's Lantern rewards, then takes a FREE slot and that slot's benefit.
#: A slot holds one courtier of any colour for the rest of the game -- 1559 of 1559
#: placement prompts in the corpus offered exactly the slots nobody stood on.
#:
#: BGA never ships the card, so these are rebuilt from what it does ship: the slot each
#: courtier took and what followed. One card per game makes a game's three slots one card,
#: and 123 games give eight of the nine whole (`bga_ground_truth.json` -> `daimyo`).
#:
#: **ONE FIELD IS INFERRED, NOT OBSERVED: card 6's slot 2.** That card -- Lantern / ? /
#: 2 Clan Points -- turns up twice, and in neither game did anyone take its middle slot.
#: "2 food" is chosen because, across the other eight, each slot-2 reward appears twice
#: except food and Clan Points (once each), and no card repeats a reward, which rules
#: Clan Points out. If a log ever shows that slot taken, the log wins.
DAIMYO_SLOTS = {
    "daimyo-01": ([_WELL], [_gain(points=2)], [_gain(seals=2)]),
    "daimyo-02": ([_WELL], [_gain(pearl=2)], [_gain(coins=3)]),
    "daimyo-03": ([_WELL], [_gain(food=2)], [_PASSAGE_2]),
    "daimyo-04": ([_LANTERN], [_gain(iron=2)], [_gain(seals=2)]),
    "daimyo-05": ([_LANTERN], [_PASSAGE_2], [_gain(coins=3)]),
    "daimyo-06": ([_LANTERN], [_gain(food=2)], [_gain(points=2)]),
    "daimyo-07": ([_LIGHT_ACTION], [_gain(pearl=2)], [_gain(points=2)]),
    "daimyo-08": ([_LIGHT_ACTION], [_PASSAGE_2], [_gain(seals=2)]),
    "daimyo-09": ([_LIGHT_ACTION], [_gain(iron=2)], [_gain(coins=3)]),
}
#: (card id, slot) pairs no game has shown. Tests hold every OTHER pair to the corpus.
DAIMYO_INFERRED = {("daimyo-06", 2)}


def _daimyo_defaults() -> list[dict]:
    out = []
    for i, (cid, slots) in enumerate(sorted(DAIMYO_SLOTS.items()), start=1):
        card = _card(cid, "daimyo", f"Daimyo's Favor {i}", level=3, back=None)
        card["slots"] = [copy.deepcopy(list(effects)) for effects in slots]
        out.append(card)
    return out


# A garden's price and payout are the printed ladder -- food cost c always pays 2c-1
# points; five Stone (rock) gardens run 1/1, 1/1, 2/3, 2/3, 3/5 and five Plant gardens
# 3/5, 4/7, 4/7, 4/7, 5/9 -- and now its ACTION is the printed one too. Six of the ten are
# dealt each game, one Plant and one Stone beside each bridge.
STONE_GARDEN_PRICES = ((1, 1), (1, 1), (2, 3), (2, 3), (3, 5))
PLANT_GARDEN_PRICES = ((3, 5), (4, 7), (4, 7), (4, 7), (5, 9))

#: The three Training Yards, in board order. Fixed printing, not a deal: the iron a
#: warrior costs and the points it is worth are (5 -> 2), (3 -> 1), (1 -> 1), which the
#: corpus shows without a single exception over 285 warrior placements.
TRAINING_YARD_PRICES = ((5, 2), (3, 1), (1, 1))


def _garden_defaults() -> list[dict]:
    return [copy.deepcopy(c) for c in _REAL_GARDENS]


def _yard_defaults() -> list[dict]:
    """The three printed yards. What a warrior DOES there comes from the Yard tiles laid
    on it at setup (`tiles`, filled in by the engine), not from the yard itself."""
    names = ("Outer Training Yard", "Middle Training Yard", "Inner Training Yard")
    return [{
        "id": f"yard-{i:02d}", "name": names[i - 1],
        "cost": cost, "vp": vp, "tiles": [],
    } for i, (cost, vp) in enumerate(TRAINING_YARD_PRICES, start=1)]


#: WHERE A GAME'S FOUR YARD TILES GO, as (yard index, face up). Four of the eight are
#: drawn; the first two share the 5-iron yard, the next two get one yard each, and the
#: faces alternate front/back. 131 of 131 games in the corpus lay them exactly so
#: (`bga_ground_truth.json` -> `yard_tile_layout`).
YARD_TILE_SLOTS = ((0, "front"), (0, "back"), (1, "front"), (2, "back"))
YARD_TILE_COUNT = 8


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
    "plant_garden": sum(1 for c in _REAL_GARDENS if c["icon"] == "plant"),
    "stone_garden": sum(1 for c in _REAL_GARDENS if c["icon"] == "stone"),
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
