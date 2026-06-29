//! PHASE 0 PARITY: load the PyTorch-exported attention weights (attn_weights.json) + fixed input
//! (attn_input.json) and run the SAME forward as attn_bench.rs / attn_net.py. Print value + policy[:6];
//! compare to attn_net.py's REF (must match ~1e-4). This proves the Rust serving/self-play forward and
//! the PyTorch training forward agree — the make-or-break for the card-set-attention bet.
//! Run from az_run:  attn_parity.exe attn_weights.json attn_input.json
use serde::Deserialize;

const NT: usize = 18; const FT: usize = 24; const D: usize = 64;
const HEADS: usize = 4; const HD: usize = D / HEADS; const FF: usize = 128;
const L: usize = 2; const FS: usize = 28; const H: usize = 128; const NACT: usize = 70;
const NEG: f32 = -1e9;
// 40 global action indices: takes+pass [0..30], reserve-deck [43..45], discard [61..66].
const GIDX: [usize; 40] = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,43,44,45,61,62,63,64,65,66];

#[derive(Deserialize)]
struct W {
    emb_w: Vec<f32>, emb_b: Vec<f32>,
    wq: Vec<Vec<f32>>, wk: Vec<Vec<f32>>, wv: Vec<Vec<f32>>, wo: Vec<Vec<f32>>,
    f1w: Vec<Vec<f32>>, f1b: Vec<Vec<f32>>, f2w: Vec<Vec<f32>>, f2b: Vec<Vec<f32>>,
    sw: Vec<f32>, sb: Vec<f32>, tw: Vec<f32>, tb: Vec<f32>,
    vw: Vec<f32>, vb: Vec<f32>, pg_w: Vec<f32>, pg_b: Vec<f32>, ptok_w: Vec<f32>, ptok_b: Vec<f32>,
}
#[derive(Deserialize)]
struct In { tokens: Vec<f32>, mask: Vec<f32>, state: Vec<f32> }

fn linear(x: &[f32], w: &[f32], b: &[f32], k: usize, m: usize, y: &mut [f32]) {
    for mi in 0..m {
        let mut s = if b.is_empty() { 0.0 } else { b[mi] };
        let row = mi * k;
        for ki in 0..k { s += x[ki] * w[row + ki]; }
        y[mi] = s;
    }
}
fn layernorm(x: &mut [f32]) {
    let n = x.len() as f32;
    let mean = x.iter().sum::<f32>() / n;
    let var = x.iter().map(|&v| (v - mean) * (v - mean)).sum::<f32>() / n;
    let inv = 1.0 / (var + 1e-5).sqrt();
    for v in x.iter_mut() { *v = (*v - mean) * inv; }
}

