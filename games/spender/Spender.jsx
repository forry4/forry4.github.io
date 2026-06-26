import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import CastlesOfCrimson from "../castles_of_crimson/CastlesOfCrimson.jsx";
import WhereWolf from "../wherewolf/WhereWolf.jsx";
import Books from "../../books/Books.jsx";
import { baseCss } from "../../shared/theme.js";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

// ─── Site identity ─────────────────────────────────────────────────────────
const SITE_NAME = "Forrest Games";
// Registry of games shown on the home menu. Add future games here — each tile
// routes to its own `screen`. `status: "ready"` is playable; "soon" shows a
// Coming Soon placeholder. Spender's lobby is the existing "browser" screen.
const GAMES = [
	{ id: "spender", name: "Spender", tagline: "A gem merchant's game of prestige", status: "ready", screen: "browser" },
	{ id: "coc", name: "Castles of Crimson", tagline: "A realm of conquest and intrigue", status: "ready", screen: "coc" },
	{ id: "wherewolf", name: "Where Wolf?", tagline: "A village of secrets and lies", status: "ready", screen: "werewolf" },
];

// ─── Constants ─────────────────────────────────────────────────────────────
const GEM_COLORS = ["white", "blue", "green", "red", "black"];
const GEM_LABELS = { white: "Diamond", blue: "Sapphire", green: "Emerald", red: "Ruby", black: "Onyx", gold: "Gold" };
const GEM_HEX = { white: "#ddd4be", blue: "#4257ff", green: "#3f9c2e", red: "#dc4040", black: "#15151a", gold: "#f5c842" };
// Frontend-only display names for the AI variants (wire codes stay H2/H3/S).
const AI_PERSONAS = { H2: "Henry", H3: "Herald", S: "Steve" };
const AI_TIERS = { H2: "easy", H3: "medium", S: "hard" };
const aiPersona = (v) => AI_PERSONAS[v] || `AI ${v}`;         // variant code -> persona name (retired codes -> "AI <code>")
const displayName = (name) => {                                // backend "AI (H2)" -> "Henry (AI)"; humans unchanged
	const m = typeof name === "string" && name.match(/^AI \((.+)\)$/);
	return m ? aiPersona(m[1]) + " (AI)" : name;                // tag AI names so a same-named human isn't confused for the bot
};

// ─── Helpers ───────────────────────────────────────────────────────────────
function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }
function emptyGems() { return { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 }; }
function gemTotal(tokens) { return Object.values(tokens).reduce((a, b) => a + b, 0); }
// Short rising two-tone "ping" via WebAudio — no asset to load. One shared, lazily
// created AudioContext (unlocked by the click gesture on the sender; the recipient's
// was already unlocked by their own in-game interactions). Best-effort: any failure
// (no WebAudio / suspended context) is swallowed silently.
let _pingCtx = null;
function playPing() {
	try {
		const AC = window.AudioContext || window.webkitAudioContext;
		if (!AC) return;
		if (!_pingCtx) _pingCtx = new AC();
		const ctx = _pingCtx;
		if (ctx.state === "suspended") ctx.resume();
		const now = ctx.currentTime;
		const osc = ctx.createOscillator();
		const gain = ctx.createGain();
		osc.type = "sine";
		osc.frequency.setValueAtTime(880, now);
		osc.frequency.setValueAtTime(1320, now + 0.08);
		gain.gain.setValueAtTime(0.0001, now);
		gain.gain.exponentialRampToValueAtTime(0.25, now + 0.012);
		gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.32);
		osc.connect(gain).connect(ctx.destination);
		osc.start(now);
		osc.stop(now + 0.34);
	} catch {}
}
function timeAgo(ts) {
	if (!ts) return "";
	const diff = Math.floor(Date.now() / 1000) - ts;
	if (diff < 60) return "just now";
	if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
	if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
	return `${Math.floor(diff / 86400)}d ago`;
}
function bonusesFrom(purchased) {
	const b = emptyGems();
	for (const c of purchased) b[c.bonus] = (b[c.bonus] || 0) + 1;
	return b;
}
function goldToAfford(cost, tokens, bonuses) {
	// gold (wild) gems needed to cover the colored shortfall after bonuses + colored tokens.
	let gold = 0;
	for (const c of GEM_COLORS) {
		const need = Math.max(0, (cost[c] || 0) - (bonuses[c] || 0));
		const have = tokens[c] || 0;
		if (have < need) gold += need - have;
	}
	return gold;
}
function canAfford(cost, tokens, bonuses) {
	return goldToAfford(cost, tokens, bonuses) <= (tokens.gold || 0);
}
function totalPoints(purchased, nobles) {
	return purchased.reduce((s, c) => s + c.points, 0) + nobles.reduce((s, n) => s + n.points, 0);
}

