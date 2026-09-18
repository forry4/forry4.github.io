# Rag Tag — Claude Context

A faithful implementation of **Tag Team** (Le Scorpion Masqué, 2025): two players,
teams of two Fighters from a roster of twelve, decks that are never shuffled.
Mounted at `/ragtag`, table `ragtag_games`, CSS namespace `.ragtag`.

Read this before touching `engine.py`, and read `data/README.md` before touching
anything under `data/`.

---

## The game, in one paragraph

Draft two Fighters each. Their two Starting Cards, in an order you choose, are your
whole Fight Deck; their other 18 cards shuffle into your Build Deck. Each **round**
is a **FIGHT!** step — both players flip the top card of their Fight Deck at the
same time and resolve both at once, until the decks run out — followed by a
**BUILD!** step: draw three, secretly keep one, slide it anywhere into your Fight
Deck *without reordering what is already there*. The played cards keep their order
and become next round's deck, one card longer. Nothing is ever shuffled again, so
both players eventually know the whole sequence; the game is about where you put
things.

---

## Where the data came from

`PLAN.md` assumed the per-fighter data could only be got out of a logged-in
BoardGameArena table via a devtools dump. **It is all public.** BGA's client CSS is
an asset manifest and the assets it names are on the CDN without a login: 12
fighter boards, 2 backs, 78 card faces. The rulebook PDF fetches fine, and BGA's
Gamehelp wiki page carries a per-fighter section for all twelve plus the FAQ that
settles most of the awkward interactions. The client bundle itself carries **no**
card tables — it is UI only — but its i18n strings name every special track and
list Milady's Intrigue effects verbatim.

`data/*.json` is a **mechanical transcription** of that art — numbers, op lists,
track layouts. The art is not committed: rules are not copyrightable, card text and
illustration are, and a mechanical table is the better engineering anyway.
`tools/fetch_bga_assets.py` re-downloads the sources so a correction can be checked
against the same pixels.

**`fighters.py` is GENERATED and COMMITTED.** `tools/import_bga.py` is the source of
truth for the transform, so a corrected dump is a re-run, never a re-transcription.
`--check` regenerates in memory and the suite fails on a stale file.

