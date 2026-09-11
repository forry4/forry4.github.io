//! Persistent offline model parity process. Load once, then evaluate rows.
use std::io::{self,BufRead,Write};
use serde_json::{json,Value};
fn main() {
    let mut model = None;
    let mut out = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let result = line.map_err(|e|e.to_string()).and_then(|s|serde_json::from_str::<Value>(&s).map_err(|e|e.to_string()))
            .and_then(|v| {
                if let Some(artifact) = v.get("model") {
                    model = Some(orbit_core::attention::Model::load(artifact)?);
                    Ok(json!({"loaded":true}))
                } else {
                    let m = model.as_ref().ok_or("Model not loaded")?;
                    if let Some(state)=v.get("search_state") {
                        let state:orbit_core::State=serde_json::from_value(state.clone()).map_err(|e|e.to_string())?;
                        state.validate()?;
                        let config=orbit_core::search::Config{
                            simulations:v["simulations"].as_u64().unwrap_or(256) as usize,
                            max_depth:v["max_depth"].as_u64().unwrap_or(96) as usize,
                            budget_ms:v["budget_ms"].as_u64().unwrap_or(5000)};
                        return orbit_core::search::choose(&state,v["seat"].as_u64().ok_or("Missing seat")? as usize,
                            v["seed"].as_u64().unwrap_or(0),config,if v["heuristic"]==true {None}else{Some(m)});
                    }
                    let started = std::time::Instant::now();
                    let value = if let Some(obs) = v.get("observation") {
                        let tokens = orbit_core::features::encode(obs,v.get("history"))?;
                        let rows = m.encode_tokens(&tokens)?;
                        m.logit_typed(&rows)?
                    } else {
                        m.logit(&v["rows"])?
                    };
                    Ok(json!({"logit":value,"elapsed_ms":started.elapsed().as_secs_f64()*1000.0}))
                }
            });
        writeln!(out,"{}",result.unwrap_or_else(|e|json!({"error":e}))).unwrap();
        out.flush().unwrap();
    }
}
