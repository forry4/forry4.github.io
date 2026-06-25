//! Layer-D leaf parity (the FULL gate): v_state.value + the component breakdown, vs Python v_state.
//! Fixtures from `tools/gen_vstate_fixtures.py`. Tolerance 1e-9.

mod common;

use common::Dump;
use serde::Deserialize;
use spender_core::v_state as VS;
use spender_core::valuation::Valuation;

#[derive(Deserialize)]
struct Comp {
    points_me: f64,
    points_opp: f64,
    engine_me: f64,
    engine_opp: f64,
    progress_me: f64,
    progress_opp: f64,
    noble_me: f64,
    noble_opp: f64,
    econ_me: f64,
    econ_opp: f64,
    stand_me: f64,
    stand_opp: f64,
    value: f64,
}

#[derive(Deserialize)]
struct Fixture {
    state: Dump,
    value0: f64,
    value1: f64,
    comp: Comp,
}

fn close(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-9
}

#[test]
fn vstate_matches_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/vstate_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_vstate_fixtures.py"));
    let fixtures: Vec<Fixture> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!fixtures.is_empty(), "no fixtures");

    // H3 leaf weights (heuristic.rs)
    let (wt, wg, wgo) = (spender_core::heuristic::W_TEMPO, spender_core::heuristic::W_GEM, spender_core::heuristic::W_GOLD);

    for (i, fx) in fixtures.iter().enumerate() {
        let s = fx.state.to_state();
        // headline: the leaf value for both seats
        let v0 = VS::value(&s, 0);
        let v1 = VS::value(&s, 1);
        assert!(close(v0, fx.value0), "value(0) #{i}: {v0} vs {}", fx.value0);
        assert!(close(v1, fx.value1), "value(1) #{i}: {v1} vs {}", fx.value1);

        // component breakdown (me=0, opp=1) for localization
        let val = Valuation::new(&s, wt, wg, wgo);
        let c = &fx.comp;
        assert!(close(VS::points_term(&val, 0), c.points_me), "points_me #{i}");
        assert!(close(VS::points_term(&val, 1), c.points_opp), "points_opp #{i}");
        assert!(close(VS::engine_stock(&val, 0), c.engine_me), "engine_me #{i}");
        assert!(close(VS::engine_stock(&val, 1), c.engine_opp), "engine_opp #{i}");
        assert!(close(VS::progress(&VS::seat_targets(&val, 0, false)), c.progress_me), "progress_me #{i}");
        assert!(close(VS::progress(&VS::seat_targets(&val, 1, true)), c.progress_opp), "progress_opp #{i}");
        assert!(close(VS::noble_stand(&val, 0), c.noble_me), "noble_me #{i}");
        assert!(close(VS::noble_stand(&val, 1), c.noble_opp), "noble_opp #{i}");
        let t_me = VS::seat_targets(&val, 0, false);
        let t_opp = VS::seat_targets(&val, 1, true);
        assert!(close(VS::econ(&val, 0, &t_me), c.econ_me), "econ_me #{i}");
        assert!(close(VS::econ(&val, 1, &t_opp), c.econ_opp), "econ_opp #{i}");
        assert!(close(VS::stand(&val, 0, 0), c.stand_me), "stand_me #{i}: {} vs {}", VS::stand(&val, 0, 0), c.stand_me);
        assert!(close(VS::stand(&val, 1, 0), c.stand_opp), "stand_opp #{i}: {} vs {}", VS::stand(&val, 1, 0), c.stand_opp);
        assert!(close(VS::value_with(&val, 0), c.value), "value(comp) #{i}");
    }
    eprintln!("v_state (full leaf) parity OK: {} states", fixtures.len());
}
