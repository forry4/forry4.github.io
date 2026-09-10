# Orbit AI campaign

Agreed 2026-09-05. Status: **Phases 1–5 prototype foundations implemented;
neural strength campaign authorized 2026-09-08 and now starting**. The current
campaign has a heuristic information-set PUCT baseline, a versioned 128-wide
policy/value guide, paired all-board arenas, sequential particle beliefs, and
an outcome-only population trainer. Phase 4 has a sealed-pool promotion
reporter with paired confidence intervals, holdout checks, regression gates and
correctness/information/timing checks. Phase 5 now has the versioned browser
worker boundary, live seat-local histories, reconnect-safe turn budgets,
whole-payload redaction and validated server fallback. No Phase 4 learned
champion has been promoted; the shipped Hard asset is an observation-only
effect-aware policy that remains replaceable by a gated champion.

The 2026-09-08 Hard v2 serving policy scores each public Agent effect program,
capture tempo, column discounts and pending choices. In a fresh 512-game arena
against the incumbent Hard v1 ranker, it scored 386–126 (75.39%) across all
eight technology boards with seat-swapped common-random-number pairs.

Delivered: typed Rust simulator, generated source fingerprint, per-decision
Python/native state/legal-move/observation parity, strict shuffle tapes,
seat-local offline histories and restore, a current-observation hidden-state
prior, CI gates, information-set PUCT, sequential particles, a 128-wide guide,
paired arenas and population training. 11,955 transitions and 331 shuffles
matched across targeted effect/boundary cases and 64 complete games on all
boards. Native tests and WASM compilation passed. See
`rust-cores/orbit-core/README.md` for commands and limits.

Phase 2 is implemented offline. The current sampler is intentionally not an
exact Bayesian posterior: sequential conditioning is represented by a finite
`HistoryBelief` particle population, with hard public-card constraints and
optional audited action likelihoods. Live history persistence and browser bot
integration are now in Phase 5.

**2026-09-06 implementation note:** Phase 2 lives in `ai/search.py`,
`ai/belief.py`, and `ai/neural.py`. `InformationSetSearch` uses PUCT over
observation-plus-public-trace information states, samples hidden hands/decks
from a sequential `HistoryBelief`, and gives opponent nodes a policy that sees
only that opponent's simulated observation/history. `SearchConfig` records the
equal-time budget knobs; `Decision.stats` are the Phase 3 policy targets. The
dependency-free guide has a fixed observation/action encoder plus a short
seat-local recurrent trace, a 128-wide shared trunk, policy head, value head,
JSON shape checks and terminal-outcome SGD.
`action_score` remains an audited one-ply diagnostic; tree expansions use its
allocation-free public prior so the Python harness can measure real simulations
within a turn budget.

**2026-09-06 Phase 3 implementation note:** `ai/selfplay.py` records JSONL
episodes with fingerprints, board sides, per-seat observations and search visit
targets. `run_arena` uses common-random-number paired games with assignments
swapped and reports pair confidence intervals, per-board scores, censored games,
and the exact mirror test. `ai/league.py` trains a tabular guide and the neural
guide from completed episodes only, retains typed historical members, and samples
opponents with the 50% empirical-game-theoretic / 25% diverse / 25% exploiter
mixture (renormalizing unavailable buckets). `tools/ai_campaign.py` exposes
`arena`, `bootstrap`, `train-neural`, `cycle`, and `gate`; all artifacts carry
the rules fingerprint. `ai/promotion.py` keeps development and sealed
confirmation pools in separate namespaces, balances board and opponent-family
weights, resamples complete CRN pairs for intervals, and reports every
matrix/cycle before an explicit promote/reject/inconclusive decision. A gate
does not wire a candidate into serving; Phase 5 is the serving boundary and
does not promote a candidate.

**2026-09-07 Phase 4 implementation note:** `ai/promotion.py` is the offline
promotion arbiter. It records reproducible pool namespaces, accepts a training
episode/manifest holdout, and runs the candidate/incumbent matrix against
named opponent families over all eight boards. Candidate deltas are bootstrapped
from aligned complete CRN pairs (including board/family/opponent regression
intervals); censored pairs remain explicitly censored. The gate also reruns
mirror/correctness and hidden-world invariance checks, validates rules/schema
metadata, and requires an external WASM timing manifest with a worker profile
before it can report `promote`. The CLI can emit a JSON artifact and optionally
return a failing process status, but it never changes the live bot.

## Objective and constraints

### Authorized neural strength campaign (2026-09-08)

This extends the prototype phases below. Their implementation status does not
mean a trained neural search exists in production. The objective is the strongest
demonstrated broad-opponent bot within five seconds of computation per WHOLE
turn, including pending choices. No optimality or unexploitable-play claim.
Local first on the RTX 4050 laptop; price cloud scaling only after measuring a
CPU self-play or GPU learning bottleneck. Paid compute requires a priced proposal.

