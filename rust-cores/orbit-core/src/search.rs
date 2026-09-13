//! Offline information-set PUCT baseline with an observation-only neural leaf.
//! Privileged input is used only as a determinization template; hidden pools are
//! replaced from public conservation before any policy/evaluator is called.
//! This current-observation prior is NOT a full-history posterior.
use crate::{attention::Model, Chance, State};
use serde_json::{json, Value};
use std::collections::{BTreeSet, HashMap};
use std::hash::{Hash, Hasher};

#[cfg(all(feature = "profile-search", not(target_arch = "wasm32")))]
type ProfileStamp = Option<std::time::Instant>;
#[cfg(any(not(feature = "profile-search"), target_arch = "wasm32"))]
type ProfileStamp = ();

#[cfg(all(feature = "profile-search", not(target_arch = "wasm32")))]
#[inline]
fn profile_enabled() -> bool {
    std::env::var_os("ORBIT_PROFILE_SEARCH").is_some()
}
#[cfg(any(not(feature = "profile-search"), target_arch = "wasm32"))]
#[inline]
fn profile_enabled() -> bool {
    false
}

#[cfg(all(feature = "profile-search", not(target_arch = "wasm32")))]
#[inline]
fn profile_start(enabled: bool) -> ProfileStamp {
    enabled.then(std::time::Instant::now)
}
#[cfg(any(not(feature = "profile-search"), target_arch = "wasm32"))]
#[inline]
fn profile_start(_: bool) -> ProfileStamp {}

#[cfg(all(feature = "profile-search", not(target_arch = "wasm32")))]
#[inline]
fn profile_elapsed(start: ProfileStamp) -> u64 {
    start.map_or(0, |instant| instant.elapsed().as_nanos() as u64)
}
#[cfg(any(not(feature = "profile-search"), target_arch = "wasm32"))]
#[inline]
fn profile_elapsed(_: ProfileStamp) -> u64 {
    0
}

#[derive(Default)]
struct SearchProfile {
    total_ns: u64,
    sample_ns: u64,
    actor_observation_ns: u64,
    opponent_rank_ns: u64,
    apply_ns: u64,
    post_observation_ns: u64,
    node_ns: u64,
    features_ns: u64,
    tensors_ns: u64,
    model_ns: u64,
    heuristic_ns: u64,
    simulations: u64,
    evaluations: u64,
    cache_hits: u64,
}

impl SearchProfile {
    fn as_value(&self) -> Value {
        json!({
            "total_ns": self.total_ns,
            "sample_ns": self.sample_ns,
            "actor_observation_ns": self.actor_observation_ns,
            "opponent_rank_ns": self.opponent_rank_ns,
            "apply_ns": self.apply_ns,
            "post_observation_ns": self.post_observation_ns,
            "node_ns": self.node_ns,
            "features_ns": self.features_ns,
            "tensors_ns": self.tensors_ns,
            "model_ns": self.model_ns,
            "heuristic_ns": self.heuristic_ns,
            "simulations": self.simulations,
            "evaluations": self.evaluations,
            "cache_hits": self.cache_hits,
        })
    }
}

#[derive(Clone, Copy)]
pub struct Config {
    pub simulations: usize,
    pub max_depth: usize,
    pub budget_ms: u64,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            simulations: 256,
            max_depth: 96,
            budget_ms: 5000,
        }
    }
}
#[derive(Default)]
struct Edge {
    visits: usize,
    sum: f64,
    prior: f64,
}
struct Node {
    moves: Vec<Value>,
    edges: Vec<Edge>,
    visits: usize,
}
impl Node {
    fn new(obs: &Value) -> Self {
        Self::new_with_prior(obs, None, 0.0)
    }

    /// `learned` is one logit per legal move in the OBSERVATION's order.
    ///
    /// The tree works in SORTED move order, so the two orders are reconciled
    /// explicitly here. This is the same gather that `policy_parity` exists to
    /// protect: a mismatch does not crash and does not look wrong -- it primes
    /// one move's search with another move's prior, which reads downstream as
    /// a policy head that failed to learn anything.
    ///
    /// At `weight == 0` this is bit-for-bit the historical prior, whether or
    /// not logits were supplied.
    fn new_with_prior(obs: &Value, learned: Option<&[f32]>, weight: f64) -> Self {
        let original = obs["legal_moves"].as_array().unwrap();
        let mut order: Vec<usize> = (0..original.len()).collect();
        order.sort_by_key(|&i| original[i].to_string());
        let moves: Vec<Value> = order.iter().map(|&i| original[i].clone()).collect();
        let scores: Vec<f64> = moves
            .iter()
            .map(|m| crate::serving::action_score(obs, m))
            .collect();
        let max = scores.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let weights: Vec<f64> = scores.iter().map(|s| ((s - max) / 4.0).exp()).collect();
        let sum = weights.iter().sum::<f64>();
        // Softmax the learned logits over the same moves, permuted into the
        // tree's order. The caller guarantees the length; falling back silently
        // on a mismatch would hide exactly the defect worth catching.
        let learned_prior: Option<Vec<f64>> = learned.filter(|_| weight > 0.0).map(|logits| {
            let top = logits.iter().copied().fold(f32::NEG_INFINITY, f32::max) as f64;
            let exponentials: Vec<f64> = order
                .iter()
                .map(|&i| ((logits[i] as f64) - top).exp())
                .collect();
            let total: f64 = exponentials.iter().sum();
            exponentials.into_iter().map(|e| e / total).collect()
        });
        let count = weights.len() as f64;
        let edges = (0..weights.len())
            .map(|i| {
                let heuristic = weights[i] / sum;
                let blended = match &learned_prior {
                    Some(prior) => (1.0 - weight) * heuristic + weight * prior[i],
                    None => heuristic,
                };
                Edge {
                    prior: 0.97 * blended + 0.03 / count,
                    ..Default::default()
                }
            })
            .collect();
        Self {
            moves,
            edges,
            visits: 0,
        }
    }
    /// `minimizing` is true at an OPPONENT node: values are kept in the root
    /// seat's frame, so the opponent maximises their negation.
    fn select(&self, minimizing: bool) -> usize {
        let mut best = 0;
        let mut score = f64::NEG_INFINITY;
        for (i, e) in self.edges.iter().enumerate() {
            let mean = if e.visits == 0 {
                0.0
            } else {
                let average = e.sum / e.visits as f64;
                if minimizing { -average } else { average }
            };
            let s =
                mean + 1.35 * e.prior * (self.visits.max(1) as f64).sqrt() / (1 + e.visits) as f64;
            if s > score {
                best = i;
                score = s;
            }
        }
        best
    }
}

