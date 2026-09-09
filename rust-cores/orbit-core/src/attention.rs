//! Portable float inference reference, sharing the Python export contract.
use serde_json::Value;
use std::collections::BTreeMap;

pub struct Model {
    pub vocabulary: Value,
    width: usize,
    heads: usize,
    layers: usize,
    weights: BTreeMap<String, Vec<f32>>,
    indexed: bool,
}

impl Model {
    pub fn load(v: &Value) -> Result<Self, String> {
        if v["version"] != "orbit-attention-value-v2" && v["version"] != "orbit-attention-value-v3" { return Err("Model version mismatch".into()); }
        crate::tensors::encode(&serde_json::json!({"vocabulary":v["vocabulary"], "tokens":[]}))?;
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
        Ok(Self{vocabulary:v["vocabulary"].clone(),width:d,heads:h,layers:l,weights,indexed})
    }
    fn linear(&self, key: &str, x: &[f32]) -> Vec<f32> {
        self.affine(&format!("{key}.weight"), &format!("{key}.bias"), x)
    }
    fn affine(&self, weight: &str, bias: &str, x: &[f32]) -> Vec<f32> {
        self.weights[weight].chunks_exact(x.len()).enumerate().map(|(i,row)| {
            dot(row,x) + self.weights.get(bias).map_or(0.0,|b| b[i])
        }).collect()
    }
    fn norm(&self,key:&str,x:&[f32]) -> Vec<f32> {
        let mean = x.iter().sum::<f32>() / x.len() as f32;
        let variance = x.iter().map(|v| (v-mean)*(v-mean)).sum::<f32>() / x.len() as f32;
        let inv = (variance+1e-5).sqrt().recip();
        let weight=&self.weights[&format!("{key}.weight")];
        let bias=&self.weights[&format!("{key}.bias")];
        x.iter().enumerate().map(|(i,v)| (v-mean)*inv*weight[i] + bias[i]).collect()
    }
    pub fn logit(&self, rows: &Value) -> Result<f32,String> {
        let rows = rows.as_array().ok_or("Expected tensor rows")?;
        if rows.is_empty() { return Err("Empty position".into()); }
        let d = self.width;
        let mut x = vec![self.weights["summary"].clone()];
        let mut counts = vec![0usize];
        let mut embedding_keys=vec!["group","kind","path","category"];
        if self.indexed {embedding_keys.extend(["card","role"]);}
        let embeddings:Vec<(&str,&Vec<f32>)> = embedding_keys.iter()
            .map(|key|(*key,&self.weights[&format!("embeddings.{key}.weight")])).collect();
        let numeric=&self.weights["number.weight"];
        // Position transforms depend only on (index, nesting depth) and these
        // fixed weights. Reuse them across fields without changing summation.
        let mut position_values=BTreeMap::new();
        for row in rows {
            let mut token = vec![0.0;d];
            for (key,w) in &embeddings {
                let id = row[*key].as_u64().ok_or("Missing embedding index")? as usize;
                let start = id.checked_mul(d).ok_or("Embedding overflow")?;
                let values = w.get(start..start.checked_add(d).ok_or("Embedding overflow")?).ok_or("Embedding out of range")?;
                for i in 0..d { token[i] += values[i]; }
            }
            let n = row["number"].as_f64().ok_or("Missing numeric feature")? as f32;
            if !n.is_finite() { return Err("Non-finite input".into()); }
            for i in 0..d { token[i] += n*numeric[i]; }
            for (depth,p) in row["positions"].as_array().ok_or("Missing positions")?.iter().enumerate() {
                let p = p.as_u64().ok_or("Invalid position")?;
                let v = position_values.entry((p,depth)).or_insert_with(|| {
                    let mut v = self.linear("position.0", &[p as f32/32.0,depth as f32/8.0]);
                    v.iter_mut().for_each(|n| *n = gelu(*n));
                    self.linear("position.2", &v)
                });
                for i in 0..d { token[i] += v[i]; }
            }
            let entity = row["entity"].as_u64().ok_or("Missing entity")? as usize;
            if entity == 0 || entity > rows.len() { return Err("Invalid entity".into()); }
            while x.len() <= entity { x.push(vec![0.0;d]); counts.push(0); }
            let v = self.linear("pool.0", &token);
            for i in 0..d { x[entity][i] += gelu(v[i]); }
            counts[entity] += 1;
        }
        for entity in 1..x.len() {
            if counts[entity] == 0 { return Err("Noncontiguous entities".into()); }
            let count = counts[entity] as f32;
            for i in 0..d { x[entity][i] = x[entity][i]/count.sqrt()+self.weights["pool_count.weight"][i]*count/32.0; }
        }
        for layer in 0..self.layers {
            let prefix = format!("blocks.{layer}");
            let qkv:Vec<Vec<f32>> = x.iter().map(|v| self.affine(&format!("{prefix}.self_attn.in_proj_weight"),
                &format!("{prefix}.self_attn.in_proj_bias"),&self.norm(&format!("{prefix}.norm1"),v))).collect();
            let hd = d/self.heads;
            let mut attended = vec![vec![0.0;d];x.len()];
            for i in 0..x.len() {
                for head in 0..self.heads {
                    let off = head*hd;
                    let mut scores:Vec<f32> = qkv.iter().map(|other| (0..hd).map(|k| qkv[i][off+k]*other[d+off+k]).sum::<f32>()/(hd as f32).sqrt()).collect();
                    let max = scores.iter().copied().fold(f32::NEG_INFINITY,f32::max);
                    scores.iter_mut().for_each(|v| *v = (*v-max).exp());
                    let sum = scores.iter().sum::<f32>();
                    for (j,score) in scores.iter().enumerate() {
                        for k in 0..hd { attended[i][off+k] += score/sum*qkv[j][2*d+off+k]; }
                    }
                }
            }
            for (i,v) in x.iter_mut().enumerate() {
                let out = self.linear(&format!("{prefix}.self_attn.out_proj"), &attended[i]);
                for k in 0..d { v[k] += out[k]; }
                let mut hidden = self.linear(&format!("{prefix}.linear1"), &self.norm(&format!("{prefix}.norm2"),v));
                hidden.iter_mut().for_each(|v| *v=gelu(*v));
                let out = self.linear(&format!("{prefix}.linear2"), &hidden);
                for k in 0..d { v[k] += out[k]; }
            }
        }
        let result = self.linear("head", &self.norm("norm",&x[0]))[0];
        if !result.is_finite() { return Err("Non-finite model result".into()); }
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
