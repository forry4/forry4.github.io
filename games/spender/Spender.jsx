import { useState, useEffect, useRef, useCallback } from "react";
import CastlesOfCrimson from "../castles_of_crimson/CastlesOfCrimson.jsx";
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
];

// ─── Constants ─────────────────────────────────────────────────────────────
const GEM_COLORS = ["white", "blue", "green", "red", "black"];
const GEM_LABELS = { white: "Diamond", blue: "Sapphire", green: "Emerald", red: "Ruby", black: "Onyx", gold: "Gold" };
const GEM_HEX = { white: "#ddd4be", blue: "#4257ff", green: "#3f9c2e", red: "#dc4040", black: "#15151a", gold: "#f5c842" };

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
.loading-logo{font-family:'Cinzel',serif;font-size:3rem;font-weight:700;color:var(--gold);letter-spacing:.06em}
.loading-sub{color:var(--text-dim);font-style:italic;font-size:.95rem}
.loading-bar-wrap{width:220px;height:5px;background:var(--surface2);border-radius:3px;overflow:hidden;border:1px solid var(--border)}
.loading-bar{height:100%;background:var(--gold);border-radius:3px;transition:width .4s ease}
.loading-hint{color:var(--text-muted);font-size:.78rem;font-style:italic}

/* ─── Auth ──────────────────────────────────────────────────────────────── */
.auth-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:32px 20px;background:var(--bg)}
.auth-logo{font-family:'Cinzel',serif;font-size:3rem;font-weight:700;color:var(--gold);letter-spacing:.06em;margin-bottom:4px}
.auth-tagline{color:var(--text-dim);font-style:italic;font-size:1.05rem;margin-bottom:32px}
.auth-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px 28px 24px;width:100%;max-width:400px}
.auth-tabs{display:flex;border-bottom:1px solid var(--border);margin-bottom:22px}
.auth-tab{flex:1;padding:10px 0;background:transparent;border:none;border-bottom:2px solid transparent;color:var(--text-dim);cursor:pointer;font-family:'Cinzel',serif;font-size:.78rem;letter-spacing:.1em;text-transform:uppercase;margin-bottom:-1px;transition:all .15s}
.auth-tab.active{color:var(--gold);border-bottom-color:var(--gold)}
.auth-tab:hover:not(.active){color:var(--text)}
.auth-field{width:100%;padding:11px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Crimson Pro',Georgia,serif;font-size:1rem;letter-spacing:normal;outline:none;margin-bottom:10px}
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
.home-logo{font-family:'Cinzel',serif;font-size:clamp(2.4rem,8vw,3.6rem);font-weight:700;color:var(--gold);letter-spacing:.06em;line-height:1.1}
.home-tagline{color:var(--text-dim);font-style:italic;font-size:1.1rem;margin-top:10px}
.home-games{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px}
.home-game-card{position:relative;text-align:left;font-family:inherit;color:inherit;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:26px 22px 24px;cursor:pointer;transition:border-color .15s,transform .15s,background .15s}
.home-game-card:hover{border-color:var(--gold);transform:translateY(-2px);background:var(--surface2)}
.home-game-card.soon{opacity:.9}
.home-game-name{font-family:'Cinzel',serif;font-size:1.32rem;font-weight:600;color:var(--gold);letter-spacing:.03em;margin-bottom:8px}
.home-game-desc{color:var(--text-dim);font-size:.95rem;line-height:1.45;font-style:italic}
.home-game-badge{position:absolute;top:14px;right:14px;font-family:'Cinzel',serif;font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;padding:3px 9px;border-radius:10px}
.home-game-badge.ready{color:var(--green-gem);border:1px solid rgba(84,194,61,.5)}
.home-game-badge.soon{color:var(--text-muted);border:1px solid var(--border)}

/* ─── Browser ───────────────────────────────────────────────────────────── */
.browser{max-width:820px;margin:0 auto;padding:0 20px 48px}
.browser-header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:36px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.browser-head-left{display:flex;align-items:center;gap:14px;min-width:0}
.browser-title{font-family:'Cinzel',serif;font-size:2rem;font-weight:700;color:var(--gold);letter-spacing:.04em}
.browser-user{display:flex;align-items:center;gap:10px}
.browser-username{font-family:'Cinzel',serif;font-size:.8rem;color:var(--text-dim);letter-spacing:.06em;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.browser-guest-badge{font-size:.65rem;letter-spacing:.1em;color:var(--text-muted);border:1px solid var(--border);padding:2px 7px;border-radius:10px;font-family:'Cinzel',serif;text-transform:uppercase}
.browser-create{margin-bottom:36px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.btn-outline.active{background:var(--gold);color:#0f0e0c}
.ai-picker-wrap{position:relative;display:inline-flex}
.ai-picker{position:absolute;top:calc(100% + 8px);left:0;z-index:30;display:flex;gap:8px;align-items:center;flex-wrap:wrap;max-width:min(92vw,420px);padding:12px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:0 10px 28px rgba(0,0,0,.5)}
.ai-picker-label{font-family:'Cinzel',serif;font-size:.72rem;letter-spacing:.06em;color:var(--text-dim);text-transform:uppercase;margin-right:4px}
.browser-section{margin-bottom:32px}
.section-hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.section-title{font-family:'Cinzel',serif;font-size:.7rem;letter-spacing:.18em;color:var(--gold);text-transform:uppercase}
.game-cards{display:flex;flex-direction:column;gap:8px}
.game-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;display:flex;align-items:center;gap:14px;transition:border-color .15s}
.game-card:hover{border-color:rgba(201,168,76,.4)}
.game-card-info{flex:1;min-width:0}
.game-card-title{font-family:'Cinzel',serif;font-size:.88rem;letter-spacing:.04em;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.game-card-meta{font-size:.78rem;color:var(--text-dim)}
.game-card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}
.your-turn-badge{background:var(--gold);color:#0f0e0c;padding:3px 10px;border-radius:12px;font-family:'Cinzel',serif;font-size:.63rem;letter-spacing:.12em;font-weight:700;text-transform:uppercase;white-space:nowrap}
.playing-badge{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border);padding:3px 10px;border-radius:12px;font-family:'Cinzel',serif;font-size:.63rem;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.empty-state{text-align:center;padding:28px 16px;color:var(--text-dim);font-style:italic;font-size:.9rem;background:var(--surface2);border-radius:var(--radius);border:1px dashed var(--border)}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.refresh-btn{background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:.9rem;padding:2px 6px;border-radius:4px;transition:color .15s}
.refresh-btn:hover{color:var(--gold)}

/* ─── Waiting ───────────────────────────────────────────────────────────── */
.waiting-screen{max-width:480px;margin:0 auto;padding:48px 20px 24px;text-align:center}
.waiting-title{font-family:'Cinzel',serif;font-size:1.1rem;color:var(--gold);margin-bottom:6px;letter-spacing:.1em}
.waiting-sub{color:var(--text-dim);font-size:.85rem;margin-bottom:24px}
.room-code-box{font-family:'Cinzel',serif;font-size:2.2rem;letter-spacing:.3em;color:var(--gold-light);text-align:center;padding:18px;background:var(--surface2);border-radius:var(--radius);margin-bottom:20px;border:1px solid var(--border);cursor:pointer;transition:border-color .15s}
.room-code-box:hover{border-color:var(--gold)}
.player-list{list-style:none;margin:0 0 20px}
.player-list li{display:flex;align-items:center;gap:8px;padding:9px 14px;background:var(--surface2);border-radius:var(--radius);margin-bottom:6px;font-family:'Cinzel',serif;font-size:.82rem;letter-spacing:.05em}
.player-list li.me{border:1px solid var(--gold);color:var(--gold)}
.copy-hint{font-size:.75rem;color:var(--text-muted);font-style:italic;margin-bottom:12px}

/* ─── Game layout ───────────────────────────────────────────────────────── */
.game{display:grid;grid-template-columns:1fr 272px;gap:12px;padding:10px;flex:1;min-height:0}
@media(max-width:900px){.game{grid-template-columns:1fr}}
.game-main{display:flex;flex-direction:column;gap:10px}
.game-sidebar{display:flex;flex-direction:column;gap:10px}
@media(max-width:900px){.game-sidebar{order:-1}}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px}
.panel-title{font-family:'Cinzel',serif;font-size:.68rem;letter-spacing:.14em;color:var(--gold);margin-bottom:10px;text-transform:uppercase}

/* ─── Bank ──────────────────────────────────────────────────────────────── */
.bank-gems{display:flex;gap:8px;flex-wrap:wrap}
.gem-stack{display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;transition:transform .12s;user-select:none}
.gem-stack:hover .gem-token{transform:scale(1.08)}
.gem-stack.selected .gem-token{box-shadow:0 0 0 2px var(--gold-light),0 0 12px rgba(232,201,106,.3)}
.gem-stack.disabled{opacity:.35;cursor:not-allowed}
.gem-stack.reserve-ready .gem-token{box-shadow:0 0 0 2px var(--gold-light),0 0 14px rgba(232,201,106,.6);animation:reserve-pulse 1.1s ease-in-out infinite}
@keyframes reserve-pulse{0%,100%{box-shadow:0 0 0 2px var(--gold-light),0 0 8px rgba(232,201,106,.45)}50%{box-shadow:0 0 0 2px var(--gold-light),0 0 18px rgba(232,201,106,.85)}}
.gem-token{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Cinzel',serif;font-weight:700;font-size:.95rem;border:2px solid rgba(255,255,255,.12);transition:all .12s}
.gem-count{font-size:.75rem;color:var(--text-dim);font-family:'Cinzel',serif}

/* ─── Cards ─────────────────────────────────────────────────────────────── */
/* overflow-x:auto clips both axes, which would cut off the hover lift / top border
   and the selection outline of the first & last items (flush at the clip edges).
   Padding on all sides + matching -margin gives clip-room without moving the row. */
.level-row{display:flex;gap:8px;align-items:flex-start;flex-wrap:nowrap;overflow-x:auto;padding:6px 4px 4px;margin:-6px -4px 0}
.level-row::-webkit-scrollbar{height:4px}.level-row::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.deck-pile{width:88px;min-height:120px;border-radius:var(--radius);border:1px dashed var(--border);display:flex;align-items:center;justify-content:center;font-family:'Cinzel',serif;font-size:.68rem;color:var(--text-dim);cursor:pointer;flex-shrink:0;background:var(--surface2);transition:all .12s;flex-direction:column;gap:4px}
.deck-pile:hover{border-color:var(--gold);color:var(--gold)}
.deck-pile.selected{border-color:var(--gold-light);color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.deck-pile.disabled{cursor:not-allowed;opacity:.5}
.deck-remaining{font-size:1.3rem;font-weight:700;color:var(--text);font-family:'Cinzel',serif}
.card{width:88px;min-height:120px;border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:8px 6px 6px;display:flex;flex-direction:column;cursor:pointer;transition:all .15s;flex-shrink:0;position:relative}
.ai-val{position:absolute;bottom:5px;right:5px;font-family:'Cinzel',serif;font-size:.62rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.4);border-radius:4px;padding:0 4px;line-height:1.4;pointer-events:none}
.ai-vals{position:absolute;bottom:3px;right:3px;display:grid;grid-template-columns:auto auto;gap:0 5px;font-family:'Cinzel',serif;font-size:.5rem;font-weight:600;color:#e8c86a;background:rgba(0,0,0,.5);border-radius:4px;padding:2px 4px;line-height:1.4;pointer-events:none}
.ai-vals b{color:#9a8fb0;font-weight:700;margin-right:1px}
.card:hover{border-color:rgba(201,168,76,.5);transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.4)}
.card.selected{border-color:var(--gold-light);box-shadow:0 0 0 2px var(--gold-light)}
.card.affordable{border-color:var(--green-gem)}
.card.affordable-gold{border-color:var(--gold-light)}
.card.disabled{cursor:not-allowed;opacity:.6}
.card-back{cursor:default;align-items:center;justify-content:center;gap:8px;border-style:dashed;background:repeating-linear-gradient(45deg,var(--surface2),var(--surface2) 6px,var(--surface) 6px,var(--surface) 12px)}
.card-back:hover{transform:none;border-color:var(--border);box-shadow:none}
.card-back-level{font-family:'Cinzel',serif;font-weight:700;font-size:1.3rem;color:var(--text-dim)}
.card-back-label{font-family:'Cinzel',serif;font-size:.55rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase}
.card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.card-points{font-family:'Cinzel',serif;font-weight:700;font-size:1.1rem;color:var(--gold);min-width:16px}
.card-points.zero{color:transparent}
.card-bonus{width:20px;height:20px;border-radius:50%;flex-shrink:0;border:1.5px solid rgba(255,255,255,.25)}
.card-cost{display:flex;flex-direction:column;gap:3px;margin-top:auto}
.cost-row{display:flex;align-items:center;gap:4px}
.cost-gem{width:10px;height:10px;border-radius:50%;flex-shrink:0;border:1px solid rgba(255,255,255,.25)}
.cost-num{font-family:'Cinzel',serif;font-size:.7rem;color:var(--text-dim)}

/* ─── Nobles ────────────────────────────────────────────────────────────── */
.nobles-row{display:flex;gap:8px;flex-wrap:wrap}
.noble{width:72px;min-height:72px;border-radius:var(--radius);background:var(--surface2);border:1px solid var(--border);padding:6px;display:flex;flex-direction:column;align-items:center;gap:4px}
.noble-points{font-family:'Cinzel',serif;font-size:1rem;font-weight:700;color:var(--gold)}
.noble-req{display:flex;flex-direction:column;gap:2px;width:100%}
.noble-req-row{display:flex;gap:3px;align-items:center;font-size:.65rem;color:var(--text-dim);font-family:'Cinzel',serif}

/* ─── Action bar ────────────────────────────────────────────────────────── */
.action-bar{display:flex;gap:8px;align-items:center;flex-wrap:nowrap;padding:10px 14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);box-sizing:border-box;min-height:62px}
.action-hint{flex:1;font-style:italic;color:var(--text-dim);font-size:.88rem;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.action-bar-btns{display:flex;gap:8px;align-items:center;flex-shrink:0;min-width:150px;justify-content:flex-end}
.action-bar-spacer{visibility:hidden;pointer-events:none;transition:none}
.turn-badge{font-family:'Cinzel',serif;font-size:.72rem;letter-spacing:.08em;padding:4px 12px;border-radius:20px;white-space:nowrap}
.turn-badge.mine{background:var(--gold);color:#0f0e0c}
.turn-badge.theirs{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
.ai-variant-badge{font-family:'Cinzel',serif;font-size:.6rem;letter-spacing:.1em;padding:2px 8px;border-radius:20px;background:var(--surface2);color:var(--text-dim);border:1px solid var(--border);white-space:nowrap}
.gap-8{display:flex;gap:8px;flex-wrap:wrap}

/* ─── Player panels ─────────────────────────────────────────────────────── */
.players-area{display:flex;flex-direction:column;gap:8px}
.player-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px;transition:border-color .2s}
/* the active player's box gets a clean gold rounded border (the only highlight);
   your own box is identified by the active dot + "(you)" label, no extra accent. */
.player-panel.active-turn{border-color:var(--gold);background:var(--surface3)}
.player-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.player-name-row{display:flex;align-items:center;gap:6px}
.player-name{font-family:'Cinzel',serif;font-size:.8rem;letter-spacing:.06em}
.active-dot{width:6px;height:6px;border-radius:50%;background:var(--gold);flex-shrink:0;animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.player-score{font-family:'Cinzel',serif;font-size:1.1rem;font-weight:700;color:var(--gold)}
.player-tokens{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}
.token-pill{display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:12px;font-family:'Cinzel',serif;font-size:.7rem;font-weight:700}
.player-bonuses{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;margin-bottom:6px}
.bonus-pill{display:flex;align-items:center;gap:3px;padding:2px 7px;border-radius:12px;font-family:'Cinzel',serif;font-size:.7rem;font-weight:700;border:1px solid}
.reserved-label{font-size:.62rem;color:var(--text-dim);font-family:'Cinzel',serif;letter-spacing:.06em;margin-bottom:4px;text-transform:uppercase}
.reserved-row{display:flex;gap:4px;flex-wrap:wrap}
.gem-total{display:inline-block;font-size:.66rem;color:var(--text);font-family:'Cinzel',serif;font-weight:600;letter-spacing:.03em;margin-top:3px;background:var(--surface3);border:1.5px solid #7a6e58;padding:1px 8px;border-radius:8px;box-shadow:0 0 0 1px rgba(0,0,0,.5)}

/* ─── Winner ────────────────────────────────────────────────────────────── */
.winner-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:32px}
.winner-title{font-family:'Cinzel',serif;font-size:3rem;color:var(--gold);margin-bottom:8px;letter-spacing:.04em}
.winner-sub{color:var(--text-dim);font-style:italic;margin-bottom:32px}
.final-scores{display:flex;flex-direction:column;gap:8px;margin-bottom:32px}
.score-row{font-family:'Cinzel',serif;font-size:1.05rem;padding:10px 28px;background:var(--surface);border-radius:var(--radius);border:1px solid var(--border)}
.score-row.winner{border-color:var(--gold);color:var(--gold)}

/* ─── Move log ──────────────────────────────────────────────────────────── */
.move-log{display:flex;flex-direction:column;gap:0;max-height:200px;overflow-y:auto;overflow-x:hidden}
.move-log::-webkit-scrollbar{width:3px}.move-log::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.log-entry{display:flex;gap:6px;align-items:baseline;font-size:.76rem;color:var(--text-dim);padding:4px 0;line-height:1.4;animation:log-in .2s ease}
.log-entry+.log-entry{border-top:1px solid rgba(58,52,42,.4)}
.log-entry:first-child{color:var(--text)}
.log-entry.clickable{cursor:pointer}
.log-entry.clickable:hover{background:rgba(201,168,76,.08);border-radius:4px}
.log-name{font-family:'Cinzel',serif;font-size:.7rem;color:var(--gold-light);flex-shrink:0}
.log-action{flex:1}
@keyframes log-in{from{opacity:0;transform:translateX(6px)}to{opacity:1;transform:none}}

/* ─── Card animations ───────────────────────────────────────────────────── */
@keyframes card-appear{from{opacity:0;transform:scale(.82) translateY(-6px)}to{opacity:1;transform:none}}
.card{animation:card-appear .22s ease}

/* ─── Gem flash ─────────────────────────────────────────────────────────── */
@keyframes gem-pop{0%,100%{transform:scale(1)}45%{transform:scale(1.3)}}
.gem-stack.flashing .gem-token{animation:gem-pop .38s ease}

/* ─── AI thinking dots ──────────────────────────────────────────────────── */
.ai-thinking{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;color:var(--text-muted);font-style:italic}
.think-dot{width:5px;height:5px;border-radius:50%;background:var(--text-muted);animation:think-blink .9s ease-in-out infinite}
.think-dot:nth-child(2){animation-delay:.2s}.think-dot:nth-child(3){animation-delay:.4s}
@keyframes think-blink{0%,100%{opacity:.25;transform:scale(.7)}50%{opacity:1;transform:scale(1.2)}}

/* ─── Toast ─────────────────────────────────────────────────────────────── */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--surface);border:1px solid var(--gold);padding:10px 20px;border-radius:var(--radius);font-family:'Cinzel',serif;font-size:.8rem;color:var(--gold);z-index:999;pointer-events:none;animation:fadeup .3s ease;white-space:nowrap}
@keyframes fadeup{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}

/* ─── Discard modal ─────────────────────────────────────────────────────── */
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.8);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px;max-width:400px;width:90%}
.modal h3{font-family:'Cinzel',serif;color:var(--gold);margin-bottom:8px}
.modal p{color:var(--text-dim);font-size:.9rem;margin-bottom:16px}
.discard-gems{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-bottom:16px}
.discard-btn{padding:8px 16px;border-radius:var(--radius);border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;font-family:'Cinzel',serif;font-size:.82rem;transition:all .12s;display:flex;align-items:center;gap:6px}
.discard-btn:hover{border-color:var(--gold);color:var(--gold)}
.discard-count{text-align:center;font-family:'Cinzel',serif;color:var(--text-dim);font-size:.85rem}

/* ─── Error/status ──────────────────────────────────────────────────────── */
.error-msg{font-size:.88rem;color:var(--red-gem);text-align:center;padding:6px 0}
.status-msg{font-size:.85rem;color:var(--text-dim);font-style:italic;text-align:center;padding:6px 0;display:flex;align-items:center;justify-content:center}
.small-muted{font-size:.8rem;color:var(--text-muted)}
.mt-8{margin-top:8px}.mt-12{margin-top:12px}

/* ─── Game nav bar ──────────────────────────────────────────────────────── */
.game-nav{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;padding-top:calc(env(safe-area-inset-top,0px) + 8px);border-bottom:1px solid var(--border);background:var(--surface);position:fixed;top:0;left:0;right:0;z-index:50}
.game-nav-spacer{height:calc(env(safe-area-inset-top,0px) + 48px);flex-shrink:0}
.game-nav-title{font-family:'Cinzel',serif;font-size:.72rem;letter-spacing:.16em;color:var(--gold);text-transform:uppercase}

@media(max-width:600px){
  .browser{padding:0 14px 40px}
  .browser-title{font-size:1.6rem}
  .game{padding:6px}
  .game-card{padding:10px 12px}
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

function CardView({ card, selected, affordable, needsGold, disabled, onClick, compact, aiValue }) {
	// An opponent's blind deck-top reserve is hidden info — show a face-down back, not the card.
	if (card.hidden) {
		return (
			<div className="card card-back" style={{ width: compact ? 72 : 88, minHeight: compact ? 96 : 120 }}>
				<span className="card-back-level">{["I", "II", "III"][(card.level || 1) - 1]}</span>
				<span className="card-back-label">Reserved</span>
			</div>
		);
	}
	return (
		<div
			className={`card${selected ? " selected" : ""}${affordable ? (needsGold ? " affordable-gold" : " affordable") : ""}${disabled ? " disabled" : ""}`}
			style={{ width: compact ? 72 : 88, minHeight: compact ? 96 : 120 }}
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

function NobleView({ noble, claimedBy }) {
	return (
		<div className="noble" style={claimedBy ? { opacity: 0.5, position: "relative" } : undefined}>
			<span className="noble-points">{noble.points}</span>
			<div className="noble-req">
				{Object.entries(noble.req).map(([c, n]) => (
					<div key={c} className="noble-req-row">
						<div style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[c], border: "1px solid rgba(255,255,255,.12)" }} />
						<span>{n}</span>
					</div>
				))}
			</div>
			{claimedBy && (
				<div style={{ fontSize: ".55rem", color: "var(--gold)", fontFamily: "'Cinzel',serif", letterSpacing: ".04em", marginTop: 2 }}>
					★ {claimedBy}
				</div>
			)}
		</div>
	);
}

// ─── useWebSocket ─────────────────────────────────────────────────────────

function useWebSocket(onMessage, { onOpen, onClose } = {}) {
	const wsRef = useRef(null);
	const [connected, setConnected] = useState(false);
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
			setConnected(true);
			try { onOpenRef.current?.({ event: ev, send }); } catch {}
		};
		ws.onclose = () => {
			setConnected(false);
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
		setConnected(false);
	}, []);

	// reconnect when the tab becomes visible (iOS kills sockets in the background)
	const getReadyState = useCallback(() => wsRef.current?.readyState ?? WebSocket.CLOSED, []);

	return { connected, connect, send, disconnect, getReadyState };
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

	const [selectedGems, setSelectedGems] = useState([]);
	const [selectedCard, setSelectedCard] = useState(null);
	const [reserveArmed, setReserveArmed] = useState(false);  // gold-first reserve: click gold, then a card
	const [toast, setToast] = useState("");
	const [confirmAbandon, setConfirmAbandon] = useState(false);
	const [reviewing, setReviewing] = useState(false);  // end-game: viewing final board + log
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
	const [myGames, setMyGames] = useState([]);
	const [browserLoading, setBrowserLoading] = useState(false);
	const [showAiPicker, setShowAiPicker] = useState(false);

	const playerName = authUser?.name || "";

	// ── fetchGames ─────────────────────────────────────────────────────────
	const fetchGames = useCallback(async (user) => {
		setBrowserLoading(true);
		try {
			const openP = fetch(`${HTTP_BASE}/games`).then(r => r.json()).catch(() => ({ games: [] }));
			const mineP = (user && !user.guest && user.session_token)
				? fetch(`${HTTP_BASE}/games/mine?token=${user.session_token}`).then(r => r.json()).catch(() => ({ games: [] }))
				: Promise.resolve({ games: [] });
			const [open, mine] = await Promise.all([openP, mineP]);
			setOpenGames(open.games || []);
			setMyGames(mine.games || []);
		} catch {
			setOpenGames([]); setMyGames([]);
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
			if (msg.message === "invalid token") {
				try { localStorage.removeItem("spender_roomId"); } catch {}
			}
			setToast(msg.message);
		}
	}, [myId, screen, roomId]);

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
	useEffect(() => {
		const handleVisibility = () => {
			if (document.visibilityState === "visible"
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
				const res = await fetch(`${HTTP_BASE}/auth/session?token=${encodeURIComponent(stored.session_token)}`,
					{ signal: ctrl.signal });
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
							setTimeout(() => { if (!cancelled) setScreen(dest); }, 350);
							return;
						}
					} catch {}
					if (!cancelled) await new Promise(r => setTimeout(r, 2000));
				}
			})();
		};
		// Fast path: if backend responds within 250ms, skip the loading screen entirely
		(async () => {
			try {
				const ctrl = new AbortController();
				const t = setTimeout(() => ctrl.abort(), 250);
				const res = await fetch(`${HTTP_BASE}/games`, { signal: ctrl.signal });
				clearTimeout(t);
				if (res.ok && !cancelled) { const dest = await resolveDest(); if (!cancelled) setScreen(dest); return; }
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

	// ── Move log helpers ──────────────────────────────────────────────────────
	function formatLogMove(mv) {
		const isMe = mv.pid === myId;
		const name = isMe ? "You" : (roomData?.players?.[mv.pid] || mv.pid.slice(0, 6));
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
		if (mv.type === "buy") {
			const col = mv.card?.bonus || mv.card?.color;
			const dot = col
				? <span style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[col], border: "1px solid rgba(255,255,255,.12)", display: "inline-block", marginLeft: 2, marginRight: 2, verticalAlign: "middle" }} />
				: null;
			return { name, action: <span>bought{dot}card{mv.card?.points ? ` +${mv.card.points}pts` : ""}</span>, card: mv.card?.cost ? mv.card : null };
		}
		if (mv.type === "reserve") {
			const col = mv.card?.bonus || mv.card?.color;
			const dot = col
				? <span style={{ width: 8, height: 8, borderRadius: "50%", background: GEM_HEX[col], border: "1px solid rgba(255,255,255,.12)", display: "inline-block", marginLeft: 2, marginRight: 2, verticalAlign: "middle" }} />
				: null;
			return { name, action: <span>reserved{dot}card</span>, card: mv.card?.cost ? mv.card : null };
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
	const handleCreate = (vsAI = false, aiVariant = "A") => {
		const newRoomId = roomCode();
		setRoomId(newRoomId);
		try { localStorage.setItem("spender_roomId", newRoomId); } catch {}
		pendingActionRef.current = vsAI
			? { action: "create", name: playerName, vs_ai: true, ai_variant: aiVariant }
			: { action: "create", name: playerName };
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
			if (authUser?.session_token) params.set("token", authUser.session_token);
			const res = await fetch(`${HTTP_BASE}/games/${gameId}/cancel?${params}`, { method: "POST" });
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
		if (!card) return <div style={{ width: 88, minHeight: 120 }} />;
		// readonly: opponent's reserved cards — visible but not selectable/affordable.
		const affordable = !opts.readonly && me && canAfford(card.cost, me.tokens, myBonuses);
		const needsGold = affordable && goldToAfford(card.cost, me.tokens, myBonuses) > 0;
		const isSelected = !opts.readonly && selectedCard?.card?.id === card.id;
		return (
			<CardView key={card.id} card={card}
				selected={isSelected}
				affordable={affordable && myTurn}
				needsGold={needsGold && myTurn}
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
		const name = roomData?.players?.[pid] || pid.slice(0, 6);
		const bonuses = bonusesFrom(p.purchased);
		const score = totalPoints(p.purchased, p.nobles);
		const isMe = pid === myId;
		const isActive = game?.turn === pid;
		return (
			<div key={pid} className={`player-panel${isMe ? " me" : ""}${isActive ? " active-turn" : ""}`}>
				<div className="player-header">
					<div className="player-name-row">
						{isActive && <span className="active-dot" />}
						<span className="player-name">{name}{isMe ? " (you)" : ""}</span>
					</div>
					<span className="player-score">{score} pts</span>
				</div>
				<div className="player-tokens">
					{[...GEM_COLORS, "gold"].map(c => (p.tokens[c] || 0) > 0 && (
						<span key={c} className="token-pill" style={{ background: GEM_HEX[c] + "55", border: `1px solid ${c === "black" ? "rgba(255,255,255,.4)" : GEM_HEX[c]}` }}>
							{/* light rim so the near-black onyx gem stays visible on the warm "your turn" (surface3) panel */}
							<span style={{ width: 10, height: 10, borderRadius: "50%", background: GEM_HEX[c], border: c === "black" ? "1px solid rgba(255,255,255,.4)" : "1px solid rgba(255,255,255,.25)", display: "inline-block" }} />
							{p.tokens[c]}
						</span>
					))}
				</div>
				{Object.values(p.tokens).some(v => v > 0) && (
					<div className="gem-total">{gemTotal(p.tokens)} gems</div>
				)}
				<div className="player-bonuses">
					{GEM_COLORS.map(c => (bonuses[c] || 0) > 0 && (
						<span key={c} className="bonus-pill" style={{ background: GEM_HEX[c] + "55", borderColor: c === "black" ? "rgba(255,255,255,.4)" : GEM_HEX[c], color: c === "black" ? "#a8a8a8" : GEM_HEX[c] }}>+{bonuses[c]} {c[0].toUpperCase()}</span>
					))}
					{p.nobles.map(n => (
						<span key={n.id} className="bonus-pill" style={{ borderColor: "var(--gold)", color: "var(--gold)" }}>★{n.points}</span>
					))}
				</div>
				{p.reserved?.length > 0 && (
					<>
						<div className="reserved-label">Reserved ({p.reserved.length}/3)</div>
						<div className="reserved-row">{p.reserved.map(c => renderCard(c, { source: "reserved", readonly: !isMe }))}</div>
					</>
				)}
			</div>
		);
	}

	function getHint() {
		if (!myTurn) return `Waiting for ${roomData?.players?.[game?.turn] || "opponent"}…`;
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
								onChange={e => setAuthName(e.target.value)} maxLength={20}
								onKeyDown={e => e.key === "Enter" && handleAuth()} />
							<input className="auth-field" placeholder="Password" type="password" value={authPassword}
								onChange={e => setAuthPassword(e.target.value)} maxLength={64}
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

	// Game browser screen
	if (screen === "browser") return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="browser">
					<div className="browser-header">
						<div className="browser-head-left">
							<button className="btn btn-ghost btn-sm" onClick={() => setScreen("home")}>
								← {SITE_NAME}
							</button>
							<div className="browser-title">Spender</div>
						</div>
						<div className="browser-user">
							{authUser?.guest && <span className="browser-guest-badge">Guest</span>}
							<span className="browser-username">{authUser?.name}</span>
						</div>
					</div>

					<div className="browser-create">
						<button className="btn btn-gold" onClick={() => handleCreate(false)}>
							+ Create New Game
						</button>
						<div className="ai-picker-wrap">
							<button className={`btn btn-outline${showAiPicker ? " active" : ""}`}
								onClick={() => setShowAiPicker(v => !v)}>
								Play vs AI {showAiPicker ? "▴" : "▾"}
							</button>
							{showAiPicker && (
								<div className="ai-picker">
									<span className="ai-picker-label">Choose AI opponent</span>
									{["A", "B", "C", "C2", "Z", "H", "H2", "H3", "S"].map(v => (
										<button key={v} className="btn btn-outline btn-sm"
											onClick={() => { setShowAiPicker(false); handleCreate(true, v); }}>
											AI {v}
										</button>
									))}
								</div>
							)}
						</div>
						<button className="refresh-btn" title="Refresh" onClick={() => fetchGames(authUser)}>
							{browserLoading ? <span className="spinner" /> : "↻"}
						</button>
					</div>

					{(() => {
						const savedId = (() => { try { return localStorage.getItem("spender_roomId"); } catch { return null; } })();
						const savedToken = savedId ? (() => { try { return localStorage.getItem(`spender_token_${savedId}_${myId}`); } catch { return null; } })() : null;
						const alreadyInMyGames = myGames.some(g => g.id === savedId);
						if (!savedId || !savedToken || alreadyInMyGames) return null;
						return (
							<div className="browser-section">
								<div className="section-hd">
									<span className="section-title">Resume</span>
								</div>
								<div className="game-cards">
									<div className="game-card" style={{ borderColor: "rgba(201,168,76,.4)" }}>
										<div className="game-card-info">
											<div className="game-card-title">Game in progress</div>
											<div className="game-card-meta">{savedId}</div>
										</div>
										<div className="game-card-actions">
											<button className="btn btn-gold btn-sm" onClick={() => handleContinue(savedId)}>
												Resume
											</button>
										</div>
									</div>
								</div>
							</div>
						);
					})()}

					{myGames.length > 0 && (
						<div className="browser-section">
							<div className="section-hd">
								<span className="section-title">Your Games</span>
								<span className="small-muted">{myGames.length} active</span>
							</div>
							<div className="game-cards">
								{myGames.map(g => (
									<div key={g.id} className="game-card">
										<div className="game-card-info">
											<div className="game-card-title">
												{g.you_are_p1 ? `${g.player1_name} (you)` : g.player1_name}
												{" vs "}
												{g.player2_name
													? (g.you_are_p1 ? g.player2_name : `${g.player2_name} (you)`)
													: "waiting for opponent…"}
											</div>
											<div className="game-card-meta">
												{g.id} · {timeAgo(g.updated_at)}
											</div>
										</div>
										<div className="game-card-actions">
											{g.status === "playing" && (
												g.your_turn
													? <span className="your-turn-badge">Your Turn</span>
													: <span className="playing-badge">Their Turn</span>
											)}
											<button className="btn btn-outline btn-sm"
												onClick={() => handleContinue(g.id)}>
												{g.status === "open" ? "Return" : "Resume"}
											</button>
										</div>
									</div>
								))}
							</div>
						</div>
					)}

					<div className="browser-section">
						<div className="section-hd">
							<span className="section-title">Open Games</span>
							<span className="small-muted">waiting for a second player</span>
						</div>
						{browserLoading && openGames.length === 0 ? (
							<div className="empty-state"><span className="spinner" />Loading…</div>
						) : openGames.length === 0 ? (
							<div className="empty-state">No open games right now. Create one!</div>
						) : (
							<div className="game-cards">
								{openGames.map(g => (
									<div key={g.id} className="game-card">
										<div className="game-card-info">
											<div className="game-card-title">
												{g.host_id === myId ? "Your game" : `${g.host_name}'s game`}
											</div>
											<div className="game-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
										</div>
										<div className="game-card-actions">
											{g.host_id === myId
												? <button className="btn btn-ghost btn-sm" onClick={() => handleCancel(g.id)}>
													Cancel
												</button>
												: <button className="btn btn-gold btn-sm" onClick={() => handleJoinGame(g.id)}>
													Join
												</button>}
										</div>
									</div>
								))}
							</div>
						)}
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
					<p className="waiting-sub">Share this code with your opponent</p>
					<div className="room-code-box" title="Click to copy"
						onClick={() => { navigator.clipboard?.writeText(roomId); setToast("Copied!"); }}>
						{roomId}
					</div>
					<p className="copy-hint">tap code to copy</p>

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
							Start Game
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

	// Winner screen
	if (screen === "game" && game?.phase === "over" && !reviewing) {
		const winners = Array.isArray(game.winner) ? game.winner : [game.winner];
		const isTie = winners.length > 1;
		const winnerNames = winners.map(w => roomData?.players?.[w] || w).join(" & ");
		return (
			<>
				<style>{css}</style>
				<div className="app">
					<div className="winner-screen">
						<div className="winner-title">{isTie ? "Draw!" : "Victory!"}</div>
						<p className="winner-sub">{isTie ? `${winnerNames} share the gem trade` : `${winnerNames} claims the gem trade`}</p>
						<div className="final-scores">
							{(game.order || []).map(pid => {
								const score = totalPoints(game.players?.[pid]?.purchased || [], game.players?.[pid]?.nobles || []);
								const name = roomData?.players?.[pid] || pid.slice(0, 6);
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
			<div className="app">
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
								{game.phase === "over" ? "Game Over" : myTurn ? "Your Turn" : `${roomData?.players?.[game.turn]}'s Turn`}
							</span>
							{roomData?.ai_variant && (
								<span className="ai-variant-badge">AI {roomData.ai_variant}</span>
							)}
							{authUser?.is_admin && roomData?.ai_variant && roomData?.ai_card_values && (
								<button className="btn btn-ghost btn-sm" title="Admin: show/hide the AI's per-card value overlay"
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
									: <span className="action-hint">{getHint()}</span>
							}
							<div className="action-bar-btns">
								{myTurn && selectedGems.length > 0 ? (
									<>
										<button className="btn btn-gold" onClick={handleTakeGems}>
											Take {selectedGems.length}
										</button>
										<button className="btn btn-ghost" onClick={() => setSelectedGems([])}>✕</button>
									</>
								) : myTurn && selectedCard?.source === "deck" ? (
									<>
										{me?.reserved?.length >= 3 &&
											<span style={{ color: "var(--text-muted)", fontSize: ".82rem" }}>Reserved slots full</span>
										}
										<button className="btn btn-ghost" onClick={() => setSelectedCard(null)}>✕</button>
									</>
								) : myTurn && selectedCard && selectedCard.source !== "deck" ? (() => {
									const affordable = canAfford(selectedCard.card.cost, me?.tokens || emptyGems(), myBonuses);
									return (
										<>
											{affordable && <button className="btn btn-gold" onClick={() => handleBuy(selectedCard.card)}>Buy</button>}
											<button className="btn btn-ghost" onClick={() => setSelectedCard(null)}>✕</button>
										</>
									);
								})() : (
									<button className="btn btn-ghost action-bar-spacer" aria-hidden="true" tabIndex={-1}>{"✕"}</button>
								)}
							</div>
						</div>

						<div className="panel">
							<div className="panel-title">Gem Bank</div>
							<div className="bank-gems">
								{[...GEM_COLORS, "gold"].map(c => {
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
										<div key={c}
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

						{["L3", "L2", "L1"].map((lk, i) => (
							<div key={lk} className="panel">
								<div className="level-row">
									<div className={`deck-pile${!myTurn ? " disabled" : ""}${reserveArmed ? " reserve-ready" : ""}${selectedCard?.source === "deck" && selectedCard?.deckLevel === 3 - i ? " selected" : ""}`}
										onClick={() => {
											if (!myTurn) return;
											if (reserveArmed && (me?.reserved?.length || 0) < 3) { handleReserve(null, 3 - i); return; }
											setSelectedGems([]); setReserveArmed(false);
											setSelectedCard(s => s?.source === "deck" && s?.deckLevel === 3 - i ? null : { source: "deck", deckLevel: 3 - i });
										}}
										title="Reserve blind from deck">
										<span style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text)", lineHeight: 1 }}>{["III","II","I"][i]}</span>
										<span style={{ fontSize: ".62rem", letterSpacing: ".08em" }}>DECK</span>
										<span className="deck-remaining">{game.decks?.[lk]?.length || 0}</span>
									</div>
									{(game.board?.[lk] || []).map((c, j) => c ? renderCard(c) : <div key={j} style={{ width: 88 }} />)}
								</div>
							</div>
						))}

						<div className="panel">
							<div className="panel-title">Nobles</div>
							<div className="nobles-row">
								{(game.nobles || []).map(n => <NobleView key={n.id} noble={n} />)}
								{/* In review, also show nobles that were claimed so the board is the full original set. */}
								{game.phase === "over" && (game.order || []).flatMap(pid =>
									(game.players?.[pid]?.nobles || []).map(n => (
										<NobleView key={n.id} noble={n}
											claimedBy={(roomData?.players?.[pid] || pid.slice(0, 6)) + (pid === myId ? " (you)" : "")} />
									))
								)}
							</div>
						</div>
					</div>

					<div className="game-sidebar">
						{(game.moves?.length > 0) && (
							<div className="panel">
								<div className="panel-title">Recent Moves</div>
								<div className="move-log">
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
