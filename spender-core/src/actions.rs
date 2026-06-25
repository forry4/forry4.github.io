//! Action-index → incumbent main.py dict-move bridge (port of `actions.action_to_move`).
//! Emits a COMPACT JSON string byte-identical to Python `json.dumps(move, separators=(",",":"))`,
//! so the browser can forward the WASM-chosen AI move straight through the normal `sendMove` path
//! and the server applies it via `_run_ai_turn`. Cards are referenced by NAME (e.g. "L1-0"), matching
//! main.py's card `id`. Resolve board slots / reserved indices against the CURRENT state (pre-apply).

use crate::cards::{CARD_NAME, NOBLE_NAME};
use crate::engine::{State, A_BUY_BOARD, A_BUY_RESV, A_DISCARD, A_NOBLE, A_PASS, A_RES_BOARD,
                    A_RES_DECK, A_TAKE1, A_TAKE2D, A_TAKE2S, A_TAKE3, TAKE2D, TAKE3};

pub const COLOR_NAMES: [&str; 6] = ["white", "blue", "green", "red", "black", "gold"];

/// Compact-JSON dict-move for action `a` in state `s` (matches Python action_to_move + json.dumps).
pub fn action_to_move_json(s: &State, a: usize) -> String {
    if a < A_PASS {
        let colors: Vec<usize> = if a < A_TAKE2D {
            TAKE3[a - A_TAKE3].to_vec()
        } else if a < A_TAKE1 {
            TAKE2D[a - A_TAKE2D].to_vec()
        } else if a < A_TAKE2S {
            vec![a - A_TAKE1]
        } else {
            let c = a - A_TAKE2S;
            vec![c, c]
        };
        let parts: Vec<String> = colors.iter().map(|&c| format!("\"{}\"", COLOR_NAMES[c])).collect();
        return format!("{{\"type\":\"take_gems\",\"colors\":[{}]}}", parts.join(","));
    }
    if a == A_PASS {
        return "{\"type\":\"take_gems\",\"colors\":[]}".to_string();
    }
    if a < A_RES_DECK {
        let ci = s.board[a - A_RES_BOARD];
        return format!("{{\"type\":\"reserve\",\"card_id\":\"{}\"}}", CARD_NAME[ci as usize]);
    }
    if a < A_BUY_BOARD {
        return format!("{{\"type\":\"reserve\",\"deck_level\":{}}}", a - A_RES_DECK + 1);
    }
    if a < A_BUY_RESV {
        let ci = s.board[a - A_BUY_BOARD];
        return format!("{{\"type\":\"buy\",\"card_id\":\"{}\"}}", CARD_NAME[ci as usize]);
    }
    if a < A_DISCARD {
        let ci = s.reserved[s.turn][a - A_BUY_RESV];
        return format!("{{\"type\":\"buy\",\"card_id\":\"{}\"}}", CARD_NAME[ci as usize]);
    }
    if a < A_NOBLE {
        return format!("{{\"type\":\"discard\",\"color\":\"{}\"}}", COLOR_NAMES[a - A_DISCARD]);
    }
    let ni = s.nobles[s.pending_nobles[a - A_NOBLE]];
    format!("{{\"type\":\"pick_noble\",\"noble_id\":\"{}\"}}", NOBLE_NAME[ni as usize])
}