### The published rules are a SOURCE, and they settle vocabulary
`TT_Rules_01/02_EN` (Fight Rules + Fighters' Guide) and `TT_FIGHTERS_PROFILES_1_EN`
are the publisher's own PDFs. They are **not** in the repo — this package holds
mechanics, not publisher copy — but they are what the wording is checked against,
and three of our names were simply wrong until 2026-08-27:

* Ching Shih's is the **Fleet track**, counted in **Ships**. We printed the
  internal id (`+1 navigation`) on card faces.
* Milady's tokens are **Schemes**. A `_comment` in `cards.json` calls them
  "Intrigue (Scheme)" — BGA's word — and a previous pass renamed the whole UI to
  Intrigue on the strength of it. The rulebook says Scheme throughout.
* The Fey Folk's is the **Spirit track**, singular.

The rulebook also **independently confirmed two corpus findings**, which is the
strongest evidence either way: its Scheme token table lists exactly 9 distinct
effects with Poison drawn three times over 11 tokens (what the corpus deduced
from duplicate token ids), and Bödvar's Bear entry matches our note on his
opening HP word for word in substance.

**Where the rulebook and the corpus disagree, the corpus wins on TIMING and the
rulebook wins on NAMES.** Two live examples: Maman Brijit's revive is printed as
"at the end of the Turn" and BGA resolves it inline (902742623 f5t2 shows the
next Intrigue landing on the revived HP) — we do what BGA does, because that is
the opponent players actually face. Joan's dial went the other way: the rulebook
says the marker pays HER on the **top right** space and her **Partner** on the
**bottom left**, and our space NAMES were rotated a step off that. The icons sit
on ring indices 2 and 4, which the corpus measured directly, so relabelling
index 1 as `top_left` satisfies both at once — the ring becomes TL → TR → BR →
BL (still clockwise) and the icons land on the spaces the rulebook names.
**Behaviour-neutral, and proved so: the full parity gate still reads 4103/4103
per-turn tracks.** Do not "fix" one of these by breaking the other.

### The one gap — CLOSED by the corpus
Milady's 11 Intrigue tokens carry only **9 distinct** abilities, and which are duplicated
is not visible in any public source: the pile is face down. This file recorded that as a
known gap rather than guessing, and said "a gamedatas dump or a replay settles it". **The
replay settled it.** BGA names each revealed token `token-milady-scheme-N`, and within one
game the token `id` is a distinct physical piece, so two ids on one face proves a duplicate.
Face 6 — POISON — is the only one that repeats, and it repeats twice (886355216 reveals it
on ids 7, 8 and 9). 3 + 8 = 11. Recording a gap honestly is what made it answerable the
moment real data arrived.

### Replay parity — FULL, and it is the strongest gate this package has
`tools/bga_{inspect,oracle,replay,fight,filter}.py` replay real BGA top-player logs
through this engine. The corpus lives OUTSIDE the repo (`TAGTEAM_CORPUS`, default
`C:/Users/Forrest/TagTeam_corpus`); nothing here downloads — the scraper is on the
`cob-mining` branch and drips ~10 games/day past BGA's replay cap.

    python -m games.rag_tag.tools.bga_filter [-v]        # all three gates, one pass
    python -m games.rag_tag.tools.bga_fight <table_id>   # one game, turn by turn

**All 40 logs reproduce exactly, on every gate** (2026-08-27; winner parity was 13/30
two sessions earlier):

    replays to the recorded winner:                     40/40
    build parse vs BGA's own public record:           198/198 (100%)
    cards revealed, vs BGA's fightLog:               1926/1926 (100%), 40/40 sequences
    every fighter's TRACKS, per turn, vs fightLog:   4103/4103 (100%), 40/40 games
                                                     40/40 matching BGA's turn count

**Read them in that order, because they are increasing resolution and they SPLIT the
failure modes.** The winner is one bit at the end of a game and tells you only that
something diverged. The reveals gate says whether the replay played the right cards in the
right order — reveals right + winner wrong is an ENGINE bug, reveals wrong means the DRIVER
lost the deck order, and those two want completely different work. The per-turn track gate
then names the exact turn.

**`trackPositionUpdated` is what made the last ten bugs findable.** It carries the health
marker's absolute board slot, stamped with its fight and turn, so "the winner is wrong"
becomes "this turn is wrong" and everything after the first bad turn is downstream noise.
`bga_fight.py` is that instrument, and it **reports its score on the games that ALREADY
reproduce separately, every run** — because an earlier per-turn damage comparison blamed
every card at 0.6–0.9, which cannot be true alongside 27 games reproducing exactly. It was
the instrument that was wrong. Calibrate before you believe a blame count.

**Ten real rules bugs came out of it that 100+ passing tests could not see**, because they
all look exactly like the rules as written and only a real game disagrees. Four of them are
one mistake wearing four hats — **WHO is acting**:
* `resolve_target` read "self" off the seat's ACTIVE fighter. Right for a card; wrong for a
  HEALTH-TRACK ICON, which belongs to whoever's marker crossed it. The Golem's own +1 Power
  icons went to his partner all game, so his Attacks went out two Power light.
* `Turn.actor` had the same bug for the Power an Attack is thrown with, so an Intrigue's
  Attack used its owner's PARTNER's Power.
* A DEFERRED op was re-run against the active fighter, so the Intrigue Milady's own track
  fires resolved as her partner — who has no planted Schemes — and did nothing at all.
* An ATTACK DECLARED AFTER THE DECLARE STEP never landed: declare banks HP once at its end,
  and an icon or a deferred THEN speaks after that.

The other six:
* **The Wild Bunch's `setup_icons` never fired.** Generated by `import_bga`, validated by
  `test_fighters`, executed by nobody — its partner started EVERY game one Power short. The
  bug's whole shape was silence, so `_apply_setup_icons` now RAISES on an op it cannot
  resolve. **Data being present and validated is not data being used.**
* **Joan's dial is a ring of FOUR**, not five: the central Halo is a start, never returned
  to. Measured, not read off the art — 21 first moves all land on 1, transitions are 1→2,
  2→3, 3→4, 4→1, and not one 4→0.
* **The Golem's presence is a one-shot SHIELD**, not a permanent flag: the next Attack on
  its holder is negated and the token goes home, which is what lets Protect the Innocent be
  invested again. A DEFLECTED Attack is still an Attack when it arrives, so the shield eats
  those too.
* **Milady's Intrigues are a pile of eleven drawn WITHOUT replacement.** The corpus also
  settles what `cards.json` had flagged as unknowable without a dump: poison is the only
  duplicated face, and it has three copies.
* **Blocks, their bonuses and the conditional branches settle by ITERATION.** No fixed order
  is right — one turn needs a Block's riposte visible to "if you are Attacked", another
  needs a conditional's Attack to be what makes the Block work.
* **Reanimation's second pass** reads the board the first left behind but takes Power from
  the turn's opening snapshot, and the opposing Block still catches it. **Maman Brijit
  revives inline**, as soon as the movement that revived her settles — not at end of turn,
  which let later damage land on the revive space where the floor swallows it.

**THE OLD POWER ORACLE RUNS AT LAG +1, measured not argued.** BGA emits
`updateCardAndFighterData` BEFORE resolving the step it announces; ours[i] vs BGA[i+k] over
the corpus: k=−1 0.358, **k=+1 0.716**, k=0 0.537, k=+2 0.454. It is now the weakest of the
gates — prefer `bga_fight`, which needs no alignment at all — but the lesson stands: **fix
the bugs you understand BEFORE calibrating.** This file previously recorded that a one-step
lag "changed nothing", honestly measured while two Power bugs were drowning the signal. A
miscalibrated oracle and a buggy engine are indistinguishable from inside.

**Alignment-free checks need no replay and no calibration** — do these first on any new
data. BGA's `startingPower` matches `base_power` for all 12 fighters, and every health
track matches slot-for-slot. **BGA's `locationArg` is a board SLOT, not our track index**:
it numbers the space printed "1" as slot 1, so alive slots read as printed HP and the
spaces below run 0, −1, −2. Nine fighters have one space under "1" and the distinction
never shows; Maman Brijit has three, so a naive index comparison scored her wrong on turn 1
of every game she appeared in — a systematic 2 in games that otherwise reproduce perfectly,
which is the signature of an ENCODING mismatch, not a rules bug.

**Six harness bugs, every one of which looked like an engine bug.** Worth knowing because
the next one will too:
* **Positions were reversed.** `addedCard.locationArg` counts from the opposite end of the
  Fight deck to our insert index. Nothing ever threw — every position stayed in range either
  way (246/246) — the cards just went in in the wrong order.
* **De-duplication keyed on the offer, then on the deck, and needed BOTH.** One build emits
  up to three packets whose two private views disagree about the kept card, so an
  offer-keyed dedup splits them; but Wong's Crippling Touch REMOVES ITSELF FROM THE GAME, so
  a Fight deck can return to a state it has already been in and a deck-keyed dedup merges
  two real builds. The key is the deck PLUS the offer as an unordered multiset — the views
  of one build offer the same three cards.
* **A forced choice is not a decision** and BGA does not log one; the Fey Folk's last
  Character stalled the replay on a move with one legal answer.
* **`fighterSpecificState.activeTrack` has gaps** — a log can stop re-broadcasting fighter
  state while the fight carries on. Which health TRACK the fightLog moves says the same
  thing, and is the fallback.
* **The engine's last request can arrive after the plan runs out** (a Character dying on a
  fight's final turn), which reported as "stalled in phase=fight".
* **`ranks.index("1")` called a 1,1 finish a win for seat 0.** 54 of the 1738 tables in the
  manifest are draws; our engine was reporting them right and the gate was marking them
  wrong.

Two pieces of SETUP RANDOMNESS have to be forced from the log, exactly like the draft and
the Build shuffle: **Mephisto's serpent coin** (`state: "back"` is black, which attacks;
`"front"` is white, which only grants a Power — derived from the four games that field him)
and **Milady's Intrigue pile**. Both are genuinely random in the real game, so these are
driver overrides, not rules fixes. The override has to be applied EXACTLY ONCE, as the
phase leaves draft: the two `order` moves sit where their Starting-Card packets fall in the
log, and the second can land after the engine has already played a whole fight.

