//! Portable float inference reference, sharing the Python export contract.
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::cell::RefCell;
use std::sync::atomic::{AtomicUsize, Ordering};
use crate::tensors::{Encoder, TensorRow};

// Position features are deterministic functions of the integer sequence
// position and nesting depth.  Orbit observations use small bounded indices
// (cards, moves, players and columns), so caching the common range removes a
// pair of matrix multiplies from every token on every leaf.  Inputs outside
// this range still use the exact old path below; the cache is an optimization,
// never a truncation of the feature contract.
const POSITION_CACHE_MAX: usize = 1024;
const POSITION_CACHE_DEPTH: usize = 8;
static NEXT_MODEL_TAG: AtomicUsize = AtomicUsize::new(1);

pub struct Model {
    pub vocabulary: Value,
    width: usize,
    heads: usize,
    layers: usize,
    weights: BTreeMap<String, Vec<f32>>,
    indexed: bool,
    has_policy: bool,
    position_cache: Vec<f32>,
    encoder: Encoder,
    cache_tag: usize,
}

/// Cache key for the exact result of the token pooling affine/GELU block.
/// Entity identity is intentionally absent: pooling is applied per token and
/// the same semantic row can be added to any entity.  The f32 bit pattern is
/// used so the cache never conflates distinct numeric observations.
#[derive(Clone, Debug, Hash, PartialEq, Eq)]
struct PoolKey {
    group: usize,
    kind: usize,
    path: usize,
    positions: Vec<usize>,
    number: u32,
    role: usize,
    card: usize,
    category: usize,
}

impl PoolKey {
    fn from_row(row: &TensorRow) -> Self {
        Self {
            group: row.group,
            kind: row.kind,
            path: row.path,
            positions: row.positions.clone(),
            number: row.number.to_bits(),
            role: row.role,
            card: row.card,
            category: row.category,
        }
    }
}

/// Reusable workspace for the variable-length Orbit forward.
///
/// Duel can use compile-time token dimensions; Orbit's semantic encoder has a
/// dynamic number of rows/entities.  Keeping the outer vectors reusable gives
/// us the same allocation property without imposing a truncation or a hidden
/// maximum on the observation contract.  The first call on a thread grows the
/// buffers; subsequent leaves reuse them.
struct LogitScratch {
    x: Vec<Vec<f32>>,
    qkv: Vec<Vec<f32>>,
    attended: Vec<Vec<f32>>,
    counts: Vec<usize>,
    scores: Vec<f32>,
    token: Vec<f32>,
    norm: Vec<f32>,
    out: Vec<f32>,
    hidden: Vec<f32>,
    active_entities: usize,
    model_id: usize,
    pool_cache: HashMap<PoolKey, Vec<f32>>,
}

impl LogitScratch {
    fn new() -> Self {
        Self {
            x: Vec::new(),
            qkv: Vec::new(),
            attended: Vec::new(),
            counts: Vec::new(),
            scores: Vec::new(),
            token: Vec::new(),
            norm: Vec::new(),
            out: Vec::new(),
            hidden: Vec::new(),
            active_entities: 0,
            model_id: 0,
            pool_cache: HashMap::new(),
        }
    }

    fn ensure(&mut self, entities: usize, width: usize, feedforward: usize) {
        while self.x.len() < entities {
            self.x.push(vec![0.0; width]);
        }
        while self.qkv.len() < entities {
            self.qkv.push(vec![0.0; width * 3]);
        }
        while self.attended.len() < entities {
            self.attended.push(vec![0.0; width]);
        }
        self.counts.resize(entities, 0);
        self.scores.resize(entities, 0.0);
        self.token.resize(width, 0.0);
        self.norm.resize(width, 0.0);
        self.out.resize(width, 0.0);
        self.hidden.resize(feedforward, 0.0);
    }
}

thread_local! {
    static LOGIT_SCRATCH: RefCell<LogitScratch> = RefCell::new(LogitScratch::new());
}

#[inline]
fn affine_into(weight: &[f32], bias: &[f32], x: &[f32], out: &mut [f32]) {
    for (i, row) in weight.chunks_exact(x.len()).enumerate() {
        out[i] = dot(row, x) + if bias.is_empty() { 0.0 } else { bias[i] };
    }
}

