import { fetchGameHistory, SESSION_EXPIRED, latestSession } from "../../shared/lobbyHistory.js";
import { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense } from "react";

// The other games are CODE-SPLIT. Statically importing them put all four games plus
// Books into one ~600KB chunk that every visitor downloaded just to see the home
// menu — Vite warned about the chunk size on every build. Each is a self-contained
// default-export component mounted at exactly one branch below, so lazy() is a
// clean fit: its chunk is fetched when you actually open that game.
//
// STALE TAB AFTER A DEPLOY — the failure mode code-splitting introduces, and the
// reason for the wrapper below. Chunk filenames carry a content hash, and GitHub
// Pages does not keep the old ones. A tab left open across a deploy still holds the
// PREVIOUS index chunk, so opening a game asks for e.g. SpenderDuel-<oldhash>.js,
// gets a 404, and React surfaces "TypeError: Importing a module script failed" in the
// error boundary. Before the split this could not happen: everything arrived in one
// chunk at page load, and a stale tab simply kept running the old build.
//
// So: retry once (covers a transient network blip), then reload the page — which
// fetches a fresh index.html with the CURRENT hashes and lands the user where they
// were. The sessionStorage guard means a genuinely missing chunk reloads only once
// and then shows the real error, instead of looping forever.
// The guard is a TIMESTAMP, not a boolean. A boolean has to be cleared somewhere for a
// tab that survives two deploys to heal twice — and clearing it on successful load
// re-arms it immediately after the reload, which loops forever (measured: 284
// navigations). A cooldown needs no reset: a second deploy minutes later is outside the
// window and heals, while a chunk that is genuinely gone reloads once and then reports.
const RELOADED_KEY = "spender_chunk_reloaded_at";
const RELOAD_COOLDOWN_MS = 30_000;
const lazyChunk = (name, importer) => lazy(() => importer().catch(() => importer()).catch((err) => {
	let last = 0;
	try { last = Number(sessionStorage.getItem(RELOADED_KEY)) || 0; } catch { /* private mode */ }
	if (Date.now() - last > RELOAD_COOLDOWN_MS) {
		try { sessionStorage.setItem(RELOADED_KEY, String(Date.now())); } catch {}
		console.warn(`[chunk] ${name} failed to load (stale build?) — reloading once`);
		window.location.reload();
		return new Promise(() => {});   // never settles; the reload takes over
	}
	console.error(`[chunk] ${name} still failing after a reload — surfacing the error`);
	throw err;
}));

const CastlesOfCrimson = lazyChunk("CastlesOfCrimson", () => import("../castles_of_crimson/CastlesOfCrimson.jsx"));
const WhereWolf = lazyChunk("WhereWolf", () => import("../wherewolf/WhereWolf.jsx"));
const SpenderDuel = lazyChunk("SpenderDuel", () => import("../spender_duel/SpenderDuel.jsx"));
const Dontminion = lazyChunk("Dontminion", () => import("../dontminion/Dontminion.jsx"));
const Dissonance = lazyChunk("Dissonance", () => import("../dissonance/Dissonance.jsx"));
const RagTag = lazyChunk("RagTag", () => import("../rag_tag/RagTag.jsx"));
const Orbit = lazyChunk("Orbit", () => import("../orbit/Orbit.jsx"));
const BlackCastle = lazyChunk("BlackCastle", () => import("../black_castle/BlackCastle.jsx"));
const SecretNames = lazyChunk("SecretNames", () => import("../secretnames/SecretNames.jsx"));
const Pinch = lazyChunk("Pinch", () => import("../pinch/Pinch.jsx"));
const Books = lazyChunk("Books", () => import("../../books/Books.jsx"));
const Notes = lazyChunk("Notes", () => import("../../notes/Notes.jsx"));
const BggFilter = lazyChunk("BggFilter", () => import("../../bggfilter/BggFilter.jsx"));

// Shown while a game's chunk loads. Deliberately an empty full-height panel in the
// site's dark background: each game injects its OWN stylesheet when it mounts, so
// there is no shared CSS to rely on here, and painting nothing avoids a flash of
// un-themed white and any layout shift when the real screen arrives.
const GameChunkLoading = () => (
	<div style={{ minHeight: "100vh", background: "#120c0d" }} />
);
import { baseCss } from "../../shared/theme.js";
import { lobbyCss, LobbyHeader, LobbyLoading, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame,
	useLastDifficulty,
	LobbyBotTier,
	createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss, LobbyHero, LobbyUser,
	RulesModal, rulesModalCss,
	useProgressiveList, LobbySectionHd, LobbyOpenTitle, LobbyTabs, TurnBadge, LobbyMatchup, LobbyAction, useListFade,
	WaitingRoom, waitingRoomCss, LobbyOpenActions, seatStateOf } from "../../shared/lobby.jsx";
import SpenderRules from "./rules.jsx";
import { GemToken, CardView, GEM_COLORS, GEM_LABELS, GEM_HEX,
	splendorPanelCss, splendorCardCss, splendorCardExtraCss, splendorPillCss,
	splendorLogCss } from "../../shared/splendor.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
// Site-shell screens, extracted out of this file (see shared/AuthScreen.jsx).
import AuthScreen from "../../shared/AuthScreen.jsx";
import { leaveOpenSeat, readRoomToken } from "../../shared/roomLifecycle.js";
import HomeScreen, { SITE_NAME, GAMES, HERO_RULE } from "../../shared/HomeScreen.jsx";
import SiteHealth, { useUnackedAlerts } from "../../shared/SiteHealth.jsx";
// The home card and Spender's own lobby must be the same colour; see shared/accents.js.
import { GAME_ACCENTS } from "../../shared/accents.js";
// Offline vs-AI: the local game driver (wasm engine + IndexedDB saves) — see offline.js.
import { OFFLINE_AI_PID, createOfflineGame, loadOfflineGame, deleteOfflineGame,
	listOfflineGames, offlineRoomData, applyOfflineMove } from "./offline.js";
// CoC's offline driver: the hub creates its records; the CoC component plays them.
import { createOfflineCocGame, COC_BOARD_NAMES } from "../castles_of_crimson/offline.js";
// Duel's offline driver: same split — the hub creates, SpenderDuel plays.
import { createOfflineDuelGame } from "../spender_duel/offline.js";
// Dissonance's offline driver: the hub creates the record, the Dissonance
// component plays it. Its referee is `classic.rs` in the same wasm the search
// pool uses -- see games/dissonance/offline.js.
import { createOfflineDissonanceGame } from "../dissonance/offline.js";
// Dissonance's PAPER SCORECARD, in the offline hub. EAGER, not a lazy chunk,
// and that is the whole point of it being here: a lazy chunk is only cached
// once it has been fetched, so a card meant for a table with no signal would
// be missing exactly when it is wanted. The entry chunk is fetched on every
// load and cache-first in the service worker, so this rides along for ~6KB.
// It carries its own stylesheet (bidpad.css + scorecard.css) and needs no
// room, no board and no network — `catalog` is optional and pricing.js
// falls back to the shipped classic list.
import DissonanceScorecard from "../dissonance/scorecard.jsx";

// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _cssText from "./Spender.css?inline";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

// ─── Site identity ─────────────────────────────────────────────────────────
// Registry of games shown on the home menu. Add future games here — each tile
// routes to its own `screen`. `status: "ready"` is playable; "soon" shows a
// Coming Soon placeholder. Spender's lobby is its "browser" spenderScreen.

// URL path segment 1 ↔ shell screen (shared/router.js). Always translate through these
// tables — GAMES[].id ≠ path for wherewolf; Spender is one site-level screen now.
// The shell owns segment 1; each sub-game owns its own segment 2 (room id). The Spender
// Spender's own waiting/game map to "spender" (or "puzzles" while puzzling) in applyPopRoute.
const SCREEN_FOR_MODE = { spender: "spender", coc: "coc", werewolf: "werewolf", duel: "duel", dontminion: "dontminion", dissonance: "dissonance", ragtag: "ragtag", orbit: "orbit", blackcastle: "blackcastle", secretnames: "secretnames", pinch: "pinch", books: "books", notes: "notes", puzzles: "puzzles", bggfilter: "bggfilter", offline: "offline" };
const MODE_FOR_SCREEN = { home: "home", spender: "spender", coc: "coc", werewolf: "werewolf", duel: "duel", dontminion: "dontminion", dissonance: "dissonance", ragtag: "ragtag", orbit: "orbit", blackcastle: "blackcastle", secretnames: "secretnames", pinch: "pinch", books: "books", notes: "notes", puzzles: "puzzles", bggfilter: "bggfilter", offline: "offline" };

// Per-game emblem — inline SVG tinted via currentColor (=the card's --accent), so no
// raster asset / CDN (keeps the self-hosted, no-CLS constraint). Small motifs that read
// the game: cut gem / castle gate / crescent moon / crown.

// ─── Constants ─────────────────────────────────────────────────────────────
// GEM_COLORS / GEM_LABELS / GEM_HEX now come from shared/splendor.jsx (imported
// above) so Spender and Spender Duel can't drift apart on the palette.
// Frontend-only display names for the AI variants (wire codes stay H2/H3/S).
const AI_PERSONAS = { H2: "Henry", H3: "Herald", S: "Steve", N: "Nina" };
const AI_TIERS = { H2: "easy", H3: "medium", S: "hard", N: "expert" };
// The variants the create modal OFFERS, weakest first — the pill row is built
// from this, and it is what a remembered last-played variant is validated
// against (a retired code must not restore as a live selection).
const AI_VARIANTS = ["H2", "H3", "S", "N"];
const aiPersona = (v) => AI_PERSONAS[v] || `AI ${v}`;         // variant code -> persona name (retired codes -> "AI <code>")
const aiTierLabel = (v) => (AI_TIERS[v] || "").replace(/^./, (c) => c.toUpperCase());  // "expert" -> "Expert"
// variant code -> the TIER the lobby rows print (`LobbyBotTier`). The persona is
// the bot's name and is already in the matchup ("Nina (AI)"); what the row was
// missing is the strength, and a retired code keeps its raw letter rather than
// rendering an empty chip beside a game that really was played against it.
const AI_TIER_LABELS = Object.fromEntries(
	Object.keys(AI_TIERS).map((v) => [v, aiTierLabel(v)]));
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
const css = baseCss + lobbyCss + _cssText
	+ splendorPanelCss + `

/* ─── Bank ──────────────────────────────────────────────────────────────── */
.bank-gems{display:flex;gap:8px;flex-wrap:wrap}
/* Desktop: the three level boxes sit in a column with the same 10px gap they had
   as direct game-main children; the board-actions (mobile button group beside the
   nobles) is hidden because the controls live in the action bar. Mobile below. */
.levels{display:flex;flex-direction:column;gap:10px}
.board-actions{display:none}
`
	+ splendorCardCss + splendorCardExtraCss + `

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
.player-panel{background:linear-gradient(180deg,rgba(255,255,255,.03),transparent 46%),var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 2px 10px -4px rgba(0,0,0,.5);transition:border-color .2s}
/* the active player's box gets a clean gold rounded border (the only highlight);
   your own box is identified by the active dot + "(you)" label, no extra accent. */
.player-panel.active-turn{border-color:var(--gold);background:linear-gradient(180deg,rgba(255,255,255,.04),transparent 46%),var(--surface3);box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 0 0 1px rgba(201,168,76,.28),0 3px 16px -4px rgba(201,168,76,.22),0 2px 10px -4px rgba(0,0,0,.5)}
/* an opponent's box is tappable to ping them — signal it (your own box has no click). */
.player-panel.pingable{cursor:pointer}
.player-panel.pingable:active{border-color:var(--gold)}
.player-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.player-name-row{display:flex;align-items:center;gap:6px}
.player-name{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem;letter-spacing:.06em}
.active-dot{width:6px;height:6px;border-radius:50%;background:var(--gold);flex-shrink:0;animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.player-score{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.1rem;font-weight:700;color:var(--gold)}
`
	+ splendorPillCss + `
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

`
	+ splendorLogCss + `
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
.fly-gem{position:fixed;animation:flyGem .55s cubic-bezier(.3,.7,.4,1) both;will-change:transform,opacity}
.fly-card{position:fixed;border-radius:8px;background:var(--surface2);border:2px solid var(--border);box-shadow:0 6px 20px rgba(0,0,0,.6);display:flex;align-items:flex-start;justify-content:space-between;padding:6px 8px;overflow:hidden;transform-origin:center;animation:fly .5s ease both;will-change:transform,opacity}
.fly-card-pt{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:var(--gold);font-size:1.3rem;line-height:1}
.fly-card-dot{width:18px;height:18px;border-radius:50%;border:1px solid rgba(255,255,255,.3);flex-shrink:0}
@keyframes fly{from{transform:translate(0,0) scale(var(--s0));opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1));opacity:.5}}
/* Gems fly the real gradient GemToken (like Duel): slower Duel easing + a deeper fade. */
@keyframes flyGem{from{transform:translate(0,0) scale(var(--s0));opacity:1}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1));opacity:.15}}

/* ─── AI thinking dots ──────────────────────────────────────────────────── */
.ai-thinking{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;color:var(--text-muted);font-style:italic}
.think-dot{width:5px;height:5px;border-radius:50%;background:var(--text-muted);animation:think-blink .9s ease-in-out infinite}
.think-dot:nth-child(2){animation-delay:.2s}.think-dot:nth-child(3){animation-delay:.4s}
@keyframes think-blink{0%,100%{opacity:.25;transform:scale(.7)}50%{opacity:1;transform:scale(1.2)}}

/* ─── Toast ─────────────────────────────────────────────────────────────── */
/* nowrap + no max-width meant a long message ran off both edges of a phone — and it is
   pointer-events:none, so there is nothing to scroll it back. It wraps and centres now,
   inside the safe area, and it sits on the same plate treatment as everything else. */
.toast{position:fixed;bottom:calc(env(safe-area-inset-bottom,0px) + 24px);left:50%;transform:translateX(-50%);
  max-width:min(30rem,calc(100vw - 32px));text-align:center;text-wrap:balance;line-height:1.4;
  background:linear-gradient(158deg,#272319,#1d1a15);border:1px solid var(--gold);
  box-shadow:inset 0 1px 0 rgba(255,240,215,.08),0 10px 26px -14px rgba(0,0,0,1);
  padding:10px 20px;border-radius:var(--radius);font-family:'Cinzel','Cinzel Fallback',serif;
  font-size:.8rem;color:var(--gold-light);z-index:999;pointer-events:none;animation:fadeup .3s ease}
@keyframes fadeup{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
@media(prefers-reduced-motion:reduce){.toast{animation:none}}

/* ─── Discard modal ─────────────────────────────────────────────────────── */
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.8);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px;max-width:400px;width:90%}
.modal h3{font-family:'Cinzel','Cinzel Fallback',serif;color:var(--gold);margin-bottom:8px}
.modal p{color:var(--text-dim);font-size:.9rem;margin-bottom:16px}
/* The how-to-play modal is the SHARED kit now (rulesModalCss / .rl-*) — Spender's
   own .rules-modal/.rules-body vocabulary was retired with it. */
.discard-gems{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-bottom:16px}
.discard-btn{padding:8px 16px;border-radius:var(--radius);border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;transition:all .12s;display:flex;align-items:center;gap:6px}
.discard-btn:hover{border-color:var(--gold);color:var(--gold)}
.discard-count{text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;color:var(--text-dim);font-size:.85rem}

/* ─── Error/status ──────────────────────────────────────────────────────── */
.error-msg{font-size:.88rem;color:var(--red-gem);text-align:center;padding:6px 0}
.status-msg{font-size:.85rem;color:var(--text-dim);font-style:italic;text-align:center;padding:6px 0;display:flex;align-items:center;justify-content:center}
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
  .actions-panel-btns{display:flex;flex-wrap:wrap;gap:calc(var(--card-h) * 0.054);align-items:center;justify-content:flex-end;flex-shrink:0;min-width:0}
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
  /* .browser PADS NOTHING. The lobby's gutter is .lby-page-in's, shared by all seven
     games, and this 14px stacked on top of it -- so Spender's phone cards sat 14px
     right of every other game's on the same screen, and 14px right of its own Back
     button. .lby-header's phone padding is in the shared sheet now and the copy here
     said the same thing twice.
     NO BACKTICKS IN THIS BLOCK. It is still CSS inside a JS TEMPLATE LITERAL -- the
     one region of this file the .css extraction did not reach -- so a single stray
     backtick reparses the rest of the file as a tagged template. Written with them,
     this comment failed the build outright (esbuild: Unexpected "in"), which is the
     lucky version of that footgun; the shipped version blanks the page. */
  .browser{padding:0}
  .game{padding:6px}
  /* NO CARD PADDING OVERRIDE. This tightened the row 3px on every side, which made
     Spender's phone cards 12px shorter than the identical card in the other six games
     -- and Spender is the lobby the shared kit was EXTRACTED from, so it was the one
     screen quietly disagreeing with the rule it had set. The shared padding is right
     at this width too. */

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

  /* ── Puzzle mode ─────────────────────────────────────────────── */
  .puzzle-top{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)}
  .puzzle-top-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.2rem;color:var(--gold)}
  .puzzle-picker{max-width:760px;margin:0 auto;padding:22px 16px}
  .puzzle-intro{text-align:center;opacity:.82;margin:0 0 20px;line-height:1.5}
  .puzzle-empty{text-align:center;opacity:.6;padding:40px 0}
  .puzzle-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
  .puzzle-card{text-align:left;font-family:inherit;color:inherit;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px 18px;cursor:pointer;transition:border-color .15s,transform .15s,background .15s}
  .puzzle-card:hover{border-color:var(--gold);transform:translateY(-2px);background:var(--surface2)}
  .puzzle-card-title{font-weight:700;margin-bottom:5px}
  .puzzle-card-meta{font-size:.84rem;opacity:.7}
  .action-hint.puzzle-wrong{color:#e0696b;font-weight:600}
  .puzzle-won{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(8,6,7,.72);z-index:60}
  .puzzle-won-card{background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:30px 36px;text-align:center;max-width:340px}
  .puzzle-won-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;color:var(--gold);margin-bottom:8px}
  .puzzle-won-sub{opacity:.85;margin-bottom:20px}
  .puzzle-won-btns{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
  .puzzle-fail{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(30,6,8,.74);z-index:60;animation:puzfailin .18s ease}
  @keyframes puzfailin{from{opacity:0}to{opacity:1}}
  .puzzle-fail-card{background:var(--surface);border:1px solid #e0696b;border-radius:var(--radius-lg);padding:30px 36px;text-align:center;max-width:360px}
  .puzzle-fail-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;color:#e0696b;margin-bottom:8px}
  .puzzle-fail-sub{opacity:.85;margin-bottom:20px;line-height:1.45}
  .puzzle-nav-aids{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
  .puzzle-hint-word{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.5rem;color:var(--gold);font-weight:700;margin:10px 0 16px}
  .puzzle-answer-list{margin:6px 0 10px;padding-left:22px;line-height:1.7}
  .puzzle-answer-note{font-size:.8rem;opacity:.7;margin:0 0 14px}
  .puzzle-card-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:5px}
  .puzzle-diff{font-size:.66rem;letter-spacing:.06em;text-transform:uppercase;padding:2px 7px;border-radius:10px;border:1px solid var(--border);opacity:.9;white-space:nowrap}
  .diff-easy{color:#7fc08a;border-color:#3f6a48}
  .diff-tricky{color:#d8b25a;border-color:#6a5a2f}
  .diff-hard{color:#e0696b;border-color:#6a3536}
` + gameMenuCss + createModalCss + lobbyCreateRowCss + rulesModalCss + waitingRoomCss;

