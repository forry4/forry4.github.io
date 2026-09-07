# Orbit simulator — Phase 1 mechanical core

A typed native simulation core for Orbit's 90-card base game. The live Python
engine remains authoritative. The generated data is a transcription shared with
Python; transitions and decision ownership are independently implemented in Rust.
The offline Python package in `games/orbit/ai/` contains the Phase 2/3 search,
belief, arena and training harness. This Rust crate remains the mechanical
simulator and future WASM transition boundary; browser bot serving is still a
later phase.

## Run the gates

From the repository root (Cargo must be on PATH):

```sh
python -m games.orbit.tools.export_native --check
cargo test --locked --release --manifest-path rust-cores/orbit-core/Cargo.toml
python -m games.orbit.tools.native_parity --games 64
cargo check --locked --target wasm32-unknown-unknown --lib --manifest-path rust-cores/orbit-core/Cargo.toml
```

Use the repository Python virtual environment for pytest:

```sh
python -m pytest games/orbit/tests -n 0 -q
```

`rust-orbit.yml` runs the Rust tests, generated-reference freshness check, WASM
compilation and Python/native differential gate. The ordinary Python CI discovers
the AI tests through the existing Orbit test directory; no optional-test skips.
After a deliberate rules change regenerate using `export_native` without `--check`.

## Contracts

- `State`: privileged compact mechanical state. Two array-indexed seats, fixed
  planet/faction arrays, numeric card IDs. Seat 0 is the initial first player;
  Python's shuffled `order` maps IDs onto these seats. Names and prose logs are
  omitted. Do not pass this type or its JSON to a policy.
- `State::observation(seat)`: explicit allowlist matching Python
  `games.orbit.ai.state.observation`. The opposing hand stays hidden even at game
  end, and the opposing pending queue never enters the observation. Whole legal
  action dictionaries are the action identities; `choose` is polymorphic.
- `State::apply`: validates membership in legal moves, then resolves until the
  next real choice or turn boundary. Pending ownership can change during a turn.
  Invalid actions do not mutate state or consume chance. Trusted valid states are
  required; this is an offline library, not an untrusted network endpoint.
- `Chance`: separate seeded native RNG or strict shuffled-pile tape. Python and
  Rust use different RNG algorithms. Differential tests supply complete shuffled
  piles, check their inventories, and reject missing or unused chance events.
- Python `Session`: privileged offline archive plus separate policy input for
  each seat. Per-seat histories retain observation diffs, own private actions and
  public card plays/mulligan counts. History survives display-log eviction and
  JSON restore. Archive restore rejects a rules/schema mismatch.
- `sample_hidden`: a conservation-correct **current-observation prior**. It is
  not a posterior conditioned on the entire observed history. Phase 2 must add
  sequential belief tracking before claiming information-set search correctness.

The rules fingerprint includes normalized engine, effects, card, board and BGA
reference sources. Artifacts must carry that fingerprint plus the observation
schema version. Keep raw BGA evidence out of self-play training datasets.

## Evidence, 2026-09-05

- 11,955 matching decision transitions, including both seats' legal moves and
  observations; 64 full Python-generated games span all eight boards.
- Targeted cases exercise every card program (three contexts each), every
  technology level/side, every bonus type, all victory routes for both seats,
  opponent bonus ownership, row rewards, and both reshuffle types. 331 shuffles
  agree. An intentional one-credit discrepancy is detected by the same bridge.
- Native conservation soak: 128 full games in Rust tests. A separate 1,000-game
  random benchmark completed 177,311 decisions without hitting its cap.
- Initial native throughput: about 179k decisions/s including one state clone
  per decision on this laptop. This excludes observation serialization, neural
  inference and tree search; it is not a browser or strength measurement.
- WASM target compilation passes. Browser ABI/worker integration and real browser
  performance verification belong to Phase 5.

These gates establish Python/native agreement. They do **not** prove the Python
rules match every BGA situation. The user authorized Phase 1 after verification;
the existing BGA audits document their observational coverage and limitations.

Run the repeatable throughput probe separately:

```sh
cargo run --locked --release --manifest-path rust-cores/orbit-core/Cargo.toml --bin bench -- 1000
```

The benchmark's 2,000-decision cap is reported as censored, never scored a draw.
The `bridge` JSONL binary is a diagnostic tool, not a fast training transport.

The complete campaign is in `games/orbit/AI_PLAN.md`. Next: promotion gates,
native/WASM search profiling and browser serving. No model is promoted by the
offline tools automatically.
