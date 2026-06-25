//! action_to_move parity: Rust action_to_move_json must byte-match Python's compact dict-move for
//! EVERY legal action over sampled states. Fixtures from `tools/gen_actionmove_fixtures.py`.

mod common;

use common::Dump;
use serde::Deserialize;
use spender_core::actions::action_to_move_json;
use std::collections::HashMap;

#[derive(Deserialize)]
struct Case {
    state: Dump,
    moves: HashMap<String, String>, // action index (as string) -> compact move json
}

#[test]
fn action_to_move_matches_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/actionmove_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_actionmove_fixtures.py"));
    let cases: Vec<Case> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!cases.is_empty());

    let mut n = 0usize;
    let mut mism = 0usize;
    for c in &cases {
        let s = c.state.to_state();
        for (a_str, want) in &c.moves {
            let a: usize = a_str.parse().unwrap();
            let got = action_to_move_json(&s, a);
            if &got != want {
                if mism < 8 {
                    eprintln!("MISMATCH a={a}: got {got}  want {want}");
                }
                mism += 1;
            }
            n += 1;
        }
    }
    assert_eq!(mism, 0, "{mism}/{n} move mismatches");
    eprintln!("action_to_move parity OK: {n} (state,action) moves");
}
