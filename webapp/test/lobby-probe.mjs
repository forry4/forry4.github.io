/* Measure what a screenshot can only suggest — run beside `lobby-shots.mjs`.
 *   cd webapp && node test/lobby-probe.mjs [--views=laptop,tablet]
 * Boots nothing; point it at a preview on 5173.
 */
import { chromium } from "playwright";

const arg = (k) => (process.argv.find((a) => a.startsWith(`--${k}=`)) || "").split("=")[1];
const only = (arg("only") || "").split(",").filter(Boolean);
const viewPick = (arg("views") || "laptop").split(",").filter(Boolean);
const PORT = 5173;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ME = "lobby-shots-user";

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
const VIEWS = {
	phone: { w: 390, h: 844 }, tablet: { w: 834, h: 1112 },
	laptop: { w: 1280, h: 800 }, desktop: { w: 1920, h: 1080 },
};

const ago = (m) => Math.floor(Date.now() / 1000) - m * 60;
const OPEN = [
	{ id: "K7QP2M", host_id: "x", host_name: "Marguerite", created_at: ago(3), players: 1,
		player_count: 1, max_players: 4, mode: "classic", host_board: "The Vineyard", same_board: true,
		expansions: ["base"], opponents: ["Marguerite"], player1_name: "Marguerite", player2_name: null },
];
const MINE = [
	{ id: "T3MW8D", status: "playing", updated_at: ago(2), turn: ME, your_turn: true, you_are_p1: true, players: 2,
		player1_id: ME, player1_name: "Aurelia", player2_id: "bot1", player2_name: "Bot 1",
		opponents: ["Bot 1"], round: 4, mode: "classic", outcome: null },
];
const HIST = Array.from({ length: 12 }, (_, i) => ({
	id: `H${i}`, you_won: i % 3 !== 1, tie: false, updated_at: ago(90 + i * 240), finished_at: ago(90 + i * 240),
	opp_name: i % 2 ? "Marguerite" : "Bot 3", opp_score: 12 + (i % 5), your_score: 17 + (i % 4),
	win_condition: "points", win_points: 15,
	players: [{ name: "Aurelia", score: 18, is_you: true }, { name: "Bot 3", score: 12, is_you: false }],
	opponents: ["Bot 3"], winners: ["Aurelia"], your_team: ["Ragnar", "Sable"], outcome: "win",
	you_are_p1: true, player1_name: "Aurelia", player2_name: "Bot 3",
}));

const browser = await chromium.launch().catch(() => chromium.launch({ channel: "msedge" }));
const rows = [];
for (const lobby of LOBBIES) {
	if (only.length && !only.includes(lobby.tag)) continue;
	for (const vk of viewPick) {
		const view = VIEWS[vk];
		const ctx = await browser.newContext({ viewport: { width: view.w, height: view.h }, reducedMotion: "reduce" });
		await ctx.addInitScript((me) => {
			localStorage.setItem("spender_user", JSON.stringify({ id: me, name: "Aurelia", session_token: "stub" }));
		}, ME);
		const page = await ctx.newPage();
		await page.route("**/auth/session*", (r) => r.abort());
		const json = (g) => ({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, games: g }) });
		await page.route("**/games/history*", (r) => r.fulfill(json(HIST)));
		await page.route("**/games/mine*", (r) => r.fulfill(json(MINE)));
		await page.route("**/games/active*", (r) => r.fulfill(json(MINE)));
		await page.route(/\/games(\?|$)/, (r) => r.fulfill(json(OPEN)));
		await page.goto(`http://localhost:${PORT}${lobby.path}`, { waitUntil: "load", timeout: 30_000 });
		await page.waitForSelector(lobby.marker, { timeout: 25_000 }).catch(() => {});
		// The marker is the game ROOT; Where Wolf shows a connecting spinner inside it
		// for a beat, so waiting on the root alone measured a page that was not there.
		await page.waitForSelector(".lby-hero", { timeout: 20_000 }).catch(() => {});
		// Where Wolf's lobby lands later than the others' — 800ms measured it mid-mount
		// and reported every box as null, which reads exactly like a broken page.
		await sleep(1800);
		const m = await page.evaluate(() => {
			const L = (s) => document.querySelector(s);
			const box = (s) => { const e = L(s); return e ? e.getBoundingClientRect() : null; };
			const r = (n) => (n == null ? null : Math.round(n));
			const cs = (s, p) => { const e = L(s); return e ? getComputedStyle(e)[p] : null; };
			const hero = box(".lby-hero"), back = box(".lby-back"), name = L(".lby-hero-name");
			const cols = box(".lby-cols") || box(".ww-lobby-grid");
			const card = box(".lby-card");
			const row = L(".lby-create-row");
			const lists = [...document.querySelectorAll(".lby-list")].map((e) => ({
				h: Math.round(e.getBoundingClientRect().height),
				scrollH: e.scrollHeight, clip: e.scrollHeight > e.clientHeight + 1,
				bottom: Math.round(e.getBoundingClientRect().bottom),
			}));
			// every card in the FIRST list, to see whether siblings are equal height
			const first = L(".lby-list");
			const cardHs = first ? [...first.querySelectorAll(".lby-card")].map((c) => Math.round(c.getBoundingClientRect().height)) : [];
			// truncation: a title whose scrollWidth exceeds its box
			const trunc = [...document.querySelectorAll(".lby-card-title")]
				.filter((e) => e.scrollWidth > e.clientWidth + 1)
				.map((e) => `${e.textContent.slice(0, 22)}  ${e.scrollWidth}>${e.clientWidth}`);
			return {
				vw: innerWidth, vh: innerHeight, docH: document.documentElement.scrollHeight,
				backL: r(back?.left), heroL: r(hero?.left), colsL: r(cols?.left), colsW: r(cols?.width),
				cardW: r(card?.width),
				heroFont: name ? getComputedStyle(name).fontFamily.split(",")[0] : null,
				heroSize: name ? getComputedStyle(name).fontSize : null,
				heroWraps: hero ? (hero.height > 90) : null,
				rowOverflows: row ? row.scrollWidth > row.clientWidth + 1 : null,
				rowHidden: row ? Math.round(row.scrollWidth - row.clientWidth) : null,
				lists, cardHs, trunc: trunc.slice(0, 4),
				ctaBg: cs(".lby-cta", "backgroundImage")?.slice(0, 60),
			};
		}).catch((e) => ({ err: String(e) }));
		rows.push({ game: lobby.tag, view: vk, ...m });
		await ctx.close();
	}
}
await browser.close();
for (const r of rows) console.log(JSON.stringify(r));
