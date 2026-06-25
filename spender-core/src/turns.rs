//! Turns-remaining horizon: NN lookup into the embedded (cards, points, gems) -> avg-turns-left
//! tables (port of valuation3's _lookup_turns + estimated_turns_remaining, mode "table").

use crate::turns_table::{TURNS_ROWS, TURNS_ROWS_21};
use std::collections::HashMap;
use std::sync::OnceLock;

pub const TURNS_FLOOR: f64 = 1.0;
const GEM_DIST_W: f64 = 0.25;
const FALLBACK: f64 = 12.0;

pub struct Table {
    map: HashMap<(i32, i32, i32), f64>,
    order: Vec<(i32, i32, i32)>, // unique keys, first-occurrence order (matches Python list(d.keys()))
}

fn build(rows: &[(i32, i32, i32, f64)]) -> Table {
    let mut map = HashMap::with_capacity(rows.len());
    let mut order = Vec::with_capacity(rows.len());
    for &(c, p, g, t) in rows {
        let k = (c, p, g);
        if !map.contains_key(&k) {
            order.push(k);
        }
        map.insert(k, t); // last write wins, like a Python dict
    }
    Table { map, order }
}

impl Table {
    fn lookup(&self, cards: i32, points: i32, gems: i32) -> f64 {
        if let Some(&v) = self.map.get(&(cards, points, gems)) {
            return v;
        }
        let mut best = FALLBACK;
        let mut bestd: Option<f64> = None;
        for &(kc, kp, kg) in &self.order {
            let dd = (kc - cards).abs() as f64
                + 2.0 * (kp - points).abs() as f64
                + GEM_DIST_W * (kg - gems).abs() as f64;
            if bestd.map_or(true, |b| dd < b) {
                bestd = Some(dd);
                best = self.map[&(kc, kp, kg)];
            }
        }
        best
    }
}

fn t15() -> &'static Table {
    static T: OnceLock<Table> = OnceLock::new();
    T.get_or_init(|| build(&TURNS_ROWS))
}
fn t21() -> &'static Table {
    static T: OnceLock<Table> = OnceLock::new();
    T.get_or_init(|| build(&TURNS_ROWS_21))
}

/// min over both seats of the table lookup, floored at TURNS_FLOOR.
pub fn estimate(
    win_points: i32,
    c0: i32, p0: i32, g0: i32,
    c1: i32, p1: i32, g1: i32,
) -> f64 {
    let tbl = if win_points == 21 && !TURNS_ROWS_21.is_empty() {
        t21()
    } else {
        t15()
    };
    let tr = tbl.lookup(c0, p0, g0).min(tbl.lookup(c1, p1, g1));
    if tr > TURNS_FLOOR {
        tr
    } else {
        TURNS_FLOOR
    }
}