Still open: the draft hands are reconstructed with invented padding — fine for parity,
**must not be used to train a draft policy**.

The three INFERRED readings below are what more parity would settle next.

---

## The engine

`engine.py`'s module docstring holds the authoritative turn order. Two things there
correct `PLAN.md`, which guessed:

* **Bonus Actions are not a late step.** "All Actions are considered simultaneous,
  INCLUDING Actions that are conditional to a success" — so a Block's bonus and an
  Attack's bonus join the same pool and net into the same single marker movement.
* **Success is not Block-only.** An unblocked Attack is equally a success (Joan's
  Sword of St. Michael, Wong's Tiger Fist).

### DECLARATION IS TWO PASSES. Do not collapse it.
Conditions that ask about the opposing card — `no_opponent_attacked`,
`self_attacked`, `own_attack_blocked` (the `OPPONENT_DEPENDENT` set) — cannot be
answered while that card is still unwalked. Seat 0 is always walked first, so a
single pass answers them against a half-declared turn **for seat 0 only, every
time**. That is a rules bug that never crashes: it showed up as seat 0 winning 45%
of a 600-game soak and nothing else. Pass one collects the unconditional actions,
the block sweep runs, pass two answers the rest, and the sweep runs again.
`test_bot.py::test_random_play_is_not_biased_towards_a_seat` is the regression.

### Three INFERRED readings
The printed rules do not settle these; they are marked in the docstring and are
what the replay fixtures would confirm.
1. A conditional Attack gated on `no_opponent_attacked` does not itself count as an
   Attack when evaluating that clause — otherwise two mirrored Hidden Daggers are
   circular.
2. "If you are Attacked" counts an Attack that was declared and not cancelled, even
   if a Block negated its damage. Consistent with a 0-Power Attack still triggering
   a Block's Bonus.
3. Maman Brijit's *You are Mine* redirects the Attacks her Block caught onto the
   opposing Partner. Both readings land the damage in the same place, so it is
   harmless either way.

### The op vocabulary is CLOSED
`effects.py` declares every op, condition kind, computed value and target with the
fields each takes, and `import_bga.py` validates the data against it. A
mis-transcribed card fails at import with its path named rather than resolving to
nothing at the table. It earned that on the first run: the Fey Folk's per-Spirit
scaling had been written `per` on one card and `times` on another.

Anything not expressible declaratively is `{"op": "fx", "name": ...}` →
`FIGHTER_FX`. `UNIMPLEMENTED_FX` is empty and the test asserts the data's fx names
are **exactly** `FIGHTER_FX | UNIMPLEMENTED_FX` in both directions, so neither an
unhandled effect nor a stale entry can survive.

### Fighters that break the general rules
| Fighter | What is special |
|---|---|
| Bödvar | Double-sided board. Rage tops out → +3 Power, **then** flip; the Bear's opening HP is his cubes *at that instant* (so the transform flushes his queued Power first), capped 15, not a ceiling afterwards. Immune to all HP change that turn. |
| Maman Brijit | **Two** KO spaces with a revive space *below* them. Pushed past both she gains 1 Power and returns to HP 4 at end of turn; the revive space is the floor, so further losses there are ignored. |
| The Wild Bunch | Moves at most one space a turn, up or down, whatever the total. Falls out of a STOP on every space below the top — no hook needed. |
| The Fey Folk | Three Characters, one at a time, each with their own track and no KO space. Losing the last HP moves the marker to Spirit; at end of turn the Spirits track advances and the next Character is chosen (a real `pending`). With all three gone they still act but cannot lose or recover HP, and they are KO **only** to their own *All Legends Must Pass*. |
| Shango | Incineration (5 Aflame!) is an instant loss that **overrides** a double KO. |
| Mephisto | *Drag You to Hell*: lose this turn for any reason and you win instead — Incineration included. |
| Wong Fei-Hung | *Crippling Touch* removes both cards from the game permanently, so decks shrink. |
| The Golem | *Reanimation* resolves the next card twice, the second pass as a fresh turn for him alone. |

### Game state
JSON-safe throughout: no sets, RNG as a list, sub-decisions in
`pending_pid`/`pending_kind`/`pending` so they survive saves and reconnects.
**No undo stack**, which sidesteps the snapshot/`rng_state` dedup trap the other
games pay for — there is exactly one RNG copy for `persist.py` to pack.

Cards are **instances**, not ids: `instances[i] = {cid, seat, slot, flipped}`, and
decks are lists of instance indices. The Fey Folk's Summoning cards flip per copy
and Crippling Touch removes specific copies, so a bare card id is not enough.

---

## The server

`main.py` is the shared six-game scaffolding. What differs:

**The game is SIMULTANEOUS**, so there is no seat on turn. The server asks
`engine.may_act`, and `_position_key` **includes who has already submitted** — a
phase-and-round key would call a simultaneous submission "unchanged", letting a
stale bot move apply against a position that had already moved on while the human
acted.

**Redaction.** Both players know which cards exist (the fighters are face up), so
the hidden information is unusually concentrated: your Fight Deck's **order** is
very nearly all of it. `test_redaction.py` searches the serialized payload for the
opponent's deck **sequence** rather than membership, because the instance→card
table is legitimately public.

**The bot plays at random**, deliberately, so the game is playable and testable
before strength work begins. There is **no difficulty picker**, which keeps this
game honestly out of `shared/tests/test_ai_difficulty_memory.py`'s roster — that
test derives its roster by grepping `games/*/[A-Z]*.jsx` for `ai_difficulty` and
will auto-enrol Rag Tag the moment tiers land, which is exactly when
`useLastDifficulty` must be wired.

---

## The frontend

Four files: `RagTag.jsx` (the screens), `art.jsx` (every drawn thing),
`narrate.jsx` (beats → sentences), `RagTag.css`.

`RagTag.jsx` renders cards from their **op lists**, not from text — the generated
data is mechanics only, so the UI says what a card does in its own vocabulary and
no second transcription lives in the frontend to drift. The one exception is
`FX_TEXT` in `art.jsx`: the `fx` ops are the cards the op vocabulary cannot
express, and rendering the literal op name put the word "Special" on the table.
Its wording follows the fx docstrings in `effects.py`.

**`you_owe` comes from the server.** A simultaneous game has no "your turn" to read
off the phase; a client that re-derives it shows the wrong prompt the moment the two
disagree, which the first draft of this file did.

### THE FIGHT IS STEPPED BY HAND, AND EACH TURN PLAYS OUT ONE ACTION AT A TIME
The FIGHT! step arrives as `beats` — one entry per turn with both revealed cards and
every delta. It used to play itself at a fixed 900ms a turn, which meant the only
thing worth watching was gone before it could be read. **Every turn now waits for a
click** (Back / Next turn / To the end), and nothing here drives the server: the
whole round is resolved and saved before the first card is shown, so stepping is
pure replay and a reconnect just restarts it. Beats live in game state and are
**replaced each round, never appended**.

**There are TWO cursors and they are paced differently on purpose.** `beatIdx` walks
the TURNS and only ever moves on a click: a turn is a decision the player made a round
ago and it deserves to be read. `stepIdx` walks the ACTIONS inside one turn and moves
on a timer (`STEP_MS` 700, after a `REVEAL_MS` 520 beat where the cards are face up and
nothing has landed) — because a card that attacks, heals and burns is one decision and
three things to watch, and the whole turn used to land in a single frame: four
sentences at once, and every health bar, Power total and token jumping to its
end-of-turn value together, so the table showed the SUM of the card rather than the
card. `prefers-reduced-motion` skips straight to the resolved turn; the stepping is
pacing rather than decoration, so honouring it means not pacing at all.

**A STEP is one event that narrates, plus the silent events that ran up to it.**
`beatSteps` in `narrate.jsx` cuts a beat up, and its `upto` is an exclusive index into
`beat.events` that serves as the narration cutoff AND the board cutoff, so the sentence
and the numbers cannot disagree. A Block that worked says nothing (the attack it
swallowed is narrated from the other side) but still happened, so it rides with the next
thing that speaks instead of becoming an empty action to sit through; trailing silent
events stretch the last step's `upto` to the end so no event is left unapplied.

**The board state per action comes from the ENGINE, not from replaying events on the
client.** Each beat carries `pre` (the board as the cards flip) and each event carries
`st` — the fighters THAT event moved. `beatStateAt` merges forward. The client models no
event kind, which is the same reason a beat carried a whole snapshot before this existed:
what a `poison` or a `transform` did to the board is the engine's answer. `Turn.note` is
the single funnel that stamps it, `_finish_beat` reduces the stamps to deltas, and
`_move_marker` had to be re-routed through `note` — it appended straight to
`beat["events"]`, which made the hp event the one event the animation is about and the
one event with no state on it. The reduction is deliberately NOT done as each event is
recorded: the Golem's Reanimation resolves a card again through a fresh `Turn` that
adopts this one's beat (`again.beat = turn.beat`), so two Turn objects write into one
event list and a trailing snapshot kept per Turn goes stale the moment the other moves
the board. Cost, measured on the worst round in 80 random games (45 events): beats raw
7.1KB → 16.9KB, zlib 870B → 1143B.

Consequences worth knowing:
* **The next prompt is held until the last ACTION of the last turn is on screen**
  (`owes` returns null while `!atEnd`, and `atEnd` now folds in the step cursor).
  Otherwise the round's outcome arrives as a question before the player has seen what
  happened — which used to mean a whole turn early, and now would mean a sentence early.
* **Back and "To the end" REVIEW; clicking the turn you are on REPLAYS it.** You press
  Back to see what happened, not to watch it again, so it lands on a turn already
  resolved — which is also why neither needs waiting for. The middle button is the only
  one that changes what it says: while a turn is still playing it finishes THAT turn, and
  only once the turn is over does it become the next one, so a click never costs you an
  action you had not seen. It is dropped on the last turn, where "To the end" says the
  same thing.
* **`.rt-actno` is a separate element from `.rt-turnno` on purpose.** The render gate
  proves the fight does not advance on its own by watching `.rt-turnno` hold still for
  2.2s, and an action counter ticking inside it would move for a reason that is not a
  turn. `.rt-actno` is present for the whole time a turn is playing — including the
  reveal beat and a turn with only ONE action, where the count is not worth printing but
  `.rt-actno-live` still has to say "still resolving" — and `screens.mjs` polls exactly
  that to know when a board is safe to read.
* **A beat is not always a turn.** Setup and instant-bonus beats carry no revealed
  cards, and counting them made the stage read "Turn 1 of 1" over two empty card
  slots before anything had been played. `isTurnBeat` is the test, in both
  `RagTag.jsx` and `narrate.jsx`.
* **"Nothing lands." waits for the turn to be over.** Printing it while a turn is still
  revealing passes a verdict on the turn a beat before the turn has one.

### The log is history, the stage is the moment
`narrate.jsx` turns a beat's events into sentences, and the SAME function feeds the
ribbon under the cards and the battle log — so the two cannot disagree, and both are
cut off at the same `upto`, so a turn reaches the log one sentence at a time exactly as
it reaches the ribbon. The log
shows the turns **already stepped past**, not the one on the stage; rendering both
put the same four sentences on screen twice, ~700px apart, which three independent
reviewers each called out. Finished rounds are archived as their NARRATED ROWS, not
as beats, because the text depends on board state that has since moved on.

### Press-and-hold / right-click reads anything
Every face that stands for a fighter or a card — the four board panels, both
played cards, the draft picks, the who-leads options, the build offers and the
rows of your Fight Deck — opens a detail modal on right-click or a long press.
The gesture is `useCardInfoGesture` in **`shared/gestures.js`**, shared with
Dontminion: the hard half is that **Android fires `contextmenu` on a long press
and iOS Safari does not**, so touch needs a real timer, and that is not a thing
to keep two copies of. Both paths funnel through one `fired` flag so a hold can
never also play the card.

Because most of those faces are rendered inside `.map()`, they go through
`<InfoTarget>` rather than calling the hook directly — a hook cannot be called
in a loop, and the wrapper gives each element its own instance.

The modal is where the rules text lives that will not fit on a face. **Every
sentence in it is GENERATED** — from op names, condition kinds, token ids, track
ids and the shape of a health track — because the data is mechanics only and
there is no publisher text to print. That is the whole design, and it is also
the whole hazard: **every one of those lookups has a fallback, and every
fallback renders the raw JSON key while looking completely deliberate.** An
unglossed `fx` prints the literal word "Special"; an unmapped op prints `op.op`;
an unmapped token prints `presence`; an unmapped track prints `+1 navigation` on
the face of a card. Nothing throws, nothing goes blank, and no render test
notices.

Two layers, and the split is load-bearing. **What a mechanic MEANS is written
once, in `art.jsx`**, keyed by the id the data uses — `OP_GLOSSARY`,
`SPACE_GLOSSARY`, `TOKEN_GLOSSARY`, `TRACK_GLOSSARY`, plus `TOKEN_WORD` /
`TRACK_WORD` for the names the board prints. **Where a thing is and how much of
it there is is DERIVED** from the track, so a corrected import moves the modal
with it. `games/rag_tag/tests/test_words.py` holds the first layer to the
second: it derives its roster from `fighters.py` and fails on any op, condition,
`fx`, token, track or kind of space the data uses and the UI cannot name.
Verified non-vacuous against all seven.

The health track is **DRAWN** (`TrackStrip`) rather than described — "1 STOP
space, the marker halts the moment it lands on one" is a sentence about a
spatial thing — and its spaces are read out by WHERE they are (`10 health — +1
Power`), not counted ("4 spaces carry an icon"). The key under it names **only
the kinds this board has**: it used to name KO, stop, icon and revive on all
twelve, nine of which have no revive space, and its longest entry was the word
"icon" — a legend meaning "something happens here, we are not saying what".

What is left over is what a board does that its track cannot draw: `boardFacts`
reads `characters`, `back`, `revive_to_hp`, `setup_icons` and the KO count off
the fields, and a board-level `note` in `boards.json` carries the one thing that
is genuinely un-derivable (the Bear's opening HP). **The catalog endpoint has to
ship those fields or the modal silently renders one fewer line and still reads
like a complete description** — `setup_icons`, `absorbs_attack`, `revive_to_hp`,
`note` and the instant bonus's OPS (it shipped as a `bool`, so the modal could
flag the bonus and not say what it paid) were all missing until 2026-08-27.
`test_server.py` guards them.

Watch the three shapes `special_track` comes in: a real space list (Bödvar,
Joan), a min/max range with `spaces: []` (Ching Shih, the Fey Folk), and **an
empty object for a fighter that has none** — which is truthy, and printed a
track Milady does not have. `SpecialTrack` therefore keys off `track.id`, not
the object. A `shape: "circular"` one is DRAWN as a ring (`DialRing`, an SVG
generated from the same `spaces`): a row of boxes is the one shape a ring is
not, and it cannot show either the wrap or the fact that the centre is entered
once and never returned to.

**A fighter with `characters` needs BOTH numbers on the fighting card** — how
much is left in the Character you can hit, and how much is left in the team.
`CharacterRoster` lists all three with the active one accented and a Spirit
struck through; without it the Fey Folk read "3/3" while carrying nine more
health nobody could see. Their `chars` map already reaches the client, so this
is client-side only.

**The modal opens with the FIGHTERS' GUIDE half, not the mechanics.** `title`,
`profile` and `rating` in `boards.json` mirror the printed profile sheet: an
epithet, a paragraph on how the Fighter plays, and five 0–5 bars
(health/offense/defense/heal/special) over the complexity dots. Everything below
it is derived from the rules and is the right answer to "how does this work" and
a useless answer to **"is this Fighter for me"** — which is the only question the
draft actually asks, and the one the modal could not answer at all. The ratings
were MEASURED off the sheet (a flattened image: sampled at 200dpi, checked
against two crops read by eye) rather than eyeballed, because the eyeballed pass
had Bödvar's DEFENSE at 2 where it is 4.

**A rating is not a scale.** `complexity` shipped as its raw 1–5 beside the
words "of 5 to learn", which tells a reader neither end of the range; it is a
word now (`COMPLEXITY_WORD`). Two of the three things a player reads on a board
were numbers that needed a legend nobody had.

### The rules panel follows the RULEBOOK's order and vocabulary
`rules.jsx` is laid out in the printed order — Goal of the Game, Setup, a Round,
Actions, who counts as whom, the icons, how a Fight ends, the Golden Rule — so a
reader who has the real rules can find the same thing in the same place. It uses
the rulebook's words (Active Fighter, Partner, Opponents, Bonus Action, Success,
Direct Damage, Stop, THEN, Power cubes, Fight Deck), because a rules panel that
renames things makes the CARDS harder to read.

