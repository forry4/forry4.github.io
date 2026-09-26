/* EVERY GAME'S BOARD: start a real game in each title and capture it at a width ladder.
 *
 * NOT A GATE — `npm run screens` decides whether the frontend ships. This is the
 * in-game counterpart to `lobby-shots.mjs` (the lobbies) and `shell-shots.mjs` (the
 * shell): it exists for the judgements a measurement cannot make, across all eleven
 * boards at once, so a visual pass can be compared BEFORE and AFTER on identical deals.
 *
 * Same convention as those files: it boots NOTHING. Point it at a frontend on 5173 and
 * a backend on 8000 that are already up — start the backend with a fixed
 * `GAMES_DEAL_SEED` (and a high `ROOM_CREATES_PER_HOUR`) so two runs deal the same
 * hands and the before/after pairs line up.
 *
 *   cd webapp && node test/game-shots.mjs <outDir> [--only=duel,coc] [--views=phone,laptop]
 *
 * HOW A STATE IS SHOT AT EVERY WIDTH: the game is played in one base context, and each
 * view opens a FRESH context carrying the base's storage (so it reclaims the same seat)
 * at that view's size and pixel ratio, loads the room URL, and captures. A fresh load
 * per width is deliberate — resizing one page would test the resize path, and a layout
 * computed once at mount would look broken in a way no player ever sees.
 *
 * Each capture also records a few measurements (sideways scroll, text under 10px,
 * clipped text, controls a thumb cannot hit) to `probe.json`.
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "game-shots";
const arg = (k) => (process.argv.find((a) => a.startsWith(`--${k}=`)) || "").split("=")[1];
const only = (arg("only") || "").split(",").filter(Boolean);
const viewPick = (arg("views") || "").split(",").filter(Boolean);
const PORT = 5173;
const BASE = `http://localhost:${PORT}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const VIEWS = [
	{ tag: "phone", w: 390, h: 844, dsf: 2, mobile: true },
	{ tag: "tablet", w: 834, h: 1112, dsf: 2, mobile: true },
	{ tag: "laptop", w: 1366, h: 768, dsf: 1 },
	{ tag: "desktop", w: 1920, h: 1080, dsf: 1 },
	// A 2560x1600 laptop at Windows' default 150% scaling, maximised in Edge: 1707 CSS
	// px wide, ~948 tall once the taskbar and the browser's own bars are taken off.
	// Opt-in (--views=scaled) because it is one person's machine, not a class of them.
	{ tag: "scaled", w: 1707, h: 948, dsf: 1.5, optIn: true },
].filter((v) => (viewPick.length ? viewPick.includes(v.tag) : !v.optIn));
// --viewport captures one screenful, the way a player sees the page; the default is
// the whole scrollable page stitched into one image.
const FULL_PAGE = !process.argv.includes("--viewport");

// --browser=msedge renders in the installed Edge rather than Playwright's Chromium.
const channel = arg("browser");
const browser = channel ? await chromium.launch({ channel })
	: await chromium.launch().catch(() => chromium.launch({ channel: "msedge" }));
const probes = [];

async function seat(id, name, view = { w: 1366, h: 900, dsf: 1 }) {
	const ctx = await browser.newContext({ viewport: { width: view.w, height: view.h }, deviceScaleFactor: view.dsf });
	await ctx.addInitScript(([i, n]) => localStorage.setItem("spender_user",
		JSON.stringify({ id: i, name: n, guest: true })), [id, name]);
	const page = await ctx.newPage();
	page.__errs = [];
	page.on("pageerror", (e) => page.__errs.push(String(e)));
	return { ctx, page };
}

const has = async (page, sel, ms = 20_000) =>
	page.waitForSelector(sel, { timeout: ms }).then(() => true).catch(() => false);
const click = async (page, sel) => page.locator(sel).first().click({ timeout: 8_000 }).then(() => true).catch(() => false);

async function createVsAi(page, route, pre) {
	await page.goto(`${BASE}${route}`, { waitUntil: "load" });
	await has(page, ".lby-cta", 30_000);
	await sleep(400);
	await click(page, ".lby-cta");
	await has(page, ".cm-panel");
	if (pre) await pre(page);
	await click(page, ".cm-create");
}

// The measurements. Each one is a thing a screenshot shows but a reviewer can miss at
// thumbnail size; none is a verdict on its own.
const probeFn = () => {
	const vw = window.innerWidth;
	const vis = (el) => {
		const r = el.getBoundingClientRect();
		if (r.width < 1 || r.height < 1) return false;
		const cs = getComputedStyle(el);
		return cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0.05;
	};
	const label = (el) => (el.className && typeof el.className === "string"
		? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".") : el.tagName.toLowerCase())
		+ ` "${(el.textContent || "").trim().slice(0, 24)}"`;
	const tiny = [], clipped = [], small = [];
	for (const el of document.querySelectorAll("body *")) {
		if (!vis(el)) continue;
		const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
		const cs = getComputedStyle(el);
		if (own && parseFloat(cs.fontSize) < 10) tiny.push(`${label(el)} ${cs.fontSize}`);
		if (own && (cs.overflowX === "hidden" || cs.overflow === "hidden") && cs.textOverflow !== "ellipsis"
			&& el.scrollWidth > el.clientWidth + 2) clipped.push(`${label(el)} ${el.scrollWidth}>${el.clientWidth}`);
		if (el.matches("button, [role=button], a[href], input, select")) {
			const r = el.getBoundingClientRect();
			if (Math.min(r.width, r.height) < 24) small.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
		}
	}
	const uniq = (a) => [...new Set(a)];
	return {
		overflowX: document.documentElement.scrollWidth > vw + 1 ? document.documentElement.scrollWidth - vw : 0,
		docH: document.documentElement.scrollHeight, innerH: window.innerHeight,
		tiny: uniq(tiny).slice(0, 12), tinyN: tiny.length,
		clipped: uniq(clipped).slice(0, 12), clippedN: clipped.length,
		smallTargets: uniq(small).slice(0, 12), smallN: small.length,
	};
};

/** Capture the base page's current URL at every view, each in a fresh context on the same storage. */
async function captureViews(game, state, base, ready, { settle = 1600, prep } = {}) {
	const url = base.page.url();
	const storage = await base.ctx.storageState();
	for (const view of VIEWS) {
		const ctx = await browser.newContext({
			viewport: { width: view.w, height: view.h }, deviceScaleFactor: view.dsf,
			storageState: storage, reducedMotion: "reduce", hasTouch: !!view.mobile, isMobile: !!view.mobile,
		});
		const page = await ctx.newPage();
		const errs = [];
		page.on("pageerror", (e) => errs.push(String(e)));
		await page.goto(url, { waitUntil: "load" });
		let ok = await has(page, ready, 30_000);
		// A root class is on the page while it is still connecting; wait for the
		// connect to finish, so a spinner is never captured as "the board".
		ok = ok && await page.waitForFunction(() =>
			!/^\s*(connecting|reconnecting|loading)/i.test(document.body.innerText.trim().slice(0, 40)),
			null, { timeout: 30_000 }).then(() => true).catch(() => false);
		await sleep(settle);
		if (prep) await prep(page);
		const name = `${game}.${state}.${view.tag}`;
		await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: FULL_PAGE });
		const p = await page.evaluate(probeFn).catch((e) => ({ err: String(e) }));
		probes.push({ name, ready: ok, errs, ...p });
		console.log(`  ${name}${ok ? "" : "  !! NOT READY"}${p.overflowX ? `  !! overflowX ${p.overflowX}` : ""}`
			+ `  tiny=${p.tinyN} clipped=${p.clippedN} small=${p.smallN} h=${p.docH}/${p.innerH}`
			+ (errs.length ? `  ERR ${errs[0].slice(0, 120)}` : ""));
		await ctx.close();
	}
	// The views took this seat's socket; bring the base back before it acts again.
	await base.page.reload({ waitUntil: "load" });
	await has(base.page, ready, 30_000);
	await sleep(800);
}

