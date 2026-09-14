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

STATUS
------
Not finished. Run `bga_replay --cowalk` for the current reach; at the time of
writing 2 of the 13 undo-free tables replay END TO END, reproducing the logged
winner, and the 13 together reach 541 of their 1,055 decisions. The rest stop at
a decision no candidate reproduces, which is the honest failure: it means our
rules and BGA's disagree about that position, or the harness still cannot see
what distinguishes two answers. Suspect the harness first -- every failure so far
has been the harness.
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
WATCHED = ("playCardDiploTech", "moveCard", "movePlanet", "setTech", "transfer",
           "discardCard", "gainBonus", "mobilize", "gainPlanet", "resetPlanet",
           "updateLeader", "deltaCredits", "deltaSolium", "setHandSize",
           "stealCredits", "stealSolium", "giveSolium")

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

    def clone(self):
        m = Mirror.__new__(Mirror)
        m.table = self.table
        m.influence = dict(self.influence)
        m.tech = dict(self.tech)
        m.columns = dict(self.columns)
        m.credits = dict(self.credits)
        m.zenithium = dict(self.zenithium)
        return m

    def num(self, card_id):
        return self.table.card_num.get(str(card_id))

    def consume(self, kind, args):
        if kind == 'movePlanet':
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
        elif kind in ('moveCard', 'mobilize', 'transfer'):
            num = self.num(args.get('card_id'))
            if num is not None and seat(args) is not None:
                planet = (PLANET_BY_ID[int(args['planet'])] if args.get('planet')
                          else ALL_CARDS[num]['planet'])
                self.columns[num] = (seat(args), planet)
        elif kind == 'discardCard':
            num = self.num(args.get('card_id'))
            if num is not None and args.get('planet_name'):
                self.columns.pop(num, None)
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

    def facts(self):
        return (tuple(sorted(self.influence.items())),
                tuple(sorted(self.tech.items())),
                tuple(sorted(self.columns.items())),
                tuple(sorted(self.credits.items())),
                tuple(sorted(self.zenithium.items())))


def engine_facts(game):
    influence = dict(game['influence'])
    tech = {(pid, f): game['players'][pid]['technology'][f]
            for pid in game['order'] for f in FACTIONS}
    columns = {num: (pid, planet)
               for pid in game['order']
               for planet, cards in game['players'][pid]['columns'].items()
               for num in cards}
    credits = {pid: game['players'][pid]['credits'] for pid in game['order']}
    zenithium = {pid: game['players'][pid]['zenithium'] for pid in game['order']}
    return (tuple(sorted(influence.items())), tuple(sorted(tech.items())),
            tuple(sorted(columns.items())), tuple(sorted(credits.items())),
            tuple(sorted(zenithium.items())))


def converge(mirror, events, start, game, budget=40, floor=0):
    """Consume from `start` until the mirror matches `game`. -> (mirror, index) or None.

    Stops at the FIRST agreement at or past `floor`, never consuming further:
    events beyond belong to decisions the engine has not reached yet.

    `floor` exists because a main action must consume THROUGH its own moveCard
    event even when that move changed nothing the mirror tracks -- otherwise the
    cursor never passes it and the next step re-reads the same action forever.
    """
    live = mirror.clone()
    target = engine_facts(game)
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
        self.events = [(mv, k, a) for mv, _i, k, a in self.table.events()
                       if k in WATCHED and not (k == 'moveCard' and a.get('location') != 'play')]
        self.pos = 0
        self.mirror = Mirror(self.table)
        self.decisions = 0
        self.resolved = collections.Counter()
        self.bonus = ScriptedBonus([int(a['bonus_num'])
                                    for _mv, _i, k, a in self.table.events()
                                    if k == 'gainBonus'])

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

    def choose(self, moves, floor=0):
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
            got = converge(self.mirror, self.events, self.pos, trial, floor=floor) if ok else None
            self.deck.script, self.bonus.i = saved, saved_bonus
            if got:
                hits.append((move, got))
        return hits

    def commit(self, move):
        """Apply for real, letting the scripted deck advance."""
        pid = R.whose_move(self.game)
        ok, err = engine.apply_move(self.game, pid, move)
        if not ok:
            raise AssertionError(f"engine rejected a move it offered: {err}")

    def step(self):
        game = self.game
        pid = R.whose_move(game)
        moves = engine.legal_moves(game, pid)
        if not moves:
            return 'stalled'
        task = game['pending']['queue'][0] if game.get('pending') else None

        if task is None:
            ev = self.next_of(MAIN)
            if ev is None:
                return 'log-exhausted'
            _mv, kind, a = ev
            num = int(a.get('card_num') or self.table.card_num[str(a['card_id'])])
            action = ('recruit' if kind == 'moveCard'
                      else 'leader' if a.get('dest_type') == 'diplo' else 'technology')
            intent = {'action': action, 'card_id': num}
            candidates = [m for m in moves if m == intent]
            if not candidates:
                self.fail = f"main action {intent} not offered; have {moves[:4]}"
                return 'no-match'
            # The cursor is NOT moved here. Events between it and this action --
            # the opponent's whole previous turn -- still have to reach the mirror.
            floor = self.events.index(ev, self.pos) + 1
            self.resolved['main'] += 1
        else:
            floor = 0
            direct = self.direct(task, moves)
            candidates = [direct] if direct else moves
            self.resolved['direct' if direct else 'trial'] += 1

        hits = self.choose(candidates, floor=floor)
        if not hits:
            self.fail = (f"no candidate reproduces BGA's state; task={task and task['type']} "
                         f"moves={[{k: v for k, v in m.items() if k != 'action'} for m in moves][:6]}")
            return 'no-converge'
        # PREFER THE CANDIDATE THAT EXPLAINS MORE OF THE LOG. Convergence stops at
        # the first agreement, so declining an optional matches with ZERO events
        # consumed and would always beat accepting it, which has to consume the
        # events its effect produced. Ranking by events consumed makes "the answer
        # that accounts for what BGA actually reported" win.
        hits.sort(key=lambda h: h[1][1], reverse=True)
        if len(hits) > 1 and hits[0][1][1] == hits[1][1][1]:
            self.resolved['ambiguous'] += 1
        move, (mirror, pos) = hits[0]
        self.commit(move)
        self.mirror, self.pos = mirror, pos
        self.decisions += 1
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
    """Walk every undo-free table and print how far each gets."""

    tables = undo_free(corpus)
    done = reached = logged = 0
    for table_id in tables:
        result = best_run(table_id, corpus)
        walk = result.get("walk")
        sides = "".join(str(result["sides"][f]) for f in ("robot", "human", "animod"))
        reach = walk.decisions if walk else 0
        reached += reach
        table = T.load(table_id, corpus)
        logged += logged_decisions(table)
        if result["status"] == "done":
            agree = str(engine.winner(walk.game)) == str(table.winner_seat)
            done += bool(agree)
            print(f"{table_id} sides={sides} DONE {reach:>4} decisions, winner "
                  f"{'agrees' if agree else 'DISAGREES'}")
        else:
            print(f"{table_id} sides={sides} {result['status']:<14} {reach:>4} decisions")
            if walk is not None and getattr(walk, "fail", None):
                print(f"    {walk.fail[:200]}")
    print()
    print(f"{done} of {len(tables)} undo-free tables replay end to end with the "
          f"logged winner; {reached} of {logged} decisions reached.")
    return 0


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
