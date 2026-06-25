//! Card-valuation core — port of `games/spender/ai/az/valuation3.py` (the variant-S leaf basis).
//!
//! Ported at the DEPLOYED config: the many default-OFF experiment flags (DECK_STAGE_TILT,
//! ENG_RECURSE_W, ENG_FIXEDPOINT, NOBLE_RACE_W, TURNS_MODE != "table", USE_TTA_GREEDY=False, ...)
//! are omitted — only the live path is reproduced. USE_POTENTIAL_ENGINE and DECK_BONUS_DISCOUNT
//! are ON (their deployed values). Parity with Python is gated to a float tolerance (~1e-9), not
//! bit-equality (float summation order differs); see `tests/scalar_parity.rs` (Layer A).
//!
//! Built in validated layers: A = stateless per-card scalars (this section); B = the `Valuation`
//! context + engine_value chain; (heuristic3 take_value + v_state STAND terms come next).

use crate::cards::{BONUS, COST, NOBLE_PTS, NOBLE_REQ, PTS};
use crate::engine::{self, State};
use crate::turns;

// ─── Tuned constants (deployed) ───────────────────────────────────────────────
pub const GOLD_BANK_CAP: i32 = 2;
pub const NOBLE_CLOSE_FLOOR: f64 = 0.3;

// ─── Layer A: stateless per-card/seat scalars ─────────────────────────────────

/// Per-color gem cost after `seat`'s permanent discounts (>= 0).
pub fn effective_cost(s: &State, ci: i32, seat: usize) -> [i32; 5] {
    let cost = &COST[ci as usize];
    let bon = &s.bonuses[seat];
    let mut out = [0i32; 5];
    for c in 0..5 {
        let d = cost[c] - bon[c];
        out[c] = if d > 0 { d } else { 0 };
    }
    out
}

/// Sum of post-discount gem cost (ignores held tokens).
pub fn total_effective_cost(s: &State, ci: i32, seat: usize) -> i32 {
    let cost = &COST[ci as usize];
    let bon = &s.bonuses[seat];
    let mut tot = 0;
    for c in 0..5 {
        let diff = cost[c] - bon[c];
        if diff > 0 {
            tot += diff;
        }
    }
    tot
}

/// Duplicate same-color gems the post-bonus cost forces you to collect.
pub fn cost_concentration(s: &State, ci: i32, seat: usize) -> i32 {
    let eff = effective_cost(s, ci, seat);
    let sum: i32 = eff.iter().sum();
    let distinct = eff.iter().filter(|&&x| x > 0).count() as i32;
    sum - distinct
}

/// Gold tokens required to buy ci now (matches the engine legality helper).
pub fn gold_needed(s: &State, ci: i32, seat: usize) -> i32 {
    engine::gold_needed(&COST[ci as usize], &s.tokens[seat], &s.bonuses[seat])
}

/// True if `seat` can buy ci this turn (enough tokens + gold).
pub fn affordable_now(s: &State, ci: i32, seat: usize) -> bool {
    gold_needed(s, ci, seat) <= s.tokens[seat][5]
}

/// Per-color gems still needed after discounts + owned colored tokens (gold NOT applied).
pub fn color_deficits(s: &State, ci: i32, seat: usize) -> [i32; 5] {
    let cost = &COST[ci as usize];
    let bon = &s.bonuses[seat];
    let tok = &s.tokens[seat];
    let mut out = [0i32; 5];
    for i in 0..5 {
        let need = cost[i] - bon[i] - tok[i];
        out[i] = if need > 0 { need } else { 0 };
    }
    out
}

/// Gems `seat` must still gather after spending matching colored tokens + gold (wild). 0 if affordable.
pub fn gems_to_collect(s: &State, ci: i32, seat: usize) -> i32 {
    let deficit: i32 = color_deficits(s, ci, seat).iter().sum::<i32>() - s.tokens[seat][5];
    if deficit > 0 {
        deficit
    } else {
        0
    }
}

/// Turns to collect remaining need `d` at 1 gem/color/turn: steepest single need, +1 iff exactly
/// four distinct colors each need 1 (take-3 then take-1).
pub fn steps(d: &[i32; 5]) -> i32 {
    let mut st = d[0];
    for i in 1..5 {
        if d[i] > st {
            st = d[i];
        }
    }
    if st == 1 {
        let npos = d.iter().filter(|&&x| x > 0).count();
        if npos == 4 {
            return 2;
        }
    }
    st
}

