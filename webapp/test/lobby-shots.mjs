/* THE SEVEN GAME LOBBIES: capture every lobby, empty and populated, at a width ladder.
 *
 * NOT A GATE — `npm run screens` decides whether the frontend ships. This is the
 * lobbies' counterpart to `shell-shots.mjs` (the three shell screens) and `shots.mjs`
 * (Rag Tag): it exists for the judgements a measurement cannot make — whether a column
 * of rows reads as a designed list or as a table someone forgot to style, whether the
 * three sections have a hierarchy, whether the page has the same light source as the
 * menu that led to it.
 *
 * Same convention as those two: it boots NOTHING. Point it at a `vite preview` on 5173
 * and a backend on 8000 that are already up.
 *
 *   cd webapp && node test/lobby-shots.mjs <outDir> [--only=duel,coc] [--views=phone,laptop]
 *
 * POPULATED IS STUBBED, NOT PLAYED. The three list endpoints are uniform across the
 * games (`/games`, `/games/mine` or `/games/active`, `/games/history`) but their ROW
 * shapes are not, so each stub row carries the UNION of the fields the seven lobbies
 * read. A field a game does not use costs nothing; a missing one renders "?" and is
 * visible in the shot, which is the point.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "lobby-shots";
const arg = (k) => (process.argv.find((a) => a.startsWith(`--${k}=`)) || "").split("=")[1];
const only = (arg("only") || "").split(",").filter(Boolean);
const viewPick = (arg("views") || "").split(",").filter(Boolean);
const states = (arg("state") || "empty,full").split(",").filter(Boolean);
const PORT = 5173;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const ME = "lobby-shots-user";

// Each lobby's route + the marker only that game's own stylesheet can produce, so a
// screen that fell back to the shell or stalled on the loader is obvious rather than
// silently captured as a blank page.
const LOBBIES = [
	{ tag: "spender", path: "/spender", marker: ".browser" },
	{ tag: "coc", path: "/coc", marker: ".coc" },
	{ tag: "wherewolf", path: "/werewolf", marker: ".ww" },
	{ tag: "duel", path: "/duel", marker: ".duel" },
	{ tag: "dontminion", path: "/dontminion", marker: ".dm" },
	{ tag: "dissonance", path: "/dissonance", marker: ".dis" },
	{ tag: "ragtag", path: "/ragtag", marker: ".ragtag" },
	{ tag: "orbit", path: "/orbit", marker: ".orbit" },
];

const VIEWS = [
	{ tag: "phone", w: 390, h: 844, dsf: 2 },
	{ tag: "tablet", w: 834, h: 1112, dsf: 2 },
	{ tag: "laptop", w: 1280, h: 800, dsf: 2 },
	{ tag: "desktop", w: 1920, h: 1080, dsf: 1 },
];

const ago = (m) => Math.floor(Date.now() / 1000) - m * 60;

// ── The union rows ──────────────────────────────────────────────────────────
const OPEN = [
	{ id: "K7QP2M", host_id: "someone-else", host_name: "Marguerite", created_at: ago(3),
		player_count: 1, players: 1, max_players: 4, mode: "classic", host_board: "The Vineyard", same_board: true,
		expansions: ["base", "intrigue"], opponents: ["Marguerite"], player1_name: "Marguerite", player2_name: null },
	{ id: "B4XZ9C", host_id: ME, host_name: "Aurelia", created_at: ago(11),
		player_count: 2, players: 2, max_players: 4, mode: "skat", host_board: "The Quarry", same_board: false,
		expansions: ["seaside"], opponents: ["Aurelia"], player1_name: "Aurelia", player2_name: null },
];
const MINE = [
	{ id: "T3MW8D", status: "playing", updated_at: ago(2), turn: ME, your_turn: true, you_are_p1: true,
		player1_id: ME, player1_name: "Aurelia", player2_id: "bot1", player2_name: "Bot 1",
		player3_id: null, player3_name: null, player4_id: null, player4_name: null,
		players: 2, opponents: ["Bot 1"], round: 4, mode: "classic", outcome: null },
	{ id: "R9HK4L", status: "playing", updated_at: ago(46), turn: "opp", your_turn: false, you_are_p1: false,
		player1_id: "opp", player1_name: "Marguerite", player2_id: ME, player2_name: "Aurelia",
		player3_id: "third", player3_name: "Cornelius", player4_id: null, player4_name: null,
		players: 3, opponents: ["Marguerite", "Cornelius"], round: 9, mode: "minor", outcome: null },
];
const HIST = (n) => Array.from({ length: n }, (_, i) => ({
	id: `H${String(i).padStart(5, "0")}`,
	you_won: i % 3 !== 1, tie: false, updated_at: ago(90 + i * 240), finished_at: ago(90 + i * 240),
	opp_name: i % 2 ? "Marguerite" : "Bot 3", opp_score: 12 + (i % 5), your_score: 17 + (i % 4),
	win_condition: "points", win_points: i % 4 === 0 ? 21 : 15,
	players: [{ name: "Aurelia", score: 17 + (i % 4), is_you: true },
		{ name: i % 2 ? "Marguerite" : "Bot 3", score: 12 + (i % 5), is_you: false }],
	opponents: [i % 2 ? "Marguerite" : "Bot 3"], winners: i % 3 !== 1 ? ["Aurelia"] : ["Marguerite"],
	// Dontminion builds its score line from `standings` (or your_vp + scores), not
	// from your_score/opp_score — omitting them made its History look scoreless.
	your_vp: 17 + (i % 4), scores: { Aurelia: 17 + (i % 4), "Bot 3": 12 + (i % 5), Marguerite: 12 + (i % 5) },
	standings: [{ name: "Aurelia", vp: 17 + (i % 4), you: true }, { name: i % 2 ? "Marguerite" : "Bot 3", vp: 12 + (i % 5) }],
	// Rag Tag's History row ends in the number of rounds the fight ran (it has no
	// post-game review to put a button there); without it the row looks half-drawn.
	your_team: ["Ragnar", "Sable"], outcome: i % 3 !== 1 ? "win" : "loss", rounds: 3 + (i % 4),
	you_are_p1: true, player1_name: "Aurelia", player2_name: i % 2 ? "Marguerite" : "Bot 3",
}));

const browser = await chromium.launch().catch(() => chromium.launch({ channel: "msedge" }));

async function shot(lobby, view, state) {
	const ctx = await browser.newContext({
		viewport: { width: view.w, height: view.h }, deviceScaleFactor: view.dsf, reducedMotion: "reduce",
	});
	// A real (non-guest) identity: History is session-gated in every lobby, so a
	// guest is short-circuited to the "log in to keep history" empty state and the
	// third column can never be seen populated.
	await ctx.addInitScript((me) => {
		localStorage.setItem("spender_user", JSON.stringify({ id: me, name: "Aurelia", session_token: "stub" }));
	}, ME);
	const page = await ctx.newPage();
	const errs = [];
	page.on("pageerror", (e) => errs.push(String(e)));
	page.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text()); });
	// The shell validates a stored session on load; a dead token clears the login,
	// but a NETWORK error deliberately does not — so aborting is how the seeded
	// user survives without having to guess the payload.
	await page.route("**/auth/session*", (r) => r.abort());
	// BOTH states are stubbed, "empty" included. The local dev DB accumulates
	// rooms from every earlier run, so an unstubbed lobby is not the first-visit
	// state at all - the first pass drew 86 rows into a column labelled empty.
	const json = (games) => ({ status: 200, contentType: "application/json",
		body: JSON.stringify({ ok: true, games }) });
	const full = state === "full";
	await page.route("**/games/history*", (r) => r.fulfill(json(full ? HIST(14) : [])));
	await page.route("**/games/mine*", (r) => r.fulfill(json(full ? MINE : [])));
	await page.route("**/games/active*", (r) => r.fulfill(json(full ? MINE : [])));
	await page.route(/\/games(\?|$)/, (r) => r.fulfill(json(full ? OPEN : [])));
	await page.goto(`http://localhost:${PORT}${lobby.path}`, { waitUntil: "load", timeout: 30_000 });
	await page.waitForSelector(lobby.marker, { timeout: 25_000 }).catch(() => {});
	await sleep(900);
	const name = `${lobby.tag}.${state}.${view.tag}`;
	await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
	const probe = await page.evaluate(() => {
		const q = (s) => document.querySelector(s);
		const n = (s) => document.querySelectorAll(s).length;
		const el = q(".lby-cols") || q(".ww-lobby-cols");
		return {
			docH: document.documentElement.scrollHeight, innerH: window.innerHeight,
			overflowX: document.documentElement.scrollWidth > window.innerWidth,
			cols: el ? Math.round(el.getBoundingClientRect().width) : null,
			rows: n(".lby-card"), empties: n(".lby-empty"),
			accent: el ? getComputedStyle(el).getPropertyValue("--lby-accent").trim() : "",
		};
	}).catch(() => ({}));
	console.log(`  ${name}.png  rows=${probe.rows} empty=${probe.empties} h=${probe.docH}` +
		`${probe.overflowX ? "  !! OVERFLOW-X" : ""}` +
		`${errs.length ? "   PAGE ERRORS: " + errs.join(" | ").slice(0, 200) : ""}`);
	await ctx.close();
}

try {
	for (const lobby of LOBBIES) {
		if (only.length && !only.includes(lobby.tag)) continue;
		console.log(lobby.tag);
		for (const state of states)
			for (const view of VIEWS) {
				if (viewPick.length && !viewPick.includes(view.tag)) continue;
				await shot(lobby, view, state);
			}
	}
} finally { await browser.close(); }
console.log(`\nwrote ${path.resolve(OUT)}`);
