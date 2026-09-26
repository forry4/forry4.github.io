/* Offline vs-AI driver for Dissonance — the client-side stand-in for main.py's
 * room server and its client-AI decision loop.
 *
 * The browser is the referee: the saved game IS `engine.py`'s game dict (dealt
 * and advanced by `classic.rs` through the wasm, which
 * `rust-cores/dissonance-core/tests/classic.rs` holds to the server move for
 * move), and every render comes from `odd_view` — the same per-seat payload
 * `engine.view_for` builds, so `Dissonance.jsx` cannot tell which referee it is
 * talking to.
 *
 * What main.py does that this mirrors:
 *  - **per-decision bot loop.** While the bot is to act, ask the engine for its
 *    view and arm `ai_search` exactly as the server does; the component's
 *    existing worker pool searches it and sinks the answer back through
 *    `applyOfflineDissonanceMove`. A decision with ONE legal answer is applied
 *    directly after a pause, so the bot does not spin up four workers to play
 *    its only card.
 *  - **move validation.** Every move — the human's and the bot's — goes through
 *    the wasm apply, which validates it against the same legality the room
 *    enforces and REFUSES rather than applies. An offline referee that trusted
 *    its inputs would be a worse game, not a faster one.
 *  - **the decision counter**, so a search answer that lands after the position
 *    moved on is dropped instead of played (the online staleness rule).
 *
 * ## THE ROUND IS PRICED HERE, NOT IN THE WASM
 *
 * `classic.rs` never scores: when the thirteenth trick lands it sets
 * `phase: "over"` and leaves `result` null. `finishRound` below builds the
 * result row and banks the match, through `pricing.js` — the client's ONE
 * mirror of `_terms_for`/`payoff`, already gated against Python by
 * `tests/test_bid_worth.py`. That keeps the price list in one place on this
 * side of the wire instead of three, and it is the same reason the online Hard
 * tier is handed `payoff_terms` as data rather than reimplementing it.
 *
 * ## CLASSIC ONLY
 *
 * The Rust referee refuses every other mode at the door (skat is a second
 * auction, minor is a different trick value, dummy needs a third hand this
 * crate cannot represent), so the hub offers classic and nothing else.
 */

import { dbPut, dbGet, dbDelete, dbList, requestPersistentStorage } from "../../shared/offline-db.js";
import { contractPrices, payoffFor } from "./pricing.js";

export const DIS_OFFLINE_AI_PID = "bot";
/** A flat floor between bot moves so its pace never leaks the device — the
 *  same reason the online client-AI path has `CLIENT_AI_MIN_MS`. */
const BOT_PAUSE_MS = 700;

const newLocalId = () =>
  "LOCAL" + Array.from({ length: 6 },
    () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 31)]).join("");

const seed32 = () => (Math.random() * 0x100000000) >>> 0;

// ─── The lazy engine worker ────────────────────────────────────────────────
//
// The SAME worker file the search pool uses, because it is the same wasm
// module — a second loader would put a second ~300KB instance of it in memory.
// This instance only ever issues referee calls (deal / apply / view).

let _engine = null;

function makeEngineWorker() {
  const url = `${import.meta.env.BASE_URL}wasm/dissonance-worker.js`;
  const w = new Worker(url, { type: "module" });
  const pending = new Map();
  let nextId = 1, readyRes;
  const ready = new Promise((r) => (readyRes = r));
  w.onmessage = (e) => {
    const d = e.data || {};
    if (d.ready !== undefined) { readyRes(!!d.ready); return; }
    const p = pending.get(d.id);
    if (p) { pending.delete(d.id); p(d); }
  };
  w.onerror = () => readyRes(false);
  return {
    async request(payload) {
      if (!(await ready)) {
        throw new Error("the game engine failed to load — go online once to download it");
      }
      const id = nextId++;
      const res = await new Promise((r) => { pending.set(id, r); w.postMessage({ ...payload, id }); });
      if (res.error) throw new Error(res.error);
      return res;
    },
  };
}

function engine(payload) {
  if (!_engine) _engine = makeEngineWorker();
  return _engine.request(payload);
}

