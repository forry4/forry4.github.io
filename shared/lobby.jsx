// Shared lobby kit for the Forrest Games site — the single source of truth for every
// game's lobby CHROME (top header bar + its buttons, section headers, game-card rows,
// empty states, loading screen, turn/status badges). Extracted so the four games
// (Spender, Castles of Crimson, Where Wolf?, Spender Duel) share one layout grammar
// instead of drifting apart.
//
// TOKEN-DRIVEN: everything reads var(--surface)/var(--border)/… so a game keeps its base
// palette, and --lby-accent (per-game, falls back to --gold) threads the game's identity
// color through the title, section labels, badges, and hovers — matching the home cards.
// Set it on the lobby root:  style={{ "--lby-accent": "#d6454b" }}
//
// Prepend `lobbyCss` to a screen's own CSS, same as baseCss.
// Components are self-contained (the header renders its OWN back/rules buttons via
// .lby-back/.lby-headbtn) so the kit never depends on a game's button system.
import React, { useState, useRef, useEffect } from "react";

// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _lobbyCssText from "./lobby.lobby-css.css?inline";
import _lobbyPageCssText from "./lobby.lobby-page-css.css?inline";
import _createModalCssText from "./lobby.create-modal-css.css?inline";
import _lobbyCreateRowCssText from "./lobby.lobby-create-row-css.css?inline";
import _gameMenuCssText from "./lobby.game-menu-css.css?inline";
import _rulesModalCssText from "./lobby.rules-modal-css.css?inline";
import _waitingRoomCssText from "./lobby.waiting-room-css.css?inline";
import { GAME_EMBLEM } from "./emblems.jsx";
import { GAME_INFO } from "./catalog.js";
import { buildPath, navigateTo } from "./router.js";

// TWO FILES, ONE STRING. `lobby.lobby-css.css` is the lobby's chrome and layout — the
// bar, the rows, the column grid, the tab bar — and it is what every game already
// appends. `lobby.lobby-page-css.css` is the PAGE the lobby sits on: the ambient
// ground and the identity band, which arrived later and would otherwise have needed
// an import added to seven game screens to say the same thing seven times.
export const lobbyCss = _lobbyCssText + _lobbyPageCssText;

// ─── The kit's own glyphs ────────────────────────────────────────────────────
// Line art on the site's one drawing grid (24x24, 1.5 stroke, round joins — see
// shared/emblems.jsx), NOT emoji. The Rules button wore 📖 and the Dissonance
// scorecard 🧮, which is the exact thing the home menu's side-feature row was
// rebuilt to remove: an emoji arrives as a different typeface, a different weight
// and often a different COLOUR SCHEME on every OS, so a hand-set page gets three
// stickers pasted onto it. These inherit currentColor, so they take the accent the
// button is already painted in.
export const RULES_GLYPH = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true" focusable="false">
		<path d="M12 7.3C10.6 6 8.7 5.3 6.6 5.3H4.4v12.3h2.2c2.1 0 4 .7 5.4 2" />
		<path d="M12 7.3c1.4-1.3 3.3-2 5.4-2h2.2v12.3h-2.2c-2.1 0-4 .7-5.4 2" />
		<path d="M12 7.3v12.3" />
	</svg>
);
export const SCORECARD_GLYPH = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true" focusable="false">
		<rect x="4.6" y="3.8" width="14.8" height="16.4" rx="2" />
		<path d="M4.6 9h14.8M12 9v11.2" />
	</svg>
);

// THE IDENTITY IN THE TOP-RIGHT, and it is the shell's lockup, not a seventh
// invention. The home menu reads "GUEST · Harness" — a role label in dim
// letterspaced small caps, then the name in the brighter serif — beside an EXIT chip.
// The seven lobbies each hand-built their own version of the right rail: five passed a
// bare `<span className="lby-head-name">`, one passed the string "Guest", and the
// result was one dim letterspaced word floating in the corner in the LABEL style, with
// its label missing. A registered player has no role word, so they get the name alone.
//
// A REGISTERED name is the way into the profile (shared/Profile.jsx), from every
// lobby at once — it navigates through the router rather than a callback, so no
// lobby has to wire it. Pass `profile={false}` where leaving would abandon
// something: at a board, in a waiting room, and in the offline hub, which has no
// server to ask. A guest's name is never a link: guests have no profile.
export function LobbyUser({ user, profile = true }) {
	if (!user?.name) return null;
	const name = <span className="lby-head-name">{user.name}</span>;
	if (profile && !user.guest) return (
		<button type="button" className="lby-ident lby-ident-link" title="Your profile"
			onClick={() => navigateTo("profile")}>{name}</button>
	);
	return (
		<span className="lby-ident">
			{user.guest && <span className="lby-ident-kind">Guest</span>}
			{name}
		</span>
	);
}

// Full-width flush top bar. Renders its own back + rules buttons (uniform across games);
// `user` is the right-side slot (name / guest badge). rulesLabel lets Duel say "How to Play".
// `menu` is the IN-GAME shape and takes precedence over the buttons: every game
// shows a single ☰ dropdown once you are at a board, never a row of Back/Rules
// buttons. Pass `menu={<GameMenu onLeave={…} onRules={…} />}` there and `onBack`/`onRules` in
// the lobby, where a plain Back is right.
export function LobbyHeader({ onBack, backLabel = "← Back", title, onRules, rulesLabel = "Rules", user, menu }) {
	return (
		<div className="lby-header">
			<div className="lby-head-left">
				{menu || <>
					{onBack && <button className="lby-back" onClick={onBack}>{backLabel}</button>}
					{onRules && <button className="lby-headbtn" onClick={onRules}>{rulesLabel}</button>}
				</>}
			</div>
			<div className="lby-title">{title}</div>
			<div className="lby-head-right">{user}</div>
		</div>
	);
}

// ─── The lobby's identity band ───────────────────────────────────────────────
// THE PAGE THE PLAYER LANDED ON HAS TO NAME ITSELF THE WAY THE CARD THEY CLICKED
// DID. Every lobby used to open with the create row floating alone in the middle of
// an otherwise empty page, under a top bar carrying a small centred title — so the
// emblem, the accent wordmark and the player-count pill that had just been used to
// choose the game all vanished at the moment of arrival, and the first thing on the
// page was a button.
//
// ONE ROW, not a hero block: identity on the left, the create row on the right. It
// occupies the height the create row already spent, so the lists do not move down —
// which matters, because a lobby's job is the lists and this page has to hold three
// columns above the fold on an 800px laptop.
//
// `game` is the catalogue id (shared/catalog.js), and it is the ONLY prop that
// matters: the emblem, the name and the player range all come from that one entry,
// so a lobby cannot drift from its home card the way a hand-passed title would.
// `title`/`players` exist for a screen that is a lobby but not a catalogue game.
export function LobbyHero({ game, title, players, children }) {
	const info = GAME_INFO[game] || {};
	const name = title || info.name || "";
	const seats = players || info.players || null;
	return (
		<div className="lby-hero">
			<div className="lby-hero-id">
				{GAME_EMBLEM[game] && (
					<span className="lby-hero-emblem" aria-hidden="true">{GAME_EMBLEM[game]}</span>
				)}
				<span className="lby-hero-text">
					<h1 className="lby-hero-name">{name}</h1>
					{seats && <span className="lby-hero-seats">{seats}</span>}
				</span>
			</div>
			{children && <div className="lby-hero-actions">{children}</div>}
		</div>
	);
}

