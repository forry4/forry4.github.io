//! Rung 2 of the value-first ladder: does the learned value, used as the MCTS LEAF (+ the H3 prior),
//! converge toward S — where 1-ply's fine-grained-noise penalty washes out? Plays S-with-learned-leaf
//! vs S-with-v_state-leaf, paired CRN, at matched sims. >=0.5 would mean the learned value converts
//! through search (green-light the self-play build); far below means the value-leaf path is weak.
//!
//! Usage: cargo run --release --features bridge --bin rung2 -- <v1.json> [decks] [sims] [threads]

use serde::Deserialize;
use spender_core::engine::{self, State};
use spender_core::valuenet::{Mlp, StandardizedMlp};
use spender_core::{feats, heuristic, rng::Rng, v_state, vsearch};
use std::sync::{Arc, Mutex};
use std::thread;

#[derive(Deserialize)]
struct V1 {
    dims: Vec<usize>,
    w: Vec<Vec<f32>>,
    b: Vec<Vec<f32>>,
    mu: Vec<f32>,
    sd: Vec<f32>,
}

const PLY_CAP: i32 = 250;

/// One game: seat `a_seat` = S-with-A-leaf, other = S-with-v_state-leaf (the default `choose_action`).
/// `ctrl`=true makes the A-leaf *also* v_state (control: must come out ~0.5 if the harness is unbiased).
fn play(deck: u64, a_seat: usize, a_sims: usize, b_sims: usize, net: &StandardizedMlp, ctrl: bool, b_h3: bool) -> f64 {
    let leaf = |st: &State, sd: usize| -> f64 {
        if ctrl {
            return v_state::value(st, sd);
        }
        let raw: Vec<f32> = feats::features(st, sd).iter().map(|&x| x as f32).collect();
        net.forward_raw(&raw) as f64
    };
    let mut s = engine::new_game(deck, 15);
    let mut srng = [
        Rng::new(0x5EED_0000 ^ (deck << 2)),
        Rng::new(0x5EED_0001 ^ (deck << 2)),
    ];
    while s.phase != engine::OVER && s.ply < PLY_CAP {
        let seat = s.turn;
        let a = if seat == a_seat {
            vsearch::choose_action_leaf(&s, seat, a_sims, &mut srng[seat], &leaf) // A = learned (or v_state ctrl) leaf, search
        } else if b_h3 {
            heuristic::choose_action(&s, seat) // B = H3 (1-ply panel opponent)
        } else {
            vsearch::choose_action(&s, seat, b_sims, &mut srng[seat]) // B = v_state leaf, search
        };
        engine::apply(&mut s, a);
    }
    let win = if s.phase == engine::OVER {
        s.winner
    } else {
        let k0 = (s.points[0], -s.purchased_n[0]);
        let k1 = (s.points[1], -s.purchased_n[1]);
        if k0 > k1 { 0 } else if k1 > k0 { 1 } else { engine::WIN_DRAW }
    };
    if win == a_seat as i32 {
        1.0
    } else if win == (1 - a_seat) as i32 {
        0.0
    } else {
        0.5
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).cloned().unwrap_or_else(|| "v1_gpu.json".into());
    let decks: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(40);
    let sims: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(400);
    let threads: usize = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(8);
    // arg5 mode: net (learned vs v_state-search) | ctrl (v_state vs v_state-search) |
    //            h3 (learned vs H3) | ctrlh3 (v_state-search vs H3, the panel baseline)
    let mode = args.get(5).map(|s| s.as_str()).unwrap_or("net");
    let ctrl = mode == "ctrl" || mode == "ctrlh3";
    let b_h3 = mode == "h3" || mode == "ctrlh3";
    // deck_base offsets the deck seeds — set it past the harvest's training range (0..6000) for an
    // OUT-OF-SAMPLE test (the net never saw these decks' positions).
    let deck_base: u64 = args.get(6).and_then(|s| s.parse().ok()).unwrap_or(0);
    // b_sims = v_state seat's sims (default = a_sims). For an EQUAL-TIME test, give the learned seat
    // FEWER sims (it's ~2x heavier/sim) e.g. a_sims=600 b_sims=1200.
    let b_sims: usize = args.get(7).and_then(|s| s.parse().ok()).unwrap_or(sims);

    let raw = std::fs::read_to_string(&path).expect("read v1.json");
    let v1: V1 = serde_json::from_str(&raw).expect("parse v1.json");
    assert_eq!(v1.mu.len(), feats::n_features(), "feature-dim mismatch");
    let net = Arc::new(StandardizedMlp::new(Mlp::from_parts(v1.dims, v1.w, v1.b), v1.mu, v1.sd));
    let a_name = if ctrl { "v_state" } else { "learned" };
    let b_name = if b_h3 { "H3(1ply)".to_string() } else { format!("v_state@{b_sims}") };
    println!(
        "rung2 [{mode}]: A=S({a_name}-leaf @{sims}) vs B={b_name}, {decks} decks (x2={} games), {threads} threads, base {deck_base}",
        decks * 2
    );

    let next = Arc::new(Mutex::new(0u64));
    let acc = Arc::new(Mutex::new((0.0f64, 0u64)));
    let mut hs = Vec::new();
    for _ in 0..threads {
        let (next, acc, net) = (Arc::clone(&next), Arc::clone(&acc), Arc::clone(&net));
        hs.push(thread::spawn(move || loop {
            let g = {
                let mut n = next.lock().unwrap();
                let v = *n;
                *n += 1;
                v
            };
            if g >= decks {
                break;
            }
            let d = deck_base + g;
            let sc = play(d, 0, sims, b_sims, &net, ctrl, b_h3) + play(d, 1, sims, b_sims, &net, ctrl, b_h3);
            let mut a = acc.lock().unwrap();
            a.0 += sc;
            a.1 += 2;
            println!("  deck {}/{} | running learned-leaf rate {:.4} ({} games)", g + 1, decks, a.0 / a.1 as f64, a.1);
            use std::io::Write;
            std::io::stdout().flush().ok();
        }));
    }
    for h in hs {
        h.join().unwrap();
    }
    let (sc, n) = *acc.lock().unwrap();
    println!("\nRESULT [{mode}]: A=S({a_name}-leaf@{sims}) win-rate {:.4} vs B={b_name} over {} games", sc / n as f64, n);
}