/// Turns to collect ci at 1 gem/color/turn (steepest remaining need, +1 on the 1-1-1-1 case).
pub fn tempo(s: &State, ci: i32, seat: usize) -> i32 {
    steps(&color_deficits(s, ci, seat))
}

/// Post-bonus sticker price (held tokens NOT subtracted).
pub fn gem_cost(s: &State, ci: i32, seat: usize) -> i32 {
    total_effective_cost(s, ci, seat)
}

/// Estimated gold: bottleneck (steepest remaining) color's need minus up-to-GOLD_BANK_CAP pulled
/// from the bank; floored at 0. First-argmax tie-break matches Python `max(range(5), key=...)`.
pub fn gold_cost(s: &State, ci: i32, seat: usize) -> i32 {
    let d = color_deficits(s, ci, seat);
    let mut steepest = 0;
    let mut color = 0usize;
    for c in 0..5 {
        if d[c] > steepest {
            steepest = d[c];
            color = c;
        }
    }
    if steepest <= 0 {
        return 0;
    }
    let capped = GOLD_BANK_CAP.min(s.bank[color]);
    (steepest - capped).max(0)
}

/// Gems for ci that cannot come from the bank (per color, need beyond bank holdings), summed.
pub fn gold_shortfall(s: &State, ci: i32, seat: usize) -> i32 {
    let d = color_deficits(s, ci, seat);
    let mut tot = 0;
    for c in 0..5 {
        let x = d[c] - s.bank[c];
        if x > 0 {
            tot += x;
        }
    }
    tot
}

/// Estimated turns for `seat` to afford ci (deployed: USE_TTA_GREEDY greedy take simulation).
/// 0 if affordable now. Spend gold on largest deficits first, then each turn take the 3 most-needed
/// distinct colors (pairing the leader when <= 2 colors remain).
pub fn turns_to_afford(s: &State, ci: i32, seat: usize) -> i32 {
    let mut d = color_deficits(s, ci, seat);
    let mut gold = s.tokens[seat][5];
    // Spend gold on the largest deficits first (first-argmax tie-break, matching Python).
    while gold > 0 && d.iter().any(|&x| x > 0) {
        let mut bi = 0usize;
        let mut bv = d[0];
        for c in 1..5 {
            if d[c] > bv {
                bv = d[c];
                bi = c;
            }
        }
        d[bi] -= 1;
        gold -= 1;
    }
    let mut turns = 0;
    while d.iter().any(|&x| x > 0) {
        // colors needing >0, sorted by descending need (stable -> ties keep ascending color order).
        let mut pos: Vec<usize> = (0..5).filter(|&c| d[c] > 0).collect();
        pos.sort_by(|&a, &b| d[b].cmp(&d[a]));
        if pos.len() >= 3 {
            for &c in &pos[..3] {
                d[c] -= 1;
            }
        } else if pos.len() == 2 {
            let (c0, c1) = (pos[0], pos[1]);
            if d[c0] >= 2 {
                d[c0] -= 2;
            } else {
                d[c0] -= 1;
                d[c1] -= 1;
            }
        } else {
            let c0 = pos[0];
            d[c0] -= if d[c0] >= 2 { 2 } else { 1 };
        }
        turns += 1;
    }
    turns
}

/// 1.0 if a +1 `bcol` bonus lowers card `costj`'s steepest-remaining color (saves a turn), else 0.0.
pub fn reduces_tempo(costj: &[i32; 5], bon: &[i32; 5], bcol: usize) -> f64 {
    let mut rem = [0i32; 5];
    for c in 0..5 {
        let v = costj[c] - bon[c];
        rem[c] = if v > 0 { v } else { 0 };
    }
    let before = steps(&rem);
    rem[bcol] -= 1;
    if steps(&rem) < before {
        1.0
    } else {
        0.0
    }
}