// ─── "There is more below this column" ───────────────────────────────────────
// A lobby column scrolls INSIDE ITSELF at the widest tier, so its last card is cut
// wherever the cap lands — through a Won badge, through the x-height of "21h ago".
// Something has to say that is a scroll and not a clipping bug, and the two CSS-only
// answers were both tried and both failed:
//
//   * a `mask-image` fade on `.lby-list` applies to the ELEMENT, and a list that does
//     not overflow is simply SHORT — so a two-card Open column had its second card
//     faded out of existence, bottom border and all, on every lobby at 1920. A card
//     with no bottom edge and clear page under it is worse than a cut one.
//   * a visible scrollbar. It is invisible in exactly the cases that matter: overlay
//     scrollbars (macOS, and every headless capture) paint nothing until a scroll is
//     in progress, so the cut card still stands alone with bare page beside it.
//
// CSS cannot ask whether a box overflows, so this measures it. `data-more` goes on any
// `.lby-list` that has content below the fold and comes off the moment it is scrolled
// to the end, so the fade is only ever over something.
//
// A lobby opts in with one line, the same discipline as `useLastDifficulty`, and
// `shared/tests/test_lobby_kit.py` fails the next lobby that lands without it — a game
// that forgets renders a perfectly normal-looking column that simply lies about its
// own edge.
export function useListFade() {
	useEffect(() => {
		// THE COLUMN'S HEIGHT IS MEASURED, NOT GUESSED. It used to be
		// `calc(100vh - <a number>)`, and the number is the list's distance from the top
		// of the page — which is not a constant: the identity band steps up at 1500px,
		// its create row is one line or two depending on the width, and a game with a
		// sixth control is taller again. Every value tried was wrong at some tier: 300
		// stopped the column ~78px short and hid a row for nothing; 256 and 268 made
		// the PAGE 20-52px taller than the viewport, so an outer scrollbar appeared
		// over a layout whose whole premise is that the columns scroll internally, and
		// dragging it revealed only black. Reading the list's own `top` is exact at
		// every tier and needs no ladder of numbers.
		// It writes a per-element custom property rather than a height, so the
		// stylesheet keeps the rule (and `--lby-list-max` keeps working as the per-game
		// override) and this only supplies the default.
		const PAGE_FOOT = 44;   // `.lby-page-in`'s bottom padding
		const size = (el) => {
			const top = el.getBoundingClientRect().top + window.scrollY;
			const avail = Math.round(window.innerHeight - top + window.scrollY - PAGE_FOOT);
			el.style.setProperty("--lby-list-fit", `${Math.max(160, avail)}px`);
		};
		const mark = (el) => {
			size(el);
			const more = el.scrollHeight - el.clientHeight - el.scrollTop > 2;
			if (more) el.setAttribute("data-more", "1");
			else el.removeAttribute("data-more");
		};
		const lists = [...document.querySelectorAll(".lby-cols .lby-list")];
		lists.forEach(mark);
		const onScroll = (e) => mark(e.currentTarget);
		lists.forEach((el) => el.addEventListener("scroll", onScroll, { passive: true }));
		// A column's height changes with the VIEWPORT (the cap is a vh) and with its
		// own content (History reveals another page as you reach the end), so one
		// mount-time measurement is not enough. ResizeObserver covers both; the window
		// listener covers a viewport change that does not resize the list itself.
		const ro = typeof ResizeObserver === "function"
			? new ResizeObserver(() => lists.forEach(mark)) : null;
		lists.forEach((el) => ro?.observe(el));
		const onResize = () => lists.forEach(mark);
		window.addEventListener("resize", onResize);
		return () => {
			lists.forEach((el) => el.removeEventListener("scroll", onScroll));
			ro?.disconnect();
			window.removeEventListener("resize", onResize);
		};
	});
}

// The relative time on every lobby row's meta line. Six games each carry a private,
// byte-identical copy of this; Where Wolf never had one at all, which is why its rows
// were the only ones that did not say how old a room was. Exported here so the seventh
// did not become a seventh copy — the other six are the obvious next thing to delete.
export function timeAgo(ts) {
	if (!ts) return "";
	const diff = Math.floor(Date.now() / 1000) - ts;
	if (diff < 60) return "just now";
	if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
	if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
	return `${Math.floor(diff / 86400)}d ago`;
}

// Section header row: a micro uppercase accent label + an optional muted note.
//
// THE NOTE IS A COUNT AND IT IS SHOWN AT ZERO TOO. It was suppressed when the list was
// empty, which meant the header's right-hand anchor vanished in exactly the state a new
// player sees first: the accent rule ran to a dead end, and the row's composition
// changed between the two states of the same screen for no reason the reader can see.
// "0 waiting" is a fact and reads as one. (The phone TAB bar still hides a zero — a
// numeric badge showing 0 is noise, a sentence saying it is information; they are
// different objects and the difference is deliberate.)
export function LobbySectionHd({ title, note }) {
	return (
		<div className="lby-section-hd">
			<div className="lby-section-title">{title}</div>
			{note != null && <span className="lby-muted">{note}</span>}
		</div>
	);
}

// THE MATCHUP LINE — who is in this game, one seat per line, with your own seat
// marked. One renderer for every lobby, because there were two treatments and the
// split was an accident of which endpoint a game happened to have: Spender and
// Castles of Crimson list ALL in-progress games (a public `list_active_games`), so a
// row can be somebody else's and they had to name both seats; the other five list
// only `/games/mine`, so each concluded that naming yourself in your own list was
// noise and printed the OPPONENT alone. It is not noise — with a few games on the go,
// the Active column is the only place the seat you are sitting in is written down,
// and "Bot 1" on one site and "Aurelia (you) vs Bot 1" on another read as two
// products. A game hands over seats; the kit decides how a matchup looks.
//
// `seats` = [{ name, you }] in SEAT order (not you-first): the order is a fact about
// the table, and re-sorting it would make the same game read differently to each
// player. A missing name renders as a placeholder rather than an empty line — an
// unfilled seat is a real state (a room mid-join), not a bug to hide.
export function LobbyMatchup({ seats, placeholder = "…" }) {
	return (
		<div className="lby-card-title matchup">
			{(seats || []).map((s, i) => (
				<div key={i}>
					{i > 0 && <span className="lby-vs">vs</span>}
					{s.name || placeholder}
					{s.you && <span className="lby-you"> (you)</span>}
				</div>
			))}
		</div>
	);
}

