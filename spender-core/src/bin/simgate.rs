//! Sim-count A/B: play Rust-S(hi sims) vs Rust-S(lo sims), paired (each deck both orientations to
//! cancel the first-player edge), and report the HI side's win rate. Tests whether more sims actually
//! win — the empirical check on the "saturation" claim.
//!
//! Usage: cargo run --release --bin simgate [hi_sims] [lo_sims] [base_seeds] [threads]
//!   base_seeds×2 = total games (each base played both orientations). Default 1_000_000 1200 50 4.
//!   WARNING: a 1M-sim move builds an ~1M-node tree (~1.5-2GB). Keep `threads` ≤ free_RAM/2GB.

use spender_core::{engine, rng::Rng, vsearch};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

fn play(deck_seed: u64, sims: [usize; 2]) -> i32 {
    let mut s = engine::new_game(deck_seed, 15);
    let mut rng = [Rng::new(deck_seed ^ 0xA5A5), Rng::new(deck_seed ^ 0x5A5A)];
    let mut ply = 0;
    while s.phase != engine::OVER && ply < 600 {
        let seat = s.turn;
        let a = vsearch::choose_action(&s, seat, sims[seat], &mut rng[seat]);
        engine::apply(&mut s, a);
        ply += 1;
    }
    s.winner
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let hi: usize = a.get(1).and_then(|s| s.parse().ok()).unwrap_or(1_000_000);
    let lo: usize = a.get(2).and_then(|s| s.parse().ok()).unwrap_or(1_200);
    let n_base: u64 = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(50);
    let threads: usize = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(4);

    // specs: (deck_seed, hi_seat) — each base seed played with hi as seat 0 then seat 1.
    let mut specs: Vec<(u64, usize)> = Vec::new();
    for g in 0..n_base {
        specs.push((50_000 + g, 0));
        specs.push((50_000 + g, 1));
    }
    let total = specs.len();
    eprintln!("simgate: {hi} sims (HI) vs {lo} sims (LO), {total} games, {threads} threads");

    let specs = Arc::new(specs);
    let next = Arc::new(AtomicUsize::new(0));
    let hi_score = Arc::new(Mutex::new(0.0f64));
    let done = Arc::new(AtomicUsize::new(0));
    let t0 = Instant::now();

    let mut handles = Vec::new();
    for _ in 0..threads {
        let (specs, next, hi_score, done) = (specs.clone(), next.clone(), hi_score.clone(), done.clone());
        handles.push(thread::spawn(move || loop {
            let i = next.fetch_add(1, Ordering::SeqCst);
            if i >= specs.len() {
                break;
            }
            let (seed, hi_seat) = specs[i];
            let sims = if hi_seat == 0 { [hi, lo] } else { [lo, hi] };
            let w = play(seed, sims);
            let sc = if w == engine::WIN_DRAW || w == engine::WIN_NONE {
                0.5
            } else if w as usize == hi_seat {
                1.0
            } else {
                0.0
            };
            let mut hs = hi_score.lock().unwrap();
            *hs += sc;
            let d = done.fetch_add(1, Ordering::SeqCst) + 1;
            eprintln!(
                "  game {d}/{} | HI {} | running HI win-rate {:.4} | {:.0}s elapsed",
                specs.len(),
                if sc == 1.0 { "WIN " } else if sc == 0.0 { "loss" } else { "draw" },
                *hs / d as f64,
                t0.elapsed().as_secs_f64(),
            );
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    let hs = *hi_score.lock().unwrap();
    let wr = hs / total as f64;
    let se = (wr * (1.0 - wr) / total as f64).sqrt();
    println!(
        "\nHI({hi}) vs LO({lo}): {wr:.4}  (+/-{:.3} 95% CI, {total} games, {:.0}s)",
        1.96 * se,
        t0.elapsed().as_secs_f64()
    );
}
