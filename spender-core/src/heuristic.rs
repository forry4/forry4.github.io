//! H3 action valuation — port of `heuristic3.py` `components`/`take_value` (deployed config).
//!
//! take_value = (engine + point) / (1 + cost), where
//!   cost   = W_TEMPO*tempo + W_GEM*gem + W_GOLD*gold      (TEMPO_TURNS_SCALE/W_SHORTFALL = 0)
//!   engine = engine_value * W_ENGINE * max(0, turns_remaining - tempo)   (turns-compound model)
//!   point  = PTS + NOBLE_SCALE*noble_progress + noble_completion          (NOBLE_RACE_W/SCARCITY = 0)
//!
//! The policy tree (`choose_action`) comes next; this is the value path used by v_state's progress
//! term and the search policy prior.

use crate::cards::{COST, PTS};
use crate::engine::{self, State, A_BUY_BOARD, A_BUY_RESV, A_DISCARD, A_PASS, A_RES_BOARD,
                    A_TAKE1, A_TAKE2D, A_TAKE2S, A_TAKE3, N_ACTIONS, TAKE2D, TAKE3};
use crate::valuation::{self, Valuation};

pub const W_TEMPO: f64 = 0.1;
pub const W_GEM: f64 = 0.3;
pub const W_GOLD: f64 = 0.4;
pub const W_ENGINE: f64 = 0.15;
pub const NOBLE_SCALE: f64 = 3.0;

// ─── policy-tree constants (deployed) ──────────────────────────────────────────
pub const GOLD_TIEBREAK: f64 = 0.2;
pub const CAP9_BUY_ABOVE: f64 = 0.5;
pub const CAP8_BUY_ABOVE: f64 = 0.8;
pub const WIN_RESERVE_MAX_TEMPO: i32 = 4;

/// (take, engine, point, cost) for card ci from seat — one source of truth for policy + overlay.
pub fn components(val: &Valuation, ci: i32, seat: usize) -> (f64, f64, f64, f64) {
    let s = val.s;
    let cost = W_TEMPO * val.tempo(ci, seat) as f64
        + W_GEM * valuation::gem_cost(s, ci, seat) as f64
        + W_GOLD * valuation::gold_cost(s, ci, seat) as f64;
    let mut engine = val.engine_value(ci, seat);
    let compound = val.estimated_turns_remaining() - val.tempo(ci, seat) as f64;
    engine *= W_ENGINE * if compound > 0.0 { compound } else { 0.0 };
    let point = PTS[ci as usize] as f64
        + NOBLE_SCALE * val.noble_progress(ci, seat)
        + valuation::noble_completion_pts(s, ci, seat) as f64;
    let take = (engine + point) / (1.0 + cost);
    (take, engine, point, cost)
}

/// Single scalar worth of card ci to seat.
pub fn take_value(val: &Valuation, ci: i32, seat: usize) -> f64 {
    components(val, ci, seat).0
}

// ─── policy tree (choose_action) — deployed config ─────────────────────────────

/// Color tuple a take action grabs, or None if `a` is not a take.
pub fn take_colors(a: usize) -> Option<Vec<usize>> {
    if (A_TAKE3..A_TAKE2D).contains(&a) {
        Some(TAKE3[a - A_TAKE3].to_vec())
    } else if (A_TAKE2D..A_TAKE1).contains(&a) {
        Some(TAKE2D[a - A_TAKE2D].to_vec())
    } else if (A_TAKE1..A_TAKE2S).contains(&a) {
        Some(vec![a - A_TAKE1])
    } else if (A_TAKE2S..A_PASS).contains(&a) {
        let c = a - A_TAKE2S;
        Some(vec![c, c])
    } else {
        None
    }
}

fn is_take2s(a: usize) -> bool {
    (A_TAKE2S..A_PASS).contains(&a)
}

/// (take_value, ci, idx, is_board) for board + own reserved, best first (stable desc).
pub fn targets(val: &Valuation, seat: usize) -> Vec<(f64, i32, usize, bool)> {
    let s = val.s;
    let mut out: Vec<(f64, i32, usize, bool)> = Vec::new();
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 {
            out.push((take_value(val, ci, seat), ci, slot, true));
        }
    }
    for (ri, &ci) in s.reserved[seat].iter().enumerate() {
        out.push((take_value(val, ci, seat), ci, ri, false));
    }
    out.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    out
}