// THE OPEN-ROW TITLE — one treatment for every lobby. The first line answers
// the two things a player needs before choosing an action: whose table it is
// and how many seats are occupied. Keep the display vocabulary here so a new
// game cannot quietly invent "is waiting", "your fight", or a game-specific
// noun that makes the shared Open Games column read differently.
//
// Backends have accumulated three equivalent count shapes over time:
// `player_count`, `players`, and `player_ids`. Prefer the explicit count, then
// the ids, then the legacy player-name columns. `max_players` is the source of
// truth for the cap, with a two-seat default for older two-player payloads.
export function LobbyOpenTitle({ game, myId, defaultMaxPlayers = 2, fallbackName = "Player" }) {
	const hostName = game?.host_name || game?.player1_name || fallbackName;
	const rawCount = game?.player_count ?? game?.players;
	const explicitCount = typeof rawCount === "number" && Number.isFinite(rawCount)
		? rawCount
		: typeof rawCount === "string" && rawCount.trim() && Number.isFinite(Number(rawCount))
			? Number(rawCount)
			: null;
	const idsCount = Array.isArray(game?.player_ids)
		? game.player_ids.filter(Boolean).length
		: null;
	const namedCount = ["player1_name", "player2_name", "player3_name", "player4_name"]
		.filter((key) => game?.[key]).length;
	const count = Math.max(1, explicitCount ?? idsCount ?? namedCount ?? 1);
	const max = Number(game?.max_players) || defaultMaxPlayers;
	return (
		<div className="lby-card-title">
			{game?.host_id === myId ? "Your game" : `${hostName}'s game`}
			<span className="lby-seats">{count}/{max}</span>
		</div>
	);
}

// WHICH BOT IT WAS — on the Active row and on the History row, in every lobby.
//
// A row that says "Aurelia (you) vs Nina (AI)" names the seat and not the
// STRENGTH, and the strength is what the reader actually wants back: History is
// a record of who you can beat, and an Active list with two vs-bot games in it
// is two different games. Every lobby already had the fact — each game's
// `save_game` has stored the tier beside the seat since the day it got a bot —
// and no lobby printed it anywhere but the create modal that chose it.
//
// `tier` is the WIRE id (`state_ai_tier` on the server: the tier a saved room
// actually played, `null` for a human table) and `labels` is the game's own
// id -> display-name map. The split is deliberate and is the same split the
// create modal already lives with: the id is the server's, the words are the
// game's, and they are genuinely different words — Spender's four variant codes
// read Easy/Medium/Hard/Expert, and Dontminion's two bots are not difficulties
// at all but NAMES (Random, Money+). A shared component that title-cased the id
// would print "Bmplus". Title-casing is only the FALLBACK, for an id the map
// does not have — a tier the game has since retired, which is still what an old
// saved row was genuinely played at (Castles of Crimson's server keeps a
// `normal` its picker has never shown). Printing the raw id there is honest;
// printing it lowercase in a row of proper nouns is just untidy.
//
// It renders NOTHING for a human game, which is what makes it safe to put on
// every row unconditionally rather than behind a per-game `g.ai_player &&`.
// The separator is the component's, not the caller's: six lobbies appending
// `" · "` by hand is six chances to leave one out, and a leading separator on
// an absent chip is a meta line that ends in a dangling middot.
export function LobbyBotTier({ tier, labels }) {
	if (!tier) return null;
	const label = labels?.[tier] || String(tier).replace(/^./, (c) => c.toUpperCase());
	return (
		<span className="lby-bot-tier" title={`Played against the ${label} bot`}>
			{" · "}{label} AI
		</span>
	);
}

// A room you have joined but which has NOT started is waiting, not active. It
// already appears in Open — with a Cancel if you host it — so listing it again
// as in-progress offers a Resume that just drops you back in the waiting room.
// Only Duel filtered; Spender, CoC, Dontminion and Dissonance all showed waiting
// rooms as active, which is the kind of thing that stays wrong in four places
// at once precisely because each lobby built its own list.
export function notWaiting(games) {
	return (games || []).filter((g) => g.status !== "open");
}

// ─── "Am I already sitting at this table?" ───────────────────────────────────
// AN OPEN-GAME ROW HAS FOUR MEANINGS AND EVERY LOBBY COULD ONLY TELL TWO APART.
// Each one asked `g.host_id === myId` and branched Return/Cancel against Join —
// so a player who had joined somebody else's table and then gone back to the
// lobby was offered **Join**, on a seat they already held. The server is right to
// refuse that (a `join` onto an occupied seat with no proof of identity is a seat
// takeover, so it answers "seat already taken — reconnect to rejoin"), which made
// the one row that could have carried them back in the one row that could not:
// reported as "they went back to the menu and now they can't play."
//
// The four states, and what each one is FOR:
//   "host"     — your table. Return, and Cancel to give it back.
//   "seated"   — someone else's table you are already in. Return, via the
//                per-seat token (`reconnect`), which is the only thing that
//                re-enters an occupied seat.
//   "full"     — every seat taken and not by you. Nothing to offer.
//   "joinable" — a free seat. Join.
//
// `player_ids` is the field the seat test needs and it arrived with this change,
// so the fallback matters: an OLD bundle against a new server, or a new bundle
// against a server that has not redeployed, reads no ids and lands on the
// previous behaviour rather than on a wrong answer. That is the expand half of
// expand/contract — the server ships the field first, this reads it second.
export function seatStateOf(g, myId) {
	if (!g || !myId) return "joinable";
	if (g.host_id && g.host_id === myId) return "host";
	const ids = Array.isArray(g.player_ids) ? g.player_ids.filter(Boolean) : [];
	if (ids.includes(myId)) return "seated";
	const max = Number(g.max_players) || 0;
	const seated = Number(g.player_count) || ids.length || 1;
	if (max && seated >= max) return "full";
	return "joinable";
}

// The one action button a lobby row gets. Extracted because the five lobbies had
// drifted to four different styles for the SAME Resume button (btn / btn-gold /
// btn-outline / btn-outline btn-sm), and a class name copied per game is a
// difference nobody chose.
//
// IT IS THE KIT'S OWN BUTTON NOW, NOT `btn btn-gold`. `.btn-gold` is the SITE's gold,
// and a row of them down a crimson game's Active column said "Spender" fourteen times
// on a page whose whole job is to be one game's. `.lby-act` reads `--lby-accent` the
// way every other thing in this kit does, and is sized for a list row rather than for
// a form (the `.btn` scale left a 40px slab beside a 17px title).
//
// Three kinds, and the distinction is what the row is FOR: `primary` is the one thing
// you came to do (Resume / Join), `secondary` is available but not the point (Review /
// Return), `danger` gives back the seat (Cancel / Abandon).
export function LobbyAction({ kind = "primary", onClick, children, title }) {
	return (
		<button type="button" className={`lby-act lby-act-${kind}`} onClick={onClick} title={title}>
			{children}
		</button>
	);
}