/// How much ci's +1 bonus advances visible nobles for `seat`, in [0, 1].
pub fn noble_progress(s: &State, ci: i32, seat: usize) -> f64 {
    let bcol = BONUS[ci as usize];
    let bon = &s.bonuses[seat];
    let mut score = 0.0;
    let mut n = 0;
    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni < 0 {
            continue;
        }
        let req = &NOBLE_REQ[ni as usize];
        let completes = (0..5).all(|c| bon[c] + if c == bcol { 1 } else { 0 } >= req[c]);
        if completes {
            continue; // scored by noble_completion_pts, not here
        }
        n += 1;
        if req[bcol] > bon[bcol] {
            let total: i32 = req.iter().sum();
            if total > 0 {
                let mut deficit = 0;
                for i in 0..5 {
                    if req[i] > bon[i] {
                        deficit += req[i] - bon[i];
                    }
                }
                let close = 1.0 - (deficit as f64) / (total as f64);
                score += NOBLE_CLOSE_FLOOR + (1.0 - NOBLE_CLOSE_FLOOR) * close;
            }
        }
    }
    if n > 0 {
        score / (n as f64)
    } else {
        0.0
    }
}

/// Immediate noble VP `seat` scores by buying ci (best single newly-claimable noble, else 0).
pub fn noble_completion_pts(s: &State, ci: i32, seat: usize) -> i32 {
    let bcol = BONUS[ci as usize];
    let bon = &s.bonuses[seat];
    let mut best = 0;
    for slot in 0..3 {
        let ni = s.nobles[slot];
        if ni < 0 {
            continue;
        }
        let req = &NOBLE_REQ[ni as usize];
        if (0..5).all(|c| bon[c] + if c == bcol { 1 } else { 0 } >= req[c]) {
            let p = NOBLE_PTS[ni as usize];
            if p > best {
                best = p;
            }
        }
    }
    best
}

/// Points per effective gem (+1 denominator keeps free points finite/top-ranked).
pub fn efficiency(s: &State, ci: i32, seat: usize) -> f64 {
    (PTS[ci as usize] as f64) / (total_effective_cost(s, ci, seat) as f64 + 1.0)
}

/// How near to the win buying ci (plus any noble it triggers) brings `seat`, capped at 1.0.
pub fn victory_closeness(s: &State, ci: i32, seat: usize, noble_pts: i32) -> f64 {
    let pts = s.points[seat] + PTS[ci as usize] + noble_pts;
    let v = (pts as f64) / (s.win_points as f64);
    if v < 1.0 {
        v
    } else {
        1.0
    }
}

// ─── Layer B: Valuation context + engine_value chain (deployed config) ─────────
// Deployed flags collapsed in: USE_POTENTIAL_ENGINE=on, DECK_BONUS_DISCOUNT=on, NOBLE_TIME_GATE=on,
// ENG_FIXEDPOINT/ENG_RECURSE_W/POT_REACH_W/BUILD_FLOOR_W/NOBLE_RACE_W=0, ENG_WEIGHT_MODE=1, TURNS_MODE="table".

pub const ENG_DIV: f64 = 8.0;
pub const ENG_FLOOR: f64 = 0.2;
pub const ENG_DECK_W: f64 = 3.5;
pub const ENG_TEMPO_SCALE: f64 = 0.3;
pub const RESERVED_ENGINE_W: f64 = 1.05;
pub const POT_ENGINE_W: f64 = 0.5;
pub const NOBLE_TURN_W: f64 = 1.0;

/// Per-card engine weight (ENG_WEIGHT_MODE=1): tempo-scaled turn-save.
#[inline]
pub fn w_card(costj: &[i32; 5], bon: &[i32; 5], bcol: usize) -> f64 {
    ENG_TEMPO_SCALE * (1.0 + reduces_tempo(costj, bon, bcol))
}

/// Per-state valuation context. Build one per leaf state; reuse across cards/seats.
pub struct Valuation<'a> {
    pub s: &'a State,
    pub deck_color_demand: [f64; 5], // seat-blind (feeds the inner eng_base)
    pub w_tempo: f64,
    pub w_gem: f64,
    pub w_gold: f64,
    turns: f64, // estimated_turns_remaining, precomputed (state-level)
}

