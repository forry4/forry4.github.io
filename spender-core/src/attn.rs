//! Card-set ATTENTION net — the weight-loading forward used by self-play + serving. PARITY-LOCKED to
//! PyTorch `attn_net.py` (verified to 1e-6 via the attn_parity bin). 18 tokens x 24 feats -> embed D=64
//! -> 2x [4-head MHA + FFN128] (residual + manual LayerNorm) -> mean-pool + state-embed -> trunk H=128 ->
//! value(tanh) + PER-TOKEN policy head (token-tied slot actions + global head; see feats::features_tokens
//! + the 70-action map). Input is the f64 token vector from `features_tokens`; computed in f32 to match
//! the f32-trained PyTorch net.
use crate::feats::{TOK_F, TOK_N, TOK_STATE};

const D: usize = 64;
const HEADS: usize = 4;
const HD: usize = D / HEADS;
const FF: usize = 128;
const L: usize = 2;
const H: usize = 128;
const NACT: usize = 70;
const NEG: f32 = -1e9;
const GIDX: [usize; 40] = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,43,44,45,61,62,63,64,65,66];

pub struct AttnNet {
    pub emb_w: Vec<f32>, pub emb_b: Vec<f32>,
    pub wq: Vec<Vec<f32>>, pub wk: Vec<Vec<f32>>, pub wv: Vec<Vec<f32>>, pub wo: Vec<Vec<f32>>,
    pub f1w: Vec<Vec<f32>>, pub f1b: Vec<Vec<f32>>, pub f2w: Vec<Vec<f32>>, pub f2b: Vec<Vec<f32>>,
    pub sw: Vec<f32>, pub sb: Vec<f32>, pub tw: Vec<f32>, pub tb: Vec<f32>,
    pub vw: Vec<f32>, pub vb: Vec<f32>, pub pg_w: Vec<f32>, pub pg_b: Vec<f32>,
    pub ptok_w: Vec<f32>, pub ptok_b: Vec<f32>,
}

#[inline]
fn linear(x: &[f32], w: &[f32], b: &[f32], k: usize, m: usize, y: &mut [f32]) {
    for mi in 0..m {
        let mut s = if b.is_empty() { 0.0 } else { b[mi] };
        let row = mi * k;
        for ki in 0..k { s += x[ki] * w[row + ki]; }
        y[mi] = s;
    }
}
#[inline]
fn layernorm(x: &mut [f32]) {
    let n = x.len() as f32;
    let mean = x.iter().sum::<f32>() / n;
    let var = x.iter().map(|&v| (v - mean) * (v - mean)).sum::<f32>() / n;
    let inv = 1.0 / (var + 1e-5).sqrt();
    for v in x.iter_mut() { *v = (*v - mean) * inv; }
}