1. Freeze Hard v2 and independent training/development/sealed seed namespaces.
   Port information-set PUCT and sequential beliefs into Rust, shared by native
   self-play, WASM and the eventual server worker. Require Python/Rust rules,
   observation, legal-action and outcome parity first. Profile native and real
   browser inference/search before committing training volumes or dates.
2. Audit and implement the feature contract described below. Start with a
   two-block attention encoder, width 64, four heads, FFN 128; compare a pooled
   token MLP on identical information, and width 96 only with timing headroom.
   The first milestone is terminal-outcome value training inside search with
   existing priors. Preserve actual decision ownership through pending chains;
   detect immediate victories and never flip value merely because an action ran.
3. Train in PyTorch using streamed replay, resumable optimizer/RNG state, whole
   game/seed-family splits, and three independent seeds for finalists. Bootstrap
   completed games from Hard v2, heuristic search and diverse exploratory bots.
   Weight games so long episodes and pending chains cannot dominate training.
   Add auxiliary observable future capture/technology/bonus progress and remaining
   turns, with censored labels masked; terminal outcomes remain the objective.
   Auxiliary heads are not hand-weighted terms in search value.
4. Cycle self-play, training and development arenas with equal board/seat coverage.
   Retain the 50% empirical-game / 25% diverse / 25% exploiter league mixture,
   including frozen Hard v2 and historical/independent opponents. Start replay
   at 50% recent / 25% historical / 25% rare-win and difficult-choice coverage,
   recording sampling weights. Reserve opponent families for evaluation.
5. Add legal-action embeddings with separate main/pending scoring heads, trained
   on root visits. Define low-search target handling explicitly. Keep learned
   priors only after equal-time gains over value-only search. Try selective
   higher-budget teacher games and observation-only reanalysis before simply
   increasing model size; outcomes anchor any search-value bootstrapping ablation.
6. Export float inference with PyTorch/native/WASM parity, then test int8 linear
   weights with float accumulation/normalization. Quantization-aware training is
   conditional on measured degradation. Version weights, encoder, rules, search
   and memory together. Benchmark 1/2/4 workers within the existing core clamp;
   preserve the 3s main + 2s follow-up starting allocation and reconnect budget.
   Native fallback uses the same model/search outside ROOM_LOCK. Hard v2 remains
   the emergency fallback and rollback artifact until the full promotion gate.
7. Screen at 128 pairs; confirm frozen candidates at 512 fresh pairs, balanced
   over eight boards, with a predeclared procedure for expansion to 2,048 pairs.
   Require >=75% observed score against frozen Hard v2 and paired 95% interval
   excluding 50%, broad-opponent improvement, existing five-percentage-point
   regression gates, exact 0.5000 mirror sanity, and no unresolved censoring.
   Retire opened confirmation pools. Later champions retain the Hard v2 threshold
   and demonstrate improvement over the incumbent, not 75% against every successor.
   Gate the actual exported WASM artifact at equal time with actual worker shape,
   including constrained devices, cold loads, long chains and deadline compliance.
8. After three unsuccessful promotion cycles diagnose tactics, target quality,
   belief/history failures and opponent coverage. Test stronger teachers,
   counterstrategies and belief improvements according to the diagnosis. A
   regret-based belief-search pilot starts on enumerable subgames only if
   information-related counterstrategies persist. Record rejected experiments.

### Feature selection: rules coverage first, measured strength second

Trace every engine rule/effect input and classify whether it changes legality,
cost, effect outcome, victory, or the acting player's knowledge. Maintain this
coverage matrix against the observation contract; unknown new fields fail closed
until reviewed. Sampled hidden hands/decks, RNG, future outcomes, display logs,
and private opposing pending/history fields never enter the learner.

| Feature group | Required distinctions | Why retained initially |
|---|---|---|
| Own hand | Card ID, cost, faction, planet, multiplicity | Legal plays and effects |
| Tableau | Exact visible IDs, owner, planet, column order | Discounts, top targets, chains |
| Captures | Per-planet identities/counts, influence, temporary captured flags | All three immediate victory patterns |
| Technology | Both levels and all board sides | Cumulative effects and bonus races |
| Bonuses | Identities, positions, availability, public discard/counts | Different payouts must not collapse |
| Resources/leader | Amounts, owner and level | Costs, hand development and choices |
| Pending/actions | Owner, source, visible task/context and every legal payload | Dynamic multi-step action sets |
| Public cards/history | Discards/counts and structured seat-local events | Conservation, remembered reveals and beliefs |
| Turn | Phase, actor, mulligan status, turn count, terminal status | Decision interpretation and outcomes |

Start from complete compact observations rather than hand-authored strategic
scores. Card identities distinguish effects; mechanical attributes support
transfer across cards. Keep planet identity/adjacency and exact column order;
do not invent planet permutation symmetries. Preserve meaningful numeric
distinctions with non-clipping scaling in the tensor adapter. Encode unknowns
explicitly and never silently truncate cards, histories or legal choices.

The prototype loses bonus identity, clips resources, aggregates tableau cards,
hashes eight history events and compares numeric captured-this-turn indices to
planet names. Add collision regressions before training. The new semantic
contract is separate from the legacy model and serving ABI so existing artifacts
cannot silently acquire different feature meanings.

