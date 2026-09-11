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
        let mut moves = obs["legal_moves"].as_array().unwrap().clone();
        moves.sort_by_key(|m| m.to_string());
        let scores: Vec<f64> = moves
            .iter()
            .map(|m| crate::serving::action_score(obs, m))
            .collect();
        let max = scores.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let weights: Vec<f64> = scores.iter().map(|s| ((s - max) / 4.0).exp()).collect();
        let sum = weights.iter().sum::<f64>();
        let edges = weights
            .iter()
            .map(|w| Edge {
                prior: 0.97 * w / sum + 0.03 / weights.len() as f64,
                ..Default::default()
            })
            .collect();
        Self {
            moves,
            edges,
            visits: 0,
        }
    }
    fn select(&self) -> usize {
        let mut best = 0;
        let mut score = f64::NEG_INFINITY;
        for (i, e) in self.edges.iter().enumerate() {
            let mean = if e.visits == 0 {
                0.0
            } else {
                e.sum / e.visits as f64
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
fn heuristic(obs: &Value) -> f64 {
    let me = obs["seat"].as_u64().unwrap() as usize;
    let progress = |seat: usize| {
        let captured = obs["players"][seat]["captured"].as_array().unwrap();
        let mut counts = [0usize; 5];
        for c in captured {
            counts[c.as_u64().unwrap() as usize] += 1;
        }
        (captured.len() as f64 / 5.0)
            .max(counts.iter().filter(|n| **n > 0).count() as f64 / 4.0)
            .max(*counts.iter().max().unwrap() as f64 / 3.0)
    };
    (progress(me) - progress(1 - me)).tanh()
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
    choose_cached_options(
        source,
        seat,
        seed,
        config,
        model,
        model_stride.max(1),
        model_weight.clamp(0.0, 1.0),
        model_temperature.max(0.1),
        true,
    )
}
fn choose_cached(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    cache_enabled: bool,
) -> Result<Value, String> {
    choose_cached_options(
        source,
        seat,
        seed,
        config,
        model,
        1,
        1.0,
        2.0,
        cache_enabled,
    )
}
fn choose_cached_options(
    source: &State,
    seat: usize,
    seed: u64,
    config: Config,
    model: Option<&Model>,
    model_stride: usize,
    model_weight: f64,
    model_temperature: f64,
    cache_enabled: bool,
) -> Result<Value, String> {
    if seat > 1 || source.actor() != Some(seat) {
        return Err("Not this seat's decision".into());
    }
    let started = crate::clock::Clock::start();
    let profiling = profile_enabled();
    let profile_started = profile_start(profiling);
    let mut profile = SearchProfile::default();
    let obs = source.observation(seat);
    let mut nodes: HashMap<(u64, String), Node> = HashMap::new();
    let root = (0, "root".to_owned());
    let node_started = profile_start(profiling);
    nodes.insert(root.clone(), Node::new(&obs));
    profile.node_ns += profile_elapsed(node_started);
    let mut rng = Chance::seeded(seed);
    let mut sims = 0;
    let mut evals = 0;
    // Exact observation keys: no hidden state, hash-only collisions, or
    // history-dependent estimates. Lifetime is one call with one fixed model.
    let mut values: HashMap<String, f64> = HashMap::new();
    let mut cache_hits = 0;
    for simulation in 0..config.simulations {
        if started.elapsed_ms() >= config.budget_ms as f64 {
            break;
        }
        let sample_started = profile_start(profiling);
        let mut world = sample(source, seat, &mut rng)?;
        profile.sample_ns += profile_elapsed(sample_started);
        let mut chance = Chance::seeded(rng.next());
        let mut path = Vec::new();
        let mut trace = 0u64;
        let mut leaf_observation: Option<Value> = None;
        for depth in 0..config.max_depth {
            let Some(actor) = world.actor() else { break };
            let actor_observation_started = profile_start(profiling);
            let actor_obs = world.observation(actor);
            profile.actor_observation_ns += profile_elapsed(actor_observation_started);
            let (mv, unvisited) = if actor == seat {
                let key = if depth == 0 {
                    root.clone()
                } else {
                    (trace, actor_obs.to_string())
                };
                let node_started = profile_start(profiling);
                let node = nodes
                    .entry(key.clone())
                    .or_insert_with(|| Node::new(&actor_obs));
                profile.node_ns += profile_elapsed(node_started);
                let action = node.select();
                let unvisited = node.edges[action].visits == 0;
                let mv = node.moves[action].clone();
                path.push((key, action));
                (mv, unvisited)
            } else {
                let moves = actor_obs["legal_moves"].as_array().unwrap();
                let opponent_started = profile_start(profiling);
                let selected = crate::serving::choose_move(
                    &actor_obs,
                    moves,
                    &Value::Null,
                    5000,
                    seed,
                );
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
            let evaluate_model = model.is_some() && simulation % model_stride == 0;
            let key = if cache_enabled {
                if model.is_some() && model_stride > 1 {
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
                    model_weight * learned + (1.0 - model_weight) * heuristic(&view)
                } else {
                    let heuristic_started = profile_start(profiling);
                    let value = heuristic(&view);
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
        "value_cache_hits":cache_hits,
        "elapsed_ms":started.elapsed_ms(),"stats":stats,"belief":"current-observation prior"});
    if profiling {
        result["profile"] = profile.as_value();
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
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
        let mut x = choose(&a, 0, 33, config, None).unwrap();
        let mut y = choose(&b, 0, 33, config, None).unwrap();
        x.as_object_mut().unwrap().remove("elapsed_ms");
        y.as_object_mut().unwrap().remove("elapsed_ms");
        assert_eq!(x, y);
        assert!(a.legal_moves(0).contains(&x["move"]));
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
