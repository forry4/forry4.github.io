//! Development arena for native search versus frozen Hard v2. Not a ship gate.
use orbit_core::{attention::Model, search::Config, State};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};
/// Run `pool` independent trees on one decision and sum their root visits.
///
/// This is the shipped serving arrangement: the browser fans the same decision
/// out to a capped worker pool and aggregates at the root, so a single tree
/// under-reports the strength the product actually has. Each tree gets the
/// whole allowance because the workers are concurrent, and the elapsed time
/// charged to the turn is the slowest tree, not their sum.
fn choose_pooled(
    state: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    pool: usize,
    model_stride: usize,
    model_weight: f64,
    model_temperature: f64,
) -> Result<Value, String> {
    if pool <= 1 {
        return orbit_core::search::choose_with_controls(
            state,
            seat,
            seed,
            config,
            model,
            model_stride,
            model_weight,
            model_temperature,
        );
    }
    let trees: Vec<Result<Value, String>> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..pool)
            .map(|k| {
                let seed = seed.wrapping_add((k as u64).wrapping_mul(0x9E3779B97F4A7C15));
                scope.spawn(move || {
                    orbit_core::search::choose_with_controls(
                        state,
                        seat,
                        seed,
                        config,
                        model,
                        model_stride,
                        model_weight,
                        model_temperature,
                    )
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|h| {
                h.join()
                    .unwrap_or_else(|_| Err("Search worker panicked".into()))
            })
            .collect()
    });
    let mut roots = Vec::new();
    for tree in trees {
        roots.push(tree?);
    }
    let first = &roots[0];
    let width = first["stats"]
        .as_array()
        .ok_or("Missing root statistics")?
        .len();
    // Move order is a deterministic sort inside the search, so equal-width
    // statistics arrays are aligned; anything else means the trees disagree
    // about the position and must not be summed.
    let mut visits = vec![0u64; width];
    let mut totals = vec![0f64; width];
    let mut simulations = 0u64;
    let mut evaluations = 0u64;
    let mut elapsed: f64 = 0.0;
    for root in &roots {
        let stats = root["stats"].as_array().ok_or("Missing root statistics")?;
        if stats.len() != width {
            return Err("Pooled trees disagree about the move list".into());
        }
        for (index, entry) in stats.iter().enumerate() {
            if entry["move"] != first["stats"][index]["move"] {
                return Err("Pooled trees disagree about move order".into());
            }
            let n = entry["visits"].as_u64().unwrap_or(0);
            visits[index] += n;
            totals[index] += entry["value"].as_f64().unwrap_or(0.0) * n as f64;
        }
        simulations += root["simulations"].as_u64().unwrap_or(0);
        evaluations += root["evaluations"].as_u64().unwrap_or(0);
        elapsed = elapsed.max(root["elapsed_ms"].as_f64().unwrap_or(0.0));
    }
    let mean = |i: usize| {
        if visits[i] == 0 {
            0.0
        } else {
            totals[i] / visits[i] as f64
        }
    };
    let best = (0..width)
        .max_by(|a, b| {
            visits[*a]
                .cmp(&visits[*b])
                .then_with(|| mean(*a).total_cmp(&mean(*b)))
        })
        .ok_or("Empty root")?;
    let stats: Vec<Value> = (0..width)
        .map(|i| json!({"move":first["stats"][i]["move"],"visits":visits[i],"value":mean(i)}))
        .collect();
    Ok(
        json!({"move":first["stats"][best]["move"],"simulations":simulations,"evaluations":evaluations,
              "elapsed_ms":elapsed,"stats":stats,"pool":pool,"belief":"current-observation prior"}),
    )
}