fn sample(source: &State, seat: usize, rng: &mut Chance) -> Result<State, String> {
    let obs = source.observation(seat);
    let mut known: BTreeSet<u16> = source.players[seat].hand.iter().copied().collect();
    known.extend(source.agent_discard.iter().copied());
    for p in &source.players {
        for col in &p.columns {
            known.extend(col.iter().copied());
        }
    }
    let mut unseen: Vec<u16> = crate::rules()
        .cards
        .keys()
        .filter(|id| !known.contains(id))
        .copied()
        .collect();
    let hand = obs["players"][1 - seat]["hand_count"]
        .as_u64()
        .ok_or("Missing hand count")? as usize;
    if unseen.len() != hand + source.agent_deck.len() {
        return Err("Agent conservation mismatch".into());
    }
    rng.shuffle(&mut unseen);
    let mut bonuses = crate::rules().bonus_pool.clone();
    bonuses.sort();
    for id in source.bonus_discard.iter().copied().chain(
        source
            .planet_bonus
            .iter()
            .chain(source.technology_bonus.iter())
            .filter_map(|x| *x),
    ) {
        let index = bonuses
            .iter()
            .position(|b| *b == id)
            .ok_or("Bonus conservation mismatch")?;
        bonuses.remove(index);
    }
    if bonuses.len() != source.bonus_deck.len() {
        return Err("Bonus reserve mismatch".into());
    }
    rng.shuffle(&mut bonuses);
    let mut world = source.clone();
    world.players[1 - seat].hand = unseen.drain(..hand).collect();
    world.agent_deck = unseen;
    world.bonus_deck = bonuses;
    Ok(world)
}

fn terminal(world: &State, seat: usize) -> Option<f64> {
    if world.phase != "over" {
        None
    } else {
        Some(
            world
                .winner
                .map_or(0.0, |w| if w == seat { 1.0 } else { -1.0 }),
        )
    }
}
/// How the search answers the OPPONENT's decisions.
///
/// This is the single most structural thing about Orbit's search, and until
/// 2026-09-12 there was only one option. `Ranker` builds nodes for the
/// searching seat ONLY: every opponent decision is answered by an external call
/// to the 1-ply `serving::choose_move` heuristic. That is not an adversarial
/// search at all -- it optimises a line against a fixed environment policy that
/// plays greedily, so it can neither find a move the opponent has no answer to
/// nor avoid one it does. It also costs 43% of search time (measured 2026-09-11
/// at 256 simulations with the heuristic leaf) to consult that strawman.
///
/// Duel had the same defect in a different flavour -- `select()` was MAX-MAX,
/// modelling the opponent as cooperating -- and the minimax fix was worth
/// 0.62 at c=1.0 and 0.67 at c=0.3 there (research log, 2026-07-26).
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum OpponentModel {
    /// Historical: the 1-ply ranker, called from outside the tree.
    #[default]
    Ranker,
    /// The opponent gets its OWN nodes and minimises the root seat's value.
    ///
    /// Values are stored from the root seat's perspective and backed up
    /// unchanged along the whole path, so this needs a sign flip in SELECTION
    /// only -- an opponent node maximises `-mean`. Within a determinized world
    /// both seats are assumed to know it, which is ordinary PIMC and the same
    /// strategy-fusion trade coherent determinization already accepted.
    Minimax,
}

/// Which leaf evaluator a search uses for nonterminal positions.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Leaf {
    /// The full public-state evaluator ported from `ai/search.py::state_value`.
    #[default]
    StateValue,
    /// Capture progress only. This is what the Rust port actually shipped from
    /// its first commit until 2026-09-11, and it is retained ONLY as the
    /// explicit control arm for the A/B that replaced it. It is not a tier.
    CaptureProgressOnly,
}

fn progress(obs: &Value, seat: usize) -> f64 {
    let captured = obs["players"][seat]["captured"].as_array().unwrap();
    let mut counts = [0usize; 5];
    for c in captured {
        counts[c.as_u64().unwrap() as usize] += 1;
    }
    (captured.len() as f64 / 5.0)
        .max(counts.iter().filter(|n| **n > 0).count() as f64 / 4.0)
        .max(*counts.iter().max().unwrap() as f64 / 3.0)
}

/// Capture progress only: the pre-2026-09-11 Rust leaf, kept as a control.
///
/// Measured over 19,034 real positions this takes **25 distinct values in an
/// entire game**, is exactly 0.0 on 35% of positions, and is flat for the first
/// 26% of every game. A tree cannot convert depth into strength over an
/// evaluator this coarse, which is why the simulation ladder stops paying at
/// ~192 and why "beats the free heuristic leaf" was never a real bar.
pub fn capture_progress_only(obs: &Value) -> f64 {
    let me = obs["seat"].as_u64().unwrap() as usize;
    (progress(obs, me) - progress(obs, 1 - me)).tanh()
}

/// Public-state leaf value from the viewing seat's perspective.
///
/// This is a faithful port of `games/orbit/ai/search.py::state_value`, which the
/// original Rust port silently reduced to its first term. Everything here is
/// read from the seat's OWN observation — opponent hands and both deck orders
/// are structurally absent, so a determinized world cannot leak through the
/// leaf. `tools/leaf_parity.py` holds Python and Rust to each other.
///
/// The weights are the Python reference's and are deliberately NOT retuned
/// here: eval-weight tuning is the documented saturated lever in three sibling
/// campaigns, and the point of this change is that the search had no state
/// evaluator at all, not that it had the wrong one.
pub fn state_value(obs: &Value) -> f64 {
    let seat = obs["seat"].as_u64().unwrap() as usize;
    let other = 1 - seat;
    if obs["phase"] == "over" {
        return match obs["winner"].as_u64() {
            None => 0.0,
            Some(w) => {
                if w as usize == seat {
                    1.0
                } else {
                    -1.0
                }
            }
        };
    }
    let me = &obs["players"][seat];
    let them = &obs["players"][other];
    let num = |v: &Value| v.as_f64().unwrap_or(0.0);
    let sum_array = |v: &Value| {
        v.as_array()
            .map_or(0.0, |items| items.iter().map(num).sum::<f64>())
    };
    let len_array = |v: &Value| v.as_array().map_or(0.0, |items| items.len() as f64);

    // Capture progress is nonlinear: two discs from one planet are much more
    // useful than two scattered discs, because the third ends the game.
    let mut value = 1.4 * (progress(obs, seat) - progress(obs, other));

    // Influence proximity — the single largest thing the old leaf could not
    // see. A disc three steps into your zone is one influence from a capture,
    // and the cubic term is what makes that urgency legible to the search.
    // Seat 0 pushes the disc positive, seat 1 negative (`gain_influence`).
    let direction = if seat == 0 { 1.0 } else { -1.0 };
    if let Some(track) = obs["influence"].as_array() {
        for position in track {
            let Some(position) = position.as_f64() else {
                continue; // captured this turn; the disc resets at turn end
            };
            let toward = position * direction;
            value += 0.11 * toward + 0.06 * toward.powi(3) / 27.0;
            if toward >= 2.0 {
                value += 0.18;
            } else if toward <= -2.0 {
                value -= 0.18;
            }
        }
    }
    value += 0.05 * (len_array(&me["captured"]) - len_array(&them["captured"]));
    value += 0.018 * (sum_array(&me["technology"]) - sum_array(&them["technology"]));
    value += 0.03 * (len_array(&me["row_bonuses"]) - len_array(&them["row_bonuses"]));
    let leader_level = num(&obs["leader"]["level"]);
    match obs["leader"]["owner"].as_u64() {
        Some(owner) if owner as usize == seat => value += 0.09 + 0.035 * leader_level,
        Some(_) => value -= 0.09 + 0.035 * leader_level,
        None => {}
    }
    value += 0.025 * (num(&me["credits"]) - num(&them["credits"]));
    value += 0.04 * (num(&me["zenithium"]) - num(&them["zenithium"]));
    // Own hand against the opponent's PUBLIC columns: both are visible to this
    // seat, and the asymmetry is the reference's, not an oversight.
    let cost_of = |cards: &Value| {
        cards.as_array().map_or(0.0, |items| {
            items
                .iter()
                .filter_map(|c| c.as_u64())
                .filter_map(|id| crate::rules().cards.get(&(id as u16)))
                .map(|card| card.cost as f64)
                .sum()
        })
    };
    let own_cards = cost_of(&me["hand"]);
    let public_opponent_cards: f64 = them["columns"]
        .as_array()
        .map_or(0.0, |columns| columns.iter().map(cost_of).sum());
    value += 0.005 * (own_cards - public_opponent_cards);
    value.tanh()
}

