"""Extract The White Castle's REAL card and tile catalogue out of BGA game logs.

WHY THIS COMES BEFORE ANY AUDIT
-------------------------------
`cards.py` is placeholder and says so. Stewards, diplomats, daimyo, gardens and yards are
generated in loops keyed on `i % 3` / `i % 4`, named "Diplomat 1".."Diplomat 12", and the
port's own manifest records `"bga_parity": "planned after launch"`. So an audit that
compared our catalogue against real games today would flag essentially every card, and not
one of those flags would be an engine bug -- it would be the data being honest about what
it is. Supply the catalogue first; audit the rules on top of it afterwards.

That is possible because BGA is unusually generous here. It does not merely log that a card
moved: it ships the card's DEFINITION inside the notification payload, repeatedly, wherever
that card is mentioned:

    card.id 10   type steward   back coin   typeArg 3
      actionBlocks[]  id "10-1"  type light|dark|blueCurtain|yellowCurtain
                      position [top|middle|bottom]   conditional and|or
        actionDescriptions[].description  "Pay ${iconPlaceholder2} ${qty} to perform ..."
        ...descriptionArgs  iconPlaceholder=coin  qty=1  numberOfResources=2
      lanternDescription + lanternDescriptionArgs

    garden cards   foodCost, pointValue, type plant|rock, locationArg = bridge colour
    yard tiles     id, type base|matcha, side front|back, actionDescription[]
    ceremony tiles id, type, actionDescription[]

The descriptions are TEMPLATES with their arguments beside them, which is what makes this
mechanical rather than a parsing exercise: `description` + `descriptionArgs` is already the
(effect, operands) pair our `cards.py` stores as `{"op": ..., "amount": ...}`.

WHAT MAKES THE OUTPUT TRUSTWORTHY
---------------------------------
A definition is seen many times across a game and across games, so the extractor does not
have to take anyone's word for it: **the same id must render the same definition every
time**, and a card whose definition differs between sightings is reported as a CONFLICT
rather than silently taking the last one. That is this tool's own non-vacuity check -- if
the walk were picking up the wrong objects, ids would collide and conflicts would appear.

Coverage is reported against the printed counts in `data/base_game_manifest.json`, so a
partial corpus says how partial it is instead of looking finished.

Usage::

    python -m games.black_castle.tools.extract_bga_catalogue [--corpus <dir>] [--out <json>]
    python -m games.black_castle.tools.extract_bga_catalogue --verbose
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

DEFAULT_CORPUS = os.environ.get("WHITECASTLE_CORPUS", "C:/Users/Forrest/WhiteCastle_corpus")

#: Printed counts, from the port's own manifest -- the denominator for coverage.
_MANIFEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "base_game_manifest.json")

#: A dict is a CARD definition if it carries an id plus at least one of these. Card objects
#: arrive under many different keys (`card`, `iconCard`, `topCard`, `mainCard`, `mainCards`,
#: `gardenCards`, ...), so the walk keys on SHAPE rather than on the name of the field that
#: happened to hold it -- a new key in a later BGA release then costs nothing.
CARD_MARKERS = ("actionBlocks", "lanternDescription")

#: Same idea for the tiles, which have a flatter shape than the cards.
TILE_MARKERS = ("actionDescription",)


def _walk(node):
    """Every dict anywhere in a payload."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _is_card(node):
    return "id" in node and any(m in node for m in CARD_MARKERS)


def _is_tile(node):
    return "id" in node and any(m in node for m in TILE_MARKERS) and "actionBlocks" not in node


def _blocks(node):
    """The effect blocks of a card, normalised and ORDER-INDEPENDENT.

    Sorted by block id because the payload's list order is presentation, not identity, and
    two sightings of one card must compare equal.
    """
    out = []
    for block in node.get("actionBlocks") or ():
        if not isinstance(block, dict):
            continue
        effects = []
        for desc in block.get("actionDescriptions") or ():
            if isinstance(desc, dict):
                effects.append({
                    "description": desc.get("description"),
                    "args": _args(desc.get("descriptionArgs")),
                })
        out.append({
            "id": block.get("id"),
            "type": block.get("type"),
            "position": list(block.get("position") or ()),
            "conditional": block.get("conditional"),
            "effects": effects,
        })
    return sorted(out, key=lambda b: str(b["id"]))


def _args(raw):
    """Effect operands, minus the presentation noise BGA carries alongside them."""
    if not isinstance(raw, dict):
        return {}
    drop = {"i18n", "disabledReason"}
    return {k: v for k, v in sorted(raw.items()) if k not in drop and not isinstance(v, (dict, list))}