fn main() {
    let line = io::stdin().lock().lines().next().unwrap().unwrap();
    let request: Value = serde_json::from_str(&line).unwrap();
    // A null model runs the same search with the heuristic leaf, so an arena can
    // separate the contribution of search from the contribution of the network.
    let model = if request["model"].is_null() {
        None
    } else {
        Some(Model::load(&request["model"]).expect("valid model"))
    };
    let opponent = request
        .get("opponent_model")
        .map(|v| Model::load(v).expect("valid opponent model"));
    let opponent_expert = request
        .get("opponent_expert")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if opponent_expert && opponent.is_some() {
        panic!("choose one opponent model or Expert")
    }
    let fixed_sims = request.get("simulations").and_then(Value::as_u64);
    assert!(
        fixed_sims.is_none_or(|n| n > 0 && n <= 10000),
        "Invalid fixed simulation count"
    );
    let pool = request["pool"].as_u64().unwrap_or(1).max(1) as usize;
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
    // Drive the candidate through the browser's own boundary: rebuild the world
    // from the seat's observation instead of searching the privileged state, and
    // fall back to the ranker wherever that reconstruction is refused. This is
    // the shipped bot, so it is the one worth measuring.
    let via_observation = request["via_observation"].as_bool().unwrap_or(false);
    // This is an offline native arena.  Unlike the browser pool it may use
    // all but one host thread, up to the generous safety ceiling below.
    assert!(pool <= 16, "Native worker pool is capped at sixteen");
    let game_workers = request
        .get("game_workers")
        .and_then(Value::as_u64)
        .unwrap_or(1)
        .max(1) as usize;
    assert!(
        game_workers <= 16,
        "Native game-worker pool is capped at sixteen"
    );
    assert!(
        pool.saturating_mul(game_workers) <= 16,
        "game_workers * root workers must fit within sixteen native threads"
    );
    let jobs = request["jobs"].as_array().unwrap();
    // Independent games can run concurrently in the offline arena.  The
    // product profile normally uses game_workers=1 so each decision retains
    // its full root ensemble; fast development probes can trade some
    // per-game ensemble width for much higher games/second, while the product
    // worker budget remains explicit in the report.
    let queue = std::sync::Mutex::new(
        jobs.iter()
            .cloned()
            .enumerate()
            .collect::<std::collections::VecDeque<_>>(),
    );
    let (tx, rx) = std::sync::mpsc::channel();
    let total = jobs.len();
    let mut ordered = vec![Value::Null; total];
    // These values are immutable for the whole request.  Borrow them into the
    // scoped game workers so every worker can reuse the decoded model without
    // cloning its weights (and without moving the request on the first loop).
    let request_ref = &request;
    let model_ref = model.as_ref();
    let opponent_ref = opponent.as_ref();
    std::thread::scope(|scope| {
        for _ in 0..game_workers {
            let queue = &queue;
            let tx = tx.clone();
            let request = request_ref;
            let model = model_ref;
            let opponent = opponent_ref;
            scope.spawn(move || loop {
                let Some((index, job)) = queue.lock().unwrap().pop_front() else {
                    break;
                };
                let seed = job["seed"].as_u64().unwrap();
                let candidate = job["candidate"].as_u64().unwrap() as usize;
                let sides: [i32; 3] = serde_json::from_value(job["sides"].clone()).unwrap();
                let budget = request["budget_ms"].as_u64().unwrap_or(100);
                // Mirror the serving allocation: the turn's main action is capped, the
                // remainder is reserved for follow-up decisions, and a forced move is
                // played without search so it cannot consume the turn's budget.
                let main_ms = request["main_action_ms"].as_u64().unwrap_or(budget);
                let followup_ms = request["followup_ms"].as_u64().unwrap_or(budget);
                let (mut state, mut chance) = State::new(seed, sides);
                let mut turn = state.turn_number;
                let mut remaining = [budget; 2];
                let mut acted = [0u32; 2];
                let mut sims = 0u64;
                let mut calls = 0;
                let mut decisions = 0;
                let mut failure = None;
                while let Some(seat) = state.actor() {
                    if decisions >= 1600 {
                        break;
                    }
                    if state.turn_number != turn {
                        turn = state.turn_number;
                        remaining = [budget; 2];
                        acted = [0; 2];
                    }
                    let legal = state.legal_moves(seat);
                    let evaluator = if seat == candidate {
                        model
                    } else if opponent_expert {
                        None
                    } else {
                        opponent
                    };
                    // Every searched seat must cross the same observation boundary.
                    // The old probe rebuilt only the candidate and the heuristic Expert;
                    // that gave a neural opponent privileged hidden state and made
                    // same-checkpoint controls asymmetric.  A neural opponent is also
                    // served from its own observation, so include it here.
                    let observation_search =
                        seat == candidate || opponent_expert || opponent.is_some();
                    let rebuild = via_observation && legal.len() > 1 && observation_search;
                    let rebuilt = if rebuild {
                        match State::from_observation(
                            &state.observation(seat),
                            seed.wrapping_add(decisions),
                        ) {
                            Ok(world) => Some(world),
                            Err(_) => None,
                        }
                    } else {
                        None
                    };
                    let searchable = if via_observation && observation_search {
                        rebuilt.is_some()
                    } else {
                        seat == candidate || opponent.is_some() || opponent_expert
                    };
                    let mv = if legal.len() == 1 {
                        legal[0].clone()
                    } else if searchable {
                        let source = rebuilt.as_ref().unwrap_or(&state);
                        let allowance = remaining[seat].min(if acted[seat] == 0 {
                            main_ms
                        } else {
                            followup_ms
                        });
                        let config = Config {
                            simulations: fixed_sims.unwrap_or(100000) as usize,
                            max_depth: 96,
                            budget_ms: if fixed_sims.is_some() {
                                60000
                            } else {
                                allowance
                            },
                        };
                        let actor_pool = if observation_search { pool } else { 1 };
                        match if actor_pool <= 1 {
                            orbit_core::search::choose_with_controls(
                                source,
                                seat,
                                seed.wrapping_add(decisions),
                                config,
                                evaluator,
                                model_stride,
                                model_weight,
                                model_temperature,
                            )
                        } else {
                            choose_pooled(
                                source,
                                seat,
                                seed.wrapping_add(decisions),
                                config,
                                evaluator,
                                actor_pool,
                                model_stride,
                                model_weight,
                                model_temperature,
                            )
                        } {
                            Ok(result) => {
                                let quota = fixed_sims.map(|n| n * actor_pool as u64);
                                if quota.is_some_and(|n| result["simulations"].as_u64() != Some(n))
                                {
                                    failure = Some(
                                        "Fixed-simulation arena exceeded safety deadline".into(),
                                    );
                                    break;
                                }
                                remaining[seat] = remaining[seat].saturating_sub(
                                    result["elapsed_ms"].as_f64().unwrap().ceil() as u64,
                                );
                                acted[seat] += 1;
                                sims += result["simulations"].as_u64().unwrap();
                                calls += 1;
                                result["move"].clone()
                            }
                            Err(error) => {
                                failure = Some(error);
                                break;
                            }
                        }
                    } else {
                        let obs = state.observation(seat);
                        orbit_core::serving::choose_move(
                            &obs,
                            obs["legal_moves"].as_array().unwrap(),
                            &Value::Null,
                            budget as i64,
                            seed,
                        )["move"]
                            .clone()
                    };
                    let _ = &legal;
                    if let Err(error) = state.apply(seat, &mv, &mut chance) {
                        failure = Some(error);
                        break;
                    }
                    decisions += 1;
                }
                tx.send(
                    json!({"index":index,"seed":seed,"candidate":candidate,"sides":sides,
            "winner":state.winner,"censored":state.phase!="over","error":failure,
            "simulations":sims,"calls":calls,"decisions":decisions}),
                )
                .unwrap();
                if failure.is_some() {
                    break;
                }
            });
        }
        drop(tx);
        for value in rx {
            let index = value["index"].as_u64().unwrap() as usize;
            ordered[index] = value;
        }
    });
    let mut out = io::BufWriter::new(io::stdout().lock());
    for value in ordered {
        writeln!(out, "{value}").unwrap();
    }
}
