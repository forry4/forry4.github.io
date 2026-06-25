//! Shared test helpers: the lossless State dump shape (mirrors the Python `dump()` in the tools),
//! used by every parity test to load Python-generated fixtures.

use serde::Deserialize;
use spender_core::engine::State;

#[derive(Deserialize)]
pub struct Dump {
    pub bank: [i32; 6],
    pub tokens: [[i32; 6]; 2],
    pub bonuses: [[i32; 5]; 2],
    pub points: [i32; 2],
    pub purchased_n: [i32; 2],
    pub purchased: [Vec<i32>; 2],
    pub reserved: [Vec<i32>; 2],
    pub reserved_blind: [Vec<bool>; 2],
    pub nobles_won: [Vec<i32>; 2],
    pub board: [i32; 12],
    pub decks: [Vec<i32>; 3],
    pub nobles: [i32; 3],
    pub turn: usize,
    pub phase: u8,
    pub pending_nobles: Vec<usize>,
    pub final_trigger: i32,
    pub winner: i32,
    pub ply: i32,
    pub win_points: i32,
}

impl Dump {
    pub fn into_state(self) -> State {
        State {
            bank: self.bank,
            tokens: self.tokens,
            bonuses: self.bonuses,
            points: self.points,
            purchased_n: self.purchased_n,
            purchased: self.purchased,
            reserved: self.reserved,
            reserved_blind: self.reserved_blind,
            nobles_won: self.nobles_won,
            board: self.board,
            decks: self.decks,
            nobles: self.nobles,
            turn: self.turn,
            phase: self.phase,
            pending_nobles: self.pending_nobles,
            final_trigger: self.final_trigger,
            winner: self.winner,
            ply: self.ply,
            win_points: self.win_points,
        }
    }
    /// Clone-free state build (Dump fields are owned; tests usually want the state but keep the
    /// dump around — this borrows by cloning the Vecs).
    pub fn to_state(&self) -> State {
        State {
            bank: self.bank,
            tokens: self.tokens,
            bonuses: self.bonuses,
            points: self.points,
            purchased_n: self.purchased_n,
            purchased: self.purchased.clone(),
            reserved: self.reserved.clone(),
            reserved_blind: self.reserved_blind.clone(),
            nobles_won: self.nobles_won.clone(),
            board: self.board,
            decks: self.decks.clone(),
            nobles: self.nobles,
            turn: self.turn,
            phase: self.phase,
            pending_nobles: self.pending_nobles.clone(),
            final_trigger: self.final_trigger,
            winner: self.winner,
            ply: self.ply,
            win_points: self.win_points,
        }
    }
}
