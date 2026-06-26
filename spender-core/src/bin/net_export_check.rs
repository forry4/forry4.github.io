//! Phase 0 export-path de-risk: build a random MLP in Rust, run a forward pass, and dump
//! {dims, weights, biases, input, output} to JSON. `net_parity.py` reloads it, recomputes the forward
//! with numpy, and asserts a match — proving the weight-layout convention (the real PyTorch->Rust
//! footgun) and inference math are consistent across the boundary. No serde dep (manual JSON).
//!
//! Usage: cargo run --release --bin net_export_check <out.json>

use spender_core::valuenet::Mlp;
use std::fs::File;
use std::io::Write;

fn f32s(v: &[f32]) -> String {
    v.iter().map(|x| format!("{x}")).collect::<Vec<_>>().join(",")
}

fn main() {
    let out = std::env::args().nth(1).unwrap_or_else(|| "net_check.json".into());
    let dims = [16usize, 32, 16, 1];
    let net = Mlp::random(&dims, 12345);
    let x: Vec<f32> = (0..dims[0]).map(|i| ((i * 13 % 17) as f32) * 0.1 - 0.7).collect();
    let y = net.forward(&x);

    // Mlp exposes weights via accessors below (added for this check).
    let mut s = String::new();
    s.push_str("{\n");
    s.push_str(&format!("  \"dims\": [{}],\n", dims.iter().map(|d| d.to_string()).collect::<Vec<_>>().join(",")));
    s.push_str("  \"w\": [");
    for (li, w) in net.weights().iter().enumerate() {
        if li > 0 { s.push(','); }
        s.push_str(&format!("[{}]", f32s(w)));
    }
    s.push_str("],\n");
    s.push_str("  \"b\": [");
    for (li, b) in net.biases().iter().enumerate() {
        if li > 0 { s.push(','); }
        s.push_str(&format!("[{}]", f32s(b)));
    }
    s.push_str("],\n");
    s.push_str(&format!("  \"x\": [{}],\n", f32s(&x)));
    s.push_str(&format!("  \"y\": {y}\n"));
    s.push_str("}\n");

    File::create(&out).unwrap().write_all(s.as_bytes()).unwrap();
    println!("wrote {out}  (rust forward y = {y})");
}
