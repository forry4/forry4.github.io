"""One BGA Zenith table, read out of its archived log.

This is the PARSING half of the replay -- `bga_replay.py` owns the driving half.
Keeping them apart is the point: the driver is proven against games our own
engine produced, so when a real table fails, the failure is here or in the rules,
never in the thing doing the asking.

WHAT AN ARCHIVED LOG ACTUALLY CONTAINS
--------------------------------------
Far more than the spectator sample the older audits were written against. An
archived replay carries all three channels -- the table's, and BOTH players'
private ones -- concatenated into one globally ordered file (`packet_id` runs
1..n, `move_id` is monotonic). That gives us:

  * `newCards`: every card's identity AT THE MOMENT IT IS DRAWN, for both seats.
    In file order this IS the draw sequence, which is what makes a forced deck
    possible at all.
  * `gameStateChange` state 20 `_private`: the acting seat's hand plus its legal
    main actions WITH THE COST BGA CHARGED. An independent check on our pricing.
  * `gameStateChange` state 35 `_private`: the option list for every sub-decision
    -- planets, cards, techs, bonuses, branches, yes/no prompts.
  * the consequence events (`movePlanet`, `setTech`, `transfer`, `gainBonus`, ...)
    that say which option was taken.

So a decision is recoverable as MENU + CHOICE, not guessed from consequences
alone. What is NOT in the log is the setup: board sides and the eight face-up
bonus tokens are never announced. See `bga_replay` for how those are recovered.

TWO CONVENTIONS THAT ARE EASY TO GET BACKWARDS, BOTH VERIFIED AGAINST REAL LOGS
------------------------------------------------------------------------------
* **Seat 1 is the first player**, so `order = [seat1, seat2]`.
* **Influence signs are INVERTED.** BGA counts a planet toward seat 1 as
  NEGATIVE; Orbit counts toward `order[0]` as positive. Measured: seat 1's first
  Mercury gain reads `position: -1`, and Terra -- which the second player starts
  one step toward -- begins at BGA `+1` where Orbit stores `-1`. So
  ``orbit = -bga``, everywhere, with no exceptions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ..cards import PLANETS

#: Where the cob-mining cron drops Zenith logs.
CORPUS = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")

#: BGA planet ids are 1..5 in the order Orbit lists them.
PLANET_BY_ID = {index + 1: planet for index, planet in enumerate(PLANETS)}

#: BGA race ids. `race_ref` in the reference data agrees; this is the inverse.
FACTION_BY_ID = {1: "robot", 2: "human", 3: "animod"}

#: `playCardDiploTech.dest_type` and `moveCard.location`, as the move `type` the
#: private menu uses. Recruit is the odd one out because BGA moves the card to a
#: column rather than announcing a destination.
MAIN_ACTION_BY_TYPE = {1: "leader", 2: "recruit", 3: "technology"}


def influence(bga_position: int | None) -> int | None:
    """BGA disc position -> Orbit influence. See the module docstring."""

    return None if bga_position is None else -int(bga_position)


@dataclass
class Decision:
    """One thing a human was asked, and what they answered.

    `menu` is BGA's own option list where it published one. It is kept beside the
    choice because it is the only independent check that our `legal_moves` offers
    the same set -- a replay that merely ACCEPTS every logged move proves that the
    move was legal, never that we were not also offering illegal ones.
    """

    move_id: int
    seat: int
    kind: str
    menu: dict | None
    events: list[tuple[str, dict]] = field(default_factory=list)


@dataclass
class Table:
    """Everything one archived log says, in the order it said it."""

    table_id: str
    packets: list
    card_num: dict[str, int] = field(default_factory=dict)
    reveal_order: list[str] = field(default_factory=list)
    seat_of_player: dict[str, int] = field(default_factory=dict)
    winner_seat: int | None = None
    undos: int = 0
    #: Card ids revealed by `newCards`, i.e. dealt to a HAND. Kept apart from
    #: `card_num` because a mobilize also reveals a card, and a log that only ever
    #: reveals mobilized cards is a spectator log with no hands in it -- the very
    #: thing the rich subset is defined to exclude.
    dealt: set = field(default_factory=set)

    @property
    def rich(self) -> bool:
        """Does this log show both seats' hands?"""

        return bool(self.dealt) and self.winner_seat is not None

    @property
    def deck_ids(self) -> list[int]:
        """The drawn cards, as card NUMBERS, in draw order.

        Ordered by BGA's own `card_id`, NOT by the order the events arrive.
        BGA allocates a card id when the card leaves the deck, so the ids are the
        draw order -- but it emits a turn's end-of-turn `newCards` refill BEFORE
        the `mobilize` events of the same turn, whose cards were drawn first and
        carry LOWER ids. Trusting event order there deals a turn's cards in the
        wrong sequence from the first mobilize onward.

        A card recycled through a reshuffle gets a fresh, higher id, so the
        ordering still holds across one.
        """

        return [self.card_num[card_id]
                for card_id in sorted(self.reveal_order, key=int)]

    def events(self):
        """(move_id, packet_index, type, args) in global order."""

        for index, packet in enumerate(self.packets):
            move_id = int(packet.get("move_id") or 0)
            for event in packet.get("data") or []:
                args = event.get("args")
                if isinstance(args, dict) or args is None:
                    yield move_id, index, event.get("type"), args or {}


