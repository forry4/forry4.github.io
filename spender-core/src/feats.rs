//! Canonical feature encoder for the learned value net — ONE source of truth shared by the harvest
//! (training data) and the Rust 1-ply / MCTS-leaf players, so the served features byte-match the
//! trained ones. `features(s, seat)` returns the vector in the SAME order as `header()` (the CSV
//! columns, minus the appended `label`). Keep them in lock-step.

use crate::cards::{BONUS, COST, LEVEL_OF, NOBLE_PTS, NOBLE_REQ, PTS};
use crate::engine::State;
use crate::heuristic::{W_GEM, W_GOLD, W_TEMPO};
use crate::v_state;
use crate::valuation::{self, Valuation};

/// Feature vector for `seat` to move in `s`. Order MUST match `header()`.
pub fn features(s: &State, seat: usize) -> Vec<f64> {
    let opp = 1 - seat;
    let val = Valuation::new(s, W_TEMPO, W_GEM, W_GOLD);
    let mut f: Vec<f64> = Vec::with_capacity(96);

    // meta
    f.push(s.ply as f64);
    f.push(seat as f64);
    f.push(s.final_trigger as f64);
    f.push(s.win_points as f64);

    // v_state baseline (the hand-value to refine), from the mover's perspective
    f.push(v_state::value_with(&val, seat));

    // per-seat raw state (me then opp)
    for &p in &[seat, opp] {
        f.push(s.points[p] as f64);
        f.push(s.purchased_n[p] as f64);
        f.push(s.reserved[p].len() as f64);
        f.push(s.tokens[p].iter().sum::<i32>() as f64);
        f.push(s.tokens[p][5] as f64); // gold
        for c in 0..5 {
            f.push(s.bonuses[p][c] as f64);
        }
        for c in 0..5 {
            f.push(s.tokens[p][c] as f64);
        }
    }

    // bank
    for c in 0..6 {
        f.push(s.bank[c] as f64);
    }

    // v_state components (me, opp)
    for &p in &[seat, opp] {
        let tg = v_state::seat_targets(&val, p, false);
        f.push(v_state::points_term(&val, p));
        f.push(v_state::engine_stock(&val, p));
        f.push(v_state::progress(&tg));
        f.push(v_state::noble_stand(&val, p));
        f.push(v_state::econ(&val, p, &tg));
    }

    // board cards: points + affordability gap for me/opp (-1 sentinels for empty slots)
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 {
            f.push(PTS[ci as usize] as f64);
            f.push(valuation::gold_needed(s, ci, seat) as f64);
            f.push(valuation::gold_needed(s, ci, opp) as f64);
        } else {
            f.push(-1.0);
            f.push(-1.0);
            f.push(-1.0);
        }
    }

    // nobles: bonus deficit for me/opp (-1 for empty slots)
    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni >= 0 {
            let req = &NOBLE_REQ[ni as usize];
            let def = |p: usize| -> i32 { (0..5).map(|c| (req[c] - s.bonuses[p][c]).max(0)).sum() };
            f.push(def(seat) as f64);
            f.push(def(opp) as f64);
        } else {
            f.push(-1.0);
            f.push(-1.0);
        }
    }

    // undealt deck remaining per level + per-color undealt cost
    let mut lvl_rem = [0.0f64; 3];
    let mut color_cost = [0.0f64; 5];
    for lvl in 0..3 {
        lvl_rem[lvl] = s.decks[lvl].len() as f64;
        for &ci in &s.decks[lvl] {
            for c in 0..5 {
                color_cost[c] += COST[ci as usize][c] as f64;
            }
        }
    }
    f.extend_from_slice(&lvl_rem);
    f.extend_from_slice(&color_cost);

    f
}

