//! Parallel offline baseline generation. Policies only receive observations.
use orbit_core::{Chance, State};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::{self, BufRead, Write};

fn merge_profile(total: &mut BTreeMap<String, u64>, result: &Value) {
    let Some(profile) = result.get("profile").and_then(Value::as_object) else {
        return;
    };
    for (key, value) in profile {
        if let Some(value) = value.as_u64() {
            *total.entry(key.clone()).or_default() += value;
        }
    }
}

fn planet_progress(observation: &Value, planet: &str, seat: usize) -> f64 {
    let Some(index) = orbit_core::PLANETS.iter().position(|p| *p == planet) else {
        return 0.0;
    };
    let raw = observation["influence"]
        .as_array()
        .and_then(|values| values.get(index))
        .and_then(Value::as_i64)
        .unwrap_or(0) as f64;
    let direction = if seat == 0 { 1.0 } else { -1.0 };
    raw * direction
}

/// Observation-only specialist pressures used to expose blind spots in the
/// league.  They are intentionally simple and deterministic: their purpose is
/// to produce counterexamples, not to become a serving bot or leak State.
fn specialist_score(observation: &Value, action: &Value, name: &str) -> f64 {
    let seat = observation["seat"].as_u64().unwrap_or(0) as usize;
    let kind = action["action"].as_str().unwrap_or("");
    let planet = action["planet"].as_str().unwrap_or("");
    let progress = planet_progress(observation, planet, seat);
    let mut value = orbit_core::serving::action_score(observation, action);
    match name {
        "racer" => {
            if kind == "recruit" {
                value += 0.22 * progress.max(0.0);
                if progress >= 2.0 {
                    value += 2.2;
                }
            }
            if matches!(kind, "technology" | "leader") {
                value -= 0.35;
            }
            if matches!(
                kind,
                "influence"
                    | "influence_other"
                    | "split_influence"
                    | "two_adjacent"
                    | "adjacent_three"
            ) {
                value += 0.30;
            }
        }
        "developer" => {
            if kind == "technology" {
                value += 1.8;
            }
            if kind == "leader" {
                value += 0.35;
            }
            if kind == "recruit" {
                value += 0.035 * action["card_id"].as_i64().unwrap_or(0) as f64;
            }
            if progress >= 2.0 && kind == "recruit" {
                value -= 0.55;
            }
        }
        "denier" => {
            let other_progress = -progress;
            if other_progress >= 2.0 {
                value += 0.8;
            }
            if matches!(
                kind,
                "transfer" | "exile" | "exile_for_matching" | "influence_other"
            ) {
                value += 0.70 + 0.24 * other_progress.max(0.0);
            }
            if kind == "recruit" && progress <= -2.0 {
                value += 0.38;
            }
        }
        _ => {}
    }
    value
}

fn specialist_move(observation: &Value, moves: &[Value], name: &str) -> Value {
    moves
        .iter()
        .enumerate()
        .max_by(|(ia, a), (ib, b)| {
            specialist_score(observation, a, name)
                .total_cmp(&specialist_score(observation, b, name))
                .then_with(|| b.to_string().cmp(&a.to_string()))
                .then_with(|| ib.cmp(ia))
        })
        .map(|(_, m)| m.clone())
        .unwrap_or_else(|| moves[0].clone())
}