Run controlled named group ablations on matched data and multiple training seeds.
Report fresh equal-time wins, board/opponent breakdowns, tactical failures and
inference cost; prediction loss/importance are diagnostic only. Group omission
is a representation ablation, not proof the information is absent: legal moves
and history may reveal the same fact. Test auxiliary heads separately from input
features, and select their inclusion by downstream playing strength.

Implementation started: `ai/features.py` provides a strict, versioned semantic
input contract, structured history validation and group omissions. It is an
audit/reference representation, NOT yet the compact tensor encoder, trained
attention model or native search. Tests preserve distinctions the legacy guide
collapses and enforce the observation boundary. Next: implement the tensor
adapter and native feature parity, then benchmark model/search before training.

First audit: `python -m games.orbit.tools.audit_features --games 8 --seed 9100`
completed all eight games (one per board), 1,470 decisions, 17 pending task types,
and at most 631 semantic observation tokens. Found 18 distinct sets of legal
actions colliding in the legacy action encoder, including mulligan selections,
technology factions and bonus locations. This is random-play coverage evidence,
not a strength result or an exhaustive feature audit. History sizing is still
unmeasured; semantic tokens are not the eventual attention-token count.

Numeric adapter milestone: `ai/tensors.py` adds frozen/exportable vocabulary,
unclipped float32 numeric values, separate sequence indices, and explicit batch
and position masks. Unknown paths/categories, incompatible fingerprints and
inexact float32 values fail explicitly. Vocabulary fitting belongs exclusively
to training inputs (the parity harness fits a fixture vocabulary, not a model).
The Rust `tensors` module independently implements the numeric conversion.
`python -m games.orbit.tools.tensor_parity` matched 2,910 observations from eight
complete games exactly (127 path templates, 149 categorical strings, seed 9200).
This establishes SEMANTIC-TO-TENSOR parity only: Python still supplies semantic
tokens. Native observation extraction, full-history parity, compact card/state
pooling, attention inference and training remain to implement. The adapter is a
reference input interface, not proof of serving speed. The complete Orbit suite
passed 94 tests after this milestone, and native core tests also passed.

Attention model milestone: `ai/attention.py` now implements the planned
64-wide/two-block/four-head value network, masked variable-length inputs,
terminal-outcome updates and model/vocabulary/optimizer/Torch RNG checkpoints.
The optional tests live in `ai/tests` and require the training environment,
not the production dependencies. `ai/TRAINING.md` documents reproducible smoke
commands and the remaining native-inference, compact-pooling and full-training
gates. This model currently attends to all semantic tokens and has no history
memory, policy or auxiliary heads. The observation-only GPU smoke is a plumbing
test on random-game outcomes, not a learned champion or a promotion candidate.

### Current implementation status (2026-09-09)

- Tensor/model v2 groups semantic fields into card/action/state entities with
  learned nonlinear pooling before attention. Every semantic field still enters
  the model; this is an architectural candidate, not an established strength gain.
- Rust independently extracts observations and histories, encodes tensors and
  runs float attention. 2,942 observation/history views matched tensor outputs
  exactly; trained float predictions matched within 1e-4 (observed max <5e-7).
- Experimental WASM is built outside shipped assets. Headless Chromium's complete
  observation-to-value path measured 8.8ms median/16.8ms p95 with one worker;
  four workers handled 4x the work in similar wall time, with parity passing.
  This is inference calibration, not a full-turn or promotion measurement.
- Immutable per-game tensor batches are cached under a bounded memory budget,
  preserving sample order and update count. The small-run epoch fell from ~5.7s
  to ~1.7-2.2s. CPU cached/uncached updates match exactly; GPU reductions can have
  small floating-point variation. Native weight-lookup hoisting also preserves
  float parity. The direct vocabulary collector exactly matches the semantic
  reference and measured ~2.9x faster on a 16-game fixture.
- Native parallel baseline generation produced 1,536 games in 6.9s with zero
  censoring. Before use, 11,955 transitions/331 shuffles passed Python/Rust parity,
  and 144 sampled Hard v2 actions matched the Python ranker. Native RNG namespaces
  are explicit and separate from Python pools; these are not identical seeded games.
- First real baseline: 1,536 training games, 192 disjoint development games,
  Hard v2/exploratory v2/random opponents, 5 epochs, cached GPU batches. Final
  development Brier 0.2256 is diagnostic only; playing strength remains unknown.
- Search integration then found an input-distribution bug: actor-only training
  never included `pending.waiting`, while search evaluates the nonacting seat.
  Generation now records BOTH separately redacted observer views every decision;
  outcome labels use observer identity. Fresh `*-native-v2` pools are retraining.
  The old actor-only model is not a promotion candidate.
- NativeValueGuide plugs the native evaluator into the existing offline PUCT,
  retains heuristic priors and fingerprints the actual checkpoint. Unknown
  features fail explicitly. The development integration probe must pass before
  any strength assertion; no serving manifest or live bot has changed.