#[inline]
fn norm_into(weight: &[f32], bias: &[f32], x: &[f32], out: &mut [f32]) {
    let mean = x.iter().sum::<f32>() / x.len() as f32;
    let variance = x
        .iter()
        .map(|v| (v - mean) * (v - mean))
        .sum::<f32>()
        / x.len() as f32;
    let inv = (variance + 1e-5).sqrt().recip();
    for (i, v) in x.iter().enumerate() {
        out[i] = (v - mean) * inv * weight[i] + bias[i];
    }
}

impl Model {
    /// Load a model for a SEARCH. Fails closed on a policy head.
    ///
    /// The search still primes PUCT from the hand-written `action_score`, so a
    /// policy model loaded here would train a prior that is then silently
    /// ignored -- precisely the difference that reads as a failed training run
    /// rather than as a wiring bug. `load_any` is the deliberate opt-in for
    /// paths that evaluate the head instead of searching with it; delete this
    /// wrapper once `Node::new` consumes the prior.
    pub fn load(v: &Value) -> Result<Self, String> {
        let model = Self::load_any(v)?;
        if model.has_policy {
            return Err("Policy-head models need the native policy prior; not implemented".into());
        }
        Ok(model)
    }

    /// Whether this artifact carries a trained policy head.
    pub fn has_policy(&self) -> bool {
        self.has_policy
    }

    pub fn load_any(v: &Value) -> Result<Self, String> {
        // v4 adds an OPTIONAL policy head. A v4 artifact without one is
        // structurally identical to v3, so it loads unchanged.
        if !matches!(
            v["version"].as_str(),
            Some("orbit-attention-value-v2" | "orbit-attention-value-v3" | "orbit-attention-value-v4")
        ) {
            return Err("Model version mismatch".into());
        }
        let encoder = Encoder::new(&v["vocabulary"])?;
        let dim = |key: &str| -> Result<usize, String> {
            let n = v["config"][key].as_u64().ok_or("Missing model dimension")? as usize;
            if n == 0 || n > 4096 { return Err("Invalid model dimension".into()); }
            Ok(n)
        };
        let (d, h, l, ff) = (dim("width")?, dim("heads")?, dim("layers")?, dim("feedforward")?);
        if d % h != 0 || l > 16 { return Err("Invalid attention shape".into()); }
        let mut shapes: BTreeMap<String, Vec<usize>> = BTreeMap::new();
        let indexed=v["config"]["indexed_features"]==true;
        if indexed {
            shapes.insert("embeddings.card.weight".into(),vec![crate::rules().cards.len()+1,d]);
            shapes.insert("embeddings.role.weight".into(),vec![4,d]);
        }
        for (key, n) in [("group", 13), ("kind", 7),
            ("path", v["vocabulary"]["paths"].as_array().unwrap().len()+1),
            ("category", v["vocabulary"]["categories"].as_array().unwrap().len()+1)] {
            shapes.insert(format!("embeddings.{key}.weight"), vec![n,d]);
        }
        for (key, shape) in [("number.weight",vec![d,1]),("position.0.weight",vec![d,2]),
            ("position.0.bias",vec![d]),("position.2.weight",vec![d,d]),("position.2.bias",vec![d]),
            ("summary",vec![1,1,d]),("pool.0.weight",vec![d,d]),("pool.0.bias",vec![d]),
            ("pool_count.weight",vec![d,1]),("norm.weight",vec![d]),("norm.bias",vec![d]),
            ("head.weight",vec![1,d]),("head.bias",vec![1])] { shapes.insert(key.into(),shape); }
        let has_policy = v["config"]["policy_head"] == true;
        if has_policy {
            shapes.insert("policy.weight".into(), vec![1, d]);
            shapes.insert("policy.bias".into(), vec![1]);
        }
        for i in 0..l {
            for (key,shape) in [("self_attn.in_proj_weight",vec![3*d,d]),("self_attn.in_proj_bias",vec![3*d]),
                ("self_attn.out_proj.weight",vec![d,d]),("self_attn.out_proj.bias",vec![d]),
                ("linear1.weight",vec![ff,d]),("linear1.bias",vec![ff]),
                ("linear2.weight",vec![d,ff]),("linear2.bias",vec![d]),
                ("norm1.weight",vec![d]),("norm1.bias",vec![d]),("norm2.weight",vec![d]),("norm2.bias",vec![d])] {
                shapes.insert(format!("blocks.{i}.{key}"),shape);
            }
        }
        let source = v["weights"].as_object().ok_or("Missing weights")?;
        if source.len() != shapes.len() { return Err("Unexpected weight keys".into()); }
        let mut weights = BTreeMap::new();
        for (key,shape) in shapes {
            let tensor = source.get(&key).ok_or(format!("Missing weight {key}"))?;
            if tensor["shape"] != serde_json::json!(shape) { return Err(format!("Weight shape: {key}")); }
            let data: Vec<f32> = tensor["data"].as_array().ok_or("Missing weight data")?.iter()
                .map(|x| x.as_f64().map(|n| n as f32).filter(|x| x.is_finite()).ok_or("Non-finite weight"))
                .collect::<Result<_,_>>()?;
            if data.len() != shape.iter().product::<usize>() { return Err(format!("Weight length: {key}")); }
            weights.insert(key,data);
        }
        let mut model=Self{vocabulary:v["vocabulary"].clone(),width:d,heads:h,layers:l,weights,indexed,
            has_policy, position_cache:Vec::new(), encoder,
            cache_tag:NEXT_MODEL_TAG.fetch_add(1, Ordering::Relaxed)};
        // The position MLP is independent of the observation.  Build it once
        // while loading instead of rebuilding it for every row of every leaf.
        model.position_cache=vec![0.0;POSITION_CACHE_MAX*POSITION_CACHE_DEPTH*d];
        for position in 0..POSITION_CACHE_MAX {
            for depth in 0..POSITION_CACHE_DEPTH {
                let mut value=model.linear("position.0",&[position as f32/32.0,depth as f32/8.0]);
                value.iter_mut().for_each(|n|*n=gelu(*n));
                let value=model.linear("position.2",&value);
                let start=(position*POSITION_CACHE_DEPTH+depth)*d;
                model.position_cache[start..start+d].copy_from_slice(&value);
            }
        }
        Ok(model)
    }
    fn linear(&self, key: &str, x: &[f32]) -> Vec<f32> {
        self.affine(&format!("{key}.weight"), &format!("{key}.bias"), x)
    }
    fn affine(&self, weight: &str, bias: &str, x: &[f32]) -> Vec<f32> {
        self.weights[weight].chunks_exact(x.len()).enumerate().map(|(i,row)| {
            dot(row,x) + self.weights.get(bias).map_or(0.0,|b| b[i])
        }).collect()
    }
    /// Evaluate one encoded observation using a thread-local reusable workspace.
    /// The arithmetic and traversal order mirrors the original allocating path;
    /// only buffer ownership and weight-key lookups move out of the inner loops.
    pub fn logit(&self, rows: &Value) -> Result<f32,String> {
        let rows = crate::tensors::decode_rows(rows)?;
        self.logit_typed(&rows)
    }

