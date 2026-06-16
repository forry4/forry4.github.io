# AZ v4 feature spec — card-valuation features

Planning doc for the **fresh feature-enriched retrain** (`checkpoints_v4_features/`).
A new input dimension makes all v3 weights incompatible, so this is a clean start —
schedule it only after the v3 run finishes and its best net is evaluated. No code or
training change happens from this doc alone.

Source of truth this maps to: [features.py](features.py) (current `N_FEATURES = 305`)
and [engine.py](engine.py) (`State`, `COST/PTS/BONUS/NOBLE_REQ`, `_gold_needed`).

## Design doctrine (why these and not others)

CLAUDE.md's hard-won conclusion: **static-eval accuracy plateaus ~0.65 regardless of
model/features — the missing info is lookahead, which is search's job, not the
evaluator's.** So the rule for adding features is narrow:

> Add a feature **only if it is expensive for the MLP to compute from the flat vector
> itself** (cross-card interactions, multi-step arithmetic). Do **not** add things the
> net already reads directly from raw state (its own points, token counts, noble reqs).
> Hand the net the hard-to-derive *raw signals*; let self-play + search learn the
> board-conditional *weighting*. We do not bake stage/strategy weighting into the
> features — that is what the net is for.

This is why factors like "how close the points bring me to victory" (user factor 8)
get **minimal** new encoding — the net already has `points/15` and the final-round
flag, so it can compute closeness trivially. The heavy lifting is in **effective cost**,
**turns-to-afford**, and especially **engine value** (the cross-card term), which an
MLP genuinely cannot discover from a flat vector.

