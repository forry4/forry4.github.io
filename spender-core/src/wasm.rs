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

/// ROOT-PARALLEL piece: run a determinized search bounded by `budget_ms` OR `max_sims` (whichever
/// comes first) and return the ROOT VISIT COUNTS (length N_ACTIONS=70). Each worker calls this with a
/// distinct seed; the main thread SUMS the vectors across workers and argmaxes — standard root
/// parallelization (no shared memory). The `max_sims` cap bounds the per-worker tree size (≈ one node
/// per sim) so a fast device can't build a multi-hundred-MB tree (and finishes snappily). `max_sims=0`
/// = no cap. Empty vec on a parse error (the caller drops that worker's contribution).
#[wasm_bindgen]
pub fn search_visits_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> Vec<i32> {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    vsearch::root_visits_until(&s, seat, &mut rng, |n| {
        n < cap && (n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms)
    })
}

// ─── Variant N: learned value leaf (embedded weights) ─────────────────────────
#[derive(Deserialize)]
struct NModel {
    dims: Vec<usize>,
    w: Vec<Vec<f32>>,
    b: Vec<Vec<f32>>,
    mu: Vec<f32>,
    sd: Vec<f32>,
}
/// N's value net, embedded at build time (the verified learned leaf).
static N_MODEL_JSON: &str = include_str!("n_model.json");

fn build_n_net() -> crate::valuenet::StandardizedMlp {
    let m: NModel = serde_json::from_str(N_MODEL_JSON).expect("embedded n_model.json");
    crate::valuenet::StandardizedMlp::new(
        crate::valuenet::Mlp::from_parts(m.dims, m.w, m.b),
        m.mu,
        m.sd,
    )
}

/// Variant N root-parallel search: identical to `search_visits_timed` but uses the LEARNED value as
/// the MCTS leaf (+ the H3 prior). The net is parsed once per call (once per move per worker —
/// negligible vs the thousands of sims it then runs). Same SUM-then-argmax aggregation as S.
#[wasm_bindgen]
pub fn search_visits_n_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> Vec<i32> {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let s = dump.into_state();
    let net = build_n_net();
    let leaf = |st: &State, sd: usize| -> f64 {
        let raw: Vec<f32> = crate::feats::features(st, sd).iter().map(|&x| x as f32).collect();
        net.forward_raw(&raw) as f64
    };
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    vsearch::root_visits_until_leaf(
        &s,
        seat,
        &mut rng,
        |n| n < cap && (n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms),
        &leaf,
    )
}

#[derive(serde::Serialize)]
struct NFull {
    visits: Vec<i32>,
    value: f64,
    q: Vec<Option<f64>>,
}

/// Variant N search returning visits + the searched POSITION VALUE + per-edge Q — for the WWSD
/// overlay's eval display (the visits-only `search_visits_n_timed` is enough to PICK a move but
/// carries no eval). JSON: `{"visits":[..70..],"value":<f64 in [-1,1], side-to-move>,"q":[..70..]}`
/// where `q[a]` is null for an unvisited action. `{"error":...}` on a parse failure. Single-threaded
/// (no worker aggregation): the friend's CPU runs the whole budget on the userscript's main thread.
#[wasm_bindgen]
pub fn search_n_full_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let net = build_n_net();
    let leaf = |st: &State, sd: usize| -> f64 {
        let raw: Vec<f32> = crate::feats::features(st, sd).iter().map(|&x| x as f32).collect();
        net.forward_raw(&raw) as f64
    };
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    let (n, w) = vsearch::root_nw_until_leaf(
        &s,
        seat,
        &mut rng,
        |i| i < cap && (i % 64 != 0 || (js_sys::Date::now() - start) < budget_ms),
        &leaf,
    );
    let tot: i32 = n.iter().sum();
    let value = if tot > 0 { w.iter().sum::<f64>() / tot as f64 } else { 0.0 };
    let q: Vec<Option<f64>> = (0..n.len())
        .map(|a| if n[a] > 0 { Some(w[a] / n[a] as f64) } else { None })
        .collect();
    serde_json::to_string(&NFull { visits: n, value, q })
        .unwrap_or_else(|_| "{\"error\":\"ser\"}".to_string())
}

/// ENDGAME REFINEMENT (#1): given the aggregate PUCT action (argmax of the summed worker visits), run
/// the exact endgame solver on the TRUE state and return the (possibly overridden) move as dict-move
/// JSON. Runs ONCE per decision on the main thread (via one worker), after visit aggregation — cheap,
/// and a no-op outside endgame positions (returns the PUCT move's dict-move unchanged). `{"error":...}`
/// on a parse failure (caller falls back to the unrefined move / server AI).
#[wasm_bindgen]
pub fn endgame_refine_move(state_json: &str, seat: usize, puct_action: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let a = crate::endgame::refine(&s, seat, puct_action, &mut rng);
    crate::actions::action_to_move_json(&s, a)
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
