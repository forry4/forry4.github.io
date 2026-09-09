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
pub const MODEL_VERSION: u32 = 2;
pub const SCHEMA_VERSION: u32 = 1;
pub const ENCODER_VERSION: &str = "orbit-observation-v1";
pub const MODEL_ID: &str = "orbit-hard-v2";
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

fn position(observation: &Value, planet: Option<&Value>, seat: usize) -> f64 {
    let Some(index) = index_of(&PLANETS, planet) else {
        return 0.0;
    };
    let Some(value) = observation
        .get("influence")
        .and_then(Value::as_array)
        .and_then(|values| values.get(index))
        .filter(|value| !value.is_null())
    else {
        return 0.0;
    };
    number(Some(value)) * if seat == 0 { 1.0 } else { -1.0 }
}

fn effect_value(
    tasks: Option<&Value>,
    observation: &Value,
    me: &Value,
    them: &Value,
    seat: usize,
) -> f64 {
    let Some(tasks) = tasks.and_then(Value::as_array) else {
        return 0.0;
    };
    let leader_owner = observation
        .get("leader")
        .and_then(|leader| leader.get("owner"))
        .and_then(Value::as_u64)
        .map(|owner| owner as usize);
    let mut total = 0.0;
    for task in tasks {
        let Some(task) = task.as_object() else {
            continue;
        };
        let kind = task.get("type").and_then(Value::as_str).unwrap_or("");
        let amount = number(task.get("amount"));
        match kind {
            "influence" => {
                total += if task.get("planet").and_then(Value::as_str).is_some() {
                    0.42 * amount * (1.0 + 0.14 * position(observation, task.get("planet"), seat))
                } else {
                    0.48 * amount
                };
            }
            "influence_other" => total += 0.45 * amount,
            "split_influence" => {
                let sum = task
                    .get("amounts")
                    .and_then(Value::as_array)
                    .map(|values| values.iter().map(|value| number(Some(value))).sum::<f64>())
                    .unwrap_or(0.0);
                total += 0.44 * sum;
            }
            "adjacent_three" => {
                total += 0.42 * (number(task.get("center")) + 2.0 * number(task.get("neighbor")));
            }
            "two_adjacent" => total += 0.42 * 2.0 * amount,
            "all_planets" => total += 0.38 * 5.0 * amount,
            "credits" => total += 0.028 * amount,
            "zenithium" => total += 0.09 * amount,
            "per_tech_first" => {
                let developed = me
                    .get("technology")
                    .and_then(Value::as_array)
                    .map(|values| {
                        values
                            .iter()
                            .filter(|value| number(Some(value)) >= 1.0)
                            .count()
                    })
                    .unwrap_or(0);
                total += 0.055 * developed as f64 * amount;
            }
            "per_nonempty" => {
                let owner = if task.get("owner").and_then(Value::as_str) == Some("self") {
                    me
                } else {
                    them
                };
                let count = owner
                    .get("columns")
                    .and_then(Value::as_array)
                    .map(|columns| {
                        columns
                            .iter()
                            .filter(|column| {
                                column.as_array().is_some_and(|cards| !cards.is_empty())
                            })
                            .count()
                    })
                    .unwrap_or(0);
                total += 0.025 * count as f64 * amount;
            }
            "mobilize" => total += 0.10 * number(task.get("count")),
            "transfer" => total += 0.25 * number(task.get("count")),
            "exile" => total += 0.20 * number(task.get("count")),
            "exile_tier" => total += 0.28,
            "exile_for_matching" => {
                total += 0.28 * task.get("count").map_or(1.0, |value| number(Some(value)));
            }
            "optional_exile_each" => {
                total += 0.15
                    * task
                        .get("planets")
                        .and_then(Value::as_array)
                        .map_or(0, Vec::len) as f64;
            }
            "draw_bonus" => total += 0.16,
            "develop" => total += 0.18,
            "leader" => {
                total += 0.28
                    + if number(task.get("level")).max(1.0) >= 2.0 {
                        0.08
                    } else {
                        0.0
                    }
            }
            "take_board_bonus" => total += 0.20,
            "spend_tier" => total += 0.50,
            "discard_hand" => total += 0.08,
            "reset_planet" => total += 0.20,
            "choose_branch" => {
                let best = task
                    .get("branches")
                    .and_then(Value::as_array)
                    .map(|branches| {
                        branches
                            .iter()
                            .map(|branch| {
                                effect_value(branch.get("tasks"), observation, me, them, seat)
                            })
                            .fold(0.0, f64::max)
                    })
                    .unwrap_or(0.0);
                total += best;
            }
            "optional" => {
                total += 0.75 * effect_value(task.get("then"), observation, me, them, seat)
            }
            "if_leader" => {
                let factor = if leader_owner == Some(seat) { 1.0 } else { 0.2 };
                total += factor * effect_value(task.get("then"), observation, me, them, seat);
            }
            "if_credits" => {
                let factor = if number(me.get("credits")) >= amount {
                    1.0
                } else {
                    0.0
                };
                total += factor * effect_value(task.get("then"), observation, me, them, seat);
            }
            "transfer_each" => {
                let count = them
                    .get("columns")
                    .and_then(Value::as_array)
                    .map(|columns| {
                        columns
                            .iter()
                            .filter(|column| {
                                column.as_array().is_some_and(|cards| !cards.is_empty())
                            })
                            .count()
                    })
                    .unwrap_or(0);
                total += 0.25 * count as f64;
            }
            _ => {}
        }
    }
    total
}

