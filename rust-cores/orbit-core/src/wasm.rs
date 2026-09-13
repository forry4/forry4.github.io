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
    determinization_period: f64,
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
                // The wasm and the worker are separate cached artifacts on the
                // same filename, so a browser can hold one without the other.
                // An absent argument arrives as NaN and now means SERVING --
                // coherent, measured 0.6094 over 128 pairs at this exact shape
                // (see `Controls::serving`). An old worker against this build
                // therefore gets the shipped search without needing to know the
                // argument exists, which is what lets this ship as one artifact
                // instead of a coupled two-push expand/contract.
                //
                // An explicit number still wins, in both directions: 0 asks for
                // the coherent world and any positive n for n simulations per
                // determinization, so 1 remains the way to request the
                // historical search. A new worker passing 0 to an older build
                // that predates this argument simply has it ignored and gets
                // that build's behaviour -- degraded, never broken.
                let controls = if determinization_period.is_finite()
                    && determinization_period >= 0.0
                {
                    crate::search::Controls {
                        determinization_period: match determinization_period.round() as u64 {
                            0 => usize::MAX,
                            n => n as usize,
                        },
                        ..crate::search::Controls::serving()
                    }
                } else {
                    crate::search::Controls::serving()
                };
                let mut result =
                    crate::search::choose_with(&world, seat, seed as u64, config, None, controls)?;
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

/// The Expert tier: iterative-deepening alpha-beta over THIS worker's world.
///
/// PIMC IS THE WORKER POOL. Each of the four workers reconstructs its own world
/// from the same observation with its own seed, searches it depth-first, and
/// returns one vote; the page sums those. So the browser is running K=4 PIMC
/// with every world getting the WHOLE turn budget, which is the arrangement
/// measured natively -- 0.6172 against the coherent MCTS Expert at serving
/// shape, 64 CRN pairs, mean depth 7.77 against the MCTS's 4.2.
///
/// THE VOTE IS VALUE-WEIGHTED, and the fraction is load-bearing rather than
/// decoration. The page's aggregation sums `visits` and takes the maximum, so a
/// plain integer vote would leave a 2-2 split to be broken by move key. The
/// native implementation breaks vote ties by the summed VALUE of the votes
/// cast, and shipping a different tie-break from the one that was measured is
/// exactly how a campaign ends up serving a player it never tested. A vote of
/// `1 + value/2000` reproduces it: four workers contribute at most 0.002, so
/// the integer part always decides first and the fraction only ever separates
/// an exact tie.
#[wasm_bindgen]
pub fn orbit_alphabeta_move_json(
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
        if legal_moves.len() == 1 {
            return Ok(json!({"move": legal_moves[0].clone(), "fell_back": false, "simulations": 0}));
        }
        let ranker = |reason: &str| {
            let mut fallback =
                serving::choose_move(&observation, &legal_moves, &memory, budget as i64, seed as u64);
            fallback["fell_back"] = json!(true);
            fallback["reason"] = json!(reason);
            fallback
        };
        // A pending chain is not reconstructable from an observation, which is
        // the same boundary the MCTS tier meets and answers the same way.
        let world = match crate::State::from_observation(&observation, seed as u64) {
            Ok(world) => world,
            Err(reason) => return Ok(ranker(&reason)),
        };
        let config = crate::alphabeta::AbConfig {
            budget_ms: budget,
            max_depth: 64,
            // Orbit barely transposes -- 1.4% table hits at depth 4, 1.3-5.4%
            // at depth 8-9, because the deck order advances with every path and
            // most moves are irreversible -- but the table costs only a
            // structural hash and the native measurement ran with it on, so it
            // stays on here to serve what was measured.
            use_table: true,
        };
        match crate::alphabeta::choose(&world, seat, seed as u64, config) {
            Ok(result) => {
                // Depth 0 means the budget did not finish a single iteration, so
                // the search has decided nothing and the ranker is the better
                // answer than an unexamined prior.
                if result["depth"].as_i64().unwrap_or(0) <= 0 {
                    return Ok(ranker("no iteration completed"));
                }
                let value = result["value"].as_f64().unwrap_or(0.0).clamp(-1.0, 1.0);
                Ok(json!({
                    "move": result["move"].clone(),
                    "stats": [{"move": result["move"].clone(), "visits": 1.0 + value / 2000.0}],
                    "depth": result["depth"].clone(),
                    "nodes": result["nodes"].clone(),
                    "simulations": result["nodes"].clone(),
                    "fell_back": false,
                }))
            }
            Err(reason) => Ok(ranker(&reason)),
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
