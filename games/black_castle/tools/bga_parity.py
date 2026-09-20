"""Derive The White Castle's RULES from BGA game logs, then hold our engine to them.

WHAT THIS IS, AND HOW IT DIFFERS FROM THE CATALOGUE TOOL
--------------------------------------------------------
`extract_bga_catalogue.py` answers "what do the CARDS say". This answers "what do the
RULES do": board geometry, what a space costs, what a worker costs, which colours may go
where, how turn order is decided, and -- the half that is checkable to the point --
**exactly how the game scores**.

The output is `data/bga_ground_truth.json`, which the tests read. The corpus is 72MB of
logs on one machine; the fixture is a few KB and is committed, so the parity tests run on
a fresh clone with no corpus at all. Regenerate it with `--write` when the corpus grows.

THE INSTRUMENT CHECKS ITSELF, AND THAT IS THE ONLY REASON TO TRUST IT
--------------------------------------------------------------------
Every derivation here is a guess until it reproduces something BGA computed independently.
BGA ships a per-player `scoreBreakdown` -- vpDuringTheGame / coinsAndSeals / food / iron /
pearl / passageOfTime / courtiers / warriors / gardeners / score -- in `updateLiveScore`.
So the tool reconstructs each final board position out of the event stream and RECOMPUTES
all nine categories with the derived formulas. A formula that is wrong does not produce a
slightly odd fixture; it fails to reproduce 70 real scoreboards and this tool exits 1.

`--verify` prints that reconstruction. It currently reads 70/70 seats exact on the 20
base-game logs, which is what makes the scoring section of the fixture evidence rather
than assertion.

TWO THINGS THAT LOOK LIKE NOISE AND ARE NOT
-------------------------------------------
- **`isUndo` events are STATE, not chatter.** BGA replays a rolled-back action as the same
  notification with `isUndo: true` carrying the RESTORED value, and players undo constantly
  (one seat restarted its turn nine times). Skipping those events reads a courtier at the
  room it was pulled back out of: courtier scoring came out wrong on 11 of 70 seats until
  undos were applied, and every one of those looked like a scoring-table bug.
- **The corpus is NOT all base game.** 9 of the 29 logs are Matcha, which adds green dice,
  a fourth personal-domain row, geishas, chasen, the Tea Fields and the Outskirts of
  Himeji, and its own cards sharing the base id space. Derive from those and the base
  board grows two action spaces that do not exist in our box. `classify()` splits them and
  everything here runs on the base games only.

Usage::

    python -m games.black_castle.tools.bga_parity [--corpus <dir>]
    python -m games.black_castle.tools.bga_parity --verify   # recompute every scoreboard
    python -m games.black_castle.tools.bga_parity --write    # refresh the committed fixture
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

DEFAULT_CORPUS = os.environ.get("WHITECASTLE_CORPUS", "C:/Users/Forrest/WhiteCastle_corpus")

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
GROUND_TRUTH = os.path.join(_DATA, "bga_ground_truth.json")

#: Notifications that only ever appear once the Matcha expansion is in the box.
_MATCHA_MARKERS = ("geishaAssigned", "geishaMoved", "ceremonyTileGained",
                   "flowerCalligraphyLanternRefresh")

#: Castle rooms, and the Clan Points a courtier standing in one is worth at the end.
#: `daimyo-card` is the same floor as `main-board-daimyo`: a courtier that reaches the
#: third floor is moved onto a Daimyo's Favor card, which is a second notification about
#: the same courtier rather than a second place to be.
COURTIER_POINTS = {
    "main-board-gate": 1,
    "main-board-steward-1": 3, "main-board-steward-2": 3, "main-board-steward-3": 3,
    "main-board-diplomat-1": 6, "main-board-diplomat-2": 6,
    "main-board-daimyo": 10, "daimyo-card": 10,
}

#: A courtier counts toward the warrior multiplier only once it is INSIDE the castle.
#: The gate is on the board but outside the walls, and it is excluded.
INSIDE_THE_CASTLE = {k for k, v in COURTIER_POINTS.items() if v >= 3}


def _packets(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _events(packets):
    for packet in packets:
        for event in packet.get("data") or ():
            if isinstance(event, dict):
                yield event


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def classify(packets):
    """-> (ruleset, seat count). ``ruleset`` is "base" or "matcha"."""
    seats, matcha = set(), False
    for event in _events(packets):
        if event.get("type") in _MATCHA_MARKERS:
            matcha = True
        args = event.get("args")
        if isinstance(args, dict) and isinstance(args.get("scoreBreakdown"), dict):
            seats |= set(args["scoreBreakdown"])
    return ("matcha" if matcha else "base"), len(seats)


def _action_args(event):
    args = event.get("args")
    if not isinstance(args, dict):
        return None
    inner = args.get("args")
    if not isinstance(inner, dict):
        return None
    action = inner.get("action")
    if not isinstance(action, dict):
        return None
    out = action.get("actionArgs")
    return out if isinstance(out, dict) else None


# --------------------------------------------------------------------------------------
# board geometry
# --------------------------------------------------------------------------------------

def action_spaces(games):
    """-> {space id: {value, dice_colors, max_dice, name}} for the base board.

    `value` and `maxNrOfDice` are printed on the board and BGA ships them literally. The
    COLOURS are not: they come from the die-colour tiles laid into each castle room at
    setup, so they are derived from what the game actually offered -- the union, over every
    "choose a die" state, of the colours whose legal-destination list contained the space.
    A personal domain row is keyed by its worker rather than by its owner, since BGA names
    those spaces after the player id.
    """
    spaces = {}
    for packets in games:
        for event in _events(packets):
            args = event.get("args") or {}
            if not isinstance(args, dict):
                continue
            inner = args.get("args") if isinstance(args.get("args"), dict) else {}
            offers = inner.get("actionSpaces")
            dice = {d["id"]: d for d in (inner.get("dice") or ()) if isinstance(d, dict)}
            if isinstance(offers, dict):
                for die_id, options in offers.items():
                    die = dice.get(int(die_id))
                    for space in options or ():
                        key = _space_key(space)
                        row = spaces.setdefault(key, {"value": space.get("value"),
                                                      "name": space.get("locationName"),
                                                      "max_dice": space.get("maxNrOfDice"),
                                                      "die_colors": set()})
                        if die:
                            row["die_colors"].add(die["type"])
            if event.get("type") == "diePlaced":
                space = args.get("actionSpace") or {}
                if space:
                    key = _space_key(space)
                    row = spaces.setdefault(key, {"value": space.get("value"),
                                                  "name": space.get("locationName"),
                                                  "max_dice": space.get("maxNrOfDice"),
                                                  "die_colors": set()})
                    row["die_colors"].add((args.get("die") or {}).get("type"))
    for row in spaces.values():
        row["die_colors"] = sorted(c for c in row["die_colors"] if c)
    return spaces


def _space_key(space):
    sid = str(space.get("id", ""))
    if "action-space-player-" in sid:
        return "personal-domain:" + str(space.get("type"))
    return sid.replace("action-space-main-board-", "")


def castle_room_colors(games):
    """-> Counter over the colour SETS a single room offered within one game.

    This is the rule our engine has no concept of. At setup each castle room is filled
    with die-colour tiles -- one per row of the card that will sit there, at least two
    distinct colours per room -- and a die may only be placed in a room whose tiles include
    its colour; the rows whose tile matches are the ones that resolve. The tiles are fixed
    for the whole game, which is exactly what the data shows: a room's colour set never
    moves even as the card in it is taken and replaced, and sets of size 3 appear (three
    rows, three tiles, sometimes three different colours).
    """
    sizes = collections.Counter()
    for packets in games:
        per_room = collections.defaultdict(set)
        for event in _events(packets):
            args = event.get("args") or {}
            if not isinstance(args, dict):
                continue
            inner = args.get("args") if isinstance(args.get("args"), dict) else {}
            offers = inner.get("actionSpaces")
            if not isinstance(offers, dict):
                continue
            dice = {d["id"]: d for d in (inner.get("dice") or ()) if isinstance(d, dict)}
            for die_id, options in offers.items():
                die = dice.get(int(die_id))
                if not die:
                    continue
                for space in options or ():
                    key = _space_key(space)
                    if key.startswith(("steward-", "diplomat-")):
                        per_room[key].add(die["type"])
        for colors in per_room.values():
            sizes[len(colors)] += 1
    return sizes


def gardens(games):
    """-> sorted [(type, foodCost, pointValue, action)] for the base garden deck."""
    out = {}
    for packets in games:
        for event in _events(packets):
            extra = _action_args(event)
            for card in (extra or {}).get("gardenCards") or ():
                key = (card.get("type"), card.get("foodCost"), card.get("pointValue"),
                       card.get("actionDescription"),
                       json.dumps({k: v for k, v in (card.get("actionDescriptionArgs") or {}).items()
                                   if k not in ("i18n", "disabledReason")}, sort_keys=True))
                out[key] = out.get(key, 0) + 1
    return sorted(out)


def training_yards(games):
    """-> {yard id: {iron_cost, point_value}}. Fixed board printing, not a random deal."""
    out = {}
    for packets in games:
        for event in _events(packets):
            extra = _action_args(event)
            for yard in (extra or {}).get("trainingYards") or ():
                out[int(yard["id"])] = {"iron_cost": yard["ironCost"],
                                        "point_value": yard["pointValue"]}
    return dict(sorted(out.items()))


def worker_costs(games):
    """-> what a worker placement actually charged, counted over the corpus.

    Read off the payments in the same packet rather than from any rule text: the iron paid
    beside each `warriorAssigned`, the coins beside each `courtierAssigned` (the audience at
    the gate), and the mother-of-pearl beside each `courtierMovedUp`, bucketed by how many
    floors the courtier climbed.
    """
    yard_iron = collections.Counter()
    gate_coins = collections.Counter()
    climb = collections.Counter()
    level = {k: (0 if k == "main-board-gate" else 1 if v == 3 else 2 if v == 6 else 3)
             for k, v in COURTIER_POINTS.items()}
    for packets in games:
        where = {}
        for packet in packets:
            events = [e for e in (packet.get("data") or ()) if isinstance(e, dict)]
            for i, event in enumerate(events):
                kind, args = event.get("type"), event.get("args") or {}
                if not isinstance(args, dict) or args.get("isUndo"):
                    continue
                before = events[max(0, i - 3):i]
                if kind == "warriorAssigned":
                    iron = sum(e["args"]["numberOfResources"] for e in before
                               if e.get("type") == "resourcePaid"
                               and (e.get("args") or {}).get("resource") == "iron"
                               and not e["args"].get("isUndo"))
                    yard_iron[(int(args["warrior"]["locationArg"]), iron)] += 1
                elif kind == "courtierAssigned":
                    coins = sum(e["args"]["numberOfCoins"] for e in before
                                if e.get("type") == "coinPaid" and not e["args"].get("isUndo"))
                    gate_coins[coins] += 1
                    where[args["courtier"]["id"]] = args["courtier"]["location"]
                elif kind in ("courtierMovedUp", "courtierPlacedOnDaimyoCard"):
                    cid = args["courtier"]["id"]
                    start = level.get(where.get(cid, "main-board-gate"), 0)
                    end = level.get(args["courtier"]["location"], 0)
                    pearl = sum(e["args"]["numberOfResources"] for e in before
                                if e.get("type") == "resourcePaid"
                                and (e.get("args") or {}).get("resource") == "pearl"
                                and not e["args"].get("isUndo"))
                    if end > start:
                        climb[(end - start, pearl)] += 1
                    where[cid] = args["courtier"]["location"]
    return {"warrior_iron_by_yard": dict(sorted(yard_iron.items())),
            "courtier_gate_coins": dict(sorted(gate_coins.items())),
            "courtier_climb_pearl_by_levels": dict(sorted(climb.items()))}


def _cards(node, out):
    if isinstance(node, dict):
        if "actionBlocks" in node and "id" in node:
            out.append(node)
        for value in node.values():
            _cards(value, out)
    elif isinstance(node, list):
        for value in node:
            _cards(value, out)


def well_rewards(games):
    """-> how many DISTINCT payouts the Well gave within one game.

    The Well is not a draw. Its two Die tiles are laid at setup dice-side DOWN, so their
    rewards face up and stay face up: "1 Daimyo Seal is gained along with the benefits
    indicated on the tiles there", the same benefits on every visit. If that is right, a
    game with several visits must show ONE payout signature -- which is what this counts,
    and a lottery would show as many signatures as visits.
    """
    per_game = collections.Counter()
    payouts = collections.Counter()
    for packets in games:
        seen = collections.Counter()
        for packet in packets:
            events = [e for e in (packet.get("data") or ()) if isinstance(e, dict)]
            for i, event in enumerate(events):
                args = event.get("args") or {}
                if event.get("type") != "diePlaced" or not isinstance(args, dict):
                    continue
                if args.get("isUndo") or not str(args["actionSpace"]["id"]).endswith("well"):
                    continue
                pid, got = str(args["playerId"]), []
                for later in events[i + 1:]:
                    kind, more = later.get("type"), later.get("args") or {}
                    if not isinstance(more, dict) or str(more.get("playerId", "")) != pid:
                        continue
                    # A gain carrying a cardId came from a card, not from the Well.
                    if more.get("isUndo") or more.get("cardId"):
                        continue
                    if kind == "resourceGained":
                        got.append("%s+%s" % (more["resource"], more["numberOfResources"]))
                    elif kind == "sealGained":
                        got.append("seal+%s" % more["numberOfSeals"])
                    elif kind == "coinGained" and more.get("dieId") is None:
                        got.append("coin+%s" % more["numberOfCoins"])
                    elif kind == "scoreUpdated":
                        got.append("vp+%s" % more["numberOfVp"])
                if got:
                    seen[tuple(sorted(got))] += 1
                    payouts[tuple(sorted(got))] += 1
        if seen:
            per_game[len(seen)] += 1
    return {"distinct_payouts_within_one_game": dict(sorted(per_game.items())),
            "payout_signatures": {" ".join(k): v for k, v in payouts.most_common()}}


def outside_the_walls(games):
    """-> which worker each Outside the Walls space let a player deploy.

    A turn can deploy more than one worker because a castle card may grant another, so
    only the turns that deployed EXACTLY ONE kind say anything about the space itself.
    Those are unambiguous, and they separate cleanly.
    """
    solo = collections.defaultdict(collections.Counter)
    for packets in games:
        pending = None
        for packet in packets:
            for event in (packet.get("data") or ()):
                if not isinstance(event, dict):
                    continue
                kind, args = event.get("type"), event.get("args") or {}
                if not isinstance(args, dict):
                    continue
                if kind == "diePlaced":
                    sid = str(args["actionSpace"]["id"])
                    pending = ([sid[-1], []] if ("outside-the-walls" in sid
                                                 and not args.get("isUndo")) else None)
                    continue
                if pending is None or args.get("isUndo"):
                    continue
                if kind in ("gardenerAssigned", "warriorAssigned"):
                    pending[1].append(kind.replace("Assigned", ""))
                elif kind in ("courtierAssigned", "courtierMovedUp"):
                    pending[1].append("courtier")
                elif kind == "gameLog" and "confirms his turn" in str(event.get("log")):
                    if len(set(pending[1])) == 1:
                        solo[pending[0]][pending[1][0]] += 1
                    pending = None
    return {space: dict(c.most_common()) for space, c in sorted(solo.items())}


def dice_stacking(games):
    """-> the most dice ever seen on one space of each kind, between rerolls."""
    peak = collections.defaultdict(int)
    for packets in games:
        live = collections.Counter()
        for event in _events(packets):
            args = event.get("args") or {}
            if event.get("type") == "diceRolled":
                live.clear()
                continue
            if event.get("type") != "diePlaced" or not isinstance(args, dict):
                continue
            sid = str(args["actionSpace"]["id"])
            family = ("personal-domain" if "action-space-player-" in sid
                      else "".join(c for c in sid.replace("action-space-main-board-", "")
                                   if not c.isdigit()).rstrip("-"))
            live[sid] += -1 if args.get("isUndo") else 1
            peak[family] = max(peak[family], live[sid])
    return dict(sorted(peak.items()))


def diamond_cards(games):
    """-> the printed cards marked with a diamond, which a 2-player game leaves out."""
    flags = collections.defaultdict(dict)
    for packets in games:
        out = []
        for packet in packets:
            _cards(packet, out)
        for card in out:
            if card.get("type") in ("steward", "diplomat"):
                flags[card["type"]][int(card["typeArg"])] = bool(card.get("diamond"))
    return {kind: {"diamond": sorted(k for k, v in rows.items() if v),
                   "plain": sorted(k for k, v in rows.items() if not v)}
            for kind, rows in sorted(flags.items())}


def yard_tiles(games):
    """-> the 8 double-sided yard tiles, and how many a game puts in play."""
    faces, in_play = {}, collections.Counter()
    for packets in games:
        latest = None
        for event in _events(packets):
            extra = _action_args(event)
            yards = (extra or {}).get("trainingYards")
            if not yards:
                continue
            latest = yards
            for yard in yards:
                for tile in yard.get("yardTiles") or ():
                    faces["%s %s" % (tile["typeArg"], tile.get("side"))] = {
                        "yard": yard["id"],
                        "action": list(tile.get("actionDescription") or ()),
                        "args": tile.get("actionDescriptionArgs"),
                    }
        if latest:
            in_play[sum(len(y.get("yardTiles") or ()) for y in latest)] += 1
    return {"faces": dict(sorted(faces.items())), "tiles_in_play_per_game": dict(in_play)}


def effect_vocabulary(games):
    """-> every distinct effect template on a base card, with its operands.

    This is the whole job that remains. Counting it is what tells a reader whether
    porting the catalogue is a rewrite or an afternoon.
    """
    templates = collections.defaultdict(collections.Counter)
    blocks = collections.Counter()
    conditionals = collections.Counter()
    for packets in games:
        out = []
        for packet in packets:
            _cards(packet, out)
        for card in out:
            for block in card["actionBlocks"]:
                blocks[block["type"]] += 1
                conditionals[block.get("conditional")] += 1
                for desc in block["actionDescriptions"]:
                    text = desc["description"].replace(" ${disabledReason}", "")
                    args = {k: v for k, v in (desc.get("descriptionArgs") or {}).items()
                            if k not in ("i18n", "disabledReason")}
                    templates[text][json.dumps(args, sort_keys=True)] += 1
    return {"block_types": dict(blocks), "conditionals": dict(conditionals),
            "templates": {t: dict(v.most_common()) for t, v in sorted(templates.items())}}


def _cards(node, out):
    if isinstance(node, dict):
        if "actionBlocks" in node and "id" in node:
            out.append(node)
        for value in node.values():
            _cards(value, out)
    elif isinstance(node, list):
        for value in node:
            _cards(value, out)


def well_rewards(games):
    """-> how many DISTINCT payouts the Well gave within one game.

    The Well is not a draw. Its two Die tiles are laid at setup dice-side DOWN, so their
    rewards face up and stay face up: "1 Daimyo Seal is gained along with the benefits
    indicated on the tiles there", the same benefits on every visit. If that is right, a
    game with several visits must show ONE payout signature -- which is what this counts,
    and a lottery would show as many signatures as visits.
    """
    per_game = collections.Counter()
    payouts = collections.Counter()
    for packets in games:
        seen = collections.Counter()
        for packet in packets:
            events = [e for e in (packet.get("data") or ()) if isinstance(e, dict)]
            for i, event in enumerate(events):
                args = event.get("args") or {}
                if event.get("type") != "diePlaced" or not isinstance(args, dict):
                    continue
                if args.get("isUndo") or not str(args["actionSpace"]["id"]).endswith("well"):
                    continue
                pid, got = str(args["playerId"]), []
                for later in events[i + 1:]:
                    kind, more = later.get("type"), later.get("args") or {}
                    if not isinstance(more, dict) or str(more.get("playerId", "")) != pid:
                        continue
                    # A gain carrying a cardId came from a card, not from the Well.
                    if more.get("isUndo") or more.get("cardId"):
                        continue
                    if kind == "resourceGained":
                        got.append("%s+%s" % (more["resource"], more["numberOfResources"]))
                    elif kind == "sealGained":
                        got.append("seal+%s" % more["numberOfSeals"])
                    elif kind == "coinGained" and more.get("dieId") is None:
                        got.append("coin+%s" % more["numberOfCoins"])
                    elif kind == "scoreUpdated":
                        got.append("vp+%s" % more["numberOfVp"])
                if got:
                    seen[tuple(sorted(got))] += 1
                    payouts[tuple(sorted(got))] += 1
        if seen:
            per_game[len(seen)] += 1
    return {"distinct_payouts_within_one_game": dict(sorted(per_game.items())),
            "payout_signatures": {" ".join(k): v for k, v in payouts.most_common()}}


def outside_the_walls(games):
    """-> which worker each Outside the Walls space let a player deploy.

    A turn can deploy more than one worker because a castle card may grant another, so
    only the turns that deployed EXACTLY ONE kind say anything about the space itself.
    Those are unambiguous, and they separate cleanly.
    """
    solo = collections.defaultdict(collections.Counter)
    for packets in games:
        pending = None
        for packet in packets:
            for event in (packet.get("data") or ()):
                if not isinstance(event, dict):
                    continue
                kind, args = event.get("type"), event.get("args") or {}
                if not isinstance(args, dict):
                    continue
                if kind == "diePlaced":
                    sid = str(args["actionSpace"]["id"])
                    pending = ([sid[-1], []] if ("outside-the-walls" in sid
                                                 and not args.get("isUndo")) else None)
                    continue
                if pending is None or args.get("isUndo"):
                    continue
                if kind in ("gardenerAssigned", "warriorAssigned"):
                    pending[1].append(kind.replace("Assigned", ""))
                elif kind in ("courtierAssigned", "courtierMovedUp"):
                    pending[1].append("courtier")
                elif kind == "gameLog" and "confirms his turn" in str(event.get("log")):
                    if len(set(pending[1])) == 1:
                        solo[pending[0]][pending[1][0]] += 1
                    pending = None
    return {space: dict(c.most_common()) for space, c in sorted(solo.items())}


def dice_stacking(games):
    """-> the most dice ever seen on one space of each kind, between rerolls."""
    peak = collections.defaultdict(int)
    for packets in games:
        live = collections.Counter()
        for event in _events(packets):
            args = event.get("args") or {}
            if event.get("type") == "diceRolled":
                live.clear()
                continue
            if event.get("type") != "diePlaced" or not isinstance(args, dict):
                continue
            sid = str(args["actionSpace"]["id"])
            family = ("personal-domain" if "action-space-player-" in sid
                      else "".join(c for c in sid.replace("action-space-main-board-", "")
                                   if not c.isdigit()).rstrip("-"))
            live[sid] += -1 if args.get("isUndo") else 1
            peak[family] = max(peak[family], live[sid])
    return dict(sorted(peak.items()))


def diamond_cards(games):
    """-> the printed cards marked with a diamond, which a 2-player game leaves out."""
    flags = collections.defaultdict(dict)
    for packets in games:
        out = []
        for packet in packets:
            _cards(packet, out)
        for card in out:
            if card.get("type") in ("steward", "diplomat"):
                flags[card["type"]][int(card["typeArg"])] = bool(card.get("diamond"))
    return {kind: {"diamond": sorted(k for k, v in rows.items() if v),
                   "plain": sorted(k for k, v in rows.items() if not v)}
            for kind, rows in sorted(flags.items())}


def yard_tiles(games):
    """-> the 8 double-sided yard tiles, and how many a game puts in play."""
    faces, in_play = {}, collections.Counter()
    for packets in games:
        latest = None
        for event in _events(packets):
            extra = _action_args(event)
            yards = (extra or {}).get("trainingYards")
            if not yards:
                continue
            latest = yards
            for yard in yards:
                for tile in yard.get("yardTiles") or ():
                    faces["%s %s" % (tile["typeArg"], tile.get("side"))] = {
                        "yard": yard["id"],
                        "action": list(tile.get("actionDescription") or ()),
                        "args": tile.get("actionDescriptionArgs"),
                    }
        if latest:
            in_play[sum(len(y.get("yardTiles") or ()) for y in latest)] += 1
    return {"faces": dict(sorted(faces.items())), "tiles_in_play_per_game": dict(in_play)}


def effect_vocabulary(games):
    """-> every distinct effect template on a base card, with its operands.

    This is the whole job that remains. Counting it is what tells a reader whether
    porting the catalogue is a rewrite or an afternoon.
    """
    templates = collections.defaultdict(collections.Counter)
    blocks = collections.Counter()
    conditionals = collections.Counter()
    for packets in games:
        out = []
        for packet in packets:
            _cards(packet, out)
        for card in out:
            for block in card["actionBlocks"]:
                blocks[block["type"]] += 1
                conditionals[block.get("conditional")] += 1
                for desc in block["actionDescriptions"]:
                    text = desc["description"].replace(" ${disabledReason}", "")
                    args = {k: v for k, v in (desc.get("descriptionArgs") or {}).items()
                            if k not in ("i18n", "disabledReason")}
                    templates[text][json.dumps(args, sort_keys=True)] += 1
    return {"block_types": dict(blocks), "conditionals": dict(conditionals),
            "templates": {t: dict(v.most_common()) for t, v in sorted(templates.items())}}


def passage_of_time(games):
    """-> track length, the checkpoint seal costs, and position -> Clan Points.

    The checkpoints are read from the places where the marker REFUSED to move: BGA sends
    `passageOfTimeMoved` with `steps: 0` when a player at a checkpoint does not pay, and the
    crossings that did happen carry the seal payment in the same packet. Three of them, at
    1 / 2 / 3 seals, which is the printed rule.

    THIS ONE DERIVATION RUNS OVER THE WHOLE CORPUS, base and Matcha alike, and that is
    deliberate rather than sloppy: the Passage of Time is base-game furniture that the
    expansion does not touch -- it adds tea, not time -- and the 20 base logs alone never
    reach past space 11, so they see only two of the three checkpoints and none of the
    fourth season. Restricting it would have shipped a fixture that stops where the corpus
    happens to stop and called that the end of the track.
    """
    gates = collections.Counter()
    blocked = collections.Counter()
    scoring = collections.Counter()
    highest = 0
    for packets in games:
        at = {}
        final = None
        for packet in packets:
            events = [e for e in (packet.get("data") or ()) if isinstance(e, dict)]
            for i, event in enumerate(events):
                args = event.get("args") or {}
                if not isinstance(args, dict):
                    continue
                if event.get("type") == "updateLiveScore":
                    final = args["scoreBreakdown"]
                    continue
                if event.get("type") != "passageOfTimeMoved":
                    continue
                pid = str(args["playerId"])
                spot = None
                for marker in args.get("influenceMarkers") or ():
                    position = int(str(marker["location"]).split("-")[1])
                    highest = max(highest, position)
                    if str(marker["playerId"]) == pid:
                        spot = position
                if spot is None:
                    continue
                was = at.get(pid, 0)
                at[pid] = spot
                if args.get("isUndo"):
                    continue
                if args.get("steps") == 0:
                    blocked[spot] += 1
                elif spot > was:
                    seals = sum(e["args"]["numberOfSeals"] for e in events[:i]
                                if e.get("type") == "sealPaid"
                                and str((e.get("args") or {}).get("playerId")) == pid
                                and not e["args"].get("isUndo"))
                    for step in range(was + 1, spot + 1):
                        if step in (6, 11, 15):
                            gates[(step, seals)] += 1
        if final:
            for pid, row in final.items():
                scoring[(at.get(pid, 0), row["passageOfTime"])] += 1
    return {"highest_seen": highest,
            "blocked_at": dict(sorted(blocked.items())),
            "checkpoint_seals": dict(sorted(gates.items())),
            "position_to_points": dict(sorted(scoring.items()))}


def turn_order(games):
    """-> how often "track position, then top of the marker stack" predicted the new order.

    Turn order for the next round is not the previous round's order: the marker furthest
    along the Passage of Time leads, and a tie is broken by which marker is ON TOP -- the
    one that arrived on that space most recently. BGA gives both halves directly, the
    space in `location` and the height in `locationArg`.
    """
    hits = misses = 0
    for packets in games:
        markers = {}
        for event in _events(packets):
            args = event.get("args") or {}
            if not isinstance(args, dict):
                continue
            if event.get("type") == "passageOfTimeMoved":
                for marker in args.get("influenceMarkers") or ():
                    markers[str(marker["playerId"])] = (
                        int(str(marker["location"]).split("-")[1]), int(marker["locationArg"]))
            elif event.get("type") == "heronsUpdated":
                actual = sorted(((int(h["locationArg"]), str(h["playerId"]))
                                 for h in args.get("herons") or ()))
                order = [pid for _, pid in actual]
                predicted = sorted(markers, key=lambda p: (-markers[p][0], -markers[p][1]))
                if order == predicted:
                    hits += 1
                else:
                    misses += 1
    return {"stack_top_first": hits, "mismatches": misses}


# --------------------------------------------------------------------------------------
# scoring, and the reconstruction that proves it
# --------------------------------------------------------------------------------------

def _resource_points(amount):
    return 2 if amount >= 7 else 1 if amount >= 3 else 0


def _passage_points(position):
    """0 / 3 / 6 by season, then the value printed on the fourth season's space."""
    if position >= 15:
        return min(15, 10 + position - 15)
    if position >= 11:
        return 6
    if position >= 6:
        return 3
    return 0


