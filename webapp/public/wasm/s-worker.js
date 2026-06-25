// Variant-S search worker: runs the WASM determinized-PUCT search off the UI thread.
// Loaded as a MODULE worker; the wasm-pack (--target web) glue + .wasm sit beside this file.
//
// Protocol (main thread -> worker):  { id, state, seat, sims, seed }   (state = compact-state JSON string)
//          (worker -> main thread):  { ready: true } once init succeeds, then { id, move } | { id, error }
//                                     { ready: false, error } if the wasm fails to load (main thread falls
//                                     back to the server AI by simply never sending client_ai_ready).

import init, { choose_move } from "./spender_core.js";

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

init()
  .then(() => {
    readyResolve(true);
    self.postMessage({ ready: true });
  })
  .catch((err) => {
    readyResolve(false);
    self.postMessage({ ready: false, error: String(err) });
  });

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (msg.state == null) return; // not a search request
  const ok = await readyP;
  if (!ok) {
    self.postMessage({ id: msg.id, error: "wasm not loaded" });
    return;
  }
  try {
    const seed = BigInt(msg.seed >>> 0);
    const move = choose_move(String(msg.state), msg.seat >>> 0, msg.sims >>> 0, seed);
    self.postMessage({ id: msg.id, move });
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