// ─── Styles ────────────────────────────────────────────────────────────────
const css = baseCss + `

/* ─── Loading ───────────────────────────────────────────────────────────── */
.loading-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;gap:16px;padding:32px;text-align:center}
.loading-logo{font-family:'Cinzel','Cinzel Fallback',serif;font-size:3rem;font-weight:700;color:var(--gold);letter-spacing:.06em}
.loading-sub{color:var(--text-dim);font-style:italic;font-size:.95rem}
.loading-bar-wrap{width:220px;height:5px;background:var(--surface2);border-radius:3px;overflow:hidden;border:1px solid var(--border)}
.loading-bar{height:100%;background:var(--gold);border-radius:3px;transition:width .4s ease}
.loading-hint{color:var(--text-muted);font-size:.78rem;font-style:italic}

/* ─── Auth ──────────────────────────────────────────────────────────────── */
.auth-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:32px 20px;background:var(--bg)}
.auth-logo{font-family:'Cinzel','Cinzel Fallback',serif;font-size:3rem;font-weight:700;color:var(--gold);letter-spacing:.06em;margin-bottom:4px}
.auth-tagline{color:var(--text-dim);font-style:italic;font-size:1.05rem;margin-bottom:32px}
.auth-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px 28px 24px;width:100%;max-width:400px}
.auth-tabs{display:flex;border-bottom:1px solid var(--border);margin-bottom:22px}
.auth-tab{flex:1;padding:10px 0;background:transparent;border:none;border-bottom:2px solid transparent;color:var(--text-dim);cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.78rem;letter-spacing:.1em;text-transform:uppercase;margin-bottom:-1px;transition:all .15s}
.auth-tab.active{color:var(--gold);border-bottom-color:var(--gold)}
.auth-tab:hover:not(.active){color:var(--text)}
.auth-field{width:100%;padding:11px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;font-size:1rem;letter-spacing:normal;outline:none;margin-bottom:10px}
.auth-field:focus{border-color:var(--gold)}
.auth-error{font-size:.82rem;color:var(--red-gem);padding:6px 0 2px;text-align:center}
.guest-name-row{display:flex;gap:8px;align-items:center;margin-bottom:10px}
.guest-name-row .auth-field{margin-bottom:0;flex:1}

/* ─── Common ────────────────────────────────────────────────────────────── */
.conn-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px;flex-shrink:0}
.conn-dot.connected{background:var(--green-gem)}.conn-dot.disconnected{background:var(--red-gem)}

/* ─── Home (Forrest Games menu) ─────────────────────────────────────────── */
.home{max-width:900px;margin:0 auto;padding:calc(env(safe-area-inset-top,0px) + 24px) 20px 48px;min-height:100vh}
.home-header{display:flex;justify-content:flex-end;align-items:center;min-height:34px}
.home-hero{text-align:center;margin:40px 0 48px}
.home-logo{font-family:'Cinzel','Cinzel Fallback',serif;font-size:clamp(2.4rem,8vw,3.6rem);font-weight:700;color:var(--gold);letter-spacing:.06em;line-height:1.1}
.home-tagline{color:var(--text-dim);font-style:italic;font-size:1.1rem;margin-top:10px}
.home-games{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
.home-game-card{position:relative;text-align:left;font-family:inherit;color:inherit;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:26px 22px 24px;cursor:pointer;transition:border-color .15s,transform .15s,background .15s}
.home-game-card:hover{border-color:var(--gold);transform:translateY(-2px);background:var(--surface2)}
.home-game-card.soon{opacity:.9}
.home-game-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.32rem;font-weight:600;color:var(--gold);letter-spacing:.03em;margin-bottom:8px}
.home-game-desc{color:var(--text-dim);font-size:.95rem;line-height:1.45;font-style:italic}
.home-game-badge{position:absolute;top:14px;right:14px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;padding:3px 9px;border-radius:10px}
.home-game-badge.ready{color:var(--green-gem);border:1px solid rgba(84,194,61,.5)}
.home-game-badge.soon{color:var(--text-muted);border:1px solid var(--border)}

/* ─── Browser ───────────────────────────────────────────────────────────── */
.browser{max-width:1400px;margin:0 auto;padding:28px 20px 48px}
/* Full-width top banner (flush to the screen edges) — lives OUTSIDE the centered
   .browser content so its bottom border spans the whole screen. Three sections:
   back button far left, game name centered, user far right (left/right flex:1 so the
   title is truly centered). */
.browser-header{display:flex;align-items:center;gap:12px;padding:12px 24px;padding-top:calc(env(safe-area-inset-top,0px) + 12px);border-bottom:1px solid var(--border);background:var(--surface)}
.browser-head-left{flex:1 1 0;display:flex;align-items:center;justify-content:flex-start;min-width:0}
.browser-title{flex:0 0 auto;text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;font-weight:700;color:var(--gold);letter-spacing:.04em}
.browser-user{flex:1 1 0;display:flex;align-items:center;justify-content:flex-end;gap:10px;min-width:0}
.browser-username{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;color:var(--text-dim);letter-spacing:.06em;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.browser-guest-badge{font-size:.65rem;letter-spacing:.1em;color:var(--text-muted);border:1px solid var(--border);padding:2px 7px;border-radius:10px;font-family:'Cinzel','Cinzel Fallback',serif;text-transform:uppercase}
.browser-create{margin-bottom:36px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:center}
/* Keep the length toggle and the Create Game button on the same line (they never
   wrap apart); the refresh button may wrap below them on narrow phones. */
.create-controls{display:inline-flex;align-items:center;gap:10px;flex-wrap:nowrap;max-width:100%}
/* game-length toggle: selected state changes ONLY background+color (fixed border/padding)
   so selecting never changes the element's size / shifts the layout */
.length-toggle{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;flex-shrink:0}
.len-btn{padding:9px 14px;background:transparent;border:none;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;letter-spacing:.03em;cursor:pointer;transition:background .12s,color .12s;white-space:nowrap}
.len-btn+.len-btn{border-left:1px solid var(--border)}
.len-btn.sel{background:var(--gold);color:#1c1710}
.btn-outline.active{background:var(--gold);color:#0f0e0c}
.ai-picker-wrap{position:relative;display:inline-flex}
/* Create-game dropdown: vs Friend on top, then the AI opponents, stacked as a menu. */
.ai-picker{position:absolute;top:calc(100% + 8px);left:50%;transform:translateX(-50%);z-index:30;display:flex;flex-direction:column;gap:6px;align-items:stretch;min-width:200px;max-width:min(92vw,300px);padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:0 10px 28px rgba(0,0,0,.5)}
.ai-picker .btn{white-space:nowrap}
.ai-picker-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.06em;color:var(--text-dim);text-transform:uppercase;text-align:center;margin-top:4px;padding-top:8px;border-top:1px solid var(--border)}
.browser-section{margin-bottom:32px}
.section-hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.section-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;letter-spacing:.18em;color:var(--gold);text-transform:uppercase}
.game-cards{display:flex;flex-direction:column;gap:8px}
.game-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;display:flex;align-items:center;gap:14px;transition:border-color .15s}
.game-card:hover{border-color:rgba(201,168,76,.4)}
.game-card-info{flex:1;min-width:0}
.game-card-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.88rem;letter-spacing:.04em;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.game-card-meta{font-size:.78rem;color:var(--text-dim)}
.game-card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}
/* Open Games: current lobby size (e.g. 1/4) next to the host name. */
.lobby-size{margin-left:8px;font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;font-size:.82rem;font-weight:600;letter-spacing:0;color:var(--gold)}
/* Active Games: one player per line (override the base nowrap/ellipsis). */
.game-card-title.matchup{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.35}
/* Lobby: Open Games + History side by side (stack on narrow screens). */
/* Lobby: left column = Open + Active stacked, right column = History on its own (so its
   length never pushes Active Games down). The widened .browser uses the empty side space
   WITHOUT thinning the games columns. grid-template-rows:min-content auto keeps Active
   directly under Open even when History (spanning both rows) is much longer. Stacks <1200px. */
/* Lobby: three adjacent columns — Open Games | Active Games | History — each its own
   column so none pushes another down. The widened .browser uses the empty side space.
   Collapses to 2 columns (Open|Active, History spanning below) under 1280px, then 1
   column under 780px. */
.lobby-grid{display:grid;grid-template-columns:1fr 1fr 340px;gap:24px 28px;align-items:start;margin-bottom:32px}
.lobby-grid>.browser-section{min-width:0;margin-bottom:0}
/* Explicit grid-row on EVERY item is REQUIRED (do not remove): the DOM order is
   Open, History, Active, so with column-only placement the sparse auto-flow cursor
   (past col 3 after History) wraps Active down to row 2 — looking "pushed down" below
   the tall History. Pinning rows makes placement ignore DOM order. */
.lobby-grid>.open-section{grid-column:1;grid-row:1}
.lobby-grid>.active-section{grid-column:2;grid-row:1}
.lobby-grid>.history-section{grid-column:3;grid-row:1}
/* Mobile-only tabbed lobby: a segmented bar that picks one section to show in the
   single-column layout (see the max-width:780px block). Hidden on desktop, where all
   three sections show side by side. */
.lobby-tabs{display:none;gap:6px;margin-bottom:18px;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:4px}
.lobby-tab{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:7px;background:transparent;border:none;color:var(--text-dim);cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;letter-spacing:.04em;padding:9px 4px;border-radius:9px;transition:background .15s,color .15s}
.lobby-tab.sel{background:var(--gold);color:#0f0e0c;font-weight:700}
.lobby-tab-count{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:rgba(0,0,0,.18);color:inherit;font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;font-size:.72rem;font-weight:600;letter-spacing:0}
.lobby-tab:not(.sel) .lobby-tab-count{background:var(--surface);color:var(--text-muted)}
/* Each column's card list behaves like the in-game move log: capped to the viewport
   and scrolls INTERNALLY instead of growing the page (the long History list otherwise
   made the page very tall). Desktop 3-col only — tablet/phone stack and scroll the
   page normally. scrollbar-gutter:stable reserves the scrollbar's space so a column
   doesn't shift when its list starts/stops scrolling. */
@media(min-width:1281px){
  .lobby-grid .game-cards{max-height:calc(100vh - 230px);overflow-y:auto;scrollbar-gutter:stable}
  .lobby-grid .game-cards::-webkit-scrollbar{width:6px}
  .lobby-grid .game-cards::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
}
@media(max-width:1280px){
  .lobby-grid{grid-template-columns:1fr 1fr}
  .lobby-grid>.open-section{grid-column:1;grid-row:1}
  .lobby-grid>.active-section{grid-column:2;grid-row:1}
  .lobby-grid>.history-section{grid-column:1 / span 2;grid-row:2}
}
@media(max-width:780px){
  /* Single column, one section at a time selected by the tab bar above. */
  .lobby-tabs{display:flex}
  .lobby-grid{grid-template-columns:1fr;gap:0}
  .lobby-grid>.browser-section{grid-column:1;grid-row:auto;margin-bottom:0}
  /* Show only the active tab's section. */
  .lobby-grid.tab-open>.active-section,
  .lobby-grid.tab-open>.history-section,
  .lobby-grid.tab-active>.open-section,
  .lobby-grid.tab-active>.history-section,
  .lobby-grid.tab-history>.open-section,
  .lobby-grid.tab-history>.active-section{display:none}
  /* The tab already labels the section — drop the big redundant heading, keep the
     muted context line on its own. */
  .lobby-grid .section-hd .section-title{display:none}
  .lobby-grid .section-hd{margin-bottom:10px}
}
/* History cards: Won/Lost badge + the final scores (winner brighter), wraps freely. */
.history-card .game-card-title{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;white-space:normal;overflow:visible}
.hist-result{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.6rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:10px;flex-shrink:0}
.hist-result.won{background:rgba(63,156,46,.18);color:var(--green-gem)}
.hist-result.lost{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
.hist-scores{color:var(--text-dim);font-size:.84rem;font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;letter-spacing:0}
.hist-score-num{color:var(--text);font-weight:600}
.your-turn-badge{background:var(--gold);color:#0f0e0c;padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.63rem;letter-spacing:.12em;font-weight:700;text-transform:uppercase;white-space:nowrap}
.playing-badge{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border);padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.63rem;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.empty-state{text-align:center;padding:28px 16px;color:var(--text-dim);font-style:italic;font-size:.9rem;background:var(--surface2);border-radius:var(--radius);border:1px dashed var(--border)}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
/* Fixed square size + centered content so swapping the ↻ glyph for the spinner
   (which carries a margin for its 'Loading…' use) doesn't resize the button and
   shift the centered button row. */
.refresh-btn{background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:.9rem;padding:0;width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;border-radius:4px;transition:color .15s;flex-shrink:0}
.refresh-btn:hover{color:var(--gold)}
.refresh-btn .spinner{margin:0}

/* ─── Waiting ───────────────────────────────────────────────────────────── */
.waiting-screen{max-width:480px;margin:0 auto;padding:48px 20px 24px;text-align:center}
.waiting-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.1rem;color:var(--gold);margin-bottom:6px;letter-spacing:.1em}
.waiting-sub{color:var(--text-dim);font-size:.85rem;margin-bottom:24px}
.room-code-box{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2.2rem;letter-spacing:.3em;color:var(--gold-light);text-align:center;padding:18px;background:var(--surface2);border-radius:var(--radius);margin-bottom:20px;border:1px solid var(--border);cursor:pointer;transition:border-color .15s}
.room-code-box:hover{border-color:var(--gold)}
.player-list{list-style:none;margin:0 0 20px}
.player-list li{display:flex;align-items:center;gap:8px;padding:9px 14px;background:var(--surface2);border-radius:var(--radius);margin-bottom:6px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;letter-spacing:.05em}
.player-list li.me{border:1px solid var(--gold);color:var(--gold)}
.copy-hint{font-size:.75rem;color:var(--text-muted);font-style:italic;margin-bottom:12px}

/* ─── Game layout ───────────────────────────────────────────────────────── */
/* overflow-x:clip (not hidden) keeps stray horizontal overflow contained WITHOUT
   making .game a scroll container — hidden made it one, which broke the sticky
   action bar's offset (it was measured against .game, not the viewport). */
.game{display:grid;grid-template-columns:1fr 272px;gap:12px;padding:10px;flex:1;min-height:0;width:100%;max-width:100%;overflow-x:clip}
@media(max-width:900px){.game{grid-template-columns:1fr}}
/* min-width:0 stops a grid track's implicit min-width:auto from growing past the
   viewport when a child (e.g. the horizontally-scrolling card rows) is wide —
   the overflow is what made mobile Safari fit-to-content and render zoomed out. */
.game-main{display:flex;flex-direction:column;gap:10px;min-width:0}
.game-sidebar{display:flex;flex-direction:column;gap:10px;min-width:0}
@media(max-width:900px){
  .game-sidebar{order:-1}
  /* Tablet + phone: the nobles and an actions box (the win-points Target + the
     Take/Buy/✕ controls) sit side by side as TWO SEPARATE boxes — the nobles box
     hugs only the nobles, the actions box fills the space to its right. They stack
     (wrap) if the row gets too narrow. The outer .nobles-panel goes transparent so
     it's just a flex row holding the two boxes. (Selectors are deliberately
     higher-specificity so they beat the unconditional .panel / .board-actions
     base rules that appear LATER in the stylesheet — esp. .board-actions{display:none},
     which otherwise hid the box on mobile entirely.) */
  .nobles-panel.panel{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;background:none;border:none;border-radius:0;padding:0}
  .nobles-panel .panel-title{display:none}
  .nobles-panel .nobles-row{flex:0 0 auto;align-content:center;gap:6px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:8px}
  /* justify-content:flex-start pins the Target to the TOP so it doesn't shift up
     when the Take/Buy/✕ buttons appear below it. */
  .nobles-panel .board-actions{flex:1 1 auto;min-width:118px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:8px;position:relative}
  .board-actions .target-label{font-size:1rem}
  .board-actions-btns{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:center}
  .board-actions-btns:empty{display:none}
  .board-actions .btn{padding:9px 14px}
}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px}
.panel-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;letter-spacing:.14em;color:var(--gold);margin-bottom:10px;text-transform:uppercase}

/* ─── Bank ──────────────────────────────────────────────────────────────── */
.bank-gems{display:flex;gap:8px;flex-wrap:wrap}
/* Desktop: the three level boxes sit in a column with the same 10px gap they had
   as direct game-main children; the board-actions (mobile button group beside the
   nobles) is hidden because the controls live in the action bar. Mobile below. */
.levels{display:flex;flex-direction:column;gap:10px}
.board-actions{display:none}
.gem-stack{display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;transition:transform .12s;user-select:none}
.gem-stack:hover .gem-token{transform:scale(1.08)}
.gem-stack.selected .gem-token{box-shadow:0 0 0 2px var(--gold-light),0 0 12px rgba(232,201,106,.3)}
.gem-stack.disabled{opacity:.35;cursor:not-allowed}
.gem-stack.reserve-ready .gem-token{box-shadow:0 0 0 2px var(--gold-light),0 0 14px rgba(232,201,106,.6);animation:reserve-pulse 1.1s ease-in-out infinite}
@keyframes reserve-pulse{0%,100%{box-shadow:0 0 0 2px var(--gold-light),0 0 8px rgba(232,201,106,.45)}50%{box-shadow:0 0 0 2px var(--gold-light),0 0 18px rgba(232,201,106,.85)}}
.gem-token{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:.95rem;border:2px solid rgba(255,255,255,.12);transition:all .12s}
.gem-count{font-size:.75rem;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif}

/* ─── Cards ─────────────────────────────────────────────────────────────── */
/* overflow-x:auto clips both axes, which would cut off the hover lift / top border
   and the selection outline of the first & last items (flush at the clip edges).
   Padding on all sides + matching -margin gives clip-room without moving the row. */
.level-row{display:flex;gap:8px;align-items:flex-start;flex-wrap:nowrap;overflow-x:auto;padding:6px 4px 4px;margin:-6px -4px 0}
.level-row::-webkit-scrollbar{height:4px}.level-row::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.deck-pile{width:var(--card-w,88px);min-height:var(--card-h,120px);border-radius:var(--radius);border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;color:var(--text-dim);cursor:pointer;flex-shrink:0;background:var(--surface2);transition:all .12s;flex-direction:column;gap:4px}
.deck-pile:hover{border-color:var(--gold);color:var(--gold)}
.deck-pile.selected{border-color:var(--gold-light);color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.deck-pile.disabled{cursor:not-allowed;opacity:.5}
.deck-remaining{font-size:1.3rem;font-weight:700;color:var(--text);font-family:'Cinzel','Cinzel Fallback',serif}
.card{width:var(--card-w,88px);min-height:var(--card-h,120px);border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:8px 6px 6px;display:flex;flex-direction:column;cursor:pointer;transition:all .15s;flex-shrink:0;position:relative}
.card-slot{width:var(--card-w,88px);flex-shrink:0}
/* Each cell in a level row (deck pile / card / empty slot) shares the row width
   equally but never exceeds --card-w (88px default; bigger on desktop). A full
   level (deck + 4 cards) always fits the column width — no horizontal scroll or
   clipped card — at every size. */
.level-row>*{flex:1 1 0;min-width:0;max-width:var(--card-w,88px)}
.ai-val{position:absolute;bottom:5px;right:5px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.4);border-radius:4px;padding:0 4px;line-height:1.4;pointer-events:none}
.ai-vals{position:absolute;bottom:3px;right:3px;display:grid;grid-template-columns:auto auto;gap:0 5px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.5rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.5);border-radius:4px;padding:2px 4px;line-height:1.4;pointer-events:none}
.ai-vals b{color:#9a8fb0;font-weight:700;margin-right:1px}
/* "mine" = overlay computed for the player on the move (your turn) — tinted green to
   distinguish from the AI's own values (gold), since the overlay flips with the turn. */
.ai-vals.mine,.ai-val.mine{color:#8fdca0;box-shadow:0 0 0 1px rgba(143,220,160,.55)}
/* The "Show AI values" toggle sits at the far LEFT of the actions box (Take/Buy stay
   to its right); same gold styling as the action buttons via .btn.btn-gold. */
.ai-vals-toggle{margin-right:auto}
/* S's whole-position eval chip, shown beside the toggle when the overlay is on (S games only). */
.ai-pos-eval{display:inline-flex;align-items:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.4);border:1px solid rgba(201,168,76,.4);border-radius:5px;padding:1px 7px;white-space:nowrap}
.ai-pos-eval.mine{color:#8fdca0;border-color:rgba(143,220,160,.5)}
.ai-pos-eval b{color:#9a8fb0;font-weight:700;margin-right:3px}
.ai-pos-eval-srch{margin-left:7px;padding-left:7px;border-left:1px solid rgba(201,168,76,.3)}
/* Pinned to the top-right of the actions box (absolute) so it never displaces the
   Target / buttons / hint. The box is position:relative (.actions-panel / .board-actions). */
.ai-pos-eval-row{position:absolute;top:7px;right:9px;display:flex;z-index:2}
.card:hover{border-color:rgba(201,168,76,.5);transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.4)}
.card.selected{border-color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.card.affordable{border-color:var(--green-gem)}
.card.affordable-gold{border-color:var(--gold-light)}
.card.disabled{cursor:not-allowed;opacity:.6}
.card-back{cursor:default;align-items:center;justify-content:center;gap:8px;border-style:dashed;background:repeating-linear-gradient(45deg,var(--surface2),var(--surface2) 6px,var(--surface) 6px,var(--surface) 12px)}
.card-back:hover{transform:none;border-color:var(--border);box-shadow:none}
.card-back-level{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.3rem;color:var(--text-dim)}
.card-back-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.55rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase}
.card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.card-points{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.1rem;color:var(--gold);min-width:16px}
.card-points.zero{color:transparent}
.card-bonus{width:20px;height:20px;border-radius:50%;flex-shrink:0;border:1.5px solid rgba(255,255,255,.25)}
.card-cost{display:flex;flex-direction:column;gap:3px;margin-top:auto}
.cost-row{display:flex;align-items:center;gap:4px}
.cost-gem{width:10px;height:10px;border-radius:50%;flex-shrink:0;border:1px solid rgba(255,255,255,.25)}
.cost-num{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;color:var(--text-dim)}

/* ─── Nobles ────────────────────────────────────────────────────────────── */
.nobles-row{display:flex;gap:8px;flex-wrap:wrap}
.noble{width:72px;min-height:72px;border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:6px;display:flex;flex-direction:column;align-items:center;gap:4px}
.noble-points{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1rem;font-weight:700;color:var(--gold)}
.noble-req{display:flex;flex-direction:column;gap:2px;width:100%}
.noble-req-row{display:flex;gap:3px;align-items:center;font-size:.65rem;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif}
.noble-req-dot{width:8px;height:8px;border-radius:2px;border:1px solid rgba(255,255,255,.12);flex-shrink:0}
/* claimer name on a taken noble — absolutely pinned to the bottom so it sits at the
   same height no matter how many requirement rows the noble has (4/4 vs 3/3/3) */
.noble-claimer{position:absolute;left:3px;right:3px;bottom:4px;text-align:center;font-size:.55rem;color:var(--gold);font-family:'Cinzel','Cinzel Fallback',serif;letter-spacing:.04em;line-height:1.05;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ─── Action bar ────────────────────────────────────────────────────────── */
/* The turn/action bar is removed on all sizes now — the Take/Buy/✕ controls live
   in the gem bank (desktop) or beside the nobles (mobile/tablet). */
.action-bar{display:none}
/* The desktop-only actions box (hint + buttons beside the nobles) is hidden on
   mobile/tablet, where the controls live next to the nobles via .board-actions. */
.actions-panel{display:none}
.action-hint{flex:1;font-style:italic;color:var(--text-dim);font-size:.88rem;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.target-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.05rem;font-weight:700;letter-spacing:.08em;color:var(--gold);text-transform:uppercase;flex-shrink:0}
.action-bar-btns{display:flex;gap:8px;align-items:center;flex-shrink:0;min-width:150px;justify-content:flex-end}
.action-bar-spacer{visibility:hidden;pointer-events:none;transition:none}
.turn-badge{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.08em;padding:4px 12px;border-radius:20px;white-space:nowrap}
.turn-badge.mine{background:var(--gold);color:#0f0e0c}
.turn-badge.theirs{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
.ai-variant-badge{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.6rem;letter-spacing:.1em;padding:2px 8px;border-radius:20px;background:var(--surface2);color:var(--text-dim);border:1px solid var(--border);white-space:nowrap}
.gap-8{display:flex;gap:8px;flex-wrap:wrap}

/* ─── Player panels ─────────────────────────────────────────────────────── */
.players-area{display:flex;flex-direction:column;gap:8px}
.player-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px;transition:border-color .2s}
/* the active player's box gets a clean gold rounded border (the only highlight);
   your own box is identified by the active dot + "(you)" label, no extra accent. */
.player-panel.active-turn{border-color:var(--gold);background:var(--surface3)}
/* an opponent's box is tappable to ping them — signal it (your own box has no click). */
.player-panel.pingable{cursor:pointer}
.player-panel.pingable:active{border-color:var(--gold)}
.player-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.player-name-row{display:flex;align-items:center;gap:6px}
.player-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;letter-spacing:.06em}
.active-dot{width:6px;height:6px;border-radius:50%;background:var(--gold);flex-shrink:0;animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.player-score{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.1rem;font-weight:700;color:var(--gold)}
.player-tokens{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}
.token-pill{display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;font-weight:700}
.player-bonuses{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;margin-bottom:6px}
.bonus-pill{display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;font-weight:700;border:1px solid}
.reserved-label{font-size:.62rem;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif;letter-spacing:.06em;margin-bottom:4px;text-transform:uppercase}
.reserved-row{display:flex;gap:4px;flex-wrap:wrap}
.gem-total{display:inline-block;font-size:.66rem;color:var(--text);font-family:'Cinzel','Cinzel Fallback',serif;font-weight:600;letter-spacing:.03em;margin-top:3px;background:var(--surface3);border:1.5px solid #7a6e58;padding:1px 8px;border-radius:8px;box-shadow:0 0 0 1px rgba(0,0,0,.5)}
/* Compact mobile player summary + log caret — hidden on desktop (shown only in
   the max-width:600px block below), so the laptop layout is unchanged. */
.player-summary{display:none;flex-wrap:wrap;gap:5px;align-items:center;margin-top:8px}
.sum-chip{display:inline-flex;align-items:center;gap:3px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;font-weight:700;color:var(--text)}
.sum-dot{width:11px;height:11px;border-radius:50%;border:1px solid rgba(255,255,255,.25);flex-shrink:0}
.sum-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.56rem;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted)}
.sum-div{width:1px;align-self:stretch;min-height:14px;background:var(--border);margin:0 3px}
.sum-none{color:var(--text-muted);font-size:.74rem}
.sum-noble{color:var(--gold)}
.sum-caret{margin-left:auto;cursor:pointer;color:var(--gold);font-size:.72rem;font-family:'Cinzel','Cinzel Fallback',serif;letter-spacing:.04em}
.log-caret{display:none}

/* ─── Winner ────────────────────────────────────────────────────────────── */
.winner-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:32px}
.winner-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:3rem;color:var(--gold);margin-bottom:8px;letter-spacing:.04em}
.winner-title.defeat{color:var(--text-dim)}
.winner-sub{color:var(--text-dim);font-style:italic;margin-bottom:32px}
.final-scores{display:flex;flex-direction:column;gap:8px;margin-bottom:32px}
.score-row{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.05rem;padding:10px 28px;background:var(--surface);border-radius:var(--radius);border:1px solid var(--border)}
.score-row.winner{border-color:var(--gold);color:var(--gold)}

/* ─── Move log ──────────────────────────────────────────────────────────── */
.move-log{display:flex;flex-direction:column;gap:0;max-height:200px;overflow-y:auto;overflow-x:hidden}
.log-empty{color:var(--text-muted);font-style:italic;font-size:.85rem;padding:4px 0}
.move-log::-webkit-scrollbar{width:3px}.move-log::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.log-entry{display:flex;gap:6px;align-items:baseline;font-size:.76rem;color:var(--text-dim);padding:4px 0;line-height:1.4;animation:log-in .2s ease}
.log-entry+.log-entry{border-top:1px solid rgba(58,52,42,.4)}
.log-entry:first-child{color:var(--text)}
.log-entry.clickable{cursor:pointer}
.log-entry.clickable:hover{background:rgba(201,168,76,.08);border-radius:4px}
/* Review: the turn currently shown on the board is highlighted in the log. */
.log-entry.log-selected{background:rgba(201,168,76,.2);border-radius:4px;box-shadow:inset 2px 0 0 var(--gold)}
/* "X won the game" marker at the top of a finished game's log. */
.log-entry.log-win .log-action{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;letter-spacing:.04em;color:var(--gold-light);font-weight:600}
/* "Game started" anchor at the bottom of the log (jumps to the initial board). */
.log-entry.log-start .log-action{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.04em;color:var(--text-dim)}
/* Review controls in the action bar: Prev / where / Next / Latest. */
.replay-nav{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.replay-where{font-size:.78rem;color:var(--text-dim);white-space:nowrap;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.replay-move{color:var(--text-muted)}
.log-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.7rem;color:var(--gold-light);flex-shrink:0}
.log-action{flex:1}
@keyframes log-in{from{opacity:0;transform:translateX(6px)}to{opacity:1;transform:none}}

/* ─── Card animations ───────────────────────────────────────────────────── */
@keyframes card-appear{from{opacity:0;transform:scale(.82) translateY(-6px)}to{opacity:1;transform:none}}
.card{animation:card-appear .22s ease}

/* ─── Gem flash ─────────────────────────────────────────────────────────── */
@keyframes gem-pop{0%,100%{transform:scale(1)}45%{transform:scale(1.3)}}
.gem-stack.flashing .gem-token{animation:gem-pop .38s ease}

/* ─── Flying gems (action animations) ───────────────────────────────────────
   A fixed overlay layer of gem dots animated between the bank and a player box;
   per-flyer --dx/--dy/--s0/--s1 set the trip + start/end scale. */
.fly-layer{position:fixed;inset:0;pointer-events:none;z-index:90}
.fly-gem{position:fixed;border-radius:50%;border:2px solid rgba(255,255,255,.3);box-shadow:0 2px 10px rgba(0,0,0,.55);animation:fly .42s ease both;will-change:transform,opacity}
.fly-card{position:fixed;border-radius:8px;background:var(--surface2);border:2px solid var(--border);box-shadow:0 6px 20px rgba(0,0,0,.6);display:flex;align-items:flex-start;justify-content:space-between;padding:6px 8px;overflow:hidden;transform-origin:center;animation:fly .5s ease both;will-change:transform,opacity}
.fly-card-pt{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:var(--gold);font-size:1.3rem;line-height:1}
.fly-card-dot{width:18px;height:18px;border-radius:50%;border:1px solid rgba(255,255,255,.3);flex-shrink:0}
@keyframes fly{from{transform:translate(0,0) scale(var(--s0));opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1));opacity:.5}}

/* ─── AI thinking dots ──────────────────────────────────────────────────── */
.ai-thinking{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;color:var(--text-muted);font-style:italic}
.think-dot{width:5px;height:5px;border-radius:50%;background:var(--text-muted);animation:think-blink .9s ease-in-out infinite}
.think-dot:nth-child(2){animation-delay:.2s}.think-dot:nth-child(3){animation-delay:.4s}
@keyframes think-blink{0%,100%{opacity:.25;transform:scale(.7)}50%{opacity:1;transform:scale(1.2)}}

/* ─── Toast ─────────────────────────────────────────────────────────────── */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--surface);border:1px solid var(--gold);padding:10px 20px;border-radius:var(--radius);font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;color:var(--gold);z-index:999;pointer-events:none;animation:fadeup .3s ease;white-space:nowrap}
@keyframes fadeup{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}

/* ─── Discard modal ─────────────────────────────────────────────────────── */
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.8);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px;max-width:400px;width:90%}
.modal h3{font-family:'Cinzel','Cinzel Fallback',serif;color:var(--gold);margin-bottom:8px}
.modal p{color:var(--text-dim);font-size:.9rem;margin-bottom:16px}
.discard-gems{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-bottom:16px}
.discard-btn{padding:8px 16px;border-radius:var(--radius);border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;transition:all .12s;display:flex;align-items:center;gap:6px}
.discard-btn:hover{border-color:var(--gold);color:var(--gold)}
.discard-count{text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;color:var(--text-dim);font-size:.85rem}

/* ─── Error/status ──────────────────────────────────────────────────────── */
.error-msg{font-size:.88rem;color:var(--red-gem);text-align:center;padding:6px 0}
.status-msg{font-size:.85rem;color:var(--text-dim);font-style:italic;text-align:center;padding:6px 0;display:flex;align-items:center;justify-content:center}
.small-muted{font-size:.8rem;color:var(--text-muted)}
.mt-8{margin-top:8px}.mt-12{margin-top:12px}

/* ─── Game nav bar ──────────────────────────────────────────────────────── */
.game-nav{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;padding-top:calc(env(safe-area-inset-top,0px) + 8px);border-bottom:1px solid var(--border);background:var(--surface);position:fixed;top:0;left:0;right:0;z-index:50}
.game-nav-spacer{height:calc(env(safe-area-inset-top,0px) + 48px);flex-shrink:0}
.game-nav-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.16em;color:var(--gold);text-transform:uppercase}

/* ── Desktop (wide) game layout ──────────────────────────────────────────────
   game-main becomes a 2-column grid: a big-card board on the left and the gem
   bank as a vertical column on its right (so the bank sits just left of the
   player sidebar). The Take/Buy/✕ controls move to the top of the gem bank, and
   cards get much larger (--card-w/--card-h). */
@media(min-width:901px){
  /* PROPORTIONAL desktop layout. The prod look (nobles+actions on top of the card
     board, vertical gem bank on the right, players+log sidebar) is preserved EXACTLY
     — only the sizing model changed: instead of fixed 144x185 cards + five max-height
     breakpoints that STEP the board down in discrete jumps (so it looked different at
     each resolution), there is now ONE viewport-driven anchor, --card-h, and EVERY
     desktop dimension below is a calc() ratio of it. So the whole board scales as one
     unit and looks identical at 1280x720 / 1920x1080 / 2560x1600 (clamp() only
     floors/caps it on extreme screens). Ratios = the old full-size px / 185.
     NOTE: never put backticks in this CSS string — it's a JS template literal. */
  .game-screen{height:100vh;overflow:hidden}
  /* --card-h drives everything; --card-w keeps the prod 144:185 (0.778) aspect.
     17vh scales the board with the window; clamp floors/caps it. Defined on .game so
     BOTH the board (.game-main) and the sidebar inherit the same anchor. */
  .game{
    --card-h:clamp(150px, 23vh, 330px);
    --card-w:calc(var(--card-h) * 0.72);
    /* Nobles get their OWN capped anchor so they don't bloat (and wrap) when --card-h
       grows to fill a tall screen — they stay ~prod-sized (120px) on big screens. */
    --noble-w:min(calc(var(--card-h) * 0.6), 128px);
    /* ONE gap token used for EVERY gap (board padding, board<->sidebar, between the
       nobles/actions row and the cards, between card levels, between cards, sidebar
       columns) so all spacing is identical at any resolution. */
    --gap:calc(var(--card-h) * 0.05);
    grid-template-columns:minmax(0,1fr) clamp(520px, 40vw, 720px);
    grid-template-rows:minmax(0,1fr);flex:none;height:calc(100vh - 48px);overflow:hidden;
    max-width:2050px;margin-inline:auto;width:100%;
    gap:var(--gap);padding:var(--gap)}
  .game-sidebar{display:grid;grid-template-columns:1.55fr 1fr;grid-template-rows:minmax(0,1fr);column-gap:var(--gap);align-items:stretch;min-height:0}
  .game-sidebar>.players-area{grid-column:1;grid-row:1;height:100%}
  .game-sidebar .player-panel{flex:1;min-height:0;overflow-y:auto}
  .game-sidebar>.log-panel{grid-column:2;grid-row:1;height:100%;display:flex;flex-direction:column}
  /* Board grid: col1 nobles (auto) | col2 cards (1fr) | col3 vertical bank.
     Row1 = nobles + actions; Row2 (1fr) = the three card rows. */
  .game-main{display:grid;grid-template-columns:auto 1fr calc(var(--card-h) * 0.55);grid-template-rows:auto 1fr;column-gap:var(--gap);row-gap:var(--gap);align-items:start}
  /* Bottom-align the (shorter) nobles to row 1's baseline so the gap from the nobles
     down to Level III == --gap too (the taller actions panel sets row 1's height). */
  .game-main>.nobles-panel{grid-column:1;grid-row:1;align-self:end}
  .actions-panel{grid-column:2;grid-row:1;align-self:stretch;display:flex;flex-direction:column;justify-content:space-between;align-items:stretch;gap:calc(var(--card-h) * 0.043);position:relative;min-width:0}
  /* The card levels FILL row 2 with a uniform --gap between them: each .level-panel is
     flex:1 (so the panels — the real flex children of .levels — divide row 2 equally
     and L1 reaches the bottom), the .level-row inside fills the panel, and the cards
     stretch to the row height. The gap between levels then == the grid row-gap above
     Level III == the board padding below Level I == --gap (all identical). Each level keeps
     its OWN box (the .level-panel gets the panel border/background/radius + --gap padding);
     because the panels are flex:1 they still fill row 2 with a uniform --gap between boxes
     (not the big space-between gaps from before). */
  .game-main>.levels{grid-column:1 / 3;grid-row:2;align-self:stretch;justify-content:flex-start;gap:var(--gap)}
  .game-main .level-panel{flex:1 1 0;min-height:0;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:var(--gap)}
  .game-main .level-panel>.level-row{flex:1 1 0;min-height:0;margin:0;padding:0}
  .bank-panel{grid-column:3;grid-row:1 / span 2;align-self:stretch;display:flex;flex-direction:column}

  /* Nobles: horizontal row on top of the cards, square, no title. Sized off the capped
     --noble-w (NOT --card-h) so they stay compact + never wrap on tall screens. */
  .nobles-panel .panel-title{display:none}
  .nobles-row{gap:calc(var(--noble-w) * 0.12);flex-wrap:nowrap}
  /* Point value pinned at the TOP (justify-content:flex-start, so it never shifts with
     the number of requirements); requirements fill the rest and sit centered on the LEFT
     (flex:1 + justify-content:center vertically + align-items:flex-start horizontally). */
  .noble{width:var(--noble-w);aspect-ratio:1;padding:calc(var(--noble-w) * 0.08);justify-content:center;align-items:flex-start;position:relative}
  /* points absolutely pinned near the top (so they never shift with req count);
     reqs are the only flow child, so justify-content:center on the noble centers them
     around the box's vertical middle, align-items:flex-start keeps them on the left. */
  .noble-points{font-size:calc(var(--noble-w) * 0.28);position:absolute;top:calc(var(--noble-w) * 0.05);left:0;right:0;text-align:center;line-height:1}
  .noble-req{gap:calc(var(--noble-w) * 0.03);flex:0 0 auto;justify-content:center;align-items:flex-start}
  .noble-req-row{font-size:calc(var(--noble-w) * 0.14);gap:calc(var(--noble-w) * 0.04)}
  .noble-req-dot{width:calc(var(--noble-w) * 0.09);height:calc(var(--noble-w) * 0.09)}
  .noble-claimer{font-size:calc(var(--noble-w) * 0.11);bottom:calc(var(--noble-w) * 0.04)}

  /* Actions box: target pinned top, buttons centered, hint at the bottom. */
  /* The hint now only ever shows a short "Waiting for X…" (empty on your turn), so let it
     WRAP to the next line when the name is long (no ellipsis — show the full name).
     overflow-wrap:anywhere breaks a long unbroken name so it can never force the column
     wider (keeps the width guarantee); a 2-3 line wrap stays within the nobles' height, so
     it still doesn't grow the actions row that shrank the card board in 3-4p lobbies. */
  .actions-panel .action-hint{flex:0 0 auto;font-size:calc(var(--card-h) * 0.082);white-space:normal;overflow-wrap:anywhere;min-width:0;max-width:100%;color:var(--text-dim);font-style:italic}
  .actions-panel-top{display:flex;flex-direction:column;gap:calc(var(--card-h) * 0.022);align-items:stretch}
  .actions-panel .target-label{align-self:stretch}
  /* min-width:0 + max-width:100% keep the buttons WITHIN this 1fr column: the actions
     box can never grow its own grid track and shove the board/sidebar around (the 3-4p
     bug — a wide nobles row shrinks this column, and a too-wide button forced it back). */
  .actions-panel-btns{display:flex;flex-wrap:wrap;gap:calc(var(--card-h) * 0.054);align-items:center;justify-content:center;flex-shrink:0;min-width:0}
  .actions-panel-btns .btn{padding:calc(var(--card-h) * 0.076) calc(var(--card-h) * 0.08);font-size:calc(var(--card-h) * 0.097);max-width:100%}
  /* The admin "Vals" toggle is compact (much less wide than the Take/Buy buttons). */
  .actions-panel-btns .ai-vals-toggle,.board-actions-btns .ai-vals-toggle{padding:calc(var(--card-h) * 0.045) calc(var(--card-h) * 0.05);font-size:calc(var(--card-h) * 0.062)}

  /* Vertical gem bank, gems clustered toward the vertical center. */
  .bank-gems{flex-direction:column;align-items:center;flex:1;justify-content:center;gap:calc(var(--card-h) * 0.097)}
  .bank-gems .gem-token{width:calc(var(--card-h) * 0.346)!important;height:calc(var(--card-h) * 0.346)!important;font-size:calc(var(--card-h) * 0.121)!important}
  .bank-gems .gem-count{font-size:calc(var(--card-h) * 0.091)}

  /* Drop the Gem Bank + Players labels on desktop (the Log label stays). */
  .bank-panel .panel-title{display:none}
  .game-sidebar>.panel-title{display:none}

  /* Sidebar player + move-log boxes scale from the same --card-h anchor. Name/score are
     kept modest so the head doesn't wrap in the (narrower) sidebar. */
  .player-panel{padding:calc(var(--card-h) * 0.06)}
  .player-name{font-size:calc(var(--card-h) * 0.062)}
  .player-score{font-size:calc(var(--card-h) * 0.085)}
  /* Gems (up to 6: 5 colours + gold) and the card/bonus indicators must ALWAYS fit one
     row: nowrap + flex-shrink + compact padding so they scale to the panel width. */
  /* Small gap between pills so each pill is as WIDE as possible (≈1/6 of the row). */
  .player-tokens,.player-bonuses{flex-wrap:nowrap;min-width:0;gap:calc(var(--card-h) * 0.008)}
  /* small separation between the gems row and the card-indicator (bonus) row. */
  .player-bonuses{margin-top:calc(var(--card-h) * 0.035)}
  /* FIXED 1/6 (gems) / 1/5 (card indicators) so a full set fills the row EXACTLY, edge to
     edge — the prod capsule shape (wide), just BIG: big dot + big count, snug height. */
  .token-pill,.bonus-pill{min-width:0;justify-content:center;font-size:calc(var(--card-h) * 0.082);padding:calc(var(--card-h) * 0.018) calc(var(--card-h) * 0.006);gap:calc(var(--card-h) * 0.014);border-radius:999px;zoom:1;white-space:nowrap;overflow:hidden}
  .player-tokens .token-pill>span{width:calc(var(--card-h) * 0.078)!important;height:calc(var(--card-h) * 0.078)!important}
  .token-pill{flex:0 1 calc((100% - var(--card-h) * 0.04) / 6)}
  /* card indicators are the SAME 1/6 width as a gem pill (5 of them take 5/6, left-aligned). */
  .bonus-pill{flex:0 1 calc((100% - var(--card-h) * 0.04) / 6)}
  /* Centre the "N gems" counter equidistant between the gems row and the bonus row:
     gap above (its margin-top) == gap below (the bonus row's margin-top). */
  .gem-total{zoom:1;font-size:calc(var(--card-h) * 0.052);margin-top:calc(var(--card-h) * 0.035);margin-bottom:0}
  /* Each reserved card is a FIXED 1/3 of the row (3 fill it; fewer are left-aligned at
     that same size, NOT stretched). flex-grow:0 = no stretch, basis = 1/3 of the row.
     Content (points / bonus colour / cost) is sized off the card's OWN width via a
     container query (cqw), NOT --card-h: the reserved-card width depends on the sidebar
     (which clamps differently from --card-h across resolutions), so a fixed --card-h
     multiple under/over-shoots — a reserved card is ~0.8-1.0x a board card, not the 0.58x
     once assumed (that left the text ~half-size). Each content cqw = the board card's
     content-to-card-WIDTH ratio (board's --card-h multiple ÷ card-w=0.72·card-h), so the
     reserved content matches the board cards' proportions at every resolution.
     container-type:inline-size only contains the inline axis, so aspect-ratio:0.72 still
     derives the height, and the flex-basis (parent-driven) can't blow up circularly. */
  .player-reserved{width:100%;min-width:0}
  .player-reserved .reserved-row{flex-wrap:nowrap;gap:calc(var(--card-h) * 0.02);width:100%}
  /* cqw is used ONLY on the card's DESCENDANTS (they resolve it against this card);
     the card's OWN padding must NOT be cqw — on the container element itself cqw resolves
     against an ANCESTOR container/viewport, not the card — so padding stays --card-h-based. */
  .player-reserved .card{zoom:1;flex:0 0 calc((100% - var(--card-h) * 0.04) / 3);min-width:0;width:auto;aspect-ratio:0.72;height:auto;min-height:0;container-type:inline-size;padding:calc(var(--card-h) * 0.04) calc(var(--card-h) * 0.035)}
  .player-reserved .card-header{margin-bottom:7cqw}
  .player-reserved .card-points{font-size:23.8cqw;min-width:0}
  .player-reserved .card-bonus{width:25.4cqw;height:25.4cqw}
  .player-reserved .card-cost{gap:4.4cqw}
  .player-reserved .cost-gem{width:13.1cqw;height:13.1cqw}
  .player-reserved .cost-num{font-size:13cqw}
  .player-tokens{min-height:calc(var(--card-h) * 0.151);align-items:flex-start;flex-wrap:nowrap;margin-bottom:0}
  .move-log{max-height:calc(100vh - 140px);flex:1;min-height:0}
  .log-entry{font-size:calc(var(--card-h) * 0.095);padding:calc(var(--card-h) * 0.034) 0}
  .log-name{font-size:calc(var(--card-h) * 0.058)}

  /* Board cards: box comes from --card-w/--card-h (base .card rules); scale the
     inner content with the same anchor. */
  /* flex:1 makes each row take an equal share of row 2's height (so the three rows
     fill it and Level I is flush to the bottom); align-items:stretch makes the cards
     fill that row height (min-height:0 below lets stretch control it, not --card-h). */
  /* container-type:size makes the row a query container so each card can be sized as a
     TRUE contain box below (needs a definite size, which flex:1 + the grid give it). */
  .level-row{overflow-x:visible;gap:var(--gap);justify-content:center;flex:1 1 0;align-items:center;container-type:size}
  /* STRICT 0.72 (exactly the reserved-card proportion), NEVER wider: the width is the
     min of the per-card row slot ((100cqw - 4 gaps)/5) and 0.72 x the box height
     (100cqh) — i.e. the largest 0.72 box that fits BOTH dimensions — so a short box
     makes the card height-bound (still 0.72), never stretched wide. */
  .game-main .level-row>*{flex:0 0 auto;width:min(calc((100cqw - 4 * var(--gap)) / 5), calc(100cqh * 0.72));aspect-ratio:0.72;height:auto;min-height:0;min-width:0;max-width:none}
  .level-row .card{padding:calc(var(--card-h) * 0.049) calc(var(--card-h) * 0.043) calc(var(--card-h) * 0.043);justify-content:space-between}
  .level-row .card-header{margin-bottom:calc(var(--card-h) * 0.043)}
  .level-row .card-points{font-size:calc(var(--card-h) * 0.147)}
  .level-row .card-bonus{width:calc(var(--card-h) * 0.157);height:calc(var(--card-h) * 0.157)}
  .level-row .cost-gem{width:calc(var(--card-h) * 0.081);height:calc(var(--card-h) * 0.081)}
  .level-row .cost-num{font-size:calc(var(--card-h) * 0.08)}
  .level-row .card-cost{gap:calc(var(--card-h) * 0.027)}
  .level-row .deck-pile{font-size:calc(var(--card-h) * 0.068);gap:calc(var(--card-h) * 0.032)}
  .level-row .deck-remaining{font-size:calc(var(--card-h) * 0.147)}
}

@media(max-width:600px){
  .browser{padding:20px 14px 40px}
  .browser-title{font-size:1.4rem}
  .browser-header{padding-left:14px;padding-right:14px}
  /* Compact the toggle + Create Game so the pair fits side by side on phones. */
  .create-controls{gap:8px}
  .create-controls .len-btn{padding:8px 10px;font-size:.74rem}
  .create-controls .ai-picker-wrap>.btn{padding:10px 14px;font-size:.82rem}
  .game{padding:6px}
  .game-card{padding:10px 12px}

  /* ── Board-first compact mobile game layout ──────────────────────────────
     The board leads (bank -> cards -> nobles+actions); players, then the move
     log, drop below. */
  .game-sidebar{order:0}            /* undo desktop order:-1 -> board comes first */
  .game-main{gap:8px}
  .game-sidebar{gap:8px}
  .panel{padding:10px}
  /* Drop the section labels (Gem Bank / Nobles / Players) on mobile — the
     content is self-evident and they only cost vertical space. The move log's
     header (.log-head) is kept: it doubles as the expand control. */
  .game .panel-title:not(.log-head){display:none}

  /* The nav scrolls with the page on mobile instead of staying pinned. */
  .game-nav{position:static}
  .game-nav-spacer{display:none}

  /* The whole turn/action bar (badge + persona + hint + AI-values) is removed on
     mobile; its Take/Buy/✕ controls move beside the nobles instead. */
  .action-bar{display:none}

  /* Gem bank: full-width row of evenly spread tokens (unchanged layout). */
  .gem-token{width:38px;height:38px;font-size:.88rem}
  .bank-gems{gap:6px;justify-content:space-between}
  /* (nobles+buttons row handled in the max-width:900 block so tablets get it too) */

  /* L3 / L2 / L1 share a single box, rows tight together. */
  .levels{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:8px;gap:4px}
  .level-panel{background:none;border:none;border-radius:0;padding:0}
  .level-row{overflow-x:visible;margin:0;padding:2px 0}

  /* Compact player panels: cards + gems always shown via the summary row; the
     full pill detail is replaced by it, and only reserved cards hide behind the
     expand caret. */
  .player-panel{padding:9px 11px}
  .player-header{margin-bottom:0}
  .player-summary{display:flex}
  .player-detail{display:none}
  .player-reserved{display:none}
  .player-panel.expanded .player-reserved{display:block;margin-top:8px}
  .players-area{gap:6px}

  /* Push the move log below the player boxes (it's first in the sidebar DOM so
     it can lead on desktop's right column). */
  .log-panel{order:1}

  /* Move log: the most recent entry stays visible; tap to expand the rest. */
  .log-head{cursor:pointer;display:flex;align-items:center;gap:6px;margin-bottom:8px}
  .log-caret{display:inline;margin-left:auto}
  .log-panel:not(.open) .log-entry:not(:first-child){display:none}

  /* Tighter nobles so the row stays one screen-width. */
  .noble{width:62px;min-height:62px;padding:5px}
}
`;

