"""Turn the BGA-derived catalogue into `catalogue.py`, the port's real card data.

WHY THIS EXISTS
---------------
`cards.py` used to generate its stewards and diplomats in loops keyed on `i % 3`, named
them "Steward 1".."Steward 15", and gave them invented effects. It said so honestly, but
it meant the port was not The White Castle in the one place that decides every turn: what
a card DOES when a die lands on it.

BGA ships each card's definition inside its notification payload, so the real catalogue is
recoverable. `extract_bga_catalogue.py` harvests it into `data/base_catalogue.json`, and
this turns that into Python.

THE DATA IS HELD TO A CLOSED VOCABULARY, WHICH IS THE POINT
-----------------------------------------------------------
Every effect BGA prints is a TEMPLATE plus its operands -- "Gain ${iconPlaceholder}
${numberOfResources}" with `{iconPlaceholder: seal, numberOfResources: 1}`. `TEMPLATES`
below maps each one to one of our ops, and a template that is not in that map **raises**
rather than being skipped. So the generator cannot quietly drop an effect it does not
understand: either the whole catalogue translates, or the build fails and says which card
and which template stopped it.

That is the same contract Rag Tag's `effects.py` has with its generated `fighters.py`, and
it exists for the same reason -- silently ignoring an unknown effect produces a game that
runs perfectly and plays a different game.

USAGE
-----
    python -m games.black_castle.tools.build_catalogue            # print a summary
    python -m games.black_castle.tools.build_catalogue --write    # regenerate catalogue.py
    python -m games.black_castle.tools.build_catalogue --check    # fail if it is stale
"""

from __future__ import annotations

import argparse
import json
import os
import pprint
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
CATALOGUE_JSON = os.path.join(_PKG, "data", "base_catalogue.json")
TARGET = os.path.join(_PKG, "catalogue.py")

#: BGA's icon vocabulary -> the field our `_gain` moves. `resource` is not a resource: it
#: is ANY resource, chosen by the player, which is why it becomes "any" rather than one of
#: the three. Getting that wrong would silently hand out food every time.
_GAIN_FIELD = {
    "coin": ("coins", None),
    "seal": ("seals", None),
    "vp": ("points", None),
    "food": ("resource", "food"),
    "iron": ("resource", "iron"),
    "pearl": ("resource", "pearl"),
    "resource": ("resource", "any"),
}

_WORKER_FOR_ICON = {
    "action-courtier": "courtiers",
    "action-warrior": "warriors",
    "action-gardener": "gardeners",
}


def _gain(args):
    icon = args["iconPlaceholder"]
    amount = int(args.get("numberOfResources", 1))
    field, resource = _GAIN_FIELD[icon]
    if field == "resource":
        return {"op": "gain", "resource": resource, "amount": amount}
    return {"op": "gain", field: amount}


#: A PRICE IS A CURRENCY AND AN AMOUNT, and the two sources disagree about the currency:
#: a castle card charges SEALS to repeat a worker action, a yard tile charges COINS. Both
#: arrive in the same `iconPlaceholder2` + `qty` pair, so flattening them to one number
#: would quietly bill a tile's 3 coins to the seal track. `cost` keeps the currency.
_COST_FIELD = {"seal": "seals", "coin": "coins"}


def _cost(args):
    qty = int(args.get("qty", 0) or 0)
    if not qty:
        return {}
    icon = args.get("iconPlaceholder2")
    if icon not in _COST_FIELD:
        raise KeyError(f"iconPlaceholder2={icon!r} is not a currency we price in")
    return {_COST_FIELD[icon]: qty}


def _worker(args):
    worker = _WORKER_FOR_ICON[args["iconPlaceholder1"]]
    return {"op": "worker_action", "worker": worker, "cost": _cost(args)}


