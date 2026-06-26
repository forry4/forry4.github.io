//! Self-gate: Rust-S WITH the endgame solver (#1) vs Rust-S plain PUCT, at MATCHED sims, paired CRN
//! (each deck played both seat-assignments to cancel the first-player edge). Reports the refined side's
//! win rate — must be >= 0.5 (never a regression), ideally up (the solver overrides only on proof).
//!
//! Usage: cargo run --release --bin selfgate_endgame [sims] [base_seeds] [threads]

use spender_core::engine::{self, State};
use spender_core::rng::Rng;
use spender_core::{endgame, vsearch};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

/// Play one full game on `deck_seed`; `refined_seat` uses the endgame-refined policy, the other plain
/// PUCT. Returns (refined side score [1.0 win / 0.5 draw / 0.0 loss], # solver overrides that changed
/// the move). The refined seat computes plain PUCT first, then the solver — so we can count exactly
/// when the override differs (this is what `choose_action_refined` does internally, exposed).
fn play_game(deck_seed: u64, refined_seat: usize, sims: usize) -> (f64, u32) {
    let mut s: State = engine::new_game(deck_seed, 15);
    let mut srng = [
        Rng::new(0x5EED_0000 ^ (deck_seed << 2)),
        Rng::new(0x5EED_0001 ^ (deck_seed << 2)),
    ];
    let mut egrng = [
        Rng::new(0x0E6_0000 ^ (deck_seed << 2)),
        Rng::new(0x0E6_0001 ^ (deck_seed << 2)),
    ];
    let mut overrides = 0u32;
    while s.phase != engine::OVER {
        let seat = s.turn;
        let a = if seat == refined_seat {
            let puct = vsearch::choose_action(&s, seat, sims, &mut srng[seat]);
            let refined = endgame::refine(&s, seat, puct, &mut egrng[seat]);
            if refined != puct {
                overrides += 1;
            }
            refined
        } else {
            vsearch::choose_action(&s, seat, sims, &mut srng[seat])
        };
        engine::apply(&mut s, a);
    }
    let score = if s.winner == refined_seat as i32 {
        1.0
    } else if s.winner == (1 - refined_seat) as i32 {
        0.0
    } else {
        0.5
    };
    (score, overrides)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let sims: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(1200);
    let base_seeds: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(40);
    let threads: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(4);

    println!(
        "selfgate_endgame: refined-S vs plain-S, {sims} sims, {base_seeds} base seeds ({} paired games), {threads} threads",
        base_seeds * 2
    );

    let next = Arc::new(Mutex::new(0u64));
    // (refined score sum, games, total overrides, games with >=1 override, score in those games)
    let acc = Arc::new(Mutex::new((0.0f64, 0u64, 0u64, 0u64, 0.0f64)));
    let t0 = Instant::now();

    let mut handles = Vec::new();
    for _ in 0..threads {
        let next = Arc::clone(&next);
        let acc = Arc::clone(&acc);
        handles.push(thread::spawn(move || loop {
            let g = {
                let mut n = next.lock().unwrap();
                let v = *n;
                *n += 1;
                v
            };
            if g >= base_seeds {
                break;
            }
            // Paired: refined on seat 0, then refined on seat 1, same deck.
            let (s0, o0) = play_game(g, 0, sims);
            let (s1, o1) = play_game(g, 1, sims);
            let mut a = acc.lock().unwrap();
            a.0 += s0 + s1;
            a.1 += 2;
            a.2 += (o0 + o1) as u64;
            if o0 > 0 {
                a.3 += 1;
                a.4 += s0;
            }
            if o1 > 0 {
                a.3 += 1;
                a.4 += s1;
            }
            let rate = a.0 / a.1 as f64;
            println!(
                "  base {}/{} | {:.1}+{:.1} (ovr {}+{}) | rate {:.4} | {} games, {}s",
                g + 1, base_seeds, s0, s1, o0, o1, rate, a.1, t0.elapsed().as_secs()
            );
        }));
    }
    for h in handles {
        h.join().unwrap();
    }

    let (score, games, tot_ovr, ovr_games, ovr_score) = *acc.lock().unwrap();
    println!(
        "\nRESULT: refined-S win rate {:.4} over {} games ({sims} sims) in {:.0}s",
        score / games as f64, games, t0.elapsed().as_secs_f64()
    );
    println!(
        "  overrides: {} total across {} games; {} games had >=1 override (refined rate in those: {:.4})",
        tot_ovr, games, ovr_games,
        if ovr_games > 0 { ovr_score / ovr_games as f64 } else { 0.5 }
    );
}