/// 125-feature encoder for variant PV (the AlphaZero policy+value net). IDENTICAL to `features()` (the
/// 101-feat variant-N encoder) EXCEPT the per-board-card block adds two Tier-1 policy features —
/// `engine_value` and `noble_progress` (mover perspective) — so 5 values/slot instead of 3 (12 slots ×
/// 2 = +24 → 125). Kept SEPARATE so variant N's 101-feat `n_model.json` keeps getting its 101 inputs.
/// This is the exact encoder `pv_model.json` was trained on — DO NOT change without retraining the net.
pub fn features_az(s: &State, seat: usize) -> Vec<f64> {
    let opp = 1 - seat;
    let val = Valuation::new(s, W_TEMPO, W_GEM, W_GOLD);
    let mut f: Vec<f64> = Vec::with_capacity(125);

    f.push(s.ply as f64);
    f.push(seat as f64);
    f.push(s.final_trigger as f64);
    f.push(s.win_points as f64);
    f.push(v_state::value_with(&val, seat));

    for &p in &[seat, opp] {
        f.push(s.points[p] as f64);
        f.push(s.purchased_n[p] as f64);
        f.push(s.reserved[p].len() as f64);
        f.push(s.tokens[p].iter().sum::<i32>() as f64);
        f.push(s.tokens[p][5] as f64);
        for c in 0..5 {
            f.push(s.bonuses[p][c] as f64);
        }
        for c in 0..5 {
            f.push(s.tokens[p][c] as f64);
        }
    }

    for c in 0..6 {
        f.push(s.bank[c] as f64);
    }

    for &p in &[seat, opp] {
        let tg = v_state::seat_targets(&val, p, false);
        f.push(v_state::points_term(&val, p));
        f.push(v_state::engine_stock(&val, p));
        f.push(v_state::progress(&tg));
        f.push(v_state::noble_stand(&val, p));
        f.push(v_state::econ(&val, p, &tg));
    }

    // board cards: pts + affordability gap (me/opp) + engine_value + noble_progress (the PV-only adds)
    for slot in 0..12 {
        let ci = s.board[slot];
        if ci >= 0 {
            f.push(PTS[ci as usize] as f64);
            f.push(valuation::gold_needed(s, ci, seat) as f64);
            f.push(valuation::gold_needed(s, ci, opp) as f64);
            f.push(val.engine_value(ci, seat));
            f.push(val.noble_progress(ci, seat));
        } else {
            for _ in 0..5 {
                f.push(-1.0);
            }
        }
    }

    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni >= 0 {
            let req = &NOBLE_REQ[ni as usize];
            let def = |p: usize| -> i32 { (0..5).map(|c| (req[c] - s.bonuses[p][c]).max(0)).sum() };
            f.push(def(seat) as f64);
            f.push(def(opp) as f64);
        } else {
            f.push(-1.0);
            f.push(-1.0);
        }
    }

    let mut lvl_rem = [0.0f64; 3];
    let mut color_cost = [0.0f64; 5];
    for lvl in 0..3 {
        lvl_rem[lvl] = s.decks[lvl].len() as f64;
        for &ci in &s.decks[lvl] {
            for c in 0..5 {
                color_cost[c] += COST[ci as usize][c] as f64;
            }
        }
    }
    f.extend_from_slice(&lvl_rem);
    f.extend_from_slice(&color_cost);

    f
}

/// ENRICHED 178-feat encoder for the deployed PV champion `net_ext_19`: the deployed base 125
/// (`features_az`, byte-identical to rust-search's `features()`) + 5 groups appended in A,B,C,D,E order:
///   A) per-color self-need (5) — summed color deficits over the top-6 v_state targets.
///   B) opponent FACE-UP reserve content (3x4 = pts/need/eng/nob); blind/empty -> -1 (hidden deck-reserves
///      stay hidden).
///   C) own reserve content (3x4); empty -> -1.
///   D) per-board-card take_value (12) — H3 acquisition score; empty -> -1.
///   E) per-board-card turns-to-afford (12) — H3 tempo; empty -> -1.
/// Total 125 + 5 + 12 + 12 + 12 + 12 = 178. PORTED VERBATIM from rust-search `feats::features_ext` (the
/// encoder net_ext_19 trained on); every helper below is byte-identical across the branches
/// (engine/valuation/v_state/heuristic), so the served features byte-match the trained ones by construction.
pub fn features_ext(s: &State, seat: usize) -> Vec<f64> {
    let opp = 1 - seat;
    let val = Valuation::new(s, W_TEMPO, W_GEM, W_GOLD);
    let mut f = features_az(s, seat); // deployed base 125

    // A) per-color self-need (5)
    let tg = v_state::seat_targets(&val, seat, false);
    let k = tg.len().min(6);
    let mut need = [0.0f64; 5];
    for &(_, ci) in &tg[..k] {
        let d = valuation::color_deficits(s, ci, seat);
        for c in 0..5 {
            need[c] += d[c] as f64;
        }
    }
    f.extend_from_slice(&need);

    // B) opponent face-up reserve content (3 slots x 4); blind/empty -> -1 (hidden info stays hidden)
    for slot in 0..3 {
        if slot < s.reserved[opp].len() && !s.reserved_blind[opp][slot] {
            let ci = s.reserved[opp][slot];
            f.push(PTS[ci as usize] as f64);
            f.push(valuation::gold_needed(s, ci, opp) as f64);
            f.push(val.engine_value(ci, opp));
            f.push(val.noble_progress(ci, opp));
        } else {
            for _ in 0..4 {
                f.push(-1.0);
            }
        }
    }

    // C) own reserve content (3 slots x 4); empty -> -1
    for slot in 0..3 {
        if slot < s.reserved[seat].len() {
            let ci = s.reserved[seat][slot];
            f.push(PTS[ci as usize] as f64);
            f.push(valuation::gold_needed(s, ci, seat) as f64);
            f.push(val.engine_value(ci, seat));
            f.push(val.noble_progress(ci, seat));
        } else {
            for _ in 0..4 {
                f.push(-1.0);
            }
        }
    }

    // D) per-board-card take_value (12) — H3 acquisition score; empty -> -1
    for slot in 0..12 {
        let ci = s.board[slot];
        f.push(if ci >= 0 { crate::heuristic::take_value(&val, ci, seat) } else { -1.0 });
    }

    // E) per-board-card turns-to-afford (12) = H3 tempo (take-turns to cover the deficit); empty -> -1
    for slot in 0..12 {
        let ci = s.board[slot];
        f.push(if ci >= 0 { valuation::tempo(s, ci, seat) as f64 } else { -1.0 });
    }

    f
}

