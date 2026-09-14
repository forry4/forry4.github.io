"""Walk a real BGA Zenith table beside the engine, one decision at a time.

`bga_table.py` reads the log and `bga_replay.build_game` forces the setup; this
is the part that decides WHICH move a human made and holds the engine to it.

WHY NOT JUST READ THE ANSWER OUT OF THE LOG
-------------------------------------------
Because the log emits the SAME event for a chosen effect and an auto-resolved
one. "The next `movePlanet` is the planet they picked" is only true if nothing
resolved itself first, and something usually did. A first cut mapped each
pending task type to an event type and stalled inside three decisions.

So the log is not read as a list of answers. Instead a MIRROR of BGA's own state
is advanced by consuming events until it AGREES with the engine, and a decision
is resolved by trying every legal move and keeping the one whose result the
mirror can reach. That also upgrades the replay from a legality check to a
PARITY check: a move being accepted only ever proved it was offered, never that
the state it produced is the state BGA had.

WHAT THE MIRROR HAS TO TRACK, AND WHY EACH PART EARNED ITS PLACE
----------------------------------------------------------------
Every field here was added because without it some decision became invisible and
the walk guessed -- then diverged several turns later, far from the cause:

  * influence and technology -- the obvious ones;
  * COLUMNS -- "which card do I exile" moves nothing else, so every candidate
    converged and the pick was arbitrary;
  * CREDITS and ZENITHIUM -- a branch like Ramses' "Transfer 2 cards OR gain 8
    Credits" differs in nothing else at all.

Two calibrations cost real time and are worth keeping written down:

  * **The control space is +/-4, not +/-3.** `engine.CONTROL_POSITION` says so and
    the corpus agrees: positions run -4..+4 and every capture is at +/-4. Orbit
    stores None the instant a disc arrives there, so raw positions disagree on
    exactly the captures. Guessed at 3 first, which halved the walk's reach.
  * **Prefer the candidate that EXPLAINS MORE of the log.** Convergence stops at
    the first agreement, so declining an optional matches having consumed ZERO
    events and beat accepting it every time. Ranking by events consumed fixed
    about a hundred and thirty decisions in one change.

MEASURED AND REJECTED -- DO NOT RE-ADD WITHOUT FIXING THE MODEL
---------------------------------------------------------------
Tracking the **Leader badge** looks like an obvious next field and is currently a
REGRESSION: 541 decisions without it, 515 with. It should help twice over -- a
branch like Geta's "take the gold Leader OR gain 8 Credits" is otherwise
invisible, and a wrong badge means a wrong hand limit, which refills the wrong
NUMBER of cards and drifts the draw script. So the idea is right and the model is
wrong.

What is known: `updateLeader` reports a seat's HAND LIMIT, not a badge -- its
`leader` value is 4, 5 or 6, i.e. no badge, silver, gold -- and a badge changing
hands emits TWO events, the taker and the loser. Tracking both seats' limits
therefore passes through a state the engine never holds; tracking the badge as
(owner, level) off the event naming a limit above the base is atomic and still
scored worse. Find out why before trying a third encoding, and A/B it: the reach
number is the only thing that settled this.

A known live example to debug against: in table 904694222 the engine declines a
`give_leader` optional ("Give the Leader for 7 Credits") that BGA accepted, with
every tracked fact in agreement at that point.

STATUS
------
The walk now replays all 40 rich archived tables end to end, including the 27
tables containing BGA undo batches, and reproduces each logged winner. It
consumes the complete watched event stream for every table; the corpus is now a
parity oracle rather than merely a setup or legality check. The remaining work
is to turn that verified trajectory set into training data and strength tests.
"""

from __future__ import annotations

import collections
import copy
import itertools
import json

from games.orbit import engine
from games.orbit.cards import ALL_CARDS, FACTIONS, PLANETS
from games.orbit.tools import bga_replay as R
from games.orbit.tools import bga_table as T
from games.orbit.tools.bga_table import FACTION_BY_ID, PLANET_BY_ID

#: The two events that announce a MAIN action.
MAIN = ("playCardDiploTech", "moveCard")

#: Everything that can move the state the mirror tracks. Anything not here is
#: presentation, and consuming it is a no-op.
WATCHED = ("newCards", "playCardDiploTech", "moveCard", "movePlanet", "setTech", "transfer",
           "discardCard", "gainBonus", "mobilize", "gainPlanet", "resetPlanet",
           "updateLeader", "deltaCredits", "deltaSolium", "setHandSize",
           "stealCredits", "stealSolium", "giveSolium", "giveCredits", "undo")

#: All eight board configurations. The sides are never announced, so they are
#: searched: a wrong side changes what a technology does, the replay diverges,
#: and "how far it got" scores the guess.
ALL_SIDES = [dict(zip(("robot", "human", "animod"), combo))
             for combo in itertools.product((1, 2), repeat=3)]

def seat(args):
    v = args.get('player_no')
    return None if v is None else str(int(v))


