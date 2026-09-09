// Orbit Hard-tier serving worker.
//
// The worker speaks the same versioned boundary as games/orbit/ai/serving.py:
//   { kind:"choose", observation, legal_moves, memory,
//     remaining_turn_budget, seed }
//     -> { move, memory, diagnostics, abi_version, model_version }
//
// A future wasm-bindgen build may provide orbit_choose_move_json from
// orbit_core.js.  The dynamic import is feature-detected so a cached or
// development build without that optional asset still answers with the
// deterministic, observation-only fallback.  Server validation and its
// watchdog remain the authority in either case.

const ABI_VERSION = 1;
const MODEL_VERSION = 2;
const MODEL_ID = "orbit-hard-v2";
const ENCODER = "orbit-observation-v1";
const SCHEMA = 1;
const PLANETS = ["mercury", "venus", "terra", "mars", "jupiter"];
const FACTIONS = ["robot", "human", "animod"];
const MAX_MEMORY_BYTES = 64 * 1024;
const MAX_BRANCHES = 32;

let optionalWasm = null;
let manifest = null;
let readyResolve;
const ready = new Promise((resolve) => { readyResolve = resolve; });

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${stable(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function size(value) {
  try { return new TextEncoder().encode(JSON.stringify(value)).length; } catch { return MAX_MEMORY_BYTES + 1; }
}

function defaultMemory() { return { version: ABI_VERSION, branches: {}, history: { events: [] } }; }

function clone(value) {
  try {
    return typeof structuredClone === "function"
      ? structuredClone(value) : JSON.parse(JSON.stringify(value));
  } catch { return defaultMemory(); }
}

function normaliseMemory(value) {
  const out = value && typeof value === "object" && !Array.isArray(value) ? clone(value) : defaultMemory();
  if (Number(out.version ?? ABI_VERSION) !== ABI_VERSION) return defaultMemory();
  out.version = ABI_VERSION;
  if (!out.branches || typeof out.branches !== "object" || Array.isArray(out.branches)) out.branches = {};
  if (!out.history || typeof out.history !== "object") out.history = { events: [] };
  const keys = Object.keys(out.branches);
  if (keys.length > MAX_BRANCHES) out.branches = Object.fromEntries(keys.slice(-MAX_BRANCHES).map((k) => [k, out.branches[k]]));
  if (size(out) <= MAX_MEMORY_BYTES) return out;
  if (Array.isArray(out.history.events)) out.history.events = out.history.events.slice(-16);
  const short = Object.keys(out.branches).slice(-8);
  out.branches = Object.fromEntries(short.map((k) => [k, out.branches[k]]));
  return size(out) <= MAX_MEMORY_BYTES ? out : defaultMemory();
}

function card(observation, move) {
  const id = move && move.card_id;
  const cards = manifest?.cards;
  const value = cards && cards[String(id)];
  const players = observation?.players || [];
  const me = players[Number(observation?.seat) || 0] || {};
  return { card: value, me };
}

const DEFAULT_POLICY = {
  recruit: 0.55, progress: 0.08, cost: 0.0749, column: 0.03, effect: 0.6941,
  capture: 2.0, near_capture: 0.2, technology: 0.1945,
  technology_level: 0.0016, leader: 0.0457, leader_animod: 0.05,
  leader_owned: 0.1, mulligan: 0.01, choice: 0.4, choice_opponent: 0.1,
  deny: 0.2, choice_capture: 2.0, accept: 0.2, decline: -0.02, tier: 0.059,
  faction: 0.1, branch_influence: 0.2, branch_resource: 0.1, bonus: 0.1,
  discard: 0.02,
};
const DEFAULT_BONUS_VALUES = { 1: 1.0, 2: 1.2, 3: 4.0, 4: 2.0, 5: 1.5, 6: 2.0, 7: 2.0, 8: 2.0 };

function policyWeights() { return manifest?.policy || DEFAULT_POLICY; }

function position(observation, planet) {
  const pi = PLANETS.indexOf(planet);
  const raw = pi >= 0 ? observation?.influence?.[pi] : null;
  if (raw == null) return 0;
  const value = Number(raw);
  return Number.isFinite(value) ? value * (Number(observation?.seat) === 0 ? 1 : -1) : 0;
}

function effectValue(tasks, observation, me, them) {
  if (!Array.isArray(tasks)) return 0;
  let total = 0;
  const leaderOwner = observation?.leader?.owner;
  const seat = observation?.seat;
  for (const task of tasks) {
    if (!task || typeof task !== "object") continue;
    const kind = task.type;
    const amount = Number(task.amount || 0);
    if (kind === "influence") {
      total += PLANETS.includes(task.planet)
        ? 0.42 * amount * (1 + 0.14 * position(observation, task.planet)) : 0.48 * amount;
    } else if (kind === "influence_other") total += 0.45 * amount;
    else if (kind === "split_influence") total += 0.44 * (task.amounts || []).reduce((sum, value) => sum + Number(value || 0), 0);
    else if (kind === "adjacent_three") total += 0.42 * (Number(task.center || 0) + 2 * Number(task.neighbor || 0));
    else if (kind === "two_adjacent") total += 0.42 * 2 * amount;
    else if (kind === "all_planets") total += 0.38 * 5 * amount;
    else if (kind === "credits") total += 0.028 * amount;
    else if (kind === "zenithium") total += 0.09 * amount;
    else if (kind === "per_tech_first") total += 0.055 * (me.technology || []).filter((value) => Number(value) >= 1).length * amount;
    else if (kind === "per_nonempty") {
      const owner = task.owner === "self" ? me : them;
      total += 0.025 * (owner.columns || []).filter((column) => Array.isArray(column) && column.length).length * amount;
    } else if (kind === "mobilize") total += 0.10 * Number(task.count || 0);
    else if (kind === "transfer") total += 0.25 * Number(task.count || 0);
    else if (kind === "exile") total += 0.20 * Number(task.count || 0);
    else if (kind === "exile_tier") total += 0.28;
    else if (kind === "exile_for_matching") total += 0.28 * Number(task.count || 1);
    else if (kind === "optional_exile_each") total += 0.15 * (task.planets || []).length;
    else if (kind === "draw_bonus") total += 0.16;
    else if (kind === "develop") total += 0.18;
    else if (kind === "leader") total += 0.28 + (Number(task.level || 1) >= 2 ? 0.08 : 0);
    else if (kind === "take_board_bonus") total += 0.20;
    else if (kind === "spend_tier") total += 0.50;
    else if (kind === "discard_hand") total += 0.08;
    else if (kind === "reset_planet") total += 0.20;
    else if (kind === "choose_branch") {
      const values = (task.branches || []).map((branch) => effectValue(branch?.tasks, observation, me, them));
      total += values.length ? Math.max(...values) : 0;
    } else if (kind === "optional") total += 0.75 * effectValue(task.then, observation, me, them);
    else if (kind === "if_leader") total += (leaderOwner === seat ? 1 : 0.2) * effectValue(task.then, observation, me, them);
    else if (kind === "if_credits") total += (Number(me.credits || 0) >= Number(task.amount || 0) ? 1 : 0) * effectValue(task.then, observation, me, them);
    else if (kind === "transfer_each") total += 0.25 * (them.columns || []).filter((column) => Array.isArray(column) && column.length).length;
  }
  return total;
}

// Card attributes and effect programs are supplied by the versioned model
// manifest. The score remains an observation-only policy; the Python engine
// validates the selected action and owns every actual effect.
function score(observation, move) {
  const action = move?.action;
  const weights = policyWeights();
  let value = 0;
  const seat = Number(observation?.seat) || 0;
  const players = observation?.players || [];
  const me = players[seat] || {};
  const them = players[1 - seat] || {};
  const id = move?.card_id;
  const attrs = manifest?.cards?.[String(id)];
  const pending = observation?.pending || {};
  const task = pending.task || {};
  const taskType = task.type;
  if (attrs) {
    const fi = FACTIONS.indexOf(attrs.faction);
    const pi = PLANETS.indexOf(attrs.planet);
    const columns = me.columns || [];
    const n = pi >= 0 && Array.isArray(columns[pi]) ? columns[pi].length : 0;
    const progress = position(observation, attrs.planet);
    if (action === "recruit") {
      const cost = Math.max(0, Number(attrs.cost || 0) - n);
      value += weights.recruit + weights.progress * progress - weights.cost * cost
        + weights.column * (n > 0 ? 1 : 0)
        + weights.effect * effectValue(manifest?.card_effects?.[String(id)], observation, me, them);
      if (progress >= 3) value += weights.capture;
      else if (progress >= 2) value += weights.near_capture;
    } else if (action === "technology") {
      const level = Number(me.technology?.[fi] || 0);
      value += weights.technology + weights.technology_level * (5 - level);
    } else if (action === "leader") {
      value += weights.leader + weights.leader_animod * (attrs.faction === "animod" ? 1 : 0)
        + weights.leader_owned * ((observation?.leader?.owner) === seat ? 1 : 0);
    }
  } else if (action === "mulligan") {
    for (const cardId of (move.card_ids || [])) {
      const cost = Number(manifest?.cards?.[String(cardId)]?.cost ?? 5);
      value += weights.mulligan * (5 - cost);
    }
  }
  if (PLANETS.includes(move?.planet)) {
    const progress = position(observation, move.planet);
    value += weights.choice * progress;
    if (["transfer", "exile", "exile_for_matching"].includes(taskType)) {
      const pi = PLANETS.indexOf(move.planet);
      const opponentColumn = Array.isArray(them.columns?.[pi]) ? them.columns[pi].length : 0;
      value += weights.deny * opponentColumn - weights.choice_opponent * progress;
    }
    if (["influence", "influence_other", "split_influence"].includes(taskType)
      && progress + Number(task.amount || 1) >= 4) value += weights.choice_capture;
  }
  if (Array.isArray(move?.planets)) value += weights.choice * move.planets.reduce((sum, planet) => sum + position(observation, planet), 0);
  if (move?.accept === true) value += weights.accept;
  else if (move?.accept === false) value += weights.decline;
  if (move?.tier != null) value += weights.tier * Number(move.tier || 0);
  if (FACTIONS.includes(move?.faction)) {
    const fi = FACTIONS.indexOf(move.faction);
    value += weights.faction * (5 - Number(me.technology?.[fi] || 0));
  }
  if (move?.branch != null) {
    const branch = Number(move.branch || 0);
    const labels = Array.isArray(task.branch_labels) ? task.branch_labels : [];
    const label = String(labels[branch] || "").toLowerCase();
    value += /influence|transfer/.test(label) ? weights.branch_influence : weights.branch_resource;
  }
  if (move?.bonus_area) {
    const values = move.bonus_area === "planet" ? observation.planet_bonus : observation.technology_bonus;
    const labels = move.bonus_area === "planet" ? PLANETS : FACTIONS;
    const token = values?.[labels.indexOf(move.slot)];
    const bonusValues = manifest?.bonus_policy_values || DEFAULT_BONUS_VALUES;
    value += weights.bonus * Number(bonusValues[String(token)] || 0);
  }
  if (action === "choose" && move?.card_id != null) {
    value -= weights.discard * Number(manifest?.cards?.[String(move.card_id)]?.cost ?? 0);
  }
  return value;
}

function positionKey(observation, legal) {
  // This is a diagnostic/cache identity only. It contains policy-visible data;
  // the server independently computes and checks its own copy.
  let hash = 2166136261;
  for (const byte of new TextEncoder().encode(stable({ observation, legal_moves: legal }))) {
    hash ^= byte; hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function chooseFallback(observation, legal, memory, remaining, seed) {
  const outMemory = normaliseMemory(memory);
  const key = positionKey(observation, legal);
  const byKey = outMemory.branches[key];
  const legalByStable = new Map(legal.map((move) => [stable(move), move]));
  let move = byKey && legalByStable.get(stable(byKey.move));
  const reused = !!move;
  if (!move && legal.length) {
    const values = legal.map((candidate) => ({ candidate, value: score(observation, candidate), key: stable(candidate) }));
    const best = Math.max(...values.map((item) => item.value));
    const ties = values.filter((item) => Math.abs(item.value - best) < 1e-12)
      .sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
    // Every worker receives the same public position.  Use the stable final
    // action key so root-parallel voting reinforces the policy's tactical
    // choice instead of randomly splitting tied actions across workers.
    move = ties[ties.length - 1]?.candidate || legal[0];
  }
  if (move) {
    outMemory.branches[key] = { move: clone(move), model: MODEL_ID };
    const keys = Object.keys(outMemory.branches);
    if (keys.length > MAX_BRANCHES) outMemory.branches = Object.fromEntries(keys.slice(-MAX_BRANCHES).map((k) => [k, outMemory.branches[k]]));
  }
  return {
    move: move || null,
    memory: outMemory,
    diagnostics: {
      abi_version: ABI_VERSION, model_version: MODEL_VERSION, model_id: MODEL_ID,
      encoder: ENCODER, schema: SCHEMA, backend: "js-fallback", legal_count: legal.length,
      position: key, seed: Number(seed) || 0, remaining_turn_budget: Math.max(0, Number(remaining) || 0),
      budget_exhausted: Number(remaining) <= 0, reused_branch: reused, fallback: true,
    },
  };
}

(async () => {
  try {
    const response = await fetch(new URL("./orbit-model.json", import.meta.url), { cache: "no-store" });
    if (!response.ok) throw new Error(`model manifest ${response.status}`);
    manifest = await response.json();
    if (manifest.abi_version !== ABI_VERSION || manifest.model_version !== MODEL_VERSION
      || manifest.encoder !== ENCODER || manifest.schema !== SCHEMA) throw new Error("model manifest mismatch");
    // Optional generated glue. Development and a partially cached deploy can
    // omit this file; the worker remains usable through the safe fallback.
    try {
      const candidate = await import("./orbit_core.js");
      if (typeof candidate.default === "function") await candidate.default();
      // A partially cached glue module may load successfully while exposing
      // no serving export.  Treat that as unavailable so diagnostics never
      // claim WASM when the JS fallback is doing the work.
      if (typeof candidate.orbit_choose_move_json === "function"
        && typeof candidate.orbit_serving_manifest_json === "function") {
        const wasmManifest = JSON.parse(candidate.orbit_serving_manifest_json());
        const compatible = ["abi_version", "model_version", "encoder", "schema", "rules"]
          .every((key) => wasmManifest[key] === manifest[key]);
        optionalWasm = compatible ? candidate : null;
      } else optionalWasm = null;
    } catch { optionalWasm = null; }
    readyResolve(true);
    self.postMessage({ ready: true, abi_version: ABI_VERSION, model_version: MODEL_VERSION,
      encoder: ENCODER, schema: SCHEMA, rules: manifest.rules,
      backend: optionalWasm ? "wasm" : "js-fallback" });
  } catch (error) {
    readyResolve(false);
    self.postMessage({ ready: false, error: String(error) });
  }
})();

self.onmessage = async (event) => {
  const message = event.data || {};
  if (!message.kind) return;
  if (!(await ready)) { self.postMessage({ id: message.id, error: "model not loaded" }); return; }
  try {
    if (message.kind !== "choose") { self.postMessage({ id: message.id, error: "unknown Orbit worker request" }); return; }
    const observation = typeof message.observation === "string" ? JSON.parse(message.observation) : message.observation;
    const legal = typeof message.legal_moves === "string" ? JSON.parse(message.legal_moves) : (message.legal_moves || observation?.legal_moves || []);
    let answer = null;
    if (optionalWasm && typeof optionalWasm.orbit_choose_move_json === "function") {
      const raw = optionalWasm.orbit_choose_move_json(JSON.stringify(observation), JSON.stringify(legal), JSON.stringify(message.memory || {}), Number(message.remaining_turn_budget) || 0, Number(message.seed) || 0);
      answer = typeof raw === "string" ? JSON.parse(raw) : raw;
    }
    if (!answer || !answer.move) answer = chooseFallback(observation, legal, message.memory, message.remaining_turn_budget, message.seed);
    self.postMessage({ id: message.id, ...answer, abi_version: ABI_VERSION, model_version: MODEL_VERSION });
  } catch (error) {
    self.postMessage({ id: message.id, error: String(error) });
  }
};
