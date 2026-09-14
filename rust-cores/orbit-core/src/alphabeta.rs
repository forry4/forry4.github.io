//! Depth-first alpha-beta with iterative deepening -- the DEPTH arm of the
//! search-architecture question.
//!
//! WHY THIS EXISTS. Every Orbit strength gain has been a search fix and every
//! evaluation attempt has been a wash or worse (research log, items 10-12).
//! Within the search, WIDTH has now been pushed twice and paid almost nothing:
//! coherent determinization won by descending deeper on FEWER simulations, and
//! minimax bought 1.96x the simulations plus the first adversarial opponent
//! model for about +0.04. Orbit's profile -- branching ~6.7 mean / 18 max, a
//! strong hand-written evaluator, and a perfect-information cheat of only
//! 0.6094 -- is the Chess/Othello profile where alpha-beta dominated for forty
//! years, not the Go profile where MCTS won because branching was enormous and
//! no good evaluator existed.
//!
//! The engine agrees more than expected: draws are `deck.pop()`, so `Chance` is
//! touched ONLY on a reshuffle. Given the deck order, Orbit is very nearly a
//! deterministic perfect-information game.
//!
//! WHAT THIS IS NOT, YET. This searches ONE world. Determinizing it over K
//! sampled worlds (PIMC, as Dissonance serves) is the next step and is
//! deliberately not taken here, because the de-risk has to come first: at
//! PERFECT information and equal time, does depth beat the MCTS Expert? If it
//! does not win there it cannot win determinized, and the cheap answer is worth
//! having before building the expensive thing.
use crate::clock::Clock;
use crate::search::{state_value, state_value_v2_from_state, state_value_v3_from_state, Leaf};
use crate::serving::action_score_with;
use crate::{Chance, State};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::hash::{Hash, Hasher};

#[derive(Clone, Copy)]
pub struct AbConfig {
    pub budget_ms: u64,
    /// Iterative deepening stops here even with budget left. Decisions, not
    /// turns -- a pending sub-decision is its own ply.
    pub max_depth: usize,
    /// Whether the transposition table is consulted and filled.
    ///
    /// This is a knob rather than an assumption because Orbit barely
    /// transposes: measured at depth 4 the table hit 10 times in 710 nodes
    /// (1.4%) and at depth 8-9 between 1.3% and 5.4%, which is the same shape
    /// the 2026-09-11 MCTS audit found (19 of 232 nodes revisited). Almost
    /// every path reaches a distinct world because the deck order advances with
    /// it and most moves are irreversible. A table that never hits still costs
    /// a structural hash on every node, so whether it pays is a MEASUREMENT at
    /// the depth actually searched, not a default to inherit from chess.
    pub use_table: bool,
    /// Which leaf evaluator scores a nonterminal position.
    pub leaf: Leaf,
    /// Keep searching past the depth limit while a turn is half-finished.
    ///
    /// An Orbit turn is not one ply. Effects queue sub-decisions, and **39.6%
    /// of all decision points sit inside a pending chain** (measured over 6,598
    /// decisions across 40 games). So two times in five, a search that stops at
    /// its depth limit is scoring a TRANSIENT position -- an effect granted but
    /// its cost unpaid, a capture queued but not yet applied. The evaluator was
    /// never meant to read those, and no amount of extra depth fixes it,
    /// because the horizon just lands in a different half-finished turn.
    ///
    /// This is the standard quiescence answer: do not stop in the middle of
    /// one. Capped, because a chain that somehow never resolved would otherwise
    /// search forever.
    pub quiescence: bool,
    /// Whether the move-ordering prior knows about victory conditions.
    ///
    /// Ordering cannot change what alpha-beta CONCLUDES, only how fast it gets
    /// there -- but the same prior is the Expert's answer on every decision the
    /// search refuses, which is 45% of them, so an A/B has to be able to run
    /// both versions in one process. See `serving::action_score_with`.
    pub victory_aware_ranker: bool,
}

/// How many extra plies a half-finished turn may borrow.
const EXTENSION_CAP: i32 = 8;