// ─── Sub-components ───────────────────────────────────────────────────────

function GemToken({ color, size = 42 }) {
	return (
		<div className="gem-token" style={{
			background: GEM_HEX[color], width: size, height: size,
			color: color === "white" || color === "gold" ? "#333" : "#fff",
		}}>
			{color === "gold" ? "★" : color[0].toUpperCase()}
		</div>
	);
}

function CardView({ card, selected, affordable, needsGold, disabled, onClick, aiValue, valsMine, dataPos }) {
	// The AI-values overlay is computed for whoever's turn it is, so label whose values these are.
	const who = valsMine ? "Your values" : "AI's values";
	// An opponent's blind deck-top reserve is hidden info — show a face-down back, not the card.
	if (card.hidden) {
		return (
			<div className="card card-back">
				<span className="card-back-level">{["I", "II", "III"][(card.level || 1) - 1]}</span>
				<span className="card-back-label">Reserved</span>
			</div>
		);
	}
	return (
		<div data-pos={dataPos}
			className={`card${selected ? " selected" : ""}${affordable ? (needsGold ? " affordable-gold" : " affordable") : ""}${disabled ? " disabled" : ""}`}
			onClick={disabled ? undefined : onClick}
		>
			<div className="card-header">
				<span className={`card-points${card.points === 0 ? " zero" : ""}`}>{card.points || ""}</span>
				<div className="card-bonus" style={{ background: GEM_HEX[card.bonus] }} />
			</div>
			<div className="card-cost">
				{Object.entries(card.cost).map(([c, n]) => n > 0 && (
					<div key={c} className="cost-row">
						<div className="cost-gem" style={{ background: GEM_HEX[c] }} />
						<span className="cost-num">{n}</span>
					</div>
				))}
			</div>
			{aiValue != null && (typeof aiValue === "object" ? (
				<div className={`ai-vals${valsMine ? " mine" : ""}`} title={`${who} — ${aiValue._s
					? "S"
					: aiValue.pot != null
					? "H3"
					: "H2"} — take / engine / point / cost`}>
					<span><b>T</b>{aiValue.t}</span>
					<span><b>E</b>{aiValue.e}</span>
					<span><b>P</b>{aiValue.p}</span>
					<span><b>C</b>{aiValue.c}</span>
				</div>
			) : (
				<span className={`ai-val${valsMine ? " mine" : ""}`} title={`${who} (variant H)`}>{aiValue}</span>
			))}
		</div>
	);
}

