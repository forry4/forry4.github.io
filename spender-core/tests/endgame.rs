//! Endgame solver (#1) correctness: it must override the PUCT pick toward a SOUND forced result
//! (forced win available / passive move is a forced loss) and be a no-op outside endgame positions.

use spender_core::cards::{COST, N_CARDS, PTS};
use spender_core::engine::{self, State};
use spender_core::rng::Rng;
use spender_core::{endgame, vsearch};

/// A hand-built endgame State: empty bank-neutral board/decks, no nobles, seat 0 to move.
fn base() -> State {
    State {
        bank: [4, 4, 4, 4, 4, 5],
        tokens: [[0; 6], [0; 6]],
        bonuses: [[0; 5], [0; 5]],
        points: [0, 0],
        purchased_n: [0, 0],
        purchased: [Vec::new(), Vec::new()],
        reserved: [Vec::new(), Vec::new()],
        reserved_blind: [Vec::new(), Vec::new()],
        nobles_won: [Vec::new(), Vec::new()],
        board: [-1; 12],
        decks: [Vec::new(), Vec::new(), Vec::new()],
        nobles: [-1, -1, -1],
        turn: 0,
        phase: engine::PLAY,
        pending_nobles: Vec::new(),
        final_trigger: -1,
        winner: engine::WIN_NONE,
        ply: 0,
        win_points: 15,
    }
}

#[test]
fn finds_forced_win_and_overrides_passive_pick() {
    // A point card seat 0 can buy for free to hit exactly win_points; opponent has 0 points and no way
    // to score → the buy is a forced win.
    let win_card = (0..N_CARDS).find(|&c| PTS[c] >= 2).unwrap() as i32;
    let p = PTS[win_card as usize];

    let mut s = base();
    s.points[0] = s.win_points - p;
    s.bonuses[0] = COST[win_card as usize]; // bonuses cover the whole cost → gold_needed == 0
    s.board[0] = win_card;

    let mut rng = Rng::new(1);
    // Hand the solver a passive PUCT pick; it must override to the winning buy.
    let chosen = endgame::refine(&s, 0, engine::A_PASS, &mut rng);
    assert_eq!(
        chosen,
        engine::A_BUY_BOARD,
        "solver should override A_PASS with the forced-win buy of board slot 0"
    );

    // And if PUCT already picked the win, it must be kept (not perturbed).
    let mut rng2 = Rng::new(2);
    assert_eq!(
        endgame::refine(&s, 0, engine::A_BUY_BOARD, &mut rng2),
        engine::A_BUY_BOARD
    );
}

#[test]
fn avoids_forced_loss_by_denial() {
    // Opponent is one free buy from winning (a 1-point card on the board). Seat 0 cannot win this turn,
    // so any passive move loses; reserving the threat card removes it from the board → not a loss.
    let threat = (0..N_CARDS).find(|&c| PTS[c] == 1).unwrap() as i32;

    let mut s = base();
    s.points = [10, 14];
    s.bonuses[1] = COST[threat as usize]; // opponent affords it for free
    s.board[0] = threat;

    // A gem take is a legal pick PUCT could plausibly make — and it's a forced loss (opponent still
    // buys the threat). The solver must switch to the one non-losing move: reserving the threat away.
    let losing_pick = engine::A_TAKE3; // take white+blue+green (bank has all)
    assert!(engine::legal_actions(&s).contains(&losing_pick));
    let mut rng = Rng::new(3);
    let chosen = endgame::refine(&s, 0, losing_pick, &mut rng);
    assert_ne!(chosen, losing_pick, "taking gems here is a forced loss");
    assert_eq!(
        chosen,
        engine::A_RES_BOARD,
        "the only non-losing move is reserving (denying) the threat card"
    );
}

#[test]
fn no_override_outside_endgame() {
    // An early midgame position (low points) must short-circuit: refine returns the PUCT pick verbatim,
    // and is_endgame is false (so the solver never even runs — zero cost there).
    let s = vsearch::demo_position(7, 8);
    assert!(
        !endgame::is_endgame(&s),
        "8-ply demo should be well short of the endgame gate"
    );
    let puct = engine::legal_actions(&s)[0];
    let mut rng = Rng::new(4);
    assert_eq!(endgame::refine(&s, s.turn, puct, &mut rng), puct);
}