**That order is also the SITE's order** (root `CLAUDE.md`, the how-to-play
section): every game's panel opens on `Goal of the Game` and then `Setup`, and
this one's printed order happens to agree from there, which is why it needed the
least moving of the nine. What it lost in the 2026-09-18 pass was the lead
paragraph and the `RulesFacts` strip — the simultaneous flip and the
never-shuffled deck are the GOAL, so they are stated there, and the player count
is in Setup.

**`RulesDefs` takes `{t, d}` PAIRS — a bare string renders an EMPTY BOX**, and so
does `RulesFacts` with `{k, v}`. Rag Tag passed bare strings in three places, so
its Setup, Health-track and Winning sections were blank strips for as long as the
game existed. Nothing could see it: the markup was all present and correctly
styled, so `screens` found its elements, the Python suite does not render, and
the CSS token test only looks at tokens. Guarded now by
`shared/tests/test_rules_kit_shapes.py`, which globs every `games/*/rules.jsx`
(Rag Tag was the only offender) and by a `screens` check that asserts no part of
the panel is blank — it read the fact boxes until the strip went away, and walks
the definition lists now, which is where the same trap lives.

### What has to be ON THE CARD, and what the modal is for
A player reported it exactly: *"Everything I need should be visible, with the modal
there to explain things if you're new."* So the fighting card carries every
number a decision depends on, and the modal explains what those numbers MEAN.

