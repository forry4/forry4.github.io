"""Replay real BGA Zenith games through Orbit's engine.

`AGENTS.md`: "BGA replays are the parity oracle." This is the harness that makes that
true. It is deliberately built in the order the Rag Tag harness was, because that order
is what got that game from 13/30 to full 40/40 parity:

  1. the ENGINE-DRIVING half first, proven against games the engine itself produced;
  2. the BGA-PARSING half second, written against real logs and never guessed.

STATUS
------
Half 1 is written and PROVEN: `selftest()` plays random games, records the intents, and
replays them through the same `drive()` a BGA log will use, asserting the replay lands on
an identical final state. So when a real log fails, the failure is in the parse or in the
rules -- not in the driver.

Half 2 is now COMPLETE for the rich archived corpus. `bga_table.py` reads a log,
`build_game` forces a table's setup, and `bga_cowalk.py` walks every choice against a
mirror of BGA's reported state. **40 of 40 tables consume their complete watched event
stream and reproduce the logged winner, including all 27 tables with undo batches.**
`--verify` separately checks that **40 of 40 reproduce both opening hands exactly.**
The pieces that took the work:

  * an archived log is one globally ordered stream across all three channels, so first
    appearance in file order IS draw order -- asserted on load rather than assumed,
    because a per-channel grouping would scramble the deck and present as a rules
    divergence twenty moves later;
  * seat 1 is the first player, and BGA's influence signs are INVERTED relative to ours;
  * draws are SCRIPTED, not pre-arranged, because BGA issues a new `card_id` for a card
    that returns through a reshuffle (4 of the 40 tables do this).

WHAT IS LEFT, AND WHY THE CORPUS IS ALL EXPANSION
-------------------------------------------------
Every archived table carrying card identities is a Secret Agents game -- 0 of 40 are
expansion-free -- so `build_game` deals the 100-card pool. That is why the expansion
exists in `effects.py` at all; see `tests/test_secret_agents.py`.

The co-walk does not read the log as a list of answers -- it cannot, because BGA emits
the same event for a chosen effect and an auto-resolved one. It converges a MIRROR of
BGA's state against the engine and picks the move the mirror can reach. The face-up bonus
tokens and board sides, neither of which is ever announced, are handled there: token
identities come from `gainBonus` at award time, the eight board configurations are
searched, and undo restores the engine, deck script, bonus script and mirror snapshot.

Usage::

    python -m games.orbit.tools.bga_replay --selftest [--games 50]
    python -m games.orbit.tools.bga_replay --verify          # forced setup vs the corpus
    python -m games.orbit.tools.bga_replay --cowalk          # full parity over all rich tables
    python -m games.orbit.tools.bga_replay <table_id>        # replay one table
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import sys

from games.orbit import engine
from games.orbit.cards import ALL_CARDS
from games.orbit.tools import bga_table

#: Where the cob-mining cron drops Zenith logs. Same env-var-with-a-default shape the Rag
#: Tag tools use, so the corpus can move without editing code.
CORP = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")
LOGS = CORP + "/logs"

#: The five actions the engine accepts. `choose` is POLYMORPHIC and that is the single
#: most useful thing to know before writing the parser: it answers whatever sub-decision
#: is pending, and its payload is one of at least nine shapes -- `card_id`, `planet`,
#: `planets` (a pair), `faction`, `tier`, `branch`, `accept`, `cost`+`amount`, or
#: `bonus_area`+`slot`. A first cut of this file keyed `choose` on `planet` alone and the
#: selftest caught it inside one game: two pending choices both matched `planet: null`.
#: So a move's identity is the WHOLE dict, not a chosen subset of it.
ACTIONS = ("mulligan", "leader", "recruit", "technology", "choose")

#: The `_private` prompt types BGA publishes for a sub-decision, each carrying its
#: own option list. Their existence is what makes a co-walk tractable: a decision
#: is a MENU plus a consequence, not a consequence to be reverse-engineered alone.
#: `confirm` is excluded -- it is the "you cannot Restart after this" dialog, a UI
#: step rather than a game choice.
DECISION_PROMPTS = frozenset(
    {"planets", "cards", "techs", "bonus", "discardcards", "choice", "apply", "yesno"})


def whose_move(game: dict) -> str:
    """Who the engine is waiting on. Mirrors tools/soak.py, which is the proven driver."""
    if game["phase"] == "mulligan":
        return next(pid for pid in game["players"] if pid not in game["mulligan_done"])
    return game["pending_pid"] if game.get("pending") else game["turn_pid"]


def as_intent(move: dict) -> dict:
    """The identity of a move: all of it.

    Subsetting the fields is what a log-shaped intent WANTS to be, and it is wrong here --
    see ACTIONS. The parser's job is therefore to reconstruct a full move from a log
    event; `match` then holds that reconstruction to what the engine actually offers,
    which is the check that makes a wrong reconstruction loud instead of silent.
    """
    action = move.get("action")
    if action not in ACTIONS:
        raise KeyError(f"unknown move action {action!r} -- ACTIONS is out of date")
    return dict(move)


def match(moves: list[dict], intent: dict) -> dict:
    """The legal move this intent names.

    SELECTED from `legal_moves`, never constructed. A hand-built move that the engine
    happens to accept proves nothing about whether it was the move the human made, and a
    hand-built move the engine rejects looks like a rules bug.
    """
    hits = [m for m in moves if as_intent(m) == intent]
    if hits:
        # MEASURED: across 10,985 decision points in 60 random games, `legal_moves` never
        # offered two byte-identical entries, so this never has to choose. If one ever
        # appears the entries are equal, and applying either is the same move.
        return hits[0]
    raise LookupError(
        f"no legal move matches {json.dumps(intent, sort_keys=True)}; "
        f"legal now: {json.dumps([as_intent(m) for m in moves], sort_keys=True)[:400]}")


def drive(game: dict, intents: list[dict], *, validate: bool = True) -> int:
    """Apply intents in order. Returns how many were consumed.

    Stops early and cleanly when the game ends, because a real log can carry trailing
    packets after the win: that is normal, not a mismatch.
    """
    used = 0
    for intent in intents:
        if engine.is_over(game):
            break
        pid = whose_move(game)
        moves = engine.legal_moves(game, pid)
        if not moves:
            raise AssertionError(f"engine stalled with {len(intents) - used} intents left")
        ok, error = engine.apply_move(game, pid, match(moves, intent))
        if not ok:
            raise AssertionError(f"engine rejected a move it had just offered: {error}")
        if validate:
            engine.validate_state(game)
        used += 1
    return used


def record(seed: int, configuration: str = "sun", move_cap: int = 1500) -> tuple[dict, list[dict]]:
    """Play a reproducible random game and keep the intents it produced.

    This is the STAND-IN for a BGA log until real ones land: same driver, same matcher,
    same comparison -- only the source of the intents differs.
    """
    chooser = random.Random(seed * 104_729 + 17)
    game = engine.new_game(["A", "B"], seed=seed, configuration=configuration)
    intents: list[dict] = []
    for _ in range(move_cap):
        if engine.is_over(game):
            return game, intents
        pid = whose_move(game)
        moves = engine.legal_moves(game, pid)
        if not moves:
            raise AssertionError(f"seed {seed} stalled")
        move = chooser.choice(moves)
        intents.append(as_intent(move))
        ok, error = engine.apply_move(game, pid, move)
        if not ok:
            raise AssertionError(f"seed {seed} rejected a legal move: {error}")
    raise AssertionError(f"seed {seed} exceeded {move_cap} moves")


def fingerprint(game: dict) -> str:
    """What two runs of the same game must agree on, to the byte.

    The move LOG is excluded on purpose: it carries prose, and comparing prose turns a
    wording change into a parity failure. Everything mechanical is in.
    """
    return json.dumps({k: v for k, v in sorted(game.items()) if k != "log"},
                      sort_keys=True, default=str)


def selftest(games: int, configuration: str = "sun") -> int:
    """Prove the DRIVER before trusting it to judge the engine.

    An instrument that has not been calibrated on cases known to pass will blame the
    thing it is measuring. This is that calibration: the intents are known-good by
    construction, so any failure here is the harness.
    """
    for seed in range(games):
        played, intents = record(seed, configuration)
        fresh = engine.new_game(["A", "B"], seed=seed, configuration=configuration)
        used = drive(fresh, intents)
        if used != len(intents):
            raise AssertionError(f"seed {seed}: consumed {used} of {len(intents)} intents")
        if engine.winner(fresh) != engine.winner(played):
            raise AssertionError(
                f"seed {seed}: replay won by {engine.winner(fresh)}, "
                f"original by {engine.winner(played)}")
        if fingerprint(fresh) != fingerprint(played):
            raise AssertionError(f"seed {seed}: replay diverged from the original game")
    print(f"driver OK: {games} games recorded and replayed to an identical final state "
          f"(configuration={configuration})")
    return 0


#: Seat ids used as Orbit player ids. Seat 1 moves first, so it is `order[0]`.
SEATS = ("1", "2")


class ScriptedDeck:
    """Draws the cards the log says were drawn, in the order it says.

    A pre-arranged deck is not enough, and the reason is worth writing down: BGA
    issues a NEW `card_id` for a card that comes back through a reshuffle, so a
    log can reveal the same card NUMBER twice (measured: 4 of the 40 archived
    tables do). Arranging one fixed deck cannot express "and then these cards
    were shuffled back in", but a scripted draw can -- it simply takes the next
    card the log names, from wherever the engine is currently keeping it.

    Conservation is preserved because the card is REMOVED from the deck or the
    discard rather than conjured, so `validate_state` still means something.

    When the script runs out -- a game that ends mid-deck, which is most of them
    -- it falls back to the engine's own draw, so the tail of a game is never
    fabricated.
    """

    def __init__(self, script: list[int]):
        self.script = list(script)
        self.taken = 0
        self.overrun = 0

    def __call__(self, game: dict) -> int | None:
        if not self.script:
            self.overrun += 1
            return _real_draw_agent(game)
        card = self.script.pop(0)
        for pile in ("agent_deck", "agent_discard"):
            if card in game[pile]:
                game[pile].remove(card)
                self.taken += 1
                return card
        raise AssertionError(
            f"the log draws card {card} but the engine has it in neither the deck "
            f"nor the discard -- it is already in play, so the draw order is wrong")


#: Captured before any patching so the fallback is the genuine article.
_real_draw_agent = engine._draw_agent


@contextlib.contextmanager
def scripted(deck: "ScriptedDeck"):
    """Install `deck` as the engine's draw for the duration.

    It has to cover the WHOLE replay, not just the opening deal: the mulligan
    refill, every end-of-turn refill and every `mobilize` draw are also draws the
    log recorded. Leaving it installed only for setup deals the right four cards
    and then diverges on the very next refill -- which is exactly how this was
    found.
    """

    previous = engine._draw_agent
    engine._draw_agent = deck
    try:
        yield deck
    finally:
        engine._draw_agent = previous


def build_game(table, board_sides: dict[str, int]) -> tuple[dict, ScriptedDeck]:
    """A game whose SETUP is the table's, not a seed's.

    The opening deal is done by the engine's own `_draw_to` through the scripted
    deck, which is the point: if the script were wrong, the very first hand would
    disagree with the log rather than something subtle going wrong twenty moves
    later. Measured across all 40 archived tables, the first eight reveals are
    seat 1's four then seat 2's four -- exactly `new_game`'s deal order.

    NOT forced here, because the log never announces them: the eight face-up
    bonus tokens, and the board sides, which the caller supplies.
    """

    game = engine.new_game(list(SEATS), seed=0, configuration=board_sides,
                           secret_agents=True)
    game["order"] = list(SEATS)
    deck = ScriptedDeck(table.deck_ids)

    # Put every card back, then deal through the script.
    for player in game["players"].values():
        player["hand"] = []
    game["agent_deck"] = list(ALL_CARDS)
    game["agent_discard"] = []
    with scripted(deck):
        for pid in game["order"]:
            engine._draw_to(game, pid, 4)
    engine.validate_state(game)
    return game, deck


def parse_actions(log: list) -> list[dict]:
    """Superseded by the co-walk in `replay_table`.

    Kept raising on purpose. A BGA log does not contain a move list that can be
    translated ONCE and then applied -- a sub-decision is a menu plus a
    consequence, and which sub-decision is being answered depends on where the
    engine has got to. So the log is read BESIDE the engine, not ahead of it.
    """
    raise NotImplementedError(
        "intents are resolved against engine state; see replay_table's co-walk")


def rich_tables(corpus: str = bga_table.CORPUS) -> list[str]:
    """Archived tables carrying both seats' card identities.

    Derived by READING the logs, never from a hand-written roster: a fixed list
    only guards the corpus shrinking, and the cron adds to it.
    """

    found = []
    directory = os.path.join(corpus, "logs")
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        table = bga_table.load(name[:-5], corpus)
        if table.rich:
            found.append(table.table_id)
    return found


def verify(corpus: str = bga_table.CORPUS) -> int:
    """Check the FORCED SETUP against every rich table, and report what remains.

    This lives in the tool rather than in pytest on purpose. The corpus is a
    gitignored local directory, so a test needing it would either fail on a fresh
    clone or -- worse -- opt out with the conditional skip the repo bans, which
    is a green tick over a check that never ran. `tests/test_bga_replay.py` covers
    everything that does not need a corpus.
    """

    tables, reproduced, undo_free, decisions = rich_tables(corpus), 0, 0, 0
    for table_id in tables:
        table = bga_table.load(table_id, corpus)
        owner = {}
        for _move_id, _index, kind, args in table.events():
            if kind != "newCards":
                continue
            raw = args.get("cards", {})
            for card in (raw.values() if isinstance(raw, dict) else raw):
                owner.setdefault(str(card["card_id"]), str(card["card_player_no"]))

        # Only the opening deal, which is all `newCards`; a mobilize reveal has no
        # owning HAND and is skipped rather than guessed at.
        expected: dict[str, list[int]] = {}
        for card_id in table.reveal_order[:8]:
            if card_id in owner:
                expected.setdefault(owner[card_id], []).append(table.card_num[card_id])

        game, _deck = build_game(table, {"robot": 1, "human": 1, "animod": 1})
        dealt = {pid: sorted(game["players"][pid]["hand"]) for pid in game["order"]}
        if dealt == {seat: sorted(cards) for seat, cards in expected.items()}:
            reproduced += 1
        else:
            print(f"  {table_id}: dealt {dealt}, log says {expected}")
        if not table.undos:
            undo_free += 1
        for _move_id, _index, kind, args in table.events():
            if kind == "playCardDiploTech" or (kind == "moveCard"
                                               and args.get("location") == "play"):
                decisions += 1
            elif kind == "gameStateChange":
                _pid, payload = bga_table.private(args)
                if payload and payload.get("type") in DECISION_PROMPTS:
                    decisions += 1
    print(f"{len(tables)} rich tables; opening deal reproduced from the forced setup "
          f"in {reproduced}/{len(tables)}")
    print(f"{undo_free} carry no undo, and the corpus holds {decisions} logged decisions")
    return 0 if reproduced == len(tables) else 1


def replay_table(table_id: str) -> int:
    path = f"{LOGS}/{table_id}.json"
    if not os.path.isfile(path):
        print(f"no log for table {table_id} at {path}")
        return 1
    with open(path, encoding="utf-8") as fh:
        log = json.load(fh)
    parse_actions(log)          # raises until half 2 exists
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("table_id", nargs="?", help="a downloaded BGA table id")
    parser.add_argument("--selftest", action="store_true",
                        help="prove the driver against engine-generated games")
    parser.add_argument("--games", type=int, default=25)
    parser.add_argument("--verify", action="store_true",
                        help="check the forced setup against every rich archived table")
    parser.add_argument("--cowalk", action="store_true",
                        help="walk every rich table beside the engine and require full parity")
    parser.add_argument("--configuration", default="sun", choices=("sun", "random"))
    args = parser.parse_args(argv)

    if args.verify:
        return verify()
    if args.cowalk:
        from games.orbit.tools import bga_cowalk
        return bga_cowalk.report()
    if args.selftest or not args.table_id:
        if not args.table_id:
            have = len(os.listdir(LOGS)) if os.path.isdir(LOGS) else 0
            print(f"{have} Zenith logs in {LOGS}; running the driver selftest.")
        return selftest(args.games, args.configuration)
    return replay_table(args.table_id)


if __name__ == "__main__":
    sys.exit(main())
