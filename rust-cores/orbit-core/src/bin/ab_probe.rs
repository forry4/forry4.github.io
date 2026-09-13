//! Is alpha-beta fast enough on Orbit to be worth arena time?
//!
//! Before spending hours of box time on a paired arena, the cheap question is
//! whether a depth-first search reaches a depth the MCTS cannot. Coherent
//! determinization descends a mean of 4.2 plies at ~10,900 simulations per
//! decision, so alpha-beta has to beat that comfortably or there is nothing to
//! test. This plays a real game from the opening and reports, per decision, the
//! depth reached and the node rate.
//!
//! Not a strength measurement -- it answers "is the prototype viable", and the
//! arena answers "is it stronger".
use orbit_core::alphabeta::{self, AbConfig};
use orbit_core::State;

use serde_json::Value;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let budget: u64 = args
        .iter()
        .position(|a| a == "--budget-ms")
        .and_then(|i| args.get(i + 1))
        .and_then(|v| v.parse().ok())
        .unwrap_or(1800);
    let decisions: usize = args
        .iter()
        .position(|a| a == "--decisions")
        .and_then(|i| args.get(i + 1))
        .and_then(|v| v.parse().ok())
        .unwrap_or(20);
    let seed: u64 = args
        .iter()
        .position(|a| a == "--seed")
        .and_then(|i| args.get(i + 1))
        .and_then(|v| v.parse().ok())
        .unwrap_or(12345);

    // The arena enumerates the eight boards as each faction's side 1 or 2, so a
    // probe on an impossible board would be measuring nothing real.
    let sides: [i32; 3] = [
        1 + ((seed >> 0) & 1) as i32,
        1 + ((seed >> 1) & 1) as i32,
        1 + ((seed >> 2) & 1) as i32,
    ];
    println!("seed {seed}, board sides {sides:?}, budget {budget}ms
");
    let compare_table = args.iter().any(|a| a == "--compare-table");
    if compare_table {
        compare(seed, sides, budget, decisions);
        return;
    }
    let (mut state, mut chance) = State::new(seed, sides);
    let mut searched = 0usize;
    let mut total_nodes = 0u64;
    let mut total_ms = 0.0f64;
    let mut depths: Vec<i64> = Vec::new();

    println!("{:>4}  {:>5}  {:>10}  {:>10}  {:>9}  {:>8}  {:>7}",
             "dec", "depth", "nodes", "nodes/s", "cutoffs", "tt_hits", "moves");

    let mut step = 0usize;
    while let Some(actor) = state.actor() {
        if searched >= decisions || step > 400 {
            break;
        }
        step += 1;
        let legal = state.legal_moves(actor);
        let mv = if legal.len() == 1 {
            legal[0].clone()
        } else {
            let result = alphabeta::choose(
                &state,
                actor,
                seed.wrapping_add(step as u64),
                AbConfig { budget_ms: budget, max_depth: 64, use_table: true, leaf: orbit_core::search::Leaf::StateValue, quiescence: false, victory_aware_ranker: true },
            )
            .expect("alpha-beta failed on a position with several legal moves");
            let nodes = result["nodes"].as_u64().unwrap();
            let ms = result["ms"].as_f64().unwrap();
            let depth = result["depth"].as_i64().unwrap();
            println!(
                "{:>4}  {:>5}  {:>10}  {:>10.0}  {:>9}  {:>8}  {:>7}",
                searched,
                depth,
                nodes,
                nodes as f64 / (ms / 1000.0).max(1e-9),
                result["cutoffs"].as_u64().unwrap(),
                result["table_hits"].as_u64().unwrap(),
                legal.len(),
            );
            searched += 1;
            total_nodes += nodes;
            total_ms += ms;
            depths.push(depth);
            result["move"].clone()
        };
        if state.apply(actor, &mv, &mut chance).is_err() {
            eprintln!("engine rejected a legal move at step {step}");
            break;
        }
    }

    if depths.is_empty() {
        println!("\nno searched decisions");
        return;
    }
    depths.sort_unstable();
    let mean_depth = depths.iter().sum::<i64>() as f64 / depths.len() as f64;
    println!();
    println!("searched decisions : {}", depths.len());
    println!("depth  min/med/max : {} / {} / {}",
             depths[0], depths[depths.len() / 2], depths[depths.len() - 1]);
    println!("mean depth         : {mean_depth:.2}  (MCTS coherent descends 4.2)");
    println!("node rate          : {:.0}/s over {:.1}s",
             total_nodes as f64 / (total_ms / 1000.0), total_ms / 1000.0);
    println!("total nodes        : {total_nodes}");
}

/// Does the transposition table pay for itself at the depth actually searched?
///
/// Orbit barely transposes, so the table is close to pure overhead: it costs a
/// structural hash on EVERY node to hit on a few percent of them. The honest
/// comparison is therefore at equal TIME -- not equal nodes and not equal depth
/// -- because what a table buys, if anything, is depth per second.
fn compare(seed: u64, sides: [i32; 3], budget: u64, decisions: usize) {
    let mut rows: Vec<(i64, i64, u64, u64, u64)> = Vec::new();
    for table in [true, false] {
        let (mut state, mut chance) = State::new(seed, sides);
        let mut searched = 0usize;
        let mut step = 0usize;
        let mut depth_sum = 0i64;
        let mut node_sum = 0u64;
        let mut hit_sum = 0u64;
        while let Some(actor) = state.actor() {
            if searched >= decisions || step > 400 {
                break;
            }
            step += 1;
            let legal = state.legal_moves(actor);
            let mv: Value = if legal.len() == 1 {
                legal[0].clone()
            } else {
                let result = alphabeta::choose(
                    &state,
                    actor,
                    seed.wrapping_add(step as u64),
                    AbConfig { budget_ms: budget, max_depth: 64, use_table: table, leaf: orbit_core::search::Leaf::StateValue, quiescence: false, victory_aware_ranker: true },
                )
                .expect("alpha-beta failed");
                depth_sum += result["depth"].as_i64().unwrap();
                node_sum += result["nodes"].as_u64().unwrap();
                hit_sum += result["table_hits"].as_u64().unwrap();
                searched += 1;
                result["move"].clone()
            };
            if state.apply(actor, &mv, &mut chance).is_err() {
                break;
            }
        }
        rows.push((table as i64, depth_sum, searched as u64, node_sum, hit_sum));
    }
    println!("{:>7}  {:>10}  {:>10}  {:>10}  {:>9}", "table", "mean depth", "decisions", "nodes", "tt hits");
    for (table, depth_sum, searched, node_sum, hit_sum) in &rows {
        println!(
            "{:>7}  {:>10.2}  {:>10}  {:>10}  {:>9}",
            if *table == 1 { "on" } else { "off" },
            *depth_sum as f64 / (*searched).max(1) as f64,
            searched,
            node_sum,
            hit_sum
        );
    }
    let on = rows[0].1 as f64 / rows[0].2.max(1) as f64;
    let off = rows[1].1 as f64 / rows[1].2.max(1) as f64;
    println!();
    if on > off + 0.05 {
        println!("The table BUYS depth at equal time ({on:.2} against {off:.2}); keep it.");
    } else if off > on + 0.05 {
        println!("The table COSTS depth at equal time ({on:.2} against {off:.2}); drop it.");
    } else {
        println!("No measurable difference ({on:.2} against {off:.2}); drop it as dead weight.");
    }
}