fn leaf_value(obs: &Value, leaf: Leaf) -> f64 {
    match leaf {
        Leaf::StateValue => state_value(obs),
        Leaf::CaptureProgressOnly => capture_progress_only(obs),
    }
}
pub fn choose(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
) -> Result<Value, String> {
    choose_with_options(source, seat, seed, config, model, 1, 1.0)
}

/// Search with an optional sparse/residual neural leaf.
///
/// The browser has a fixed whole-turn budget, so paying for a neural forward
/// on every simulation can reduce the number of tactical samples enough to
/// lose strength.  ``model_stride`` evaluates the network on every Nth leaf;
/// the other leaves use the free, audited heuristic.  ``model_weight`` blends
/// the two values on network evaluations.  The default ``choose`` path keeps
/// the original all-network semantics for reproducibility; experiments opt in
/// explicitly and report the setting in their arena artifact.
pub fn choose_with_options(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    model_stride: usize,
    model_weight: f64,
) -> Result<Value, String> {
    choose_with_controls(
        source,
        seat,
        seed,
        config,
        model,
        model_stride,
        model_weight,
        2.0,
    )
}

/// Full experimental controls, including logit temperature.  A temperature
/// above two softens an overconfident terminal-outcome predictor before it can
/// dominate PUCT; the default remains exactly the historical logit/2 mapping.
pub fn choose_with_controls(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    model_stride: usize,
    model_weight: f64,
    model_temperature: f64,
) -> Result<Value, String> {
    choose_with_leaf(
        source,
        seat,
        seed,
        config,
        model,
        model_stride,
        model_weight,
        model_temperature,
        Leaf::default(),
    )
}

/// Every experimental knob in one place.
///
/// `Default` reproduces the historical search exactly, so an existing entry
/// point that does not mention `Controls` is byte-identical to what it was.
#[derive(Clone, Copy, Debug)]
pub struct Controls {
    pub model_stride: usize,
    pub model_weight: f64,
    pub model_temperature: f64,
    pub leaf: Leaf,
    /// How many consecutive simulations share one sampled world and one frozen
    /// chance stream.
    ///
    /// `1` is the historical behaviour: a fresh determinization EVERY
    /// simulation. Because a node's key embeds the observation that follows
    /// from that world, resampling per simulation means almost no node is ever
    /// visited twice -- measured 2026-09-11 at 19 of 232 nodes per search, mean
    /// depth 2.4 plies, with the exact leaf cache hitting 0.3% of the time.
    /// `usize::MAX` is one coherent world for the whole call, which restores
    /// the tree (63% multi-visit nodes, depth 4.2) at the cost of PIMC-style
    /// strategy fusion. Duel shipped the coherent form; Orbit's hidden
    /// information is about half of Duel's (perfect-information cheat 0.6094
    /// against 0.7250), so the trade is its own measurement, not an inheritance.
    pub determinization_period: usize,
    /// How the opponent's decisions are answered inside the tree.
    ///
    /// `Ranker` is the historical search. `Minimax` gives the opponent its own
    /// nodes, which is both the adversarial fix and a way to DELETE the 43% the
    /// external ranker call costs, rather than paying it twice over.
    pub opponent_model: OpponentModel,
    /// Whether hidden information is resampled at all.
    ///
    /// `true` is every search this campaign has ever run: `sample()` rebuilds
    /// the opponent's hand and the deck order from the seat's observation, so
    /// handing the search a privileged state changes NOTHING -- it throws the
    /// real hands away and resamples. That is correct for serving and it is why
    /// the arena's `via_observation` flag is about which state is handed IN,
    /// not about what the search then knows.
    ///
    /// `false` searches the world exactly as given, which is only meaningful
    /// when the caller passes the true state. It exists for one measurement:
    /// comparing search ARCHITECTURES at equal information. Without it, giving
    /// alpha-beta the true state and the MCTS a resampled one measures the
    /// hidden-information cheat (worth 0.6094 on its own) and calls it depth.
    pub determinize: bool,
    /// How much of the PUCT prior comes from the network's policy head.
    ///
    /// `0.0` is the historical search: the prior is entirely the frozen
    /// hand-written `action_score`, which the 2026-09-11 audit measured
    /// deciding 50.5% of moves outright. Above zero the model must carry a
    /// policy head, and one extra forward runs per NEW node -- Orbit expands
    /// far more nodes than it revisits (19 of 232 under per-simulation
    /// determinization), so that cost is real and is the first thing to
    /// measure, not assume.
    pub policy_prior_weight: f64,
}

impl Default for Controls {
    fn default() -> Self {
        Self {
            model_stride: 1,
            model_weight: 1.0,
            model_temperature: 2.0,
            leaf: Leaf::default(),
            determinization_period: 1,
            opponent_model: OpponentModel::Ranker,
            determinize: true,
            policy_prior_weight: 0.0,
        }
    }
}