def definition(node):
    """The identity-bearing part of a card or tile: what must not vary between sightings.

    Deliberately EXCLUDES `location` / `locationArg` / `gardeners` / `playerId` -- those say
    where the card is right now and who is standing on it, which changes every turn and is
    not the card.
    """
    if _is_card(node):
        out = {
            "kind": "card",
            "type": node.get("type"),
            "back": node.get("back"),
            "typeArg": node.get("typeArg"),
            "diamond": node.get("diamond"),
            "blocks": _blocks(node),
            "lantern": {
                "description": node.get("lanternDescription"),
                "args": _args(node.get("lanternDescriptionArgs")),
            } if node.get("lanternDescription") else None,
        }
        for extra in ("foodCost", "pointValue"):
            if node.get(extra) is not None:
                out[extra] = node[extra]
        return out
    return {
        "kind": "tile",
        "type": node.get("type"),
        "typeArg": node.get("typeArg"),
        "side": node.get("side"),
        "effects": [
            {"description": d, "args": {}} if isinstance(d, str) else {"description": None, "args": _args(d)}
            for d in (node.get("actionDescription") or ())
        ],
        "args": [_args(a) for a in (node.get("actionDescriptionArgs") or ()) if isinstance(a, dict)],
    }


def harvest(paths):
    """-> (catalogue, conflicts, sightings). Keyed (kind, type, id, face)."""
    catalogue, conflicts = {}, collections.defaultdict(list)
    sightings = collections.Counter()
    for path in paths:
        try:
            packets = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for node in _walk(packets):
            if not isinstance(node, dict):
                continue
            if not (_is_card(node) or _is_tile(node)):
                continue
            body = definition(node)
            # THE FACE IS PART OF THE IDENTITY, NOT A DISAGREEMENT. A matcha yard tile is
            # double-sided and its two faces are different cards wearing one id -- front
            # "Perform 1 yard-tile Action(s)", back "Gain chasen 3", and even a different
            # `typeArg`. Keying without the side reported that as a corrupted definition;
            # keying WITH it records both faces and leaves a genuine disagreement still
            # able to surface, which is the whole point of the check.
            key = (body["kind"], str(node.get("type")), str(node.get("id")),
                   str(node.get("side") or ""))
            sightings[key] += 1
            blob = json.dumps(body, sort_keys=True)
            if key not in catalogue:
                catalogue[key] = body
            elif json.dumps(catalogue[key], sort_keys=True) != blob:
                if blob not in conflicts[key]:
                    conflicts[key].append(blob)
    return catalogue, conflicts, sightings


def expected_counts():
    try:
        data = json.load(open(_MANIFEST, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("components") or {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=None, help="write the catalogue as JSON")
    ap.add_argument("--verbose", action="store_true", help="print every definition found")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    catalogue, conflicts, sightings = harvest(paths)
    by_type = collections.Counter(key[1] for key in catalogue)

    print(f"{len(paths)} logs -> {len(catalogue)} distinct definitions, "
          f"{sum(sightings.values())} sightings\n")
    print(f"  {'type':<20} {'found':>6} {'sightings':>10}")
    for kind in sorted(by_type):
        seen = sum(n for key, n in sightings.items() if key[1] == kind)
        print(f"  {kind:<20} {by_type[kind]:>6} {seen:>10}")

    printed = expected_counts()
    if printed:
        print(f"\n  printed counts, for reference: "
              + ", ".join(f"{k}={v}" for k, v in sorted(printed.items()) if isinstance(v, int)))

    # THE EXTRACTOR'S OWN CHECK. One id must mean one definition, everywhere, always.
    print(f"\n  ids whose definition DISAGREED between sightings : {len(conflicts)}"
          f"   <- a defect in this walk, or in the data")
    for key, blobs in list(conflicts.items())[:5]:
        print(f"    {key}: {len(blobs) + 1} distinct renderings")
    if not conflicts:
        print("    (one id+face means one definition, across every sighting)")

    if args.verbose:
        print("\ndefinitions:")
        for key in sorted(catalogue, key=lambda k: (k[0], k[1], int(k[2]) if k[2].isdigit() else 0, k[3])):
            face = f" [{key[3]}]" if key[3] else ""
            print(f"  {key[1]} {key[2]}{face}: {json.dumps(catalogue[key])[:150]}")

    if args.out:
        payload = {":".join(p for p in k if p): v for k, v in catalogue.items()}
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        print(f"\nwrote {len(payload)} definitions -> {args.out}")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
