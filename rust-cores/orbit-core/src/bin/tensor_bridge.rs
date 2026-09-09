//! Offline semantic-to-tensor parity harness, one request per line.
use std::io::{self, BufRead, Write};
fn main() {
    let mut out = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let result = line.map_err(|e| e.to_string())
            .and_then(|s| serde_json::from_str(&s).map_err(|e| e.to_string()))
            .and_then(|mut v: serde_json::Value| {
                if let Some(obs) = v.get("observation") {
                    v["tokens"] = orbit_core::features::encode(obs,v.get("history"))?;
                }
                if v.get("vocabulary").is_none() { Ok(v["tokens"].clone()) }
                else { orbit_core::tensors::encode(&v) }
            });
        let value = result.unwrap_or_else(|e| serde_json::json!({"error": e}));
        writeln!(out, "{value}").unwrap();
        out.flush().unwrap();
    }
}