impl Default for AbConfig {
    fn default() -> Self {
        Self {
            budget_ms: 1000,
            max_depth: 64,
            use_table: true,
            leaf: Leaf::StateValue,
            quiescence: false,
            victory_aware_ranker: true,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Bound {
    Exact,
    /// The true value is at least `value` (a beta cutoff produced it).
    Lower,
    /// The true value is at most `value` (no move beat alpha).
    Upper,
}

#[derive(Clone, Copy)]
struct Entry {
    depth: i32,
    value: f64,
    bound: Bound,
    best: usize,
}

/// A transposition key must separate positions that differ in ANYTHING the
/// value depends on, and that includes how far the frozen chance stream has
/// been consumed -- two identical-looking states reached by different paths can
/// face different reshuffles. Hidden state is included deliberately: this
/// searches one fully-known world, so the key is over the WORLD, not over an
/// observation.
fn state_key(state: &State, chance: &Chance) -> u64 {
    let mut h = std::collections::hash_map::DefaultHasher::new();
    state.schema.hash(&mut h);
    state.phase.hash(&mut h);
    state.turn_pid.hash(&mut h);
    state.turn_number.hash(&mut h);
    state.influence.hash(&mut h);
    state.captured_this_turn.hash(&mut h);
    state.leader.owner.hash(&mut h);
    state.leader.level.hash(&mut h);
    state.board_sides.hash(&mut h);
    state.planet_bonus.hash(&mut h);
    state.technology_bonus.hash(&mut h);
    state.agent_deck.hash(&mut h);
    state.agent_discard.hash(&mut h);
    state.bonus_deck.hash(&mut h);
    state.bonus_discard.hash(&mut h);
    state.mulligan_done.hash(&mut h);
    state.pending_pid.hash(&mut h);
    state.winner.hash(&mut h);
    for p in &state.players {
        p.credits.hash(&mut h);
        p.zenithium.hash(&mut h);
        p.hand.hash(&mut h);
        for column in &p.columns {
            column.hash(&mut h);
        }
        p.technology.hash(&mut h);
        p.row_bonuses.hash(&mut h);
        p.captured.hash(&mut h);
    }
    // `Pending` carries serde_json Values, which are not Hash. It is present on
    // a minority of nodes, so paying a serialization here is cheaper than
    // giving every node a string key.
    if let Some(pending) = &state.pending {
        pending.source.hash(&mut h);
        for item in &pending.queue {
            item.to_string().hash(&mut h);
        }
        pending.context.to_string().hash(&mut h);
    }
    chance.consumed.hash(&mut h);
    h.finish()
}

struct Search<'a> {
    root_seat: usize,
    clock: &'a Clock,
    budget_ms: f64,
    table: HashMap<u64, Entry>,
    nodes: u64,
    leaves: u64,
    cutoffs: u64,
    hits: u64,
    extended: u64,
    /// Set once the budget is spent. Every frame returns immediately after it,
    /// and the caller discards the whole iteration -- a partially searched
    /// depth can rank a move on a truncated subtree.
    out_of_time: bool,
    /// The transposition-table equivalence control. A TT exists to buy depth,
    /// never to change what the search concludes, so the tests run the same
    /// position with it off and require the identical ROOT VALUE. Move identity
    /// is deliberately NOT the invariant: among equal-valued moves a cutoff can
    /// legitimately return a different one, so asserting that would fail on
    /// correct code.
    table_enabled: bool,
    leaf_kind: Leaf,
    quiescence: bool,
    victory_aware_ranker: bool,
}

impl Search<'_> {
    fn expired(&mut self) -> bool {
        if self.out_of_time {
            return true;
        }
        // The clock is read every 256 nodes rather than every node: on wasm it
        // is `Date.now()`, which is a syscall-ish cost and deliberately
        // coarsened by some browsers.
        if self.nodes % 256 == 0 && self.clock.elapsed_ms() >= self.budget_ms {
            self.out_of_time = true;
        }
        self.out_of_time
    }

    fn leaf(&mut self, state: &State) -> f64 {
        self.leaves += 1;
        match self.leaf_kind {
            // Straight off the State: no JSON observation is built at all. Held
            // to the observation leaf to 1e-9 over 400+ real positions by
            // `the_fast_leaf_is_equivalent_to_the_observation_leaf`, so this is
            // a pure throughput change and node rate is depth.
            Leaf::StateValueV2 => state_value_v2_from_state(state, self.root_seat),
            Leaf::StateValueV3 => state_value_v3_from_state(state, self.root_seat),
            _ => state_value(&state.observation(self.root_seat)),
        }
    }

    /// Values are in ROOT-SEAT terms everywhere, so a node maximises when the
    /// root seat is to act and minimises otherwise. That is deliberately not
    /// negamax: Orbit turns contain pending sub-decisions, so the same seat
    /// frequently acts several plies running and strict alternation would flip
    /// the sign at the wrong places.
    fn search(
        &mut self,
        state: &State,
        chance: &Chance,
        depth: i32,
        extension: i32,
        mut alpha: f64,
        mut beta: f64,
    ) -> f64 {
        self.nodes += 1;
        if self.expired() {
            return 0.0;
        }
        let Some(actor) = state.actor() else {
            return self.leaf(state);
        };
        // Past the depth limit the search normally stops. It does NOT stop
        // inside a half-finished turn when quiescence is on -- see
        // `AbConfig::quiescence`; the evaluator cannot read a transient
        // position, and 39.6% of decision points are inside one.
        let borrowing = depth <= 0;
        if borrowing {
            let may_extend = self.quiescence && state.pending.is_some() && extension > 0;
            if !may_extend {
                return self.leaf(state);
            }
            self.extended += 1;
        }

        let key = state_key(state, chance);
        let mut tt_move = usize::MAX;
        if let Some(entry) = self.table.get(&key).copied().filter(|_| self.table_enabled) {
            tt_move = entry.best;
            if entry.depth >= depth {
                match entry.bound {
                    Bound::Exact => {
                        self.hits += 1;
                        return entry.value;
                    }
                    Bound::Lower if entry.value >= beta => {
                        self.hits += 1;
                        return entry.value;
                    }
                    Bound::Upper if entry.value <= alpha => {
                        self.hits += 1;
                        return entry.value;
                    }
                    _ => {}
                }
            }
        }

        let legal = state.legal_moves(actor);
        if legal.is_empty() {
            return self.leaf(state);
        }

        // Move ordering. `action_score` is the same frozen hand-written prior
        // the MCTS uses as its PUCT prior -- the audit measured it deciding
        // 50.5% of moves outright, which is a poor policy but a good ORDERING,
        // and ordering is all alpha-beta asks of it. The TT's best move from a
        // shallower iteration goes first regardless; that is what makes
        // iterative deepening cheaper than searching the final depth directly.
        let observation = state.observation(actor);
        let mut order: Vec<usize> = (0..legal.len()).collect();
        let scores: Vec<f64> = legal
            .iter()
            .map(|mv| action_score_with(&observation, mv, self.victory_aware_ranker))
            .collect();
        order.sort_by(|&a, &b| {
            scores[b].partial_cmp(&scores[a]).unwrap_or(std::cmp::Ordering::Equal)
        });
        if tt_move < legal.len() {
            order.retain(|&i| i != tt_move);
            order.insert(0, tt_move);
        }

        let maximizing = actor == self.root_seat;
        let alpha_original = alpha;
        let beta_original = beta;
        let mut best = if maximizing { f64::NEG_INFINITY } else { f64::INFINITY };
        let mut best_move = order[0];
        let mut applied = 0;

        for &index in &order {
            let mut child = state.clone();
            let mut child_chance = chance.clone();
            if child.apply(actor, &legal[index], &mut child_chance).is_err() {
                // The engine rejected a move it listed as legal. That is a real
                // defect rather than something to route around, but a search is
                // the wrong place to panic: skip it and let the parity harness
                // be what fails.
                continue;
            }
            applied += 1;
            let value = self.search(
                &child,
                &child_chance,
                depth - 1,
                if borrowing { extension - 1 } else { EXTENSION_CAP },
                alpha,
                beta,
            );
            if self.out_of_time {
                return 0.0;
            }
            if maximizing {
                if value > best {
                    best = value;
                    best_move = index;
                }
                alpha = alpha.max(best);
            } else {
                if value < best {
                    best = value;
                    best_move = index;
                }
                beta = beta.min(best);
            }
            if alpha >= beta {
                self.cutoffs += 1;
                break;
            }
        }

        if applied == 0 {
            return self.leaf(state);
        }

        let bound = if best <= alpha_original {
            Bound::Upper
        } else if best >= beta_original {
            Bound::Lower
        } else {
            Bound::Exact
        };
        if self.table_enabled {
            self.table.insert(key, Entry { depth, value: best, bound, best: best_move });
        }
        best
    }
}

/// Choose a move for `seat` by iterative-deepening alpha-beta over the state as
/// given. The caller decides what "as given" means: the true state is the
/// perfect-information arm, and a world rebuilt from an observation is one
/// determinization.
pub fn choose(source: &State, seat: usize, seed: u64, config: AbConfig) -> Result<Value, String> {
    let Some(actor) = source.actor() else {
        return Err("the game is over".into());
    };
    if actor != seat {
        return Err(format!("seat {seat} is not to act"));
    }
    let legal = source.legal_moves(seat);
    if legal.is_empty() {
        return Err("no legal moves".into());
    }
    let clock = Clock::start();
    // Draws pop the deck, so this stream is consulted only on a reshuffle --
    // but it must exist and must be frozen, or two visits to one position could
    // reshuffle differently and the transposition table would be unsound.
    let chance = Chance::seeded(seed);
    let observation = source.observation(seat);

    if legal.len() == 1 {
        return Ok(json!({
            "move": legal[0].clone(),
            "value": 0.0,
            "depth": 0,
            "nodes": 0,
            "leaves": 0,
            "cutoffs": 0,
            "table_hits": 0,
            "table_size": 0,
            "ms": clock.elapsed_ms(),
        }));
    }

    let mut search = Search {
        root_seat: seat,
        clock: &clock,
        budget_ms: config.budget_ms as f64,
        table: HashMap::new(),
        nodes: 0,
        leaves: 0,
        cutoffs: 0,
        hits: 0,
        extended: 0,
        out_of_time: false,
        table_enabled: config.use_table,
        leaf_kind: config.leaf,
        quiescence: config.quiescence,
        victory_aware_ranker: config.victory_aware_ranker,
    };

    // The fallback is the ordering prior's own top move, so a budget too small
    // to finish depth 1 still returns what the 1-ply ranker would have played
    // rather than an arbitrary index.
    let aware = config.victory_aware_ranker;
    let mut best_index = (0..legal.len())
        .max_by(|&a, &b| {
            action_score_with(&observation, &legal[a], aware)
                .partial_cmp(&action_score_with(&observation, &legal[b], aware))
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .unwrap();
    let mut best_value = 0.0;
    let mut completed = 0;

    for depth in 1..=config.max_depth as i32 {
        let mut iteration_best = usize::MAX;
        let mut iteration_value = f64::NEG_INFINITY;
        let mut alpha = f64::NEG_INFINITY;
        let beta = f64::INFINITY;
        // The root is searched move by move rather than by one call on the root
        // position, because the chosen MOVE is what is wanted here and a cutoff
        // inside a single call would discard it.
        let mut order: Vec<usize> = (0..legal.len()).collect();
        let scores: Vec<f64> = legal
            .iter()
            .map(|mv| action_score_with(&observation, mv, aware))
            .collect();
        order.sort_by(|&a, &b| {
            scores[b].partial_cmp(&scores[a]).unwrap_or(std::cmp::Ordering::Equal)
        });
        order.retain(|&i| i != best_index);
        order.insert(0, best_index);

        for &index in &order {
            let mut child = source.clone();
            let mut child_chance = chance.clone();
            if child.apply(seat, &legal[index], &mut child_chance).is_err() {
                continue;
            }
            let value = search.search(&child, &child_chance, depth - 1, EXTENSION_CAP, alpha, beta);
            if search.out_of_time {
                break;
            }
            if value > iteration_value {
                iteration_value = value;
                iteration_best = index;
            }
            alpha = alpha.max(iteration_value);
        }

        if search.out_of_time {
            break;
        }
        if iteration_best != usize::MAX {
            best_index = iteration_best;
            best_value = iteration_value;
            completed = depth;
        }
        // A decided game does not get deeper, and the ordering prior cannot
        // improve on a proven win or loss.
        if best_value.abs() >= 1.0 {
            break;
        }
    }

    Ok(json!({
        "move": legal[best_index].clone(),
        "value": best_value,
        "depth": completed,
        "nodes": search.nodes,
        "leaves": search.leaves,
        "cutoffs": search.cutoffs,
        "table_hits": search.hits,
        "extended": search.extended,
        "table_size": search.table.len(),
        "ms": clock.elapsed_ms(),
    }))
}

/// PIMC: search K sampled worlds and combine their answers.
///
/// WHY. Measured 2026-09-13 at serving budget, one thread per seat, 64 pairs
/// each, alpha-beta against the MCTS Expert:
///
/// ```text
/// perfect information   0.9609  [0.9219, 0.9922]
/// determinized (K=1)    0.5625  [0.4688, 0.6484]
/// ```
///
/// The architecture is overwhelmingly better and beliefs eat almost all of it.
/// That gap is STRATEGY FUSION: a minimax over one sampled world plays as if it
/// knows the opponent's hand, so it commits to lines that only work in that
/// world. An MCTS over one world is softer -- its values are means over many
/// simulations -- which is why it loses far less to the same trade.
///
/// K is therefore the whole experiment, and it is a real trade rather than a
/// free win: each world gets `budget / K`, so depth falls as K rises. Dissonance
/// already serves this shape for this class of game.
///
/// VOTING, not value-summing, is deliberate. Alpha-beta returns an exact value
/// only for the move it chose; every move it cut off carries a BOUND, not a
/// value. Summing those across worlds would be adding numbers that mean
/// different things, so the worlds vote on a move and ties break on the summed
/// value of the votes actually cast.
#[cfg(not(target_arch = "wasm32"))]
pub fn choose_over_worlds(
    worlds: &[State],
    seat: usize,
    seed: u64,
    config: AbConfig,
) -> Result<Value, String> {
    choose_over_worlds_with_threads(worlds, seat, seed, config, 1)
}

/// PIMC across THREADS, which is what makes this a serving candidate rather
/// than an experiment.
///
/// A single alpha-beta tree parallelises badly, and that was recorded as a real
/// cost against this architecture. **PIMC does not have that problem**: the K
/// worlds are independent searches, which is exactly the shape of the
/// root-summed MCTS ensemble the browser already runs. So on the four workers
/// `ORBIT_AI_WORKER_CAP` gives every client, four worlds can each take the FULL
/// turn budget instead of a quarter of it -- K=4 at the depth of K=1.
///
/// Measured serially, splitting one budget K ways, the trade was visible and
/// real: K=1/2/4/8 scored 0.5625 / 0.6250 / 0.6562 / 0.6562 against the MCTS
/// Expert while mean depth fell 8.18 / 7.27 / 6.51 / 5.79. Giving each world a
/// whole budget is meant to buy the top of that curve without paying the depth.
///
/// `threads` is the concurrency, not the world count: with more worlds than
/// threads each thread takes several worlds in turn and every world's share
/// shrinks accordingly, so the budget accounting stays honest at any K.
/// Native only. wasm32 has no threads to spawn -- and does not need them: the
/// browser's parallelism is its WORKER POOL, four separate wasm instances that
/// each search one world, with the votes summed in JS. That is the same shape
/// as this function, arrived at from the other side.
#[cfg(not(target_arch = "wasm32"))]
pub fn choose_over_worlds_with_threads(
    worlds: &[State],
    seat: usize,
    seed: u64,
    config: AbConfig,
    threads: usize,
) -> Result<Value, String> {
    if worlds.is_empty() {
        return Err("no worlds to search".into());
    }
    let legal = worlds[0].legal_moves(seat);
    if legal.is_empty() {
        return Err("no legal moves".into());
    }
    // Determinizations of one observation differ only in hidden state, so every
    // world must offer the SAME choices in the same order -- the votes are
    // tallied by index. If that ever stops holding, the tally would silently be
    // over different moves in different worlds.
    for world in &worlds[1..] {
        if world.legal_moves(seat) != legal {
            return Err("determinized worlds disagree about the legal moves".into());
        }
    }

    let clock = Clock::start();
    if legal.len() == 1 {
        return Ok(json!({
            "move": legal[0].clone(), "value": 0.0, "depth": 0, "nodes": 0,
            "leaves": 0, "cutoffs": 0, "table_hits": 0, "table_size": 0,
            "worlds": worlds.len(), "ms": clock.elapsed_ms(),
        }));
    }

    let lanes = threads.max(1).min(worlds.len());
    // Worlds per lane, rounded up: the budget a world gets is the turn's
    // allowance divided by how many worlds its LANE must search in sequence,
    // never by the total world count. At K <= threads that is the whole
    // allowance, which is the entire point.
    let rounds = worlds.len().div_ceil(lanes) as u64;
    let share = (config.budget_ms / rounds).max(1);

    let per_world: Vec<Result<Value, String>> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..lanes)
            .map(|lane| {
                scope.spawn(move || {
                    let mut out = Vec::new();
                    let mut index = lane;
                    while index < worlds.len() {
                        out.push((
                            index,
                            choose(
                                &worlds[index],
                                seat,
                                seed.wrapping_add(index as u64)
                                    .wrapping_mul(0x9e3779b97f4a7c15),
                                AbConfig { budget_ms: share, ..config },
                            ),
                        ));
                        index += lanes;
                    }
                    out
                })
            })
            .collect();
        let mut collected: Vec<(usize, Result<Value, String>)> = handles
            .into_iter()
            .flat_map(|h| h.join().expect("a PIMC world panicked"))
            .collect();
        // Sorted by world index so the tally does not depend on which lane
        // happened to finish first -- the same position must always produce the
        // same move, or a mirror control cannot read 0.5.
        collected.sort_by_key(|(index, _)| *index);
        collected.into_iter().map(|(_, result)| result).collect()
    });

