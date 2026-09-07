//! wasm-bindgen exports for the Orbit browser serving worker.
//!
//! The exported functions deliberately take JSON policy inputs rather than a
//! privileged `State`. The worker and Python room validate the move against
//! the live engine; this module is an acceleration boundary, never an
//! authorization boundary.

use serde_json::{json, Value};
use wasm_bindgen::prelude::*;

use crate::serving;

fn parse_object(raw: &str, label: &str) -> Result<Value, String> {
    let value: Value = serde_json::from_str(raw).map_err(|err| format!("{label}: {err}"))?;
    if !value.is_object() {
        return Err(format!("{label} must be an object"));
    }
    Ok(value)
}

fn parse_array(raw: &str, label: &str) -> Result<Vec<Value>, String> {
    let value: Value = serde_json::from_str(raw).map_err(|err| format!("{label}: {err}"))?;
    value
        .as_array()
        .cloned()
        .ok_or_else(|| format!("{label} must be an array"))
}

/// Choose one action through the same versioned boundary as Python and JS.
#[wasm_bindgen]
pub fn orbit_choose_move_json(
    observation_json: &str,
    legal_moves_json: &str,
    memory_json: &str,
    remaining_turn_budget: f64,
    seed: u32,
) -> String {
    let result = (|| {
        let observation = parse_object(observation_json, "observation")?;
        let legal_moves = parse_array(legal_moves_json, "legal_moves")?;
        let memory: Value =
            serde_json::from_str(memory_json).map_err(|err| format!("memory: {err}"))?;
        Ok::<_, String>(serving::choose_move(
            &observation,
            &legal_moves,
            &memory,
            remaining_turn_budget.round() as i64,
            seed as u64,
        ))
    })();
    match result {
        Ok(value) => serde_json::to_string(&value)
            .unwrap_or_else(|err| json!({"error": format!("encode result: {err}")}).to_string()),
        Err(error) => json!({"error": error}).to_string(),
    }
}

/// Export the compatibility manifest so a generated glue bundle can be
/// checked against the adjacent model asset before it arms a room.
#[wasm_bindgen]
pub fn orbit_serving_manifest_json() -> String {
    serde_json::to_string(&serving::manifest())
        .unwrap_or_else(|err| json!({"error": format!("encode manifest: {err}")}).to_string())
}
