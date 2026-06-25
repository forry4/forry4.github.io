//! Whole-position value V(state) — port of `v_state.py` (the variant-S search leaf). Deployed config:
//! ENDGAME_TIEBREAK_W / NOBLE_MULTI_W / RESERVE_PENALTY / NOBLE_RACE_W = 0, PROGRESS_DECAY = 1.0.
//!
//!   V(s, seat) = tanh( (STAND(me) - STAND(opp)) / SCALE )   in [-1, 1]
//! Terminal states return the hard win/loss/draw value (the MCTS leaf is never terminal in serving).

use crate::cards::{NOBLE_PTS, NOBLE_REQ};
use crate::engine::{self, State};
use crate::heuristic;
use crate::valuation::{self, Valuation};

pub const W_POINTS: f64 = 1.0;
pub const W_ENGINE_STK: f64 = 0.4;
pub const W_PROGRESS: f64 = 3.54;
pub const W_NOBLE: f64 = 0.6;
pub const W_ECON: f64 = 0.3;
pub const SCALE: f64 = 8.0;
pub const WIN_CONVEX: f64 = 0.1;
pub const NOBLE_TURN_W: f64 = 1.0;
pub const PROGRESS_TOPK: usize = 6;
pub const TURNS_REF: f64 = 12.0;
pub const ENGINE_DR_EXP: f64 = 0.5;
pub const ECON_HOARD: f64 = 0.15;
pub const ECON_GOLD: f64 = 0.2;
pub const BLIND_RESERVE_CONST: f64 = 0.5;

pub fn points_term(val: &Valuation, seat: usize) -> f64 {
    let p = val.s.points[seat];
    let over = p - (val.s.win_points - 5);
    (p as f64) + if over > 0 { WIN_CONVEX * (over as f64) * (over as f64) } else { 0.0 }
}

pub fn engine_stock(val: &Valuation, seat: usize) -> f64 {
    let bon = &val.s.bonuses[seat];
    let horizon = val.estimated_turns_remaining();
    let mut cover = 0.0;
    for c in 0..5 {
        let b = bon[c];
        if b > 0 {
            cover += val.deck_color_demand[c] * (b as f64).powf(ENGINE_DR_EXP);
        }
    }
    cover * (horizon / TURNS_REF)
}

/// (take_value, ci) for board + own reserved (hiding `seat`'s blind reserves when hide_blind), best
/// first. Stable descending sort matches Python's `sort(reverse=True)` (ties keep original order).
pub fn seat_targets(val: &Valuation, seat: usize, hide_blind: bool) -> Vec<(f64, i32)> {
    let s = val.s;
    let mut out: Vec<(f64, i32)> = Vec::new();
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 {
            out.push((heuristic::take_value(val, ci, seat), ci));
        }
    }
    for (ri, &ci) in s.reserved[seat].iter().enumerate() {
        if hide_blind && s.reserved_blind[seat][ri] {
            continue;
        }
        out.push((heuristic::take_value(val, ci, seat), ci));
    }
    out.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    out
}

pub fn progress(targets: &[(f64, i32)]) -> f64 {
    if targets.is_empty() {
        return 0.0;
    }
    let k = PROGRESS_TOPK.min(targets.len());
    // PROGRESS_DECAY = 1.0 -> plain mean of the top k
    let sum: f64 = targets[..k].iter().map(|t| t.0).sum();
    sum / (k as f64)
}

pub fn noble_stand(val: &Valuation, seat: usize) -> f64 {
    let s = val.s;
    let bon = &s.bonuses[seat];
    let horizon = val.estimated_turns_remaining();
    let mut vals: Vec<f64> = Vec::new();
    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni < 0 {
            continue;
        }
        let req = &NOBLE_REQ[ni as usize];
        let total: i32 = req.iter().sum();
        if total == 0 {
            continue;
        }
        let mut deficit = 0;
        for c in 0..5 {
            if req[c] > bon[c] {
                deficit += req[c] - bon[c];
            }
        }
        if deficit == 0 {
            vals.push(NOBLE_PTS[ni as usize] as f64);
            continue;
        }
        let close = 1.0 - (deficit as f64) / (total as f64);
        let time_factor = horizon / (horizon + NOBLE_TURN_W * (deficit as f64));
        vals.push((NOBLE_PTS[ni as usize] as f64) * close * time_factor);
    }
    if vals.is_empty() {
        return 0.0;
    }
    vals.iter().copied().fold(f64::NEG_INFINITY, f64::max)
}

pub fn econ(val: &Valuation, seat: usize, targets: &[(f64, i32)]) -> f64 {
    let tok = &val.s.tokens[seat];
    let gold = tok[5];
    let ntok: i32 = tok.iter().sum();
    let useful_gold = if let Some(&(_, best_ci)) = targets.first() {
        gold.min(valuation::gold_needed(val.s, best_ci, seat)) as f64
    } else {
        0.0
    };
    let over = ntok - 8;
    ECON_GOLD * useful_gold - if over > 0 { ECON_HOARD * (over as f64) } else { 0.0 }
}

pub fn stand(val: &Valuation, seat: usize, observer: usize) -> f64 {
    let hide_blind = seat != observer;
    let targets = seat_targets(val, seat, hide_blind);
    let mut st = W_POINTS * points_term(val, seat)
        + W_ENGINE_STK * engine_stock(val, seat)
        + W_PROGRESS * progress(&targets)
        + W_NOBLE * noble_stand(val, seat)
        + W_ECON * econ(val, seat, &targets);
    // RESERVE_PENALTY = 0
    if hide_blind {
        let n_blind = val.s.reserved_blind[seat].iter().filter(|&&b| b).count() as f64;
        st += BLIND_RESERVE_CONST * n_blind;
    }
    st
}

pub fn value_with(val: &Valuation, seat: usize) -> f64 {
    let (me, opp) = (seat, 1 - seat);
    ((stand(val, me, me) - stand(val, opp, me)) / SCALE).tanh()
}

pub fn value(s: &State, seat: usize) -> f64 {
    if s.phase == engine::OVER {
        if s.winner == seat as i32 {
            return 1.0;
        }
        if s.winner == (1 - seat) as i32 {
            return -1.0;
        }
        return 0.0;
    }
    let val = Valuation::new(s, heuristic::W_TEMPO, heuristic::W_GEM, heuristic::W_GOLD);
    value_with(&val, seat)
}
