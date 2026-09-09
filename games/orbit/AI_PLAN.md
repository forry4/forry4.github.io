# Orbit AI campaign

Agreed 2026-09-05. Status: **Phases 1–5 implemented**. The current
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
- Keep one Hard tier plus the existing random bot. No separate adaptive product.

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
together; preserve client compatibility and a rollback champion.

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

## Research references

- ISMCTS: https://eprints.whiterose.ac.uk/id/eprint/75048/1/CowlingPowleyWhitehouse2012.pdf
- PSRO: https://arxiv.org/abs/1711.00832
- ReBeL: https://arxiv.org/abs/2007.13544
- Student of Games: https://arxiv.org/abs/2112.03178

These motivate candidates, not an assertion that any is strongest for Orbit.
