//! WASM entry points (Phase 2). Compiled only for `wasm32` (gated in lib.rs), so native builds and
//! `cargo test` never pull wasm-bindgen.
//!
//! `bench_move` builds the SAME deterministic mid-game position as the native `bench` bin and runs the
//! variant-S search for `sims` simulations, returning the chosen action index. JS times the call with
//! `performance.now()` → sims/second, compared to the native baseline + Render's logged ~380–870/move.
//!
//! `choose_action_for` is the real serving entry: it takes a compact-state JSON dump (the same shape the
//! cross-impl bridge uses) and returns the chosen action index. The action→move-dict bridge (actions.py)
//! is still unported; the browser glue will map the index for now or we port it in Phase 3.

use crate::engine::State;
use crate::rng::Rng;
use crate::vsearch;
use serde::Deserialize;
use wasm_bindgen::prelude::*;

/// Benchmark: run the search on a deterministic mid-game position; return the chosen action (JS times it).
#[wasm_bindgen]
pub fn bench_move(setup_seed: u64, setup_moves: u32, sims: usize, search_seed: u64) -> i32 {
    let pos = vsearch::demo_position(setup_seed, setup_moves);
    let mut rng = Rng::new(search_seed);
    vsearch::choose_action(&pos, pos.turn, sims, &mut rng) as i32
}

#[derive(Deserialize)]
struct Dump {
    bank: [i32; 6],
    tokens: [[i32; 6]; 2],
    bonuses: [[i32; 5]; 2],
    points: [i32; 2],
    purchased_n: [i32; 2],
    purchased: [Vec<i32>; 2],
    reserved: [Vec<i32>; 2],
    reserved_blind: [Vec<bool>; 2],
    nobles_won: [Vec<i32>; 2],
    board: [i32; 12],
    decks: [Vec<i32>; 3],
    nobles: [i32; 3],
    turn: usize,
    phase: u8,
    pending_nobles: Vec<usize>,
    final_trigger: i32,
    winner: i32,
    ply: i32,
    win_points: i32,
}

impl Dump {
    fn into_state(self) -> State {
        State {
            bank: self.bank, tokens: self.tokens, bonuses: self.bonuses, points: self.points,
            purchased_n: self.purchased_n, purchased: self.purchased, reserved: self.reserved,
            reserved_blind: self.reserved_blind, nobles_won: self.nobles_won, board: self.board,
            decks: self.decks, nobles: self.nobles, turn: self.turn, phase: self.phase,
            pending_nobles: self.pending_nobles, final_trigger: self.final_trigger,
            winner: self.winner, ply: self.ply, win_points: self.win_points,
        }
    }
}

/// Serving entry: search the given compact-state JSON for `seat` and return the chosen move as a
/// compact dict-move JSON string (the exact shape main.py's move handler accepts). `{"error":...}`
/// on a parse failure (the caller falls back to the server AI).
#[wasm_bindgen]
pub fn choose_move(state_json: &str, seat: usize, sims: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let a = vsearch::choose_action(&s, seat, sims, &mut rng);
    crate::actions::action_to_move_json(&s, a)
}

/// Time-budgeted serving entry: keep running simulations until `budget_ms` wall-clock has elapsed,
/// then pick the move. This makes the AI "think" for the full budget (far more sims than a fixed
/// count) instead of finishing in ~0.2s. `Date.now()` (valid in workers) is checked every 64 sims so
/// the JS-boundary overhead stays negligible.
#[wasm_bindgen]
pub fn choose_move_timed(state_json: &str, seat: usize, budget_ms: f64, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let a = vsearch::choose_action_until(&s, seat, &mut rng, |n| {
        n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms
    });
    crate::actions::action_to_move_json(&s, a)
}

/// ROOT-PARALLEL piece: run a time-budgeted determinized search and return the ROOT VISIT COUNTS
/// (length N_ACTIONS=70). Each worker calls this with a distinct seed; the main thread SUMS the
/// vectors across workers and argmaxes — standard root parallelization (no shared memory). Empty vec
/// on a parse error (the caller drops that worker's contribution).
#[wasm_bindgen]
pub fn search_visits_timed(state_json: &str, seat: usize, budget_ms: f64, seed: u64) -> Vec<i32> {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    vsearch::root_visits_until(&s, seat, &mut rng, |n| {
        n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms
    })
}

/// Convert the aggregate-winning action index to a dict-move JSON for the given state (the main thread
/// resolves it once, after summing visits across the worker pool). `{"error":...}` on a parse failure.
#[wasm_bindgen]
pub fn action_to_move_for(state_json: &str, action: usize) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    crate::actions::action_to_move_json(&s, action)
}
