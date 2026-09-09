//! Numeric adapter parity reference. Inputs are audited semantic tokens, not State.
//! This does not yet port observation-to-semantic extraction or run a model.
use serde_json::{json, Value};

pub fn encode(request: &Value) -> Result<Value, String> {
    encode_parts(&request["vocabulary"], &request["tokens"])
}

pub fn encode_parts(v: &Value, tokens: &Value) -> Result<Value, String> {
    if (v["version"] != "orbit-tensors-v2" && v["version"] != "orbit-tensors-v3") || v["encoder"] != "orbit-semantic-v1"
        || v["rules"] != crate::rules().rules || v["numeric_scale"] != 32 {
        return Err("Tensor vocabulary version/rules mismatch".into());
    }
    let groups = json!(["bonuses", "captures", "history", "leader", "legal_actions",
        "own_hand", "pending", "public_cards", "resources", "tableau", "technology", "turn"]);
    let kinds = json!(["object", "sequence", "missing", "boolean", "number", "category"]);
    if v["groups"] != groups || v["kinds"] != kinds { return Err("Vocabulary metadata mismatch".into()); }
    for name in ["paths", "categories"] {
        let items = v[name].as_array().ok_or("Vocabulary array missing")?;
        let strings: Vec<&str> = items.iter().map(|x| x.as_str().ok_or("Expected string"))
            .collect::<Result<_, _>>()?;
        if strings.windows(2).any(|w| w[0] >= w[1]) { return Err("Vocabulary must be sorted unique".into()); }
    }
    let lookup = |field: &str, value: &Value| -> Result<usize, String> {
        let items=v[field].as_array().ok_or("Vocabulary array missing")?;
        let index=if matches!(field,"paths"|"categories") {
            let target=value.as_str().ok_or("Expected vocabulary string")?;
            items.binary_search_by(|x|x.as_str().unwrap().cmp(target)).ok()
        }else{items.iter().position(|x|x==value)};
        index.map(|i|i+1).ok_or_else(||format!("Unknown {field}: {value}"))
    };
    let mut rows = Vec::new();
    let mut entities = std::collections::BTreeMap::new();
    let observer=tokens.as_array().ok_or("Missing tokens")?.iter()
        .find(|t|t["path"]==json!(["seat"])).and_then(|t|t["value"].as_u64());
    for token in tokens.as_array().ok_or("Missing tokens")? {
        let parts = token["path"].as_array().ok_or("Missing path")?;
        let mut size = 1;
        if parts.first() == Some(&json!("players")) && parts.len() >= 2 {
            size = 2;
            if parts.get(2) == Some(&json!("columns")) { size = parts.len().min(5); }
            else if parts.get(2) == Some(&json!("hand")) { size = parts.len().min(4); }
        } else if parts.first() == Some(&json!("legal_moves")) || parts.first() == Some(&json!("agent_discard")) {
            size = parts.len().min(2);
        } else if parts.first() == Some(&json!("history")) && parts.get(1) == Some(&json!("events")) {
            size = parts.len().min(3);
        }
        let mut entity_key = vec![token["group"].clone()];
        entity_key.extend(parts.iter().take(size).cloned());
        let key_string = serde_json::to_string(&entity_key).map_err(|e|e.to_string())?;
        let next = entities.len()+1;
        let entity = *entities.entry(key_string).or_insert(next);
        let mut template = Vec::new();
        let mut positions = Vec::new();
        for part in parts {
            if let Some(n) = part.as_i64() {
                if !(0..i32::MAX as i64).contains(&n) { return Err("Position out of range".into()); }
                positions.push(n);
                template.push(Value::Null);
            } else if part.is_string() { template.push(part.clone()); }
            else { return Err("Invalid path component".into()); }
        }
        let key = serde_json::to_string(&template).map_err(|e| e.to_string())?;
        let kind = token["kind"].as_str().ok_or("Missing kind")?;
        let mut role=1;
        if let Some(observer)=observer {
            if let Some(at)=parts.iter().position(|p|p=="players") {
                if let Some(seat)=parts.get(at+1).and_then(Value::as_u64) {role=if seat==observer {2}else{3};}
            }
        }
        let is_card=kind=="number" && (
            (parts.len()>=2 && parts[parts.len()-2..]==[json!("attributes"),json!("id")]) || parts.last()==Some(&json!("card_id"))
            || (parts.len()>=2 && parts[parts.len()-2]=="card_ids" && parts.last().unwrap().is_u64())
            || (parts.len()==2 && parts[0]=="agent_discard" && parts[1].is_u64())
            || (parts.len()==4 && parts[0]=="players" && parts[2]=="hand")
            || (parts.len()==5 && parts[0]=="players" && parts[2]=="columns"));
        let card=if is_card {
            let id=token["value"].as_u64().ok_or("Missing card ID")?;
            crate::rules().cards.keys().position(|c|*c as u64==id).ok_or("Unknown card ID")?+1
        }else{0};
        let number = match kind {
            "number" | "object" | "sequence" | "boolean" => {
                let raw = if let Some(b) = token["value"].as_bool() { if b {1.0} else {0.0} }
                    else { token["value"].as_f64().ok_or("Expected numeric value")? };
                let value = (raw / 32.0) as f32;
                if !value.is_finite() || value as f64 * 32.0 != raw { return Err("Inexact float32 feature".into()); }
                value
            },
            _ => 0.0,
        };
        rows.push(json!({"group":lookup("groups", &token["group"])?,
            "kind":lookup("kinds", &token["kind"])?, "path":lookup("paths", &json!(key))?,
            "positions":positions, "number":number, "entity":entity, "role":role, "card":card,
            "category":if kind == "category" {lookup("categories", &token["value"])?} else {0}}));
    }
    Ok(json!(rows))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Value {
        json!({"vocabulary": {
            "version":"orbit-tensors-v2", "encoder":"orbit-semantic-v1",
            "rules":crate::rules().rules, "numeric_scale":32,
            "groups":["bonuses","captures","history","leader","legal_actions",
                "own_hand","pending","public_cards","resources","tableau","technology","turn"],
            "kinds":["object","sequence","missing","boolean","number","category"],
            "paths":["[\"players\",null,\"credits\"]"], "categories":[]},
            "tokens":[{"group":"resources", "kind":"number",
                "path":["players",0,"credits"], "value":40}]})
    }
    #[test]
    fn keeps_numeric_value_and_zero_position() {
        let result = encode(&fixture()).unwrap();
        assert_eq!(result[0]["number"], 1.25);
        assert_eq!(result[0]["positions"], json!([0]));
        assert_eq!(result[0]["path"], 1);
    }
    #[test]
    fn rejects_stale_unknown_and_inexact_inputs() {
        let mut request = fixture();
        request["vocabulary"]["rules"] = json!("stale");
        assert!(encode(&request).is_err());
        request = fixture();
        request["tokens"][0]["path"][2] = json!("unreviewed");
        assert!(encode(&request).is_err());
        request = fixture();
        request["tokens"][0]["value"] = json!(16_777_217);
        assert!(encode(&request).is_err());
    }
}