pub(crate) fn score(observation: &Value, action: &Value) -> f64 {
    let action_name = action.get("action").and_then(Value::as_str).unwrap_or("");
    let seat = observation.get("seat").and_then(Value::as_u64).unwrap_or(0) as usize;
    let players = observation.get("players").and_then(Value::as_array);
    let me = players
        .and_then(|items| items.get(seat))
        .unwrap_or(&Value::Null);
    let them = players
        .and_then(|items| items.get(1 - seat))
        .unwrap_or(&Value::Null);
    let card_id = action.get("card_id").and_then(Value::as_u64);
    let card = card_id.and_then(|id| crate::rules().cards.get(&(id as u16)));
    let pending_task = observation
        .get("pending")
        .and_then(|pending| pending.get("task"))
        .unwrap_or(&Value::Null);
    let task_type = pending_task
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("");
    let mut result = 0.0;
    if let Some(card) = card {
        let planet_index = PLANETS
            .iter()
            .position(|value| *value == card.planet)
            .unwrap_or(0);
        let column_len = me
            .get("columns")
            .and_then(Value::as_array)
            .and_then(|columns| columns.get(planet_index))
            .and_then(Value::as_array)
            .map_or(0, Vec::len) as f64;
        let progress = position(observation, Some(&Value::String(card.planet.clone())), seat);
        match action_name {
            "recruit" => {
                let cost = (card.cost as f64 - column_len).max(0.0);
                result += 0.55 + 0.08 * progress - 0.0749 * cost
                    + if column_len > 0.0 { 0.03 } else { 0.0 };
                let card_tasks = crate::rules()
                    .card_effects
                    .get(&card.id)
                    .cloned()
                    .map(Value::Array);
                result += 0.6941 * effect_value(card_tasks.as_ref(), observation, me, them, seat);
                if progress >= 3.0 {
                    result += 2.0;
                } else if progress >= 2.0 {
                    result += 0.2;
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
                    .map_or(0.0, |value| number(Some(value)));
                result += 0.1945 + 0.0016 * (5.0 - level);
            }
            "leader" => {
                result += 0.0457 + 0.05 * (card.faction == "animod") as i32 as f64;
                let owner = observation
                    .get("leader")
                    .and_then(|leader| leader.get("owner"))
                    .and_then(Value::as_u64);
                result += 0.1 * (owner == Some(seat as u64)) as i32 as f64;
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
                result += 0.01 * (5.0 - cost);
            }
        }
    }
    if let Some(planet) = action.get("planet").and_then(Value::as_str) {
        let planet_value = position(observation, Some(&Value::String(planet.to_owned())), seat);
        result += 0.4 * planet_value;
        if matches!(task_type, "transfer" | "exile" | "exile_for_matching") {
            let index = PLANETS
                .iter()
                .position(|value| *value == planet)
                .unwrap_or(0);
            let opponent_column = them
                .get("columns")
                .and_then(Value::as_array)
                .and_then(|columns| columns.get(index))
                .and_then(Value::as_array)
                .map_or(0, Vec::len) as f64;
            result += 0.2 * opponent_column - 0.1 * planet_value;
        }
        if matches!(
            task_type,
            "influence" | "influence_other" | "split_influence"
        ) && planet_value + number(pending_task.get("amount")).max(1.0) >= 4.0
        {
            result += 2.0;
        }
    }
    if let Some(planets) = action.get("planets").and_then(Value::as_array) {
        result += 0.4
            * planets
                .iter()
                .map(|planet| position(observation, Some(planet), seat))
                .sum::<f64>();
    }
    if action.get("accept").and_then(Value::as_bool) == Some(true) {
        result += 0.2;
    }
    if action.get("accept").and_then(Value::as_bool) == Some(false) {
        result -= 0.02;
    }
    result += 0.059 * number(action.get("tier"));
    if let Some(faction) = action.get("faction").and_then(Value::as_str) {
        if let Some(index) = FACTIONS.iter().position(|value| *value == faction) {
            let level = me
                .get("technology")
                .and_then(Value::as_array)
                .and_then(|values| values.get(index))
                .map_or(0.0, |value| number(Some(value)));
            result += 0.1 * (5.0 - level);
        }
    }
    if let Some(branch) = action.get("branch").and_then(Value::as_u64) {
        let label = pending_task
            .get("branch_labels")
            .and_then(Value::as_array)
            .and_then(|labels| labels.get(branch as usize))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_ascii_lowercase();
        result += if label.contains("influence") || label.contains("transfer") {
            0.2
        } else {
            0.1
        };
    }
    if let Some(area) = action.get("bonus_area").and_then(Value::as_str) {
        let (values, labels): (Option<&Vec<Value>>, &[&str]) = if area == "planet" {
            (
                observation.get("planet_bonus").and_then(Value::as_array),
                &PLANETS,
            )
        } else {
            (
                observation
                    .get("technology_bonus")
                    .and_then(Value::as_array),
                &FACTIONS,
            )
        };
        if let (Some(values), Some(index)) = (values, index_of(labels, action.get("slot"))) {
            let token = values.get(index).and_then(Value::as_u64).unwrap_or(0);
            let bonus = match token {
                1 => 1.0,
                2 => 1.2,
                3 => 4.0,
                4 => 2.0,
                5 => 1.5,
                6..=8 => 2.0,
                _ => 0.0,
            };
            result += 0.1 * bonus;
        }
    }
    if action_name == "choose" {
        if let Some(id) = card_id {
            let cost = crate::rules()
                .cards
                .get(&(id as u16))
                .map_or(0.0, |card| card.cost as f64);
            result -= 0.02 * cost;
        }
    }
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
        // Root-parallel workers all see the same public position.  Keep their
        // decision stable so voting reinforces a tactical tie instead of
        // randomly splitting it between equivalent branches.
        index = ties.last().map(|item| item.2);
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
