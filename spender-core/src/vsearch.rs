//! Variant-S search — port of `vsearch.py` (deployed config). Determinized PUCT over the v_state leaf
//! with an H3-derived policy prior (softmax over take_value + the H3-greedy-pick anchor).

use crate::engine::{self, State, A_BUY_BOARD, A_BUY_RESV, A_PASS, A_RES_BOARD, A_RES_DECK, A_TAKE3,
                    N_ACTIONS, PLAY};
use crate::heuristic::{self, W_GEM, W_GOLD, W_TEMPO};
use crate::mcts::Search;
use crate::rng::Rng;
use crate::v_state;
use crate::valuation::Valuation;

pub const C_PUCT: f64 = 1.5;
pub const SIMS: usize = 200;
pub const POLICY_TEMP: f64 = 0.7;
pub const RESERVE_PRIOR_W: f64 = 0.5;
pub const TAKE_PRIOR_W: f64 = 1.0;
pub const H3_PICK_W: f64 = 1.5;

/// Card id a buy/reserve-from-board action targets, or -1 (deck reserve / non-card action).
fn card_for_action(s: &State, seat: usize, a: usize) -> i32 {
    if (A_BUY_BOARD..A_BUY_BOARD + 12).contains(&a) {
        s.board[a - A_BUY_BOARD]
    } else if (A_BUY_RESV..A_BUY_RESV + 3).contains(&a) {
        let ri = a - A_BUY_RESV;
        if ri < s.reserved[seat].len() {
            s.reserved[seat][ri]
        } else {
            -1
        }
    } else if (A_RES_BOARD..A_RES_BOARD + 12).contains(&a) {
        s.board[a - A_RES_BOARD]
    } else {
        -1
    }
}

/// Pre-softmax score per legal action: buys by take_value, reserves at a discount, takes by their
/// colors' share of the top targets' demand (normalized), + the H3-greedy-pick anchor.
fn action_scores(val: &Valuation, seat: usize, legal: &[usize]) -> Vec<f64> {
    let s = val.s;
    let tg = heuristic::targets(val, seat);
    let need = heuristic::need_vector(val, seat, &tg);
    let nt: f64 = need.iter().sum();
    let need_tot = if nt != 0.0 { nt } else { 1.0 };
    let mut scores = vec![0.0f64; N_ACTIONS];
    for &a in legal {
        if (A_BUY_BOARD..A_BUY_RESV + 3).contains(&a) {
            let ci = card_for_action(s, seat, a);
            scores[a] = if ci >= 0 { heuristic::take_value(val, ci, seat) } else { 0.0 };
        } else if (A_RES_BOARD..A_RES_DECK + 3).contains(&a) {
            let ci = card_for_action(s, seat, a);
            let tv = if ci >= 0 { heuristic::take_value(val, ci, seat) } else { 0.0 };
            scores[a] = RESERVE_PRIOR_W * tv;
        } else if (A_TAKE3..A_PASS).contains(&a) {
            if let Some(colors) = heuristic::take_colors(a) {
                let s_need: f64 = colors.iter().map(|&c| need[c]).sum();
                scores[a] = TAKE_PRIOR_W * (s_need / need_tot);
            }
        }
    }
    if H3_PICK_W > 0.0 {
        let a_star = heuristic::choose_action_with(val, seat);
        scores[a_star] += H3_PICK_W;
    }
    scores
}

/// Softmax of action_scores over legal actions -> prior probs [N_ACTIONS] (0 on illegal).
fn policy_prior(val: &Valuation, seat: usize, legal: &[usize]) -> Vec<f64> {
    let mut probs = vec![0.0f64; N_ACTIONS];
    if legal.is_empty() {
        return probs;
    }
    let scores = action_scores(val, seat, legal);
    let mx = legal.iter().map(|&a| scores[a]).fold(f64::NEG_INFINITY, f64::max);
    let mut tot = 0.0;
    for &a in legal {
        let e = ((scores[a] - mx) / POLICY_TEMP).exp();
        probs[a] = e;
        tot += e;
    }
    if tot > 0.0 {
        for &a in legal {
            probs[a] /= tot;
        }
    }
    probs
}

