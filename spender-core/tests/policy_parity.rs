//! Policy-tree parity: heuristic3.choose_action (greedy H3, deterministic), exact match vs Python.
//! Fixtures from `tools/gen_policy_fixtures.py`.

mod common;

use common::Dump;
use serde::Deserialize;
use spender_core::heuristic;

#[derive(Deserialize)]
struct Case {
    state: Dump,
    seat: usize,
    action: usize,
}

#[test]
fn policy_matches_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/policy_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_policy_fixtures.py"));
    let cases: Vec<Case> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!cases.is_empty(), "no fixtures");

    let mut mism = 0usize;
    for (i, c) in cases.iter().enumerate() {
        let s = c.state.to_state();
        let got = heuristic::choose_action(&s, c.seat);
        if got != c.action {
            if mism < 8 {
                eprintln!("MISMATCH #{i}: phase={} got {} want {}", s.phase, got, c.action);
            }
            mism += 1;
        }
    }
    assert_eq!(mism, 0, "{mism}/{} policy mismatches", cases.len());
    eprintln!("policy parity OK: {} cases", cases.len());
}