class Mirror:
    """What BGA says the state is. Only ABSOLUTE facts, which are the reliable ones."""

    def __init__(self, table):
        self.table = table
        self.influence = {p: 0 for p in PLANETS}
        self.influence['terra'] = -1
        self.tech = {(s, f): 0 for s in ('1', '2') for f in FACTIONS}
        #: BGA reports the Leader badge as each seat's hand limit (4/5/6),
        #: rather than naming the badge itself.  A transfer is announced as a
        #: pair (recipient at 5, former owner at 4); a direct Leader action can
        #: announce recipient 5 or 6.  Retaining the owner and side lets the walk
        #: distinguish accepting a "give Leadership" reward from declining it,
        #: and keeps the scripted refill on the right hand.
        self.leader = {"owner": None, "level": 0}
        #: card NUMBER -> (seat, planet) for every Agent standing in a column.
        #: Without this, "which card do I exile" changes nothing the mirror can
        #: see, every candidate converges, and the walk picks one arbitrarily --
        #: which diverges several turns later, far from the cause.
        self.columns = {}
        #: Resources. A `choose_branch` like "Transfer 2 cards OR gain 8 Credits"
        #: differs in NOTHING else, so without these both branches converge and the
        #: walk picks one arbitrarily.
        self.credits = {'1': engine.STARTING_CREDITS, '2': engine.STARTING_CREDITS}
        self.zenithium = {'1': engine.STARTING_ZENITHIUM, '2': engine.STARTING_ZENITHIUM}
        #: Card numbers in each hand.  Rich BGA logs announce draws in
        #: `newCards`, but several effects (notably discard-hand) remove cards
        #: without an event.  Keeping identities here makes those otherwise
        #: invisible choices observable when a later card is played.
        self.hands = {'1': set(), '2': set()}
        self.track_hands = False

    def clone(self):
        m = Mirror.__new__(Mirror)
        m.table = self.table
        m.influence = dict(self.influence)
        m.tech = dict(self.tech)
        m.leader = dict(self.leader)
        m.columns = dict(self.columns)
        m.credits = dict(self.credits)
        m.zenithium = dict(self.zenithium)
        m.hands = {pid: set(cards) for pid, cards in self.hands.items()}
        m.track_hands = self.track_hands
        return m

    def num(self, card_id):
        return self.table.card_num.get(str(card_id))

    def consume(self, kind, args):
        if kind == 'newCards':
            raw = args.get('cards', {})
            cards = raw.values() if isinstance(raw, dict) else raw
            for card in cards:
                if not isinstance(card, dict):
                    continue
                num = self.num(card.get('card_id'))
                sid = card.get('card_player_no')
                if num is not None and sid is not None:
                    self.hands.setdefault(str(int(sid)), set()).add(num)
        elif kind == 'movePlanet':
            # The control space is +/-4, not +/-3 (engine.CONTROL_POSITION), and
            # the corpus agrees: positions run -4..+4 and every capture is at +/-4.
            # Orbit stores None the instant a disc reaches it, so a raw position
            # would disagree on exactly the captures. Measured the wrong way round
            # first -- clamping at 3 cut the walk's reach by half.
            position = int(args['position'])
            planet = PLANET_BY_ID[int(args['planet'])]
            self.influence[planet] = (None if abs(position) >= engine.CONTROL_POSITION
                                      else -position)
        elif kind == 'resetPlanet':
            self.influence[PLANET_BY_ID[int(args['planet'])]] = 0
        elif kind == 'gainPlanet':
            self.influence[PLANET_BY_ID[int(args['planet'])]] = None
        elif kind == 'setTech':
            self.tech[(seat(args), FACTION_BY_ID[int(args['race'])])] = int(args['step'])
        elif kind == 'updateLeader':
            sid = seat(args)
            limit = int(args.get('leader', 4))
            if sid is None:
                return
            if limit >= 5:
                self.leader = {"owner": sid, "level": 2 if limit >= 6 else 1}
            elif self.leader.get("owner") == sid:
                # The losing-seat event in a transfer reports 4.  Do not clear
                # a newly assigned badge when BGA emits that event after the
                # recipient's 5/6 event.
                self.leader = {"owner": None, "level": 0}
        elif kind in ('moveCard', 'mobilize', 'transfer'):
            num = self.num(args.get('card_id'))
            if num is not None and seat(args) is not None:
                sid = seat(args)
                # A played card leaves its hand.  A transfer is already in a
                # column, while mobilize goes straight from the deck to one.
                if kind == 'moveCard' and args.get('location') == 'play':
                    self.hands.setdefault(sid, set()).discard(num)
                planet = (PLANET_BY_ID[int(args['planet'])] if args.get('planet')
                          else ALL_CARDS[num]['planet'])
                self.columns[num] = (sid, planet)
        elif kind == 'playCardDiploTech':
            num = self.num(args.get('card_id'))
            sid = seat(args)
            if num is not None and sid is not None:
                self.hands.setdefault(sid, set()).discard(num)
        elif kind == 'discardCard':
            num = self.num(args.get('card_id'))
            if num is not None:
                if args.get('planet_name'):
                    self.columns.pop(num, None)
                else:
                    # Hand discard packets do not consistently carry a seat;
                    # the card identity is enough in a rich log.
                    for cards in self.hands.values():
                        cards.discard(num)
        elif kind == 'deltaCredits':
            # `nb` is the signed change here; `delta` is on deltaSolium instead.
            self.credits[seat(args)] += int(args['nb'])
        elif kind == 'deltaSolium':
            self.zenithium[seat(args)] += int(args['delta'])
        elif kind in ('stealCredits', 'stealSolium'):
            pot = self.credits if kind == 'stealCredits' else self.zenithium
            taker = seat(args)
            other = '2' if taker == '1' else '1'
            pot[taker] += int(args['nb'])
            pot[other] -= int(args['nb'])
        elif kind == 'giveSolium':
            giver = seat(args)
            other = '2' if giver == '1' else '1'
            self.zenithium[giver] -= int(args['nb'])
            self.zenithium[other] += int(args['nb'])
        elif kind == 'giveCredits':
            giver = seat(args)
            other = '2' if giver == '1' else '1'
            self.credits[giver] -= int(args['nb'])
            self.credits[other] += int(args['nb'])

    def facts(self):
        facts = (tuple(sorted(self.influence.items())),
                tuple(sorted(self.tech.items())),
                tuple(sorted(self.columns.items())),
                tuple(sorted(self.credits.items())),
                tuple(sorted(self.zenithium.items())))
        if self.track_hands:
            facts += (tuple((pid, tuple(sorted(cards)))
                            for pid, cards in sorted(self.hands.items())),)
        return facts + ((self.leader.get("owner"),
                         int(self.leader.get("level", 0))),)


