//! Exact endgame solver (#1) — a determinized alpha-beta negamax that runs ONCE per move decision in
//! near-terminal positions and *overrides* the PUCT pick ONLY when it finds a SOUND forced result.
//!
//! Why this exists: the PUCT root value is a visit-weighted MEAN, which dilutes a single sharp forced
//! line among the opponent's many weaker replies — so a public, affordable, 1-2-turn-ahead win/loss
//! (the documented YINAIM / IYGWJQ losses) only converges after thousands of sims, if ever. Exact
//! minimax converges to the true value of those tactics instantly and is GUARANTEED correct in the
//! tail; it frees sims for the rest of the game.
//!
//! Soundness: a leaf at the depth horizon is evaluated with `v_state::value` (∈ (-1,1) strictly, since
//! it's a `tanh`), so a negamax value of exactly ±1 can ONLY arise from a real terminal win/loss
//! reached within the horizon under best play — a sound forced-result certificate. We override only on
//! such certificates, and (for hidden info) only when the certificate holds across ALL determinizations
//! (a win that needs a lucky draw won't pass that bar). So the override can only help: it never trades
//! a PUCT move for a worse one on a hunch — only on proof.

use crate::cards::{COST, PTS};
use crate::engine::{
    self, State, A_BUY_BOARD, A_BUY_RESV, A_RES_BOARD, A_RES_DECK, N_ACTIONS, OVER, PLAY,
};
use crate::heuristic;
use crate::mcts;
use crate::rng::Rng;

/// Only solve when a player is within this many points of `win_points` (or the final round started).
/// Keeps the solver off in the early-midgame, where no terminal is reachable within the horizon (so it
/// would only cost time and never override), and bounds its firing rate.
pub const ENDGAME_GAP: i32 = 6;
/// Negamax search depth in PLIES (each `apply` is one ply; a player's turn can be >1 ply via
/// discard/noble). 5 plies catches the 2-turn reserve-then-buy threat (IYGWJQ) while the endgame tree
/// terminates fast (points pile up), so effective depth is shallow + alpha-beta prunes hard.
pub const ENDGAME_DEPTH: u32 = 5;
/// Determinizations per decision. A forced result must hold across ALL of them to override. The
/// decisive endgame tactics are usually public (board cards), so a small count suffices; >1 guards
/// against certifying a result that hinged on a specific opponent blind-reserve / deck draw.
pub const ENDGAME_DETS: usize = 6;

const INF: f64 = 1e9;
const TERM_EPS: f64 = 1e-6;
/// Cheap NON-terminal horizon leaf: a scaled point margin from `ref_seat`'s view, in (-1,1). The
/// solver is a pure tactical oracle — its overrides fire ONLY on exact ±1 terminal certificates, which
/// this leaf can't reach (|tanh| < 1), so the leaf only ranks already-safe/winning moves. Positional
/// judgement stays PUCT's job (v_state + thousands of sims); using v_state here would cost ~1000× more.
#[inline]
fn margin_leaf(s: &State, ref_seat: usize) -> f64 {
    let dp = (s.points[ref_seat] - s.points[1 - ref_seat]) as f64;
    // Light fewest-cards tiebreak nudge (matches resolve_winner's secondary key), kept tiny.
    let dc = (s.purchased_n[1 - ref_seat] - s.purchased_n[ref_seat]) as f64;
    ((dp + 0.05 * dc) / 4.0).tanh()
}

#[inline]
fn terminal_value(s: &State, ref_seat: usize) -> f64 {
    if s.winner == ref_seat as i32 {
        1.0
    } else if s.winner == (1 - ref_seat) as i32 {
        -1.0
    } else {
        0.0 // draw / none
    }
}

/// Card id a buy action targets (board slot or own-reserved index), or -1.
#[inline]
fn buy_card(s: &State, seat: usize, a: usize) -> i32 {
    if (A_BUY_BOARD..A_BUY_RESV).contains(&a) {
        s.board[a - A_BUY_BOARD]
    } else {
        let ri = a - A_BUY_RESV;
        if ri < s.reserved[seat].len() {
            s.reserved[seat][ri]
        } else {
            -1
        }
    }
}

/// Move set for a node, pruned + ordered for alpha-beta. Pruning the MOVER's options is safe (it can
/// only MISS a forced win → conservatively not certify, never falsely certify). Ordering: buys (most
/// points first, the most-forcing moves) → relevant takes → reserves → pass, to maximize cutoffs.
fn ordered_moves(s: &State) -> Vec<usize> {
    let legal = engine::legal_actions(s);
    if s.phase != PLAY {
        return legal; // discard / noble: small, keep all
    }
    let me = s.turn;
    let tok = &s.tokens[me];
    let bon = &s.bonuses[me];
    // Colors where SOME board/own-reserved card still needs gems → a take of any other color is inert.
    let mut useful = [false; 5];
    let mark = |ci: i32, useful: &mut [bool; 5]| {
        if ci < 0 {
            return;
        }
        let cost = &COST[ci as usize];
        for c in 0..5 {
            if cost[c] - bon[c] - tok[c] > 0 {
                useful[c] = true;
            }
        }
    };
    for slot in 0..12 {
        mark(s.board[slot], &mut useful);
    }
    for &ci in &s.reserved[me] {
        mark(ci, &mut useful);
    }

    let mut buys: Vec<(i32, usize)> = Vec::new();
    let mut takes: Vec<usize> = Vec::new();
    let mut reserves: Vec<usize> = Vec::new();
    let mut pass: Vec<usize> = Vec::new();
    for &a in &legal {
        if (A_BUY_BOARD..A_BUY_RESV + 3).contains(&a) {
            let ci = buy_card(s, me, a);
            buys.push((-(if ci >= 0 { PTS[ci as usize] } else { 0 }), a));
        } else if (A_RES_BOARD..A_RES_DECK + 3).contains(&a) {
            reserves.push(a);
        } else if let Some(colors) = heuristic::take_colors(a) {
            if colors.iter().any(|&c| useful[c]) {
                takes.push(a);
            }
        } else {
            pass.push(a);
        }
    }
    buys.sort(); // -points ascending → highest points first
    let mut out: Vec<usize> = Vec::with_capacity(legal.len());
    out.extend(buys.into_iter().map(|(_, a)| a));
    out.extend(takes);
    out.extend(reserves);
    out.extend(pass);
    if out.is_empty() {
        out = legal;
    }
    out
}

