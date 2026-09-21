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
by the `cob-mining` cron. **39 logs today, and only 26 of them are base game** — the other
13 are Matcha, which adds green dice, a fourth personal-domain row, geishas, chasen, the
Tea Fields and the Outskirts of Himeji, and whose cards share the base id space. Derive
from the whole pile and the base board grows two action spaces that are not in our box, so
`tools/bga_parity.py` splits them and works on the 26.

**The corpus grew 20 → 26 base games on 2026-09-20 and not one derived rule moved.** The 6
new games contributed 20 scoreboards the formulas had never been fitted to and reproduced
all 20, which is the strongest evidence the board half is right that we have: a fitted
formula does not generalise to unseen games for free. Two things did change, and neither
is a rule — see *Reading a log: the two eras* below.

**The audit ran. It is `tools/bga_parity.py`, its output is `data/bga_ground_truth.json`,
and `tests/test_bga_parity.py` holds the engine to it.** The fixture is committed and is a
few KB, so those tests run on a fresh clone with no corpus; regenerate with `--write`.

- **The instrument checks itself, and nothing here should be trusted further than that
  check.** BGA ships a per-player `scoreBreakdown` it computed independently, so the tool
  reconstructs each final board out of the event stream and recomputes all nine categories
  with the formulas it is about to write down. **90 of 90 seats, exact.** A scoring rule
  that is wrong does not produce a subtly odd fixture; it fails to reproduce 90 real
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
| Turn order tie-break | last round's leader stayed ahead | the marker ON TOP leads — 78 of 78 in the corpus |
| Starting resource cards | 9 | 8 |
| The Well | 1 seal + two tiles revealed at random from a hidden bag, which locked undo | 1 seal + its own TWO tiles, face up from setup, same payout every visit |
| Outside the Walls actions | any of the three workers from either space | left = Gardener or Courtier, right = Warrior or Courtier |
| 2-player deck | all 15 stewards and 12 diplomats | the 6 + 3 diamond-marked cards stay in the box: 9 and 9 |

**And one rule this audit got WRONG before getting it right.** The first pass deleted the
`1 die at two players, 2 at three or four` check on the reasoning that board printing does
not shrink. The printing does not -- but "in a 1- or 2-player game, dice cannot be stacked
on top of other dice in any part of the game" is a separate 2-player rule, and at the time
the corpus could not have caught the mistake because **it contained no 2-player games at
all**. It went back in as `SOLO_OR_DUEL_DICE`, on the rulebook's authority alone.

**The second batch brought the first 2-player table, and it confirms the restored rule.**
Peak occupancy alone would be weak — a short game may simply never crowd a space — so the
test is what the game OFFERED. In BGA's "choose a die" state every legal destination is
listed for every takeable die, and at two players **a space already holding a die was
offered zero times out of 552**, against 6,831 times at three and four players. That is a
rule being enforced; a coincidence of play does not look like that. The same log carries
**no diamond-marked card at all**, and it drew 8 distinct stewards from a 15-card deck
without once hitting one of the 6 diamonds — C(9,8)/C(15,8) = 0.0014 if they were still in
the box. Both duel rules are now measurements rather than quotations, pinned in the
fixture's `two_player` block.

The lesson survives being confirmed, and is the cheap one: a corpus that cannot reach a
case is not evidence about that case, and "the data does not show this" is not the same as
"this is not so". The fix was to go and get the case, which took six games.

**The Well is the one space that never fills up** — the corpus shows THREE dice on it at
four players, more than any room ever holds. The engine already offers it unconditionally;
what the test guards is a future blanket capacity rule sweeping the Well up with the rooms.

### Reading a log: the two eras

**The newest logs are the OLDEST tables, and they use an older payload.** The second batch
has lower table ids (731–775M against 858–904M), so anything "new" in them may be BGA's
schema changing rather than the game's rules. Two such differences turned up, and both
split *perfectly cleanly by log*, which is what tells drift apart from a rule:

- **`conditional` is absent on the older payload.** All 6 new logs report no conditional on
  any block; all 20 older ones report `and`. This is not a new kind of conditional and it
  is certainly not an `or` — the fixture records it as `None` only because
  `block.get("conditional")` returns that for a missing key.
- **A free action is spelled two ways.** The older payload writes `qty: 0` with a coin icon
  where the newer one omits the cost entirely, so `Perform Gardener Action` and `Perform
  Warrior Action` each gained a second operand set that is the same behaviour.

Net of that drift the remaining job grew by exactly **one** operand set — `Gain seal Decree
Card`, which is real — and no new template. When a bigger corpus seems to add vocabulary,
check the era split before believing it.