/** Is this browser's cached artifact new enough to referee at all?
 *
 *  Probed by DEALING a throwaway round rather than by sniffing the export
 *  table: the worker is the only thing that can see the module, and an
 *  artifact that predates the referee answers with a plain error, which is
 *  what the hub turns into "go online once to update it". Fail-closed, per the
 *  repo's rule that a tier which cannot run must not be offered. */
export async function dissonanceOfflineReady() {
  try {
    await engine({ kind: "deal", seats: ["a", "b"], seed: 1, opener: 0, match: null });
    return true;
  } catch {
    return false;
  }
}

// ─── Records ───────────────────────────────────────────────────────────────

const aiSeatOf = (rec) => 1 - rec.mySeat;
export const dissonancePids = (rec, myId) =>
  rec.mySeat === 0 ? [myId, DIS_OFFLINE_AI_PID] : [DIS_OFFLINE_AI_PID, myId];

async function save(rec) {
  rec.updated = Date.now();
  await dbPut(rec);
  return rec;
}

export async function createOfflineDissonanceGame({ tier, myId }) {
  const mySeat = Math.random() < 0.5 ? 0 : 1;
  const rec = {
    id: newLocalId(),
    game: "dissonance",
    mySeat,
    tier,                       // "hard" | "expert" — the client-WASM tiers
    status: "playing",
    decisionSeq: 0,
    created: Date.now(),
    updated: Date.now(),
  };
  const pids = dissonancePids(rec, myId);
  // Seat 0 opens round 1, as it does online.
  const { g } = await engine({ kind: "deal", seats: pids, seed: seed32(), opener: 0, match: null });
  rec.g = g;
  await save(rec);
  requestPersistentStorage();
  return rec;
}

export const loadOfflineDissonanceGame = (id) => dbGet(id);
export const deleteOfflineDissonanceGame = (id) => dbDelete(id);
export const listOfflineDissonanceGames = async () =>
  (await dbList()).filter((r) => r.game === "dissonance");

// ─── Scoring: the one thing the wasm does not do ───────────────────────────

/** `engine._finish` + `_bank_round` + `_match_result_keys`, in JS.
 *
 *  Mutates `g` in place, exactly as the server does: fills `result`, adds the
 *  round to `match.scores`, appends the scorecard line and decides `match.over`.
 *  Every number comes out of `pricing.js`, so this file holds no price list.
 */
export function finishRound(g, catalog = null) {
  if (g.phase !== "over" || g.result) return g;
  const a = g.auction;
  const decl = a.declarer;
  const dpts = g.pts[decl];
  // NULL IS CHECKED FIRST AND WINS — taking no scoring trick is only reachable
  // with a non-positive total, so it can never coincide with a made contract.
  const nullMade = g.etricks[decl] === 0;
  const made = !nullMade && dpts >= a.level;
  const jump = a.jump || 0;
  const doubled = !!g.doubled;
  const prices = contractPrices(catalog, "classic");
  const p = prices.price(a.level, jump, doubled);
  const value = payoffFor(prices, { level: a.level, jump, doubled, pts: dpts, nullMade });
  // Exactly one side ever scores, which is what makes the signed payoff a
  // faithful single number (`engine._split`).
  const scores = [0, 0];
  scores[value >= 0 ? decl : 1 - decl] = Math.abs(value);

  const res = {
    ended_early: false,
    mode: "classic",
    declarer: decl,
    level: a.level,
    denom: a.denom,
    target: a.level,
    null: nullMade,
    null_value: prices.nullMake,
    doubled,
    // What the Double was actually worth: this same round, scored as if the
    // defender had let it stand. The panel narrates the difference the bet
    // made, so it needs the counterfactual rather than a base to compare.
    undoubled: payoffFor(prices, { level: a.level, jump, doubled: false, pts: dpts, nullMade }),
    jump,
    make_value: p.make,
    set_base: p.setBase,
    short_rate: p.short,
    ramp: p.ramp,
    declarer_pts: dpts,
    declarer_etricks: g.etricks[decl],
    made,
    short: nullMade || made ? 0 : a.level - dpts,
    over: made ? dpts - a.level : 0,
    over_bonus: p.over,
    scores,
  };

  const m = g.match;
  if (m) {
    m.scores[0] += scores[0];
    m.scores[1] += scores[1];
    m.over = Math.max(m.scores[0], m.scores[1]) >= m.target;
    (m.rounds = m.rounds || []).push(roundLine(g, m, res));
    Object.assign(res, {
      match_scores: [...m.scores],
      match_target: m.target,
      match_over: !!m.over,
      match_winner: m.scores[0] === m.scores[1] ? -1 : (m.scores[0] > m.scores[1] ? 0 : 1),
      round: m.round,
    });
  }
  g.result = res;
  return g;
}

