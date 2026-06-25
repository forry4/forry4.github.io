//! Compact Splendor simulator — a faithful Rust port of `games/spender/ai/az/engine.py`.
//!
//! Rule-parity with the Python engine is gated by a differential test (`tests/engine_parity.rs`):
//! Python plays random games and dumps (initial state, [(action, resulting state)]); Rust replays
//! the same actions from the same states and the full integer state must match after every move.
//!
//! Color order: white=0, blue=1, green=2, red=3, black=4, gold=5.
//! Card ids: 0..39 = L1, 40..69 = L2, 70..89 = L3. Seats 0 and 1.

use crate::cards::{BONUS, COST, LEVEL_OF, NOBLE_PTS, NOBLE_REQ, N_CARDS, N_NOBLES, PTS};
use crate::rng::Rng;

// ─── Phases / constants ──────────────────────────────────────────────────────
pub const PLAY: u8 = 0;
pub const DISCARD: u8 = 1;
pub const NOBLE: u8 = 2;
pub const OVER: u8 = 3;

pub const WIN_NONE: i32 = -1;
pub const WIN_DRAW: i32 = 2;
pub const TOKEN_CAP: i32 = 10;
pub const WIN_POINTS: i32 = 15;
pub const BANK_INIT: [i32; 6] = [4, 4, 4, 4, 4, 5];

// ─── Action space (fixed indices, 70 actions) ────────────────────────────────
pub const A_TAKE3: usize = 0; // 0..9
pub const A_TAKE2D: usize = 10; // 10..19
pub const A_TAKE1: usize = 20; // 20..24
pub const A_TAKE2S: usize = 25; // 25..29
pub const A_PASS: usize = 30; // 30
pub const A_RES_BOARD: usize = 31; // 31..42 (slot order)
pub const A_RES_DECK: usize = 43; // 43..45 (level-1)
pub const A_BUY_BOARD: usize = 46; // 46..57 (slot order)
pub const A_BUY_RESV: usize = 58; // 58..60 (reserved index)
pub const A_DISCARD: usize = 61; // 61..66 (color, incl. gold)
pub const A_NOBLE: usize = 67; // 67..69 (pending_nobles index)
pub const N_ACTIONS: usize = 70;

/// combinations(0..5, 3) in lexicographic order (matches Python itertools.combinations).
pub const TAKE3: [[usize; 3]; 10] = [
    [0, 1, 2], [0, 1, 3], [0, 1, 4], [0, 2, 3], [0, 2, 4],
    [0, 3, 4], [1, 2, 3], [1, 2, 4], [1, 3, 4], [2, 3, 4],
];
/// combinations(0..5, 2) in lexicographic order.
pub const TAKE2D: [[usize; 2]; 10] = [
    [0, 1], [0, 2], [0, 3], [0, 4], [1, 2],
    [1, 3], [1, 4], [2, 3], [2, 4], [3, 4],
];

