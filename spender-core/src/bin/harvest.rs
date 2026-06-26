//! #3 premise-test harvest: play S-vs-S self-play and log, per ply, a rich feature vector + v_state's
//! OWN value (the baseline to beat) + the eventual game OUTCOME from the mover's perspective. Output is
//! a CSV consumed by an offline fit (Python) that asks the decisive question: can a leaf trained on
//! game OUTCOMES (not V_search — that's horizon-limited and known to wash out) predict the result —
//! ESPECIALLY early-game — better than v_state? If yes, a learned leaf carries beyond-search-horizon
//! development signal that search can't recover (so it wouldn't wash out at high sims); if it only
//! matches v_state, the leaf is saturated and #3 pivots.
//!
//! Usage: cargo run --release --bin harvest [games] [sims] [threads] [outfile]

use spender_core::cards::{COST, PTS};
use spender_core::engine::{self, State};
use spender_core::heuristic::{W_GEM, W_GOLD, W_TEMPO};
use spender_core::rng::Rng;
use spender_core::v_state;
use spender_core::valuation::{self, Valuation};
use spender_core::vsearch;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Instant;

/// Feature vector for `seat` to move in `s`. Order MUST match `header()`.
fn features(s: &State, seat: usize) -> Vec<f64> {
    let opp = 1 - seat;
    let val = Valuation::new(s, W_TEMPO, W_GEM, W_GOLD);
    let mut f: Vec<f64> = Vec::with_capacity(96);

    // meta
    f.push(s.ply as f64);
    f.push(seat as f64);
    f.push(s.final_trigger as f64);
    f.push(s.win_points as f64);

    // v_state baseline (the value to beat) — from the mover's perspective
    f.push(v_state::value_with(&val, seat));

    // per-seat raw state (me then opp)
    for &p in &[seat, opp] {
        f.push(s.points[p] as f64);
        f.push(s.purchased_n[p] as f64);
        f.push(s.reserved[p].len() as f64);
        f.push(s.tokens[p].iter().sum::<i32>() as f64);
        f.push(s.tokens[p][5] as f64); // gold
        for c in 0..5 {
            f.push(s.bonuses[p][c] as f64);
        }
        for c in 0..5 {
            f.push(s.tokens[p][c] as f64);
        }
    }

    // bank
    for c in 0..6 {
        f.push(s.bank[c] as f64);
    }

    // v_state components (me, opp) — pre-weight terms; a fit over JUST these tests weight-tuning
    for &p in &[seat, opp] {
        let tg = v_state::seat_targets(&val, p, false);
        f.push(v_state::points_term(&val, p));
        f.push(v_state::engine_stock(&val, p));
        f.push(v_state::progress(&tg));
        f.push(v_state::noble_stand(&val, p));
        f.push(v_state::econ(&val, p, &tg));
    }

    // board cards: points + affordability gap for me/opp (-1 sentinels for empty slots)
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 {
            f.push(PTS[ci as usize] as f64);
            f.push(valuation::gold_needed(s, ci, seat) as f64);
            f.push(valuation::gold_needed(s, ci, opp) as f64);
        } else {
            f.push(-1.0);
            f.push(-1.0);
            f.push(-1.0);
        }
    }

    // nobles: bonus deficit for me/opp (-1 for empty slots)
    use spender_core::cards::NOBLE_REQ;
    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni >= 0 {
            let req = &NOBLE_REQ[ni as usize];
            let def = |p: usize| -> i32 {
                (0..5).map(|c| (req[c] - s.bonuses[p][c]).max(0)).sum()
            };
            f.push(def(seat) as f64);
            f.push(def(opp) as f64);
        } else {
            f.push(-1.0);
            f.push(-1.0);
        }
    }

    // undealt deck remaining per level + per-color undealt cost (board-replenishment supply signal)
    let mut lvl_rem = [0.0f64; 3];
    let mut color_cost = [0.0f64; 5];
    for lvl in 0..3 {
        lvl_rem[lvl] = s.decks[lvl].len() as f64;
        for &ci in &s.decks[lvl] {
            for c in 0..5 {
                color_cost[c] += COST[ci as usize][c] as f64;
            }
        }
    }
    f.extend_from_slice(&lvl_rem);
    f.extend_from_slice(&color_cost);

    f
}

fn header() -> String {
    let mut h: Vec<String> = vec![
        "ply".into(), "mover".into(), "final_trigger".into(), "win_points".into(), "vstate".into(),
    ];
    for who in ["me", "opp"] {
        for n in ["points", "npurch", "nresv", "ntok", "gold"] {
            h.push(format!("{who}_{n}"));
        }
        for c in 0..5 {
            h.push(format!("{who}_bon{c}"));
        }
        for c in 0..5 {
            h.push(format!("{who}_tok{c}"));
        }
    }
    for c in 0..6 {
        h.push(format!("bank{c}"));
    }
    for who in ["me", "opp"] {
        for n in ["ptsterm", "engstock", "progress", "noble", "econ"] {
            h.push(format!("{who}_{n}"));
        }
    }
    for slot in 0..12 {
        h.push(format!("bd{slot}_pts"));
        h.push(format!("bd{slot}_myneed"));
        h.push(format!("bd{slot}_oppneed"));
    }
    for slot in 0..3 {
        h.push(format!("nb{slot}_mydef"));
        h.push(format!("nb{slot}_oppdef"));
    }
    for lvl in 0..3 {
        h.push(format!("deck{lvl}_rem"));
    }
    for c in 0..5 {
        h.push(format!("deckcost{c}"));
    }
    h.push("label".into()); // outcome from mover's view: 1.0 win / 0.5 draw / 0.0 loss
    h.join(",")
}

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
        // Only record PLAY decisions (the leaf is what the search evaluates there).
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
            // Label each ply by its mover's outcome.
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
                println!(
                    "  game {}/{} | {} rows | {}s",
                    g, games, total, t0.elapsed().as_secs()
                );
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
