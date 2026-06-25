//! Layer-B leaf parity: Valuation context + engine_value chain + turns + noble time-gate, vs Python.
//! Fixtures from `tools/gen_valuation_fixtures.py`. Tolerance 1e-9 (same IEEE ops + summation order).

mod common;

use common::Dump;
use serde::Deserialize;
use spender_core::heuristic;
use spender_core::valuation::Valuation;

#[derive(Deserialize)]
struct Case {
    ci: i32,
    seat: usize,
    cs: f64,
    eb: f64,
    pot: f64,
    ev: f64,
    np: f64,
    take: f64,
    tk_eng: f64,
    tk_pt: f64,
    tk_cost: f64,
}

#[derive(Deserialize)]
struct Fixture {
    state: Dump,
    wt: f64,
    wg: f64,
    wgo: f64,
    turns: f64,
    dcd: [f64; 5],
    dds0: [f64; 5],
    dds1: [f64; 5],
    cases: Vec<Case>,
}

fn close(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-9
}
fn close_arr(a: &[f64; 5], b: &[f64; 5]) -> bool {
    (0..5).all(|i| close(a[i], b[i]))
}

#[test]
fn valuation_matches_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/valuation_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_valuation_fixtures.py"));
    let fixtures: Vec<Fixture> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!fixtures.is_empty(), "no fixtures");

    let mut n = 0usize;
    for fx in &fixtures {
        let s = fx.state.to_state();
        let val = Valuation::new(&s, fx.wt, fx.wg, fx.wgo);
        assert!(close(val.estimated_turns_remaining(), fx.turns), "turns: {} vs {}", val.estimated_turns_remaining(), fx.turns);
        assert!(close_arr(&val.deck_color_demand, &fx.dcd), "deck_color_demand");
        assert!(close_arr(&val.deck_demand_seat(0), &fx.dds0), "deck_demand_seat(0)");
        assert!(close_arr(&val.deck_demand_seat(1), &fx.dds1), "deck_demand_seat(1)");
        for c in &fx.cases {
            let (ci, seat) = (c.ci, c.seat);
            let tag = format!("ci={ci} seat={seat}");
            let cs = val.cost_scalar(ci, seat, None);
            assert!(close(cs, c.cs), "cost_scalar {tag}: {cs} vs {}", c.cs);
            let eb = val.eng_base(ci, seat);
            assert!(close(eb, c.eb), "eng_base {tag}: {eb} vs {}", c.eb);
            let pot = val.potential_value(ci, seat);
            assert!(close(pot, c.pot), "potential_value {tag}: {pot} vs {}", c.pot);
            let ev = val.engine_value(ci, seat);
            assert!(close(ev, c.ev), "engine_value {tag}: {ev} vs {}", c.ev);
            let np = val.noble_progress(ci, seat);
            assert!(close(np, c.np), "noble_progress {tag}: {np} vs {}", c.np);
            // Layer C: heuristic3.components (take, engine, point, cost)
            let (tk, eng, pt, cst) = heuristic::components(&val, ci, seat);
            assert!(close(cst, c.tk_cost), "components.cost {tag}: {cst} vs {}", c.tk_cost);
            assert!(close(eng, c.tk_eng), "components.engine {tag}: {eng} vs {}", c.tk_eng);
            assert!(close(pt, c.tk_pt), "components.point {tag}: {pt} vs {}", c.tk_pt);
            assert!(close(tk, c.take), "components.take {tag}: {tk} vs {}", c.take);
            n += 1;
        }
    }
    eprintln!("valuation parity OK: {} states, {} cases", fixtures.len(), n);
}
