//! Rung 1 of the value-first ladder: is a self-play-learned value better than the hand-V at 1-ply
//! (where leaf quality matters MOST — no search to override it)? Plays a 1-ply-greedy player on the
//! learned value (`v1.json`) vs (a) H3 and (b) 1-ply-greedy on the hand v_state, paired CRN. All three
//! policies are deterministic, so each deck is played both seat-assignments and that's the only
//! variation (cancels the first-player edge).
//!
//! Usage: cargo run --release --features bridge --bin rung1 -- <v1.json> [decks] [threads]

use serde::Deserialize;
use spender_core::engine::{self, State, A_PASS};
use spender_core::feats;
use spender_core::heuristic;
use spender_core::v_state;
use spender_core::valuenet::{Mlp, StandardizedMlp};
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

const V: u8 = 0; // learned value, 1-ply
const VSTATE: u8 = 1; // hand v_state, 1-ply
const H3: u8 = 2; // heuristic greedy

#[inline]
fn terminal_value(s: &State, me: usize) -> f32 {
    if s.winner == me as i32 {
        1.0
    } else if s.winner == (1 - me) as i32 {
        -1.0
    } else {
        0.0
    }
}

/// 1-ply greedy on the learned value: pick the move maximizing the resulting position's value FROM ME.
fn value_1ply(net: &StandardizedMlp, s: &State, me: usize) -> usize {
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        return A_PASS;
    }
    let mut best = legal[0];
    let mut bestv = f32::NEG_INFINITY;
    for &a in &legal {
        let mut c = s.clone();
        engine::apply(&mut c, a);
        let v = if c.phase == engine::OVER {
            terminal_value(&c, me)
        } else {
            let raw: Vec<f32> = feats::features(&c, c.turn).iter().map(|&x| x as f32).collect();
            let vmover = net.forward_raw(&raw); // value from c.turn's perspective
            if c.turn == me { vmover } else { -vmover }
        };
        if v > bestv {
            bestv = v;
            best = a;
        }
    }
    best
}

/// 1-ply greedy on the hand v_state (the apples-to-apples "learned vs hand value at 1-ply" baseline).
fn vstate_1ply(s: &State, me: usize) -> usize {
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        return A_PASS;
    }
    let mut best = legal[0];
    let mut bestv = f32::NEG_INFINITY;
    for &a in &legal {
        let mut c = s.clone();
        engine::apply(&mut c, a);
        let v = v_state::value(&c, me) as f32; // already mover-agnostic (from me) + handles OVER
        if v > bestv {
            bestv = v;
            best = a;
        }
    }
    best
}

fn pick(tag: u8, net: &StandardizedMlp, s: &State, me: usize) -> usize {
    match tag {
        V => value_1ply(net, s, me),
        VSTATE => vstate_1ply(s, me),
        _ => heuristic::choose_action(s, me),
    }
}

/// Play one deterministic game; return policy-A's score (A controls seat `a_seat`). A MOVE CAP bounds
/// pathologically long games (a weak policy may never score → hundreds of plies): past the cap, decide
/// by points (then fewest cards), matching the engine tiebreak.
const PLY_CAP: i32 = 250;
fn play(deck: u64, a_seat: usize, a_tag: u8, b_tag: u8, net: &StandardizedMlp) -> f64 {
    let mut s = engine::new_game(deck, 15);
    while s.phase != engine::OVER && s.ply < PLY_CAP {
        let seat = s.turn;
        let tag = if seat == a_seat { a_tag } else { b_tag };
        let a = pick(tag, net, &s, seat);
        engine::apply(&mut s, a);
    }
    let win = if s.phase == engine::OVER {
        s.winner
    } else {
        // capped: decide by (points, -cards), like resolve_winner
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

fn arena(label: &str, a_tag: u8, b_tag: u8, decks: u64, threads: usize, net: Arc<StandardizedMlp>) {
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
            let s = play(g, 0, a_tag, b_tag, &net) + play(g, 1, a_tag, b_tag, &net);
            let mut a = acc.lock().unwrap();
            a.0 += s;
            a.1 += 2;
        }));
    }
    for h in hs {
        h.join().unwrap();
    }
    let (sc, n) = *acc.lock().unwrap();
    println!("  {label:<28} A win-rate {:.4}  ({} games)", sc / n as f64, n);
    use std::io::Write;
    std::io::stdout().flush().ok(); // unbuffer (println block-buffers when redirected to a file)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).cloned().unwrap_or_else(|| "v1.json".into());
    let decks: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(200);
    let threads: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(8);

    let raw = std::fs::read_to_string(&path).expect("read v1.json");
    let v1: V1 = serde_json::from_str(&raw).expect("parse v1.json");
    assert_eq!(v1.mu.len(), feats::n_features(), "feature-dim mismatch vs feats::features()");
    let mlp = Mlp::from_parts(v1.dims, v1.w, v1.b);
    let net = Arc::new(StandardizedMlp::new(mlp, v1.mu, v1.sd));
    println!(
        "rung1: learned-V 1-ply vs baselines, {decks} decks (x2 = {} games), {threads} threads, in_dim {}",
        decks * 2, net.in_dim()
    );
    arena("learned-V(1ply) vs H3", V, H3, decks, threads, Arc::clone(&net));
    arena("learned-V(1ply) vs vstate(1ply)", V, VSTATE, decks, threads, Arc::clone(&net));
    arena("[ref] vstate(1ply) vs H3", VSTATE, H3, decks, threads, Arc::clone(&net));
}