/// CSV header — column order matches `features()` exactly, plus the appended `label`.
pub fn header() -> String {
    let mut h: Vec<String> = vec![
        "ply".into(), "mover".into(), "final_trigger".into(), "win_points".into(), "vstate".into(),
    ];
    for who in ["me", "opp"] {
        for n in ["points", "npurch", "nresv", "ntok", "gold"] {
            h.push(format!("{who}_{n}"));
        }
        for c in 0..5 {
            h.push(format!("{who}_bon{c}"));
        }
        for c in 0..5 {
            h.push(format!("{who}_tok{c}"));
        }
    }
    for c in 0..6 {
        h.push(format!("bank{c}"));
    }
    for who in ["me", "opp"] {
        for n in ["ptsterm", "engstock", "progress", "noble", "econ"] {
            h.push(format!("{who}_{n}"));
        }
    }
    for slot in 0..12 {
        h.push(format!("bd{slot}_pts"));
        h.push(format!("bd{slot}_myneed"));
        h.push(format!("bd{slot}_oppneed"));
    }
    for slot in 0..3 {
        h.push(format!("nb{slot}_mydef"));
        h.push(format!("nb{slot}_oppdef"));
    }
    for lvl in 0..3 {
        h.push(format!("deck{lvl}_rem"));
    }
    for c in 0..5 {
        h.push(format!("deckcost{c}"));
    }
    h.push("label".into());
    h.join(",")
}

/// Number of features (excludes the label column).
pub fn n_features() -> usize {
    header().split(',').count() - 1
}

// ── CARD-SET ATTENTION tokenizer (ported from rust-search for variant-N attention serving) ──
// 18 tokens (12 board + 3 own-reserved + 3 nobles, empties masked) x 24 feats; + 28 state feats.
// One unified per-token schema; nobles encode their REQUIREMENTS in the cost slot (a noble is "acquired"
// by having those bonuses). Mover = seat; OPP reserves are NOT tokenized (no hidden-info leak).
pub const TOK_N: usize = 18;
pub const TOK_F: usize = 24;
pub const TOK_STATE: usize = 28;

fn card_token(s: &State, val: &Valuation, ci: i32, seat: usize, opp: usize, ttype: usize, out: &mut Vec<f64>) {
    let c = ci as usize;
    for k in 0..5 { out.push(COST[c][k] as f64); }                                   // 0-4 cost
    for k in 0..5 { out.push(if BONUS[c] == k { 1.0 } else { 0.0 }); }               // 5-9 bonus 1-hot
    out.push(PTS[c] as f64);                                                          // 10 points
    out.push(LEVEL_OF[c] as f64 / 3.0);                                               // 11 level
    out.push(crate::heuristic::take_value(val, ci, seat));                            // 12 take_value (me)
    out.push(valuation::tempo(s, ci, seat) as f64);                                   // 13 turns-to-afford
    out.push(val.engine_value(ci, seat));                                             // 14 engine
    out.push(val.noble_progress(ci, seat));                                           // 15 noble progress
    out.push(valuation::gold_needed(s, ci, seat) as f64);                             // 16 gold needed
    out.push(if valuation::affordable_now(s, ci, seat) { 1.0 } else { 0.0 });         // 17 affordable now (me)
    out.push(crate::heuristic::take_value(val, ci, opp));                             // 18 opp take_value
    out.push(if valuation::affordable_now(s, ci, opp) { 1.0 } else { 0.0 });          // 19 opp affordable now
    out.push((s.points[seat] + PTS[c] + valuation::noble_completion_pts(s, ci, seat)) as f64 / s.win_points as f64); // 20 closing
    for t in 0..3 { out.push(if t == ttype { 1.0 } else { 0.0 }); }                   // 21-23 type 1-hot
}