def engine_facts(game, include_hands=False):
    influence = dict(game['influence'])
    tech = {(pid, f): game['players'][pid]['technology'][f]
            for pid in game['order'] for f in FACTIONS}
    columns = {num: (pid, planet)
               for pid in game['order']
               for planet, cards in game['players'][pid]['columns'].items()
               for num in cards}
    credits = {pid: game['players'][pid]['credits'] for pid in game['order']}
    zenithium = {pid: game['players'][pid]['zenithium'] for pid in game['order']}
    hands = {pid: tuple(sorted(game['players'][pid]['hand'])) for pid in game['order']}
    facts = (tuple(sorted(influence.items())), tuple(sorted(tech.items())),
             tuple(sorted(columns.items())), tuple(sorted(credits.items())),
             tuple(sorted(zenithium.items())))
    if include_hands:
        facts += (tuple((pid, hands[pid]) for pid in sorted(hands)),)
    return facts + ((game.get('leader', {}).get('owner'),
                     int(game.get('leader', {}).get('level', 0))),)


def converge(mirror, events, start, game, budget=40, floor=0):
    """Consume from `start` until the mirror matches `game`. -> (mirror, index) or None.

    Stops at the FIRST agreement at or past `floor`, never consuming further:
    events beyond belong to decisions the engine has not reached yet.

    `floor` exists because a main action must consume THROUGH its own moveCard
    event even when that move changed nothing the mirror tracks -- otherwise the
    cursor never passes it and the next step re-reads the same action forever.
    """
    live = mirror.clone()
    target = engine_facts(game, include_hands=live.track_hands)
    if start >= floor and live.facts() == target:
        return live, start
    i = start
    steps = 0
    while i < len(events) and steps < budget:
        _mv, kind, args = events[i]
        live.consume(kind, args)
        i += 1
        steps += 1
        if i >= floor and live.facts() == target:
            return live, i
    return None


class ScriptedBonus:
    """The bonus token each award actually paid, taken from the log.

    The eight face-up tokens are NEVER announced at setup, so a seeded game gives
    the wrong bonus and the wrong effect follows -- which is how this was found: an
    engine holding a pending influence choice where BGA had taken a Leader badge.

    `bonus_effects` is the single funnel both award paths go through (the capture
    path inlines the rest, but still calls it), and the log emits exactly one
    `gainBonus` per award, so overriding it here is 1:1. The engine keeps its own
    slot bookkeeping, so OCCUPANCY -- which is what drives future availability --
    stays the engine's; only the token's identity comes from the log.
    """

    def __init__(self, types):
        self.types = list(types)
        self.i = 0
        self.overrun = 0

    def __call__(self, token_type):
        if self.i < len(self.types):
            token_type = self.types[self.i]
            self.i += 1
        else:
            self.overrun += 1
        return _real_bonus_effects(token_type)


_real_bonus_effects = engine.bonus_effects


