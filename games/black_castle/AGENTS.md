# The Black Castle

The Black Castle is the base-game digital port of The White Castle (2023).
`engine.py` is the authoritative, JSON-safe rules engine. `main.py` owns only
rooms, websocket authentication, persistence, and bot scheduling. The browser
never calculates outcomes.

The first release intentionally exposes one ruleset (`base`) and one opponent
tier (`easy`). Easy chooses uniformly from the legal move list. The room model
already supports two or three bot seats, so a single human can play a 3- or
4-seat table while expansion data can be added later without changing the
wire protocol.

Keep private ordered decks, RNG state, undo snapshots, and pending choices out
of `player_view` for every recipient. New fields in the room state need a
redaction test and a persistence round trip before shipping.

## BGA parity: what the corpus proved, and what it proved WRONG

The corpus is `$WHITECASTLE_CORPUS` (default `C:/Users/Forrest/WhiteCastle_corpus`), filled
by the `cob-mining` cron. **29 logs today, and only 20 of them are base game** — the other
nine are Matcha, which adds green dice, a fourth personal-domain row, geishas, chasen, the
Tea Fields and the Outskirts of Himeji, and whose cards share the base id space. Derive
from the whole pile and the base board grows two action spaces that are not in our box, so
`tools/bga_parity.py` splits them and works on the 20.

**The audit ran. It is `tools/bga_parity.py`, its output is `data/bga_ground_truth.json`,
and `tests/test_bga_parity.py` holds the engine to it.** The fixture is committed and is a
few KB, so those tests run on a fresh clone with no corpus; regenerate with `--write`.

- **The instrument checks itself, and nothing here should be trusted further than that
  check.** BGA ships a per-player `scoreBreakdown` it computed independently, so the tool
  reconstructs each final board out of the event stream and recomputes all nine categories
  with the formulas it is about to write down. **70 of 70 seats, exact.** A scoring rule
  that is wrong does not produce a subtly odd fixture; it fails to reproduce 70 real
  scoreboards and the tool exits 1.
- **`isUndo` events are STATE, not chatter.** BGA replays a rolled-back action as the same
  notification with `isUndo: true` carrying the RESTORED value, and players undo constantly
  — one seat restarted its turn nine times in a row. Courtier scoring came out wrong on 11
  of 70 seats until undos were applied, and every one of those looked exactly like a
  scoring-table bug.
- **`id` is the COPY, `typeArg` is the CARD.** Card id 28 is one decree in one game and a
  different one in the next. Keyed on `id`, 240 steward sightings "disagree"; keyed on
  `typeArg`, **zero conflicts** and the counts land on the printed box — 15 stewards, 12
  diplomats, 5 plant and 5 stone gardens. `extract_bga_catalogue.py` already keyed this
  way but harvested the Matcha logs too, and since their cards share the id space it
  reported 18 stewards and 9 plant gardens — more than the box contains, which reads as
  over-coverage rather than as two boxes counted as one. It is base-only now
  (`--with-expansions` to opt back in) and lands on every printed count at 0 conflicts,
  which is the independent evidence that `typeArg` is the identity.

### Fixed, because the corpus disproved what we had

| Rule | Was | Is |
|---|---|---|
| Passage of Time scoring | `>=11` scored the raw position (11–15) | 0 / 3 / 6 by season, then 10–15 printed in the fourth |
| Checkpoints | `{6:1, 10:2, 11:3}` | `{6:1, 11:2, 15:3}` — markers stop dead on 5, 10 and 14 |
| Track length | 15 | 20 (four seasons of 6/5/4/6 spaces) |
| Social climb | floor2 → daimyo cost 5 pearl; floor1 → daimyo impossible | one floor costs 2, two floors cost 5, everywhere |
| Personal domain | any die in any of the three rows | coral takes only coral, black only black, white only white |
| Castle room capacity | 1 die at 2 players, 2 at 3–4 | 2 at every player count |
| Training yards | 8 generated yards, 4 dealt | the printed 3, always all 3: 5 iron→2 pts, 3→1, 1→1 |
| Gardens | 3 plots, only the Plant card reachable | 6 plots; the ladder is cost *c* pays 2*c*−1 |
| Turn order tie-break | last round's leader stayed ahead | the marker ON TOP leads — 60 of 60 in the corpus |
| Starting resource cards | 9 | 8 |
| The Well | 1 seal + two tiles revealed at random from a hidden bag, which locked undo | 1 seal + its own TWO tiles, face up from setup, same payout every visit |
| Outside the Walls actions | any of the three workers from either space | left = Gardener or Courtier, right = Warrior or Courtier |
| 2-player deck | all 15 stewards and 12 diplomats | the 6 + 3 diamond-marked cards stay in the box: 9 and 9 |

**And one rule this audit got WRONG before getting it right.** The first pass deleted the
`1 die at two players, 2 at three or four` check on the reasoning that board printing does
not shrink. The printing does not -- but "in a 1- or 2-player game, dice cannot be stacked
on top of other dice in any part of the game" is a separate 2-player rule, and the corpus
could never have caught the mistake because **it contains no 2-player games at all**. It
is back, as `SOLO_OR_DUEL_DICE`, with a test that says where it comes from. The lesson is
the cheap one: a corpus that cannot reach a case is not evidence about that case, and
"the data does not show this" is not the same as "this is not so".