def reconstruct(packets, yard_points):
    """-> {pid: (computed breakdown, BGA's breakdown)} for one finished game."""
    held = collections.defaultdict(dict)
    courtier_at, warrior_at, gardener_at = {}, {}, {}
    garden_points, track, final = {}, {}, None
    for event in _events(packets):
        kind, args = event.get("type"), event.get("args") or {}
        if kind == "updateLiveScore":
            final = args["scoreBreakdown"]
            continue
        if not isinstance(args, dict):
            continue
        for card in (_action_args(event) or {}).get("gardenCards") or ():
            garden_points[card["id"]] = card["pointValue"]
        pid = str(args.get("playerId", ""))
        if kind in ("resourceGained", "resourcePaid"):
            held[pid][args["resource"]] = args["resourceValue"]
        elif kind in ("coinGained", "coinPaid"):
            held[pid]["coin"] = args["coinValue"]
        elif kind in ("sealGained", "sealPaid"):
            held[pid]["seal"] = args["sealValue"]
        elif kind in ("courtierAssigned", "courtierMovedUp", "courtierPlacedOnDaimyoCard"):
            courtier_at[args["courtier"]["id"]] = (pid, args["courtier"]["location"])
        elif kind == "warriorAssigned":
            warrior_at[args["warrior"]["id"]] = (
                pid, None if args.get("isUndo") else int(args["warrior"]["locationArg"]))
        elif kind == "gardenerAssigned":
            gardener_at[args["gardener"]["id"]] = (
                pid, None if args.get("isUndo") else int(args["gardener"]["locationArg"]))
        elif kind == "passageOfTimeMoved":
            for marker in args.get("influenceMarkers") or ():
                track[str(marker["playerId"])] = int(str(marker["location"]).split("-")[1])
    out = {}
    for pid, given in (final or {}).items():
        purse = held.get(pid, {})
        rooms = [where for owner, where in courtier_at.values() if owner == pid]
        inside = sum(1 for where in rooms if where in INSIDE_THE_CASTLE)
        yards = [yard for owner, yard in warrior_at.values() if owner == pid and yard]
        plots = [garden_points.get(card, 0)
                 for owner, card in gardener_at.values() if owner == pid and card]
        mine = {
            "coinsAndSeals": (purse.get("coin", 0) + purse.get("seal", 0)) // 5,
            "food": _resource_points(purse.get("food", 0)),
            "iron": _resource_points(purse.get("iron", 0)),
            "pearl": _resource_points(purse.get("pearl", 0)),
            "passageOfTime": _passage_points(track.get(pid, 0)),
            "courtiers": sum(COURTIER_POINTS.get(where, 0) for where in rooms),
            "warriors": sum(yard_points[yard] for yard in yards) * inside,
            "gardeners": sum(plots),
        }
        out[pid] = (mine, {k: given[k] for k in mine})
    return out