function NobleView({ noble, claimedBy, dimmed }) {
	// A claimed noble is faded; its claimer name is absolutely pinned to the bottom
	// (and the points/reqs top-aligned) so the name sits at the same height on a
	// 2-row (4/4) noble as on a 3-row (3/3/3) one.
	return (
		<div className="noble" style={(claimedBy || dimmed) ? { opacity: 0.5, position: "relative", justifyContent: "flex-start" } : undefined}>
			<span className="noble-points">{noble.points}</span>
			<div className="noble-req">
				{Object.entries(noble.req).map(([c, n]) => (
					<div key={c} className="noble-req-row">
						<div className="noble-req-dot" style={{ background: GEM_HEX[c] }} />
						<span>{n}</span>
					</div>
				))}
			</div>
			{claimedBy && (
				<div className="noble-claimer">★ {claimedBy}</div>
			)}
		</div>
	);
}

// ─── useWebSocket ─────────────────────────────────────────────────────────

function useWebSocket(onMessage, { onOpen, onClose } = {}) {
	const wsRef = useRef(null);
	const onMsgRef = useRef(onMessage);
	const onOpenRef = useRef(onOpen);
	const onCloseRef = useRef(onClose);
	const urlRef = useRef(null);
	const intentionalRef = useRef(false);
	const retryTimerRef = useRef(null);
	onMsgRef.current = onMessage;
	onOpenRef.current = onOpen;
	onCloseRef.current = onClose;

	const connect = useCallback((url) => {
		intentionalRef.current = false;
		urlRef.current = url;
		if (retryTimerRef.current) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
		if (wsRef.current) wsRef.current.close();
		const ws = new WebSocket(url);
		wsRef.current = ws;
		const send = (data) => {
			if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data));
		};
		ws.onopen = (ev) => {
			try { onOpenRef.current?.({ event: ev, send }); } catch {}
		};
		ws.onclose = () => {
			try { onCloseRef.current?.(); } catch {}
			// auto-reconnect unless the user intentionally disconnected
			if (!intentionalRef.current && urlRef.current) {
				retryTimerRef.current = setTimeout(() => connect(urlRef.current), 2000);
			}
		};
		ws.onerror = () => {};
		ws.onmessage = (e) => {
			try { onMsgRef.current(JSON.parse(e.data)); } catch {}
		};
	}, []);

	const send = useCallback((data) => {
		if (wsRef.current?.readyState === WebSocket.OPEN)
			wsRef.current.send(JSON.stringify(data));
	}, []);

	const disconnect = useCallback(() => {
		intentionalRef.current = true;
		urlRef.current = null;
		if (retryTimerRef.current) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
		wsRef.current?.close();
		wsRef.current = null;
	}, []);

	// reconnect when the tab becomes visible (iOS kills sockets in the background)
	const getReadyState = useCallback(() => wsRef.current?.readyState ?? WebSocket.CLOSED, []);

	return { connect, send, disconnect, getReadyState };
}

// ─── Main App ──────────────────────────────────────────────────────────────