#[derive(Clone, PartialEq, Eq, Debug)]
pub struct State {
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

/// Deck level offsets, derived from the card tables (robust to a deck-size change).
fn level_offsets() -> (usize, usize) {
    let l2 = LEVEL_OF.iter().position(|&l| l == 2).unwrap();
    let l3 = LEVEL_OF.iter().position(|&l| l == 3).unwrap();
    (l2, l3)
}

pub fn new_game(seed: u64, win_points: i32) -> State {
    let mut rng = Rng::new(seed);
    let (l2, l3) = level_offsets();
    let mut d1: Vec<i32> = (0..l2 as i32).collect();
    let mut d2: Vec<i32> = (l2 as i32..l3 as i32).collect();
    let mut d3: Vec<i32> = (l3 as i32..N_CARDS as i32).collect();
    rng.shuffle(&mut d1);
    rng.shuffle(&mut d2);
    rng.shuffle(&mut d3);
    // Board refills use pop() (end of list) — deal the same way.
    let mut board = [-1i32; 12];
    let mut decks = [d1, d2, d3];
    for (lvl, deck) in decks.iter_mut().enumerate() {
        for i in 0..4 {
            board[lvl * 4 + i] = deck.pop().unwrap_or(-1);
        }
    }
    let mut noble_ids: Vec<i32> = (0..N_NOBLES as i32).collect();
    rng.shuffle(&mut noble_ids);
    let nobles = [noble_ids[0], noble_ids[1], noble_ids[2]];
    State {
        bank: BANK_INIT,
        tokens: [[0; 6]; 2],
        bonuses: [[0; 5]; 2],
        points: [0, 0],
        purchased_n: [0, 0],
        purchased: [Vec::new(), Vec::new()],
        reserved: [Vec::new(), Vec::new()],
        reserved_blind: [Vec::new(), Vec::new()],
        nobles_won: [Vec::new(), Vec::new()],
        board,
        decks,
        nobles,
        turn: 0,
        phase: PLAY,
        pending_nobles: Vec::new(),
        final_trigger: -1,
        winner: WIN_NONE,
        ply: 0,
        win_points,
    }
}

/// Gold required to buy; affordable iff result <= tokens[5].
#[inline]
pub fn gold_needed(cost: &[i32; 5], tokens: &[i32; 6], bonuses: &[i32; 5]) -> i32 {
    let mut gn = 0;
    for i in 0..5 {
        let need = cost[i] - bonuses[i];
        if need > 0 {
            let short = need - tokens[i];
            if short > 0 {
                gn += short;
            }
        }
    }
    gn
}

pub fn legal_actions(s: &State) -> Vec<usize> {
    if s.phase == OVER {
        return Vec::new();
    }
    let me = s.turn;
    let tok = &s.tokens[me];

    if s.phase == DISCARD {
        return (0..6).filter(|&i| tok[i] > 0).map(|i| A_DISCARD + i).collect();
    }
    if s.phase == NOBLE {
        return (0..s.pending_nobles.len()).map(|i| A_NOBLE + i).collect();
    }

    let mut acts: Vec<usize> = Vec::new();
    let bank = &s.bank;
    let bon = &s.bonuses[me];

    // Takes (allowed even at 10 tokens — discard phase handles overflow).
    for (k, combo) in TAKE3.iter().enumerate() {
        if bank[combo[0]] > 0 && bank[combo[1]] > 0 && bank[combo[2]] > 0 {
            acts.push(A_TAKE3 + k);
        }
    }
    for (k, combo) in TAKE2D.iter().enumerate() {
        if bank[combo[0]] > 0 && bank[combo[1]] > 0 {
            acts.push(A_TAKE2D + k);
        }
    }
    for c in 0..5 {
        if bank[c] > 0 {
            acts.push(A_TAKE1 + c);
        }
        if bank[c] >= 4 {
            acts.push(A_TAKE2S + c);
        }
    }

    // Reserves
    if s.reserved[me].len() < 3 {
        for slot in 0..12 {
            if s.board[slot] >= 0 {
                acts.push(A_RES_BOARD + slot);
            }
        }
        for lvl in 0..3 {
            if !s.decks[lvl].is_empty() {
                acts.push(A_RES_DECK + lvl);
            }
        }
    }

    // Buys
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 && gold_needed(&COST[ci as usize], tok, bon) <= tok[5] {
            acts.push(A_BUY_BOARD + slot);
        }
    }
    for (ri, &ci) in s.reserved[me].iter().enumerate() {
        if gold_needed(&COST[ci as usize], tok, bon) <= tok[5] {
            acts.push(A_BUY_RESV + ri);
        }
    }

    if acts.is_empty() {
        acts.push(A_PASS);
    }
    acts
}

// ─── Apply ───────────────────────────────────────────────────────────────────

fn resolve_winner(s: &mut State) {
    s.phase = OVER;
    let k0 = (s.points[0], -s.purchased_n[0]);
    let k1 = (s.points[1], -s.purchased_n[1]);
    s.winner = if k0 > k1 {
        0
    } else if k1 > k0 {
        1
    } else {
        WIN_DRAW
    };
}

fn finish_turn(s: &mut State, seat: usize) {
    if s.points[seat] >= s.win_points && s.final_trigger < 0 {
        s.final_trigger = seat as i32;
    }
    s.turn = 1 - s.turn;
    s.ply += 1;
    if s.final_trigger >= 0 && (s.turn as i32) <= s.final_trigger {
        resolve_winner(s);
    }
}

/// True if over the cap (phase set to DISCARD, turn NOT finished).
fn maybe_enter_discard(s: &mut State, seat: usize) -> bool {
    if s.tokens[seat].iter().sum::<i32>() > TOKEN_CAP {
        s.phase = DISCARD;
        true
    } else {
        false
    }
}

fn claim_noble(s: &mut State, seat: usize, slot: usize) {
    let ni = s.nobles[slot];
    s.nobles_won[seat].push(ni);
    s.points[seat] += NOBLE_PTS[ni as usize];
    s.nobles[slot] = -1;
}

