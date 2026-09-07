//! Small, versioned serving boundary shared by native tooling and a future
//! wasm-bindgen export.
//!
//! The Python room remains authoritative.  This helper intentionally accepts
//! an allowlisted observation plus the already validated legal actions; it
//! never accepts the privileged `State` or a hidden deck.  A production model
//! can replace the deterministic fallback without changing its JSON contract.

use serde_json::{json, Map, Value};

use crate::{FACTIONS, PLANETS};

pub const ABI_VERSION: u32 = 1;
pub const MODEL_VERSION: u32 = 1;
pub const SCHEMA_VERSION: u32 = 1;
pub const ENCODER_VERSION: &str = "orbit-observation-v1";
pub const MODEL_ID: &str = "orbit-hard-v1";
pub const TURN_BUDGET_MS: u32 = 5_000;
pub const MAIN_ACTION_BUDGET_MS: u32 = 3_000;
pub const FOLLOWUP_RESERVE_MS: u32 = 2_000;
pub const MAX_MEMORY_BYTES: usize = 64 * 1024;
pub const MAX_BRANCHES: usize = 32;

fn stable_hash(value: &Value, mut state: u32) -> u32 {
    // A tiny deterministic FNV-style hash is enough for tie-breaking.  It is
    // not a source of game randomness and never inspects data outside the
    // supplied policy inputs.
    let encoded = canonical(value);
    for byte in encoded.as_bytes() {
        state ^= *byte as u32;
        state = state.wrapping_mul(16_777_619);
    }
    state
}

fn position_key(observation: &Value, legal_moves: &[Value]) -> String {
    let payload = json!({"observation": observation, "legal_moves": legal_moves});
    format!("{:08x}", stable_hash(&payload, 2_166_136_261))
}

fn default_memory() -> Value {
    json!({"version": ABI_VERSION, "branches": {}, "history": {"events": []}})
}

fn memory_size(value: &Value) -> usize {
    serde_json::to_vec(value).map_or(MAX_MEMORY_BYTES + 1, |bytes| bytes.len())
}

fn trim_object_tail(object: &mut Map<String, Value>, keep: usize) {
    if object.len() <= keep {
        return;
    }
    let keys = object.keys().cloned().collect::<Vec<_>>();
    let drop_count = keys.len().saturating_sub(keep);
    for key in keys.into_iter().take(drop_count) {
        object.remove(&key);
    }
}

fn normalize_memory(value: &Value) -> Value {
    let mut result = match value.as_object() {
        Some(object) => Value::Object(object.clone()),
        None => default_memory(),
    };
    if result
        .as_object()
        .and_then(|object| object.get("version"))
        .and_then(Value::as_u64)
        .unwrap_or(ABI_VERSION as u64)
        != ABI_VERSION as u64
    {
        result = default_memory();
    }
    {
        let object = result.as_object_mut().expect("memory object");
        object.insert("version".into(), json!(ABI_VERSION));
        if !object.get("branches").is_some_and(Value::is_object) {
            object.insert("branches".into(), Value::Object(Map::new()));
        }
        if !object.get("history").is_some_and(Value::is_object) {
            object.insert("history".into(), json!({"events": []}));
        }
        if let Some(branches) = object.get_mut("branches").and_then(Value::as_object_mut) {
            trim_object_tail(branches, MAX_BRANCHES);
        }
    }
    if memory_size(&result) <= MAX_MEMORY_BYTES {
        return result;
    }
    {
        let object = result.as_object_mut().expect("memory object");
        if let Some(history) = object.get_mut("history").and_then(Value::as_object_mut) {
            if let Some(events) = history.get_mut("events").and_then(Value::as_array_mut) {
                let keep_from = events.len().saturating_sub(16);
                *events = events.split_off(keep_from);
            }
        }
        if let Some(branches) = object.get_mut("branches").and_then(Value::as_object_mut) {
            trim_object_tail(branches, 8);
        }
    }
    if memory_size(&result) <= MAX_MEMORY_BYTES {
        result
    } else {
        default_memory()
    }
}