class Walk:
    def __init__(self, table_id, sides, corpus=T.CORPUS):
        self.table = T.load(table_id, corpus)
        self.game, self.deck = R.build_game(self.table, sides)
        self._force_board_token_occupancy()
        self.events = [(mv, k, a) for mv, _i, k, a in self.table.events()
                       if k in WATCHED and not (k == 'moveCard' and a.get('location') != 'play')]
        self.pos = 0
        self.mirror = Mirror(self.table)
        self.decisions = 0
        self.resolved = collections.Counter()
        # A BGA undo retracts the complete current turn segment.  Keep the
        # pre-main-action state and the two scripted streams so the replacement
        # action starts from exactly the same world and draw position.
        self._action_snapshot = None
        self.bonus = ScriptedBonus([int(a['bonus_num'])
                                    for _mv, _i, k, a in self.table.events()
                                    if k == 'gainBonus'])

    def _force_board_token_occupancy(self):
        """Recover one-time board-token availability from BGA's public events.

        BGA never serializes the face-up token layout.  ``build_game`` therefore
        has to seed arbitrary token values, which is enough for setup but can
        make the engine pay a planet or technology bonus that BGA already spent.
        The first control of a planet and the first level-2 technology are the
        two observable opportunities to consume those slots: a same-move
        ``gainBonus`` means the slot was present, while no payout means it had
        already been taken (usually by ``take_board_bonus``).  Keep the seeded
        value for present slots—the scripted award stream supplies its identity—
        and clear only slots that the log proves are gone.
        """
        raw = list(self.table.events())
        by_move = collections.defaultdict(list)
        for mv, _i, kind, args in raw:
            by_move[mv].append((kind, args))
        # A no-payout first capture proves that its face-up slot was claimed
        # earlier, but it must not be applied retroactively.  In particular a
        # table can claim the slot with card 417 and only capture that planet
        # later.  Keep the stream's chronology: only captures that precede the
        # first board-claim opportunity can be safely cleared at setup; later
        # absences are resolved by the claim candidate itself.
        board_claim_moves = []
        for mv, _i, kind, args in raw:
            if kind not in MAIN:
                continue
            try:
                card_num = int(args.get('card_num'))
            except (TypeError, ValueError):
                continue
            if card_num == 417:
                board_claim_moves.append(mv)
        first_board_claim = min(board_claim_moves, default=None)
        first_planet = {}
        first_tech = {}
        for index, (mv, _i, kind, args) in enumerate(raw):
            if kind == 'movePlanet':
                try:
                    if abs(int(args.get('position', 0))) < engine.CONTROL_POSITION:
                        continue
                    planet = PLANET_BY_ID[int(args['planet'])]
                except (KeyError, TypeError, ValueError):
                    continue
                if planet not in first_planet:
                    first_planet[planet] = (mv, any(k == 'gainBonus' for k, _a in by_move[mv]))
            elif kind == 'setTech' and int(args.get('step', 0)) == 2:
                try:
                    faction = FACTION_BY_ID[int(args['race'])]
                except (KeyError, TypeError, ValueError):
                    continue
                if faction not in first_tech:
                    # BGA starts a level's effect resolution in the packet
                    # after ``setTech``.  In particular, a fixed token can be
                    # announced on the next move id alongside mobilize/draw
                    # packets, so checking only this move falsely clears a
                    # token that is still on the track.  Stop at the next main
                    # action: anything before it belongs to this technology.
                    paid = any(k == 'gainBonus' for k, _a in by_move[mv])
                    if not paid:
                        for _mv2, _i2, kind2, _args2 in raw[index + 1:]:
                            if kind2 in MAIN:
                                break
                            if kind2 == 'gainBonus':
                                paid = True
                                break
                    first_tech[faction] = (mv, paid)

        for planet, (capture_move, paid) in first_planet.items():
            if (not paid and (first_board_claim is None
                              or capture_move < first_board_claim)):
                self.game['planet_bonus'][planet] = None
        for faction, (advance_move, paid) in first_tech.items():
            if (not paid and (first_board_claim is None
                              or advance_move < first_board_claim)):
                self.game['technology_bonus'][faction] = None

    def _trial_mirror(self, trial, task=None):
        """Apply state removals that BGA omitted before consuming public events.

        The archived stream does not announce every discard from a hand (the
        discard-hand effect is the important example), and an exile can remove
        an Agent without a `discardCard` packet.  Additions remain event-driven:
        `newCards`, `moveCard`, and `mobilize` still have to appear in the log.
        This keeps the reconciliation narrow while making a later use of a
        silently removed card reject the wrong candidate.
        """

        mirror = self.mirror.clone()
        for pid in self.game['order']:
            before = set(self.game['players'][pid]['hand'])
            after = set(trial['players'][pid]['hand'])
            for num in before - after:
                mirror.hands.setdefault(pid, set()).discard(num)
        return mirror

    # -- the log's own answer, where it is unambiguous -------------------------
    def direct(self, task, moves):
        """Evidence that names the answer outright. None = fall through to trial."""
        kind = task['type']
        shape = {k for m in moves for k in m if k != 'action'}
        if kind == 'develop' and shape == {'faction'}:
            ev = self.next_of(('setTech',))
            if ev:
                f = FACTION_BY_ID[int(ev[2]['race'])]
                return next((m for m in moves if m.get('faction') == f), None)
        return None

    def next_of(self, kinds, limit=30):
        for j in range(self.pos, min(len(self.events), self.pos + limit)):
            if self.events[j][1] in kinds:
                return self.events[j]
        return None

    def _bga_exile_is_emitted(self, planet, limit=80):
        """Whether the current tier-exile branch has public discard packets.

        BGA can leave the prompt in the stream after a just-captured planet,
        but only the branches that actually remove Agents emit ``discardCard``
        packets.  Looking ahead to the next main action is safe here: all
        packets before it belong to the current pending turn segment.
        """
        end = min(len(self.events), self.pos + limit)
        for _mv, kind, args in self.events[self.pos:end]:
            if kind in MAIN:
                break
            if kind == 'discardCard' and args.get('planet_name'):
                if str(args.get('planet_name')).lower() == str(planet).lower():
                    return True
        return False

    def _planet_lookahead(self, trial, task, start=None, limit=40):
        """Score a trial against the planet movements that follow its choice.

        A two-adjacent choice only queues explicit influence tasks.  Until the
        first task is answered, every pair has the same public state, so the
        ordinary mirror convergence cannot distinguish them.  BGA does expose
        the answer as the next ``movePlanet`` packet.  Capture bonus 3 also
        exposes an influence movement of its own; skip that one so it does not
        get mistaken for the second adjacent planet.
        """
        if not task or task.get('type') not in ('two_adjacent', 'adjacent_three'):
            return 0
        queue = (trial.get('pending') or {}).get('queue') or []
        expected = [t.get('planet') for t in queue
                    if t.get('type') in ('influence', 'influence_other')
                    and t.get('planet')]
        if not expected:
            return 0
        score = 0
        wanted = 0
        skip_bonus_influence = False
        cursor = self.pos if start is None else start
        for _mv, kind, args in self.events[cursor:cursor + limit]:
            if kind == 'gainBonus':
                # Token 3 is the influence bonus.  Other bonus effects do not
                # emit a planet movement, so carrying a generic skip flag would
                # hide a real adjacent movement later in the stream.
                try:
                    skip_bonus_influence = int(args.get('bonus_num')) == 3
                except (TypeError, ValueError):
                    skip_bonus_influence = False
                continue
            if kind != 'movePlanet':
                continue
            if skip_bonus_influence:
                skip_bonus_influence = False
                continue
            if wanted >= len(expected):
                break
            actual = PLANET_BY_ID[int(args['planet'])]
            score += actual == expected[wanted]
            wanted += 1
        return score

    def _board_lookahead(self, trial, task, limit=None):
        """Score a board-bonus slot against later fixed/capture payouts.

        BGA's ``Choose a Bonus`` menu reports token *types*, not the planet or
        technology slot the player removed.  The slot is therefore invisible
        at the choice itself, but its occupancy is observable when a later
        level-2 technology or planet capture tries to pay it.  Use those
        already-recorded payouts to resolve the otherwise arbitrary slot
        choice.  This is deliberately a tie-break: the normal mirror remains
        the parity gate for all material state.
        """
        if not task or task.get('type') != 'take_board_bonus':
            return 0
        events = self.events
        # A board slot can be claimed many turns before its first observable
        # capture.  A fixed window silently misses that evidence on long
        # tables, making the ranker fall back to the first legal slot.  The
        # table is already a bounded replay, so scan to its end by default;
        # callers may still pass a smaller limit for a focused probe.
        end = len(events) if limit is None else min(len(events), self.pos + limit)
        score = 0

        # A level-2 technology pays its fixed token before the level-1
        # technology effects.  A level-1 Human side can itself draw a token,
        # so subtract that known draw when deciding whether a fixed payout was
        # present.  (The other level-1 effects never draw a token.)
        for faction in FACTIONS:
            tech_event = None
            for j in range(self.pos, end):
                _mv, kind, args = events[j]
                if (kind == 'setTech'
                        and FACTION_BY_ID.get(int(args.get('race', 0))) == faction
                        and int(args.get('step', 0)) == 2):
                    tech_event = j
                    break
            if tech_event is None:
                continue
            observed = 0
            for j in range(tech_event + 1, end):
                _mv, kind, args = events[j]
                if kind == 'setHandSize':
                    break
                if kind in ('playCardDiploTech', 'moveCard'):
                    break
                if kind == 'gainBonus':
                    observed += 1
            side = trial.get('board_sides', {}).get(faction, 1)
            known_draws = sum(t.get('type') == 'draw_bonus'
                              for t in engine.technology_effects(faction, side, 1))
            fixed_paid = observed > known_draws
            slot_present = trial.get('technology_bonus', {}).get(faction) is not None
            score += int(fixed_paid == slot_present)

        # A planet capture's payout is tied to the move id that reaches the
        # control space.  Looking backwards from ``gainPlanet`` is too broad:
        # BGA can settle two captures in one turn, and the previous capture's
        # gainBonus would otherwise be attributed to the next planet.  Compare
        # the first future control-space movement with the candidate's
        # remaining face-up token instead.
        for planet in PLANETS:
            capture = None
            for j in range(self.pos, end):
                _mv, kind, args = events[j]
                try:
                    is_capture = (kind == 'movePlanet'
                                  and abs(int(args.get('position', 0)))
                                      >= engine.CONTROL_POSITION
                                  and PLANET_BY_ID.get(int(args.get('planet', 0))) == planet)
                except (TypeError, ValueError):
                    is_capture = False
                if is_capture:
                    capture = j
                    break
            if capture is None:
                continue
            move_id = events[capture][0]
            paid = any(mv == move_id and kind == 'gainBonus'
                       for mv, kind, _args in events[capture:])
            slot_present = trial.get('planet_bonus', {}).get(planet) is not None
            score += int(paid == slot_present)
        return score

    def choose(self, moves, floor=0, task=None):
        """The legal move whose RESULT the mirror can reach.

        A trial DRAWS: the scripted deck is engine-global, so every rejected
        candidate that refills a hand eats entries the real line still needs. The
        script is therefore saved and restored around each trial, and the winner is
        applied once more for real. Without this the deck silently drifts and the
        failure surfaces as "the log played a card that is not in hand" many moves
        later.
        """
        hits = []
        for move in moves:
            saved, saved_bonus = list(self.deck.script), self.bonus.i
            trial = copy.deepcopy(self.game)
            pid = R.whose_move(trial)
            ok, _err = engine.apply_move(trial, pid, move)
            trial_mirror = self._trial_mirror(trial, task=task) if ok else None
            got = (converge(trial_mirror, self.events, self.pos, trial, floor=floor)
                   if ok else None)
            self.deck.script, self.bonus.i = saved, saved_bonus
            if got:
                # `converge` has already consumed the candidate's own movement
                # packets.  Starting the lookahead at that returned cursor is
                # essential when the candidate captures: the capture packet is
                # followed by its bonus, and the first remaining movement is
                # the next queued effect.  Re-scanning from `self.pos` counts
                # the candidate's capture as the next task and loses the
                # orientation of an adjacent pair exactly when a bonus is
                # inserted between its two movements.
                lookahead = (self._planet_lookahead(trial, task, start=got[1])
                             + self._board_lookahead(trial, task))
                hits.append((move, got, lookahead))
        return hits

    def commit(self, move):
        """Apply for real, letting the scripted deck advance."""
        pid = R.whose_move(self.game)
        ok, err = engine.apply_move(self.game, pid, move)
        if not ok:
            raise AssertionError(f"engine rejected a move it offered: {err}")

    def _rewind_undo(self):
        """Restore the action that the next ``undo`` batch retracts.

        Undo packets contain low-level reverse operations, but replaying those
        records would duplicate engine rules (and still would not rewind the
        scripted deck).  The engine snapshot is the single authoritative
        rollback; the cursor advances past the reverse packets and the next
        BGA action is then reconciled from the restored mirror.
        """
        if not self._action_snapshot:
            # If the retracted action was never applied by the mirror (the
            # undo can be encountered before its main event), there is
            # nothing to restore.  Consume the reverse packets and continue
            # from the replacement branch instead of treating the stream
            # boundary as a parity failure.
            j = self.pos
            while j < len(self.events) and self.events[j][1] == 'undo':
                j += 1
            self.pos = j
            self.resolved['undo_skip'] += 1
            return True
        snap = self._action_snapshot
        undo_index = self.pos
        # ``bonus.types`` is initially the whole BGA gainBonus stream.  An
        # action that was undone can have emitted one or more bonus packets;
        # those packets are still present in the archive but must not remain
        # in the scripted final line after restoring the action snapshot.
        self.bonus.types = list(snap.get('bonus_types', self.bonus.types))
        dropped = [int(a.get('bonus_num')) for _mv, kind, a
                   in self.events[snap.get('event_pos', undo_index):undo_index]
                   if kind == 'gainBonus' and a.get('bonus_num') is not None]
        base = int(snap['bonus_i'])
        for token in dropped:
            if base < len(self.bonus.types) and self.bonus.types[base] == token:
                del self.bonus.types[base]
            else:
                try:
                    del self.bonus.types[self.bonus.types.index(token, base)]
                except ValueError:
                    pass
        self.game = copy.deepcopy(snap['game'])
        self.deck.script = list(snap['deck'])
        self.bonus.i = base
        self.mirror = snap['mirror'].clone()
        j = undo_index
        while j < len(self.events) and self.events[j][1] == 'undo':
            j += 1
        self.pos = j
        self._action_snapshot = None
        self.resolved['undo'] += 1
        return True

    def _undo_before_next_main(self):
        """Handle an undo waiting in the stream before choosing another move."""
        undo = None
        main = None
        for j in range(self.pos, len(self.events)):
            kind = self.events[j][1]
            if kind == 'undo':
                undo = j
                break
            if kind in MAIN:
                main = j
                break
        if undo is None or (main is not None and main < undo):
            return False
        self.pos = undo
        return self._rewind_undo()

    def _retracted_main(self, index):
        """Return the undo index when the main event at ``index`` was undone.

        BGA writes the reverse records in a later move id than the action they
        retract.  From the replay stream's perspective the first undo before
        the next main action therefore belongs to the main event at ``index``.
        """
        for j in range(index + 1, len(self.events)):
            kind = self.events[j][1]
            if kind == 'undo':
                return j
            if kind in MAIN:
                return None
        return None

    def step(self):
        game = self.game
        # A retract is a stream boundary.  It must be processed before the
        # engine sees the next pending task or main action; otherwise the
        # replacement move would be applied on top of the abandoned state.
        if self._undo_before_next_main():
            return None
        pid = R.whose_move(game)
        moves = engine.legal_moves(game, pid)
        if not moves:
            return 'stalled'
        task = game['pending']['queue'][0] if game.get('pending') else None
        if task and task.get('type') == 'exile_tier':
            # This is an internal replay hint derived from the archived stream;
            # player_view strips underscore keys, and ordinary server games do
            # not set it.
            task['_bga_exile'] = self._bga_exile_is_emitted(task['planet'])

        if task is None:
            ev = self.next_of(MAIN)
            if ev is None:
                return 'log-exhausted'
            _mv, kind, a = ev
            num = int(a.get('card_num') or self.table.card_num[str(a['card_id'])])
            action = ('recruit' if kind == 'moveCard'
                      else 'leader' if a.get('dest_type') == 'diplo' else 'technology')
            intent = {'action': action, 'card_id': num}
            # Do not execute a move that BGA immediately retracts.  The
            # reverse packets may arrive before the replacement action, and
            # the abandoned branch can already be absent from ``moves`` after
            # an earlier parity difference.  Detect the stream boundary
            # before requiring the engine to offer the stale move.
            ev_index = self.events.index(ev, self.pos)
            undo_index = self._retracted_main(ev_index)
            if undo_index is not None:
                base = self.bonus.i
                dropped = [int(args.get('bonus_num')) for _mv, kind, args
                           in self.events[self.pos:undo_index]
                           if kind == 'gainBonus' and args.get('bonus_num') is not None]
                for token in dropped:
                    if base < len(self.bonus.types) and self.bonus.types[base] == token:
                        del self.bonus.types[base]
                    else:
                        try:
                            del self.bonus.types[self.bonus.types.index(token, base)]
                        except ValueError:
                            pass
                self.pos = undo_index + 1
                self._action_snapshot = None
                self.resolved['undo_skip'] += 1
                return None
            candidates = [m for m in moves if m == intent]
            if not candidates:
                self.fail = f"main action {intent} not offered; have {moves[:4]}"
                return 'no-match'
            # The cursor is NOT moved here. Events between it and this action --
            # the opponent's whole previous turn -- still have to reach the mirror.
            floor = self.events.index(ev, self.pos) + 1
            self._action_snapshot = {
                'game': copy.deepcopy(self.game),
                'deck': list(self.deck.script),
                'bonus_i': self.bonus.i,
                'bonus_types': list(self.bonus.types),
                'mirror': self.mirror.clone(),
                'turn_pid': self.game.get('turn_pid'),
                'event_pos': self.pos,
            }
            self.resolved['main'] += 1
        else:
            floor = 0
            direct = self.direct(task, moves)
            candidates = [direct] if direct else moves
            self.resolved['direct' if direct else 'trial'] += 1

        hits = self.choose(candidates, floor=floor, task=task)
        if not hits:
            self.fail = (f"no candidate reproduces BGA's state; task={task and task['type']} "
                         f"moves={[{k: v for k, v in m.items() if k != 'action'} for m in moves][:6]}")
            return 'no-converge'
        # PREFER THE CANDIDATE THAT EXPLAINS MORE OF THE LOG. Convergence stops at
        # the first agreement, so declining an optional matches with ZERO events
        # consumed and would always beat accepting it, which has to consume the
        # events its effect produced. Ranking by events consumed makes "the answer
        # that accounts for what BGA actually reported" win.
        hits.sort(key=lambda h: (h[1][1], h[2]), reverse=True)
        if len(hits) > 1 and hits[0][1][1] == hits[1][1][1] and hits[0][2] == hits[1][2]:
            self.resolved['ambiguous'] += 1
        move, (mirror, pos), _lookahead = hits[0]
        self.commit(move)
        self.mirror, self.pos = mirror, pos
        self.decisions += 1
        if (self._action_snapshot
                and self.game.get('pending') is None
                and self.game.get('turn_pid') != self._action_snapshot.get('turn_pid')):
            self._action_snapshot = None
        return None