Three things were only in the modal and are now on the card:

* **the special track, drawn** (`SpecialOnCard`). These were chips — "Fleet 7",
  "Divine Voice 2", "Spirit 1". An integer says where the marker is and nothing
  about where it is GOING, which is the entire purpose of these tracks: Ching
  Shih's deck reads thresholds at 7/10/15/20, Bödvar's Rage ends the moment it
  tops out, Joan's dial pays on two spaces of four. A track with real spaces
  draws a pip each; a short range (the Spirit track, 1–4) draws pips derived
  from the range; a long range (the Fleet, 0–20) draws a bar with `TRACK_MARKS`
  notched on it.
* **every Character's health** (`CharacterRoster`), not just the one on the board.
* **the health track itself**, which was already there.

`guide` in `boards.json` is the other half: the Fighters' Guide rules that the
tracks and tokens cannot be read off — the Wild Bunch moving ONE space when hit
and healed on the same Turn, Incineration not being health loss, a Scheme from
the Health track resolving in a mini-phase after the cards. Everything the modal
CAN derive still is; `guide` is only what it cannot.

### Everything visual is drawn in the bundle
There is no licensed art in the repo (see *Where the data came from*), so `art.jsx`
carries a hand-authored emblem and accent colour per fighter plus the mechanical
icon set. Hand-drawn beats a hash — a hashed hue puts the pirate and the devil on
neighbouring reds. No file is fetched, so nothing can 404 or need a cache-bust.

