//! Parallel offline baseline generation. Policies only receive observations.
use orbit_core::{search::Controls, search::OpponentModel, Chance, State};
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

/// The root visit distribution, stripped to what a policy target needs.
///
/// Moves are already in the search's deterministic sort order, so the array
/// index is a stable identity within one decision; the move itself is kept so a
/// trainer never has to reconstruct the legal-move ordering to line rows up.
fn compact_visits(result: &Value) -> Value {
    let Some(stats) = result["stats"].as_array() else {
        return Value::Null;
    };
    Value::Array(
        stats
            .iter()
            .map(|entry| {
                json!({
                    "move": entry["move"],
                    "visits": entry["visits"],
                    "prior": entry["prior"],
                })
            })
            .collect(),
    )
}

/// Sample a move from the root visit distribution instead of taking the argmax.
///
/// The teacher played `argmax(visits)` at every decision from the first commit
/// until 2026-09-11, deterministically, so the value network only ever saw the
/// consequences of moves its own policy already preferred: no counterfactual
/// coverage of the lines it declined. Spender's log is explicit that Dirichlet
/// ROOT noise washed for it ("exploration is not the bottleneck") while
/// visit-count sampling for the opening ~30 plies did not, so this is the form
/// borrowed.
///
/// `plies` is how many of a game's opening decisions sample; after that the
/// teacher is the argmax again, so endgame labels stay the policy's own.
/// `temperature` of 1.0 samples proportionally to visits; higher is flatter.
/// Sampling uses the PRIVATE policy RNG, never the game's chance stream, so the
/// deal is untouched and a seeded run stays reproducible.
fn sample_by_visits(
    result: &Value,
    moves: &[Value],
    temperature: f64,
    rng: &mut Chance,
) -> Option<Value> {
    let stats = result["stats"].as_array()?;
    let mut weights: Vec<f64> = Vec::with_capacity(stats.len());
    for entry in stats {
        let visits = entry["visits"].as_f64().unwrap_or(0.0);
        weights.push(if visits > 0.0 {
            visits.powf(1.0 / temperature.max(1e-6))
        } else {
            0.0
        });
    }
    let total: f64 = weights.iter().sum();
    if !(total > 0.0) {
        return None;
    }
    // One draw from the private RNG, quantized so the choice is exactly
    // reproducible from the seed rather than depending on float ordering.
    const RESOLUTION: usize = 1 << 20;
    let mut ticket = (rng.index(RESOLUTION) as f64 / RESOLUTION as f64) * total;
    for (entry, weight) in stats.iter().zip(&weights) {
        ticket -= weight;
        if ticket <= 0.0 && *weight > 0.0 {
            let candidate = entry["move"].clone();
            return moves.contains(&candidate).then_some(candidate);
        }
    }
    None
}

#[allow(clippy::too_many_arguments)]
fn game(
    job: &Value,
    models: &[orbit_core::attention::Model],
    simulations: usize,
    controls: Controls,
    sample_plies: u64,
    sample_temperature: f64,
    record_policy: bool,
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
        let mut search_stats: Option<Value> = None;
        let mv = if let Some(index) = model_index(&names[seat]) {
            let config = orbit_core::search::Config {
                simulations,
                max_depth: 96,
                budget_ms: 60000,
            };
            let result = orbit_core::search::choose_with(
                &state,
                seat,
                seed.wrapping_add(decision),
                config,
                Some(&models[index]),
                controls,
            )?;
            if result["simulations"].as_u64() != Some(simulations as u64) {
                return Err("Fixed-simulation teacher exceeded safety deadline".into());
            }
            merge_profile(&mut profile, &result);
            search_evaluations += result["evaluations"].as_u64().unwrap();
            search_value = result["root_value"].as_f64();
            if record_policy {
                search_stats = Some(compact_visits(&result));
            }
            // The label stays the game's terminal outcome; only which move is
            // PLAYED is sampled, and only in the opening.
            if decision < sample_plies {
                sample_by_visits(&result, moves, sample_temperature, &mut policy_rng)
                    .unwrap_or_else(|| result["move"].clone())
            } else {
                result["move"].clone()
            }
        } else if names[seat] == "expert" {
            let config = orbit_core::search::Config {
                simulations,
                max_depth: 96,
                budget_ms: 60000,
            };
            let result = orbit_core::search::choose_with(
                &state,
                seat,
                seed.wrapping_add(decision),
                config,
                None,
                controls,
            )?;
            if result["simulations"].as_u64() != Some(simulations as u64) {
                return Err("Fixed-simulation Expert teacher exceeded safety deadline".into());
            }
            merge_profile(&mut profile, &result);
            search_value = result["root_value"].as_f64();
            if record_policy {
                search_stats = Some(compact_visits(&result));
            }
            if decision < sample_plies {
                sample_by_visits(&result, moves, sample_temperature, &mut policy_rng)
                    .unwrap_or_else(|| result["move"].clone())
            } else {
                result["move"].clone()
            }
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
            let mut step = json!({"actor_seat":seat,"observer_seat":viewer,
                "observation":if viewer==seat {obs.clone()} else {state.observation(viewer)},
                "search_value":if viewer==seat {search_value.map_or(Value::Null,|value|json!(value))} else {Value::Null}});
            // POLICY TARGET. The campaign has never recorded one: the value
            // network has no policy head and the PUCT prior is the frozen
            // hand-written `action_score`, which the search then agrees with a
            // majority of the time. A policy head cannot be trained without
            // these rows, so they are recorded here (actor view only, gated,
            // and only where a search actually ran). Visits are the AlphaZero
            // target; the prior is kept beside them so a later run can measure
            // how far the learned policy moved from the hand-written one.
            if record_policy && viewer == seat {
                if let Some(stats) = search_stats.as_ref() {
                    step["visits"] = stats.clone();
                }
            }
            steps.push(step);
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
    // Opening plies whose PLAYED move is sampled from the root visit counts.
    // Zero reproduces the historical deterministic argmax teacher exactly, and
    // is the control arm for the A/B this was added for.
    let sample_plies = request["sample_plies"].as_u64().unwrap_or(0);
    // Teacher search regime. Defaults reproduce the historical teacher exactly;
    // once a serving regime is confirmed, the teacher should mirror it so the
    // rows describe the search that will actually consume them.
    let leaf = match request.get("leaf").and_then(Value::as_str) {
        None | Some("state-value") => orbit_core::search::Leaf::StateValue,
        Some("capture-progress-only") => orbit_core::search::Leaf::CaptureProgressOnly,
        Some(other) => panic!("unknown leaf {other}"),
    };
    let determinization_period = match request
        .get("determinization_period")
        .and_then(Value::as_u64)
    {
        None | Some(1) => 1usize,
        Some(0) => usize::MAX,
        Some(n) => n as usize,
    };
    let controls = Controls {
        model_stride,
        model_weight,
        model_temperature,
        leaf,
        determinization_period,
        opponent_model: OpponentModel::Ranker,
        // Training data is generated from what a SERVED search sees, so hidden
        // information is resampled here as it always has been. The
        // perfect-information mode exists for one architecture comparison and
        // would poison a value target with knowledge the server never has.
        determinize: true,
        policy_prior_weight: 0.0,
    };
    let record_policy = request["record_policy"].as_bool().unwrap_or(false);
    let sample_temperature = request["sample_temperature"]
        .as_f64()
        .unwrap_or(1.0)
        .max(1e-6);
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
                    controls,
                    sample_plies,
                    sample_temperature,
                    record_policy,
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