def load(table_id: str, corpus: str = CORPUS) -> Table:
    path = os.path.join(corpus, "logs", f"{table_id}.json")
    with open(path, encoding="utf-8") as handle:
        packets = json.load(handle)
    table = Table(table_id=table_id, packets=packets)

    # The file is globally ordered, so first appearance IS draw order. Assert it
    # rather than assume it: a per-channel grouping would silently scramble the
    # deck and present as a rules divergence twenty moves later.
    last = -1
    for index, packet in enumerate(packets):
        packet_id = int(packet.get("packet_id") or 0)
        if packet_id < last:
            raise AssertionError(
                f"table {table_id}: packet {index} is out of order "
                f"({packet_id} after {last}); the log is not a single ordered stream")
        last = packet_id

    for _move_id, _index, kind, args in table.events():
        if kind == "newCards":
            raw = args.get("cards", {})
            for card in (raw.values() if isinstance(raw, dict) else raw):
                if not isinstance(card, dict):
                    continue
                card_id = str(card["card_id"])
                if card_id not in table.card_num:
                    table.card_num[card_id] = int(card["card_num"])
                    table.reveal_order.append(card_id)
                    table.seat_of_player.setdefault(str(card["card_player_no"]), 0)
                table.dealt.add(card_id)
        elif kind == "mobilize":
            # A MOBILIZE IS ALSO A DRAW, and it is announced differently: the card
            # goes from the deck straight into a column, which is public, so BGA
            # names it in the `mobilize` event and never emits `newCards` for it.
            # Leaving these out drops them from the draw order, and the deck then
            # deals the wrong cards from the first mobilize onward -- which
            # presents as an effect doing nothing, or as a capture that never
            # happened in the real game.
            card_id = str(args["card_id"])
            if card_id not in table.card_num:
                table.card_num[card_id] = int(args["card_num"])
                table.reveal_order.append(card_id)
        elif kind == "undo":
            table.undos += 1
        elif kind == "gameover":
            table.winner_seat = int(args["player_no"])
    return table


def seat_of(args: dict) -> int | None:
    """The seat an event is about. BGA spells it three ways."""

    for key in ("player_no", "card_player_no", "playerId"):
        if args.get(key) is not None:
            try:
                return int(args[key])
            except (TypeError, ValueError):
                return None
    return None


def private(args: dict) -> tuple[int | None, dict | None]:
    """(BGA player_id, private payload) for a gameStateChange, or (None, None)."""

    nested = args.get("args")
    if not isinstance(nested, dict):
        return None, None
    payload = nested.get("_private")
    if not isinstance(payload, dict):
        return None, None
    return nested.get("player_id"), payload