#: THE CLOSED VOCABULARY. A template that is not here stops the build.
TEMPLATES = {
    "Gain ${iconPlaceholder} ${numberOfResources}":
        _gain,
    "Gain ${iconPlaceholder} Decree Card":
        lambda a: {"op": "decree", "icon": a["iconPlaceholder"]},
    "Gain ${iconPlaceholder} Lantern Rewards":
        lambda a: {"op": "lantern_rewards"},
    "Move ${iconPlaceholder} ${numberOfSteps} Passage of Time":
        lambda a: {"op": "passage", "steps": int(a.get("numberOfSteps", 1))},
    "Perform ${iconPlaceholder} Well Action":
        lambda a: {"op": "well_action", "cost": {}},
    "Perform ${iconPlaceholder1} Courtier Actions": _worker,
    "Perform ${iconPlaceholder1} Warrior Action": _worker,
    "Perform ${iconPlaceholder1} Gardener Action": _worker,
    "Pay ${iconPlaceholder2} ${qty} to perform ${iconPlaceholder1} Courtier Actions": _worker,
    "Pay ${iconPlaceholder2} ${qty} to perform ${iconPlaceholder1} Warrior Action": _worker,
    "Pay ${iconPlaceholder2} ${qty} to perform ${iconPlaceholder1} Gardener Action": _worker,
    # --- the two below appear only on YARD TILES, which are data-only for now ---
    "Perform ${iconPlaceholder1} Personal Domain Action":
        lambda a: {"op": "domain_action", "cost": _cost(a)},
    "Pay ${iconPlaceholder2} ${qty} to perform Perform ${iconPlaceholder1} Personal Domain Action":
        lambda a: {"op": "domain_action", "cost": _cost(a)},
    "Perform any ${iconPlaceholder} Action on the Main Board":
        lambda a: {"op": "main_board_action", "die_tile": a["iconPlaceholder"], "cost": _cost(a)},
    "Pay ${iconPlaceholder2} ${qty} to perform any ${iconPlaceholder} Action on the Main Board":
        lambda a: {"op": "main_board_action", "die_tile": a["iconPlaceholder"], "cost": _cost(a)},
}

#: Every op this generator can emit. `cards.py` re-exports it and the engine is tested
#: against it, so an op added here without an implementation fails a test rather than
#: becoming a card that does nothing when played. The last two reach only yard tiles,
#: which nothing resolves yet -- the test that holds the engine to this list knows that.
OPS = ("gain", "decree", "lantern_rewards", "passage", "well_action", "worker_action",
       "domain_action", "main_board_action")

#: The ops that only a yard tile can carry, and which the engine therefore need not
#: implement until the tile-action system lands.
TILE_ONLY_OPS = ("domain_action", "main_board_action")

#: BGA type -> (our id prefix, our `kind`, castle level). Level is what the engine prices
#: a courtier's climb on; a starting or decree card has no floor, so it is 0.
_KINDS = {
    "steward": ("steward", "steward", 1),
    "diplomat": ("diplomat", "diplomat", 2),
    "starting-resources": ("resource", "starting_resource", 0),
    "starting-action": ("action", "starting_action", 0),
    "decree": ("decree", "decree", 0),
}

_TITLES = {"steward": "Steward", "diplomat": "Diplomat",
           "starting_resource": "Resource", "starting_action": "Action",
           "decree": "Decree"}


def translate(effect, where):
    """One BGA effect -> one of our op dicts, or a hard failure naming the card."""
    text = effect.get("description")
    args = effect.get("args") or {}
    if text not in TEMPLATES:
        raise SystemExit(
            f"{where}: no op for template {text!r}.\n"
            f"  Add it to TEMPLATES (and implement the op in engine._apply_effects), or "
            f"the card would silently do nothing.")
    try:
        return TEMPLATES[text](args)
    except KeyError as exc:
        raise SystemExit(f"{where}: template {text!r} is missing operand {exc}")


def build(raw):
    """-> {section name: [card dicts]} for every card type the corpus carries."""
    out = {kind: [] for _, (_, kind, _) in _KINDS.items()}
    for key, node in sorted(raw.items(), key=_sort_key):
        if node.get("kind") != "card":
            continue
        bga_type = node.get("type")
        if bga_type not in _KINDS:
            continue
        prefix, kind, level = _KINDS[bga_type]
        number = int(node["typeArg"])
        where = f"{bga_type} {number}"

        blocks = []
        for block in node.get("blocks") or ():
            blocks.append({
                "type": block.get("type"),
                # WHICH ROWS the block covers. The die tile colours in a room decide which
                # row resolves, so this is the field that rule will read -- it is carried
                # now even though the rule itself is not implemented yet.
                "position": list(block.get("position") or ()),
                "effects": [translate(e, where) for e in block.get("effects") or ()],
            })

        card = {
            "id": f"{prefix}-{number:02d}",
            "kind": kind,
            "name": f"{_TITLES[kind]} {number}",
            "level": level,
            "back": node.get("back"),
            "blocks": blocks,
            # `light` and `dark` are DERIVED from the blocks, flattened in printed order,
            # because that is the shape the engine already resolves. When the die-colour
            # rule lands it will select a BLOCK and these become a fallback.
            "light": [e for b in blocks if b["type"] == "light" for e in b["effects"]],
            "dark": [e for b in blocks if b["type"] == "dark" for e in b["effects"]],
            "lantern": (translate(node["lantern"], where + " lantern")
                        if node.get("lantern") else None),
            "cost": 0,
            "vp": 0,
            "color": None,
            "icon": None,
            "diamond": bool(node.get("diamond")),
        }
        out[kind].append(card)
    return out