// ─── An Open row's actions ───────────────────────────────────────────────────
// THE FOUR ANSWERS, IN ONE PLACE, because every lobby hand-wrote two of them and
// the two it left out are the ones that strand a player. Nine copies of
//
//     {g.host_id === myId ? <>Return Cancel</> : <Join/>}
//
// is nine copies of the same wrong branch: a table you are ALREADY SEATED AT is
// not yours and is not joinable, and the Join it was offered is refused by the
// server as a seat takeover ("seat already taken — reconnect to rejoin"). Return
// there goes through the per-seat token (`reconnect`), which is the only action
// that re-enters an occupied seat.
//
// `onCancel` is optional: a game with no cancel endpoint renders the host's row
// with Return alone rather than a button that cannot work. A non-host who is
// already seated gets the same Return path plus an explicit Leave action. Leaving
// the lobby itself is never destructive; this button is the only thing that
// releases a pre-start seat.
export function LobbyOpenActions({ state, onReturn, onJoin, onCancel, onLeave }) {
	if (state === "host") return (
		<>
			<LobbyAction kind="secondary" onClick={onReturn}>Return</LobbyAction>
			{onCancel && <LobbyAction kind="danger" onClick={onCancel}>Cancel</LobbyAction>}
		</>
	);
	// "You are in this room already" — the row that used to say Join.
	if (state === "seated") return (
		<>
			<LobbyAction kind="secondary" onClick={onReturn}>Return</LobbyAction>
			{onLeave && <LobbyAction kind="danger" onClick={onLeave}>Leave</LobbyAction>}
		</>
	);
	// A full table is not an error and not an invitation: say so instead of
	// offering a Join the server will refuse with "room full".
	if (state === "full") return <TurnBadge>Table full</TurnBadge>;
	return <LobbyAction onClick={onJoin}>Join</LobbyAction>;
}

export function LobbyEmpty({ children }) {
	return <div className="lby-empty">{children}</div>;
}

// The mobile-only segmented bar that picks WHICH lobby column shows once the grid
// has collapsed to one. Spender, Duel and Dontminion each carried a near-verbatim
// copy of this (identical gap/radius/padding/flex/type scale — only the accent and
// a couple of alpha values differed), and CoC never got one at all despite having
// the same three columns.
//
// `tabs` = [{ key, label, count? }]; `key` must match the column's
// `lby-col-<key>` class, because the SHOW/HIDE is pure CSS off `tab-<key>` on the
// grid (see .lby-cols in the stylesheet) rather than conditional rendering — a
// hidden column stays mounted, so its scroll position and this list's paging
// survive tab switches.
export function LobbyTabs({ tabs, value, onChange }) {
	return (
		<div className="lby-tabs" role="tablist">
			{tabs.filter(Boolean).map((t) => (
				<button key={t.key} type="button" role="tab" aria-selected={value === t.key}
					className={`lby-tab${value === t.key ? " sel" : ""}`}
					onClick={() => onChange(t.key)}>
					{t.label}
					{t.count != null && <span className="lby-tab-count">{t.count}</span>}
				</button>
			))}
		</div>
	);
}

// Centered spinner + label — the shared game-entry loading screen.
export function LobbyLoading({ label = "Loading…" }) {
	return (
		<div className="lby-loading">
			<span className="lby-spinner" />
			<span>{label}</span>
		</div>
	);
}

// Turn/status pill. mine=true → accent "your turn"; else the muted "their turn / waiting".
export function TurnBadge({ mine, children }) {
	return <span className={`lby-badge ${mine ? "lby-badge-turn" : "lby-badge-wait"}`}>{children}</span>;
}

// Stale-while-revalidate cache for the lobby lists — render the last-known lists INSTANTLY
// on a repeat open, then let the fetch refresh them. localStorage + JSON, namespaced by
// game (ns) + user/guest id (scope) + list key, so different accounts on one device never
// see each other's lists (history is user-specific). All best-effort — any failure is a
// no-op fallback, never a throw.
export function readLobbyCache(ns, scope, key, fallback) {
	try {
		const v = localStorage.getItem(`lbyc.${ns}.${scope}.${key}`);
		return v ? JSON.parse(v) : fallback;
	} catch { return fallback; }
}
export function writeLobbyCache(ns, scope, key, val) {
	try { localStorage.setItem(`lbyc.${ns}.${scope}.${key}`, JSON.stringify(val)); } catch {}
}

// ─── Finish-time lobby refresh ──────────────────────────────────────────────
// A game you just finished must not still be sitting under Active when you get
// back to the lobby. The lists above render from the cache, and that cache was
// last written the last time the LOBBY was open — BEFORE this game ended — so
// the finished row stayed under Active, and out of History, until the lobby's
// own fetch landed. On a cold backend that is tens of seconds of a lobby that
// is simply wrong.
//
// So refresh at the moment the game ENDS, while the player is still reading the
// result screen: drop the room from the Active list (state AND cache) right
// away, then re-fetch every list so History holds the real server-built row by
// the time they navigate back. Synthesizing that history row on the client was
// the alternative and is worse — eight games, eight bespoke row shapes, each a
// fresh chance to show a wrong score for a moment.
//
// The re-fetch waits a beat on purpose: not every game saves before it
// broadcasts, so a fetch fired straight off the "over" message can beat the
// row's own status='over' write and read the game back as still active. The
// lobby's on-entry fetch stays the backstop in either case.
//
// Fires ONCE per room — "over" re-broadcasts for the whole review afterwards.
export function useFinishedGameSync(over, roomId, onFinished, delayMs = 700) {
	const doneRef = useRef(null);
	const cbRef = useRef(onFinished);
	cbRef.current = onFinished;
	useEffect(() => {
		if (!over || !roomId || doneRef.current === roomId) return;
		doneRef.current = roomId;
		const t = setTimeout(() => cbRef.current(roomId), delayMs);
		return () => clearTimeout(t);
	}, [over, roomId, delayMs]);
}

// Drop one game from a cached lobby list — state and cache together, so the
// removal survives the trip back to the lobby instead of being undone by the
// cached copy on the next render.
export function dropLobbyGame(ns, scope, key, gameId, setList) {
	setList((prev) => {
		const next = (prev || []).filter((g) => g && g.id !== gameId);
		writeLobbyCache(ns, scope, key, next);
		return next;
	});
}

// ─── Last-played AI difficulty (every game that has an AI opponent) ──────────
// The create modal's difficulty row starts on whatever this player last STARTED
// a game against — per game, per identity — instead of one hardcoded tier for
// everyone forever. Same storage discipline as the lobby cache above:
// localStorage, namespaced by game (ns) + user/guest id (scope), every access
// best-effort (a failure is a no-op fallback, never a throw).
//
// It is written when a vs-AI game is actually CREATED, not when the picker
// moves — "last PLAYED". Opening the modal, browsing the tiers and backing out,
// or creating a vs-Friend game, all leave the remembered tier alone.
//
// The stored id is validated against the tiers the game currently OFFERS, so a
// retired one (Spender's variant codes, Dontminion's plain Big Money) falls
// back to the game's own default instead of restoring a selection the server
// would silently coerce to a different bot than the label claims.
const lastDiffKey = (ns, scope) => `lastdiff.${ns}.${scope}`;

export function readLastDifficulty(ns, scope, offered, fallback) {
	try {
		const v = localStorage.getItem(lastDiffKey(ns, scope));
		return v !== null && offered.includes(v) ? v : fallback;
	} catch { return fallback; }
}
export function writeLastDifficulty(ns, scope, value) {
	try { localStorage.setItem(lastDiffKey(ns, scope), String(value)); } catch {}
}