Performance is now a campaign requirement: profile preprocessing, data generation,
GPU update time, native/WASM inference and search separately. Keep mathematically
equivalent caching/layout/allocation improvements behind equivalence gates. Mixed
precision, bigger batches, changed architectures, reduced simulations/features
or changed targets require fresh equal-time strength comparisons. Do not trade
away information or search correctness to report higher throughput.

Build one bot with the strongest measured broad-opponent win rate, using fresh
counterstrategies to expose weaknesses. A league win is evidence, not proof of
unexploitability or optimal play.

- All eight base-game technology configurations receive equal coverage.
- Training uses generated bot games only. BGA games are correctness evidence,
  never policy/value training examples.
- Serve through browser WASM, desktop first with phones supported, within **3–5
  seconds of computation per entire turn**, including follow-up decisions.
- Local training: RTX 4050 Laptop, 6 GB VRAM; 12 logical CPU cores observed.
- No fixed campaign endpoint. Continue while fresh evaluations justify the work;
  diagnose three unsuccessful promotion cycles before extending the same recipe.
- Keep three explicit tiers: Easy (random), Normal (the original public
  ranker), and Hard (the effect-aware serving policy). No adaptive product.

## Phase 0 — verify the game before learning it

Verification against BGA Zenith precedes the Rust port and training. Check all
90 base cards, costs, factions, planets, 30 technology levels, eight bonus types
and their inventory, setup, information visibility, mulligans, reshuffles,
target restrictions, effect order, captures and immediate victory.

Use the existing BGA audits and source reference, and normalized replay
checkpoints when sufficient source data exists. Compare each observable decision
and effect, not only the final winner. Record each discrepancy as a focused
regression test. Do not infer missing hidden setup or report unobserved behavior
as verified. Do not use agreement between two copies of our engine as independent
BGA evidence.

**2026-09-05 authorization:** the user reports having verified that everything
seems to work and explicitly requests Phase 1. Proceed on that basis. The current
AGENTS.md also records zero contradictions in the card/effect/magnitude/technology
audits. These are bounded observations, not exhaustive rules proof: spectator
logs lack initial setup and hidden hands, so full BGA game replay remains limited.
Keep those limitations visible; new actual contradictions stop data generation
until resolved. No additional real-game harvesting is required for training.

Fingerprint engine and mechanical reference sources. Every future trajectory,
model and experiment records that fingerprint. A rules change requires fresh
validation and invalidates affected datasets/models; do not silently mix versions.

## Phase 1 — simulator and information foundations

1. Save this plan separately from the original game implementation PLAN.md.
2. Build a compact typed Rust state and full effect interpreter, using generated
   declarative data from Python. Python remains the live rules authority.
3. Build a native JSON bridge and deterministic parity runner. Compare all
   mechanical fields, both seats' legal actions, pending owner, and outcomes at
   every decision. Supply explicit shuffled piles rather than require identical
   Python/Rust RNG algorithms. Test chance consumption and conservation too.
4. Add targeted fixtures for all effect programs and boundary cases, plus complete
   generated games across all eight boards. Inject a mismatch to prove the gate
   can fail. Keep generated reference data synchronized with a check-only command.
5. Define an allowlisted observation contract and per-seat structured history,
   independent of the 300-entry display log. Only that seat's legal information
   enters its history; never include true hidden state or simulation RNG. Provide
   a serializable offline session to prove save/restore before live integration.
6. Add a feasible hidden-state sampler with card/bonus conservation. Distinguish
   a current-observation prior from a history-conditioned belief; do not advertise
   the former as the latter. Learned action-likelihood weighting is a later ablation.
7. Profile native transitions and cloning; add CI gates. No neural training or
   production bot replacement in this phase. Browser serving integration is Phase 5.

The preliminary random probe (32 games) found median eight legal actions and
108.5 turns, with a maximum 18 legal actions in that sample. These are initial
measurements, not bounds or estimates of strong-play game length.

## Phase 2 — algorithm comparison and baseline opposition

**Primary candidate: neural-guided information-set search.** Use PUCT for our
choices, grouping by our observation history. Sample feasible hidden worlds and
one frozen opponent policy per simulation trajectory. Opponent policies see only
their own simulated observations/history, never our actual hand. Future choices
may differ across worlds only after information distinguishing those worlds is
observed. Chance events are not player choices. Follow actual decision ownership,
including the opponent's decisions during our turn; no automatic sign flip per
action. Check victory immediately and resolve pending chains faithfully.

This is approximate improvement against a mixture, not safe equilibrium search.
Do not independently solve fully revealed worlds and label the average an
information-consistent strategy.

Initial model: shared card encoders, pooled hand features, ordered column features,
board/resources, recurrent observation memory, legal-action scorer, scalar outcome
head, 128-wide hidden representations. Preserve planet identity and adjacency;
arbitrary planet permutations are not valid symmetries. Compare larger attention
models only when browser inference profiling leaves adequate search headroom.