/** One scorecard line, DERIVED from the result row — never re-read off the
 *  board, which would be a second copy of the scoring (`engine._round_summary`
 *  makes the same point). */
function roundLine(g, m, res) {
  return {
    round: m.round,
    declarer: res.declarer,
    level: res.level,
    denom: res.denom,
    target: res.target,
    pts: res.declarer_pts,
    made: res.made,
    null: res.null,
    doubling: res.doubled ? 2 : 1,
    scores: [...res.scores],
    deal: g.deal || null,
    reveal: {
      log: [...(g.auction.log || [])],
      shown_at_deal: [...(g.shown_at_deal || [])],
      swap_take: g.swap_take ?? null,
      swap_give: g.swap_give ?? null,
      looked: null,
    },
  };
}

// ─── Room data: the offline analog of broadcast_room ───────────────────────

export async function dissonanceOfflineRoomData(rec, myId, myName) {
  const pids = dissonancePids(rec, myId);
  const { view } = await engine({ kind: "view", g: rec.g, seat: rec.mySeat });
  return {
    room_id: rec.id,
    players: { [myId]: myName || "You", [DIS_OFFLINE_AI_PID]: "Bot" },
    host: myId,
    status: rec.status,
    vs_ai: true,
    ai_player: DIS_OFFLINE_AI_PID,
    ai_difficulty: rec.tier,
    mode: "classic",
    max_players: 2,
    offline: true,
    game: view,
  };
}

// ─── Applying a move ───────────────────────────────────────────────────────

/** Apply one move. `isAi` says whose seat it is for; everything is validated by
 *  the engine either way. Returns `{ok, rec}` or `{ok:false, err}`. */
export async function applyOfflineDissonanceMove(rec, move, myId, { isAi = false } = {}) {
  const pids = dissonancePids(rec, myId);
  const pid = isAi ? DIS_OFFLINE_AI_PID : myId;
  if (!pids.includes(pid)) return { ok: false, err: "not a seat in this game" };
  let g;
  try {
    ({ g } = await engine({ kind: "apply", g: rec.g, pid, move, seed: seed32() }));
  } catch (e) {
    return { ok: false, err: String(e?.message || e) };
  }
  rec.g = g;
  if (g.phase === "over" && !g.result) {
    finishRound(rec.g);
    // The MATCH ends the room, not the round: between rounds the game stays
    // playable so either seat can deal the next one.
    if (rec.g.match?.over) rec.status = "over";
  }
  return { ok: true, rec: await save(rec) };
}

/** Walking out. Banks nothing and closes the match, which is what the online
 *  forfeit does after paying it — offline there is nobody to pay. */
export async function abandonOfflineDissonanceGame(rec) {
  rec.status = "over";
  return save(rec);
}

// ─── The per-decision bot loop ─────────────────────────────────────────────

/** The offline analog of the server arming `ai_search` on each bot decision.
 *
 *  A single-legal decision applies directly after a pause (the server does the
 *  same — it only arms where the bot has a CHOICE, which is why the browser
 *  gate counts ARMED decisions rather than answers). A real decision arms the
 *  search and returns; the component's pool answers it and calls back in.
 *
 *  `publish(rec, aiSearch|null)` re-renders; `isCurrent()` cancels the loop
 *  when the screen or the game changes under it.
 */
