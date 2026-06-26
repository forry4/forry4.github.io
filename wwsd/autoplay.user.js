// ==UserScript==
// @name         WWSD Autoplay (Steve plays for you)
// @namespace    wwsd
// @version      0.1.0
// @description  Watches your spendee game, asks the WWSD service (variant S) for the move, and plays it via the site's own Meteor methods. Approach A: runs in your logged-in browser tab.
// @match        https://spendee.mattle.online/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==
//
// SETUP
//   1. Fill in CONFIG.SECRET (your WWSD_SECRET) and CONFIG.SERVICE below.
//   2. Install in Tampermonkey/Violentmonkey, open spendee, log in.
//   3. The "WWSD Auto" panel appears top-left. It starts DISABLED.
//   4. FIRST, wire the SITE ADAPTER (one-time): click "Record calls", then make ONE manual
//      move of each type (take gems, buy a card, reserve a card, start a game). The console
//      logs the exact Meteor method name + params each fired. Send those to fill in `playAction`
//      / `startNewGame` / `resolveSubDecision` below. Until then, autoplay can analyze + decide
//      but cannot execute (it will log "ADAPTER NOT WIRED").
//   5. Once wired, click Enable. Steve takes your turns.
//
(function () {
  'use strict';

  // ─────────────────────────────────────────────────────────────────────────
  // CONFIG  — edit these
  // ─────────────────────────────────────────────────────────────────────────
  const CONFIG = {
    SECRET:     'PASTE_YOUR_WWSD_SECRET',          // the WWSD_SECRET set on the service
    SERVICE:    'https://wwsd.onrender.com/move',  // your WWSD /move endpoint
    THINK_SECS: 0,        // think-time: 0 = server default (~3.5s); else 1..60 (longer = stronger, slower)
    MY_NAME:    '',       // your spendee display name; blank = auto-detect via Meteor.userId()
    AUTO_START: false,    // when a game ends, auto-create/queue a new one (needs startNewGame wired)
    POLL_MS:    1500,     // how often to check whose turn it is
    ACT_DELAY_MS: 700,    // small pause before playing (feels less robotic; also lets state settle)
    ENABLED:    false,    // master switch — leave OFF; toggle from the panel
    REGULAR_JOB: 'SPENDEE_REGULAR',  // the "normal main move" job; other jobs = sub-decisions
  };

  // The colour order shared by spendee and our engine: index -> name.
  const COLORS = ['white', 'blue', 'green', 'red', 'black'];

  // ─────────────────────────────────────────────────────────────────────────
  // Meteor access helpers
  // ─────────────────────────────────────────────────────────────────────────
  function meteorReady() { return typeof window.Meteor !== 'undefined' && Meteor.connection; }

  function gamesCollection() {
    return Meteor.connection._mongo_livedata_collections['games'];
  }
  function fetchGames() {
    try { return gamesCollection().find().fetch(); } catch (e) { return []; }
  }

  // Trim a full game doc to what WWSD wants (mirrors the bookmarklet's projection).
  function trimForWwsd(g) {
    return { status: g.status, settings: g.settings, players: g.players, data: g.data };
  }

  // Which seat am I in this game? Prefer a userId match; fall back to MY_NAME.
  function findMySeat(g) {
    const uid = (function () { try { return Meteor.userId(); } catch (e) { return null; } })();
    const players = g.players || [];
    for (let i = 0; i < players.length; i++) {
      const p = players[i] || {};
      if (uid && (p.userId === uid || p._id === uid || p.id === uid)) return i;
    }
    if (CONFIG.MY_NAME) {
      for (let i = 0; i < players.length; i++) {
        if ((players[i] || {}).name === CONFIG.MY_NAME) return i;
      }
    }
    return -1;
  }

  // Find the in-progress game I'm a participant of (first match).
  function findMyActiveGame() {
    for (const g of fetchGames()) {
      if (g.status !== 'INPROGRESS') continue;
      const seat = findMySeat(g);
      if (seat >= 0) return { game: g, seat };
    }
    return null;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // WWSD service call
  // ─────────────────────────────────────────────────────────────────────────
  async function askWwsd(trimmedGame) {
    const secs = CONFIG.THINK_SECS | 0;
    const url = CONFIG.SERVICE + (secs ? (CONFIG.SERVICE.indexOf('?') >= 0 ? '&' : '?') + 't=' + secs : '');
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WWSD-Secret': CONFIG.SECRET },
      body: JSON.stringify({ games: [trimmedGame] }),
    });
    return res.json();
  }

  // ═════════════════════════════════════════════════════════════════════════
  // SITE ADAPTER  — the ONLY part that needs spendee's Meteor method names.
  // Use "Record calls" + manual moves to discover them, then fill these in.
  // Each receives the FULL game doc `g` (so g._id and g.data are available) and
  // the WWSD structured action. Return a Promise (use callMeteor()).
  // ═════════════════════════════════════════════════════════════════════════

  // Promise wrapper around Meteor.call.
  function callMeteor(name, ...args) {
    return new Promise((resolve, reject) => {
      Meteor.call(name, ...args, (err, result) => (err ? reject(err) : resolve(result)));
    });
  }

  const ADAPTER_TODO = '__WWSD_ADAPTER_NOT_WIRED__';

  // Play a main move (action.kind ∈ take3 | take2_diff | take2_same | take1 |
  // pass | reserve_board | reserve_deck | buy_board | buy_reserved).
  //   action.colors    : gem colour indices (0..4) for takes
  //   action.card_id   : spendee card index for buy_board / reserve_board / buy_reserved
  //   action.level     : 1..3 for reserve_deck
  // card_id IS the id you'll find in g.data.bank.showedCards / players[seat].reservedCards.
  async function playAction(g, action) {
    // EXAMPLE shape (REPLACE method names + params with what "Record calls" shows):
    //   switch (action.kind) {
    //     case 'take3': case 'take2_diff': case 'take2_same': case 'take1':
    //       return callMeteor('games.takeChips', { gameId: g._id, chips: action.colors });
    //     case 'buy_board': case 'buy_reserved':
    //       return callMeteor('games.buyCard', { gameId: g._id, cardId: action.card_id });
    //     case 'reserve_board':
    //       return callMeteor('games.reserveCard', { gameId: g._id, cardId: action.card_id });
    //     case 'reserve_deck':
    //       return callMeteor('games.reserveFromDeck', { gameId: g._id, level: action.level - 1 });
    //     case 'pass':
    //       return callMeteor('games.pass', { gameId: g._id });
    //   }
    console.warn('[WWSD] playAction:', action.kind, action, 'on game', g._id);
    throw new Error(ADAPTER_TODO + ' playAction(' + action.kind + ')');
  }

  // Resolve a non-regular job (discard down over the cap, pick a noble, etc).
  // We don't yet know spendee's job names — log them so we can wire this.
  async function resolveSubDecision(g, job) {
    console.warn('[WWSD] sub-decision job needs wiring:', job, 'game', g._id, g.data && g.data.state);
    throw new Error(ADAPTER_TODO + ' resolveSubDecision(' + job + ')');
  }

  // Create/queue a fresh game (only used if CONFIG.AUTO_START).
  async function startNewGame() {
    console.warn('[WWSD] startNewGame needs wiring');
    throw new Error(ADAPTER_TODO + ' startNewGame');
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Discovery helpers (run once to wire the adapter)
  // ─────────────────────────────────────────────────────────────────────────
  function listMethods() {
    try {
      const names = Object.keys(Meteor.connection._methodHandlers).sort();
      console.log('[WWSD] %d client method stubs:', names.length, names);
      return names;
    } catch (e) { console.error('[WWSD] listMethods failed', e); return []; }
  }

  // Wrap Meteor.connection.apply so every outgoing method call (name + params) is logged.
  // Make your manual moves, read the console, then turn it off (toggle again).
  let _recordOrig = null;
  function toggleRecord() {
    const conn = Meteor.connection;
    if (_recordOrig) {
      conn.apply = _recordOrig; _recordOrig = null;
      console.log('[WWSD] call recording OFF');
      return false;
    }
    _recordOrig = conn.apply.bind(conn);
    conn.apply = function (name, args, options, callback) {
      try { console.log('[WWSD] Meteor.call →', name, JSON.parse(JSON.stringify(args))); } catch (e) {}
      return _recordOrig(name, args, options, callback);
    };
    console.log('[WWSD] call recording ON — make one manual move of each type now');
    return true;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // The autoplay loop
  // ─────────────────────────────────────────────────────────────────────────
  let lastTurnKey = null;   // dedupe: act at most once per (game, ply)
  let busy = false;
  let lastEndedGame = null;  // dedupe AUTO_START

  function turnKey(g) {
    const st = (g.data && g.data.state) || {};
    return g._id + ':' + (st.ply != null ? st.ply : '') + ':' + (st.currentPlayerIndex != null ? st.currentPlayerIndex : '');
  }

  async function tick() {
    if (!CONFIG.ENABLED || busy || !meteorReady()) return;
    const found = findMyActiveGame();
    if (!found) {
      if (CONFIG.AUTO_START) { /* handled in endgame branch below via fetchGames scan */ }
      setStatus('idle — no active game' + (CONFIG.MY_NAME ? '' : ' (set MY_NAME if not detected)'));
      return;
    }
    const { game: g, seat } = found;
    const st = (g.data && g.data.state) || {};
    if (st.currentPlayerIndex !== seat) { setStatus('waiting for opponent…'); return; }

    const key = turnKey(g);
    if (key === lastTurnKey) return;  // already acted this turn

    const job = st.currentJob;
    busy = true;
    try {
      if (job && job !== CONFIG.REGULAR_JOB) {
        setStatus('sub-decision: ' + job + ' — needs adapter');
        await sleep(CONFIG.ACT_DELAY_MS);
        await resolveSubDecision(g, job);
        lastTurnKey = key;
        return;
      }
      setStatus('thinking…');
      const d = await askWwsd(trimForWwsd(g));
      if (!d || !d.ok) { setStatus('WWSD: ' + ((d && d.message) || 'no result')); return; }
      if (!d.action) { setStatus('WWSD gave no structured action (old server?)'); return; }
      setStatus('playing: ' + d.recommendation);
      await sleep(CONFIG.ACT_DELAY_MS);
      await playAction(g, d.action);
      lastTurnKey = key;
      setStatus('played: ' + d.recommendation);
    } catch (e) {
      const wired = !(e && String(e.message).indexOf(ADAPTER_TODO) >= 0);
      setStatus((wired ? 'error: ' : 'ADAPTER NOT WIRED — ') + (e && e.message));
      console.error('[WWSD] tick error', e);
    } finally {
      busy = false;
    }
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ─────────────────────────────────────────────────────────────────────────
  // Control panel
  // ─────────────────────────────────────────────────────────────────────────
  let statusEl = null;
  function setStatus(s) { if (statusEl) statusEl.textContent = s; }

  function buildPanel() {
    const box = document.createElement('div');
    box.id = 'wwsd-auto';
    box.style.cssText = 'position:fixed;top:12px;left:12px;z-index:2147483647;width:260px;' +
      'background:#241a10;color:#f0e6d8;border:1px solid #b5852f;border-radius:10px;padding:10px 12px;' +
      'font:13px system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.5)';
    const mkBtn = (label) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = 'background:#b5852f;color:#1b140d;border:0;border-radius:7px;padding:6px 10px;' +
        'font-weight:700;cursor:pointer;margin:4px 4px 0 0';
      return b;
    };
    const title = document.createElement('div');
    title.innerHTML = '<b style="color:#e8c170">WWSD Auto</b>';
    const toggle = mkBtn(CONFIG.ENABLED ? 'Disable' : 'Enable');
    toggle.onclick = () => {
      CONFIG.ENABLED = !CONFIG.ENABLED;
      toggle.textContent = CONFIG.ENABLED ? 'Disable' : 'Enable';
      toggle.style.background = CONFIG.ENABLED ? '#4a8f4a' : '#b5852f';
      lastTurnKey = null;
      setStatus(CONFIG.ENABLED ? 'enabled' : 'disabled');
    };
    toggle.style.background = CONFIG.ENABLED ? '#4a8f4a' : '#b5852f';

    const step = mkBtn('Play 1 move');
    step.onclick = async () => { lastTurnKey = null; const was = CONFIG.ENABLED; CONFIG.ENABLED = true; await tick(); CONFIG.ENABLED = was; };

    const methods = mkBtn('List methods');
    methods.onclick = () => { listMethods(); setStatus('method names → console'); };

    const record = mkBtn('Record calls');
    record.onclick = () => { const on = toggleRecord(); record.style.background = on ? '#4a8f4a' : '#b5852f'; setStatus(on ? 'recording → console' : 'recording off'); };

    statusEl = document.createElement('div');
    statusEl.style.cssText = 'margin-top:8px;color:#cdbfa8;font-size:12px;min-height:16px;word-break:break-word';
    statusEl.textContent = CONFIG.SECRET === 'PASTE_YOUR_WWSD_SECRET' ? 'set CONFIG.SECRET first' : 'ready';

    box.appendChild(title);
    box.appendChild(toggle);
    box.appendChild(step);
    box.appendChild(methods);
    box.appendChild(record);
    box.appendChild(statusEl);
    document.body.appendChild(box);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Boot
  // ─────────────────────────────────────────────────────────────────────────
  function boot() {
    if (!meteorReady()) { setTimeout(boot, 1000); return; }
    buildPanel();
    setInterval(tick, CONFIG.POLL_MS);
    // expose for console use
    window.WWSD = { listMethods, toggleRecord, fetchGames, findMyActiveGame, CONFIG };
    console.log('[WWSD] autoplay loaded. window.WWSD available.');
  }
  boot();
})();