Baselines cover immediate capture/defense, concentrated racing, diverse-planet
racing, technology, leader/hand development, resource efficiency and disruption.
Keep different strategic pressures without hard-coding them into the learned
reward. The random bot remains a correctness baseline.

Compare heuristic information-set search, neural policy alone, and neural-guided
search at equal serving time, across independent training seeds. Retain the simpler
search if inference costs more strength than it adds.

Backups:

- Recurrent PPO without search if simulation/search-training throughput limits
  progress; compare under matched training resources and independent opponents.
- Regret-based learning/belief-state search, inspired by ReBeL/Student of Games,
  if persistent counterstrategies expose information-related weaknesses that the
  primary method cannot repair. First validate on enumerable Orbit subgames,
  then run a bounded full-game pilot. Do not inherit theoretical guarantees for
  an approximate implementation.

## Phase 3 — population self-play

Bootstrap from generated baseline/search games. Train policy on search-improved
action distributions and value on completed-game win/draw/loss. No resource,
technology, capture, or short-game reward shaping. Capped games are censored,
never silently labeled draws. Maintain exploration for mulligans and choices.

Retain historical champions, independent learners, strategic specialists and
successful exploiters based on distinct matchup behavior. Train against 50%
empirical game-theoretic league mixture, 25% uniformly sampled diverse retained
opponents, 25% current weakness-exposing opponents; redistribute unavailable
categories. Balance boards and seats. Train fresh exploiters against frozen
champions; a failed exploit search proves only that this attack failed.

Track code/rules/model/encoder versions, seeds, opponents, resources, censored
games and evaluation settings. Compare belief weighting by fresh-game strength,
not prediction accuracy. Separate tactical depth, value quality, belief error,
opponent diversity and inference overhead before changing one axis at a time.

## Phase 4 — promotion gates

Separate training, development and sealed confirmation pools. Hold out opponent
families/training runs as well as deal seeds. Once a confirmation weakness enters
training, replace that test. Report full matchup matrices and cycles, balanced
overall score, board/family groups and confidence intervals, not Elo alone.

- Paired deals with swapped agent assignments, retaining initial seat advantages.
- Equal board and opponent-family weights; actual serving worker arrangement.
- 128 paired matches for screening; 512 fresh pairs for confirmation, expanding
  to 2,048 if uncertain. Confidence calculations resample complete pairs.
- Require supported balanced-pool improvement, a positive incumbent matchup,
  no confirmed board/family regression greater than five percentage points,
  and all correctness/information/timing gates. Inconclusive candidates stay
  experimental. Native timing must be calibrated against actual WASM throughput.
- Re-run targeted tactics and fresh counterstrategy attacks for each proposed
  champion. Lower training loss or random-bot wins cannot promote a model.

## Phase 5 — browser serving

Versioned boundary:
`choose_move(observation, legal_moves, memory, remaining_turn_budget, seed)`.
Return an existing legal move, updated memory and development diagnostics.

Cap workers at `max(1, min(hardwareConcurrency - 1, 4))`. Budget five seconds per
turn, initially three for its main action and reserve the remainder for follow-ups.
Reuse matching search branches; use cached/policy-only actions when exhausted.
Waiting on the other player does not consume computation time. Reconnect must
retain remaining turn budget and discard stale search.

Integrate structured per-seat history with live persistence/redaction, including
legacy-save handling; do not reconstruct private histories from raw hidden state.
Use the existing armed request, position validation, watchdog and server fallback
pattern. Server validates all moves and runs fallback outside ROOM_LOCK. Retain
the strongest cheap validated fallback and difficulty memory via the shared lobby.

Test whole-payload redaction, hidden-world permutations, enumerable sampler
cases, Python/native/WASM parity, model export, total-turn timing, stale replies,
reconnect, failed workers and responsive browser play. Version model/WASM assets
together; preserve client compatibility and a rollback champion. Keep Easy,
Normal and Hard selectable in the create modal while only Hard uses the browser
serving boundary.

**2026-09-07 implementation note:** Orbit now has the versioned Python serving
contract, an optional Rust/wasm-bindgen export, and a module worker that loads a
rules-fingerprinted model manifest. The browser uses a capped root-parallel
pool and sends one validated decision at a time; a missing, stale, illegal or
slow reply falls back to the server ranker outside `ROOM_LOCK`. Per-seat
observation histories and the remaining five-second turn budget survive saves
and reconnects. The v2 manifest contains the validated card encoder and
effect-aware Hard policy; promotion remains an explicit Phase 4 decision, so a
future champion can replace the asset without changing the room protocol. The
deterministic asset is regenerated with
`python -m games.orbit.tools.export_serving`; the wasm-pack output beside it is
rebuilt from the same Rust source version.

### 2026-09-09 indexed features and performance follow-up

The v3 experiment preserves every audited v2 input and adds explicit categorical
card identity and neutral/self/opponent role embeddings. This tests a concrete
representation hypothesis: a numeric card ID and a seat index force the value
network to learn identity and ownership indirectly. Both adapters implement the
same mapping, and v2 checkpoints remain readable. Select features using controlled
ablations, held-out calibration, tactical fixtures and paired playing strength;
never infer strength from training loss alone.