impl AttnNet {
    /// (value in [-1,1], 70 policy logits). `tokens` = TOK_N*TOK_F f64, `mask` = TOK_N, `state` = TOK_STATE.
    pub fn forward(&self, tokens: &[f64], mask: &[f64], state: &[f64]) -> (f64, Vec<f64>) {
        let tok: Vec<f32> = tokens.iter().map(|&x| x as f32).collect();
        let msk: Vec<f32> = mask.iter().map(|&x| x as f32).collect();
        let st: Vec<f32> = state.iter().map(|&x| x as f32).collect();
        let nob: Vec<f32> = vec![];
        let mut x = vec![0f32; TOK_N * D];
        for t in 0..TOK_N {
            let mut e = vec![0f32; D];
            linear(&tok[t * TOK_F..t * TOK_F + TOK_F], &self.emb_w, &self.emb_b, TOK_F, D, &mut e);
            x[t * D..t * D + D].copy_from_slice(&e);
        }
        let scale = 1.0 / (HD as f32).sqrt();
        for l in 0..L {
            let (mut q, mut k, mut v) = (vec![0f32; TOK_N * D], vec![0f32; TOK_N * D], vec![0f32; TOK_N * D]);
            for t in 0..TOK_N {
                linear(&x[t * D..t * D + D], &self.wq[l], &nob, D, D, &mut q[t * D..t * D + D]);
                linear(&x[t * D..t * D + D], &self.wk[l], &nob, D, D, &mut k[t * D..t * D + D]);
                linear(&x[t * D..t * D + D], &self.wv[l], &nob, D, D, &mut v[t * D..t * D + D]);
            }
            let mut ctx = vec![0f32; TOK_N * D];
            for h in 0..HEADS {
                let off = h * HD;
                for i in 0..TOK_N {
                    let mut sc = vec![f32::NEG_INFINITY; TOK_N];
                    let mut mx = f32::NEG_INFINITY;
                    for j in 0..TOK_N {
                        if msk[j] < 0.5 { continue; }
                        let mut s = 0.0;
                        for d in 0..HD { s += q[i * D + off + d] * k[j * D + off + d]; }
                        s *= scale; sc[j] = s; if s > mx { mx = s; }
                    }
                    let mut den = 0.0;
                    for j in 0..TOK_N { if msk[j] >= 0.5 { sc[j] = (sc[j] - mx).exp(); den += sc[j]; } }
                    for d in 0..HD {
                        let mut acc = 0.0;
                        for j in 0..TOK_N { if msk[j] >= 0.5 { acc += sc[j] * v[j * D + off + d]; } }
                        ctx[i * D + off + d] = acc / den;
                    }
                }
            }
            for t in 0..TOK_N {
                let mut o = vec![0f32; D];
                linear(&ctx[t * D..t * D + D], &self.wo[l], &nob, D, D, &mut o);
                for d in 0..D { x[t * D + d] += o[d]; }
                layernorm(&mut x[t * D..t * D + D]);
            }
            for t in 0..TOK_N {
                let mut h1 = vec![0f32; FF];
                linear(&x[t * D..t * D + D], &self.f1w[l], &self.f1b[l], D, FF, &mut h1);
                for vv in h1.iter_mut() { if *vv < 0.0 { *vv = 0.0; } }
                let mut h2 = vec![0f32; D];
                linear(&h1, &self.f2w[l], &self.f2b[l], FF, D, &mut h2);
                for d in 0..D { x[t * D + d] += h2[d]; }
                layernorm(&mut x[t * D..t * D + D]);
            }
        }
        let mut pool = vec![0f32; D]; let mut cnt = 0.0;
        for t in 0..TOK_N { if msk[t] >= 0.5 { cnt += 1.0; for d in 0..D { pool[d] += x[t * D + d]; } } }
        if cnt > 0.0 { for d in 0..D { pool[d] /= cnt; } }
        let mut se = vec![0f32; D];
        linear(&st, &self.sw, &self.sb, TOK_STATE, D, &mut se);
        let mut cat = vec![0f32; 2 * D];
        cat[..D].copy_from_slice(&pool); cat[D..].copy_from_slice(&se);
        let mut ht = vec![0f32; H];
        linear(&cat, &self.tw, &self.tb, 2 * D, H, &mut ht);
        for vv in ht.iter_mut() { if *vv < 0.0 { *vv = 0.0; } }
        let mut val = vec![0f32; 1]; linear(&ht, &self.vw, &self.vb, H, 1, &mut val);
        // policy
        let mut gl = vec![0f32; 40]; linear(&ht, &self.pg_w, &self.pg_b, H, 40, &mut gl);
        let mut pol = vec![NEG; NACT];
        for (gi, &ai) in GIDX.iter().enumerate() { pol[ai] = gl[gi]; }
        let mut ptok = [[0f32; 2]; TOK_N];
        for t in 0..TOK_N { linear(&x[t * D..t * D + D], &self.ptok_w, &self.ptok_b, D, 2, &mut ptok[t]); }
        for i in 0..12 { if msk[i] >= 0.5 { pol[46 + i] = ptok[i][0]; pol[31 + i] = ptok[i][1]; } }
        for j in 0..3 { if msk[12 + j] >= 0.5 { pol[58 + j] = ptok[12 + j][0]; } }
        for kk in 0..3 { if msk[15 + kk] >= 0.5 { pol[67 + kk] = ptok[15 + kk][0]; } }
        (val[0].tanh() as f64, pol.iter().map(|&x| x as f64).collect())
    }
}

#[cfg(feature = "bridge")]
#[derive(serde::Deserialize)]
struct AttnJson {
    emb_w: Vec<f32>, emb_b: Vec<f32>,
    wq: Vec<Vec<f32>>, wk: Vec<Vec<f32>>, wv: Vec<Vec<f32>>, wo: Vec<Vec<f32>>,
    f1w: Vec<Vec<f32>>, f1b: Vec<Vec<f32>>, f2w: Vec<Vec<f32>>, f2b: Vec<Vec<f32>>,
    sw: Vec<f32>, sb: Vec<f32>, tw: Vec<f32>, tb: Vec<f32>,
    vw: Vec<f32>, vb: Vec<f32>, pg_w: Vec<f32>, pg_b: Vec<f32>, ptok_w: Vec<f32>, ptok_b: Vec<f32>,
}

#[cfg(feature = "bridge")]
impl AttnNet {
    pub fn from_json(path: &str) -> Self {
        let j: AttnJson = serde_json::from_str(&std::fs::read_to_string(path).expect("read attn json")).expect("parse attn json");
        AttnNet {
            emb_w: j.emb_w, emb_b: j.emb_b, wq: j.wq, wk: j.wk, wv: j.wv, wo: j.wo,
            f1w: j.f1w, f1b: j.f1b, f2w: j.f2w, f2b: j.f2b,
            sw: j.sw, sb: j.sb, tw: j.tw, tb: j.tb, vw: j.vw, vb: j.vb,
            pg_w: j.pg_w, pg_b: j.pg_b, ptok_w: j.ptok_w, ptok_b: j.ptok_b,
        }
    }
}
