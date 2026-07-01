//! ATTN vs ATTN gate: pit two card-set-attention nets (A vs B) via determinized PUCT
//! (root_visits_until_pv), paired CRN (each deck played both A-seat ways) -> unbiased A win-rate vs B.
//! Use: measure whether a value-debiased net (A) actually out-plays the original (B). When A and B share
//! everything but the value head, this isolates whether the value correction improves search play.
//! Usage: gate_attn2 <A.json> <B.json> [games] [sims] [threads] [deck_base] [win_points]
use spender_core::attn::AttnNet;
use spender_core::engine::{self, State};
use spender_core::feats::features_tokens;
use spender_core::{rng::Rng, vsearch};
use std::sync::{Arc, Mutex};
use std::thread;

const PLY_CAP: i32 = 250;

fn argmax_move(v: &[i32], s: &State) -> usize {
    let legal = engine::legal_actions(s);
    if legal.is_empty() { return engine::A_PASS; }
    let mut best = legal[0]; let mut bv = v[legal[0]];
    for &x in &legal[1..] { if v[x] > bv { bv = v[x]; best = x; } }
    best
}

fn attn_move(net: &AttnNet, s: &State, seat: usize, sims: usize, rng: &mut Rng) -> usize {
    let pv = |st: &State, sd: usize| -> (f64, Vec<f64>) {
        let (t, m, state) = features_tokens(st, sd);
        net.forward(&t, &m, &state)
    };
    let v = vsearch::root_visits_until_pv(s, seat, rng, |n| n < sims, &pv);
    argmax_move(&v, s)
}

fn play(deck: u64, sims: usize, a: &AttnNet, b: &AttnNet, a_seat: usize, wp: i32) -> f64 {
    let mut s = engine::new_game(deck, wp);
    let mut rng = [Rng::new(0xA771 ^ (deck << 1)), Rng::new(0xA772 ^ (deck << 1))];
    while s.phase != engine::OVER && s.ply < PLY_CAP {
        let seat = s.turn;
        let mv = if seat == a_seat { attn_move(a, &s, seat, sims, &mut rng[seat]) }
                 else { attn_move(b, &s, seat, sims, &mut rng[seat]) };
        engine::apply(&mut s, mv);
    }
    let win = if s.phase == engine::OVER { s.winner } else {
        let k0 = (s.points[0], -s.purchased_n[0]); let k1 = (s.points[1], -s.purchased_n[1]);
        if k0 > k1 { 0 } else if k1 > k0 { 1 } else { engine::WIN_DRAW }
    };
    if win == a_seat as i32 { 1.0 } else if win == (1 - a_seat) as i32 { 0.0 } else { 0.5 }
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let a_path = a.get(1).cloned().expect("usage: gate_attn2 <A.json> <B.json> ...");
    let b_path = a.get(2).cloned().expect("need B.json");
    let games: u64 = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(120);
    let sims: usize = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(128);
    let threads: usize = a.get(5).and_then(|s| s.parse().ok()).unwrap_or(6);
    let deck_base: u64 = a.get(6).and_then(|s| s.parse().ok()).unwrap_or(880_000_000);
    let wp: i32 = a.get(7).and_then(|s| s.parse().ok()).unwrap_or(15);

    let na = Arc::new(AttnNet::from_json(&a_path));
    let nb = Arc::new(AttnNet::from_json(&b_path));
    println!("gate_attn2: A={} vs B={} @ {} sims, wp {}", a_path, b_path, sims, wp);
    let total = games * 2;
    let next = Arc::new(Mutex::new(0u64));
    let score = Arc::new(Mutex::new(0.0f64));
    let mut handles = Vec::new();
    for _ in 0..threads {
        let (next, score, na, nb) = (Arc::clone(&next), Arc::clone(&score), Arc::clone(&na), Arc::clone(&nb));
        handles.push(thread::spawn(move || loop {
            let t = { let mut n = next.lock().unwrap(); let v = *n; *n += 1; v };
            if t >= total { break; }
            let r = play(deck_base + (t / 2), sims, &na, &nb, (t % 2) as usize, wp);
            *score.lock().unwrap() += r;
        }));
    }
    for h in handles { h.join().unwrap(); }
    let wr = *score.lock().unwrap() / total as f64;
    let se = (wr * (1.0 - wr) / total as f64).sqrt();
    println!("RESULT [gate_attn2]: A win-rate {:.4} +-{:.4} vs B over {} games @ {} sims, wp {}", wr, se, total, sims, wp);
}
