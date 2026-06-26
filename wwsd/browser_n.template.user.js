// ==UserScript==
// @name         WWSD Browser-N (Steve runs in your browser)
// @namespace    wwsd
// @version      0.8.1
// @description  Runs Splendor variant N (the learned-leaf AI) entirely in YOUR browser via WASM on the friend's spendee site — no server. Shows N's recommended move, position eval, and top alternatives; optional autoplay.
// @match        https://spendee.mattle.online/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==
//
// This file is ASSEMBLED by wwsd/build_browser_n.py — it inlines the wasm-pack (--target no-modules)
// glue + the 101-feature variant-N wasm (base64) so there is NO hosting, CORS, or fetch dependency.
// Edit the LOGIC here; re-run the build script to regenerate wwsd_browser_n.user.js. (The browser
// needs CSP `script-src 'wasm-unsafe-eval'` for WASM; a hobby Meteor app typically allows it.)
//
(function () {
  'use strict';

  // ─────────────────────────────────────────────────────────────────────────
  // CONFIG
  // ─────────────────────────────────────────────────────────────────────────
  const CONFIG = {
    THINK_SECS: 3.0,    // wall-clock budget (NB: ignored inside the wasm — MAX_SIMS is the real cap)
    MAX_SIMS:   3000,   // hard sim cap per move — keeps each search short (~2-3s) so the page can't freeze
    MY_NAME:    '',     // your spendee display name; blank = auto via Meteor.userId()
    AUTO_PLAY:  false,  // execute the move (needs the SITE ADAPTER wired); false = advisor overlay only
    AUTO_START: false,  // when no game is active, auto-create a fresh vs-CPU game (full hands-off loop)
    SPEED:      'fast', // auto-created game timer: 'fast' | 'normal' | 'slow'
    TARGET:     '15',   // auto-created game target score: '15' | '21'
    POLL_MS:    1500,
    OPEN_MS:    900,    // wait after a click that OPENS a modal, before clicking inside it (site animation)
    STEP_MS:    420,    // base gap between in-modal clicks (a little jitter is added) — raise if the site lags
    HOLD_MS:    1600,   // press-and-hold duration for the Reserve button — raise if a reserve doesn't register
    MIN_DELAY_MS: 2000, // autoplay pacing: each turn takes a RANDOM MIN..MAX ms total (compute counts toward it),
    MAX_DELAY_MS: 4000, // so it never plays instantly — looks like a person thinking 2-4s
    ENABLED:    true,   // master switch (auto-analyzes on your turn) — toggle from the panel
    REGULAR_JOB: 'SPENDEE_REGULAR',
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Friend's deck tables (from wwsd_defs.json) — index → bonus colour / points; noble → points.
  // Used to build the engine State dump (bonuses + score) the WASM consumes.
  // ─────────────────────────────────────────────────────────────────────────
  const BONUS = [0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,3,3,3,3,3,3,3,3,4,4,4,4,4,4,4,4,0,0,0,0,0,0,1,1,1,1,1,1,2,2,2,2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4];
  const PTS   = [0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,2,3,1,2,1,2,2,3,1,2,1,2,2,3,1,1,2,2,2,3,1,2,1,2,2,3,1,2,1,2,4,5,4,3,4,5,4,3,4,5,4,3,4,5,4,3,4,5,4,3];
  const NOBLE_PTS = [3,3,3,3,3,3,3,3,3,3];

  // CRITICAL: the friend's spendee deck and OUR compiled WASM (Spender) deck contain the same 90
  // cards but in COMPLETELY DIFFERENT index order — only the multiset matches (89 cards map exactly;
  // friend #3 [2 blue/2 black, white bonus] has no exact twin → mapped to its nearest, Spender #36
  // [2 blue/2 green]). The WASM looks up card COST/BONUS/PTS by index from ITS deck, so we MUST
  // translate every friend card id → Spender id before handing the dump to the engine (the Python
  // WWSD did this by override_engine(); the WASM can't be overridden). F2S[friendId] = spenderId.
  const F2S = [35,33,34,36,39,37,32,38,8,12,10,14,15,9,13,11,16,22,19,17,23,20,21,18,26,24,29,30,31,28,27,25,1,4,0,2,7,5,6,3,67,69,64,66,65,68,49,51,46,50,47,48,55,57,53,52,54,56,62,63,59,60,58,61,43,45,40,42,41,44,87,89,88,86,75,77,76,74,80,81,79,78,83,85,84,82,71,73,72,70];
  const F2S_NOBLE = [7,9,8,5,6,3,2,1,0,4];   // nobles are reordered too; engine NOBLE_REQ is looked up by id
  const remapId = ci => (ci == null || ci < 0) ? ci : F2S[ci];   // friend → Spender (engine) space
  const remapNoble = ni => (ni == null || ni < 0) ? ni : F2S_NOBLE[ni];
  // Friend's TRUE per-card costs (wwsd_defs.json), friend-index space — for the affordability guard
  // that closes the one inexact (#3) card and any future deck drift.
  const COST_F = [[0,3,0,0,0],[0,0,0,2,1],[0,1,1,1,1],[0,2,0,0,2],[0,0,4,0,0],[0,1,2,1,1],[0,2,2,0,1],[3,1,0,0,1],[1,0,0,0,2],[0,0,0,0,3],[1,0,1,1,1],[0,0,2,0,2],[0,0,0,4,0],[1,0,1,2,1],[1,0,2,2,0],[0,1,3,1,0],[2,1,0,0,0],[0,0,0,3,0],[1,1,0,1,1],[0,2,0,2,0],[0,0,0,0,4],[1,1,0,1,2],[0,1,0,2,2],[1,3,1,0,0],[0,2,1,0,0],[3,0,0,0,0],[1,1,1,0,1],[2,0,0,2,0],[4,0,0,0,0],[2,1,1,0,1],[2,0,1,0,2],[1,0,0,1,3],[0,0,2,1,0],[0,0,3,0,0],[1,1,1,1,0],[2,0,2,0,0],[0,4,0,0,0],[1,2,1,1,0],[2,2,0,1,0],[0,0,1,3,1],[0,0,0,5,0],[6,0,0,0,0],[0,0,3,2,2],[0,0,1,4,2],[2,3,0,3,0],[0,0,0,5,3],[0,5,0,0,0],[0,6,0,0,0],[0,2,2,3,0],[2,0,0,1,4],[0,2,3,0,3],[5,3,0,0,0],[0,0,5,0,0],[0,0,6,0,0],[2,3,0,0,2],[3,0,2,3,0],[4,2,0,0,1],[0,5,3,0,0],[0,0,0,0,5],[0,0,0,6,0],[2,0,0,2,3],[1,4,2,0,0],[0,3,0,2,3],[3,0,0,0,5],[5,0,0,0,0],[0,0,0,0,6],[3,2,2,0,0],[0,1,4,2,0],[3,0,3,0,2],[0,0,5,3,0],[0,0,0,0,7],[3,0,0,0,7],[3,0,0,3,6],[0,3,3,5,3],[7,0,0,0,0],[7,3,0,0,0],[6,3,0,0,3],[3,0,3,3,5],[0,7,0,0,0],[0,7,3,0,0],[3,6,3,0,0],[5,3,0,3,3],[0,0,7,0,0],[0,0,7,3,0],[0,3,6,3,0],[3,5,3,0,3],[0,0,0,7,0],[0,0,0,7,3],[0,0,3,6,3],[3,3,5,3,0]];
  // Can `seat` afford friend card `ci` from its tokens+bonuses+gold? (true Splendor rule.)
  function affordFriend(dump, seat, ci) {
    if (ci == null || ci < 0) return false;
    const tok = dump.tokens[seat], bon = dump.bonuses[seat], cost = COST_F[ci];
    let need = 0;
    for (let c = 0; c < 5; c++) need += Math.max(0, cost[c] - (bon[c] || 0) - (tok[c] || 0));
    return need <= (tok[5] || 0);
  }
  // Is action `a` actually affordable in the REAL (friend) game? Non-buys are always "affordable".
  function actionAffordable(dump, a) {
    if (a >= 46 && a < 58) return affordFriend(dump, dump.turn, dump.board[a - 46]);
    if (a >= 58) return affordFriend(dump, dump.turn, (dump.reserved[dump.turn] || [])[a - 58]);
    return true;
  }

  // Engine constants (mirror games/spender/ai/az/engine.py + the Rust engine)
  const PLAY = 0, WIN_NONE = -1, A_PASS = 30;
  const G = ['white', 'blue', 'green', 'red', 'black'];
  const C3 = []; for (let a = 0; a < 5; a++) for (let b = a + 1; b < 5; b++) for (let c = b + 1; c < 5; c++) C3.push([a, b, c]);
  const C2 = []; for (let a = 0; a < 5; a++) for (let b = a + 1; b < 5; b++) C2.push([a, b]);

  // ─────────────────────────────────────────────────────────────────────────
  // Inlined WASM (no-modules glue defines `wasm_bindgen`; the .wasm is base64 below)
  // ─────────────────────────────────────────────────────────────────────────
  //__GLUE__
  const WASM_B64 = "__WASM_B64__";
  let _wasmReady = null;
  function _b64bytes(b64) {
    const bin = atob(b64);
    const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  function loadWasm() {
    if (!_wasmReady) _wasmReady = wasm_bindgen({ module_or_path: _b64bytes(WASM_B64) }).then(() => wasm_bindgen);
    return _wasmReady;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // spendee `data` → engine State dump (port of wwsd/analyze.py to_state)
  // card ids & colours are identity (their index == our engine card id).
  // ─────────────────────────────────────────────────────────────────────────
  function toDump(data, winPoints) {
    const bank = data.bank, players = data.players;
    const d = {
      bank: bank.chips.slice(0, 5).concat([bank.goldChips || 0]),
      tokens: [], bonuses: [], points: [], purchased_n: [],
      purchased: [], reserved: [], reserved_blind: [], nobles_won: [],
      board: [], decks: [], nobles: [],
      turn: data.state.currentPlayerIndex | 0, phase: PLAY, pending_nobles: [],
      final_trigger: -1, winner: WIN_NONE, ply: 0, win_points: winPoints | 0,
    };
    for (let seat = 0; seat < 2; seat++) {
      const p = players[seat];
      d.tokens.push(p.chips.slice(0, 5).concat([p.goldChips || 0]));
      const b = [0, 0, 0, 0, 0];
      for (const ci of p.purchasedCards) b[BONUS[ci]]++;
      d.bonuses.push(b);
      let pts = 0;
      for (const ci of p.purchasedCards) pts += PTS[ci];
      for (const ni of p.nobles) pts += NOBLE_PTS[ni];
      d.points.push(pts);
      d.purchased_n.push(p.purchasedCards.length);
      d.purchased.push(p.purchasedCards.slice());
      d.reserved.push(p.reservedCards.slice());
      d.reserved_blind.push(p.reservedCards.map(() => false));
      d.nobles_won.push(p.nobles.slice());
    }
    for (let lvl = 0; lvl < 3; lvl++) for (const slot of bank.showedCards[lvl]) d.board.push(slot == null ? -1 : slot);
    for (let lvl = 0; lvl < 3; lvl++) d.decks.push(bank.hiddenCards[lvl].slice());
    d.nobles = bank.nobles.concat([-1, -1, -1]).slice(0, 3);
    return d;
  }

  // Translate a friend-space dump → Spender(engine)-space for the WASM: remap every card id so the
  // engine's compiled COST/BONUS/PTS tables describe the SAME physical cards. Seats/tokens/points are
  // unchanged (card identity is preserved by the bijection). The original (friend-space) dump is kept
  // for display + execution — action indices are positional/by-slot, so they line up across both spaces.
  function toEngineDump(dump) {
    const e = JSON.parse(JSON.stringify(dump));
    e.board = dump.board.map(remapId);
    e.decks = dump.decks.map(lvl => lvl.map(remapId));
    e.purchased = dump.purchased.map(seat => seat.map(remapId));
    e.reserved = dump.reserved.map(seat => seat.map(remapId));
    e.nobles = dump.nobles.map(remapNoble);                 // board nobles: friend → Spender id
    e.nobles_won = dump.nobles_won.map(seat => seat.map(remapNoble));
    return e;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // action index → human text + machine move (ports of _describe_move / _structured_move)
  // ─────────────────────────────────────────────────────────────────────────
  function _cardLabel(ci) {
    if (ci == null || ci < 0) return '?';
    const lvl = ci < 40 ? 1 : ci < 70 ? 2 : 3;
    return `L${lvl} ${G[BONUS[ci]]} ${PTS[ci]}pt`;
  }
  function describeMove(dump, a) {
    if (a < 10) return 'Take 3: ' + C3[a].map(i => G[i]).join(', ');
    if (a < 20) return 'Take 2: ' + C2[a - 10].map(i => G[i]).join(', ');
    if (a < 25) return 'Take 1: ' + G[a - 20];
    if (a < 30) return 'Take 2 ' + G[a - 25] + ' (same)';
    if (a === 30) return 'Pass';
    if (a < 43) { const s = a - 31; return `Reserve L${(s / 4 | 0) + 1} #${s % 4 + 1}: ${_cardLabel(dump.board[s])}`; }
    if (a < 46) return `Reserve from L${a - 43 + 1} deck`;
    if (a < 58) { const s = a - 46; return `Buy L${(s / 4 | 0) + 1} #${s % 4 + 1}: ${_cardLabel(dump.board[s])}`; }
    const ri = a - 58; return `Buy reserved #${ri + 1}: ${_cardLabel((dump.reserved[dump.turn] || [])[ri])}`;
  }
  function structuredMove(dump, a) {
    if (a < 10) return { kind: 'take3', colors: C3[a].slice(), color_names: C3[a].map(i => G[i]) };
    if (a < 20) return { kind: 'take2_diff', colors: C2[a - 10].slice(), color_names: C2[a - 10].map(i => G[i]) };
    if (a < 25) { const c = a - 20; return { kind: 'take1', colors: [c], color_names: [G[c]] }; }
    if (a < 30) { const c = a - 25; return { kind: 'take2_same', color: c, colors: [c, c], color_names: [G[c]] }; }
    if (a === 30) return { kind: 'pass' };
    if (a < 43) { const s = a - 31; return { kind: 'reserve_board', level: (s / 4 | 0) + 1, slot: s, col: s % 4, card_id: dump.board[s] }; }
    if (a < 46) return { kind: 'reserve_deck', level: a - 43 + 1 };
    if (a < 58) { const s = a - 46; return { kind: 'buy_board', level: (s / 4 | 0) + 1, slot: s, col: s % 4, card_id: dump.board[s] }; }
    const ri = a - 58; return { kind: 'buy_reserved', reserved_index: ri, card_id: (dump.reserved[dump.turn] || [])[ri] };
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Meteor / games-doc helpers
  // ─────────────────────────────────────────────────────────────────────────
  function meteorReady() { return typeof window.Meteor !== 'undefined' && window.Meteor.connection; }
  function fetchGames() {
    try { return window.Meteor.connection._mongo_livedata_collections['games'].find().fetch(); } catch (e) { return []; }
  }
  function findMySeat(g) {
    const uid = (function () { try { return window.Meteor.userId(); } catch (e) { return null; } })();
    const players = g.players || [];
    for (let i = 0; i < players.length; i++) {
      const p = players[i] || {};
      if (uid && (p.userId === uid || p._id === uid || p.id === uid)) return i;
    }
    if (CONFIG.MY_NAME) for (let i = 0; i < players.length; i++) if ((players[i] || {}).name === CONFIG.MY_NAME) return i;
    return -1;
  }
  function findMyActiveGame() {
    for (const g of fetchGames()) {
      if (g.status !== 'INPROGRESS') continue;
      const seat = findMySeat(g);
      if (seat >= 0) return { game: g, seat };
    }
    return null;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Run variant N locally and shape the result like WWSD's /move response.
  // ─────────────────────────────────────────────────────────────────────────
  async function analyzePosition(game, seat) {
    const data = game.data;
    const winPoints = parseInt((game.settings || {}).targetScore) || 15;
    const dump = toDump(data, winPoints);           // friend-space (for display + execution)
    const engineDump = toEngineDump(dump);           // Spender-space (correct costs for the WASM)
    const wb = await loadWasm();
    const seed = BigInt(((Date.now() >>> 0) ^ (seat << 28)) >>> 0);
    const raw = wb.search_n_full_timed(JSON.stringify(engineDump), seat >>> 0, CONFIG.THINK_SECS * 1000, CONFIG.MAX_SIMS >>> 0, seed);
    const d = JSON.parse(raw);
    if (d.error) throw new Error('N error: ' + d.error);
    const tot = d.visits.reduce((a, b) => a + b, 0);
    // Drop any buy the engine liked that isn't actually affordable in the REAL game (guards the one
    // inexact remap card + any deck drift) — never recommend a move you can't pay for.
    const order = d.visits.map((v, a) => [a, v]).filter(x => x[1] > 0 && actionAffordable(dump, x[0]))
      .sort((a, b) => b[1] - a[1]);
    const top = order.length ? order[0][0] : A_PASS;
    const denom = tot || 1;
    return {
      dump, seat, sims: tot, value: d.value,
      recommendation: describeMove(dump, top), rec_eval: d.q[top], action: structuredMove(dump, top),
      alternatives: order.slice(1, 6).map(([a, v]) => ({
        pct: +(100 * v / denom).toFixed(1), text: describeMove(dump, a), eval: d.q[a], action: structuredMove(dump, a),
      })),
    };
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SITE ADAPTER — only needed for AUTO_PLAY. Discover spendee's Meteor methods
  // (Object.keys(Meteor.connection._methodHandlers) + record manual moves), then wire these.
  // ═══════════════════════════════════════════════════════════════════════════
  function callMeteor(name, ...args) {
    return new Promise((resolve, reject) => window.Meteor.call(name, ...args, (e, r) => (e ? reject(e) : resolve(r))));
  }
  const ADAPTER_TODO = '__WWSD_ADAPTER_NOT_WIRED__';

  // Spendee move = insert into the `gameActions` collection (the method its own UI fires:
  // /gameActions/insert). The envelope is constant; only `action` varies.
  // Meteor-style 17-char client id (the UI generates one for each insert; the method needs it).
  function _meteorId() {
    try { if (window.Random && window.Random.id) return window.Random.id(); } catch (e) {}
    const cs = '23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz';
    let s = ''; for (let i = 0; i < 17; i++) s += cs[Math.floor(Math.random() * cs.length)];
    return s;
  }
  function spendeeAction(seat, action) {
    switch (action.kind) {
      case 'take3': case 'take2_diff': case 'take2_same': case 'take1': {
        const chips = [0, 0, 0, 0, 0];             // per-colour COUNT, our colour order (white..black)
        for (const c of action.colors) chips[c]++;
        return { type: 'pickChips', playerIndex: seat, chips };
      }
      case 'buy_board': case 'buy_reserved':
        return { type: 'buyCard', playerIndex: seat, cardIndex: action.card_id };       // cardIndex = spendee card id
      case 'reserve_board':
        return { type: 'reserveShowedCard', playerIndex: seat, cardIndex: action.card_id };
      case 'reserve_deck':
        return { type: 'reserveHiddenCard', playerIndex: seat, level: action.level - 1 }; // confirmed: 0-indexed level
      case 'pass':
        return { type: 'pass', playerIndex: seat };                                     // (unconfirmed shape)
      default: throw new Error('unmapped action: ' + action.kind);
    }
  }
  let _lastIds = null;   // {gameId, gameManagerId} from the last observed insert (fallback only)
  async function playAction(g, action) {
    const seat = ((g.data && g.data.state) || {}).currentPlayerIndex;
    const ids = _lastIds || {};
    const gameId = g.gameId || g._id || ids.gameId;                                   // the CURRENT game first
    const gameManagerId = g.gameManagerId || (g.data && g.data.gameManagerId) || ids.gameManagerId;
    if (gameId == null || gameManagerId == null) throw new Error('no gameId/gameManagerId');
    const doc = {
      _id: _meteorId(), gameId, gameManagerId, playerIndex: seat, isFromPlayer: true,
      action: spendeeAction(seat, action), isDummy: false, createdAt: Date.now(),
    };
    // CRITICAL: call the server METHOD the UI fires. collection.insert on the raw minimongo store
    // (_mongo_livedata_collections) is LOCAL-ONLY and never reaches the server — that was the bug.
    return new Promise((res, rej) => window.Meteor.call('/gameActions/insert', doc, (e, r) => (e ? rej(e) : res(r))));
  }
  function listMethods() {
    try { const n = Object.keys(window.Meteor.connection._methodHandlers).sort(); console.log('[WWSD] methods', n); return n; }
    catch (e) { return []; }
  }
  // One permanent hook on Meteor's method send: always caches gameId/gameManagerId from any
  // gameActions insert (yours, the opponent's, or the CPU's), and logs everything while recording.
  let _recording = false, _applyHooked = false;
  function installApplyHook() {
    if (_applyHooked || !meteorReady()) return;
    _applyHooked = true;
    const c = window.Meteor.connection, orig = c.apply.bind(c);
    c.apply = function (n, a, o, cb) {
      if (n === '/gameActions/insert' && a && a[0] && a[0].gameId != null) _lastIds = { gameId: a[0].gameId, gameManagerId: a[0].gameManagerId };
      if (_recording) { try { console.log('[WWSD] call →', n, JSON.parse(JSON.stringify(a))); } catch (e) {} }
      return orig(n, a, o, cb);
    };
  }
  function toggleRecord() { _recording = !_recording; console.log('[WWSD] record', _recording ? 'ON' : 'OFF'); return _recording; }

  // ── DOM-click recorder (discovery for UI autoplay) ──────────────────────────
  // Logs a compact descriptor of every element you click, so we can learn spendee's selectors for
  // tokens / cards / buy / reserve / confirm and write the click adapter from real evidence.
  function _elDesc(el) {
    if (!el || el.nodeType !== 1) return String(el);
    const tag = el.tagName.toLowerCase();
    const id = el.id ? '#' + el.id : '';
    const cls = (typeof el.className === 'string' && el.className.trim()) ? '.' + el.className.trim().split(/\s+/).join('.') : '';
    const data = [...el.attributes].filter(a => a.name.startsWith('data-') || ['role', 'aria-label', 'title', 'alt', 'name', 'value'].includes(a.name))
      .map(a => `[${a.name}=${JSON.stringify(a.value)}]`).join('');
    const txt = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 32);
    const bg = (el.style && el.style.backgroundColor) || '';
    const r = el.getBoundingClientRect();
    return `${tag}${id}${cls}${data}${bg ? ' bg=' + bg : ''}${txt ? ' "' + txt + '"' : ''} @${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}`;
  }
  // The whole game is drawn on ONE <canvas> (div.board > canvas) — clicks are hit-tested internally by
  // pixel position. So we record click COORDINATES as a FRACTION of the canvas (resize-independent) and
  // replay moves by dispatching synthetic pointer/mouse events at those fractions.
  function boardCanvas() {
    return document.querySelector('.board canvas') || document.querySelector('canvas');
  }
  let _domRecording = false, _domHooked = false;
  function installClickRecorder() {
    if (_domHooked) return;
    _domHooked = true;
    document.addEventListener('click', (ev) => {
      if (!_domRecording) return;
      const cv = boardCanvas();
      let frac = '';
      if (cv) {
        const r = cv.getBoundingClientRect();
        frac = ` canvasFrac=(${((ev.clientX - r.left) / r.width).toFixed(4)},${((ev.clientY - r.top) / r.height).toFixed(4)})` +
               ` cv=${Math.round(r.width)}x${Math.round(r.height)}@${Math.round(r.left)},${Math.round(r.top)}`;
      }
      console.log(`[WWSD-DOM] CLICK @client(${ev.clientX},${ev.clientY})${frac}  ${_elDesc(ev.target)}`);
    }, true);
  }
  function toggleDomRecord() { _domRecording = !_domRecording; console.log('[WWSD-DOM] click-record', _domRecording ? 'ON — click each gem/card/button; canvasFrac is what matters' : 'OFF'); return _domRecording; }

  // Dispatch a synthetic click at a canvas FRACTION (fx,fy in 0..1). Returns the client coords used.
  // We fire the full pointer+mouse sequence because canvas engines listen on various ones. NOTE: synthetic
  // events have isTrusted=false; if the engine ignores them, UI-autoplay is impossible (test this FIRST).
  function synthClickCanvas(fx, fy) {
    const cv = boardCanvas();
    if (!cv) { console.warn('[WWSD] no board canvas'); return null; }
    const r = cv.getBoundingClientRect();
    const x = r.left + fx * r.width, y = r.top + fy * r.height;
    const base = { bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y,
      screenX: x, screenY: y, button: 0, buttons: 1, pointerId: 1, pointerType: 'mouse', isPrimary: true };
    const fire = (type, Ctor) => cv.dispatchEvent(new Ctor(type, type.startsWith('pointer') ? base : base));
    try { fire('pointerover', PointerEvent); fire('pointerenter', PointerEvent); fire('pointerdown', PointerEvent); } catch (e) {}
    fire('mousedown', MouseEvent);
    try { fire('pointerup', PointerEvent); } catch (e) {}
    fire('mouseup', MouseEvent);
    fire('click', MouseEvent);
    console.log(`[WWSD] synthClick @frac(${fx},${fy}) → client(${Math.round(x)},${Math.round(y)})`);
    return { x, y };
  }

  // ── UI click-adapter coordinates (canvas fractions, recorded on spendee) ────────────────────────
  // Drive the canvas game by synthetic clicks. All values are fractions of the board canvas so they
  // survive resize (assuming the engine scales proportionally). Re-record if spendee's layout changes.
  const UI = {
    openTake: [0.410, 0.452],    // click a board bank gem → opens the "select chips" modal
    takeGem: {                   // gem positions INSIDE the select-chips modal (top→bottom)
      white: [0.420, 0.278], blue: [0.422, 0.401], green: [0.422, 0.506], red: [0.423, 0.624], black: [0.419, 0.735],
    },
    takePick: [0.392, 0.823],    // "pick" button that finalizes the take
    takeCancel: [0.464, 0.112],  // ✕ on the select-chips modal
    // Exact face-up card positions, indexed by engine slot (0-3 L1 bottom, 4-7 L2 mid, 8-11 L3 top;
    // col = slot%4 left→right). Recorded directly (rows are slightly tilted, so exact beats interpolation).
    cardFrac: [
      [0.582, 0.865], [0.696, 0.884], [0.805, 0.898], [0.932, 0.886],   // L1  (slots 0-3)
      [0.587, 0.618], [0.697, 0.619], [0.815, 0.627], [0.925, 0.629],   // L2  (slots 4-7)
      [0.581, 0.379], [0.696, 0.381], [0.817, 0.372], [0.936, 0.368],   // L3  (slots 8-11)
    ],
    buyBtn: [0.867, 0.450],      // "Buy" in the card modal (plain click)
    reserveBtn: [0.867, 0.829],  // "Reserve" in the card AND deck modal (PRESS-AND-HOLD)
    cardCancel: [0.964, 0.286],  // ✕ on the card modal
    // Reserve-from-deck: click the face-down pile (L1/L2/L3) → same hold-reserve button.
    deckFrac: [[0.492, 0.818], [0.494, 0.572], [0.495, 0.320]],
    // Buy-from-reserve: click your stacked reserve pile → modal lists reserved cards (oldest at TOP);
    // click that card's row to buy it. Index matches engine reserved[] order (0 = oldest).
    reservePile: [0.020, 0.241],
    buyReserved: [[0.522, 0.477], [0.524, 0.702], [0.522, 0.925]],
    reservedCancel: [0.551, 0.061],
    // Pass: click the green Pass button → confirm modal → confirm.
    passBtn: [0.323, 0.196], passConfirm: [0.741, 0.605],
    // Discard modal (over 10 tokens): fixed vertical column, gold above white; click selects one;
    // "return" finalizes. Positions are fixed (missing token types don't shift the others).
    discardGem: {
      gold: [0.334, 0.250], white: [0.334, 0.357], blue: [0.335, 0.455], green: [0.334, 0.552], red: [0.335, 0.656], black: [0.336, 0.756],
    },
    discardReturn: [0.389, 0.847],
  };
  function cardSlotFrac(slot) { return UI.cardFrac[slot]; }   // engine board slot → exact canvas fraction
  const _gpause = () => sleep(CONFIG.STEP_MS + Math.floor(Math.random() * 160));   // jittered gap between clicks

  // Take gems: open the modal, click each wanted colour in the modal, confirm. `colors` = engine
  // colour NAMES from the structured action (e.g. ['white','green','black'] or ['red','red']).
  async function uiTakeGems(colors) {
    synthClickCanvas(...UI.openTake);
    await sleep(CONFIG.OPEN_MS);                        // let the modal open/animate
    for (const c of colors) { synthClickCanvas(...UI.takeGem[c]); await _gpause(); }
    synthClickCanvas(...UI.takePick);
    console.log('[WWSD] uiTakeGems', colors, '→ pick');
  }

  // Press-and-hold at a canvas fraction for `ms` (pointer/mouse DOWN, wait, UP+click) — for Reserve.
  async function synthHoldCanvas(fx, fy, ms) {
    const cv = boardCanvas();
    if (!cv) { console.warn('[WWSD] no board canvas'); return; }
    const r = cv.getBoundingClientRect();
    const x = r.left + fx * r.width, y = r.top + fy * r.height;
    const down = { bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y,
      screenX: x, screenY: y, button: 0, buttons: 1, pointerId: 1, pointerType: 'mouse', isPrimary: true };
    try { cv.dispatchEvent(new PointerEvent('pointerover', down)); cv.dispatchEvent(new PointerEvent('pointerdown', down)); } catch (e) {}
    cv.dispatchEvent(new MouseEvent('mousedown', down));
    await sleep(ms);
    const up = Object.assign({}, down, { buttons: 0 });
    try { cv.dispatchEvent(new PointerEvent('pointerup', up)); } catch (e) {}
    cv.dispatchEvent(new MouseEvent('mouseup', up));
    cv.dispatchEvent(new MouseEvent('click', up));
    console.log(`[WWSD] synthHold @frac(${fx},${fy}) ${ms}ms → client(${Math.round(x)},${Math.round(y)})`);
  }

  // Buy / reserve a face-up board card by engine slot: click the card → modal → Buy (click) / Reserve (hold).
  async function uiBuyBoard(slot) {
    const [fx, fy] = cardSlotFrac(slot);
    synthClickCanvas(fx, fy);
    await sleep(CONFIG.OPEN_MS);
    synthClickCanvas(...UI.buyBtn);
    console.log('[WWSD] uiBuyBoard slot', slot, '@frac', [fx.toFixed(3), fy.toFixed(3)]);
  }
  async function uiReserveBoard(slot) {
    const [fx, fy] = cardSlotFrac(slot);
    synthClickCanvas(fx, fy);
    await sleep(CONFIG.OPEN_MS);
    await synthHoldCanvas(UI.reserveBtn[0], UI.reserveBtn[1], CONFIG.HOLD_MS);
    console.log('[WWSD] uiReserveBoard slot', slot, '@frac', [fx.toFixed(3), fy.toFixed(3)]);
  }
  // Reserve the top of a face-down deck: click the pile (level 1-3) → modal → hold Reserve.
  async function uiReserveDeck(level) {
    synthClickCanvas(...UI.deckFrac[level - 1]);
    await sleep(CONFIG.OPEN_MS);
    await synthHoldCanvas(UI.reserveBtn[0], UI.reserveBtn[1], CONFIG.HOLD_MS);
    console.log('[WWSD] uiReserveDeck level', level);
  }
  // Buy one of your reserved cards by engine reserved index (0 = oldest): open the reserve pile → click its row.
  async function uiBuyReserved(ri) {
    synthClickCanvas(...UI.reservePile);
    await sleep(CONFIG.OPEN_MS);
    synthClickCanvas(...UI.buyReserved[ri]);
    console.log('[WWSD] uiBuyReserved index', ri);
  }
  // Pass: click Pass → confirm modal → confirm.
  async function uiPass() {
    synthClickCanvas(...UI.passBtn);
    await sleep(CONFIG.OPEN_MS);
    synthClickCanvas(...UI.passConfirm);
    console.log('[WWSD] uiPass');
  }
  // Discard: click each token to return (one per click; repeat a colour to return 2), then "return".
  async function uiDiscard(colors) {
    for (const c of colors) { synthClickCanvas(...UI.discardGem[c]); await _gpause(); }
    synthClickCanvas(...UI.discardReturn);
    console.log('[WWSD] uiDiscard', colors, '→ return');
  }
  // Heuristic: which `n` gems to return when a take overfills past 10. Discard the most-abundant
  // COLOURED gems first (keeps a balanced hand; never throws away flexible gold unless nothing else).
  function chooseDiscards(tok, n) {
    const c = tok.slice(), out = [];
    for (let k = 0; k < n; k++) {
      let best = -1, bestv = 0;
      for (let i = 0; i < 5; i++) if (c[i] > bestv) { bestv = c[i]; best = i; }
      if (best >= 0) { out.push(G[best]); c[best]--; } else { out.push('gold'); c[5]--; }
    }
    return out;
  }

  // Master dispatcher: execute N's structured action via the canvas UI. `dump` is the friend-space
  // dump (for the seat's tokens, to pre-compute any forced discard after an over-10 take).
  async function playMove(action, dump) {
    const seat = dump.turn;
    switch (action.kind) {
      case 'take3': case 'take2_diff': case 'take2_same': case 'take1': {
        const colors = action.colors.map(i => G[i]);
        const tok = dump.tokens[seat].slice();           // predict post-take tokens for discard
        for (const i of action.colors) tok[i]++;
        const nDiscard = Math.max(0, tok.reduce((a, b) => a + b, 0) - 10);
        await uiTakeGems(colors);
        if (nDiscard > 0) { await sleep(CONFIG.OPEN_MS + 350); await uiDiscard(chooseDiscards(tok, nDiscard)); }
        return;
      }
      case 'buy_board': return uiBuyBoard(action.slot);
      case 'buy_reserved': return uiBuyReserved(action.reserved_index);
      case 'reserve_board': return uiReserveBoard(action.slot);
      case 'reserve_deck': return uiReserveDeck(action.level);
      case 'pass': return uiPass();
      default: throw new Error('playMove: unhandled action kind ' + action.kind);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // The loop
  // ─────────────────────────────────────────────────────────────────────────
  let lastKey = null, busy = false, _retries = {};
  // A key that CHANGES on every move. spendee's state has no reliable ply counter, so we hash the
  // parts of `data` that change when anyone moves (each player's card counts + chips + the bank) plus
  // whose turn it is. Without this the key was constant across your turns (only currentPlayerIndex,
  // which doesn't change on YOUR turns) → the "already analyzed" guard skipped every auto-analysis.
  function turnKey(g) {
    const data = g.data || {}, st = data.state || {}, players = data.players || [], bank = data.bank || {};
    let sig = '';
    for (const p of players) {
      sig += (p.purchasedCards || []).length + '/' + (p.reservedCards || []).length + '/' +
             (p.chips || []).join(',') + '/' + (p.goldChips || 0) + '|';
    }
    sig += 'B' + (bank.chips || []).join(',') + '/' + (bank.goldChips || 0);
    return g._id + ':' + st.currentPlayerIndex + ':' + sig;
  }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  async function tick() {
    if (!CONFIG.ENABLED || busy || !meteorReady()) return;
    const found = findMyActiveGame();
    if (!found) { setStatus('idle — no active game' + (CONFIG.MY_NAME ? '' : ' (set MY_NAME if not detected)')); return; }
    const { game: g, seat } = found;
    const st = (g.data && g.data.state) || {};
    if (st.currentPlayerIndex !== seat) { setStatus('waiting for opponent…'); return; }
    const key = turnKey(g);
    if (key === lastKey) return;
    const job = st.currentJob;
    busy = true;
    try {
      if (job && job !== CONFIG.REGULAR_JOB) { setStatus('sub-decision (' + job + ') — resolve manually'); lastKey = key; return; }
      setStatus('N thinking…');
      const t0 = Date.now();
      const r = await analyzePosition(g, seat);
      renderResult(r);
      if (!CONFIG.AUTO_PLAY) { lastKey = key; return; }
      // human-like pacing: make the whole turn take a RANDOM 2-4s. The capped search (~2-3s) counts
      // toward it, so a fast result waits out the remainder rather than slamming the move instantly.
      const target = CONFIG.MIN_DELAY_MS + Math.random() * (CONFIG.MAX_DELAY_MS - CONFIG.MIN_DELAY_MS);
      const wait = target - (Date.now() - t0);
      if (wait > 0) { setStatus('playing in ' + (wait / 1000).toFixed(1) + 's…'); await sleep(wait); }
      await playMove(r.action, r.dump);            // execute via the canvas UI (synthetic clicks)
      setStatus('played: ' + r.recommendation);
      // Verify the move COMMITTED. If a click missed, the turn won't advance and a modal is left open →
      // close any stray modal and retry (capped), instead of hard-freezing.
      await sleep(1600);
      const af = findMyActiveGame();
      const s2 = af ? ((af.game.data && af.game.data.state) || {}) : {};
      const committed = !af || s2.currentPlayerIndex !== af.seat ||
        (s2.currentJob && s2.currentJob !== CONFIG.REGULAR_JOB) || turnKey(af.game) !== key;
      if (committed) { lastKey = key; _retries = {}; }
      else {
        _retries[key] = (_retries[key] || 0) + 1;
        synthClickCanvas(...UI.cardCancel); await sleep(250); synthClickCanvas(...UI.takeCancel);
        if (_retries[key] <= 2) { lastKey = null; setStatus('move missed — retrying (' + _retries[key] + ')…'); }
        else { lastKey = key; setStatus('autoplay stuck — finish this move manually; it resumes after'); }
      }
    } catch (e) {
      const wired = String(e && e.message).indexOf(ADAPTER_TODO) < 0;
      setStatus((wired ? 'error: ' : 'autoplay needs SITE ADAPTER — ') + (e && e.message));
      console.error('[WWSD]', e);
    } finally { busy = false; }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Panel / overlay
  // ─────────────────────────────────────────────────────────────────────────
  let statusEl = null, resultEl = null;
  function setStatus(s) { if (statusEl) statusEl.textContent = s; }
  const sev = v => (v == null ? 'na' : (v >= 0 ? '+' : '') + v.toFixed(2));
  function renderResult(r) {
    setStatus(`${r.sims} sims · target ${(r.dump.win_points)}`);
    if (!resultEl) return;
    const lbl = r.value > 0.15 ? 'favored' : r.value < -0.15 ? 'behind' : 'even';
    let h = `<div style="font-weight:700;color:#e8c170">${r.recommendation}`;
    if (r.rec_eval != null) h += ` <span style="color:#b8a888;font-weight:400;font-size:12px">(${sev(r.rec_eval)})</span>`;
    h += `</div><div style="margin-top:3px;color:#cdbfa8;font-size:12px">position: ${sev(r.value)} (${lbl})</div>`;
    if (r.alternatives.length) {
      h += `<ul style="margin:5px 0 0;padding-left:16px;color:#cdbfa8;font-size:12px">`;
      for (const a of r.alternatives) h += `<li>${a.pct}% ${a.text}${a.eval != null ? ` (${sev(a.eval)})` : ''}</li>`;
      h += `</ul>`;
    }
    resultEl.innerHTML = h;
  }

  function buildPanel() {
    const box = document.createElement('div');
    box.id = 'wwsd-n';
    box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;width:280px;background:#241a10;color:#f0e6d8;' +
      'border:1px solid #b5852f;border-radius:10px;padding:10px 12px;font:13px system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.5)';
    const mk = (t) => { const b = document.createElement('button'); b.textContent = t; b.style.cssText = 'background:#b5852f;color:#1b140d;border:0;border-radius:7px;padding:6px 10px;font-weight:700;cursor:pointer;margin:4px 4px 0 0'; return b; };
    box.innerHTML = '<b style="color:#e8c170">WWSD · N (browser)</b>';
    const toggle = mk(CONFIG.ENABLED ? 'Disable' : 'Enable');
    const setTog = () => { toggle.textContent = CONFIG.ENABLED ? 'Disable' : 'Enable'; toggle.style.background = CONFIG.ENABLED ? '#4a8f4a' : '#b5852f'; };
    toggle.onclick = () => { CONFIG.ENABLED = !CONFIG.ENABLED; lastKey = null; setTog(); setStatus(CONFIG.ENABLED ? 'enabled' : 'disabled'); };
    setTog();
    const once = mk('Analyze now');
    once.onclick = async () => { lastKey = null; const w = CONFIG.ENABLED; CONFIG.ENABLED = true; await tick(); CONFIG.ENABLED = w; };
    const auto = mk('Autoplay: off');
    auto.onclick = () => { CONFIG.AUTO_PLAY = !CONFIG.AUTO_PLAY; auto.textContent = 'Autoplay: ' + (CONFIG.AUTO_PLAY ? 'on' : 'off'); auto.style.background = CONFIG.AUTO_PLAY ? '#4a8f4a' : '#b5852f'; };
    const methods = mk('List methods'); methods.onclick = () => { listMethods(); setStatus('methods → console'); };
    const record = mk('Record'); record.onclick = () => { const on = toggleRecord(); record.style.background = on ? '#4a8f4a' : '#b5852f'; };
    const domrec = mk('Rec DOM'); domrec.onclick = () => { const on = toggleDomRecord(); domrec.style.background = on ? '#4a8f4a' : '#b5852f'; setStatus(on ? 'DOM-record ON — make moves; check console' : 'DOM-record off'); };
    statusEl = document.createElement('div'); statusEl.style.cssText = 'margin-top:8px;color:#cdbfa8;font-size:12px;min-height:16px';
    statusEl.textContent = 'loading N…';
    resultEl = document.createElement('div'); resultEl.style.cssText = 'margin-top:6px';
    for (const el of [toggle, once, auto, methods, record, domrec, statusEl, resultEl]) box.appendChild(el);
    document.body.appendChild(box);
  }

  function boot() {
    if (!meteorReady()) { setTimeout(boot, 1000); return; }
    installApplyHook();
    installClickRecorder();
    buildPanel();
    loadWasm().then(() => setStatus('ready')).catch(e => setStatus('WASM failed: ' + e.message + ' (CSP?)'));
    setInterval(tick, CONFIG.POLL_MS);
    window.WWSD_N = { analyzePosition, findMyActiveGame, listMethods, toggleRecord, toggleDomRecord, synthClickCanvas, synthHoldCanvas, boardCanvas, uiTakeGems, uiBuyBoard, uiReserveBoard, uiReserveDeck, uiBuyReserved, uiPass, uiDiscard, playMove, cardSlotFrac, UI, toDump, CONFIG };
    console.log('[WWSD] browser-N loaded. window.WWSD_N available.');
  }
  boot();
})();