export default function SpenderApp() {
	// ── Persistent identity ────────────────────────────────────────────────
	const [authUser, setAuthUser] = useState(() => {
		try { const s = localStorage.getItem("spender_user"); if (s) return JSON.parse(s); } catch {}
		return null;
	});
	const [myId, setMyId] = useState(() => {
		try {
			const s = localStorage.getItem("spender_user");
			if (s) { const u = JSON.parse(s); if (u?.id) return u.id; }
			const g = localStorage.getItem("spender_myId");
			if (g) return g;
		} catch {}
		const id = uid();
		try { localStorage.setItem("spender_myId", id); } catch {}
		return id;
	});

	// ── Screen & room state ────────────────────────────────────────────────
	const [screen, setScreen] = useState("loading");
	const [loadingProgress, setLoadingProgress] = useState(0);
	const [showLoading, setShowLoading] = useState(false);
	const [modalCard, setModalCard] = useState(null);
	const [roomId, setRoomId] = useState("");
	const [roomData, setRoomData] = useState(null);
	// ── Game review / replay (read-only rewind of a finished game) ──
	const [reviewing, setReviewing] = useState(false);            // viewing a finished game's board + log
	const [replaySnapshots, setReplaySnapshots] = useState(null); // [{turn,mover,move,game}], or null = no turn-by-turn
	const [replayTurn, setReplayTurn] = useState(null);           // which past turn drives the board; null = final
	const [pinged, setPinged] = useState(false);                  // a ping arrived while the tab was hidden (drives the "waiting for you" tab alert)

	// ── Derived game state (must be before useEffect hooks that use `game`) ──
	const liveGame = roomData?.game;
	// In review you can rewind to any past turn: that snapshot drives the BOARD, while the
	// move log + card catalog stay sourced from the final game so every turn stays clickable.
	const reviewBoardGame = (replayTurn != null && replaySnapshots && replaySnapshots[replayTurn])
		? replaySnapshots[replayTurn].game : null;
	const game = reviewBoardGame || liveGame;
	// Admin AI-values overlay source: in review it rides on the rewound snapshot (static-only,
	// no searched eval); live it comes from roomData (which also carries the searched eval).
	const reviewSnap = reviewBoardGame ? replaySnapshots[replayTurn] : null;
	const aiCardValues = reviewSnap ? reviewSnap.ai_card_values : roomData?.ai_card_values;
	const aiValuesPid = reviewSnap ? reviewSnap.ai_values_pid : roomData?.ai_values_pid;
	const aiPositionEval = reviewSnap ? reviewSnap.ai_position_eval : roomData?.ai_position_eval;
	const aiPositionEvalSearched = reviewSnap ? null : roomData?.ai_position_eval_searched;
	const me = game?.players?.[myId];
	// No move is ever possible in review — force not-your-turn regardless of the rewound snapshot's phase.
	const myTurn = !reviewing && game?.turn === myId && game?.phase === "playing";
	const myBonuses = me ? bonusesFrom(me.purchased) : emptyGems();
	const aiThinking = !reviewing && game?.ai_player && game?.turn === game?.ai_player && game?.phase === "playing";
	// Derived from game state (not a transient message) so a later room_update
	// can't clear an unmet requirement — the server keeps these set until resolved.
	const needsDiscard = !reviewing && game?.pending_discard_pid === myId;
	const needsNobleChoice = !reviewing && game?.pending_noble_pid === myId;
	// Show the finished-game chrome (Back-to-Results / no Abandon) whenever we're looking at
	// a finished game — based on the LIVE game's phase, so a rewound snapshot's "playing"
	// phase never leaks live-game controls into review.
	const reviewChrome = reviewing || liveGame?.phase === "over";
	// Turn-by-turn navigation is available once snapshots loaded (a game predating the
	// setup snapshot has none — review still shows the final board).
	const replayNav = reviewing && Array.isArray(replaySnapshots) && replaySnapshots.length > 1;
	const replayIdx = replayTurn == null
		? (replaySnapshots ? replaySnapshots.length - 1 : 0)
		: replayTurn;
	// Catalog of every card currently visible in state (board + both players'
	// purchased/reserved), keyed by id. The move log stores only card_id (the server
	// log is id-only); this resolves those ids back to full cards for display + the
	// inspect modal. Complete by construction: a logged buy/reserve card is always
	// present somewhere in the live state (purchased/reserved/board).
	// Built from the FINAL game (liveGame), not the rewound snapshot, so every logged
	// card resolves even while the board is showing an earlier turn.
	const cardsById = useMemo(() => {
		const m = {};
		if (!liveGame) return m;
		const add = (c) => { if (c && c.id && c.cost) m[c.id] = c; };
		const b = liveGame.board || {};
		for (const lk of ["L1", "L2", "L3"]) (b[lk] || []).forEach(add);
		for (const p of Object.values(liveGame.players || {})) {
			(p.purchased || []).forEach(add);
			(p.reserved || []).forEach(add);
		}
		return m;
	}, [liveGame]);

	// Map each move-log entry (newest-first) to its 0-based turn index, so a click in the
	// log jumps the review board to that turn. A turn = one primary move (take/buy/reserve)
	// plus its trailing discard/noble sub-entries.
	const moveTurns = useMemo(() => {
		const moves = liveGame?.moves || [];
		const n = moves.length;
		const res = new Array(n).fill(0);
		const PRIMARY = new Set(["take_gems", "buy", "reserve"]);
		let t = -1;
		for (let i = n - 1; i >= 0; i--) {            // walk oldest-first
			if (PRIMARY.has(moves[i].type)) t++;
			res[i] = Math.max(0, t);
		}
		return res;
	}, [liveGame]);

	const [selectedGems, setSelectedGems] = useState([]);
	const [selectedCard, setSelectedCard] = useState(null);
	const [reserveArmed, setReserveArmed] = useState(false);  // gold-first reserve: click gold, then a card
	const [toast, setToast] = useState("");
	const [confirmAbandon, setConfirmAbandon] = useState(false);
	const [resultReady, setResultReady] = useState(false);  // gate the win/loss screen until 2s after game ends
	// Mobile-only: per-player expand toggle (compact one-line summaries) + log collapse.
	// No effect on desktop, where CSS always shows full panels + the move log.
	const [playerExpanded, setPlayerExpanded] = useState({});
	const [logOpen, setLogOpen] = useState(false);
	// Admin-only debug overlay: the per-card AI values (H2's take/engine/point/cost, H's value).
	// OFF by default; only admins get the toggle, so regular players never see it.
	const [showAiVals, setShowAiVals] = useState(() => {
		try { return localStorage.getItem("spender_show_ai_vals") === "1"; } catch { return false; }
	});

	// ── Auth form state ────────────────────────────────────────────────────
	const [authTab, setAuthTab] = useState("login");
	const [authName, setAuthName] = useState("");
	const [authPassword, setAuthPassword] = useState("");
	const [guestName, setGuestName] = useState("");
	const [authError, setAuthError] = useState("");
	const [authLoading, setAuthLoading] = useState(false);

	// ── Browser state ──────────────────────────────────────────────────────
	const [openGames, setOpenGames] = useState([]);
	const [activeGames, setActiveGames] = useState([]);   // ALL in-progress games (yours + others')
	const [historyGames, setHistoryGames] = useState([]); // your FINISHED games (vs AI or humans)
	const [browserLoading, setBrowserLoading] = useState(false);
	const [showCreateMenu, setShowCreateMenu] = useState(false);
	const [winPoints, setWinPoints] = useState(15);   // 15 = Classic, 21 = Long mode
	const [lobbyTab, setLobbyTab] = useState("open");  // mobile-only: which lobby section is shown (open|active|history)

	const playerName = authUser?.name || "";

	// ── fetchGames ─────────────────────────────────────────────────────────
	const fetchGames = useCallback(async (user) => {
		setBrowserLoading(true);
		try {
			const openP = fetch(`${HTTP_BASE}/games`).then(r => r.json()).catch(() => ({ games: [] }));
			// Active Games is PUBLIC: all in-progress games (yours + others', vs-AI or
			// not). The frontend pins yours to the top via myId. No auth needed.
			const activeP = fetch(`${HTTP_BASE}/games/active`).then(r => r.json()).catch(() => ({ games: [] }));
			// History (your finished games) is session-gated — only fetch for a logged-in user.
			const histP = user?.session_token
				? fetch(`${HTTP_BASE}/games/history`, { headers: { Authorization: `Bearer ${user.session_token}` } })
					.then(r => r.json()).catch(() => ({ games: [] }))
				: Promise.resolve({ games: [] });
			const [open, active, hist] = await Promise.all([openP, activeP, histP]);
			setOpenGames(open.games || []);
			setActiveGames(active.games || []);
			setHistoryGames(hist.games || []);
		} catch {
			setOpenGames([]); setActiveGames([]); setHistoryGames([]);
		}
		setBrowserLoading(false);
	}, []);

	// ── handleMessage ──────────────────────────────────────────────────────
	const handleMessage = useCallback((msg) => {
		const room = msg.room;
		if (room?.reconnect_tokens?.[myId]) {
			const rid = room.room_id || roomId;
			try {
				localStorage.setItem(`spender_token_${rid}_${myId}`, room.reconnect_tokens[myId]);
				if (rid) localStorage.setItem("spender_roomId", rid);
			} catch {}
		}

		// A finished game ("over") still belongs on the game screen so the
		// winner/review UI shows — only a not-yet-started game goes to "waiting".
		const inGame = (s) => s === "playing" || s === "over";
		if (msg.type === "created") {
			setRoomData(msg.room);
			if (inGame(msg.room?.status)) setScreen("game");
			else setScreen("waiting");
		} else if (msg.type === "joined") {
			setRoomData(msg.room);
			if (inGame(msg.room?.status)) setScreen("game");
			else setScreen("waiting");
		} else if (msg.type === "reconnected") {
			setRoomData(msg.room);
			if (inGame(msg.room.status)) setScreen("game");
			else setScreen("waiting");
		} else if (msg.type === "room_update") {
			setRoomData(msg.room);
			if (inGame(msg.room.status) && screen !== "game") setScreen("game");
		} else if (msg.type === "ping") {
			// Another player tapped your player box (or you tapped theirs) → chime.
			playPing();
			// If you're on another tab, also raise the "waiting for you" tab indicator.
			if (document.hidden) setPinged(true);
		} else if (msg.type === "error") {
			// A join into a cancelled/gone game (the backend rejects it now instead of
			// fabricating a hostless room): clear the stale pointer + refresh the list
			// so the dead game disappears.
			const gone = typeof msg.message === "string"
				&& (msg.message.includes("no longer available") || msg.message === "room not found");
			if (msg.message === "invalid token" || gone) {
				try { localStorage.removeItem("spender_roomId"); } catch {}
			}
			if (gone && authUser) fetchGames(authUser);
			setToast(msg.message);
		}
	}, [myId, screen, roomId, authUser, fetchGames]);

	// ── WebSocket ──────────────────────────────────────────────────────────
	const pendingActionRef = useRef(null);

	const { connect, send, disconnect, getReadyState } = useWebSocket(handleMessage, {
		onOpen: ({ send: wsSend }) => {
			if (pendingActionRef.current) {
				wsSend(pendingActionRef.current);
				pendingActionRef.current = null;
				return;
			}
			// auto-reconnect on page load
			try {
				const savedRoomId = localStorage.getItem("spender_roomId");
				const tok = savedRoomId ? localStorage.getItem(`spender_token_${savedRoomId}_${myId}`) : null;
				if (tok) wsSend({ action: "reconnect", token: tok });
			} catch {}
		},
		onClose: () => {},
	});

	// ── Mount: auto-reconnect to saved room ────────────────────────────────
	useEffect(() => {
		try {
			const savedRoomId = localStorage.getItem("spender_roomId");
			const savedToken = savedRoomId ? localStorage.getItem(`spender_token_${savedRoomId}_${myId}`) : null;
			if (savedRoomId && savedToken) {
				setRoomId(savedRoomId);
				connect(`${WS_BASE}/${savedRoomId}/${myId}`);
			}
		} catch {}
		return () => disconnect();
	}, []); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Reconnect when tab becomes visible (iOS kills WS in background) ────
	const roomIdRef = useRef(roomId);
	roomIdRef.current = roomId;
	const screenRef = useRef(screen);
	screenRef.current = screen;
	const reviewingRef = useRef(reviewing);
	reviewingRef.current = reviewing;
	useEffect(() => {
		const handleVisibility = () => {
			// Only auto-reconnect when actively on the game screen — otherwise tabbing
			// back would dump a lobby/waiting user into a stale waiting room. Never while
			// reviewing a finished game (no live socket — a reconnect would be spurious).
			if (document.visibilityState === "visible"
				&& screenRef.current === "game"
				&& !reviewingRef.current
				&& roomIdRef.current
				&& getReadyState() !== WebSocket.OPEN) {
				connect(`${WS_BASE}/${roomIdRef.current}/${myId}`);
			}
		};
		document.addEventListener("visibilitychange", handleVisibility);
		return () => document.removeEventListener("visibilitychange", handleVisibility);
	}, [myId, connect, getReadyState]); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Client-side AI: ROOT-PARALLEL variant-S search across the player's CPU cores ─────────
	// For a vs-S game we offload the AI's move to a POOL of WASM workers. Each runs an independent
	// determinized search for the budget; we SUM their root visit counts and pick the argmax (standard
	// root parallelization — no shared memory, no COOP/COEP). The server stays authoritative: it
	// validates the submitted move and falls back to its own search if the client doesn't answer.
	// Graceful — if no worker loads we never announce capability and the server computes as before.
	// Pool capped (each worker builds a large search tree at the budget → bounded memory across devices).
	const CLIENT_AI_BUDGET_MS = 4500;   // slow-device time ceiling
	const CLIENT_AI_MAX_SIMS = 100000;  // per-worker sims cap (~1 node/sim → bounds tree memory; fast
	                                    // devices hit this in ~2s, snappy; 0 = no cap). ~400k aggregate
	                                    // across the pool — far past saturation, no strength cost.
	const wasmPoolRef = useRef(null);          // [{ ready, request, terminate }] — RPC-wrapped workers
	const [wasmReady, setWasmReady] = useState(false);
	const clientAiArmedRef = useRef(null);     // room_id we've announced capability for
	const aiDispatchPlyRef = useRef(-1);       // ply we've already dispatched a search for

	useEffect(() => {
		if (roomData?.ai_variant !== "S" || wasmPoolRef.current || typeof Worker === "undefined") return;
		const url = `${import.meta.env.BASE_URL}wasm/s-worker.js`;
		const cores = Math.max(1, Math.min(navigator.hardwareConcurrency || 4, 4));
		const makeWorker = () => {
			let w;
			try { w = new Worker(url, { type: "module" }); } catch { return null; }
			const pending = new Map();
			let resolveReady, nextId = 1;
			const ready = new Promise((res) => (resolveReady = res));
			w.onmessage = (e) => {
				const d = e.data || {};
				if (d.ready !== undefined) { resolveReady(!!d.ready); return; }
				if (d.id != null && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
			};
			w.onerror = () => resolveReady(false);
			return {
				ready,
				request(payload) {
					const id = nextId++;
					return new Promise((res) => { pending.set(id, res); w.postMessage({ ...payload, id }); });
				},
				terminate() { try { w.terminate(); } catch {} },
			};
		};
		const pool = Array.from({ length: cores }, makeWorker).filter(Boolean);
		wasmPoolRef.current = pool;
		Promise.all(pool.map((wk) => wk.ready)).then((flags) => {
			const live = pool.filter((_, i) => flags[i]);
			if (live.length > 0) {
				wasmPoolRef.current = live;
				setWasmReady(true);
				console.info(`[client-AI] ${live.length}/${cores} WASM search workers ready`);
			} else {
				console.warn("[client-AI] no WASM workers loaded → server AI");
			}
		});
		return () => { pool.forEach((wk) => wk.terminate()); wasmPoolRef.current = null; setWasmReady(false); };
	}, [roomData?.ai_variant]);

	// Announce capability once per room → the server then ships `ai_search` on the AI's turn.
	useEffect(() => {
		if (wasmReady && roomData?.ai_variant === "S" && roomData?.room_id
			&& clientAiArmedRef.current !== roomData.room_id) {
			clientAiArmedRef.current = roomData.room_id;
			send({ action: "client_ai_ready" });
		}
	}, [wasmReady, roomData?.room_id, roomData?.ai_variant, send]);

	// On the AI's turn the server ships `ai_search` → fan a seeded search to every worker, SUM their
	// root visit vectors, argmax, convert the winner to a move, and submit it.
	useEffect(() => {
		const as = roomData?.ai_search;
		const pool = wasmPoolRef.current;
		if (!as || !wasmReady || !pool || pool.length === 0) return;
		if (aiDispatchPlyRef.current === as.ply) return; // one dispatch per ply
		aiDispatchPlyRef.current = as.ply;
		const stateStr = JSON.stringify(as.state);
		const t0 = performance.now();
		(async () => {
			try {
				const visitsArrays = await Promise.all(pool.map((wk, i) =>
					wk.request({
						kind: "search", state: stateStr, seat: as.seat,
						budget: CLIENT_AI_BUDGET_MS, maxSims: CLIENT_AI_MAX_SIMS,
						seed: ((as.ply * 2654435761) ^ (i * 40503 + 1)) >>> 0,
					}).then((d) => d.visits).catch(() => null)));
				const total = new Int32Array(70);
				let sims = 0, contrib = 0;
				for (const v of visitsArrays) {
					if (!v || v.length < 70) continue;
					contrib++;
					for (let a = 0; a < 70; a++) { total[a] += v[a]; sims += v[a]; }
				}
				if (contrib === 0) return; // every worker failed → the server fallback covers it
				let best = 0, bv = -1;
				for (let a = 0; a < 70; a++) if (total[a] > bv) { bv = total[a]; best = a; }
				// Endgame solver (#1): refine the aggregate PUCT pick on the TRUE state (exact negamax;
				// overrides only on a sound forced win/loss). Returns the dict-move directly (refine+convert
				// in one), and is a no-op outside endgame positions.
				const conv = await pool[0].request({
					kind: "refine", state: stateStr, seat: as.seat, action: best,
					seed: ((as.ply * 2246822519) ^ 0x9e3779b1) >>> 0,
				});
				const mv = JSON.parse(conv.move);
				if (mv && !mv.error) {
					const ms = Math.round(performance.now() - t0);
					console.info(`[client-AI] ${contrib} workers, ${sims} sims in ${ms}ms ->`, mv);
					send({ action: "ai_move", move: mv });
				}
			} catch {}
		})();
	}, [roomData, wasmReady, send]);

	// ── "Someone's waiting for you" tab indicator (permission-free) ─────────
	// When the tab is HIDDEN and it's your turn OR a ping arrived, flash the page
	// title and swap in the alert favicon so an unfocused tab shows someone's waiting.
	// Cleared the moment you return (visibilitychange → visible). No Notifications API.
	useEffect(() => {
		const BASE_TITLE = "Forrest Games";
		const icon = document.querySelector('link[rel~="icon"][type="image/svg+xml"]');
		const baseIcon = icon ? icon.href : null;
		const alertIcon = baseIcon ? baseIcon.replace("favicon.svg", "favicon-alert.svg") : null;
		const alertText = () => (myTurn ? "🔔 Your turn!" : "👋 Someone's waiting!");
		let timer = null, flip = false;
		const stop = () => {
			if (timer) { clearInterval(timer); timer = null; }
			document.title = BASE_TITLE;
			if (icon && baseIcon) icon.href = baseIcon;
		};
		const flash = () => {
			if (icon && alertIcon) icon.href = alertIcon;
			document.title = alertText();
			if (!timer) timer = setInterval(() => {
				flip = !flip;
				document.title = flip ? BASE_TITLE : alertText();
			}, 1100);
		};
		const evaluate = () => {
			if (!document.hidden) { stop(); if (pinged) setPinged(false); return; }
			if (myTurn || pinged) flash(); else stop();
		};
		evaluate();
		document.addEventListener("visibilitychange", evaluate);
		return () => { document.removeEventListener("visibilitychange", evaluate); stop(); };
	}, [myTurn, pinged]);

	useEffect(() => {
		if (screen === "browser" && authUser) fetchGames(authUser);
	}, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		if (toast) { const t = setTimeout(() => setToast(""), 2500); return () => clearTimeout(t); }
	}, [toast]);

	// Hold on the final board for 2s after the game ends before revealing the
	// win/loss screen, so the player sees the move that ended it. Resets whenever
	// the game isn't over (a new game), so the next ending delays again.
	useEffect(() => {
		if (game?.phase === "over") {
			const t = setTimeout(() => setResultReady(true), 2000);
			return () => clearTimeout(t);
		}
		setResultReady(false);
	}, [game?.phase]);

	// ── Mobile zoom fix ────────────────────────────────────────────────────
	// On the game screen, iOS Safari otherwise picks a too-small page scale on
	// first paint (it fits-to-content while the layout momentarily overflows the
	// viewport) and renders the board zoomed out until a reflow — e.g. the first
	// Take/✕ button appearing — snaps it back to scale 1. Pinning the viewport to
	// scale 1 (user-scalable=no) while the game is mounted forces the correct
	// zoom the whole time; the cleanup restores normal pinch-zoom on other screens.
	useEffect(() => {
		const vp = document.querySelector('meta[name="viewport"]');
		if (!vp) return;
		const base = "width=device-width, initial-scale=1.0";
		if (screen === "game") vp.setAttribute("content", base + ", maximum-scale=1.0, user-scalable=no");
		return () => vp.setAttribute("content", base);
	}, [screen]);

	// ── Loading: ping backend until ready, then proceed to auth/browser ────
	useEffect(() => {
		if (screen !== "loading") return;
		let cancelled = false;
		// Resolve the landing screen. For a logged-in (non-guest) user we also
		// validate the stored session token here: it can be silently dead (7-day
		// expiry, or superseded by a login on another device — there's one token
		// per user), which downgrades every authenticated request to anonymous
		// (e.g. the Books "Edit ranking" button disappears) while the UI still
		// shows you logged in. A definite ok:false clears the stale login so you
		// land on auth and can re-login. A network/parse error keeps you logged in
		// (a blip must never log anyone out). Called only after the backend is
		// confirmed reachable, so the error branch means a real transport failure.
		const resolveDest = async () => {
			let stored = null;
			try { const s = localStorage.getItem("spender_user"); if (s) stored = JSON.parse(s); } catch {}
			if (!stored) return "auth";
			if (stored.guest || !stored.session_token) return "home";
			try {
				const ctrl = new AbortController();
				const t = setTimeout(() => ctrl.abort(), 5000);
				const res = await fetch(`${HTTP_BASE}/auth/session`,
					{ signal: ctrl.signal, headers: { Authorization: `Bearer ${stored.session_token}` } });
				clearTimeout(t);
				const data = await res.json();
				if (data?.ok && data.user) {
					// Keep the token; refresh the cached identity (name / is_admin).
					const fresh = { ...stored, name: data.user.name, is_admin: !!data.user.is_admin };
					try { localStorage.setItem("spender_user", JSON.stringify(fresh)); } catch {}
					if (!cancelled) setAuthUser(fresh);
					return "home";
				}
				if (data && data.ok === false) {  // definitively invalid — clear it
					try {
						localStorage.removeItem("spender_user");
						localStorage.removeItem("spender_roomId");
					} catch {}
					const newId = uid();
					try { localStorage.setItem("spender_myId", newId); } catch {}
					if (!cancelled) { setAuthUser(null); setMyId(newId); }
					return "auth";
				}
			} catch { /* transport/parse error — don't punish a blip, stay logged in */ }
			return "home";
		};
		let interval = null;
		const startPolling = () => {
			const startTime = Date.now();
			interval = setInterval(() => {
				if (cancelled) return;
				setLoadingProgress(Math.min((Date.now() - startTime) / 25000, 0.9));
			}, 100);
			(async () => {
				while (!cancelled) {
					try {
						const ctrl = new AbortController();
						const t = setTimeout(() => ctrl.abort(), 5000);
						const res = await fetch(`${HTTP_BASE}/games`, { signal: ctrl.signal });
						clearTimeout(t);
						if (res.ok && !cancelled) {
							clearInterval(interval);
							setLoadingProgress(1);
							const dest = await resolveDest();
							await waitFonts();
							setTimeout(() => { if (!cancelled) setScreen(dest); }, 350);
							return;
						}
					} catch {}
					if (!cancelled) await new Promise(r => setTimeout(r, 2000));
				}
			})();
		};
		// Wait for the web fonts (Cinzel/Crimson) to actually finish loading before
		// revealing a real screen, so the first paint already uses them — otherwise the
		// page paints in the fallback serif then "snaps" wider when the fonts swap in.
		// document.fonts.load() is what TRIGGERS + awaits the load (document.fonts.ready
		// alone resolves early, since the blank loading screen has no text to pull the
		// fonts). Capped at 1.5s so a slow/failed font load never blocks the app; on
		// reload the fonts are cached, so this resolves ~instantly.
		const waitFonts = async () => {
			try {
				if (!document.fonts?.load) return;
				await Promise.race([
					Promise.all([
						document.fonts.load('700 1rem Cinzel'),
						document.fonts.load('600 1rem Cinzel'),
						document.fonts.load('400 1rem Cinzel'),
						document.fonts.load('400 1rem "Crimson Pro"'),
					]),
					new Promise(r => setTimeout(r, 1500)),
				]);
			} catch {}
		};
		// Fast path: if backend responds within 250ms, skip the loading screen entirely
		(async () => {
			try {
				const ctrl = new AbortController();
				const t = setTimeout(() => ctrl.abort(), 250);
				const res = await fetch(`${HTTP_BASE}/games`, { signal: ctrl.signal });
				clearTimeout(t);
				if (res.ok && !cancelled) { const dest = await resolveDest(); await waitFonts(); if (!cancelled) setScreen(dest); return; }
			} catch {}
			if (!cancelled) { setShowLoading(true); startPolling(); }
		})();
		return () => { cancelled = true; if (interval) clearInterval(interval); };
	}, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Gem flash when bank count drops ───────────────────────────────────────
	const prevBankRef = useRef(null);
	const [flashGems, setFlashGems] = useState(new Set());
	useEffect(() => {
		if (reviewing || !game?.bank) return;   // no flashes while rewinding a finished game
		const prev = prevBankRef.current;
		if (prev) {
			const flashing = new Set(
				[...GEM_COLORS, "gold"].filter(c => (prev[c] ?? 0) > (game.bank[c] ?? 0))
			);
			if (flashing.size > 0) {
				setFlashGems(flashing);
				const t = setTimeout(() => setFlashGems(new Set()), 420);
				prevBankRef.current = { ...game.bank };
				return () => clearTimeout(t);
			}
		}
		prevBankRef.current = { ...game.bank };
	}, [game]); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Flying gems: on each single move, animate the gems that moved between the
	//    bank and the acting player's box. Driven by per-player token deltas, so it
	//    covers take (bank->you, shrink), buy/discard (you->bank, grow), and
	//    reserve-gold (bank->you, shrink) for every player including the AI. ──────
	const [flyers, setFlyers] = useState([]);
	const prevPlayersRef = useRef(null);
	const prevBoardRef = useRef(null);
	const prevMovesLenRef = useRef(0);
	const flyIdRef = useRef(0);
	useEffect(() => {
		if (reviewing) return;   // no flying gems/cards while rewinding a finished game
		const players = game?.players;
		if (!players) return;
		const prev = prevPlayersRef.current;
		const prevBoard = prevBoardRef.current;
		const movesLen = game?.moves?.length || 0;
		const prevMovesLen = prevMovesLenRef.current;
		// Snapshot players (tokens + purchased ids) + board slot ids for next diff.
		const snap = {};
		for (const pid of Object.keys(players)) {
			snap[pid] = { tokens: { ...(players[pid].tokens || {}) }, purchased: (players[pid].purchased || []).map(c => c.id) };
		}
		const boardSnap = {};
		for (const lk of ["L3", "L2", "L1"]) boardSnap[lk] = (game.board?.[lk] || []).map(c => c ? c.id : null);
		prevPlayersRef.current = snap;
		prevBoardRef.current = boardSnap;
		prevMovesLenRef.current = movesLen;
		// Only animate exactly one new move (avoids a burst on load/reconnect).
		if (!prev || movesLen !== prevMovesLen + 1) return;

		const ALL = [...GEM_COLORS, "gold"];
		const specs = [];   // gem moves
		for (const pid of Object.keys(players)) {
			const before = prev[pid];
			if (!before) continue;
			const now = players[pid].tokens || {};
			for (const c of ALL) {
				const delta = (now[c] || 0) - (before.tokens[c] || 0);
				if (delta > 0) specs.push({ pid, color: c, count: delta, grow: false });   // bank -> player
				else if (delta < 0) specs.push({ pid, color: c, count: -delta, grow: true }); // player -> bank
			}
		}

		// A bought card: a player's purchased grew. Find the new card + the board
		// slot it came from (so it can fly from there to the buyer's box).
		let cardFly = null;
		for (const pid of Object.keys(players)) {
			const before = prev[pid];
			if (!before) continue;
			const nowPurchased = players[pid].purchased || [];
			if (nowPurchased.length > before.purchased.length) {
				const beforeIds = new Set(before.purchased);
				const bought = nowPurchased.find(c => !beforeIds.has(c.id));
				if (bought) {
					let pos = null;
					if (prevBoard) for (const lk of ["L3", "L2", "L1"]) {
						const idx = (prevBoard[lk] || []).indexOf(bought.id);
						if (idx >= 0) { pos = `${lk}-${idx}`; break; }
					}
					cardFly = { pid, card: bought, pos };
				}
			}
		}

		if (!specs.length && !cardFly) return;

		const raf = requestAnimationFrame(() => {
			const made = [];
			let total = 0;
			// Center of the first VISIBLE element matching `sel` inside the box (its
			// per-color gem/card indicator); falls back to the box center (e.g. on
			// mobile where the detail pills are hidden).
			const targetIn = (boxEl, sel) => {
				const el = boxEl.querySelector(sel);
				if (el) { const r = el.getBoundingClientRect(); if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
				const r = boxEl.getBoundingClientRect();
				return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
			};
			for (const s of specs) {
				const bankEl = document.querySelector(`.gem-stack[data-color="${s.color}"] .gem-token`);
				const boxEl = document.querySelector(`.player-panel[data-pid="${s.pid}"]`);
				if (!bankEl || !boxEl) continue;
				const br = bankEl.getBoundingClientRect();
				const bank = { x: br.left + br.width / 2, y: br.top + br.height / 2 };
				const box = targetIn(boxEl, `.token-pill[data-token="${s.color}"]`);  // this color's gem indicator
				const size = Math.max(18, Math.round(br.width || 40));
				const from = s.grow ? box : bank;
				const to = s.grow ? bank : box;
				const n = Math.min(s.count, 5);
				for (let i = 0; i < n && total < 8; i++, total++) {
					made.push({
						id: ++flyIdRef.current, kind: "gem", color: s.color, size,
						x: from.x, y: from.y, dx: to.x - from.x, dy: to.y - from.y,
						s0: s.grow ? 0.35 : 1, s1: s.grow ? 1 : 0.35, delay: i * 55,
					});
				}
			}
			// Bought card flies from its board slot to the buyer's box, shrinking.
			if (cardFly && cardFly.pos) {
				const slotEl = document.querySelector(`.level-row [data-pos="${cardFly.pos}"]`);
				const boxEl = document.querySelector(`.player-panel[data-pid="${cardFly.pid}"]`);
				if (slotEl && boxEl) {
					const sr = slotEl.getBoundingClientRect();
					const cx = sr.left + sr.width / 2, cy = sr.top + sr.height / 2;
					// fly to this card's bonus-color indicator (its card pill); fallback box center
					const dest = targetIn(boxEl, `.bonus-pill[data-bonus="${cardFly.card.bonus}"]`);
					made.push({
						id: ++flyIdRef.current, kind: "card",
						color: cardFly.card.bonus, points: cardFly.card.points,
						x: sr.left, y: sr.top, w: Math.round(sr.width), h: Math.round(sr.height),
						dx: dest.x - cx, dy: dest.y - cy, s0: 1, s1: 0.22, delay: 0,
					});
				}
			}
			if (!made.length) return;
			setFlyers(f => [...f, ...made]);
			const ids = new Set(made.map(m => m.id));
			const maxDelay = made.reduce((m, x) => Math.max(m, x.delay), 0);
			setTimeout(() => setFlyers(f => f.filter(x => !ids.has(x.id))), 560 + maxDelay);
		});
		return () => cancelAnimationFrame(raf);
	}, [game]); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Move log helpers ──────────────────────────────────────────────────────
	function formatLogMove(mv) {
		const isMe = mv.pid === myId;
		const name = isMe ? "You" : displayName(roomData?.players?.[mv.pid] || mv.pid.slice(0, 6));
		if (mv.type === "take_gems") {
			if (!mv.colors?.length) return { name, action: "passed" };
			const freq = {};
			for (const c of mv.colors) freq[c] = (freq[c] || 0) + 1;
			const parts = Object.entries(freq).map(([c, n]) => (
				<span key={c} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
					{n > 1 ? `${n}× ` : ""}
					<span style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[c], border: "1px solid rgba(255,255,255,.12)", display: "inline-block", flexShrink: 0 }} />
				</span>
			));
			return { name, action: <span>took {parts.reduce((a, b) => [a, " ", b])}</span> };
		}
		// Resolve the card: new logs carry card_id (look up the catalog); older saved
		// games carry the full mv.card inline. Either path yields a full card dict.
		const mvCard = mv.card || (mv.card_id ? cardsById[mv.card_id] : null);
		if (mv.type === "buy") {
			const col = mvCard?.bonus || mvCard?.color;
			const dot = col
				? <span style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[col], border: "1px solid rgba(255,255,255,.12)", display: "inline-block", marginLeft: 2, marginRight: 2, verticalAlign: "middle" }} />
				: null;
			return { name, action: <span>bought{dot}card{mvCard?.points ? ` +${mvCard.points}pts` : ""}</span>, card: mvCard?.cost ? mvCard : null };
		}
		if (mv.type === "reserve") {
			const col = mvCard?.bonus || mvCard?.color;
			const dot = col
				? <span style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[col], border: "1px solid rgba(255,255,255,.12)", display: "inline-block", marginLeft: 2, marginRight: 2, verticalAlign: "middle" }} />
				: null;
			return { name, action: <span>reserved{dot}card</span>, card: mvCard?.cost ? mvCard : null };
		}
		if (mv.type === "discard") {
			// Each over-10 discard is logged with its gem color; show exactly which gem.
			const dot = mv.color
				? <span style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[mv.color], border: "1px solid rgba(255,255,255,.12)", display: "inline-block", marginLeft: 2, marginRight: 2, verticalAlign: "middle" }} />
				: null;
			return { name, action: <span>discarded{dot}gem</span> };
		}
		if (mv.type === "noble") return { name, action: `claimed noble +${mv.pts}pts` };
		return { name, action: mv.type };
	}

	// ── Auth actions ───────────────────────────────────────────────────────
	const handleAuth = async () => {
		if (!authName.trim() || !authPassword.trim()) {
			setAuthError("Name and password required"); return;
		}
		setAuthError(""); setAuthLoading(true);
		try {
			const endpoint = authTab === "login" ? "/auth/login" : "/auth/register";
			const res = await fetch(`${HTTP_BASE}${endpoint}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ name: authName.trim(), password: authPassword.trim() }),
			});
			const data = await res.json();
			if (data.ok) {
				const user = { id: data.user.id, name: data.user.name, is_admin: !!data.user.is_admin, session_token: data.session_token || null };
				try { localStorage.setItem("spender_user", JSON.stringify(user)); localStorage.setItem("spender_myId", user.id); } catch {}
				setAuthUser(user);
				setMyId(user.id);
				setScreen("home");
			} else {
				setAuthError(data.message || "Something went wrong");
			}
		} catch {
			setAuthError("Could not reach server");
		}
		setAuthLoading(false);
	};

	const handleGuestPlay = () => {
		const name = guestName.trim() || `Guest${Math.floor(Math.random() * 9000 + 1000)}`;
		const user = { id: myId, name, guest: true };
		setAuthUser(user);
		setScreen("home");
	};

	const handleLogout = () => {
		try {
			localStorage.removeItem("spender_user");
			localStorage.removeItem("spender_roomId");
		} catch {}
		const newId = uid();
		setMyId(newId);
		try { localStorage.setItem("spender_myId", newId); } catch {}
		setAuthUser(null);
		setScreen("auth");
		setRoomData(null);
		setRoomId("");
		disconnect();
	};

	// ── Room / game actions ────────────────────────────────────────────────
	const handleCreate = (vsAI = false, aiVariant = "A", wp = 15) => {
		const newRoomId = roomCode();
		setRoomId(newRoomId);
		try { localStorage.setItem("spender_roomId", newRoomId); } catch {}
		pendingActionRef.current = vsAI
			? { action: "create", name: playerName, vs_ai: true, ai_variant: aiVariant, win_points: wp }
			: { action: "create", name: playerName, win_points: wp };
		connect(`${WS_BASE}/${newRoomId}/${myId}`);
	};

	const handleJoinGame = (gameId) => {
		setRoomId(gameId);
		try { localStorage.setItem("spender_roomId", gameId); } catch {}
		pendingActionRef.current = { action: "join", name: playerName };
		connect(`${WS_BASE}/${gameId}/${myId}`);
	};

	const handleCancel = async (gameId) => {
		let ok = false;
		try {
			const params = new URLSearchParams({ player_id: myId });
			const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
			const res = await fetch(`${HTTP_BASE}/games/${gameId}/cancel?${params}`, { method: "POST", headers });
			const data = await res.json().catch(() => ({}));
			ok = !!data.ok;
			if (!ok) setToast(data.message || "Couldn't cancel that game");
		} catch {
			setToast("Couldn't reach the server");
		}
		if (!ok) return;   // only clear local resume pointers once the game is really gone
		try {
			if (localStorage.getItem("spender_roomId") === gameId) localStorage.removeItem("spender_roomId");
			localStorage.removeItem(`spender_token_${gameId}_${myId}`);
		} catch {}
		fetchGames(authUser);
	};

	const handleContinue = (gameId) => {
		const savedToken = localStorage.getItem(`spender_token_${gameId}_${myId}`);
		setRoomId(gameId);
		try { localStorage.setItem("spender_roomId", gameId); } catch {}
		pendingActionRef.current = savedToken
			? { action: "reconnect", token: savedToken }
			: { action: "join", name: playerName };
		connect(`${WS_BASE}/${gameId}/${myId}`);
	};

	// ── Read-only review of a finished game (rewind any turn; no moves possible) ──
	// Fetches the final board + a per-turn snapshot list. Entered from a History card
	// (no WebSocket) or from the in-game post-game screen (live socket left untouched).
	const enterReview = async (gameId) => {
		const haveLive = !!(roomData?.game) && roomId === gameId;   // already on this finished game
		try {
			const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
			const res = await fetch(`${HTTP_BASE}/games/${gameId}/review`, { headers });
			const data = await res.json();
			if (!data.ok) {
				if (haveLive) { setReplaySnapshots(null); setReplayTurn(null); setReviewing(true); return; }
				setToast(data.message || "Couldn't load that game"); return;
			}
			const snaps = Array.isArray(data.snapshots) ? data.snapshots : null;
			if (!haveLive) {
				// History entry: no socket — synthesize the room state from the fetched final board.
				disconnect();   // ensure no stray socket can overwrite the synthetic review state
				setRoomId(gameId);
				setRoomData({
					room_id: data.room_id,
					players: data.players || {},
					status: data.status || "over",
					game: data.final,
					ai_variant: data.ai_variant,
				});
				setResultReady(true);
				setScreen("game");
			}
			setReplaySnapshots(snaps);
			setReplayTurn(null);
			setReviewing(true);
		} catch {
			if (haveLive) { setReplaySnapshots(null); setReplayTurn(null); setReviewing(true); return; }
			setToast("Couldn't reach the server");
		}
	};

	// Jump the review board to a turn (0-based; the last snapshot is the final position).
	const goToTurn = (idx) => {
		if (!replaySnapshots) return;
		setReplayTurn(Math.max(0, Math.min(replaySnapshots.length - 1, idx)));
	};
	const goToFinal = () => setReplayTurn(null);

	const goToMenu = () => {
		disconnect();
		setScreen("browser");
		setRoomData(null);
		setSelectedGems([]);
		setSelectedCard(null);
		setConfirmAbandon(false);
		setReviewing(false);
		setReplaySnapshots(null);
		setReplayTurn(null);
		fetchGames(authUser);
	};

	const handleAbandon = () => {
		send({ action: "abandon" });
		setConfirmAbandon(false);
	};

	const handleStart = () => send({ action: "start" });

	const sendMove = (move) => send({ action: "move", move });

	const handleTakeGems = () => {
		if (!myTurn || selectedGems.length === 0) return;
		sendMove({ type: "take_gems", colors: selectedGems });
		setSelectedGems([]);
	};

	const handleReserve = (card, deckLevel) => {
		if (!myTurn) return;
		if (deckLevel) sendMove({ type: "reserve", deck_level: deckLevel });
		else sendMove({ type: "reserve", card_id: card.id });
		setSelectedCard(null);
		setReserveArmed(false);
	};

	// Reserve the currently-selected card (board or deck) — triggered by clicking
	// the gold coin (you take a gold token when you reserve).
	const handleReserveSelected = () => {
		if (!myTurn || !selectedCard || selectedCard.source === "reserved") return;
		if ((me?.reserved?.length || 0) >= 3) return;
		if (selectedCard.source === "deck") handleReserve(null, selectedCard.deckLevel);
		else handleReserve(selectedCard.card);
	};

	const handleBuy = (card) => {
		if (!myTurn) return;
		sendMove({ type: "buy", card_id: card.id });
		setSelectedCard(null);
		setReserveArmed(false);
	};

	const handleDiscard = (color) => sendMove({ type: "discard", color });
	const handleUndoDiscard = () => sendMove({ type: "undo_discard" });
	const handleNobleChoice = (nobleId) => sendMove({ type: "pick_noble", noble_id: nobleId });

	const handleGemClick = (color) => {
		if (!myTurn) return;
		setSelectedCard(null);
		setReserveArmed(false);
		const bankCount = game?.bank[color] || 0;
		if (bankCount <= 0) return;
		setSelectedGems(prev => {
			const freq = {};
			for (const c of prev) freq[c] = (freq[c] || 0) + 1;
			const has = freq[color] || 0;

			if (has === 2) return [];                          // clicking the doubled gem clears it
			if (has === 1) {
				// Double-take (two of one color) is only allowed when the pile is full
				// AND this is the only gem selected. With anything else selected, a
				// click on an already-selected gem just deselects it.
				if (prev.length === 1 && bankCount >= 4) return [color, color];
				return prev.filter(c => c !== color);          // deselect it
			}
			// has === 0: adding a new color
			if (prev.length >= 3) return prev;
			if (Object.values(freq).some(n => n === 2)) return prev; // can't mix with a double-take
			return [...prev, color];
		});
	};

	// ── Render helpers ─────────────────────────────────────────────────────
	function renderCard(card, opts = {}) {
		if (!card) return <div className="card-slot" />;
		// readonly: opponent's reserved cards — visible but not selectable/affordable.
		const affordable = !opts.readonly && me && canAfford(card.cost, me.tokens, myBonuses);
		const needsGold = affordable && goldToAfford(card.cost, me.tokens, myBonuses) > 0;
		const isSelected = !opts.readonly && selectedCard?.card?.id === card.id;
		return (
			<CardView key={card.id} card={card}
				selected={isSelected}
				affordable={affordable && myTurn}
				needsGold={needsGold && myTurn}
				dataPos={opts.dataPos}
				aiValue={(authUser?.is_admin && showAiVals) ? aiCardValues?.[card.id] : null}
				valsMine={aiValuesPid === myId}
				disabled={opts.disabled}
				onClick={() => {
					if (opts.readonly || !myTurn) return;
					const source = opts.source || "board";
					// gold-first reserve: gold armed, then click a (non-reserved) card
					if (reserveArmed && source !== "reserved" && (me?.reserved?.length || 0) < 3) {
						handleReserve(card);
						return;
					}
					setSelectedGems([]);
					setReserveArmed(false);
					setSelectedCard(isSelected ? null : { card, source });
				}}
			/>
		);
	}

	function renderPlayerPanel(pid) {
		const p = game?.players?.[pid];
		if (!p) return null;
		const name = displayName(roomData?.players?.[pid] || pid.slice(0, 6));
		const bonuses = bonusesFrom(p.purchased);
		const score = totalPoints(p.purchased, p.nobles);
		const isMe = pid === myId;
		const isActive = game?.turn === pid;
		// Mobile compact view: your own panel expands by default (you need your
		// tokens/reserved to act); opponents collapse to the one-line summary.
		const expanded = playerExpanded[pid] ?? isMe;
		const toggleExpand = () => setPlayerExpanded(m => ({ ...m, [pid]: !(m[pid] ?? isMe) }));
		const noblePts = p.nobles.reduce((s, n) => s + n.points, 0);
		// Tapping another player's box pings them (and you) — a quick "poke" chime.
		const canPing = !isMe && !reviewing;
		const pingPlayer = () => { playPing(); send({ action: "ping", target: pid }); };
		return (
			<div key={pid} data-pid={pid}
				className={`player-panel${isMe ? " me" : ""}${isActive ? " active-turn" : ""}${expanded ? " expanded" : ""}${canPing ? " pingable" : ""}`}
				onClick={canPing ? pingPlayer : undefined}>
				<div className="player-header" onClick={p.reserved?.length > 0 ? toggleExpand : undefined}>
					<div className="player-name-row">
						{isActive && <span className="active-dot" />}
						<span className="player-name">{name}{isMe ? " (you)" : ""}</span>
					</div>
					<span className="player-score">{score} pts</span>
				</div>
				{/* Compact at-a-glance row — mobile only (CSS). Shows cards bought AND
				    gems held so both are visible WITHOUT expanding; the caret appears
				    only when there are reserved cards (the one thing expand reveals). */}
				<div className="player-summary" onClick={p.reserved?.length > 0 ? toggleExpand : undefined}>
					<span className="sum-label">cards</span>
					{GEM_COLORS.map(c => (bonuses[c] || 0) > 0 && (
						<span key={"b" + c} className="sum-chip">
							<span className="sum-dot" style={{ background: GEM_HEX[c], borderColor: c === "black" ? "rgba(255,255,255,.45)" : "rgba(255,255,255,.25)" }} />
							{bonuses[c]}
						</span>
					))}
					{GEM_COLORS.every(c => !(bonuses[c] > 0)) && <span className="sum-none">—</span>}
					{noblePts > 0 && <span className="sum-chip sum-noble">★{noblePts}</span>}
					<span className="sum-div" />
					<span className="sum-label">gems</span>
					{[...GEM_COLORS, "gold"].map(c => (p.tokens[c] || 0) > 0 && (
						<span key={"t" + c} className="sum-chip">
							<span className="sum-dot" style={{ background: GEM_HEX[c], borderColor: c === "black" ? "rgba(255,255,255,.45)" : "rgba(255,255,255,.25)" }} />
							{p.tokens[c]}
						</span>
					))}
					{gemTotal(p.tokens) === 0 && <span className="sum-none">—</span>}
					{p.reserved?.length > 0 && <span className="sum-caret">{expanded ? "▾" : "▸"} {p.reserved.length} reserved</span>}
				</div>
				<div className="player-detail">
				<div className="player-tokens">
					{[...GEM_COLORS, "gold"].map(c => (p.tokens[c] || 0) > 0 && (
						<span key={c} data-token={c} className="token-pill" style={{ background: GEM_HEX[c] + "55", border: `1px solid ${c === "black" ? "rgba(255,255,255,.4)" : GEM_HEX[c]}` }}>
							{/* light rim so the near-black onyx gem stays visible on the warm "your turn" (surface3) panel */}
							<span style={{ width: 10, height: 10, borderRadius: "50%", background: GEM_HEX[c], border: c === "black" ? "1px solid rgba(255,255,255,.4)" : "1px solid rgba(255,255,255,.25)", display: "inline-block" }} />
							{p.tokens[c]}
						</span>
					))}
				</div>
				{/* always render (even "0 gems") so the bonus pills below keep a fixed position */}
				<div className="gem-total">{gemTotal(p.tokens)} {gemTotal(p.tokens) === 1 ? "gem" : "gems"}</div>
				<div className="player-bonuses">
					{GEM_COLORS.map(c => (bonuses[c] || 0) > 0 && (
						<span key={c} data-bonus={c} className="bonus-pill" style={{ background: GEM_HEX[c] + "55", borderColor: c === "black" ? "rgba(255,255,255,.4)" : GEM_HEX[c], color: c === "black" ? "#a8a8a8" : GEM_HEX[c] }}>+{bonuses[c]} {c[0].toUpperCase()}</span>
					))}
					{p.nobles.map(n => (
						<span key={n.id} className="bonus-pill" style={{ borderColor: "var(--gold)", color: "var(--gold)" }}>★{n.points}</span>
					))}
				</div>
				</div>
				{p.reserved?.length > 0 && (
					<div className="player-reserved">
						<div className="reserved-label">Reserved ({p.reserved.length}/3)</div>
						<div className="reserved-row">{p.reserved.map(c => renderCard(c, { source: "reserved", readonly: !isMe }))}</div>
					</div>
				)}
			</div>
		);
	}

	// Replay controls shown in the action bar while reviewing a finished game: a turn
	// indicator + Prev/Next/Latest. Turn-by-turn nav needs the snapshot list (older games
	// predating the setup snapshot have none — then we just show the final board).
	// Snapshot[idx] is the board AFTER move (idx-1): idx 0 = the start (before any move),
	// idx N = the final position (after the last move).
	function renderReplayBar() {
		const total = replaySnapshots ? replaySnapshots.length : 0;   // N+1 snapshots
		const turns = Math.max(0, total - 1);                         // N moves/turns
		const idx = replayIdx;
		const atStart = idx <= 0;
		const atFinal = replayTurn == null || idx >= turns;
		// The move that PRODUCED the board on screen (snapshot[idx] = state after that move).
		const producedBy = (!atStart && replaySnapshots) ? replaySnapshots[idx - 1] : null;
		const moverName = producedBy ? displayName(roomData?.players?.[producedBy.mover] || producedBy.mover) : null;
		return (
			<>
				<span className="turn-badge theirs">
					{atStart ? "Game start" : atFinal ? "Final position" : `Turn ${idx} / ${turns}`}
				</span>
				{roomData?.ai_variant && (
					<span className="ai-variant-badge">{aiPersona(roomData.ai_variant)}</span>
				)}
				{replayNav ? (
					<div className="replay-nav">
						<button className="btn btn-ghost btn-sm" disabled={idx <= 0}
							onClick={() => goToTurn(idx - 1)}>◀ Prev</button>
						<span className="replay-where">
							{atStart
								? "Before any moves"
								: <>{moverName}{producedBy?.move ? <span className="replay-move"> · {producedBy.move}</span> : null}</>}
						</span>
						<button className="btn btn-ghost btn-sm" disabled={idx >= turns}
							onClick={() => goToTurn(idx + 1)}>Next ▶</button>
						<button className="btn btn-outline btn-sm" disabled={atFinal} onClick={goToFinal}>Latest</button>
					</div>
				) : (
					<span className="action-hint">
						Final board &amp; game log{replaySnapshots === null ? " · turn-by-turn replay isn’t available for this game" : " · click a move in the log to rewind"}
					</span>
				)}
				<div className="action-bar-btns">
					<button className="btn btn-ghost action-bar-spacer" aria-hidden="true" tabIndex={-1}>{"✕"}</button>
				</div>
			</>
		);
	}

	// The Take/Buy/✕ controls. Rendered in the desktop action bar AND (on mobile)
	// inline with the gem bank — shared so the logic lives in one place.
	function renderActionButtons() {
		// No ✕/cancel button — clicking a selected gem or card again toggles it off
		// (handleGemClick / the card onClick), so the cancel control is redundant and
		// its width was bloating the actions box + shifting the layout in 3-4p lobbies.
		if (game.phase === "over" || !myTurn) return null;
		if (selectedGems.length > 0) return (
			<button className="btn btn-gold" onClick={handleTakeGems}>Take <span style={{ display: "inline-block", width: "0.62em", textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{selectedGems.length}</span></button>
		);
		if (selectedCard?.source === "deck")
			return me?.reserved?.length >= 3 ? <span style={{ color: "var(--text-muted)", fontSize: ".82rem" }}>Reserved slots full</span> : null;
		if (selectedCard && selectedCard.source !== "deck") {
			const affordable = canAfford(selectedCard.card.cost, me?.tokens || emptyGems(), myBonuses);
			return affordable ? <button className="btn btn-gold" onClick={() => handleBuy(selectedCard.card)}>Buy</button> : null;
		}
		return null;
	}

	// Admin-only gold button (styled like Take) that toggles the per-card AI value
	// overlay. Lives at the far-left of the actions box; rendered on either turn so the
	// overlay (computed for whoever's turn it is) can be toggled any time.
	function renderAiValsToggle() {
		// Just the toggle button now (the eval pill is renderAiEval, placed on its own row ABOVE
		// the buttons so it doesn't push Take/✕ to a second row). Works live AND in review; gated
		// on admin + overlay data for the shown position.
		if (!authUser?.is_admin || !aiCardValues) return null;
		return (
			<button className="btn btn-gold ai-vals-toggle"
				title="Show/hide the per-card AI value overlay (computed for whoever's turn it is)"
				onClick={() => setShowAiVals(v => {
					const n = !v;
					try { localStorage.setItem("spender_show_ai_vals", n ? "1" : "0"); } catch {}
					return n;
				})}>
				{showAiVals ? "Hide" : "Vals"}
			</button>
		);
	}

	// The S position eval pill — rendered on its OWN row above the action buttons.
	function renderAiEval() {
		if (!showAiVals || !authUser?.is_admin || !aiCardValues) return null;
		const evL = aiPositionEval;            // S only: STATIC leaf eval (instant)
		if (evL == null) return null;
		const evS = aiPositionEvalSearched;    // SEARCHED eval (live only — null in review)
		const mine = aiValuesPid === myId;
		const fmt = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
		return (
			<div className="ai-pos-eval-row">
				<span className={`ai-pos-eval${mine ? " mine" : ""}`}
					title={`S's whole-position eval from ${mine ? "your" : "the AI's"} perspective (+1 = ${mine ? "you" : "AI"} winning). leaf = static v(state); srch = after S's PUCT search (reused from the AI's move on its turn, freshly searched on yours)`}>
					<b>leaf</b>{fmt(evL)}{!reviewing && <span className="ai-pos-eval-srch"><b>srch</b>{evS != null ? fmt(evS) : "…"}</span>}
				</span>
			</div>
		);
	}

	function getHint() {
		// Minimal by design: the actions-box hint shows ONLY who we're waiting on (when it's
		// not your turn). On your turn it's empty — the Take/Buy buttons + the discard/noble
		// modals already convey everything. The old verbose per-action hints were removed
		// because in a squeezed 3-4p actions column they wrapped to several lines, growing the
		// actions row and shrinking the card board below it.
		if (!myTurn) return `Waiting for ${displayName(roomData?.players?.[game?.turn] || "opponent")}…`;
		return "";
	}

	// ── Screens ────────────────────────────────────────────────────────────

	// Loading screen (only shown after 250ms fast-path check misses)
	if (screen === "loading") {
		if (!showLoading) return <style>{css}</style>;
		return (
			<>
				<style>{css}</style>
				<div className="app loading-screen">
					<div className="loading-logo">{SITE_NAME}</div>
					<p className="loading-sub">Waking up the server…</p>
					<div className="loading-bar-wrap">
						<div className="loading-bar" style={{ width: `${Math.round(loadingProgress * 100)}%` }} />
					</div>
					<p className="loading-hint">
						{loadingProgress >= 0.99 ? "Ready!" : loadingProgress < 0.05 ? "Connecting…" : `${Math.round(loadingProgress * 100)}%`}
					</p>
				</div>
			</>
		);
	}

	// Auth screen
	if (screen === "auth") return (
		<>
			<style>{css}</style>
			<div className="app auth-screen">
				<div className="auth-logo">{SITE_NAME}</div>
				<p className="auth-tagline">A collection of tabletop games</p>

				<div className="auth-card">
					<div className="auth-tabs">
						{["login", "register", "guest"].map(tab => (
							<button key={tab} className={`auth-tab${authTab === tab ? " active" : ""}`}
								onClick={() => { setAuthTab(tab); setAuthError(""); }}>
								{tab === "login" ? "Sign In" : tab === "register" ? "Register" : "Guest"}
							</button>
						))}
					</div>

					{authTab !== "guest" ? (
						<>
							<input className="auth-field" placeholder="Name" value={authName}
								onChange={e => setAuthName(e.target.value)} maxLength={authTab === "register" ? 16 : 64}
								onKeyDown={e => e.key === "Enter" && handleAuth()} />
							<input className="auth-field" placeholder="Password" type="password" value={authPassword}
								onChange={e => setAuthPassword(e.target.value)} maxLength={authTab === "register" ? 16 : 128}
								onKeyDown={e => e.key === "Enter" && handleAuth()} />
							{authError && <div className="auth-error">{authError}</div>}
							<button className="btn btn-gold btn-full mt-8" onClick={handleAuth} disabled={authLoading}>
								{authLoading && <span className="spinner" />}
								{authTab === "login" ? "Sign In" : "Create Account"}
							</button>
						</>
					) : (
						<>
							<p style={{ color: "var(--text-dim)", fontSize: ".88rem", marginBottom: 14, lineHeight: 1.5 }}>
								Play without an account. Your game history won't be saved.
							</p>
							<div className="guest-name-row">
								<input className="auth-field" placeholder="Display name (optional)"
									value={guestName} onChange={e => setGuestName(e.target.value)} maxLength={20}
									onKeyDown={e => e.key === "Enter" && handleGuestPlay()} />
							</div>
							<button className="btn btn-outline btn-full mt-8" onClick={handleGuestPlay}>
								Play as Guest
							</button>
						</>
					)}
				</div>
			</div>
		</>
	);

	// Home menu — pick a game (Forrest Games landing)
	if (screen === "home") return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="home">
					<div className="home-header">
						<div className="browser-user">
							{authUser?.guest && <span className="browser-guest-badge">Guest</span>}
							<span className="browser-username">{authUser?.name}</span>
							<button className="btn btn-ghost btn-sm" onClick={handleLogout}>
								{authUser?.guest ? "Exit" : "Logout"}
							</button>
						</div>
					</div>

					<div className="home-hero">
						<div className="home-logo">{SITE_NAME}</div>
						<p className="home-tagline">Choose a game</p>
					</div>

					<div className="home-games">
						{GAMES.map(gm => (
							<button key={gm.id} className={`home-game-card ${gm.status}`}
								onClick={() => setScreen(gm.screen)}>
								<span className={`home-game-badge ${gm.status}`}>
									{gm.status === "ready" ? "Play" : "Soon"}
								</span>
								<div className="home-game-name">{gm.name}</div>
								<div className="home-game-desc">{gm.tagline}</div>
							</button>
						))}
					</div>

					<div style={{ textAlign: "center", marginTop: 24 }}>
						<button type="button" className="btn btn-ghost" onClick={() => setScreen("books")}>
							📚 Books
						</button>
					</div>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// Books — personal ranked reading list (public read, owner edit)
	if (screen === "books") return (
		<Books authUser={authUser} onExit={() => setScreen("home")} />
	);

	// Castles of Crimson — self-contained game component, mounted by the shell.
	if (screen === "coc") {
		return <CastlesOfCrimson myId={myId} authUser={authUser} onExit={() => setScreen("home")} />;
	}

	// Where Wolf? — self-contained social-deduction game component.
	if (screen === "werewolf") {
		return <WhereWolf myId={myId} authUser={authUser} onExit={() => setScreen("home")} />;
	}

	// Game browser screen
	if (screen === "browser") return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="browser-header">
					<div className="browser-head-left">
						<button className="btn btn-ghost btn-sm" onClick={() => setScreen("home")}>
							← Back
						</button>
					</div>
					<div className="browser-title">Spender</div>
					<div className="browser-user">
						{authUser?.guest && <span className="browser-guest-badge">Guest</span>}
						<span className="browser-username">{authUser?.name}</span>
					</div>
				</div>
				<div className="browser">
					<div className="browser-create">
						<div className="create-controls">
						<div className="length-toggle" title="Game length (Classic = race to 15, Long = race to 21) — also filters the open games below">
							{[[15, "Classic 15"], [21, "Long 21"]].map(([wp, label]) => (
								<button key={wp} type="button" className={`len-btn${winPoints === wp ? " sel" : ""}`}
									onClick={() => setWinPoints(wp)}>{label}</button>
							))}
						</div>
						<div className="ai-picker-wrap">
							<button className={`btn btn-gold${showCreateMenu ? " active" : ""}`}
								title="Create a game — play a friend or one of the AI opponents"
								onClick={() => setShowCreateMenu(v => !v)}>
								+ Create Game {showCreateMenu ? "▴" : "▾"}
							</button>
							{showCreateMenu && (
								<div className="ai-picker">
									<button className="btn btn-gold btn-sm"
										title="Create a game for 2-4 players — friends join from Open Games (or your room code)"
										onClick={() => { setShowCreateMenu(false); handleCreate(false, "A", winPoints); }}>
										vs Friend
									</button>
									<span className="ai-picker-label">vs AI</span>
									{["H2", "H3", "S"].map(v => (
										<button key={v} className="btn btn-outline btn-sm"
											onClick={() => { setShowCreateMenu(false); handleCreate(true, v, winPoints); }}>
											{aiPersona(v)} ({AI_TIERS[v]})
										</button>
									))}
								</div>
							)}
						</div>
						</div>
						<button className="refresh-btn" title="Refresh" onClick={() => fetchGames(authUser)}>
							{browserLoading ? <span className="spinner" /> : "↻"}
						</button>
					</div>

					{/* Mobile-only tab bar: pick one section to show in the single-column layout. */}
					<div className="lobby-tabs" role="tablist">
						{[
							["open", "Open", openGames.filter(g => (g.win_points || 15) === winPoints).length],
							["active", "Active", activeGames.filter(g => (g.win_points || 15) === winPoints).length],
							["history", "History", historyGames.filter(g => (g.win_points || 15) === winPoints).length],
						].map(([key, label, count]) => (
							<button key={key} type="button" role="tab" aria-selected={lobbyTab === key}
								className={`lobby-tab${lobbyTab === key ? " sel" : ""}`}
								onClick={() => setLobbyTab(key)}>
								{label}{count > 0 ? <span className="lobby-tab-count">{count}</span> : null}
							</button>
						))}
					</div>

					<div className={`lobby-grid tab-${lobbyTab}`}>
					<div className="browser-section open-section">
						<div className="section-hd">
							<span className="section-title">Open Games</span>
							<span className="small-muted">{winPoints === 21 ? "Long (21)" : "Classic (15)"} - waiting for players (2-4)</span>
						</div>
						{browserLoading && openGames.length === 0 ? (
							<div className="empty-state"><span className="spinner" />Loading…</div>
						) : openGames.filter(g => (g.win_points || 15) === winPoints).length === 0 ? (
							<div className="empty-state">No open {winPoints === 21 ? "Long (21)" : "Classic (15)"} games right now. Create one!</div>
						) : (
							<div className="game-cards">
								{openGames.filter(g => (g.win_points || 15) === winPoints).map(g => (
									<div key={g.id} className="game-card">
										<div className="game-card-info">
											<div className="game-card-title">
												{g.host_id === myId ? "Your game" : `${g.host_name}'s game`}
												<span className="lobby-size">{g.player_count || 1}/{g.max_players || 4}</span>
											</div>
											<div className="game-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
										</div>
										<div className="game-card-actions">
											{g.host_id === myId
												? <>
													<button className="btn btn-outline btn-sm" onClick={() => handleContinue(g.id)}>
														Return
													</button>
													<button className="btn btn-ghost btn-sm" onClick={() => handleCancel(g.id)}>
														Cancel
													</button>
												</>
												: <button className="btn btn-gold btn-sm" onClick={() => handleJoinGame(g.id)}>
													Join
												</button>}
										</div>
									</div>
								))}
							</div>
						)}
					</div>
					<div className="browser-section history-section">
						<div className="section-hd">
							<span className="section-title">History</span>
							<span className="small-muted">your recent games</span>
						</div>
						{(!authUser || authUser.guest) ? (
							<div className="empty-state">Log in to see your game history.</div>
						) : historyGames.filter(g => (g.win_points || 15) === winPoints).length === 0 ? (
							<div className="empty-state">No finished {winPoints === 21 ? "Long (21)" : "Classic (15)"} games yet.</div>
						) : (
							<div className="game-cards">
								{historyGames.filter(g => (g.win_points || 15) === winPoints).map(g => {
									// History is always YOUR games, so drop the repeated "you" —
									// just show Won/Lost vs the opponent(s) and the score (yours-theirs).
									const me = g.players.find(p => p.is_you);
									const opps = g.players.filter(p => !p.is_you);
									const oppNames = opps.map(o => displayName(o.name)).join(", ") || "—";
									const myScore = me ? me.score : 0;
									const oppScore = opps.length ? Math.max(...opps.map(o => o.score)) : 0;
									return (
									<div key={g.id} className="game-card history-card">
										<div className="game-card-info">
											<div className="game-card-title">
												<span className={`hist-result ${g.you_won ? "won" : "lost"}`}>{g.you_won ? "Won" : "Lost"}</span>
												<span className="hist-scores">vs {oppNames} <span className="hist-score-num">{myScore}-{oppScore}</span></span>
											</div>
											<div className="game-card-meta">{timeAgo(g.finished_at)}{g.win_points === 21 ? " · Long (21)" : ""}</div>
										</div>
										<div className="game-card-actions">
											<button className="btn btn-outline btn-sm" onClick={() => enterReview(g.id)}>Review</button>
										</div>
									</div>
									);
								})}
							</div>
						)}
					</div>

					{(() => {
						// All in-progress games (yours + others'). Yours pinned to the top;
						// each sub-list is already updated_at-desc from the backend.
						const hasMe = g => [g.player1_id, g.player2_id, g.player3_id, g.player4_id].includes(myId);
						const lenGames = activeGames.filter(g => (g.win_points || 15) === winPoints);
						const mine = lenGames.filter(hasMe);
						const others = lenGames.filter(g => !hasMe(g));
						const ordered = [...mine, ...others];
						return (
							<div className="browser-section active-section">
								<div className="section-hd">
									<span className="section-title">Active Games</span>
									<span className="small-muted">{ordered.length} in progress</span>
								</div>
								{ordered.length === 0 ? (
									<div className="empty-state">No games in progress.</div>
								) : (
								<div className="game-cards">
									{ordered.map(g => {
										// 2-4 seats; show the full matchup, marking your own seat.
										const seats = [
											[g.player1_id, g.player1_name], [g.player2_id, g.player2_name],
											[g.player3_id, g.player3_name], [g.player4_id, g.player4_name],
										].filter(([id, nm]) => id || nm);
										const isMine = seats.some(([id]) => id === myId);
										const turnName = (seats.find(([id]) => id === g.turn) || [])[1] || null;
										return (
											<div key={g.id} className="game-card">
												<div className="game-card-info">
													<div className="game-card-title matchup">
														{seats.map(([id, nm], i) => (
															<div key={id || i}>{i > 0 ? "vs " : ""}{displayName(nm)}{id === myId ? " (you)" : ""}</div>
														))}
													</div>
													<div className="game-card-meta">{g.id} · {timeAgo(g.updated_at)}</div>
												</div>
												<div className="game-card-actions">
													{isMine ? (
														<>
															{g.turn === myId
																? <span className="your-turn-badge">Your Turn</span>
																: <span className="playing-badge">Their Turn</span>}
															<button className="btn btn-outline btn-sm" onClick={() => handleContinue(g.id)}>Resume</button>
														</>
													) : (
														<span className="playing-badge">{turnName ? `${displayName(turnName)}'s turn` : "In progress"}</span>
													)}
												</div>
											</div>
										);
									})}
								</div>
								)}
							</div>
						);
					})()}
					</div>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// Waiting screen
	if (screen === "waiting") return (
		<>
			<style>{css}</style>
			<div className="app" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
				<div className="waiting-screen">
					<p className="waiting-title">Room Code</p>
					<p className="waiting-sub">Share this code with your friends — 2 to 4 players</p>
					<div className="room-code-box" title="Click to copy"
						onClick={() => { navigator.clipboard?.writeText(roomId); setToast("Copied!"); }}>
						{roomId}
					</div>
					<p className="copy-hint">tap code to copy</p>

					<p className="waiting-sub">{Object.keys(roomData?.players || {}).length}/4 players joined</p>
					<ul className="player-list">
						{roomData?.players && Object.entries(roomData.players).map(([id, name]) => (
							<li key={id} className={id === myId ? "me" : ""}>
								<span className={`conn-dot ${roomData?.status !== "over" ? "connected" : "disconnected"}`} />
								{name}{id === myId ? " (you)" : ""}
								{id === roomData?.host ? " ♔" : ""}
							</li>
						))}
					</ul>

					{roomData?.host === myId ? (
						<button className="btn btn-gold btn-full"
							disabled={!roomData?.players || Object.keys(roomData.players).length < 2}
							onClick={handleStart}>
							{(Object.keys(roomData?.players || {}).length >= 2)
								? `Start Game (${Object.keys(roomData.players).length} players)`
								: "Start Game"}
						</button>
					) : (
						<p className="status-msg">Waiting for the host to start…</p>
					)}

					<button className="btn btn-ghost btn-full mt-8" onClick={goToMenu}>
						← Back to Menu
					</button>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// Winner screen (held back 2s after the game ends — see the resultReady effect —
	// so the final board is visible for a beat before the result is revealed).
	if (screen === "game" && game?.phase === "over" && !reviewing && resultReady) {
		const winners = Array.isArray(game.winner) ? game.winner : [game.winner];
		const isTie = winners.length > 1;
		const iWon = winners.includes(myId);
		const winnerNames = winners.map(w => displayName(roomData?.players?.[w] || w)).join(" & ");
		return (
			<>
				<style>{css}</style>
				<div className="app">
					<div className="winner-screen">
						<div className={`winner-title${!isTie && !iWon ? " defeat" : ""}`}>{isTie ? "Draw!" : iWon ? "Victory!" : "Defeat"}</div>
						<p className="winner-sub">{isTie ? `${winnerNames} share the gem trade` : `${winnerNames} claims the gem trade`}</p>
						<div className="final-scores">
							{(game.order || []).map(pid => {
								const score = totalPoints(game.players?.[pid]?.purchased || [], game.players?.[pid]?.nobles || []);
								const name = displayName(roomData?.players?.[pid] || pid.slice(0, 6));
								const isWinner = winners.includes(pid);
								return (
									<div key={pid} className={`score-row${isWinner ? " winner" : ""}`}>
										{isWinner ? "★ " : ""}{name} — {score} pts
									</div>
								);
							})}
						</div>
						<div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
							<button className="btn btn-gold" onClick={() => enterReview(roomId)}>
								Review Board & Log
							</button>
							<button className="btn btn-outline" onClick={() => {
								try { localStorage.removeItem("spender_roomId"); } catch {}
								setReviewing(false);
								setReplaySnapshots(null); setReplayTurn(null);
								setScreen("browser"); setRoomData(null); setRoomId(""); disconnect();
								fetchGames(authUser);
							}}>
								Back to Browser
							</button>
						</div>
					</div>
				</div>
			</>
		);
	}

	// Game screen
	if (screen === "game" && game) return (
		<>
			<style>{css}</style>
			<div className="app game-screen">
				<div className="game-nav">
					{reviewChrome
						? <button className="btn btn-ghost btn-sm" onClick={() => { setReplayTurn(null); setReviewing(false); setResultReady(true); }}>← Back to Results</button>
						: <button className="btn btn-ghost btn-sm" onClick={goToMenu}>← Menu</button>}
					<span className="game-nav-title">Spender{reviewChrome ? " — Review" : ""}</span>
					{reviewChrome
						? <span style={{ width: 64 }} />
						: <button className="btn btn-danger btn-sm" onClick={() => setConfirmAbandon(true)}>Abandon</button>}
				</div>
				<div className="game-nav-spacer" />
				<div className="game">
					<div className="game-main">

						<div className="action-bar">
								{reviewing ? renderReplayBar() : (<>
							<span className={`turn-badge ${game.phase === "over" ? "theirs" : myTurn ? "mine" : "theirs"}`}>
								{game.phase === "over" ? "Game Over" : myTurn ? "Your Turn" : `${displayName(roomData?.players?.[game.turn])}'s Turn`}
							</span>
							{roomData?.ai_variant && (
								<span className="ai-variant-badge">{aiPersona(roomData.ai_variant)}</span>
							)}
							{game.phase === "over"
								? <span className="action-hint">Final board &amp; game log</span>
								: aiThinking
									? <span className="ai-thinking"><span className="think-dot"/><span className="think-dot"/><span className="think-dot"/> thinking…</span>
									: <><span className="target-label" style={{ marginRight: 6 }}>Target: {game.win_points || 15}</span><span className="action-hint">{getHint()}</span></>
							}
							<div className="action-bar-btns">
								{renderActionButtons() || <button className="btn btn-ghost action-bar-spacer" aria-hidden="true" tabIndex={-1}>{"✕"}</button>}
							</div>
								</>)}
						</div>

						<div className="panel bank-panel">
							<div className="panel-title">Gem Bank</div>
							<div className="bank-gems">
								{/* gold (the wild/reserve token) first so it sits above white */}
								{["gold", ...GEM_COLORS].map(c => {
									const count = game.bank[c] || 0;
									const isGold = c === "gold";
									const selCount = selectedGems.filter(x => x === c).length;
									// Gold coin doubles as the "reserve" control, both directions:
									//   card-first: select a card, then click gold to reserve it
									//   gold-first: click gold to ARM, then click any card to reserve it
									// (gold bank can be 0 — you still reserve, just without gaining a gold).
									const slotsOpen = (me?.reserved?.length || 0) < 3;
									const goldReserveReady = isGold && myTurn && selectedCard
										&& selectedCard.source !== "reserved" && slotsOpen;
									const goldActive = isGold && myTurn && slotsOpen;     // clickable (arm or complete)
									const goldLit = goldReserveReady || (isGold && reserveArmed);  // pulse when engaged
									const disabled = isGold ? !goldActive : (!myTurn || count === 0);
									return (
										<div key={c} data-color={c}
											className={`gem-stack${selCount > 0 ? " selected" : ""}${goldLit ? " reserve-ready" : ""}${flashGems.has(c) ? " flashing" : ""}${disabled ? " disabled" : ""}`}
											onClick={() => {
												if (!isGold) { handleGemClick(c); return; }
												if (goldReserveReady) { handleReserveSelected(); return; }
												if (slotsOpen) { setSelectedGems([]); setSelectedCard(null); setReserveArmed(a => !a); }
											}}
											title={isGold
												? (goldReserveReady ? "Reserve the selected card (take a gold)"
													: reserveArmed ? "Reserve armed — click a card to reserve it"
													: slotsOpen ? "Reserve: click here then a card, or select a card first"
													: "Reserve slots full (3/3)")
												: GEM_LABELS[c]}>
											<GemToken color={c} />
											<span className="gem-count">{count}</span>
										</div>
									);
								})}
							</div>
						</div>

						<div className="levels">
						{["L3", "L2", "L1"].map((lk, i) => (
							<div key={lk} className="panel level-panel">
								<div className="level-row">
									<div className={`deck-pile${!myTurn ? " disabled" : ""}${reserveArmed ? " reserve-ready" : ""}${selectedCard?.source === "deck" && selectedCard?.deckLevel === 3 - i ? " selected" : ""}`}
										onClick={() => {
											if (!myTurn) return;
											if (reserveArmed && (me?.reserved?.length || 0) < 3) { handleReserve(null, 3 - i); return; }
											setSelectedGems([]); setReserveArmed(false);
											setSelectedCard(s => s?.source === "deck" && s?.deckLevel === 3 - i ? null : { source: "deck", deckLevel: 3 - i });
										}}
										title="Reserve blind from deck">
										<span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--text)", lineHeight: 1 }}>{["III","II","I"][i]}</span>
										<span style={{ fontSize: ".76rem", letterSpacing: ".08em" }}>DECK</span>
										{(game.decks?.[lk]?.length ?? 0) <= 5 && <span className="deck-remaining">{game.decks?.[lk]?.length || 0}</span>}
									</div>
									{(game.board?.[lk] || []).map((c, j) => c ? renderCard(c, { dataPos: `${lk}-${j}` }) : <div key={j} className="card-slot" data-pos={`${lk}-${j}`} />)}
								</div>
							</div>
						))}
						</div>

						<div className="panel nobles-panel">
							<div className="panel-title">Nobles</div>
							<div className="nobles-row">
								{(() => {
									// Render the FULL original noble set in a stable id-sorted order so
									// nobles NEVER move when one is claimed. A claimed noble shows
									// faded + the claimer's name (same look during play and in review).
									const claimerOf = {};
									(game.order || []).forEach(pid =>
										(game.players?.[pid]?.nobles || []).forEach(n => {
											claimerOf[n.id] = displayName(roomData?.players?.[pid] || pid.slice(0, 6)) + (pid === myId ? " (you)" : "");
										}));
									const claimed = (game.order || []).flatMap(pid => game.players?.[pid]?.nobles || []);
									const all = [...(game.nobles || []), ...claimed].sort((a, b) => String(a.id).localeCompare(String(b.id)));
									const unclaimed = new Set((game.nobles || []).map(n => n.id));
									return all.map(n =>
										unclaimed.has(n.id)
											? <NobleView key={n.id} noble={n} />
											: <NobleView key={n.id} noble={n} dimmed claimedBy={claimerOf[n.id]} />
									);
								})()}
							</div>
							{/* Mobile/tablet only (CSS): a box to the right of the nobles with the
							    win-points Target + the Take/Buy/✕ controls (AI "thinking" indicator
							    during the bot's turn). The hint is dropped here — no room beside the
							    nobles. */}
							{game.phase !== "over" && (
								<div className="board-actions">
									<span className="target-label">Target: {game.win_points || 15}</span>
									{renderAiEval()}
									<div className="board-actions-btns">
										{renderAiValsToggle()}
										{aiThinking
											? <span className="ai-thinking"><span className="think-dot"/><span className="think-dot"/><span className="think-dot"/> thinking…</span>
											: renderActionButtons()}
									</div>
								</div>
							)}
						</div>

						{/* Desktop only (CSS): a box beside the nobles with the turn hint +
						    the Take/Buy/✕ controls (AI 'thinking' indicator on the bot's turn). */}
						{/* Column layout (desktop): Target pinned to the TOP, hint to the BOTTOM,
						    buttons centered between them — so a NARROW box (4-player games widen the
						    nobles row, shrinking this column) never squishes the hint beside the buttons. */}
						<div className="panel actions-panel">
							{game.phase !== "over" && (
								<div className="actions-panel-top">
									<span className="target-label">Target: {game.win_points || 15}</span>
								</div>
							)}
							{renderAiEval()}
							<div className="actions-panel-btns">
								{renderAiValsToggle()}
								{aiThinking
									? <span className="ai-thinking"><span className="think-dot"/><span className="think-dot"/><span className="think-dot"/> thinking…</span>
									: renderActionButtons()}
							</div>
							<span className="action-hint">{game.phase === "over" ? "Final board & game log" : getHint()}</span>
						</div>
					</div>

					<div className="game-sidebar">
						{(
							<div className={`panel log-panel${logOpen ? " open" : ""}`}>
								<div className="panel-title log-head" onClick={() => setLogOpen(o => !o)}>
									Log <span className="log-caret">{logOpen ? "▾" : "▸"}</span>
								</div>
								<div className="move-log">
									{liveGame?.phase === "over" && (() => {
										// "X won the game" — a plain (unclickable) marker at the top of the log,
										// derived from game.winner so it needs no persisted entry and works for
										// every finished game (incl. ones predating the setup snapshot).
										const winners = Array.isArray(liveGame.winner)
											? liveGame.winner : (liveGame.winner != null ? [liveGame.winner] : []);
										const names = winners.map(w => displayName(roomData?.players?.[w] || (typeof w === "string" ? w.slice(0, 6) : w)));
										const label = names.length === 0 ? "Game over"
											: names.length > 1 ? `${names.join(" & ")} tied the game`
											: `${names[0]} won the game`;
										return (
											<div className="log-entry log-win">
												<span className="log-action">🏆 {label}</span>
											</div>
										);
									})()}
									{((liveGame?.moves) || []).map((mv, i) => {
										const { name, action, card } = formatLogMove(mv);
										// Each move row jumps to the board AFTER that move: snapshot[turn+1]. In a
										// live (non-review) game a click instead inspects the move's card.
										const turnIdx = moveTurns[i];
										// A turn spans several rows (a buy + its noble claim, a take + a discard);
										// highlight only its PRIMARY row so exactly one row marks the shown state.
										const isPrimary = mv.type === "take_gems" || mv.type === "buy" || mv.type === "reserve";
										const selectedTurn = replayNav && replayIdx === turnIdx + 1 && isPrimary;
										const handleClick = replayNav
											? () => goToTurn(turnIdx + 1)
											: (card ? () => setModalCard(card) : undefined);
										const clickable = replayNav || !!card;
										return (
											<div key={i}
												className={`log-entry${clickable ? " clickable" : ""}${selectedTurn ? " log-selected" : ""}`}
												onClick={handleClick}>
												<span className="log-name">{name}</span>
												<span className="log-action">{action}</span>
											</div>
										);
									})}
									{liveGame && (
										// "Game started" — the oldest entry (bottom), shown from the moment you
										// load in (even before any move). Clicking shows the initial board
										// (snapshot[0], before anyone has moved).
										<div className={`log-entry log-start${replayNav ? " clickable" : ""}${replayNav && replayIdx === 0 ? " log-selected" : ""}`}
											onClick={replayNav ? () => goToTurn(0) : undefined}>
											<span className="log-action">▶ Game started</span>
										</div>
									)}
								</div>
							</div>
						)}
						<div className="panel-title" style={{ padding: "0 4px" }}>Players</div>
						<div className="players-area">
							{(game.order || []).map(pid => renderPlayerPanel(pid))}
						</div>
					</div>
				</div>

				{flyers.length > 0 && (
					<div className="fly-layer">
						{flyers.map(f => f.kind === "card" ? (
							<div key={f.id} className="fly-card" style={{
								left: f.x, top: f.y, width: f.w, height: f.h, borderColor: GEM_HEX[f.color],
								"--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0, "--s1": f.s1,
								animationDelay: `${f.delay}ms`,
							}}>
								<span className="fly-card-pt">{f.points || ""}</span>
								<span className="fly-card-dot" style={{ background: GEM_HEX[f.color] }} />
							</div>
						) : (
							<div key={f.id} className="fly-gem" style={{
								left: f.x - f.size / 2, top: f.y - f.size / 2, width: f.size, height: f.size,
								background: GEM_HEX[f.color],
								"--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0, "--s1": f.s1,
								animationDelay: `${f.delay}ms`,
							}} />
						))}
					</div>
				)}

				{modalCard && (
					<div className="modal-backdrop" onClick={() => setModalCard(null)}>
						<div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 220, textAlign: "center" }}>
							<div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
								<CardView card={modalCard} />
							</div>
							<button className="btn btn-ghost btn-sm" style={{ width: "100%" }} onClick={() => setModalCard(null)}>Close</button>
						</div>
					</div>
				)}

				{needsDiscard && me && (
					<div className="modal-backdrop">
						<div className="modal">
							<h3>Too Many Gems</h3>
							<p>You have {gemTotal(me.tokens)} gems. Discard down to 10.</p>
							<div className="discard-gems">
								{[...GEM_COLORS, "gold"].map(c => {
									const count = me.tokens[c] || 0;
									return count > 0 && (
										<button key={c} className="discard-btn" onClick={() => handleDiscard(c)}>
											<span style={{ width: 10, height: 10, borderRadius: "50%", background: GEM_HEX[c], display: "inline-block" }} />
											{GEM_LABELS[c]} ({count})
										</button>
									);
								})}
							</div>
							<div className="discard-count">Total: {gemTotal(me.tokens)} / 10</div>
							<div style={{ display: "flex", justifyContent: "center", marginTop: 14 }}>
								<button className="btn btn-ghost btn-sm" onClick={handleUndoDiscard}>↩ Undo turn</button>
							</div>
						</div>
					</div>
				)}

				{needsNobleChoice && (() => {
					const pending = game?.pending_noble_choice || [];
					const choices = (game?.nobles || []).filter(n => pending.includes(n.id));
					return choices.length > 0 && (
						<div className="modal-backdrop">
							<div className="modal">
								<h3>Choose a Noble</h3>
								<p>You qualify for multiple nobles. Choose one to claim.</p>
								<div style={{ display: "flex", gap: 12, marginTop: 12, justifyContent: "center", flexWrap: "wrap" }}>
									{choices.map(n => (
										<button key={n.id} className="btn btn-gold" onClick={() => handleNobleChoice(n.id)}
											style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "12px 16px" }}>
											<NobleView noble={n} />
										</button>
									))}
								</div>
							</div>
						</div>
					);
				})()}

				{confirmAbandon && (
					<div className="modal-backdrop">
						<div className="modal">
							<h3>Abandon Game?</h3>
							<p>This counts as a loss for you. Your opponent will be awarded the win.</p>
							<div style={{ display: "flex", gap: 10, marginTop: 8 }}>
								<button className="btn btn-danger" onClick={handleAbandon}>Yes, Abandon</button>
								<button className="btn btn-ghost" onClick={() => setConfirmAbandon(false)}>Cancel</button>
							</div>
						</div>
					</div>
				)}

				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// Loading / fallback
	return (
		<>
			<style>{css}</style>
			<div className="app" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
				<p style={{ color: "var(--text-dim)", fontStyle: "italic", fontFamily: "'Cinzel',serif", fontSize: ".9rem" }}>Loading…</p>
			</div>
		</>
	);
}