fn game(
    job: &Value,
    models: &[orbit_core::attention::Model],
    simulations: usize,
    model_stride: usize,
    model_weight: f64,
    model_temperature: f64,
) -> Result<Value, String> {
    let seed = job["seed"].as_u64().ok_or("Missing seed")?;
    let sides: [i32; 3] =
        serde_json::from_value(job["sides"].clone()).map_err(|e| e.to_string())?;
    if sides.iter().any(|s| !(1..=2).contains(s)) {
        return Err("Invalid board sides".into());
    }
    let names = job["policies"].as_array().ok_or("Missing policies")?;
    let model_index = |name: &Value| {
        name.as_str()
            .and_then(|n| n.strip_prefix("neural-"))
            .and_then(|n| n.parse::<usize>().ok())
    };
    if names.len() != 2
        || names.iter().any(|n| {
            !matches!(
                n.as_str(),
                Some(
                    "hard-v2"
                        | "exploratory-v2"
                        | "random"
                        | "expert"
                        | "racer"
                        | "racer-soft"
                        | "developer"
                        | "denier"
                )
            ) && !model_index(n).is_some_and(|i| i < models.len())
        })
    {
        return Err("Unknown policy".into());
    }
    let (mut state, mut chance) = State::new(seed, sides);
    let mut policy_rng = Chance::seeded(seed ^ job["assignment"].as_u64().unwrap_or(0));
    let mut steps = Vec::new();
    let mut search_evaluations = 0u64;
    let mut profile = BTreeMap::new();
    for decision in 0..1600 {
        let Some(seat) = state.actor() else {
            break;
        };
        let obs = state.observation(seat);
        let moves = obs["legal_moves"]
            .as_array()
            .ok_or("Missing legal actions")?;
        if moves.is_empty() {
            return Err("Nonterminal actor without moves".into());
        }
        let mut search_value: Option<f64> = None;
        let mv = if let Some(index) = model_index(&names[seat]) {
            let config = orbit_core::search::Config {
                simulations,
                max_depth: 96,
                budget_ms: 60000,
            };
            let result = orbit_core::search::choose_with_controls(
                &state,
                seat,
                seed.wrapping_add(decision),
                config,
                Some(&models[index]),
                model_stride,
                model_weight,
                model_temperature,
            )?;
            if result["simulations"].as_u64() != Some(simulations as u64) {
                return Err("Fixed-simulation teacher exceeded safety deadline".into());
            }
            merge_profile(&mut profile, &result);
            search_evaluations += result["evaluations"].as_u64().unwrap();
            search_value = result["root_value"].as_f64();
            result["move"].clone()
        } else if names[seat] == "expert" {
            let config = orbit_core::search::Config {
                simulations,
                max_depth: 96,
                budget_ms: 60000,
            };
            let result = orbit_core::search::choose_with_controls(
                &state,
                seat,
                seed.wrapping_add(decision),
                config,
                None,
                model_stride,
                model_weight,
                model_temperature,
            )?;
            if result["simulations"].as_u64() != Some(simulations as u64) {
                return Err("Fixed-simulation Expert teacher exceeded safety deadline".into());
            }
            merge_profile(&mut profile, &result);
            search_value = result["root_value"].as_f64();
            result["move"].clone()
        } else if matches!(
            names[seat].as_str(),
            Some("racer") | Some("developer") | Some("denier")
        ) {
            specialist_move(&obs, moves, names[seat].as_str().unwrap())
        } else if names[seat] == "racer-soft" {
            // A full-speed racer can make the learner choose the local
            // loss-minimising line forever.  The research campaign found a
            // smooth curriculum when a fraction of its replies are random;
            // keep this stochasticity in the private policy RNG only.
            if policy_rng.index(100) < 70 {
                specialist_move(&obs, moves, "racer")
            } else {
                moves[policy_rng.index(moves.len())].clone()
            }
        } else if names[seat] == "random"
            || (names[seat] == "exploratory-v2" && policy_rng.index(100) < 20)
        {
            moves[policy_rng.index(moves.len())].clone()
        } else {
            let result = orbit_core::serving::choose_move(&obs, moves, &Value::Null, 5000, seed);
            result
                .get("move")
                .filter(|m| moves.contains(m))
                .ok_or("Ranker returned illegal move")?
                .clone()
        };
        for viewer in 0..2 {
            steps.push(json!({"actor_seat":seat,"observer_seat":viewer,
                "observation":if viewer==seat {obs.clone()} else {state.observation(viewer)},
                "search_value":if viewer==seat {search_value.map_or(Value::Null,|value|json!(value))} else {Value::Null}}));
        }
        state.apply(seat, &mv, &mut chance)?;
    }
    state.validate()?;
    let mut result = json!({"seed":seed,"pair":job["pair"],"assignment":job["assignment"],
        "board":job["board"],"policies":names,"censored":state.phase!="over", "winner":state.winner,
        "steps":steps,"search_evaluations":search_evaluations});
    if !profile.is_empty() {
        result["profile"] = json!(profile);
    }
    Ok(result)
}
fn main() {
    let input = io::stdin()
        .lock()
        .lines()
        .next()
        .expect("request")
        .expect("read");
    let request: Value = serde_json::from_str(&input).expect("JSON");
    if let Some(obs) = request.get("observation") {
        let result = orbit_core::serving::choose_move(
            obs,
            obs["legal_moves"].as_array().expect("moves"),
            &Value::Null,
            5000,
            0,
        );
        println!("{result}");
        return;
    }
    let jobs = request["jobs"].as_array().expect("jobs").clone();
    let models: Vec<orbit_core::attention::Model> = request["models"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|v| orbit_core::attention::Model::load(v).expect("valid teacher model"))
        .collect();
    let simulations = request["simulations"].as_u64().unwrap_or(64) as usize;
    assert!(
        simulations > 0 && simulations <= 10000,
        "Invalid simulation budget"
    );
    let model_stride = request
        .get("model_stride")
        .and_then(Value::as_u64)
        .unwrap_or(1)
        .max(1) as usize;
    let model_weight = request
        .get("model_weight")
        .and_then(Value::as_f64)
        .unwrap_or(1.0)
        .clamp(0.0, 1.0);
    let model_temperature = request
        .get("model_temperature")
        .and_then(Value::as_f64)
        .unwrap_or(2.0)
        .max(0.1);
    let total = jobs.len();
    // Native data generation is offline and each worker owns one independent
    // game.  Leave one host thread for the OS, while allowing larger machines
    // to scale beyond the browser's UI-oriented worker cap.
    let threads = request["threads"].as_u64().unwrap_or(1).clamp(1, 16) as usize;
    let jobs = std::sync::Mutex::new(
        jobs.into_iter()
            .enumerate()
            .collect::<std::collections::VecDeque<_>>(),
    );
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::scope(|scope| {
        for _ in 0..threads {
            let tx = tx.clone();
            let jobs = &jobs;
            let models = &models;
            scope.spawn(move || loop {
                let Some((index, job)) = jobs.lock().unwrap().pop_front() else {
                    break;
                };
                let value = match game(
                    &job,
                    models,
                    simulations,
                    model_stride,
                    model_weight,
                    model_temperature,
                ) {
                    Ok(g) => json!({"index":index,"game":g}),
                    Err(e) => json!({"index":index,"error":e}),
                };
                tx.send(value).unwrap();
            });
        }
        let mut out = io::BufWriter::new(io::stdout().lock());
        for _ in 0..total {
            writeln!(out, "{}", rx.recv().unwrap()).unwrap();
            out.flush().unwrap();
        }
    });
}