def run(table_id, sides, cap=3000, corpus=T.CORPUS):
    w = Walk(table_id, sides, corpus)
    w.fail = None
    # mulligan
    owner = {}
    for _mv, _i, k, a in w.table.events():
        if k != 'newCards':
            continue
        raw = a.get('cards', {})
        for c in (raw.values() if isinstance(raw, dict) else raw):
            owner.setdefault(str(c['card_id']), str(c['card_player_no']))
    first_main = next((n for n, e in enumerate(w.events) if e[1] in MAIN), len(w.events))
    tossed = collections.defaultdict(list)
    keep = []
    for n, (mv, kind, a) in enumerate(w.events):
        if n < first_main and kind == 'newCards':
            continue
        if n < first_main and kind == 'discardCard' and a.get('card_id') is not None:
            s = owner.get(str(a['card_id']))
            if s:
                tossed[s].append(w.table.card_num[str(a['card_id'])])
                continue
        keep.append((mv, kind, a))
    w.events = keep
    engine.bonus_effects = w.bonus
    try:
      with R.scripted(w.deck):
        for pid in w.game['order']:
            intent = {'action': 'mulligan', 'card_ids': sorted(tossed.get(pid, []))}
            ok, err = engine.apply_move(w.game, pid, intent)
            if not ok:
                return dict(status=f'mulligan:{err}', walk=w)
            w.decisions += 1
        # `newCards` in the opening deal are already represented by build_game
        # and by the forced mulligan above.  Start the hand mirror after setup,
        # then consume only draws announced during play.
        w.mirror.hands = {
            pid: set(w.game['players'][pid]['hand']) for pid in w.game['order']
        }
        w.mirror.track_hands = True
        for _ in range(cap):
            if engine.is_over(w.game):
                return dict(status='done', walk=w, winner=engine.winner(w.game))
            bad = w.step()
            if bad:
                return dict(status=bad, walk=w)
    finally:
        engine.bonus_effects = _real_bonus_effects
    return dict(status='cap', walk=w)