// `[value, setValue, remember]` — a drop-in for the `useState` the create modal
// used to hold. `remember(v)` is what makes a tier stick, so call it where the
// vs-AI game is created, not from the picker's onChange.
export function useLastDifficulty(ns, scope, offered, fallback) {
	const [value, setValue] = useState(() => readLastDifficulty(ns, scope, offered, fallback));
	// Identity can change under a mounted lobby (log in / log out) and the
	// remembered tier is per-identity, so re-read when scope moves. Guarded by a
	// ref rather than by a dep list: `offered` is an array literal at every call
	// site, so a dep on it would re-run every render and clobber the pick the
	// player just made in the open modal.
	const scopeRef = useRef(scope);
	useEffect(() => {
		if (scopeRef.current === scope) return;
		scopeRef.current = scope;
		setValue(readLastDifficulty(ns, scope, offered, fallback));
	});
	return [value, setValue, (v) => writeLastDifficulty(ns, scope, v)];
}

// ─── Progressive History reveal (all four games' History lists) ──────────────
// Show the newest HISTORY_PAGE games, reveal another page when the reader
// scrolls the end of the list into view, and stop at HISTORY_MAX.
//
// HISTORY_MAX IS ALSO EVERY BACKEND'S `list_user_history` SQL LIMIT (they were
// 20/30/30/30 and are now 50 across the board), so the ceiling is enforced on
// both sides: the client can never ask for a page the server didn't send, and a
// cached old bundle against the new server simply renders all 50 at once.
//
// A SENTINEL + IntersectionObserver, not a scroll handler, because the four
// lobbies scroll differently and a handler would need to know which element
// moves: Spender's `.game-cards` is its own overflow container above 1281px and
// the PAGE scrolls below that, CoC/Duel/Dontminion have no scroller at all so
// only the page ever moves, and the mobile tab layouts move a third thing
// again. The sentinel is correct in all of them and needs no CSS. (An element
// clipped by an ancestor's `overflow` is reported as NOT intersecting, which is
// exactly what makes Spender's inner scroller work without a special case.)
export const HISTORY_PAGE = 10;
export const HISTORY_MAX = 50;

export function useProgressiveList(items, { page = HISTORY_PAGE, max = HISTORY_MAX } = {}) {
	const [shown, setShown] = useState(page);
	const sentinelRef = useRef(null);
	const visible = items.slice(0, Math.min(shown, max));
	const more = visible.length < Math.min(items.length, max);
	// `shown` is a dep on purpose: an observer only calls back when intersection
	// CHANGES, so a sentinel that is still on screen after a reveal would never
	// fire again and the list would strand at 20. Re-observing re-reports the
	// current state, which fills until the sentinel is off screen or max is hit
	// — the standard behaviour, and self-limiting at HISTORY_MAX / page steps.
	useEffect(() => {
		const el = sentinelRef.current;
		if (!el || !more) return;
		if (typeof IntersectionObserver !== "function") { setShown(max); return; }
		const io = new IntersectionObserver((entries) => {
			if (entries.some((e) => e.isIntersecting)) setShown((n) => Math.min(n + page, max));
		});
		io.observe(el);
		return () => io.disconnect();
	}, [more, shown, page, max]);
	// `shown` deliberately SURVIVES a refresh: the lobby re-fetches its lists on
	// a poll/refresh, and resetting here would yank a reader three pages in back
	// to the top every time one of their games ended.
	const sentinel = more
		? <div className="lby-more" ref={sentinelRef} aria-hidden="true" />
		: null;
	return [visible, sentinel];
}

// ─── Create-game modal kit (shared across all four games) ────────────────────
// One "+ Create Game" button per lobby opens a CreateModal holding every option
// (opponent, AI difficulty, seats, length, boards…) as labeled rows — replaces the
// per-game floating dropdown pickers. Token-driven with hard fallbacks (CoC's bare
// mount has no baseCss); --lby-accent threads each game's identity color through
// the selected states + Create button. Append `createModalCss` to the game's CSS.
export const createModalCss = _createModalCssText;

// The lobby create/join/refresh/rules row — one shared control bar across all six games:
//   [ + Create Game (gold) ]  [ CODE ] [ Join ]  [ ↻ ]  [ 📖 Rules ]
// The create button is ALWAYS gold (not the per-game accent), matching CoC; Rules carries
// the per-game accent. `onJoin` receives the trimmed, upper-cased code; `codeMaxLength` is
// 6 everywhere except Where Wolf (4). `onRules` is optional only so the component stays
// usable without one — every lobby passes it. Token-driven with hard fallbacks so it
// renders in CoC's bare mount too. On phones the row SCROLLS SIDEWAYS rather than wrapping
// (five controls stop fitting at ~430px) — see the stylesheet.
export const lobbyCreateRowCss = _lobbyCreateRowCssText;

export function LobbyCreateRow({ onCreate, onJoin, onRefresh, refreshing = false,
	onRules, rulesLabel = "Rules", createLabel = "+ Create Game", codeMaxLength = 6,
	extra = null }) {
	const [code, setCode] = useState("");
	const submit = () => { const c = code.trim().toUpperCase(); if (c) onJoin(c); };
	return (
		<div className="lby-create-row">
			<button type="button" className="lby-cta" onClick={onCreate}>{createLabel}</button>
			<div className="lby-join">
				<input className="lby-code" placeholder="CODE" value={code} maxLength={codeMaxLength}
					onChange={(e) => setCode(e.target.value)}
					onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
				<button type="button" className="lby-join-btn" onClick={submit}>Join</button>
			</div>
			<button type="button" className="lby-refresh" aria-label="Refresh" onClick={onRefresh}>
				{refreshing ? <span className="lby-spinner" /> : "↻"}
			</button>
			{/* THE LABEL IS AN ELEMENT so a narrow phone can drop it and keep the glyph.
			    `aria-label` carries the name either way — a control whose text is
			    display:none is a control with no accessible name. See the <=430px
			    block in the stylesheet for why this row has to give something back. */}
			{onRules && (
				<button type="button" className="lby-rules" onClick={onRules} aria-label={rulesLabel}>
					<span className="lby-rules-ic" aria-hidden="true">{RULES_GLYPH}</span>
					<span className="lby-btn-label">{rulesLabel}</span>
				</button>
			)}
			{/* ONE OPTIONAL SLOT, after Rules, for a control only one game has —
			    today Dissonance's paper scorecard. A node rather than an
			    `onX`/`xLabel` pair, so the kit never learns what any single game
			    keeps there. Style its button `.lby-extra`, which the sheet gives
			    the Rules look: a SEPARATE class on purpose, because `.lby-rules`
			    is how the render gate counts Rules buttons and a second one
			    wearing that class reads as a duplicate. It is the SIXTH control
			    in a row that already stops fitting a phone at ~430px, which the
			    sideways scroll handles (`justify-content: safe center` — plain
			    `center` pushes the overflow off the unreachable LEFT edge). */}
			{extra}
		</div>
	);
}

// ─── Rules ("How to play") modal kit — shared by all six games ───────────────
// The CHROME is shared; the CONTENT stays per-game (each game has a rules.jsx
// next to it). One panel means one scrolling behaviour: the panel is capped to
// the viewport and `.rl-body` is the only scroller, so a ruleset can be as long
// as it needs to be without ever growing the page or clipping its own footer.
// Append `rulesModalCss` to the game's CSS (after `lobbyCreateRowCss`).
export const rulesModalCss = _rulesModalCssText;

