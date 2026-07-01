//! Score a wwsd racer benchmark (wwsd/analyze_games.py --benchmark) with a serving attention net.
//! For each bot-turn position (engine-space State dump), run feats::features_tokens -> attn value, and
//! emit {net_value, search_value(recorded), label(eventual outcome), hard} to CSV. This measures how the
//! STATIC value head reads the positions the deployed net misjudged (the search values were recorded live).
//!
//! Build+run (from spender-core, with the bridge feature that enables AttnNet::from_json):
//!   cargo run --release --features bridge --bin score_bench -- BENCH.json NET.json OUT.csv
use serde::Deserialize;
use spender_core::attn::AttnNet;
use spender_core::engine::State;
use spender_core::feats;

// Mirror of wasm.rs::Dump (the exact engine-space State the WASM/wwsd logger emits).
#[derive(Deserialize)]
struct Dump {
    bank: [i32; 6],
    tokens: [[i32; 6]; 2],
    bonuses: [[i32; 5]; 2],
    points: [i32; 2],
    purchased_n: [i32; 2],
    purchased: [Vec<i32>; 2],
    reserved: [Vec<i32>; 2],
    reserved_blind: [Vec<bool>; 2],
    nobles_won: [Vec<i32>; 2],
    board: [i32; 12],
    decks: [Vec<i32>; 3],
    nobles: [i32; 3],
    turn: usize,
    phase: u8,
    pending_nobles: Vec<usize>,
    final_trigger: i32,
    winner: i32,
    ply: i32,
    win_points: i32,
}
#[derive(Deserialize)]
struct Pos { ply: i32, value: f64, label: f64, hard: bool, dump: Dump }
#[derive(Deserialize)]
struct Game { #[serde(rename = "gameId")] game_id: String, positions: Vec<Pos> }
#[derive(Deserialize)]
struct Bench { games: Vec<Game> }

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let bench_path = args.get(1).map(|s| s.as_str()).unwrap_or("racer_benchmark.json");
    let net_path = args.get(2).map(|s| s.as_str()).unwrap_or("net_attn_3.json");
    let out_path = args.get(3).map(|s| s.as_str()).unwrap_or("bench_scored.csv");

    let net = AttnNet::from_json(net_path);
    let bench: Bench = serde_json::from_str(&std::fs::read_to_string(bench_path).expect("read bench"))
        .expect("parse bench");

    let mut rows = String::from("gid,ply,seat,net_value,search_value,label,hard\n");
    let (mut n, mut n_hard) = (0usize, 0usize);
    // aggregates: net value on hard-loss positions, and calibration accumulators
    let (mut hard_sum, mut hard_n) = (0f64, 0usize);
    let (mut loss_net_sum, mut loss_n) = (0f64, 0usize);
    let (mut win_net_sum, mut win_n) = (0f64, 0usize);
    // for AUC: collect (net_value, is_win) over decisive positions
    let mut pts: Vec<(f64, bool)> = Vec::new();

    for g in &bench.games {
        for p in &g.positions {
            let seat = p.dump.turn;
            if seat > 1 { continue; }
            let s = { // p.dump is borrowed and State's Vec fields aren't Copy, so rebuild by field
                State {
                    bank: p.dump.bank,
                    tokens: p.dump.tokens,
                    bonuses: p.dump.bonuses,
                    points: p.dump.points,
                    purchased_n: p.dump.purchased_n,
                    purchased: [p.dump.purchased[0].clone(), p.dump.purchased[1].clone()],
                    reserved: [p.dump.reserved[0].clone(), p.dump.reserved[1].clone()],
                    reserved_blind: [p.dump.reserved_blind[0].clone(), p.dump.reserved_blind[1].clone()],
                    nobles_won: [p.dump.nobles_won[0].clone(), p.dump.nobles_won[1].clone()],
                    board: p.dump.board,
                    decks: [p.dump.decks[0].clone(), p.dump.decks[1].clone(), p.dump.decks[2].clone()],
                    nobles: p.dump.nobles,
                    turn: p.dump.turn,
                    phase: p.dump.phase,
                    pending_nobles: p.dump.pending_nobles.clone(),
                    final_trigger: p.dump.final_trigger,
                    winner: p.dump.winner,
                    ply: p.dump.ply,
                    win_points: p.dump.win_points,
                }
            };
            let (tok, mask, state) = feats::features_tokens(&s, seat);
            let (val, _pol) = net.forward(&tok, &mask, &state);
            rows.push_str(&format!("{},{},{},{:.4},{:.4},{},{}\n",
                g.game_id, p.ply, seat, val, p.value, p.label as i32, p.hard as i32));
            n += 1;
            if p.hard { n_hard += 1; hard_sum += val; hard_n += 1; }
            if p.label < 0.0 { loss_net_sum += val; loss_n += 1; pts.push((val, false)); }
            else if p.label > 0.0 { win_net_sum += val; win_n += 1; pts.push((val, true)); }
        }
    }
    std::fs::write(out_path, &rows).expect("write csv");

    // AUC: P(net_value(win) > net_value(loss)) over all decisive position pairs (rank-based).
    let auc = {
        let wins: Vec<f64> = pts.iter().filter(|x| x.1).map(|x| x.0).collect();
        let losses: Vec<f64> = pts.iter().filter(|x| !x.1).map(|x| x.0).collect();
        if wins.is_empty() || losses.is_empty() { f64::NAN } else {
            let mut c = 0f64; let tot = (wins.len() * losses.len()) as f64;
            for &w in &wins { for &l in &losses { if w > l { c += 1.0; } else if (w - l).abs() < 1e-12 { c += 0.5; } } }
            c / tot
        }
    };
    println!("scored {n} positions ({n_hard} hard) -> {out_path}");
    println!("mean NET value on HARD positions (value head thought bot winning, bot lost): {:.3}",
        if hard_n > 0 { hard_sum / hard_n as f64 } else { f64::NAN });
    println!("mean NET value: LOSS positions {:.3} (n={loss_n})  |  WIN/CLOSE positions {:.3} (n={win_n})",
        if loss_n > 0 { loss_net_sum / loss_n as f64 } else { f64::NAN },
        if win_n > 0 { win_net_sum / win_n as f64 } else { f64::NAN });
    println!("static value-head AUC vs eventual outcome (win>loss): {:.3}", auc);
}