def best_run(table_id: str, corpus: str = T.CORPUS) -> dict:
    """The configuration that gets furthest. See ALL_SIDES for why this is a search."""

    best = None
    for sides in ALL_SIDES:
        try:
            result = run(table_id, sides, corpus=corpus)
        except Exception as exc:                       # a harness bug, not a verdict
            result = dict(status=f"error:{type(exc).__name__}: {str(exc)[:90]}",
                          walk=None)
        result["sides"] = sides
        reach = result["walk"].decisions if result.get("walk") else -1
        if best is None or reach > (best["walk"].decisions if best.get("walk") else -1):
            best = result
    return best


def undo_free(corpus: str = T.CORPUS) -> list[str]:
    """Rich tables with no `undo`, DERIVED from the corpus rather than listed.

    A hardcoded roster only ever guards the corpus shrinking, and the cron adds
    to it -- a new table would join unwalked and silently.
    """

    return [table_id for table_id in R.rich_tables(corpus)
            if not T.load(table_id, corpus).undos]


def report(corpus: str = T.CORPUS) -> int:
    """Walk every rich table and require a complete event-and-winner match."""

    tables = R.rich_tables(corpus)
    done = 0
    for table_id in tables:
        result = best_run(table_id, corpus)
        walk = result.get("walk")
        sides = "".join(str(result["sides"][f]) for f in ("robot", "human", "animod"))
        reach = walk.decisions if walk else 0
        table = T.load(table_id, corpus)
        complete = (result["status"] == "done"
                    and walk is not None
                    and walk.pos == len(walk.events))
        if complete:
            agree = str(engine.winner(walk.game)) == str(table.winner_seat)
            done += bool(agree)
            print(f"{table_id} sides={sides} DONE {reach:>4} decisions, winner "
                  f"{'agrees' if agree else 'DISAGREES'}")
        else:
            print(f"{table_id} sides={sides} {result['status']:<14} {reach:>4} decisions")
            if walk is not None and getattr(walk, "fail", None):
                print(f"    {walk.fail[:200]}")
    print()
    print(f"{done} of {len(tables)} rich tables replay end to end with the "
          "logged winner and consume the complete watched event stream.")
    return 0 if done == len(tables) else 1


def logged_decisions(table) -> int:
    """How many decisions the log records for a table."""

    total = 0
    for _move_id, _index, kind, args in table.events():
        if kind == "playCardDiploTech" or (kind == "moveCard"
                                           and args.get("location") == "play"):
            total += 1
        elif kind == "gameStateChange":
            _pid, payload = T.private(args)
            if payload and payload.get("type") in R.DECISION_PROMPTS:
                total += 1
    return total