impl<'a> Valuation<'a> {
    pub fn new(s: &'a State, w_tempo: f64, w_gem: f64, w_gold: f64) -> Self {
        // seat-blind deck color demand (integer accumulation — exact, order-independent)
        let mut demand = [0i64; 5];
        let mut total = 0i64;
        for lvl in 0..3 {
            for &ci in &s.decks[lvl] {
                let cost = &COST[ci as usize];
                for i in 0..5 {
                    demand[i] += cost[i] as i64;
                    total += cost[i] as i64;
                }
            }
        }
        let dcd = if total > 0 {
            let mut d = [0.0; 5];
            for i in 0..5 {
                d[i] = demand[i] as f64 / total as f64;
            }
            d
        } else {
            [0.0; 5]
        };
        let turns = turns::estimate(
            s.win_points,
            s.purchased_n[0], s.points[0], s.tokens[0].iter().sum(),
            s.purchased_n[1], s.points[1], s.tokens[1].iter().sum(),
        );
        Valuation { s, deck_color_demand: dcd, w_tempo, w_gem, w_gold, turns }
    }

    #[inline]
    pub fn estimated_turns_remaining(&self) -> f64 {
        self.turns
    }

    /// Seat-aware bonus-discounted deck demand (DECK_BONUS_DISCOUNT): per color, undealt-deck cost not
    /// covered by `seat`'s bonuses, normalized by the RAW deck total (magnitude legitimately shrinks).
    pub fn deck_demand_seat(&self, seat: usize) -> [f64; 5] {
        let bon = &self.s.bonuses[seat];
        let mut demand = [0.0f64; 5];
        let mut raw_total = 0.0f64;
        for lvl in 0..3 {
            for &ci in &self.s.decks[lvl] {
                let cost = &COST[ci as usize];
                for c in 0..5 {
                    let cc = cost[c];
                    if cc > 0 {
                        raw_total += cc as f64;
                        let rem = cc - bon[c];
                        if rem > 0 {
                            demand[c] += rem as f64;
                        }
                    }
                }
            }
        }
        if raw_total > 0.0 {
            let mut out = [0.0; 5];
            for c in 0..5 {
                out[c] = demand[c] / raw_total;
            }
            out
        } else {
            [0.0; 5]
        }
    }

    /// take_value's total_cost = W_TEMPO*tempo + W_GEM*gem + W_GOLD*gold for ci, optionally with one
    /// extra bonus in `extra_bcol`. First-argmax tie-break on `color`.
    pub fn cost_scalar(&self, ci: i32, seat: usize, extra_bcol: Option<usize>) -> f64 {
        let bon = &self.s.bonuses[seat];
        let tok = &self.s.tokens[seat];
        let bank = &self.s.bank;
        let eb: i32 = extra_bcol.map_or(-1, |c| c as i32);
        let cost = &COST[ci as usize];
        let (mut gem, mut steepest, mut color, mut nonzero, mut ones) = (0i32, 0i32, 0usize, 0i32, 0i32);
        for c in 0..5 {
            let bc = bon[c] + if c as i32 == eb { 1 } else { 0 };
            let sticker = cost[c] - bc;
            if sticker > 0 {
                gem += sticker;
            }
            let need = sticker - tok[c];
            if need > 0 {
                nonzero += 1;
                if need == 1 {
                    ones += 1;
                }
                if need > steepest {
                    steepest = need;
                    color = c;
                }
            }
        }
        let (tempo_v, gold) = if steepest <= 0 {
            (0, 0)
        } else {
            let tempo_v = steepest + if nonzero == 4 && ones == 4 { 1 } else { 0 };
            let capped = GOLD_BANK_CAP.min(bank[color]);
            ((tempo_v), (steepest - capped).max(0))
        };
        self.w_tempo * (tempo_v as f64) + self.w_gem * (gem as f64) + self.w_gold * (gold as f64)
    }

    /// cj's LEVEL-0 (legacy, non-recursive) engine value; uses the SEAT-BLIND deck_color_demand.
    pub fn eng_base(&self, cj: i32, seat: usize) -> f64 {
        let s = self.s;
        let bcol = BONUS[cj as usize];
        let bon = &s.bonuses[seat];
        let bon_b = bon[bcol];
        let mut ev = 0.0;
        for slot in 0..12 {
            let ck = s.board[slot];
            if ck < 0 || ck == cj {
                continue;
            }
            if COST[ck as usize][bcol] - bon_b > 0 {
                let imp = (PTS[ck as usize] as f64) / ENG_DIV + ENG_FLOOR;
                ev += imp * w_card(&COST[ck as usize], bon, bcol);
            }
        }
        for &ck in &s.reserved[seat] {
            if ck == cj {
                continue;
            }
            if COST[ck as usize][bcol] - bon_b > 0 {
                let imp = (PTS[ck as usize] as f64) / ENG_DIV + ENG_FLOOR;
                ev += RESERVED_ENGINE_W * imp * w_card(&COST[ck as usize], bon, bcol);
            }
        }
        ev += self.deck_color_demand[bcol] * ENG_DECK_W;
        ev
    }