On the same 1,536 training / 192 development games, the indexed epoch-4 model
reached development Brier 0.16871, compared with the non-indexed control's best
0.19764. Both checkpoints scored 10/16 against Hard v2 on the same fresh eight-board
paired development pool at 250 ms per whole turn. This scout establishes neither
an improvement between checkpoints nor a promotion. The indexed model passed
4,464 complete observation-to-native-value checks (maximum logit error 7.75e-6).
Tensor parity additionally covered 2,942 observations, including 32 history views.
The value model itself still omits history as an explicit ablation.

Performance work now includes CPU-side validation of CPU training labels,
exact observation-keyed leaf caching within each native search call, binary
lookup of sorted vocabulary entries, borrowed vocabulary/token encoding, and
reuse of identical positional transforms within a native evaluation. The
`benchmark_search` tool compares two binaries on fixed simulations and rejects
any change in moves, node counts or edge statistics. Retain timing scope and
cache-hit counts: small timing differences alone do not prove an optimization.

Fused FP32 AdamW remains opt-in. A matched five-epoch indexed run reached Brier
0.16707, but concurrent work confounded its wall-clock comparison and rounding
changes prevent claiming identical optimization trajectories. Measure isolated
throughput and multiple training seeds before adopting it as the default.
Experimental WASM artifacts stay outside the shipped assets. Full five-second
search, history-conditioned determinization, league self-play, auxiliary heads,
quantization and sealed promotion gates remain outstanding.

### 2026-09-09 leaf attribution and the serving-shape budget

The native development arena now reports the shared paired `ArenaResult`, so a
native probe carries pair scores, a paired bootstrap interval and the per-board
breakdown instead of a bare win count. Re-reading the earlier 16-game scouts
through it shows they established nothing: 0.625 with a 95% interval of
[0.500, 0.812] and 0.688 with [0.438, 0.938]. Folding the rows also fixed a
scoring error: a `winner` of `null` is the deck-exhaustion draw and had been
counted as a candidate loss in both seat-swapped games.

A `heuristic` sentinel checkpoint runs the identical search with no network,
which is the control the campaign lacked; without it a win over Hard v2 cannot
be attributed to the value model rather than to search. Six arms of 64 balanced
pairs each, all against Hard v2 on identical deals:

| leaf | condition | score | 95% interval |
|---|---|---|---|
| indexed v3 | 250 ms/turn | 0.648 | [0.570, 0.727] |
| heuristic | 250 ms/turn | 0.578 | [0.500, 0.656] |
| indexed v3 | 24 fixed simulations | 0.508 | [0.422, 0.586] |
| heuristic | 24 fixed simulations | 0.469 | [0.383, 0.555] |
| indexed v3 | 96 fixed simulations | 0.586 | [0.492, 0.672] |
| heuristic | 96 fixed simulations | 0.609 | [0.531, 0.688] |

Paired network-minus-heuristic differences on the same deals are +0.070
[-0.039, +0.180] at equal time, +0.039 [-0.063, +0.141] at 24 simulations and
-0.023 [-0.141, +0.094] at 96. Every interval spans zero and the sign changes
with simulation count, so **the indexed v3 value model has no measured advantage
over the free heuristic leaf**, while costing 18.3x more per simulation. Search
itself is the gain: both leaves beat Hard v2 given enough simulations. Equal-time
remains the ship criterion, but it cannot attribute a win, because the cheaper
leaf silently compensates with more simulations; report both regimes or neither.

Two harness faults surfaced from the same data. Fixed 96 simulations on every
decision (0.609) beat a timed arm averaging 383 (0.578), because the arena gave
each turn one pot and let the first decision drain it: every follow-up then ran
zero simulations and played the highest prior, which is Hard v2's own move. And
both fixed-24 arms sit at or below 0.5, so **a search under roughly 24
simulations is weaker than its own prior**. (Superseded for the heuristic leaf:
see 2026-09-10 below. Neither this rung nor the 96 one reproduces on the tree
that documents them, and at 328 pairs the 24-simulation heuristic search reads
0.550 [0.511, 0.588] -- above parity, not below it.) The arena now mirrors serving —
forced moves are played without search, per-decision allowance is
`min(remaining, main_action_ms | followup_ms)`, and `--workers` runs the
root-summed pool the browser actually serves, verified at exactly N x sims per
call and reproducible across runs.

At the serving shape (3.5 s/turn, 2100/1400, four workers) the heuristic leaf
reaches 18,874 simulations per decision, a 49x increase, and scored 0.750
[0.625, 0.875] on a 16-pair scout. A larger run on fresh deals was stopped early
at 32 balanced pairs and read **0.625 [0.500, 0.750]**; the scout was optimistic
and the honest estimate is the mid-to-high 0.6 range. This is a development
probe, not a promotion, and it is measured against an opponent the search models
exactly, since `serving::choose_move` is deterministic and is both the arena's
Hard v2 and the search's internal opponent model.