fn canonical(value: &Value) -> String {
    match value {
        Value::Null => "null".to_owned(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => serde_json::to_string(value).unwrap_or_default(),
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(canonical).collect::<Vec<_>>().join(",")
        ),
        Value::Object(values) => {
            let mut keys = values.keys().collect::<Vec<_>>();
            keys.sort();
            format!(
                "{{{}}}",
                keys.iter()
                    .map(|key| format!(
                        "{}:{}",
                        serde_json::to_string(*key).unwrap(),
                        canonical(&values[*key])
                    ))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
    }
}

fn exact_keys(object: &Map<String, Value>, allowed: &[&str]) -> bool {
    object.len() == allowed.len() && allowed.iter().all(|key| object.contains_key(*key))
}

fn number(value: Option<&Value>) -> f64 {
    value.and_then(Value::as_f64).unwrap_or(0.0)
}

fn index_of(values: &[&str], value: Option<&Value>) -> Option<usize> {
    value
        .and_then(Value::as_str)
        .and_then(|needle| values.iter().position(|item| *item == needle))
}

fn score(observation: &Value, action: &Value) -> f64 {
    let action_name = action.get("action").and_then(Value::as_str).unwrap_or("");
    let seat = observation.get("seat").and_then(Value::as_u64).unwrap_or(0) as usize;
    let players = observation.get("players").and_then(Value::as_array);
    let me = players
        .and_then(|items| items.get(seat))
        .unwrap_or(&Value::Null);
    let card = action
        .get("card_id")
        .and_then(Value::as_u64)
        .and_then(|id| crate::rules().cards.get(&(id as u16)));
    let mut result = 0.0;
    if let Some(card) = card {
        let planet = PLANETS
            .iter()
            .position(|value| *value == card.planet)
            .unwrap_or(0);
        let column_len = me
            .get("columns")
            .and_then(Value::as_array)
            .and_then(|columns| columns.get(planet))
            .and_then(Value::as_array)
            .map_or(0, Vec::len) as f64;
        match action_name {
            "recruit" => {
                let cost = (card.cost as f64 - column_len).max(0.0);
                result += 0.42 * (1.0 - cost / 10.0);
                if let Some(position) = observation
                    .get("influence")
                    .and_then(Value::as_array)
                    .and_then(|values| values.get(planet))
                    .filter(|value| !value.is_null())
                {
                    let direction = if seat == 0 { 1.0 } else { -1.0 };
                    result += 0.16 * number(Some(position)) * direction / 4.0;
                }
                if column_len > 0.0 {
                    result += 0.04;
                }
            }
            "technology" => {
                let faction = FACTIONS
                    .iter()
                    .position(|value| *value == card.faction)
                    .unwrap_or(0);
                let level = me
                    .get("technology")
                    .and_then(Value::as_array)
                    .and_then(|values| values.get(faction))
                    .and_then(Value::as_i64)
                    .unwrap_or(0) as f64;
                result += 0.25 + 0.035 * (5.0 - level);
            }
            "leader" => {
                result += 0.13;
                result += match card.faction.as_str() {
                    "robot" => 0.05,
                    "human" => 0.04,
                    "animod" => 0.045,
                    _ => 0.0,
                };
            }
            _ => {}
        }
    } else if action_name == "mulligan" {
        if let Some(ids) = action.get("card_ids").and_then(Value::as_array) {
            for id in ids {
                let cost = id
                    .as_u64()
                    .and_then(|value| crate::rules().cards.get(&(value as u16)))
                    .map_or(5.0, |card| card.cost as f64);
                result += 0.012 * (5.0 - cost);
            }
        }
    }
    let direction = if seat == 0 { 1.0 } else { -1.0 };
    if let Some(planet) = index_of(&PLANETS, action.get("planet")) {
        if let Some(position) = observation
            .get("influence")
            .and_then(Value::as_array)
            .and_then(|values| values.get(planet))
            .filter(|value| !value.is_null())
        {
            result += 0.18 * number(Some(position)) * direction / 4.0;
        }
    }
    if let Some(planets) = action.get("planets").and_then(Value::as_array) {
        for planet in planets {
            if let Some(index) = index_of(&PLANETS, Some(planet)) {
                if let Some(position) = observation
                    .get("influence")
                    .and_then(Value::as_array)
                    .and_then(|values| values.get(index))
                    .filter(|value| !value.is_null())
                {
                    result += 0.08 * number(Some(position)) * direction / 4.0;
                }
            }
        }
    }
    if action.get("accept").and_then(Value::as_bool) == Some(true) {
        result += 0.025;
    }
    result += 0.018 * number(action.get("tier"));
    result += 0.01 * number(action.get("cost"));
    result -= 0.0005 * number(action.get("branch"));
    result
}

/// Return the JSON contract used by `games/orbit/ai/serving.py`.
pub fn manifest() -> Value {
    json!({
        "abi_version": ABI_VERSION,
        "model_version": MODEL_VERSION,
        "model_id": MODEL_ID,
        "encoder": ENCODER_VERSION,
        "schema": SCHEMA_VERSION,
        "rules": crate::rules().rules,
        "turn_budget_ms": TURN_BUDGET_MS,
        "main_action_budget_ms": MAIN_ACTION_BUDGET_MS,
        "followup_reserve_ms": FOLLOWUP_RESERVE_MS,
    })
}

/// Choose an existing legal action and return `{move, memory, diagnostics}`.
///
/// The current implementation is deliberately a cheap deterministic fallback;
/// the browser worker uses the same shape and can feature-detect a generated
/// model export.  The server must still validate the returned action against
/// the live Python engine.
pub fn choose_move(
    observation: &Value,
    legal_moves: &[Value],
    memory: &Value,
    remaining_turn_budget: i64,
    seed: u64,
) -> Value {
    const OBSERVATION_KEYS: [&str; 21] = [
        "schema",
        "phase",
        "turn_pid",
        "turn_number",
        "influence",
        "captured_this_turn",
        "leader",
        "board_sides",
        "planet_bonus",
        "technology_bonus",
        "agent_discard",
        "bonus_discard",
        "mulligan_done",
        "pending_pid",
        "winner",
        "seat",
        "players",
        "agent_deck_count",
        "bonus_deck_count",
        "pending",
        "legal_moves",
    ];
    const PLAYER_KEYS_WITH_HAND: [&str; 8] = [
        "credits",
        "zenithium",
        "columns",
        "technology",
        "row_bonuses",
        "captured",
        "hand_count",
        "hand",
    ];
    const PLAYER_KEYS_HIDDEN_HAND: [&str; 7] = [
        "credits",
        "zenithium",
        "columns",
        "technology",
        "row_bonuses",
        "captured",
        "hand_count",
    ];
    let observation_object = match observation.as_object() {
        Some(object) if exact_keys(object, &OBSERVATION_KEYS) => object,
        _ => return json!({"error": "Orbit serving observation fields mismatch"}),
    };
    if observation.get("schema").and_then(Value::as_u64) != Some(SCHEMA_VERSION as u64) {
        return json!({"error": "Orbit serving observation schema mismatch"});
    }
    let seat = observation.get("seat").and_then(Value::as_u64);
    let players = observation.get("players").and_then(Value::as_array);
    if !matches!(seat, Some(0 | 1)) || players.map_or(true, |players| players.len() != 2) {
        return json!({"error": "Orbit serving observation shape mismatch"});
    }
    for (index, player) in players.unwrap().iter().enumerate() {
        let Some(player) = player.as_object() else {
            return json!({"error": "Orbit serving observation player shape mismatch"});
        };
        let expected_keys = if index == seat.unwrap() as usize {
            exact_keys(player, &PLAYER_KEYS_WITH_HAND)
        } else {
            exact_keys(player, &PLAYER_KEYS_HIDDEN_HAND)
        };
        if !expected_keys {
            return json!({"error": "Orbit serving observation player fields mismatch"});
        }
    }
    if legal_moves.iter().any(|action| !action.is_object()) {
        return json!({"error": "Orbit serving legal moves must be objects"});
    }
    let Some(advertised) = observation_object
        .get("legal_moves")
        .and_then(Value::as_array)
    else {
        return json!({"error": "Orbit serving advertised legal moves must be objects"});
    };
    if advertised.iter().any(|action| !action.is_object()) {
        return json!({"error": "Orbit serving advertised legal moves must be objects"});
    }
    {
        let mut expected = legal_moves.iter().map(canonical).collect::<Vec<_>>();
        let mut actual = advertised.iter().map(canonical).collect::<Vec<_>>();
        expected.sort();
        actual.sort();
        if expected != actual {
            return json!({"error": "Orbit serving legal-move list mismatch"});
        }
    }
    let mut next_memory = normalize_memory(memory);
    let key = position_key(observation, legal_moves);
    let mut reused_branch = false;
    let mut index = next_memory
        .get("branches")
        .and_then(Value::as_object)
        .and_then(|branches| branches.get(&key))
        .and_then(|entry| entry.get("move"))
        .and_then(|candidate| {
            let candidate_key = canonical(candidate);
            legal_moves
                .iter()
                .position(|move_| canonical(move_) == candidate_key)
        });
    if index.is_some() {
        reused_branch = true;
    } else if !legal_moves.is_empty() {
        let scored = legal_moves
            .iter()
            .enumerate()
            .map(|(index, action)| (score(observation, action), canonical(action), index))
            .collect::<Vec<_>>();
        let best = scored
            .iter()
            .map(|item| item.0)
            .fold(f64::NEG_INFINITY, f64::max);
        let mut ties = scored
            .into_iter()
            .filter(|item| (item.0 - best).abs() <= 1e-12)
            .collect::<Vec<_>>();
        ties.sort_by(|left, right| left.1.cmp(&right.1));
        let mut state = (seed as u32) ^ 0x9e37_79b9;
        state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
        index = Some(ties[(state as usize) % ties.len()].2);
    }
    if let Some(chosen) = index {
        if let Some(branches) = next_memory
            .get_mut("branches")
            .and_then(Value::as_object_mut)
        {
            branches.insert(
                key.clone(),
                json!({
                    "move": legal_moves[chosen].clone(),
                    "model": MODEL_ID,
                }),
            );
            trim_object_tail(branches, MAX_BRANCHES);
        }
    }
    json!({
        "move": index.map(|i| legal_moves[i].clone()),
        "memory": next_memory,
        "diagnostics": {
            "abi_version": ABI_VERSION,
            "model_version": MODEL_VERSION,
            "model_id": MODEL_ID,
            "encoder": ENCODER_VERSION,
            "schema": SCHEMA_VERSION,
            "rules": crate::rules().rules,
            "backend": "rust-fallback",
            "legal_count": legal_moves.len(),
            "position": key,
            "seed": seed,
            "remaining_turn_budget": remaining_turn_budget.max(0),
            "budget_exhausted": remaining_turn_budget <= 0,
            "reused_branch": reused_branch,
            "fallback": true,
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn observation() -> Value {
        json!({
            "schema": SCHEMA_VERSION,
            "phase": "play",
            "turn_pid": 0,
            "turn_number": 1,
            "influence": [0, 0, 0, 0, 0],
            "captured_this_turn": [],
            "leader": {"owner": null, "level": 0},
            "board_sides": [1, 1, 1],
            "planet_bonus": [null, null, null, null, null],
            "technology_bonus": [null, null, null],
            "agent_discard": [],
            "bonus_discard": [],
            "mulligan_done": [],
            "pending_pid": null,
            "winner": null,
            "seat": 0,
            "players": [
                {"credits": 5, "zenithium": 2, "columns": [[], [], [], [], []], "technology": [0, 0, 0], "row_bonuses": [], "captured": [], "hand_count": 0, "hand": []},
                {"credits": 5, "zenithium": 2, "columns": [[], [], [], [], []], "technology": [0, 0, 0], "row_bonuses": [], "captured": [], "hand_count": 0}
            ],
            "agent_deck_count": 80,
            "bonus_deck_count": 8,
            "pending": null,
            "legal_moves": [
                {"action": "choose", "accept": false},
                {"action": "choose", "accept": true}
            ]
        })
    }

    #[test]
    fn serving_choice_is_legal_and_branch_reuse_is_bounded() {
        let obs = observation();
        let legal = vec![
            json!({"action": "choose", "accept": false}),
            json!({"action": "choose", "accept": true}),
        ];
        let first = choose_move(&obs, &legal, &Value::Null, 5_000, 17);
        let chosen = first.get("move").expect("a legal move");
        assert!(legal.iter().any(|move_| move_ == chosen));
        assert_eq!(first["memory"]["version"], json!(ABI_VERSION));
        assert!(first["memory"]["branches"].as_object().unwrap().len() <= MAX_BRANCHES);
        let second = choose_move(&obs, &legal, &first["memory"], 0, 99);
        assert_eq!(second["move"], first["move"]);
        assert_eq!(second["diagnostics"]["reused_branch"], json!(true));
    }

    #[test]
    fn serving_rejects_a_mismatched_advertised_action_list() {
        let mut obs = observation();
        obs["legal_moves"] = json!([{"action": "choose", "accept": false}]);
        let legal = vec![json!({"action": "choose", "accept": true})];
        assert_eq!(
            choose_move(&obs, &legal, &Value::Null, 0, 1)["error"],
            json!("Orbit serving legal-move list mismatch")
        );
    }
}