    /// ci's potential as a destination (POT_REACH_W=0 -> just the base): PTS + POT_ENGINE_W * eng_base.
    pub fn potential_value(&self, ci: i32, seat: usize) -> f64 {
        (PTS[ci as usize] as f64) + POT_ENGINE_W * self.eng_base(ci, seat)
    }

    /// take-value uplift a +1 `bcol` bonus gives ci (BUILD_FLOOR_W=0 -> pure convexity gap).
    pub fn delta_take(&self, ci: i32, seat: usize, bcol: usize) -> f64 {
        let c0 = self.cost_scalar(ci, seat, None);
        let c1 = self.cost_scalar(ci, seat, Some(bcol));
        let gap = 1.0 / (1.0 + c1) - 1.0 / (1.0 + c0);
        self.potential_value(ci, seat) * gap
    }

    /// Value of the permanent +1 bonus ci grants (H3 Delta-take model). Top-level deck term is
    /// SEAT-AWARE; the inner eng_base (inside potential) stays seat-blind.
    pub fn engine_value(&self, ci: i32, seat: usize) -> f64 {
        let s = self.s;
        let bcol = BONUS[ci as usize];
        let bon_b = s.bonuses[seat][bcol];
        let mut ev = 0.0;
        for slot in 0..12 {
            let cj = s.board[slot];
            if cj < 0 || cj == ci {
                continue;
            }
            if COST[cj as usize][bcol] - bon_b > 0 {
                ev += self.delta_take(cj, seat, bcol);
            }
        }
        for &cj in &s.reserved[seat] {
            if cj == ci {
                continue;
            }
            if COST[cj as usize][bcol] - bon_b > 0 {
                ev += RESERVED_ENGINE_W * self.delta_take(cj, seat, bcol);
            }
        }
        ev += self.deck_demand_seat(seat)[bcol] * ENG_DECK_W;
        ev
    }

    /// Time-gated noble progress (the deployed method version): relevance×closeness per non-completing
    /// noble, each faded by feasibility in the turns left after acquiring ci. n divides by ALL
    /// non-completing visible nobles (so a card advancing 1 of 3 is diluted).
    pub fn noble_progress(&self, ci: i32, seat: usize) -> f64 {
        let s = self.s;
        let bcol = BONUS[ci as usize];
        let bon = &s.bonuses[seat];
        let mut n = 0;
        let mut pairs: Vec<(f64, i32)> = Vec::new();
        for slot in 0..3 {
            let ni = s.nobles[slot];
            if ni < 0 {
                continue;
            }
            let req = &NOBLE_REQ[ni as usize];
            let completes = (0..5).all(|c| bon[c] + if c == bcol { 1 } else { 0 } >= req[c]);
            if completes {
                continue;
            }
            n += 1;
            if req[bcol] > bon[bcol] {
                let total: i32 = req.iter().sum();
                if total == 0 {
                    continue;
                }
                let mut deficit = 0;
                for c in 0..5 {
                    if req[c] > bon[c] {
                        deficit += req[c] - bon[c];
                    }
                }
                let close = 1.0 - (deficit as f64) / (total as f64);
                let base = NOBLE_CLOSE_FLOOR + (1.0 - NOBLE_CLOSE_FLOOR) * close;
                pairs.push((base, deficit));
            }
        }
        if n == 0 {
            return 0.0;
        }
        let mut eff = self.turns - tempo(s, ci, seat) as f64;
        if eff < 0.0 {
            eff = 0.0;
        }
        let mut score = 0.0;
        for (base, deficit) in pairs {
            score += base * (eff / (eff + NOBLE_TURN_W * (deficit as f64)));
        }
        score / (n as f64)
    }
}