None of this is servable today. `wasm.rs` exports the Hard v2 ranker only;
`search::choose` takes a privileged `State` as its determinization template, and
Phase 5 forbids sending one to a browser. The observation already carries every
mechanical field except `agent_deck`, `bonus_deck` and the opponent hand, which
are exactly the pools `sample()` resamples, so an Expert tier needs
`State::from_observation` with a public-field parity test, a search wasm export,
the tier wired through both ends, and a rebuilt asset.

### 2026-09-09 the Expert tier: searching from an observation

Expert ships the heuristic-leaf PUCT search into the browser. The obstacle was
never the search: `wasm.rs` exported only the ranker, and `search::choose` takes
a privileged `State` as its determinization template, which Phase 5 forbids
sending to a browser. `State::from_observation` closes that gap. Every
mechanical field is public in the observation except the agent deck, the bonus
reserve and the opposing hand, and those are exactly the pools the search's own
determinizer already resamples, so the rebuilt world is ONE sample of the seat's
information set and the search resamples it per simulation. A test walks a real
game and checks every public field, both hand counts, the deck lengths, the
legal-move SET and card conservation, plus that permuting everything the seat
cannot see leaves the reconstruction unchanged.

Move ORDER cannot match and the test asserts sets: the observation sorts the
observer's own hand while the live state keeps draw order. Hand order is not
public, so the browser could never recover it, and the search sorts moves anyway.

A pending chain is REFUSED rather than guessed, because the observation redacts
the queue to its first task through a key whitelist; a search over an invented
continuation would be searching a game that does not exist. Expert therefore
searches its main action and RANKS its follow-ups, which is a real cost, not a
rounding error: only 20 of 75.9 decisions per game are searched, and at a fixed
96 simulations the reconstruction path scores 0.531 [0.453, 0.617] against the
privileged path's 0.609, a paired -0.078 [-0.188, +0.031].

Measured as shipped -- rebuilt worlds, ranked pending chains, 3.5 s per turn
split 2100/1400, four root-summed workers -- Expert scores **0.719 (23-9),
95% interval [0.5625, 0.875]** over 16 balanced pairs against Hard v2 at 8,350
simulations per searched decision. Two caveats travel with that number. The
browser is about 2.7x slower than native (measured: ~0.83 simulations per
millisecond in a headless worker against ~2.25 native), so a real player's
Expert searches roughly a third as much. And the opponent is one the search
models exactly, since `serving::choose_move` is deterministic and is both the
arena's Hard v2 and the search's internal opponent model.

Three harness faults had to be fixed before any of this could be measured
honestly, and each was worth more than the tuning it replaced: a `winner` of
`null` scored as a loss rather than a draw; the turn's first decision drained
the whole budget so every follow-up ran zero simulations and played the
opponent's own top move; and the browser pool aggregated by plurality VOTE while
the arena root-summed visits. The client now sums visits when a worker reports
them, so the shipped aggregation is the measured one, and Hard is unaffected
because a ranking worker reports none.

`npm run expert-search` is the artifact gate: it drives the committed wasm in a
real browser worker and requires a legal move, non-zero simulations inside the
budget, root visits to sum, and a refusal on pending chains. It found a real bug
in itself first -- two seats mulligan on turn 0 and shared a label, so a
label keyed lookup checked one position against another's legal list.

### Research-log audit: borrow mechanisms, preserve their conditions

Reviewed `docs/ai-research-log.md` Duel sessions July 22–30 and the actual
`duel-core/src/attn.rs` and `tools/train_attn*.py` implementations. Priority changes:

- Benchmark chunked dot products as an opt-in native/WASM build. Duel measured
  1.9x faster forward inference, but it reassociates FP32 sums. Orbit needs its own
  parity, tactical and equal-time gates. Scratch-buffer reuse comes after profiling;
  Duel measured only about 4% from that optimization in its July 22 workload.
- When policy priors arrive, compute them on first descent, not for unrevisited
  expansions. Duel's lazy-prior implementation saved 1.55x with unchanged decisions.
  The current Orbit value-only search cannot claim this saving.
- GPU-resident inputs are already used. Test larger, length-bucketed batches as a
  separate training recipe, not an equivalent optimization: batch size changes
  update counts and optimization dynamics. Keep whole-game/paired-seed holdouts.
- Before repeated neural self-play, run a no-learning self-gate and measure the
  teacher-versus-student gap. Reject a consistently negative improvement loop;
  more data and better Brier/AUC are not evidence of stronger play. Maintain
  current-checkpoint anchor data when fine-tuning. Policy/auxiliary gradients can
  damage the value trunk, so compare frozen-trunk and co-training explicitly.
- Audit the opponent model and sampling before harvesting large search datasets.
  Orbit currently searches against fixed Hard v2 replies. Test adversarial replies
  and current-observation sampling versus coherent independent-world trees; do not
  transfer Duel's near-perfect-information justification to Orbit's hidden hands.