/// Color demand summed over the top-3 take_value cards, weighted by value × per-color deficit.
pub fn need_vector(val: &Valuation, seat: usize, tg: &[(f64, i32, usize, bool)]) -> [f64; 5] {
    let mut need = [0.0f64; 5];
    for &(tv, ci, _, _) in tg.iter().take(3) {
        if tv <= 0.0 {
            continue;
        }
        let d = valuation::color_deficits(val.s, ci, seat);
        for i in 0..5 {
            need[i] += tv * (d[i] as f64);
        }
    }
    need
}

/// Opponent's best single affordable buy next turn: (gain, ci, slot[>=0 board / -1 reserved]).
fn opp_best_buy(val: &Valuation, opp: usize) -> (i32, i32, i32) {
    let s = val.s;
    let (mut bg, mut bci, mut bslot) = (0, -1, -1);
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 && valuation::affordable_now(s, ci, opp) {
            let gain = PTS[ci as usize] + valuation::noble_completion_pts(s, ci, opp);
            if gain > bg {
                bg = gain;
                bci = ci;
                bslot = slot as i32;
            }
        }
    }
    for &ci in &s.reserved[opp] {
        if valuation::affordable_now(s, ci, opp) {
            let gain = PTS[ci as usize] + valuation::noble_completion_pts(s, ci, opp);
            if gain > bg {
                bg = gain;
                bci = ci;
                bslot = -1;
            }
        }
    }
    (bg, bci, bslot)
}

/// Opponent's best reserve-then-buy 2-turn win threat: (gain, ci, slot) or (0,-1,-1).
fn opp_best_reserve_buy(val: &Valuation, opp: usize) -> (i32, i32, i32) {
    let s = val.s;
    if s.bank[5] <= 0 || s.reserved[opp].len() >= 3 {
        return (0, -1, -1);
    }
    let opp_gold = s.tokens[opp][5];
    let (mut bg, mut bci, mut bslot) = (0, -1, -1);
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci < 0 || valuation::affordable_now(s, ci, opp) {
            continue;
        }
        if valuation::gold_needed(s, ci, opp) != opp_gold + 1 {
            continue;
        }
        let gain = PTS[ci as usize] + valuation::noble_completion_pts(s, ci, opp);
        if gain > bg {
            bg = gain;
            bci = ci;
            bslot = slot as i32;
        }
    }
    (bg, bci, bslot)
}

/// Would reaching p_win (with cards_win cards) WIN given the final-round rule?
fn secure_win(val: &Valuation, seat: usize, p_win: i32, cards_win: i32) -> bool {
    let s = val.s;
    let opp = 1 - seat;
    if seat == 1 || s.final_trigger == opp as i32 {
        return true;
    }
    let (gain, _, _) = opp_best_buy(val, opp);
    let opp_pts = s.points[opp] + gain;
    let opp_cards = s.purchased_n[opp] + if gain > 0 { 1 } else { 0 };
    let overtakes = opp_pts > p_win || (opp_pts == p_win && opp_cards < cards_win);
    !overtakes
}

fn deny(s: &State, seat: usize, slot: i32, ci: i32, in_legal: &[bool], _v: &Valuation) -> Option<usize> {
    if s.reserved[seat].len() < 3 {
        let a = A_RES_BOARD + slot as usize;
        if in_legal[a] {
            return Some(a);
        }
    }
    if valuation::affordable_now(s, ci, seat) {
        let a = A_BUY_BOARD + slot as usize;
        if in_legal[a] {
            return Some(a);
        }
    }
    None
}

/// Reserve ci iff gold-NECESSARY and reserving can bank enough gold to cover the shortfall.
fn reservable(val: &Valuation, seat: usize, ci: i32, slot: usize, in_legal: &[bool]) -> Option<usize> {
    let s = val.s;
    let short = valuation::gold_shortfall(s, ci, seat);
    let held = s.tokens[seat][5];
    let free = 3 - s.reserved[seat].len() as i32;
    if held < short && short <= held + free {
        let a = A_RES_BOARD + slot;
        if in_legal[a] {
            return Some(a);
        }
    }
    None
}

fn winning_reserve(val: &Valuation, seat: usize, in_legal: &[bool]) -> Option<usize> {
    let s = val.s;
    if s.reserved[seat].len() >= 3 || s.bank[5] <= 0 {
        return None;
    }
    let (mut best_a, mut best_pts): (Option<usize>, i32) = (None, -1);
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci < 0 || valuation::affordable_now(s, ci, seat) {
            continue;
        }
        if s.points[seat] + PTS[ci as usize] + valuation::noble_completion_pts(s, ci, seat) < s.win_points {
            continue;
        }
        if valuation::tempo(s, ci, seat) >= WIN_RESERVE_MAX_TEMPO {
            continue;
        }
        if let Some(a) = reservable(val, seat, ci, slot, in_legal) {
            if best_a.is_none() || PTS[ci as usize] > best_pts {
                best_a = Some(a);
                best_pts = PTS[ci as usize];
            }
        }
    }
    best_a
}