/// Build a deterministic mid-game PLAY position by playing `moves` greedy-H3 plies from new_game(seed).
/// Used by the benchmarks (native + WASM) so both measure the search on the SAME representative state.
pub fn demo_position(seed: u64, moves: u32) -> State {
    let mut s = engine::new_game(seed, 15);
    for _ in 0..moves {
        if s.phase == engine::OVER {
            break;
        }
        let a = heuristic::choose_action(&s, s.turn);
        engine::apply(&mut s, a);
    }
    s
}

/// Return a legal engine action for `seat`, running a FIXED `sims` simulations.
pub fn choose_action(s: &State, seat: usize, sims: usize, rng: &mut Rng) -> usize {
    choose_action_until(s, seat, rng, |n| n < sims)
}

/// PUCT pick, then refined by the exact endgame solver (#1). `eg_rng` is SEPARATE from the search rng
/// so the PUCT decision stream is unaffected by whether refinement runs — a clean A/B (the self-gate
/// relies on this). Falls through to the plain PUCT move outside endgame positions.
pub fn choose_action_refined(
    s: &State,
    seat: usize,
    sims: usize,
    search_rng: &mut Rng,
    eg_rng: &mut Rng,
) -> usize {
    let puct = choose_action(s, seat, sims, search_rng);
    crate::endgame::refine(s, seat, puct, eg_rng)
}

/// Like `choose_action` but with a CUSTOM leaf VALUE function (keeps the H3 policy prior + the
/// determinized PUCT). For the value-first ladder rung 2: swap v_state for a learned value as the MCTS
/// leaf and test whether it converts through search (where 1-ply's fine-grained-noise penalty washes
/// out). `leaf_value(state, seat)` returns the value in [-1,1] from `seat`'s perspective.
pub fn choose_action_leaf(
    s: &State,
    seat: usize,
    sims: usize,
    rng: &mut Rng,
    leaf_value: &dyn Fn(&State, usize) -> f64,
) -> usize {
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        return A_PASS;
    }
    if s.phase != PLAY || legal.len() == 1 {
        return heuristic::choose_action(s, seat);
    }
    let mut search = Search::new(s.clone(), C_PUCT);
    let eval = |ls: &State, lseat: usize, ll: &[usize]| -> (Vec<f64>, f64) {
        let val = Valuation::new(ls, W_TEMPO, W_GEM, W_GOLD);
        let probs = policy_prior(&val, lseat, ll);
        let value = leaf_value(ls, lseat);
        (probs, value)
    };
    let mut n = 0usize;
    while n < sims {
        search.sim(rng, &eval);
        n += 1;
    }
    let visits = search.root_visits();
    let mut best = legal[0];
    let mut bv = visits[legal[0]];
    for &a in &legal[1..] {
        if visits[a] > bv {
            bv = visits[a];
            best = a;
        }
    }
    best
}

/// Root visit counts (length N_ACTIONS) after running simulations while `keep_going(n_done)` is true.
/// PLAY decisions are searched (determinized PUCT, V leaf); DISCARD/NOBLE and single-legal positions
/// one-hot the greedy-H3 pick (so argmax/aggregation still selects it). This is the unit ROOT-PARALLEL
/// aggregates: independent searches' visit vectors are SUMMED across workers, then argmax'd.
pub fn root_visits_until<F: FnMut(usize) -> bool>(
    s: &State,
    seat: usize,
    rng: &mut Rng,
    mut keep_going: F,
) -> Vec<i32> {
    let mut out = vec![0i32; N_ACTIONS];
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        out[A_PASS] = 1;
        return out;
    }
    if s.phase != PLAY || legal.len() == 1 {
        out[heuristic::choose_action(s, seat)] = 1;
        return out;
    }
    let mut search = Search::new(s.clone(), C_PUCT);
    let eval = |ls: &State, lseat: usize, ll: &[usize]| -> (Vec<f64>, f64) {
        let val = Valuation::new(ls, W_TEMPO, W_GEM, W_GOLD);
        let value = v_state::value_with(&val, lseat);
        let probs = policy_prior(&val, lseat, ll);
        (probs, value)
    };
    let mut n = 0usize;
    while keep_going(n) {
        search.sim(rng, &eval);
        n += 1;
    }
    search.root_visits().to_vec()
}

