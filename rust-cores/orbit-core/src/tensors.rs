//! Numeric adapter parity reference. Inputs are audited semantic tokens, not State.
//!
//! The JSON representation remains the compatibility boundary used by the
//! parity bridges. Native search uses `Encoder::encode_typed` so vocabulary,
//! path and card-ID lookups are validated once per model instead of once per
//! leaf, and the evaluator can consume rows without rebuilding JSON values.
use serde_json::{json, Value};
use std::collections::HashMap;

pub const GROUPS: [&str; 12] = [
    "bonuses", "captures", "history", "leader", "legal_actions", "own_hand",
    "pending", "public_cards", "resources", "tableau", "technology", "turn",
];
pub const KINDS: [&str; 6] = ["object", "sequence", "missing", "boolean", "number", "category"];

#[derive(Clone, Debug, PartialEq)]
pub struct TensorRow {
    pub group: usize,
    pub kind: usize,
    pub path: usize,
    pub positions: Vec<usize>,
    pub number: f32,
    pub entity: usize,
    pub role: usize,
    pub card: usize,
    pub category: usize,
}

pub struct Encoder {
    paths: HashMap<String, usize>,
    categories: HashMap<String, usize>,
    card_ids: HashMap<u16, usize>,
}

impl Encoder {
    pub fn new(v: &Value) -> Result<Self, String> {
        if (v["version"] != "orbit-tensors-v2" && v["version"] != "orbit-tensors-v3")
            || v["encoder"] != "orbit-semantic-v1"
            || v["rules"] != crate::rules().rules
            || v["numeric_scale"] != 32
        {
            return Err("Tensor vocabulary version/rules mismatch".into());
        }
        if v["groups"] != json!(GROUPS) || v["kinds"] != json!(KINDS) {
            return Err("Vocabulary metadata mismatch".into());
        }
        let mut paths = HashMap::new();
        let mut categories = HashMap::new();
        for (field, target) in [("paths", &mut paths), ("categories", &mut categories)] {
            let items = v[field].as_array().ok_or("Vocabulary array missing")?;
            let mut previous = None;
            for (index, item) in items.iter().enumerate() {
                let value = item.as_str().ok_or("Expected string")?;
                if previous.is_some_and(|old: &str| old >= value) {
                    return Err("Vocabulary must be sorted unique".into());
                }
                previous = Some(value);
                target.insert(value.to_owned(), index + 1);
            }
        }
        let card_ids = crate::rules()
            .cards
            .keys()
            .enumerate()
            .map(|(index, id)| (*id, index + 1))
            .collect();
        Ok(Self {
            paths,
            categories,
            card_ids,
        })
    }

    fn index(names: &[&str], value: &Value, field: &str) -> Result<usize, String> {
        let target = value
            .as_str()
            .ok_or_else(|| format!("Expected {field} string"))?;
        names
            .iter()
            .position(|name| *name == target)
            .map(|index| index + 1)
            .ok_or_else(|| format!("Unknown {field}: {target}"))
    }