export async function runDissonanceBotLoop(rec, myId, publish, isCurrent) {
  for (let step = 0; step < 80; step++) {
    if (!isCurrent() || rec.status === "over") return;
    const g = rec.g;
    const aiSeat = aiSeatOf(rec);
    // Between rounds nobody is on turn and the BOT NEVER DEALS — the result
    // panel stays up until a human presses Next round, exactly as online.
    if (g.phase === "over") return;
    const { view } = await engine({ kind: "view", g, seat: aiSeat });
    if (turnSeatOf(view) !== aiSeat) return;   // the human's turn — loop done
    if (!isCurrent()) return;

    const forced = onlyMove(view);
    if (forced) {
      await new Promise((r) => setTimeout(r, BOT_PAUSE_MS));
      if (!isCurrent()) return;
      const res = await applyOfflineDissonanceMove(rec, forced, myId, { isAi: true });
      if (!res.ok) { console.debug("[dissonance offline-AI] forced apply failed:", res.err); return; }
      rec = res.rec;
      await publish(rec, null);
      continue;
    }

    // A real decision → arm it and hand over to the pool. `payoff` is what the
    // ONLINE server ships from `engine.payoff_terms`; offline it comes from
    // pricing.js, the same numbers by the same gate.
    rec.decisionSeq += 1;
    await save(rec);
    const armed = {
      decision: rec.decisionSeq,
      seat: aiSeat,
      view,
      payoff: payoffTermsFor(g),
      budget_ms: 4000,
    };
    // A decision BEFORE trick 1 is priced from an option list rather than
    // searched as a card. `search` (Expert's tree payload) is deliberately
    // absent — see the tier note at the top of the hub's create row: offline
    // runs HARD, and a tier that cannot run must not be offered.
    if (view.phase === "auction" || view.phase === "double") {
      armed.auction = {
        phase: view.phase,
        // WHOEVER WOULD BE DECLARING under these options — NOT always the seat
        // being asked. At the Double the acting seat is the DEFENDER while the
        // options describe the declarer's settled contract, and the searcher
        // derives BOTH which side it solves for (the declarer leads trick 1)
        // and the SIGN it answers with from this one field. Naming the wrong
        // seat is the bug the server already paid for: two legal options, a
        // plausible number on each, and a Double taken about as often on
        // contracts that made as on ones that failed.
        declarer: view.phase === "double" ? view.auction.declarer : aiSeat,
        options: auctionOptions(view),
        pass: view.phase === "auction" && view.options?.may_pass ? { kind: "pass" } : null,
      };
    }
    await publish(rec, armed);
    return;
  }
}

/** A move the bot can always make without searching, for a decision whose
 *  answer the referee refused. Online, a decision the browser cannot answer
 *  is played by the SERVER bot (the per-decision fallback every client-served
 *  tier has); offline there is no server, and a refused answer used to leave
 *  the round frozen with nothing to press. This is that fallback: weak, legal,
 *  and never a stall. */
function fallbackMove(view) {
  if (view.phase === "swap") return { kind: "swap", take: null, give: null };
  if (view.phase === "double") return { kind: "double", on: false };
  if (view.phase === "play") return view.legal?.length ? { kind: "play", card: view.legal[0] } : null;
  if (view.phase === "auction") {
    if (view.options?.may_pass) return { kind: "pass" };
    const bid = view.options?.bids?.[0];
    return bid ? { kind: "bid", level: bid[0], denom: bid[1] } : null;
  }
  return null;
}

/** Play the bot's fallback move for the position as it stands. */
export async function applyOfflineBotFallback(rec, myId) {
  const { view } = await engine({ kind: "view", g: rec.g, seat: aiSeatOf(rec) });
  if (turnSeatOf(view) !== aiSeatOf(rec)) return { ok: false, err: "not the bot's turn" };
  const move = fallbackMove(view);
  if (!move) return { ok: false, err: `no fallback move in the ${view.phase} phase` };
  return applyOfflineDissonanceMove(rec, move, myId, { isAi: true });
}

/** Which seat must act, off the VIEW rather than the dict — the view is what
 *  the online path reads too, so there is one answer to "whose turn". */
function turnSeatOf(view) {
  if (view.phase === "auction") return view.auction.to_act;
  if (view.phase === "swap") return view.auction.declarer;
  if (view.phase === "double") return 1 - view.auction.declarer;
  if (view.phase === "play") return view.turn_seat;
  return -1;
}

/** The bot's only legal answer, or null when it has a real choice.
 *
 *  Under mandatory follow-suit most plays are forced, and the swap/Double
 *  prompts always have several — so this is what keeps four workers from
 *  spinning up to play a singleton, which is the same economy the server's
 *  "only arm where there is a choice" rule buys. */