# --------------------------------------------------------------------------------------

def build(games, yard_points, all_games=None):
    spaces = action_spaces(games)
    return _jsonable({
        "source": "BGA game logs, base game only",
        "action_spaces": {k: v for k, v in sorted(spaces.items())},
        "castle_room_color_set_sizes": dict(sorted(castle_room_colors(games).items())),
        "gardens": [{"type": t, "food_cost": c, "point_value": p, "action": a,
                     "action_args": json.loads(g)}
                    for t, c, p, a, g in gardens(games)],
        "training_yards": training_yards(games),
        "yard_tiles": yard_tiles(games),
        "well": well_rewards(games),
        "outside_the_walls": outside_the_walls(games),
        "dice_stacking_peak": dice_stacking(games),
        "diamond_cards": diamond_cards(games),
        "effect_vocabulary": effect_vocabulary(games),
        "yard_tiles": yard_tiles(games),
        "well": well_rewards(games),
        "outside_the_walls": outside_the_walls(games),
        "dice_stacking_peak": dice_stacking(games),
        "diamond_cards": diamond_cards(games),
        "effect_vocabulary": effect_vocabulary(games),
        "worker_costs": worker_costs(games),
        "passage_of_time": passage_of_time(all_games or games),
        "turn_order": turn_order(games),
        "scoring": {
            "courtier_points_by_room": COURTIER_POINTS,
            "warriors": "sum of the point value of each warrior's yard, times the number "
                        "of that clan's courtiers INSIDE the castle (the gate does not count)",
            "gardeners": "sum of the point value of every garden card a gardener stands on",
            "coins_and_seals": "(coins + seals) // 5",
            "resources": "0 below 3, 1 at 3-6, 2 at 7 (the cap), per resource",
            "passage_of_time": "0 / 3 / 6 by season, then 10-15 printed in the fourth",
        },
        "caps": {"seals": 5, "resources": 7, "coins": None},
        "structure": {"rounds": 3, "turns_per_player_per_round": 3,
                      "dice_per_color": {"2": 3, "3": 4, "4": 5},
                      "die_colors": ["red", "black", "white"],
                      "bridge_names": ["Coral", "Black", "White"]},
    })


