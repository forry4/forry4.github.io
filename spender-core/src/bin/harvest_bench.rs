//! Harvest a wwsd racer benchmark into the attn training CSV (train_attn.py schema) with a game-level
//! train/held-out split (no position from one game straddles both). Emits, per bot-turn position:
//!   game, <432 tokens + 18 mask + 28 state = 478 feats>, label(win=1/loss=0/tie=.5), margin(bot-opp),
//!   value(recorded search root), pol(placeholder — value-debias probe is value-only).
//! Features come from feats::features_tokens (the SAME fn serving uses) so train/serve parity holds; the
//! Python sanity check confirms the flatten/reshape alignment.
//!
//! Build+run (from spender-core):
//!   cargo build --release --features bridge --bin harvest_bench
//!   ./target/release/harvest_bench BENCH.json OUT_PREFIX [heldout_every=5]
//!     -> OUT_PREFIX_train.csv + OUT_PREFIX_heldout.csv
use serde::Deserialize;
use spender_core::attn::AttnNet;
use spender_core::engine::State;
use spender_core::feats;
use std::io::Write;

#[derive(Deserialize)]
struct Dump {
    bank: [i32; 6], tokens: [[i32; 6]; 2], bonuses: [[i32; 5]; 2], points: [i32; 2],
    purchased_n: [i32; 2], purchased: [Vec<i32>; 2], reserved: [Vec<i32>; 2],
    reserved_blind: [Vec<bool>; 2], nobles_won: [Vec<i32>; 2], board: [i32; 12],
    decks: [Vec<i32>; 3], nobles: [i32; 3], turn: usize, phase: u8,
    pending_nobles: Vec<usize>, final_trigger: i32, winner: i32, ply: i32, win_points: i32,
}
#[derive(Deserialize)]
struct Pos { value: f64, label: f64, dump: Dump }
#[derive(Deserialize)]
struct Game { #[serde(rename = "gameId")] game_id: String, margin: f64, positions: Vec<Pos> }
#[derive(Deserialize)]
struct Bench { games: Vec<Game> }

fn state_of(d: &Dump) -> State {
    State {
        bank: d.bank, tokens: d.tokens, bonuses: d.bonuses, points: d.points,
        purchased_n: d.purchased_n, purchased: [d.purchased[0].clone(), d.purchased[1].clone()],
        reserved: [d.reserved[0].clone(), d.reserved[1].clone()],
        reserved_blind: [d.reserved_blind[0].clone(), d.reserved_blind[1].clone()],
        nobles_won: [d.nobles_won[0].clone(), d.nobles_won[1].clone()],
        board: d.board, decks: [d.decks[0].clone(), d.decks[1].clone(), d.decks[2].clone()],
        nobles: d.nobles, turn: d.turn, phase: d.phase, pending_nobles: d.pending_nobles.clone(),
        final_trigger: d.final_trigger, winner: d.winner, ply: d.ply, win_points: d.win_points,
    }
}

fn header() -> String {
    let mut h = String::from("game");
    // 478 feature cols: 432 tokens, 18 mask, 28 state
    for i in 0..432 { h.push_str(&format!(",t{i}")); }
    for i in 0..18 { h.push_str(&format!(",m{i}")); }
    for i in 0..28 { h.push_str(&format!(",s{i}")); }
    h.push_str(",label,margin,value,netv,pol");   // netv = Rust static value (parity check; train_attn ignores it)
    h
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let bench_path = args.get(1).map(|s| s.as_str()).unwrap_or("racer_benchmark.json");
    let prefix = args.get(2).map(|s| s.as_str()).unwrap_or("bench");
    let heldout_every: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(5);
    let net_path = args.get(4).map(|s| s.as_str()).unwrap_or("net_attn_3.json");

    let net = AttnNet::from_json(net_path);
    let bench: Bench = serde_json::from_str(&std::fs::read_to_string(bench_path).expect("read bench"))
        .expect("parse bench");
    let mut ftr = std::fs::File::create(format!("{prefix}_train.csv")).unwrap();
    let mut fho = std::fs::File::create(format!("{prefix}_heldout.csv")).unwrap();
    let hdr = header();
    writeln!(ftr, "{hdr}").unwrap();
    writeln!(fho, "{hdr}").unwrap();

    let (mut ntr, mut nho, mut gtr, mut gho) = (0usize, 0usize, 0usize, 0usize);
    for (gi, g) in bench.games.iter().enumerate() {
        let heldout = gi % heldout_every == 0;              // game-level split (every Nth game held out)
        if heldout { gho += 1; } else { gtr += 1; }
        for p in &g.positions {
            let seat = p.dump.turn;
            if seat > 1 { continue; }
            let s = state_of(&p.dump);
            let (tok, mask, st) = feats::features_tokens(&s, seat);
            let (netv, _pol) = net.forward(&tok, &mask, &st);   // Rust static value for the parity column
            let y = (p.label + 1.0) / 2.0;                  // win=1 loss=0 tie=.5
            let mut row = String::with_capacity(4096);
            row.push_str(&g.game_id);
            for v in tok.iter().chain(mask.iter()).chain(st.iter()) { row.push_str(&format!(",{:.6}", v)); }
            row.push_str(&format!(",{y},{},{:.4},{:.4},30:1", g.margin as i32, p.value, netv));
            let f = if heldout { &mut fho } else { &mut ftr };
            writeln!(f, "{row}").unwrap();
            if heldout { nho += 1; } else { ntr += 1; }
        }
    }
    println!("train: {ntr} rows / {gtr} games -> {prefix}_train.csv");
    println!("heldout: {nho} rows / {gho} games -> {prefix}_heldout.csv");
    println!("(478 feat cols = 432 tok + 18 mask + 28 state; label=win1/loss0/tie.5; value=recorded search)");
}
