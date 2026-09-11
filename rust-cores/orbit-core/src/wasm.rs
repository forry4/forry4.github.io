//! wasm-bindgen exports for the Orbit browser serving worker.
//!
//! The exported functions deliberately take JSON policy inputs rather than a
//! privileged `State`. The worker and Python room validate the move against
//! the live engine; this module is an acceleration boundary, never an
//! authorization boundary.

use serde_json::{json, Value};
use wasm_bindgen::prelude::*;

use crate::serving;

thread_local! {
    static NEURAL: std::cell::RefCell<Option<crate::attention::Model>> = const { std::cell::RefCell::new(None) };
}

/// Experimental value evaluator; does not arm or replace the serving bot.
#[wasm_bindgen]
pub fn orbit_neural_load_json(raw: &str) -> String {
    let result = parse_object(raw,"model").and_then(|v|crate::attention::Model::load(&v));
    match result {
        Ok(model) => { NEURAL.with(|slot| *slot.borrow_mut()=Some(model)); json!({"loaded":true}).to_string() },
        Err(error) => json!({"error":error}).to_string(),
    }
}

#[wasm_bindgen]
pub fn orbit_neural_value_json(raw: &str) -> String {
    let result = parse_object(raw,"observation").and_then(|obs| NEURAL.with(|slot| {
        let slot=slot.borrow();
        let model=slot.as_ref().ok_or("Neural model not loaded")?;
        let tokens=crate::features::encode(&obs,None)?;
        let rows=model.encode_tokens(&tokens)?;
        model.logit_typed(&rows)
    }));
    match result { Ok(logit)=>json!({"logit":logit}).to_string(), Err(error)=>json!({"error":error}).to_string() }
}

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

/// Search one decision through the Phase 5 boundary, for the Expert tier.
///
/// The worker holds no privileged state, so the world is rebuilt from the seat's
/// own observation and the hidden pools are dealt from public conservation. Two
/// consequences are deliberate and must not be papered over by a caller:
///
///   * a pending chain is REFUSED, because the observation redacts the queue to
///     its first task -- the caller falls back to `orbit_choose_move_json`, and
///     the returned object says `fell_back` so a room can tell the difference;
///   * the search is one sample of the seat's information set per simulation, a
///     current-observation prior rather than a full-history posterior.
///
/// `budget_ms` is this decision's allowance, already split from the whole-turn
/// budget by the server. The returned move is still validated by the room.
#[wasm_bindgen]
pub fn orbit_search_move_json(
    observation_json: &str,
    legal_moves_json: &str,
    memory_json: &str,
    budget_ms: f64,
    seed: u32,
) -> String {
    let result: Result<Value, String> = (|| {
        let observation = parse_object(observation_json, "observation")?;
        let legal_moves = parse_array(legal_moves_json, "legal_moves")?;
        let memory: Value =
            serde_json::from_str(memory_json).map_err(|err| format!("memory: {err}"))?;
        let budget = budget_ms.max(0.0).round() as u64;
        let seat = observation["seat"].as_u64().ok_or("observation has no seat")? as usize;
        // One legal move needs no search and must not spend the turn's budget.
        if legal_moves.len() == 1 {
            return Ok(json!({"move": legal_moves[0].clone(), "fell_back": false, "simulations": 0}));
        }
        match crate::State::from_observation(&observation, seed as u64) {
            Ok(world) => {
                let config = crate::search::Config {
                    simulations: 1_000_000,
                    max_depth: 96,
                    budget_ms: budget,
                };
                let mut result = crate::search::choose(&world, seat, seed as u64, config, None)?;
                let result_stats = result["stats"].as_array().cloned().unwrap_or_default();
                // A search that ran no simulations has decided nothing; the
                // ranker is the better answer, not a random prior.
                if result["simulations"].as_u64().unwrap_or(0) == 0 {
                    let mut fallback =
                        serving::choose_move(&observation, &legal_moves, &memory, budget as i64, seed as u64);
                    fallback["fell_back"] = json!(true);
                    fallback["reason"] = json!("no simulations completed");
                    return Ok(fallback);
                }
                if let Some(object) = result.as_object_mut() {
                    // Keep only move/visits. The pool root-SUMS these across
                    // workers, which is the aggregation the arena measured;
                    // plurality voting over one move per worker throws away
                    // how sure each tree was.
                    let compact: Vec<Value> = result_stats
                        .iter()
                        .map(|entry| json!({"move": entry["move"], "visits": entry["visits"]}))
                        .collect();
                    object.insert("stats".into(), json!(compact));
                    object.insert("fell_back".into(), json!(false));
                }
                Ok(result)
            }
            Err(reason) => {
                let mut fallback =
                    serving::choose_move(&observation, &legal_moves, &memory, budget as i64, seed as u64);
                fallback["fell_back"] = json!(true);
                fallback["reason"] = json!(reason);
                Ok(fallback)
            }
        }
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