### Three layout traps, all paid for twice
* **`baseCss` is not optional.** Rag Tag shipped without it. The shared lobby kit is
  written against the site theme tokens (`--surface`, `--border`, `--radius`), so
  every `border: 1px solid var(--border)` in that kit was invalid at
  computed-value time and resolved to `0px none`. The lobby still laid out, so it
  read as a design choice rather than a missing import.
* **`.app` is a COLUMN FLEX container**, and both `.rt-wrap` and the shared
  `.lby-cols` carry `margin-inline: auto`. Auto margins beat `align-items: stretch`
  on a flex item, so both shrink-wrapped to their content: the whole game rendered
  in a ~430px strip on an 834px tablet, and the layout WIDTH CHANGED BETWEEN PHASES
  because content was driving it. Any centred wrapper inside `.app` needs an
  explicit `width: 100%`. Dontminion hit this and fixed it the same way;
  **Spender Duel still has it** (`.duel-lobby-cols`, measured 851px of 1440).

* **A variant written ABOVE its base rule loses.** `.rt-ctl-danger` and `.rt-ctl`
  are equal specificity, so whichever is written last wins — and the danger
  variant sat 400 lines above the base rule, so the Abandon button came out
  painted identically to Keep playing. Same family as the media-query trap below:
  in this sheet, order IS the cascade. Keep a `rt-ctl-*` variant next to the
  others, after `.rt-ctl`.