/// Claim/queue nobles after a buy. True if a NOBLE decision is pending.
fn after_buy_nobles(s: &mut State, seat: usize) -> bool {
    let bon = s.bonuses[seat];
    let mut claimable: Vec<usize> = Vec::new();
    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni >= 0 {
            let req = &NOBLE_REQ[ni as usize];
            if bon[0] >= req[0] && bon[1] >= req[1] && bon[2] >= req[2] && bon[3] >= req[3] && bon[4] >= req[4] {
                claimable.push(slot);
            }
        }
    }
    if claimable.is_empty() {
        return false;
    }
    if claimable.len() == 1 {
        claim_noble(s, seat, claimable[0]);
        return false;
    }
    s.pending_nobles = claimable;
    s.phase = NOBLE;
    true
}

fn refill(s: &mut State, slot: usize) {
    let deck = &mut s.decks[slot / 4];
    s.board[slot] = deck.pop().unwrap_or(-1);
}

/// Apply action in-place. Caller guarantees `a` is legal (from `legal_actions`).
pub fn apply(s: &mut State, a: usize) {
    let me = s.turn;

    if s.phase == DISCARD {
        let c = a - A_DISCARD;
        s.tokens[me][c] -= 1;
        s.bank[c] += 1;
        if s.tokens[me].iter().sum::<i32>() <= TOKEN_CAP {
            s.phase = PLAY;
            finish_turn(s, me);
        }
        return;
    }

    if s.phase == NOBLE {
        let slot = s.pending_nobles[a - A_NOBLE];
        claim_noble(s, me, slot);
        s.pending_nobles.clear();
        s.phase = PLAY;
        finish_turn(s, me);
        return;
    }

    if a < A_PASS {
        // all take variants
        let colors: Vec<usize> = if a < A_TAKE2D {
            TAKE3[a - A_TAKE3].to_vec()
        } else if a < A_TAKE1 {
            TAKE2D[a - A_TAKE2D].to_vec()
        } else if a < A_TAKE2S {
            vec![a - A_TAKE1]
        } else {
            let c = a - A_TAKE2S;
            vec![c, c]
        };
        for &c in &colors {
            s.bank[c] -= 1;
            s.tokens[me][c] += 1;
        }
        if !maybe_enter_discard(s, me) {
            finish_turn(s, me);
        }
        return;
    }

    if a == A_PASS {
        finish_turn(s, me);
        return;
    }

    if a < A_RES_DECK {
        // reserve from board
        let slot = a - A_RES_BOARD;
        let ci = s.board[slot];
        s.reserved[me].push(ci);
        s.reserved_blind[me].push(false);
        refill(s, slot);
        if s.bank[5] > 0 {
            s.bank[5] -= 1;
            s.tokens[me][5] += 1;
        }
        if !maybe_enter_discard(s, me) {
            finish_turn(s, me);
        }
        return;
    }

    if a < A_BUY_BOARD {
        // reserve from deck top (blind)
        let lvl = a - A_RES_DECK;
        let ci = s.decks[lvl].pop().expect("deck non-empty (legal)");
        s.reserved[me].push(ci);
        s.reserved_blind[me].push(true);
        if s.bank[5] > 0 {
            s.bank[5] -= 1;
            s.tokens[me][5] += 1;
        }
        if !maybe_enter_discard(s, me) {
            finish_turn(s, me);
        }
        return;
    }

    // Buys
    let ci: i32;
    if a < A_BUY_RESV {
        let slot = a - A_BUY_BOARD;
        ci = s.board[slot];
        refill(s, slot);
    } else {
        let ri = a - A_BUY_RESV;
        ci = s.reserved[me].remove(ri);
        s.reserved_blind[me].remove(ri);
    }

    let cost = &COST[ci as usize];
    for i in 0..5 {
        let need = cost[i] - s.bonuses[me][i];
        if need > 0 {
            let pay = if s.tokens[me][i] < need { s.tokens[me][i] } else { need };
            if pay > 0 {
                s.tokens[me][i] -= pay;
                s.bank[i] += pay;
            }
            let short = need - pay;
            if short > 0 {
                s.tokens[me][5] -= short;
                s.bank[5] += short;
            }
        }
    }
    s.bonuses[me][BONUS[ci as usize]] += 1;
    s.points[me] += PTS[ci as usize];
    s.purchased_n[me] += 1;
    s.purchased[me].push(ci);
    if !after_buy_nobles(s, me) {
        finish_turn(s, me);
    }
}
