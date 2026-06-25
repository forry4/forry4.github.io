//! Native sims/second benchmark of the variant-S search, on a deterministic mid-game position.
//! The apples-to-apples baseline for the WASM benchmark (which runs the SAME demo_position).
//!
//! Usage: cargo run --release --bin bench [sims] [setup_moves] [reps]

use spender_core::rng::Rng;
use spender_core::vsearch;
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let sims: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(2000);
    let setup_moves: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(24);
    let reps: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(5);

    let pos = vsearch::demo_position(12345, setup_moves);
    let legal = spender_core::engine::legal_actions(&pos);
    eprintln!(
        "demo position: ply {} phase {} turn {} legal {} (pts {:?})",
        pos.ply, pos.phase, pos.turn, legal.len(), pos.points
    );

    // warmup (JIT-free, but warms caches / branch predictors)
    let mut wrng = Rng::new(1);
    let _ = vsearch::choose_action(&pos, pos.turn, 200, &mut wrng);

    let t = Instant::now();
    let mut last = 0usize;
    for r in 0..reps {
        let mut rng = Rng::new(100 + r as u64);
        last = vsearch::choose_action(&pos, pos.turn, sims, &mut rng);
    }
    let el = t.elapsed().as_secs_f64();
    let total = (sims * reps) as f64;
    println!(
        "native: {sims} sims x {reps} reps in {el:.3}s = {:.0} sims/s  (chose action {last})",
        total / el
    );
}