    /// Convert semantic tokens with the model's validated, cached vocabulary.
    pub fn encode_tokens(&self, tokens: &Value) -> Result<Vec<TensorRow>, String> {
        self.encoder.encode_typed(tokens)
    }

    /// Tokens to rows, plus the `legal move index -> entity id` map the policy
    /// head is gathered at. Both come from one pass so they cannot disagree.
    pub fn encode_tokens_with_actions(&self, tokens: &Value)
        -> Result<(Vec<TensorRow>, Vec<usize>), String> {
        self.encoder.encode_with_actions(tokens)
    }

    /// Evaluate typed rows without a JSON allocation on the search leaf path.
    pub fn logit_typed(&self, rows: &[TensorRow]) -> Result<f32,String> {
        if rows.is_empty() { return Err("Empty position".into()); }
        LOGIT_SCRATCH.with(|cell| {
            let mut scratch = cell.borrow_mut();
            let mut unused = Vec::new();
            self.logit_into(rows, &mut scratch, &[], &mut unused)
        })
    }

    /// The value logit AND one policy logit per legal move, in the
    /// observation's own move order.
    ///
    /// `actions` comes from `Encoder::encode_with_actions`; the two must be
    /// produced from the SAME tokens or the logits line up with the wrong
    /// moves, which trains and serves a quietly misaligned prior.
    pub fn value_and_policy(&self, rows: &[TensorRow], actions: &[usize])
        -> Result<(f32, Vec<f32>), String> {
        if rows.is_empty() { return Err("Empty position".into()); }
        if !self.has_policy { return Err("Model has no policy head".into()); }
        if actions.is_empty() { return Err("No legal moves to score".into()); }
        LOGIT_SCRATCH.with(|cell| {
            let mut scratch = cell.borrow_mut();
            let mut policy = Vec::with_capacity(actions.len());
            let value = self.logit_into(rows, &mut scratch, actions, &mut policy)?;
            Ok((value, policy))
        })
    }