fn noble_token(s: &State, ni: i32, seat: usize, opp: usize, out: &mut Vec<f64>) {
    let n = ni as usize;
    let req = &NOBLE_REQ[n];
    for k in 0..5 { out.push(req[k] as f64); }                                         // 0-4 cost = requirements
    for _ in 0..5 { out.push(0.0); }                                                   // 5-9 bonus 1-hot = none
    out.push(NOBLE_PTS[n] as f64);                                                     // 10 points
    out.push(0.0);                                                                     // 11 level (n/a)
    out.push(0.0); out.push(0.0); out.push(0.0);                                       // 12-14 take/tempo/engine n/a
    let (mut met_s, mut met_o, mut tot, mut def_s, mut def_o) = (0i32, 0i32, 0i32, 0i32, 0i32);
    for c in 0..5 {
        let r = req[c];
        tot += r;
        met_s += s.bonuses[seat][c].min(r);
        met_o += s.bonuses[opp][c].min(r);
        def_s += (r - s.bonuses[seat][c]).max(0);
        def_o += (r - s.bonuses[opp][c]).max(0);
    }
    out.push(if tot > 0 { met_s as f64 / tot as f64 } else { 0.0 });                   // 15 my progress
    out.push(def_s as f64);                                                            // 16 my deficit
    out.push(if def_s == 0 { 1.0 } else { 0.0 });                                      // 17 I qualify
    out.push(if tot > 0 { met_o as f64 / tot as f64 } else { 0.0 });                   // 18 opp progress
    out.push(if def_o == 0 { 1.0 } else { 0.0 });                                      // 19 opp qualifies
    out.push((s.points[seat] + NOBLE_PTS[n]) as f64 / s.win_points as f64);            // 20 closing
    out.push(0.0); out.push(0.0); out.push(1.0);                                       // 21-23 type = noble
}

/// Tokenize a state from `seat`'s view -> (tokens [18*24], mask [18], state [28]).
pub fn features_tokens(s: &State, seat: usize) -> (Vec<f64>, Vec<f64>, Vec<f64>) {
    let opp = 1 - seat;
    let val = Valuation::new(s, W_TEMPO, W_GEM, W_GOLD);
    let mut toks = Vec::with_capacity(TOK_N * TOK_F);
    let mut mask = vec![0.0f64; TOK_N];
    for i in 0..12 {
        let ci = s.board[i];
        if ci >= 0 { card_token(s, &val, ci, seat, opp, 0, &mut toks); mask[i] = 1.0; }
        else { for _ in 0..TOK_F { toks.push(0.0); } }
    }
    for i in 0..3 {
        if i < s.reserved[seat].len() {
            card_token(s, &val, s.reserved[seat][i], seat, opp, 1, &mut toks); mask[12 + i] = 1.0;
        } else { for _ in 0..TOK_F { toks.push(0.0); } }
    }
    for i in 0..3 {
        let ni = s.nobles[i];
        if ni >= 0 { noble_token(s, ni, seat, opp, &mut toks); mask[15 + i] = 1.0; }
        else { for _ in 0..TOK_F { toks.push(0.0); } }
    }
    let mut st = Vec::with_capacity(TOK_STATE);
    for c in 0..5 { st.push(s.bonuses[seat][c] as f64); }
    for c in 0..5 { st.push(s.bonuses[opp][c] as f64); }
    for c in 0..6 { st.push(s.tokens[seat][c] as f64); }
    for c in 0..6 { st.push(s.tokens[opp][c] as f64); }
    st.push(s.points[seat] as f64);
    st.push(s.points[opp] as f64);
    st.push(s.win_points as f64);
    st.push(s.ply as f64 / 50.0);
    st.push(s.reserved[seat].len() as f64);
    st.push(s.reserved[opp].len() as f64);
    (toks, mask, st)
}
