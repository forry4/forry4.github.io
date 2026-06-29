//! Variant-S Splendor search core, ported from `games/spender/ai/az/` (Python).
//!
//! Goal: maximize sims/second of variant S's determinized PUCT search by running it as native
//! Rust (offline self-play/gates) and WASM (in the player's browser). Rule/eval parity with the
//! Python reference is validated by differential + tolerance tests (see `tests/`).
//!
//! Color order matches the engine everywhere: white=0, blue=1, green=2, red=3, black=4, gold=5.
//! Card ids are global ints: 0..39 = L1, 40..69 = L2, 70..89 = L3. 2-player only; seats 0 and 1.

pub mod actions;
pub mod attn;
pub mod cards;
pub mod endgame;
pub mod feats;
pub mod engine;
pub mod heuristic;
pub mod mcts;
pub mod rng;
pub mod turns;
mod turns_table;
pub mod v_state;
pub mod valuenet;
pub mod valuation;
pub mod vsearch;

#[cfg(target_arch = "wasm32")]
pub mod wasm;