    fn logit_into(&self, rows: &[TensorRow], scratch: &mut LogitScratch,
                  actions: &[usize], policy: &mut Vec<f32>) -> Result<f32,String> {
        let d = self.width;
        // A scratch workspace is shared by all Model values on one worker
        // thread.  Pooled vectors depend on weights, so invalidate them when
        // the model changes (the pointer is stable for the lifetime of a
        // loaded model and is never exposed to the wire).
        let model_id = self.cache_tag;
        if scratch.model_id != model_id {
            scratch.pool_cache.clear();
            scratch.model_id = model_id;
        }
        let ff = self
            .weights["blocks.0.linear1.weight"]
            .len()
            .checked_div(d)
            .ok_or("Invalid feedforward shape")?;
        // A thread-local workspace outlives this forward.  Clear every row
        // used by the previous observation before accumulating the new one;
        // otherwise a shorter next observation would inherit stale entities.
        let previous_entities = scratch.active_entities.max(1);
        scratch.ensure(previous_entities, d, ff);
        let previous_entities = previous_entities.min(scratch.x.len());
        for row in &mut scratch.x[..previous_entities] {
            row[..d].fill(0.0);
        }
        scratch.counts[..previous_entities].fill(0);
        scratch.x[0].copy_from_slice(&self.weights["summary"]);
        let mut entity_count = 1usize;
        scratch.counts[0] = 0;
        let group_embedding = self.weights["embeddings.group.weight"].as_slice();
        let kind_embedding = self.weights["embeddings.kind.weight"].as_slice();
        let path_embedding = self.weights["embeddings.path.weight"].as_slice();
        let category_embedding = self.weights["embeddings.category.weight"].as_slice();
        let mut embedding_weights: [&[f32]; 6] = [
            group_embedding,
            kind_embedding,
            path_embedding,
            category_embedding,
            &[],
            &[],
        ];
        let embedding_count = if self.indexed {
            embedding_weights[4] = self.weights["embeddings.card.weight"].as_slice();
            embedding_weights[5] = self.weights["embeddings.role.weight"].as_slice();
            6
        } else {
            4
        };
        let numeric = self.weights["number.weight"].as_slice();
        let pool_weight = self.weights["pool.0.weight"].as_slice();
        let pool_bias = self.weights["pool.0.bias"].as_slice();

        // Position transforms depend only on (index, nesting depth) and these
        // fixed weights. Reuse them across fields without changing summation.
        for row in rows {
            scratch.token[..d].fill(0.0);
            for index in 0..embedding_count {
                let id = match index {
                    0 => row.group,
                    1 => row.kind,
                    2 => row.path,
                    3 => row.category,
                    4 => row.card,
                    5 => row.role,
                    _ => return Err("Invalid embedding index".into()),
                };
                let start = id.checked_mul(d).ok_or("Embedding overflow")?;
                let end = start.checked_add(d).ok_or("Embedding overflow")?;
                let values = embedding_weights[index]
                    .get(start..end)
                    .ok_or("Embedding out of range")?;
                for i in 0..d {
                    scratch.token[i] += values[i];
                }
            }
            let n = row.number;
            if !n.is_finite() {
                return Err("Non-finite input".into());
            }
            for i in 0..d {
                scratch.token[i] += n * numeric[i];
            }
            for (depth, &p) in row.positions.iter().enumerate() {
                if p < POSITION_CACHE_MAX && depth < POSITION_CACHE_DEPTH {
                    let start = (p * POSITION_CACHE_DEPTH + depth) * d;
                    for i in 0..d {
                        scratch.token[i] += self.position_cache[start + i];
                    }
                } else {
                    // Preserve the previous unbounded behavior for any future
                    // observation whose positions exceed the common cache.
                    let mut value =
                        self.linear("position.0", &[p as f32 / 32.0, depth as f32 / 8.0]);
                    value.iter_mut().for_each(|n| *n = gelu(*n));
                    let value = self.linear("position.2", &value);
                    for i in 0..d {
                        scratch.token[i] += value[i];
                    }
                }
            }
            let entity = row.entity;
            if entity == 0 || entity > rows.len() {
                return Err("Invalid entity".into());
            }
            if entity + 1 > entity_count {
                entity_count = entity + 1;
                scratch.ensure(entity_count, d, ff);
            }
            let entity_row = &mut scratch.x[entity];
            let key = PoolKey::from_row(row);
            if let Some(pooled) = scratch.pool_cache.get(&key) {
                for i in 0..d {
                    entity_row[i] += pooled[i];
                }
            } else {
                affine_into(pool_weight, pool_bias, &scratch.token[..d], &mut scratch.out[..d]);
                for i in 0..d {
                    scratch.out[i] = gelu(scratch.out[i]);
                    entity_row[i] += scratch.out[i];
                }
                // Bound the per-thread cache.  Clearing at the bound keeps
                // memory predictable while preserving exact arithmetic for
                // every hit; a future miss simply recomputes the same row.
                if scratch.pool_cache.len() >= 16384 {
                    scratch.pool_cache.clear();
                }
                scratch.pool_cache.insert(key, scratch.out[..d].to_vec());
            }
            scratch.counts[entity] += 1;
        }
        for entity in 1..entity_count {
            if scratch.counts[entity] == 0 {
                return Err("Noncontiguous entities".into());
            }
            let count = scratch.counts[entity] as f32;
            for i in 0..d {
                scratch.x[entity][i] = scratch.x[entity][i] / count.sqrt()
                    + self.weights["pool_count.weight"][i] * count / 32.0;
            }
        }

        for layer in 0..self.layers {
            let prefix = format!("blocks.{layer}");
            let qkv_weight = self.weights[&format!("{prefix}.self_attn.in_proj_weight")].as_slice();
            let qkv_bias = self.weights[&format!("{prefix}.self_attn.in_proj_bias")].as_slice();
            let norm1_weight = self.weights[&format!("{prefix}.norm1.weight")].as_slice();
            let norm1_bias = self.weights[&format!("{prefix}.norm1.bias")].as_slice();
            for entity in 0..entity_count {
                norm_into(
                    norm1_weight,
                    norm1_bias,
                    &scratch.x[entity][..d],
                    &mut scratch.norm[..d],
                );
                affine_into(
                    qkv_weight,
                    qkv_bias,
                    &scratch.norm[..d],
                    &mut scratch.qkv[entity][..3 * d],
                );
            }
            for entity in 0..entity_count {
                scratch.attended[entity][..d].fill(0.0);
            }
            let hd = d / self.heads;
            let scale = 1.0 / (hd as f32).sqrt();
            for i in 0..entity_count {
                for head in 0..self.heads {
                    let off = head * hd;
                    let mut max = f32::NEG_INFINITY;
                    for j in 0..entity_count {
                        let mut score = 0.0;
                        for k in 0..hd {
                            score += scratch.qkv[i][off + k]
                                * scratch.qkv[j][d + off + k];
                        }
                        let score = score * scale;
                        scratch.scores[j] = score;
                        if score > max {
                            max = score;
                        }
                    }
                    for j in 0..entity_count {
                        scratch.scores[j] = (scratch.scores[j] - max).exp();
                    }
                    let sum = scratch.scores[..entity_count].iter().sum::<f32>();
                    for j in 0..entity_count {
                        let score = scratch.scores[j];
                        for k in 0..hd {
                            scratch.attended[i][off + k] += score / sum
                                * scratch.qkv[j][2 * d + off + k];
                        }
                    }
                }
            }

            let out_weight = self.weights[&format!("{prefix}.self_attn.out_proj.weight")].as_slice();
            let out_bias = self.weights[&format!("{prefix}.self_attn.out_proj.bias")].as_slice();
            let f1_weight = self.weights[&format!("{prefix}.linear1.weight")].as_slice();
            let f1_bias = self.weights[&format!("{prefix}.linear1.bias")].as_slice();
            let f2_weight = self.weights[&format!("{prefix}.linear2.weight")].as_slice();
            let f2_bias = self.weights[&format!("{prefix}.linear2.bias")].as_slice();
            let norm2_weight = self.weights[&format!("{prefix}.norm2.weight")].as_slice();
            let norm2_bias = self.weights[&format!("{prefix}.norm2.bias")].as_slice();
            for entity in 0..entity_count {
                affine_into(
                    out_weight,
                    out_bias,
                    &scratch.attended[entity][..d],
                    &mut scratch.out[..d],
                );
                for i in 0..d {
                    scratch.x[entity][i] += scratch.out[i];
                }
                norm_into(
                    norm2_weight,
                    norm2_bias,
                    &scratch.x[entity][..d],
                    &mut scratch.norm[..d],
                );
                affine_into(
                    f1_weight,
                    f1_bias,
                    &scratch.norm[..d],
                    &mut scratch.hidden[..ff],
                );
                scratch.hidden[..ff]
                    .iter_mut()
                    .for_each(|value| *value = gelu(*value));
                affine_into(
                    f2_weight,
                    f2_bias,
                    &scratch.hidden[..ff],
                    &mut scratch.out[..d],
                );
                for i in 0..d {
                    scratch.x[entity][i] += scratch.out[i];
                }
            }
        }

        let head_weight = self.weights["head.weight"].as_slice();
        let head_bias = self.weights["head.bias"].as_slice();
        let norm_weight = self.weights["norm.weight"].as_slice();
        let norm_bias = self.weights["norm.bias"].as_slice();
        norm_into(
            norm_weight,
            norm_bias,
            &scratch.x[0][..d],
            &mut scratch.norm[..d],
        );
        affine_into(
            head_weight,
            head_bias,
            &scratch.norm[..d],
            &mut scratch.out[..1],
        );
        let result = scratch.out[0];
        if !result.is_finite() {
            return Err("Non-finite model result".into());
        }
        if !actions.is_empty() {
            // Entity `e` sits at row `e` of the post-block workspace, exactly as
            // the Python head gathers at `action_entity`: `pooled` is scatter
            // indexed by entity id and the summary token occupies row 0.
            let policy_weight = self.weights.get("policy.weight")
                .ok_or("Model has no policy head")?.as_slice();
            let policy_bias = self.weights.get("policy.bias")
                .ok_or("Model has no policy head")?[0];
            policy.clear();
            for &entity in actions {
                if entity == 0 || entity >= entity_count {
                    return Err("Action entity is outside the encoded observation".into());
                }
                norm_into(norm_weight, norm_bias, &scratch.x[entity][..d],
                          &mut scratch.norm[..d]);
                let logit = dot(policy_weight, &scratch.norm[..d]) + policy_bias;
                if !logit.is_finite() {
                    return Err("Non-finite policy logit".into());
                }
                policy.push(logit);
            }
        }
        scratch.active_entities = entity_count;
        Ok(result)
    }
}