- Test short rollout versus static leaves in Orbit's actual serving shape. The
  July 29/30 Duel result supersedes the older static-leaf claim: a 0.61 single-tree
  screen became 0.40 with four workers. Match independent trees, per-worker depth,
  move aggregation, and whole-turn timing. Weak-bot wins are only a competence floor;
  include near-peer checkpoints, fresh seeds, mirror controls and targeted tactics.

### 2026-09-10 the fixed-simulation ladder: an elbow at ~192, not a plateau

Seven heuristic-leaf rungs against Hard v2, **328 balanced pairs each** (4,592
games, 6.2 core-hours), all on the `development-native-search-v1` deals through
`summarise` and the shared paired bootstrap.

| fixed simulations | score | 95% interval | W-L-D | core-seconds | decisions/game |
|---|---|---|---|---|---|
| 24 | 0.550 | [0.511, 0.588] | 361-295-0 | 192 | 80.8 |
| 48 | 0.584 | [0.549, 0.619] | 383-273-0 | 473 | 83.6 |
| 96 | 0.648 | [0.613, 0.681] | 425-231-0 | 1,082 | 84.6 |
| 144 | 0.672 | [0.636, 0.709] | 441-215-0 | 1,743 | 86.4 |
| 192 | 0.688 | [0.651, 0.724] | 451-205-0 | 2,448 | 88.8 |
| 384 | 0.695 | [0.660, 0.730] | 456-200-0 | 5,237 | 89.5 |
| 768 | 0.704 | [0.669, 0.741] | 462-194-0 | 11,120 | 92.1 |

**The curve never plateaus.** It rises monotonically across the whole 32x range:
`768 - 24` is `+0.154 [+0.104, +0.206]`, and 768 (0.704) is above 384 (0.695) is
above 192 (0.688). Every rung clears parity, 24 included.

**What breaks at ~192 is the RATE, not the climb.** Two doublings below the elbow
(`48 -> 192`) buy `+0.104 [+0.055, +0.154]`; the two doublings above it
(`192 -> 768`) buy `+0.017 [-0.034, +0.066]`. The difference between those two
equal-width spans, paired on the same deals, is `+0.087 [+0.002, +0.175]` -- clear
of zero, but *only just*, and that margin is the honest strength of the claim.
Above the elbow each doubling costs ~2.1x compute for under a point of score:
192 -> 384 is +0.008 for +2,789 core-seconds, 384 -> 768 is +0.009 for +5,883.
So the elbow is a **cost-effectiveness** boundary, not a strength ceiling -- more
search still helps, it just stops being worth buying.

Only two adjacent steps are individually resolvable even at 328 pairs (`48 -> 96`
at `+0.064 [+0.017, +0.111]`, and nothing above it). Adjacent doublings are simply
smaller than what a paired arena of this width can see; the elbow is established
by comparing equal-width SPANS, not neighbours, which is the analysis that makes
the question answerable at affordable cost.

**Two earlier conclusions from this same ladder were wrong, and the failure mode is
the point.** A 64-pair version measured 192 -> 0.664, 384 -> 0.656, 768 -> 0.664 and
called it saturation. Both faults were in the arithmetic, not the engine:

- **The plateau's left edge was never measured.** Paired deltas were computed only
  among the three new rungs, so 192 became the plateau's start by construction. The
  96 rung was in the same table: `768 - 96` read `+0.008 [-0.117, +0.125]`, exactly
  as flat. The follow-up guess that the knee was therefore "at 96 or below" repeated
  the identical error on a different rung.
- **Nothing in that ladder was resolvable at all.** Paired per-pair differences have
  SD ~0.45, so 64 pairs resolves only +/-0.11, and EVERY rung-to-rung difference was
  smaller than that -- `768 - 24` included, at `+0.094 [-0.023, +0.203]`. Flat was
  the only reading 64 pairs could have produced.

The 64-pair run put 768 at 0.664; at 328 pairs 768 is 0.704 and even 192 alone is
0.688. The flat top was noise, and it happened to look exactly like the finding one
hopes for.

**The rule to carry: compute a paired arena's resolution BEFORE reading its rungs,
and size the run to the effect you intend to detect.** With per-pair SD ~0.45 the
pair count is `(1.96 * 0.45 / d)^2` -- about 88 pairs for +/-0.10, 328 for +/-0.05,
912 for +/-0.03, 2,040 for +/-0.02. A series of differences smaller than the
half-width is noise, and a FLAT such series is the shape noise takes. When the
effect of interest is smaller than any affordable half-width, compare wider spans
instead of neighbours rather than reporting the neighbours as zero.

## Research references

- ISMCTS: https://eprints.whiterose.ac.uk/id/eprint/75048/1/CowlingPowleyWhitehouse2012.pdf
- PSRO: https://arxiv.org/abs/1711.00832
- ReBeL: https://arxiv.org/abs/2007.13544
- Student of Games: https://arxiv.org/abs/2112.03178

These motivate candidates, not an assertion that any is strongest for Orbit.
