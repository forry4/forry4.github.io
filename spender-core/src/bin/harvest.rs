//! #3 / value-net harvest: play S-vs-S self-play and log, per ply, the canonical feature vector
//! (`feats::features`) + v_state's own value + the eventual game OUTCOME from the mover's perspective.
//! Output is a CSV consumed by the offline value fit (Python). Feature encoding lives in `crate::feats`
//! (shared with the Rust 1-ply / MCTS-leaf players) so trained and served features byte-match.
//!
//! Usage: cargo run --release --bin harvest [games] [sims] [threads] [outfile]

use spender_core::engine::{self, State};
use spender_core::feats::{features, header};
use spender_core::rng::Rng;
use spender_core::vsearch;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

/// Play one S-vs-S game; return per-ply (mover, feature row) plus the final winner.
fn play_and_record(deck_seed: u64, sims: usize) -> (Vec<(usize, Vec<f64>)>, i32) {
    let mut s: State = engine::new_game(deck_seed, 15);
    let mut rng = [
        Rng::new(0xA11CE ^ (deck_seed << 1)),
        Rng::new(0xB0B ^ (deck_seed << 1)),
    ];
    let mut rows: Vec<(usize, Vec<f64>)> = Vec::new();
    while s.phase != engine::OVER {
        let seat = s.turn;
        if s.phase == engine::PLAY {
            rows.push((seat, features(&s, seat)));
        }
        let a = vsearch::choose_action(&s, seat, sims, &mut rng[seat]);
        engine::apply(&mut s, a);
    }
    (rows, s.winner)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let games: u64 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(2000);
    let sims: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(200);
    let threads: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(6);
    let outfile = args.get(4).cloned().unwrap_or_else(|| "harvest.csv".into());

    let file = File::create(&outfile).expect("create outfile");
    let mut w = BufWriter::new(file);
    writeln!(w, "{}", header()).unwrap();
    let writer = Arc::new(Mutex::new(w));
    let next = Arc::new(Mutex::new(0u64));
    let rowcount = Arc::new(Mutex::new(0u64));
    let t0 = Instant::now();

    println!("harvest: {games} S-vs-S games @ {sims} sims, {threads} threads -> {outfile}");

    let mut handles = Vec::new();
    for _ in 0..threads {
        let next = Arc::clone(&next);
        let writer = Arc::clone(&writer);
        let rowcount = Arc::clone(&rowcount);
        handles.push(thread::spawn(move || loop {
            let g = {
                let mut n = next.lock().unwrap();
                let v = *n;
                *n += 1;
                v
            };
            if g >= games {
                break;
            }
            let (rows, winner) = play_and_record(g, sims);
            let mut buf = String::new();
            for (mover, feat) in &rows {
                let label = if winner == *mover as i32 {
                    1.0
                } else if winner == (1 - *mover) as i32 {
                    0.0
                } else {
                    0.5
                };
                for (i, x) in feat.iter().enumerate() {
                    if i > 0 {
                        buf.push(',');
                    }
                    buf.push_str(&format!("{x}"));
                }
                buf.push_str(&format!(",{label}\n"));
            }
            let nrows = rows.len() as u64;
            {
                let mut wl = writer.lock().unwrap();
                wl.write_all(buf.as_bytes()).unwrap();
            }
            let total = {
                let mut rc = rowcount.lock().unwrap();
                *rc += nrows;
                *rc
            };
            if g % 100 == 0 {
                println!("  game {}/{} | {} rows | {}s", g, games, total, t0.elapsed().as_secs());
            }
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    writer.lock().unwrap().flush().unwrap();
    let total = *rowcount.lock().unwrap();
    println!(
        "DONE: {} rows from {} games in {:.0}s -> {}",
        total, games, t0.elapsed().as_secs_f64(), outfile
    );
}