export function RulesModal({ title = "How to play", onClose, closeLabel = "Got it",
	icon = RULES_GLYPH, children }) {
	const panelRef = useRef(null);
	const onCloseRef = useRef(onClose);
	useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
	useEffect(() => {
		const previouslyFocused = document.activeElement;
		const panel = panelRef.current;
		const focusable = () => [...(panel?.querySelectorAll(
			'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
		) || [])].filter((el) => !el.hasAttribute("hidden") && el.getClientRects().length);
		// TAKE FOCUS NOW, not on the next animation frame. The panel is already laid
		// out when this effect runs (it has no entry animation), so deferring bought
		// nothing and left a window where focus still sat on the Rules button BEHIND
		// the backdrop — arbitrarily long in a background tab, where rAF is throttled
		// to a stop. It also raced this modal's own render gate, which read
		// activeElement once and went red on 7 of 9 lobbies on a loaded CI runner.
		// The frame is kept only as a SECOND attempt, for a panel whose children
		// mount a tick late; it no-ops once focus is already inside.
		const takeFocus = () => { if (!panel?.contains(document.activeElement)) focusable()[0]?.focus(); };
		takeFocus();
		const focusFrame = requestAnimationFrame(takeFocus);
		const onKey = (e) => {
			if (e.key === "Escape") { e.preventDefault(); onCloseRef.current(); return; }
			if (e.key !== "Tab") return;
			const items = focusable();
			if (!items.length) { e.preventDefault(); panel?.focus(); return; }
			const first = items[0];
			const last = items[items.length - 1];
			if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
			else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
		};
		document.addEventListener("keydown", onKey);
		return () => {
			cancelAnimationFrame(focusFrame);
			document.removeEventListener("keydown", onKey);
			if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) previouslyFocused.focus();
		};
	}, []);
	return (
		<div className="rl-backdrop" onClick={onClose}>
			<div className="rl-panel" role="dialog" aria-modal="true" aria-label={title}
				ref={panelRef} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
				<div className="rl-head">
					<div className="rl-title"><span className="rl-title-ic" aria-hidden="true">{icon}</span>{title}</div>
					<button type="button" className="rl-x" aria-label="Close" onClick={onClose}>✕</button>
				</div>
				<div className="rl-body">{children}</div>
				<div className="rl-foot">
					<button type="button" className="rl-done" onClick={onClose}>{closeLabel}</button>
				</div>
			</div>
		</div>
	);
}

// An accent-headed section of the rules.
export function RulesSection({ title, children }) {
	return (
		<section className="rl-sec">
			<h4>{title}</h4>
			{children}
		</section>
	);
}

// A summary strip of label/value pairs. `items` = [{ k, v }] — k is the micro
// uppercase label, v the value.
//
// NO RULESET USES IT TODAY, and that is deliberate rather than an oversight: every
// game's rules panel opens on "Goal of the Game" (Orbit's shape, adopted by all
// nine), so the player count lives in Setup and the win condition in Goal, where a
// reader looks for them. It used to head seven of the panels as a players / length
// / goal strip. It is kept because the panel is reused for things that are not a
// rulebook — Dissonance's paper scorecard borrows `.rl-lead` already — so a
// summary strip is a reasonable thing for the kit to be able to draw. Whoever
// reaches for it should know it is currently drawn nowhere, and that
// `shared/tests/test_rules_kit_shapes.py` still guards its item SHAPE (a bare
// string renders an empty box).
export function RulesFacts({ items }) {
	return (
		<div className="rl-facts">
			{items.filter(Boolean).map((it, i) => (
				<div className="rl-fact" key={i}>
					<span className="rl-fact-k">{it.k}</span>
					<span className="rl-fact-v">{it.v}</span>
				</div>
			))}
		</div>
	);
}

// Term/definition grid — roles, tile types, card abilities, phases. `items` =
// [{ t, d }]. Two columns on desktop, stacked below 560px (see the stylesheet).
export function RulesDefs({ items }) {
	return (
		<dl className="rl-dl">
			{items.filter(Boolean).map((it, i) => (
				<React.Fragment key={i}>
					<dt>{it.t}</dt>
					<dd>{it.d}</dd>
				</React.Fragment>
			))}
		</dl>
	);
}

// A called-out aside inside a section ("the thing to notice").
export function RulesTip({ children }) {
	return <div className="rl-tip">{children}</div>;
}

// Backdrop + panel + titled header with a ✕. Backdrop click and Escape both close.
export function CreateModal({ title, onClose, children }) {
	useEffect(() => {
		const onKey = (e) => { if (e.key === "Escape") onClose(); };
		document.addEventListener("keydown", onKey);
		return () => document.removeEventListener("keydown", onKey);
	}, [onClose]);
	return (
		<div className="cm-backdrop" onClick={onClose}>
			<div className="cm-panel" onClick={(e) => e.stopPropagation()}>
				<div className="cm-head">
					<div className="cm-title">{title}</div>
					<button type="button" className="cm-x" aria-label="Close" onClick={onClose}>✕</button>
				</div>
				{children}
			</div>
		</div>
	);
}

// A labeled option row (micro uppercase label above the control).
export function CmRow({ label, children }) {
	return (
		<div className="cm-row">
			{label != null && <span className="cm-label">{label}</span>}
			{children}
		</div>
	);
}

/* Segmented control: options = [{ value, label, title? }].
 *
 * `wrap` turns the single clipped row into a WRAPPING chip group, and it exists
 * because the base control cannot hold four long labels on a phone: the buttons
 * are `white-space: nowrap` inside an `overflow: hidden` box, so anything past
 * the fold is not merely off-screen, it is UNREACHABLE — no scroll, no
 * affordance, nothing to swipe. Measured on the offline hub's game picker at a
 * 390px viewport: 485px of buttons in a 330px box, with the fourth option
 * ending 154px past the right edge. Opt in wherever the option count or the
 * label length can grow; the default stays exactly as it was for the five
 * modals that fit.
 */
export function CmSeg({ options, value, onChange, wrap = false }) {
	return (
		<div className={`cm-seg${wrap ? " cm-seg-wrap" : ""}`}>
			{options.map((o) => (
				<button key={String(o.value)} type="button" title={o.title}
					className={`cm-seg-btn${value === o.value ? " sel" : ""}`}
					onClick={() => onChange(o.value)}>{o.label}</button>
			))}
		</div>
	);
}