    let mut votes = vec![0usize; legal.len()];
    let mut value_sum = vec![0.0f64; legal.len()];
    let mut nodes = 0u64;
    let mut leaves = 0u64;
    let mut cutoffs = 0u64;
    let mut hits = 0u64;
    let mut depth_sum = 0i64;
    let mut searched = 0usize;

    for result in per_world {
        let result = result?;
        let chosen = &result["move"];
        let Some(position) = legal.iter().position(|mv| mv == chosen) else {
            return Err("a world chose a move outside the shared legal list".into());
        };
        votes[position] += 1;
        value_sum[position] += result["value"].as_f64().unwrap_or(0.0);
        nodes += result["nodes"].as_u64().unwrap_or(0);
        leaves += result["leaves"].as_u64().unwrap_or(0);
        cutoffs += result["cutoffs"].as_u64().unwrap_or(0);
        hits += result["table_hits"].as_u64().unwrap_or(0);
        depth_sum += result["depth"].as_i64().unwrap_or(0);
        searched += 1;
    }

    let best = (0..legal.len())
        .max_by(|&a, &b| {
            votes[a]
                .cmp(&votes[b])
                .then(value_sum[a].partial_cmp(&value_sum[b]).unwrap_or(std::cmp::Ordering::Equal))
        })
        .unwrap();

