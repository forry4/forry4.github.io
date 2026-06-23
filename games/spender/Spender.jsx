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
/* game-length toggle: selected state changes ONLY background+color (fixed border/padding)
   so selecting never changes the element's size / shifts the layout */
.length-toggle{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;flex-shrink:0}
.len-btn{padding:9px 14px;background:transparent;border:none;color:var(--text-dim);font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;letter-spacing:.03em;cursor:pointer;transition:background .12s,color .12s;white-space:nowrap}
.len-btn+.len-btn{border-left:1px solid var(--border)}
.len-btn.sel{background:var(--gold);color:#1c1710}
.btn-outline.active{background:var(--gold);color:#0f0e0c}
.ai-picker-wrap{position:relative;display:inline-flex}
.ai-picker{position:absolute;top:calc(100% + 8px);left:0;z-index:30;display:flex;gap:8px;align-items:center;flex-wrap:wrap;max-width:min(92vw,420px);padding:12px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:0 10px 28px rgba(0,0,0,.5)}
.ai-picker-label{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.06em;color:var(--text-dim);text-transform:uppercase;margin-right:4px}
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
  .lobby-grid{grid-template-columns:1fr}
  .lobby-grid>.open-section{grid-column:1;grid-row:1}
  .lobby-grid>.active-section{grid-column:1;grid-row:2}
  .lobby-grid>.history-section{grid-column:1;grid-row:3}
  .lobby-grid>.browser-section{margin-bottom:24px}
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
  .nobles-panel .board-actions{flex:1 1 auto;min-width:118px;display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:8px}
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
  /* Top row = nobles box + an actions box (hint + Take/Buy/✕) side by side, on
     top of the card board; a vertical gem bank spans to their right; the player
     sidebar is the outer grid's wide 2nd column. L-to-R: nobles/cards, bank, players. */
  /* Lock the game screen to the viewport so nothing (esp. the recent-moves list)
     grows the page past the window; the board fills naturally and the move log
     scrolls internally instead. */
  .game-screen{height:100vh;overflow:hidden}
  /* .game needs an EXPLICIT definite height (not flex:1 — flex-basis:0% isn't a
     definite height the grid fr/minmax can resolve against, so the row would
     grow to its tallest content = the recent-moves list, pushing past the screen
     and resizing the player boxes). flex:none + height:calc + minmax(0,1fr) BOUNDS
     the single row to the viewport, so the sidebar is a fixed height: the move log
     scrolls internally and the player boxes never resize.
     NOTE: never put backticks in this CSS string — it's a JS template literal. */
  .game{grid-template-columns:1fr 560px;grid-template-rows:minmax(0,1fr);flex:none;height:calc(100vh - 48px);overflow:hidden}
  /* Sidebar = two full-height columns: players (left, wider so 6 tokens fit one
     row) + recent moves (far right). min-height:0 lets the move log scroll. */
  /* grid-template-rows:minmax(0,1fr) bounds the sidebar's row to its (definite)
     height too — without it the inner row grows to the moves content and the log
     gets clipped instead of scrolling (same trap as the outer .game grid). */
  .game-sidebar{display:grid;grid-template-columns:1.6fr 1fr;grid-template-rows:minmax(0,1fr);column-gap:14px;align-items:stretch;min-height:0}
  /* Both pinned to row 1 — without an explicit row the descending DOM-order vs
     column-order (log-panel first=col2, players second=col1) made grid's sparse
     flow drop the players to row 2 (moves top-right, players bottom-left). */
  /* Players column: the two boxes each take half the height — box 1 flush to the
     top down to the middle, box 2 flush to the bottom up to the middle. */
  .game-sidebar>.players-area{grid-column:1;grid-row:1;height:100%}
  /* flex:1 splits the column evenly across 2-4 player boxes; overflow-y:auto lets a
     cramped 3-4 player box scroll internally instead of overflowing the grid. */
  .game-sidebar .player-panel{flex:1;min-height:0;overflow-y:auto}
  /* Moves column fills the full height (flush to the bottom of the screen). */
  .game-sidebar>.log-panel{grid-column:2;grid-row:1;height:100%;display:flex;flex-direction:column}
  /* align-content:start keeps the rows packed at the top — without it grid's
     default stretches the auto rows to fill a tall viewport, inflating the top
     row into a big gap above the cards. */
  /* Explicit grid-template-rows is REQUIRED: with auto/implicit rows, the bank's
     grid-row:1/-1 resolved to a single row (-1 == line 1) so it never spanned
     down to the cards, and the cards got pushed into a separate band (the gap). */
  /* Row 2 is 1fr so the card board fills the remaining viewport height; the card
     rows then spread to reach the bottom of the screen. */
  .game-main{display:grid;grid-template-columns:auto 1fr 132px;grid-template-rows:auto 1fr;column-gap:16px;row-gap:10px;align-items:start;--card-w:144px;--card-h:185px}
  .game-main>.nobles-panel{grid-column:1;grid-row:1}
  /* align-self:stretch so the hint box matches the nobles box height in row 1;
     hint on the left, buttons pushed to the right edge of the box. */
  .actions-panel{grid-column:2;grid-row:1;align-self:stretch;display:flex;flex-direction:column;justify-content:space-between;align-items:stretch;gap:8px}
  /* Fill row 2 and space the three card rows out so the bottom row is flush with
     the bottom of the screen. */
  .game-main>.levels{grid-column:1 / 3;grid-row:2;align-self:stretch;justify-content:space-between}
  /* Bank spans both rows (explicit span) + stretches, so it runs down to the
     bottom of the card board (gems spread over that height). */
  .bank-panel{grid-column:3;grid-row:1 / span 2;align-self:stretch;display:flex;flex-direction:column}

  /* Nobles: horizontal row on top of the cards, 1.5x larger; no title. */
  .nobles-panel .panel-title{display:none}
  /* exactly square: aspect-ratio:1 makes height track the (wider) width */
  .noble{width:120px;aspect-ratio:1;padding:9px;gap:6px;justify-content:center}
  .noble-points{font-size:1.5rem}
  .noble-req-row{font-size:.95rem;gap:4px}
  .noble-req-dot{width:12px;height:12px}
  .noble-claimer{font-size:.72rem;bottom:6px}

  /* Actions box: hint takes the left, bigger buttons pinned to the right. */
  /* hint at the bottom, full box width, wraps freely (flex:0 so space-between pins it
     to the bottom instead of it growing to fill; override base nowrap/ellipsis/flex:1). */
  .actions-panel .action-hint{flex:0 0 auto;font-size:.95rem;white-space:normal;overflow:visible;text-overflow:clip;color:var(--text-dim);font-style:italic}
  /* target pinned to the top, full width. */
  .actions-panel .target-label{align-self:stretch}
  /* buttons centered between target and hint (no margin-left:auto — that was for the old row layout). */
  .actions-panel-btns{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:center;flex-shrink:0}
  .actions-panel-btns .btn{padding:14px 30px;font-size:1.12rem}

  /* Vertical gem bank; gems clustered toward the vertical center, closer together. */
  .bank-gems{flex-direction:column;align-items:center;flex:1;justify-content:center;gap:18px}
  .bank-gems .gem-token{width:64px!important;height:64px!important;font-size:1.4rem!important}
  .bank-gems .gem-count{font-size:1.05rem}

  /* Drop the Gem Bank + Players labels on desktop (the Log label stays). */
  .bank-panel .panel-title{display:none}
  .game-sidebar>.panel-title{display:none}

  /* Bigger recent-moves + player boxes in the wider sidebar. */
  .player-panel{padding:16px}
  .player-name{font-size:1rem}
  .player-score{font-size:1.4rem}
  /* gem + card (bonus) indicators +20% via zoom (scales box+content+inline dots, with reflow) */
  .token-pill,.bonus-pill{font-size:.82rem;padding:3px 9px;zoom:1.2}
  .bonus-pill{padding:3px 9.5px}      /* card bonus indicator width +1px net (9->9.5 each side) */
  .gem-total{zoom:1.2}                /* "N gems" counter +20% */
  .player-reserved .card{zoom:1.1;width:89px}    /* reserved cards +10%, width 89px */
  /* reserve the token-row height so 0 gems doesn't shift the bonus pills up;
     align-items:flex-start so the row's min-height doesn't STRETCH the pills taller */
  .player-tokens{min-height:28px;align-items:flex-start}
  /* Cap the move log to ~viewport height (explicit, so it bounds even if the
     nested-grid height chain doesn't propagate) — it scrolls within and never
     pushes the page past the window. */
  .move-log{max-height:calc(100vh - 140px);flex:1;min-height:0}
  .log-entry{font-size:.92rem;padding:6px 0}
  .log-name{font-size:.84rem}

  /* Board cards: scale the box (via --card-*) and the inner content. */
  .level-row{overflow-x:visible;gap:10px;justify-content:center}
  .level-row .card{padding:9px 8px 8px}
  .level-row .card-header{margin-bottom:8px}
  .level-row .card-points{font-size:1.7rem}
  .level-row .card-bonus{width:29px;height:29px}
  .level-row .cost-gem{width:15px;height:15px}
  .level-row .cost-num{font-size:.92rem}
  .level-row .card-cost{gap:5px}
  .level-row .deck-pile{font-size:.78rem;gap:6px}
  .level-row .deck-remaining{font-size:1.7rem}
}

@media(max-width:600px){
  .browser{padding:20px 14px 40px}
  .browser-title{font-size:1.4rem}
  .browser-header{padding-left:14px;padding-right:14px}
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

function CardView({ card, selected, affordable, needsGold, disabled, onClick, aiValue, dataPos }) {
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
				<div className="ai-vals" title={aiValue.pot != null
					? "H3 — take / engine / point / cost"
					: "H2 — take / engine / point / cost"}>
					<span><b>T</b>{aiValue.t}</span>
					<span><b>E</b>{aiValue.e}</span>
					<span><b>P</b>{aiValue.p}</span>
					<span><b>C</b>{aiValue.c}</span>
				</div>
			) : (
				<span className="ai-val" title="AI card value (variant H)">{aiValue}</span>
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

	// ── Derived game state (must be before useEffect hooks that use `game`) ──
	const game = roomData?.game;
	const me = game?.players?.[myId];
	const myTurn = game?.turn === myId && game?.phase === "playing";
	const myBonuses = me ? bonusesFrom(me.purchased) : emptyGems();
	const aiThinking = game?.ai_player && game?.turn === game?.ai_player && game?.phase === "playing";
	// Derived from game state (not a transient message) so a later room_update
	// can't clear an unmet requirement — the server keeps these set until resolved.
	const needsDiscard = game?.pending_discard_pid === myId;
	const needsNobleChoice = game?.pending_noble_pid === myId;
	// Catalog of every card currently visible in state (board + both players'
	// purchased/reserved), keyed by id. The move log stores only card_id (the server
	// log is id-only); this resolves those ids back to full cards for display + the
	// inspect modal. Complete by construction: a logged buy/reserve card is always
	// present somewhere in the live state (purchased/reserved/board).
	const cardsById = useMemo(() => {
		const m = {};
		if (!game) return m;
		const add = (c) => { if (c && c.id && c.cost) m[c.id] = c; };
		const b = game.board || {};
		for (const lk of ["L1", "L2", "L3"]) (b[lk] || []).forEach(add);
		for (const p of Object.values(game.players || {})) {
			(p.purchased || []).forEach(add);
			(p.reserved || []).forEach(add);
		}
		return m;
	}, [game]);

	const [selectedGems, setSelectedGems] = useState([]);
	const [selectedCard, setSelectedCard] = useState(null);
	const [reserveArmed, setReserveArmed] = useState(false);  // gold-first reserve: click gold, then a card
	const [toast, setToast] = useState("");
	const [confirmAbandon, setConfirmAbandon] = useState(false);
	const [reviewing, setReviewing] = useState(false);  // end-game: viewing final board + log
	const [resultReady, setResultReady] = useState(false);  // gate the win/loss screen until ~1s after game ends
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
	const [showAiPicker, setShowAiPicker] = useState(false);
	const [winPoints, setWinPoints] = useState(15);   // 15 = Classic, 21 = Long mode

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
	useEffect(() => {
		const handleVisibility = () => {
			// Only auto-reconnect when actively on the game screen — otherwise tabbing
			// back would dump a lobby/waiting user into a stale waiting room.
			if (document.visibilityState === "visible"
				&& screenRef.current === "game"
				&& roomIdRef.current
				&& getReadyState() !== WebSocket.OPEN) {
				connect(`${WS_BASE}/${roomIdRef.current}/${myId}`);
			}
		};
		document.addEventListener("visibilitychange", handleVisibility);
		return () => document.removeEventListener("visibilitychange", handleVisibility);
	}, [myId, connect, getReadyState]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		if (screen === "browser" && authUser) fetchGames(authUser);
	}, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		if (toast) { const t = setTimeout(() => setToast(""), 2500); return () => clearTimeout(t); }
	}, [toast]);

	// Hold on the final board for ~1s after the game ends before revealing the
	// win/loss screen, so the player sees the move that ended it. Resets whenever
	// the game isn't over (a new game), so the next ending delays again.
	useEffect(() => {
		if (game?.phase === "over") {
			const t = setTimeout(() => setResultReady(true), 1000);
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
		if (!game?.bank) return;
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
				const user = { id: data.user.id, name: data.user.name, session_token: data.session_token || null };
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

	const goToMenu = () => {
		disconnect();
		setScreen("browser");
		setRoomData(null);
		setSelectedGems([]);
		setSelectedCard(null);
		setConfirmAbandon(false);
		setReviewing(false);
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
				aiValue={(authUser?.is_admin && showAiVals) ? roomData?.ai_card_values?.[card.id] : null}
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
		return (
			<div key={pid} data-pid={pid} className={`player-panel${isMe ? " me" : ""}${isActive ? " active-turn" : ""}${expanded ? " expanded" : ""}`}>
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

	// The Take/Buy/✕ controls. Rendered in the desktop action bar AND (on mobile)
	// inline with the gem bank — shared so the logic lives in one place.
	function renderActionButtons() {
		if (game.phase === "over" || !myTurn) return null;
		if (selectedGems.length > 0) return (
			<>
				<button className="btn btn-gold" onClick={handleTakeGems}>Take {selectedGems.length}</button>
				<button className="btn btn-ghost" onClick={() => setSelectedGems([])}>✕</button>
			</>
		);
		if (selectedCard?.source === "deck") return (
			<>
				{me?.reserved?.length >= 3 && <span style={{ color: "var(--text-muted)", fontSize: ".82rem" }}>Reserved slots full</span>}
				<button className="btn btn-ghost" onClick={() => setSelectedCard(null)}>✕</button>
			</>
		);
		if (selectedCard && selectedCard.source !== "deck") {
			const affordable = canAfford(selectedCard.card.cost, me?.tokens || emptyGems(), myBonuses);
			return (
				<>
					{affordable && <button className="btn btn-gold" onClick={() => handleBuy(selectedCard.card)}>Buy</button>}
					<button className="btn btn-ghost" onClick={() => setSelectedCard(null)}>✕</button>
				</>
			);
		}
		return null;
	}

	function getHint() {
		if (!myTurn) return `Waiting for ${displayName(roomData?.players?.[game?.turn] || "opponent")}…`;
		const slotsFull = (me?.reserved?.length || 0) >= 3;
		if (reserveArmed) return "Reserve armed — click a card or deck to reserve it (or the gold coin to cancel)";
		if (selectedCard?.source === "deck")
			return slotsFull ? "Reserved slots full (3/3)" : `Click the gold coin to reserve blind from Level ${selectedCard.deckLevel} deck`;
		if (selectedCard) {
			const affordable = canAfford(selectedCard.card.cost, me?.tokens || emptyGems(), myBonuses);
			const canReserve = selectedCard.source !== "reserved" && !slotsFull;
			if (affordable) return canReserve ? "Buy this card, or click the gold coin to reserve" : "Buy this card";
			return canReserve ? "Click the gold coin to reserve this card" : "Can't afford yet";
		}
		if (selectedGems.length > 0) return `${selectedGems.length} gem(s) selected — confirm to take`;
		return "Take gems, or click a card then the gold coin to reserve";
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
						<div className="length-toggle" title="Game length (Classic = race to 15, Long = race to 21) — also filters the open games below">
							{[[15, "Classic 15"], [21, "Long 21"]].map(([wp, label]) => (
								<button key={wp} type="button" className={`len-btn${winPoints === wp ? " sel" : ""}`}
									onClick={() => setWinPoints(wp)}>{label}</button>
							))}
						</div>
						<button className="btn btn-gold" title="Create a game for 2-4 players — friends join from Open Games (or your room code)"
							onClick={() => handleCreate(false, "A", winPoints)}>
							+ Create Game
						</button>
						<div className="ai-picker-wrap">
							<button className={`btn btn-outline${showAiPicker ? " active" : ""}`}
								onClick={() => setShowAiPicker(v => !v)}>
								Play vs AI {showAiPicker ? "▴" : "▾"}
							</button>
							{showAiPicker && (
								<div className="ai-picker">
									<span className="ai-picker-label">Choose AI opponent</span>
									{["H2", "H3", "S"].map(v => (
										<button key={v} className="btn btn-outline btn-sm"
											onClick={() => { setShowAiPicker(false); handleCreate(true, v, winPoints); }}>
											{aiPersona(v)} ({AI_TIERS[v]})
										</button>
									))}
								</div>
							)}
						</div>
						<button className="refresh-btn" title="Refresh" onClick={() => fetchGames(authUser)}>
							{browserLoading ? <span className="spinner" /> : "↻"}
						</button>
					</div>

					<div className="lobby-grid">
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
						) : historyGames.length === 0 ? (
							<div className="empty-state">No finished games yet.</div>
						) : (
							<div className="game-cards">
								{historyGames.map(g => {
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
						const mine = activeGames.filter(hasMe);
						const others = activeGames.filter(g => !hasMe(g));
						const ordered = [...mine, ...others];
						return (
							<div className="browser-section active-section">
								<div className="section-hd">
									<span className="section-title">Active Games</span>
									<span className="small-muted">{activeGames.length} in progress</span>
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

	// Winner screen (held back ~1s after the game ends — see the resultReady effect —
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
							<button className="btn btn-gold" onClick={() => setReviewing(true)}>
								Review Board & Log
							</button>
							<button className="btn btn-outline" onClick={() => {
								try { localStorage.removeItem("spender_roomId"); } catch {}
								setReviewing(false);
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
					{game.phase === "over"
						? <button className="btn btn-ghost btn-sm" onClick={() => setReviewing(false)}>← Back to Results</button>
						: <button className="btn btn-ghost btn-sm" onClick={goToMenu}>← Menu</button>}
					<span className="game-nav-title">Spender{game.phase === "over" ? " — Review" : ""}</span>
					{game.phase === "over"
						? <span style={{ width: 64 }} />
						: <button className="btn btn-danger btn-sm" onClick={() => setConfirmAbandon(true)}>Abandon</button>}
				</div>
				<div className="game-nav-spacer" />
				<div className="game">
					<div className="game-main">

						<div className="action-bar">
							<span className={`turn-badge ${game.phase === "over" ? "theirs" : myTurn ? "mine" : "theirs"}`}>
								{game.phase === "over" ? "Game Over" : myTurn ? "Your Turn" : `${displayName(roomData?.players?.[game.turn])}'s Turn`}
							</span>
							{roomData?.ai_variant && (
								<span className="ai-variant-badge">{aiPersona(roomData.ai_variant)}</span>
							)}
							{authUser?.is_admin && roomData?.ai_variant && roomData?.ai_card_values && (
								<button className="btn btn-ghost btn-sm ai-vals-toggle" title="Admin: show/hide the AI's per-card value overlay"
									onClick={() => setShowAiVals(v => {
										const n = !v;
										try { localStorage.setItem("spender_show_ai_vals", n ? "1" : "0"); } catch {}
										return n;
									})}>
									{showAiVals ? "Hide AI values" : "Show AI values"}
								</button>
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
									<div className="board-actions-btns">
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
							{game.phase !== "over" && <span className="target-label">Target: {game.win_points || 15}</span>}
							<div className="actions-panel-btns">
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
									{(game.moves || []).length === 0 && <div className="log-empty">No moves yet</div>}
									{(game.moves || []).map((mv, i) => {
										const { name, action, card } = formatLogMove(mv);
										return (
											<div key={i} className={`log-entry${card ? " clickable" : ""}`}
												onClick={card ? () => setModalCard(card) : undefined}>
												<span className="log-name">{name}</span>
												<span className="log-action">{action}</span>
											</div>
										);
									})}
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