Confirmed already correct and now pinned by a test: courtier points by floor (1/3/6/10),
warriors = Σ(yard points) × courtiers INSIDE the castle (the gate does not multiply),
gardeners = Σ(garden points), (coins+seals)//5, resources 0/1/2 at <3 / 3–6 / 7, caps of 5
seals and 7 of each resource, 3 rounds × 3 turns, dice per colour 3/4/5 at 2/3/4 players,
bridges sorted ascending with both ends takeable, the left end paying the Lantern, and the
die-value difference settled in coins either way.

### THE CATALOGUE IS REAL NOW (2026-09-20)

**`cards.py` is no longer placeholder.** `catalogue.py` is GENERATED by
`tools/build_catalogue.py` from `data/base_catalogue.json`, and carries the printed
15 stewards, 12 diplomats, 9 starting resource cards, 3 starting action cards and 3
decrees with their real effects. `tests/test_catalogue.py` re-runs the generator and fails
if the checked-in file is stale, so a hand edit is caught rather than merely lost — the
same contract Rag Tag's `fighters.py` has.

**The vocabulary is closed, and that is the load-bearing part.** Every BGA effect is a
template plus operands, `TEMPLATES` maps each to one of 8 ops, and a template that is not
in the map **stops the build** naming the card. Silently skipping an unknown effect gives
a game that runs perfectly and plays a different game. The 8: gain
(coin/food/iron/pearl/seal/vp/any-resource), gain Lantern Rewards, move the Passage of
Time, perform a Courtier / Gardener / Warrior action, perform the Well action, gain a
Decree Card, plus `domain_action` and `main_board_action`, which appear **only on yard
tiles** and are data-only until a tile-action system exists.

Three things that were not obvious until the data was real:

- **A PRICE IS A CURRENCY, NOT A NUMBER.** A castle card charges SEALS to repeat a worker
  action; a yard tile charges COINS. Both arrive as the same `qty` beside an icon, so a
  cost flattened to an integer bills a tile's 3 coins to the seal track — a divergence a
  player would feel and no obvious test would catch. `cost` is `{currency: amount}`.
- **`Gain <resource> N` does not name the resource.** Ten of the 68 cards grant "a
  resource", and resolving that quietly — always food, say — is exactly the kind of
  divergence that never surfaces as an error. It is kept as `"any"` and the engine ASKS,
  via a `choose_resource` pending, one pick per unit.
- **The draft is held open for that pick.** `draft_queue` is `reversed(turn_order)`, so
  the last seat to draft is `turn_order[0]` — the player about to take turn 1. Closing the
  draft over their unresolved choice leaked the pending into the play phase and handed
  them an `end_turn` for a turn they had not taken.

**Counts that were wrong, and both the same mistake.** `starting_resource` was 8 (there
are **9**, three backed with each of pearl/iron/food — typeArg 3 is the rarest at 8
sightings and the 20-log corpus simply never dealt it) and `starting_action` was 6 (there
are **3**, one per worker, across 444 sightings). Both had been trimmed to match an
under-sampled observation, which is the deleted-2-player-dice-rule error wearing a
different hat: *the data not showing something is not the thing being absent.* The counts
are now DERIVED from the catalogue rather than typed beside it.

### The castle Die tiles: SOLVED AND IMPLEMENTED (2026-09-20)

**One Die tile sits beside each action block, and a die resolves every block whose tile
matches its colour.** The engine used to pick `light` or `dark` from
`(die value + room index) % 2` — which made the die's COLOUR meaningless in the castle and
its VALUE decide the action, when the printed game is the other way round.

**The geometry was proved twice, from unrelated evidence.** Every printed Steward card has
exactly 3 action blocks and every Diplomat exactly 2 (from the card catalogue); a steward
room holds 3 tiles and a diplomat room 2 (from the colour sets the corpus offers, via
`die_tile_bag`). 3×3 + 2×2 = 13 in the castle and 2 at the Well. Two derivations, different
data, same answer.

**How the rule itself was verified.** The logs ship no die-tile object at all, so the rule
is not readable — it has to be inferred from what happened. For every castle placement,
the fired block is identifiable from the worker it deployed (56% of 378 placements), and
the claim under test is that a room's tiles are fixed for the whole game, so the same room
plus the same die colour must fire the same block slot no matter which card is standing
there. Results:

- **a slot index beyond the card's block count: 0 occurrences.** That is the sharp
  falsifier and it never fired.
- **99 of 100 rooms had no colour collision** — no slot fired by two different colours,
  which is what "one tile per block" requires.
- the shape distribution is exactly the prediction, including **13 rooms where one colour
  fired TWO slots** — always a room whose tiles showed only two distinct colours, i.e. one
  colour doubled. A colour on two tiles performs both rows; that falls out of matching
  every tile rather than being bolted on.
- the single collision is a measurement artifact, not a counterexample: that room showed
  three colours with red→0 and black→1 already clean, so white must be slot 2. The
  resolution window runs to the next die placement and so includes the rest of the turn,
  where a worker deployed from Outside the Walls or the personal domain is attributed to
  the card by mistake.