fn finish_reserve(val: &Valuation, seat: usize, tg: &[(f64, i32, usize, bool)], in_legal: &[bool]) -> Option<usize> {
    let s = val.s;
    if tg.is_empty() || s.reserved[seat].len() >= 3 || s.bank[5] <= 0 {
        return None;
    }
    let (_, ci, idx, is_board) = tg[0];
    if !is_board || valuation::affordable_now(s, ci, seat) {
        return None;
    }
    let a = A_RES_BOARD + idx;
    if !in_legal[a] {
        return None;
    }
    let n_tokens: i32 = s.tokens[seat].iter().sum();
    let d = valuation::color_deficits(s, ci, seat);
    let total: i32 = d.iter().sum();
    let dmax = *d.iter().max().unwrap();
    if (n_tokens == 8 && total == 2 && dmax == 2) || (n_tokens == 9 && total == 1) {
        return Some(a);
    }
    None
}

fn choose_discard(val: &Valuation, seat: usize, legal: &[usize], tg: &[(f64, i32, usize, bool)]) -> usize {
    let need = need_vector(val, seat, tg);
    let s = val.s;
    let mut best_a = legal[0];
    let mut best_key: Option<(u8, f64, f64)> = None;
    for &a in legal {
        let c = a - A_DISCARD;
        let is_gold = c == 5;
        let need_c = if is_gold { f64::INFINITY } else { need[c] };
        let key = (is_gold as u8, need_c, -(s.tokens[seat][c] as f64));
        if best_key.map_or(true, |b| key_lt3(key, b)) {
            best_key = Some(key);
            best_a = a;
        }
    }
    best_a
}

/// Take gems bringing the top target closest to affordable; spare picks spill to next targets.
fn choose_take(val: &Valuation, seat: usize, tg: &[(f64, i32, usize, bool)], legal: &[usize]) -> Option<usize> {
    let s = val.s;
    if let Some(&(_, target, _, _)) = tg.first() {
        let need = need_vector(val, seat, tg);
        let bon = &s.bonuses[seat];
        let tok = &s.tokens[seat];
        let tcost = &COST[target as usize];
        let mut best_a: Option<usize> = None;
        let mut best_key: Option<(i32, i32, f64)> = None;
        for &a in legal {
            let colors = match take_colors(a) {
                Some(c) if !is_take2s(a) => c,
                _ => continue,
            };
            // simulate taking these gems: d_after[c] = max(0, cost - bon - (tok + added))
            let mut added = [0i32; 5];
            for &c in &colors {
                added[c] += 1;
            }
            let mut d = [0i32; 5];
            for c in 0..5 {
                let v = tcost[c] - bon[c] - tok[c] - added[c];
                d[c] = if v > 0 { v } else { 0 };
            }
            let need_sum: f64 = colors.iter().map(|&c| need[c]).sum();
            let key = (valuation::steps(&d), d.iter().sum::<i32>(), -need_sum);
            if best_key.map_or(true, |b| key_lt3f(key, b)) {
                best_key = Some(key);
                best_a = Some(a);
            }
        }
        if best_a.is_some() {
            return best_a;
        }
    }
    // fallback: a take-3, then any non-take-2-same take
    for &a in legal {
        if (A_TAKE3..A_TAKE2D).contains(&a) {
            return Some(a);
        }
    }
    for &a in legal {
        if take_colors(a).is_some() && !is_take2s(a) {
            return Some(a);
        }
    }
    None
}

// lexicographic comparisons (Python tuple ordering) for the policy keys
fn key_lt3(x: (u8, f64, f64), y: (u8, f64, f64)) -> bool {
    if x.0 != y.0 {
        return x.0 < y.0;
    }
    if x.1 != y.1 {
        return x.1 < y.1;
    }
    x.2 < y.2
}
fn key_lt3f(x: (i32, i32, f64), y: (i32, i32, f64)) -> bool {
    if x.0 != y.0 {
        return x.0 < y.0;
    }
    if x.1 != y.1 {
        return x.1 < y.1;
    }
    x.2 < y.2
}