    pub fn encode_typed(&self, tokens: &Value) -> Result<Vec<TensorRow>, String> {
        let tokens = tokens.as_array().ok_or("Missing tokens")?;
        let observer = tokens.iter().find_map(|token| {
            let path = token["path"].as_array()?;
            (path.len() == 1 && path[0].as_str() == Some("seat"))
                .then(|| token["value"].as_u64())
                .flatten()
        });
        let mut rows = Vec::with_capacity(tokens.len());
        let mut entities: HashMap<String, usize> = HashMap::new();
        for token in tokens {
            let parts = token["path"].as_array().ok_or("Missing path")?;
            let first = parts.first().and_then(Value::as_str);
            let mut size = 1;
            if first == Some("players") && parts.len() >= 2 {
                size = 2;
                if parts.get(2).and_then(Value::as_str) == Some("columns") {
                    size = parts.len().min(5);
                } else if parts.get(2).and_then(Value::as_str) == Some("hand") {
                    size = parts.len().min(4);
                }
            } else if matches!(first, Some("legal_moves" | "agent_discard")) {
                size = parts.len().min(2);
            } else if first == Some("history")
                && parts.get(1).and_then(Value::as_str) == Some("events")
            {
                size = parts.len().min(3);
            }
            let mut entity_key = Vec::with_capacity(size + 1);
            entity_key.push(token["group"].clone());
            entity_key.extend(parts.iter().take(size).cloned());
            let key_string = serde_json::to_string(&entity_key).map_err(|e| e.to_string())?;
            let next = entities.len() + 1;
            let entity = *entities.entry(key_string).or_insert(next);

            let mut template = Vec::with_capacity(parts.len());
            let mut positions = Vec::new();
            for part in parts {
                if let Some(n) = part.as_i64() {
                    if !(0..i32::MAX as i64).contains(&n) {
                        return Err("Position out of range".into());
                    }
                    positions.push(n as usize);
                    template.push(Value::Null);
                } else if part.is_string() {
                    template.push(part.clone());
                } else {
                    return Err("Invalid path component".into());
                }
            }
            let key = serde_json::to_string(&template).map_err(|e| e.to_string())?;
            let kind = token["kind"].as_str().ok_or("Missing kind")?;
            let mut role = 1;
            if let Some(observer) = observer {
                if let Some(at) = parts
                    .iter()
                    .position(|part| part.as_str() == Some("players"))
                {
                    if let Some(seat) = parts.get(at + 1).and_then(Value::as_u64) {
                        role = if seat == observer { 2 } else { 3 };
                    }
                }
            }
            let is_card = kind == "number"
                && ((parts.len() >= 2
                    && parts[parts.len() - 2].as_str() == Some("attributes")
                    && parts.last().and_then(Value::as_str) == Some("id"))
                    || parts.last().and_then(Value::as_str) == Some("card_id")
                    || (parts.len() >= 2
                        && parts[parts.len() - 2].as_str() == Some("card_ids")
                        && parts.last().is_some_and(Value::is_u64))
                    || (parts.len() == 2
                        && first == Some("agent_discard")
                        && parts[1].is_u64())
                    || (parts.len() == 4
                        && first == Some("players")
                        && parts[2].as_str() == Some("hand"))
                    || (parts.len() == 5
                        && first == Some("players")
                        && parts[2].as_str() == Some("columns")));
            let card = if is_card {
                let id = token["value"].as_u64().ok_or("Missing card ID")? as u16;
                *self.card_ids.get(&id).ok_or("Unknown card ID")?
            } else {
                0
            };
            let number = match kind {
                "number" | "object" | "sequence" | "boolean" => {
                    let raw = token["value"]
                        .as_bool()
                        .map(|value| if value { 1.0 } else { 0.0 })
                        .or_else(|| token["value"].as_f64())
                        .ok_or("Expected numeric value")?;
                    let value = (raw / 32.0) as f32;
                    if !value.is_finite() || value as f64 * 32.0 != raw {
                        return Err("Inexact float32 feature".into());
                    }
                    value
                }
                _ => 0.0,
            };
            let group = Self::index(&GROUPS, &token["group"], "group")?;
            let kind_index = Self::index(&KINDS, &token["kind"], "kind")?;
            let category = if kind == "category" {
                let value = token["value"].as_str().ok_or("Expected category string")?;
                *self
                    .categories
                    .get(value)
                    .ok_or_else(|| format!("Unknown categories: {value}"))?
            } else {
                0
            };
            let path = *self
                .paths
                .get(&key)
                .ok_or_else(|| format!("Unknown paths: {key}"))?;
            rows.push(TensorRow {
                group,
                kind: kind_index,
                path,
                positions,
                number,
                entity,
                role,
                card,
                category,
            });
        }
        Ok(rows)
    }

    pub fn encode_json(&self, tokens: &Value) -> Result<Value, String> {
        Ok(json!(self
            .encode_typed(tokens)?
            .iter()
            .map(TensorRow::as_value)
            .collect::<Vec<_>>()))
    }
}

impl TensorRow {
    pub fn as_value(&self) -> Value {
        json!({"group": self.group, "kind": self.kind, "path": self.path,
               "positions": self.positions, "number": self.number, "entity": self.entity,
               "role": self.role, "card": self.card, "category": self.category})
    }
}

pub fn encode(request: &Value) -> Result<Value, String> {
    encode_parts(&request["vocabulary"], &request["tokens"])
}

pub fn encode_parts(v: &Value, tokens: &Value) -> Result<Value, String> {
    Encoder::new(v)?.encode_json(tokens)
}

pub fn decode_rows(rows: &Value) -> Result<Vec<TensorRow>, String> {
    let rows = rows.as_array().ok_or("Expected tensor rows")?;
    let mut result = Vec::with_capacity(rows.len());
    for row in rows {
        let positions = row["positions"]
            .as_array()
            .ok_or("Missing positions")?
            .iter()
            .map(|value| {
                let value = value.as_u64().ok_or("Invalid position")?;
                if value >= i32::MAX as u64 {
                    return Err("Position out of range".into());
                }
                Ok(value as usize)
            })
            .collect::<Result<Vec<_>, String>>()?;
        let number = row["number"].as_f64().ok_or("Missing numeric feature")? as f32;
        if !number.is_finite() {
            return Err("Non-finite numeric feature".into());
        }
        let read = |name: &str| {
            row[name]
                .as_u64()
                .map(|value| value as usize)
                .ok_or_else(|| format!("Missing {name}"))
        };
        result.push(TensorRow {
            group: read("group")?,
            kind: read("kind")?,
            path: read("path")?,
            positions,
            number,
            entity: read("entity")?,
            role: read("role")?,
            card: read("card")?,
            category: read("category")?,
        });
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Value {
        json!({"vocabulary": {
            "version":"orbit-tensors-v2", "encoder":"orbit-semantic-v1",
            "rules":crate::rules().rules, "numeric_scale":32,
            "groups":["bonuses", "captures", "history", "leader", "legal_actions",
                "own_hand", "pending", "public_cards", "resources", "tableau", "technology", "turn"],
            "kinds":["object", "sequence", "missing", "boolean", "number", "category"],
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
    fn typed_rows_serialize_identically() {
        let request = fixture();
        let encoder = Encoder::new(&request["vocabulary"]).unwrap();
        let typed = encoder.encode_typed(&request["tokens"]).unwrap();
        assert_eq!(json!(typed.iter().map(TensorRow::as_value).collect::<Vec<_>>()), encode(&request).unwrap());
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