**Setup enforces NO ROOM ALL ONE COLOUR**, because a monochrome room would be a dead room
— two of the three die colours would resolve nothing in it. The corpus shows the
consequence: a diplomat room displayed two distinct colours 40/40 and a steward room two or
three, never one. `_deal_room_tiles` reaches that by re-laying until it holds rather than
by the printed push-a-tile-on procedure; the two differ only in the distribution over
layouts, which nothing in the corpus can distinguish. **The first version did implement the
push-on rule and was wrong** — it passed a hand-traced example and still produced a
monochrome room in 21 of 1200 deals, because its repair pass could re-break a room it had
already walked. A constraint you can check at a glance beats a procedure you cannot.

**A die may now only enter a room one of whose tiles shows its colour**, and
`test_a_die_always_has_somewhere_legal_to_go` pins that this can never close every
destination: the Well takes any colour and never fills up.

**The tiles are per-field redacted.** A castle tile lies colour side UP, so its colour is
public board state — it is what decides which dice may enter — and its reward face is down.
The tiles are nested inside `castle.rooms`, and a nested copy of hidden state is exactly
how this repo's redaction was defeated once before, so the test asserts against the
serialized castle of a real game.

### STILL NOT PARITY — do not describe this port as faithful

1. **The Daimyo's Favor cards are still ours.** All 3 of them, and they are the one part of
   the catalogue the corpus **cannot** supply: BGA only ships a Daimyo card's definition
   once a courtier reaches the third floor, and across 26 base games that never happens.
   `cards.py` still generates 9 of them. The rulebook, not the corpus, is the source here.
2. **A courtier climbing INTO a room takes that room's card** — `resourcePaid` →
   `courtierMovedUp` → `lanternCardGained`, 202 times — and a new card is revealed behind
   it. That is how the Lantern Area fills, and the Lantern is what the left end of a bridge
   pays out. Our engine resolves room cards with DICE and never hands the card to anyone.

**The Die tiles, now that the setup rule is known.** There are 15, each DOUBLE-SIDED: a
die colour on one face, a reward on the other. Setup lays 3 of them into the castle spaces
marked ♦ (one of each colour), fills the numbered castle spaces 1-10 in order — moving a
tile on to the next room whenever a room would end up all one colour — and puts the last
two at the Well, dice-side DOWN. That accounts for 13 castle tile spaces across 5 rooms,
so three rooms carry three tiles and two carry two, which is why a room shows two colours
106 times and three colours 24 times in the corpus and never more. **Both halves are
implemented now** — the Well's two tiles pay their fixed reward every visit, and the
castle's thirteen decide which rows a die resolves (see the Die tiles section above).
What is still unknown is the 13 castle tiles' REWARD faces, which stay face down all game
and are therefore never observable.
**And the bag is SOLVED: five tiles of each colour.** No rules text states it and no
single game comes close — the most informative one alone leaves six candidates — but each
game rules some out and the intersection over the corpus is a single bag. The 6 games
added on 2026-09-20 did not disturb it: the answer is still uniquely 5/5/5.
`tools/bga_parity.py:die_tile_bag()` does it as a constraint problem, and two things make
it a derivation rather than a curve fit. The room split is not assumed: a diplomat room
showed exactly two colours **40 times out of 40** and never three, while steward rooms
reach three, so diplomats hold 2 tiles and stewards 3 — which is also what puts the three
♦ spaces in the steward rooms. And the Well count is not assumed: solving with 0 or 1
tiles at the Well yields **no consistent bag at all**, and only the rulebook's own "place
the well tiles last" admits one. A wrong geometry here does not give a slightly-off
answer, it gives an empty set — which is why an earlier pass, reading three tiles into
every room, concluded the logs *ruled 5/5/5 out*. They rule it in.

**What is left of the tiles is the REWARD faces**, and only two of the fifteen are ever
read — the pair at the Well, whose payout the logs show directly. Seventeen games give
seventeen samples of two tiles drawn from the bag (`coin+1`, `food+1`, `iron+1`, `pearl+1`
and `vp+1` all appear, and one game paid `iron+1` twice, so at least two iron tiles
exist). That is enough to reconstruct the reward multiset with more games, by the same
intersection trick; the castle tiles' reward faces stay face down all game and never
matter.

Also still unverified: the 3 Daimyo Favor cards, and **every 2-player rule beyond the two
above** — which are now confirmed, but on the strength of a SINGLE duel log. One game is
enough to settle a rule the game enforces on every offer (no stacking: 552 chances, 0
violations) and enough to make the diamond removal unlikely to be chance (p ≈ 0.0008); it
is not enough to turn up a duel rule nobody has thought to look for. More 2-player tables
remain the cheapest thing the corpus could gain.

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

