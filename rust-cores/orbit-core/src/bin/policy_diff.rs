//! How often do two checkpoints actually choose a DIFFERENT move?
//!
//! The 2026-09-11 audit found the league's twelve rejected generations were not
//! failing to learn so much as failing to be measurable: the incumbent and a
//! rejected candidate picked the same move 77.9% of the time at the fixed
//! screen's own budget, and the frozen hand-written prior decided 65.5% of the
//! incumbent's. Two players that agree that often cannot be separated by any
//! affordable arena, so this runs FIRST and lets the league decline to buy one.
//!
//! Unlike an arena this needs no pairing, no seat swap and no confidence
//! interval: it counts decisions, and a decision is a fact. It is also cheap,
//! because only the reference player's move is applied — the trajectory is one
//! game, not two.
use orbit_core::{attention::Model, search::Config, State};
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

fn model_of(request: &Value, key: &str) -> Option<Model> {
    request
        .get(key)
        .filter(|v| !v.is_null())
        .map(|v| Model::load(v).expect("valid model"))
}

fn main() {
    let line = io::stdin().lock().lines().next().unwrap().unwrap();
    let request: Value = serde_json::from_str(&line).unwrap();
    // A null model is the heuristic leaf, so this also measures "how much does
    // the network move the search off its own prior" with no checkpoint at all.
    let reference = model_of(&request, "model");
    let other = model_of(&request, "other_model");
    let simulations = request["simulations"].as_u64().unwrap_or(32).max(1) as usize;
    assert!(simulations <= 10000, "Invalid fixed simulation count");
    let games = request["games"].as_u64().unwrap_or(8).max(1);
    let seed_base = request["seed"].as_u64().unwrap_or(0);
    let config = Config {
        simulations,
        max_depth: 96,
        budget_ms: 600_000,
    };

    let (mut agree, mut total) = (0u64, 0u64);
    let (mut agree_multi, mut multi) = (0u64, 0u64);
    let mut reference_follows_prior = 0u64;
    let mut errors: Vec<String> = Vec::new();

    for index in 0..games {
        // Every board side combination in turn, so agreement is not read off
        // one technology layout.
        let sides: [i32; 3] = std::array::from_fn(|i| 1 + ((index >> i) & 1) as i32);
        let seed = seed_base
            .wrapping_add(index.wrapping_mul(0x9E37_79B9_7F4A_7C15))
            .wrapping_add(1);
        let (mut state, mut chance) = State::new(seed, sides);
        for step in 0..600u64 {
            let Some(actor) = state.actor() else { break };
            let moves = state.legal_moves(actor);
            if moves.is_empty() {
                break;
            }
            // Both searches see the identical position AND the identical search
            // seed, so any disagreement is the checkpoint, never the sampler.
            let decision_seed = seed.wrapping_mul(31).wrapping_add(step);
            let a = match orbit_core::search::choose(
                &state,
                actor,
                decision_seed,
                config,
                reference.as_ref(),
            ) {
                Ok(value) => value,
                Err(error) => {
                    errors.push(error);
                    break;
                }
            };
            let b = match orbit_core::search::choose(
                &state,
                actor,
                decision_seed,
                config,
                other.as_ref(),
            ) {
                Ok(value) => value,
                Err(error) => {
                    errors.push(error);
                    break;
                }
            };
            total += 1;
            let same = a["move"] == b["move"];
            if same {
                agree += 1;
            }
            if moves.len() > 1 {
                multi += 1;
                if same {
                    agree_multi += 1;
                }
            }
            // The shared frozen prior is the third player in the room; report
            // how much of the reference's policy it is already deciding.
            if let Some(stats) = a["stats"].as_array() {
                if let Some(top) = stats.iter().max_by(|x, y| {
                    x["prior"]
                        .as_f64()
                        .unwrap_or(0.0)
                        .total_cmp(&y["prior"].as_f64().unwrap_or(0.0))
                }) {
                    if top["move"] == a["move"] {
                        reference_follows_prior += 1;
                    }
                }
            }
            // Advance on the reference's move; a shared trajectory keeps the
            // comparison on positions the incumbent actually reaches.
            let chosen = a["move"].clone();
            if !moves.contains(&chosen) {
                errors.push("Search returned an illegal move".into());
                break;
            }
            if let Err(error) = state.apply(actor, &chosen, &mut chance) {
                errors.push(error);
                break;
            }
        }
    }

    let pct = |n: u64, d: u64| if d == 0 { 0.0 } else { 100.0 * n as f64 / d as f64 };
    let report = json!({
        "decisions": total,
        "agree": agree,
        "agree_pct": pct(agree, total),
        "decisions_with_a_real_choice": multi,
        "agree_pct_where_more_than_one_legal_move": pct(agree_multi, multi),
        "reference_follows_hand_written_prior_pct": pct(reference_follows_prior, total),
        "games": games,
        "simulations": simulations,
        "errors": errors,
        "complete": errors.is_empty() && total > 0,
    });
    let mut out = io::stdout().lock();
    writeln!(out, "{}", report).unwrap();
    out.flush().unwrap();
}