#[inline]
fn dot(a:&[f32],b:&[f32])->f32 {
    #[cfg(feature="chunked-dot")]
    {
        // Adapted from duel-core/attn.rs. This deliberately reassociates the
        // reduction; unlike memoization it requires numerical/strength gates.
        let mut lanes=[0.0f32;8];
        let mut ac=a.chunks_exact(8);let mut bc=b.chunks_exact(8);
        for (x,y) in ac.by_ref().zip(bc.by_ref()) {
            for i in 0..8 {lanes[i]+=x[i]*y[i];}
        }
        let mut sum=lanes.iter().sum::<f32>();
        for (x,y) in ac.remainder().iter().zip(bc.remainder()) {sum+=x*y;}
        sum
    }
    #[cfg(not(feature="chunked-dot"))]
    {a.iter().zip(b).map(|(x,y)|x*y).sum()}
}

fn gelu(x:f32) -> f32 {
    // Abramowitz-Stegun erf approximation; parity gate bounds accumulated error.
    let z = x / std::f32::consts::SQRT_2;
    let t = 1.0/(1.0+0.3275911*z.abs());
    let erf = 1.0 - (((((1.0614054*t-1.4531521)*t)+1.4214138)*t-0.28449672)*t+0.2548296)*t*(-z*z).exp();
    0.5*x*(1.0+erf.copysign(z))
}
