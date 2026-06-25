//! Cross-impl bridge for the strength self-gate (native-only; `--features bridge`).
//!
//! Reads one JSON request per stdin line: {"state": <State dump>, "seat": u, "sims": u, "seed": u64}
//! and prints the chosen action index per line. Lets the Python self-gate harness pit Rust-S against
//! Python-S move-for-move. Not part of the WASM build.

use serde::Deserialize;
use spender_core::engine::State;
use spender_core::rng::Rng;
use spender_core::vsearch;
use std::io::{self, BufRead, Write};

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

impl Dump {
    fn into_state(self) -> State {
        State {
            bank: self.bank, tokens: self.tokens, bonuses: self.bonuses, points: self.points,
            purchased_n: self.purchased_n, purchased: self.purchased, reserved: self.reserved,
            reserved_blind: self.reserved_blind, nobles_won: self.nobles_won, board: self.board,
            decks: self.decks, nobles: self.nobles, turn: self.turn, phase: self.phase,
            pending_nobles: self.pending_nobles, final_trigger: self.final_trigger,
            winner: self.winner, ply: self.ply, win_points: self.win_points,
        }
    }
}

#[derive(Deserialize)]
struct Req {
    state: Dump,
    seat: usize,
    sims: usize,
    seed: u64,
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        let req: Req = serde_json::from_str(&line).expect("parse request");
        let s = req.state.into_state();
        let mut rng = Rng::new(req.seed);
        let a = vsearch::choose_action(&s, req.seat, req.sims, &mut rng);
        writeln!(out, "{a}").unwrap();
        out.flush().unwrap();
    }
}
