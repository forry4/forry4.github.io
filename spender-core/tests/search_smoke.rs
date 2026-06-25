//! Search smoke test: Rust-S self-play must produce only legal moves and terminate (mechanical
//! end-to-end check of mcts + vsearch). Strength parity vs Python-S is a separate cross-impl gate.

use spender_core::{engine, rng::Rng, vsearch};

#[test]
fn rust_s_selfplay_completes() {
    for g in 0..8u64 {
        let mut s = engine::new_game(1000 + g, if g % 2 == 0 { 15 } else { 21 });
        let mut rng = Rng::new(42 + g);
        let mut plies = 0;
        while s.phase != engine::OVER && plies < 400 {
            let seat = s.turn;
            let legal = engine::legal_actions(&s);
            let a = vsearch::choose_action(&s, seat, 48, &mut rng);
            assert!(legal.contains(&a), "illegal action {a} (game {g}, ply {plies}, phase {})", s.phase);
            engine::apply(&mut s, a);
            plies += 1;
        }
        assert_eq!(s.phase, engine::OVER, "game {g} did not finish within 400 plies");
    }
    eprintln!("Rust-S self-play smoke OK: 8 games completed, all moves legal");
}
