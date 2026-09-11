# Orbit attention training foundation

This optional offline environment uses PyTorch and NumPy. It is separate from
the production requirements; the normal web/backend test suite does not import
PyTorch. Tested locally with PyTorch 2.11.0+cu128, CUDA and NumPy 2.4.6.

From the repository root, using the existing training virtual environment:

```powershell
.venv/Scripts/python.exe -m pytest games/orbit/ai/tests -q -n 0 -p no:cacheprovider --basetemp=games/orbit/ai/runs/pytest-attention-new-run
.venv/Scripts/python.exe -m games.orbit.tools.attention_smoke --output games/orbit/ai/runs/attention-new-run --steps 8
```

Use a new output directory each time; the smoke command refuses to overwrite one.
Pass `--device cpu` for a CPU-only smoke. The default requires CUDA explicitly,
so a missing accelerator cannot silently change a timing report's meaning.

The smoke generates eight completed random games, four observation samples per
seat/game, and updates on two samples per seat from each board across eight
batches. It excludes censored games, uses terminal seat outcomes and records
the seed. The vocabulary is fitted on these smoke samples only. This is an
observation-only ablation: history is deliberately omitted. There is no held-out
evaluation, search, opponent league or promotion result in this command.

`attention.py` implements width 64, four heads, two pre-norm attention blocks,
FFN 128 and a scalar win logit. A learned summary token reads every semantic
token with padding masks. Sequence indices carry their array depth through a
small nonlinear position encoder. The model preserves variable token lengths;
v2 now pools fields through a nonlinear encoder into card/action/state entities
before attention. Recurrent history updates remain unimplemented.

The native float evaluator precomputes the deterministic position MLP for the
common card/move/column index range when a checkpoint loads, while retaining an
unbounded fallback for larger future indices. This changes no features or
search choices: a real 148-position parity pass stayed within 1.55e-6 logit
error, and a same-seed fixed-64 probe had identical winners, step counts and
evaluation counts. The CPU-native build reduced that probe from 163.9 s to
156.9 s. Native observation extraction now constructs the allowlisted public
projection directly; a parity walk matched the serializer and a fixed-64
one-game probe stayed at the same winner, 150 steps and 4,632 evaluations while
falling from 29.7 s to 28.4 s. Keep the portable browser/WASM path separate
from this offline build. Search reuses that post-move observation for the
nonterminal leaf instead of rebuilding it; four alternating probes had the
same canonical game hash and averaged another 1.046x speedup.
Internal rollouts also use a private apply path that skips a duplicate
legal-list build; the public engine API remains validating. Two canonical-hash
probes matched exactly and averaged another 1.013x speedup.

The leaf profiler attributes the remaining cost to the value path: about 78%
attention, 10% tensor conversion, 5% feature extraction and under 1% hidden
inventory sampling. Native search therefore caches the validated vocabulary
and card-ID map at model load and sends typed rows through a reusable,
variable-length attention workspace. A 5,594-position observation/native pass
kept maximum logit error below 3.70e-6; fixed-search moves, edge statistics and
node counts were identical with a 1.71x timing improvement at 32 simulations.
The observation-to-value bridge measured 1.46x end-to-end speedup at 1.91e-6
maximum error. WASM uses the same typed path. A separately gated chunked Q·K
kernel changed search statistics despite only ~1.10x extra speed, so it remains
rejected for the strength campaign.

The pooled-row cache reuses the exact affine/GELU result for repeated semantic
rows across leaves. It is keyed by all row inputs and a monotonic model-load tag
to prevent stale values after a browser checkpoint reload. The 5,594-position
parity walk and fixed-search probes stayed exact; measured speed was 1.04–1.07x
for search and 1.03x for the bridge. The cache is staged for a clean-boundary
campaign binary and still needs a browser/WASM timing check.

Fused FP32 AdamW is available as an opt-in training flag. An isolated 24-update
probe on one prepared batch measured 12.44 ms/update versus 20.07 ms/update for
regular AdamW (1.61x); the maximum parameter difference after the probe was
5.8e-4. It changes floating-point update order, so it needs a matched multi-seed
strength A/B before becoming the campaign default.

`train_batch` uses weighted binary cross entropy on terminal outcomes, finite
target/gradient checks and gradient clipping. The checkpoint includes model,
vocabulary/rules/config, AdamW state, step, metadata and Torch CPU/CUDA RNG state.
The caller is responsible for trajectory sampling state; the smoke sampler is
deterministic from its step. Full campaign checkpoints will also need dataset
manifest, sampler cursor, seed partitions and scheduling state.

