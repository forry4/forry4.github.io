//! Phase 0: measure Rust-CPU value-net inference throughput vs net size, and translate it into
//! self-play feasibility (the number that gates the affordable architecture). Single-threaded evals/s
//! per core × cores × the rung-2 MCTS budget → self-play games/hour.
//!
//! Usage: cargo run --release --bin net_bench [evals_per_net] [cores] [sims_per_move] [moves_per_game]

use spender_core::valuenet::{AttnNet, Mlp};
use std::time::Instant;

fn bench_mlp(name: &str, dims: &[usize], iters: usize) -> f64 {
    let net = Mlp::random(dims, 42);
    let x: Vec<f32> = (0..dims[0]).map(|i| ((i % 7) as f32) * 0.1 - 0.3).collect();
    // warmup
    let mut acc = 0.0f32;
    for _ in 0..2000 {
        acc += net.forward(&x);
    }
    let t = Instant::now();
    for _ in 0..iters {
        acc += net.forward(&x);
    }
    let el = t.elapsed().as_secs_f64();
    let eps = iters as f64 / el;
    println!(
        "  {name:<22} dims {:?}  ->  {:>10.0} evals/s/core  ({:.2} us/eval)  [sink {:.3}]",
        dims, eps, 1e6 / eps, acc
    );
    eps
}

fn bench_attn(name: &str, t: usize, d: usize, hh: usize, iters: usize) -> f64 {
    let net = AttnNet::random(t, d, hh, 7);
    let tokens: Vec<f32> = (0..t * d).map(|i| ((i % 11) as f32) * 0.05 - 0.2).collect();
    let mut acc = 0.0f32;
    for _ in 0..1000 {
        acc += net.forward(&tokens);
    }
    let tm = Instant::now();
    for _ in 0..iters {
        acc += net.forward(&tokens);
    }
    let el = tm.elapsed().as_secs_f64();
    let eps = iters as f64 / el;
    println!(
        "  {name:<22} T={t} d={d} head={hh}  ->  {:>10.0} evals/s/core  ({:.2} us/eval)  [sink {:.3}]",
        eps, 1e6 / eps, acc
    );
    eps
}

fn feasibility(label: &str, eps_per_core: f64, cores: f64, sims: f64, moves: f64) {
    let evals_per_game = sims * moves; // 1 leaf eval per MCTS sim, sims per move, moves per game
    let games_per_sec = eps_per_core * cores / evals_per_game;
    let games_per_hour = games_per_sec * 3600.0;
    println!(
        "  {label:<22} {:>8.0} games/hour  ({:.1} games/s)  | 10k games in {:.1} min",
        games_per_hour, games_per_sec, 10_000.0 / games_per_sec / 60.0
    );
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let iters: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(300_000);
    let cores: f64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(10.0);
    let sims: f64 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(400.0);
    let moves: f64 = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(56.0);

    println!("=== Rust-CPU value-net inference throughput (single core, {iters} evals each) ===");
    let m_s = bench_mlp("MLP-S [128,256,1]", &[128, 256, 1], iters);
    let m_m = bench_mlp("MLP-M [128,256,256,1]", &[128, 256, 256, 1], iters);
    let m_l = bench_mlp("MLP-L [128,512,512,1]", &[128, 512, 512, 1], iters);
    let a_s = bench_attn("Attn-S T18 d48", 18, 48, 128, iters / 4);
    let a_m = bench_attn("Attn-M T18 d64", 18, 64, 128, iters / 4);

    println!(
        "\n=== self-play feasibility ({cores:.0} cores, {sims:.0} sims/move, {moves:.0} moves/game) ===\n  (1 leaf eval / MCTS sim; the H3 prior reuses the existing fast path)"
    );
    feasibility("MLP-S", m_s, cores, sims, moves);
    feasibility("MLP-M", m_m, cores, sims, moves);
    feasibility("MLP-L", m_l, cores, sims, moves);
    feasibility("Attn-S", a_s, cores, sims, moves);
    feasibility("Attn-M", a_m, cores, sims, moves);
    println!(
        "\n  (context: v_state leaf serves ~1500-2100 clean sims/s; for rung-1 1-ply self-play, evals/game ≈ moves only, ~{:.0}x cheaper than rung-2.)",
        sims
    );
}
