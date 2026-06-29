//! Gate the CARD-SET ATTENTION net vs net_night_14 (MLP, variant N), both via determinized PUCT
//! (root_visits_until_pv): the attn net evaluates leaves via `attn::AttnNet` on `features_tokens`; N via
//! its 178-feat `features_ext` MLP. Paired CRN (each deck both attn-seat ways) -> unbiased. Reports the
//! ATTN net's win-rate vs N. SANITY use: attn_warm (clean distill of N) should land ~0.5; a trained
//! attn net climbing >0.5 = attention beat the MLP.
//! Usage: gate_attn <attn.json> <mlp178.json> [games] [sims] [threads] [deck_base] [win_points]
use serde::Deserialize;
use spender_core::attn::AttnNet;
use spender_core::engine::{self, State};
use spender_core::feats::{features_ext, features_tokens};
use spender_core::valuenet::PolicyValueNet;
use spender_core::{rng::Rng, vsearch};
use std::sync::{Arc, Mutex};
use std::thread;

#[derive(Deserialize)]
struct PVJson {
    mu: Vec<f32>, sd: Vec<f32>, tdims: Vec<usize>,
    tw: Vec<Vec<f32>>, tb: Vec<Vec<f32>>,
    vw: Vec<f32>, vb: Vec<f32>, pw: Vec<f32>, pb: Vec<f32>, n_act: usize,
}
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

fn mlp_move(net: &PolicyValueNet, s: &State, seat: usize, sims: usize, rng: &mut Rng) -> usize {
    let pv = |st: &State, sd: usize| -> (f64, Vec<f64>) {
        let raw: Vec<f32> = features_ext(st, sd).iter().map(|&x| x as f32).collect();
        let (v, logits) = net.forward_raw(&raw);
        (v as f64, logits.iter().map(|&x| x as f64).collect())
    };
    let v = vsearch::root_visits_until_pv(s, seat, rng, |n| n < sims, &pv);
    argmax_move(&v, s)
}

fn play(deck: u64, sims: usize, attn: &AttnNet, mlp: &PolicyValueNet, attn_seat: usize, wp: i32) -> f64 {
    let mut s = engine::new_game(deck, wp);
    let mut rng = [Rng::new(0xA771 ^ (deck << 1)), Rng::new(0xA772 ^ (deck << 1))];
    while s.phase != engine::OVER && s.ply < PLY_CAP {
        let seat = s.turn;
        let a = if seat == attn_seat { attn_move(attn, &s, seat, sims, &mut rng[seat]) }
                else { mlp_move(mlp, &s, seat, sims, &mut rng[seat]) };
        engine::apply(&mut s, a);
    }
    let win = if s.phase == engine::OVER { s.winner } else {
        let k0 = (s.points[0], -s.purchased_n[0]); let k1 = (s.points[1], -s.purchased_n[1]);
        if k0 > k1 { 0 } else if k1 > k0 { 1 } else { engine::WIN_DRAW }
    };
    if win == attn_seat as i32 { 1.0 } else if win == (1 - attn_seat) as i32 { 0.0 } else { 0.5 }
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let attn_path = a.get(1).cloned().expect("usage: gate_attn <attn.json> <mlp178.json> ...");
    let mlp_path = a.get(2).cloned().expect("need mlp178.json");
    let games: u64 = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(120);
    let sims: usize = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(128);
    let threads: usize = a.get(5).and_then(|s| s.parse().ok()).unwrap_or(6);
    let deck_base: u64 = a.get(6).and_then(|s| s.parse().ok()).unwrap_or(880_000_000);
    let wp: i32 = a.get(7).and_then(|s| s.parse().ok()).unwrap_or(15);

    let attn = Arc::new(AttnNet::from_json(&attn_path));
    let j: PVJson = serde_json::from_str(&std::fs::read_to_string(&mlp_path).expect("read mlp")).expect("parse mlp");
    assert_eq!(j.mu.len(), 178, "mlp must be the 178-feat net (net_night_14)");
    let mlp = Arc::new(PolicyValueNet::from_parts(j.mu, j.sd, j.tdims, j.tw, j.tb, j.vw, j.vb, j.pw, j.pb, j.n_act));
    println!("gate_attn: {} vs {} @ {} sims, win_points {}", attn_path, mlp_path, sims, wp);
    let total = games * 2;
    let next = Arc::new(Mutex::new(0u64));
    let score = Arc::new(Mutex::new(0.0f64));
    let mut handles = Vec::new();
    for _ in 0..threads {
        let (next, score, attn, mlp) = (Arc::clone(&next), Arc::clone(&score), Arc::clone(&attn), Arc::clone(&mlp));
        handles.push(thread::spawn(move || loop {
            let t = { let mut n = next.lock().unwrap(); let v = *n; *n += 1; v };
            if t >= total { break; }
            let r = play(deck_base + (t / 2), sims, &attn, &mlp, (t % 2) as usize, wp);
            *score.lock().unwrap() += r;
        }));
    }
    for h in handles { h.join().unwrap(); }
    let wr = *score.lock().unwrap() / total as f64;
    let se = (wr * (1.0 - wr) / total as f64).sqrt();
    println!("RESULT [gate_attn]: ATTN win-rate {:.4} +-{:.4} vs net_night_14 over {} games @ {} sims, wp {}", wr, se, total, sims, wp);
}
