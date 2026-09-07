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
const MODEL_VERSION = 1;
const MODEL_ID = "orbit-hard-v1";
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

// Card attributes are supplied by the model manifest when a trained export is
// available.  The fallback only needs the public action shape; its score keeps
// conversion into influence/technology ahead of hoarding resources.
function score(observation, move) {
  const action = move?.action;
  let value = 0;
  const seat = Number(observation?.seat) || 0;
  const players = observation?.players || [];
  const me = players[seat] || {};
  const id = move?.card_id;
  const attrs = manifest?.cards?.[String(id)];
  if (attrs) {
    const fi = FACTIONS.indexOf(attrs.faction);
    const pi = PLANETS.indexOf(attrs.planet);
    const columns = me.columns || [];
    const n = pi >= 0 && Array.isArray(columns[pi]) ? columns[pi].length : 0;
    if (action === "recruit") {
      value += 0.42 * (1 - Math.max(0, Number(attrs.cost || 0) - n) / 10);
      const pos = observation.influence?.[pi];
      if (pos != null) value += 0.16 * Number(pos) * (seat === 0 ? 1 : -1) / 4;
      value += 0.04 * (n > 0 ? 1 : 0);
    } else if (action === "technology") {
      const level = Number(me.technology?.[fi] || 0);
      value += 0.25 + 0.035 * (5 - level);
    } else if (action === "leader") {
      value += 0.13 + ({ robot: 0.05, human: 0.04, animod: 0.045 }[attrs.faction] || 0);
    }
  } else if (action === "mulligan") {
    for (const cardId of (move.card_ids || [])) {
      const cost = Number(manifest?.cards?.[String(cardId)]?.cost ?? 5);
      value += 0.012 * (5 - cost);
    }
  }
  if (move?.planet) {
    const pi = PLANETS.indexOf(move.planet);
    const pos = observation.influence?.[pi];
    if (pos != null) value += 0.18 * Number(pos) * (seat === 0 ? 1 : -1) / 4;
  }
  for (const planet of (move?.planets || [])) {
    const pi = PLANETS.indexOf(planet);
    const pos = observation.influence?.[pi];
    if (pos != null) value += 0.08 * Number(pos) * (seat === 0 ? 1 : -1) / 4;
  }
  if (move?.accept === true) value += 0.025;
  if (move?.tier != null) value += 0.018 * Number(move.tier || 0);
  if (move?.cost) value += 0.01 * Number(move.cost);
  if (move?.branch != null) value -= 0.0005 * Number(move.branch || 0);
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
    const ties = values.filter((item) => Math.abs(item.value - best) < 1e-12).sort((a, b) => a.key.localeCompare(b.key));
    let state = (Number(seed) >>> 0) || 1;
    state = Math.imul(state ^ 0x9e3779b9, 1664525) + 1013904223;
    move = ties[(state >>> 0) % Math.max(1, ties.length)]?.candidate || legal[0];
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