Confirmed already correct and now pinned by a test: courtier points by floor (1/3/6/10),
warriors = Σ(yard points) × courtiers INSIDE the castle (the gate does not multiply),
gardeners = Σ(garden points), (coins+seals)//5, resources 0/1/2 at <3 / 3–6 / 7, caps of 5
seals and 7 of each resource, 3 rounds × 3 turns, dice per colour 3/4/5 at 2/3/4 players,
bridges sorted ascending with both ends takeable, the left end paying the Lantern, and the
die-value difference settled in coins either way.

### STILL NOT PARITY — do not describe this port as faithful

Three things the corpus specifies completely and the engine does not implement. They are
one job, not three, because they are the same loop:

1. **`cards.py` is still placeholder** and still says so in its own code. The real
   catalogue IS recoverable — 15 stewards and 12 diplomats at zero conflicts, plus the
   starting, decree and garden cards — but the effects are templates
   (`"Pay ${iconPlaceholder2} ${qty} to perform ${iconPlaceholder1} Gardener Action"`)
   over a vocabulary we have no ops for.
   **That vocabulary is SMALL, and measuring it is the difference between a rewrite and an
   afternoon: 11 distinct templates across the whole base catalogue, over 31 operand sets --
   19 of which are the amounts on the single `Gain <icon> <n>` template, a table rather
   than a behaviour -- collapsing to 8 ops** — gain (coin/food/iron/pearl/seal/vp/any-resource, 1–5), gain
   Lantern Rewards, move the Passage of Time 1–2, perform a Courtier / Gardener / Warrior
   action (free or for 1 seal), perform the Well action, and gain a Decree Card. **Every
   base block is `light` or `dark` and every conditional is `and`** — the blue/yellow
   curtains and `or` belong to Matcha's flower and calligraphy cards, not to this box, so
   neither is on the critical path.
2. **The die-colour tiles in the castle rooms.** Each room is filled at setup with one
   colour tile per ROW of the card that will sit there, at least two distinct colours per
   room. A die may only be placed in a room whose tiles include its colour, and **the rows
   whose tile matches are the ones that resolve** — so a colour appearing twice performs
   two actions. Our engine instead picks light or dark from `(die value + room index) % 2`,
   which is not a rule in this game. The evidence is unambiguous: a room's colour set is
   stable for a whole game while the card in it changes repeatedly, and sets of size 3
   occur (81 rooms of 2 colours, 19 of 3).
3. **A courtier climbing INTO a room takes that room's card** — `resourcePaid` →
   `courtierMovedUp` → `lanternCardGained`, 202 times — and a new card is revealed behind
   it. That is how the Lantern Area fills, and the Lantern is what the left end of a bridge
   pays out. Our engine resolves room cards with DICE and never hands the card to anyone.

**The Die tiles, now that the setup rule is known.** There are 15, each DOUBLE-SIDED: a
die colour on one face, a reward on the other. Setup lays 3 of them into the castle spaces
marked ♦ (one of each colour), fills the numbered castle spaces 1-10 in order — moving a
tile on to the next room whenever a room would end up all one colour — and puts the last
two at the Well, dice-side DOWN. That accounts for 13 castle tile spaces across 5 rooms,
so three rooms carry three tiles and two carry two, which is why a room shows two colours
81 times and three colours 19 times in the corpus and never more. The Well half is
implemented; the castle half is the colour rule above, still open.
**What is still NOT pinned** is the colour composition of the 15-tile bag. No rules text
we have states it, and the logs rule out a flat 5/5/5 under a 3-tiles-per-room reading —
one game needs at least 5 black while another allows at most 4 white. `cards.py` models it
5/5/5 and says so. Deriving each room's per-ROW colour from the effects that actually
fired would settle it; a first attempt resolved only 28 of 208 placements, because a row
whose gains carry no `cardId` cannot be attributed.

Also still unverified: the 3 Daimyo Favor cards, and **every 2-player rule beyond the two
above** — the corpus has no 2-player games, so nothing about a duel is evidence here.

### The yard tiles, for when the tile engine lands

The 8 Training Yard tiles are double-sided too, and **a game puts 4 of them in play — two
in the blue orientation and two in the yellow — distributed 2/1/1 across the three yards**
(8 of the 20 logs carry all three yards and every one of them reads 2/1/1). All 16 faces
are in `data/bga_ground_truth.json`. Our yards still carry one placeholder `effect` each
instead, which is the same job as the card effects and lands with them.

### What the logs do and do not carry

- **Generously**: `diePlaced` names the die (id, colour, pips) AND the exact action space,
  and the "choose a die" state (`gameStateChange` id 20) lists **every legal destination
  for every takeable die**, which is what made the colour rules derivable at all.
  `warriorAssigned` / `courtierMovedUp` / `gardenerAssigned` / `passageOfTimeMoved` /
  `resourceGained` / `sealPaid` / `scoreUpdated` cover placement, movement and payment,
  and each payment event carries the player's NEW TOTAL, so holdings are reconstructable.
- **Not at all**: which card a player drew or holds. `actionCardGained` and
  `lanternCardGained` carry only a `playerId` and `newMainBoardCardRevealed` is empty, so
  hands are hidden exactly as in Orbit. The catalogue and the public board are readable; a
  full move-replay is not.