/// Root visit counts with a CUSTOM leaf VALUE function (keeps the H3 prior) — the root-parallel
/// serving unit for variant N (learned value leaf). Mirrors `root_visits_until` but swaps the leaf.
pub fn root_visits_until_leaf<F: FnMut(usize) -> bool>(
    s: &State,
    seat: usize,
    rng: &mut Rng,
    mut keep_going: F,
    leaf_value: &dyn Fn(&State, usize) -> f64,
) -> Vec<i32> {
    let mut out = vec![0i32; N_ACTIONS];
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        out[A_PASS] = 1;
        return out;
    }
    if s.phase != PLAY || legal.len() == 1 {
        out[heuristic::choose_action(s, seat)] = 1;
        return out;
    }
    let mut search = Search::new(s.clone(), C_PUCT);
    let eval = |ls: &State, lseat: usize, ll: &[usize]| -> (Vec<f64>, f64) {
        let val = Valuation::new(ls, W_TEMPO, W_GEM, W_GOLD);
        let probs = policy_prior(&val, lseat, ll);
        let value = leaf_value(ls, lseat);
        (probs, value)
    };
    let mut n = 0usize;
    while keep_going(n) {
        search.sim(rng, &eval);
        n += 1;
    }
    search.root_visits().to_vec()
}

/// Like `root_visits_until_leaf` but ALSO returns the root per-edge WIN sums, so a caller can surface
/// the searched position value (sum W / sum N) and per-move Q (W[a]/N[a]). Used by the WWSD browser
/// overlay's eval display; the play path uses the visits-only variant. Degenerate (no-search) phases
/// return one-hot visits and all-zero wins.
pub fn root_nw_until_leaf<F: FnMut(usize) -> bool>(
    s: &State,
    seat: usize,
    rng: &mut Rng,
    mut keep_going: F,
    leaf_value: &dyn Fn(&State, usize) -> f64,
) -> (Vec<i32>, Vec<f64>) {
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        let mut n = vec![0i32; N_ACTIONS];
        n[A_PASS] = 1;
        return (n, vec![0.0; N_ACTIONS]);
    }
    if s.phase != PLAY || legal.len() == 1 {
        let mut n = vec![0i32; N_ACTIONS];
        n[heuristic::choose_action(s, seat)] = 1;
        return (n, vec![0.0; N_ACTIONS]);
    }
    let mut search = Search::new(s.clone(), C_PUCT);
    let eval = |ls: &State, lseat: usize, ll: &[usize]| -> (Vec<f64>, f64) {
        let val = Valuation::new(ls, W_TEMPO, W_GEM, W_GOLD);
        let probs = policy_prior(&val, lseat, ll);
        let value = leaf_value(ls, lseat);
        (probs, value)
    };
    let mut i = 0usize;
    while keep_going(i) {
        search.sim(rng, &eval);
        i += 1;
    }
    (search.root_visits().to_vec(), search.root_wins().to_vec())
}

/// Return a legal engine action for `seat`, running simulations while `keep_going(n_done)` is true.
/// Lets the caller use a sims count OR a wall-clock budget. = argmax (first-max over legal) of the
/// root visits.
pub fn choose_action_until<F: FnMut(usize) -> bool>(
    s: &State,
    seat: usize,
    rng: &mut Rng,
    keep_going: F,
) -> usize {
    let visits = root_visits_until(s, seat, rng, keep_going);
    let legal = engine::legal_actions(s);
    if legal.is_empty() {
        return A_PASS;
    }
    let mut best = legal[0];
    let mut bestv = visits[legal[0]];
    for &a in &legal[1..] {
        if visits[a] > bestv {
            bestv = visits[a];
            best = a;
        }
    }
    best
}
