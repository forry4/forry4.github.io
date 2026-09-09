# Orbit attention training foundation

This optional offline environment uses PyTorch and NumPy. It is separate from
the production requirements; the normal web/backend test suite does not import
PyTorch. Tested locally with PyTorch 2.11.0+cu128, CUDA and NumPy 2.4.6.

From the repository root, using the existing training virtual environment:

```powershell
.venv/Scripts/python.exe -m pytest games/orbit/ai/tests -q -n 0 -p no:cacheprovider --basetemp=.pytest-attention-new-run
.venv/Scripts/python.exe -m games.orbit.tools.attention_smoke --output .orbit-attention-new-run --steps 8
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

`train_batch` uses weighted binary cross entropy on terminal outcomes, finite
target/gradient checks and gradient clipping. The checkpoint includes model,
vocabulary/rules/config, AdamW state, step, metadata and Torch CPU/CUDA RNG state.
The caller is responsible for trajectory sampling state; the smoke sampler is
deterministic from its step. Full campaign checkpoints will also need dataset
manifest, sampler cursor, seed partitions and scheduling state.

Tests verify batch padding invariance, real parameter updates, exact continuation
of the next CPU update after checkpoint restoration, and rejection of invalid
targets before parameter mutation. GPU smoke checks checkpoint prediction parity.

Next gates: native observation extraction; compact entity/history representation;
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