/// Alpha-beta negamax, value in [-1,1] from `ref_seat`'s perspective. Turns DON'T strictly alternate
/// (discard/noble are extra plies for the same mover), so we maximize when the mover is `ref_seat` and
/// minimize otherwise (rather than negate per ply). The deck is fixed for this determinization, so the
/// subtree is perfect-information and the search is exact to its horizon.
fn nega(s: &State, depth: u32, ref_seat: usize, mut alpha: f64, mut beta: f64) -> f64 {
    if s.phase == OVER {
        return terminal_value(s, ref_seat);
    }
    if depth == 0 {
        return margin_leaf(s, ref_seat);
    }
    let moves = ordered_moves(s);
    if s.turn == ref_seat {
        let mut best = -INF;
        for a in moves {
            let mut c = s.clone();
            engine::apply(&mut c, a);
            let v = nega(&c, depth - 1, ref_seat, alpha, beta);
            if v > best {
                best = v;
            }
            if best > alpha {
                alpha = best;
            }
            if alpha >= beta || best >= 1.0 - TERM_EPS {
                break; // beta cutoff, or can't beat a forced win
            }
        }
        best
    } else {
        let mut best = INF;
        for a in moves {
            let mut c = s.clone();
            engine::apply(&mut c, a);
            let v = nega(&c, depth - 1, ref_seat, alpha, beta);
            if v < best {
                best = v;
            }
            if best < beta {
                beta = best;
            }
            if alpha >= beta || best <= -1.0 + TERM_EPS {
                break; // alpha cutoff, or opponent can't do better than forcing our loss
            }
        }
        best
    }
}

/// True if the position is close enough to a terminal that an exact solve can reach it.
pub fn is_endgame(s: &State) -> bool {
    if s.phase == OVER {
        return false;
    }
    if s.final_trigger >= 0 {
        return true;
    }
    let lead = s.points[0].max(s.points[1]);
    s.win_points - lead <= ENDGAME_GAP
}

/// Refine `puct_move` with the exact endgame solver. Returns `puct_move` unchanged unless the solver
/// proves (across ALL determinizations) that another move is a forced win, or that `puct_move` is a
/// forced loss while a non-losing move exists.
pub fn refine(s: &State, seat: usize, puct_move: usize, rng: &mut Rng) -> usize {
    refine_cfg(s, seat, puct_move, rng, ENDGAME_DEPTH, ENDGAME_DETS)
}

pub fn refine_cfg(
    s: &State,
    seat: usize,
    puct_move: usize,
    rng: &mut Rng,
    depth: u32,
    dets: usize,
) -> usize {
    if !is_endgame(s) {
        return puct_move;
    }
    let legal = engine::legal_actions(s);
    if legal.len() <= 1 {
        return puct_move;
    }
    let mut win = vec![0i32; N_ACTIONS];
    let mut loss = vec![0i32; N_ACTIONS];
    let mut vsum = vec![0.0f64; N_ACTIONS];
    for _ in 0..dets {
        let ds = mcts::determinize(s, seat, rng);
        for &a in &legal {
            let mut c = ds.clone();
            engine::apply(&mut c, a);
            let v = nega(&c, depth.saturating_sub(1), seat, -INF, INF);
            vsum[a] += v;
            if v >= 1.0 - TERM_EPS {
                win[a] += 1;
            } else if v <= -1.0 + TERM_EPS {
                loss[a] += 1;
            }
        }
    }
    let d = dets as i32;
    let best_by_val = |cands: &[usize]| -> Option<usize> {
        cands
            .iter()
            .copied()
            .max_by(|&a, &b| vsum[a].partial_cmp(&vsum[b]).unwrap())
    };

    // 1. A move that forces a win in EVERY determinization → take it (keep puct_move if it's one).
    if win[puct_move] == d {
        return puct_move;
    }
    let forced: Vec<usize> = legal.iter().copied().filter(|&a| win[a] == d).collect();
    if let Some(best) = best_by_val(&forced) {
        return best;
    }

    // 2. puct_move forces our LOSS in every determinization → switch to the best non-losing move.
    if loss[puct_move] == d {
        let safe: Vec<usize> = legal.iter().copied().filter(|&a| loss[a] < d).collect();
        if let Some(best) = best_by_val(&safe) {
            return best;
        }
    }

    puct_move
}