def _jsonable(node):
    """JSON has string keys only, and several derivations are keyed by a PAIR.

    "yard 1 charged 5 iron, 187 times" is one observation, so the pair is the key and the
    count is the evidence -- flattening it to a plain map would throw away the very thing
    that says a cost is uniform rather than merely common. The pairs are joined with a
    space and the tests split them back.
    """
    if isinstance(node, dict):
        return {(" ".join(str(p) for p in k) if isinstance(k, tuple) else str(k)): _jsonable(v)
                for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_jsonable(v) for v in node]
    return node


def _fmt(counter):
    return ", ".join(f"{k}={v}" for k, v in counter.items())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--verify", action="store_true",
                    help="recompute every final scoreboard from the derived rules")
    ap.add_argument("--write", action="store_true", help="refresh data/bga_ground_truth.json")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    base, skipped = [], collections.Counter()
    for path in paths:
        packets = _packets(path)
        ruleset, seats = classify(packets)
        if ruleset == "base":
            base.append(packets)
        skipped[(ruleset, seats)] += 1
    print(f"{len(paths)} logs: " + _fmt(skipped))
    print(f"deriving from the {len(base)} BASE-game logs\n")
    if not base:
        return 1

    yards = training_yards(base)
    yard_points = {k: v["point_value"] for k, v in yards.items()}
    truth = build(base, yard_points, all_games=[_packets(p) for p in paths])

    for key in ("action_spaces", "training_yards", "passage_of_time", "worker_costs",
                "turn_order", "castle_room_color_set_sizes", "well", "outside_the_walls",
                "dice_stacking_peak", "diamond_cards"):
        print(key)
        print("  " + json.dumps(truth[key], indent=1).replace("\n", "\n  "))
    print("gardens")
    for row in truth["gardens"]:
        print(f"  {row['type']:<6} cost {row['food_cost']} -> {row['point_value']} points"
              f"   {row['action']}")

    exact = wrong = 0
    problems = []
    for path, packets in zip([p for p in paths if _packets(p) and classify(_packets(p))[0] == "base"], base):
        for pid, (mine, given) in reconstruct(packets, yard_points).items():
            if mine == given:
                exact += 1
            else:
                wrong += 1
                problems.append((os.path.basename(path), pid,
                                 {k: (mine[k], given[k]) for k in mine if mine[k] != given[k]}))
    print(f"\nscoreboard reconstruction: {exact} seats exact, {wrong} wrong")
    for row in problems[:10]:
        print("  MISMATCH", row)
    if args.verify and wrong:
        return 1

    if args.write:
        truth["reconstruction"] = {"seats_exact": exact, "seats_wrong": wrong,
                                   "base_logs": len(base)}
        with open(GROUND_TRUTH, "w", encoding="utf-8") as fh:
            json.dump(truth, fh, indent=1, sort_keys=True)
        print(f"\nwrote {GROUND_TRUTH}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
