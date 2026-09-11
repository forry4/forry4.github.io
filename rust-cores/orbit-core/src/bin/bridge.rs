//! Offline JSONL differential-test boundary. Never accepts production requests.
use orbit_core::{rules, Chance, State};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

fn run(v: Value) -> Result<Value, String> {
    let mut state: State = serde_json::from_value(v["state"].clone()).map_err(|e| e.to_string())?;
    state.validate()?;
    // Leaf-parity mode: evaluate BOTH seats' observations and return both leaf
    // evaluators. `tools/leaf_parity.py` holds the Rust state-value port to the
    // `ai/search.py::state_value` reference it was ported from; the capture-only
    // arm is returned alongside so the control the A/B uses is covered too.
    if v["leaf_only"].as_bool().unwrap_or(false) {
        let mut state_values = Vec::new();
        let mut capture_only = Vec::new();
        for seat in 0..2 {
            let observation = state.observation(seat);
            state_values.push(orbit_core::search::state_value(&observation));
            capture_only.push(orbit_core::search::capture_progress_only(&observation));
        }
        return Ok(json!({"rules": rules().rules, "state_value": state_values,
                         "capture_progress_only": capture_only}));
    }
    let legal_before = [state.legal_moves(0), state.legal_moves(1)];
    let tape: Vec<Vec<u16>> =
        serde_json::from_value(v["shuffles"].clone()).map_err(|e| e.to_string())?;
    let mut chance = Chance::scripted(tape);
    let seat = v["seat"].as_u64().ok_or("missing seat")? as usize;
    let applied = state.apply(seat, &v["move"], &mut chance);
    state.validate()?;
    if chance.remaining() != 0 {
        return Err("unused scripted shuffle".into());
    }
    Ok(
        json!({"rules":rules().rules,"ok":applied.is_ok(),"error":applied.err(),
        "before_moves":legal_before,"moves":[state.legal_moves(0),state.legal_moves(1)],
        "observations":[state.observation(0),state.observation(1)],
        "state":state,"shuffles_consumed":chance.consumed}),
    )
}

fn main() {
    let mut out = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let result = line
            .map_err(|e| e.to_string())
            .and_then(|s| serde_json::from_str(&s).map_err(|e| e.to_string()))
            .and_then(run);
        let value = result.unwrap_or_else(|e| json!({"bridge_error":e}));
        writeln!(out, "{value}").unwrap();
        out.flush().unwrap();
    }
}