impl Controls {
    /// What Orbit actually SERVES, as one named thing.
    ///
    /// `Default` is deliberately the HISTORICAL search, so every past campaign
    /// number reproduces without archaeology; this is the separate, explicit
    /// statement of what ships, and the two are expected to diverge.
    ///
    /// Coherent determinization, measured 2026-09-12 at real serving shape --
    /// a 3000ms turn split 1800/1200 and a four-worker root ensemble, which is
    /// what `ORBIT_AI_WORKER_CAP` hands every client with five or more threads:
    ///
    /// ```text
    /// 0.6094 over 128 CRN pairs, 95% CI [0.550, 0.669]
    /// 19 losses / 62 splits / 47 wins
    /// ```
    ///
    /// Individual 16-pair pools ranged 0.4375 to 0.7188, which is why the bar
    /// is 128 pairs and why no single pool is a verdict.
    ///
    /// It wins while doing FEWER simulations -- about 10,900 per decision
    /// against per-simulation determinization's 14,200 -- because reusing the
    /// tree means descending it (mean depth 4.2 plies against 2.4). The lever
    /// is the soundness of the search, not its throughput.
    pub fn serving() -> Self {
        Self {
            determinization_period: usize::MAX,
            ..Self::default()
        }
    }

    fn sanitized(self) -> Self {
        Self {
            model_stride: self.model_stride.max(1),
            model_weight: self.model_weight.clamp(0.0, 1.0),
            model_temperature: self.model_temperature.max(0.1),
            determinization_period: self.determinization_period.max(1),
            policy_prior_weight: self.policy_prior_weight.clamp(0.0, 1.0),
            ..self
        }
    }
}

/// Same as [`choose_with_controls`] with an explicit leaf evaluator.
#[allow(clippy::too_many_arguments)]
pub fn choose_with_leaf(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    model_stride: usize,
    model_weight: f64,
    model_temperature: f64,
    leaf: Leaf,
) -> Result<Value, String> {
    choose_with(source, seat, seed, config, model, Controls {
        model_stride,
        model_weight,
        model_temperature,
        leaf,
        ..Controls::default()
    })
}

