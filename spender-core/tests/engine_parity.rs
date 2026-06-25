//! Differential parity: replay Python-generated random games through the Rust engine and assert
//! both `legal_actions` and the full integer state match exactly after every move.
//!
//! Fixtures are produced by `tools/gen_engine_fixtures.py` (run it before this test).

mod common;

use common::Dump;
use serde::Deserialize;
use spender_core::engine;

#[derive(Deserialize)]
struct Step {
    legal: Vec<usize>,
    a: usize,
    after: Dump,
}

#[derive(Deserialize)]
struct Game {
    init: Dump,
    steps: Vec<Step>,
}

#[test]
fn engine_matches_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/engine_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_engine_fixtures.py"));
    let games: Vec<Game> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!games.is_empty(), "no fixtures");

    let (mut n_games, mut n_steps) = (0usize, 0usize);
    for (gi, game) in games.into_iter().enumerate() {
        let mut s = game.init.into_state();
        for (si, step) in game.steps.into_iter().enumerate() {
            // legal_actions parity (sorted-equal; order shouldn't matter to the search)
            let mut got = engine::legal_actions(&s);
            got.sort_unstable();
            assert_eq!(got, step.legal, "legal_actions mismatch game {gi} step {si}");
            // apply + full-state parity
            engine::apply(&mut s, step.a);
            let expected = step.after.into_state();
            assert_eq!(s, expected, "state mismatch game {gi} step {si} after action {}", step.a);
            n_steps += 1;
        }
        n_games += 1;
    }
    eprintln!("engine parity OK: {n_games} games, {n_steps} steps");
}