function onlyMove(view) {
  // THE SWAP IS NEVER SEARCHED. Online it stays on the server bot on purpose
  // (`CLIENT_AI_PHASES` in main.py leaves it out: it is a choice about
  // information with no contract price the solver can search), so the browser
  // pool has no swap answer at all — handed one, it searched a CARD and the
  // referee refused "play card N" in the swap phase. That froze every offline
  // round the bot declared: nothing re-armed after the refusal. Offline has no
  // server bot to take it, so the bot stands pat, which is always legal. The
  // fitted swap (`bot.choose_swap`, `bid::SwapPolicy::choose` in the Rust core)
  // is worth ~+1.5 to a declarer and is the follow-up, not a reason to stall.
  if (view.phase === "swap") return { kind: "swap", take: null, give: null };
  if (view.phase === "play") {
    return view.legal?.length === 1 ? { kind: "play", card: view.legal[0] } : null;
  }
  if (view.phase === "auction") {
    const bids = view.options?.bids || [];
    if (!bids.length && view.options?.may_pass) return { kind: "pass" };
    if (bids.length === 1 && !view.options?.may_pass) {
      return { kind: "bid", level: bids[0][0], denom: bids[0][1] };
    }
  }
  return null;
}

/** `engine.auction_payoff_options`, in JS — every action open to the seat on
 *  turn, PRICED, each carrying ITS MOVE.
 *
 *  THE LIST IS POSITIONAL: its index is the pooling key across the worker pool
 *  and the answer that comes back, so it is built exactly once, here. The
 *  browser holds no rule — it picks an index and sends back the move it was
 *  handed, which is the same discipline the online server follows and the
 *  reason the searcher needs no offline branch.
 *
 *  PASSING IS PRICED, and it is the option both bots used to value at zero: a
 *  pass hands the standing contract to the OPPONENT at their price, so it is
 *  worth minus what that contract pays them. `opp` tells the search to solve
 *  the other seat declaring (they lead, worth ~0.93 points) and negate. Valuing
 *  it at zero is what makes a SACRIFICE unreachable — a sacrifice is a contract
 *  that prices negative, bought because passing prices worse.
 */
function auctionOptions(view, catalog = null) {
  const prices = contractPrices(catalog, "classic");
  const terms = (level, jump, doubled) => {
    const p = prices.price(level, jump, doubled);
    return {
      denom: 0, level, target: level, make: p.make, over: p.over,
      set_base: p.setBase, short: p.short, ramp: p.ramp, null: prices.nullMake,
    };
  };
  const out = [];
  if (view.phase === "auction") {
    const standing = view.auction.level;
    for (const [lvl, d] of view.options?.bids || []) {
      // Priced as "this bid buys the contract", i.e. as the FINAL bid, so the
      // jump it would arrive by is its own rise over the standing level (the
      // opening's rise is its whole level, per the v2 rule). Myopic on purpose.
      out.push({ ...terms(lvl, lvl - standing, false), denom: d,
                 move: { kind: "bid", level: lvl, denom: d } });
    }
    if (view.options?.may_pass) {
      out.push({ ...terms(standing, view.auction.jump || 0, !!view.doubled),
                 denom: view.auction.denom, opp: true, move: { kind: "pass" } });
    }
  } else if (view.phase === "double") {
    // BOTH BRANCHES ARE PRICED AS OPTIONS, because declining is not worth zero
    // — it is worth the undoubled contract, which is a live payoff either way.
    for (const on of [true, false]) {
      out.push({ ...terms(view.auction.level, view.auction.jump || 0, on),
                 denom: view.auction.denom, move: { kind: "double", on } });
    }
  }
  return out;
}

/** `engine.payoff_terms` for the settled contract, from pricing.js.
 *
 *  The searcher optimises the payoff the room will actually apply rather than
 *  the trick points that only measure it — which is what lets it duck for the
 *  Null consolation. Offline that rule has to be handed over the same way.
 */
export function payoffTermsFor(g, catalog = null) {
  const a = g.auction;
  if (!a || a.level <= 0) return null;
  const prices = contractPrices(catalog, "classic");
  const p = prices.price(a.level, a.jump || 0, !!g.doubled);
  return {
    denom: a.denom,
    level: a.level,
    target: a.level,
    make: p.make,
    over: p.over,
    set_base: p.setBase,
    short: p.short,
    ramp: p.ramp,
    null: prices.nullMake,
  };
}