// ─── In-game options menu (shared across all four games) ─────────────────────
// A single hamburger button that opens a dropdown of game actions — replaces the
// per-game row of Menu / Rules / Abandon buttons in the in-game top bar.
// Token-driven with hard fallbacks so it renders correctly even in CoC's bare
// mount (no baseCss). Append `gameMenuCss` to the game's own <style>.
//
// THE MENU OWNS ITS OWN ITEMS. It used to take an `items` array, and nine call
// sites each typed the same three rows out by hand — the chrome was shared and
// the CONTENT was nine copies, which is the arrangement this repo has already
// paid for at the lobby row and the create button. It drifted exactly as you
// would expect: Orbit shipped "How to play" above "Return to lobby" with `?`
// and `×` for icons, i.e. different words, different glyphs and a different
// ORDER from the other eight, in the one place on every screen where a player
// looks for the way out. A game now passes three callbacks and cannot express
// the drift.
//
// The rows are Return to menu / View rules / Abandon game, in that order, and
// the third is the destructive one so it is painted as such and sits last. A
// row whose handler is absent is dropped, which is how a game omits an action:
//   • Where Wolf has NO Abandon and that is deliberate, not an oversight. Its
//     server-side `abandon` on a game in progress only drops the socket (you are
//     voted in absentia); there is nothing to forfeit, so the row would promise
//     an action the game does not have.
//   • Every game with an `over` state passes `onAbandon={over ? null : …}` —
//     there is nothing to abandon once the result is on the board.
//
// `local` is the ONE variant, and it is a named mode rather than free-text
// labels precisely so it cannot become a re-theming hook: in the offline hub the
// destination really is Local Games rather than the site menu, and the action
// really is deleting a local save rather than forfeiting to an opponent. Saying
// "Abandon game" there would describe a server the tab is not talking to.
export const gameMenuCss = _gameMenuCssText;

export function GameMenu({ onLeave, onRules, onAbandon, local = false,
	align = "left", label = "Menu" }) {
	const items = [
		{ label: local ? "Back to Local Games" : "Return to menu", icon: "←", onClick: onLeave },
		{ label: "View rules", icon: "📖", onClick: onRules },
		{ label: local ? "Delete game" : "Abandon game", icon: "⚑", danger: true, onClick: onAbandon },
	].filter((it) => it.onClick);
	return <GameMenuChrome items={items} align={align} label={label} />;
}

// The dropdown mechanics only — kept apart from the rows above so the "what a
// menu contains" decision and the "how a dropdown behaves" one are not one
// function. Not exported: the rows are the contract.
function GameMenuChrome({ items, align, label }) {
	const [open, setOpen] = useState(false);
	const ref = useRef(null);
	useEffect(() => {
		if (!open) return;
		const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
		const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
		document.addEventListener("mousedown", onDoc);
		document.addEventListener("keydown", onKey);
		return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
	}, [open]);
	return (
		<div className="gm-wrap" ref={ref}>
			<button type="button" className="gm-btn" aria-haspopup="menu" aria-expanded={open}
				aria-label={label} onClick={() => setOpen((o) => !o)}>
				<span /><span /><span />
			</button>
			{open && (
				<div className={`gm-menu gm-${align}`} role="menu">
					{items.map((it, i) => (
						<button type="button" key={i} role="menuitem"
							className={`gm-item${it.danger ? " gm-danger" : ""}`}
							onClick={() => { setOpen(false); it.onClick(); }}>
							{it.icon != null && <span className="gm-item-ic">{it.icon}</span>}
							{it.label}
						</button>
					))}
				</div>
			)}
		</div>
	);
}

// ─── The waiting room ────────────────────────────────────────────────────────
// THE ONE SCREEN WHOSE WHOLE JOB IS TO GET A SECOND PERSON TO THE SAME URL, and
// the last screen in the product that every game still built by hand. Nine of
// them, and they had drifted exactly the way the lobby row and the ☰ menu did
// before this treatment:
//
//   * the way out read "← Back to Menu" (Spender), "Leave" (CoC), "← Back to
//     lobby" (Duel), "Back to lobby" (Rag Tag, Orbit), lived in a ☰ (Where Wolf,
//     Dissonance), was the header's back button (Dontminion) — and in Black
//     Castle did not exist at all, so a host who changed their mind had the
//     browser's Back button and nothing else;
//   * the room code was click-to-copy in two games, inert text in six, and the
//     page's own <h1> in Dontminion and Dissonance;
//   * four games printed a static "Waiting for the host to start…" with nothing
//     moving on the page, which is indistinguishable from a page that has hung.
//
// AND THE THING IT WAS ALL FOR WAS MISSING FROM ALL NINE: what you could copy was
// the room CODE, so inviting someone meant sending six letters plus instructions
// for where to type them. The site has had room URLs since the router landed and
// every game already enters a room from one — `InviteLink` just puts that URL on
// the screen. A link needs no explanation and survives being pasted anywhere.
//
// The component owns the CHROME (identity, invite, seats, the go button, the way
// out). A game brings its accent, its own word for "start", and whatever setup is
// genuinely its own — Where Wolf's role picker, Dontminion's expansion line — via
// `children`, which is the game's to style. `shared/tests/test_waiting_room_kit.py`
// fails the game that stops using it; `spenderWaitingRoom` in
// `webapp/test/screens.mjs` drives the real thing with two clients and a copied
// link, and `waitingRoomKit` beside it holds three games' rendered chrome together.
export const waitingRoomCss = _waitingRoomCssText;

// The absolute URL of a room. `buildPath` already owns the path grammar (and the
// VITE_BASE sub-path), so this is only the origin in front of it — which is the
// whole difference between something a player can send and something they cannot.
export function inviteUrl(game, roomId) {
	const route = GAME_INFO[game]?.screen || game;   // catalogue id ≠ path for wherewolf
	try { return window.location.origin + buildPath(route, roomId); } catch { return ""; }
}

// CLIPBOARD, WITH THE OLD PATH UNDERNEATH IT. `navigator.clipboard` is undefined
// outside a secure context and can reject when the document is not focused, and
// both cases return the same thing to the caller as "no clipboard": nothing
// copied, no error anyone sees. The execCommand fallback is deprecated and works
// everywhere, so it is the floor rather than the ceiling.
async function copyText(text) {
	try {
		if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
	} catch { /* fall through */ }
	try {
		const ta = document.createElement("textarea");
		ta.value = text;
		ta.setAttribute("readonly", "");
		// Off-screen but NOT display:none / visibility:hidden — a hidden element
		// cannot hold a selection, so the copy silently does nothing.
		ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none";
		document.body.appendChild(ta);
		ta.select();
		ta.setSelectionRange(0, text.length);
		const ok = document.execCommand("copy");
		document.body.removeChild(ta);
		return ok;
	} catch { return false; }
}

const LINK_GLYPH = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
		<path d="M10.2 13.8a3.6 3.6 0 0 0 5.4.4l2.6-2.6a3.6 3.6 0 0 0-5.1-5.1l-1.5 1.5" />
		<path d="M13.8 10.2a3.6 3.6 0 0 0-5.4-.4l-2.6 2.6a3.6 3.6 0 0 0 5.1 5.1l1.5-1.5" />
	</svg>
);