**NOTHING ON THE SURFACE IS SELECTABLE** (`user-select: none` on `.ragtag`, with
`input`/`textarea`/`[contenteditable]` exempted). This matters more here than in
the other games because **press-and-hold IS Rag Tag's read gesture**: on a phone
a long press raised the browser's selection handles and copy callout instead of
opening the Fighter, so the game's own gesture was fighting the platform's. Same
rule and reasoning as Dissonance.

**The game menu is the shared one, and abandon ASKS.** Return / rules / abandon,
in that order, with icons — and abandon opens a confirmation rather than firing
on the click. Rag Tag was the last game that did it directly, so one stray tap in
the menu ended the fight.

CSS is a real `.css` file imported `?inline` — never a JS template literal. The
sheet must not set `display`/`grid-template-columns`/`gap` on `.rt-lobby-cols`: it
is concatenated after the shared one, so a base rule there out-orders the shared
media rules and pins a phone to three columns. Width and padding ARE fair game.

---

## Testing

`pytest games/rag_tag/tests -n0 -q` — 141 tests.

| File | Covers |
|---|---|
| `test_fighters` | the generated data: staleness, the closed op vocabulary, deck sizes, every track able to end a fighter, and that no `--` transcription artefact reaches the detail modal |
| `test_engine` | the rules, mostly by rigging an exact position and resolving ONE turn — a simultaneous game has no "make a move and see"; plus the beat NARRATION events (attack/block/cancel), which render as an empty log line rather than as any kind of failure |
| `test_bot` | the soak: whole games over random teams, every fighter forced in, invariants, seat symmetry |
| `test_server` | rooms, moves, the bot scheduler end to end |
| `test_ws_auth` | seat identity binding |
| `test_redaction` | the whole serialized payload of a REAL played game |
| `test_persist` | compaction round trip, structural proof it did something, resume mid-fight and mid-build |
| `test_words` | every op, condition, `fx`, token, track, complexity rating, profile/rating block and kind of space the DATA uses has words in the UI — the one gate over a layer whose every failure mode renders a plausible-looking sentence rather than throwing. Also the two SHAPE guards (a circular track is drawn as a circle; a board of Characters lists them all on the fighting card), which exist because the browser can only check those when Joan or the Fey Folk happen to be drafted |