Tests verify batch padding invariance, real parameter updates, exact continuation
of the next CPU update after checkpoint restoration, and rejection of invalid
targets before parameter mutation. GPU smoke checks checkpoint prediction parity.

Next gates: compact entity/history representation;
Rust float inference parity; real browser timing; streaming outcome trainer with
whole-game seed splits; observation-only value guide integration into audited
search. A lower smoke loss or fast CUDA forward pass is not playing strength.

## Native and outcome-training commands (2026-09-09)

The native extractor, tensor adapter, float model and an offline PUCT baseline
are now implemented. The PUCT sampler uses a current-observation prior; it does
not yet port the sequential history belief. Hard v2 is still the shipped bot.

```powershell
C:/Users/Forrest/.cargo/bin/cargo.exe build --release --locked --manifest-path rust-cores/orbit-core/Cargo.toml --bins
.venv/Scripts/python.exe -m games.orbit.tools.tensor_parity
.venv/Scripts/python.exe -m games.orbit.tools.native_value_data NEW_TRAIN_DIR --games 1536 --namespace train-native-v2
.venv/Scripts/python.exe -m games.orbit.tools.native_value_data NEW_DEV_DIR --games 192 --namespace development-native-v2
.venv/Scripts/python.exe -m games.orbit.tools.value_campaign train NEW_TRAIN_DIR NEW_DEV_DIR NEW_MODEL_DIR --epochs 5
.venv/Scripts/python.exe -m games.orbit.tools.native_search_arena CHECKPOINT.pt REPORT.json --pairs 8 --budget-ms 250
```

Use new directories; namespaces identify fixed pools, so re-running a namespace
does not create fresh holdout seeds. Native/Python generators use different RNGs
and explicitly different pools. Native v2 records both observer views at every
decision; actor-only v1 missed waiting states and cannot qualify for promotion.
Vocabulary is learned only from training observations; the direct collector is
tested against the semantic reference. Cached game batches are bounded to at
most 1GiB/one-quarter free VRAM (256MiB on CPU). The dataset shards remain the
source of truth and carry checksums. Resume validates the dataset fingerprints.

The native arena is currently a development probe against Hard v2. It does not
replace the sealed-pool promotion reporter, enforce browser worker timing, or
claim full-history beliefs. Full-turn budget accounting is retained per seat.
Unknown feature paths/categories are fatal diagnostic errors, not silent fallbacks.

Native float artifacts can also be tested in headless Chromium using
`export_neural_bench` and `webapp/test/orbit-neural-bench.mjs`. Build experimental
WASM into a separate local output directory; do not overwrite shipped assets.

Before rebuilding all native binaries, let arenas using those executables finish
or use a separate cargo target directory: Windows cannot replace a running EXE.
For a local CPU campaign, an isolated native-instruction build is safe and
usually faster; pass both resulting binaries to the league so the portable
browser/WASM build is untouched:

```powershell
$env:RUSTFLAGS='-C target-cpu=native'
C:/Users/Forrest/.cargo/bin/cargo.exe build --release --locked --features chunked-dot `
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native `
  --bin neural_arena --bin value_generate --bin bridge --bin policy_diff
```

⚠ **Rebuild `games/orbit/ai/runs/target-native` after ANY change to `rust-cores/orbit-core`,
and rebuild ALL FOUR binaries.** Every campaign tool prefers that directory when
it exists, so a stale copy silently runs the old search while the portable build
runs the new one. The failure is not an error: it is an arena that reads exactly
0.5000 with zero variance, because both arms are the same old code. That
signature — a perfect 0.5 where the two arms should differ — means a stale
binary, not a null result. It cost two wasted runs on 2026-09-11.

## Leaf parity (Python reference vs Rust port)

```powershell
python -m games.orbit.tools.leaf_parity --games 8
```

Walks real games and compares `rust-cores/orbit-core/src/search.rs::state_value`
against `games/orbit/ai/search.py::state_value` position by position; 2,728
positions currently match at a maximum absolute delta of **0.0**. This harness
exists because the original Rust port silently kept only the FIRST TERM of the
reference — capture progress, without the 1.4 weight or any of the influence,
technology, leader, bonus, economy or hand terms — and a leaf that drops terms
still returns a plausible number. Deliberately uses the PORTABLE build, since it
is checking the arithmetic that ships rather than a `target-cpu=native
--features chunked-dot` binary built to reassociate float reductions.

`games/orbit/tests/test_ai_leaf.py` pins the Python reference's sensitivity to
each term in CI, where no Rust binary exists.