// ── Per game: reach each state worth looking at, then capture it. ─────────────────
const GAMES = {
	async spender() {
		const b = await seat("gs-spender", "Aurelia");
		await createVsAi(b.page, "/spender");
		await has(b.page, ".gem-stack", 30_000);
		await captureViews("spender", "board", b, ".gem-stack");
		await b.ctx.close();
	},
	async coc() {
		const b = await seat("gs-coc", "Aurelia");
		await createVsAi(b.page, "/coc");
		await has(b.page, ".coc-board-hex", 30_000);
		await captureViews("coc", "board", b, ".coc-board-hex", { settle: 2500 });
		await b.ctx.close();
	},
	async duel() {
		const b = await seat("gs-duel", "Aurelia");
		await createVsAi(b.page, "/duel");
		await has(b.page, ".duel", 30_000);
		await sleep(1500);
		await captureViews("duel", "board", b, ".duel", { settle: 2500 });
		await b.ctx.close();
	},
	async dontminion() {
		const b = await seat("gs-dontminion", "Aurelia");
		await createVsAi(b.page, "/dontminion");
		await has(b.page, ".dm-supply .dm-card", 30_000);
		await captureViews("dontminion", "board", b, ".dm-supply .dm-card", { settle: 2500 });
		await b.ctx.close();
	},
	async dissonance() {
		const b = await seat("gs-dissonance", "Aurelia");
		await createVsAi(b.page, "/dissonance", async (p) => {
			await p.locator(".cm-seg-btn", { hasText: "Easy" }).first().click().catch(() => {});
		});
		await has(b.page, ".dis-bidgrid, .dis-trick", 30_000);
		await sleep(1500);
		await captureViews("dissonance", "auction", b, ".dis-bidgrid, .dis-trick", { settle: 2000 });
		await b.ctx.close();
	},
	async ragtag() {
		const b = await seat("gs-ragtag", "Aurelia");
		await createVsAi(b.page, "/ragtag");
		await has(b.page, ".rt-prompt .rt-pick", 30_000);
		await captureViews("ragtag", "draft", b, ".rt-prompt .rt-pick");
		for (let round = 0; round < 2; round++) {
			await has(b.page, ".rt-prompt .rt-pick", 30_000);
			await b.page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
			await sleep(1200);
		}
		for (let i = 0; i < 4; i++) {
			const hd = await b.page.locator(".rt-prompt h3").first().innerText().catch(() => "");
			if (/Character|leads/i.test(hd)) {
				await b.page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
				await sleep(1200);
			} else if (await b.page.locator(".rt-stage").count()) break;
			else await sleep(1000);
		}
		if (await has(b.page, ".rt-stage", 30_000)) {
			await click(b.page, ".rt-ctl-go:not([disabled])");
			await sleep(800);
			await captureViews("ragtag", "fight", b, ".rt-stage");
		}
		await b.ctx.close();
	},
	async orbit() {
		const b = await seat("gs-orbit", "Aurelia");
		await createVsAi(b.page, "/orbit", async (p) => {
			await p.locator(".cm-seg-btn", { hasText: "Easy" }).first().click().catch(() => {});
		});
		if (await has(b.page, ".or-mulligan", 30_000)) {
			await captureViews("orbit", "mulligan", b, ".or-mulligan");
			await click(b.page, ".or-mulligan .or-primary");
		}
		await sleep(4000);
		await captureViews("orbit", "board", b, ".orbit", { settle: 3000 });
		await b.ctx.close();
	},
	async blackcastle() {
		const b = await seat("gs-blackcastle", "Moon Clan");
		await createVsAi(b.page, "/blackcastle");
		await has(b.page, ".bc-game-hero", 30_000);
		await sleep(1500);
		if (await b.page.locator(".bc-draft-grid").count())
			await captureViews("blackcastle", "draft", b, ".bc-game-hero");
		for (let i = 0; i < 24 && await b.page.locator(".bc-draft-grid").count(); i++) {
			const pair = b.page.locator(".bc-draft-pair:not([disabled])").first();
			if (await pair.count()) {
				await pair.click().catch(() => {});
				await click(b.page, ".bc-draft-confirm .bc-primary:not([disabled])");
			}
			await sleep(500);
		}
		if (await has(b.page, ".bc-board", 30_000)) {
			await sleep(2500);
			await captureViews("blackcastle", "board", b, ".bc-board", { settle: 2500 });
		}
		await b.ctx.close();
	},
	async pinch() {
		const b = await seat("gs-pinch", "Aurelia");
		await createVsAi(b.page, "/pinch");
		await has(b.page, ".pi-board-svg", 30_000);
		// Place a few rings so the board is not empty.
		for (let i = 0; i < 5; i++) {
			const t = b.page.locator(".pi-target .pi-hit").first();
			if (!await t.waitFor({ state: "visible", timeout: 20_000 }).then(() => true).catch(() => false)) break;
			await t.click().catch(() => {});
			await sleep(300);
		}
		await sleep(2000);
		await captureViews("pinch", "board", b, ".pi-board-svg");
		await b.ctx.close();
	},
	async secretnames() {
		const a = await seat("gs-sn-alpha", "Vega");
		const z = await seat("gs-sn-beta", "Rook");
		await createVsAi(a.page, "/secretnames");
		await has(a.page, ".wr-panel", 30_000);
		await captureViews("secretnames", "waiting", a, ".wr-panel");
		const code = ((await a.page.locator(".wr-code-btn").textContent().catch(() => "")) || "").replace(/[^A-Z0-9]/g, "");
		await z.page.goto(`${BASE}/secretnames/${code}`, { waitUntil: "load" });
		await a.page.waitForFunction(() => document.querySelectorAll(".wr-seat:not(.wr-seat-open)").length === 2,
			null, { timeout: 30_000 }).catch(() => {});
		await click(a.page, ".wr-start:not([disabled])");
		await sleep(2500);
		await captureViews("secretnames", "board", a, ".secretnames", { settle: 2000 });
		await a.ctx.close(); await z.ctx.close();
	},
	async wherewolf() {
		const seats = [await seat("gs-ww-a", "Vega"), await seat("gs-ww-b", "Rook"), await seat("gs-ww-c", "Juno")];
		await createVsAi(seats[0].page, "/werewolf");
		await has(seats[0].page, ".wr-panel", 30_000);
		const code = ((await seats[0].page.locator(".wr-code-btn").textContent().catch(() => "")) || "").replace(/[^A-Z0-9]/g, "");
		for (const s of seats.slice(1)) await s.page.goto(`${BASE}/werewolf/${code}`, { waitUntil: "load" });
		await seats[0].page.waitForFunction(() => document.querySelectorAll(".wr-seat:not(.wr-seat-open)").length >= 3,
			null, { timeout: 30_000 }).catch(() => {});
		await sleep(800);
		await captureViews("wherewolf", "waiting", seats[0], ".wr-panel");
		await click(seats[0].page, ".wr-start:not([disabled])");
		await sleep(3000);
		await captureViews("wherewolf", "night", seats[0], ".ww", { settle: 2000 });
		for (const s of seats) await s.ctx.close();
	},
};

try {
	for (const [name, run] of Object.entries(GAMES)) {
		if (only.length && !only.includes(name)) continue;
		console.log(name);
		try { await run(); } catch (e) { console.log(`  !! ${name} failed: ${String(e).slice(0, 300)}`); }
	}
} finally {
	writeFileSync(path.join(OUT, "probe.json"), JSON.stringify(probes, null, 1));
	await browser.close();
}
console.log(`\nwrote ${path.resolve(OUT)}`);