/// H3 greedy action for `seat`, reusing a prebuilt Valuation (the search anchor passes the leaf's).
pub fn choose_action_with(val: &Valuation, seat: usize) -> usize {
    let s = val.s;
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        return A_PASS;
    }
    let mut in_legal = [false; N_ACTIONS];
    for &a in &legal {
        in_legal[a] = true;
    }

    if s.phase == engine::DISCARD {
        return choose_discard(val, seat, &legal, &targets(val, seat));
    }
    if s.phase == engine::NOBLE {
        return legal[0];
    }

    let opp = 1 - seat;
    let tg = targets(val, seat);

    // affordable buys, ranked by take_value with a small gold-spend tiebreak
    let mut buys: Vec<(f64, usize, i32)> = Vec::new(); // (sort_key, action, ci)
    for slot in 0..12 {
        let ci = s.board[slot];
        let a = A_BUY_BOARD + slot;
        if ci >= 0 && in_legal[a] {
            let k = take_value(val, ci, seat) - GOLD_TIEBREAK * valuation::gold_needed(s, ci, seat) as f64;
            buys.push((k, a, ci));
        }
    }
    for (ri, &ci) in s.reserved[seat].iter().enumerate() {
        let a = A_BUY_RESV + ri;
        if in_legal[a] {
            let k = take_value(val, ci, seat) - GOLD_TIEBREAK * valuation::gold_needed(s, ci, seat) as f64;
            buys.push((k, a, ci));
        }
    }
    buys.sort_by(|x, y| y.0.partial_cmp(&x.0).unwrap());

    // 1) winning buy (taken only if SECURE; else deny the opponent's overtaking card)
    if !buys.is_empty() {
        let mut winning: Vec<(i32, usize)> = Vec::new();
        for &(_, a, ci) in &buys {
            let gain = PTS[ci as usize] + valuation::noble_completion_pts(s, ci, seat);
            if s.points[seat] + gain >= s.win_points {
                winning.push((gain, a));
            }
        }
        if !winning.is_empty() {
            winning.sort_by(|x, y| y.cmp(x)); // desc by (gain, a)
            let (w_gain, w_a) = winning[0];
            if secure_win(val, seat, s.points[seat] + w_gain, s.purchased_n[seat] + 1) {
                return w_a;
            }
            let (_og, oci, oslot) = opp_best_buy(val, opp);
            if oslot >= 0 {
                if let Some(da) = deny(s, seat, oslot, oci, &in_legal, val) {
                    return da;
                }
            }
            return w_a;
        }
    }

    // 1b) winning via reserve
    if let Some(wr) = winning_reserve(val, seat, &in_legal) {
        return wr;
    }

    // 2) endgame denial (opponent wins next turn off the board)
    let (og, oci, oslot) = opp_best_buy(val, opp);
    if oslot >= 0 && s.points[opp] + og >= s.win_points {
        if let Some(da) = deny(s, seat, oslot, oci, &in_legal, val) {
            return da;
        }
    }
    // 2b) 2-turn endgame denial (reserve-then-buy)
    let (og2, oci2, oslot2) = opp_best_reserve_buy(val, opp);
    if oslot2 >= 0 && s.points[opp] + og2 >= s.win_points {
        if let Some(da2) = deny(s, seat, oslot2, oci2, &in_legal, val) {
            return da2;
        }
    }

    // (USE_OPP_SNIPE off -> take_targets == targets)
    // 3) token-cap anti-hoard
    let n_tokens: i32 = s.tokens[seat].iter().sum();
    if n_tokens >= 8 {
        if !buys.is_empty() {
            let best_tv = take_value(val, buys[0].2, seat);
            let best_a = buys[0].1;
            if n_tokens >= 10 {
                return best_a;
            }
            if n_tokens == 9 && best_tv > CAP9_BUY_ABOVE {
                return best_a;
            }
            if n_tokens == 8 && best_tv > CAP8_BUY_ABOVE {
                return best_a;
            }
        }
        if let Some(a) = finish_reserve(val, seat, &tg, &in_legal) {
            return a;
        }
        return choose_take(val, seat, &tg, &legal).unwrap_or(legal[0]);
    }

    // 4) buy the top take_value card if affordable, else take toward it
    if let Some(&(_, _ci, idx, is_board)) = tg.first() {
        let top_a = if is_board { A_BUY_BOARD + idx } else { A_BUY_RESV + idx };
        if in_legal[top_a] {
            return top_a;
        }
    }
    // 4b/5 off (USE_TAKE2 / USE_SPECULATIVE_RESERVE)
    choose_take(val, seat, &tg, &legal).unwrap_or(legal[0])
}

/// H3 greedy action for `seat` (builds its own Valuation).
pub fn choose_action(s: &State, seat: usize) -> usize {
    let val = Valuation::new(s, W_TEMPO, W_GEM, W_GOLD);
    choose_action_with(&val, seat)
}