def yard_tile_faces(raw):
    """-> {(tile number, side): [ops]} for the eight double-sided yard tiles.

    Carried as DATA, not yet wired: the engine has no tile-action system, so these are
    here for the pass that builds one rather than being silently half-implemented.
    """
    faces = {}
    for key, node in sorted(raw.items(), key=_sort_key):
        if node.get("kind") != "tile" or node.get("type") != "base":
            continue
        number, side = int(node["typeArg"]), node.get("side")
        where = f"yard tile {number} {side}"
        faces[f"{number}:{side}"] = [translate(e, where) for e in node.get("effects") or ()]
    return faces


def _sort_key(item):
    key, node = item
    return (str(node.get("type")), int(node.get("typeArg") or 0), str(node.get("side") or ""))


_HEADER = '''"""The base box's REAL cards, as Board Game Arena deals them.

GENERATED by ``tools/build_catalogue.py`` from ``data/base_catalogue.json`` -- do not edit
by hand. ``tests/test_catalogue.py`` re-runs the generator and fails if this file is
stale, so an edit here is not merely lost, it is caught.

The source is 26 base-game BGA logs, in which every one of these definitions rendered
identically across all {sightings} sightings -- see ``tools/extract_bga_catalogue.py``,
whose conflict count is 0.

    STEWARDS / DIPLOMATS              the castle cards, with their light and dark blocks
    STARTING_RESOURCE_CARDS           the nine drafted at setup, one per player
    STARTING_ACTION_CARDS             the three worker-action cards
    DECREE_CARDS                      the three decrees
    YARD_TILE_FACES                   both faces of all eight yard tiles (data only)

A block carries its ``position`` -- which of the card's three rows it occupies -- because
the castle die-colour rule selects a ROW. That rule is not implemented yet; the field is
recorded so it can be, without re-deriving the catalogue.
"""

'''


def render(sections, faces, sightings):
    body = [_HEADER.format(sightings=sightings)]
    order = [("STEWARDS", "steward"), ("DIPLOMATS", "diplomat"),
             ("STARTING_RESOURCE_CARDS", "starting_resource"),
             ("STARTING_ACTION_CARDS", "starting_action"),
             ("DECREE_CARDS", "decree")]
    for name, kind in order:
        body.append(f"{name} = " + pprint.pformat(sections[kind], width=96, sort_dicts=True))
        body.append("")
        body.append("")
    body.append("YARD_TILE_FACES = " + pprint.pformat(faces, width=96, sort_dicts=True))
    body.append("")
    return "\n".join(body)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="regenerate catalogue.py")
    ap.add_argument("--check", action="store_true", help="exit 1 if catalogue.py is stale")
    args = ap.parse_args(argv)

    try:
        raw = json.load(open(CATALOGUE_JSON, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {CATALOGUE_JSON}: {exc}")
        print("regenerate it with: python -m games.black_castle.tools.extract_bga_catalogue "
              "--out games/black_castle/data/base_catalogue.json")
        return 1

    sections = build(raw)
    faces = yard_tile_faces(raw)
    text = render(sections, faces, sum(1 for _ in raw))

    for name, cards in sorted(sections.items()):
        print(f"  {name:<20} {len(cards):>3} cards, "
              f"{sum(len(b['effects']) for c in cards for b in c['blocks']):>3} effects")
    print(f"  {'yard tile faces':<20} {len(faces):>3}")

    if args.check:
        current = open(TARGET, encoding="utf-8").read() if os.path.exists(TARGET) else ""
        if current != text:
            print("\ncatalogue.py is STALE -- regenerate with --write")
            return 1
        print("\ncatalogue.py is up to date")
        return 0

    if args.write:
        with open(TARGET, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"\nwrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