fn forward(w: &W, tokens: &[f32], mask: &[f32], state: &[f32]) -> (f32, Vec<f32>) {
    let nob: Vec<f32> = vec![]; // q/k/v/o have no bias
    let mut x = vec![0f32; NT * D];
    for t in 0..NT {
        let mut e = vec![0f32; D];
        linear(&tokens[t * FT..t * FT + FT], &w.emb_w, &w.emb_b, FT, D, &mut e);
        x[t * D..t * D + D].copy_from_slice(&e);
    }
    let scale = 1.0 / (HD as f32).sqrt();
    for l in 0..L {
        let (mut q, mut k, mut v) = (vec![0f32; NT * D], vec![0f32; NT * D], vec![0f32; NT * D]);
        for t in 0..NT {
            linear(&x[t * D..t * D + D], &w.wq[l], &nob, D, D, &mut q[t * D..t * D + D]);
            linear(&x[t * D..t * D + D], &w.wk[l], &nob, D, D, &mut k[t * D..t * D + D]);
            linear(&x[t * D..t * D + D], &w.wv[l], &nob, D, D, &mut v[t * D..t * D + D]);
        }
        let mut ctx = vec![0f32; NT * D];
        for h in 0..HEADS {
            let off = h * HD;
            for i in 0..NT {
                let mut sc = vec![f32::NEG_INFINITY; NT];
                let mut mx = f32::NEG_INFINITY;
                for j in 0..NT {
                    if mask[j] < 0.5 { continue; }
                    let mut s = 0.0;
                    for d in 0..HD { s += q[i * D + off + d] * k[j * D + off + d]; }
                    s *= scale; sc[j] = s; if s > mx { mx = s; }
                }
                let mut den = 0.0;
                for j in 0..NT { if mask[j] >= 0.5 { sc[j] = (sc[j] - mx).exp(); den += sc[j]; } }
                for d in 0..HD {
                    let mut acc = 0.0;
                    for j in 0..NT { if mask[j] >= 0.5 { acc += sc[j] * v[j * D + off + d]; } }
                    ctx[i * D + off + d] = acc / den;
                }
            }
        }
        for t in 0..NT {
            let mut o = vec![0f32; D];
            linear(&ctx[t * D..t * D + D], &w.wo[l], &nob, D, D, &mut o);
            for d in 0..D { x[t * D + d] += o[d]; }
            layernorm(&mut x[t * D..t * D + D]);
        }
        for t in 0..NT {
            let mut h1 = vec![0f32; FF];
            linear(&x[t * D..t * D + D], &w.f1w[l], &w.f1b[l], D, FF, &mut h1);
            for vv in h1.iter_mut() { if *vv < 0.0 { *vv = 0.0; } }
            let mut h2 = vec![0f32; D];
            linear(&h1, &w.f2w[l], &w.f2b[l], FF, D, &mut h2);
            for d in 0..D { x[t * D + d] += h2[d]; }
            layernorm(&mut x[t * D..t * D + D]);
        }
    }
    let mut pool = vec![0f32; D]; let mut cnt = 0.0;
    for t in 0..NT { if mask[t] >= 0.5 { cnt += 1.0; for d in 0..D { pool[d] += x[t * D + d]; } } }
    if cnt > 0.0 { for d in 0..D { pool[d] /= cnt; } }
    let mut se = vec![0f32; D];
    linear(state, &w.sw, &w.sb, FS, D, &mut se);
    let mut cat = vec![0f32; 2 * D];
    cat[..D].copy_from_slice(&pool); cat[D..].copy_from_slice(&se);
    let mut ht = vec![0f32; H];
    linear(&cat, &w.tw, &w.tb, 2 * D, H, &mut ht);
    for vv in ht.iter_mut() { if *vv < 0.0 { *vv = 0.0; } }
    let mut val = vec![0f32; 1]; linear(&ht, &w.vw, &w.vb, H, 1, &mut val);
    // policy: 40 global (from trunk ht) + 30 token-tied (from per-token reps x)
    let mut gl = vec![0f32; 40]; linear(&ht, &w.pg_w, &w.pg_b, H, 40, &mut gl);
    let mut pol = vec![NEG; NACT];
    for (gi, &ai) in GIDX.iter().enumerate() { pol[ai] = gl[gi]; }
    let mut ptok = [[0f32; 2]; NT];
    for t in 0..NT { linear(&x[t * D..t * D + D], &w.ptok_w, &w.ptok_b, D, 2, &mut ptok[t]); }
    for i in 0..12 { if mask[i] >= 0.5 { pol[46 + i] = ptok[i][0]; pol[31 + i] = ptok[i][1]; } }
    for j in 0..3 { if mask[12 + j] >= 0.5 { pol[58 + j] = ptok[12 + j][0]; } }
    for k in 0..3 { if mask[15 + k] >= 0.5 { pol[67 + k] = ptok[15 + k][0]; } }
    (val[0].tanh(), pol)
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let wp = a.get(1).cloned().unwrap_or_else(|| "attn_weights.json".into());
    let ip = a.get(2).cloned().unwrap_or_else(|| "attn_input.json".into());
    let w: W = serde_json::from_str(&std::fs::read_to_string(&wp).expect("read weights")).expect("parse w");
    let inp: In = serde_json::from_str(&std::fs::read_to_string(&ip).expect("read input")).expect("parse in");
    let (v, pol) = forward(&w, &inp.tokens, &inp.mask, &inp.state);
    println!("RUST value = {:.6}", v);
    let idx = [0usize, 1, 31, 46, 68, 60];
    print!("RUST pol[0,1,31,46,68,60] = ");
    for &i in &idx { print!("{:.6} ", pol[i]); }
    println!();
    // also exercise the LIB forward (attn::AttnNet) -> must match the local forward + the PyTorch REF
    let net = spender_core::attn::AttnNet::from_json(&wp);
    let tf: Vec<f64> = inp.tokens.iter().map(|&x| x as f64).collect();
    let mf: Vec<f64> = inp.mask.iter().map(|&x| x as f64).collect();
    let sf: Vec<f64> = inp.state.iter().map(|&x| x as f64).collect();
    let (v2, pol2) = net.forward(&tf, &mf, &sf);
    println!("LIB  value = {:.6}", v2);
    print!("LIB  pol[0,1,31,46,68,60] = ");
    for &i in &idx { print!("{:.6} ", pol2[i]); }
    println!();
}