Frontend: `webapp/test/screens.mjs` §`ragtagFight` (lane A) creates a vs-bot game
and plays a full round in a browser. Mounting the route proves nothing about a
simultaneous game; only playing one does. It specifically asserts the two things a
render test would miss: that the fight **does not advance on its own**, and that the
next decision is **held back** until the last turn is on screen.

**Still no `test_parity`, deliberately — and the replay harness existing does not
change that.** The harness needs the BGA corpus, which lives OUTSIDE the repo and is
not redistributable, so a pytest wrapper would have to skip when it is absent. The
repo's rule is that a test which cannot reach its state must FAIL rather than opt out,
and `core/tests/test_no_conditional_skips.py` enforces it mechanically — so parity
stays a TOOL you run (`bga_filter`), not a test that lies about being green.
What parity findings DO get is a normal unit test each, rigged to an exact position.
That is how all ten of them are held down now, and each one carries the table and turn it
came from in its docstring — a rules bug found by a real game is worth almost nothing as a
green tick and quite a lot as a sentence saying what the real game did.

---

## Open follow-ups

* MORE LOGS. Every one of the 40 now reproduces exactly, so the gate has stopped
  finding bugs — not because there are none left, but because these 40 games stopped
  exercising anything new. The scraper drips ~10/day; re-run `bga_filter` as it grows.
* A bot with any strength at all, and the difficulty picker that comes with it.
* The lobby empty states, the emoji Rules glyph and the History column width are
  all the SHARED kit (`shared/lobby.jsx`), flagged repeatedly by the visual review
  but owned by seven games — a change there is a seven-game change.
* The 14 expansion fighters BGA also serves (Arthur's Legacy and one more) — the
  importer and the op vocabulary already handle their shape; only the transcription
  and their special rules are missing.
