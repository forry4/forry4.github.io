// ==UserScript==
// @name         WWSD Browser-N (Steve runs in your browser)
// @namespace    wwsd
// @version      0.2.0
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
    THINK_SECS: 3.0,   // wall-clock budget N thinks per move (your CPU; more = stronger)
    MAX_SIMS:   0,     // 0 = no cap (budget-limited)
    MY_NAME:    '',    // your spendee display name; blank = auto via Meteor.userId()
    AUTO_PLAY:  false, // execute the move (needs the SITE ADAPTER wired); false = advisor overlay only
    POLL_MS:    1500,
    ACT_DELAY_MS: 700,
    ENABLED:    false, // master switch — toggle from the panel
    REGULAR_JOB: 'SPENDEE_REGULAR',
  };

  // ─────────────────────────────────────────────────────────────────────────
  // Friend's deck tables (from wwsd_defs.json) — index → bonus colour / points; noble → points.
  // Used to build the engine State dump (bonuses + score) the WASM consumes.
  // ─────────────────────────────────────────────────────────────────────────
  const BONUS = [0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,3,3,3,3,3,3,3,3,4,4,4,4,4,4,4,4,0,0,0,0,0,0,1,1,1,1,1,1,2,2,2,2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4];
  const PTS   = [0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,2,3,1,2,1,2,2,3,1,2,1,2,2,3,1,1,2,2,2,3,1,2,1,2,2,3,1,2,1,2,4,5,4,3,4,5,4,3,4,5,4,3,4,5,4,3,4,5,4,3];
  const NOBLE_PTS = [3,3,3,3,3,3,3,3,3,3];

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
    const dump = toDump(data, winPoints);
    const wb = await loadWasm();
    const seed = BigInt(((Date.now() >>> 0) ^ (seat << 28)) >>> 0);
    const raw = wb.search_n_full_timed(JSON.stringify(dump), seat >>> 0, CONFIG.THINK_SECS * 1000, CONFIG.MAX_SIMS >>> 0, seed);
    const d = JSON.parse(raw);
    if (d.error) throw new Error('N error: ' + d.error);
    const tot = d.visits.reduce((a, b) => a + b, 0);
    const order = d.visits.map((v, a) => [a, v]).filter(x => x[1] > 0).sort((a, b) => b[1] - a[1]);
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
  async function playAction(g, action) {
    // EXAMPLE (replace names/params with what the recorder shows):
    //   switch (action.kind) {
    //     case 'take3': case 'take2_diff': case 'take2_same': case 'take1':
    //       return callMeteor('games.takeChips', { gameId: g._id, chips: action.colors });
    //     case 'buy_board': case 'buy_reserved':
    //       return callMeteor('games.buyCard', { gameId: g._id, cardId: action.card_id });
    //     case 'reserve_board':
    //       return callMeteor('games.reserveCard', { gameId: g._id, cardId: action.card_id });
    //     case 'reserve_deck':
    //       return callMeteor('games.reserveFromDeck', { gameId: g._id, level: action.level - 1 });
    //   }
    console.warn('[WWSD] playAction', action.kind, action, g._id);
    throw new Error(ADAPTER_TODO + ' playAction(' + action.kind + ')');
  }
  function listMethods() {
    try { const n = Object.keys(window.Meteor.connection._methodHandlers).sort(); console.log('[WWSD] methods', n); return n; }
    catch (e) { return []; }
  }
  let _recOrig = null;
  function toggleRecord() {
    const c = window.Meteor.connection;
    if (_recOrig) { c.apply = _recOrig; _recOrig = null; console.log('[WWSD] record OFF'); return false; }
    _recOrig = c.apply.bind(c);
    c.apply = function (n, a, o, cb) { try { console.log('[WWSD] call →', n, JSON.parse(JSON.stringify(a))); } catch (e) {} return _recOrig(n, a, o, cb); };
    console.log('[WWSD] record ON — make one manual move of each type'); return true;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // The loop
  // ─────────────────────────────────────────────────────────────────────────
  let lastKey = null, busy = false;
  function turnKey(g) { const st = (g.data && g.data.state) || {}; return g._id + ':' + (st.ply != null ? st.ply : '') + ':' + st.currentPlayerIndex; }
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
      const r = await analyzePosition(g, seat);
      renderResult(r);
      lastKey = key;
      if (CONFIG.AUTO_PLAY) { await sleep(CONFIG.ACT_DELAY_MS); await playAction(g, r.action); }
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
    box.style.cssText = 'position:fixed;top:12px;left:12px;z-index:2147483647;width:280px;background:#241a10;color:#f0e6d8;' +
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
    statusEl = document.createElement('div'); statusEl.style.cssText = 'margin-top:8px;color:#cdbfa8;font-size:12px;min-height:16px';
    statusEl.textContent = 'loading N…';
    resultEl = document.createElement('div'); resultEl.style.cssText = 'margin-top:6px';
    for (const el of [toggle, once, auto, methods, record, statusEl, resultEl]) box.appendChild(el);
    document.body.appendChild(box);
  }

  function boot() {
    if (!meteorReady()) { setTimeout(boot, 1000); return; }
    buildPanel();
    loadWasm().then(() => setStatus('ready')).catch(e => setStatus('WASM failed: ' + e.message + ' (CSP?)'));
    setInterval(tick, CONFIG.POLL_MS);
    window.WWSD_N = { analyzePosition, findMyActiveGame, listMethods, toggleRecord, toDump, CONFIG };
    console.log('[WWSD] browser-N loaded. window.WWSD_N available.');
  }
  boot();
})();