/// The full-control entry point.
pub fn choose_with(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    controls: Controls,
) -> Result<Value, String> {
    choose_cached_options(source, seat, seed, config, model, controls.sanitized(), true)
}
/// The cache-equivalence control arm: same search, cache switchable.
///
/// Test-only. The cache must not change a single chosen move -- it exists to
/// buy simulations, not to alter them -- so every regime is asserted against
/// this with `cache_enabled` false. Nothing in a serving or offline path
/// reaches it, hence `cfg(test)` rather than an `allow(dead_code)` that would
/// also hide a genuinely abandoned function.
#[cfg(test)]
fn choose_cached(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    cache_enabled: bool,
) -> Result<Value, String> {
    choose_cached_options(source, seat, seed, config, model, Controls::default(), cache_enabled)
}
fn choose_cached_options(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    controls: Controls,
    cache_enabled: bool,
) -> Result<Value, String> {
    let Controls {
        model_stride,
        model_weight,
        model_temperature,
        leaf,
        determinization_period,
        opponent_model,
        determinize,
        policy_prior_weight,
    } = controls;
    if seat > 1 || source.actor() != Some(seat) {
        return Err("Not this seat's decision".into());
    }
    // A model that carries a policy head must have it USED. Silently searching
    // with the hand-written prior instead is the failure that reads as a policy
    // head which learned nothing, so it fails loudly here rather than producing
    // a number. `Model::load` refuses policy artifacts for the same reason;
    // this is the second gate, for anything that got in through `load_any`.
    if model.is_some_and(Model::has_policy) && policy_prior_weight <= 0.0 {
        return Err("A policy-head model needs a positive policy prior weight".into());
    }
    let started = crate::clock::Clock::start();
    let profiling = profile_enabled();
    let profile_started = profile_start(profiling);
    let mut profile = SearchProfile::default();
    let obs = source.observation(seat);
    let mut nodes: HashMap<(u64, String), Node> = HashMap::new();
    let root = (0, "root".to_owned());
    let node_started = profile_start(profiling);
    // One forward per NEW node when a learned prior is asked for. Counted
    // separately from leaf evaluations so its cost is visible rather than
    // folded into `evaluations`.
    let mut policy_evaluations = 0usize;
    // Nodes created for the OPPONENT's decisions. Zero under `Ranker` by
    // construction, and the only direct evidence that the adversarial half of
    // the tree is actually being built -- node TOTALS cannot show it, because
    // expanding an opponent node ends that simulation's descent and so trades
    // against nodes on our own side.
    let mut opponent_nodes = 0usize;
    let learned_prior = |observation: &Value| -> Result<Option<Vec<f32>>, String> {
        if policy_prior_weight <= 0.0 {
            return Ok(None);
        }
        let model = model.ok_or("A policy prior weight needs a model")?;
        if !model.has_policy() {
            return Err("A policy prior weight needs a policy-head model".into());
        }
        let tokens = crate::features::encode(observation, None)?;
        let (rows, actions) = model.encode_tokens_with_actions(&tokens)?;
        // The length is checked HERE, where it can still be an error. `Node`
        // indexes the logits by move, so a short list would otherwise either
        // panic or, worse, be silently truncated into a shuffled prior.
        if actions.len() != observation["legal_moves"].as_array().map_or(0, Vec::len) {
            return Err("Policy logits do not cover every legal move".into());
        }
        Ok(Some(model.value_and_policy(&rows, &actions)?.1))
    };
    let root_prior = learned_prior(&obs)?;
    if root_prior.is_some() {
        policy_evaluations += 1;
    }
    nodes.insert(
        root.clone(),
        Node::new_with_prior(&obs, root_prior.as_deref(), policy_prior_weight),
    );
    profile.node_ns += profile_elapsed(node_started);
    let mut rng = Chance::seeded(seed);
    let mut sims = 0;
    let mut evals = 0;
    // Exact observation keys: no hidden state, hash-only collisions, or
    // history-dependent estimates. Lifetime is one call with one fixed model.
    let mut values: HashMap<String, f64> = HashMap::new();
    let mut cache_hits = 0;
    let mut determinization: Option<State> = None;
    let mut frozen_chance_seed: u64 = 0;
    let mut opponent_replies: HashMap<String, Value> = HashMap::new();
    let mut opponent_cache_hits = 0usize;
    for simulation in 0..config.simulations {
        if started.elapsed_ms() >= config.budget_ms as f64 {
            break;
        }
        let sample_started = profile_start(profiling);
        if simulation % determinization_period == 0 {
            determinization = Some(if determinize {
                sample(source, seat, &mut rng)?
            } else {
                source.clone()
            });
            frozen_chance_seed = rng.next();
        }
        // `expect` cannot fire: simulation 0 always takes the branch above.
        let mut world = determinization.clone().expect("determinization sampled");
        profile.sample_ns += profile_elapsed(sample_started);
        let mut chance = Chance::seeded(frozen_chance_seed);
        let mut path = Vec::new();
        let mut trace = 0u64;
        let mut leaf_observation: Option<Value> = None;
        for depth in 0..config.max_depth {
            let Some(actor) = world.actor() else { break };
            let actor_observation_started = profile_start(profiling);
            let actor_obs = world.observation(actor);
            profile.actor_observation_ns += profile_elapsed(actor_observation_started);
            let searched_here = actor == seat || opponent_model == OpponentModel::Minimax;
            let minimizing = actor != seat;
            let (mv, unvisited) = if searched_here {
                let key = if depth == 0 {
                    root.clone()
                } else {
                    (trace, actor_obs.to_string())
                };
                // One extra lookup, and only for opponent decisions, which
                // exist at all only under `Minimax`.
                let fresh_opponent_node = minimizing && !nodes.contains_key(&key);
                let node_started = profile_start(profiling);
                // The default path keeps its single hash lookup; only a
                // learned prior pays for the miss check, because computing it
                // returns a Result that `or_insert_with` cannot carry.
                let node = if policy_prior_weight > 0.0 {
                    if !nodes.contains_key(&key) {
                        let prior = learned_prior(&actor_obs)?;
                        if prior.is_some() {
                            policy_evaluations += 1;
                        }
                        nodes.insert(
                            key.clone(),
                            Node::new_with_prior(&actor_obs, prior.as_deref(), policy_prior_weight),
                        );
                    }
                    nodes.get_mut(&key).expect("inserted above")
                } else {
                    nodes
                        .entry(key.clone())
                        .or_insert_with(|| Node::new(&actor_obs))
                };
                if minimizing && fresh_opponent_node {
                    opponent_nodes += 1;
                }
                profile.node_ns += profile_elapsed(node_started);
                let action = node.select(minimizing);
                let unvisited = node.edges[action].visits == 0;
                let mv = node.moves[action].clone();
                path.push((key, action));
                (mv, unvisited)
            } else {
                let moves = actor_obs["legal_moves"].as_array().unwrap();
                let opponent_started = profile_start(profiling);
                // THE OPPONENT MODEL IS 43% OF THIS SEARCH'S TIME, and the
                // evaluator is ~0% of it (measured 2026-09-11 at 256 simulations
                // with the heuristic leaf). Every accepted speedup in the
                // preceding campaign targeted the neural leaf, which is correct
                // for that build and irrelevant to the tier that actually ships.
                //
                // The reply is a PURE FUNCTION of the acting seat's observation
                // here: `memory` is always Null, the budget is a constant, and
                // `seed` is fixed for the whole call, while `moves` is just
                // `actor_obs["legal_moves"]`. So keying on the serialized
                // observation is exact, not approximate -- the same equivalence
                // gate as the leaf cache, and it shares its flag so
                // `choose_cached(.., false)` still reproduces the uncached search.
                //
                // It only pays under a COHERENT tree: with a fresh
                // determinization per simulation almost no position recurs,
                // which is why the leaf cache hit 0.3% of the time.
                // Gated on the determinization regime, not just `cache_enabled`.
                // With a fresh world every simulation NO opponent position ever
                // recurs: measured 0 hits and a 0.93x SLOWDOWN at 192
                // simulations, because the key still costs a serialization.
                // Under coherence the same cache is 1.40x at 192 and 1.66x at
                // 768, growing with simulations as the tree deepens.
                let selected = if cache_enabled && determinization_period > 1 {
                    let key = actor_obs.to_string();
                    if let Some(hit) = opponent_replies.get(&key) {
                        opponent_cache_hits += 1;
                        hit.clone()
                    } else {
                        let computed = crate::serving::choose_move(
                            &actor_obs,
                            moves,
                            &Value::Null,
                            5000,
                            seed,
                        );
                        if opponent_replies.len() < 4096 {
                            opponent_replies.insert(key, computed.clone());
                        }
                        computed
                    }
                } else {
                    crate::serving::choose_move(
                        &actor_obs,
                        moves,
                        &Value::Null,
                        5000,
                        seed,
                    )
                };
                profile.opponent_rank_ns += profile_elapsed(opponent_started);
                (
                    selected["move"].clone(),
                    false,
                )
            };
            let apply_started = profile_start(profiling);
            world.apply_search(actor, &mv, &mut chance)?;
            profile.apply_ns += profile_elapsed(apply_started);
            let mut hash = std::collections::hash_map::DefaultHasher::new();
            trace.hash(&mut hash);
            // The observation used to key the next information-set node is
            // also exactly the leaf view when this simulation stops. Keep it
            // so a nonterminal leaf does not serialize the same world twice.
            let post_observation_started = profile_start(profiling);
            let post_observation = world.observation(seat);
            profile.post_observation_ns += profile_elapsed(post_observation_started);
            post_observation.to_string().hash(&mut hash);
            leaf_observation = Some(post_observation);
            if actor == seat
                || matches!(
                    mv["action"].as_str(),
                    Some("recruit" | "technology" | "leader")
                )
            {
                mv.to_string().hash(&mut hash);
            } else if mv["action"] == "mulligan" {
                mv["card_ids"]
                    .as_array()
                    .map_or(0, Vec::len)
                    .hash(&mut hash);
            }
            trace = hash.finish();
            if unvisited || started.elapsed_ms() >= config.budget_ms as f64 {
                break;
            }
        }
        let value = if let Some(v) = terminal(&world, seat) {
            v
        } else {
            let view = leaf_observation.unwrap_or_else(|| world.observation(seat));
            // Sparse/residual leaves must not reuse a heuristic value for a
            // simulation that is scheduled to run the network (or vice
            // versa).  Keep the exact view key while separating the two
            // evaluator modes only when a stride is active.
            // A zero model weight means the LEAF is the hand-written evaluator, so
            // the forward would be computed and then multiplied by zero -- and
            // with a net leaf that forward is ~86% of search time. Skipping it
            // is value-preserving (w*x + (1-w)*leaf is exactly leaf at w=0) and
            // is what makes the hybrid measurable at equal TIME: hand-written
            // leaf, learned PRIOR, which is the half of the search the frozen
            // `action_score` was losing.
            let evaluate_model =
                model.is_some() && model_weight > 0.0 && simulation % model_stride == 0;
            let key = if cache_enabled {
                if leaf != Leaf::default() || determinization_period != 1 {
                    format!("{:?}:{}:{}", leaf, determinization_period, view)
                } else if model.is_some() && model_stride > 1 {
                    format!(
                        "{}:{}",
                        if evaluate_model {
                            "neural"
                        } else {
                            "heuristic"
                        },
                        view
                    )
                } else {
                    view.to_string()
                }
            } else {
                String::new()
            };
            if let Some(value) = values.get(&key) {
                cache_hits += 1;
                *value
            } else {
                let value = if let Some(model) = model.filter(|_| evaluate_model) {
                    let features_started = profile_start(profiling);
                    let tokens = crate::features::encode(&view, None)?;
                    profile.features_ns += profile_elapsed(features_started);
                    let tensors_started = profile_start(profiling);
                    let rows = model.encode_tokens(&tokens)?;
                    profile.tensors_ns += profile_elapsed(tensors_started);
                    let model_started = profile_start(profiling);
                    evals += 1;
                    let learned = (model.logit_typed(&rows)? as f64 / model_temperature).tanh();
                    profile.model_ns += profile_elapsed(model_started);
                    model_weight * learned + (1.0 - model_weight) * leaf_value(&view, leaf)
                } else {
                    let heuristic_started = profile_start(profiling);
                    let value = leaf_value(&view, leaf);
                    profile.heuristic_ns += profile_elapsed(heuristic_started);
                    value
                };
                if cache_enabled && values.len() < 4096 {
                    values.insert(key, value);
                }
                value
            }
        };
        for (key, action) in path {
            let node = nodes.get_mut(&key).unwrap();
            node.visits += 1;
            node.edges[action].visits += 1;
            node.edges[action].sum += value;
        }
        sims += 1;
    }
    let node = &nodes[&root];
    let best = if sims == 0 {
        node.edges
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.prior.total_cmp(&b.1.prior))
            .unwrap()
            .0
    } else {
        node.edges
            .iter()
            .enumerate()
            .max_by(|a, b| {
                a.1.visits.cmp(&b.1.visits).then_with(|| {
                    let mean = |e: &Edge| {
                        if e.visits == 0 {
                            0.0
                        } else {
                            e.sum / e.visits as f64
                        }
                    };
                    mean(a.1).total_cmp(&mean(b.1))
                })
            })
            .unwrap()
            .0
    };
    let root_value = if node.visits == 0 {
        0.0
    } else {
        node.edges.iter().map(|edge| edge.sum).sum::<f64>() / node.visits as f64
    };
    let stats: Vec<Value> = node
        .moves
        .iter()
        .zip(&node.edges)
        .map(|(m, e)| {
            json!({"move":m,"visits":e.visits,
         "value":if e.visits==0{0.0}else{e.sum/e.visits as f64},"prior":e.prior})
         })
         .collect();
    profile.simulations = sims as u64;
    profile.evaluations = evals as u64;
    profile.cache_hits = cache_hits as u64;
    profile.total_ns = profile_elapsed(profile_started);
    let mut result = json!({"move":node.moves[best],"simulations":sims,"evaluations":evals,"nodes":nodes.len(),"root_value":root_value,
        "value_cache_hits":cache_hits,"opponent_cache_hits":opponent_cache_hits,
        "policy_evaluations":policy_evaluations,"policy_prior_weight":policy_prior_weight,
        "opponent_nodes":opponent_nodes,"opponent_model":format!("{opponent_model:?}"),
        "elapsed_ms":started.elapsed_ms(),"stats":stats,"belief":"current-observation prior",
        "determinization_period":determinization_period,"leaf":format!("{leaf:?}")});
    if profiling {
        result["profile"] = profile.as_value();
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The historical search must stay reachable without naming any knob.
    /// A silent default flip would rewrite every past campaign number's meaning.
    #[test]
    fn defaults_are_the_historical_search() {
        let controls = Controls::default();
        assert_eq!(controls.determinization_period, 1, "per-simulation resampling");
        assert_eq!(controls.model_stride, 1);
        assert_eq!(controls.model_weight, 1.0);
        assert_eq!(controls.model_temperature, 2.0);
        assert_eq!(controls.leaf, Leaf::StateValue);
        assert_eq!(controls.policy_prior_weight, 0.0, "the hand-written action_score prior");
        assert_eq!(controls.opponent_model, OpponentModel::Ranker,
                   "the 1-ply ranker, called from outside the tree");
    }

    /// The whole correctness claim of `Minimax` in one assertion: values are
    /// kept in the ROOT SEAT's frame, so an opponent node must prefer the move
    /// that makes that value SMALLER. Getting this backwards would build a
    /// search that helps its opponent -- which is exactly the max-max defect
    /// Duel shipped for months before measuring it.
    #[test]
    fn an_opponent_node_minimises_the_root_seats_value() {
        let observation = an_observation_whose_moves_need_reordering();
        let mut node = Node::new(&observation);
        assert!(node.edges.len() > 2, "fixture needs a real choice");
        // Equal visits so the exploration term is identical across edges and
        // only the mean can decide.
        node.visits = 30;
        for (index, edge) in node.edges.iter_mut().enumerate() {
            edge.visits = 10;
            edge.sum = 10.0 * (index as f64 / 10.0);
        }
        let best_for_us = node.edges.len() - 1;
        assert_eq!(node.select(false), best_for_us, "our seat takes the highest value");
        assert_eq!(node.select(true), 0, "the opponent takes the lowest");
    }

    /// Minimax must actually BUILD the opponent's half of the tree, and the two
    /// seats' keys must not collide -- an observation embeds its own seat, so
    /// they cannot, and this pins that rather than trusting it.
    #[test]
    fn minimax_gives_the_opponent_its_own_nodes() {
        let (state, _) = State::new(22, [1, 2, 1]);
        // Enough simulations to get PAST our own turn: an Orbit turn is several
        // decisions by the same seat, so a small tree never reaches the
        // opponent at all and the two models are trivially identical.
        let config = Config { simulations: 512, max_depth: 64, budget_ms: 60000 };
        // COHERENT, because minimax is meaningless without a tree: under
        // per-simulation determinization every opponent node is fresh, so the
        // descent breaks at the first one and the opponent half is never
        // revisited. The two fixes are complementary, not independent.
        let coherent = Controls { determinization_period: usize::MAX, ..Controls::default() };
        let ranker = choose_with(&state, 0, 33, config, None, coherent).unwrap();
        let minimax = choose_with(&state, 0, 33, config, None,
                                  Controls { opponent_model: OpponentModel::Minimax,
                                             ..coherent }).unwrap();
        // Node TOTALS cannot show this: expanding an opponent node ends that
        // simulation's descent, so it trades against nodes on our own side and
        // the totals can move either way. Count the opponent's nodes directly.
        assert_eq!(ranker["opponent_nodes"], json!(0),
                   "the ranker never puts the opponent in the tree");
        assert!(minimax["opponent_nodes"].as_u64().unwrap() > 0,
                "minimax built no opponent nodes at all");
        assert_ne!(ranker["nodes"], minimax["nodes"], "the trees must differ in shape");
        assert_eq!(minimax["simulations"], json!(512), "same simulation budget");
        // Seat 0 and seat 1 observe different things, so their node keys differ.
        assert_ne!(state.observation(0).to_string(), state.observation(1).to_string());
    }

    /// What ships is stated separately from what reproduces. If these two ever
    /// coincide it should be because someone decided so, not because a default
    /// drifted: `Default` is load-bearing for every past campaign number.
    #[test]
    fn serving_is_coherent_and_default_is_not() {
        assert_eq!(Controls::serving().determinization_period, usize::MAX);
        assert_eq!(Controls::default().determinization_period, 1);
        // Everything else about the shipped search is the historical search.
        let serving = Controls::serving();
        let historical = Controls::default();
        assert_eq!(serving.model_stride, historical.model_stride);
        assert_eq!(serving.model_weight, historical.model_weight);
        assert_eq!(serving.model_temperature, historical.model_temperature);
        assert_eq!(serving.leaf, historical.leaf);
        assert_eq!(serving.policy_prior_weight, historical.policy_prior_weight);
    }

    /// A real observation with its legal moves deliberately REVERSED.
    ///
    /// `State::observation` sorts `legal_moves` with `serde_json::to_string`
    /// (lib.rs), which is the very key `Node` sorts by -- so for every
    /// observation the search actually sees, the permutation is the identity
    /// and a slot-versus-move bug is invisible. The first version of the test
    /// below used the opening position and PASSED with the mapping deliberately
    /// broken.
    ///
    /// That makes the reconciliation untestable on real data and worth keeping
    /// anyway: it is what holds the contract ("logits in the observation's
    /// order") if any caller ever hands the node an unsorted observation, and
    /// it costs one index. So the order is inverted here on purpose, and the
    /// inversion is asserted rather than assumed.
    fn an_observation_whose_moves_need_reordering() -> Value {
        let (state, _) = State::new(22, [1, 2, 1]);
        let mut observation = state.observation(0);
        let mut legal = observation["legal_moves"].as_array().unwrap().clone();
        assert!(legal.len() > 2, "fixture needs a real choice");
        legal.reverse();
        let keys: Vec<String> = legal.iter().map(|m| m.to_string()).collect();
        let mut sorted = keys.clone();
        sorted.sort();
        assert_ne!(keys, sorted, "the fixture must actually need reordering");
        observation["legal_moves"] = Value::Array(legal);
        observation
    }

    /// The learned prior arrives in the OBSERVATION's move order; the tree
    /// works in sorted order. This is the gather that fails silently -- a
    /// wrong mapping primes one move's search with another move's prior and
    /// reads downstream as a policy head that learned nothing.
    #[test]
    fn a_learned_prior_follows_the_move_not_the_slot() {
        let observation = an_observation_whose_moves_need_reordering();
        let legal = observation["legal_moves"].as_array().unwrap().clone();
        assert!(legal.len() > 2, "fixture needs a real choice");
        for target in [0usize, legal.len() / 2, legal.len() - 1] {
            let mut logits = vec![0.0f32; legal.len()];
            logits[target] = 20.0;
            let node = Node::new_with_prior(&observation, Some(&logits), 1.0);
            let best = (0..node.edges.len())
                .max_by(|&a, &b| node.edges[a].prior.total_cmp(&node.edges[b].prior))
                .unwrap();
            assert_eq!(node.moves[best], legal[target],
                       "the peak followed the slot rather than the move");
        }
    }

    /// Zero weight must be the historical prior to the BIT, even when logits
    /// are supplied, or no past campaign number reproduces.
    #[test]
    fn a_zero_weight_policy_prior_is_the_historical_prior() {
        let observation = an_observation_whose_moves_need_reordering();
        let count = observation["legal_moves"].as_array().unwrap().len();
        let logits: Vec<f32> = (0..count).map(|i| i as f32 * 3.0).collect();
        let plain = Node::new(&observation);
        let zero = Node::new_with_prior(&observation, Some(&logits), 0.0);
        assert_eq!(plain.moves, zero.moves);
        for (a, b) in plain.edges.iter().zip(&zero.edges) {
            assert_eq!(a.prior.to_bits(), b.prior.to_bits());
        }
    }

    /// A prior that does not sum to one is not a prior; PUCT would silently
    /// rescale exploration with it.
    #[test]
    fn every_blend_is_still_a_distribution() {
        let observation = an_observation_whose_moves_need_reordering();
        let count = observation["legal_moves"].as_array().unwrap().len();
        let logits: Vec<f32> = (0..count).map(|i| (i % 5) as f32).collect();
        for weight in [0.0, 0.25, 0.5, 1.0] {
            let node = Node::new_with_prior(&observation, Some(&logits), weight);
            let total: f64 = node.edges.iter().map(|e| e.prior).sum();
            assert!((total - 1.0).abs() < 1e-9, "weight {weight} summed to {total}");
            assert!(node.edges.iter().all(|e| e.prior > 0.0), "no move may be unreachable");
        }
    }

    /// Asking for a learned prior without a head must FAIL, never fall back to
    /// the hand-written prior: a silent fallback is a measurement that reports
    /// the policy head doing nothing when it was never consulted.
    #[test]
    fn a_policy_prior_without_a_policy_model_is_refused() {
        let (state, _) = State::new(22, [1, 2, 1]);
        let config = Config { simulations: 8, max_depth: 8, budget_ms: 5000 };
        let controls = Controls { policy_prior_weight: 0.5, ..Controls::default() };
        assert!(choose_with(&state, 0, 33, config, None, controls).is_err());
    }

    /// The mechanism behind the 2026-09-11 coherent result, asserted rather than
    /// described: resampling the hidden world every simulation makes node keys
    /// unique, so the tree is rebuilt instead of reused. Holding one
    /// determinization for the call must therefore produce FEWER nodes for the
    /// same simulation count -- the same work, shared.
    #[test]
    fn coherent_determinization_reuses_the_tree() {
        let (state, _) = State::new(22, [1, 2, 1]);
        let config = Config { simulations: 192, max_depth: 96, budget_ms: 600_000 };
        let per_sim = choose_with(&state, 0, 33, config, None, Controls::default()).unwrap();
        let coherent = choose_with(&state, 0, 33, config, None, Controls {
            determinization_period: usize::MAX,
            ..Controls::default()
        })
        .unwrap();
        let nodes = |v: &Value| v["nodes"].as_u64().unwrap();
        assert_eq!(per_sim["simulations"], coherent["simulations"]);
        assert!(
            nodes(&coherent) < nodes(&per_sim),
            "coherent {} should reuse more of the tree than per-sim {}",
            nodes(&coherent),
            nodes(&per_sim)
        );
        assert_eq!(coherent["determinization_period"], json!(usize::MAX));
    }

    /// The leaf the Rust port shipped until 2026-09-11 is retained only as a
    /// control, and it is a strict subset of the reference: capture progress
    /// alone. Pin the difference so neither can be quietly swapped for the other.
    #[test]
    fn the_control_leaf_is_blind_where_the_reference_is_not() {
        let (state, _) = State::new(22, [1, 2, 1]);
        let observation = state.observation(0);
        let reference = state_value(&observation);
        let control = capture_progress_only(&observation);
        assert_eq!(control, 0.0, "no captures yet, so the old leaf sees nothing");
        assert!(reference != 0.0, "the reference reads influence, economy and tempo");
    }

    /// Both caches are exact, so the cached and uncached searches must agree
    /// BIT FOR BIT at every determinization period -- including the coherent
    /// one, which is the only regime where the opponent cache actually hits.
    #[test]
    fn caches_are_exact_under_every_determinization_regime() {
        let (state, _) = State::new(22, [1, 2, 1]);
        let config = Config { simulations: 96, max_depth: 12, budget_ms: 600_000 };
        for period in [1usize, 8, usize::MAX] {
            let controls = Controls { determinization_period: period, ..Controls::default() };
            let mut cached =
                choose_cached_options(&state, 0, 33, config, None, controls, true).unwrap();
            let mut plain =
                choose_cached_options(&state, 0, 33, config, None, controls, false).unwrap();
            for value in [&mut cached, &mut plain] {
                let object = value.as_object_mut().unwrap();
                object.remove("elapsed_ms");
                object.remove("value_cache_hits");
                object.remove("opponent_cache_hits");
            }
            assert_eq!(cached, plain, "caching changed the search at period {period}");
        }
    }

    /// ...and the opponent cache must actually DO something under coherence,
    /// or it is 43% of the search time left on the table with extra bookkeeping.
    #[test]
    fn the_opponent_cache_hits_once_the_tree_is_coherent() {
        let (state, _) = State::new(22, [1, 2, 1]);
        let config = Config { simulations: 192, max_depth: 96, budget_ms: 600_000 };
        let hits = |period: usize| {
            let controls = Controls { determinization_period: period, ..Controls::default() };
            choose_with(&state, 0, 33, config, None, controls).unwrap()["opponent_cache_hits"]
                .as_u64()
                .unwrap()
        };
        let coherent = hits(usize::MAX);
        assert!(coherent > 0, "coherent search reused no opponent reply");
        assert!(
            coherent > hits(1),
            "coherent {} should reuse more opponent replies than per-sim {}",
            coherent,
            hits(1)
        );
    }

    #[test]
    fn exact_leaf_cache_preserves_fixed_simulation_statistics() {
        let (state, _) = State::new(22, [1, 2, 1]);
        let config = Config {
            simulations: 128,
            max_depth: 8,
            budget_ms: 60000,
        };
        let cached = choose_cached(&state, 0, 33, config, None, true).unwrap();
        let reference = choose_cached(&state, 0, 33, config, None, false).unwrap();
        assert_eq!(cached["stats"], reference["stats"]);
        assert_eq!(cached["move"], reference["move"]);
        assert_eq!(cached["simulations"], reference["simulations"]);
        // Depth zero deliberately revisits one leaf, exercising the hit path
        // independently of whether this shuffled game produces transpositions.
        let repeated = choose_cached(
            &state,
            0,
            33,
            Config {
                max_depth: 0,
                ..config
            },
            None,
            true,
        )
        .unwrap();
        assert_eq!(repeated["value_cache_hits"], 127);
    }
    #[test]
    fn unseen_world_changes_cannot_change_fixed_sim_search() {
        let (a, _) = State::new(22, [1, 2, 1]);
        let mut b = a.clone();
        let card = b.agent_deck.pop().unwrap();
        let old = std::mem::replace(&mut b.players[1].hand[0], card);
        b.agent_deck.push(old);
        b.agent_deck.reverse();
        b.bonus_deck.reverse();
        let config = Config {
            simulations: 24,
            max_depth: 8,
            budget_ms: 60000,
        };
        // The guarantee must hold under EVERY determinization regime, not just
        // the historical one. Coherent search commits to a single sampled world
        // for the whole call, which is the change most likely to let privileged
        // state reach a leaf if `sample` were ever bypassed.
        for period in [1usize, 8, usize::MAX] {
            let controls = Controls { determinization_period: period, ..Controls::default() };
            let mut x = choose_with(&a, 0, 33, config, None, controls).unwrap();
            let mut y = choose_with(&b, 0, 33, config, None, controls).unwrap();
            x.as_object_mut().unwrap().remove("elapsed_ms");
            y.as_object_mut().unwrap().remove("elapsed_ms");
            assert_eq!(x, y, "hidden state reached the search at period {period}");
            assert!(a.legal_moves(0).contains(&x["move"]));
        }
    }
    #[test]
    fn immediate_alternate_win_is_resolved_by_engine_not_leaf() {
        let (mut state, mut chance) = State::new(27, [1, 1, 1]);
        state
            .apply(0, &json!({"action":"mulligan","card_ids":[]}), &mut chance)
            .unwrap();
        state
            .apply(1, &json!({"action":"mulligan","card_ids":[]}), &mut chance)
            .unwrap();
        let seat = state.actor().unwrap();
        let card = &crate::rules().cards[&state.players[seat].hand[0]];
        let planet = crate::PLANETS
            .iter()
            .position(|p| *p == card.planet)
            .unwrap();
        state.players[seat].credits = 100;
        state.players[seat].captured = vec![planet, planet];
        state.influence[planet] = Some(if seat == 0 { 3 } else { -3 });
        let result = choose(
            &state,
            seat,
            7,
            Config {
                simulations: 64,
                max_depth: 12,
                budget_ms: 60000,
            },
            None,
        )
        .unwrap();
        state.apply(seat, &result["move"], &mut chance).unwrap();
        assert_eq!(state.winner, Some(seat));
    }
    #[test]
    fn search_does_not_mutate_live_template_after_real_play() {
        let (mut state, mut chance) = State::new(81, [2, 1, 2]);
        for _ in 0..24 {
            let Some(seat) = state.actor() else { break };
            let moves = state.legal_moves(seat);
            let mv = moves[chance.index(moves.len())].clone();
            state.apply(seat, &mv, &mut chance).unwrap();
        }
        let seat = state.actor().unwrap();
        let before = state.clone();
        let result = choose(
            &state,
            seat,
            9,
            Config {
                simulations: 12,
                max_depth: 12,
                budget_ms: 60000,
            },
            None,
        )
        .unwrap();
        assert_eq!(state, before);
        assert!(state.legal_moves(seat).contains(&result["move"]));
    }
}