## Is there anything to measure? (`policy_diff`)

```powershell
python -m games.orbit.tools.policy_diff <incumbent.pt> <candidate.pt> --games 8 --simulations 32
```

Reports how often two checkpoints choose a different move on a self-play
trajectory, in seconds rather than the hours an arena costs. Above
`--agreement-ceiling` (97%) the candidate is a no-op and the league skips its
arena. Use the SELF-PLAY number: against a random opponent the same pair of
checkpoints reads 77.9% agreement, because a random opponent manufactures
positions where most moves are obvious; in self-play — the distribution an arena
actually samples — they read 63.4%. The identity control (a checkpoint against
itself) must read exactly 100.0%.

## Resumable Expert league

The long strength campaign keeps the current Expert frozen, trains neural
learners against Expert/Hard/exploratory/random mixtures plus targeted
developer, denier and soft-tempo racer opponents. Each generation also records
a self-play anchor from its current parent. This follows the other games'
research findings: a generic self-play league can share a blind spot, a full
racer can create a fitness valley, and a fixed old anchor allows basin drift.
The native-v2 corpus remains a foundation anchor:

```powershell
.venv/Scripts/python.exe -m games.orbit.tools.neural_league --iterations 1
```

The state and logs are written under `games/orbit/ai/runs/neural-league/`. Re-running the
command resumes after completed generations; interrupted native datasets retain
verified shards and regenerate only missing jobs. Every parent and candidate first
passes a same-checkpoint mirror (a cheap 24-simulation exact control by default)
and a near-peer parent arena. The default fixed filter now uses one root tree
and concurrent game workers, with 32 simulations over 16 paired matches and
two pairs per technology board; it is deliberately a screen, not a strength
claim. Candidates below the fixed trigger skip timed
work. A candidate above it gets an eight-pair scout at the fast 250 ms proxy
budget (150 ms main action + 100 ms follow-up). Each proxy game keeps the
four-tree serving root ensemble, while independent paired games run concurrently
(`--proxy-game-workers`; three on a 12-thread host), so the native arena uses
the host instead of serializing complete games. Promising scouts are re-read on
fresh proxy rungs of 32, 128 and 512 pairs (`--confirm-ladder`); the first two
rungs are directional filters and only
the final 512-pair rung can promote statistically. The actual browser profile is
measured only by the rare 16-pair serving check after a passing 512-pair rung.
`--always-timed` restores timed proxy work for every candidate, while
`--serving-check-pairs 0` intentionally leaves promotion unconfirmed. A
candidate is only promotion ready after the proxy reaches both a 0.75 score and
a 0.75 paired-bootstrap lower bound with no censored games and the serving
check is complete and above its compatibility floor; the script records the
planned roster shift but does not alter serving assets. Use `--iterations N` for
a longer league, `--baseline-timed` to measure the initial proxy reference, and
keep the native arena executable idle before rebuilding it on Windows.

When more than one candidate clears the timed trigger, confirmation re-gates
the promising checkpoints in descending screen order on independent fresh
seeds. This avoids selecting a lucky in-loop winner, a failure mode seen in the
Spender and Castles of Crimson campaigns.

The fixed screen is a filter, not a strength claim. If a candidate clears
`--timed-trigger` (0.62 by default), the runner lazily measures the fast proxy
and only then considers confirmation. Reports retain board/family/seat
breakdowns, censored pairs, worker/budget profiles and the exact model
stride/weight/temperature controls. Intermediate confirmation rungs may stop a
clearly weak candidate, but their intervals are never a promotion result; the
final rung is a fixed sample rather than an optional stopping rule. Before
starting a long campaign, calibrate the proxy on identical paired deals:

```powershell
.venv/Scripts/python.exe -m games.orbit.tools.arena_calibrate `
  games/orbit/ai/runs/calibration `
  games/orbit/ai/runs/value-fit-indexed-v3/epoch-004.pt `
  games/orbit/ai/runs/neural-league-v2/g003/model/epoch-006.pt `
  --pairs 8 --budgets 250,500,1000 --workers 1,4,8,11 --game-workers auto
```

The calibration report is an ordering/throughput diagnostic. A score at one
budget is never numerically extrapolated into a score at another; only the
serving-shaped check can validate the final transfer.

New search shards also retain the root value on the acting seat's observation.
The league defaults to a gentle `--root-value-beta 0.25` blend with the
terminal result, following the measured value-bootstrap signal in the Spender
and Castles of Crimson campaigns. Set it to zero for the matched
outcome-only control; observer rows and the old foundation anchor always stay
terminal-labelled.
