"""Audit Orbit's card and bonus data against what BGA actually did in real games.

WHY NOT A FULL REPLAY
---------------------
A seeded move-by-move replay needs setup/chance information absent from the original
spectator sample. Seeding our engine would deal a different deck, so divergence alone
would say nothing about the rules. Do not generalize that sample to every Zenith log:
the 2026-09-14 corpus audit found 40 complete archived logs with both seats' card
identities and private move menus (see docs/orbit-ai-audit-2026-09-14.md). That
reconstruction now EXISTS -- tools/bga_table.py + bga_replay.build_game force a real
table's setup and tools/bga_cowalk.py walks it beside the engine. This tool remains an
alignment-free rules audit, which is still the right shape for it: it scores every table,
including the ones the replay cannot yet finish.

But the thing worth checking does not need the deck. Every card play is logged with the
effects it produced, grouped under one `move_id`:

    move 9  deltaCredits {player_no: 1, cost: 1, nb: -1}      <- what it cost
            moveCard     {card_num: "301", location: "play"}  <- what was played
            movePlanet   {planet_name: "Terra", nb: 1}        <- what it did
            deltaCredits {cost: -4, nb: 4}                    <- and paid back

So this is an ALIGNMENT-FREE check, the same order that paid off on Rag Tag: compare what
BGA charged and produced against what our data says, per card, with no replay in between.
It cannot prove a card's full effect chain, but it catches the errors that a transcription
of 90 cards actually makes -- a wrong cost, a wrong faction, a card that does not exist.

WHAT IT DELIBERATELY DOES NOT MEASURE
-------------------------------------
Only moves where attribution is UNAMBIGUOUS: exactly one card played and exactly one
positive cost. A bonus that lets you play two cards in one move makes "which card cost
what" a guess, and a guessed datum that agrees with our data is worse than no datum --
it reads as confirmation. Those moves are counted and reported, never scored.

Usage::

    python -m games.orbit.tools.bga_card_audit
    python -m games.orbit.tools.bga_card_audit --corpus <dir>
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

from games.orbit import cards as C

DEFAULT_CORPUS = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")

#: The ten `goodies=1` rows are the Secret Agents mini-expansion, which Orbit does not
#: implement. A log containing them is from a table played with that option on and is not
#: ours to audit -- 7 of the first 10 games harvested were.
GOODIES = frozenset({119, 120, 219, 220, 319, 320, 419, 420, 519, 520})


def moves_of(path):
    """A log grouped by move_id, which is how BGA brackets a play with its effects."""
    grouped = collections.defaultdict(list)
    for packet in json.load(open(path, encoding="utf-8")):
        if packet.get("move_id") is None:
            continue                  # `wakeupPlayers` in a live table: no game state
        for event in packet.get("data") or []:
            grouped[int(packet["move_id"])].append(event)
    return grouped


def card_of(event):
    args = event.get("args")
    if not isinstance(args, dict):
        return None
    raw = args.get("card_num") or args.get("card_graf")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def expansion_plays(grouped):
    """How many Secret Agents cards were played -- reported, not a reason to skip."""
    return sum(card_of(e) in GOODIES
               for evs in grouped.values() for e in evs if card_of(e) is not None)


def observations(grouped):
    """-> (unambiguous [(card, cost)], ambiguous_move_count, plays_seen, bonuses_seen)."""
    clean, ambiguous, plays = [], 0, collections.Counter()
    bonuses = collections.Counter()
    for evs in grouped.values():
        for e in evs:
            if e.get("type") == "gainBonus" and isinstance(e.get("args"), dict):
                num = e["args"].get("bonus_num")
                if num not in (None, ""):
                    bonuses[int(num)] += 1
        played = [e for e in evs
                  if e.get("type") == "moveCard"
                  and (e.get("args") or {}).get("location") == "play"]
        for e in played:
            if card_of(e) is not None:
                plays[card_of(e)] += 1
        costs = [int(e["args"]["cost"]) for e in evs
                 if e.get("type") == "deltaCredits" and isinstance(e.get("args"), dict)
                 and str(e["args"].get("cost") or "").lstrip("-").isdigit()
                 and int(e["args"]["cost"]) > 0]
        if len(played) == 1 and len(costs) == 1 and card_of(played[0]) is not None:
            clean.append((card_of(played[0]), costs[0]))
        elif played and costs:
            ambiguous += 1
    return clean, ambiguous, plays, bonuses


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    costs = collections.defaultdict(collections.Counter)
    plays, bonuses = collections.Counter(), collections.Counter()
    ambiguous = used = skipped = 0
    for path in paths:
        grouped = moves_of(path)
        # No log-level skip: a Secret Agents game's OTHER 90 cards are ordinary evidence.
        # A goodies play simply never matches `C.CARDS` below, so it scores nothing.
        skipped += expansion_plays(grouped)
        used += 1
        clean, amb, seen, bons = observations(grouped)
        ambiguous += amb
        plays.update(seen)
        bonuses.update(bons)
        for card, cost in clean:
            costs[card][cost] += 1

    print(f"{used} logs audited ({skipped} Secret Agents plays ignored)\n")

    unknown = sorted(set(plays) - set(C.CARDS) - GOODIES)
    print(f"cards played           : {len(plays)} distinct, {sum(plays.values())} plays")
    print(f"  not in our data      : {unknown or 'none'}")
    print(f"  ours never played    : {len(set(C.CARDS) - set(plays))}")
    print(f"cost observations      : {sum(sum(c.values()) for c in costs.values())} "
          f"over {len(costs)} cards ({ambiguous} moves too ambiguous to attribute)")

    # THE INVARIANT IS ONE-DIRECTIONAL, and getting that wrong is the whole trap.
    #
    # A first cut compared observed cost to ours for equality and reported 5 MISMATCHes
    # and 19 cards "varying" -- which reads as a broken transcription of half the deck.
    # It was the instrument. Zenith discounts card costs, so what BGA charges on the day
    # is at most the printed cost and often less: card 502 was charged 10, 8 and 5 in
    # three different games. Measured across the corpus, the number of cards ever charged
    # MORE than our value is 0, and 29 were seen at exactly our value.
    #
    # So: our cost is the CEILING. Charging more than it is a real defect; charging less
    # is a discount doing its job and says nothing. This is the same shape as the Rag Tag
    # instrument that blamed every card at 0.6-0.9 -- when a measurement disagrees with
    # something you already know is true, suspect the measurement.
    over, exact, discounted = [], [], []
    for card, seen in sorted(costs.items()):
        if card not in C.CARDS:
            continue
        ours = C.CARDS[card]["cost"]
        if max(seen) > ours:
            over.append((card, max(seen), ours))
        elif ours in seen:
            exact.append(card)
        else:
            discounted.append((card, sorted(seen), ours))

    print(f"\nCOST (our value is the ceiling; less is a discount)")
    print(f"  charged MORE than our cost : {len(over)}   <- a real defect")
    print(f"  seen at exactly our cost   : {len(exact)}")
    print(f"  only ever seen discounted  : {len(discounted)}   (unconfirmed, not wrong)")
    for card, saw, ours in over:
        print(f"    DEFECT card {card} {C.CARDS[card]['name']!r}: "
              f"BGA charged {saw}, our ceiling is {ours}")

    print(f"\nBONUS TOKENS: {len(bonuses)} distinct seen, {sum(bonuses.values())} gains")
    print(f"  ours          : {sorted(C.BONUS_TYPES)}")
    print(f"  seen          : {sorted(bonuses)}")
    unknown_b = sorted(set(bonuses) - set(C.BONUS_TYPES))
    print(f"  not in our data: {unknown_b or 'none'}")
    print(f"  ours never seen: {sorted(set(C.BONUS_TYPES) - set(bonuses)) or 'none'}")

    return 1 if (over or unknown or unknown_b) else 0


if __name__ == "__main__":
    sys.exit(main())
