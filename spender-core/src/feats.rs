//! Canonical feature encoder for the learned value net — ONE source of truth shared by the harvest
//! (training data) and the Rust 1-ply / MCTS-leaf players, so the served features byte-match the
//! trained ones. `features(s, seat)` returns the vector in the SAME order as `header()` (the CSV
//! columns, minus the appended `label`). Keep them in lock-step.

use crate::cards::{COST, NOBLE_REQ, PTS};
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