// ─── Sub-components ───────────────────────────────────────────────────────

// GemToken and CardView live in shared/splendor.jsx (imported above) — Spender Duel
// renders the same gems and jewel cards from that one source, instead of the
// lookalikes it used to carry. CardView's Duel-only props (crowns, pearls, wild
// bonus, ability glyph) are optional; Spender passes none and renders as before.

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
			// Stale-socket guard (the frontend analog of the backend's): if a newer connect() has
			// already replaced this socket, do nothing. Without it, a socket closed BY connect()
			// (e.g. the visibility handler firing while a reconnect is mid-handshake) fires this
			// onclose AFTER wsRef points at the new socket, schedules a reconnect, and that reconnect
			// then closes the healthy new socket — a self-sustaining ~2s disconnect/reconnect loop.
			if (wsRef.current !== ws) return;
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
	const [authNotice, setAuthNotice] = useState("");
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
	// SITE-LEVEL mode only: loading | auth | home | spender | coc | werewolf | duel |
	// books | puzzles. `screen` used to ALSO carry Spender's own browser/waiting/game,
	// conflating "which part of the site am I in" with "which Spender screen" — which is
	// what made the shell impossible to lift out of this file. Spender's own screen now
	// lives in `spenderScreen` and is only meaningful while screen === "spender".
	const [screen, setScreen] = useState("loading");
	// The owner's Site health panel: its unread-alert count badges the Home tile, and
	// is re-read each time Home shows so it is never an hour stale.
	const [siteAlerts, refreshSiteAlerts] = useUnackedAlerts(authUser);
	const [siteHealthOpen, setSiteHealthOpen] = useState(false);
	useEffect(() => { if (screen === "home") refreshSiteAlerts(); }, [screen, refreshSiteAlerts]);
	const [spenderScreen, setSpenderScreen] = useState("browser");   // browser | waiting | game
	// a room connect is in flight (create / join / continue / deep-link) — while it
	// is AND we're still on the lobby, show the spinner instead of the lobby, so a
	// reconnect doesn't flash the lobby then snap into the game (matches CoC).
	const [connecting, setConnecting] = useState(false);

	// Enter one of Spender's own screens. Always sets BOTH, so the two can never drift
	// (a bare setSpenderScreen while the site is on, say, /coc would render nothing).
	// NOTE: a puzzle also runs on "game" — with puzzling=true and no socket.
	const goSpender = (sub) => { setScreen("spender"); setSpenderScreen(sub); };
	const [loadingProgress, setLoadingProgress] = useState(0);
	const [showLoading, setShowLoading] = useState(false);
	// Bumped when the tab is foregrounded while still stuck on the loading screen, to
	// re-kick the loading effect with a fresh fetch (a fetch started during a
	// background/freeze transition can hang with its abort timer throttled).
	const [loadingKick, setLoadingKick] = useState(0);
	const [modalCard, setModalCard] = useState(null);
	const [roomId, setRoomId] = useState("");
	const [roomData, setRoomData] = useState(null);
	// A Spender room id arriving from the URL (deep link / popstate Forward) — consumed by
	// the deep-entry effect once the browser (lobby) screen is up. Plain /spender never
	// sets it, preserving the deliberate no-auto-resume-on-mount design.
	const [deepRoom, setDeepRoom] = useState(null);
	// ── Game review / replay (read-only rewind of a finished game) ──
	const [reviewing, setReviewing] = useState(false);            // viewing a finished game's board + log
	const [replaySnapshots, setReplaySnapshots] = useState(null); // [{turn,mover,move,game}], or null = no turn-by-turn
	const [replayTurn, setReplayTurn] = useState(null);           // which past turn drives the board; null = final
	// ── Puzzle mode (scripted endgame: find the unique winning line vs S) ──
	const [puzzling, setPuzzling] = useState(false);     // in a puzzle (drives the game screen, no socket)
	const [puzzle, setPuzzle] = useState(null);          // the loaded puzzle file
	const [puzHeroPid, setPuzHeroPid] = useState(null);  // the hero's pid in the puzzle's own labeling
	const [puzStep, setPuzStep] = useState(0);           // index of the next step to resolve
	const [puzAttempts, setPuzAttempts] = useState(1);   // 1-based attempt counter
	const [puzFeedback, setPuzFeedback] = useState("");  // "S: ..." reply line / wrong-move message
	const [puzWrong, setPuzWrong] = useState(false);     // last move was wrong (just restarted)
	const [puzSolved, setPuzSolved] = useState(false);   // reached the winning final position
	const [puzList, setPuzList] = useState(null);        // the /puzzles listing for the picker (null = not loaded)
	const [puzHintOpen, setPuzHintOpen] = useState(false); // hint popup: the answer's CATEGORY only (buy/reserve/take)
	const [puzHistory, setPuzHistory] = useState([]);    // back-stack of visited puzzle ids (so an accidental Next isn't a dead end)
	const [puzAnswerOpen, setPuzAnswerOpen] = useState(false); // the "show the full solution" modal
	const [puzFailed, setPuzFailed] = useState(false);   // a wrong move was made -> explicit FAIL overlay
	const [puzHideOverlay, setPuzHideOverlay] = useState(false); // Return -> view the board, hide the result overlay
	const [puzFailMove, setPuzFailMove] = useState(null);          // the wrong move the player just tried
	const [pinged, setPinged] = useState(false);                  // a ping arrived while the tab was hidden (drives the "waiting for you" tab alert)
	// ── Offline vs-AI mode (local wasm engine, no socket, IndexedDB saves) ──
	const [offline, setOffline] = useState(false);       // an offline SPENDER game drives the game screen (like puzzling)
	const [offlineRecord, setOfflineRecord] = useState(null);   // the saved-game record (offline.js shape)
	const [offlineGames, setOfflineGames] = useState(null);     // hub list (null = loading)
	const [offlineGameSel, setOfflineGameSel] = useState("spender"); // hub New Game: which game
	const [offlineVariant, setOfflineVariant] = useState("N");  // Spender tier — only the
	const [offlineWin, setOfflineWin] = useState(15);           //   client-WASM tiers exist offline
	const [offlineCocTier, setOfflineCocTier] = useState("expert"); // CoC tier (hard|expert)
	const [offlineCocMyBoard, setOfflineCocMyBoard] = useState("1");  // CoC board picks
	const [offlineCocOppBoard, setOfflineCocOppBoard] = useState("1");
	const [offlineDuelTier, setOfflineDuelTier] = useState("expert"); // Duel tier (hard|expert)
	// A CoC/Duel offline game in play: the shell mounts that game's component with this
	// record (they own their whole screen, unlike Spender whose game screen lives here).
	const [offlinePlay, setOfflinePlay] = useState(null);
	// Per-game download state: {spender|coc|duel: null | {done,total} | "ok" | "err"}
	const [precacheState, setPrecacheState] = useState({});
	// Dissonance's paper scorecard, opened from the hub (see the import).
	const [offlineCard, setOfflineCard] = useState(false);

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
	// A genuine human-vs-human game — the ONLY context where another player can be waiting on you.
	// Excludes vs-AI games (game.ai_player set), puzzles (puzzle set, no opponent), and review.
	const humanGame = !reviewing && !!game && !game.ai_player && !puzzle;
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
	const [resultReady, setResultReady] = useState(false);  // gate the win/loss screen until 0.5s after game ends
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

	// ── Browser state ──────────────────────────────────────────────────────
	const [openGames, setOpenGames] = useState(() => readLobbyCache("spender", myId, "open", []));
	const [activeGames, setActiveGames] = useState(() => readLobbyCache("spender", myId, "active", []));   // ALL in-progress games (yours + others')
	const [historyGames, setHistoryGames] = useState(() => readLobbyCache("spender", myId, "history", [])); // your FINISHED games (vs AI or humans)
	// History reveals 10 at a time as the reader reaches the end of the list, up
	// to the 50 the backend sends — see useProgressiveList.
	const [historyShown, historyMore] = useProgressiveList(historyGames);
	// A column that scrolls inside itself must say so — see `useListFade`.
	useListFade();
	const [browserLoading, setBrowserLoading] = useState(false);
	const [showCreateModal, setShowCreateModal] = useState(false);  // the New Game options modal
	const [createOpp, setCreateOpp] = useState("ai");        // "friend" | "ai"
	// AI difficulty (wire code) — defaults to the last variant this player
	// actually started a game against, falling back to Nina for a first game.
	const [createVariant, setCreateVariant, rememberVariant] =
		useLastDifficulty("spender", myId, AI_VARIANTS, "N");
	const [createSeats, setCreateSeats] = useState(2);       // friend-lobby seat cap (2-4)
	const [showRules, setShowRules] = useState(false);  // lobby "How to Play" modal
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
				? fetchGameHistory(`${HTTP_BASE}/games/history`, user).catch(() => null)
				: Promise.resolve({ games: [] });
			const [open, active, hist] = await Promise.all([openP, activeP, histP]);
			const og = open.games || [], ag = active.games || [], hg = hist?.games;
			setOpenGames(og); setActiveGames(ag);
			if (hg) {
				setHistoryGames(hg);
				writeLobbyCache("spender", myId, "history", hg);
			}
			writeLobbyCache("spender", myId, "open", og);
			writeLobbyCache("spender", myId, "active", ag);
		} catch {
			setOpenGames([]); setActiveGames([]);
		}
		setBrowserLoading(false);
	}, [myId]);

	// ── handleMessage ──────────────────────────────────────────────────────
	const handleMessage = useCallback((msg) => {
		setConnecting(false);        // any authoritative reply ends the connect loader
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
		// Entering a room (server-confirmed, never at click time) gives it its URL —
		// /spender/<RID>. waiting and game share the one room URL (status picks the
		// internal screen); pushPath's dedup makes deep-link/repeat messages no-ops.
		if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
			const rid = room?.room_id || roomId;
			if (rid) pushPath(buildPath("spender", rid));
			urlAttemptRef.current = null;
		}
		if (msg.type === "created") {
			setRoomData(msg.room);
			if (inGame(msg.room?.status)) goSpender("game");
			else goSpender("waiting");
		} else if (msg.type === "joined") {
			setRoomData(msg.room);
			if (inGame(msg.room?.status)) goSpender("game");
			else goSpender("waiting");
		} else if (msg.type === "reconnected") {
			setRoomData(msg.room);
			if (inGame(msg.room.status)) goSpender("game");
			else goSpender("waiting");
		} else if (msg.type === "room_update") {
			setRoomData(msg.room);
			if (inGame(msg.room.status) && spenderScreen !== "game") goSpender("game");
		} else if (msg.type === "ping") {
			// Another player tapped your player box (or you tapped theirs) → chime.
			playPing();
			// If you're on another tab, also raise the "waiting for you" tab indicator.
			if (document.hidden) setPinged(true);
		} else if (msg.type === "error") {
			// "unknown action" is only ever emitted by the server's final dispatch else — a client/
			// backend VERSION SKEW (e.g. a new client sends an action a not-yet-deployed backend lacks,
			// like client_ai_hidden during a deploy window). Never user-actionable → swallow it silently.
			if (msg.message === "unknown action") return;
			// A join into a cancelled/gone game (the backend rejects it now instead of
			// fabricating a hostless room): clear the stale pointer + refresh the list
			// so the dead game disappears.
			const gone = typeof msg.message === "string"
				&& (msg.message.includes("no longer available") || msg.message === "room not found");
			if (msg.message === "invalid token" || gone) {
				try { localStorage.removeItem("spender_roomId"); } catch {}
			}
			// URL-driven attempt (deep link / popstate Forward) failed. A stale token gets
			// ONE retry as a plain join (the invite-link case: token orphaned but the room
			// is open); anything else falls back to the lobby and the dead room URL is
			// replaced with /spender so a reload doesn't re-attempt it.
			const ua = urlAttemptRef.current;
			if (ua) {
				if (msg.message === "invalid token" && !ua.retried) {
					ua.retried = true;
					try { localStorage.removeItem(`spender_token_${ua.rid}_${myId}`); } catch {}
					handleContinue(ua.rid);   // token now gone → plain join
					return;
				}
				urlAttemptRef.current = null;
				replacePath(buildPath("spender"));
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

	// ── Mount: do NOT auto-resume a saved game ─────────────────────────────
	// Auto-reconnecting on load snapped you from the home/lobby straight into the game
	// (the async "reconnected"/"room_update" forced goSpender("game")) — jarring. Resume
	// is now EXPLICIT via the lobby's Resume/Continue buttons (handleContinue connects +
	// enters). Keep only the disconnect cleanup so an explicit connection tears down on
	// unmount.
	useEffect(() => {
		return () => disconnect();
	}, []); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Reconnect when tab becomes visible (iOS kills WS in background) ────
	const roomIdRef = useRef(roomId);
	roomIdRef.current = roomId;
	const screenRef = useRef(screen);
	screenRef.current = screen;
	const spenderScreenRef = useRef(spenderScreen);
	spenderScreenRef.current = spenderScreen;
	const reviewingRef = useRef(reviewing);
	reviewingRef.current = reviewing;
	// A puzzle drives the "game" screen with roomId set to the puzzle id but NO socket
	// (it's a local scripted line). Without this ref the visibility reconnect below would
	// fire during a puzzle and open a bogus WS to a room named after the puzzle, whose
	// server reply replaces roomData and wipes the puzzle board.
	const puzzlingRef = useRef(puzzling);
	puzzlingRef.current = puzzling;
	// An offline game also drives the "game" screen with NO socket (roomId = the local save
	// id) — same reasons as puzzlingRef: the visibility reconnect must never open a WS to a
	// room named after a local save, and popstate must treat it as its own site-level mode.
	const offlineRef = useRef(offline);
	offlineRef.current = offline;
	const offlineRecordRef = useRef(offlineRecord);
	offlineRecordRef.current = offlineRecord;
	const offlinePlayRef = useRef(offlinePlay);
	offlinePlayRef.current = offlinePlay;
	// Fresh-closure mirror for the AI-dispatch effect's offline fork (the effect's deps are
	// tuned for the online path; a ref keeps the fork from widening them).
	const submitOfflineAiMoveRef = useRef(null);

	// ── URL routing (shared/router.js) ─────────────────────────────────────
	// Segment 1 (game mode) is owned HERE; each sub-game owns its own segment 2 (room id).
	const initialRouteRef = useRef(parsePath());   // parsed once at first render; landAt consumes it
	const pendingRouteRef = useRef(null);          // deep link stashed across the auth screen
	const applyPopRouteRef = useRef(() => {});     // fresh-closure mirror for the mount-once popstate effect
	// A URL-driven room attempt in flight ({rid, retried}): its failure falls back to the
	// lobby (replacePath /spender + toast) instead of leaving a dead room URL; a stale
	// reconnect token is retried ONCE as a plain join (invite-link case).
	const urlAttemptRef = useRef(null);
	useEffect(() => subscribe((route) => {
		// Back/Forward. While still booting, just retarget the landing; while on auth,
		// retarget the post-login destination. Otherwise apply the route now.
		if (screenRef.current === "loading") { initialRouteRef.current = route; return; }
		if (screenRef.current === "auth") { pendingRouteRef.current = route.game && route.game !== "home" ? route : null; return; }
		applyPopRouteRef.current(route);
	}), []); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		const handleVisibility = () => {
			// Only auto-reconnect when actively on the game screen — otherwise tabbing
			// back would dump a lobby/waiting user into a stale waiting room. Never while
			// reviewing a finished game or playing a puzzle (neither has a live socket —
			// a reconnect would be spurious and, in a puzzle, clobbers the board).
			if (document.visibilityState === "visible"
				&& screenRef.current === "spender" && spenderScreenRef.current === "game"
				&& !reviewingRef.current
				&& !puzzlingRef.current
				&& !offlineRef.current
				&& roomIdRef.current
				&& getReadyState() !== WebSocket.OPEN) {
				connect(`${WS_BASE}/${roomIdRef.current}/${myId}`);
			}
			// If the tab was reloaded/frozen and we're still stuck on the loading
			// screen, re-fire the load now that we're actually foreground — the
			// backgrounded fetch may be hung with its abort timer throttled.
			if (document.visibilityState === "visible" && screenRef.current === "loading") {
				setLoadingKick(k => k + 1);
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
	const CLIENT_AI_BUDGET_MS = 4500;     // slow-device time ceiling
	const CLIENT_AI_MAX_SIMS_TOTAL = 10000; // AGGREGATE sims/move across the whole pool (visits are summed).
	                                        // Split evenly per worker at dispatch (perWorker = ceil(TOTAL/pool)).
	                                        // ~1 node/sim → also bounds tree memory; slow devices hit the time
	                                        // budget first. wwsd is NOT capped this way (own MAX_SIMS knob).
	const wasmPoolRef = useRef(null);          // [{ ready, request, terminate }] — RPC-wrapped workers
	const [wasmReady, setWasmReady] = useState(false);
	const clientAiArmedRef = useRef(null);     // room_id we've announced capability for
	const aiDispatchPlyRef = useRef(-1);       // ply we've already dispatched a search for

	useEffect(() => {
		if (!["S", "N"].includes(roomData?.ai_variant) || wasmPoolRef.current || typeof Worker === "undefined") return;
		const url = `${import.meta.env.BASE_URL}wasm/spender-worker.js`;
		// Reserve one core for the browser's main/compositor/raster threads: the WASM search is CPU-bound,
		// and a pool that pegs EVERY core starves the compositor → the GPU-composited flying-gem/card
		// animations stutter while the AI thinks. Sims are capped in AGGREGATE (perWorkerSims scales to the
		// pool size), so one fewer worker keeps total sims ~unchanged — this only bites on low-core machines
		// where the contention actually exists (6-/8-core boxes still get the full 4).
		const cores = Math.max(1, Math.min((navigator.hardwareConcurrency || 4) - 1, 4));
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
		if (wasmReady && ["S", "N"].includes(roomData?.ai_variant) && roomData?.room_id
			&& clientAiArmedRef.current !== roomData.room_id) {
			clientAiArmedRef.current = roomData.room_id;
			send({ action: "client_ai_ready" });
			send({ action: "client_ai_hidden", hidden: document.hidden }); // seed the server's tab-state
		}
	}, [wasmReady, roomData?.room_id, roomData?.ai_variant, send]);

	// Tell the server when this tab backgrounds/foregrounds. While hidden the server does NOT fall back
	// to its weaker S move — it waits for this client's full-strength N move, which a throttled/frozen
	// tab delivers whenever it next gets CPU (usually on refocus). Without this signal the server's
	// anti-hang timeout would substitute S; the flag suppresses that so the bot always plays N.
	useEffect(() => {
		const notify = () => {
			if (clientAiArmedRef.current) send({ action: "client_ai_hidden", hidden: document.hidden });
		};
		document.addEventListener("visibilitychange", notify);
		return () => document.removeEventListener("visibilitychange", notify);
	}, [send]);

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
		// Aggregate cap (10k) split across the pool so the SUMMED sims never exceed the total.
		const perWorkerSims = Math.max(1, Math.ceil(CLIENT_AI_MAX_SIMS_TOTAL / pool.length));
		(async () => {
			try {
				const visitsArrays = await Promise.all(pool.map((wk, i) =>
					wk.request({
						// "N" (Nina, the top tier) plays the strongest learned net via the PV policy+value search.
						// The old value-leaf N serving (searchN / n_model.json) is RETAINED in the worker + wasm
						// as a record, just no longer routed to. Swap pv_model.json to update what "N" plays.
						kind: roomData?.ai_variant === "N" ? "searchPV" : "search", state: stateStr, seat: as.seat,
						budget: CLIENT_AI_BUDGET_MS, maxSims: perWorkerSims,
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
					// Offline: the move is applied locally by the driver instead of submitted —
					// the browser IS the server here. Same search, same move, different sink.
					if (offlineRef.current) submitOfflineAiMoveRef.current?.(mv);
					else send({ action: "ai_move", move: mv });
				}
			} catch {}
		})();
	}, [roomData, wasmReady, send]);

	// ── "Someone's waiting for you" tab indicator (permission-free) ─────────
	// In a human-vs-human game only, when the tab is HIDDEN and it's your turn OR a
	// ping arrived, flash the page title and swap in the alert favicon so an unfocused
	// tab shows someone's waiting. Never fires for vs-AI or puzzle games (no human is
	// waiting there). Cleared the moment you return (visibilitychange → visible). No Notifications API.
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
			// Only alert when a real human opponent is waiting — never for vs-AI or puzzle games.
			if (humanGame && (myTurn || pinged)) flash(); else stop();
		};
		evaluate();
		document.addEventListener("visibilitychange", evaluate);
		return () => { document.removeEventListener("visibilitychange", evaluate); stop(); };
	}, [humanGame, myTurn, pinged]);

	// ── Turn chime ──────────────────────────────────────────────────────────
	const prevMyTurnRef = useRef(false);
	// Play a short sound the moment it becomes your turn in a human-vs-human game
	// (focused or not). Fires only on the not-your-turn → your-turn transition, so
	// it never repeats while you're already on the clock. Never for vs-AI, puzzles,
	// or review (humanGame gates those out). The AudioContext is already unlocked by
	// your own in-game clicks; best-effort otherwise (playPing swallows failures).
	useEffect(() => {
		const wasMyTurn = prevMyTurnRef.current;
		prevMyTurnRef.current = myTurn;
		if (humanGame && myTurn && !wasMyTurn) playPing();
	}, [humanGame, myTurn]);

	useEffect(() => {
		if (screen === "spender" && spenderScreen === "browser" && authUser) fetchGames(authUser);
	}, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

	// The game you just finished leaves Active and joins History the moment it
	// ENDS, not when the lobby next loads — see useFinishedGameSync (shared kit).
	useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
		dropLobbyGame("spender", myId, "active", rid, setActiveGames);
		if (authUser) fetchGames(authUser);
	});

	useEffect(() => {
		if (toast) { const t = setTimeout(() => setToast(""), 2500); return () => clearTimeout(t); }
	}, [toast]);

	// a connect that never answers must not leave the spinner up forever
	useEffect(() => {
		if (!connecting) return;
		const t = setTimeout(() => {
			setConnecting(false);
			setToast("Still connecting — the server may be waking up. Try again in a moment.");
		}, 15000);
		return () => clearTimeout(t);
	}, [connecting]);

	// Hold on the final board for 0.5s after the game ends before revealing the
	// win/loss screen, so the player sees the move that ended it. Resets whenever
	// the game isn't over (a new game), so the next ending delays again.
	useEffect(() => {
		if (game?.phase === "over") {
			const t = setTimeout(() => setResultReady(true), 500);
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
		if (screen === "spender" && spenderScreen === "game") vp.setAttribute("content", base + ", maximum-scale=1.0, user-scalable=no");
		return () => vp.setAttribute("content", base);
	}, [screen]);

	// ── Loading: ping backend until ready, then proceed to auth/browser ────
	useEffect(() => {
		if (screen !== "loading") return;
		let cancelled = false;
		// Resolve the landing screen. For a logged-in (non-guest) user we also
		// validate the stored session token here: it can be silently dead (unused
		// for 90 days, or logged out — each device has its own session, see
		// core.auth), which downgrades every authenticated request to anonymous
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
							setTimeout(() => { if (!cancelled) landAt(dest); }, 350);
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
						// the ITALIC face is a separate file and a separate
						// display:optional decision — leaving it out of the gate
						// (and out of index.html's preloads) is what made every
						// italic on the site render in the heavier Georgia
						// fallback until a reload warmed the cache
						document.fonts.load('italic 400 1rem "Crimson Pro"'),
					]),
					new Promise(r => setTimeout(r, 1500)),
				]);
			} catch {}
		};
		// OFFLINE route: the whole point of /offline is working with NO backend, so it must
		// never gate on the ping (the polling loop below has no give-up branch). Land straight
		// on the hub — identity is local (guest myId / cached login) and needs no network.
		if (initialRouteRef.current?.game === "offline") {
			(async () => { await waitFonts(); if (!cancelled) landAt("home"); })();
			return () => { cancelled = true; };
		}
		// Fast path: if backend responds within 250ms, skip the loading screen entirely
		(async () => {
			try {
				const ctrl = new AbortController();
				const t = setTimeout(() => ctrl.abort(), 250);
				const res = await fetch(`${HTTP_BASE}/games`, { signal: ctrl.signal });
				clearTimeout(t);
				if (res.ok && !cancelled) { const dest = await resolveDest(); await waitFonts(); if (!cancelled) landAt(dest); return; }
			} catch {}
			if (!cancelled) { setShowLoading(true); startPolling(); }
		})();
		return () => { cancelled = true; if (interval) clearInterval(interval); };
	}, [screen, loadingKick]); // eslint-disable-line react-hooks/exhaustive-deps

	// ── Gem flash when bank count drops ───────────────────────────────────────
	const prevBankRef = useRef(null);
	const [flashGems, setFlashGems] = useState(new Set());
	useEffect(() => {
		if (reviewing || !game?.bank) return;   // no flashes while rewinding (puzzle steps DO animate)
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
	// Run the flight through the Web Animations API with LITERAL pixel values.
	//
	// The CSS keyframes interpolate `translate(var(--dx), var(--dy))`. An animation
	// whose keyframes read custom properties can't reliably be promoted to the
	// compositor, so it runs on the MAIN thread — where it competes with whatever
	// else is happening. That never showed while the animation started only after the
	// server broadcast (nothing else was running). Now that a take animates from the
	// click, the broadcast re-render plus the AI's WASM worker start-up land right in
	// the flight, and cost a dropped frame at the landing.
	//
	// Literal values let the compositor own it, so main-thread work can't stutter it.
	// The CSS animation stays as the fallback for browsers without WAAPI.
	const animatedFlyRef = useRef(new Set());
	const animateFlyer = (el, f) => {
		if (!el || typeof el.animate !== "function") return;
		if (animatedFlyRef.current.has(f.id)) return;   // refs fire on every re-render
		animatedFlyRef.current.add(f.id);
		el.style.animation = "none";                    // take over from the CSS keyframes
		el.animate(
			[{ transform: `translate(0,0) scale(${f.s0})`, opacity: 1 },
			 { transform: `translate(${f.dx}px, ${f.dy}px) scale(${f.s1})`,
			   opacity: f.kind === "card" ? 0.5 : 0.15 }],
			{ duration: f.kind === "card" ? 500 : 550, delay: f.delay || 0,
			  easing: "cubic-bezier(.3,.7,.4,1)", fill: "both" });
	};

	// Set when we pre-animate our OWN take on click (see handleTakeGems). The server
	// broadcast that follows would otherwise diff the same gems and fly them a second
	// time. Timestamped so a rejected/never-arriving move can't suppress a later,
	// legitimate animation forever.
	const preFlownRef = useRef(0);

	// Spawn flyers for gem moves (+ optionally a bought card). Measures in ONE
	// requestAnimationFrame — all reads together, no interleaved writes — so it can't
	// thrash layout. Extracted from the diff effect below so a click can fire it
	// immediately, before the server has replied.
	const spawnFlyers = (specs, cardFly) => {
		if (!specs.length && !cardFly) return () => {};
		const raf = requestAnimationFrame(() => {
			const made = [];
			let total = 0;
			// Center of the first VISIBLE element matching one of `sels`, in order.
			//
			// The ORDER matters, and the middle entry is not decoration. A per-colour
			// `.token-pill` only exists once you already hold that colour, so when a
			// take is pre-animated on click the pill for a NEW colour has not rendered
			// yet. Falling straight through to the box centre put the gems ~108px below
			// where they actually land, and made all three converge on one point.
			// `.player-tokens` (the row that will contain the pills) is present with
			// real dimensions even while empty, and its centre measured within 1px of
			// the pills' final y — so it is the right fallback.
			const targetIn = (boxEl, ...sels) => {
				for (const sel of sels) {
					const el = sel && boxEl.querySelector(sel);
					if (el) { const r = el.getBoundingClientRect(); if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }
				}
				const r = boxEl.getBoundingClientRect();
				return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
			};
			for (const s of specs) {
				const bankEl = document.querySelector(`.gem-stack[data-color="${s.color}"] .gem-token`);
				const boxEl = document.querySelector(`.player-panel[data-pid="${s.pid}"]`);
				if (!bankEl || !boxEl) continue;
				const br = bankEl.getBoundingClientRect();
				const bank = { x: br.left + br.width / 2, y: br.top + br.height / 2 };
				// this colour's gem indicator; the gem row while that pill doesn't exist yet
				const box = targetIn(boxEl, `.token-pill[data-token="${s.color}"]`, ".player-tokens");
				const size = Math.max(18, Math.round(br.width || 40));
				const from = s.grow ? box : bank;
				const to = s.grow ? bank : box;
				const n = Math.min(s.count, 5);
				for (let i = 0; i < n && total < 8; i++, total++) {
					made.push({
						id: ++flyIdRef.current, kind: "gem", color: s.color, size,
						x: from.x, y: from.y, dx: to.x - from.x, dy: to.y - from.y,
						s0: s.grow ? 0.55 : 1, s1: s.grow ? 1 : 0.55, delay: i * 55,
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
					const dest = targetIn(boxEl, `.bonus-pill[data-bonus="${cardFly.card.bonus}"]`, ".player-bonuses");
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
			setTimeout(() => setFlyers(f => f.filter(x => !ids.has(x.id))), 600 + maxDelay);
		});
		return () => cancelAnimationFrame(raf);
	};

	useEffect(() => {
		if (reviewing) return;   // no flying gems/cards while rewinding (puzzle steps DO animate)
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

		// We already flew our own take the moment it was clicked; don't fly it twice.
		// Only bank->you gems for US are dropped — an over-cap discard (you->bank) in
		// the same broadcast was never pre-animated and must still show.
		let gemSpecs = specs;
		if (preFlownRef.current && Date.now() - preFlownRef.current < 5000) {
			gemSpecs = specs.filter(s => !(s.pid === myId && !s.grow));
			preFlownRef.current = 0;
		}

		return spawnFlyers(gemSpecs, cardFly);
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
	// The FORM lives in shared/AuthScreen.jsx; the shell keeps identity. A
	// registered user's id/token is persisted, a guest's is not (guests keep the
	// anonymous id they already had, so a game started before signing in stays theirs).
	const handleAuthenticated = (user) => {
		setAuthNotice("");
		if (!user.guest) {
			try {
				localStorage.setItem("spender_user", JSON.stringify(user));
				localStorage.setItem("spender_myId", user.id);
			} catch {}
			setMyId(user.id);
		}
		setAuthUser(user);
		consumePendingRoute();
	};

	const handleLogout = () => {
		// End this device's session on the server too (sessions last 90 days from last
		// use, so forgetting the token locally is not a logout). Best effort: the local
		// sign-out below happens regardless, even offline.
		const tok = authUser?.session_token;
		if (tok && !authUser?.guest) {
			fetch(`${HTTP_BASE}/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${tok}` }, keepalive: true })
				.catch(() => {});
		}
		setAuthNotice("");
		setHistoryGames([]);
		try {
			localStorage.removeItem("spender_user");
			localStorage.removeItem("spender_roomId");
		} catch {}
		const newId = uid();
		setMyId(newId);
		try { localStorage.setItem("spender_myId", newId); } catch {}
		setAuthUser(null);
		replacePath(buildPath("home"));
		setScreen("auth");
		setRoomData(null);
		setRoomId("");
		disconnect();
	};

	// Lobby refreshes can discover a session that expired while this tab was
	// open. Keep the route and cached lists so signing in returns to that lobby.
	useEffect(() => {
		const syncLogin = () => {
			if (!authUser?.session_token) return;
			try {
				const latest = latestSession(authUser);
				if (latest.session_token !== authUser.session_token) setAuthUser(latest);
			} catch {}
		};
		const expired = ({ detail }) => {
			if (!authUser?.session_token || detail.id !== authUser.id) return;
			try { if (latestSession(authUser).session_token !== detail.session_token) { syncLogin(); return; } } catch { return; }
			pendingRouteRef.current = parsePath();
			try { localStorage.removeItem("spender_user"); localStorage.removeItem("spender_roomId"); } catch {}
			const newId = uid();
			try { localStorage.setItem("spender_myId", newId); } catch {}
			setMyId(newId);
			setAuthUser(null);
			setHistoryGames([]);
			setAuthNotice("Your session expired. Sign in again to load your game history.");
			setScreen("auth");
			setRoomData(null); setRoomId(""); disconnect();
		};
		const storage = (event) => { if (event.key === "spender_user") syncLogin(); };
		window.addEventListener(SESSION_EXPIRED, expired);
		window.addEventListener("storage", storage);
		return () => {
			window.removeEventListener(SESSION_EXPIRED, expired);
			window.removeEventListener("storage", storage);
		};
	}, [authUser, disconnect]);

	// ── Room / game actions ────────────────────────────────────────────────
	const handleCreate = (vsAI = false, aiVariant = "A", wp = 15, maxPlayers = 4) => {
		if (vsAI) rememberVariant(aiVariant);   // this game's variant is the next modal's default
		const newRoomId = roomCode();
		setRoomId(newRoomId);
		try { localStorage.setItem("spender_roomId", newRoomId); } catch {}
		pendingActionRef.current = vsAI
			? { action: "create", name: playerName, vs_ai: true, ai_variant: aiVariant, win_points: wp }
			: { action: "create", name: playerName, win_points: wp, max_players: maxPlayers };
		setConnecting(true);
		connect(`${WS_BASE}/${newRoomId}/${myId}`);
	};

	const handleJoinGame = (gameId) => {
		setRoomId(gameId);
		try { localStorage.setItem("spender_roomId", gameId); } catch {}
		pendingActionRef.current = { action: "join", name: playerName, session_token: authUser?.session_token };
		setConnecting(true);
		connect(`${WS_BASE}/${gameId}/${myId}`);
	};

	const handleCancel = async (gameId) => {
		let ok = false;
		try {
			const params = new URLSearchParams({ player_id: myId });
			const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
			const roomToken = readRoomToken(`spender_token_${gameId}_${myId}`);
			if (roomToken) headers["X-Room-Token"] = roomToken;
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

	const handleLeaveSeat = async (gameId) => {
		try {
			await leaveOpenSeat({
				endpoint: `${HTTP_BASE}/games`, roomId: gameId, playerId: myId,
				tokenKey: `spender_token_${gameId}_${myId}`, sessionToken: authUser?.session_token,
			});
			setToast("Seat released");
			fetchGames(authUser);
		} catch (err) {
			setToast(err?.message || "Could not leave that table");
		}
	};

	const handleContinue = (gameId) => {
		const savedToken = localStorage.getItem(`spender_token_${gameId}_${myId}`);
		setRoomId(gameId);
		try { localStorage.setItem("spender_roomId", gameId); } catch {}
		pendingActionRef.current = savedToken
			? { action: "reconnect", token: savedToken }
			: { action: "join", name: playerName, session_token: authUser?.session_token };
		setConnecting(true);
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
				goSpender("game");
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

	// ── Puzzle mode ────────────────────────────────────────────────────────
	// A puzzle is a fully-scripted line: the player reproduces the hero moves; a
	// wrong move restarts; the opponent's (S's) frozen replies auto-play. We reuse
	// the whole game screen by RELABELING each step's snapshot so the hero is `myId`
	// (which activates the normal take/buy/reserve UI) and intercepting the single
	// sendMove to compare the player's move to the canonical one. No socket.
	const PUZ_OPP = "puzzle_opp";

	const relabelGame = (gd, heroPid) => {
		if (!gd) return gd;
		const order0 = gd.order || [];
		const oppPid = order0.find(p => p !== heroPid);
		const map = (p) => (p === heroPid ? myId : p === oppPid ? PUZ_OPP : p);
		const g = { ...gd, order: order0.map(map), players: {} };
		for (const p of order0) g.players[map(p)] = gd.players[p];
		if (gd.turn != null) g.turn = map(gd.turn);
		for (const k of ["pending_discard_pid", "pending_noble_pid", "final_round_trigger"])
			if (gd[k]) g[k] = map(gd[k]);
		if (typeof gd.winner === "string") g.winner = map(gd.winner);
		else if (Array.isArray(gd.winner)) g.winner = gd.winner.map(map);
		return g;
	};

	const movesEqual = (a, b) => {
		if (!a || !b || a.type !== b.type) return false;
		if (a.type === "take_gems")
			return [...(a.colors || [])].sort().join(",") === [...(b.colors || [])].sort().join(",");
		if (a.type === "buy") return a.card_id === b.card_id;
		if (a.type === "reserve")
			return (a.card_id || null) === (b.card_id || null) && (a.deck_level || null) === (b.deck_level || null);
		if (a.type === "discard") return a.color === b.color;
		if (a.type === "pick_noble") return a.noble_id === b.noble_id;
		return JSON.stringify(a) === JSON.stringify(b);
	};

	const fmtEval = (v) => (v == null ? "?" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2));
	const puzMoveEval = (m) => { const list = puzzle?.meta?.move_evals || []; const hit = list.find(e => e.move && movesEqual(m, e.move)); return hit ? hit.eval : null; };
	// Players don't know card ids — describe a card by its POSITION in its row ("L3 #1" = the
	// first card of the L3 row), resolved against the puzzle's STARTING position (every label we
	// show — answer, failed move, Answer modal — describes a move from that position). A card in
	// the hero's hand is "your reserved card".
	const puzCardRef = (cardId) => {
		const pos = puzzle?.position;
		if (!cardId || !pos) return cardId;
		for (const lvl of ["L3", "L2", "L1"]) {
			const i = (pos.board?.[lvl] || []).findIndex(c => c && c.id === cardId);
			if (i >= 0) return `${lvl} #${i + 1}`;
		}
		const res = pos.players?.[puzHeroPid]?.reserved || [];
		const j = res.findIndex(c => c && c.id === cardId);
		if (j >= 0) return res.length > 1 ? `your reserved card #${j + 1}` : "your reserved card";
		return cardId;
	};
	const moveLabel = (m) => {
		if (!m) return "";
		if (m.type === "take_gems") return m.colors?.length ? "take " + m.colors.map(c => GEM_LABELS[c] || c).join(", ") : "pass";
		if (m.type === "buy") return "buy " + puzCardRef(m.card_id);
		if (m.type === "reserve") return "reserve " + (m.card_id ? puzCardRef(m.card_id) : "from the L" + m.deck_level + " deck");
		if (m.type === "discard") return "discard " + (GEM_LABELS[m.color] || m.color);
		if (m.type === "pick_noble") return "claim a noble";
		return m.type;
	};

	const PUZ_OPP_DELAY = 850;   // beat before/between the opponent's scripted replies

	// Newest-first move log for the moves played THROUGH step `idx` (so the game log
	// and the fly animations light up during a puzzle, just like a real game).
	const puzMovesThrough = (puz, idx) => {
		const out = [];
		for (let k = 0; k < Math.min(idx, puz.steps.length); k++) {
			const st = puz.steps[k];
			out.unshift({ ...st.move, pid: st.seat === puz.hero_seat ? myId : PUZ_OPP });
		}
		return out;
	};

	// Show the board at snapshot `idx` (idx >= len -> the final position), carrying the
	// accumulated move log. Stepping one idx at a time makes moves grow by exactly one,
	// which is what the fly-animation + log rendering key off.
	const showPuzzleAt = (puz, heroPid, idx) => {
		const snap = idx >= puz.steps.length ? puz.final : puz.steps[idx].snapshot;
		const g = { ...relabelGame(snap, heroPid), moves: puzMovesThrough(puz, idx) };
		setRoomData(rd => ({ ...(rd || {}), game: g }));
	};

	const loadPuzzles = async () => {
		try {
			const res = await fetch(`${HTTP_BASE}/puzzles`);
			const data = await res.json();
			const _list = Array.isArray(data.puzzles) ? data.puzzles : [];
			setPuzList(_list);
			return _list;
		} catch { setPuzList([]); return []; }
	};

	const PUZ_SEEN_KEY = "spender_puzzle_seen";
	const getSeen = () => { try { return new Set(JSON.parse(localStorage.getItem(PUZ_SEEN_KEY) || "[]")); } catch { return new Set(); } };
	const markSeen = (id) => { try { const s = getSeen(); s.add(id); localStorage.setItem(PUZ_SEEN_KEY, JSON.stringify([...s].slice(-2000))); } catch {} };
	// Target answer-type mix for the one-at-a-time draw (buys are common, takes rare/prized).
	const PUZ_TYPE_WEIGHTS = [["buy", 0.60], ["take", 0.15], ["reserve", 0.25]];
	const pickPuzzleType = () => {
		let r = Math.random();
		for (const [t, w] of PUZ_TYPE_WEIGHTS) { if (r < w) return t; r -= w; }
		return "buy";
	};
	const pickPuzzleId = (list) => {
		const bank = (list || []).filter(p => p.kind === "advantage");   // one-at-a-time mode = single 'only-move' puzzles
		if (!bank.length) return null;
		const seen = getSeen();
		let pool = bank.filter(p => !seen.has(p.id));
		if (!pool.length) { try { localStorage.removeItem(PUZ_SEEN_KEY); } catch {} pool = bank; }   // exhausted -> reshuffle
		// draw an answer-type by the target mix, then a random unseen puzzle of that type; fall
		// through the other types (by weight) if that bucket is empty so small pools still serve.
		const at = (p) => p.answer_type || "buy";   // undefined (pre-deploy backend) -> treat as buy
		for (const t of [pickPuzzleType(), "buy", "take", "reserve"]) {
			const tp = pool.filter(p => at(p) === t);
			if (tp.length) return tp[Math.floor(Math.random() * tp.length)].id;
		}
		return pool[Math.floor(Math.random() * pool.length)].id;
	};
	const enterPuzzles = async () => {
		setScreen("puzzles"); setPuzList(null); setPuzHistory([]);   // fresh session -> empty back-stack
		const list = await loadPuzzles();
		const id = pickPuzzleId(list);
		if (id) startPuzzle(id);
	};

	const startPuzzle = async (id) => {
		try {
			const res = await fetch(`${HTTP_BASE}/puzzles/${id}`);
			const puz = await res.json();
			if (!puz || !Array.isArray(puz.steps) || !puz.steps.length) { setToast("Couldn't load that puzzle"); return; }
			const heroPid = (puz.position.order || [])[puz.hero_seat];
			disconnect();
			setReviewing(false); setReplaySnapshots(null); setReplayTurn(null);
			setPuzzle(puz); setPuzHeroPid(heroPid); markSeen(id);
			setPuzStep(0); setPuzAttempts(1); setPuzFeedback(""); setPuzWrong(false); setPuzSolved(false);
			setPuzHintOpen(false); setPuzAnswerOpen(false); setPuzFailed(false); setPuzHideOverlay(false); setPuzFailMove(null);
			// reset the animation baselines so the opening board doesn't spuriously animate
			prevBankRef.current = null; prevPlayersRef.current = null; prevBoardRef.current = null; prevMovesLenRef.current = 0;
			setSelectedGems([]); setSelectedCard(null); setReserveArmed(false);
			setRoomId(id);
			setRoomData({
				room_id: id,
				// name the opponent "AI (X)" so displayName maps it to the persona ("Nina (AI)" etc.),
				// not the bare variant code
				players: { [myId]: (authUser?.name || "You"), [PUZ_OPP]: `AI (${puz.opponent || "S"})` },
				status: "playing",
				game: { ...relabelGame(puz.steps[0].snapshot, heroPid), moves: [] },
			});
			setPuzzling(true);
			goSpender("game");
		} catch { setToast("Couldn't reach the server"); }
	};

	// Intercepts sendMove while in a puzzle: compare the move to the current hero
	// step. Correct -> advance + auto-play the frozen opponent replies; wrong -> restart.
	const submitPuzzleMove = (move) => {
		const puz = puzzle;
		if (!puz || puzFailed || puzSolved) return;
		const cur = puz.steps[puzStep];
		setSelectedGems([]); setSelectedCard(null); setReserveArmed(false);
		setPuzHintOpen(false);   // each step gets a fresh hint
		if (!cur || !cur.is_hero) return;
		if (!movesEqual(move, cur.move)) {
			// WRONG — an explicit FAIL. The board stays put; the fail overlay makes it
			// unmistakable (vs the old silent reset). "Try again" restarts the puzzle.
			setPuzFailMove(move);
			setPuzWrong(true);
			setPuzFailed(true);
			setPuzFeedback("");
			return;
		}
		// CORRECT — show the board after the hero's move (this animates it + logs it),
		// then play the frozen opponent replies one at a time with a beat, so the
		// opponent visibly moves, until it's the hero's turn again (or the puzzle is won).
		setPuzWrong(false); setPuzFeedback("");
		showPuzzleAt(puz, puzHeroPid, puzStep + 1);
		let idx = puzStep + 1;
		if (idx >= puz.steps.length) { setPuzStep(idx); setPuzSolved(true); return; }  // hero's move ended it
		if (puz.steps[idx].is_hero) { setPuzStep(idx); return; }   // consecutive hero decision (no opp between)
		const playOpp = () => {
			if (idx < puz.steps.length && !puz.steps[idx].is_hero) {
				const st = puz.steps[idx];
				idx += 1;
				showPuzzleAt(puz, puzHeroPid, idx);          // after the opponent's move (animates it)
				setPuzFeedback("S played " + moveLabel(st.move));
				setTimeout(playOpp, PUZ_OPP_DELAY);
			} else {
				setPuzStep(idx);
				if (idx >= puz.steps.length) { setPuzSolved(true); setPuzFeedback(""); }
				else setPuzFeedback("");                      // hero's turn again
			}
		};
		setTimeout(playOpp, PUZ_OPP_DELAY);
	};

	const restartPuzzle = () => {
		if (!puzzle) return;
		if (puzFailed) setPuzAttempts(a => a + 1);   // retry after a fail counts as a new attempt
		setPuzStep(0); setPuzWrong(false); setPuzSolved(false); setPuzFailed(false); setPuzFeedback(""); setPuzHideOverlay(false); setPuzFailMove(null);
		setPuzHintOpen(false);
		prevBankRef.current = null; prevPlayersRef.current = null; prevBoardRef.current = null; prevMovesLenRef.current = 0;
		setSelectedGems([]); setSelectedCard(null); setReserveArmed(false);
		showPuzzleAt(puzzle, puzHeroPid, 0);
	};

	// State-only puzzle teardown — shared by exitPuzzle (user action, pushes the URL) and
	// the popstate handler (Back/Forward, which must NEVER write the URL).
	const resetPuzzleState = () => {
		setPuzzling(false); setPuzzle(null); setPuzSolved(false); setPuzWrong(false); setPuzFailed(false);
		setPuzFeedback(""); setRoomData(null); setRoomId("");
		setPuzHintOpen(false); setPuzAnswerOpen(false);
		setSelectedGems([]); setSelectedCard(null); setReserveArmed(false);
	};

	const exitPuzzle = () => {
		resetPuzzleState();
		pushPath(buildPath("home"));
		setScreen("home");
	};

	const nextPuzzle = () => {
		if (puzzle?.id) { markSeen(puzzle.id); setPuzHistory(h => [...h, puzzle.id]); }  // remember where we were
		const id = pickPuzzleId(puzList || []);
		if (id) startPuzzle(id);
		else exitPuzzle();
	};

	// Go back to the previously-shown puzzle (fixes an accidental Next; you can re-solve or review it).
	const prevPuzzle = () => {
		if (!puzHistory.length) return;
		const id = puzHistory[puzHistory.length - 1];
		setPuzHistory(h => h.slice(0, -1));
		startPuzzle(id);
	};

	// ── Offline vs-AI mode ─────────────────────────────────────────────────
	// The game screen renders a synthesized roomData (the puzzle-mode pattern) whose game
	// dict comes from the LOCAL wasm engine via offline.js; there is no socket at all.
	// The AI plays through the exact same worker-pool dispatch as online — the synthesized
	// roomData carries ai_search when it's the AI's turn — with the resulting move routed
	// into the driver instead of a WS send.

	// Rebuild + publish the synthesized roomData for a record. The state swap drives the
	// same diff-based animations a server broadcast would.
	const publishOfflineRoom = async (rec) => {
		const rd = await offlineRoomData(rec, myId, authUser?.name);
		setOfflineRecord(rec);
		setRoomData(rd);
	};

	const enterOfflineGame = async (rec) => {
		disconnect();                              // an offline game must never share the screen with a live socket
		setReviewing(false); setReplaySnapshots(null); setReplayTurn(null);
		setResultReady(rec.status === "over");     // re-opening a finished save shows the result immediately
		// reset the animation baselines so the resumed board doesn't spuriously animate
		prevBankRef.current = null; prevPlayersRef.current = null; prevBoardRef.current = null; prevMovesLenRef.current = 0;
		setSelectedGems([]); setSelectedCard(null); setReserveArmed(false);
		aiDispatchPlyRef.current = -1;             // ply counters are per-game; a stale one would eat the first dispatch
		setRoomId(rec.id);
		setOffline(true);
		offlineRef.current = true;                 // the render below may need it before the commit
		await publishOfflineRoom(rec);
		goSpender("game");
	};

	// Enter a saved game by record, routed by which game owns it: Spender plays on this
	// file's game screen; a CoC/Duel record mounts that game's component instead.
	const enterOfflineRecord = (rec) => {
		if (rec.game === "coc" || rec.game === "duel" || rec.game === "dissonance") {
			disconnect();                    // never share the screen with a live socket
			setOfflinePlay(rec);
			offlinePlayRef.current = rec;
			return Promise.resolve();
		}
		return enterOfflineGame(rec);
	};

	// Enter the hub (list screen). A deep-linked save id resumes that game once loaded;
	// a dead id just leaves you on the hub (replace the URL so reload doesn't re-try it).
	const enterOfflineHub = (rid) => {
		setScreen("offline");
		setOfflinePlay(null);
		offlinePlayRef.current = null;
		setOfflineGames(null);
		listOfflineGames().then((list) => setOfflineGames(list));
		if (rid) {
			loadOfflineGame(rid).then((rec) => {
				if (rec) enterOfflineRecord(rec);
				else replacePath(buildPath("offline"));
			});
		}
	};

	const createAndEnterOffline = async () => {
		try {
			if (offlineGameSel === "coc") {
				const rec = await createOfflineCocGame({
					myBoard: offlineCocMyBoard, oppBoard: offlineCocOppBoard, tier: offlineCocTier,
				});
				pushPath(buildPath("offline", rec.id));
				await enterOfflineRecord(rec);
				return;
			}
			if (offlineGameSel === "duel") {
				const rec = await createOfflineDuelGame({ tier: offlineDuelTier });
				pushPath(buildPath("offline", rec.id));
				await enterOfflineRecord(rec);
				return;
			}
			if (offlineGameSel === "dissonance") {
				const rec = await createOfflineDissonanceGame({ tier: "hard", myId });
				pushPath(buildPath("offline", rec.id));
				await enterOfflineRecord(rec);
				return;
			}
			const rec = await createOfflineGame({ aiVariant: offlineVariant, winPoints: offlineWin });
			pushPath(buildPath("offline", rec.id));
			await enterOfflineGame(rec);
		} catch (e) {
			setToast(String(e?.message || "Couldn't start an offline game"));
		}
	};

	// Exit a CoC/Duel offline game back to the hub (the component's onExit).
	const exitOfflinePlayToHub = () => {
		setOfflinePlay(null);
		offlinePlayRef.current = null;
		pushPath(buildPath("offline"));
		enterOfflineHub(null);
	};

	// Human move sink (the sendMove fork). Illegal is user-visible; the engine failing to
	// load (cold cache, never downloaded) surfaces as its own message.
	const submitOfflineMove = async (move) => {
		const rec = offlineRecordRef.current;
		if (!rec) return;
		try {
			const res = await applyOfflineMove(rec, move, myId, { isAi: false });
			if (!res.ok) { setToast(res.err); return; }
			await publishOfflineRoom(res.rec);
		} catch (e) {
			setToast(String(e?.message || "Move failed"));
		}
	};

	// AI move sink (the worker-pool dispatch fork). A stale/illegal submission is dropped
	// silently — same policy as the server's ai_move handler (races are normal, not errors).
	const submitOfflineAiMove = async (move) => {
		const rec = offlineRecordRef.current;
		if (!rec) return;
		try {
			const res = await applyOfflineMove(rec, move, myId, { isAi: true });
			if (res.ok) await publishOfflineRoom(res.rec);
			else console.debug("[offline-AI] dropped:", res.err);
		} catch (e) {
			console.debug("[offline-AI] apply failed:", e);
		}
	};
	submitOfflineAiMoveRef.current = submitOfflineAiMove;

	// State-only teardown — shared by user exits (which also write the URL) and the
	// popstate handler (which must never write it).
	const resetOfflineState = () => {
		setOffline(false);
		offlineRef.current = false;
		setOfflineRecord(null);
		setRoomData(null); setRoomId("");
		setReviewing(false); setReplaySnapshots(null); setReplayTurn(null);
		setSelectedGems([]); setSelectedCard(null); setReserveArmed(false);
		setConfirmAbandon(false);
	};

	const exitOfflineToHub = () => {
		resetOfflineState();
		pushPath(buildPath("offline"));
		enterOfflineHub(null);
	};

	const handleDeleteOffline = async (id) => {
		await deleteOfflineGame(id);
		setOfflineGames(await listOfflineGames());
	};

	// ── Offline asset precache (the "Download for offline" button) ─────────
	// Everything else on the page is cached opportunistically by sw.js, but the wasm is
	// only ever fetched lazily during a live vs-AI game — a cold install has no engine.
	// This asks the service worker to precache it deliberately (cache:"reload", bypassing
	// the ~10-min Pages TTL) and streams progress back over a MessageChannel. PER GAME —
	// nobody pays for engines they don't play (CoC's fetched model bins are ~4x the other
	// two games combined; Spender + Duel embed their nets in the wasm). Each list carries
	// the fonts too (tiny, and any single download must make that game FULLY offline).
	// `warm` covers the localStorage caches the SW can't serve: CoC's board layouts (its
	// game screen hard-gates on them) and Duel's card catalog. Sizes are the real gzip'd
	// transfer, rounded up.
	const OFFLINE_ASSETS = {
		spender: {
			label: "Spender", size: "~1 MB",
			urls: ["wasm/spender-worker.js", "wasm/spender_core.js", "wasm/spender_core_bg.wasm"],
		},
		coc: {
			label: "Castles of Crimson", size: "~5 MB",
			urls: ["wasm/coc-worker.js", "wasm/coc_core.js", "wasm/coc_core_bg.wasm",
				"wasm/coc_pv_model.bin", "wasm/coc_pv_model_hard.bin"],
			warm: () => fetch(`${HTTP_BASE}/coc/boards`).then((r) => r.json())
				.then((data) => { try { localStorage.setItem("coc_boards_v1", JSON.stringify(data)); } catch {} }),
		},
		dissonance: {
			label: "Dissonance", size: "~350 KB",
			// The SMALLEST of the four, and the only one whose wasm is both the
			// AI and the referee: `classic.rs` runs the room offline, so there is
			// no engine to download beside the search.
			urls: ["wasm/dissonance-worker.js", "wasm/dissonance.js", "wasm/dissonance_bg.wasm"],
			warm: () => fetch(`${HTTP_BASE}/dissonance/catalog`).then((r) => r.json())
				.then((d) => { try { localStorage.setItem("dis_catalog", JSON.stringify(d)); } catch {} }),
		},
		duel: {
			label: "Spender Duel", size: "~1 MB",
			urls: ["wasm/duel-worker.js", "wasm/duel_core.js", "wasm/duel_core_bg.wasm"],
			// Same key + shape SpenderDuel.jsx's own catalog cache uses (the full /catalog body).
			warm: () => fetch(`${HTTP_BASE}/duel/catalog`).then((r) => r.json())
				.then((d) => { try { if (d.ok) localStorage.setItem("duel_catalog", JSON.stringify(d)); } catch {} }),
		},
	};
	const FONT_URLS = ["fonts/cinzel.latin.woff2", "fonts/crimsonpro.latin.woff2", "fonts/crimsonpro-italic.latin.woff2"];
	const startPrecache = (gameKey) => {
		const spec = OFFLINE_ASSETS[gameKey];
		if (!spec) return;
		const setGame = (v) => setPrecacheState((s) => ({ ...s, [gameKey]: v }));
		const urls = [...spec.urls, ...FONT_URLS].map((p) => `${import.meta.env.BASE_URL}${p}`);
		spec.warm?.().catch(() => {});
		const ctrl = navigator.serviceWorker?.controller;
		if (!ctrl) { setGame("err"); return; }
		const ch = new MessageChannel();
		ch.port1.onmessage = (e) => {
			const d = e.data || {};
			if (d.ok) setGame("ok");
			else if (d.error) setGame("err");
			else if (d.total) setGame({ done: d.done, total: d.total });
		};
		setGame({ done: 0, total: urls.length });
		ctrl.postMessage({ type: "PRECACHE_OFFLINE", urls }, [ch.port2]);
	};

	// State-only exit from a Spender room/review — shared by goToMenu (user action) and
	// the popstate handler (which must never write the URL itself).
	const leaveSpenderRoomState = () => {
		disconnect();
		setRoomData(null);
		setSelectedGems([]);
		setSelectedCard(null);
		setConfirmAbandon(false);
		setReviewing(false);
		setReplaySnapshots(null);
		setReplayTurn(null);
	};

	const goToMenu = () => {
		leaveSpenderRoomState();
		pushPath(buildPath("spender"));   // leave the room URL (dedup no-op when popstate-driven)
		goSpender("browser");
		fetchGames(authUser);
	};

	// ── URL routing helpers (see shared/router.js for the contract) ─────────
	// nav(): user-initiated navigation — write the URL FIRST, then the screen, so a mode
	// component always mounts with its URL already correct (sub-games read it at mount).
	const nav = (screenName) => {
		pushPath(buildPath(MODE_FOR_SCREEN[screenName] || "home"));
		setScreen(screenName);
	};

	// enterRoute(): state-only navigation to a parsed route — used by boot, the post-auth
	// consume, and popstate. NEVER pushes (the URL is already what it should be); only an
	// unknown path is normalized (replace, not push).
	const enterRoute = (route) => {
		const g = route?.game;
		if (!g || g === "home") {
			if (!g) replacePath(buildPath("home"));   // unknown path → "/"
			setScreen("home");
			return;
		}
		if (g === "puzzles") { enterPuzzles(); return; }   // needs the fetch+pick, not just the screen
		if (g === "offline") { enterOfflineHub(route.room); return; }   // needs the saved-game list (+ a deep-linked resume)
		if (g === "spender") {
			goSpender("browser");
			if (route.room) setDeepRoom(route.room);   // deep entry once the lobby is up
			return;
		}
		setScreen(SCREEN_FOR_MODE[g]);   // coc/werewolf/duel/books mount and read their own segment 2
	};

	// landAt(): boot injection — resolveDest still decides auth-vs-in, the initial URL
	// decides WHERE. A deep link seen while logged out is stashed across the auth screen
	// (URL left untouched so it survives in the address bar) and consumed after login/guest.
	const landAt = (dest) => {
		if (dest === "auth") {
			const r = initialRouteRef.current;
			pendingRouteRef.current = r && r.game && r.game !== "home" ? r : null;
			setScreen("auth");
			return;
		}
		enterRoute(initialRouteRef.current || { game: "home", room: null });
	};

	const consumePendingRoute = () => {
		const route = pendingRouteRef.current;
		pendingRouteRef.current = null;
		if (route) { enterRoute(route); return; }
		replacePath(buildPath("home"));
		setScreen("home");
	};

	// applyPopRoute(): Back/Forward while on a real screen. Mode-level plus Spender's own
	// segment 2 — a same-mode pop in a SUB-game belongs to its own subscription. Mirrored
	// into applyPopRouteRef every render so the mount-once popstate effect never runs a
	// stale closure.
	const applyPopRoute = (route) => {
		const s = screenRef.current;
		// "in a Spender ROOM" means waiting/game — the lobby (browser) is not a room.
		const inRoomScreen = s === "spender"
			&& (spenderScreenRef.current === "waiting" || spenderScreenRef.current === "game");
		const inSpenderRoom = inRoomScreen && !puzzlingRef.current && !offlineRef.current;
		// A puzzle or an offline game runs on Spender's game screen but is its own site-level mode.
		const curMode = inRoomScreen
			? (puzzlingRef.current ? "puzzles" : offlineRef.current ? "offline" : "spender")
			: (MODE_FOR_SCREEN[s] || "home");
		const target = route.game === null ? "home" : route.game;
		if (target === curMode) {
			if (target === "offline") {
				// Offline owns its own segment 2 (the local save id): Back out of a game →
				// the hub; Forward (or cross-save) into a game → resume it. State-only.
				// Covers BOTH offline surfaces: Spender (offlineRef, this file's game
				// screen) and CoC (offlinePlayRef, the mounted component).
				const rid = route.room;
				const inGame = offlineRef.current || !!offlinePlayRef.current;
				const curRid = offlinePlayRef.current ? offlinePlayRef.current.id : roomIdRef.current;
				if (!rid && inGame) { resetOfflineState(); enterOfflineHub(null); }
				else if (rid && (!inGame || rid !== curRid)) {
					resetOfflineState(); enterOfflineHub(rid);
				}
				return;
			}
			if (target === "spender") {
				// Spender owns its own segment 2 (rooms live in the shell, unlike sub-games).
				const rid = route.room;
				if (rid && (!inSpenderRoom || rid !== roomIdRef.current)) {
					// Forward into a room (or across rooms): via the lobby + the deep-entry effect.
					if (inSpenderRoom) leaveSpenderRoomState();
					goSpender("browser");
					setDeepRoom(rid);
				} else if (!rid && (inSpenderRoom || urlAttemptRef.current)) {
					// Back out of the room → lobby — INCLUDING out of a still-connecting URL
					// attempt (popping during the join's round trip would otherwise let the
					// late "joined" push the room URL back). goToMenu disconnects; its push
					// dedups (URL already /spender).
					urlAttemptRef.current = null;
					goToMenu();
				}
			}
			return;   // a sub-game's segment-2 change is handled by its own subscription
		}
		// Leaving the current mode: state-only cleanup, then land on the target.
		if (puzzlingRef.current) resetPuzzleState();
		else if (offlineRef.current) resetOfflineState();
		else if (inRoomScreen) leaveSpenderRoomState();
		if (offlinePlayRef.current) { setOfflinePlay(null); offlinePlayRef.current = null; }
		enterRoute(route);
	};
	applyPopRouteRef.current = applyPopRoute;

	// Deep entry into a Spender room from the URL: once the lobby screen is up, run the
	// EXISTING resume semantics (saved token → reconnect, else join — exactly the
	// invite-link behavior). handleContinue's pendingActionRef suppresses the onOpen
	// auto-reconnect fallback, so a deep link into room B can't cross-wire with a saved
	// pointer at room A. Runs post-commit, so myId/playerName are settled after auth.
	useEffect(() => {
		if (!deepRoom || screen !== "spender" || spenderScreen !== "browser") return;
		urlAttemptRef.current = { rid: deepRoom, retried: false };
		handleContinue(deepRoom);
		setDeepRoom(null);
	}, [deepRoom, screen]); // eslint-disable-line react-hooks/exhaustive-deps

	const handleAbandon = () => {
		if (offline) {
			// No server to record a forfeit against — abandoning a local game just deletes
			// the save and returns to the hub.
			const id = offlineRecordRef.current?.id;
			if (id) deleteOfflineGame(id);
			exitOfflineToHub();
			return;
		}
		send({ action: "abandon" });
		setConfirmAbandon(false);
	};

	// Rules modal — defined once and rendered in BOTH the lobby and the in-game screen
	// (reached from the options menu), so "How to Play" is available anywhere. Chrome +
	// scrolling come from the shared kit; the words live in ./rules.jsx.
	const rulesModalEl = showRules && (
		<RulesModal title="How to play — Spender" onClose={() => setShowRules(false)}>
			<SpenderRules />
		</RulesModal>
	);

	const handleStart = () => send({ action: "start" });

	const sendMove = (move) => {
		if (puzzling) { submitPuzzleMove(move); return; }   // puzzle: compare to canonical, don't send
		if (offline) { submitOfflineMove(move); return; }   // offline: apply through the local engine
		send({ action: "move", move });
	};

	const handleTakeGems = () => {
		if (!myTurn || selectedGems.length === 0) return;
		// INSTANT ACKNOWLEDGEMENT. The server is authoritative, so the board and our
		// token counts can only change when its broadcast arrives — measured at ~250ms
		// median to Render but ranging past 1s, and that VARIANCE is what reads as
		// jitter far more than the delay itself. Until now a click produced no feedback
		// at all for that whole window.
		//
		// So fly the gems immediately. This changes NO game state — it is purely the
		// animation, which is why it needs no rollback if the server rejects the move
		// (it can't, in practice: the UI only enables legal takes). The flight lasts
		// ~600ms, which happens to cover a typical round trip, so the counts settle
		// just about as the gems land.
		//
		// A puzzle is resolved locally with no socket, so its animation already comes
		// from the state diff — pre-flying there would double it. Same for offline: the
		// local apply lands in ~ms, so the diff animation IS the feedback.
		if (!puzzling && !offline) {
			const counts = {};
			for (const c of selectedGems) counts[c] = (counts[c] || 0) + 1;
			spawnFlyers(Object.entries(counts).map(([color, count]) =>
				({ pid: myId, color, count, grow: false })), null);
			preFlownRef.current = Date.now();   // tells the diff effect not to repeat it
		}
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
	// The puzzle status line that replaces the normal action bar (turn badge + hint +
	// the Take/Buy controls, which still funnel through sendMove -> submitPuzzleMove).
	function renderPuzzleBar() {
		const steps = puzzle?.steps || [];
		const total = steps.filter(s => s.is_hero).length;
		const done = steps.slice(0, puzStep).filter(s => s.is_hero).length;
		const cur = steps[puzStep];
		return (<>
			<span className="turn-badge mine">{puzSolved ? "Solved!" : "Your Move"}</span>
			<span className="target-label" style={{ marginRight: 6 }}>Target: {game.win_points || 15}</span>
			<span className={`action-hint${puzWrong ? " puzzle-wrong" : ""}`}>
				{puzSolved ? (puzzle?.kind === "advantage" ? "You found the only move!" : "You found the win!") : (puzFeedback || `Move ${Math.min(done + 1, total)} of ${total}`)}
			</span>
			<div className="action-bar-btns">
				{renderActionButtons() || <button className="btn btn-ghost action-bar-spacer" aria-hidden="true" tabIndex={-1}>{"✕"}</button>}
			</div>
		</>);
	}

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
		// The AI has no client to notify, so pinging it is pointless: keep its box inert.
		const canPing = !isMe && !reviewing && pid !== game?.ai_player;
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
		// on admin + overlay data for the shown position. Variant N has NO per-card overlay (only a
		// position eval), so accept either the per-card values OR a position eval.
		if (!authUser?.is_admin || (!aiCardValues && aiPositionEval == null)) return null;
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

	// The position eval pill — rendered on its OWN row above the action buttons. S shows leaf+srch;
	// N shows just its learned-value eval of the current position (no static/searched split).
	function renderAiEval() {
		if (!showAiVals || !authUser?.is_admin || (!aiCardValues && aiPositionEval == null)) return null;
		const evL = aiPositionEval;            // S = STATIC leaf eval; N = learned-value eval (both instant)
		if (evL == null) return null;
		const isN = roomData?.ai_variant === "N";
		const evS = aiPositionEvalSearched;    // S only: SEARCHED eval (live only — null in review)
		const mine = aiValuesPid === myId;
		const fmt = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
		return (
			<div className="ai-pos-eval-row">
				<span className={`ai-pos-eval${mine ? " mine" : ""}`}
					title={isN
						? `N's learned-value eval of the current position from ${mine ? "your" : "the AI's"} perspective (+1 = ${mine ? "you" : "AI"} winning)`
						: `S's whole-position eval from ${mine ? "your" : "the AI's"} perspective (+1 = ${mine ? "you" : "AI"} winning). leaf = static v(state); srch = after S's PUCT search (reused from the AI's move on its turn, freshly searched on yours)`}>
					<b>{isN ? "eval" : "leaf"}</b>{fmt(evL)}{!reviewing && !isN && <span className="ai-pos-eval-srch"><b>srch</b>{evS != null ? fmt(evS) : "…"}</span>}
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
				{/* THE THIRD SHELL SCREEN, and on a cold Render dyno the one a first-time
				    visitor looks at for 30-50 seconds — so it wears the same wordmark,
				    the same ornament and the same ground as the two screens behind it
				    (`.loading-screen` is named alongside `.home`/`.auth-screen` in the
				    paired selectors in Spender.css) rather than being a bare progress
				    bar on black. */}
				<div className="app loading-screen">
					{/* Same shell as the auth screen: the block centres in the space above
					    the strapline and the strapline takes the bottom edge. It used to
					    be one centred column biased upward with trailing padding, which
					    left ~40% of every viewport empty BELOW it — 308px at 1280x800,
					    460px at 1920x1080 — on the one screen a cold visitor stares at
					    for thirty seconds. */}
					<div className="auth-main">
					<h1 className="loading-logo">{SITE_NAME}</h1>
					{HERO_RULE}
					<p className="loading-sub">Waking the server…</p>
					{/* role=progressbar with the real value, so the wait is announced
					    rather than being a decorative div that only sighted users can
					    read. aria-valuetext carries the same words as the caption. */}
					<div className="loading-bar-wrap" role="progressbar" aria-label="Connecting"
						aria-valuemin={0} aria-valuemax={100}
						aria-valuenow={Math.round(loadingProgress * 100)}>
						<div className="loading-bar" style={{ width: `${Math.round(loadingProgress * 100)}%` }} />
					</div>
					<p className="loading-hint">
						{loadingProgress >= 0.99 ? "Ready" : loadingProgress < 0.05 ? "Connecting…" : `${Math.round(loadingProgress * 100)}%`}
					</p>
					{/* The polling loop above never gives up, so a user with NO connection needs an
					    exit that doesn't. Navigating away from "loading" cancels the poll (the
					    effect's cleanup); the offline hub then works entirely from local storage. */}
					<button className="btn btn-ghost loading-escape"
						onClick={() => { pushPath(buildPath("offline")); enterOfflineHub(null); }}>
						Play offline vs AI
					</button>
					</div>				</div>
			</>
		);
	}

	// Auth screen
	if (screen === "auth") return (
		// heroRule is the home menu's ornament, handed over rather than re-drawn:
		// the front door and the menu behind it are one title plate.
		<AuthScreen siteName={SITE_NAME} httpBase={HTTP_BASE} css={css} myId={myId}
			heroRule={HERO_RULE} notice={authNotice} onAuthenticated={handleAuthenticated} />
	);

	// Home menu — pick a game (Forrest Games landing)
	if (screen === "home") return (
		<HomeScreen authUser={authUser} css={css} toast={toast}
			onPickGame={nav}
			onPuzzles={() => { pushPath(buildPath("puzzles")); enterPuzzles(); }}
			onBooks={() => nav("books")}
			onNotes={() => nav("notes")}
			onBggFilter={() => nav("bggfilter")}
			onSiteHealth={() => setSiteHealthOpen(true)} siteAlerts={siteAlerts}
			siteHealth={siteHealthOpen && (
				<SiteHealth authUser={authUser} onClose={() => setSiteHealthOpen(false)} onChanged={refreshSiteAlerts} />
			)}
			onLogout={handleLogout} />
	);

	// Books — personal ranked reading list (public read, owner edit)
	if (screen === "books") return (
		<Suspense fallback={<GameChunkLoading />}>
			<Books authUser={authUser} onExit={() => nav("home")} />
		</Suspense>
	);

	// Notes — the owner's private notebook (folders, notes, screenshots). The server
	// refuses everyone else on every route; the page shows them a "private" notice.
	if (screen === "notes") return (
		<Suspense fallback={<GameChunkLoading />}>
			<Notes authUser={authUser} onExit={() => nav("home")} />
		</Suspense>
	);

	// BGG Filter — static BoardGameGeek dataset, filtered client-side. No backend.
	if (screen === "bggfilter") return (
		<Suspense fallback={<GameChunkLoading />}>
			<BggFilter onExit={() => nav("home")} />
		</Suspense>
	);

	// Castles of Crimson — self-contained game component, mounted by the shell.
	if (screen === "coc") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<CastlesOfCrimson myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Where Wolf? — self-contained social-deduction game component.
	if (screen === "werewolf") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<WhereWolf myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Spender Duel — self-contained 2-player game component.
	if (screen === "duel") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<SpenderDuel myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	if (screen === "dontminion") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<Dontminion myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Dissonance — self-contained 2-player trick-taking game component.
	if (screen === "dissonance") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<Dissonance myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Rag Tag — self-contained 2-player auto battler.
	if (screen === "ragtag") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<RagTag myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Orbit — faithful two-player Zenith with a random first-release opponent.
	if (screen === "orbit") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<Orbit myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Black Castle — the 2–4 seat Himeji worker-placement game.
	if (screen === "blackcastle") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<BlackCastle myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Pinch — two-player rings, reversible markers, and a random practice bot.
	if (screen === "pinch") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<Pinch myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// SecretNames — the two-player cooperative word game.
	if (screen === "secretnames") {
		return (
			<Suspense fallback={<GameChunkLoading />}>
				<SecretNames myId={myId} authUser={authUser} onExit={() => nav("home")} />
			</Suspense>
		);
	}

	// Puzzle picker — pick a scripted endgame puzzle to solve vs S.
	if (screen === "puzzles") return (
		<>
			<style>{css}</style>
			<div className="app">
				<div className="puzzle-top">
					<button className="btn btn-ghost btn-sm" onClick={() => nav("home")}>← Back</button>
					<span className="puzzle-top-title">Spender Puzzles</span>
					<span style={{ width: 56 }} />
				</div>
				<div className="puzzle-picker">
						{(puzList == null) && <div className="puzzle-empty">Loading puzzle…</div>}
						{(puzList != null && puzList.length === 0) && <div className="puzzle-empty">No puzzles available yet.</div>}
					</div>
					{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// A CoC/Duel offline game in play: mount that game's component with the record. It
	// renders its own whole screen (CoC's board layout / Duel's card catalog come from
	// their localStorage caches, warmed by the precache).
	if (screen === "offline" && offlinePlay) return (
		<Suspense fallback={<GameChunkLoading />}>
			{offlinePlay.game === "duel"
				? <SpenderDuel myId={myId} authUser={authUser} offline={offlinePlay}
					onExit={exitOfflinePlayToHub} />
				: offlinePlay.game === "dissonance"
					? <Dissonance myId={myId} authUser={authUser} offline={offlinePlay}
						onExit={exitOfflinePlayToHub} />
					: <CastlesOfCrimson myId={myId} authUser={authUser} offline={offlinePlay}
						onExit={exitOfflinePlayToHub} />}
		</Suspense>
	);

	// Local vs AI hub — start/resume/delete offline games + the offline-asset download.
	// Reachable with NO backend (the boot gate skips the ping for /offline).
	if (screen === "offline") return (
		<>
			<style>{css}</style>
			<div className="app" style={{ "--lby-accent": "#7fb069" }}>
				<LobbyHeader
					onBack={() => nav("home")}
					title="Local vs AI"
					user={<LobbyUser user={authUser} />}
				/>
				<div className="browser offline-hub">
					<div className="offline-panel">
						<CmRow label="Game">
							{/* WRAP: four games no longer fit one phone row, and the base
							    control clips rather than scrolls -- see cm-seg-wrap. */}
							<CmSeg wrap value={offlineGameSel} onChange={setOfflineGameSel} options={[
								{ value: "spender", label: "Spender" },
								{ value: "coc", label: "Castles of Crimson" },
								{ value: "duel", label: "Spender Duel" },
								{ value: "dissonance", label: "Dissonance" },
							]} />
						</CmRow>
						{offlineGameSel === "duel" && (
							<CmRow label="Difficulty">
								<CmSeg value={offlineDuelTier} onChange={setOfflineDuelTier} options={[
									{ value: "hard", label: "Hard" }, { value: "expert", label: "Expert" },
								]} />
								<span className="cm-hint">The client-WASM tiers — the same nets that play online.</span>
							</CmRow>
						)}
						{offlineGameSel === "spender" && (<>
							<CmRow label="Opponent">
								<div className="cm-pills">
									{["S", "N"].map(v => (
										<button key={v} type="button" className={`cm-pill${offlineVariant === v ? " sel" : ""}`}
											onClick={() => setOfflineVariant(v)}>
											<span className="cm-pill-name">{aiPersona(v)}</span>
											<span className="cm-pill-sub">{aiTierLabel(v)}</span>
										</button>
									))}
								</div>
								<span className="cm-hint">These are the strongest opponents — the same AI that runs in your browser online.</span>
							</CmRow>
							<CmRow label="Length">
								<CmSeg value={offlineWin} onChange={setOfflineWin} options={[
									{ value: 15, label: "Classic 15" }, { value: 21, label: "Long 21" },
								]} />
							</CmRow>
						</>)}
						{offlineGameSel === "coc" && (<>
							<CmRow label="Difficulty">
								<CmSeg value={offlineCocTier} onChange={setOfflineCocTier} options={[
									{ value: "hard", label: "Hard" }, { value: "expert", label: "Expert" },
								]} />
								<span className="cm-hint">The client-WASM tiers — the same nets that play online.</span>
							</CmRow>
							<CmRow label="Your Board">
								<select className="input offline-select" value={offlineCocMyBoard}
									onChange={(e) => setOfflineCocMyBoard(e.target.value)}>
									{Object.entries(COC_BOARD_NAMES).map(([id, nm]) =>
										<option key={id} value={id}>{id} — {nm}</option>)}
								</select>
							</CmRow>
							<CmRow label="Bot's Board">
								<select className="input offline-select" value={offlineCocOppBoard}
									onChange={(e) => setOfflineCocOppBoard(e.target.value)}>
									{Object.entries(COC_BOARD_NAMES).map(([id, nm]) =>
										<option key={id} value={id}>{id} — {nm}</option>)}
								</select>
							</CmRow>
						</>)}
						{offlineGameSel === "dissonance" && (
							<CmRow label="Difficulty">
								<span className="cm-hint">
									Hard — the exact solver, in this browser. Classic rounds to 200.
								</span>
							</CmRow>
						)}
						{/* duel: the Difficulty row above is its whole config (always 2p, one board) */}
						<button type="button" className="cm-create" style={{ marginTop: 10 }}
							onClick={createAndEnterOffline}>
							Start Game
						</button>
					</div>

					<div className="offline-panel">
						<h3 className="offline-h">Saved games</h3>
						{offlineGames == null && <div className="puzzle-empty">Loading…</div>}
						{offlineGames != null && offlineGames.length === 0 &&
							<div className="puzzle-empty">No local games yet — start one above.</div>}
						{(offlineGames || []).map(g => (
							<div key={g.id} className="offline-save-row">
								<div className="offline-save-info">
									{g.game === "coc"
										? <><b>Castles</b> · {g.tier === "hard" ? "Hard" : "Expert"}</>
										: g.game === "duel"
											? <><b>Duel</b> · {g.tier === "hard" ? "Hard" : "Expert"}</>
											: <><b>Spender · {aiPersona(g.aiVariant)}</b> · {g.winPoints === 21 ? "Long 21" : "Classic 15"}</>}
									{" · "}{g.status === "over" ? "finished" : "in progress"}
									<span className="offline-save-time"> · {timeAgo(Math.floor((g.updated || 0) / 1000))}</span>
								</div>
								<div className="offline-save-btns">
									<button className="btn btn-gold btn-sm"
										onClick={() => { pushPath(buildPath("offline", g.id)); enterOfflineRecord(g); }}>
										{g.status === "over" ? "View" : "Continue"}
									</button>
									<button className="btn btn-ghost btn-sm" onClick={() => handleDeleteOffline(g.id)}>✕</button>
								</div>
							</div>
						))}
					</div>

					<div className="offline-panel">
						<h3 className="offline-h">Play with no connection</h3>
						<p className="offline-note">
							Download a game's AI engine so it works fully offline — even in airplane mode.
							Install the site to your home screen first for the best experience.
						</p>
						{Object.entries(OFFLINE_ASSETS).map(([key, spec]) => {
							const st = precacheState[key];
							return (
								<div key={key} className="offline-save-row">
									<div className="offline-save-info"><b>{spec.label}</b> · {spec.size}</div>
									<div className="offline-save-btns">
										{st === "ok" && <span className="offline-note ok">✓ Ready offline</span>}
										{st && typeof st === "object" &&
											<span className="offline-note">Downloading… {st.done}/{st.total}</span>}
										{st === "err" &&
											<span className="offline-note err">Unavailable here — open the live site once, then retry. </span>}
										{(st == null || st === "err") &&
											<button className="btn btn-outline btn-sm" onClick={() => startPrecache(key)}>Download</button>}
									</div>
								</div>
							);
						})}
					</div>

					{/* KEEPING SCORE AT A REAL TABLE — the one thing here that needs no
					    engine at all. The card is localStorage plus `pricing.js`, the
					    same mirror of `engine._terms_for` the board prices with, so it
					    works with no connection and no download. It sits in the hub
					    because the hub is the only screen you can REACH with no
					    connection: the Dissonance lobby is behind the backend ping. */}
					<div className="offline-panel">
						<h3 className="offline-h">Playing with real cards?</h3>
						<p className="offline-note">
							Keep a Dissonance scorecard here — it works with no connection and
							nothing to download, and it scores each round the way the game does.
						</p>
						<div className="offline-save-row">
							<div className="offline-save-info"><b>Paper scorecard</b> · classic</div>
							<div className="offline-save-btns">
								<button className="btn btn-outline btn-sm"
									onClick={() => setOfflineCard(true)}>Open</button>
							</div>
						</div>
					</div>
				</div>
				{offlineCard && <DissonanceScorecard onClose={() => setOfflineCard(false)} />}
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// Game browser screen
	// connecting to a room while still on the lobby → spinner, not a lobby flash (CoC)
	if (screen === "spender" && spenderScreen === "browser" && connecting) return (
		<>
			<style>{css}</style>
			<div className="app" style={{ "--lby-accent": GAME_ACCENTS.spender }}>
				<LobbyLoading label="Connecting…" />
			</div>
		</>
	);
	if (screen === "spender" && spenderScreen === "browser") return (
		<>
			<style>{css}</style>
			<div className="app" style={{ "--lby-accent": GAME_ACCENTS.spender }}>
				{/* NO `title` IN A LOBBY. The identity lives in the band below (LobbyHero):
				    the emblem, the accent wordmark and the player pill are what the home
				    card was, and repeating the name in a 1.2rem centred slug 60px above
				    them is two titles, not a hierarchy. The bar keeps Back and the user,
				    which is all it is for here; in-GAME it still carries its title. */}
				<LobbyHeader
					onBack={() => nav("home")}
					user={<LobbyUser user={authUser} />}
				/>
				<div className="browser lby-page">
					<div className="lby-page-in">
						<LobbyHero game="spender">
						<LobbyCreateRow
							onCreate={() => setShowCreateModal(true)}
							onJoin={(code) => handleJoinGame(code)}
							onRefresh={() => fetchGames(authUser)}
							onRules={() => setShowRules(true)}
							refreshing={browserLoading} />
						</LobbyHero>

					{showCreateModal && (
						<CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
							<CmRow label="Opponent">
								<CmSeg value={createOpp} onChange={setCreateOpp} options={[
									{ value: "friend", label: "VS Friend", title: "An open game friends join from Open Games (or your room code)" },
									{ value: "ai", label: "VS AI", title: "Starts instantly against one of the AI opponents" },
								]} />
							</CmRow>
							{createOpp === "ai" ? (
								<CmRow label="AI Difficulty">
									<div className="cm-pills">
										{AI_VARIANTS.map(v => (
											<button key={v} type="button" className={`cm-pill${createVariant === v ? " sel" : ""}`}
												onClick={() => setCreateVariant(v)}>
												<span className="cm-pill-name">{aiPersona(v)}</span>
												<span className="cm-pill-sub">{aiTierLabel(v)}</span>
											</button>
										))}
									</div>
								</CmRow>
							) : (
								<CmRow label="Players">
									<CmSeg value={createSeats} onChange={setCreateSeats}
										options={[2, 3, 4].map(n => ({ value: n, label: String(n) }))} />
									<span className="cm-hint">Friends join from Open Games — or send your room code.</span>
								</CmRow>
							)}
							<CmRow label="Length">
								<CmSeg value={winPoints} onChange={setWinPoints} options={[
									{ value: 15, label: "Classic 15" }, { value: 21, label: "Long 21" },
								]} />
							</CmRow>
							<div className="cm-footer">
								<span className="cm-summary">
									Creating: <b>{createOpp === "ai"
										? `${aiPersona(createVariant)} (${aiTierLabel(createVariant)})`
										: `vs Friend · up to ${createSeats} players`}</b> · <b>{winPoints === 21 ? "Long 21" : "Classic 15"}</b>
								</span>
								<button type="button" className="cm-create"
									onClick={() => { setShowCreateModal(false); handleCreate(createOpp === "ai", createVariant, winPoints, createSeats); }}>
									Create Game
								</button>
							</div>
						</CreateModal>
					)}

					{/* Mobile-only tab bar: pick one section to show in the single-column layout. */}
					<LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
						{ key: "open", label: "Open", count: openGames.length || null },
						{ key: "active", label: "Active", count: activeGames.length || null },
						{ key: "history", label: "History", count: historyGames.length || null },
					]} />

					<div className={`lobby-grid lby-cols tab-${lobbyTab}`}>
					<div className="browser-section lby-col-open">
						<LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
						{browserLoading && openGames.length === 0 ? (
							<div className="lby-empty"><span className="lby-spinner lby-spinner-sm" />Loading…</div>
						) : openGames.length === 0 ? (
							<div className="lby-empty">No open games — create one.</div>
						) : (
							<div className="lby-list">
								{openGames.map(g => (
									<div key={g.id} className="lby-card">
										<div className="lby-card-info">
											<LobbyOpenTitle game={g} myId={myId} defaultMaxPlayers={4} />
											<div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
										</div>
						<div className="lby-card-actions">
							<LobbyOpenActions state={seatStateOf(g, myId)}
								onReturn={() => handleContinue(g.id)} onJoin={() => handleJoinGame(g.id)}
								onLeave={() => handleLeaveSeat(g.id)} onCancel={() => handleCancel(g.id)} />
						</div>
									</div>
								))}
							</div>
						)}
					</div>
					<div className="browser-section lby-col-history">
						<LobbySectionHd title="History" note={`${historyGames.length} finished`} />
						{(!authUser || authUser.guest) ? (
							<div className="lby-empty">Log in to keep your game history.</div>
						) : historyGames.length === 0 ? (
							<div className="lby-empty">No finished games yet.</div>
						) : (
							<div className="lby-list">
								{historyShown.map(g => {
									// History is always YOUR games, so drop the repeated "you" —
									// just show Won/Lost vs the opponent(s) and the score (yours-theirs).
									const me = g.players.find(p => p.is_you);
									const opps = g.players.filter(p => !p.is_you);
									const oppNames = opps.map(o => displayName(o.name)).join(", ") || "—";
									const myScore = me ? me.score : 0;
									const oppScore = opps.length ? Math.max(...opps.map(o => o.score)) : 0;
									return (
									<div key={g.id} className="lby-card lby-card-hist">
										<div className="lby-card-info">
											<div className="lby-card-title">
												<span className={`hist-result ${g.you_won ? "won" : "lost"}`}>{g.you_won ? "Won" : "Lost"}</span>
												<span className="hist-scores">vs {oppNames} <span className="hist-score-num">{myScore}–{oppScore}</span></span>
											</div>
											<div className="lby-card-meta">{timeAgo(g.finished_at)}{g.win_points === 21 ? " · Long (21)" : ""}<LobbyBotTier tier={g.ai_difficulty} labels={AI_TIER_LABELS} /></div>
										</div>
										<div className="lby-card-actions">
											<LobbyAction kind="secondary" onClick={() => enterReview(g.id)}>Review</LobbyAction>
										</div>
									</div>
									);
								})}
								{historyMore}
							</div>
						)}
					</div>

					{(() => {
						// All in-progress games (yours + others'). Yours pinned to the top;
						// each sub-list is already updated_at-desc from the backend.
						const hasMe = g => [g.player1_id, g.player2_id, g.player3_id, g.player4_id].includes(myId);
						const lenGames = activeGames;
						const mine = lenGames.filter(hasMe);
						const others = lenGames.filter(g => !hasMe(g));
						const ordered = [...mine, ...others];
						return (
							<div className="browser-section lby-col-active">
								<LobbySectionHd title="Active Games" note={`${ordered.length} in progress`} />
								{ordered.length === 0 ? (
									<div className="lby-empty">No games in progress.</div>
								) : (
								<div className="lby-list">
									{ordered.map(g => {
										// 2-4 seats; show the full matchup, marking your own seat.
										const seats = [
											[g.player1_id, g.player1_name], [g.player2_id, g.player2_name],
											[g.player3_id, g.player3_name], [g.player4_id, g.player4_name],
										].filter(([id, nm]) => id || nm);
										const isMine = seats.some(([id]) => id === myId);
										const turnName = (seats.find(([id]) => id === g.turn) || [])[1] || null;
										return (
											<div key={g.id} className="lby-card">
												<div className="lby-card-info">
													<LobbyMatchup seats={seats.map(([id, nm]) => (
														{ name: displayName(nm), you: id === myId }))} />
													<div className="lby-card-meta">{g.id} · {timeAgo(g.updated_at)}<LobbyBotTier tier={g.ai_difficulty} labels={AI_TIER_LABELS} /></div>
												</div>
												<div className="lby-card-actions">
													{isMine ? (
														<>
															{g.turn === myId
																? <TurnBadge mine>Your turn</TurnBadge>
																: <TurnBadge>Their turn</TurnBadge>}
															<LobbyAction onClick={() => handleContinue(g.id)}>Resume</LobbyAction>
														</>
													) : (
														<TurnBadge>{turnName ? `${displayName(turnName)}'s turn` : "In progress"}</TurnBadge>
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
				</div>
				{rulesModalEl}
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);

	// Waiting screen — the SHARED kit (`WaitingRoom` in shared/lobby.jsx). It used to
	// be a hand-built panel here: a click-to-copy ROOM CODE, a `<ul>` of seats, and a
	// "← Back to Menu" that no other game spelled the same way.
	if (screen === "spender" && spenderScreen === "waiting") {
		return (
			<>
				<style>{css}</style>
				<div className="app" style={{ "--lby-accent": GAME_ACCENTS.spender }}>
					<WaitingRoom
						game="spender" roomId={roomId}
						players={roomData?.players} hostId={roomData?.host} myId={myId}
						min={2} max={roomData?.max_players || 4}
						note="The host deals once everyone is in."
						user={authUser}
						onLeave={goToMenu}
						onRules={() => setShowRules(true)}
						onStart={handleStart} />
					{rulesModalEl}
					{toast && <div className="toast">{toast}</div>}
				</div>
			</>
		);
	}

	// Winner screen (held back 0.5s after the game ends — see the resultReady effect —
	// so the final board is visible for a beat before the result is revealed).
	if (screen === "spender" && spenderScreen === "game" && game?.phase === "over" && !reviewing && !puzzling && resultReady) {
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
							{/* Review needs the server's per-turn snapshots — a local save has none.
							    "View board" drops the overlay so the final position is inspectable. */}
							{offline
								? <button className="btn btn-gold" onClick={() => setResultReady(false)}>View board</button>
								: <button className="btn btn-gold" onClick={() => enterReview(roomId)}>Review game</button>}
							{offline
								? <button className="btn btn-outline" onClick={exitOfflineToHub}>Back to Local Games</button>
								: <button className="btn btn-outline" onClick={() => {
									try { localStorage.removeItem("spender_roomId"); } catch {}
									setReviewing(false);
									setReplaySnapshots(null); setReplayTurn(null);
									pushPath(buildPath("spender"));   // leave the finished room's URL
									goSpender("browser"); setRoomData(null); setRoomId(""); disconnect();
									fetchGames(authUser);
								}}>
									Back to lobby
								</button>}
						</div>
					</div>
				</div>
			</>
		);
	}

	// Game screen
	if (screen === "spender" && spenderScreen === "game" && game) return (
		<>
			<style>{css}</style>
			<div className="app game-screen">
				<div className="game-nav">
					{puzzling
						? <button className="btn btn-ghost btn-sm" onClick={exitPuzzle}>← Puzzles</button>
						: reviewChrome
						? <button className="btn btn-ghost btn-sm" onClick={() => { setReplayTurn(null); setReviewing(false); setResultReady(true); }}>← Back to Results</button>
						/* Offline: "menu" is the Local Games hub, and leaving just closes the
						   game (the save persists) — no socket to tear down, no server forfeit.
						   `local` re-words both rows; see GameMenu in shared/lobby.jsx. A JSX
						   `{/* … *​/}` comment is not legal here: this is the expression half of
						   a ternary, not JSX children. */
						: <GameMenu local={!!offline}
								onLeave={offline ? exitOfflineToHub : goToMenu}
								onRules={() => setShowRules(true)}
								onAbandon={() => setConfirmAbandon(true)} />}
					<span className="game-nav-title">Spender{puzzling ? " — Puzzle" : reviewChrome ? " — Review" : ""}</span>
					{puzzling
						? <div className="puzzle-nav-aids">
								<button className="btn btn-ghost btn-sm" onClick={() => setPuzHintOpen(true)} disabled={puzSolved}>💡 Hint</button>
								<button className="btn btn-ghost btn-sm" onClick={() => setPuzAnswerOpen(true)} disabled={puzSolved}>Answer</button>
								<button className="btn btn-ghost btn-sm" onClick={restartPuzzle} title="Restart puzzle">↻</button>
									<button className="btn btn-ghost btn-sm" onClick={prevPuzzle} disabled={!puzHistory.length} title="Back to the previous puzzle">◀ Prev</button>
									<button className="btn btn-ghost btn-sm" onClick={nextPuzzle} title="Skip to next puzzle">Next ▸</button>
							</div>
						: reviewChrome
						? <span style={{ width: 64 }} />
						: <span style={{ width: 40 }} />}
				</div>
				<div className="game-nav-spacer" />
				<div className="game">
					<div className="game-main">

						<div className="action-bar">
								{reviewing ? renderReplayBar() : puzzling ? renderPuzzleBar() : (<>
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
												<span className="log-turn">{isPrimary ? turnIdx + 1 : ""}</span>
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

				{puzzling && puzHintOpen && (
					<div className="modal-backdrop" onClick={() => setPuzHintOpen(false)}>
						<div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 320, textAlign: "center" }}>
							<h3 style={{ marginTop: 0 }}>💡 Hint</h3>
							<p className="puzzle-hint-word">{(() => {
								const t = puzzle?.steps?.[puzStep]?.move?.type;
								return t === "take_gems" ? "Take gems" : t === "reserve" ? "Reserve" : "Buy";
							})()}</p>
							<button className="btn btn-ghost btn-sm" style={{ width: "100%" }} onClick={() => setPuzHintOpen(false)}>Close</button>
						</div>
					</div>
				)}

				{puzzling && puzAnswerOpen && (
					<div className="modal-backdrop" onClick={() => setPuzAnswerOpen(false)}>
						<div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 320 }}>
							<h3 style={{ marginTop: 0 }}>Solution</h3>
							<ol className="puzzle-answer-list">
								{(puzzle?.steps || []).filter(s => s.is_hero).map((s, i) => (
									<li key={i}>{moveLabel(s.move)}</li>
								))}
							</ol>
							<p className="puzzle-answer-note">S's replies in between are forced. Close this and play the line, or restart.</p>
							<button className="btn btn-ghost btn-sm" style={{ width: "100%" }} onClick={() => setPuzAnswerOpen(false)}>Close</button>
						</div>
					</div>
				)}

				{puzzling && puzSolved && !puzHideOverlay && (
					<div className="puzzle-won">
						<div className="puzzle-won-card">
							<div className="puzzle-won-title">Solved!</div>
							<div className="puzzle-won-sub">
								{puzzle?.kind === "advantage"
									? <>The only move: <b>{moveLabel(puzzle.steps[0].move)}</b> · N eval <b>{fmtEval(puzMoveEval(puzzle.steps[0].move) ?? puzzle?.meta?.best_eval)}</b></>
									: <>You beat {aiPersona(puzzle?.opponent || "S")}, {game.players?.[myId] ? totalPoints(game.players[myId].purchased, game.players[myId].nobles) : 0}{" – "}{game.players?.[PUZ_OPP] ? totalPoints(game.players[PUZ_OPP].purchased, game.players[PUZ_OPP].nobles) : 0}</>}
								{puzAttempts > 1 ? `  ·  ${puzAttempts} attempts` : ""}
							</div>
							<div className="puzzle-won-btns">
								<button className="btn btn-gold" onClick={nextPuzzle}>Next ▸</button>
								<button className="btn btn-outline" onClick={() => setPuzHideOverlay(true)}>Return</button>
								{!!puzHistory.length && <button className="btn btn-outline" onClick={prevPuzzle}>◀ Prev</button>}
								<button className="btn btn-outline" onClick={exitPuzzle}>Exit</button>
							</div>
						</div>
					</div>
				)}

				{puzzling && puzFailed && !puzHideOverlay && (
					<div className="puzzle-fail">
						<div className="puzzle-fail-card">
							<div className="puzzle-fail-title">✗ Wrong Move</div>
							<div className="puzzle-fail-sub">
								{puzzle?.kind === "advantage"
									? <>You played <b>{moveLabel(puzFailMove)}</b> · N eval <b>{fmtEval(puzMoveEval(puzFailMove))}</b> — not the move that holds the advantage. Try again.</>
									: <>That isn't the solution — puzzle failed. There's exactly one winning line.</>}
							</div>
							<div className="puzzle-won-btns">
								<button className="btn btn-gold" onClick={restartPuzzle}>↻ Try again</button>
								<button className="btn btn-outline" onClick={() => setPuzHideOverlay(true)}>Return</button>
								{!!puzHistory.length && <button className="btn btn-outline" onClick={prevPuzzle}>◀ Prev</button>}
								<button className="btn btn-outline" onClick={exitPuzzle}>Exit</button>
							</div>
						</div>
					</div>
				)}

				{flyers.length > 0 && (
					<div className="fly-layer">
						{flyers.map(f => f.kind === "card" ? (
							<div key={f.id} className="fly-card" ref={el => animateFlyer(el, f)} style={{
								left: f.x, top: f.y, width: f.w, height: f.h, borderColor: GEM_HEX[f.color],
								"--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0, "--s1": f.s1,
								animationDelay: `${f.delay}ms`,
							}}>
								<span className="fly-card-pt">{f.points || ""}</span>
								<span className="fly-card-dot" style={{ background: GEM_HEX[f.color] }} />
							</div>
						) : (
							<div key={f.id} className="fly-gem" ref={el => animateFlyer(el, f)} style={{
								left: f.x - f.size / 2, top: f.y - f.size / 2, width: f.size, height: f.size,
								"--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0, "--s1": f.s1,
								animationDelay: `${f.delay}ms`,
							}}>
								<GemToken color={f.color} size={f.size} />
							</div>
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
							<h3>{offline ? "Delete Game?" : "Abandon Game?"}</h3>
							<p>{offline
								? "This deletes the local save. Nothing is recorded — offline games never leave this device."
								: "This counts as a loss for you. Your opponent will be awarded the win."}</p>
							<div style={{ display: "flex", gap: 10, marginTop: 8 }}>
								<button className="btn btn-danger" onClick={handleAbandon}>{offline ? "Yes, Delete" : "Yes, Abandon"}</button>
								<button className="btn btn-ghost" onClick={() => setConfirmAbandon(false)}>Cancel</button>
							</div>
						</div>
					</div>
				)}

				{rulesModalEl}
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