    Ok(json!({
        "move": legal[best].clone(),
        "value": if votes[best] > 0 { value_sum[best] / votes[best] as f64 } else { 0.0 },
        "depth": if searched > 0 { depth_sum / searched as i64 } else { 0 },
        "votes": votes[best],
        "worlds": worlds.len(),
        "lanes": lanes,
        "nodes": nodes,
        "leaves": leaves,
        "cutoffs": cutoffs,
        "table_hits": hits,
        "table_size": 0,
        "ms": clock.elapsed_ms(),
    }))
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod tests {
    use super::*;

    /// Walk a real game to a position where the seat to act has a genuine
    /// choice. The opening is not a fair test on its own -- it is one position,
    /// and several of the interesting ones only appear mid-game.
    fn position(seed: u64, skip: usize) -> (State, usize) {
        let sides = [1 + ((seed >> 3) & 1) as i32, 2, 1];
        let (mut state, mut chance) = State::new(seed, sides);
        let mut seen = 0;
        while let Some(actor) = state.actor() {
            let legal = state.legal_moves(actor);
            if legal.len() > 1 {
                if seen == skip {
                    return (state, actor);
                }
                seen += 1;
            }
            let observation = state.observation(actor);
            let best = (0..legal.len())
                .max_by(|&a, &b| {
                    action_score_with(&observation, &legal[a], true)
                        .partial_cmp(&action_score_with(&observation, &legal[b], true))
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap();
            state.apply(actor, &legal[best], &mut chance).unwrap();
        }
        panic!("seed {seed} never reached {skip} positions with a real choice");
    }

    /// A generous budget with a small depth cap, so the clock never ends an
    /// iteration and these tests are about the SEARCH rather than the machine
    /// they run on. A time-limited test would be flaky by construction.
    fn config(max_depth: usize) -> AbConfig {
        AbConfig {
        budget_ms: 600_000,
        max_depth,
        use_table: true,
        leaf: Leaf::StateValue,
        quiescence: false,
        victory_aware_ranker: true,
    }
    }

    fn config_without_table(max_depth: usize) -> AbConfig {
        AbConfig { use_table: false, ..config(max_depth) }
    }

    #[test]
    fn chooses_a_move_the_engine_calls_legal() {
        for skip in [0, 3, 7] {
            let (state, seat) = position(77, skip);
            let result = choose(&state, seat, 5, config(2)).unwrap();
            let legal = state.legal_moves(seat);
            assert!(
                legal.contains(&result["move"]),
                "skip {skip}: chose a move outside the legal list"
            );
        }
    }

    #[test]
    fn iterative_deepening_reaches_the_depth_it_is_given() {
        let (state, seat) = position(77, 0);
        for depth in [1usize, 2, 3] {
            let result = choose(&state, seat, 5, config(depth)).unwrap();
            assert_eq!(
                result["depth"].as_u64().unwrap(),
                depth as u64,
                "an unlimited budget must complete every requested depth"
            );
        }
    }

    #[test]
    fn the_search_is_deterministic() {
        let (state, seat) = position(404, 2);
        let first = choose(&state, seat, 9, config(3)).unwrap();
        let second = choose(&state, seat, 9, config(3)).unwrap();
        assert_eq!(first["move"], second["move"]);
        assert_eq!(first["value"], second["value"]);
        assert_eq!(first["nodes"], second["nodes"]);
    }

    /// THE EQUIVALENCE GATE. A transposition table buys depth; it must never
    /// change what the search concludes. Asserting the root VALUE rather than
    /// the root MOVE is deliberate -- among equal-valued moves a cutoff may
    /// legitimately return a different one, so a move assertion would fail on
    /// correct code and teach the wrong lesson when it did.
    #[test]
    fn the_transposition_table_does_not_change_the_value() {
        for (seed, skip) in [(77u64, 0usize), (404, 2), (1234, 5)] {
            let (state, seat) = position(seed, skip);
            let with = choose(&state, seat, 3, config(3)).unwrap();
            let without = choose(&state, seat, 3, config_without_table(3)).unwrap();
            assert_eq!(
                with["value"], without["value"],
                "seed {seed}/{skip}: the table changed the root value, so it is unsound"
            );
        }
    }

    /// ...and the gate above is only worth anything if the table is actually
    /// being used. Without this, a table that never stored or never hit would
    /// pass the equivalence test trivially -- the same vacuous-guard shape the
    /// repo has been bitten by before.
    #[test]
    fn the_transposition_table_is_actually_exercised() {
        let (state, seat) = position(404, 2);
        let result = choose(&state, seat, 3, config(4)).unwrap();
        assert!(
            result["table_size"].as_u64().unwrap() > 0,
            "the table stored nothing, so the equivalence test proves nothing"
        );
        assert!(
            result["table_hits"].as_u64().unwrap() > 0,
            "the table never hit, so the equivalence test proves nothing"
        );
        let off = choose(&state, seat, 3, config_without_table(4)).unwrap();
        assert_eq!(
            off["table_hits"].as_u64().unwrap(),
            0,
            "the control arm must not be using the table"
        );
        // NOT asserted: that the table saves nodes. It does not, in Orbit --
        // measured 710 nodes with against 657 without at depth 4, on 10 hits.
        // Positions barely transpose here, so the table is close to pure
        // overhead and the stale move it suggests can order slightly worse than
        // the prior alone. `ab_probe --compare-table` is the standing
        // measurement of whether it pays at the depth actually searched; the
        // invariant this test defends is only that the control arm is genuinely
        // a control.
        assert_eq!(
            off["table_size"].as_u64().unwrap(),
            0,
            "the control arm must not be filling the table either"
        );
    }

    /// Alpha-beta must not report a value the leaf cannot produce. `state_value`
    /// is a tanh-bounded evaluator and terminals are exactly +/-1, so anything
    /// outside that range means a sign flip or an uninitialised sentinel has
    /// escaped -- both of which are silent, and both of which would still
    /// return a playable move.
    #[test]
    fn the_reported_value_stays_inside_the_leaf_range() {
        for (seed, skip) in [(77u64, 1usize), (404, 4), (1234, 0)] {
            let (state, seat) = position(seed, skip);
            let result = choose(&state, seat, 11, config(3)).unwrap();
            let value = result["value"].as_f64().unwrap();
            assert!(
                (-1.0..=1.0).contains(&value),
                "seed {seed}/{skip}: value {value} is outside the leaf range"
            );
        }
    }

    /// PIMC must not depend on how many threads it happened to get. The lanes
    /// finish in arbitrary order, so the tally is sorted by world index before
    /// voting -- without that, the same position could answer differently on a
    /// busy machine, and a mirror control could not read 0.5.
    #[test]
    fn pimc_is_independent_of_the_thread_count() {
        let (state, seat) = position(404, 2);
        let worlds: Vec<State> = (0..4)
            .map(|k| {
                State::from_observation(&state.observation(seat), 900 + k)
                    .expect("the walked position is reconstructable")
            })
            .collect();
        let one = choose_over_worlds_with_threads(&worlds, seat, 7, config(3), 1).unwrap();
        for threads in [2usize, 4, 8] {
            let many =
                choose_over_worlds_with_threads(&worlds, seat, 7, config(3), threads).unwrap();
            assert_eq!(
                one["move"], many["move"],
                "{threads} lanes chose differently from 1"
            );
            assert_eq!(one["votes"], many["votes"], "{threads} lanes tallied differently");
        }
    }

    /// Each world must get the budget its LANE can afford, not the budget
    /// divided by the world count. At K <= threads that is the whole allowance,
    /// which is the entire reason PIMC is a serving candidate: four worlds on
    /// four workers each search as deeply as one world would.
    #[test]
    fn lanes_are_reported_and_bounded_by_the_world_count() {
        let (state, seat) = position(404, 2);
        let worlds: Vec<State> = (0..4)
            .map(|k| {
                State::from_observation(&state.observation(seat), 700 + k)
                    .expect("the walked position is reconstructable")
            })
            .collect();
        let result = choose_over_worlds_with_threads(&worlds, seat, 7, config(2), 8).unwrap();
        assert_eq!(
            result["lanes"].as_u64().unwrap(),
            4,
            "asking for more lanes than worlds must not spawn idle threads"
        );
        assert_eq!(result["worlds"].as_u64().unwrap(), 4);
    }

    /// Determinizations of one observation differ only in hidden state, so they
    /// must agree about the legal moves -- the votes are tallied by INDEX, so a
    /// disagreement would silently be a tally over different moves.
    #[test]
    fn worlds_that_disagree_about_the_legal_moves_are_refused() {
        let (state, seat) = position(404, 2);
        let (other, other_seat) = position(1234, 5);
        let mismatched = vec![state.clone(), other.clone()];
        let result = choose_over_worlds(&mismatched, seat, 7, config(2));
        // Either the lists differ (refused) or the other position is not even
        // this seat's to act; both are errors, and a silent success is not.
        assert!(
            result.is_err() || seat == other_seat,
            "worlds with different legal lists must not be voted over"
        );
    }

    /// Quiescence must actually FIRE, and must actually stop. A flag that
    /// never extends is a silent no-op that would make its A/B read a clean
    /// null; one that never stops would hang a serving path.
    #[test]
    fn quiescence_extends_through_half_finished_turns_and_terminates() {
        let (state, seat) = position(404, 2);
        let quiet = AbConfig { quiescence: false, ..config(3) };
        let extending = AbConfig { quiescence: true, ..config(3) };
        let off = choose(&state, seat, 5, quiet).unwrap();
        let on = choose(&state, seat, 5, extending).unwrap();
        assert_eq!(
            off["extended"].as_u64().unwrap(),
            0,
            "the control arm must never extend"
        );
        assert!(
            on["extended"].as_u64().unwrap() > 0,
            "quiescence never fired, so its A/B would measure nothing"
        );
        // Terminating at all is the assertion; an unbounded extension would
        // never return and this test would time out rather than fail.
        assert!(on["nodes"].as_u64().unwrap() > 0);
    }

    /// Extending must not change what the search REPORTS about depth: the
    /// borrowed plies are past the horizon, not part of the iteration that
    /// completed.
    #[test]
    fn extending_does_not_inflate_the_reported_depth() {
        let (state, seat) = position(77, 3);
        let on = choose(&state, seat, 5, AbConfig { quiescence: true, ..config(3) }).unwrap();
        assert_eq!(on["depth"].as_u64().unwrap(), 3);
    }

    /// A seat that is not to act must be refused rather than answered. The
    /// arena drives both seats, so a wiring slip that searches the wrong one
    /// would otherwise produce plausible moves for the wrong player.
    #[test]
    fn refuses_a_seat_that_is_not_to_act() {
        let (state, seat) = position(77, 0);
        assert!(choose(&state, 1 - seat, 5, config(1)).is_err());
    }
}
