//! Un-anchored self-play harvester: N plays ITSELF (the learned value leaf + H3 prior, in search) and
//! logs per-ply (features, mover, eventual OUTCOME). This is the engine of the value-first self-play
//! loop — the value bootstraps on its OWN increasingly-strong play, beyond S's distribution (unlike the
//! S-vs-S `harvest`). Same CSV schema as `harvest` (feats::header).
//!
//! Usage: cargo run --release --features bridge --bin harvest_n -- <net.json> [games] [sims] [threads] [outfile] [deck_base]

use serde::Deserialize;
use spender_core::engine::{self, State};
use spender_core::feats::{self, features, header};
use spender_core::valuenet::{Mlp, StandardizedMlp};
use spender_core::{rng::Rng, vsearch};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

#[derive(Deserialize)]
struct V1 { dims: Vec<usize>, w: Vec<Vec<f32>>, b: Vec<Vec<f32>>, mu: Vec<f32>, sd: Vec<f32> }

const PLY_CAP: i32 = 250;

/// One N-vs-N game (both seats = learned-leaf search). Returns per-ply (mover, features) + winner.
fn play_and_record(deck: u64, sims: usize, net: &StandardizedMlp) -> (Vec<(usize, Vec<f64>)>, i32) {
    let leaf = |st: &State, sd: usize| -> f64 {
        let raw: Vec<f32> = feats::features(st, sd).iter().map(|&x| x as f32).collect();
        net.forward_raw(&raw) as f64
    };
    let mut s = engine::new_game(deck, 15);
    let mut rng = [Rng::new(0x4E01 ^ (deck << 1)), Rng::new(0x4E02 ^ (deck << 1))];
    let mut rows: Vec<(usize, Vec<f64>)> = Vec::new();
    while s.phase != engine::OVER && s.ply < PLY_CAP {
        let seat = s.turn;
        if s.phase == engine::PLAY {
            rows.push((seat, features(&s, seat)));
        }
        let a = vsearch::choose_action_leaf(&s, seat, sims, &mut rng[seat], &leaf);
        engine::apply(&mut s, a);
    }
    let winner = if s.phase == engine::OVER {
        s.winner
    } else {
        let k0 = (s.points[0], -s.purchased_n[0]);
        let k1 = (s.points[1], -s.purchased_n[1]);
        if k0 > k1 { 0 } else if k1 > k0 { 1 } else { engine::WIN_DRAW }
    };
    (rows, winner)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).cloned().unwrap_or_else(|| "v1_gpu.json".into());
    let games: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2000);
    let sims: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(200);
    let threads: usize = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(10);
    let outfile = args.get(5).cloned().unwrap_or_else(|| "data_n.csv".into());
    let deck_base: u64 = args.get(6).and_then(|s| s.parse().ok()).unwrap_or(2_000_000);

    let raw = std::fs::read_to_string(&path).expect("read net json");
    let v1: V1 = serde_json::from_str(&raw).expect("parse net json");
    assert_eq!(v1.mu.len(), feats::n_features(), "feature-dim mismatch");
    let net = Arc::new(StandardizedMlp::new(Mlp::from_parts(v1.dims, v1.w, v1.b), v1.mu, v1.sd));

    let file = File::create(&outfile).expect("create outfile");
    let mut w = BufWriter::new(file);
    writeln!(w, "{}", header()).unwrap();
    let writer = Arc::new(Mutex::new(w));
    let next = Arc::new(Mutex::new(0u64));
    let rowcount = Arc::new(Mutex::new(0u64));
    let t0 = Instant::now();
    println!("harvest_n: {games} N-vs-N games @ {sims} sims, {threads} threads, deck_base {deck_base} -> {outfile}");

    let mut handles = Vec::new();
    for _ in 0..threads {
        let (next, writer, rowcount, net) = (Arc::clone(&next), Arc::clone(&writer), Arc::clone(&rowcount), Arc::clone(&net));
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
            let (rows, winner) = play_and_record(deck_base + g, sims, &net);
            let mut buf = String::new();
            for (mover, feat) in &rows {
                let label = if winner == *mover as i32 { 1.0 } else if winner == (1 - *mover) as i32 { 0.0 } else { 0.5 };
                for (i, x) in feat.iter().enumerate() {
                    if i > 0 { buf.push(','); }
                    buf.push_str(&format!("{x}"));
                }
                buf.push_str(&format!(",{label}\n"));
            }
            let nrows = rows.len() as u64;
            writer.lock().unwrap().write_all(buf.as_bytes()).unwrap();
            let total = { let mut rc = rowcount.lock().unwrap(); *rc += nrows; *rc };
            if g % 200 == 0 {
                println!("  game {}/{} | {} rows | {}s", g, games, total, t0.elapsed().as_secs());
                use std::io::Write as _;
                std::io::stdout().flush().ok();
            }
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    writer.lock().unwrap().flush().unwrap();
    println!("DONE: {} rows from {} games in {:.0}s -> {}", *rowcount.lock().unwrap(), games, t0.elapsed().as_secs_f64(), outfile);
}
