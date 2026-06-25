//! Layer-A leaf parity: the stateless per-card/seat scalars in `valuation`, vs Python `valuation3`.
//! Fixtures from `tools/gen_scalar_fixtures.py`. Ints exact; floats within 1e-9.

mod common;

use common::Dump;
use serde::Deserialize;
use spender_core::valuation as V;

#[derive(Deserialize)]
struct Case {
    ci: i32,
    seat: usize,
    eff: [i32; 5],
    tec: i32,
    conc: i32,
    gn: i32,
    cdef: [i32; 5],
    gtc: i32,
    tta: i32,
    tempo: i32,
    gemc: i32,
    goldc: i32,
    gshort: i32,
    nprog: f64,
    ncomp: i32,
    effi: f64,
    vclose: f64,
}

#[derive(Deserialize)]
struct Fixture {
    state: Dump,
    cases: Vec<Case>,
}

fn close(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-9
}

#[test]
fn scalars_match_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/scalar_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_scalar_fixtures.py"));
    let fixtures: Vec<Fixture> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!fixtures.is_empty(), "no fixtures");

    let mut n = 0usize;
    for fx in &fixtures {
        let s = fx.state.to_state();
        for c in &fx.cases {
            let (ci, seat) = (c.ci, c.seat);
            let tag = format!("ci={ci} seat={seat}");
            assert_eq!(V::effective_cost(&s, ci, seat), c.eff, "effective_cost {tag}");
            assert_eq!(V::total_effective_cost(&s, ci, seat), c.tec, "total_effective_cost {tag}");
            assert_eq!(V::cost_concentration(&s, ci, seat), c.conc, "cost_concentration {tag}");
            assert_eq!(V::gold_needed(&s, ci, seat), c.gn, "gold_needed {tag}");
            assert_eq!(V::color_deficits(&s, ci, seat), c.cdef, "color_deficits {tag}");
            assert_eq!(V::gems_to_collect(&s, ci, seat), c.gtc, "gems_to_collect {tag}");
            assert_eq!(V::turns_to_afford(&s, ci, seat), c.tta, "turns_to_afford {tag}");
            assert_eq!(V::tempo(&s, ci, seat), c.tempo, "tempo {tag}");
            assert_eq!(V::gem_cost(&s, ci, seat), c.gemc, "gem_cost {tag}");
            assert_eq!(V::gold_cost(&s, ci, seat), c.goldc, "gold_cost {tag}");
            assert_eq!(V::gold_shortfall(&s, ci, seat), c.gshort, "gold_shortfall {tag}");
            assert_eq!(V::noble_completion_pts(&s, ci, seat), c.ncomp, "noble_completion_pts {tag}");
            let np = V::noble_progress(&s, ci, seat);
            assert!(close(np, c.nprog), "noble_progress {tag}: {np} vs {}", c.nprog);
            let ef = V::efficiency(&s, ci, seat);
            assert!(close(ef, c.effi), "efficiency {tag}: {ef} vs {}", c.effi);
            let vc = V::victory_closeness(&s, ci, seat, 0);
            assert!(close(vc, c.vclose), "victory_closeness {tag}: {vc} vs {}", c.vclose);
            n += 1;
        }
    }
    eprintln!("scalar parity OK: {} states, {} cases", fixtures.len(), n);
}