// The invite control: one full-width button carrying the URL, and the room code
// under it for the cases a link cannot serve (read aloud across a table, typed
// into the lobby's own Join field).
//
// THE CONFIRMATION IS ON THE BUTTON, not in a toast. Every game that had a copy
// affordance reported it through its own `setToast`, which is a per-game wiring
// the next game forgets and, on a phone, puts the confirmation at the far end of
// the screen from the thumb that just pressed it. This owns the state, so a game
// passes nothing.
export function InviteLink({ game, roomId }) {
	const [copied, setCopied] = useState(null);   // "link" | "code" | null
	const [failed, setFailed] = useState(false);
	const timer = useRef(null);
	useEffect(() => () => clearTimeout(timer.current), []);
	// NOTHING TO INVITE TO YET. Two games render this screen while the room is
	// still connecting (Dissonance's branch is `screen === "waiting" || !game`),
	// and an invite control offering `…/dissonance/` with an empty code beside it
	// is worse than no control: it is a link a host can copy and send.
	if (!roomId) return null;
	const url = inviteUrl(game, roomId);
	const flash = (what, ok) => {
		setCopied(ok ? what : null);
		setFailed(!ok);
		clearTimeout(timer.current);
		timer.current = setTimeout(() => { setCopied(null); setFailed(false); }, 2000);
	};
	const pretty = url.replace(/^https?:\/\//, "");
	return (
		<div className="wr-invite">
			<button type="button" className={`wr-invite-btn${copied === "link" ? " ok" : ""}`}
				title={url}
				aria-label={`Copy the invite link for room ${roomId}`}
				onClick={async () => flash("link", await copyText(url))}>
				<span className="wr-invite-ic" aria-hidden="true">{LINK_GLYPH}</span>
				<span className="wr-invite-text">
					<span className="wr-invite-label">{copied === "link" ? "Link copied" : "Invite link"}</span>
					{/* The URL reads right-to-left so the ROOM CODE is the part that
					    survives the ellipsis — it is the only part that differs. The
					    bidi isolate keeps a mixed-direction origin from reordering. */}
					<span className="wr-invite-url">&#x2066;{pretty}&#x2069;</span>
				</span>
				<span className="wr-invite-hint">{copied === "link" ? "✓" : "Copy"}</span>
			</button>
			<div className="wr-code-row">
				<span className="wr-code-lbl">Room code</span>
				<button type="button" className={`wr-code-btn${copied === "code" ? " ok" : ""}`}
					aria-label={`Copy the room code ${roomId}`}
					onClick={async () => flash("code", await copyText(roomId))}>
					{roomId}
				</button>
			</div>
			{/* Announced, not merely coloured: the button's own label changes for
			    sighted users, and this is the same fact for a screen reader. The
			    failure case is the one that MUST be said — a browser with no
			    clipboard permission otherwise looks identical to a successful copy. */}
			<span className="lby-sr-only" role="status" aria-live="polite">
				{failed ? "Could not copy — select the link and copy it manually."
					: copied === "link" ? "Invite link copied to the clipboard."
					: copied === "code" ? "Room code copied to the clipboard." : ""}
			</span>
		</div>
	);
}

// The screen. `game` is the catalogue id and is the only identity prop — the
// emblem, the name and the invite URL all come from that one entry, so a waiting
// room cannot drift from the card that was tapped to reach it.
//
// `min` is the seat count the game needs to deal; it drives the host's blocked
// label. `max` is the table capacity and drives the open-seat chips, so a four-
// seat table shows all three seats still available after its host sits down.
// `canStart` is for a blocker the seat count cannot express (Where Wolf's deck
// has to match the player count) and pairs with `blockedLabel` to say why.
export function WaitingRoom({
	game, roomId, players, hostId, myId,
	min = 2, max = null, note = null,
	onStart, startLabel = "Start Game", canStart = true, blockedLabel = null,
	onLeave, onRules, user, children, banner, connected = true,
}) {
	const info = GAME_INFO[game] || {};
	const seats = Object.entries(players || {});
	const seated = seats.length;
	const short = Math.max(0, min - seated);
	const seatCapacity = Number(max);
	const openSeats = Number.isFinite(seatCapacity) && seatCapacity > 0
		? Math.max(0, seatCapacity - seated)
		: short;
	const isHost = hostId != null && hostId === myId;
	const label = !connected ? "Reconnecting…"
		: short ? `Waiting for ${short} more player${short === 1 ? "" : "s"}…`
		: (!canStart && blockedLabel) ? blockedLabel : startLabel;
	return (
		<div className="lby-page">
			<LobbyHeader onBack={onLeave} backLabel="← Back to lobby" onRules={onRules}
				user={<LobbyUser user={user} profile={false} />} />
			<div className="wr-in">
				{/* A game's own strip above the panel — Where Wolf's reconnect prompt is
				    the only one today, and it has to be ABOVE the panel rather than in
				    it: a dropped socket means the seats below are stale. */}
				{banner}
				<div className="wr-panel">
					<div className="wr-id">
						{GAME_EMBLEM[game] && <span className="wr-emblem" aria-hidden="true">{GAME_EMBLEM[game]}</span>}
						<span className="wr-kicker">Waiting room</span>
						<h1 className="wr-name">{info.name || ""}</h1>
					</div>

					<InviteLink game={game} roomId={roomId} />

					{note && <p className="wr-note">{note}</p>}

					<div className="wr-count">
						{seated}{max ? `/${max}` : ""} {seated === 1 ? "player" : "players"} seated
					</div>
					<div className="wr-seats">
						{seats.map(([pid, nm]) => (
							<span key={pid} className={`wr-seat${pid === myId ? " wr-seat-me" : ""}`}>
								{pid === hostId && <span className="wr-seat-crown" title="Host" aria-label="host">♛</span>}
								{nm}
								{pid === myId && <span className="wr-seat-you">(you)</span>}
							</span>
						))}
						{/* Empty chips show every seat still available at this table. The
						    start label above still uses `short`, so a four-seat table can
						    start at two while continuing to advertise its two spare seats. */}
						{Array.from({ length: openSeats }, (_, i) => (
							<span key={`open-${i}`} className="wr-seat wr-seat-open">Open seat</span>
						))}
					</div>

					{/* THE SEAT LIST IS A LIVE FEED, AND A DEAD SOCKET LOOKS EXACTLY
					    LIKE AN EMPTY TABLE. This screen's whole content arrives over
					    the WebSocket, so a drop freezes it at whatever it last said —
					    reported as "I invited a friend, they joined, and it still read
					    1/2; I had to back out and come back to see them." The host's
					    Start button goes with it: pressing it on a closed socket sends
					    nothing and says nothing, which is the same silence one step
					    later. The retry itself is the game's (`useAutoReconnect`);
					    this is the part that says so. */}
					{!connected && (
						<div className="wr-drop" role="status" aria-live="polite">
							<span className="lby-spinner lby-spinner-sm" />
							<span>Reconnecting — the seats above may be out of date.</span>
						</div>
					)}

					{children && <div className="wr-extra">{children}</div>}

					{/* The host gets the button; everyone else gets the same sentence
					    with something MOVING beside it. Four of the nine printed that
					    sentence as static text, which on a cold backend is
					    indistinguishable from a page that has hung — and is what the
					    non-host is staring at for the whole of this screen. */}
					<div className="wr-go">
						{isHost
							? <button type="button" className="wr-start"
								disabled={!!short || !canStart || !connected} onClick={onStart}>{label}</button>
							: <span className="wr-status"><span className="lby-spinner" />
								Waiting for the host to start…</span>}
					</div>
				</div>
			</div>
		</div>
	);
}
