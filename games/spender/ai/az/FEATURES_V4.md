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
a permanent +1 `bcol` bonus. Value = discount it gives every *other* visible card,
weighted by that card's worth and by how `bcol`-hungry it is, **plus** a deck-wide term
for the cards not yet revealed:
```
ev = 0
for cj in the 12 board cards, cj != ci, present:
    needs = max(0, COST[cj][bcol] - bon_me[bcol])      # does cj still need this color?
    if needs > 0:
        w_value    = PTS[cj]/5 + 0.2                    # high-point cards weigh more (+floor)
        w_scarcity = COST[cj][bcol] / max(1, sum(COST[cj]))   # cj is bcol-heavy
        ev += w_value * w_scarcity
ev += DECK_COLOR_DEMAND[bcol] * 0.5     # precomputed: bcol share of remaining deck costs
```
This is the term an MLP cannot assemble from a flat vector (it requires reasoning across
all board cards at once). `DECK_COLOR_DEMAND` is computed once per `encode()` from
`s.decks` (the permanent-bonus-applies-to-future-cards insight). **We deliberately do
NOT stage-weight `ev`** — the net learns to discount engine value late-game from the
existing point/final-trigger features.

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
  because it was never representable. ~2 floats.
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