User note honored: the **post-cost-reduction gem cost is NOT dropped** — it's a
first-class signal, distinct from tempo. The "effective cost" block (features 1-5 below)
is exactly `cost − your bonuses`, i.e. the discounted gem cost after your card
reductions. Tempo (turns-to-afford) is weighted higher, but effective cost matters
*independently* of tempo because it drives three things tempo cannot see: **efficiency**
(points per effective gem — the strategy model's core "is this a good deal" lever),
**token economy** (total gems you must spend / discard pressure), and **contestability**
(a cheap-effective high-value card is one the opponent can also afford soon). Base
printed cost also remains in the existing per-card block (`cost/7`), but that's
incidental — the signal that matters is the post-reduction cost.

## Candidate-card set (which cards get the rich block)

15 slots, in fixed order so indexing is stable:
- **12 board slots** (buyable by both players → full me+opp blocks).
- **3 of my own reserved slots** (buyable by me only → opp-block zeroed).

Opponent blind reserves are NOT candidates (hidden identity; `determinize()` handles
them). My reserved are always known to me.

## Per-slot valuation block (17 floats/slot)

For candidate card `ci` in a slot (all-zero if slot empty). `me = s.turn`, `opp = 1-me`.
`bon_me = s.bonuses[me]`, `tok_me = s.tokens[me]`, etc. `bcol = E.BONUS[ci]`.

### ME side (12 floats)
| # | feature | formula | norm |
|---|---------|---------|------|
| 1-5 | **effective cost** per color | `max(0, COST[ci][i] - bon_me[i])` for i in 0..4 | `/7` |
| 6 | **gems-to-collect** (tempo raw) | `sum_i max(0, COST[ci][i] - bon_me[i] - tok_me[i])` | `/10` |
| 7 | **gold needed** | `E._gold_needed(COST[ci], tok_me, bon_me)` | `/5` |
| 8 | **turns-to-afford** (tempo) | see formula below | `/6`, cap 1 |
| 9 | **affordable now** | `1.0` if `gold_needed <= tok_me[5]` else `0.0` | — |
| 10 | **my noble progress** | noble-deficit this bonus reduces (below) | 0..1 |
| 11 | **victory closeness if bought** | `min(1, (points_me + PTS[ci] + noble_gain) / 15)` | 0..1 |
| 12 | **engine value (me)** | cross-card scalar (below) | `/3`, cap 1 |

### OPP side (5 floats) — denial / contest signals (zero for my-reserved slots)
| # | feature | formula | norm |
|---|---------|---------|------|
| 13 | **opp gold needed** | `E._gold_needed(COST[ci], tok_opp, bon_opp)` | `/5` |
| 14 | **opp affordable now** | opp could buy it next turn (key reserve/denial trigger) | — |
| 15 | **opp noble progress** | same as #10 with `bon_opp` | 0..1 |
| 16 | **opp victory closeness if bought** | same as #11 with opp totals | 0..1 |
| 17 | **engine value (opp)** | same as #12 with `bon_opp` | `/3`, cap 1 |

`17 × 15 slots = 255 new floats.`

### Formula details

**turns-to-afford (#8).** Let `d[i] = max(0, COST[ci][i] - bon_me[i] - tok_me[i])`,
`D = sum(d)`, `net = max(0, D - tok_me[5])` (gold covers any color). A take grabs up to
3 different colors, or 2 of one color (bank≥4). Estimate:
```
turns_est = max( ceil(net / 3), max_i ceil(d[i] / 2) )
```
A signal, not an oracle — it distinguishes "1 gem of 1 color away" from "needs 4 red,
collecting ~1/turn." Directly attacks the over-reserve / weak-tempo problem.

**noble progress (#10).** For each visible noble `ni` (`s.nobles`), if its requirement
in color `bcol` is still unmet for this player (`NOBLE_REQ[ni][bcol] > bon[bcol]`), this
card's +1 bonus advances it. Score:
```
np = sum over visible nobles of [ (NOBLE_REQ[ni][bcol] > bon[bcol]) * (closeness_ni) ]
closeness_ni = 1 - deficit_ni / total_ni     # how near that noble already is
```
normalized by number of nobles. Captures user factors 3+4 (progress AND closeness) in
one scalar, and #15 does the same for the opponent (factors 5+6).

**engine value (#12) — THE cross-card factor (user factors 10/11).** Buying `ci` grants
a permanent +1 `bcol` bonus. Value = discount it gives every *other* card that still needs
`bcol` — the visible board cards **and** the player's own **reserved** cards (committed
targets you intend to buy, so a bonus advancing one is real engine value) — weighted by
each card's worth and by how `bcol`-hungry it is, **plus** a deck-wide term for the cards
not yet revealed:
```
ev = 0
for cj in the 12 board cards, cj != ci, present:
    needs = max(0, COST[cj][bcol] - bon_me[bcol])      # does cj still need this color?
    if needs > 0:
        w_value    = PTS[cj]/5 + 0.2                    # high-point cards weigh more (+floor)
        w_scarcity = COST[cj][bcol] / max(1, sum(COST[cj]))   # cj is bcol-heavy
        ev += w_value * w_scarcity
for cj in my reserved cards, cj != ci:                 # committed targets count too
    needs = max(0, COST[cj][bcol] - bon_me[bcol])
    if needs > 0:
        ev += RESERVED_ENGINE_W * (PTS[cj]/5 + 0.2) * (COST[cj][bcol] / max(1, sum(COST[cj])))
ev += DECK_COLOR_DEMAND[bcol] * 0.5     # precomputed: bcol share of remaining deck costs
```
`RESERVED_ENGINE_W = 1.05` — a reserved card counts a hair MORE than one board card (a
commitment premium), not a pile that dominates the board. **Net-feature note:** the
encoder's me-side engine value (#12) must include this reserved-card contribution so the
feature matches the heuristic's `valuation.engine_value`; the opp-side engine value (#17)
stays board-only (opponent blind reserves are hidden). Validated as a *correctness* fix
(a bonus toward a card you reserved genuinely IS engine value); if it dents win rate the
cause is reserving bad cards — a reserve-*decision* problem, not a valuation flaw, fixed by
the reserve gates + end-game denial below, not by ignoring reserves.
This is the term an MLP cannot assemble from a flat vector (it requires reasoning across
all board cards at once). `DECK_COLOR_DEMAND` is computed once per `encode()` from
`s.decks` (the permanent-bonus-applies-to-future-cards insight). **We deliberately do
NOT stage-weight `ev`** — the net learns to discount engine value late-game from the
existing point/final-trigger features.

**The principled definition (the *why* behind the formula above).** A bonus is worth
exactly: **(the number of future cards you will actually buy that the discount applies
to) × (those cards' value).** Every property of engine value falls out of this one
statement:
- **It decays with game stage** because at the end you will buy almost no more cards, so
  the discount lands on nothing → ~0 value; early, many future buys → high value. (This
  is why a *free* 0-point card can be worthless late — see the heuristic's buy-vs-gem
  gate: a card discounting <=1 other card is worth no more than a single token.)
- **It rises when the board shows high-value, same-color-heavy L2/L3 cards**, because
  those are the cards you *intend* to buy, so the discount will actually be realized on
  them — captured by `w_value × w_scarcity`.
The formula above is the static proxy (visible board + a crude deck term + the net's
stage discounting). The **sharp** version is "expected future discounted purchases ×
value", which only a searching agent can evaluate (it sees how many cards it really buys
downstream). HEURISTIC NOTE: four 1-ply refinements toward this sharp form (reachability
term, cost-discounting, end-game stage-decay, buy-vs-gem gate) were A/B'd and all came
back neutral-to-negative — the greedy bot's static engine value is *saturated*; only the
net can exploit the sharper signal. Keep this definition as the engine-value feature's
north star for the retrain.

**reachability — the COMPLEMENT of engine value (incoming build-path support).** Engine
value asks "how much does buying `ci` help me afford *other* cards" (outgoing). Reach-
ability asks the reverse: "how much do the *other board cards* help me afford `ci`"
(incoming). It exists because an expensive card with a steep single-color cost is only a
realistic target if the board offers a path to build that color — otherwise it is a
**mirage** the bot chases/reserves but never buys (the diagnostic found **78% of the
heuristic's reserves go unused**, almost all steep L3s). Defined for a card with a steep
single-color need only:
```
reach = 0
for c in 0..4 where COST[ci][c] - bon_me[c] >= REACH_STEEP (=4):   # steep colors only
    for cj in the 12 board cards, cj != ci:
        if LEVEL[cj] < LEVEL[ci] and BONUS[cj] == c:               # lower-level, same color
            reach += PTS[cj]/5 + 0.3                               # high-value support weighs more
```
0 for any card with no steep single-color cost (those are reachable by normal spread
gem-taking and need no path). This is the **"is this target actually reachable from the
board"** half of the strategy model's backward-planning (the engine-value half is the
"which L1s advance my targets" direction). Like engine value, it is a cross-card
interaction an MLP cannot easily derive — a genuine feature, not a re-weighting.

**Single-color tempo realism (refines turns-to-afford #8).** The bank holds only 4 of a
color and depletes (and the opponent competes), so you cannot sustain take-2-same on one
color. Model a single-color deficit as ~1 turn for the first 2, then 1/turn: a
7-of-one-color card is ~6 turns, not the naive `ceil(7/2)=4`. Without this the tempo
penalty under-rates how far steep cards are, so the bot over-values mirages. (Heuristic
result of reachability + this refinement: see the deployed tuning lineage in
`heuristic.py`.)

## Heuristic structural-campaign findings → net-feature guidance (June 2026)

A 1-ply greedy A/B campaign on the v4 heuristic (committed in `heuristic.py`) tested five
structural ideas on **fresh paired seeds** vs the A/B/C/C2 greedy mix. **Read these
results as net-feature guidance through one caveat that flips the usual intuition:**

> **The 1-ply A/B is a WEAK test for a net feature.** It only measures whether a greedy
> argmax bot uses the signal better — not whether a *searching* net (with a co-evolving
> league) can exploit it. A feature that is neutral-or-negative at 1-ply can still be
> valuable for the net, because search + diverse opponents teach uses a greedy policy
> never demonstrates. Same logic as "self-play is blind to denial the opponent never
> threatens": the cure is to *give the net the feature*, not to omit it.

| idea | 1-ply A/B result | net-feature verdict |
|------|------------------|---------------------|
| **noble-completion VP** (the +3 a buy claims) | **+0.024, z=2.05 — WIN** | **Include, crisply.** Helped even greedy → unambiguous. Expose the discrete noble-claim VP per candidate as its own float (today it's only folded into victory-closeness #11); the net benefits from the sharp scalar — add `noble_gain/3` per me/opp side. `valuation.noble_completion_pts()` already computes it. |
| **tempo** (turns-to-afford #8) | multiplicative time-discount reshape = wash | **Keep the RAW feature.** Wash means the *greedy* use is saturated; the net learns racing/tempo through lookahead. Do NOT pre-bake a tempo discount into the feature — hand it raw turns-to-afford and let search weight it. |
| **opponent-contest / denial** (opp proximity × opp VP) | wash at 1-ply (confirmed at 2000 games) | **Keep — this is precisely a "documented blind spot" feature.** Greedy denial rarely pays, so 1-ply *cannot* show its value; the opp block (#13–17) + "Opponent threat/plan" addition give the net the raw material to learn denial **with** search + league. The 1-ply wash is the expected, non-disqualifying result. |
| **backward-planning** (target-focused engine value) | **hurt** (−0.04 sig as add-on; −0.38 as replacement) | **At most an ADDITIVE feature, never a valuation override.** The collapse when it *replaced* `engine_value` proved the broad engine_value is load-bearing. The "incoming" half (reachability) is already a feature; an "outgoing target-focus" float is low-priority (it hurt even additively at 1-ply) — defer unless the net shows a specific gap. |
| **end-game defense** (secure-win + 1-turn overtake/win denial) | **+0.048, z=+8.09 — BIGGEST WIN** (positive vs all of A/B/C/C2; diagnostic cut "won 15 first but lost" 1.8%→1.0%) | **Add NO new feature — it is SEARCH.** A lookahead behavior fully representable by features already planned here: opp affordable-now (#14) + opp victory-closeness (#16) + the final-trigger / seat-parity globals + noble-completion (`noble_gain/3`). Keep the final-round signal SHARP (flag + seat-parity bit) so the net can tell "does my 15 actually end the game." It is the *positive-result* sibling of the "Opponent threat/plan" blind-spot feature. See the dedicated subsection below. |

**Takeaway:** the campaign's *negative* 1-ply results are not vetoes on features — they
confirm the features encode signal the *greedy* policy can't use, which is exactly where a
searching net has headroom. The one place the heuristic result is a direct feature
instruction: **noble-completion** earned an explicit crisp scalar (`noble_gain/3`).

### End-game defense (June 2026) — analytic 1-turn win / denial (a WIN, and a SEARCH behavior)

A fifth structural idea, added after a playtest where the bot **handed back a winnable
game**: it grabbed its 15th point as *first* player, then the opponent took a final turn
and overtook. The engine's final-round rule (`engine._finish_turn`): a player reaching 15
sets `final_trigger`; the game ends only when, after the turn flips, `s.turn <=
final_trigger`. In 2p that means **seat 0 (first player) reaching 15 grants the opponent
one final turn** (they can reach 16+, or tie at 15 and win the **fewest-cards** tiebreak),
while **seat 1 reaching 15 ends the game immediately** (a secure win). The bot ignored this
and treated any winning buy as a win.

The fix (`USE_ENDGAME_DEFENSE`, all analytic — *no simulation*, 1 turn ahead for both
sides; `affordable_now` is exact, so there is zero estimation error):
- `_opp_best_buy(s, opp)` — the opponent's best single buy **next turn** over board +
  their own reserved cards they can afford **now**, by `PTS + noble_completion_pts`;
  returns its board slot (deniable) or −1 (their reserved → not deniable).
- `_secure_win(...)` — reaching `p_win` actually wins iff seat 1 / already on the final
  turn, **or** the opponent's best buy can't overtake on `(points, −cards)`.
- behavior: take a winning buy only if `_secure_win`; else **deny** the opponent's
  overtaking card (reserve it, else buy it) and win securely next turn; if undeniable
  (their own reserved, or no legal reserve/buy) grab 15 and hope. Separately, when the bot
  **can't** win this turn but the opponent can win on theirs via a *board* card, deny it.

**Result — the LARGEST measured structural win of the campaign** (bigger than
noble-completion's +0.024, and unlike denial's *wash*). Two validations:
- **A/B vs the full A/B/C/C2 mix, 2000 fresh paired seeds, OFF→ON: +0.0480, z=+8.09**
  (122 seeds better / 25 worse) — overall 0.732 → 0.780, and positive against **every**
  opponent (A +0.059, B +0.039, C +0.032, C2 +0.062). It generalizes because the
  secure-win check stops the bot "winning into a first-player loss" against any racer, not
  just one.
- **Diagnostic**, bot as FIRST player (seat 0) vs C2, 800 games, OFF→ON: win rate
  **0.759 → 0.797 (+0.038)**, and the exact failure it targets — "reached 15 first but
  LOST" — fell **1.8% → 1.0%** (14→8 games), confirming the gain comes from the mechanism
  it was designed for, not a side effect.

**Net-feature verdict — give the raw signal crisply; this is SEARCH, not a new feature.**
Unlike the other rows, end-game defense adds **no new feature** — it is a lookahead
behavior a searching net produces for free, and it is *fully representable by features
already planned here*: **opp affordable-now (#14)** and **opp victory-closeness-if-bought
(#16)** are the overtake signal; the **final-round / seat-parity globals** (`final_trigger`
flag + side-to-move, already in state) are the secure-vs-insecure distinction;
**noble-completion** (`noble_gain/3`, the crisp scalar above) makes a win-*via-noble*
visible to the same check. Two consequences for the retrain:
1. It is the *positive-result* sibling of the **"Opponent threat/plan"** blind-spot
   feature (Anti-ceiling section): denial was a 1-ply *wash* because greedy denial rarely
   pays, but the secure-win/overtake distinction is exploitable **even greedily** (+0.038)
   — strong evidence the opp-block + threat features are load-bearing, not speculative.
2. Make the final-round signal **sharp**: keep the `final_trigger` flag AND a seat-parity
   bit so the net can compute "does my 15 actually end the game" without having to infer it
   — the heuristic needed exactly that distinction to stop throwing first-player wins.

### Cost / tempo-accuracy campaign (June 2026) — one WIN (W_COST), the rest saturated

A second wave of structural A/Bs, all on the corrected-tta base. **The headline: a card's
total *cost* is a real, missing signal; making the tempo *estimate* more accurate is not.**

- **`W_COST` — SHIPPED (the win).** A cheapness discount for **0-point cards only**:
  `card_value /= (1 + 0.4 * total_effective_cost)`. Rationale: `efficiency = pts/(cost+1)`
  is 0 for point-less cards, so cost is invisible there and two same-bonus 0-pt cards tie
  regardless of price (engine/noble key only on bonus *color*); this prices the cheaper one
  higher (same engine benefit for less invested → more leftover gems). Validated **+0.028,
  z=+2.87** vs all-off over 2000 paired seeds; "W_COST + W_SPREAD combined" was no better
  than W_COST alone. **Net guidance:** expose **`total_effective_cost` per candidate** (and
  it already underlies `efficiency`) — the net needs the raw cost, not just points-per-cost,
  because for 0-point engine cards the *level* of investment is the whole signal.
- **Tested and REJECTED** (all default-off, stripped from the heuristic; kept here so we
  don't relitigate):
  | idea | result | why |
  |------|--------|-----|
  | **W_SPREAD** (L1 cost-concentration discount) | +0.039 @1000 → **−0.002 @2000 (wash)** | the 1000-seed gain was regression-to-the-mean noise; `cost_concentration` survives only as a *net* scalar candidate |
  | **cap-aware take** (avoid overflowing the 10-cap) | **−0.0145 (hurt)** | the "take-then-discard" churn is cosmetic; banking the extra gem + choosing what to keep beats the tidy discard |
  | **reserve-for-gold** (reserve a 1-gold-short target for the wild) | +0.0005 (inert) | the trigger almost never fires |
  | **noble-contention** (boost a card whose noble the opp also races) | +0.010 @1000 → −0.004 @1000 (wash) | denial is a documented 1-ply blind spot; a *net* feature, not a greedy win |
  | **TTA_PAIR_ONCE** (take-2-same needs bank≥4 → pair a color once) | **−0.026, z=−1.86 (hurt)** | *correct* (4-of-a-color is really 3 turns) but the slightly-optimistic tta keeps the bot usefully aggressive; accuracy here costs more than the error did |
  | **engine-value tta-decay** (discount engine value by turns-away) | +0.005 (wash) | consistent positive *lean* but never significant — a sharper net signal, not a greedy win |

**The load-bearing meta-finding (do NOT relitigate):** every tempo/reachability *accuracy*
refinement washed or hurt for the greedy bot — and `cap-aware`/`pair-once` actively **hurt**
because they make it more *pessimistic*, and the mildly-optimistic tempo estimate keeps it
aggressively pursuing cards (which beats caution). This is the saturation thesis in sharp
form: **for the 1-ply policy, value/scoring signals (end-game defense, W_COST) win; tempo
accuracy does not.** These accuracy refinements are exactly the sharper signals a *searching*
net can exploit where a greedy argmax can't — so they belong in the feature set, not as
greedy levers. (Mirage note: a planned `unreachable_by_taking` check generalizes the hard
`≥5-single-color` mirage to "affordable within the 10-hold cap + gold budget, on *effective*
cost" — same class; expected to help the net more than greedy H.)

## Global additions (6 floats)

| feature | formula | norm |
|---------|---------|------|
| **est. turns remaining** (stage) | `(15 - max(points_me, points_opp))` scaled, 0 if final_trigger set | `/15`, cap 1 |
| **board color demand vs my bonuses** (5) | per color: `sum over board cards of max(0, COST[c][i]-bon_me[i])` | `/20`, cap 1 |

The stage float makes the opening↔endgame shift crisp (the net can read "lots of turns
left → engine value matters" vs "near end → only points matter"). Board-color-demand
gives the diminishing-returns-on-owned-color signal: a color the board no longer
demands is a weak bonus target.

## New total

```
305 (existing, unchanged) + 255 (per-slot ×15) + 6 (global) ≈ 566 features
```
First MLP layer grows 305→566 inputs (~+134k params on a 512-wide layer; net is ~600k →
~730k). Trains fine on the 4050; numpy inference cost negligible.

## Implementation notes

- All new computation lives in `features.encode()`. Precompute per-`encode` once:
  `DECK_COLOR_DEMAND[6]` from `s.decks`, and the board-demand vector — then reuse across
  the 15 slots so it stays O(cards), not O(cards²)-with-recompute.
- `net.py`: bump the input dim constant (or read `features.N_FEATURES`); everything
  downstream is unchanged.
- `infer_np.py` / `export.py`: no logic change — they read `N_FEATURES` and weight
  shapes from the net, so the larger first layer flows through automatically.
- **Perspective:** all me/opp blocks are already side-to-move relative (existing
  convention). Keep it. Opponent blind-reserve identity stays hidden (only my reserved
  get the rich block; opp's hidden reserves contribute nothing here).

## Branch / rollout procedure (from CLAUDE.md)

1. Finish the v3 run; record iter-300 best net strength (arena vs B/C2).
2. Copy `checkpoints_v3/` → `checkpoints_v3_backup/`.
3. Implement this spec in `features.py` (+ input-dim bump). Update `test_az_actions.py`
   feature tests for the new `N_FEATURES` and add unit tests for each new formula
   (effective cost, turns-to-afford monotonicity, engine value > 0 when a same-color
   board card exists, opp-block zero on my-reserved slots).
4. Fresh run in `checkpoints_v4_features/` — **no `--resume`** (new input dim).
5. Arena gate: ship only if v4 best ≥0.70 vs B and C2 AND beats the v3 best head-to-head.
   If worse, delete the branch and `--resume` from `checkpoints_v3_backup/`.

## Open knobs (decide at implementation, not now)

- **Explicit efficiency / value-density feature** per candidate card: `points / (total
  effective cost + 1)`, and likely a noble-inclusive variant `(points + expected noble
  pts) / (effective cost + 1)`. Rationale: the strategy model treats points-per-gem as
  the core "good deal" lever, and that's a *ratio* — ReLU MLPs approximate division
  poorly, so the net may not derive it cleanly from effective cost (#1-5) + points alone.
  Falls under the same "expensive for the MLP to compute" doctrine as engine value. ~1-2
  floats/slot. Lean toward including it.
- Whether to also oversample early-game positions in the replay buffer (the other half
  of the weak-opening fix — keeps true value targets, just trains openings more). Cheap
  to add; orthogonal to features.
- Optional richer **league opponent** built on this same valuation as a heuristic — not
  shipped as a player (static eval caps ~0.65) but a tougher sparring partner that
  punishes bad reserves/weak openings harder than C2.

## Anti-ceiling design — why v3 plateaued and how v4 avoids it

**What a ceiling is NOT:** "a self-play net can't exceed its opponents." That's false —
AlphaZero reached superhuman play from random self-play with *no external opponents*,
because the opponent (itself) co-evolves: better net -> better games -> better targets ->
better net. The loop creates its own richness; it is not bounded by a fixed reference.

**What actually caps progress (the precise diagnosis of v3):**
1. **A *fixed external* opponent creates a local ceiling.** The eps-curriculum pins the
   opponent at the C2/A/B heuristics. Once the net matches them there is no gradient past
   "just beats the heuristic" -> gate scores flatline ~0.5. This is specific to fixed
   opponents, NOT to self-play in general.
2. **Exploration / equilibrium collapse**, not a richness bound. Shared-net self-play
   (which we use) can tunnel into one strategy or a degenerate equilibrium (documented
   0-0 and single-strategy collapses) and stop generating novelty. Fixable with
   exploration noise + asymmetric (frozen past-self) opponents.
3. **Search depth caps target *quality*, not reachable strategy.** More sims = cleaner
   policy/value targets, but cannot help once the explored strategy space has collapsed
   (why the v3 sims bumps 512->768->1024 did nothing).
4. **Features can *expand* reachable strategy, not just exploit a fixed space.** A
   strategy the net cannot represent can never be explored into — so richer features
   enlarge the reachable space. (Earlier framing that "features only use richness" was
   overstated.)

Compounding all of this in v3: the metric we watched (curriculum p / self-gate) was
*internal* and rose while real strength stayed flat — the documented misleading-metric
failure. The fix below makes the climb *self-improving* (co-evolving opponents), keeps
exploration alive (anti-collapse), and judges progress by an *external* yardstick.

### Feature additions that target known blind spots (ceilings form where the net is blind)
- **Reserve opportunity-cost** scalar per card: `(denial value + gold flexibility) −
  (tempo lost)`, derived from opp-affordable + turns-to-afford. Over-reserving is the
  observed weakness; make the *cost* of reserving explicit instead of inferred. ~1 float.
- **Opponent threat/plan**, not just opponent state: the opponent's best card by
  efficiency + their turns-to-afford it, so "they're one turn from a 5-pt card" becomes a
  perceivable, blockable threat. Denial is a documented self-play blind spot precisely
  because it was never representable. ~2 floats. **Concrete evidence it's load-bearing:**
  the heuristic's end-game defense (above) computes exactly this — the opponent's best
  next-turn buy — and turning it on is a measured +0.038 win rate as first player vs C2.
  The general (any-turn) version is the same signal one move earlier.
- **Future-proof the input dimension — reserve 16 zero-padded input slots now.** Later
  features fill those slots WITHOUT changing `N_FEATURES`, so the first-layer weight shape
  is identical and a future feature add can **warm-start/fine-tune from the existing
  checkpoint instead of a cold start.** Costs ~8k dead params now (those columns are 0 →
  no gradient → harmless); saves a full from-scratch retrain later.

## Training run spec (v4) — concrete settings to avoid the v3 problems

1. **Arena-vs-C2 as the north-star, logged every ~10 iters — NOT curriculum p.** Run a
   40-60 game arena probe vs C2 *and* vs the v3 best net periodically; log it. All
   decisions (plateau? ship? stop?) key off this external ground-truth number, not the
   internal gate. Single most important process fix — it catches "internal metric rising
   while real strength is flat" early (the exact trap that cost the v3 endgame). C2 here
   is a *yardstick*, not the strategy to climb toward.
2. **Co-evolving league as the primary climb, not a fixed heuristic.** Make frozen
   past-AZ checkpoints the main opponents (AlphaZero's actual mechanism — the opponent
   improves with the net, so there is no fixed ceiling). Keep heuristics A/B/C2 + the
   richer v4-valuation heuristic in the mix as *diversity/anti-blind-spot* sparring (they
   punish over-reserving / weak openings C2 ignores), but the strength gradient comes
   from beating ever-stronger past selves.
3. **Fixed high sims from iter 0 — no ramping.** Ramping (128->768) made early iters
   distill weak policy targets the net later had to unlearn. Start v4 at the final sims
   (>=512, likely 768) so every target is clean from the start.
4. **Keep exploration high** (Dirichlet eps ~0.35, temp-moves ~20) — the anti-collapse
   lever. v4 features let the net *represent* board-conditional plans, but it still must
   *see* both resolve; features without exploration just tunnel faster.
5. **Plateau-response ladder, in this order:** if arena-vs-C2 is flat for K iters ->
   (a) more exploration, (b) more/stronger opponents (deeper league pool), (c) more sims,
   (d) bigger net. Capacity LAST (capacity before data/search-quality just overfits).
   Prevents the reactive sims-bump thrashing we just did.

## Build sequencing — heuristic-first (agreed)

Build the v4 heuristic bot *before* the AZ retrain. This is not a detour: the heuristic
and the net's feature encoder share the same valuation core, so step 1 is also the first
half of the feature work — with a usable, testable artifact at the midpoint.

**Why heuristic-first:**
- **Shared code, built once:** `valuation.py` (the per-card/seat scalars) is imported by
  *both* the heuristic (`card_value` + `choose_move`) and `features.py` (packs the same
  scalars into the net input). Build once, use twice.
- **Cheap correctness test of the whole v4 design:** if the valuation is sound, a greedy
  bot using it should beat or match C2. If it can't, the model has a flaw — found in an
  afternoon instead of after a multi-day training run. This is the de-risk gate.
- **The anti-blind-spot sparring partner** the training spec already calls for (punishes
  over-reserving / weak openings C2 ignores).

**Critical caveat (ties to the anti-ceiling section):** the heuristic is a *diversity +
yardstick* opponent, NOT the primary climb. A fixed opponent gives no gradient once
matched (the v3 ceiling). Primary climb = co-evolving past-AZ selves; the heuristic is a
*league slice* + the external arena yardstick. "Train against it as one ingredient" ≠
"train against it as the goal."

**Risk to avoid:** don't let the heuristic's factor-combination *weights* become a tuning
rabbit hole — weight-tuning is the documented saturated path (~0.65 ceiling). Hand-set
weights to "clearly competent," run one arena check vs C2/B, stop. We want behavioral
*diversity* (reserves well, opens well), not a perfectly tuned static eval.

**Steps:**
1. `valuation.py` — shared scalar core: `effective_cost`, `total_effective_cost`,
   `gems_to_collect`, `gold_needed`, `affordable_now`, `turns_to_afford`,
   `noble_progress`, `engine_value` (cross-card + deck-demand term), `efficiency`,
   `victory_closeness`. Pure Python on `engine.State`; a `Valuation` context precomputes
   state-wide aggregates (deck color demand) once. **(current step)**
2. Heuristic bot on the core: `card_value()` (hand-set weighted combo) +
   `choose_action()`:
   - **Buy** the highest-value affordable card; always take a winning buy (reaches 15) or
     a noble-completing buy; otherwise buy only if its value is within `BUY_FRACTION` of
     the best (possibly unaffordable) target — don't waste a turn on a weak card when a
     much better one is reachable.
   - **Reserve — disciplined, because modeling the *counter* to over-reserving is the
     point.** Strictness rises as slots fill, and the opening is protected:
     - value threshold *escalates with slots already used*: `RESERVE_BASE +
       n_reserved * RESERVE_STEP` (0 used → a high-value card qualifies; the **last slot**
       demands an extremely-high one);
     - reserve only on a **big value-gap to the next-best card** (a unique opportunity)
       OR an **imminent opponent buy** (denial) — and only when the card is *unaffordable
       now* (if you can just buy it, don't reserve it);
     - **opening tempo cap:** at most one reserve while `s.ply < OPENING_PLY` (~first 4
       turns each) — early tempo builds the engine, not reserves.
   - **Take gems** that best cover the color needs of the top target cards (weighted by
     value × per-color deficit), else a generically useful take-3.
3. **Validation gate:** arena the heuristic vs C2/B. Competent (>= ~C2) -> proceed; weak
   -> fix the valuation before any training. A *behavioral* check too: confirm it does
   NOT over-reserve (it should rarely hold >1 reserve early) — that discipline is what
   makes it a useful anti-blind-spot sparring partner.
4. `features.py` on the same module (+ 16 spare zero-padded slots) -> fresh v4 AZ retrain
   with the heuristic as a league slice and the arena-vs-C2 north-star probe.
