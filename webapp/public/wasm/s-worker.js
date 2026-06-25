// Variant-S search worker (ROOT-PARALLEL). Loaded as a MODULE worker; the wasm-pack (--target web)
// glue + .wasm sit beside this file. One of N identical workers — the main thread fans a seeded search
// to each, SUMS their root visit vectors, argmaxes, and asks one worker to convert the winner to a move.
//
// Protocol (main -> worker):
//   { id, kind:"search",  state, seat, budget, seed }  -> { id, visits:[70 ints] }
//   { id, kind:"convert", state, action }              -> { id, move }            (compact dict-move JSON)
// Lifecycle: { ready:true } once init succeeds, or { ready:false, error } if the wasm won't load
//   (the main thread then drops this worker; if none are ready it never announces client_ai_ready and
//   the server computes the move).

import init, { search_visits_timed, action_to_move_for } from "./spender_core.js";

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

init()
  .then(() => { readyResolve(true); self.postMessage({ ready: true }); })
  .catch((err) => { readyResolve(false); self.postMessage({ ready: false, error: String(err) }); });

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (!msg.kind) return;
  const ok = await readyP;
  if (!ok) { self.postMessage({ id: msg.id, error: "wasm not loaded" }); return; }
  try {
    if (msg.kind === "search") {
      const seed = BigInt(msg.seed >>> 0);
      const visits = search_visits_timed(String(msg.state), msg.seat >>> 0, Number(msg.budget), seed);
      self.postMessage({ id: msg.id, visits: Array.from(visits) });
    } else if (msg.kind === "convert") {
      const move = action_to_move_for(String(msg.state), msg.action >>> 0);
      self.postMessage({ id: msg.id, move });
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
