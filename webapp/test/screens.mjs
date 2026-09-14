/* Game-screen render gate — the coverage `smoke.mjs` cannot provide.
 *
 * WHY THIS EXISTS. The smoke test loads three routes and asserts #root is non-empty,
 * which reads like "the app renders". It isn't: the shell pings the backend BEFORE it
 * routes anywhere, and the smoke run has no backend — so all three routes sit on the
 * loading screen. They report an identical #root length that is ~99% injected CSS.
 * Smoke genuinely catches a blank page, a bundle that throws, and layout shift. It has
 * never once rendered a game.
 *
 * So every game screen has been shipping unverified, which is also why the Spender.jsx
 * shell/game split keeps getting deferred: there is nothing to catch a regression in it.
 *
 * WHAT THIS DOES: boots the REAL backend (uvicorn on the composition root), serves the
 * built frontend on 5173 — which is load-bearing, `core/config.py` only allowlists that
 * port for CORS, and on any other port the browser fetch is blocked and the app hangs
 * on the loader — seeds a guest identity, then drives each game route and asserts it
 * rendered ITS OWN screen: distinct, substantial content and no uncaught page errors.
 *
 * Run: `npm run screens` (from webapp/). Needs Python + the backend requirements.
 * Use `--only=blockName[,blockName]` for a focused, named screen contract; CI
 * uses this for a game-only release, while any shared change keeps the full gate.
 */
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";
// The accent contract lives in ONE place; this gate reads it rather than re-listing it.
import { GAME_ACCENTS, ACCENT_AA_EXEMPT } from "../../shared/accents.js";

const webappDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webappDir, "..");
const PORT = 5173;            // CORS-allowlisted; see above
const API_PORT = 8000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const onlyArg = process.argv.find((arg) => arg.startsWith("--only="));
const ONLY_BLOCKS = (onlyArg?.slice("--only=".length) || process.env.SCREENS_ONLY || "")
	.split(",").map((name) => name.trim()).filter(Boolean);

// Each game owns one route and must render a marker only IT can produce. The marker is
// a CSS class from that game's own stylesheet, so a screen that silently fell back to
// the shell (or to the loader) fails instead of passing on "something rendered".
const SCREENS = [
	{ path: "/duel", chunk: "SpenderDuel", marker: ".duel" },
	{ path: "/coc", chunk: "CastlesOfCrimson", marker: ".coc" },
	{ path: "/werewolf", chunk: "WhereWolf", marker: ".ww" },
	{ path: "/dontminion", chunk: "Dontminion", marker: ".dm" },
	{ path: "/dissonance", chunk: "Dissonance", marker: ".dis" },
	{ path: "/ragtag", chunk: "RagTag", marker: ".ragtag" },
	{ path: "/orbit", chunk: "Orbit", marker: ".orbit" },
	{ path: "/books", chunk: "Books", marker: ".bk-app" },
	{ path: "/bggfilter", chunk: "BggFilter", marker: ".bgf" },
];

// Newest mtime across everything the bundle is built FROM — the same four trees
// `deploy-pages.yml` filters its build on. Used only to decide whether an existing
// dist/ may be REUSED (see runBuild): a flag alone would be a promise that some
// caller really did just build, and the whole reason this harness builds at all is
// that a stale dist/ makes a broken change look green. A timestamp cannot lie.
function newestSourceMtime() {
	let newest = 0;
	const skipDirs = new Set(["node_modules", "dist", "__pycache__", "tests", "test-results"]);
	// Only what can actually reach the bundle. Walking every file under games/
	// would drag in the AI model blobs and training data for no signal.
	const exts = /\.(jsx?|mjs|css|html|json|svg|png|jpe?g|woff2?|wasm|bin)$/i;
	const walk = (dir) => {
		let entries;
		try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
		for (const e of entries) {
			if (e.name.startsWith(".") || skipDirs.has(e.name)) continue;
			const full = path.join(dir, e.name);
			if (e.isDirectory()) walk(full);
			else if (exts.test(e.name)) {
				try { newest = Math.max(newest, statSync(full).mtimeMs); } catch { /* raced */ }
			}
		}
	};
	for (const d of ["webapp", "games", "shared", "books"]) walk(path.join(repoRoot, d));
	return newest;
}

// BUILD FIRST — without this the harness happily tests whatever is already in
// dist/, and a build that FAILS leaves the previous, working bundle in place, so a
// broken change would sail through green. (Caught exactly that way.)
//
// The one exception is a caller that JUST built the identical bundle — `npm run
// smoke` runs the same `vite build` with the same env moments earlier, in both CI
// and .githooks/pre-push, so the pair used to pay for that build twice. Setting
// SCREENS_REUSE_BUILD=1 offers the existing dist/, and this VERIFIES the offer
// rather than taking it: unless dist/ is newer than every source file it is built
// from, it rebuilds anyway. So the invariant survives a stale flag, a partial
// build, and an edit made between the two gates.
function runBuild() {
	if (process.env.SCREENS_REUSE_BUILD === "1") {
		let builtAt = 0;
		try { builtAt = statSync(path.join(webappDir, "dist", "index.html")).mtimeMs; } catch {}
		const srcAt = newestSourceMtime();
		if (builtAt && builtAt > srcAt) {
			console.log("  reusing the bundle the previous gate just built (dist/ is newer than every source)");
			return Promise.resolve();
		}
		console.log(builtAt
			? "  dist/ is older than a source file — building despite SCREENS_REUSE_BUILD"
			: "  no dist/ to reuse — building");
	}
	return new Promise((res, rej) => {
		const b = spawn("npx", ["vite", "build"], { cwd: webappDir, stdio: ["ignore", "ignore", "inherit"], shell: true });
		b.on("exit", (code) => (code === 0 ? res() : rej(new Error(`vite build exited ${code}`))));
	});
}

async function waitForHttp(url, timeoutMs, label) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		try {
			const res = await fetch(url);
			if (res.ok) return true;
		} catch { /* not up yet */ }
		await sleep(500);
	}
	throw new Error(`${label} did not come up at ${url} within ${timeoutMs}ms`);
}

// Poll until a measurement stops moving, rather than sleeping a guessed interval.
// Two consecutive equal samples is the rule the FitText rig below already used
// inline; hoisted so every resize and every "wait for the server to answer" can
// use it. Faster than a fixed sleep when the page is quick, and — the half that
// matters — still correct when the box is loaded, which a fixed sleep is not.
async function settle(page, read, { tries = 25, gap = 60 } = {}) {
	let prev;
	for (let i = 0; i < tries; i++) {
		const now = await page.evaluate(read).catch(() => null);
		if (i > 0 && JSON.stringify(now) === JSON.stringify(prev)) return now;
		prev = now;
		await sleep(gap);
	}
	return prev;
}

// Card faces re-fit their title and body text from a ResizeObserver, so the frame
// right after setViewportSize still carries the PREVIOUS width's sizes — which is
// exactly what the fixed sleep after every resize was waiting out.
const settleFits = (page) => settle(page, () => [
	window.innerWidth, window.innerHeight,
	[...document.querySelectorAll(".dm-card-name, .dm-card-body")]
		.map((e) => getComputedStyle(e).fontSize).join(","),
]);

// Wait for a page-side predicate, capped, swallowing the timeout. The cap is the
// old fixed sleep, so a genuinely slow answer still gets the window it used to.
const until = (page, fn, ms, arg = null) => page.waitForFunction(fn, arg, { timeout: ms })
	.then(() => true).catch(() => false);

// CI installs the browser Playwright asks for and the first branch takes it.
// The escape hatch is for a box that has a Chromium Playwright's pin does not
// name — a preinstalled one in a container image, say, where the pin moved from
// build 1194 to 1228 and the gate stops being runnable at all. Silently falling
// back to msedge was the old answer and only worked on one machine.
async function launchBrowser() {
	const exe = process.env.PLAYWRIGHT_CHROMIUM_PATH;
	if (exe) return await chromium.launch({ executablePath: exe });
	try { return await chromium.launch(); }
	catch { return await chromium.launch({ channel: "msedge" }); }
}

let api, preview, browser;

// Kill the process TREE, not just the child. Both servers are spawned with
// `shell: true`, so `child.kill()` reaps the shell and leaves the real uvicorn /
// vite grandchild running — which then squats on the port and makes the NEXT run
// test a stale backend (exactly the failure the started_at guard above now
// catches). Reaping properly is the actual fix; the guard is the safety net.
const killTree = (child) => {
	if (!child?.pid) return;
	try {
		if (process.platform === "win32") {
			// spawnSync, not spawn: shutdown() runs from process "exit", where an async
			// child never gets to run and the server survives the harness.
			spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
		} else {
			process.kill(-child.pid, "SIGKILL");
		}
	} catch { /* already gone */ }
	try { child.kill(); } catch {}
};
const shutdown = () => { for (const p of [api, preview]) killTree(p); };
process.on("exit", shutdown);
process.on("SIGINT", () => { shutdown(); process.exit(130); });

try {
	// Record BEFORE spawning: /health reports `started_at` (core/build_info), so we can
	// prove the backend answering us is the one WE started.
	//
	// THIS IS NOT PARANOIA. A stale uvicorn left on 8000 from an earlier session makes
	// our spawn fail to bind while the health check succeeds instantly — against the OLD
	// code. Every backend assertion then silently tests a build that no longer exists.
	// Caught exactly that way: a deliberately broken engine.apply_move still "passed".
	// The port can't just be randomised — VITE_WS_URL bakes localhost:8000 into the
	// bundle — so detect it and fail loudly instead.
	const spawnedAt = Math.floor(Date.now() / 1000);
	console.log("starting backend (uvicorn app:app) + building ...");
	// GAMES_DEAL_SEED makes every deal a function of WHO IS AT THE TABLE instead
	// of the clock. It is the fix for this gate's most expensive failure mode: 11
	// of the 15 failed Pages deploys in the 500 runs to 2026-08-28 were this gate,
	// and the ones that were the harness rather than the product were all "an
	// assertion that holds on SOME deals" — green here, red in CI on the first run
	// that drew the other hand. Each block below seeds its own stable guest id, so
	// each gets its own fixed deal no matter which LANE it lands in. Override it
	// to re-roll every hand at once when you want to know a check is not merely
	// memorising one deal. See core.rooms.deal_rng.
	api = spawn("python", ["-m", "uvicorn", "app:app", "--port", String(API_PORT)],
		{ cwd: repoRoot, stdio: "ignore", shell: true,
			env: { ...process.env, GAMES_DEAL_SEED: process.env.GAMES_DEAL_SEED || "screens-1" } });
	// The build needs nothing from the backend, so it runs WHILE uvicorn boots
	// rather than after it. Started before the await so both clocks run together.
	const built = runBuild();
	await waitForHttp(`http://localhost:${API_PORT}/health`, 90_000, "backend");
	const health = await (await fetch(`http://localhost:${API_PORT}/health`)).json();
	if (!(health.started_at >= spawnedAt - 2)) {
		throw new Error(
			`port ${API_PORT} is already serving a DIFFERENT backend (started_at=${health.started_at}, ` +
			`we started at ${spawnedAt}). Kill it and re-run — otherwise this harness tests stale code.`);
	}
	console.log("  backend up (verified ours)");
	await built;
	console.log("  built");

	console.log("serving the built frontend ...");
	preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"],
		{ cwd: webappDir, stdio: "ignore", shell: true });
	await waitForHttp(`http://localhost:${PORT}/`, 60_000, "vite preview");
	console.log("  preview up");

	browser = await launchBrowser();
	const failures = [];

	const shell = [];

	// Dissonance's cheapest legal bid, used by both blocks below. It is a helper and
	// not four inline clicks because of a RACE that bites intermittently: the
	// denomination buttons are disabled per LEVEL, so clicking a level and then
	// immediately reading `:not([disabled])` can pick from the PREVIOUS render.
	// The Bid button then stays disabled — and as the opener there is no Pass, so
	// the harness spun in the auction until its loop ran out, and the failure
	// surfaced as "no tricks were ever played" rather than as a stuck auction.
	// Settle between clicks, and confirm the button really is live.
	const disBidCheaply = async (page) => {
		// NO LEVELS LEFT IS A REAL STATE, not a broken selector. Denominations are
		// per-player no-repeat, so once this seat has named all five it can only
		// pass. Reaching for a level anyway burned a 5s actionability timeout an
		// iteration, and the CALLER's "are we bidding" test keyed on the same
		// element, so the harness sat out its whole deadline in the auction and
		// reported it as "no tricks were ever played".
		//
		// `:not([disabled])` IS LOAD-BEARING SINCE THE PAD BECAME FIXED. The
		// grid now always renders the whole ladder and disables the rungs that
		// do not outrank the standing bid, so `button` alone matches keys that
		// can never be clicked — and `.first()` is usually one of them. Playwright
		// waits out its full actionability timeout on a disabled button, which is
		// the exact hang described above, arrived at from the other direction.
		const levels = page.locator(".dis-bidgrid button:not([disabled])");
		if (await levels.count() === 0) {
			await page.getByRole("button", { name: /^Pass$/ }).first()
				.click({ timeout: 5_000 }).catch(() => {});
			return "";
		}
		await levels.first().click({ timeout: 5_000 }).catch(() => {});
		await sleep(150);
		// WHAT THE SELECTED BID IS WORTH, read HERE and returned to the caller.
		// The pick row is filled from local state the instant a rung is chosen,
		// so it is populated on every bid this harness makes -- where the
		// STANDING contract's row depends on whether a bid has landed yet, i.e.
		// on which seat opened, which is random. A check that sampled the
		// standing row at one instant duly failed in CI and skipped the deploy.
		const picked = await page.locator(".dis-worth-pick").first()
			.textContent().catch(() => "");
		const denoms = page.locator(".dis-denoms button:not([disabled])");
		const n = await denoms.count();
		for (let d = 0; d < n; d++) {
			await denoms.nth(d).click({ timeout: 5_000 }).catch(() => {});
			await sleep(150);
			const bid = page.getByRole("button", { name: /^Bid / }).first();
			if (await bid.count() && await bid.isEnabled()) {
				await bid.click({ timeout: 5_000 }).catch(() => {});
				return (picked || "").replace(/\s+/g, " ").trim();
			}
		}
		// Nothing legal at that level — pass if the rules allow it. The opener
		// cannot, but by then some denomination above will have worked.
		await page.getByRole("button", { name: /^Pass$/ }).first()
			.click({ timeout: 5_000 }).catch(() => {});
		return (picked || "").replace(/\s+/g, " ").trim();
	};

	async function routeMounts(log) {
		for (const { path: route, chunk, marker } of SCREENS) {
			const ctx = await browser.newContext();
			// A guest identity skips the auth screen without touching the DB.
			await ctx.addInitScript(() => localStorage.setItem("spender_user",
				JSON.stringify({ id: "screens-harness", name: "Harness", guest: true })));
			const page = await ctx.newPage();
			const errors = [];
			const assets = [];
			page.on("pageerror", (e) => errors.push(String(e)));
			page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });
			page.on("request", (r) => {
				const u = r.url();
				if (u.includes("/assets/")) assets.push(u.split("/").pop());
			});

			await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: "networkidle" });
			// The screen arrives after the backend ping resolves and the lazy chunk lands.
			let markerCount = 0;
			for (let i = 0; i < 20 && markerCount === 0; i++) {
				markerCount = await page.locator(marker).count().catch(() => 0);
				if (markerCount === 0) await sleep(400);
			}
			const rootLen = await page.evaluate(() => document.getElementById("root").innerHTML.length);
			const gotChunk = assets.some((a) => a.startsWith(`${chunk}-`));

			const problems = [];
			if (markerCount === 0) problems.push(`no element matching "${marker}" (screen never mounted)`);
			if (!gotChunk) problems.push(`lazy chunk ${chunk}-*.js was never fetched`);
			if (rootLen < 5000) problems.push(`#root only ${rootLen} chars (looks like the loader)`);
			if (errors.length) problems.push(`${errors.length} page error(s): ${errors[0].slice(0, 200)}`);

			if (problems.length) {
				failures.push(`${route}: ${problems.join("; ")}`);
				log(`  FAIL ${route}`);
				problems.forEach((p) => log(`         ${p}`));
			} else {
				log(`  OK   ${route.padEnd(10)} chunk=${chunk} #root=${rootLen}`);
			}
			await ctx.close();
		}
	}

	// ── Shell interactions ────────────────────────────────────────────────────
	// Rendering a screen by URL proves the component mounts. These prove the SHELL
	// still works: the state it owns (screen, identity, routing) is exactly what a
	// Spender.jsx shell/game split would break, and none of it is exercised by
	// loading a deep link directly.
	async function shellNav(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "screens-harness", name: "Harness", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));

		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};
		const has = async (sel, ms = 25_000) => {
			await page.waitForSelector(sel, { timeout: ms }).catch(() => {});
			return (await page.locator(sel).count().catch(() => 0)) > 0;
		};
		// A click that can't land is itself a finding, not a reason to abort: when the
		// shell breaks, several checks fail together and the whole picture is the
		// useful output. Swallow the timeout so the remaining checks still report.
		const click = async (sel, nth = 0) => {
			try { await page.locator(sel).nth(nth).click({ timeout: 15_000 }); return true; }
			catch { return false; }
		};
		const at = () => { try { return new URL(page.url()).pathname; } catch { return "?"; } };

		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
		check("home renders the game menu", await has(".home-game-card"));

		// Click through to a game. nav() must write the URL BEFORE switching screen,
		// because a sub-game reads parsePath() at mount.
		check("can click the Duel card", await click(".home-game-card", 3));
		check("clicking a game card mounts that game", await has(".duel"));
		check("...and the URL became its route", at() === "/duel", `got ${at()}`);

		// Back must return home. The router contract is that popstate is the ONLY
		// notifier and a no-op path write never double-pushes — a broken split shows
		// up here as Back doing nothing, or needing two presses.
		await page.goBack({ waitUntil: "networkidle" }).catch(() => {});
		check("Back returns to the home menu", await has(".home-game-card"));
		check("...and the URL went back to /", at() === "/", `got ${at()}`);

		// Spender's own lobby is the shell's most entangled screen: it shares the
		// shell's auth state and game-list fetching.
		check("can click the Spender card", await click(".home-game-card", 0));
		check("Spender lobby renders", await has(".browser"));

		check("no page errors during shell navigation", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Auth screen ───────────────────────────────────────────────────────────
	// Every context above SEEDS a guest identity to skip straight to a game, so
	// nothing else here ever renders the auth screen. It is the site's front door
	// and the first screen extracted out of Spender.jsx, so it gets its own pass
	// with NO stored user.
	async function authScreen(log) {
		const ctx = await browser.newContext();           // deliberately unseeded
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};
		const has = async (sel, ms = 25_000) => {
			await page.waitForSelector(sel, { timeout: ms }).catch(() => {});
			return (await page.locator(sel).count().catch(() => 0)) > 0;
		};

		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
		check("a fresh visitor gets the auth screen", await has(".auth-screen"));
		check("...with all three tabs", await page.locator(".auth-tab").count() === 3);

		// Guest sign-in is the one path that needs no account, so it is the flow the
		// harness can drive end to end: it must produce an identity and land on home.
		await page.locator(".auth-tab").nth(2).click().catch(() => {});
		const guestBtn = page.locator("button", { hasText: "Play as Guest" });
		await guestBtn.click({ timeout: 15_000 }).catch(() => {});
		check("guest sign-in reaches the home menu", await has(".home-game-card"));
		const stored = await page.evaluate(() => localStorage.getItem("spender_user"));
		check("...and a guest is NOT persisted to localStorage", stored === null,
			`got ${stored}`);
		// THE TAB STRIP HOLDS STILL ACROSS THE THREE TABS, AT EVERY TIER — and note what
		// this replaced. It used to assert the panel was ONE HEIGHT, which was the right
		// check while the card was vertically centred: a shorter tab moved the strip up,
		// under the cursor that had just clicked it. The card is top-anchored now, so the
		// strip cannot move whatever the panel does, and holding the height instead cost
		// an 84px void above and below Guest's fact list. THE HAZARD IS THE SAME ONE; only
		// the mechanism that guards it changed, so this asserts the thing that actually
		// matters rather than a proxy for it. 1920 is here because the >=1500 tier scales
		// the type, and is where an edited helper line would first show up.
		for (const vp of [{ width: 1280, height: 800 }, { width: 1920, height: 1080 }]) {
			await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
			await page.setViewportSize(vp);
			await page.waitForSelector(".auth-card", { timeout: 20_000 }).catch(() => {});
			const marks = [];
			for (let i = 0; i < 3; i++) {
				await page.locator(".auth-tab").nth(i).click().catch(() => {});
				await page.waitForTimeout(220);
				marks.push(await page.evaluate(() => {
					const t = document.querySelector(".auth-tabs").getBoundingClientRect();
					const c = document.querySelector(".auth-card").getBoundingClientRect();
					const f = document.querySelector(".auth-field");
					return { tabs: Math.round(t.top), card: Math.round(c.top),
						field: f ? Math.round(f.getBoundingClientRect().top) : null };
				}).catch(() => null));
			}
			const same = (k) => new Set(marks.map((m) => m && m[k])).size === 1;
			check(`the tab strip and the first field hold still across the tabs at ${vp.width}x${vp.height}`,
				same("tabs") && same("card") && same("field"), JSON.stringify(marks));
		}

		// EVERY PIECE OF TEXT ON THE FRONT DOOR CLEARS AA, not just the ones someone
		// thought to check. Three separate review rounds each found a different single
		// element under 4.5:1 -- a helper line, a section label, a button label -- and each
		// time it was a token reused one step too far down the hierarchy. This walks the
		// rendered text instead: for each text node it composites the real background by
		// walking ancestors to the first opaque fill, so it measures what is actually behind
		// the glyphs rather than `--bg`. That matters here because the top of the page is
		// LIT -- the warm lamp raises the local ground and takes the contrast down with it,
		// which is exactly how "GUEST" measured 4.02 while its token measured 5.9.
		const thin = await page.evaluate(() => {
			const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
			const rgb = (v) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = "#000"; cv.fillStyle = v;
				cv.fillRect(0, 0, 1, 1); return [...cv.getImageData(0, 0, 1, 1).data]; };
			const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; };
				return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
			const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };
			// First ancestor with a non-transparent background, flattened over the page ground.
			const groundOf = (el) => {
				const base = rgb(getComputedStyle(document.body).backgroundColor);
				let out = [base[0], base[1], base[2]];
				const stack = [];
				for (let n = el; n && n !== document.documentElement; n = n.parentElement) stack.unshift(n);
				for (const n of stack) {
					const c = rgb(getComputedStyle(n).backgroundColor);
					const a = c[3] / 255;
					if (a > 0) out = out.map((v, i) => Math.round(c[i] * a + v * (1 - a)));
				}
				return out;
			};
			const bad = [];
			for (const el of document.querySelectorAll(".auth-screen *")) {
				const txt = [...el.childNodes].filter((n) => n.nodeType === 3)
					.map((n) => n.textContent.trim()).join(" ").trim();
				if (!txt) continue;
				const cs = getComputedStyle(el);
				if (cs.visibility === "hidden" || cs.display === "none" || +cs.opacity === 0) continue;
				// The wordmark's glyphs are painted by a gradient through `background-clip:text`,
				// so its `color` is transparent and compositing it against the ground measures
				// 1.09:1 on type that is obviously fine. Skip ONLY that case, narrowly: a
				// transparent colour with no text-clipped background is a genuine bug and must
				// still be caught.
				const clipped = (cs.webkitBackgroundClip || cs.backgroundClip) === "text";
				if (clipped && rgb(cs.color)[3] === 0) continue;
				const px = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700;
				// WCAG "large text": >=24px, or >=18.66px bold.
				const floor = (px >= 24 || (bold && px >= 18.66)) ? 3 : 4.5;
				const r = ratio(rgb(cs.color), groundOf(el));
				if (r < floor) bad.push(`"${txt.slice(0, 28)}" ${r.toFixed(2)}:1 @${px}px (needs ${floor})`);
			}
			return bad;
		});
		check("every piece of text on the sign-in screen clears its AA floor",
			thin.length === 0, thin.join(" | ").slice(0, 400));

		// THE BUSY BUTTON DRAWS A SPINNER AND DOES NOT MOVE ITS LABEL. Both halves
		// were broken at once and by the same line: the pending state rendered
		// `<span className="spinner" />`, a class no stylesheet has defined since
		// the site's three hand-rolled spinners were folded into `.lby-spinner`.
		// It therefore painted a 0x0 box — no feedback at all on the one control
		// the whole front door hangs on — while still taking a flex slot in a
		// `.btn` with `gap: 8px`, which slid the centred label 4px right for the
		// length of the request and back again when it resolved. Measured: 4.00px
		// on iPhone-sized viewports, held for as long as the login took. Neither
		// half shows up in a screenshot of the resting screen, so both are
		// asserted here: the spinner has a real box and a running animation, and
		// the label's own text range does not move between the two states.
		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
		await page.waitForSelector(".auth-screen", { timeout: 20_000 }).catch(() => {});
		// Hold the request open so the pending state can be measured at leisure.
		await page.route("**/auth/login", async (route) => { await sleep(1500); await route.continue(); });
		await page.locator(".auth-tab").first().click().catch(() => {});
		await page.locator("#auth-name").fill("screensgate").catch(() => {});
		await page.locator("#auth-pass").fill("screensgate").catch(() => {});
		const labelX = () => page.evaluate(() => {
			const button = document.querySelector(".auth-panel .btn");
			const text = [...button.childNodes].find((node) => node.nodeType === 3);
			const range = document.createRange();
			range.selectNodeContents(text);
			const spin = button.querySelector(".btn-spin");
			return {
				x: Math.round(range.getBoundingClientRect().x * 100) / 100,
				spinner: spin && { w: Math.round(spin.getBoundingClientRect().width),
					animating: spin.getAnimations().length > 0 },
			};
		}).catch(() => null);
		const resting = await labelX();
		await page.locator(".auth-panel .btn").click().catch(() => {});
		await page.waitForTimeout(320);
		const busy = await labelX();
		check("the busy sign-in button shows a real spinner without moving its label",
			!!resting && !!busy && !resting.spinner && !!busy.spinner
			&& busy.spinner.w >= 8 && busy.spinner.animating && busy.x === resting.x,
			JSON.stringify({ resting, busy }));
		await page.unroute("**/auth/login");

		check("no page errors during auth", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}


	// ── Home screen: the two things about it that are MEASURED, not eyeballed ──
	//
	// `routeMounts`/`shellNav` prove the menu renders and its cards click through.
	// Neither can see the two properties the landing page was actually shipping
	// broken, because both are quantities rather than presence:
	//
	//  1. THE CONTENT COLUMN'S WIDTH. `.home` had `margin:0 auto` + `max-width` and
	//     is a flex ITEM, and auto inline margins on a flex item cancel the default
	//     `stretch` — so the box sized to fit-content (~516px) and the max-width
	//     never applied at ANY viewport. The whole site rendered as a narrow ribbon
	//     down the middle of a desktop for as long as that rule existed, and every
	//     DOM-level check passed the entire time. A width is the only thing that
	//     catches it, so this asserts the column really does use the screen.
	//  2. THE ACCENT PALETTE. Each game's colour is its card title's ink, so it has
	//     to clear AA on the card (the titles are ~1.2rem — under the large-text
	//     exemption), and all game accents have to be tellable APART or the colour is not
	//     doing the identifying job it exists for. Two of them were the same gold.
	//     Both are properties of a hex literal in shared/HomeScreen.jsx, i.e. exactly
	//     the kind of thing a new game copies from its neighbour and gets wrong; the
	//     failure is a title that is merely hard to read, which nothing else fails on.
	//
	// Colour maths runs in the PAGE, off getComputedStyle, so it measures what the
	// browser actually painted — including any later stylesheet that overrides an
	// accent — rather than re-reading the source constants and agreeing with itself.
	async function homeScreen(log) {
		const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "screens-home", name: "Harness", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
		await page.waitForSelector(".home-game-card", { timeout: 25_000 }).catch(() => {});

		const m = await page.evaluate(() => {
			const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
			const rgb = (s) => {
				cv.clearRect(0, 0, 1, 1); cv.fillStyle = "#000"; cv.fillStyle = s;
				cv.fillRect(0, 0, 1, 1);
				return [...cv.getImageData(0, 0, 1, 1).data].slice(0, 3);
			};
			const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
			const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
			const contrast = (a, b) => {
				const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
				return (x + 0.05) / (y + 0.05);
			};
			// Hue only needs to be good enough to catch "these two are the same
			// colour", so plain HSL hue beats pulling in a colour library.
			const hue = ([r, g, b]) => {
				const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
				if (!d) return null;                       // grey: no hue to compare
				let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
				return ((h * 60) % 360 + 360) % 360;
			};
			const cards = [...document.querySelectorAll(".home-game-card")];
			const names = cards.map((c) => {
				const t = c.querySelector(".home-game-name");
				// The card paints a gradient, so `backgroundColor` is transparent and
				// the ink actually sits on the page ground under it. Measure against
				// --surface, the lighter of the two stops, which is the harder case.
				const surface = rgb(getComputedStyle(document.documentElement).getPropertyValue("--surface") ||
					getComputedStyle(document.body).backgroundColor);
				const ink = rgb(getComputedStyle(t).color);
				return { text: t.textContent, id: c.dataset.game, ink, hue: hue(ink),
					contrast: +contrast(ink, surface).toFixed(2) };
			});
			const home = document.querySelector(".home").getBoundingClientRect();
			const grid = document.querySelector(".home-games").getBoundingClientRect();
			const extras = document.querySelector(".home-extras").getBoundingClientRect();
			const pillY = cards.slice(0, 3).map((c) =>
				Math.round(c.querySelector(".home-game-players").getBoundingClientRect().bottom));
			return {
				names, homeW: Math.round(home.width), innerW: window.innerWidth,
				docW: document.documentElement.scrollWidth,
				gridL: Math.round(grid.left), gridR: Math.round(grid.right),
				extrasL: Math.round(extras.left), extrasR: Math.round(extras.right),
				pillY, cards: cards.length,
			};
		});

		check("the home column uses the screen, not fit-content", m.homeW >= m.innerW * 0.7,
			`.home is ${m.homeW}px inside a ${m.innerW}px viewport — if this collapsed to `
			+ `~516px, something reintroduced an auto inline margin on the flex item`);
		check("the home page does not scroll sideways", m.docW <= m.innerW, `${m.docW} > ${m.innerW}`);
		// Two blocks, one pair of edges: the catalogue and the side features had
		// private max-widths that agreed at neither end.
		check("the catalogue and the side features share both edges",
			m.gridL === m.extrasL && m.gridR === m.extrasR,
			`games ${m.gridL}..${m.gridR} vs extras ${m.extrasL}..${m.extrasR}`);
		// The pill is a sibling of the card head precisely so this holds.
		check("every player-count pill in a row sits on one baseline",
			new Set(m.pillY).size === 1, JSON.stringify(m.pillY));

		// THE EMBLEM PLATE MUST CARRY ITS ACCENT'S HUE. It is derived by mixing the
		// accent into the card ground, and mixing in sRGB let the ground's warm hue win
		// — hardest for the cool accents, where Where Wolf's plate came out
		// chromatically NEUTRAL and read as disabled beside six tinted siblings, and
		// Dontminion's cyan rendered green. A plate that has lost its hue is exactly as
		// broken as a title that has, and neither shows up in any DOM check.
		const plates = await page.evaluate(() => {
			const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
			const rgb = (s) => {
				cv.clearRect(0, 0, 1, 1); cv.fillStyle = "#000"; cv.fillStyle = s;
				cv.fillRect(0, 0, 1, 1);
				return [...cv.getImageData(0, 0, 1, 1).data].slice(0, 3);
			};
			const hue = ([r, g, b]) => {
				const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
				if (!d) return null;
				let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
				return ((h * 60) % 360 + 360) % 360;
			};
			return [...document.querySelectorAll(".home-game-card")].map((c) => {
				const ink = rgb(getComputedStyle(c.querySelector(".home-game-name")).color);
				const fill = rgb(getComputedStyle(c.querySelector(".home-game-emblem")).backgroundColor);
				const [mx, mn] = [Math.max(...fill), Math.min(...fill)];
				return { text: c.querySelector(".home-game-name").textContent,
					accentHue: hue(ink), plateHue: hue(fill), plateChroma: +((mx - mn) / 255).toFixed(3) };
			});
		});
		const flat = plates.filter((p) => p.plateChroma < 0.045);
		check("every emblem plate is visibly tinted", flat.length === 0,
			flat.map((f) => `${f.text} chroma ${f.plateChroma}`).join(", "));
		const drift = plates.filter((p) => p.accentHue != null && p.plateHue != null
			&& Math.min(Math.abs(p.accentHue - p.plateHue), 360 - Math.abs(p.accentHue - p.plateHue)) > 22);
		check("...and holds its accent's hue", drift.length === 0,
			drift.map((d) => `${d.text} ${Math.round(d.accentHue)}->${Math.round(d.plateHue)}`).join(", "));

		// EVERY CARD IS THE SAME SIZE, AT EVERY TIER. There used to be a "banner": a card
		// alone on its row spanned the row, which made the final game a different shape
		// from the other six and cost three separate bugs on its own (the pill's alignment,
		// a chevron that leaked into the one-column tier, and a plate 15px below its
		// siblings'). The user's call, and the right one: identical cards, and a last
		// row that is simply not full. This is the check that keeps it that way.
		for (const w of [390, 834, 1180, 1600, 1920]) {
			await page.setViewportSize({ width: w, height: 1000 });
			await page.waitForTimeout(250);
			const cards = await page.evaluate(() => {
				const cs = [...document.querySelectorAll(".home-game-card")];
				const r = (e) => e.getBoundingClientRect();
				const at = (c, sel) => { const e = c.querySelector(sel); return e
					? [Math.round(r(e).left - r(c).left), Math.round(r(e).top - r(c).top)] : null; };
				return {
					w: cs.map((c) => Math.round(r(c).width)),
					h: cs.map((c) => Math.round(r(c).height)),
					plate: cs.map((c) => String(at(c, ".home-game-emblem"))),
					title: cs.map((c) => String(at(c, ".home-game-name"))),
					pill: cs.map((c) => String(at(c, ".home-game-players"))),
					chevron: cs.map((c) => +getComputedStyle(c.querySelector(".home-game-go")).opacity),
				};
			});
			const one = (k) => new Set(cards[k]).size === 1;
			check(`all game cards are identical at ${w}px`,
				["w", "h", "plate", "title", "pill", "chevron"].every(one),
				JSON.stringify(cards));
		}
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.waitForTimeout(200);

		// THE TITLES CLEAR AA, WITH A SELF-POLICING EXEMPTION LIST. A game's accent is its
		// own `--lby-accent` and is not adjusted to suit this check (see
		// shared/accents.js), so one title ships under the 4.5:1 floor by explicit
		// choice. An exemption that only ever whitelists is a hole, so this fails three
		// ways: an unlisted title under 4.5, a LISTED title that has since fallen under
		// 3.0 (the floor the spine and plate are held to), and a listed title that now
		// clears 4.5 — a STALE row, which must be deleted rather than left claiming an
		// exemption it no longer needs. Same shape as core/tests/test_no_conditional_skips.py.
		const exempt = ACCENT_AA_EXEMPT;   // shared/accents.js — one list, not two
		const dim = m.names.filter((n) => !exempt[n.id] && n.contrast < 4.5);
		check(`all ${m.names.length} game titles clear AA on the card`, dim.length === 0,
			dim.map((d) => `${d.text} ${d.contrast}:1`).join(", "));
		const exBad = m.names.filter((n) => exempt[n.id] && n.contrast < 3);
		check("...and the exempted title still clears the 3:1 floor", exBad.length === 0,
			exBad.map((d) => `${d.text} ${d.contrast}:1`).join(", "));
		const exStale = m.names.filter((n) => exempt[n.id] && n.contrast >= 4.5);
		check("...and no exemption is stale", exStale.length === 0,
			exStale.map((d) => `${d.text} now clears AA at ${d.contrast}:1 — drop its row`).join(", "));
		const exUnseen = Object.keys(exempt).filter((k) => !m.names.some((n) => n.id === k));
		check("...and every exemption names a real card", exUnseen.length === 0, exUnseen.join(", "));

		// THE CARD'S COLOUR IS THE GAME'S COLOUR — the check this whole section exists
		// for, and the one that was missing when it mattered. Each game sets a
		// `--lby-accent` driving its own lobby, and the home card is supposed to be the
		// same value; the two lived in different files agreeing only by habit, and the
		// moment a palette rule pushed on the catalogue they drifted — Castles of CRIMSON
		// shipped pink and Dontminion's gold shipped cyan, past every check here,
		// because nothing compared the two ends. This enters each game and compares its
		// RENDERED `--lby-accent` against the colour its home card actually paints, so it
		// holds for the two games that define theirs in CSS and cannot import the shared
		// module. Comparison is on painted sRGB, not on the token text, so a hex, a
		// resolved `var()` and an `rgb()` all compare equal.
		const ACCENT_PAGES = [
			{ id: "spender", card: 0, marker: ".browser" },
			{ id: "coc", path: "/coc", marker: ".coc" },
			{ id: "wherewolf", path: "/werewolf", marker: ".ww" },
			{ id: "duel", path: "/duel", marker: ".duel" },
			{ id: "dontminion", path: "/dontminion", marker: ".dm" },
			{ id: "dissonance", path: "/dissonance", marker: ".dis" },
			{ id: "ragtag", path: "/ragtag", marker: ".ragtag" },
			{ id: "orbit", path: "/orbit", marker: ".orbit" },
		];
		// Every game in the catalogue must be listed, or a new one joins unmeasured —
		// the roster is derived, not hand-kept.
		const unlisted = Object.keys(GAME_ACCENTS).filter((k) => !ACCENT_PAGES.some((g) => g.id === k));
		check("every game in the catalogue is colour-checked", unlisted.length === 0, unlisted.join(", "));
		const cardInk = Object.fromEntries(m.names.map((n) => [n.id, n.ink.join(",")]));
		const mismatched = [];
		for (const g of ACCENT_PAGES) {
			const c = await browser.newContext();
			await c.addInitScript(() => localStorage.setItem("spender_user",
				JSON.stringify({ id: "accent-fidelity", name: "Harness", guest: true })));
			const pg = await c.newPage();
			await pg.goto(`http://localhost:${PORT}${g.path || "/"}`, { waitUntil: "load" });
			if (g.card != null) await pg.locator(".home-game-card").nth(g.card)
				.click({ timeout: 15_000 }).catch(() => {});
			const there = await pg.waitForSelector(g.marker, { timeout: 25_000 })
				.then(() => true).catch(() => false);
			const got = there ? await pg.evaluate((sel) => {
				const cv = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
				const raw = getComputedStyle(document.querySelector(sel))
					.getPropertyValue("--lby-accent").trim();
				cv.fillStyle = "#000"; cv.fillStyle = raw; cv.fillRect(0, 0, 1, 1);
				return { raw, rgb: [...cv.getImageData(0, 0, 1, 1).data].slice(0, 3).join(",") };
			}, g.marker) : null;
			await c.close();
			if (!there) { mismatched.push(`${g.id}: ${g.marker} never rendered`); continue; }
			if (!got.raw) { mismatched.push(`${g.id}: sets no --lby-accent`); continue; }
			if (got.rgb !== cardInk[g.id])
				mismatched.push(`${g.id}: card ${cardInk[g.id]} vs game ${got.rgb} (${got.raw})`);
		}
		check("every home card is its game's own colour", mismatched.length === 0,
			mismatched.join(" | "));

		// THE WIDTHS A LADDER BREAKS AT ARE THE ONES ON ITS BOUNDARIES, and a fixed set
		// of device viewports never visits them: this walks 559/560, 999/1000 and
		// 1499/1500 (each tier's last and first pixel) plus the extremes, and asserts
		// three things at every one — the page does not scroll sideways, no card escapes
		// the content column, and the six grid cards are all the SAME width. That last
		// one is what catches a `calc()` basis that stops dividing evenly, which is the
		// shape every bug in this grid has had.
		const boundaries = [280, 320, 559, 560, 640, 834, 999, 1000, 1100, 1280, 1499, 1500, 1920, 2560];
		const bad = [];
		for (const w of boundaries) {
			await page.setViewportSize({ width: w, height: 900 });
			await page.waitForTimeout(200);
			const m = await page.evaluate(() => {
				const cards = [...document.querySelectorAll(".home-game-card")];
				const box = document.querySelector(".home").getBoundingClientRect();
				// ALL GAME CARDS, not just the first row. The final card used to be a full-width banner
				// and had to be excluded here; every card is the same size now, so
				// including it is the stronger check and this line is the assertion.
				const widths = [...new Set(cards.map((c) => Math.round(c.getBoundingClientRect().width)))];
				const outside = cards.filter((c) => {
					const r = c.getBoundingClientRect();
					return r.left < box.left - 1 || r.right > box.right + 1;
				}).length;
				return { over: document.documentElement.scrollWidth > window.innerWidth, widths, outside };
			});
			if (m.over || m.outside || m.widths.length !== 1) bad.push(`${w}px ${JSON.stringify(m)}`);
		}
		check(`the home grid survives all ${boundaries.length} breakpoint boundaries`, bad.length === 0,
			bad.slice(0, 3).join(" | "));

		// ── SHELL WORDMARKS ─────────────────────────────────────────────────────
		// Loading and auth are one entrance sequence, so their hero lockup must not
		// shift while the backend wakes. The menu intentionally differs: it puts a
		// compact wordmark in its identity rail, leaving the catalogue as the page's
		// title. Test both contracts rather than letting an old "all three match" rule
		// undo the menu composition.
		const lockup = async (page) => page.evaluate(() => {
			const el = document.querySelector(".auth-logo,.loading-logo");
			const cs = getComputedStyle(el), r = el.getBoundingClientRect();
			const rule = document.querySelector(".home-rule");
			return { top: Math.round(r.top + window.scrollY),
				px: cs.fontSize, track: cs.letterSpacing,
				ruleW: rule ? Math.round(rule.getBoundingClientRect().width) : null,
				gap: rule ? Math.round(rule.getBoundingClientRect().top - r.bottom) : null };
		});
		// Two viewports are deliberate: a responsive contract tested at only one branch is
		// no contract at all.
		for (const vp of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
		await page.setViewportSize(vp);
		await page.waitForTimeout(250);
		const menu = await page.evaluate(() => {
			const header = document.querySelector(".home-header");
			const logo = document.querySelector(".home-corner-logo");
			const user = document.querySelector(".browser-user");
			const rule = document.querySelector(".home-rule");
			if (!header || !logo || !user) return null;
			const h = header.getBoundingClientRect(), l = logo.getBoundingClientRect(), u = user.getBoundingClientRect();
			return { left: Math.round(l.left - h.left), top: Math.round(l.top - h.top),
				bottom: Math.round(h.bottom - l.bottom), beforeUser: l.right < u.left, rule: !!rule,
				fontSize: parseFloat(getComputedStyle(logo).fontSize) };
		});
		check(`the menu keeps a compact wordmark in its identity rail at ${vp.width}x${vp.height}`,
			menu && Math.abs(menu.left) <= 1 && menu.top >= -1 && menu.bottom >= -1
				&& menu.beforeUser && !menu.rule && menu.fontSize < 28,
			JSON.stringify(menu));
		const marks = {};
		for (const [name, seedUser, stall] of [["auth", false, false], ["loading", false, true]]) {
			const c = await browser.newContext({ viewport: vp });
			// The loading screen is only reachable when the backend MISSES the shell's
			// 250ms fast path, which is the spun-down-dyno case it exists for.
			if (stall) await c.route("**/games**", async (route) => {
				await new Promise((r) => setTimeout(r, 1200)); await route.continue();
			});
			const pg = await c.newPage();
			await pg.goto(`http://localhost:${PORT}/`, { waitUntil: "load" });
			await pg.waitForSelector(stall ? ".loading-logo" : ".auth-logo", { timeout: 25_000 }).catch(() => {});
			await pg.waitForTimeout(400);
			marks[name] = await lockup(pg).catch(() => null);
			await c.close();
		}
		const off = ["top", "px", "track", "ruleW", "gap"].filter((k) =>
			new Set(Object.values(marks).map((m) => m?.[k])).size !== 1);
		check(`the wordmark lockup is identical on loading and auth at ${vp.width}x${vp.height}`,
			marks.auth && marks.loading && off.length === 0,
			off.length ? `${off.join(",")} differ: ${JSON.stringify(marks)}` : "a screen did not render");
		}

		check("no page errors on the home menu", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Play a turn ───────────────────────────────────────────────────────────
	// The only end-to-end exercise of the stack that actually matters: create a
	// vs-AI game, take gems, and watch the board change. Everything above proves
	// screens MOUNT. This proves the WebSocket handshake, the room server, the
	// engine's apply_move, the per-recipient broadcast and the AI scheduler all
	// still work together — none of which any other test touches from the client.
	//
	// It is also the coverage the shell/game split needs: `screen` currently
	// conflates the site-level mode with Spender's own browser/waiting/game, and
	// separating them is exactly the kind of change that renders fine and plays
	// wrong.
	async function spenderPlayTurn(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "play-harness", name: "Player", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};
		const has = async (sel, ms = 25_000) => {
			await page.waitForSelector(sel, { timeout: ms }).catch(() => {});
			return (await page.locator(sel).count().catch(() => 0)) > 0;
		};

		await page.goto(`http://localhost:${PORT}/spender`, { waitUntil: "networkidle" });
		check("Spender lobby reachable by URL", await has(".lby-create-row"));

		// New Game -> the modal defaults to a vs-AI opponent, so accept and create.
		await page.locator(".lby-cta").click({ timeout: 15_000 }).catch(() => {});
		check("the create-game modal opens", await has(".cm-panel"));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});

		// A vs-AI game starts immediately — no waiting room.
		check("a vs-AI game starts and the board renders", await has(".gem-stack", 30_000));
		const boardCards = await page.locator(".card").count().catch(() => 0);
		check("the board dealt its cards", boardCards >= 12, `saw ${boardCards}`);

		// The first player is randomised, so the bot may move first — WAIT for our
		// turn rather than assuming it. `disabled` marks a stack that can't be taken
		// (empty bank, or not our turn).
		let takeable = 0;
		for (let i = 0; i < 40 && takeable < 3; i++) {
			takeable = await page.locator(".gem-stack:not(.disabled)").count().catch(() => 0);
			if (takeable < 3) await sleep(500);
		}
		check("our turn arrives (waiting out the bot if it moved first)",
			takeable >= 3, `${takeable} takeable stacks`);

		// Snapshot our own panel: the server broadcast updating it is the proof the
		// move was really applied, and comparing text avoids depending on the exact
		// markup of the token row.
		const myPanel = () => page.locator(".player-panel.me").first().innerText().catch(() => "");
		const panelBefore = await myPanel();

		// Click three distinct COLOURS by data-color. Not `nth(i)` over the
		// non-disabled set: that set is re-evaluated after every click (selecting
		// gems disables others), and it includes the GOLD stack — whose click handler
		// arms a reserve and CLEARS the gem selection, which silently cost a gem.
		const colours = (await page.evaluate(() =>
			[...document.querySelectorAll(".gem-stack:not(.disabled)")]
				.map((e) => e.dataset.color)
				.filter((c) => c && c !== "gold"))).slice(0, 3);
		check("three colours are available to take", colours.length === 3, colours.join(","));
		for (const c of colours) {
			await page.locator(`.gem-stack[data-color="${c}"]`).click({ timeout: 10_000 }).catch(() => {});
		}
		// `button:visible` matters: the actions area is rendered THREE times (mobile and
		// desktop variants) and only one copy is visible. innerText happily reads a
		// hidden copy, so a plain .first() click times out — and because the click was
		// wrapped in .catch(() => {}), the move silently never happened while the label
		// check still passed. Clicking is now a CHECK, not a swallowed side effect.
		const takeBtn = page.locator("button:visible", { hasText: /^Take/ });
		const takeLabel = await takeBtn.first().innerText().catch(() => "");
		check("the Take button reflects the 3 selected gems",
			takeLabel.replace(/\s+/g, "") === "Take3", `label was ${JSON.stringify(takeLabel)}`);
		const submitted = await takeBtn.first().click({ timeout: 15_000 })
			.then(() => true).catch(() => false);
		check("the Take button is clickable", submitted);

		let panelAfter = panelBefore;
		for (let i = 0; i < 30 && panelAfter === panelBefore; i++) {
			await sleep(400);
			panelAfter = await myPanel();
		}
		check("the server applied the move and re-broadcast our panel",
			panelAfter !== panelBefore && panelAfter.length > 0,
			`panel unchanged: ${JSON.stringify(panelBefore.slice(0, 60))}`);
		// Back OUT of a live room. This drives applyPopRoute's inSpenderRoom branch —
		// the subtlest thing the site/Spender screen split touches, since it has to tell
		// "in a Spender ROOM" (waiting/game) from "in the Spender LOBBY" (browser) now
		// that those live in two different pieces of state.
		await page.goBack({ waitUntil: "networkidle" }).catch(() => {});
		const backToLobby = await has(".lby-create-row", 20_000);
		check("Back leaves a live game and returns to the Spender lobby", backToLobby,
			`url ${new URL(page.url()).pathname}`);

		// Puzzles are their own SITE-level mode but render on Spender's GAME screen —
		// the one place the two levels deliberately disagree (site mode "puzzles",
		// spenderScreen "game", puzzling=true, and no socket). /puzzles picks one
		// immediately rather than showing a list, so assert the board itself.
		await page.goto(`http://localhost:${PORT}/puzzles`, { waitUntil: "networkidle" });
		const puzzleBoard = await has(".game", 25_000);
		const puzzleText = await page.locator("#root").innerText().catch(() => "");
		check("a puzzle renders on Spender's game screen", puzzleBoard && /PUZZLE/i.test(puzzleText),
			`board=${puzzleBoard} url=${new URL(page.url()).pathname}`);

		check("no page errors while playing", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Two clients: the waiting room ─────────────────────────────────────────
	// Spender's `waiting` screen is only reachable in a human-vs-human game, so a
	// single-client walk can never see it — it was the last Spender screen with no
	// coverage at all. Two browser contexts: one creates a friend game, the other
	// joins by the shared room code, and both must end up seated in the same room.
	// This also exercises the join handshake and the broadcast fan-out to a SECOND
	// socket, which the vs-AI walk never touches.
	async function spenderWaitingRoom(log) {
		const mk = async (id) => {
			const c = await browser.newContext();
			await c.addInitScript((pid) => localStorage.setItem("spender_user",
				JSON.stringify({ id: pid, name: pid, guest: true })), id);
			return c;
		};
		const hostCtx = await mk("host-harness");
		const joinCtx = await mk("join-harness");
		const host = await hostCtx.newPage();
		const joiner = await joinCtx.newPage();
		const errors = [];
		host.on("pageerror", (e) => errors.push("host: " + e));
		joiner.on("pageerror", (e) => errors.push("joiner: " + e));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await host.goto(`http://localhost:${PORT}/spender`, { waitUntil: "networkidle" });
		await host.waitForSelector(".lby-create-row", { timeout: 25_000 }).catch(() => {});
		await host.locator(".lby-cta").click({ timeout: 15_000 }).catch(() => {});
		await host.waitForSelector(".cm-panel", { timeout: 15_000 }).catch(() => {});
		// Switch the opponent segment from the default (AI) to "friend".
		await host.locator(".cm-seg button").first().click({ timeout: 10_000 }).catch(() => {});
		await host.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});

		const gotWaiting = await host.waitForSelector(".room-code-box", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a friend game reaches the waiting room", gotWaiting);
		const code = (await host.locator(".room-code-box").innerText().catch(() => "")).trim();
		check("the waiting room shows a join code", /^[A-Z]{4,8}$/.test(code), `got ${JSON.stringify(code)}`);

		if (code) {
			await joiner.goto(`http://localhost:${PORT}/spender`, { waitUntil: "networkidle" });
			await joiner.waitForSelector(".lby-code", { timeout: 25_000 }).catch(() => {});
			await joiner.locator(".lby-code").fill(code).catch(() => {});
			await joiner.locator(".lby-join-btn").click({ timeout: 15_000 }).catch(() => {});
			const joined = await joiner.waitForSelector(".room-code-box", { timeout: 30_000 })
				.then(() => true).catch(() => false);
			check("the second client joins that room", joined);

			// The host must LEARN about the joiner — that is the broadcast working.
			let seats = 0;
			for (let i = 0; i < 25 && seats < 2; i++) {
				seats = await host.locator(".player-list li").count().catch(() => 0);
				if (seats < 2) await sleep(400);
			}
			check("the host sees the second player arrive", seats >= 2, `saw ${seats} seats`);

			// DEEP LINK into that room by URL — the invite-link path. This is driven by
			// a separate deep-entry effect that only runs on Spender's LOBBY screen, and
			// a shipped bug proved nothing was watching it: after the site/Spender screen
			// split its guard still read `screen !== "browser"`, which can never be true
			// now, so invite links silently stopped working while every other check
			// stayed green.
			const deep = await joinCtx.newPage();
			await deep.goto(`http://localhost:${PORT}/spender/${code}`, { waitUntil: "networkidle" });
			const landed = await deep.waitForSelector(".room-code-box, .game", { timeout: 30_000 })
				.then(() => true).catch(() => false);
			check("a deep link enters the room it names", landed,
				`url ${new URL(deep.url()).pathname}`);
			await deep.close();
		}
		check("no page errors in the two-client flow", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await hostCtx.close();
		await joinCtx.close();
	}

	// ── The shared lobby Rules button + how-to-play modal ─────────────────────
	// One kit, every lobby — so it is worth driving all of them rather than one. The
	// three contracts that regress silently:
	//   1. every lobby actually PASSES onRules (the button is opt-in, so a game
	//      that forgets it renders a perfectly fine lobby with no way in);
	//   2. the BODY is the scroller, not the page — `.rl-body` has min-height:0
	//      and one stray CSS edit turns the panel into a page-height modal whose
	//      "Got it" button sits below the fold (the shape every per-game copy of
	//      this modal used to have);
	//   3. on a phone the create row SCROLLS SIDEWAYS instead of wrapping, and
	//      the page itself must not scroll sideways with it.
	async function rulesModal(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "rules-harness", name: "Rules", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		for (const route of ["/spender", "/coc", "/werewolf", "/duel", "/dontminion", "/dissonance", "/ragtag", "/orbit"]) {
			await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: "networkidle" });
			await page.waitForSelector(".lby-rules", { timeout: 25_000 }).catch(() => {});
			const hasBtn = await page.locator(".lby-rules").count().catch(() => 0);
			check(`${route} lobby offers a Rules button`, hasBtn === 1, `count ${hasBtn}`);
			if (!hasBtn) continue;

			await page.locator(".lby-rules").click({ timeout: 10_000 }).catch(() => {});
			await page.waitForSelector(".rl-body", { timeout: 10_000 }).catch(() => {});
			const geom = await page.evaluate(() => {
				const panel = document.querySelector(".rl-panel");
				const body = document.querySelector(".rl-body");
				const done = document.querySelector(".rl-done");
				if (!panel || !body || !done) return null;
				return {
					panelH: panel.getBoundingClientRect().height,
					viewH: window.innerHeight,
					bodyScrolls: body.scrollHeight > body.clientHeight + 1,
					doneBottom: done.getBoundingClientRect().bottom,
					sections: document.querySelectorAll(".rl-sec").length,
				};
			});
			check(`${route} rules open with real content`, !!geom && geom.sections >= 4,
				JSON.stringify(geom));
			if (!geom) continue;
			check(`${route} rules scroll INSIDE the panel`,
				geom.bodyScrolls && geom.panelH <= geom.viewH,
				`panel ${Math.round(geom.panelH)} view ${geom.viewH} scrolls ${geom.bodyScrolls}`);
			check(`${route} rules keep the close button on screen`,
				geom.doneBottom <= geom.viewH, `bottom ${Math.round(geom.doneBottom)}`);

			await page.keyboard.press("Escape");
			await page.waitForSelector(".rl-panel", { state: "detached", timeout: 5_000 })
				.catch(() => {});
			const stillOpen = await page.locator(".rl-panel").count().catch(() => 1);
			check(`${route} rules close on Escape`, stillOpen === 0, `count ${stillOpen}`);
		}

		// PHONES: EVERY CONTROL IS REACHABLE. This replaces a pair of checks that
		// asserted the row OVERFLOWS and stayed on one line — the sideways-scroller
		// behaviour, which fitted nothing and merely moved Rules 280px past the right
		// edge of a 390px screen where nothing on the page said it was there. The row
		// is an explicit two-row grid at this width now (see the stylesheet), so what
		// is worth asserting is the property the old pair was a proxy for: nothing is
		// clipped, nothing is stranded, and the page still does not scroll sideways.
		// Verified non-vacuous by restoring `flex-wrap:nowrap;overflow-x:auto` — the
		// outside check fails and names Rules.
		await page.setViewportSize({ width: 380, height: 760 });
		await page.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await page.waitForSelector(".lby-create-row", { timeout: 25_000 }).catch(() => {});
		const row = await page.evaluate(() => {
			const el = document.querySelector(".lby-create-row");
			if (!el) return null;
			const rb = el.getBoundingClientRect();
			const outside = [...el.children]
				.map((c) => [c.className, c.getBoundingClientRect()])
				.filter(([, b]) => b.right > rb.right + 1 || b.left < rb.left - 1
					|| b.right > window.innerWidth + 1 || b.left < -1)
				.map(([cls, b]) => `${cls} ${Math.round(b.left)}..${Math.round(b.right)}`);
			return {
				n: el.children.length, outside,
				clipped: el.scrollWidth > el.clientWidth + 1,
				pageWide: document.documentElement.scrollWidth > window.innerWidth + 1,
			};
		});
		// Dissonance on purpose: it is the game with the SIXTH control (Scorecard), so
		// it is the widest the row ever gets and the one that failed hardest before.
		check("every phone create-row control is inside the viewport",
			!!row && row.outside.length === 0 && row.n >= 5, JSON.stringify(row));
		check("...with nothing clipped off the row", !!row && !row.clipped, JSON.stringify(row));
		check("...and without making the PAGE scroll sideways", !!row && !row.pageWide,
			JSON.stringify(row));
		check("no page errors in the rules pass", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dontminion's expansion picker ─────────────────────────────────────────
	// Three contracts that regress SILENTLY (a one-word edit to a useState, a CSS
	// rule that stops the list scrolling) and that nothing else here would catch:
	// Base Set alone is the default, the LIST scrolls rather than the modal, and
	// Select all toggles both ways. The set count grows every expansion phase, so
	// the picker is the part of that modal most likely to be touched.
	async function dmExpansionPicker(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "picker-harness", name: "Picker", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		const opened = await page.waitForSelector(".dm-checks", { timeout: 15_000 })
			.then(() => true).catch(() => false);
		check("Dontminion's create modal opens", opened);

		if (opened) {
			const p = await page.evaluate(() => {
				const list = document.querySelector(".dm-checks");
				const panel = document.querySelector(".cm-panel");
				return {
					on: [...list.querySelectorAll(".dm-check-on")].map((b) => b.textContent.trim()),
					total: list.querySelectorAll(".dm-check").length,
					listScrolls: list.scrollHeight > list.clientHeight + 1,
					panelScrolls: panel.scrollHeight > panel.clientHeight + 1,
				};
			});
			check("...with Base Set the only expansion selected",
				p.on.length === 1 && /Base/.test(p.on[0]), JSON.stringify(p.on));
			// The list only NEEDS to scroll once it outgrows its cap; assert the
			// modal doesn't, which is the property the cap exists to preserve.
			check("...the expansion LIST scrolls, not the whole modal",
				!p.panelScrolls && (p.total < 4 || p.listScrolls),
				`list=${p.listScrolls} panel=${p.panelScrolls} of ${p.total}`);

			// The bot tier is the one create option that changes who you PLAY —
			// it must be pickable, and must default to the bot that plays a real
			// game (main.py coerces an unknown tier away silently, so a typo'd
			// id here would look fine and quietly seat the random bot).
			const bots = await page.evaluate(() => {
				const row = document.querySelector(".dm-cm-botstyle");
				if (!row) return null;
				return {
					label: row.querySelector(".cm-label")?.textContent.trim(),
					labels: [...row.querySelectorAll(".cm-seg-btn")].map((b) => b.textContent.trim()),
					sel: [...row.querySelectorAll(".cm-seg-btn.sel")].map((b) => b.textContent.trim()),
					// one line with the bot count, and its name must not wrap
					oneLine: row.getBoundingClientRect().top
						=== document.querySelector(".dm-cm-two > .dm-cm-col").getBoundingClientRect().top
						&& [...row.querySelectorAll(".cm-seg-btn")]
							.every((b) => b.getBoundingClientRect().height < 44),
				};
			});
			// Defaults to the STRONGEST tier (main.DEFAULT_DIFFICULTY = bmplus,
			// labelled "Money+"). Asserted on the label rather than the id
			// because the id never reaches the DOM; the full tier names ride
			// as button titles, since a longer label would be clipped by the
			// seg track's overflow:hidden — which is what the one-line check
			// below guards.
			check("...the bot style is pickable, defaulting to the strongest tier",
				!!bots && bots.labels.length >= 2 && bots.sel.length === 1
				&& /money\+/i.test(bots.sel[0]), JSON.stringify(bots));
			check("...sharing one line with the bot count, without wrapping",
				!!bots && bots.oneLine, JSON.stringify(bots));

			// The Require picker is built from /catalog, so an empty list means
			// the server field is missing or misnamed — exactly the drift the
			// wire-contract test can't see from the browser side.
			const req = await page.evaluate(() => {
				const list = document.querySelector(".dm-checks-req");
				if (!list) return null;
				return {
					labels: [...list.querySelectorAll(".dm-check")].map((b) => b.textContent.trim()),
					on: list.querySelectorAll(".dm-check-on").length,
					scrolls: list.scrollHeight > list.clientHeight + 1,
				};
			});
			check("...the Require picker offers all three bonuses, none preselected",
				!!req && req.labels.length === 3 && req.on === 0
				&& req.labels.some((l) => /\+2 Actions/.test(l))
				&& req.labels.some((l) => /\+1 Buy/.test(l))
				&& req.labels.some((l) => /\+2 Cards/.test(l)), JSON.stringify(req));
			// three fixed entries always fit — a scrollbar here means it wrongly
			// inherited the expansion list's cap
			check("...and the Require list needs no scrollbar", !!req && !req.scrolls,
				JSON.stringify(req));

			await page.click(".dm-checks-req .dm-check");
			const reqOn = await page.evaluate(() => ({
				on: document.querySelectorAll(".dm-checks-req .dm-check-on").length,
				hint: document.querySelector(".cm-hint")?.textContent || "",
			}));
			check("...checking one is reflected in the hint",
				reqOn.on === 1 && /always including a card that gives/.test(reqOn.hint),
				JSON.stringify(reqOn));
			await page.click(".dm-checks-req .dm-check");   // back to none for the create below

			await page.click(".dm-check-all");
			const all = await page.evaluate(() => ({
				on: document.querySelectorAll(".dm-checks .dm-check-on").length,
				total: document.querySelectorAll(".dm-checks .dm-check").length,
				disabled: document.querySelector(".cm-create").disabled,
			}));
			check("Select all turns every expansion on",
				all.total > 1 && all.on === all.total && !all.disabled, JSON.stringify(all));

			await page.click(".dm-check-all");
			const none = await page.evaluate(() => ({
				on: document.querySelectorAll(".dm-checks .dm-check-on").length,
				disabled: document.querySelector(".cm-create").disabled,
			}));
			// Empty is a REACHABLE state, so Create must refuse it — the server
			// rejects an empty expansion set and the error would be opaque.
			check("...and pressing it again clears them, disabling Create",
				none.on === 0 && none.disabled, JSON.stringify(none));
		}
		check("no page errors in the expansion picker", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dontminion's card face ────────────────────────────────────────────────
	// The first check here that actually PLAYS Dontminion — the route test above
	// mounts the lobby and never renders a card. Two geometry contracts, both of
	// which a one-line CSS edit can break silently:
	//   1. all four text insets are EQUAL. They were 12px (the shared .card
	//      frame's padding stacked on each row's own), and the title's right
	//      inset was smaller still because FitText measured the PADDING box.
	//   2. on the smallest face (56px, the in-play rows) the cost coin sits
	//      BESIDE the type labels, not wrapped under them.
	async function dmCardFace(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "cardface-harness", name: "Face", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`${`http://localhost:${PORT}`}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-panel", { timeout: 15_000 }).catch(() => {});
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a Dontminion game deals a board", dealt);

		if (dealt) {
			const g = await page.evaluate(() => {
				const c = document.querySelector(".dm-supply .dm-card");
				const cb = c.getBoundingClientRect();
				const span = c.querySelector(".dm-fitspan").getBoundingClientRect();
				const nameBox = c.querySelector(".dm-card-name");
				const ncs = getComputedStyle(nameBox);
				const types = c.querySelector(".dm-types").getBoundingClientRect();
				const cost = c.querySelector(".dm-cost").getBoundingClientRect();
				const r = (n) => +n.toFixed(1);
				return {
					titleLeft: r(span.left - cb.left),
					titleRight: r(cb.right - span.right),
					typesLeft: r(types.left - cb.left),
					costRight: r(cb.right - cost.right),
					costBottom: r(cb.bottom - cost.bottom),
					// the FitText bug: the name grew into its own right inset
					nameOverflow: r(span.width - (nameBox.clientWidth
						- parseFloat(ncs.paddingLeft) - parseFloat(ncs.paddingRight))),
				};
			});
			// The title is left-aligned and usually shorter than the card, so its
			// RIGHT gap is only meaningful as "at least the inset" — the bug made
			// it smaller than the left one.
			check("card insets are the same on every side",
				Math.abs(g.typesLeft - g.costRight) < 1 && Math.abs(g.typesLeft - g.costBottom) < 1
				&& Math.abs(g.typesLeft - g.titleLeft) < 1, JSON.stringify(g));
			// FitText only misbehaves on a name it has to SHRINK, and no supply name
			// shrinks at any sane width — asserting at desktop size PASSED with the
			// bug still in (verified, which is why this block exists).
			//
			// So narrow the viewport until the always-present Province pile is forced
			// to shrink. Narrow it TOO far and the required size drops under FitText's
			// own 8px floor, where the text overflows no matter how it was measured —
			// a real limit, but not this bug, and asserting there fails on correct
			// code. The rig therefore sweeps down and stops at the first width that
			// shrinks the name while staying ABOVE the floor. Geometry is
			// deterministic, so this picks the same width every run; if no width
			// qualifies the check FAILS rather than passing unexercised.
			let rig = null;
			for (const w of [320, 300, 280, 260, 250, 245, 240, 235]) {
				await page.setViewportSize({ width: w, height: 900 });
				// FitText refits from a ResizeObserver, so the reading right after a
				// resize can be the PREVIOUS width's. Poll until two consecutive
				// samples agree instead of trusting one fixed sleep — an
				// intermittently-failing shared gate is worse than no gate. The
				// shared `settleFits` is that same rule at a 60ms rather than a
				// 150ms step, which this sweep pays once per candidate width.
				await settleFits(page);
				const r = await page.evaluate(() => {
					const card = [...document.querySelectorAll(".dm-supply .dm-card")]
						.find((c) => c.querySelector(".dm-fitspan")?.textContent === "Province");
					if (!card) return null;
					const box = card.querySelector(".dm-card-name");
					const span = card.querySelector(".dm-fitspan");
					const cs = getComputedStyle(box);
					const content = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
					const cb = card.getBoundingClientRect(), sb = span.getBoundingClientRect();
					return {
						shrank: !!box.style.fontSize,
						fontPx: +parseFloat(cs.fontSize).toFixed(2),
						overflow: +(sb.width - content).toFixed(1),
						gapLeft: +(sb.left - cb.left).toFixed(1),
						gapRight: +(cb.right - sb.right).toFixed(1),
					};
				});
				if (r?.shrank && r.fontPx > 8.05) { rig = { w, ...r }; break; }
			}
			check("...and a title it must shrink still respects its right inset",
				!!rig && rig.overflow <= 0.5 && Math.abs(rig.gapLeft - rig.gapRight) < 1.5,
				JSON.stringify(rig));
			await page.setViewportSize({ width: 1280, height: 900 });
			await settleFits(page);

			// Longest type label on the SMALLEST face: clone a real card into the
			// 56px in-play context rather than trusting a computed estimate.
			const fit = await page.evaluate(() => {
				const host = document.querySelector(".dm-opp-inplay");
				const clone = document.querySelector(".dm-supply .dm-card").cloneNode(true);
				// The in-play rows animate cards in (dm-enter scales them up), and a
				// freshly appended clone is measured MID-ANIMATION: rects come back
				// ~6% small. A uniform scale doesn't change whether the foot wrapped,
				// so the verdict held — but the reported widths were fiction. Kill the
				// animation and assert we measured settled layout, so a future
				// geometry surprise fails loudly instead of printing numbers that
				// don't reconcile.
				clone.style.animation = "none";
				const t = clone.querySelectorAll(".dm-type");
				[...t].slice(1).forEach((x) => x.remove());
				t[0].textContent = "Duration";          // the widest label we ship
				host.appendChild(clone);
				const foot = clone.querySelector(".dm-card-foot");
				const costEl = clone.querySelector(".dm-cost");
				const fcs = getComputedStyle(foot);
				const avail = foot.clientWidth - parseFloat(fcs.paddingLeft) - parseFloat(fcs.paddingRight)
					- costEl.getBoundingClientRect().width - parseFloat(fcs.columnGap || "0");
				const label = t[0].getBoundingClientRect().width;
				const types = clone.querySelector(".dm-types").getBoundingClientRect();
				const cost = costEl.getBoundingClientRect();
				const out = {
					faceW: +clone.getBoundingClientRect().width.toFixed(1),
					cssW: +parseFloat(getComputedStyle(clone).width).toFixed(1),
					avail: +avail.toFixed(1), label: +label.toFixed(1),
					slack: +(avail - label).toFixed(1),
					wrapped: cost.top >= types.bottom - 0.5,
				};
				clone.remove();
				return out;
			});
			check("the cost coin shares a row with the types on the 56px face",
				!fit.wrapped && fit.slack > 0 && Math.abs(fit.faceW - fit.cssW) < 0.5,
				JSON.stringify(fit));

			// The count pill straddles the card's bottom edge, so tightening the
			// foot's inset walked the type label straight under it — 7px of overlap
			// on every supply pile, which is how this check earned its place.
			const pills = await page.evaluate(() => {
				const bad = [];
				for (const slot of document.querySelectorAll(".dm-pile-slot")) {
					// Fan slots (your hand, an opponent's hand) hold a ROW of cards under
					// one centred pill, so "the slot's card" is meaningless there — the
					// pill is not labelling the card it happens to sit over. Only
					// single-card slots have the pill-labels-this-card relationship.
					if (slot.matches(".dm-myhand, .dm-opp-hand")) continue;
					const card = slot.querySelector(".dm-card");
					const pill = slot.querySelector(".dm-pile-count");
					if (!card || !pill) continue;
					const pb = pill.getBoundingClientRect();
					for (const [what, el] of [["types", card.querySelector(".dm-types")],
						["cost", card.querySelector(".dm-cost")]]) {
						if (!el || !el.textContent.trim()) continue;
						const b = el.getBoundingClientRect();
						if (pb.top < b.bottom && pb.bottom > b.top && pb.left < b.right && pb.right > b.left) {
							bad.push({ card: card.querySelector(".dm-fitspan")?.textContent, what,
								by: +(b.bottom - pb.top).toFixed(1) });
						}
					}
				}
				return bad.slice(0, 5);
			});
			check("the pile count never covers a card's type or cost",
				pills.length === 0, JSON.stringify(pills));

			// ── the landscape row: EMPTY here, real on an Adventures board ────────
			// This board is Base Set only, so it has no Events and the row must
			// render NOTHING — not an empty flex container with its own padding and
			// border, which would push the whole Supply down on every game that
			// isn't using landscapes. Token badges are the same story.
			const dormant = await page.evaluate(() => ({
				rows: document.querySelectorAll(".dm-lscape-row").length,
				faces: document.querySelectorAll(".dm-lscape").length,
				tokens: document.querySelectorAll(".dm-tokens").length,
				supplyTop: document.querySelector(".dm-supply")
					?.firstElementChild?.className ?? null,
			}));
			check("a board with no landscapes renders no landscape row at all",
				dormant.rows === 0 && dormant.faces === 0 && dormant.tokens === 0
				&& /dm-basics/.test(dormant.supplyTop || ""),
				JSON.stringify(dormant));

			// ── Supply faces render fitted rules text (the `body` opt-in) ─────────
			// Rules text used to be gated off small faces; supply piles now pass
			// <DmCardFace body> and FitBodyText fills within a 10-16px band, cutting
			// a too-long rule with "…" (the full card is a press/right-click away).
			// The deal is RANDOM, so rather than demand a particular wordy card (a
			// ~2% deal has none — a flaky gate), assert the INVARIANTS: text renders,
			// the band holds, nothing overflows, short cards hit the ceiling, and a
			// face is truncated IFF its full rule can't fit at the floor. The
			// biconditional exercises the truncation logic on every deal without
			// depending on which cards were dealt.
			await page.setViewportSize({ width: 1000, height: 900 });   // squeezes kingdom piles to the 88px floor
			await settleFits(page);                                     // let FitBodyText's ResizeObserver refit
			const bodyTxt = await page.evaluate(() => {
				const rows = [...document.querySelectorAll(".dm-supply .dm-card")].map((c) => {
					const el = c.querySelector(".dm-card-body");
					const name = c.querySelector(".dm-fitspan")?.textContent;
					if (!el) return { name, hasBody: false };
					const px = +parseFloat(getComputedStyle(el).fontSize).toFixed(2);
					const shown = el.textContent;
					// full rule rides in the face's title as "Name (cost) — <text>"
					const full = (c.getAttribute("title") || "").split(" — ").slice(1).join(" — ");
					// measure the FULL text at the floor, then restore the fitter's output
					const prevF = el.style.fontSize, prevT = el.textContent;
					el.style.fontSize = "10px"; el.textContent = full;
					const fullOverflows = el.scrollHeight > el.clientHeight + 0.5;
					el.textContent = prevT; el.style.fontSize = prevF;
					return { name, hasBody: true, px, shown, truncated: /…$/.test(shown),
						fullOverflows, overflow: el.scrollHeight - el.clientHeight };
				});
				const b = rows.filter((r) => r.hasBody);
				const basic = /^(Copper|Silver|Gold|Estate|Duchy|Province|Curse)$/;
				return {
					total: rows.length, withText: b.filter((r) => r.shown && r.shown.length).length,
					outOfBand: b.filter((r) => r.px < 9.9 || r.px > 16.1).map((r) => [r.name, r.px]),
					overflowing: b.filter((r) => r.overflow > 1).map((r) => r.name),
					short: b.filter((r) => basic.test(r.name)),
					mismatch: b.filter((r) => r.truncated !== r.fullOverflows).map((r) => [r.name, r.truncated, r.fullOverflows]),
					floorOff: b.filter((r) => r.truncated && Math.abs(r.px - 10) > 0.6).map((r) => [r.name, r.px]),
					sample: b.slice(0, 3).map((r) => [r.name, r.px, r.truncated]),
				};
			});
			check("every supply pile renders fitted body text",
				bodyTxt.total > 0 && bodyTxt.withText === bodyTxt.total, JSON.stringify(bodyTxt.sample));
			// short cards must NOT balloon (ceiling) and nothing may overflow (floor)
			check("...within the 10-16px band, short cards capped, none overflowing",
				bodyTxt.outOfBand.length === 0 && bodyTxt.overflowing.length === 0
				&& bodyTxt.short.length > 0 && bodyTxt.short.every((r) => r.px >= 15.5),
				JSON.stringify({ band: bodyTxt.outOfBand, over: bodyTxt.overflowing,
					short: bodyTxt.short.map((r) => [r.name, r.px]) }));
			// truncation is exactly "the full rule can't fit at the floor", and every
			// cut face sits at the 10px floor
			check("...truncated with an ellipsis iff the full rule can't fit at the floor",
				bodyTxt.mismatch.length === 0 && bodyTxt.floorOff.length === 0,
				JSON.stringify({ mismatch: bodyTxt.mismatch, floorOff: bodyTxt.floorOff }));

			// A BODY BOX CAN LOSE HEIGHT WITHOUT LOSING WIDTH, and FitBodyText used to skip
			// the refit when it did — its ResizeObserver guard was width-only while its fit
			// criterion (scrollHeight <= clientHeight) is a HEIGHT test. The box is `flex:1`
			// between the name and the foot, so its height is the card minus the NAME, and
			// FitText sizes that name independently.
			//
			// NONE OF THE CHECKS ABOVE CAN SEE THAT, and neither can `settleFits`: a fitter
			// that wrongly declines to refit is indistinguishable from one that has
			// converged, so the font size is stable and the text overflows anyway. It
			// reached CI as an intermittently red gate (run #779, on a commit touching only
			// Orbit files) rather than as a bug report. So drive the one input a viewport
			// resize never varies on its own: change the NAMES' size, leave every width
			// alone, and assert the bodies actually re-fit.
			// Verified non-vacuous against the unfixed component: 17 boxes changed height,
			// 0 changed width, 0 re-fitted, 8 piles left overflowing (Cellar, Harbinger,
			// Bandit and Witch among them).
			const heightOnly = await page.evaluate(async () => {
				const settled = () => new Promise((r) =>
					requestAnimationFrame(() => requestAnimationFrame(r)));
				const read = () => [...document.querySelectorAll(".dm-supply .dm-card")]
					.map((c) => {
						const el = c.querySelector(".dm-card-body");
						return el && {
							px: +parseFloat(getComputedStyle(el).fontSize).toFixed(2),
							txt: el.textContent, h: el.clientHeight,
							w: +el.getBoundingClientRect().width.toFixed(2),
							over: +(el.scrollHeight - el.clientHeight).toFixed(1),
							name: c.querySelector(".dm-fitspan")?.textContent,
						};
					}).filter(Boolean);
				const before = read();
				const names = [...document.querySelectorAll(".dm-supply .dm-card .dm-card-name")];
				const restore = names.map((n) => n.style.fontSize);
				// FitText writes the size onto .dm-card-name, so this is the same input it
				// produces — just larger than any width would ask for, which makes the
				// squeeze on the body below it unambiguous.
				for (const n of names) {
					n.style.fontSize = (parseFloat(getComputedStyle(n).fontSize) * 2.2) + "px";
				}
				await settled(); await new Promise((r) => setTimeout(r, 400)); await settled();
				const after = read();
				const out = {
					cards: after.length,
					widthMoved: after.filter((a, i) => Math.abs(a.w - before[i].w) > 0.5).length,
					heightMoved: after.filter((a, i) => a.h !== before[i].h).length,
					refitted: after.filter((a, i) => a.px !== before[i].px || a.txt !== before[i].txt).length,
					overflowing: after.filter((a) => a.over > 1).map((a) => a.name),
				};
				names.forEach((n, i) => { n.style.fontSize = restore[i]; });
				await settled(); await new Promise((r) => setTimeout(r, 400));
				return out;
			});
			check("a body box that loses HEIGHT but keeps its width still re-fits",
				heightOnly.heightMoved > 0 && heightOnly.widthMoved === 0
				&& heightOnly.refitted > 0 && heightOnly.overflowing.length === 0,
				JSON.stringify(heightOnly));

			await page.setViewportSize({ width: 1280, height: 900 });
			await settleFits(page);

			// The log reads CHRONOLOGICALLY — oldest at the top, newest at the
			// bottom — and follows the newest line. Both the brightened line and
			// the slide-in animation key off :last-child, so a flip back to
			// newest-first would highlight and animate the wrong end silently.
			const readLog = () => page.evaluate(() => {
				const box = document.querySelector(".dm-log");
				if (!box) return null;
				const lines = [...box.querySelectorAll(".dm-log-line")].map((l) => l.textContent.trim());
				return {
					lines,
					atBottom: box.scrollHeight - box.scrollTop - box.clientHeight < 80,
					// the turn-1 marker is the OLDEST turn event, so chronological
					// order puts it near the top, never at the very end
					firstTurnIdx: [...box.querySelectorAll(".dm-log-line")]
						.findIndex((l) => l.classList.contains("dm-log-turn")),
				};
			});
			const logBefore = await readLog();

			// Right-click / press-and-hold opens the card's detail modal without
			// firing the card's PRIMARY action. Tested on an affordable Copper in
			// the buy phase, because that is the case where a plain click really
			// does buy — the pile count is the witness that it didn't.
			await page.locator(".dm-turnbtns .btn", { hasText: /to buy phase/i })
				.click({ timeout: 10_000 }).catch(() => {});
			// The buy phase has arrived once the button that got us here is gone —
			// which is the state the checks below actually need, and it lands well
			// inside the 800ms this used to sleep unconditionally.
			await until(page, () => ![...document.querySelectorAll(".dm-turnbtns .btn")]
				.some((b) => /to buy phase/i.test(b.textContent)), 800);

			const copperCount = () => page.evaluate(() => {
				const el = [...document.querySelectorAll(".dm-supply .dm-pile-slot")]
					.find((x) => x.querySelector(".dm-fitspan")?.textContent === "Copper");
				return el?.querySelector(".dm-pile-count")?.textContent ?? null;
			});
			const infoOpen = () => page.locator(".dm-cardinfo").count().then((n) => n > 0);
			const closeInfo = async () => {
				if (await infoOpen()) {
					await page.locator(".dm-backdrop").first().click({ position: { x: 5, y: 5 } });
					await sleep(250);
				}
			};
			const copper = page.locator(".dm-supply .dm-card").filter({ hasText: "Copper" }).first();
			const c0 = await copperCount();
			await copper.click({ button: "right" });
			await sleep(350);
			const rc = { opened: await infoOpen(), title: await page.locator(".dm-cardinfo-detail h2")
				.textContent().catch(() => null) };
			await closeInfo();
			const c1 = await copperCount();
			check("right-click opens the card detail without buying",
				rc.opened && rc.title === "Copper" && c0 === c1 && c0 !== null,
				JSON.stringify({ ...rc, c0, c1 }));

			// Synthetic touch hold — Playwright has no press-and-hold, and the iOS
			// path is a timer rather than a `contextmenu`, so dispatch the real
			// pointer sequence with pointerType "touch".
			const bb = await copper.boundingBox();
			const hold = (ms) => page.evaluate(async ([x, y, dur]) => {
				const el = document.elementFromPoint(x, y).closest(".dm-card");
				const mk = (type) => new PointerEvent(type, { bubbles: true, cancelable: true,
					composed: true, pointerId: 1, pointerType: "touch", isPrimary: true,
					clientX: x, clientY: y });
				el.dispatchEvent(mk("pointerdown"));
				await new Promise((r) => setTimeout(r, dur));
				el.dispatchEvent(mk("pointerup"));
				el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true,
					clientX: x, clientY: y }));
			}, [bb.x + bb.width / 2, bb.y + bb.height / 2, ms]);

			await hold(650);
			await sleep(350);
			const heldOpen = await infoOpen();
			await closeInfo();
			const c2 = await copperCount();
			check("press-and-hold opens the card detail without buying",
				heldOpen && c1 === c2, JSON.stringify({ heldOpen, c1, c2 }));

			// ...and the gesture must not eat an ordinary tap.
			await hold(80);
			// A tap BUYS, so the witness is the pile count moving. Waiting for that
			// is both faster and stricter than sleeping 800ms and hoping.
			await until(page, (was) => {
				const el = [...document.querySelectorAll(".dm-supply .dm-pile-slot")]
					.find((x) => x.querySelector(".dm-fitspan")?.textContent === "Copper");
				return (el?.querySelector(".dm-pile-count")?.textContent ?? null) !== was;
			}, 800, c2);
			const c3 = await copperCount();
			const tapOpened = await infoOpen();
			await closeInfo();
			check("a short tap still buys, and opens nothing",
				c2 !== c3 && !tapOpened, JSON.stringify({ c2, c3, tapOpened }));

			// That buy ALWAYS logs (unlike the phase click, which logs nothing the
			// client renders — anchoring here instead of there is what makes this
			// deterministic rather than deal-dependent). Chronological order means
			// the log only ever grows at the END, so everything on screen before
			// the buy must still be there, in order, as a PREFIX of the new list.
			// Asserting a specific "newest line" can't work — the bot moves too.
			const logAfter = await readLog();
			const grewAtEnd = !!logBefore && !!logAfter
				&& logAfter.lines.length > logBefore.lines.length
				&& logBefore.lines.every((t, i) => logAfter.lines[i] === t);
			check("the log runs oldest-to-newest — new lines are APPENDED at the bottom",
				grewAtEnd, JSON.stringify({
					before: logBefore?.lines.slice(-3), after: logAfter?.lines.slice(-5),
				}));

			// ...and it FOLLOWS that newest line, including after a scroll the
			// READER did not cause. The list renders only the newest 200 lines, so
			// past 200 entries every turn evicts lines off the top and Chrome's
			// scroll ANCHORING pulls scrollTop back on its own to hold the visible
			// text still. Reading that as "they scrolled up to re-read" latched the
			// log in place for the rest of the game — and only on a PC, because iOS
			// Safari implements no scroll anchoring. Simulated directly (a scroll
			// with no preceding gesture) rather than by playing 200 turns, and the
			// log is forced to overflow so the check can't be vacuous on a short one.
			// force a scroller regardless of how much this deal has logged, and start
			// it pinned at the bottom so the move away from it is a REAL change the
			// browser reports (React sets no style prop on this element, so the
			// inline max-height survives every re-render)
			await page.evaluate(() => {
				const el = document.querySelector(".dm-log");
				el.style.maxHeight = "60px";
				el.scrollTop = el.scrollHeight;
			});
			await sleep(200);
			const logPre = await page.evaluate(() => {
				const el = document.querySelector(".dm-log");
				if (!el) return null;
				el.scrollTop = 0;   // ...as scroll anchoring does: no gesture, real event
				return { n: el.querySelectorAll(".dm-log-line").length,
					canScroll: el.scrollHeight > el.clientHeight + 4 };
			});
			await sleep(300);       // let that scroll event dispatch
			// ending the turn is the reliable log generator here — the buy phase is
			// already spent by the tap test above, and the bot's reply logs plenty
			await page.locator(".dm-turnbtns .btn", { hasText: /end turn/i })
				.click({ timeout: 10_000 }).catch(() => {});
			// The check below needs the log to have GROWN (follow.n > logPre.n) and
			// to have settled at the bottom, so wait for exactly that instead of
			// sleeping long enough for the bot's whole reply. The cap is the old
			// 2500ms, so a slow bot still gets the window it had.
			await until(page, (n) => document.querySelectorAll(".dm-log .dm-log-line").length > n,
				2500, logPre?.n ?? 0);
			// ...then let the follow-scroll land before the gap is measured.
			await settle(page, () => {
				const el = document.querySelector(".dm-log");
				return el ? [el.querySelectorAll(".dm-log-line").length, Math.round(el.scrollTop)] : null;
			});
			const follow = await page.evaluate(() => {
				const el = document.querySelector(".dm-log");
				const r = { gap: +(el.scrollHeight - el.scrollTop - el.clientHeight).toFixed(1),
					n: el.querySelectorAll(".dm-log-line").length };
				el.style.maxHeight = "";
				return r;
			});
			check("the log still follows the newest line after a scroll the reader did not cause",
				!!logPre && logPre.canScroll && follow.n > logPre.n && follow.gap < 48,
				JSON.stringify({ canScroll: logPre?.canScroll, lines: [logPre?.n, follow.n],
					gapFromBottom: follow.gap }));

			// Phone width stacks your piles / hand / buttons into one column, and the
			// count pills hang BELOW their slot — so "hand N" landed on top of the
			// buttons (measured 6px into them). Nothing in the column may overlap.
			await page.setViewportSize({ width: 390, height: 844 });
			await settleFits(page);
			const mob = await page.evaluate(() => {
				const pill = document.querySelector(".dm-myhand .dm-pile-count");
				const btns = document.querySelector(".dm-turnbtns");
				if (!pill || !btns) return { missing: true };
				const p = pill.getBoundingClientRect(), b = btns.getBoundingClientRect();
				// ...and lifting it must not push it onto a card's own text
				let onCard = null;
				for (const el of document.querySelectorAll(".dm-me .dm-types, .dm-me .dm-cost")) {
					if (!el.textContent.trim()) continue;
					const r = el.getBoundingClientRect();
					if (p.top < r.bottom && p.bottom > r.top && p.left < r.right && p.right > r.left) {
						onCard = el.className; break;
					}
				}
				return { overlapWithButtons: +(p.bottom - b.top).toFixed(1), onCard };
			});
			check("on a phone the hand count clears the buttons and the cards",
				!mob.missing && mob.overlapWithButtons < 0 && !mob.onCard, JSON.stringify(mob));
			await page.setViewportSize({ width: 1280, height: 900 });
			await settleFits(page);
		}
		check("no page errors while rendering the board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── the landscape row on a REAL Adventures board (ph. 7) ──────────────────
	// The empty-state pin above is the layout-shift guard; it says nothing about
	// whether the row WORKS, and a component that throws on its first real
	// landscape would satisfy it perfectly. Adventures ships 20 Events, so the
	// row is now reachable by any player and owes a real render.
	//
	// ─── Lobby History pages 10 at a time, and stops at 50 ───────────────────
	// `useProgressiveList` (shared/lobby.jsx) is wired identically into all four
	// lobbies, so covering it once covers the logic; each game's wiring is one
	// line. Driven against a STUBBED /games/history rather than a seeded DB: the
	// point is the reveal, and 55 synthetic rows make both the page size and the
	// HISTORY_MAX cap exact instead of dependent on what this box has played.
	// ── The paper scorecard ────────────────────────────────────────────────
	// Dissonance's lobby keeps a manual score-keeper for a game played with real
	// cards, and it is the one screen that COMPUTES a payout rather than quoting
	// one the server settled. Nothing at runtime would notice it drifting from
	// the engine, so this drives a real round through it and checks the two
	// things a wrong price list would break: that the arithmetic it PRINTS
	// evaluates to the score it BANKS (no hardcoded prices in the harness --
	// the line is evaluated, so the assertion survives any re-pricing), and that
	// the Null consolation flips who scores.
	async function dissonanceScorecard(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "card-harness", name: "Cardy", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await page.waitForSelector(".lby-create-row", { timeout: 25_000 }).catch(() => {});
		// The slot carries its OWN class: `.lby-rules` is how the rules block
		// counts Rules buttons, and a second button wearing it would read there
		// as a duplicate rather than as the scorecard.
		const rules = await page.locator(".lby-rules").count().catch(() => 0);
		const extra = await page.locator(".lby-extra").count().catch(() => 0);
		check("the dissonance lobby offers Rules AND a Scorecard", rules === 1 && extra === 1,
			`rules ${rules} extra ${extra}`);
		if (!extra) { await ctx.close(); return; }

		await page.locator(".lby-extra").click({ timeout: 10_000 }).catch(() => {});
		await page.waitForSelector(".dsc-entry", { timeout: 10_000 }).catch(() => {});
		check("the scorecard opens", await page.locator(".dsc-entry").count() === 1);

		const names = page.locator(".dsc-player input");
		await names.nth(0).fill("Alice");
		await names.nth(1).fill("Bob");
		const field = (label) => page.locator(".dsc-field").filter({ hasText: label });
		const bump = async (label, n, which) => {
			for (let i = 0; i < n; i++) {
				await field(label).locator(".dsc-step button").nth(which).click({ timeout: 5_000 });
			}
		};
		// A made contract, Kontra'd, with a one-rung leap and two overtricks --
		// which is every term the price list has in one round.
		await page.locator(".dsc-field .dis-bidgrid button", { hasText: /^4$/ }).first().click();
		await page.locator(".dsc-field .dis-denoms button").nth(3).click();
		await bump("Final jump", 1, 1);
		await page.getByRole("button", { name: /Not doubled/ }).click();
		await bump("Declarer's points", 6, 1);

		const shown = (await page.locator(".dsc-preview").innerText()).replace(/\s+/g, " ");
		// THE PRINTED LINE, EVALUATED. `×` to `*` and the unicode minus to ASCII
		// is the whole translation -- if the panel ever prints a term it did not
		// charge, or charges one it did not print, these stop agreeing.
		const m = shown.match(/scores (\d+)/);
		const maths = (await page.locator(".dsc-pre-maths").innerText())
			.replace(/×/g, "*").replace(/−/g, "-");
		let evaluated = null;
		try { evaluated = Function(`"use strict"; return (${maths});`)(); } catch { /* below */ }
		check("the scorecard's arithmetic reaches the score it shows",
			!!m && evaluated === Number(m[1]), `${shown} => ${maths} = ${evaluated}`);

		await page.getByRole("button", { name: "Add round" }).click();
		const banked = await page.locator(".dsc-table .dsc-row").nth(1).innerText().catch(() => "");
		check("the round lands on the card with that score",
			!!m && banked.replace(/\s+/g, " ").includes(m[1]), `${banked} vs ${m?.[1]}`);

		// NULL. A declarer on a non-positive total may have won no scoring trick
		// at all, which the points alone cannot settle -- so the toggle appears
		// there and nowhere else, and it moves the score to the other side.
		await page.locator(".dsc-field .dis-bidgrid button", { hasText: /^5$/ }).first().click();
		await page.locator(".dsc-field .dis-denoms button").nth(0).click();
		await bump("Declarer's points", 3, 0);
		const set = await page.locator(".dsc-pre-line").innerText();
		const nullBtn = page.getByRole("button", { name: /Won no \+\d+ trick/ });
		check("a non-positive total offers the Null consolation",
			await nullBtn.count() === 1);
		await nullBtn.click({ timeout: 5_000 }).catch(() => {});
		const nul = await page.locator(".dsc-pre-line").innerText();
		// Alice is still the declarer here (adding a round resets the contract,
		// not the seat), so being set pays BOB and the consolation pays ALICE.
		check("Null pays the DECLARER instead of setting them",
			set.includes("Bob") && nul.includes("Alice"), `${set} -> ${nul}`);

		// It is a card for a game that outlasts a tab.
		await page.getByRole("button", { name: "Add round" }).click();
		await page.reload({ waitUntil: "networkidle" });
		await page.waitForSelector(".lby-extra", { timeout: 25_000 }).catch(() => {});
		await page.locator(".lby-extra").click({ timeout: 10_000 }).catch(() => {});
		await page.waitForSelector(".dsc-table", { timeout: 10_000 }).catch(() => {});
		const rows = await page.locator(".dsc-table .dsc-row").count().catch(() => 0);
		check("the card survives a reload", rows === 3, `rows ${rows} (1 head + 2)`);

		// ── AND IT IS REACHABLE WITH THE BACKEND GONE ──────────────────────
		// The card is for a table with real cards, where there may be no signal
		// at all — so the claim under test is not "the modal renders" but "you
		// can GET to it with nothing answering". The Dissonance lobby cannot be
		// reached then (it sits behind the boot ping); the offline hub can, and
		// that is why the card is duplicated there. Blocking the API origin is
		// the honest simulation: the 5173 bundle still serves, nothing else does.
		await page.route(`http://localhost:${API_PORT}/**`, (r) => r.abort());
		await page.goto(`http://localhost:${PORT}/offline`, { waitUntil: "domcontentloaded" });
		await page.waitForSelector(".offline-hub", { timeout: 25_000 }).catch(() => {});
		check("the offline hub opens with the backend unreachable",
			await page.locator(".offline-hub").count() === 1);
		await page.getByRole("button", { name: /^Open$/ }).first()
			.click({ timeout: 10_000 }).catch(() => {});
		await page.waitForSelector(".dsc-entry", { timeout: 10_000 }).catch(() => {});
		check("...and the paper scorecard opens there too",
			await page.locator(".dsc-entry").count() === 1);
		// IT ALSO HAS TO BE DRESSED. The card borrows the board's bid keys, and
		// the board's stylesheet is not loaded here — that is the entire reason
		// bidpad.css and scorecard.css exist as their own files. A DOM-only check
		// passes just as happily over an unstyled card, so measure the two rules
		// that can only come from those sheets: the pad's fifth-width key, and
		// the card's own flex row.
		const dressed = await page.evaluate(() => {
			const key = document.querySelector(".dsc-pads .dis-bidgrid button");
			const row = document.querySelector(".dsc-players");
			const pad = document.querySelector(".dsc-pads .dis-bidgrid");
			if (!key || !row || !pad) return { missing: true };
			return {
				keyW: key.getBoundingClientRect().width,
				padW: pad.getBoundingClientRect().width,
				display: getComputedStyle(row).display,
				radius: getComputedStyle(key).borderTopLeftRadius,
			};
		});
		check("...wearing the board's own bid keys, five to a row",
			!dressed.missing && dressed.display === "flex" && dressed.radius === "9px"
			&& dressed.keyW > 0 && dressed.keyW < dressed.padW / 4,
			JSON.stringify(dressed));

		check("no page errors on the scorecard", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	async function lobbyHistory(log) {
		const ctx = await browser.newContext();
		// a session_token so the lobby actually fetches history (a guest is short-
		// circuited to an empty list), and a SHORT viewport so the initial 10 rows
		// push the sentinel below the fold — otherwise a tall window can see the
		// end of the list immediately and legitimately reveals the next page at
		// mount, which would make "shows 10" flaky rather than wrong.
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "hist-harness", name: "Histy", session_token: "stub" })));
		const page = await ctx.newPage();
		await page.setViewportSize({ width: 1280, height: 500 });
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		// The shell validates the stored session on load and a definitively-dead
		// token clears the login — but a NETWORK error never does (deliberate), so
		// aborting is how the seeded user survives without guessing the payload.
		await page.route("**/auth/session*", (r) => r.abort());
		const TOTAL = 55;     // > HISTORY_MAX, so the cap is exercised too
		await page.route("**/games/history*", (r) => r.fulfill({
			status: 200, contentType: "application/json",
			body: JSON.stringify({
				ok: true,
				games: Array.from({ length: TOTAL }, (_, i) => ({
					id: `G${String(i).padStart(3, "0")}`,
					players: ["Histy", "Bot 1"], opponents: ["Bot 1"],
					your_vp: 30, scores: { Histy: 30, "Bot 1": 10 },
					standings: [{ name: "Histy", vp: 30, you: true, won: true },
						{ name: "Bot 1", vp: 10, you: false, won: false }],
					you_won: true, winners: ["Histy"], updated_at: 1750000000 - i * 60,
					// EVERY OTHER ROW IS A HUMAN GAME, with no tier at all. The
					// bot chip is only correct if it renders for one and not the
					// other: a version that printed the game's DEFAULT difficulty
					// (which every save blob carries, bot or not) labels every
					// vs-friend row too, and reads exactly as right.
					...(i % 2 ? {} : { ai_difficulty: "bmplus" }),
				})),
			}),
		}));

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		const rows = () => page.locator(".lby-col-history .lby-card").count();
		await page.waitForFunction(
			() => document.querySelectorAll(".lby-col-history .lby-card").length > 0,
			null, { timeout: 20_000 }).catch(() => {});
		const first = await rows();
		check("History shows the first page only, not every finished game",
			first === 10, JSON.stringify({ first, of: TOTAL }));

		// WHICH BOT THE ROW WAS PLAYED AGAINST, end to end: the wire id the
		// server sends -> `LobbyBotTier` -> this game's own words for it.
		// Dontminion is the one whose tiers are NAMES rather than difficulty
		// rungs, so it is also the case that proves the label comes from the
		// game's map and not from title-casing the id ("Bmplus").
		const tiers = await page.evaluate(() => {
			const rows = [...document.querySelectorAll(".lby-col-history .lby-card")];
			return {
				rows: rows.length,
				chips: rows.filter((el) => el.querySelector(".lby-bot-tier")).length,
				words: [...new Set(rows.map((el) =>
					el.querySelector(".lby-bot-tier")?.textContent.replace(/\s+/g, " ").trim())
					.filter(Boolean))],
			};
		});
		check("a History row names the bot it was played against, and a human game names none",
			tiers.rows === 10 && tiers.chips === 5
			&& JSON.stringify(tiers.words) === JSON.stringify(["· Money+ AI"]),
			JSON.stringify(tiers));

		// scrolling the end of the list into view reveals the next page
		await page.locator(".lby-col-history .lby-more").scrollIntoViewIfNeeded()
			.catch(() => {});
		await sleep(500);
		const second = await rows();
		check("...and reaching the end of it reveals another page",
			second > first && second % 10 === 0,
			JSON.stringify({ first, second }));

		// keep going until it stops growing — it must stop at HISTORY_MAX, never
		// at the 55 the server sent
		let last = second;
		for (let i = 0; i < 12; i++) {
			const sentinel = page.locator(".lby-col-history .lby-more");
			if (await sentinel.count() === 0) break;
			await sentinel.scrollIntoViewIfNeeded().catch(() => {});
			await sleep(350);
			const n = await rows();
			if (n === last) break;
			last = n;
		}
		check("...and stops at HISTORY_MAX rather than at everything the server sent",
			last === 50 && TOTAL > 50, JSON.stringify({ last, sent: TOTAL }));
		check("no page errors paging through History", errors.length === 0,
			errors[0] || "");
		await ctx.close();
	}

	// An Adventures-only board deals at least one Event on 99.65% of seeds
	// (measured over 20k), so this asserts the BICONDITIONAL rather than
	// demanding one: a face implies a well-formed row, and no face implies no
	// row. Never deal-dependent, and it exercises the real render path on all
	// but ~1 run in 300 — the same shape as the body-text truncation check.
	async function dmAdventures(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "adv-harness", name: "Adv", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		// Adventures ON, Base Set OFF — an Adventures-only pool, so the Event
		// deal is over the set that actually has Events.
		for (const label of ["Adventures", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		check("the Adventures expansion is selectable",
			picked.length === 1 && /Adventures/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("an Adventures game deals a board", dealt);

		if (dealt) {
			const ls = await page.evaluate(() => {
				const row = document.querySelector(".dm-lscape-row");
				const faces = [...document.querySelectorAll(".dm-lscape")];
				const supply = document.querySelector(".dm-supply");
				return {
					rows: document.querySelectorAll(".dm-lscape-row").length,
					firstChildIsRow: !!row && supply.firstElementChild === row,
					insideBoard: !!row
						&& row.getBoundingClientRect().width <= supply.getBoundingClientRect().width + 1,
					faces: faces.map((f) => ({
						name: f.querySelector(".dm-ls-name")?.textContent || "",
						cost: f.querySelector(".dm-ls-cost")?.textContent || "",
						kind: f.querySelector(".dm-ls-kind")?.textContent || "",
						text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
						overflows: f.scrollHeight > f.clientHeight + 1,
					})),
				};
			});
			const wellFormed = ls.faces.length > 0
				&& ls.rows === 1 && ls.firstChildIsRow && ls.insideBoard
				&& ls.faces.every((f) => f.name && /^\$\d+$/.test(f.cost) && f.kind
					&& f.text > 0 && !f.overflows);
			check("an Event renders in the landscape row, above the Supply and inside it",
				ls.faces.length === 0 ? ls.rows === 0 : wellFormed, JSON.stringify(ls));
		}
		check("no page errors on an Adventures board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── a REAL Empires board (ph. 8): landmarks and Debt prices ───────────────
	// Two render paths arrive with this set and neither existed before it:
	//   * a LANDMARK in the landscape row — a landscape that is never bought, so
	//     it prints NO price at all and shows its VP store instead. The
	//     Adventures block above asserts every face carries a `$N`, which is
	//     exactly the assumption a landmark breaks;
	//   * a DEBT price on a Supply face — an orange hexagon, and for the four
	//     {ND} Actions it REPLACES the coin cost rather than sitting beside it
	//     (Engineer is {4D}, not "$0 + 4D"), so a board full of them must not
	//     render a row of misleading zeroes.
	// Both are asserted as well-formedness biconditionals rather than demanding
	// a particular deal, the same shape the rest of this file uses.
	async function dmEmpires(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "emp-harness", name: "Emp", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		for (const label of ["Empires", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		check("the Empires expansion is selectable",
			picked.length === 1 && /Empires/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("an Empires game deals a board", dealt);

		if (dealt) {
			const board = await page.evaluate(() => {
				const faces = [...document.querySelectorAll(".dm-lscape")].map((f) => ({
					name: f.querySelector(".dm-ls-name")?.textContent || "",
					kind: f.querySelector(".dm-ls-kind")?.textContent || "",
					cost: f.querySelector(".dm-ls-cost")?.textContent || "",
					vp: f.querySelector(".dm-ls-vp")?.textContent || "",
					text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
					overflows: f.scrollHeight > f.clientHeight + 1,
				}));
				const debts = [...document.querySelectorAll(".dm-supply .dm-card")]
					.filter((c) => c.querySelector(".dm-cost-d"))
					.map((c) => ({
						badge: c.querySelector(".dm-cost-d text")?.textContent || "",
						solo: !!c.querySelector(".dm-cost-d-solo"),
						coin: c.querySelector(".dm-cost")?.textContent || "",
					}));
				return { rows: document.querySelectorAll(".dm-lscape-row").length, faces, debts };
			});
			// every face is well formed, and a landmark prints NO price
			const facesOk = board.faces.every((f) =>
				f.name && f.kind && f.text > 0 && !f.overflows
				&& (f.kind === "landmark"
					? f.cost === ""
					: /^\$\d+( \+ \d+D)?$|^\d+D$/.test(f.cost)));
			check("a landmark renders with a VP store and no price at all",
				board.faces.length === 0
					? board.rows === 0
					: board.rows === 1 && facesOk,
				JSON.stringify(board.faces));
			// a Debt badge is a positive number, and a {ND} card shows NO coin
			check("a Debt-costed pile shows a Debt badge instead of a misleading $0",
				board.debts.every((d) => /^[1-9]\d*$/.test(d.badge)
					&& (d.solo ? d.coin === "" : d.coin !== "")),
				JSON.stringify(board.debts));
		}
		check("no page errors on an Empires board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── a REAL Renaissance board (ph. 9): PROJECTS and the Villagers mat ──────
	// Two more render paths this set adds, neither reachable before it:
	//   * a PROJECT in the landscape row. It prints a price like an Event but
	//     is bought ONCE and then permanent, marked by a per-player CUBE — so
	//     the row must render cube dots for owners and none for a fresh board.
	//     The Empires block above asserts a landmark prints no price; a project
	//     does print one, which is the other side of that biconditional.
	//   * the VILLAGERS counter in the resource bar, whose SPEND control is
	//     driven by the server's `spendable` (Villagers are Action-phase only)
	//     rather than by any client-side rule.
	// Written as well-formedness assertions rather than demanding a particular
	// deal, the same shape as the rest of this file.
	async function dmRenaissance(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "ren-harness", name: "Ren", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		for (const label of ["Renaissance", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		// the ph.-3 lesson: the picker used to map a literal list, so a shipped
		// set could be correct on the backend and unpickable in the UI
		check("the Renaissance expansion is selectable",
			picked.length === 1 && /Renaissance/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a Renaissance game deals a board", dealt);

		if (dealt) {
			const board = await page.evaluate(() => {
				const faces = [...document.querySelectorAll(".dm-lscape")].map((f) => ({
					name: f.querySelector(".dm-ls-name")?.textContent || "",
					kind: f.querySelector(".dm-ls-kind")?.textContent || "",
					cost: f.querySelector(".dm-ls-cost")?.textContent || "",
					cubes: f.querySelectorAll(".dm-cube").length,
					text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
					overflows: f.scrollHeight > f.clientHeight + 1,
				}));
				return { rows: document.querySelectorAll(".dm-lscape-row").length, faces };
			});
			// a PROJECT renders like a purchasable landscape and, on a fresh
			// board, carries NO cube — nobody has bought one yet
			const projects = board.faces.filter((f) => f.kind === "project");
			check("a Project renders with a price, its text and no cube yet",
				board.faces.length === 0
					? board.rows === 0
					: board.rows === 1 && projects.every((f) =>
						f.name && f.text > 0 && !f.overflows
						&& /^\$\d+$/.test(f.cost) && f.cubes === 0),
				JSON.stringify(board.faces));
		}
		check("no page errors on a Renaissance board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── a REAL Menagerie board (ph. 10): WAYS and the Exile mat ───────────────
	// The set is only creatable if `main.KNOWN_EXPANSIONS` carries it — which is
	// exactly what Renaissance shipped without, and what nothing in the Python
	// suite could see (the engine's own KINGDOM had the set, so every engine
	// test passed while the create request silently fell back to base+intrigue).
	// This block is the browser half of that guard.
	//
	// The new render path is a WAY: a landscape that is CONSULTED, never bought,
	// so it must print NO price. A Way's `cost` field is inert (`way` is not in
	// BUYABLE_LANDSCAPE_KINDS), so rendering its $0 would read as "free to buy"
	// for something there is no move for — the same biconditional the Empires
	// block asserts for landmarks and the Renaissance block for projects.
	{
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "men-harness", name: "Men", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) console.log(`  OK   ${name}`);
			else { shell.push(name); console.log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
		for (const label of ["Menagerie", "Base Set"]) {
			await page.locator(".dm-checks .dm-check", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".dm-checks .dm-check-on")].map((b) => b.textContent.trim()));
		check("the Menagerie expansion is selectable",
			picked.length === 1 && /Menagerie/.test(picked[0]), JSON.stringify(picked));
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a Menagerie game deals a board", dealt);

		if (dealt) {
			const board = await page.evaluate(() => {
				const faces = [...document.querySelectorAll(".dm-lscape")].map((f) => ({
					kind: f.querySelector(".dm-ls-kind")?.textContent || "",
					name: f.querySelector(".dm-ls-name")?.textContent || "",
					cost: f.querySelector(".dm-ls-cost")?.textContent || "",
					title: f.getAttribute("title") || "",
					text: (f.querySelector(".dm-ls-text")?.textContent || "").length,
					overflows: f.scrollHeight > f.clientHeight + 1,
				}));
				return { rows: document.querySelectorAll(".dm-lscape-row").length, faces };
			});
			const ways = board.faces.filter((f) => f.kind === "way");
			// A Way prints its name and rules text but NO price — in the face AND
			// in the tooltip, which the CSS `display:none` could never cover.
			check("a Way renders with its text and no price at all",
				ways.every((f) => f.name && f.text > 0 && !f.overflows
					&& f.cost === "" && !/\$/.test(f.title.split("\n")[0])),
				JSON.stringify(ways));
			// ...and the row itself is well-formed whatever the deal produced
			check("the Menagerie landscape row is well-formed",
				board.faces.length === 0 ? board.rows === 0 : board.rows === 1,
				JSON.stringify(board.faces.map((f) => f.kind)));
			// The Exile mat is a public per-seat zone that SCORES, so it renders
			// for every seat — but only once something is on it, exactly like the
			// Tavern mat. A fresh board must show none rather than an empty chip.
			const chips = await page.evaluate(() =>
				[...document.querySelectorAll(".dm-mat-chip")].map((c) => c.getAttribute("title") || ""));
			check("a fresh board shows no empty Exile chip",
				!chips.some((t) => /Exile/i.test(t)), JSON.stringify(chips));
		}
		check("no page errors on a Menagerie board", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dontminion: the detail modal is not card-only ─────────────────────────
	// A Dominion table is not only cards, and everything else on it used to be
	// unreadable: an Event's text is CLIPPED by its own face, a Landmark is never
	// bought so nothing ever opens it, and an Artifact nobody has taken yet
	// appears NOWHERE on the board at all. This block drives the three paths that
	// fixed that:
	//   1. the info gesture (right-click) on a LANDSCAPE — not a card face;
	//   2. the same gesture on a resource COUNTER, which carries spend buttons,
	//      so the gesture has to win without swallowing the button;
	//   3. the Kingdom browser's landscape + Artifact sections.
	//
	// Both the landscape deal and the Artifact roster are RANDOM (p11 deals 0-2
	// landscapes; Artifacts exist only if a Border Guard / Flag Bearer /
	// Treasurer / Swashbuckler was dealt), so the rig re-deals until it has a
	// board that exercises both rather than asserting whatever turned up — a
	// pass on an empty board would be a green tick over nothing. Renaissance
	// alone deals a landscape ~99.9% of the time and a bearer ~89%, so 8 attempts
	// miss with probability ~1e-8; missing FAILS, it does not skip.
	async function dmInfoModal(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "dminfo-harness", name: "Info", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};
		// cards.ARTIFACTS' `by` column, the other way round: which Artifacts a
		// game must keep available, given the kingdom it dealt.
		const ARTIFACT_BY = {
			"Flag Bearer": ["Flag"], "Border Guard": ["Horn", "Lantern"],
			Treasurer: ["Key"], Swashbuckler: ["Treasure Chest"],
		};
		const readBoard = () => page.evaluate(() => ({
			kingdom: [...document.querySelectorAll(".dm-supply .dm-kingdom .dm-card .dm-fitspan")]
				.map((s) => s.textContent.trim()),
			landscapes: [...document.querySelectorAll(".dm-lscape-row .dm-ls-name")]
				.map((s) => s.textContent.trim()),
		}));

		let board = null;
		for (let attempt = 0; attempt < 8 && !board; attempt++) {
			await page.goto(`http://localhost:${PORT}/dontminion`, { waitUntil: "networkidle" });
			await page.waitForSelector(".dm", { timeout: 25_000 }).catch(() => {});
			await page.getByRole("button", { name: /new game|create/i }).first()
				.click({ timeout: 15_000 }).catch(() => {});
			await page.waitForSelector(".dm-checks", { timeout: 15_000 }).catch(() => {});
			// Renaissance ONLY: the densest landscape pool we ship, and the only
			// set with Artifacts — mixing Base back in halves both odds.
			for (const label of ["Renaissance", "Base Set"]) {
				await page.locator(".dm-checks .dm-check", { hasText: label }).first()
					.click({ timeout: 10_000 }).catch(() => {});
			}
			await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});
			const dealt = await page.waitForSelector(".dm-supply .dm-card", { timeout: 30_000 })
				.then(() => true).catch(() => false);
			if (!dealt) continue;
			const b = await readBoard();
			const wanted = b.kingdom.filter((n) => ARTIFACT_BY[n]);
			if (b.landscapes.length && wanted.length) board = { ...b, wanted };
		}
		check("a Renaissance deal with both a landscape and an Artifact was reached",
			!!board, "8 deals produced none — see the block comment");
		if (!board) { await ctx.close(); return; }

		const expectArtifacts = [...new Set(board.wanted.flatMap((n) => ARTIFACT_BY[n]))].sort();

		// 1 — right-click a landscape. The plain click is BUY (or the info modal
		//     when it isn't buyable); the hold/right-click must read it either way.
		await page.locator(".dm-lscape-row .dm-lscape").first().click({ button: "right", timeout: 10_000 });
		const ls = await page.evaluate(() => {
			const m = document.querySelector(".dm-cardinfo");
			return m && {
				title: m.querySelector("h2")?.textContent.trim() || "",
				meta: m.querySelector(".dm-cardinfo-meta")?.textContent.trim() || "",
				text: m.querySelector(".dm-cardinfo-text")?.textContent.trim() || "",
				face: !!m.querySelector(".dm-cardinfo-lscape .dm-lscape"),
			};
		});
		check("right-clicking an Event/Project opens its detail modal",
			!!ls && ls.title === board.landscapes[0] && ls.face, JSON.stringify(ls));
		// The KIND blurb ("a Project is bought once, with a Buy…") is the half no
		// card prints, so it has to lead the text, above the card's own words.
		check("...leading with what that kind of landscape IS",
			!!ls && /\b(Event|Project|Landmark|Way|Trait|Prophecy)\b/.test(ls.text)
				&& ls.text.length > 120 && !!ls.meta, JSON.stringify(ls?.text?.slice(0, 120)));
		await page.locator(".dm-cardinfo .btn").click({ timeout: 10_000 });

		// 2 — a resource counter. It OWNS its click (the spend buttons live inside
		//     it), so this is the case the gesture has to win without eating them.
		await page.waitForSelector(".dm-resbar .dm-chip-info", { timeout: 25_000 });
		await page.locator(".dm-resbar .dm-chip-info").first().click({ button: "right", timeout: 10_000 });
		const counter = await page.evaluate(() => {
			const m = document.querySelector(".dm-cardinfo");
			return m && {
				title: m.querySelector("h2")?.textContent.trim() || "",
				text: m.querySelector(".dm-cardinfo-text")?.textContent.trim() || "",
				emblem: !!m.querySelector(".dm-cardinfo-emblem"),
			};
		});
		check("right-clicking a resource counter explains it too",
			!!counter && counter.title.length > 0 && counter.text.length > 60 && counter.emblem,
			JSON.stringify(counter));
		await page.locator(".dm-cardinfo .btn").click({ timeout: 10_000 });

		// 3 — the Kingdom browser. Landscapes are dealt WITH the kingdom, and an
		//     untaken Artifact has no other home on the whole screen.
		await page.locator(".dm-kingdom-btn").click({ timeout: 10_000 });
		await page.waitForSelector(".dm-kingdom-modal", { timeout: 10_000 });
		const kg = await page.evaluate(() => {
			const m = document.querySelector(".dm-kingdom-modal");
			return {
				heads: [...m.querySelectorAll("h3")].map((h) => h.textContent.trim()),
				landscapes: [...m.querySelectorAll(".dm-kgrid-wide .dm-lscape:not(.dm-ls-artifact) .dm-ls-name")]
					.map((s) => s.textContent.trim()).sort(),
				artifacts: [...m.querySelectorAll(".dm-ls-artifact .dm-ls-name")]
					.map((s) => s.textContent.replace("🏳", "").trim()).sort(),
				notes: m.querySelectorAll(".dm-kg-note").length,
			};
		});
		check("the Kingdom lists the Events/Projects it was dealt",
			JSON.stringify(kg.landscapes) === JSON.stringify([...board.landscapes].sort())
				&& kg.heads.some((h) => /Events|Projects|Landmarks|Ways/.test(h)) && kg.notes > 0,
			JSON.stringify(kg));
		// The exact roster, derived from the DEALT kingdom rather than hardcoded:
		// this is the check that would have caught the old board, where Lantern
		// and Horn existed in the rules and nowhere in the UI.
		check("...and every Artifact this game keeps, held or not",
			JSON.stringify(kg.artifacts) === JSON.stringify(expectArtifacts)
				&& kg.heads.includes("Artifacts"),
			`${JSON.stringify(kg.artifacts)} vs ${JSON.stringify(expectArtifacts)} from ${JSON.stringify(board.wanted)}`);
		await page.locator(".dm-ls-artifact").first().click({ timeout: 10_000 });
		const art = await page.evaluate(() => {
			const m = document.querySelector(".dm-cardinfo");
			return m && {
				title: m.querySelector("h2")?.textContent.trim() || "",
				meta: m.querySelector(".dm-cardinfo-meta")?.textContent.trim() || "",
				text: m.querySelector(".dm-cardinfo-text")?.textContent.trim() || "",
			};
		});
		check("an Artifact row opens its rules and says who holds it",
			!!art && expectArtifacts.includes(art.title)
				&& /not taken yet|has it|held by/.test(art.meta) && art.text.length > 80,
			JSON.stringify(art));

		check("no page errors reading the board's non-card things", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Offline vs-AI (Spender local play) ────────────────────────────────────
	// The first browser coverage of BOTH the offline driver and the client-WASM AI
	// path: /offline must boot with no backend ping, create a local game through the
	// wasm engine, and — with the network genuinely CUT (context.setOffline) — apply a
	// human move and get an AI reply from the worker-pool search. Then, back online
	// (the preview server is the asset origin; there's no SW on localhost to serve a
	// reload's assets), a reload must resume the save from IndexedDB.
	async function offlineSpender(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "offline-harness", name: "Offline", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		// The search pool announces itself on the console once its workers have FETCHED and
		// compiled the wasm — the network can only be cut after that (see below).
		let poolReady = false;
		page.on("console", (m) => { if (/\[client-AI\].*ready/.test(m.text())) poolReady = true; });
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/offline`, { waitUntil: "load" });
		const hubUp = await page.waitForSelector(".offline-panel", { timeout: 20_000 })
			.then(() => true).catch(() => false);
		check("the Local-vs-AI hub renders", hubUp);

		if (hubUp) {
			// S searches its full 4.5s budget per move; that's the real serving shape.
			await page.locator(".cm-pill", { hasText: "Steve" }).click({ timeout: 10_000 }).catch(() => {});
			await page.locator(".cm-create", { hasText: "Start Game" }).click({ timeout: 10_000 }).catch(() => {});
			const board = await page.waitForSelector(".gem-stack", { timeout: 20_000 })
				.then(() => true).catch(() => false);
			check("Start Game deals a local board", board);
			check("...at its /offline/<LOCALID> URL",
				/^\/offline\/LOCAL[A-Z0-9]+$/.test(new URL(page.url()).pathname),
				new URL(page.url()).pathname);

			// Cut the network only once the search pool has its wasm in memory — cutting
			// earlier races the pool's module fetches and hangs the AI's first search
			// (caught exactly that way; the AI can open the game when seats shuffle it
			// first). On a real device this window is covered by the SW precache.
			for (let i = 0; i < 40 && !poolReady; i++) await sleep(250);
			check("the search worker pool arms", poolReady);
			await ctx.setOffline(true);

			let takeable = 0;
			for (let i = 0; i < 60 && takeable < 3; i++) {   // the AI may move first — wait it out
				takeable = await page.locator(".gem-stack:not(.disabled)").count().catch(() => 0);
				if (takeable < 3) await sleep(500);
			}
			check("our turn arrives with the network OFF", takeable >= 3, `${takeable} takeable`);

			const colours = (await page.evaluate(() =>
				[...document.querySelectorAll(".gem-stack:not(.disabled)")]
					.map((e) => e.dataset.color).filter((c) => c && c !== "gold"))).slice(0, 3);
			for (const c of colours) {
				await page.locator(`.gem-stack[data-color="${c}"]`).click({ timeout: 10_000 }).catch(() => {});
			}
			const moved = await page.locator("button:visible", { hasText: /^Take/ }).first()
				.click({ timeout: 10_000 }).then(() => true).catch(() => false);
			check("a take-gems move applies through the local engine", moved);

			// The AI's reply is the whole point: the worker pool searches and the driver
			// applies — no server anywhere.
			let aiMoved = false;
			for (let i = 0; i < 50 && !aiMoved; i++) {
				aiMoved = (await page.locator(".gem-stack:not(.disabled)").count().catch(() => 0)) >= 3
					&& !(await page.locator(".ai-thinking").count().catch(() => 0));
				if (!aiMoved) await sleep(500);
			}
			check("the wasm AI replies while offline", aiMoved);

			// Assets need the network again for a reload (no SW on localhost) — the SAVE
			// must not: it comes from IndexedDB.
			await ctx.setOffline(false);
			await page.reload({ waitUntil: "load" }).catch(() => {});
			const resumed = await page.waitForSelector(".gem-stack", { timeout: 20_000 })
				.then(() => true).catch(() => false);
			check("a reload resumes the save from IndexedDB", resumed);

			await page.goBack().catch(() => {});
			const listed = await page.waitForSelector(".offline-save-row", { timeout: 10_000 })
				.then(() => true).catch(() => false);
			check("Back lands on the hub with the save listed", listed);
		}
		check("no page errors in offline play", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Every lobby column spans the phone ────────────────────────────────────
	// The base rules pin each column with two classes; the phone reset used one,
	// and specificity beats source order, so Active stayed in column 2 of a
	// one-column grid — rendered shrunk to content against the right edge. The
	// existing tier checks all measured the GRID, which was correctly 1fr; only
	// the column's own box shows it. Checked on every game that pins columns.
	async function phoneLobbyColumns(log) {
		const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "phone-harness", name: "Phone", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		// EVERY game that pins columns — kept in step with the Python contract
		// test, which derives the same roster from the tree. CoC earns its place
		// specifically: it is the one whose own sheet is concatenated BEFORE the
		// shared one, so it resolves these ties in the opposite order.
		for (const [route, marker] of [["/spender", ".sp-lobby, .lby-cols"],
			["/duel", ".duel"], ["/coc", ".coc"], ["/dontminion", ".dm"],
			["/dissonance", ".dis"], ["/ragtag", ".ragtag"], ["/orbit", ".orbit"]]) {
			await page.goto(`http://localhost:${PORT}${route}`, { waitUntil: "networkidle" });
			await page.waitForSelector(marker, { timeout: 25_000 }).catch(() => {});
			await page.waitForSelector(".lby-tabs", { timeout: 15_000 }).catch(() => {});
			for (const tab of ["Open", "Active", "History"]) {
				await page.locator(".lby-tab", { hasText: new RegExp(`^${tab}`) }).first()
					.click({ timeout: 8_000 }).catch(() => {});
				await sleep(180);
				const m = await page.evaluate(() => {
					const cols = document.querySelector(".lby-cols");
					if (!cols) return null;
					const vis = [...cols.children].find((c) => getComputedStyle(c).display !== "none");
					if (!vis) return null;
					const cb = cols.getBoundingClientRect(), vb = vis.getBoundingClientRect();
					return {
						gridW: Math.round(cb.width), colW: Math.round(vb.width),
						leftGap: Math.round(vb.left - cb.left),
						rightGap: Math.round(cb.right - vb.right),
						col: getComputedStyle(vis).gridColumnStart,
					};
				});
				// Three things, each catching a different half of the defect:
				// track 1 (an implicit track is the bug itself), most of the
				// width (not shrunk to content), and CENTRED — a column pushed
				// against one edge is what the phone actually showed. Gaps are
				// compared rather than required to be zero, because a game may
				// legitimately pad its own column (Dontminion uses 18px).
				check(`${route} ${tab} spans the phone`,
					!!m && m.col === "1" && m.colW >= m.gridW * 0.85
						&& Math.abs(m.leftGap - m.rightGap) <= 2,
					JSON.stringify(m));
			}
		}
		check("no page errors in the phone lobby", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dissonance's skat auction ───────────────────────────────────────────────
	// Skat mode is a room FLAG chosen in the create modal, which is exactly the
	// failure class this gate exists for: Dontminion's Renaissance set rendered
	// fine and could not be CREATED, because a list in main.py was stale. A
	// mounted /dissonance screen says nothing about whether picking "Skat" deals a
	// skat game, so this drives the segment, the deal, and the first bid — the
	// value ladder is a middle panel that does not exist in classic mode at all.
	async function dissonanceSkat(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "skat-harness", name: "Skat", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dis", { timeout: 25_000 }).catch(() => {});
		// The per-frame panel recorder, installed HERE because the reported blink
		// is skat, ROUND 1 — the configuration this block previously drove only
		// as far as one completed trick, so the END of a skat round had no
		// browser coverage at all. Same open-ended signature as the classic one:
		// markers plus a text digest, so an unpredicted intruder names itself.
		await page.evaluate(() => {
			window.__panels = [];
			let lastPanel = null;
			const panelNow = () => {
				const has = (s) => !!document.querySelector(s);
				const marks = [
					has(".dis-valgrid") || has(".dis-bidgrid") ? "AUCTION" : "",
					has(".dis-denoms") ? "denoms" : "",
					has(".dis-clears") ? "clears" : "",
					has(".dis-reveal") ? "reveal" : "",
					has(".dis-result") ? "RESULT" : "",
					has(".dis-trick") ? "board" : "",
				].filter(Boolean).join("+");
				const mid = document.querySelector(".dis-mid, .dis-centre, .dis-table");
				const txt = (mid?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60);
				return `${marks || "(no marker)"} :: ${txt}`;
			};
			const tick = () => {
				const p = panelNow();
				if (p !== lastPanel) { window.__panels.push([Math.round(performance.now()), p]); lastPanel = p; }
				requestAnimationFrame(tick);
			};
			requestAnimationFrame(tick);
		});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		// The modal is the shared shape every other game uses: segmented rows,
		// then one deferred "Create Game" in the footer. Selecting an option must
		// NOT create the room on its own.
		for (const label of [/^VS AI$/, /^Normal$/, /^Skat$/]) {
			await page.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		check("the create modal carries opponent, difficulty and auction",
			["VS AI", "Normal", "Skat"].every((x) => picked.includes(x)), JSON.stringify(picked));
		const stillOpen = await page.locator(".cm-panel").count();
		check("picking an option does not create the game on its own", stillOpen === 1);

		await page.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		// A skat room deals immediately vs the bot, straight into the number
		// ladder — a grid that classic mode never renders.
		const ladder = await page.waitForSelector(".dis-valgrid button", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("a skat room deals into the number ladder", ladder);

		if (ladder) {
			const rungs = await page.evaluate(() =>
				[...document.querySelectorAll(".dis-valgrid button")].map((b) => +b.textContent));
			check("the ladder is ascending and server-supplied, not a 1..12 level row",
				rungs.length > 12 && rungs.every((v, i) => i === 0 || v > rungs[i - 1]),
				JSON.stringify(rungs.slice(0, 8)));

			await page.locator(".dis-valgrid button").first().click().catch(() => {});
			// Selecting a number shows what it could BUY — the mode's whole
			// argument, and the one thing /catalog is fetched for.
			const clears = await page.waitForSelector(".dis-clears .dis-clear", { timeout: 10_000 })
				.then(() => true).catch(() => false);
			check("a selected number shows every game that clears it", clears);

			// A SELECTED BID MUST BE READABLE. This shipped broken in both
			// auction modes and nothing could see it: `.on` pairs `background:
			// var(--accent)` with a near-black `color`, and --accent was defined
			// nowhere a board could reach — so an undefined var() made only the
			// BACKGROUND declaration invalid, leaving dark text on the unchanged
			// dark button. Markup, geometry and class names were all perfect; the
			// number was simply invisible. Contrast is the only thing that sees
			// it, so measure that rather than the class.
			const readable = await page.evaluate(() => {
				const on = document.querySelector(".dis-valgrid button.on");
				if (!on) return { err: "no selected rung" };
				const cs = getComputedStyle(on);
				const parse = (c) => (c.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
				// Alpha 0 means the declaration was dropped, so the button is
				// still painting whatever is behind it — report it as such
				// rather than measuring a transparent colour as if it were one.
				const a = Number((cs.backgroundColor.match(/[\d.]+/g) || [])[3] ?? 1);
				const lum = (rgb) => {
					const [r, g, b] = rgb.map((v) => {
						const s = v / 255;
						return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
					});
					return 0.2126 * r + 0.7152 * g + 0.0722 * b;
				};
				const L1 = lum(parse(cs.backgroundColor));
				const L2 = lum(parse(cs.color));
				const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
				return { bg: cs.backgroundColor, fg: cs.color, alpha: a,
					ratio: Math.round(ratio * 100) / 100 };
			});
			check("a selected bid is painted, not left transparent",
				readable.alpha > 0, JSON.stringify(readable));
			// 3:1 is the large/bold-text floor. The broken build measured ~1.3.
			check("...and its number contrasts with what it sits on",
				readable.ratio >= 3, JSON.stringify(readable));

			// ...AND IT MUST SURVIVE :hover, ON EVERY FAMILY OF SELECTABLE
			// BUTTON. The check above tested only `.dis-valgrid` and passed
			// while the SUIT row was visibly broken on a phone: the hover fill
			// out-specified `.on` (`:not(:disabled)` contributes its argument,
			// so (0,3,1) beat (0,2,1)) and repainted the selected button grey,
			// leaving `.on`'s near-black glyph on it. `:hover` LATCHES to the
			// last thing tapped on iOS, so that was permanent, not transient —
			// reported from a phone with the number green and the suit not.
			// valgrid was the one family that happened to be safe, purely
			// because its hover rule ties on specificity and loses on source
			// order, which is exactly why testing one family proved nothing.
			// Hover is the only way to see it: idle, all four are correct.
			for (const fam of [".dis-valgrid button.on", ".dis-bidgrid button.on",
				".dis-denoms button.on", ".dis-ann.on"]) {
				const el = await page.$(fam);
				if (!el) continue;              // not every family is on screen in every phase
				const before = await el.evaluate((e) => getComputedStyle(e).backgroundColor);
				await el.hover();
				const after = await el.evaluate((e) => getComputedStyle(e).backgroundColor);
				check(`a selected ${fam} keeps its colour under :hover`,
					after === before, `${fam}: ${before} -> ${after}`);
			}

			// GRAND has to be among them. It is served like every other
			// denomination (a base in /catalog, a row in `declare`), so a
			// frontend that quietly dropped it — a label array one short, a
			// filter that stopped at no-trump — would render a perfectly normal
			// hint with a game missing from it and nothing red anywhere.
			const clearLabels = await page.evaluate(() =>
				[...document.querySelectorAll(".dis-clears .dis-clear")].map((s) => s.textContent.trim()));
			check("the clears hint offers Grand alongside the suits",
				clearLabels.some((s) => s.includes("Grand")), JSON.stringify(clearLabels));
			check("no clears entry renders an unnamed denomination",
				clearLabels.length > 0 && clearLabels.every((s) => /\d+(♣|♦|♥|♠|NT|Grand)$/.test(s)),
				JSON.stringify(clearLabels));

			await page.getByRole("button", { name: /^Bid \d+$/ }).first()
				.click({ timeout: 10_000 }).catch(() => {});
			// The bot answers, and the round moves on — to its own bid, or to
			// the talon prompt if it passed. Either way the auction is NOT stuck.
			// The check below wants log >= 2, so wait for exactly that, capped at
			// the 2500ms this used to sleep flat.
			await until(page,
				() => document.querySelectorAll(".dis-bidlog div").length >= 2, 2500);
			const moved = await page.evaluate(() => ({
				log: document.querySelectorAll(".dis-bidlog div").length,
				phase: !!document.querySelector(".dis-auction, .dis-result"),
			}));
			check("the bot answers a number bid", moved.log >= 2 && moved.phase,
				JSON.stringify(moved));
		}

		// Drive the room to a completed trick. Skat puts FOUR phases between the
		// last bid and trick 1 (talon, declare, Kontra, Re), each with its own
		// control, so a loop that only clicks cards never reaches play at all —
		// which is exactly what this check caught the first time it ran. Take
		// whichever control is on screen.
		// The sleeps here are POLLING CADENCE, not settle windows: every exit in
		// both loops below is evidence (.dis-lasttrick / .dis-result appearing),
		// and a click landing on a not-yet-updated control is validated away by
		// the server. Full-tilt play is already proven territory — the beat block
		// deliberately runs at 90-260ms — so these run at the same pace rather
		// than the 450/500ms they idled at when the block was written.
		const step = async (name) => {
			const b = page.getByRole("button", { name }).first();
			if (await b.count() === 0) return false;
			await b.click({ timeout: 5_000 }).catch(() => {});
			await sleep(220);
			return true;
		};
		let grandPicked = false;
		for (let i = 0; i < 120; i++) {   // 2x the old 60: same wall-clock at half the sleep
			if (await page.locator(".dis-lasttrick").count() > 0) break;
			if (await step(/^Play Hand/)) continue;           // talon
			// Pick GRAND at the declaration when it is offered, so this gate
			// plays a real Grand round rather than only rendering its label:
			// the tens are trump and belong to no suit, which is the one
			// contract where follow-suit differs, and it is worth having a
			// browser drive it end to end against the live engine.
			if (!grandPicked && await step(/^Grand×\d+$/)) {
				grandPicked = true;
				continue;
			}
			if (await step(/^Declare$/)) continue;            // declaration
			if (await step(/^Let it stand$/)) continue;       // defender declines Kontra
			if (await step(/^Accept$/)) continue;             // declarer declines Re
			if (await step(/^Pass$/)) continue;               // settle the auction
			const card = page.locator(".dis-seat .dis-card.play").last();
			if (await card.count() > 0) {
				await card.click({ timeout: 5_000 }).catch(() => {});
				await sleep(220);
				continue;
			}
			await sleep(250);
		}
		const lt = await page.evaluate(() => {
			const el = document.querySelector(".dis-lasttrick");
			if (!el) return null;
			return {
				cards: el.querySelectorAll(".dis-card").length,
				marksWinner: !!el.querySelector(".dis-lt-play.won"),
			};
		});
		check("the previous trick stays visible beside the board",
			!!lt && lt.cards === 2 && lt.marksWinner, JSON.stringify(lt));
		check("no page errors in the skat auction", errors.length === 0,
			errors[0]?.slice(0, 160) || "");

		// THE DESKTOP BOARD IS THREE COLUMNS, and which side each lands on is a
		// GEOMETRIC fact, not a source-order one: the DOM is board, info, match
		// (the order a phone stacks and a screen reader hears), and the wide
		// grid places the match to the LEFT explicitly. A regression there
		// auto-places the match under the table and looks like a stray panel
		// rather than a broken layout, so it is measured by x-coordinate.
		//
		// The felt FILLING its column is the other half. It briefly sized itself
		// to its seven cards, which left the surplus width as bare page — and a
		// `container-type: size` table whose width stops being definite collapses
		// to its padding (31px in a 1616px column, twice now: once from an auto
		// margin, once from a malformed CSS comment that dropped the whole
		// declaration). A ratio catches both, and nothing else in the gate would.
		const cols = await page.evaluate(() => {
			const box = (s) => {
				const el = document.querySelector(s);
				if (!el) return null;
				const r = el.getBoundingClientRect();
				return { x: Math.round(r.x), w: Math.round(r.width) };
			};
			const t = box(".dis-table"), i = box(".dis-side-info"), m = box(".dis-side-match");
			const main = box(".dis-main");
			return { t, i, m, main, width: window.innerWidth,
				scrolls: document.documentElement.scrollHeight
					> document.documentElement.clientHeight + 1 };
		});
		check("the match column sits left of the felt, the round's info right of it",
			!!cols.t && !!cols.i && !!cols.m
				&& cols.m.x + cols.m.w <= cols.t.x + 1
				&& cols.i.x >= cols.t.x + cols.t.w - 1,
			JSON.stringify(cols));
		// >= 45% of the grid, not of the window: two panel columns are entitled
		// to the rest. A collapsed table reads ~2%.
		check("...and the felt fills the column it was given",
			!!cols.t && !!cols.main && cols.t.w >= cols.main.w * 0.45,
			JSON.stringify(cols));
		check("the desktop board does not scroll", cols.scrolls === false,
			JSON.stringify(cols));
		// THE TRICK LINE vs THE NAME UNDER A CARD. The line used to be absolutely
		// positioned over the bottom of the trick band, 4px clear of a ~14px
		// label, so "Trick 5 of 13 · −1" drew straight through "Bot". Only
		// geometry can see it — the text is all present and all "visible".
		//
		// It needs a card ON THE TABLE, which is not a state the board sits in:
		// a trick clears itself. So play one and measure inside the hold, and
		// treat "never got a reading" as a FAILURE rather than skipping — a null
		// here would be a green tick over a check that never ran.
		let trickLine = null;
		for (let i = 0; i < 14 && trickLine === null; i++) {
			trickLine = await page.evaluate(() => {
				const info = document.querySelector(".dis-trickinfo");
				const label = document.querySelector(".dis-tp .muted");
				if (!info || !label) return null;
				const a = info.getBoundingClientRect(), b = label.getBoundingClientRect();
				return { overlaps: !(a.bottom <= b.top + 1 || a.top >= b.bottom - 1),
					gap: Math.round((a.top - b.bottom) * 10) / 10 };
			});
			if (trickLine !== null) break;
			const c = page.locator(".dis-seat .dis-card.play").last();
			if (await c.count() > 0) await c.click({ timeout: 3_000 }).catch(() => {});
			await sleep(150);
		}
		check("the trick line does not draw over the name under a played card",
			trickLine !== null && trickLine.overlaps === false,
			JSON.stringify(trickLine));
		// PLAY'S TEXT RIDES THE RAIL ON A WIDE DESKTOP (2026-08-12): the trick
		// counter, the contract chip and the turn bar sit BESIDE the felt's
		// cards, not between the seats — the same placement the auction and the
		// report get. Geometry again: the playside's left edge must clear the
		// hand row's right edge, or it is back in the middle paying for itself
		// out of the card budget.
		const rail = await page.evaluate(() => {
			const ps = document.querySelector(".dis-playside");
			const hand = document.querySelector(".dis-table .dis-seat .dis-hand");
			if (!ps || !hand) return null;
			const a = ps.getBoundingClientRect(), b = hand.getBoundingClientRect();
			return { psX: Math.round(a.x), handRight: Math.round(b.x + b.width),
				chip: !!ps.querySelector(".dis-chip"), info: !!ps.querySelector(".dis-trickinfo"),
				beside: a.x >= b.x + b.width - 1 };
		});
		check("play's trick line, contract chip and turn bar sit beside the cards",
			rail !== null && rail.beside === true && rail.chip && rail.info,
			JSON.stringify(rail));
		// THE BIDDING AND THE ROUND'S TRICKS live in the two panels, and both
		// are the only place either can be read: the bid log used to sit inside
		// the auction panel and vanished the moment the auction ended.
		const logs = await page.evaluate(() => ({
			bids: document.querySelectorAll(".dis-p-contract .dis-bidlog > div").length,
			tricks: document.querySelectorAll(".dis-p-points .dis-th-row").length,
			firstTrick: document.querySelector(".dis-p-points .dis-th-row")?.innerText
				?.replace(/\s+/g, " ").trim() || "",
		}));
		check("the bidding is still on screen after the auction has ended",
			logs.bids >= 2, JSON.stringify(logs));
		// LIVE PANELS FIRST. Last trick changes every trick; Contract settles once
		// a round. Ordering is DOM order in the JSX, so it is one line to get
		// wrong and invisible to everything else in this file.
		const order = await page.evaluate(() => {
			const y = (s) => { const e = document.querySelector(s); if (!e) return null;
				return Math.round(e.getBoundingClientRect().y); };
			return { last: y(".dis-p-last"), contract: y(".dis-p-contract"),
				points: y(".dis-p-points") };
		});
		check("the last trick sits above the contract, which sits above the points",
			order.last !== null && order.contract !== null && order.points !== null
				&& order.last < order.contract && order.contract < order.points,
			JSON.stringify(order));
		check("...and every completed trick is listed with who took it and what it paid",
			logs.tricks >= 1 && /^#\d+ .+ [+−-]?\d+$/.test(logs.firstTrick),
			JSON.stringify(logs));

		// Everything the board tells you must survive a PHONE. The side panel is
		// where the last trick, the talon and the move log live, and the mobile
		// sheet used to display:none the whole column — so three things a player
		// paid the auction to see were desktop-only, silently.
		await page.setViewportSize({ width: 390, height: 844 });
		await sleep(400);
		const onPhone = await page.evaluate(() => {
			const vis = (sel) => {
				const el = document.querySelector(sel);
				if (!el) return null;
				const r = el.getBoundingClientRect();
				return getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0;
			};
			return {
				side: vis(".dis-side"),
				lastTrick: vis(".dis-p-last"),
				contractChip: vis(".dis-chip"),
				lastTrickCards: document.querySelectorAll(".dis-lasttrick .dis-card").length,
				// These two USED to be dropped on a phone as duplicates of the
				// chip and the seat rows. They are not duplicates any more —
				// they carry the bidding and the round's trick history, which
				// live nowhere else — so a phone must show them.
				contractPanel: vis(".dis-p-contract"),
				pointsPanel: vis(".dis-p-points"),
				phoneBids: document.querySelectorAll(".dis-p-contract .dis-bidlog > div").length,
				phoneTricks: document.querySelectorAll(".dis-p-points .dis-th-row").length,
				pageScrollsSideways: document.documentElement.scrollWidth
					> document.documentElement.clientWidth + 1,
			};
		});
		check("the last trick survives a phone",
			onPhone.side === true && onPhone.lastTrick === true
				&& onPhone.lastTrickCards === 2,
			JSON.stringify(onPhone));
		check("the contract is on screen on a phone", onPhone.contractChip === true,
			JSON.stringify(onPhone));
		check("...and the bidding and the trick history survive a phone too",
			onPhone.contractPanel === true && onPhone.pointsPanel === true
				&& onPhone.phoneBids >= 2 && onPhone.phoneTricks >= 1,
			JSON.stringify(onPhone));
		check("the phone board does not scroll sideways",
			onPhone.pageScrollsSideways === false, JSON.stringify(onPhone));
		// The board must FILL the phone, not size itself to its content and leave
		// a third of the screen dead below it.
		const fill = await page.evaluate(() => {
			const t = document.querySelector(".dis-table");
			if (!t) return null;
			return { table: Math.round(t.getBoundingClientRect().height),
				view: window.innerHeight };
		});
		check("the board fills the phone rather than sizing to its content",
			!!fill && fill.table >= fill.view * 0.8, JSON.stringify(fill));

		// PLAY ROUND 1 OUT — the reported configuration. This runs LAST in the
		// block on purpose: it ends on the result panel, and every check above
		// needs a live mid-play board. (Putting it earlier broke "the contract is
		// on screen on a phone", which is a fair description of what a finished
		// game looks like.)
		// 400 x 120ms keeps the WALL-CLOCK budget the loop had at 200 x 260ms —
		// halving the sleep without touching the bound would have silently halved
		// the deadline instead, which reads as "round never finished" on a slow box.
		for (let i = 0; i < 400; i++) {
			if (await page.locator(".dis-result").count() > 0) break;
			const card = page.locator(".dis-seat .dis-card.play").last();
			if (await card.count() > 0) {
				await card.click({ timeout: 5_000 }).catch(() => {});
				await sleep(120);
				continue;
			}
			await sleep(120);
		}
		const skatPanels = await page.evaluate(() => window.__panels || []);
		const sRes = skatPanels.findIndex(([, p]) => p.includes("RESULT"));
		check("a skat round 1 plays out to its result panel", sRes >= 0,
			`tail=${JSON.stringify(skatPanels.slice(-6))}`);
		// The transition assertion, in the configuration the blink was reported
		// in. It names whatever it finds rather than testing a guess.
		const sBefore = sRes > 0 ? skatPanels[sRes - 1][1] : null;
		check("nothing gets a frame between the last trick and the skat result",
			sRes <= 0 || sBefore.includes("board"),
			`the frame before RESULT showed: ${sBefore} | tail=${JSON.stringify(skatPanels.slice(-8))}`);
		await ctx.close();

		// ── MINOR mode, same failure class as skat's opening check: a room FLAG
		// picked in the create modal (the Renaissance lesson — a mounted screen
		// says nothing about whether picking "Minor" deals a minor game). What
		// separates a minor room from a classic one on screen is the LADDER: the
		// classic bid grid capped at level 6, straight off the server's option
		// list — so that cap is the deal-really-happened marker, the way skat's
		// value ladder is above.
		const mctx = await browser.newContext();
		await mctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "minor-harness", name: "Minor", guest: true })));
		const mpage = await mctx.newPage();
		const merrors = [];
		mpage.on("pageerror", (e) => merrors.push(String(e)));
		await mpage.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await mpage.waitForSelector(".dis", { timeout: 25_000 }).catch(() => {});
		await mpage.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await mpage.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		for (const label of [/^VS AI$/, /^Easy$/, /^Minor$/]) {
			await mpage.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const mpicked = await mpage.evaluate(() =>
			[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		check("the create modal offers Minor as a third mode",
			mpicked.includes("Minor"), JSON.stringify(mpicked));
		await mpage.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		const mgrid = await mpage.waitForSelector(".dis-bidgrid button", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("a minor room deals into the classic bid grid", mgrid);
		if (mgrid) {
			// WHO OPENS IS RANDOM (seats are shuffled at the deal), so the grid is
			// either the opener's full ladder or an overtake range above the bot's
			// opening bid. Each case has its own minor-only marker: the full
			// ladder reads exactly 1..6 where classic's reads 1..10, and once the
			// bot's contract stands the side panel prices Null against "no +1
			// trick" where classic says +2. Assert whichever case this deal is.
			// The Null price is read off the CONTRACT PANEL's text, not off a
			// `.dis-scorerow`: the classic/minor panel was condensed to a
			// headline plus one money line (2026-08-12), so the price moved out
			// of a row and this read "" — the gate failed on a room that was
			// perfectly correct. The panel is the stable thing to ask; where
			// inside it the price sits is layout.
			const m = await mpage.evaluate(() => ({
				levels: [...document.querySelectorAll(".dis-bidgrid button")].map((b) => +b.textContent),
				nullRow: document.querySelector(".dis-p-contract")?.textContent || "",
			}));
			const openerCase = Math.min(...m.levels) === 1 && Math.max(...m.levels) === 6;
			const overtakeCase = m.nullRow.includes("+1") && Math.max(...m.levels) <= 6;
			check("the room is really minor: a 1..6 ladder or a +1-trick Null price",
				openerCase || overtakeCase, JSON.stringify(m));
		}
		check("no page errors creating a minor room", merrors.length === 0,
			merrors[0]?.slice(0, 160) || "");
		await mctx.close();

		// ── DUMMY mode, the same Renaissance lesson a third time, and with more
		// to prove than the others: this room flag does not just re-price the
		// game, it deals a THIRD HAND and makes the trick three cards wide. A
		// mounted board says nothing about whether that shape survives the
		// create modal, the deal, the wire and the renderer -- and none of it is
		// covered by the Rust parity fixtures, which are two-seat.
		const dctx = await browser.newContext();
		await dctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "dummy-harness", name: "Dummy", guest: true })));
		const dpage = await dctx.newPage();
		const derrors = [];
		dpage.on("pageerror", (e) => derrors.push(String(e)));
		await dpage.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await dpage.waitForSelector(".dis", { timeout: 25_000 }).catch(() => {});
		await dpage.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await dpage.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		for (const label of [/^VS AI$/, /^Easy$/, /^Dummy$/]) {
			await dpage.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const dpicked = await dpage.evaluate(() =>
			[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		check("the create modal offers Dummy as a fourth mode",
			dpicked.includes("Dummy"), JSON.stringify(dpicked));
		await dpage.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		const dealt = await dpage.waitForSelector(".dis-bidgrid button, .dis-dummy", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("a dummy room deals", dealt);
		// THE THIRD SEAT IS THE MARKER, and it has to be on screen: the whole
		// mechanic is that you can read and play a hand that is not yours.
		const dseat = await dpage.evaluate(() => {
			const el = document.querySelector(".dis-dummy");
			if (!el) return null;
			const r = el.getBoundingClientRect();
			return {
				visible: getComputedStyle(el).display !== "none" && r.height > 0,
				name: el.querySelector(".dis-seatname")?.textContent || "",
				faceUp: el.querySelectorAll(".dis-hand .dis-card:not(.back)").length,
				backs: el.querySelectorAll(".dis-hand .dis-card.back").length,
				piles: el.querySelectorAll(".dis-pile").length,
				seats: document.querySelectorAll(".dis-seat").length,
			};
		});
		check("the dummy is on the board, face up, with its own piles",
			!!dseat && dseat.visible && dseat.faceUp === 7 && dseat.backs === 0
			&& dseat.piles === 3 && dseat.seats === 3, JSON.stringify(dseat));
		check("...and it says whose hand it is", /dummy/i.test(dseat?.name || ""),
			JSON.stringify(dseat?.name));
		// Play a few tricks out and watch the trick grow to THREE cards. Two
		// would mean the dummy is decorative -- rendered but not dealt into the
		// trick, which is exactly what a half-wired third seat looks like.
		let widest = 0;
		for (let i = 0; i < 120; i++) {
			widest = Math.max(widest, await dpage.evaluate(() =>
				document.querySelectorAll(".dis-trick .dis-tp").length));
			if (widest >= 3) break;
			const card = dpage.locator(".dis-card.play").first();
			if (await card.count() > 0) {
				await card.click({ timeout: 5_000 }).catch(() => {});
				await sleep(120);
				continue;
			}
			// Still bidding — dummy mode runs CLASSIC's auction (level, then
			// denomination, then Bid), so the shared helper drives it rather
			// than a hand-rolled click that only looked like it worked.
			if (await dpage.locator(".dis-bidgrid button").count() > 0) {
				await disBidCheaply(dpage);
				await sleep(200);
				continue;
			}
			// The defender's Double sits between the auction and trick 1.
			const stand = dpage.getByRole("button", { name: /^Let it stand$/ }).first();
			if (await stand.count() > 0) {
				await stand.click({ timeout: 5_000 }).catch(() => {});
			}
			await sleep(150);
		}
		check("a trick in a dummy room is three cards wide", widest >= 3,
			`widest trick seen: ${widest}`);
		check("the trick line counts to the mode's own length",
			/of 13\b/.test(await dpage.locator(".dis-trickinfo").first()
				.textContent().catch(() => "")),
			await dpage.locator(".dis-trickinfo").first().textContent().catch(() => ""));
		// THE WIDE DECK REACHED THE BROWSER. Dummy deals 40 cards -- the base 32
		// plus a 5 and a 6 in each suit, at ids 32..39 -- and a client that
		// still decoded ids as `suit*8 + rank` would render those eight as suit
		// 4 and 5, i.e. a blank glyph and an undefined rank, not an error. 39 of
		// the 40 are dealt, so a board mid-round holds at least seven of the
		// eight; asserting one is enough to catch a decoder that cannot see
		// them at all.
		const lows = await dpage.evaluate(() => {
			const seen = new Set();
			for (const el of document.querySelectorAll(".dis-card .dis-r"))
				seen.add(el.textContent.trim());
			return [...seen];
		});
		check("the wide deck's 5s and 6s render as themselves",
			lows.includes("5") || lows.includes("6"), JSON.stringify(lows));
		check("...and no card renders with an unknown rank or suit",
			lows.every((r) => ["5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
				.includes(r)), JSON.stringify(lows));
		// A DUMMY ROOM HAS NO TALON, and `shown` is an empty array there --
		// which is TRUTHY, so the panel rendered under a heading promising
		// cards with nothing beneath it.
		check("no talon panel in a room that has no talon",
			await dpage.locator(".dis-p-talon").count() === 0);
		// THE PHONE LAYOUT, measured rather than eyeballed. Three seats plus
		// the auction panel do not fit a pinned viewport, and the card size
		// budget divided by a hardcoded FOUR card rows -- so every card came
		// out half again too tall and the seats drew straight over the
		// auction. The assertion is geometric: no two sections of the table
		// may overlap, and no card may escape its own seat.
		await dpage.setViewportSize({ width: 390, height: 844 });
		await sleep(400);
		const phone = await dpage.evaluate(() => {
			const kids = [...(document.querySelector(".dis-table")?.children || [])]
				.map((el) => {
					const r = el.getBoundingClientRect();
					return { cls: String(el.className).slice(0, 20), top: r.top, bot: r.bottom };
				})
				.filter((k) => k.bot > k.top);
			const overlaps = [];
			for (let i = 1; i < kids.length; i++) {
				if (kids[i].top < kids[i - 1].bot - 1) {
					overlaps.push(`${kids[i - 1].cls}/${kids[i].cls}`);
				}
			}
			let escaped = 0;
			for (const seat of document.querySelectorAll(".dis-seat")) {
				const sr = seat.getBoundingClientRect();
				for (const c of seat.querySelectorAll(".dis-card")) {
					const cr = c.getBoundingClientRect();
					if (cr.bottom > sr.bottom + 1 || cr.top < sr.top - 1) escaped++;
				}
			}
			return {
				overlaps, escaped, sections: kids.length,
				sideways: document.documentElement.scrollWidth
					> document.documentElement.clientWidth + 1,
			};
		});
		check("the three-seat board does not overlap itself on a phone",
			phone.overlaps.length === 0 && phone.sections >= 4, JSON.stringify(phone));
		check("...and no card escapes its own seat", phone.escaped === 0,
			JSON.stringify(phone));
		check("...and the phone board does not scroll sideways",
			phone.sideways === false, JSON.stringify(phone));
		check("no page errors creating and playing a dummy room", derrors.length === 0,
			derrors[0]?.slice(0, 160) || "");
		await dctx.close();
	}

	// ── QUARTET, the fifth mode: four hands, two players ───────────────────────
	// The Renaissance lesson a fourth time, and this mode has the most to prove
	// of any of them. It deals FOUR hands off a 52-card deck, plays NINE tricks
	// of four, adds a phase between the auction and trick 1, and ends with three
	// cards still in every hand. None of that is covered by the Rust parity
	// fixtures (two-seat), and `client_searchable` is false so no browser search
	// touches it either -- what is here plus `test_quartet.py` is the coverage.
	async function dissonanceQuartet(log) {
		const ctx = await browser.newContext();
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "quartet-harness", name: "Quartet", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		await page.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dis", { timeout: 25_000 }).catch(() => {});
		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		for (const label of [/^VS AI$/, /^Easy$/, /^Quartet$/]) {
			await page.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		check("the create modal offers Quartet as a fifth mode",
			picked.includes("Quartet"), JSON.stringify(picked));
		await page.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		const dealt = await page.waitForSelector(".dis-bidgrid button, .dis-qmine", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("a quartet room deals", dealt);

		// FOUR SEATS, and the redaction visible on the board: your own two hands
		// face up, the opponent's two face down. Publishing either of theirs
		// would delete the finesse, which is the mode's whole point, so this is
		// a rules assertion as much as a rendering one.
		const board = await page.evaluate(() => {
			const seat = (sel) => {
				const el = document.querySelector(sel);
				if (!el) return null;
				const r = el.getBoundingClientRect();
				return {
					visible: getComputedStyle(el).display !== "none" && r.height > 0,
					name: el.querySelector(".dis-seatname")?.textContent || "",
					faceUp: el.querySelectorAll(".dis-hand .dis-card:not(.back)").length,
					backs: el.querySelectorAll(".dis-hand .dis-card.back").length,
				};
			};
			return {
				mine: seat(".dis-qmine"), opp: seat(".dis-qopp"),
				seats: document.querySelectorAll(".dis-seat").length,
				piles: document.querySelectorAll(".dis-pile").length,
			};
		});
		check("the board draws four seats", board.seats === 4, JSON.stringify(board));
		check("the hand opposite you is face up, and is yours to play",
			!!board.mine && board.mine.visible && board.mine.faceUp === 12
			&& board.mine.backs === 0, JSON.stringify(board.mine));
		check("...and BOTH of the opponent's hands stay face down",
			!!board.opp && board.opp.backs === 12 && board.opp.faceUp === 0,
			JSON.stringify(board.opp));
		check("quartet deals no piles", board.piles === 0, JSON.stringify(board));

		// ── SORTED BY SUIT, AND FANNED ONLY AS MUCH AS THE ROW NEEDS ─────────
		// Card ids stopped being sortable when the deck grew: the base 32 are
		// `suit * 8 + rank`, but the wide deck's 5s and 6s sit at 32..39 and the
		// full deck's 2/3/4 at 40..51, appended so nothing older moved. Sorted
		// by id a quartet hand reads 7..A of every suit, THEN the 5s and 6s of
		// every suit, then the 2s/3s/4s -- four suits interleaved three times.
		const hand = await page.evaluate(() => {
			const seat = document.querySelector(".dis-qmine");
			const cards = [...seat.querySelectorAll(".dis-hand .dis-card")];
			const suits = cards.map((c) => c.querySelector(".dis-s")?.textContent?.trim() || "?");
			const r = cards.map((c) => c.getBoundingClientRect());
			const cw = r[0]?.width || 0;
			const steps = r.slice(0, -1).map((x, i) => r[i + 1].left - x.left);
			return { n: cards.length, suits,
				rows: new Set(r.map((x) => Math.round(x.top))).size,
				strip: steps.length && cw
					? Math.round(100 * (steps.reduce((a, b) => a + b, 0) / steps.length) / cw)
					: null };
		});
		// Each suit must appear as ONE contiguous run -- that is what "sorted by
		// suit" means, and it does not depend on which suit order is chosen.
		const runs = hand.suits.filter((s, i) => s !== hand.suits[i - 1]);
		check("a hand is sorted into suits", runs.length === new Set(runs).size,
			JSON.stringify(hand.suits));
		// A WRAPPED HAND IS THE FAILURE THIS GUARDS. It is invisible in a
		// screenshot -- it just looks like a fan -- and it doubles the seat's
		// height, which is what pushed a player's own hand off the screen.
		check("...and it lays out on a single row", hand.rows === 1,
			JSON.stringify({ rows: hand.rows, n: hand.n }));
		// ...without burying the cards to do it. The fan is solved from the row
		// space, so it is only ever as much overlap as the row actually needs.
		check("...without overlapping more than it has to",
			hand.strip !== null && hand.strip >= 35,
			`visible strip ${hand.strip}% of a card`);

		// Drive: auction -> the COMMIT phase -> double -> tricks. A phase with
		// no handler on the client is exactly where a room stalls forever, and
		// commit is the one phase no other mode has.
		let sawCommit = false;
		let widest = 0;
		const pipOrders = new Set();
		// SAMPLED DURING PLAY, not read at the end: the loop is long enough to
		// finish the round, and once the result panel is up `.dis-trickinfo` is
		// gone -- so reading it afterwards measures nothing and reports "".
		//
		// AND IT IS READ THROUGH `evaluate`, NOT `locator.textContent()`, which
		// is what hung this block for 24 minutes. A Playwright locator
		// AUTO-WAITS for its element: on a selector matching nothing,
		// `.textContent()` blocks for the full 30s default before rejecting,
		// and `.catch()` does not skip the wait -- it only swallows the result.
		// Inside a loop that runs long after the round has ended, that is 30s
		// an iteration. `evaluate` reads the DOM as it is right now and returns
		// immediately. (The `.count() > 0` guards below are safe for the same
		// reason -- `count()` does not auto-wait.)
		let trickLine = "";
		// A WALL-CLOCK BUDGET, not just an iteration count. Every click here
		// carries an actionability timeout, so a board that goes un-clickable
		// turns 160 iterations into 13 minutes -- which is exactly what a bad
		// CSS change did once, and it stalled the whole gate rather than
		// failing it. The loop is a best-effort drive; running out of budget
		// simply means the checks below report what they found.
		const deadline = Date.now() + 90_000;
		for (let i = 0; i < 160 && Date.now() < deadline; i++) {
			const snap = await page.evaluate(() => ({
				width: document.querySelectorAll(".dis-trick .dis-tp").length,
				info: document.querySelector(".dis-trickinfo")?.textContent || "",
				pips: [...document.querySelectorAll(".dis-seatname .dis-qorder")]
					.map((e) => e.textContent),
			}));
			widest = Math.max(widest, snap.width);
			trickLine = snap.info || trickLine;
			if (snap.pips && snap.pips.length === 4) pipOrders.add(snap.pips.join(""));
			if (await page.locator(".dis-bidgrid button").count() > 0) {
				await disBidCheaply(page);
				await sleep(200);
				continue;
			}
			// The commit panel: pick which hand leads, then confirm.
			const lead = page.getByRole("button", { name: /leads$/ }).first();
			if (await lead.count() > 0) {
				// THE SCREEN A PLAYER GOT STUCK ON. The two lead buttons were
				// `btn dis-annbtn` with no `btn-ghost`, and `.btn` is
				// `border: none` while `.dis-annbtn` only sets a border COLOUR
				// -- so they rendered as bare accent text that did not read as
				// buttons, with no selected state, while the go button stayed
				// disabled until one was picked. Three things have to hold.
				if (!sawCommit) {
					const pre = await page.evaluate(() => {
						const b = document.querySelector(".dis-auction .dis-annbtn");
						const go = document.querySelector(".dis-gobtn");
						return { ring: b ? getComputedStyle(b).boxShadow : "",
							goDisabled: !!go?.disabled, goText: go?.textContent.trim() || "" };
					});
					check("the lead buttons are painted, not bare text",
						/inset/.test(pre.ring), pre.ring.slice(0, 60));
					check("...and the go button says what is missing until one is picked",
						pre.goDisabled && /which hand leads/i.test(pre.goText),
						JSON.stringify(pre));
				}
				sawCommit = true;
				await lead.click({ timeout: 5_000 }).catch(() => {});
				// WAIT FOR THE CONDITION, don't sleep a guessed interval. A fixed 200ms
				// made this check intermittently red — observed selected:true with
				// goDisabled:true, i.e. the click had landed and the button had simply
				// not re-rendered yet — and an intermittently red gate here is a failed
				// Pages deploy, which is this harness's most expensive failure mode. The
				// cap is generous and the assertion below is unchanged, so a button that
				// genuinely never frees still fails.
				// TWO races, not one: the button's `disabled` clears on the next render, and
				// its fill arrives over a CSS transition — read at t=0 the background is
				// still the transparent it is animating FROM, which is exactly the value
				// this check treats as "not visibly selected".
				await until(page, () => {
					const go = document.querySelector(".dis-gobtn");
					const sel = document.querySelector(".dis-annbtn.sel");
					if (!sel || !go || go.disabled) return false;
					return getComputedStyle(sel).backgroundColor !== "rgba(0, 0, 0, 0)";
				}, 5_000);
				const post = await page.evaluate(() => {
					const sel = document.querySelector(".dis-annbtn.sel");
					const go = document.querySelector(".dis-gobtn");
					return { selected: !!sel,
						filled: sel ? getComputedStyle(sel).backgroundColor : "",
						goDisabled: !!go?.disabled,
						pips: [...document.querySelectorAll(".dis-seatname .dis-qorder")]
							.map((e) => e.textContent) };
				});
				check("picking a hand visibly selects it and frees the go button",
					post.selected && !post.goDisabled
					&& !/rgba\(0, 0, 0, 0\)/.test(post.filled), JSON.stringify(post));
				check("...and the four seats number themselves 1-4 in play order",
					post.pips.length === 4
					&& new Set(post.pips).size === 4
					&& post.pips.slice().sort().join("") === "1234", JSON.stringify(post.pips));
				await page.getByRole("button", { name: /^Play it as dealt$/ }).first()
					.click({ timeout: 5_000 }).catch(() => {});
				await sleep(200);
				continue;
			}
			const stand = page.getByRole("button", { name: /^Let it stand$/ }).first();
			if (await stand.count() > 0) {
				await stand.click({ timeout: 5_000 }).catch(() => {});
				await sleep(150);
				continue;
			}
			const card = page.locator(".dis-card.play").first();
			if (await card.count() > 0) {
				// CLICK THE VISIBLE STRIP, NOT THE CENTRE. A fanned hand lays each
				// card partly under the one before it -- that is the point of a
				// fan -- so with twelve cards the covered part reaches past the
				// middle and the centre belongs to the neighbour. Playwright
				// clicks centres by default and waits out its actionability
				// timeout when the point is covered, so the whole board read as
				// unclickable and no trick ever formed.
				// A human is unaffected: they tap what they can SEE, and the
				// visible strip is exactly the part that belongs to that card.
				const b = await card.boundingBox().catch(() => null);
				await card.click({
					timeout: 5_000,
					...(b ? { position: { x: Math.max(2, b.width - 6), y: b.height / 2 } } : {}),
				}).catch(() => {});
				await sleep(120);
				continue;
			}
			await sleep(150);
		}
		check("the commit phase is reachable and answerable in the browser", sawCommit);
		// THE NUMBERS HAVE TO FOLLOW THE LEAD. Whoever wins a trick leads the
		// next one, so the 1..4 on the seats re-orders as the round goes -- a
		// static numbering would be worse than none, since it would say the
		// wrong thing for most of the round.
		check("the play-order numbers re-order as the lead moves",
			pipOrders.size > 1,
			`orders seen: ${[...pipOrders].join("  ")}`);
		check("a trick in a quartet room is four cards wide", widest >= 4,
			`widest trick seen: ${widest}`);
		check("the trick line counts to the mode's own length -- nine, not thirteen",
			/of 9\b/.test(trickLine), JSON.stringify(trickLine));

		// THE FULL DECK REACHED THE BROWSER. Quartet deals all 52 -- the 2, 3
		// and 4 live at ids 40..51, appended so nothing older moved -- and a
		// client still decoding on the old block boundaries would draw them
		// with a blank glyph and an undefined rank rather than throwing. The
		// same failure the wide deck's 5s and 6s were guarded against.
		const ranks = await page.evaluate(() => {
			const seen = new Set();
			for (const el of document.querySelectorAll(".dis-card .dis-r"))
				seen.add(el.textContent.trim());
			return [...seen];
		});
		const ALL = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
		// COMMENTED OUT, deliberately, 2026-08-27 — do not restore as-is.
		//
		//   check("the full deck's low ranks render as themselves",
		//     ranks.some((r) => ["2", "3", "4"].includes(r)), JSON.stringify(ranks));
		//
		// It is a SAMPLED assertion over a random deal: it needs a 2, 3 or 4 to
		// land in the hands this seat can see, and when none does it fails while
		// nothing is wrong. Observed failing deals include
		// ["J","Q","5","A","6","K","8","9","7"] and
		// ["5","7","10","9","J","Q","K","6","A","8"]. It was failing often enough
		// to block three consecutive pushes, and a gate that cries wolf is worse
		// than no gate — it trains everyone to reach for --no-verify.
		//
		// Little is lost: the check below is what actually guards the thing this
		// pair exists for. A client still decoding on the OLD block boundaries
		// draws the 2/3/4 (ids 40..51) with a blank glyph and an undefined rank,
		// and `every(r => ALL.includes(r))` catches exactly that — on ANY deal,
		// not just one that happened to contain a low card. The commented line
		// only added "and we specifically saw one".
		//
		// TO RESTORE IT PROPERLY it needs a deterministic deal rather than a
		// bigger sample: seed the room, or assert against the DEALT hand from the
		// server payload instead of what this seat can see.
		check("no card renders with an unknown rank",
			ranks.length > 0 && ranks.every((r) => ALL.includes(r)), JSON.stringify(ranks));

		// A QUARTET ROOM HAS NO TALON -- its four out-cards are pure secrecy and
		// nobody is ever shown them. `shown` is an empty array, which is TRUTHY,
		// and that is how dummy mode once rendered a heading over nothing.
		check("no talon panel in a room that has no talon",
			await page.locator(".dis-p-talon").count() === 0);

		// ── ALL FOUR HANDS HAVE TO BE ON THE SCREEN ──────────────────────────
		// Four twelve-card hands is nearly twice the board any other mode draws,
		// and the first cut of this layout put a player's OWN hand below the
		// bottom of the viewport at every desktop size -- while every card on it
		// rendered perfectly, so nothing threw and no existing check noticed.
		// Geometry is the only thing that can see it.
		//
		// Measured at the desktop sizes, where a board is expected to fit whole.
		// Phones are allowed to scroll vertically (the three-seat board already
		// does) -- what is NOT allowed anywhere is a hand clipped inside its own
		// seat, a sideways scroll, or two sections drawn on top of each other.
		for (const [label, w, h] of [["desktop", 1440, 900], ["laptop", 1280, 800]]) {
			await page.setViewportSize({ width: w, height: h });
			await sleep(400);
			const geo = await page.evaluate(() => {
				const seats = [...document.querySelectorAll(".dis-seat")].map((el) => {
					const b = el.getBoundingClientRect();
					let escaped = 0;
					for (const c of el.querySelectorAll(".dis-card")) {
						const cr = c.getBoundingClientRect();
						if (cr.bottom > b.bottom + 1 || cr.top < b.top - 1) escaped++;
					}
					return { off: b.top < -1 || b.bottom > innerHeight + 1, escaped,
						h: Math.round(b.height) };
				});
				// AN OVERLAP NEEDS BOTH AXES. The railed desktop layout puts the
				// auction panel in its own COLUMN beside the seats, so a y-only
				// test reports every desktop board as broken.
				const kids = [...(document.querySelector(".dis-table")?.children || [])]
					.map((el) => el.getBoundingClientRect())
					.filter((b) => b.height > 0 && b.width > 0);
				let overlaps = 0;
				for (let i = 0; i < kids.length; i++)
					for (let j = i + 1; j < kids.length; j++) {
						const a = kids[i], b = kids[j];
						if (a.left < b.right - 1 && b.left < a.right - 1
							&& a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps++;
					}
				return { seats, overlaps,
					sideways: document.documentElement.scrollWidth
						> document.documentElement.clientWidth + 1 };
			});
			check(`all four hands are on screen at ${label} ${w}x${h}`,
				geo.seats.length === 4 && geo.seats.every((s) => !s.off),
				JSON.stringify(geo.seats));
			check(`...and no card escapes its seat at ${label}`,
				geo.seats.every((s) => s.escaped === 0), JSON.stringify(geo.seats));
			check(`...and no two sections overlap at ${label}`, geo.overlaps === 0,
				String(geo.overlaps));
			check(`...and the board does not scroll sideways at ${label}`,
				geo.sideways === false);
		}
		// On a phone the board may scroll, but nothing may be clipped or run off
		// the side -- the same bar the three-seat board is held to.
		//
		// MEASURED ON A LIVE BOARD, not on the round-end panel. By this point the
		// round is usually over, and quartet is the only mode whose hands still
		// HOLD cards then (every other plays all thirteen), so its seats are the
		// only ones with anything to spill when the result panel takes the
		// space -- a phone-only, round-end-only overflow of the reveal. Dealing
		// the next round puts a real board back, which is the state a player
		// spends the round in and the one worth guarding.
		const next = page.getByRole("button", { name: /next round/i }).first();
		if (await next.count() > 0) {
			await next.click({ timeout: 5_000 }).catch(() => {});
			await sleep(600);
		}
		await page.setViewportSize({ width: 390, height: 844 });
		await sleep(400);
		const ph = await page.evaluate(() => {
			let escaped = 0;
			const per = [];
			for (const seat of document.querySelectorAll(".dis-seat")) {
				const sr = seat.getBoundingClientRect();
				let n = 0;
				for (const c of seat.querySelectorAll(".dis-card")) {
					const cr = c.getBoundingClientRect();
					if (cr.bottom > sr.bottom + 1 || cr.top < sr.top - 1) n++;
				}
				escaped += n;
				per.push({ cls: (String(seat.className).match(/dis-q\w+/) || ["own"])[0],
					n, cards: seat.querySelectorAll(".dis-card").length,
					h: Math.round(sr.height) });
			}
			return { escaped, per,
				phase: (document.querySelector(".dis-table")?.className || "")
					.match(/ph-\w+/)?.[0] || "?",
				seats: document.querySelectorAll(".dis-seat").length,
				sideways: document.documentElement.scrollWidth
					> document.documentElement.clientWidth + 1 };
		});
		check("the four-hand board still draws four seats on a phone",
			ph.seats === 4, JSON.stringify(ph));
		check("...with no card escaping its seat", ph.escaped === 0, JSON.stringify(ph));
		check("...and no sideways scroll", ph.sideways === false, JSON.stringify(ph));

		check("no page errors creating and playing a quartet room",
			errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Dissonance's client-searched tiers, in the browser ──────────────────────
	// Dissonance is the only game here whose CARD PLAY runs client-side, and the
	// whole path is invisible to Python: a module Worker loads wasm-pack glue, the
	// glue fetches a .wasm from /wasm/, the page announces `client_ai_ready`, and
	// the server then ships one armed decision at a time. Every failure in that
	// chain degrades SILENTLY to the server's heuristic bot — a missing artifact,
	// a stale filename, a CSP, a worker that throws — so the room keeps playing
	// and keeps saying Hard. That is precisely why it needs a played game rather
	// than a mounted screen.
	//
	// IT DRIVES **EXPERT**, NOT HARD, AND THAT IS STRICTLY MORE COVERAGE FOR THE
	// SAME MINUTES. Expert is Hard plus a minimax over the auction, riding on the
	// same armed request and the same wasm export — so an Expert game exercises
	// every step Hard does AND the auction search on top. Hard's own difference
	// is the ABSENCE of the `auction.search` block, which is a Python assertion
	// (`test_expert.py`) and needs no browser. Playing both here would double the
	// most expensive block in the gate to re-check the cheap half.
	async function dissonanceHard(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "hard-harness", name: "Hard", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		const searches = [];
		// THE FORK, read off the socket itself. `ai_search` frames arriving but no
		// answers going back means the BROWSER failed; no frames at all means the
		// server never armed, which is a completely different fix. Guessing between
		// those two cost a whole session once.
		// DECISIONS, not frames. The armed request lives in ROOM STATE so every
		// re-broadcast re-ships it — that durability is the point of it, and it
		// means one decision can arrive on any number of frames. Counting frames
		// made `armed` a function of how many moves the harness happened to send
		// while the bot was thinking, so a perfectly-working tier that answered
		// all four of its decisions read as "answered 4 of 6 armed".
		const frames = { ai_search: 0, room_update: 0 };
		const decisions = new Set();
		const restated = new Set();   // any "needs/must take N pts" seen in play
		let ctSeen = false;           // ...and whether the contract box ever rendered
		const worthBad = new Set();   // any malformed "makes N · down for N"
		let worthSeen = false;        // ...and whether a priced row was ever shown
		//   (latched from the BID PICKER, which fills from local state on every
		//    bid, and from the standing-contract row sampled below)
		page.on("websocket", (ws) => {
			ws.on("framereceived", ({ payload }) => {
				if (typeof payload !== "string") return;
				if (payload.includes('"ai_search"')) {
					frames.ai_search++;
					for (const m of payload.matchAll(/"decision":\s*(\d+)/g)) decisions.add(m[1]);
				}
				if (payload.includes('"room_update"')) frames.room_update++;
			});
			ws.on("socketerror", (e) => errors.push(`ws: ${e}`));
		});
		page.on("pageerror", (e) => errors.push(String(e)));
		// Every console line, not just ours: a module worker that throws while
		// loading reports there and nowhere else.
		page.on("console", (m) => {
			const t = m.text();
			if (t.includes("client-AI")) searches.push(t);
			if (m.type() === "error" || /wasm|worker/i.test(t)) errors.push(`[${m.type()}] ${t.slice(0, 200)}`);
		});
		// Each answered decision logs its worker count, world count and latency —
		// the only visible sign the client tier ran, and the detail a failure here
		// needs (every other path is a silent return to the server bot).
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dis", { timeout: 25_000 }).catch(() => {});
		// Count the protocol rather than infer it from the board: a game that
		// plays out perfectly is exactly what the fallback looks like.
		await page.evaluate(() => {
			window.__acts = [];
			const send = WebSocket.prototype.send;
			WebSocket.prototype.send = function (d) {
				try { window.__acts.push(JSON.parse(d).action); } catch {}
				return send.call(this, d);
			};
		});

		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		for (const label of [/^VS AI$/, /^Expert$/, /^Classic$/]) {
			await page.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		const picked = await page.evaluate(() =>
			[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		check("Expert is offered in the create modal", picked.includes("Expert"), JSON.stringify(picked));
		await page.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dis-bidgrid, .dis-trick", { timeout: 25_000 }).catch(() => {});

		// STOPS ON EVIDENCE, not on a finished game. What this block is for is
		// whether the browser answers the bot's decisions at all; six answers say
		// that as well as thirteen do, and playing the rest costs minutes of gate
		// time on a box already running the beat block's game and four WASM
		// workers. One round-trip per iteration for the same reason — at three or
		// four the loop spent its budget on latency and timed out mid-auction,
		// which reads identically to "the client never answered".
		const deadline = Date.now() + 240_000;
		const answered = async () => (await page.evaluate(
			() => window.__acts.filter((a) => a === "ai_move").length));
		while (Date.now() < deadline) {
			if (await answered() >= 4) break;
			const st = await page.evaluate(() => {
				const q = (s) => document.querySelector(s);
				if (q(".dis-result")) return { over: true };
				// THE DOUBLE PROMPT, when the BOT declared and this seat is the
				// defender. Unhandled it is a 240s stall that reports as "no
				// tricks were ever played" — and it went unseen from the day
				// Double shipped, because disBidCheaply overtakes through five
				// denominations before passing, so the harness almost always
				// wins the auction and the prompt goes to the server bot
				// instead. The deals where the bot outlasts all five overtakes
				// are real, just rare: two CI runs in a row finally drew one.
				// Decline, which is also what the server tier always answers.
				const dbl = [...document.querySelectorAll(".dis-auction button")]
					.find((b) => /^Let it stand$/.test(b.textContent.trim()));
				if (dbl) { dbl.click(); return { acted: true }; }
				// Stand pat FIRST: the swap panel shares `.dis-auction`.
				const pat = [...document.querySelectorAll("button")]
					.find((b) => /stand pat/i.test(b.textContent));
				if (pat) { pat.click(); return { acted: true }; }
				// Bidding needs BOTH signals, because each one alone has a state where
				// it is absent. The level grid disappears once this seat has named
				// all five denominations (per-player no-repeat) and only Pass is
				// left; and at the OPENING bid there is no Pass at all — the opener
				// must bid — while Bid stays disabled until a level and a
				// denomination are picked. Keying on either one alone parks the
				// harness in the auction until its deadline, which then reports as
				// "no tricks were ever played".
				const bidding = q(".dis-auction") && (q(".dis-bidgrid button")
					|| [...document.querySelectorAll(".dis-auction button")]
						.some((b) => !b.disabled && /^(Pass|Bid )/.test(b.textContent.trim())));
				if (bidding) return { bidding: true };
				const seats = document.querySelectorAll(".dis-seat");
				const card = seats[seats.length - 1]?.querySelector(".dis-card.play");
				if (card) { card.click(); return { acted: true }; }
				return {};
			});
			if (st.over) break;
			// THE TARGET MUST NOT BE RESTATED IN WORDS (2026-08-17). In classic and
			// minor the target IS the level, already on screen as a glyph, so any
			// line spelling it out says the same number twice. It was removed from
			// the auction panel, reported still visible, and found in TWO more
			// places -- the in-play contract box ("needs 2 pts") and the phone chip
			// ("must take 2 pts"), different words each time. Grepping one phrasing
			// is what let it survive twice, so this reads RENDERED text.
			//
			// SAMPLED EVERY TURN rather than once: the contract box only exists
			// during play, so a single check placed in the auction block passed
			// against elements that were not on screen yet -- vacuous in exactly
			// the place the bug lived. `ctSeen` is the non-vacuity latch and is
			// asserted below, so "never looked" fails as loudly as "found one".
			const rest = await page.evaluate(() => {
				const sel = ".dis-ctsub, .dis-chip, .dis-ctline, .dis-contractrow";
				const els = [...document.querySelectorAll(sel)];
				const bad = [];
				for (const el of els) {
					const t = el.textContent.replace(/\s+/g, " ").trim();
					if (/needs \d+ pts?|must take \d+ pts?/.test(t)) bad.push(t);
				}
				const worth = [...document.querySelectorAll(".dis-worth")]
					.map((el) => el.textContent.replace(/\s+/g, " ").trim());
				return { n: els.length, box: !!document.querySelector(".dis-ctsub"), bad, worth };
			});
			if (rest.box) ctSeen = true;
			for (const b of rest.bad) restated.add(b);
			// WHAT A BID IS WORTH, latched. A standing bid exists at some point in
			// every game, so sampling the whole game reaches the populated form
			// without depending on which seat opened.
			for (const t of rest.worth) {
				if (!t) continue;
				worthSeen = true;
				if (!/makes \d+ · down for \d+/.test(t)) worthBad.add(t);
			}
			if (st.bidding) {
				const pick = await disBidCheaply(page);
				if (pick) {
					worthSeen = true;
					if (!/makes \d+ · down for \d+/.test(pick)) worthBad.add(pick);
				}
				await sleep(250);
				continue;
			}
			await sleep(st.acted ? 120 : 250);
		}

		const acts = await page.evaluate(() => {
			const c = {};
			for (const a of window.__acts) c[a] = (c[a] || 0) + 1;
			return c;
		});
		check("the page announces it can search", (acts.client_ai_ready || 0) >= 1,
			JSON.stringify(acts));
		// The bot has thirteen cards to play and a couple of them are forced (the
		// server applies those itself without asking), so most — not all — of the
		// game must come back from the browser. Zero means the wasm never loaded.
		// EVERY ARMED DECISION, not an absolute count. The server only arms a
		// decision where the bot has a CHOICE — under mandatory follow-suit most
		// plays are forced and it applies those itself — so how many arrive is a
		// property of the DEAL. An absolute threshold failed on deals with more
		// forced moves while the tier was working perfectly, and read exactly like
		// the tier being broken. One in flight is tolerated: the loop stops on its
		// own count, so the server can arm one more behind it.
		const armed = decisions.size;
		check("the browser answered every decision the server armed",
			armed >= 3 && (acts.ai_move || 0) >= armed - 1,
			`${armed} decisions on ${frames.ai_search} frames · ${JSON.stringify(acts)} `
			+ `searches=${JSON.stringify(searches.slice(0, 2))} err=${JSON.stringify(errors.slice(0, 2))}`);
		// Each answer logs its worker count, world count and latency. Zero of those
		// with a live `client_ai_ready` is the wasm loading and the SEARCH failing,
		// which is a different fix from the socket never being armed.
		check("...and the searches really ran in the browser", searches.length >= armed - 1,
			`${searches.length} logged of ${armed} armed: ${JSON.stringify(searches.slice(0, 2))}`);
		// THE AUCTION SPECIFICALLY. Card decisions and auction decisions come back
		// on the same socket action, so a tier whose auction search failed and
		// whose card search worked answers most of the game and reads green here.
		// That is the exact shape of the Grand outage: `options_from_json` rejected
		// denomination 6, every skat auction answered nothing, and the room played
		// out on the server bot still labelled Hard. Auction answers log an option
		// count; card answers log a card.
		check("...including the auction, which is the Expert tier's whole difference",
			searches.some((s) => /options in/.test(s)),
			`no auction answer among ${searches.length}: ${JSON.stringify(searches.slice(0, 3))}`);
		check("no page errors driving the client-side search",
			!errors.some((e) => !e.startsWith("[info]")), errors.slice(0, 3).join(" | ").slice(0, 300));
		// NON-VACUITY FIRST, because this is the check that was already vacuous
		// once: if the contract box never rendered, the scan above proved nothing
		// and must say so rather than pass.
		check("the in-play contract box actually rendered (else the scan below is empty)",
			ctSeen, "no .dis-ctsub was ever on screen during the game");
		check("...and the target is never restated in words beside its own glyph",
			restated.size === 0, JSON.stringify([...restated].slice(0, 3)));
		check("a bid is priced before it is made: makes N, down for N",
			worthSeen, "no .dis-worth row ever carried text during the game");
		check("...and every priced row it showed was well-formed",
			worthBad.size === 0, JSON.stringify([...worthBad].slice(0, 3)));
		await ctx.close();
	}

	// ── Dissonance's completed-trick beat ───────────────────────────────────────
	// A finished trick stays face up for TRICK_HOLD_MS before it moves to the
	// side panel. It is a pure timing behaviour, so nothing in Python can see it
	// and a mounted screen says nothing about it — and it shipped broken in two
	// ways that only a played-out game exposes. (1) The hold stopped at phase
	// `play`, so the trick that ENDS the game (the thirteenth, or the +2 that
	// breaks a Null) was swapped for the result panel in the same frame: held
	// 0ms, every other trick 700ms. (2) A player who answered inside the hold
	// was leading the next trick behind a screen still showing the last one, so
	// two finished tricks ran together with an 18ms frame between them.
	// This plays a whole classic game AT FULL TILT — clicking the instant a card
	// offers itself, which is the case that broke — and measures every dwell.
	async function dissonanceBeat(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "hold-harness", name: "Hold", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/dissonance`, { waitUntil: "networkidle" });
		await page.waitForSelector(".dis", { timeout: 25_000 }).catch(() => {});
		// Sample the middle of the board every frame and record each change. A
		// polling loop from Node cannot see a state that lasts one frame, which
		// is precisely the size of the bug.
		await page.evaluate(() => {
			window.__hold = [];
			// The RESULT PANEL is sampled on the same frames, because the end of
			// the game is where these two interact. `heldTrick` is set from an
			// effect, and React paints BEFORE effects run — so on the message
			// that ends the game the panel can paint for one frame before the
			// hold takes it back down, giving result -> last trick -> result.
			// One frame is invisible to any polling loop and easy to miss by
			// eye, which is exactly why it is recorded rather than watched.
			window.__resultFlips = [];
			// WHICH PANEL is on screen, every frame. A user reported a one-frame
			// blink of *something* just before the result — they explicitly were
			// NOT sure what, so this must not be built around a guess. It records
			// the known markers AND a short text digest of the centre panel, so
			// an intruder nobody predicted still identifies itself in the failure
			// message rather than only registering as "not what we expected".
			window.__panels = [];
			let lastPanel = null;
			const panelNow = () => {
				const has = (s) => !!document.querySelector(s);
				const marks = [
					has(".dis-valgrid") || has(".dis-bidgrid") ? "AUCTION" : "",
					has(".dis-denoms") ? "denoms" : "",
					has(".dis-clears") ? "clears" : "",
					has(".dis-reveal") ? "reveal" : "",
					has(".dis-result") ? "RESULT" : "",
					has(".dis-trick") ? "board" : "",
				].filter(Boolean).join("+");
				// The digest is what makes this open-ended: whatever paints, its
				// words come back with it.
				const mid = document.querySelector(".dis-mid, .dis-centre, .dis-table");
				const txt = (mid?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60);
				return `${marks || "(no marker)"} :: ${txt}`;
			};
			let last = null, lastRes = null;
			const tick = () => {
				const pnl = panelNow();
				if (pnl !== lastPanel) { window.__panels.push([Math.round(performance.now()), pnl]); lastPanel = pnl; }
				const t = document.querySelector(".dis-trick");
				const s = !t ? "-" : [...t.querySelectorAll(".dis-tp .dis-card")]
					.map((e) => e.textContent.trim()).join(" ") || "(none)";
				if (s !== last) { window.__hold.push([performance.now(), s]); last = s; }
				const res = !!document.querySelector(".dis-result");
				if (res !== lastRes) { window.__resultFlips.push([performance.now(), res]); lastRes = res; }
				requestAnimationFrame(tick);
			};
			requestAnimationFrame(tick);
		});

		await page.getByRole("button", { name: /new game|create/i }).first()
			.click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
		for (const label of [/^VS AI$/, /^Normal$/, /^Classic$/]) {
			await page.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		await page.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".dis-bidgrid, .dis-trick", { timeout: 25_000 }).catch(() => {});

		// THE AUCTION, MEASURED BEFORE A CARD IS PLAYED. Three claims, and they
		// are only checkable here — the panel is gone by trick 1.
		//
		//  * The ladder tops out at the mode's cap, in two rows of five. Classic
		//    ran 1..12 until 2026-08-10 (its parity ceiling); 11 and 12 were
		//    reachable but never bid, and twelve buttons is not a shape.
		//  * The panel sits BESIDE the cards on a desktop. It used to be a row
		//    between the two seats.
		//  * ...which is what lets the cards keep the PLAY size through every
		//    phase. They used to shrink for the auction and again for the
		//    round-end report, because the card budget was paying for the panel.
		const auc = await page.evaluate(() => {
			const x = (s) => { const e = document.querySelector(s); if (!e) return null;
				const r = e.getBoundingClientRect();
				return { x: Math.round(r.x), w: Math.round(r.width) }; };
			const grid = document.querySelector(".dis-bidgrid");
			const btn = grid ? grid.querySelector("button") : null;
			const card = document.querySelector(".dis-seat .dis-card");
			return {
				levels: [...document.querySelectorAll(".dis-bidgrid button")].map((b) => +b.textContent),
				btnW: btn ? btn.getBoundingClientRect().width : 0,
				gridW: grid ? grid.getBoundingClientRect().width : 0,
				gap: grid ? parseFloat(getComputedStyle(grid).columnGap) || 0 : 0,
				seat: x(".dis-seat"), panel: x(".dis-auction"),
				cardW: card ? Math.round(card.getBoundingClientRect().width) : 0,
			};
		});
		// WHO OPENS IS RANDOM (seats shuffle at the deal), so the full 1..10 is
		// only on screen when this seat opens; either way nothing above the cap
		// may be offered, and the keys are the same width in both cases.
		check("no bid above the mode's cap is ever offered",
			auc.levels.length > 0 && Math.max(...auc.levels) <= 10, JSON.stringify(auc));

		// THE STANDING-BID LINE (2026-08-17). It is ONE row -- "Ada 5♦" -- where it
		// used to be a contract row plus a separate "Ada needs 5 pts" beneath, and
		// the pre-bid state renders NOTHING where it used to say "no bid yet".
		//
		// OBSERVES ONLY. The first version of this bid, to force the standing
		// state -- which consumed this block's own turn and left the three level-pad
		// checks below reading an auction that had moved on. Never spend shared
		// state in a block that measures it.
		//
		// WHICH SEAT OPENS IS RANDOM, so both states are asserted rather than one
		// being waited for: empty when nothing stands, holder-plus-contract when
		// something does. The RESERVE is checked unconditionally off the computed
		// style, because that is the property that actually matters and it does not
		// depend on who opened -- an empty row now takes its height from
		// `min-height` alone, and if that is ever lost the row collapses to 0 and
		// the first bid of every auction shoves the keypad down. Which is exactly
		// the bug the old placeholders were shortened to avoid.
		const row = await page.evaluate(() => {
			const el = document.querySelector(".dis-contractrow");
			if (!el) return null;
			const c = el.querySelector(".dis-contract");
			return {
				reserve: parseFloat(getComputedStyle(el).minHeight) || 0,
				h: Math.round(el.getBoundingClientRect().height),
				text: el.textContent.trim(),
				holder: c?.querySelector(".dis-holder")?.textContent.trim() || "",
				chHeight: c ? Math.round(c.getBoundingClientRect().height) : 0,
				standing: !!document.querySelector(".dis-standing"),
			};
		});
		check("the contract row reserves its height in CSS, not with placeholder text",
			!!row && row.reserve >= 32, JSON.stringify(row));
		check(row?.text
			? "a standing bid is ONE line, holder and contract together"
			: "...and nothing at all is drawn before a bid stands",
			!!row && (row.text
				? (!!row.holder && row.chHeight <= row.reserve + 6)
				: row.h >= 32),
			JSON.stringify(row));
		check("...with no placeholder and no separate 'needs N pts' row",
			!!row && !/no bid yet|no contract yet|needs/.test(row.text) && !row.standing,
			JSON.stringify(row));

		// WHAT A BID IS WORTH, beside the keys (2026-08-17). Two rows: the
		// STANDING contract's price and the SELECTED bid's. The NUMBERS are
		// pinned against the engine in `tests/test_bid_worth.py`, which is where
		// arithmetic belongs; what can only fail here is the row rendering empty
		// or losing the height reserve it shares with the contract row above.
		const worth = await page.evaluate(() => {
			const rows = [...document.querySelectorAll(".dis-worth")];
			return {
				n: rows.length,
				reserved: rows.every((r) => r.getBoundingClientRect().height >= 12),
				texts: rows.map((r) => r.textContent.replace(/\s+/g, " ").trim()),
			};
		});
		// BOTH ROWS EXIST AND RESERVE THEIR HEIGHT. Whether they have TEXT here
		// depends on which seat opened, which is random -- so the populated form
		// is asserted in `dissonanceHard`, latched over a whole game, rather than
		// gambled on at one instant. (This check first demanded the text and CI
		// duly opened from the other seat, failing the render gate and skipping
		// the deploy: the feature was fine, the check was not.)
		check("the auction reserves a row for what a contract is worth",
			worth.n >= 1 && worth.reserved, JSON.stringify(worth));
		check("...and whatever it shows is a price, never a stray label",
			worth.texts.every((t) => t === "" || /makes \d+ · down for \d+/.test(t)),
			JSON.stringify(worth));

		// The ladder is centered FLEX at fifth-widths (2026-08-12), not a
		// 5-column grid — a responder's short legal set centers instead of
		// hugging the left edge beside dead tracks. Fifth-width keys are what
		// still make a full 1..10 ladder land as two rows of five.
		check("...and the keys are fifth-width, so a full ladder is two rows of five",
			auc.btnW > 0 && Math.abs(auc.btnW - (auc.gridW - 4 * auc.gap) / 5) <= 1.5,
			JSON.stringify(auc));
		check("the auction panel sits beside the cards, not between the seats",
			!!auc.panel && !!auc.seat && auc.panel.x >= auc.seat.x + auc.seat.w - 1,
			JSON.stringify(auc));

		// THE LEVEL PAD IS THE WHOLE LADDER AND IT DOES NOT MOVE (2026-08-14).
		// It used to render only the LEGAL levels, so the pad shrank and
		// re-flowed after every bid and the key under your thumb became a
		// different number — a misbid waiting to happen on a phone. Now every
		// rung is drawn and the illegal ones are disabled, which is how the
		// denominations were always drawn. Asserted as three facts: the pad is
		// the full ladder, an unreachable rung is present-but-disabled, and the
		// geometry is IDENTICAL across a bid landing (the property a shrinking
		// pad broke, and the only one a user actually feels).
		const padOf = () => page.evaluate(() => {
			const b = [...document.querySelectorAll(".dis-bidgrid button")];
			const one = b[0]?.getBoundingClientRect();
			// The panel's own children, so a failure NAMES the element that grew
			// rather than leaving a bare pixel delta to bisect by hand.
			const panel = document.querySelector(".dis-auction");
			const above = panel ? [...panel.children].map((c) =>
				`${c.className.split(" ")[0] || c.tagName}:${Math.round(c.getBoundingClientRect().height)}`
			).join(" ") : "";
			return {
				n: b.length,
				disabled: b.filter((x) => x.disabled).length,
				labels: b.map((x) => +x.textContent).join(","),
				x: one ? Math.round(one.x) : -1, y: one ? Math.round(one.y) : -1,
				above,
			};
		});
		const padBefore = await padOf();
		check("the level pad draws the whole 1..10 ladder, not just the legal set",
			padBefore.n === 10 && padBefore.labels === "1,2,3,4,5,6,7,8,9,10",
			JSON.stringify(padBefore));
		// The pad is SAMPLED THROUGH THE WHOLE GAME below rather than across one
		// driven bid, and the first version of this check is why: it bid once and
		// re-measured, but a single bid can END the auction (the bot passes), so
		// it read an empty pad and failed on a board that was perfectly correct.
		// The play loop already walks every auction state this room reaches --
		// several standing bids, both seats, and the next round's opening -- so
		// the samples come from there and the assertions run after it.
		// ...and NON-VACUITY, DETERMINISTICALLY. Asking the real auction to
		// visit two different legal sets is up to the deal: one run sampled
		// [0,0,1,2] and the next [4,4], so the same code failed on a board that
		// was correct — a flaky gate is worse than none. The claim is that the
		// pad's geometry does not depend on WHICH rungs are legal, so toggle
		// the disabled set in the DOM and re-measure: under the old
		// render-only-the-legal-set pad this was impossible to even ask, and
		// under this one it must be a no-op by construction.
		const pressure = await page.evaluate(() => {
			const g = document.querySelector(".dis-bidgrid");
			if (!g) return null;
			const btns = [...g.querySelectorAll("button")];
			if (!btns.length) return null;
			const geo = () => {
				const r = g.getBoundingClientRect(), b = btns[0].getBoundingClientRect();
				return [btns.length, Math.round(r.width), Math.round(r.height),
					Math.round(b.x), Math.round(b.y)].join("/");
			};
			const was = btns.map((b) => b.disabled);
			const before = geo();
			btns.forEach((b, i) => { b.disabled = i % 2 === 0; });
			const half = geo();
			btns.forEach((b) => { b.disabled = true; });
			const none = geo();
			btns.forEach((b, i) => { b.disabled = was[i]; });
			return { before, half, none, restored: geo() };
		});
		check("...and changing which rungs are legal cannot move the pad",
			!!pressure && pressure.before === pressure.half
			&& pressure.before === pressure.none
			&& pressure.before === pressure.restored,
			JSON.stringify(pressure));
		const padSamples = [padBefore];

		// EVERY BUTTON ON THIS BOARD IS VISIBLE, and `btn-ghost` was the one
		// variant that was not: the shared kit paints it `transparent` with
		// `--text-dim` text, which on the dark green board is an almost
		// invisible rectangle — the same failure as the nine bare `.btn`s this
		// file's CSS carries a note about, one variant along. Pass is the one
		// a player meets most, so it is the one gated. Nothing but a browser
		// can see this: the button renders, works, and reads fine in the DOM.
		// ASSERTED ON THE CLASS, VIA A PROBE, not on whichever button happens to
		// be on screen: at the opening there is no Pass at all (the opener must
		// bid), so the first version of this check read `null` and failed on a
		// perfectly good board. A probe mounted inside `.dis` measures the paint
		// the class actually applies, which is the thing that was broken.
		const ghost = await page.evaluate(() => {
			const host = document.querySelector(".dis");
			if (!host) return null;
			const b = document.createElement("button");
			b.className = "btn btn-ghost";
			b.textContent = "Pass";
			b.style.position = "absolute"; b.style.left = "-9999px";
			host.appendChild(b);
			const s = getComputedStyle(b);
			const alpha = (c) => {
				const m = c.match(/rgba?\(([^)]+)\)/);
				if (!m) return 1;
				const p = m[1].split(",").map((v) => parseFloat(v));
				return p.length > 3 ? p[3] : 1;
			};
			const out = {
				text: b.textContent.trim().slice(0, 12),
				bg: s.backgroundImage !== "none" ? "gradient" : s.backgroundColor,
				bgAlpha: s.backgroundImage !== "none" ? 1 : alpha(s.backgroundColor),
				borderAlpha: alpha(s.borderTopColor),
			};
			b.remove();
			return out;
		});
		check("a secondary button (Pass) is actually painted, not transparent",
			!!ghost && (ghost.bgAlpha > 0.05 || ghost.borderAlpha > 0.18),
			JSON.stringify(ghost));

		// THE RAIL CLASS AND THE RENDERED MIDDLE MUST AGREE. The desktop grid,
		// the card budget and the reserve all key on `dis-rail-*`, which the
		// renderer sets from the same conditions the middle's ternary branches
		// on -- two expressions of one fact, and the layout silently uses the
		// WRONG budget if they ever part (the class replaced `:has()`, which
		// could not drift because it read the DOM directly). Checked here and
		// again after the game is played out, so both the auction and the
		// play/report shapes are covered.
		const railAgrees = () => page.evaluate(() => {
			const t = document.querySelector(".dis-table");
			if (!t) return { err: "no table" };
			const cls = [...t.classList].find((c) => c.startsWith("dis-rail-"));
			const child = t.querySelector(":scope > .dis-result") ? "dis-rail-result"
				: t.querySelector(":scope > .dis-auction") ? "dis-rail-auction"
					: t.querySelector(":scope > .dis-playside") ? "dis-rail-play" : "none";
			return { cls, child, ok: cls === child };
		});
		const railAuc = await railAgrees();
		check("the table's rail class matches the middle it is rendering",
			railAuc.ok, JSON.stringify(railAuc));

		// A GAME SURFACE, NOT A DOCUMENT: no text selection anywhere on the
		// board, and no native tooltip on a card (hovering your own hand used
		// to pop "King of Spades" over the table a beat later). Inputs are the
		// deliberate exception — the lobby's room-code field is typed and
		// pasted into, and a field you cannot select in is broken.
		const sel = await page.evaluate(() => {
			// A FACE-UP card: the first `.dis-card` on the board is the
			// opponent's back, which carries no name by design.
			const card = document.querySelector(".dis-seat:last-of-type .dis-hand .dis-card")
				|| document.querySelector(".dis-card");
			const st = (e) => e ? getComputedStyle(e).userSelect : null;
			const inp = document.querySelector(".dis input");
			return { card: st(card), title: card?.getAttribute("title") ?? null,
				aria: !!card?.getAttribute("aria-label"), input: inp ? st(inp) : "n/a" };
		});
		check("nothing on the board is selectable, and a card has no tooltip",
			sel.card === "none" && sel.title === null && sel.aria, JSON.stringify(sel));

		// NO FACE-UP CARD IS DIMMED, in any form. Cards render identically whether
		// or not they are playable; legality lives in the `play` affordance and is
		// enforced server-side. Two earlier versions of this failed differently:
		// `opacity` let a pile's buried card show through its top (they sit
		// offset, so the two read as one smeared card), and the
		// `filter: brightness()` that replaced it kept the real problem, a hand
		// that read as two kinds of card. This guards the ABSENCE of all three.
		// Pure CSS, so nothing in Python sees it.
		//
		// SAMPLED DURING PLAY, not after. By the end of a round the piles are
		// empty and render placeholders -- no buried card behind anything, and
		// nothing dimmed -- so the check read as vacuous exactly when the round
		// ran to thirteen tricks and as fine when it settled early. It passed
		// locally on an early-settling deal and went red in CI on a complete one.
		let piles = null;
		const samplePiles = async () => {
			if (piles) return;
			const p = await page.evaluate(() => {
				const tops = [...document.querySelectorAll(".dis-piles .dis-pilewrap")]
					.map((w) => [...w.children].find((c) => c.classList.contains("dis-card")))
					.filter(Boolean);
				return {
					n: tops.length,
					dimmed: tops.filter((t) => t.classList.contains("dim")).length,
					seeThrough: tops.filter((t) => +getComputedStyle(t).opacity < 1).length,
					greyed: tops.filter((t) => getComputedStyle(t).filter !== "none").length,
					buried: document.querySelectorAll(".dis-buried").length,
				};
			});
			// Accept the first frame with a covered pile on the table. It must NOT
			// also require a dimmed top the way it used to: nothing is dimmed any
			// more, so that condition would never accept a sample and the check
			// would fail as "never caught a turn" rather than passing.
			if (p.n >= 3 && p.buried > 0) piles = p;
		};

		// ONE ROUND-TRIP PER ITERATION for the common case. This block runs right
		// after the Hard one, which leaves four WASM workers' worth of heat on the
		// box, and at three or four round-trips a turn the loop was spending its
		// budget on latency rather than on the game — it timed out during the
		// auction in CI while passing four times in a row locally. Reading the
		// state and playing a card in the same evaluate collapses that; the cards
		// are plain divs with an onClick, so there is no actionability to lose.
		const beatDeadline = Date.now() + 240_000;
		while (Date.now() < beatDeadline) {
			await samplePiles();
			const st = await page.evaluate(() => {
				const q = (s) => document.querySelector(s);
				if (q(".dis-result")) return { over: true };
				// THE DOUBLE PROMPT, when the BOT declared and this seat is the
				// defender. Unhandled it is a 240s stall that reports as "no
				// tricks were ever played" — and it went unseen from the day
				// Double shipped, because disBidCheaply overtakes through five
				// denominations before passing, so the harness almost always
				// wins the auction and the prompt goes to the server bot
				// instead. The deals where the bot outlasts all five overtakes
				// are real, just rare: two CI runs in a row finally drew one.
				// Decline, which is also what the server tier always answers.
				const dbl = [...document.querySelectorAll(".dis-auction button")]
					.find((b) => /^Let it stand$/.test(b.textContent.trim()));
				if (dbl) { dbl.click(); return { acted: true }; }
				// Stand pat FIRST: the swap panel shares `.dis-auction`.
				const pat = [...document.querySelectorAll("button")]
					.find((b) => /stand pat/i.test(b.textContent));
				if (pat) { pat.click(); return { acted: true }; }
				// Bidding needs BOTH signals, because each one alone has a state where
				// it is absent. The level grid disappears once this seat has named
				// all five denominations (per-player no-repeat) and only Pass is
				// left; and at the OPENING bid there is no Pass at all — the opener
				// must bid — while Bid stays disabled until a level and a
				// denomination are picked. Keying on either one alone parks the
				// harness in the auction until its deadline, which then reports as
				// "no tricks were ever played".
				const bidding = q(".dis-auction") && (q(".dis-bidgrid button")
					|| [...document.querySelectorAll(".dis-auction button")]
						.some((b) => !b.disabled && /^(Pass|Bid )/.test(b.textContent.trim())));
				if (bidding) return { bidding: true };
				const seats = document.querySelectorAll(".dis-seat");
				const card = seats[seats.length - 1]?.querySelector(".dis-card.play");
				if (card) { card.click(); return { acted: true }; }
				return {};
			});
			if (st.over) break;
			if (st.bidding) {
				// One sample per auction state the game passes through, so the
				// pad's invariants are asserted over real standing bids rather
				// than over one contrived one.
				padSamples.push(await padOf());
				await disBidCheaply(page); await sleep(250); continue;
			}
			await sleep(st.acted ? 90 : 200);
		}
		// THE PAD IS THE SAME TEN KEYS IN THE SAME PLACE, whatever is legal.
		const pads = padSamples.filter((p) => p.n > 0);
		check("...every auction state draws all ten rungs, in the same place",
			pads.length >= 2 && pads.every((p) => p.n === 10
				&& p.labels === "1,2,3,4,5,6,7,8,9,10"
				&& p.x === pads[0].x && p.y === pads[0].y),
			JSON.stringify(pads.slice(0, 4)));

		check("the piles were sampled with cards still on the table",
			!!piles && piles.buried > 0, JSON.stringify(piles));
		check("no face-up card is dimmed, greyed or see-through",
			!!piles && piles.dimmed === 0 && piles.seeThrough === 0
			&& piles.greyed === 0, JSON.stringify(piles));

		const trace = await page.evaluate(() => window.__hold);
		// Dwell of state i = when state i+1 replaced it. The last entry has no
		// successor, so it is dropped rather than guessed at.
		const dwells = trace.slice(0, -1).map((e, i) => ({
			cards: e[1], ms: Math.round(trace[i + 1][0] - e[0]) }))
			.filter((d) => d.cards.split(" ").length === 2);
		const shortest = dwells.reduce((a, b) => (b.ms < a.ms ? b : a), { ms: Infinity });
		// A failure here used to say only "0 finished tricks", which is the symptom
		// of three different causes (a stuck auction, a timed-out loop, a trick
		// area that stopped rendering) and told them apart not at all. Say where
		// it actually got to, so the next red run is one read rather than one
		// six-minute experiment.
		const stuck = await page.evaluate(() => ({
			mid: document.querySelector(".dis-auction, .dis-trick, .dis-result")?.className,
			turnbar: document.querySelector(".dis-turnbar")?.textContent,
			buttons: [...document.querySelectorAll(".dis-auction button")]
				.map((b) => `${b.textContent.trim().slice(0, 12)}${b.disabled ? "(off)" : ""}`).slice(0, 10),
			playable: document.querySelectorAll(".dis-card.play").length,
		}));
		check("a whole game was played out", dwells.length >= 8,
			`${dwells.length} finished tricks, ${trace.length} frames — ${JSON.stringify(stuck)}`);
		const railEnd = await railAgrees();
		check("...and the rail class still matches the middle at the report",
			railEnd.ok, JSON.stringify(railEnd));
		// THE CARDS ARE THE SAME SIZE AT THE END AS AT THE AUCTION. This is the
		// point of moving the panels into a rail: the board no longer redraws at
		// a different scale for the auction and again for the report, which it
		// did for as long as the middle column had to pay for them.
		const endW = await page.evaluate(() => {
			const c = document.querySelector(".dis-seat .dis-card");
			const p = document.querySelector(".dis-result");
			return { cardW: c ? Math.round(c.getBoundingClientRect().width) : 0,
				result: !!p, resultX: p ? Math.round(p.getBoundingClientRect().x) : null };
		});
		check("the cards never change size between the auction, play and the report",
			endW.cardW > 0 && endW.cardW === auc.cardW,
			JSON.stringify({ auction: auc.cardW, ...endW }));
		// The shortest dwell rides in the NAME, so it prints on success too. This is
		// the one assertion in the file whose margin can be eroded by nothing but
		// load — it wants 550ms out of a 700ms hold — and a gate that shows its
		// margin only once it has already failed gives no warning that it is drifting.
		check(`every finished trick is held, even at full tilt (shortest ${shortest.ms}ms of 700)`,
			dwells.length >= 8 && shortest.ms >= 550,
			`shortest ${JSON.stringify(shortest)} of ${JSON.stringify(dwells.map((d) => d.ms))}`);
		// The game-ending trick is the one this most easily loses: it arrives in
		// the same message as the result. Its dwell is the LAST two-card entry.
		check("the trick that ends the game is held too, not replaced by the result",
			dwells.length >= 8 && dwells[dwells.length - 1].ms >= 550,
			JSON.stringify(dwells[dwells.length - 1] || null));
		// ...AND THE RESULT PANEL MUST NOT FLASH BEFORE THAT HOLD. The check
		// above measures the hold once it starts, so it passes just as happily
		// when the panel painted a frame earlier and was yanked back down. That
		// is a visible blink of the final score before the last trick — the
		// user-reported "flash of something as the game ends". The panel should
		// appear exactly ONCE, so more than one on-flip is the bug.
		const flips = await page.evaluate(() => window.__resultFlips || []);
		const appearances = flips.filter(([, shown]) => shown).length;
		check("the result panel does not flash before the final trick's hold",
			appearances <= 1, `result panel appeared ${appearances}x: ${JSON.stringify(flips)}`);
		// WHAT PRECEDES THE RESULT MUST BE THE BOARD — whatever the intruder is.
		// Reported: "right before the contract made screen, a blink of something
		// for maybe one frame", with the reporter explicitly unsure what it was.
		// So this asserts the transition rather than the suspect: the last thing
		// on screen before the result should be the held final trick, and any
		// other state getting a frame in between fails and PRINTS ITSELF. The
		// flip-counter above cannot see this at all — the result still appears
		// exactly once either way. Not reproduced in classic vs bot over two
		// runs, so this is the net rather than a regression guard.
		const panels = await page.evaluate(() => window.__panels || []);
		const iRes = panels.findIndex(([, p]) => p.includes("RESULT"));
		const before = iRes > 0 ? panels[iRes - 1][1] : null;
		check("nothing gets a frame between the last trick and the result",
			iRes <= 0 || before.includes("board"),
			`the frame before RESULT showed: ${before} | tail=${JSON.stringify(panels.slice(-6))}`);
		// ── the round that just ended is one round of a MATCH ────────────────
		// A game is played to 100, so the result panel carries the running
		// standing and deals again rather than sending anyone to the lobby. One
		// round CAN settle it outright — a classic level-12 contract pays 144 —
		// so this must not assume there is a next round to play.
		const after = await page.evaluate(() => {
			const t = (s) => document.querySelector(s)?.textContent || "";
			return {
				match: t(".dis-match"),
				panel: t(".dis-p-match"),
				// The side panel's scorecard: one line per round banked. It is
				// fed by `match.rounds` off the wire, so a panel that renders
				// nothing is exactly what a field that never shipped looks like.
				card: [...document.querySelectorAll(".dis-mcard .dis-mrow")]
					.filter((r) => !r.classList.contains("dis-mrow-hd"))
					.map((r) => [...r.children].map((c) => c.textContent.trim())),
				next: [...document.querySelectorAll(".dis-result button")]
					.some((b) => /next round/i.test(b.textContent)),
				lobby: [...document.querySelectorAll(".dis-result button")]
					.some((b) => /back to lobby/i.test(b.textContent)),
			};
		});
		check("the result panel shows the match standing, not just the round",
			/Match to \d+/.test(after.match), JSON.stringify(after).slice(0, 200));
		// One round played, so one line — and it carries the four things the
		// running total on its own cannot say.
		check("the match panel lists the round that was just scored",
			after.card.length === 1 && after.card[0][0] === "1"
			&& after.card[0][1].length > 0
			// The declarer's trick points against their target. NEGATIVE is
			// ordinary — seven of thirteen tricks cost a point.
			&& /^-?\d+\/\d+$|^—$/.test(after.card[0][2])
			&& /^[+−]\d+$/.test(after.card[0][3]),
			JSON.stringify(after.card));
		check("a match still running offers the next round; a decided one does not",
			after.next !== /wins the match|Match drawn/.test(after.match) && after.lobby,
			JSON.stringify(after).slice(0, 200));
		if (after.next) {
			const before = await page.evaluate(() =>
				document.querySelector(".dis-p-match")?.textContent || "");
			await page.evaluate(() => [...document.querySelectorAll(".dis-result button")]
				.find((b) => /next round/i.test(b.textContent))?.click());
			let dealt = null;
			const dealBy = Date.now() + 15_000;
			while (!dealt && Date.now() < dealBy) {
				dealt = await page.evaluate(() => {
					const q = (s) => document.querySelector(s);
					if (q(".dis-result")) return null;      // still on the old round
					return q(".dis-auction")
						? { round: q(".dis-p-match")?.textContent || "" } : null;
				});
				if (!dealt) await sleep(250);
			}
			check("Next round deals again instead of ending the game", !!dealt,
				JSON.stringify(dealt));
			check("...and the match total carries across the deal",
				!!dealt && /Round 2/.test(dealt.round) && dealt.round !== before,
				`${before} -> ${dealt?.round}`);
			// The scorecard is the MATCH's, not the round's, so round 1's line
			// is still there while round 2 is being bid.
			const kept = await page.evaluate(() =>
				document.querySelectorAll(".dis-mcard .dis-mrow").length);
			check("...and round 1 stays on the scorecard through the next deal",
				kept === 2, `header + rows = ${kept}`);
		}

		// ── the DOUBLE-DUMMY figure ──────────────────────────────────────────
		// It lives in the ROUND'S STORY now (2026-08-13), not as a fifth column
		// on the scorecard — it prices one deal in one contract, so it belongs
		// where those hands are on screen. What is checked has not changed, and
		// both halves fail silently outside a browser: the figure RESOLVES (the
		// whole worker -> wasm -> odd_review chain degrades to a "Solving…" that
		// never fills, which is exactly what a missing export or a mis-shaped
		// deal looks like — and this room is vs the NORMAL bot, so the wasm
		// loads COLD here; the review must not lean on Hard's pool being
		// armed), and the answer is STABLE, since an exact solve must not move
		// across re-renders.
		{
			await page.evaluate(() => {
				const row = [...document.querySelectorAll(".dis-mcard .dis-mrow-open")][0];
				row?.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
			});
			const ddText = () => page.evaluate(() => {
				const secs = [...document.querySelectorAll(".cm-panel .dis-story-sec")];
				const sec = secs.find((x) => /Double dummy/i.test(x.querySelector(".dis-story-hd")?.textContent || ""));
				const b = sec?.querySelector(".dis-story-ctline b");
				const t = b?.textContent.trim();
				return t && /^[+\u2212-]\d+$/.test(t) ? t : null;
			});
			const solved = await page.waitForFunction(() => {
				const secs = [...document.querySelectorAll(".cm-panel .dis-story-sec")];
				const sec = secs.find((x) => /Double dummy/i.test(x.querySelector(".dis-story-hd")?.textContent || ""));
				const b = sec?.querySelector(".dis-story-ctline b");
				const t = b?.textContent.trim();
				return t && /^[+\u2212-]\d+$/.test(t) ? t : null;
			}, null, { timeout: 25_000 }).then((h) => h.jsonValue()).catch(() => null);
			check("the round story's double-dummy figure resolves to a signed score",
				!!solved, String(solved));
			const cells = await page.evaluate(() => {
				// A ROW IS ONE LINE TALL. The scorecard's type grew from 0.72rem
				// to 0.8rem when the match got a column of its own, and the only
				// elastic field in the row is the declarer's name — which
				// ellipsises, so nothing can wrap. Measured rather than trusted:
				// this is exactly the change that would silently double a row.
				const cs = [...document.querySelectorAll(".dis-mcard .dis-mrow-ct")];
				const line = cs.length
					? Math.max(...cs.map((c) => c.getBoundingClientRect().height)) : 0;
				const card = document.querySelector(".dis-mcard");
				return {
					rows: document.querySelectorAll(".dis-mcard .dis-mrow:not(.dis-mrow-hd)").length,
					dd: document.querySelectorAll(".dis-mcard .dis-mrow-dd").length,
					hd: document.querySelector(".dis-mcard .dis-mrow-hd")?.children.length,
					lineH: Math.round(line),
					fontPx: card ? Math.round(parseFloat(getComputedStyle(card).fontSize)) : 0,
					// ...and the ROW still fits its column. The name ellipsises,
					// so a too-large type shows up here — the fixed-width number
					// columns push the grid past its box — long before it shows
					// up as a second line.
					overflowsX: card ? card.scrollWidth > card.clientWidth + 1 : null,
					// ...and the rows pack to the TOP. The card takes the slack in
					// its column now, and a grid stretches its auto rows by
					// default — which spread four played rounds evenly down a
					// 900px column instead of listing them.
					alignContent: card ? getComputedStyle(card).alignContent : null,
				};
			});
			check("a scorecard row is one line tall at the larger type",
				cells.fontPx >= 14 && cells.lineH > 0 && cells.lineH <= cells.fontPx * 1.7
					&& cells.overflowsX === false,
				JSON.stringify(cells));
			check("...and its rows pack to the top rather than spreading",
				cells.alignContent === "start", JSON.stringify(cells));
			check("every banked round is a four-column row",
				!!cells.rows && cells.dd === 0 && cells.hd === 4, JSON.stringify(cells));
			await sleep(700);
			const again = await ddText();
			check("...and the answer holds still across re-renders",
				again === solved, `first ${solved}, later ${again}`);
			// ...and it is NOT on the scorecard any more: a stale fifth column
			// there would mean the move half-happened.
			const noDd = await page.evaluate(() => ({
				cells: document.querySelectorAll(".dis-mcard .dis-mrow-dd").length,
				hd: document.querySelector(".dis-mcard .dis-mrow-hd")?.children.length,
			}));
			check("...and the scorecard is back to four columns without it",
				noDd.cells === 0 && noDd.hd === 4, JSON.stringify(noDd));
			await page.evaluate(() => {
				[...document.querySelectorAll(".cm-panel button, .cm-x, .cm-close")]
					.find((b) => /close|×/i.test(b.textContent || b.getAttribute("aria-label") || ""))?.click();
			});
			await sleep(300);

			// A scorecard row opens the ROUND STORY: the whole deal face up —
			// both hands, the piles, the talon with what the declarer was
			// shown, and the bidding. Right-click drives the same handler a
			// long-press fires (contextmenu), so it is the path asserted.
			await page.evaluate(() => {
				const row = [...document.querySelectorAll(".dis-mcard .dis-mrow-open")][0];
				row.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
			});
			const story = await page.waitForFunction(() => {
				const panel = document.querySelector(".cm-panel .dis-story");
				if (!panel) return null;
				const cards = panel.querySelectorAll(".dis-card").length;
				const secs = [...panel.querySelectorAll(".dis-story-hd")].map((h) => h.textContent);
				return {
					cards,
					bids: panel.querySelectorAll(".dis-story-bid").length,
					shown: panel.querySelectorAll(".dis-story-shown").length,
					// A taken card sits in the declarer's hand row with its own
					// badge, so shown+took is the full "declarer saw three".
					took: panel.querySelectorAll(".dis-story-took").length,
					talon: secs.some((t) => /Out of play/i.test(t)),
					// The panel widened for the card rows; the create modal's
					// 372px would fold a seven-card hand onto three lines.
					wide: (document.querySelector(".cm-panel")?.getBoundingClientRect().width || 0) > 500,
				};
			}, null, { timeout: 8_000 }).then((h) => h.jsonValue()).catch(() => null);
			// 32 cards face up: 2×7 hands + 2×6 piles + 6 out. The declarer was
			// shown three of the six — outlined, and asserted by count.
			check("right-clicking a scorecard row lays the round out face up",
				!!story && story.cards === 32 && story.talon && story.bids >= 1 && story.wide,
				JSON.stringify(story));
			check("...with the three cards the declarer was shown outlined",
				!!story && story.shown + story.took === 3, JSON.stringify(story));

			// ── PAR ────────────────────────────────────────────────────────
			// The same deal solved in every denomination from BOTH sides: what
			// each player could have taken as declarer, and whether they could
			// have ducked to Null there. Twenty exact solves over a two-worker
			// pool, and every one of them is a synthetic contract whose payoff
			// IS the answer (`PAR_TERMS`) — so the failure this catches is the
			// chain going quiet: a reader that refuses the re-trumped deal, a
			// terms shape the wire drops, or a worker that never answers all
			// leave cells sitting on their placeholder forever, which reads as
			// a table that is merely still thinking.
			const par = await page.waitForFunction(() => {
				const t = document.querySelector(".cm-panel .dis-partable");
				if (!t) return null;
				const cells = [...t.querySelectorAll(".dis-parcell")];
				const nums = cells.map((c) => c.querySelector("b")?.textContent.trim());
				if (!cells.length || nums.some((n) => !n || !/^\d+$/.test(n))) return null;
				const rows = [...t.querySelectorAll(".dis-parden")].map((d) => d.textContent.trim());
				const playedIdx = cells.findIndex((c) => c.classList.contains("dis-parcell-played"));
				return {
					rows, cells: cells.length, nums,
					played: playedIdx >= 0 ? rows[Math.floor(playedIdx / 2)] : null,
					playedN: cells.filter((c) => c.classList.contains("dis-parcell-played")).length,
					// One number per column may be lit as that seat's best, and
					// it is only lit once the whole column has landed.
					top: cells.filter((c) => c.classList.contains("dis-parcell-top")).length,
					contract: document.querySelector(".cm-panel .dis-story-ctline b")?.textContent.trim(),
				};
			}, null, { timeout: 60_000 }).then((h) => h.jsonValue()).catch(() => null);
			check("the round story's par table solves every denomination from both sides",
				!!par && par.rows.length === 5 && par.cells === 10,
				JSON.stringify(par));
			// The contract that was really played is ringed, exactly once, in
			// its own denomination's row — the table's one anchor to the round
			// it is describing.
			check("...and rings the contract that was actually played",
				!!par && par.playedN === 1 && !!par.played
					&& (par.contract || "").includes(par.played),
				JSON.stringify(par));
			check("...and marks each side's best denomination",
				!!par && par.top >= 2, JSON.stringify(par));
			await page.evaluate(() => {
				document.querySelector(".cm-panel .cm-x")?.click();
			});
			const storyGone = await page.waitForFunction(
				() => !document.querySelector(".cm-panel .dis-story"),
				null, { timeout: 4_000 }).then(() => true).catch(() => false);
			check("...and the story closes", storyGone, "");
		}

		check("no page errors playing a game out", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── The create modal opens on the tier you last PLAYED ───────────────────
	// One game covers the behaviour (`useLastDifficulty` is shared, and each
	// game's wiring is one line that `shared/tests/test_ai_difficulty_memory.py`
	// checks statically). Duel, because its default is Hard and its Easy tier
	// starts a game instantly, so the assertion is over two DIFFERENT tiers
	// rather than over the default agreeing with itself.
	async function lastDifficulty(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "lastdiff-harness", name: "Diff", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};
		const openModal = async () => {
			await page.goto(`http://localhost:${PORT}/duel`, { waitUntil: "networkidle" });
			await page.waitForSelector(".duel", { timeout: 25_000 }).catch(() => {});
			await page.getByRole("button", { name: /new game|create/i }).first()
				.click({ timeout: 15_000 }).catch(() => {});
			await page.waitForSelector(".cm-seg", { timeout: 15_000 }).catch(() => {});
			return page.evaluate(() =>
				[...document.querySelectorAll(".cm-seg .cm-seg-btn.sel")].map((b) => b.textContent.trim()));
		};

		// A first-time player gets the game's own default.
		const first = await openModal();
		check("a player with no history gets the game's default tier",
			first.includes("Hard") && !first.includes("Easy"), JSON.stringify(first));

		// Play one game against a DIFFERENT tier…
		for (const label of [/^VS AI$/, /^Easy$/]) {
			await page.locator(".cm-seg .cm-seg-btn", { hasText: label }).first()
				.click({ timeout: 10_000 }).catch(() => {});
		}
		await page.locator(".cm-create").first().click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".duel-board", { timeout: 25_000 }).catch(() => {});

		// …and the next modal, on a FRESH page load, opens on it.
		const again = await openModal();
		check("the create modal reopens on the tier that was actually played",
			again.includes("Easy") && !again.includes("Hard"), JSON.stringify(again));

		// Browsing the picker is not playing: a tier merely clicked must not stick.
		await page.locator(".cm-seg .cm-seg-btn", { hasText: /^Expert$/ }).first()
			.click({ timeout: 10_000 }).catch(() => {});
		const afterBrowsing = await openModal();
		check("a tier only clicked, never played, does not become the default",
			afterBrowsing.includes("Easy") && !afterBrowsing.includes("Expert"),
			JSON.stringify(afterBrowsing));

		check("no page errors remembering the difficulty", errors.length === 0,
			errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Offline vs-AI (Castles of Crimson) ────────────────────────────────────
	// The CoC offline stack is deeper than Spender's: a per-decision bot loop, a
	// model-fetching search pool, and a board-layout localStorage cache the game
	// screen hard-gates on. The scenario seeds the boards cache (what the hub's
	// Download button does online), creates a local game, cuts the network once the
	// search pool is armed, and plays the SETUP castle placement both ways — ours by
	// clicking a legal hex, the bot's through the offline search loop.
	async function offlineCoc(log) {
		const boards = await (await fetch(`http://localhost:${API_PORT}/coc/boards`)).json();
		const ctx = await browser.newContext();
		await ctx.addInitScript(([user, boardsJson]) => {
			localStorage.setItem("spender_user", user);
			localStorage.setItem("coc_boards_v1", boardsJson);
		}, [JSON.stringify({ id: "coc-offline-harness", name: "CocOff", guest: true }),
			JSON.stringify(boards)]);
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		let poolReady = false;
		page.on("console", (m) => { if (/\[coc client-AI\].*ready/.test(m.text())) poolReady = true; });
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/offline`, { waitUntil: "load" });
		await page.waitForSelector(".offline-panel", { timeout: 20_000 }).catch(() => {});
		await page.locator(".cm-seg button", { hasText: "Castles of Crimson" }).click({ timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-create", { hasText: "Start Game" }).click({ timeout: 10_000 }).catch(() => {});
		const mounted = await page.waitForSelector(".coc", { timeout: 20_000 })
			.then(() => true).catch(() => false);
		check("a local Castles game mounts the CoC screen", mounted);
		check("...at its /offline/<LOCALID> URL",
			/^\/offline\/LOCAL[A-Z0-9]+$/.test(new URL(page.url()).pathname), new URL(page.url()).pathname);

		if (mounted) {
			for (let i = 0; i < 60 && !poolReady; i++) await sleep(250);
			check("the CoC search pool arms (model fetched)", poolReady);
			await ctx.setOffline(true);

			// Our setup turn arrives (the bot's castle, if it opens, plays through the
			// offline search loop) → click a legal burgundy hex to place our castle.
			let legal = 0;
			for (let i = 0; i < 90 && legal === 0; i++) {
				legal = await page.locator(".coc-hex.legal").count().catch(() => 0);
				if (legal === 0) await sleep(500);
			}
			check("our castle placement arrives with the network OFF", legal > 0, `${legal} legal`);
			await page.locator(".coc-hex.legal").first().click({ timeout: 10_000 }).catch(() => {});

			// Both castles down → round 1 rolls and play begins; wait for OUR first real
			// turn (the bot's opening turn runs the per-decision loop offline).
			const badge = await page.waitForSelector("text=Your turn", { timeout: 90_000 })
				.then(() => true).catch(() => false);
			check("the game reaches round 1 and our turn (bot played offline)", badge);

			// THE GAME SCREEN FITS THE WINDOW. The board's aesthetic height floor is
			// `38vw` — a HEIGHT taken from the viewport's WIDTH — so a wide window used to
			// ask for board room the window did not have and the page grew a scrollbar for
			// space nothing needed: at 2560 it wanted 973px of board to hold the same
			// 619px-wide ring it draws at 1800 (the wrap's max-width), and a 2560x1600
			// panel at 150% OS scaling — 1707x~940 CSS px — overflowed by a few dozen px.
			// Both bounds are measured at runtime (`--coc-board-cap`, and the log's floor),
			// so they are asserted here at the sizes that drove them. 1366x768-class windows
			// are NOT listed: there the duchy row alone is taller than the window and the
			// page correctly scrolls. The depot ring must still fit INSIDE the board at
			// every one of them — that is the invariant the cap is not allowed to break,
			// and the reason it is a ceiling on the floor rather than a height.
			const wasViewport = page.viewportSize();
			for (const vp of [{ width: 2560, height: 1600 }, { width: 2560, height: 1000 },
				{ width: 1920, height: 1080 }, { width: 1707, height: 948 }]) {
				await page.setViewportSize(vp);
				await sleep(400);
				const fit = await page.evaluate(() => {
					const de = document.documentElement;
					const bh = document.querySelector(".coc-board-hex").getBoundingClientRect();
					const spill = [...document.querySelectorAll(".coc-board-hex [data-depot]")]
						.map((el) => el.getBoundingClientRect())
						.filter((r) => r.top < bh.top - 1 || r.bottom > bh.bottom + 1).length;
					return { over: de.scrollHeight - innerHeight, wide: de.scrollWidth - innerWidth,
						board: Math.round(bh.height), spill };
				});
				check(`the Castles game fits a ${vp.width}x${vp.height} window`,
					fit.over <= 0 && fit.wide <= 0, JSON.stringify(fit));
				check(`...with every depot inside the board at ${vp.width}x${vp.height}`,
					fit.spill === 0, JSON.stringify(fit));
			}
			if (wasViewport) await page.setViewportSize(wasViewport);

			await ctx.setOffline(false);   // assets for a reload (no SW on localhost)
			await page.reload({ waitUntil: "load" }).catch(() => {});
			const resumed = await page.waitForSelector(".coc", { timeout: 20_000 })
				.then(() => true).catch(() => false);
			check("a reload resumes the Castles save from IndexedDB", resumed);

			await page.goBack().catch(() => {});
			const listed = await page.waitForSelector(".offline-save-row", { timeout: 10_000 })
				.then(() => true).catch(() => false);
			check("Back lands on the hub with the Castles save listed", listed);
		}
		check("no page errors in offline Castles play", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Offline vs-AI (Spender Duel) ──────────────────────────────────────────
	// Duel's offline stack: per-decision bot loop + the root-parallel search pool
	// (nets embedded in the wasm — no model fetch) + a card-catalog localStorage
	// cache. Seats are dealt randomly, so the scenario just waits for OUR turn
	// (the bot's opening decision, if it goes first, runs the offline search),
	// takes one token, and requires the bot's reply with the network OFF.
	/* DISSONANCE OFFLINE — the referee runs in the browser, not just the AI.
	 *
	 * This is the block that would catch the failure the whole feature is built
	 * to avoid: `classic.rs` refereeing a round through the wasm, priced by
	 * pricing.js, with nothing answering. The Rust parity gate proves the RULES
	 * agree with the server; only a browser can prove the three pieces are
	 * actually wired to each other, and the ways they can fail (a worker that
	 * never loads, a view the board cannot render, a bot loop that never arms)
	 * all look like a game that simply sits there.
	 */
	async function offlineDissonance(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript((user) => {
			localStorage.setItem("spender_user", user);
		}, JSON.stringify({ id: "dis-offline-harness", name: "DisOff", guest: true }));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		let searched = false;
		const aiLines = [];
		page.on("console", (m) => {
			const t = m.text();
			// BOTH log prefixes: the card path says "dissonance", the auction
			// path still says "oddtrick" (an export-era name the artifact keeps).
			if (/client-AI/.test(t)) { searched = true; aiLines.push(t.slice(0, 120)); }
		});
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/offline`, { waitUntil: "load" });
		await page.waitForSelector(".offline-panel", { timeout: 20_000 }).catch(() => {});

		// EVERY GAME IN THE PICKER IS REACHABLE ON A PHONE, and this is measured
		// rather than assumed because the failure is silent and total: the base
		// `.cm-seg` is `overflow:hidden` with `nowrap` buttons, so an option past
		// the fold cannot be scrolled to, swiped to, or seen. Adding Dissonance
		// made four options 485px wide in a 330px box at 390px — the last one
		// ending 154px past the edge — and the only symptom was a game that did
		// not appear to exist. A DOM check would have passed the whole time, so
		// this compares rectangles.
		await page.setViewportSize({ width: 390, height: 844 });
		await sleep(200);
		const picker = await page.evaluate(() => {
			const seg = document.querySelector(".cm-seg");
			if (!seg) return { missing: true };
			const box = seg.getBoundingClientRect();
			return {
				clipped: seg.scrollWidth > seg.clientWidth + 1,
				outside: [...seg.querySelectorAll(".cm-seg-btn")]
					.filter((b) => {
						const r = b.getBoundingClientRect();
						return r.right > box.right + 1 || r.left < box.left - 1;
					})
					.map((b) => b.textContent.trim()),
				n: seg.querySelectorAll(".cm-seg-btn").length,
			};
		});
		check("every offline game is reachable in the picker on a phone",
			!picker.missing && !picker.clipped && picker.outside?.length === 0 && picker.n >= 4,
			JSON.stringify(picker));
		await page.setViewportSize({ width: 1280, height: 900 });
		await sleep(200);

		await page.locator(".cm-seg button", { hasText: "Dissonance" }).click({ timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-create", { hasText: "Start Game" }).click({ timeout: 10_000 }).catch(() => {});
		const mounted = await page.waitForSelector(".dis", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("a local Dissonance game mounts the board", mounted);
		check("...at its /offline/<LOCALID> URL",
			/^\/offline\/LOCAL[A-Z0-9]+$/.test(new URL(page.url()).pathname),
			new URL(page.url()).pathname);
		if (!mounted) {
			check("no page errors dealing an offline round", errors.length === 0,
				errors[0]?.slice(0, 200) || "");
			await ctx.close();
			return;
		}

		// THE DEAL CAME OUT OF THE WASM, and it is a real one: two seats, seven
		// cards in the near hand and its three piles. A referee that answered
		// with an empty or half-built view would still "mount".
		const dealt = await page.evaluate(() => {
			const seats = [...document.querySelectorAll(".dis-table .dis-seat")];
			const near = seats[seats.length - 1];
			return {
				seats: seats.length,
				hand: near?.querySelectorAll(".dis-hand .dis-card").length ?? 0,
				piles: near?.querySelectorAll(".dis-pilewrap").length ?? 0,
			};
		});
		check("the local referee dealt a real hand", dealt.seats === 2 && dealt.hand === 7,
			JSON.stringify(dealt));

		// Drive the round the way `dissonanceBeat` does — the same button names
		// and the same `.dis-seat .dis-card.play` affordance, so this block is
		// testing the REFEREE rather than a second idea of how the board works.
		const step = async (name) => {
			const b = page.getByRole("button", { name }).first();
			if (await b.count() === 0) return false;
			await b.click({ timeout: 5_000 }).catch(() => {});
			await sleep(220);
			return true;
		};
		// THE NETWORK GOES OFF ONCE THE POOL HAS LOADED, not before, and that is
		// a property of the HARNESS rather than a softening of the claim.
		// localhost runs no service worker, so a page taken offline before its
		// workers have fetched `dissonance-worker.js` and the 300KB wasm can
		// never load them — the bot then answers nothing and the round stalls in
		// the auction, which is exactly what this block did on its first run and
		// is an artifact of the harness, not of the feature. In the product the
		// hub's Download button has already put both in the SW cache. Everything
		// after the flip — the referee, the search, the trick fold, the save —
		// runs with nothing answering.
		let offlineFrom = -1;
		let reachedPlay = false, played = 0;
		for (let i = 0; i < 160; i++) {
			if (offlineFrom < 0 && searched) {
				await ctx.setOffline(true);
				offlineFrom = i;
			}
			if (!reachedPlay && await page.locator(".dis-trickinfo").count() > 0) reachedPlay = true;
			if (played >= 3 && offlineFrom >= 0) break;
			// The bid pad first: either seat may open, so the harness bids
			// whenever it is offered one.
			if (await page.locator(".dis-bidgrid button:not([disabled])").count() > 0) {
				await disBidCheaply(page);
				await sleep(260);
				continue;
			}
			if (await step(/^Stand pat$/)) continue;          // decline the swap
			if (await step(/^Let it stand$/)) continue;       // decline the Double
			if (await step(/^Pass$/)) continue;               // settle the auction
			const card = page.locator(".dis-seat .dis-card.play").last();
			if (await card.count() > 0) {
				await card.click({ timeout: 5_000 }).catch(() => {});
				played += 1;
				await sleep(400);
				continue;
			}
			await sleep(400);                                  // the bot is thinking
		}
		// WHAT THE BOARD WAS SHOWING, so a stall says which phase it stalled in
		// rather than "false". A round that never leaves the auction and one
		// that never gets a card back from the bot are different bugs.
		const stuck = await page.evaluate(() => ({
			bidPad: !!document.querySelector(".dis-bidgrid"),
			myKeys: document.querySelectorAll(".dis-bidgrid button:not([disabled])").length,
			buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim())
				.filter(Boolean).slice(0, 8),
			contract: document.querySelector(".dis-contract")?.textContent?.trim() || "",
			trick: document.querySelector(".dis-trickinfo")?.textContent?.trim() || "",
			playable: document.querySelectorAll(".dis-seat .dis-card.play").length,
			// THE REFEREE'S REFUSAL, if it made one: the driver surfaces an
			// illegal move as a toast rather than throwing, so without this a
			// rejected bot move looks exactly like a bot that never answered.
			toast: document.querySelector(".toast")?.textContent?.trim() || "",
		}));
		check("the round reaches trick 1", reachedPlay,
			JSON.stringify(stuck) + " ai=" + JSON.stringify(aiLines.slice(0, 3)));
		check("...and the network was off for it", offlineFrom >= 0,
			"the search pool never loaded, so the block never went offline");
		// EVERY CARD AFTER THE FIRST IS THE PROOF: to be offered a second one,
		// the referee had to apply ours, see whose turn it was, arm a decision,
		// take the search's answer and fold the trick — the whole loop, with
		// nothing answering.
		check("cards play through the local referee, and the bot answers", played >= 2,
			`played ${played} ${JSON.stringify(stuck)}`);
		const trickNo = await page.locator(".dis-trickinfo").first().textContent().catch(() => "");
		check("...and the round advances past trick 1 with no network",
			/Trick ([2-9]|1[0-3]) of 13/.test(trickNo), trickNo);
		check("...with the search really running in this browser", searched,
			"no [dissonance client-AI] line — the bot fell through to nothing");

		// A save survives a reload, which is the difference between a game and a
		// tab. (Back online only for the assets: localhost has no service worker.)
		await ctx.setOffline(false);
		await page.reload({ waitUntil: "load" }).catch(() => {});
		const resumed = await page.waitForSelector(".dis", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("the local game resumes after a reload", resumed);

		check("no page errors playing offline", errors.length === 0,
			errors[0]?.slice(0, 200) || "");
		await ctx.close();
	}

	async function offlineDuel(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript((user) => {
			localStorage.setItem("spender_user", user);
		}, JSON.stringify({ id: "duel-offline-harness", name: "DuelOff", guest: true }));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		let poolReady = false;
		page.on("console", (m) => { if (/\[duel client-AI\].*ready/.test(m.text())) poolReady = true; });
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/offline`, { waitUntil: "load" });
		await page.waitForSelector(".offline-panel", { timeout: 20_000 }).catch(() => {});
		await page.locator(".cm-seg button", { hasText: "Spender Duel" }).click({ timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-create", { hasText: "Start Game" }).click({ timeout: 10_000 }).catch(() => {});
		const mounted = await page.waitForSelector(".duel", { timeout: 20_000 })
			.then(() => true).catch(() => false);
		check("a local Duel game mounts the Duel screen", mounted);
		check("...at its /offline/<LOCALID> URL",
			/^\/offline\/LOCAL[A-Z0-9]+$/.test(new URL(page.url()).pathname), new URL(page.url()).pathname);

		if (mounted) {
			// The catalog fetch + the search pool both need the network once; the pool-ready
			// line is the later of the two (workers instantiate the 5MB wasm).
			for (let i = 0; i < 60 && !poolReady; i++) await sleep(250);
			check("the Duel search pool arms", poolReady);
			await ctx.setOffline(true);

			// Wait for our turn (if the bot was dealt seat 0 its whole opening decision —
			// search included — must run offline first).
			const myTurn = await page.waitForSelector(".duel-turnbadge:has-text('Your turn')", { timeout: 90_000 })
				.then(() => true).catch(() => false);
			check("our turn arrives with the network OFF", myTurn);

			// Take one token: click board gems until the Take button appears (a gold
			// click arms the reserve flow instead — the next gem click clears it).
			let took = false;
			const tokens = page.locator(".duel-board .gem-token");
			const n = await tokens.count().catch(() => 0);
			for (let i = 0; i < n && !took; i++) {
				await tokens.nth(i).click({ timeout: 5_000 }).catch(() => {});
				took = (await page.locator("button:has-text('Take 1')").count().catch(() => 0)) > 0;
			}
			if (took) await page.locator("button:has-text('Take 1')").click({ timeout: 5_000 }).catch(() => {});
			check("a take submits through the local engine", took);

			// The bot answers offline (3.5s budget + pacing), then it's our turn again.
			const botReplied = await page.waitForSelector(".duel-turnbadge:has-text('Bot is playing')", { timeout: 30_000 })
				.then(() => true).catch(() => false);
			const back = botReplied && await page.waitForSelector(".duel-turnbadge:has-text('Your turn')", { timeout: 90_000 })
				.then(() => true).catch(() => false);
			check("the wasm AI replies while offline", back);

			await ctx.setOffline(false);   // assets for a reload (no SW on localhost)
			await page.reload({ waitUntil: "load" }).catch(() => {});
			const resumed = await page.waitForSelector(".duel", { timeout: 20_000 })
				.then(() => true).catch(() => false);
			check("a reload resumes the Duel save from IndexedDB", resumed);

			await page.goBack().catch(() => {});
			const listed = await page.waitForSelector(".offline-save-row", { timeout: 10_000 })
				.then(() => true).catch(() => false);
			check("Back lands on the hub with the Duel save listed", listed);
		}
		check("no page errors in offline Duel play", errors.length === 0, errors[0]?.slice(0, 160) || "");
		await ctx.close();
	}

	// ── Two lanes, run concurrently ───────────────────────────────
	// Every block above owns its own browser context and its own room, so they are
	// independent. They are NOT interchangeable, though, and a flat "run them all"
	// would be wrong twice over.
	//
	// A client-WASM pool sizes itself at max(1, min(hc-1, 4)), so on a 4-core box two
	// SEARCHING blocks at once oversubscribe the machine. Lane A therefore holds every
	// block that arms a pool (dissonanceHard + the three offline blocks) together with
	// the two that measure frame-level TIMING rather than settled layout: skat's panel
	// recorder, and beat's per-trick dwells, which assert >= 550ms against a 700ms hold.
	// They stay serial, in their existing order, so the adjacency those two were tuned
	// against (beat immediately after Hard, comments there) is exactly what it was.
	//
	// Lane B holds the DOM/geometry blocks. They contend for nothing but the renderer
	// and every one of them asserts a settled measurement, never an elapsed time.
	//
	// IF dissonanceBeat EVER TURNS FLAKY, move dmCardFace (lane B's heaviest, ~20s of
	// resizes and re-fits) into lane A before touching the dwell thresholds: it costs
	// ~10s of wall clock and removes the only real load running beside those frames.
	//
	// Output is buffered per block and flushed as one group, because two lanes writing
	// line-by-line interleave into something no one can read. The group header carries
	// the block's own wall time, which is what you want when deciding what to cut next.
	const runLane = async (blocks) => {
		for (const fn of blocks) {
			const buf = [];
			const t0 = Date.now();
			try {
				await fn((s) => buf.push(s));
			} catch (e) {
				// A block that throws must not take its LANE down with it: the other
				// blocks still have findings, and losing them turns one broken selector
				// into a run that proved nothing. Recorded as a failure, so the gate is
				// still red — it just stays red for a readable reason.
				buf.push(`  FAIL ${fn.name} threw: ${String(e?.message || e).slice(0, 200)}`);
				shell.push(`${fn.name} threw`);
			} finally {
				console.log([`── ${fn.name} (${((Date.now() - t0) / 1000).toFixed(1)}s)`,
					...buf].join("\n"));
				// ON CI, ALSO EMIT EACH FAILURE AS A WORKFLOW ANNOTATION. The run log
				// needs an authenticated download; annotations are readable by anyone who
				// can see the repo. When this gate fails the Pages deploy, the one line
				// saying what broke is otherwise visible only to whoever can sign in and
				// unzip a log, which is a poor place for it. Every check already carries
				// its measurements in `detail`; this only puts them where they can be
				// read. One site, because every block's `check` funnels failures here.
				if (process.env.GITHUB_ACTIONS) {
					for (const line of buf.filter((l) => l.startsWith("  FAIL "))) {
						const [, name, detail] = line.slice(7).match(/^(.*?)(?:  (.*))?$/s);
						// `%` is the escape character in a workflow command, so a raw one
						// in a measurement would corrupt the annotation it appears in.
						const flat = (t) => String(t).replace(/%/g, "%25").replace(/\s+/g, " ").trim();
						console.log(`::error title=${flat(fn.name + ": " + name).replace(/[:,]/g, " ").slice(0, 180)}`
							+ `::${flat(detail || "no detail").slice(0, 900)}`);
					}
				}
			}
		}
	};

	// Lane A's ORDER is load-bearing, not arbitrary. The offline blocks go first so
	// they overlap lane B's cheap opening blocks, which leaves dissonanceBeat — the
	// most timing-sensitive thing in the file — running in the tail, where lane B has
	// already finished and it has the box almost to itself. Measured: beat is the
	// last ~20s either way, so this costs nothing and buys it a quiet machine.

	// Rag Tag: create a game against the bot and play a whole round through --
	// draft, who-leads, the fight animation, and a BUILD! submission. The point
	// is that this game is SIMULTANEOUS, so there is no "your turn" to wait on:
	// every prompt appears because the server said `you_owe`, and a client that
	// re-derived it would show the wrong one. Only a real play-through catches
	// that; mounting the route proves nothing about it.
	async function ragtagFight(log) {
		const ctx = await browser.newContext();
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "ragtag-harness", name: "RagHarness", guest: true })));
		const page = await ctx.newPage();
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(`ragtag: ${name}`); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/ragtag`, { waitUntil: "networkidle" });
		await page.waitForSelector(".lby-create-row", { timeout: 25_000 }).catch(() => {});
		check("lobby reachable by URL", await page.locator(".lby-create-row").count() > 0);

		// The rules panel. `RulesFacts` reads {k, v} off each item and Rag Tag was
		// passing bare strings, so three of its sections rendered as EMPTY boxes --
		// present, correctly styled, and saying nothing. Assert the boxes have text
		// in them, not merely that they exist.
		await page.locator(".lby-create-row button", { hasText: /rules/i }).first()
			.click({ timeout: 10_000 }).catch(() => {});
		await sleep(500);
		const factText = await page.locator(".rl-fact").allInnerTexts().catch(() => []);
		check("the rules panel opens, and no part of it is blank",
			factText.length > 0 && factText.every((t) => t.trim().length > 4)
			&& await page.locator(".rl-sec").count() > 5,
			`${factText.length} fact boxes: ${JSON.stringify(factText.map((t) => t.slice(0, 20)))}`);
		await page.keyboard.press("Escape").catch(() => {});
		await sleep(300);

		await page.locator(".lby-cta").click({ timeout: 15_000 }).catch(() => {});
		await page.waitForSelector(".cm-create", { timeout: 15_000 }).catch(() => {});
		await page.locator(".cm-create").click({ timeout: 15_000 }).catch(() => {});

		// Draft: two picks, and the second hand is the one the bot passed across.
		//
		// The picks are DELIBERATE, not "whatever is first". Two of the board-panel
		// checks below are conditional on who was drafted — a ring is only drawn by
		// a fighter who has one, and only the Fey Folk have Characters — and a
		// conditional nothing reached is a green tick over an untested claim. That
		// used to be covered by the draft being random: see it eventually, over many
		// runs. The deal is SEEDED now (see GAMES_DEAL_SEED above), which buys the
		// determinism this gate needed and takes "eventually" away with it — an
		// unlucky seed would park those two checks at zero for good. So reach for the
		// fighters that exercise them instead of hoping, and ASSERT below that both
		// were reached. Which fighter is drafted is not what this block tests; what
		// their board panel renders is.
		const WANTED = [/fey folk/i, /joan/i];
		let drafted = 0;
		for (let round = 0; round < 2; round++) {
			await page.waitForSelector(".rt-prompt .rt-pick", { timeout: 25_000 }).catch(() => {});
			const picks = page.locator(".rt-prompt .rt-pick");
			const n = await picks.count();
			if (n === 0) break;
			const labels = await picks.allInnerTexts().catch(() => []);
			const wanted = labels.findIndex((t) => WANTED.some((re) => re.test(t)));
			await picks.nth(wanted >= 0 ? wanted : 0).click().catch(() => {});
			drafted += 1;
			await sleep(700);
		}
		check("drafted two fighters", drafted === 2, `made ${drafted} pick(s)`);

		// The Fey Folk ask for a Character before anything else; if they were
		// drafted the same prompt shape answers it, so this loop covers both.
		for (let i = 0; i < 3; i++) {
			const heading = await page.locator(".rt-prompt h3").first().innerText().catch(() => "");
			if (!/Who leads/i.test(heading) && await page.locator(".rt-prompt .rt-pick").count() > 0
				&& /Character/i.test(heading)) {
				await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
				await sleep(600);
			} else break;
		}

		// Who leads.
		await page.waitForSelector(".rt-prompt .rt-pick", { timeout: 20_000 }).catch(() => {});
		const leadHd = await page.locator(".rt-prompt h3").first().innerText().catch(() => "");
		check("asked who leads", /leads/i.test(leadHd), `heading was "${leadHd}"`);
		await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});

		// The fight resolves server-side and arrives as beats. It is played back
		// BY HAND -- one click a turn -- so the two things worth gating are that
		// it does NOT advance on its own, and that the next decision is held back
		// until the last turn is on screen. Both are behaviour a passing render
		// test would happily miss.
		await page.waitForSelector(".rt-stage", { timeout: 25_000 }).catch(() => {});
		check("the stage appears", await page.locator(".rt-stage").count() > 0);

		const turnsThisRound = await page.locator(".rt-steps .rt-step").count();
		check("a step marker per turn", turnsThisRound >= 2, `${turnsThisRound} markers`);

		// A TURN is played out one ACTION at a time -- a card that attacks, heals and
		// burns is one decision and three things to watch, and it used to land in a
		// single frame, every bar, total and token jumping to the sum together. The two
		// halves of that are asserted separately because they fail differently: the
		// ribbon has to GROW inside one turn (the actions arrive), and the turn counter
		// has to HOLD (a turn boundary is still a click, so the fight cannot run away
		// from the player). One check waiting on both would prove neither.
		const liveLines = () => page.locator(".rt-ribbon .rt-rib").count();
		const firstTurnText = await page.locator(".rt-turnno").first().innerText().catch(() => "");
		const ribbonAtOnce = await liveLines();
		const actLabel = await page.locator(".rt-actno").first().innerText().catch(() => "");
		await sleep(2200);
		const ribbonLater = await liveLines();
		const stillTurnText = await page.locator(".rt-turnno").first().innerText().catch(() => "");
		check("the fight does not advance a TURN on its own",
			firstTurnText === stillTurnText && /1\b/.test(stillTurnText),
			`was "${firstTurnText}", now "${stillTurnText}"`);
		// Gated on the counter READ AT THE START, not merely on its presence: a turn
		// with one action has nothing to stagger, and a harness that arrived late
		// enough to find the turn already finished would otherwise fail for being
		// slow. "action 1 of 4" is the only state that proves anything here.
		const acts = /action (\d+) of (\d+)/.exec(actLabel);
		if (acts && Number(acts[1]) < Number(acts[2])) {
			check("the actions of a turn arrive one at a time, not all at once",
				ribbonLater > ribbonAtOnce,
				`${ribbonAtOnce} -> ${ribbonLater} ribbon lines; counter was "${actLabel}"`);
		}

		// Whatever turn is on the stage, let it FINISH playing before reading anything
		// off the boards. Every check below compares two board states, and one read
		// mid-action is a false failure that looks exactly like the bug this block
		// exists to catch.
		const settled = async () => {
			await sleep(150);            // let the click render before believing the DOM
			for (let i = 0; i < 40; i++) {
				if (await page.locator(".rt-actno-live").count() === 0) return;
				await sleep(250);
			}
		};
		await settled();

		const cardNames = await page.locator(".rt-card-name").allInnerTexts().catch(() => []);
		check("both revealed cards are named",
			cardNames.filter((t) => t && t !== "—").length >= 2,
			JSON.stringify(cardNames));

		// The log runs up to AND INCLUDING the turn on the stage, and marks that one.
		// It used to stop one turn short to avoid printing the same sentences twice;
		// that reads as "the log is always one turn behind" while you play, so the
		// live turn is marked instead.
		const logLines = await page.locator(".rt-log-line").count();
		check("the battle log is present", await page.locator(".rt-log").count() === 1);
		check("the log includes the turn on the stage",
			await page.locator(".rt-log-turn.rt-log-now").count() === 1,
			`${await page.locator(".rt-log-turn.rt-log-now").count()} marked rows`);

		// Nothing may ask for the next decision while turns remain unwatched.
		if (turnsThisRound > 1) {
			const heldHd = await page.locator(".rt-prompt h3").count();
			check("the next decision waits for the replay to finish", heldHd === 0,
				`a prompt was already showing: "${await page.locator(".rt-prompt h3").first().innerText().catch(() => "")}"`);
		}

		const healthNow = async () => (await page.locator(".rt-fighter .rt-hp b")
			.allInnerTexts().catch(() => [])).join("|");
		
		// THE CARDS FLIP BEFORE ANYTHING MOVES. Each beat carries the board as it
		// stood when the cards were turned over, and the turn walks forward from
		// there -- so the frame right after "Next turn" must still show the board
		// that turn INHERITED. Reading it here is the only moment that state is
		// observable, and before per-event state existed there was no such frame at
		// all: the whole turn landed at once.
		const beforeNext = await healthNow();
		await page.locator(".rt-ctl-go").click({ timeout: 10_000 }).catch(() => {});
		const atFlip = await healthNow();
		check("the next turn flips its cards before it moves the boards",
			atFlip === beforeNext, `"${beforeNext}" became "${atFlip}" on the flip`);
		await settled();
		const afterNext = await page.locator(".rt-turnno").first().innerText().catch(() => "");
		check("Next turn advances the fight", afterNext !== stillTurnText,
			`still "${afterNext}"`);
		const logAfter = await page.locator(".rt-log-line").count();
		check("the turn just watched lands in the log", logAfter > logLines,
			`${logLines} -> ${logAfter}`);

		// THE FIGHTER BOARDS STEP WITH THE CURSOR. The server resolves a whole round in
		// one go, so reading the boards off live state made every health bar jump to its
		// end-of-round value the moment the round landed, while the cards and the log
		// walked through it turn by turn. Both branches are asserted: if the round cost
		// somebody health the readouts MUST differ, and if it cost nobody any they must
		// not -- a one-sided check here would pass on a quiet round without proving
		// anything.
		// "To the end" is picked BY ITS TEXT, not by position: the control row is
		// [Back, Next turn / Finish turn, To the end] only while there is something
		// left to watch, and collapses to just [Back] once there is not -- so `.last()`
		// silently becomes Back on a two-turn round and both reads land on the same
		// turn. The middle button changes its own text mid-turn, which is a second
		// reason not to reach for it by position. It also has to be put BACK at the end
		// afterwards, because the next decision is deliberately held until the last
		// ACTION of the last turn is on screen, and leaving the cursor at turn 1
		// strands the whole BUILD step.
		const toEnd = async () => {
			const btn = page.locator(".rt-ctl", { hasText: "To the end" });
			if (await btn.count()) { await btn.first().click().catch(() => {}); await sleep(400); }
		};
		// Back and "To the end" REVIEW: they land on a turn already resolved rather
		// than replaying it, so neither needs settling for.
		const toStart = async () => {
			for (let i = 0; i < 12; i++) {
				const back = page.locator(".rt-ctl").first();
				if (await back.isDisabled().catch(() => true)) break;
				await back.click().catch(() => {});
				await sleep(150);
			}
		};
		// WHETHER the boards should differ between turn 1 and the end is not something the
		// round tally can answer: a round can spend all its health on turn 1 -- Protect the
		// Innocent's self-damage is a starting card, so it usually does -- and then the
		// board after turn 1 ALREADY is the end-of-round board, correctly. Gating on the
		// tally called that a failure. What settles it is the LOG, which now runs up to the
		// live turn: if it grows more health lines between turn 1 and the end, health moved
		// after turn 1 and the boards must move with it; if it does not, they must not.
		// Scoped to the LIVE round's section: archived rounds keep their own lines, and
		// counting those would make the two reads differ for a reason that is not this.
		const hpLines = async () => (await page.locator(".rt-log-live .rt-log-line").allInnerTexts()
			.catch(() => [])).filter((t) => /\b(takes|recovers)\s+\d+/.test(t)).length;
		await toEnd();
		const endHealth = await healthNow();
		const endHp = await hpLines();
		const tally = await page.locator(".rt-resolved").first().innerText().catch(() => "");
		await toStart();
		const startHealth = await healthNow();
		const startHp = await hpLines();
		check("the round tally is on screen at the end", tally.length > 0,
			`tally was "${tally.replace(/\n/g, " ")}"`);
		const movedLater = endHp > startHp;
		check(movedLater
			? "the boards show THIS turn, not the end of the round"
			: "the boards hold still when no health moves after turn 1",
			movedLater ? startHealth !== endHealth : startHealth === endHealth,
			`turn 1 "${startHealth}" (${startHp} hp lines) vs end "${endHealth}" `
			+ `(${endHp} hp lines); tally "${tally.replace(/\n/g, " ")}"`);
		await toEnd();

		// The detail modal. Right-click is the desktop half of the gesture
		// (shared/gestures.js); the touch half is a timer, because iOS Safari does
		// not fire `contextmenu` on a long press. What matters here is that the
		// gesture reaches a fighter AND a card, and that it does not also trigger
		// whatever the plain click on that element was wired to do.
		// ALL FOUR fighters on the board, not just the first. Every sentence in
		// this modal is GENERATED from op names, token ids and track ids, and every
		// one of those lookups has a fallback that renders the raw JSON key -- that
		// is how "+1 navigation", "Starts with 1 presence" and a legend entry whose
		// whole text was the word "icon" all shipped looking deliberate for months.
		// Which fighters are on the board is random, so sweeping the four is what
		// turns one sample into four; the checks below are written to hold for any
		// fighter, and the exhaustive per-roster gate is the Python
		// `games/rag_tag/tests/test_words.py`. This is the render-level half: a raw
		// key reaching the page through JSX rather than through a missing entry.
		const seenBoards = [];
		const boardFails = { leak: [], key: [], rate: [], head: [], dial: [], roster: [],
			profile: [] };
		// Which fighters get drafted is random, so the two CONDITIONAL checks below
		// (a ring must be drawn as one; a board with Characters must show them all)
		// see nothing at all unless Joan or the Fey Folk turn up. A conditional that
		// nothing reached is a green tick over an untested claim, so the run SAYS how
		// many boards each one actually looked at rather than leaving it to be
		// assumed. The unconditional checks above hold for all four every run.
		const exercised = { ring: 0, roster: 0, special: 0 };
		const nFighters = await page.locator(".rt-fighter").count();
		for (let i = 0; i < nFighters; i++) {
			await page.locator(".rt-fighter").nth(i).click({ button: "right" }).catch(() => {});
			await sleep(350);
			const who = await page.locator(".rt-modal h2").first().innerText().catch(() => "");
			if (!who) continue;
			seenBoards.push(who);
			const body = await page.locator(".rt-modal-body").first().innerText().catch(() => "");
			const leak = body.match(/\b[a-z]+_[a-z_]+\b/g) || [];
			if (leak.length) boardFails.leak.push(`${who}: ${leak.slice(0, 3).join()}`);
			// The key names only the kinds of space THIS board has, and each entry is
			// a sentence rather than a label -- the old one named all four kinds on
			// every board and its longest entry was one word.
			const rows = await page.locator(".rt-modal-key li").allInnerTexts().catch(() => []);
			if (!rows.length || !rows.every((t) => t.split(/\s+/).length > 4)) {
				boardFails.key.push(`${who}: ${JSON.stringify(rows.map((t) => t.slice(0, 18)))}`);
			}
			// Every board carries a complexity rating, so this one is never vacuous.
			// It rendered as the raw 1-5 beside "of 5 to learn" -- a scale the reader
			// has never been shown either end of. It is dots plus a WORD now, in the
			// rating block, so check the word is there and that no unexplained "N of
			// 5" survives anywhere in the panel. Match only the literal phrasing --
			// "N / 5" collides with the Fey Folk's honest "3 / 4 / 5 health".
			const cx = (await page.locator(".rt-modal .rt-rate-cx .rt-rate-n").first()
				.innerText().catch(() => "")).trim();
			const dots = await page.locator(".rt-modal .rt-rate-cx .rt-dot").count();
			if (!/^[A-Z][a-z]+$/.test(cx) || dots !== 5 || /\bof 5\b/.test(body)) {
				boardFails.rate.push(`${who}: "${cx}", ${dots} dots`);
			}
			// The Fighters' Guide half: an epithet, a paragraph, and five rating
			// bars. Every board has one, so this is never vacuous -- and it is the
			// only part of the modal that answers the question the DRAFT asks.
			const bars = await page.locator(".rt-modal .rt-rate").count();
			const blurb = (await page.locator(".rt-modal .rt-profile").first()
				.innerText().catch(() => "")).trim();
			if (bars !== 6 || blurb.length < 80) {
				boardFails.profile.push(`${who}: ${bars} bars, ${blurb.length}-char blurb`);
			}
			const heads = await page.locator(".rt-modal h3").allInnerTexts().catch(() => []);
			if (!heads.some((h) => /health track/i.test(h))
				|| await page.locator(".rt-modal .rt-strip .rt-cell").count() === 0) {
				boardFails.head.push(`${who}: ${JSON.stringify(heads)}`);
			}
			// CONDITIONAL, and that is the point: a fighter without a ring or without
			// Characters cannot fail these, but one WITH them cannot pass by omission
			// either. Joan's dial rendered as a row of boxes -- the one shape a ring
			// is not -- and the Fey Folk's three Characters had their health nowhere.
			const ringHd = await page.locator(".rt-special-hd", { hasText: "in a ring" }).count();
			if (ringHd > 0) {
				exercised.ring += 1;
				if (await page.locator(".rt-dial").count() === 0) boardFails.dial.push(who);
			}
			const tracks = await page.locator(".rt-modal-track-block").count();
			const onBoard = await page.locator(".rt-fighter").nth(i)
				.locator(".rt-rost").count();
			if (onBoard > 0) {
				exercised.roster += 1;
				if (onBoard !== tracks) {
					boardFails.roster.push(`${who}: ${onBoard} on the card, ${tracks} tracks`);
				}
			}
			await page.keyboard.press("Escape").catch(() => {});
			await sleep(150);
		}
		// A Fighter with a special track must DRAW it on the card. It used to be a
		// chip with an integer in it, which says where the marker is and nothing
		// about where it is going -- the whole point of a track. Conditional on the
		// draft, so it reports what it saw.
		const withTrack = await page.locator(".rt-fighter .rt-sp").count();
		exercised.special = withTrack;
		check("right-click opens the details of every fighter on the board",
			seenBoards.length === nFighters && nFighters === 4,
			`opened ${seenBoards.length} of ${nFighters}: ${JSON.stringify(seenBoards)}`);
		await page.locator(".rt-fighter").first().click({ button: "right" }).catch(() => {});
		await sleep(350);
		check("...and the details name its cards",
			await page.locator(".rt-modal-chip").count() > 0);
		check("...and none of them prints a raw data key", boardFails.leak.length === 0,
			JSON.stringify(boardFails.leak));
		check("...and each board key explains the kinds of space it draws",
			boardFails.key.length === 0, JSON.stringify(boardFails.key));
		check("...and each opens with a profile and five rated bars",
			boardFails.profile.length === 0, JSON.stringify(boardFails.profile));
		check("...and each rates the fighter in words, not on an unexplained scale",
			boardFails.rate.length === 0, JSON.stringify(boardFails.rate));
		check("...and each draws its health track under its own heading",
			boardFails.head.length === 0, JSON.stringify(boardFails.head));
		check("...and a track the panel calls a ring is DRAWN as one",
			boardFails.dial.length === 0, JSON.stringify(boardFails.dial));
		check("...and a fighter with Characters shows every one of them on its card",
			boardFails.roster.length === 0, JSON.stringify(boardFails.roster));
		// The two checks above are conditional, so they pass by DEFAULT on a board
		// that cannot fail them. While the draft was random this was reported and
		// left to the reader; with a seeded deal the draft is fixed, so a run that
		// reaches neither would report zero forever and nobody would look. The
		// draft above steers toward both — this is the half that fails if that ever
		// stops working, which is the only way the steering can be trusted.
		check("...and the two conditional board checks actually reached a board",
			exercised.ring > 0 && exercised.roster > 0,
			`boards opened: ${seenBoards.join(", ")} — ${exercised.ring} with a ring,`
			+ ` ${exercised.roster} with Characters (both must be > 0; if the seeded`
			+ ` draft stopped offering them, change GAMES_DEAL_SEED in this file)`);
		log(`  ..   boards opened: ${seenBoards.join(", ")}`
			+ ` (${exercised.ring} with a ring, ${exercised.roster} with Characters,`
			+ ` ${exercised.special} drawing a special track)`);
		await page.keyboard.press("Escape").catch(() => {});
		await sleep(300);
		check("Escape closes it", await page.locator(".rt-modal").count() === 0);

		await page.locator(".rt-card").first().click({ button: "right" }).catch(() => {});
		await sleep(400);
		const cardInfo = await page.locator(".rt-modal h2").first().innerText().catch(() => "");
		check("right-click on a played card opens its details", cardInfo.length > 0,
			`modal title was "${cardInfo}"`);
		const cardText = await page.locator(".rt-modal-body").first()
			.innerText().catch(() => "");
		const cardLeak = cardText.match(/\b[a-z]+_[a-z_]+\b/g) || [];
		check("...and the card text never prints a raw data key", cardLeak.length === 0,
			`leaked ${JSON.stringify(cardLeak.slice(0, 4))} in "${cardInfo}"`);
		check("...and it explains a mechanic the face does not",
			/how it works/i.test(cardText), `text was "${cardText.slice(0, 90)}"`);
		await page.locator(".rt-modal-close").click({ timeout: 5_000 }).catch(() => {});
		await sleep(300);
		check("the close button closes it", await page.locator(".rt-modal").count() === 0);

		// BUILD!: pick a card, pick a slot, lock it in.
		await page.waitForSelector(".rt-prompt h3", { timeout: 30_000 }).catch(() => {});
		const buildHd = await page.locator(".rt-prompt h3").first().innerText().catch(() => "");
		check("reached the BUILD! step", /Build/i.test(buildHd), `heading was "${buildHd}"`);
		const offered = await page.locator(".rt-prompt .rt-pick").count();
		check("three cards offered", offered === 3, `offered ${offered}`);

		// There is no disabled "Lock it in" any more: a grey slab with a button's
		// box read as the CTA you were waiting to be allowed to press. Until the
		// choice is complete the panel states the REQUIREMENT instead, and the
		// button does not exist at all.
		check("no button before the choice is complete",
			await page.locator(".rt-go").count() === 0);
		const needTxt = await page.locator(".rt-need").first().innerText().catch(() => "");
		check("the panel says what is still missing", /pick a card/i.test(needTxt),
			`said "${needTxt}"`);

		await page.locator(".rt-prompt .rt-pick").first().click().catch(() => {});
		await page.waitForSelector(".rt-drop", { timeout: 10_000 }).catch(() => {});
		const slots = await page.locator(".rt-slots .rt-drop").count();
		check("a labelled drop zone above, between and below every card",
			slots >= 3, `${slots} drop zones`);
		await page.locator(".rt-slots .rt-drop").first().click().catch(() => {});
		await page.locator(".rt-go").click({ timeout: 10_000 }).catch(() => {});

		// The round turns over, and the finished round stays in the log.
		await sleep(2500);
		const roundText = await page.locator(".rt-stage-hd .rt-round").first().innerText().catch(() => "");
		check("a second round began", /2/.test(roundText), `stage header was "${roundText}"`);
		// The log now includes the turn on the stage, so round 2 opens with a live
		// section already. Step one turn anyway and assert the PAIR: the finished
		// round kept, and the live one it is building beneath it.
		await page.locator(".rt-ctl-go").click({ timeout: 8_000 }).catch(() => {});
		await sleep(600);
		const rounds = await page.locator(".rt-log-round h4").allInnerTexts().catch(() => []);
		// ABANDON ASKS FIRST. Rag Tag fired it straight off the menu item, so the
		// click that opened the menu could end the fight; every other game confirms.
		// Driven rather than read because the whole point is the interaction: the
		// menu opens, the item opens a dialog, and BACKING OUT leaves you playing.
		await page.locator(".gm-btn").first().click({ timeout: 10_000 }).catch(() => {});
		await sleep(200);
		// The item's own text includes its icon span, so an anchored match misses
		// it. Select the menu item by class and filter on the label.
		const abItem = page.locator(".gm-item.gm-danger", { hasText: "Abandon game" }).first();
		const hasItem = await abItem.count() > 0;
		await abItem.click({ timeout: 5_000 }).catch(() => {});
		await sleep(250);
		const asked = await page.locator(".rt-confirm").count() > 0;
		check("abandoning asks before it ends the fight",
			hasItem && asked, `menu item ${hasItem}, dialog ${asked}`);
		// the danger action has to LOOK like one -- this variant was written above
		// the base rule at equal specificity and came out painted like Keep playing
		const dangerCol = await page.locator(".rt-confirm .rt-ctl-danger").first()
			.evaluate((e) => getComputedStyle(e).color).catch(() => "");
		check("...and the destructive button is painted as one",
			!!dangerCol && dangerCol !== await page.locator(".rt-confirm .rt-ctl:not(.rt-ctl-danger)")
				.first().evaluate((e) => getComputedStyle(e).color).catch(() => ""),
			`danger colour ${dangerCol}`);
		await page.locator(".rt-confirm .rt-ctl", { hasText: "Keep playing" }).first()
			.click({ timeout: 5_000 }).catch(() => {});
		await sleep(300);
		check("...and backing out leaves the fight running",
			await page.locator(".rt-confirm").count() === 0
			&& await page.locator(".rt-side").count() > 0);

		check("the log keeps the finished round and starts the live one",
			rounds.length >= 2 && /1/.test(rounds[0]), JSON.stringify(rounds));

		check("no page errors", errors.length === 0, errors[0]?.slice(0, 200) || "");
		await ctx.close();
	}

	// Orbit's hand is presentation-sorted by planet then printed cost, and the
	// deal is NOT seeded, so this is read off whatever was dealt rather than
	// compared against a fixed hand. Both keys come from the rendered face — the
	// planet from the card's own `or-<planet>` class (the colour IS the planet
	// here) and the cost from the price chip — so it checks what a player sees
	// rather than the array the component was handed.
	const OR_PLANETS = ["mercury", "venus", "terra", "mars", "jupiter"];
	async function orbitHandIsSorted(page, scope) {
		const cards = await page.evaluate(({ scope, planets }) =>
			[...document.querySelectorAll(`${scope} .or-agent`)].map((el) => ({
				planet: planets.findIndex((p) => el.classList.contains(`or-${p}`)),
				cost: Number(el.querySelector(".or-card-price b")?.textContent),
			})), { scope, planets: OR_PLANETS });
		// An EMPTY read is a failure (wrong scope, or a hand that did not render);
		// a one-card hand is trivially ordered and must not be reported as one.
		if (!cards.length) return false;
		if (cards.some((c) => c.planet < 0 || !Number.isFinite(c.cost))) return false;
		return cards.every((c, i) => i === 0
			|| c.planet > cards[i - 1].planet
			|| (c.planet === cards[i - 1].planet && c.cost >= cards[i - 1].cost));
	}

	// ── Orbit: real room, mulligan, one complete player action ────────────────
	async function orbitPlay(log) {
		const ctx = await browser.newContext({ viewport: { width: 1280, height: 960 } });
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "orbit-harness", name: "Orbiter", guest: true })));
		// EVERY SCREEN ORBIT PAINTS, IN ORDER, FROM THE FIRST FRAME. A one-frame
		// wrong screen is invisible to a `waitForSelector` — by the time anything
		// can be queried it is already gone — so the deep-link check below needs a
		// record kept as it happens rather than a state read afterwards.
		await ctx.addInitScript(() => {
			window.__orbitFrames = [];
			const tick = () => {
				const root = document.querySelector(".orbit");
				let painted = "none";
				if (root) {
					if (root.querySelector(".lby-cols, .lby-create-row")) painted = "LOBBY";
					else if (root.querySelector(".lby-loading")) painted = "connecting";
					else if (root.querySelector(".or-mulligan")) painted = "mulligan";
					else if (root.querySelector(".or-influence")) painted = "game";
					else if (root.querySelector(".or-wait")) painted = "waiting";
					else painted = "other";
				}
				const seen = window.__orbitFrames;
				if (!seen.length || seen[seen.length - 1] !== painted) seen.push(painted);
				requestAnimationFrame(tick);
			};
			requestAnimationFrame(tick);
		});
		const page = await ctx.newPage();
		let socket, latestFrame, fixtureMode = false;
		const fixtureReplies = [];
		await page.routeWebSocket("**/orbit/ws/**", (ws) => {
			socket = ws;
			const server = ws.connectToServer();
			ws.onMessage((message) => {
				if (fixtureMode) fixtureReplies.push(JSON.parse(String(message)));
				else server.send(message);
			});
			server.onMessage((message) => {
				const data = JSON.parse(String(message));
				if (data.room?.game) latestFrame = data;
				if (!fixtureMode) ws.send(message);
			});
		});
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		await page.goto(`http://localhost:${PORT}/orbit`, { waitUntil: "networkidle" });
		const lobby = await page.waitForSelector(".orbit .lby-create-row", { timeout: 25_000 })
			.then(() => true).catch(() => false);
		check("Orbit lobby is reachable", lobby);
		await page.locator(".lby-cta").click({ timeout: 10_000 }).catch(() => {});
		const modal = await page.waitForSelector(".cm-panel", { timeout: 10_000 })
			.then(() => true).catch(() => false);
		const opponentLabels = await page.locator(".cm-row").first().locator(".cm-seg-btn").allTextContents().catch(() => []);
		const difficultyLabels = await page.locator(".cm-row").nth(1).locator(".cm-seg-btn").allTextContents().catch(() => []);
		check("Orbit offers friend or AI with easy/normal/hard/expert difficulty", modal
			&& await page.locator(".cm-seg-btn").count() === 6
			&& JSON.stringify(opponentLabels) === JSON.stringify(["VS Friend", "VS AI"])
			&& JSON.stringify(difficultyLabels) === JSON.stringify(["Easy", "Normal", "Hard", "Expert"])
			&& await page.locator(".cm-hint").count() === 0
			&& !(await page.locator(".cm-panel").textContent()).includes("Technology board"),
			JSON.stringify({ opponentLabels, difficultyLabels }));
		const friendOpponent = page.locator(".cm-seg-btn", { hasText: "VS Friend" });
		const aiOpponent = page.locator(".cm-seg-btn", { hasText: "VS AI" });
		const easyDifficulty = page.locator(".cm-seg-btn", { hasText: "Easy" });
		const normalDifficulty = page.locator(".cm-seg-btn", { hasText: "Normal" });
		const hardDifficulty = page.locator(".cm-seg-btn", { hasText: "Hard" });
		await easyDifficulty.click({ timeout: 10_000 }).catch(() => {});
		check("Orbit can select the easy AI tier",
			await page.locator(".cm-summary b").textContent().catch(() => "") === "vs Easy AI");
		await normalDifficulty.click({ timeout: 10_000 }).catch(() => {});
		check("Orbit can select the normal AI tier",
			await page.locator(".cm-summary b").textContent().catch(() => "") === "vs Normal AI");
		await hardDifficulty.click({ timeout: 10_000 }).catch(() => {});
		check("Orbit can select the Hard AI tier",
			await page.locator(".cm-summary b").textContent().catch(() => "") === "vs Hard AI");
		await friendOpponent.click({ timeout: 10_000 }).catch(() => {});
		check("Orbit can switch to a friend game",
			await page.locator(".cm-summary b").textContent().catch(() => "") === "vs Friend"
			&& await page.locator(".cm-row").count() === 1);
		await aiOpponent.click({ timeout: 10_000 }).catch(() => {});
		await hardDifficulty.click({ timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-create").click({ timeout: 10_000 }).catch(() => {});

		const mulligan = await page.waitForSelector(".or-mulligan", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("a vs-AI room deals a four-card opening hand", mulligan
			&& await page.locator(".or-mulligan .or-agent").count() === 4);
		// THE OPENING MULLIGAN MARKS FOR REMOVAL, NOT FOR KEEPING. It reused the
		// hand's `.selected` treatment — lit, ringed, an accent bar along the top
		// edge — so the cards a first-time player had chosen to throw away were
		// the four brightest things on the first screen of their first game, in
		// the same language every other screen uses for "this is the card I am
		// playing". Assert the DIRECTION, not just the class: faded, pushed DOWN
		// (`.selected` lifts), and carrying neither the class nor the lit bar.
		const mulliganPick = page.locator(".or-mulligan .or-agent").first();
		await mulliganPick.click({ timeout: 10_000 }).catch(() => {});
		// `.or-agent` transitions transform and box-shadow over 140ms, and a
		// computed style read inside that window is a MIDPOINT — the first cut of
		// this check read dy 0 and a half-faded shadow and reported the rule as
		// not applying at all.
		await sleep(300);
		const marked = await page.evaluate(() => {
			const el = document.querySelector(".or-mulligan .or-agent.discarding");
			if (!el) return null;
			const cs = getComputedStyle(el);
			const dy = Number((cs.transform.match(/matrix\(([^)]*)\)/)?.[1] || "").split(",")[5]);
			return {
				opacity: Number(cs.opacity), dy, boxShadow: cs.boxShadow,
				alsoSelected: el.classList.contains("selected"),
				tagged: !!el.querySelector(".or-discard-tag"),
				discarding: document.querySelectorAll(".or-mulligan .or-agent.discarding").length,
				highlighted: document.querySelectorAll(".or-mulligan .or-agent.selected").length,
			};
		});
		check("a mulligan pick reads as removal — faded and pushed down, never lit and lifted",
			!!marked && marked.opacity < 0.75 && marked.dy > 0 && !marked.alsoSelected
			&& marked.boxShadow === "none" && marked.tagged
			&& marked.discarding === 1 && marked.highlighted === 0, JSON.stringify(marked));
		if (process.env.ORBIT_SHOTS) {
			// The opening mulligan with one card marked — the frame a visual review
			// has to see, because "faded" is a comparison against the cards beside
			// it and a default board shows neither state.
			await page.screenshot({ path: "test-results/orbit-mulligan-marked.png", fullPage: true });
		}
		await mulliganPick.click({ timeout: 10_000 }).catch(() => {});
		await sleep(300);
		check("un-marking a mulligan pick puts it back",
			await page.locator(".or-mulligan .or-agent.discarding").count() === 0
			&& Number(await mulliganPick.evaluate((el) => getComputedStyle(el).opacity)) === 1);
		// The hand is SORTED, so this holds for whatever four Agents were dealt —
		// which is the only kind of assertion Orbit's unseeded deal can carry.
		check("the opening hand is ordered by planet, then by cost",
			await orbitHandIsSorted(page, ".or-mulligan"));
		await page.locator(".or-mulligan .or-primary").click({ timeout: 10_000 }).catch(() => {});
		const board = await page.waitForSelector(".or-influence", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("the five-planet and three-track boards render", board
			&& await page.locator(".or-track").count() === 5
			&& await page.locator(".or-tech-col").count() === 3);
		check("the Orbit banner shows the game name without the room id",
			(await page.locator(".or-game .lby-title").textContent().catch(() => "")).trim() === "Orbit");

		// A DEEP LINK NEVER PAINTS THE LOBBY FIRST. Opening /orbit/<room> — which
		// is what a player gets when a game is already open and they come back
		// through the sign-in screen — used to render one full frame of the LOBBY
		// before the resume effect ran: `connecting` started false and was set in
		// a `useEffect`, which runs AFTER paint, so the first frame satisfied
		// `screen === "lobby" && !connecting` and drew the whole lobby on top of
		// a game in progress. Measured at 13ms, which is long enough to see and
		// far too short for any selector-based check to catch, hence the frame
		// recorder above. The URL is known before React renders anything, so the
		// first frame is the "Connecting…" panel it was always meant to be.
		const roomUrl = page.url();
		check("a game deep link is a room URL", /\/orbit\/[A-Z0-9]+$/.test(roomUrl), roomUrl);
		await page.reload({ waitUntil: "domcontentloaded" });
		await page.waitForSelector(".or-influence", { timeout: 30_000 }).catch(() => {});
		const painted = await page.evaluate(() => window.__orbitFrames || []);
		check("a deep link resumes the game without flashing the lobby",
			painted.length > 0 && !painted.includes("LOBBY") && painted.includes("game"),
			JSON.stringify(painted));
		const influenceCopy = await page.locator(".or-influence").textContent();
		check("the influence board omits the redundant planet control heading",
			!influenceCopy.includes("Planet control") && await page.locator(".or-influence-head").count() === 0,
			influenceCopy.slice(0, 120));

		// WHOSE IS IT. Both rails carry a Leader chip (including the "No badge"
		// state — it used to render only under its owner, so no badge and no chip
		// looked the same), and the technology board names both seats in its key
		// rather than printing two unlabelled pips.
		const seating = await page.evaluate(() => ({
			badges: [...document.querySelectorAll(".or-player .or-leader")].map((el) => el.textContent.trim()),
			key: [...document.querySelectorAll(".or-tech-key b")].map((el) => el.textContent.trim()),
			mine: document.querySelectorAll(".or-player.mine .or-played-agents").length,
			glyphs: /[☿♀⊕♂♃]/.test(document.querySelector(".or-table").textContent),
		}));
		check("both seats show a Leader badge state and are named on the tech key",
			seating.badges.length === 2 && seating.badges.every((text) => text.length > 0)
			&& seating.key.length === 2 && seating.mine === 1 && !seating.glyphs,
			JSON.stringify(seating));

		// A technology bonus token sits on the LEVEL-2 space of its own track,
		// which is the space that pays it, and opens its effect when pressed.
		const tokens = await page.evaluate(() => [...document.querySelectorAll(".or-tech-col")]
			.map((col) => {
				const rows = [...col.querySelectorAll(".or-tech-row")];
				const withToken = rows.findIndex((row) => row.querySelector(".or-tech-token"));
				return withToken < 0 ? null : rows[withToken].querySelector(".or-tech-lv").textContent.trim();
			}));
		check("each technology track's bonus token sits on its level-2 space",
			tokens.length === 3 && tokens.every((level) => level === "2"), JSON.stringify(tokens));

		// FIVE SPACES, ALL THE SAME SIZE. A `min-height` let each space grow to
		// its own text and the ladder came out visibly ragged; and the seat marker
		// belongs ON the level a player is at, not in a sixth "level 0" row bolted
		// under the track. Both are geometry, so both are checkable.
		const ladder = await page.evaluate(() => {
			const cols = [...document.querySelectorAll(".or-tech-col")];
			const heights = new Set();
			const levels = cols.map((col) => [...col.querySelectorAll(".or-tech-lv")]
				.map((el) => el.textContent.trim()).join(""));
			for (const el of document.querySelectorAll(".or-tech-space")) {
				heights.add(Math.round(el.getBoundingClientRect().height));
			}
			return { levels, heights: [...heights] };
		});
		check("every technology track is the same five spaces, 5 down to 1",
			ladder.levels.length === 3 && ladder.levels.every((seq) => seq === "54321"),
			JSON.stringify(ladder.levels));
		check("...and every space on them is exactly the same height",
			ladder.heights.length === 1, JSON.stringify(ladder.heights));
		const techText = await page.evaluate(() => [...document.querySelectorAll(".or-tech-text")].map((el) => {
			const style = getComputedStyle(el);
			return { lines: style.webkitLineClamp, align: style.alignSelf };
		}));
		check("desktop technology descriptions use the complete rung without a line clamp",
			techText.length === 15 && techText.every(({ align }) => align === "center"),
			JSON.stringify(techText));
		await page.locator(".or-tech-token").first().click({ timeout: 10_000 }).catch(() => {});
		const tokenInfo = await page.evaluate(() => {
			const panel = document.querySelector(".or-info");
			return panel ? panel.textContent.replace(/\s+/g, " ").trim() : "";
		});
		check("pressing a bonus token opens a modal naming its effect",
			/bonus token/i.test(tokenInfo) && /(Credits|Zenithium|influence|Leader|Mobilize|Exile|Transfer)/.test(tokenInfo),
			tokenInfo.slice(0, 120));
		await page.keyboard.press("Escape").catch(() => {});
		await page.waitForSelector(".or-info", { state: "detached", timeout: 5_000 }).catch(() => {});

		// Seating is random, so wait through the bot's opening action. A PLAYABLE
		// hand card is the server's legal-move list arriving at this seat. It is
		// `.playable`, not `:not(:disabled)`: a card you cannot play is still one
		// you can open and read, so no hand card is ever disabled any more.
		const card = page.locator(".or-hand-zone .or-agent.playable").first();
		const gotTurn = await card.waitFor({ state: "visible", timeout: 30_000 })
			.then(() => true).catch(() => false);
		check("the random opponent yields a legal player turn", gotTurn);
		if (gotTurn) await card.click().catch(() => {});
		const actionCopy = await page.locator(".or-action-bar button").allTextContents().catch(() => []);
		check("all three card uses show their exact price or faction",
			actionCopy.length === 3
			&& actionCopy.some((text) => text.includes("Credits"))
			&& actionCopy.some((text) => text.includes("Zenithium"))
			&& actionCopy.some((text) => text.includes("Leader")),
			JSON.stringify(actionCopy));
		check("the Become Leader use names its faction bonus",
			actionCopy.some((text) => /Become Leader · \w+ \(gain 1 Zenithium\)|Become Leader · \w+ \(gain 3 Credits\)|Become Leader · \w+ \(mobilize 2\)/.test(text)),
			JSON.stringify(actionCopy));
		// STEERED to Recruit, and asserted below rather than sampled: the deal is
		// seeded, so "some games recruit" would be "this game never recruits" for
		// good, and the placed-Agent panel is exactly what the phone checks read.
		const recruit = page.locator(".or-action-bar button:not(:disabled)", { hasText: "Recruit" });
		const action = await recruit.count().catch(() => 0)
			? recruit.first() : page.locator(".or-action-bar button:not(:disabled)").first();
		const actionReady = await action.waitFor({ state: "visible", timeout: 10_000 })
			.then(() => true).catch(() => false);
		check("a selected Agent offers a server-legal action", actionReady);
		const logBefore = await page.locator(".or-log p").count().catch(() => 0);
		if (actionReady) await action.click().catch(() => {});

		// Some Agent/technology programs ask several questions. Answer every one
		// until the turn passes; this is the reconnect-safe generic decision path.
		for (let i = 0; i < 12; i++) {
			const choice = page.locator(".or-decision button").first();
			if (!await choice.count().catch(() => 0)) break;
			await choice.click().catch(() => {});
			await sleep(120);
		}
		await page.waitForFunction((n) => document.querySelectorAll(".or-log p").length > n,
			logBefore, { timeout: 20_000 }).catch(() => {});
		const logAfter = await page.locator(".or-log p").count().catch(() => 0);
		check("the action resolves and is broadcast into the log", logAfter > logBefore,
			`${logBefore} -> ${logAfter}`);

		// THE LOG NARRATES, IT DOES NOT JUST NAME THE CARD. A real turn has to
		// have written down where the disc went, what the play cost and who drew
		// what — the whole point of the entry being a list of parts rather than
		// one sentence. Asserted against a SEEDED deal, so these are properties
		// any Orbit turn has, never this particular hand's.
		const narration = await page.evaluate(() => {
			const lines = [...document.querySelectorAll(".or-log p")].map((p) => p.textContent);
			const all = lines.join("\n");
			return {
				lines: lines.length,
				turnMarks: document.querySelectorAll(".or-log-line.turn-start").length,
				seated: document.querySelectorAll(".or-log-line.mine, .or-log-line.theirs").length,
				refs: document.querySelectorAll(".or-log-ref").length,
				disc: /influence on .+ the disc moves/i.test(all),
				draw: /draws \d+ Agent/i.test(all),
				money: /(Credits|Zenithium)/.test(all),
			};
		});
		check("the log narrates disc movement, resources and the end-of-turn draw",
			narration.disc && narration.draw && narration.money && narration.turnMarks >= 2,
			JSON.stringify(narration));
		check("...and marks whose action each line was", narration.seated > 0, JSON.stringify(narration));
		// A NAME IN THE LOG IS A DOOR. Pressing an Agent named in a past entry
		// opens the very same detail modal the table opens, so reading back is
		// never "which card was that?".
		check("the log names Agents as pressable references", narration.refs > 0,
			JSON.stringify(narration));
		if (narration.refs > 0) {
			await page.locator(".or-log-card").first().click({ timeout: 10_000 }).catch(() => {});
			const fromLog = await page.evaluate(() => {
				const panel = document.querySelector(".or-info");
				return panel ? { eyebrow: panel.querySelector(".or-eyebrow")?.textContent.trim(),
					cost: panel.querySelectorAll(".or-info-cost").length,
					defs: panel.querySelectorAll(".or-info-defs dt").length,
					defsHeading: panel.querySelector(".or-info-defs h3")?.textContent.trim(),
					usesNote: /one card, three uses/i.test(panel.textContent || "") } : null;
			});
			check("pressing a card named in the log opens that Agent's card",
				!!fromLog && /agent/i.test(fromLog.eyebrow || "") && fromLog.cost === 1,
				JSON.stringify(fromLog));
			// EVERY term the printed sentence uses is defined under it. Checked on
			// whatever card the seeded game happened to play, because the property
			// holds for all 90: no rules string in the game matches zero entries.
			check("...with its rules jargon explained beneath the printed text",
				!!fromLog && fromLog.defs > 0, JSON.stringify(fromLog));
			check("...with a Keywords heading and no three-use note",
				!!fromLog && fromLog.defsHeading === "Keywords" && !fromLog.usesNote,
				JSON.stringify(fromLog));
			await page.keyboard.press("Escape").catch(() => {});
			await page.waitForSelector(".or-info", { state: "detached", timeout: 5_000 }).catch(() => {});
		}
		const geometry = await page.evaluate(() => {
			const influence = document.querySelector(".or-influence").getBoundingClientRect();
			const jupiter = document.querySelector(".or-track.or-jupiter").getBoundingClientRect();
			return {
				wide: document.documentElement.scrollWidth > window.innerWidth + 1,
				cards: document.querySelectorAll(".or-hand-zone .or-agent").length,
				// TEN CELLS, FIVE PER SEAT, AT EVERY WIDTH. There used to be two
				// treatments of this one fact — a pair of full-width panels below
				// the influence board on a tall desktop, and five counts folded
				// into the player boxes everywhere else — which is why this gate
				// carried a "never both at once" check. There is one treatment now.
				played: document.querySelectorAll(".or-played-agent").length,
				visiblePlayed: [...document.querySelectorAll(".or-played-agent")]
					.filter((el) => el.getBoundingClientRect().width > 0).length,
				retiredPanels: document.querySelectorAll(".or-columns, .or-slot").length,
				jupiterGap: Math.round(influence.bottom - jupiter.bottom),
				detachedStackControls: document.querySelectorAll(".or-stack").length,
			};
		});
		check("the complete public table and private hand remain on the page",
			!geometry.wide && geometry.cards > 0 && geometry.played === 10,
			JSON.stringify(geometry));
		check("the planet panel ends cleanly after its tracks",
			geometry.jupiterGap >= 0 && geometry.jupiterGap <= 24, JSON.stringify(geometry));
		check("placed Agents use one card-stack face, not a detached stack control",
			geometry.detachedStackControls === 0, JSON.stringify(geometry));
		check("placed Agents live in the player box at every width, with no second treatment",
			geometry.visiblePlayed === 10 && geometry.retiredPanels === 0, JSON.stringify(geometry));
		// THE FACE IS THE NAME, THE COUNT AND THE TOP AGENT'S COST — and nothing
		// else. The cost is there because the RULES read it: `card_cost` pays
		// Credits equal to the printed cost of the Agent an effect exiles,
		// transfers or discards, and both seats' column tops are the pool those
		// effects draw from, so answering "what does taking their Mars top pay?"
		// used to mean opening a modal per column mid-decision. The faction glyph
		// and the rules sentence stay OUT: a full card face in a 30px box is the
		// treatment this row replaced, so the check bounds it from both sides.
		// An EMPTY planet keeps its cell — collapsing it would break the column
		// alignment the row exists for — and shows neither a name nor a zero.
		const placedFaces = await page.evaluate(() => {
			const cells = [...document.querySelectorAll(".or-played-agent")];
			const filled = cells.filter((cell) => !cell.classList.contains("empty"));
			const box = (el) => el.getBoundingClientRect();
			return {
				cells: cells.length,
				filled: filled.length,
				extraFacts: document.querySelectorAll(".or-played-agent .or-agent-text, .or-played-agent .or-agent-foot").length,
				coins: filled.filter((cell) => cell.querySelector(".or-played-cost .or-resource-icon.credits")).length,
				quantities: filled.filter((cell) => /^×[0-9]+$/.test(cell.querySelector(".or-played-quantity")?.textContent || "")).length,
				complete: filled.every((cell) => !!cell.querySelector(".or-played-name")?.textContent.trim()
					&& /^[0-9]+$/.test(cell.querySelector(".or-played-count")?.textContent.trim() || "")),
				costs: filled.map((cell) => cell.querySelector(".or-played-cost")?.textContent.trim()),
				emptyQuiet: cells.filter((cell) => cell.classList.contains("empty"))
					.every((cell) => !cell.querySelector(".or-played-count")),
				// The price takes its width out of the NAME's, so the thing to
				// guard is what is left for the name — a face reduced to two
				// letters and an ellipsis is not a name, and the single clipped
				// line means it fails silently rather than growing.
				nameWidth: Math.min(...filled.map((cell) => Math.round(box(cell.querySelector(".or-played-name")).width))),
				// A price that overflows its own cell is worse than no price: it
				// is the one addition to this box that can push the name out.
				spills: filled.filter((cell) => {
					const cost = cell.querySelector(".or-played-cost");
					return !cost || box(cost).right > box(cell).right + 1
						|| box(cost).bottom > box(cell).bottom + 1;
				}).length,
				// ...AND BY HOW MUCH IT FITS. A 1px tolerance rates "fits by
				// 0.69px" and "fits" the same, and that is exactly how the 320px
				// cell shipped: green here, 2px over on the runner's wider fonts.
				// The margin has to clear a real font difference, not a hair.
				costClear: Math.min(...filled.map((cell) => {
					const cost = cell.querySelector(".or-played-cost");
					return cost ? box(cell).right - box(cost).right : Infinity;
				})),
			};
		});
		check("a played Agent shows its name and top cost beside its stack count",
			placedFaces.cells === 10 && placedFaces.filled > 0 && placedFaces.extraFacts === 0
			&& placedFaces.coins === placedFaces.filled && placedFaces.quantities === placedFaces.filled
			&& placedFaces.complete && placedFaces.emptyQuiet && placedFaces.nameWidth >= 44
			&& placedFaces.costs.every((c) => /^[0-9]+$/.test(c || ""))
			&& placedFaces.spills === 0 && placedFaces.costClear >= 2,
			JSON.stringify(placedFaces));

		// THE ROW IS THE PLANET BOARD'S OWN EDGE — one cell per planet, on the
		// same five columns, so a stack sits directly under (yours) or over
		// (theirs) the track it belongs to. That adjacency is the ONLY label the
		// row has, which makes it a geometry contract rather than a preference:
		// `.or-influence` and `.or-played-agents` have to resolve the same inline
		// padding and the same gutter (`--or-board-pad` / `--or-board-gap`), and
		// a tier that restates one without the other reads fine at Mercury and
		// drifts half a cell by Jupiter. Measured against the TRACK COLUMN's
		// centre, not the disc's: on a phone the bonus token takes a sub-column
		// beside the track, so the disc is deliberately off-centre within it.
		const alignment = await page.evaluate(() => {
			const centre = (el) => { const b = el.getBoundingClientRect(); return b.left + b.width / 2; };
			const tracks = [...document.querySelectorAll(".or-influence .or-track")].map(centre);
			return [...document.querySelectorAll(".or-player")].map((rail) => {
				const cells = [...rail.querySelectorAll(".or-played-agent")].map(centre);
				return { cells: cells.length, drift: Math.round(Math.max(...cells.map((c, i) => Math.abs(c - tracks[i])))) };
			});
		});
		check("each seat's played Agents sit on the planet board's own five columns",
			alignment.length === 2 && alignment.every((rail) => rail.cells === 5 && rail.drift <= 4),
			JSON.stringify(alignment));
		check("your hand is ordered by planet, then by cost",
			await orbitHandIsSorted(page, ".or-hand-zone"));
		// Stress the presentation through a room update, after the real action.
		// Fixture moves are never sent to the server.
		fixtureMode = true;
		const fixture = structuredClone(latestFrame);
		fixture.type = "room_update";
		const gameView = fixture.room.game;
		const self = gameView.players["orbit-harness"];
		while (self.hand.length < 6) self.hand.push({ ...self.hand[0], id: 1000 + self.hand.length });
		self.columns[self.hand[0].planet] = [self.hand[0], self.hand[1]];
		for (const player of Object.values(gameView.players)) player.technology.robot = 1;
		gameView.leader = { owner: "orbit-harness", level: 2 };
		// Both hand-limit cases on one frame: the Gold badge holder at 6 of 6, and
		// the badge-less seat holding 5 against a limit of 4, which is legal.
		const opponent = Object.entries(gameView.players).find(([id]) => id !== "orbit-harness")[1];
		opponent.hand = Array.from({ length: 5 }, () => ({ hidden: true }));
		gameView.pending = null;
		gameView.pending_pid = null;
		gameView.turn_pid = "orbit-harness";
		gameView.legal_moves = [{ action: "recruit", card_id: self.hand[0].id }];
		gameView.log = Array.from({ length: 80 }, (_, i) => ({ turn: i + 1, message: `History ${i + 1}: Orbiter gains influence on Mercury.` }));
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction(() => document.querySelectorAll(".or-log p").length === 80);
		// Every player box and the hand header use the same `N / N cards` shape,
		// including when a hand is exactly at its limit. All THREE shapes are
		// steered onto frames rather than sampled, because the seeded deal would
		// otherwise park one of them at "never" for good.
		const readCounters = () => page.evaluate(() => ({
			rails: [...document.querySelectorAll(".or-player")].map((rail) => ({
				badge: rail.querySelector(".or-leader").textContent.trim(),
				cards: rail.querySelector(".or-hand-count").textContent.replace(/\s+/g, " ").trim(),
			})),
			hand: document.querySelector(".or-player.mine .or-hand-count").textContent.replace(/\s+/g, " ").trim(),
			duplicateHeader: !!document.querySelector(".or-hand-head"),
			legacy: document.querySelector(".or-log p").textContent.includes("History 1"),
		}));
		const counters = await readCounters();
		check("the player box owns the hand count, with no duplicate hand heading", !counters.duplicateHeader);
		const badged = counters.rails.find((rail) => /gold/i.test(rail.badge));
		const plain = counters.rails.find((rail) => /no badge/i.test(rail.badge));
		// AT the limit: both counts include the limit so the two player boxes have
		// the same readable contract.
		check("a seat sitting at its hand limit prints the count and ratio",
			!!badged && badged.cards === "6 / 6 cards" && counters.hand === "6 / 6 cards",
			JSON.stringify(counters));
		// ABOVE it: the ratio remains the same compact contract; the tint and title
		// still explain that the hand is legally over its limit.
		check("...a seat over its limit still shows the count and ratio",
			!!plain && plain.cards === "5 / 4 cards", JSON.stringify(counters));
		// BELOW it, mid-turn: the ratio says how many come back at end of turn.
		self.hand = self.hand.slice(0, 4);
		gameView.legal_moves = [{ action: "recruit", card_id: self.hand[0].id }];
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction(() => document.querySelectorAll(".or-hand-zone .or-agent").length === 4);
		const below = await readCounters();
		check("...and a seat below it shows the limit it will draw back up to",
			below.hand === "4 / 6 cards", JSON.stringify(below));
		// Restore the six-card frame the rest of this block is written against.
		while (self.hand.length < 6) self.hand.push({ ...self.hand[0], id: 1000 + self.hand.length });
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction(() => document.querySelectorAll(".or-hand-zone .or-agent").length === 6);
		check("a log entry written before the parts format still renders",
			counters.legacy, JSON.stringify(counters.legacy));
		await page.locator(".or-hand-zone .or-agent").first().click();
		const selectedStyle = await page.locator(".or-hand-zone .or-agent.selected").first().evaluate((el) => ({
			planet: [...el.classList].find((name) => ["or-mercury", "or-venus", "or-terra", "or-mars", "or-jupiter"].includes(name)),
			color: getComputedStyle(el).color,
			outline: getComputedStyle(el).outlineColor,
			border: getComputedStyle(el).borderTopColor,
		}));
		check("a selected card is highlighted in its planet color",
			!!selectedStyle.planet && selectedStyle.color === selectedStyle.outline
			&& selectedStyle.color === selectedStyle.border, JSON.stringify(selectedStyle));
		const stacked = ".or-played-agent:not(.empty)";
		for (const selector of [".or-hand-zone .or-agent", ".or-influence button.or-bonus", ".or-tech-token", ".or-tech-space", stacked]) {
			await page.locator(selector).first().click({ button: "right" });
			check(`right-click opens details for ${selector}`, await page.locator(".or-info").isVisible());
			await page.keyboard.press("Escape");
		}
		await page.locator(stacked).first().click({ button: "right" });
		await page.locator(".or-info-list button").first().click({ button: "right" });
		check("right-click opens an Agent within a column", await page.locator(".or-info-cost").count() === 1);
		await page.keyboard.press("Escape");
		await page.locator(".or-log > div").evaluate((el) => { el.scrollTop = 0; });
		gameView.log.push({ turn: 81, message: "Newest move stays visible" });
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction(() => document.querySelectorAll(".or-log p").length === 81);
		check("a new log entry scrolls to the latest move", await page.locator(".or-log > div").evaluate(
			(el) => el.scrollHeight > el.clientHeight && Math.abs(el.scrollHeight - el.clientHeight - el.scrollTop) <= 2));
		const checkTrackPresentation = async (label) => {
			const trackStyle = await page.evaluate(() => {
				const goalsExtend = [...document.querySelectorAll(".or-track-spaces")].every((track) => {
					const r = track.getBoundingClientRect();
					const goals = [...track.querySelectorAll(".goal")];
					const line = getComputedStyle(track, "::before");
					const vertical = parseFloat(line.borderLeftWidth) > 0 && parseFloat(line.borderTopWidth) === 0;
					const horizontal = parseFloat(line.borderTopWidth) > 0 && parseFloat(line.borderLeftWidth) === 0;
					const centers = goals.map((el) => {
						const box = el.getBoundingClientRect();
						return { x: box.left + box.width / 2, y: box.top + box.height / 2 };
					});
					const lineBox = vertical
						? { start: r.top + r.height / 18, end: r.bottom - r.height / 18 }
						: { start: r.left + r.width / 18, end: r.right - r.width / 18 };
					return line.content !== "none" && (vertical || horizontal)
						&& (vertical
							? centers[0].y <= lineBox.start + 3 && centers[1].y >= lineBox.end - 3
							: centers[0].x <= lineBox.start + 3 && centers[1].x >= lineBox.end - 3);
				});
				const occupied = document.querySelector(".or-tech-space.mine.theirs");
				const vacant = document.querySelector(".or-tech-space:not(.mine):not(.theirs)");
				const middle = [...document.querySelectorAll(".or-space.middle")]
					.map((el) => getComputedStyle(el, "::before"))
					.map((style) => ({ width: parseFloat(style.width), height: parseFloat(style.height) }));
				const regular = [...document.querySelectorAll(".or-space:not(.middle):not(.goal)")]
					.map((el) => getComputedStyle(el, "::before"))
					.map((style) => ({ width: parseFloat(style.width), height: parseFloat(style.height) }));
				return { goalsExtend, dots: occupied.querySelectorAll(".or-tech-seats i").length,
					noGlow: getComputedStyle(occupied).boxShadow === "none"
						&& getComputedStyle(occupied).borderColor === getComputedStyle(vacant).borderColor,
					middle: middle.length === 5 && middle.every(({ width, height }) => width > regular[0].width && height > regular[0].height) };
			});
			check(`${label}: track lines stop at both goal spots and technology uses dots without side lighting`,
				trackStyle.goalsExtend && trackStyle.dots === 2 && trackStyle.noGlow && trackStyle.middle, JSON.stringify(trackStyle));
		};
		await checkTrackPresentation("Desktop");
		// The desktop targets are product sizes, not incidental screenshots.
		// At 2560 the shared page measure used to put the menu/name more than 500px
		// from their edges; at 1920 the board ran about 160px below the fold. Keep
		// both contracts measurable while the compact board evolves.
		for (const viewport of [{ width: 2560, height: 1600 }, { width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 1280, height: 800 }, { width: 1024, height: 768 }]) {
			await page.setViewportSize(viewport);
			await sleep(200);
			const desktop = await page.evaluate(() => {
				const hand = document.querySelector(".or-hand-zone").getBoundingClientRect();
				const logBox = document.querySelector(".or-log").getBoundingClientRect();
				const cards = [...document.querySelectorAll(".or-hand-zone .or-agent")].map((el) => el.getBoundingClientRect());
				const menu = document.querySelector(".lby-head-left .gm-btn").getBoundingClientRect();
				const user = document.querySelector(".lby-head-right").getBoundingClientRect();
				const techHeights = [...document.querySelectorAll(".or-tech-space")]
					.map((el) => Math.round(el.getBoundingClientRect().height));
				const slotHeights = [...document.querySelectorAll(".or-played-agent")]
					.map((el) => Math.round(el.getBoundingClientRect().height));
				const influence = document.querySelector(".or-influence").getBoundingClientRect();
				const other = document.querySelector(".or-player.theirs").getBoundingClientRect();
				const mine = document.querySelector(".or-player.mine").getBoundingClientRect();
				const verticalTracks = [...document.querySelectorAll(".or-track")].every((row) => {
					const track = row.querySelector(".or-track-spaces").getBoundingClientRect();
					const token = row.querySelector(".or-bonus").getBoundingClientRect();
					return track.height > track.width && token.left > track.right && token.left - track.right < 35;
				});
				return {
					verticalTable: verticalTracks && other.bottom <= influence.top && mine.top >= influence.bottom,
					wide: document.documentElement.scrollWidth > innerWidth + 1,
					tall: document.documentElement.scrollHeight > innerHeight + 1,
					scrollHeight: document.documentElement.scrollHeight,
					menuLeft: Math.round(menu.left),
					userRight: Math.round(user.right),
					viewportWidth: innerWidth,
					techHeights: [...new Set(techHeights)],
					maxSlotHeight: Math.max(...slotHeights),
					logBottom: logBox.bottom,
					handBottom: hand.bottom,
					logBesideHand: logBox.left >= hand.right,
					sixFit: cards.length === 6 && cards.every((r) => r.left >= hand.left && r.right <= hand.right),
					uniformCards: Math.max(...cards.map((r) => r.width)) - Math.min(...cards.map((r) => r.width)) < 1,
					hint: document.querySelector(".or-player.mine .or-player-hint")?.textContent.trim(),
					handSubhead: document.querySelectorAll(".or-hand-head h2").length,
					// THE THREE PANELS THAT COMPETE FOR ONE COLUMN OF HEIGHT, and
					// the reason all three are measured together: the technology
					// ladder, the log and the planet board were each sized in
					// isolation and the sum was whatever it came out to. Pinning
					// the log at a fixed height and stretching technology cropped
					// LEVELS 1 AND 2 off the bottom of every track (rungs are
					// `minmax(0, 1fr)`, the text inside them is not, and `.or-tech`
					// is `overflow: hidden`); the board then took what was left,
					// which at 1920x937 was its 240px floor. So: nothing clipped,
					// a log worth reading, and a board that gets the give.
					techClipped: (() => {
						const panel = document.querySelector(".or-tech").getBoundingClientRect();
						return [...document.querySelectorAll(".or-tech-space")]
							.filter((el) => el.getBoundingClientRect().bottom > panel.bottom + 1)
							.map((el) => el.querySelector(".or-tech-lv")?.textContent.trim());
					})(),
					logHeight: Math.round(logBox.height),
					influenceHeight: Math.round(document.querySelector(".or-influence").getBoundingClientRect().height),
				};
			});
			check(`Orbit fills ${viewport.width}x${viewport.height} without page scrolling`,
				!desktop.wide && !desktop.tall, JSON.stringify(desktop));
			check(`desktop ${viewport.width}px follows the phone's vertical table with nearby bonuses`, desktop.verticalTable, JSON.stringify(desktop));
			check(`the log ends with the play area beside six equal cards at ${viewport.width}px`,
				desktop.logBesideHand && Math.abs(desktop.logBottom - desktop.handBottom) <= 2
				&& (viewport.width < 1500 || desktop.sixFit) && desktop.uniformCards, JSON.stringify(desktop));
			check(`the ${viewport.width}px game header reaches both screen edges`,
				desktop.menuLeft <= 22 && desktop.userRight >= desktop.viewportWidth - 22,
				JSON.stringify(desktop));
			check(`technology gets taller readable rungs and placed-Agent rows stay compact at ${viewport.width}px`,
				desktop.techHeights.length <= 2 && desktop.techHeights[0] >= 46
				&& desktop.maxSlotHeight <= 40, JSON.stringify(desktop));
			check(`every technology rung stays inside its panel at ${viewport.width}px`,
				desktop.techClipped.length === 0, JSON.stringify(desktop));
			// The floor is TIERED because the budget is: a 768px-tall window has
			// ~700px for a header-less table, of which the hand and its reserved
			// control strip take a fixed 300. The numbers are what the layout can
			// actually deliver once technology is content-sized and the log takes
			// the remainder — 203px of track at 1366x768 against 154 before, 479
			// at 1920x1080 against 354 — so they catch the squeeze coming back
			// rather than describing an ideal nothing reaches.
			check(`the log and the planet board both get a readable share at ${viewport.width}px`,
				desktop.logHeight >= 240 && desktop.influenceHeight >= (viewport.height >= 1000 ? 300 : 195),
				JSON.stringify(desktop));
			check("the turn hint lives beside your player name, not above the hand",
				!!desktop.hint && desktop.handSubhead === 0,
				JSON.stringify(desktop));
			if (process.env.ORBIT_SHOTS) {
				await page.screenshot({ path: `test-results/orbit-${viewport.width}x${viewport.height}-after.png`, fullPage: true });
			}
		}
		await page.setViewportSize({ width: 390, height: 844 });
		await sleep(250);
		const phone = await page.evaluate(() => {
			const inside = (el) => {
				const r = el.getBoundingClientRect();
				return r.left >= -1 && r.right <= window.innerWidth + 1;
			};
			const sections = [...document.querySelectorAll(
				".or-influence, .or-tech, .or-score-rail, .or-hand-zone, .or-decision")];
			const other = document.querySelector(".or-player.theirs").getBoundingClientRect();
			const influence = document.querySelector(".or-influence").getBoundingClientRect();
			const mine = document.querySelector(".or-player.mine").getBoundingClientRect();
			return {
				wide: document.documentElement.scrollWidth > window.innerWidth + 1,
				outside: sections.filter((section) => !inside(section)).map((section) => section.className),
				order: other.bottom <= influence.top + 1 && mine.top >= influence.bottom - 1,
			};
		});
		check("the playable board stays inside a phone viewport",
			!phone.wide && phone.outside.length === 0, JSON.stringify(phone));
		check("the influence board sits between the opponent and your player boxes on a phone",
			phone.order, JSON.stringify(phone));

		// A SECTION CAN SIT INSIDE THE VIEWPORT AND STILL HIDE ITS CONTENT: the
		// check above measures the panel's own box, and the influence rows, the
		// technology grid and both placed-Agent grids used to satisfy it while
		// scrolling sideways INSIDE themselves, which put two of five planets and
		// a third of every track behind a horizontal drag on a page that scrolls
		// vertically. Assert the inner boxes are not scrollers, and that all five
		// planet columns are actually on screen. The HAND is exempt and stays a
		// scroller on purpose — full-size cards, and up to six of them.
		const inner = await page.evaluate(() => {
			const scrollers = [...document.querySelectorAll(
				".or-influence, .or-track, .or-track-spaces, .or-tech-grid, .or-played-agents")]
				.filter((el) => el.scrollWidth > el.clientWidth + 1)
				.map((el) => `${el.className}:${el.scrollWidth}>${el.clientWidth}`);
			const cells = [...document.querySelectorAll(".or-played-agent")];
			const offscreen = cells.filter((cell) => {
				const r = cell.getBoundingClientRect();
				return r.left < -1 || r.right > window.innerWidth + 1 || r.width < 8;
			}).length;
			// The player-box row is the only placed-Agent treatment there is, so
			// the top Agent's cost has to be here or it does not exist at this
			// size. An occupied cell shows both numbers; an empty one is disabled
			// and shows neither.
			const occupied = cells.filter((cell) => !cell.disabled);
			const railCosts = {
				occupied: occupied.length,
				priced: occupied.filter((cell) => /^\d+$/.test(
					cell.querySelector(".or-played-cost")?.textContent.trim() || "")).length,
				emptyPriced: cells.filter((cell) => cell.disabled && cell.querySelector(".or-played-cost")).length,
				// Two numbers in a 70px cell is the whole risk here. The NAME is
				// display:none at this width and reports an empty box, so a child
				// with no box is skipped rather than read as sitting at the page
				// origin -- which is a spill on every cell, for every seat.
				spills: cells.filter((cell) => [...cell.children].some((kid) => {
					const k = kid.getBoundingClientRect(), c = cell.getBoundingClientRect();
					if (!k.width && !k.height) return false;
					return k.right > c.right + 1 || k.bottom > c.bottom + 1 || k.left < c.left - 1;
				})).length,
				// The same margin, for the same reason, on the narrowest cell in
				// the game. See the note beside `costClear` above.
				clearance: Math.min(...cells.flatMap((cell) => {
					const c = cell.getBoundingClientRect();
					return [...cell.children].map((kid) => kid.getBoundingClientRect())
						.filter((k) => k.width > 0)
						.flatMap((k) => [k.left - c.left, c.right - k.right]);
				}), Infinity),
			};
			const bonuses = [...document.querySelectorAll(".or-bonus")].map((el) => {
				const r = el.getBoundingClientRect();
				return { w: Math.round(r.width), h: Math.round(r.height) };
			});
			const tokenOverlaps = [...document.querySelectorAll(".or-influence .or-track")]
				.filter((row) => {
					const a = row.querySelector(".or-bonus").getBoundingClientRect();
					const b = row.querySelector(".or-track-spaces").getBoundingClientRect();
					return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
				}).length;
			const bonusRight = [...document.querySelectorAll(".or-influence .or-track")].every((row) => {
				const bonus = row.querySelector(".or-bonus").getBoundingClientRect();
				const track = row.querySelector(".or-track-spaces").getBoundingClientRect();
				return bonus.left >= track.right - 1
					&& bonus.top + bonus.height / 2 >= track.top
					&& bonus.top + bonus.height / 2 <= track.bottom;
			});
			const trackCentered = [...document.querySelectorAll(".or-influence .or-track")].every((row) => {
				const track = row.querySelector(".or-track-spaces").getBoundingClientRect();
				const name = row.querySelector(".or-track-name").getBoundingClientRect();
				return Math.abs(track.left + track.width / 2 - (name.left + name.width / 2)) <= 1;
			});
			const influence = document.querySelector(".or-influence").getBoundingClientRect();
			const trackHeights = [...document.querySelectorAll(".or-influence .or-track-spaces")]
				.map((el) => Math.round(el.getBoundingClientRect().height));
			return { scrollers, cells: cells.length, offscreen, railCosts, bonuses, tokenOverlaps, bonusRight,
				trackCentered, trackHeights, influenceHeight: Math.round(influence.height) };
		});
		check("no board on a phone hides content behind a sideways scroll",
			inner.scrollers.length === 0, JSON.stringify(inner.scrollers));
		check("all five played-Agent counts are on screen for both seats",
			inner.cells === 10 && inner.offscreen === 0, JSON.stringify(inner));
		check("the phone played-Agent cell carries the top Agent's cost without spilling",
			inner.railCosts.occupied > 0
			&& inner.railCosts.priced === inner.railCosts.occupied
			&& inner.railCosts.emptyPriced === 0 && inner.railCosts.spills === 0
			&& inner.railCosts.clearance >= 2,
			JSON.stringify(inner.railCosts));
		check("bonus tokens are uniformly compact and clear of every planet track",
			inner.bonuses.every(({ w, h }) => Math.abs(w - h) <= 1 && w <= 30)
			&& inner.tokenOverlaps === 0 && inner.bonusRight && inner.trackCentered, JSON.stringify(inner));
		check("phone influence rails retain their height with a compact turn narration footer",
			inner.trackHeights.length === 5 && Math.min(...inner.trackHeights) > 160 && inner.influenceHeight <= 250,
			JSON.stringify(inner));

		// PHONE HIERARCHY. Technology starts as three tiny progress summaries,
		// expands back to all fifteen real spaces, and the Log comes after the
		// hand instead of interrupting the board before the player's controls.
		const collapsedTech = await page.evaluate(() => {
			const body = document.querySelector(".or-tech-body");
			const hand = document.querySelector(".or-hand-zone").getBoundingClientRect();
			const logBox = document.querySelector(".or-log").getBoundingClientRect();
			const summaries = [...document.querySelectorAll(".or-tech-summary-row")];
			return {
				bodyHidden: getComputedStyle(body).display === "none",
				summaries: summaries.length,
				levels: summaries.map((row) => [...row.querySelectorAll(":scope > span > b")]
					.map((el) => el.textContent.trim())),
				logAfterHand: logBox.top >= hand.bottom - 1,
				logHeight: Math.round(logBox.height),
			};
		});
		check("technology collapses on a phone to both players' level on all three tracks",
			collapsedTech.bodyHidden && collapsedTech.summaries === 3
			&& collapsedTech.levels.every((levels) => levels.length === 2
				&& levels.every((level) => /^\d+$/.test(level))), JSON.stringify(collapsedTech));
		check("the Log is the final board section on a phone",
			collapsedTech.logAfterHand, JSON.stringify(collapsedTech));
		check("the mobile Log has the taller reading viewport",
			collapsedTech.logHeight >= 195, JSON.stringify(collapsedTech));
		if (process.env.ORBIT_SHOTS) {
			await page.screenshot({ path: "test-results/orbit-390x844-after.png", fullPage: true });
		}
		await page.locator(".or-tech-toggle").click({ timeout: 10_000 }).catch(() => {});
		await sleep(100);
		const expandedTech = await page.evaluate(() => ({
			bodyVisible: getComputedStyle(document.querySelector(".or-tech-body")).display !== "none",
			spaces: [...document.querySelectorAll(".or-tech-space")]
				.filter((el) => el.getBoundingClientRect().height > 0).length,
			expanded: document.querySelector(".or-tech-toggle")?.getAttribute("aria-expanded"),
		}));
		check("the compact technology summary expands to the complete ladder",
			expandedTech.bodyVisible && expandedTech.spaces === 15 && expandedTech.expanded === "true",
			JSON.stringify(expandedTech));
		await checkTrackPresentation("Phone");
		await page.locator(".or-tech-toggle").click({ timeout: 10_000 }).catch(() => {});

		// Every readable face opens the same modal, so neither treatment loses rules
		// text. This runs at the phone size, where the rail count is the face: press
		// one, then a card in the column it opens, and its own effect comes back.
		const slot = page.locator(".or-player.mine .or-played-agent:not(:disabled)").first();
		const hasSlot = await slot.count().catch(() => 0);
		if (hasSlot) {
			await slot.click({ timeout: 10_000 }).catch(() => {});
			const columnInfo = await page.locator(".or-info-list button").count().catch(() => 0);
			if (columnInfo) await page.locator(".or-info-list button").first().click().catch(() => {});
			const cardInfo = await page.evaluate(() => {
				const panel = document.querySelector(".or-info");
				return panel ? panel.textContent.replace(/\s+/g, " ").trim() : "";
			});
			check("pressing a placed Agent opens its full card text",
				/Agent/.test(cardInfo) && /Credits/.test(cardInfo) && cardInfo.length > 60,
				cardInfo.slice(0, 120));
			await page.keyboard.press("Escape").catch(() => {});
		} else {
			check("pressing a placed Agent opens its full card text", false,
				"the turn played produced no recruited Agent to press");
		}
		// Public room frames drive motion for BOTH seats; duplicate broadcasts must
		// not replay it. Pin transition time rather than racing the screenshot clock.
		await page.setViewportSize({ width: 390, height: 844 });
		await page.evaluate(() => window.scrollTo(0, 0));
		const opponentId = Object.keys(gameView.players).find((id) => id !== "orbit-harness");
		gameView.influence.mercury = 0;
		socket.send(JSON.stringify(fixture));
		await sleep(750);
		for (const [pid, seat] of [["orbit-harness", "mine"], [opponentId, "theirs"]]) {
			gameView.turn_pid = pid;
			gameView.legal_moves = pid === "orbit-harness" ? [{ action: "recruit", card_id: self.hand[0].id }] : [];
			gameView.players[pid].credits += 3;
			gameView.players[pid].zenithium += 2;
			gameView.influence.mercury = seat === "mine" ? 2 : -2;
			gameView.log.push({ turn: ++gameView.turn_number, pid, message: `${fixture.room.players[pid]} gains 3 Credits and 2 Zenithium; Mercury moves toward them.` });
			socket.send(JSON.stringify(fixture));
			await page.waitForFunction((seat) => document.querySelectorAll(`.or-player.${seat} .or-resource-delta`).length === 2, seat);
			const moving = await page.locator(".or-mercury .or-disc").evaluate((el) => {
				const motion = el.getAnimations().find((a) => a.transitionProperty === "top");
				if (!motion) return false;
				motion.pause(); motion.currentTime = 220;
				return motion.effect.getTiming().duration >= 200;
			});
			check(`${seat}: influence slides between authoritative positions`, moving);
			check(`${seat}: resource gains and current actor are visible`, await page.locator(`.or-player.${seat} .or-resource-delta.gain`).count() === 2
				&& await page.locator(`.or-player.${seat}.active`).count() === 1);
			if (process.env.ORBIT_SHOTS) await page.screenshot({ path: `test-results/orbit-motion-${seat}.png`, fullPage: true });
			await page.locator(".or-mercury .or-disc").evaluate((el) => el.getAnimations().forEach((a) => a.finish()));
			await sleep(1900);
			socket.send(JSON.stringify(fixture));
			await sleep(100);
			check(`${seat}: duplicate broadcast does not replay resource effects`, await page.locator(".or-resource-delta").count() === 0);
		}
		check("turn recap is removed and the full log remains readable",
			await page.locator(".or-activity, .or-recap").count() === 0
			&& /Mercury moves/.test(await page.locator(".or-log").innerText()));
		// A first recruit must not resize either player's row. Also exercise the
		// widest real column (18 Agents) with a two-digit top cost at phone widths.
		const orbitCatalog = await page.evaluate(() => JSON.parse(localStorage.getItem("orbit_catalog")));
		const savedColumns = Object.fromEntries(Object.entries(gameView.players)
			.map(([pid, player]) => [pid, structuredClone(player.columns)]));
		// `spills` answers "did it overflow"; `clearance` answers "by how much did
		// it fit", and only the second tells a sound layout from one sitting a
		// hair inside the edge. The 320px cell cleared its border box by 1.69px,
		// i.e. 0.69px past the 1px tolerance below, and duly overflowed on CI's fonts -- a
		// pass that was really a coin flip on font metrics, and unreadable as one
		// from a green tick. Reporting the narrowest margin makes it assertable.
		const slotGeometry = () => page.evaluate(() => ({
			rows: [...document.querySelectorAll(".or-played-agents")].map((el) => el.getBoundingClientRect().height),
			cells: [...document.querySelectorAll(".or-played-agent")].map((el) => el.getBoundingClientRect().height),
			spills: [...document.querySelectorAll(".or-played-agent")].filter((el) => {
				const box = el.getBoundingClientRect();
				return [...el.children].some((child) => {
					const r = child.getBoundingClientRect();
					return r.width > 0 && (r.left < box.left + 1 || r.right > box.right - 1 || r.bottom > box.bottom - 1);
				});
			}).length,
			// HORIZONTAL ONLY, deliberately. Width is the axis that overflowed and the
			// axis a two-digit pair actually contends for; the vertical box is fixed
			// at 26px and stays covered by `spills` above. Asserting a margin on an
			// axis whose slack has not been measured across platforms is how a gate
			// starts failing for a reason that is not the bug.
			clearance: [...document.querySelectorAll(".or-played-agent")].flatMap((el) => {
				const box = el.getBoundingClientRect();
				return [...el.children].map((child) => child.getBoundingClientRect()).filter((r) => r.width > 0)
					.flatMap((r) => [r.left - box.left, box.right - r.right]);
			}).reduce((a, b) => Math.min(a, b), Infinity),
		}));
		for (const viewport of [{ width: 320, height: 844 }, { width: 390, height: 844 },
			{ width: 768, height: 1024 }, { width: 1366, height: 768 }, { width: 1920, height: 1080 }]) {
			await page.setViewportSize(viewport);
			for (const player of Object.values(gameView.players)) player.columns = Object.fromEntries(OR_PLANETS.map((p) => [p, []]));
			socket.send(JSON.stringify(fixture));
			await page.waitForFunction(() => document.querySelectorAll(".or-played-agent.empty").length === 10);
			const empty = await slotGeometry();
			for (const count of [1, 18]) {
				for (const player of Object.values(gameView.players)) {
					const column = Object.values(orbitCatalog.cards).filter((card) => card.planet === "jupiter");
					column.sort((a, b) => a.cost - b.cost);
					player.columns.jupiter = column.slice(-count);
				}
				socket.send(JSON.stringify(fixture));
				await page.waitForFunction((count) => [...document.querySelectorAll(".or-played-count")]
					.filter((el) => Number(el.textContent) === count).length === 2, count);
				const filled = await slotGeometry();
				// WHERE the two numbers sit, not just that they fit. On a phone the
				// name is gone and the count and price go to OPPOSITE EDGES, so the
				// five cells read as two aligned columns down the row; on a pointer
				// width the name rejoins and sits against the PRICE, keeping the two
				// facts about the top card together and leaving the count — which is
				// about the column, not the card — alone on the left. Both are easy
				// to undo with a `justify-content` or a `text-align` and neither
				// would fail any other check in this file.
				const order = await page.evaluate(() => {
					const cell = [...document.querySelectorAll(".or-played-agent")]
						.find((el) => el.querySelector(".or-played-quantity") && el.querySelector(".or-played-cost"));
					if (!cell) return null;
					const c = cell.getBoundingClientRect();
					const q = cell.querySelector(".or-played-quantity").getBoundingClientRect();
					const p = cell.querySelector(".or-played-cost").getBoundingClientRect();
					const nameEl = cell.querySelector(".or-played-name");
					const nameShown = nameEl && getComputedStyle(nameEl).display !== "none";
					const n = nameShown ? nameEl.getBoundingClientRect() : null;
					return {
						countFirst: q.left < p.left, nameShown,
						countInset: q.left - c.left, priceInset: c.right - p.right,
						// how far the name's INK sits from the price it belongs with
						nameGap: n ? p.left - n.right : null,
						width: c.width,
					};
				});
				if (count === 18) {
					const phone = viewport.width <= 980;
					check(`${viewport.width}px: the count leads and the price trails${phone ? ", pinned to opposite edges" : ", with the name against the price"}`,
						!!order && order.countFirst && order.nameShown === !phone
						// edge-pinned on a phone: both insets are just the cell padding
						&& (!phone || (order.countInset <= 4 && order.priceInset <= 4))
						// ...and on a pointer width the name closes up to the price
						&& (phone || (order.nameGap !== null && order.nameGap >= 0 && order.nameGap <= 6)),
						JSON.stringify(order));
				}
				check(`${viewport.width}px: ${count} played Agents keep the empty row's size and all numbers fit`,
					JSON.stringify(empty.rows) === JSON.stringify(filled.rows)
					&& JSON.stringify(empty.cells) === JSON.stringify(filled.cells)
					&& filled.spills === 0 && filled.clearance >= 2,
					JSON.stringify({ empty, filled }));
			}
		}
		for (const [pid, columns] of Object.entries(savedColumns)) gameView.players[pid].columns = columns;
		socket.send(JSON.stringify(fixture));
		for (const width of [320, 360, 390, 430, 768, 900]) {
			await page.setViewportSize({ width, height: 844 });
			const fit = await page.evaluate(() => ({
				page: document.documentElement.scrollWidth <= innerWidth,
				resources: [...document.querySelectorAll(".or-resource")].every((el) => el.getBoundingClientRect().right <= innerWidth),
				icons: document.querySelectorAll(".or-resources .or-resource-icon").length === 4,
				tech: [...document.querySelectorAll(".or-tech-summary-row strong")].every((el) => el.scrollWidth <= el.clientWidth + 1),
			}));
			check(`${width}px: resources, faction names and custom icons fit`, fit.page && fit.resources && fit.icons && fit.tech, JSON.stringify(fit));
			if (process.env.ORBIT_SHOTS) await page.screenshot({ path: `test-results/orbit-polish-${width}.png`, fullPage: true });
		}
		await page.setViewportSize({ width: 390, height: 844 });
		gameView.influence.mercury = gameView.order[0] === "orbit-harness" ? 3 : -3;
		socket.send(JSON.stringify(fixture));
		await sleep(400);
		if (process.env.ORBIT_SHOTS) await page.locator(".or-influence").screenshot({ path: "test-results/orbit-capture-before.png" });
		self.captured.push("mercury"); gameView.influence.mercury = null;
		socket.send(JSON.stringify(fixture));
		await page.waitForSelector(".or-mercury .or-disc.captured");
		check("capture exits toward your goal rather than sliding back to centre", await page.locator(".or-mercury .or-disc").evaluate((el) => {
			el.getAnimations().forEach((a) => { a.pause(); a.currentTime = 140; });
			return parseFloat(el.style.getPropertyValue("--or-position")) > 90;
		}));
		if (process.env.ORBIT_SHOTS) await page.locator(".or-influence").screenshot({ path: "test-results/orbit-capture-middle.png" });
		await page.locator(".or-mercury .or-disc").evaluate((el) => el.getAnimations().forEach((a) => a.finish()));
		if (process.env.ORBIT_SHOTS) await page.locator(".or-influence").screenshot({ path: "test-results/orbit-capture-end.png" });
		gameView.influence.mercury = 0;
		socket.send(JSON.stringify(fixture));
		await page.waitForSelector(".or-mercury .or-disc.returning");
		check("replacement disc appears at centre without a reverse-movement animation", await page.locator(".or-mercury .or-disc").evaluate((el) => el.getAnimations().length === 0 && el.style.getPropertyValue("--or-position") === "50%"));
		// Decision fixtures use the real catalog names and task metadata. Test the
		// instruction and the available responses, not merely that a box appeared.
		const planetNames = ["mercury", "venus", "terra", "mars", "jupiter"];
		const planetMoves = planetNames.map((planet) => ({ action: "choose", planet }));
		const decisions = [
			["influence", 109, { type: "influence", amount: 2 }, planetMoves, "gain 2 influence"],
			["split", 110, { type: "split_influence", amounts: [1, 1], selected: ["mercury"] }, planetMoves.slice(1), "Planet 2 of 2"],
			["own-exile", 102, { type: "exile", owner: "self", count: 2, done: 1, reward: { resource: "credits", amount: 10 } }, planetMoves.slice(1), "your top Agent"],
			["enemy-exile", 510, { type: "exile", owner: "opponent", count: 1 }, planetMoves, "opponent’s top Agent"],
			["optional-exile", 310, { type: "optional_exile_each", planets: ["mercury", "venus", "mars", "jupiter"], index: 0, reward: "influence" }, [{ action: "choose", accept: true }, { action: "choose", accept: false }], "Gain 1 Mercury influence"],
			["spend", 218, { type: "spend_tier", resource: "zenithium", exclude: "venus" }, [{ action: "choose", cost: 1, amount: 1 }, { action: "choose", cost: 2, amount: 2 }, { action: "choose", cost: 0, amount: 0 }], "Spend Zenithium"],
			["adjacent", 314, { type: "adjacent_three", center: 2, neighbor: 1 }, planetMoves.slice(1, 4), "2 influence there and 1 on each neighbour"],
		];
		for (const width of [320, 390, 1920, 2560]) {
			await page.setViewportSize({ width, height: width === 1920 ? 1080 : width === 2560 ? 1600 : 844 });
			await page.evaluate(() => scrollTo(0, 0));
			let boardBefore;
			if (width >= 1920) boardBefore = await page.locator(".or-influence").boundingBox();
			for (const [kind, cardId, task, moves, expected] of decisions) {
				gameView.turn_pid = "orbit-harness";
				gameView.pending_pid = "orbit-harness";
				gameView.pending = { source: orbitCatalog.cards[String(cardId)].name, task };
				gameView.legal_moves = moves;
                // Every offered column has a real public Agent to choose.
                for (const player of [self, opponent]) for (const planet of planetNames) {
                    player.columns[planet] = [Object.values(orbitCatalog.cards).find((card) => card.planet === planet)];
                }

				socket.send(JSON.stringify(fixture));
				await page.waitForFunction((expected) => document.querySelector(".or-decision")?.textContent.includes(expected), expected);
				if (width >= 1920) {
					const fit = await page.evaluate(() => {
						const inside = (node) => { const r = node.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight + 1 && r.left >= 0 && r.right <= innerWidth; };
						const hand = document.querySelector(".or-hand-zone").getBoundingClientRect();
						return { pageFits: document.documentElement.scrollHeight <= innerHeight + 1,
							visible: [...document.querySelectorAll(".or-influence, .or-decision, .or-hand-zone .or-agent, .or-decision button")].every(inside),
							controlsFit: document.querySelector(".or-decision").getBoundingClientRect().bottom <= hand.bottom,
							// The overshoot, not just the verdict: the hand zone is a FIXED
							// reserve (see `.or-live .or-hand-zone`), so a failure here is a
							// number to re-cut that reserve by, and reading it off a screenshot
							// is how it got mis-cut in the first place.
							overshoot: Math.round(document.querySelector(".or-decision").getBoundingClientRect().bottom - hand.bottom),
							spacing: Math.round(document.querySelector(".or-track-spaces").getBoundingClientRect().height / 9) };
					});
					const boardNow = await page.locator(".or-influence").boundingBox();
					check(`${width}px ${kind}: the full hand, decision and spaced tracks fit together`, fit.pageFits && fit.visible && fit.controlsFit && fit.spacing >= 27, JSON.stringify(fit));
					check(`${width}px ${kind}: decisions keep the board stationary`, Math.abs(boardNow.y - boardBefore.y) < 1 && Math.abs(boardNow.height - boardBefore.height) < 1);
				}
				check(`${width}px ${kind}: instruction names the action and source`, (await page.locator(".or-decision").innerText()).includes(gameView.pending.source));
				if (kind === "own-exile" && width === 390) {
					const beforeHold = fixtureReplies.length;
					const choice = page.locator(".or-decision button").first();
					await choice.scrollIntoViewIfNeeded();
					const box = await choice.boundingBox();
					const touch = await ctx.newCDPSession(page);
					await touch.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x + box.width / 2, y: box.y + box.height / 2 }] });
					await sleep(800);
					const openedDuringHold = await page.locator(".or-info").count();
					await touch.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
					await touch.detach();
					check("holding a decision Agent opens its card without submitting the choice", fixtureReplies.length === beforeHold && await page.locator(".or-info-cost").count() === 1, JSON.stringify({ box, openedDuringHold, replies: fixtureReplies.slice(beforeHold) }));
					await page.mouse.click(5, 5);
					check("a fresh backdrop press dismisses the inspected card", await page.locator(".or-info").count() === 0);
				}
				if (kind === "influence") {
					const rects = await page.locator(".or-decision button").evaluateAll((nodes) => nodes.map((node) => { const r = node.getBoundingClientRect(); return { y: r.y, left: r.left, right: r.right }; }));
					check(`${width}px: all five planet choices fit in one row`, rects.length === 5 && rects.every((r) => r.y === rects[0].y && r.left >= 0 && r.right <= width));
				}
				await page.locator(".or-decision").scrollIntoViewIfNeeded();
				if (process.env.ORBIT_SHOTS) await page.screenshot({ path: `test-results/orbit-decision-${kind}-${width}.png` });
			}
		}
		// Measure every printed card, not just six copies of whichever random
		// card opened this game. A fitting outer face can still clip its prose.
		const savedHand = self.hand;
		gameView.pending = null; gameView.pending_pid = null; gameView.legal_moves = [];
		await page.emulateMedia({ reducedMotion: "reduce" });
		for (const viewport of [{ width: 1920, height: 1080 }, { width: 2560, height: 1600 },
			{ width: 1366, height: 768 }, { width: 320, height: 844 }, { width: 390, height: 844 }, { width: 768, height: 1024 }]) {
			await page.setViewportSize(viewport);
			const clipped = [];
			const measurements = [];
			const cards = Object.values(orbitCatalog.cards);
			for (let offset = 0; offset < cards.length; offset += 6) {
				self.hand = cards.slice(offset, offset + 6);
				socket.send(JSON.stringify(fixture));
				// WAIT FOR THE WHOLE BATCH, NOT ITS FIRST CARD. Waiting on hand[0]
				// returns the moment React commits the first face, and the other
				// five are then measured mid-render: they report empty computed
				// styles (NaN) or a pre-fit geometry. It reproduced as a rare
				// failure naming cards 201/301/401/501 -- every one of them the
				// FIRST id of its own batch, which is the tell that the wait, not
				// the layout, was what moved.
				await page.waitForFunction((ids) => ids.every((id) =>
					!!document.querySelector(`.or-hand [data-card-id="${id}"]`)), self.hand.map((c) => c.id));
				measurements.push(...await page.locator(".or-hand-zone .or-agent").evaluateAll((nodes) => nodes.map((node) => {
					const text = node.querySelector(".or-agent-text");
					const height = node.getBoundingClientRect().height;
					const head = node.querySelector(".or-agent-top").getBoundingClientRect();
					const gap = text.getBoundingClientRect().top - head.bottom;
					node.style.height = "auto"; node.style.alignSelf = "start"; text.style.flex = "none";
					const needed = node.getBoundingClientRect().height;
					node.style.height = ""; node.style.alignSelf = ""; text.style.flex = "";
					// ONE LINE, MEASURED AS ONE LINE. A title that wrapped would be
					// ~2x its own line-height, so comparing the rendered height
					// against the line box catches a wrap whatever caused it --
					// a name longer than the fitter's floor, a font whose glyphs
					// are wider here than on the dev box, or the fitter simply
					// not running. `scrollWidth` then catches the other failure
					// in the same place: fitted down but still overflowing.
					const name = node.querySelector("strong");
					const nameSpan = name.querySelector("span");
					const nameCs = getComputedStyle(name);
					return { id: node.dataset.cardId, height, needed, gap, line: parseFloat(getComputedStyle(text).lineHeight),
						nameH: name.getBoundingClientRect().height,
						nameLine: parseFloat(nameCs.lineHeight) || parseFloat(nameCs.fontSize) * 1.18,
						nameFs: parseFloat(nameCs.fontSize),
						nameOver: nameSpan ? nameSpan.scrollWidth - nameSpan.clientWidth : 0 };
				})));
				clipped.push(...await page.locator(".or-hand-zone .or-agent").evaluateAll((nodes) => nodes.flatMap((node) => {
					const text = node.querySelector(".or-agent-text"), foot = node.querySelector(".or-agent-foot");
					const range = document.createRange(); range.selectNodeContents(text);
					const ink = range.getBoundingClientRect(), box = node.getBoundingClientRect();
					// SAY WHICH BOUND BROKE AND BY HOW MUCH. A bare list of card ids
					// names the cards and not the defect, which leaves the reader to
					// re-derive it -- and on CI, where these numbers are the only
					// evidence and the run log needs a sign-in to read, that is the
					// difference between a fixable failure and a rerun. `transform` is
					// here because these are BOUNDING rects: a card measured mid-flight
					// reports a scaled box against unscaled tolerances, so a non-`none`
					// transform means the measurement, not the layout, is what is wrong.
					const footBox = foot.getBoundingClientRect(), why = [];
					if (ink.bottom > footBox.top + 1) why.push(`text over foot by ${(ink.bottom - footBox.top).toFixed(2)}`);
					if (footBox.bottom > box.bottom - 2) why.push(`foot past card by ${(footBox.bottom - box.bottom).toFixed(2)}`);
					if (text.scrollWidth > text.clientWidth + 1) why.push(`text ${text.scrollWidth - text.clientWidth}px too wide`);
					if (parseFloat(getComputedStyle(text).fontSize) < 11.5) why.push(`font shrank to ${getComputedStyle(text).fontSize}`);
					return why.length
						? [`${node.dataset.cardId}: ${why.join(", ")} (transform ${getComputedStyle(node).transform})`]
						: [];
				})));
			}
			check(`${viewport.width}px: all 90 card sentences fit at full text size`, cards.length === 90 && clipped.length === 0, JSON.stringify(clipped));
			// A WRAPPED TITLE IS CHARGED TO EVERY CARD, because the hand reserves
			// one height for all 90 faces — so this is a check about the whole
			// hand's height, not about one long name. The floor is asserted from
			// the other side too: shrinking is only an acceptable answer to a long
			// name while the result is still readable.
			// A NON-FINITE MEASUREMENT MUST FAIL, NOT VANISH. `getComputedStyle` on a
			// node that has left the DOM returns empty strings, so a card caught
			// mid-rerender reports NaN -- and every test below is a `>` comparison,
			// which NaN answers `false`. Those rows sailed through all three checks
			// while proving nothing, and the count drifting 90 -> 89 was the only
			// outward sign. Assert the roster, then the geometry.
			const unmeasured = measurements.filter((m) => !Number.isFinite(m.nameFs) || !Number.isFinite(m.nameH));
			const seen = new Set(measurements.map((m) => m.id));
			const wrapped = measurements.filter((m) => m.nameH > m.nameLine * 1.5);
			const overflowed = measurements.filter((m) => m.nameOver > 1);
			const tiniest = measurements.reduce((a, b) => a.nameFs < b.nameFs ? a : b, { nameFs: Infinity });
			check(`${viewport.width}px: every card title is one line, shrunk to fit if need be`,
				unmeasured.length === 0 && seen.size === cards.length
				&& wrapped.length === 0 && overflowed.length === 0 && tiniest.nameFs >= 8,
				JSON.stringify({ unmeasured: unmeasured.length, seen: seen.size, of: cards.length,
					wrapped: wrapped.slice(0, 4), overflowed: overflowed.slice(0, 4), tiniest }));
			const tallest = measurements.reduce((a, b) => a.needed > b.needed ? a : b);
			// The reserved height must be EARNED by the longest face rather than
			// guessed high, but the slack it leaves can only be judged to the
			// nearest LINE: `needed` moves in whole wrapped lines, and which word
			// a sentence breaks on is the font's decision, not the layout's. This
			// bound was a flat 14px against ~4-5px of real slack, so a face that
			// wrapped one line shorter on CI's fonts than on a dev box read as
			// ~19px of waste and failed a layout that was in fact correct --
			// a platform difference reported as a regression. Allowing one line
			// plus the measured slack still catches what the check is for (a
			// height padded out by a line or more of dead space); it only stops
			// asserting that two font stacks break the same sentence alike.
			check(`${viewport.width}px: compact cards fit the longest face with tight title spacing`,
				measurements.every((m) => m.needed <= m.height + 1 && m.gap <= 5)
				&& tallest.height - tallest.needed <= tallest.line + 6,
				JSON.stringify({ ...tallest, slack: +(tallest.height - tallest.needed).toFixed(2) }));
			// Review the longest face beside four other planets, with an actual
			// pointer selection. Its hover shadow must retain the selected edge.
			self.hand = [orbitCatalog.cards[tallest.id], ...OR_PLANETS.filter((planet) => planet !== orbitCatalog.cards[tallest.id].planet)
				.map((planet) => cards.find((card) => card.planet === planet))];
			gameView.turn_pid = "orbit-harness";
			gameView.legal_moves = self.hand.map((card) => ({ action: "recruit", card_id: card.id }));
			socket.send(JSON.stringify(fixture));
			await page.waitForFunction((id) => !!document.querySelector(`.or-hand [data-card-id="${id}"]`), tallest.id);
			const selected = page.locator(`.or-hand [data-card-id="${tallest.id}"]`);
			await selected.click();
			const hovered = await selected.evaluate((el) => {
				const s = getComputedStyle(el);
				return { shadow: s.boxShadow, color: s.color, border: s.borderTopColor, outline: s.outlineWidth, transform: s.transform };
			});
			await page.mouse.move(0, 0);
			const idleShadow = await selected.evaluate((el) => getComputedStyle(el).boxShadow);
			check(`${viewport.width}px: selection keeps its planet-colored inset edge under the pointer`,
				hovered.shadow === idleShadow && hovered.shadow.includes("inset") && hovered.shadow.includes(hovered.color)
				&& hovered.border === hovered.color && hovered.outline === "0px" && hovered.transform === "none", JSON.stringify(hovered));
			if (process.env.ORBIT_SHOTS) await page.screenshot({ path: `test-results/orbit-cards-${viewport.width}.png`, fullPage: true });
			await page.keyboard.press("Tab");
			await page.keyboard.press("Shift+Tab");
			await selected.hover();
			check(`${viewport.width}px: keyboard focus keeps a separate visible ring even under the pointer`,
				await selected.evaluate((el) => document.activeElement === el && getComputedStyle(el).outlineWidth === "2px"
					&& getComputedStyle(el).outlineColor === getComputedStyle(el).color));
			await selected.click();
		}
		self.hand = savedHand;
		socket.send(JSON.stringify(fixture));
		await page.emulateMedia({ reducedMotion: "no-preference" });
		await page.setViewportSize({ width: 1920, height: 1080 });
		await page.evaluate(() => scrollTo(0, 0));
		for (const action of ["recruit", "technology", "leader"]) {
			const played = orbitCatalog.cards["109"];
			self.hand = [played, orbitCatalog.cards["210"], orbitCatalog.cards["314"], orbitCatalog.cards["502"]];
			gameView.turn_pid = "orbit-harness";
			gameView.legal_moves = [{ action, card_id: played.id }];
			socket.send(JSON.stringify(fixture));
			await page.waitForSelector('.or-hand [data-card-id="109"]');
			await page.waitForFunction(() => !document.querySelector(".or-card-flight"));
			await page.locator('.or-hand [data-card-id="109"]').click();
			const beforeRequest = fixtureReplies.length;
			await page.locator(".or-action-bar button:enabled").click();
			await page.waitForTimeout(80);
			check(`${action}: clicking sends the move without animating unconfirmed state`, fixtureReplies.length > beforeRequest && await page.locator(".or-card-flight").count() === 0);
			self.hand = [orbitCatalog.cards["110"], ...self.hand.slice(1)];
			if (action === "recruit") self.columns[played.planet].push(played);
			if (action === "technology") self.technology[played.faction] = 2;
			gameView.log.push({ turn: gameView.turn_number, pid: "orbit-harness", action,
				parts: ["Orbiter ", { c: played.id, v: played.name }, ` ${action}.`] });
			socket.send(JSON.stringify(fixture));
			await page.waitForSelector(`.or-card-flight[data-flight="${action}"]`);
			const travel = await page.evaluate((action) => {
				const flight = document.querySelector(`.or-card-flight[data-flight="${action}"]`);
				const animation = flight.getAnimations()[0]; animation.pause();
				const at = (time) => { animation.currentTime = time; const r = flight.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
				const start = at(0), middle = at(300), end = at(619);
				const key = action === "recruit" ? "column-orbit-harness-mercury" : action === "technology" ? "tech-rung-robot-2" : "leader-orbit-harness";
				const target = document.querySelector(`[data-motion-key="${key}"]`);
				const r = target.getBoundingClientRect();
				animation.currentTime = 300;
				return { shrinking: start.w > middle.w && middle.w > end.w,
					landed: Math.abs(end.x + end.w / 2 - r.x - r.width / 2) < 2 && Math.abs(end.y + end.h / 2 - r.y - r.height / 2) < 2,
					start, middle, end };
			}, action);
			check(`${action}: a confirmed card shrinks into its actual destination`, travel.shrinking && travel.landed, JSON.stringify(travel));
			check(`${action}: the replacement card draws into the hand`, await page.locator('.or-card-flight[data-flight="draw"]').count() === 1);
			// A DRAW IS DEALT TO THE LEFT EDGE AND THEN SLIDES INTO ORDER, which
			// is two movements and not one — there is no deck beside the hand any
			// more to fly out of, and the hand is sorted, so a card that travelled
			// straight to its sorted place appeared to materialise in the middle
			// of the fan. Assert the SHAPE: it starts left of where it ends, is
			// standing in the leftmost slot at the dwell, and finishes on its own
			// card. Measured against the leftmost card's box, so this holds
			// whichever card the sort happens to put first.
			const dealt = await page.evaluate(() => {
				const flight = document.querySelector('.or-card-flight[data-flight="draw"]');
				const animation = flight.getAnimations()[0]; animation.pause();
				const at = (time) => { animation.currentTime = time; const r = flight.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y) }; };
				const slot = document.querySelector(".or-hand .or-agent").getBoundingClientRect();
				const start = at(0), landed = at(280), settled = at(759);
				animation.currentTime = 0;
				return { start, landed, settled, slotX: Math.round(slot.x) };
			});
			check(`${action}: the drawn card is dealt to the leftmost slot before it slides into order`,
				dealt.start.x < dealt.landed.x && Math.abs(dealt.landed.x - dealt.slotX) <= 2
				&& dealt.settled.x >= dealt.landed.x, JSON.stringify(dealt));
			if (process.env.ORBIT_SHOTS) await page.screenshot({ path: `test-results/orbit-card-flight-${action}.png` });
			await page.evaluate(() => document.querySelectorAll(".or-card-flight").forEach((node) => node.getAnimations().forEach((animation) => animation.finish())));
			await page.waitForFunction(() => !document.querySelector(".or-card-flight"));
			socket.send(JSON.stringify(fixture));
			await page.waitForTimeout(80);
			check(`${action}: duplicate broadcasts do not replay card travel`, await page.locator(".or-card-flight").count() === 0);
		}
		await page.emulateMedia({ reducedMotion: "reduce" });
		self.hand = savedHand;
		socket.send(JSON.stringify(fixture));
		await page.waitForTimeout(80);
		check("reduced motion updates the hand without card flights", await page.locator(".or-card-flight").count() === 0);
		await page.emulateMedia({ reducedMotion: "no-preference" });
		// The bot's wait state belongs in its seat rail. A full-width status slab
		// makes the board feel like it is jumping between unrelated screens.
		const botSeat = Object.keys(gameView.players).find((id) => id !== "orbit-harness");
		fixture.room.ai_player = botSeat;
		gameView.phase = "playing";
		gameView.pending = null;
		gameView.pending_pid = null;
		gameView.turn_pid = botSeat;
		gameView.legal_moves = [];
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction(() => document.querySelector(".or-player.theirs .or-player-hint")?.textContent.includes("Thinking"));
		check("bot thinking stays in the opponent rail", await page.locator(".or-status").count() === 0
			&& (await page.locator(".or-player.theirs .or-player-hint").innerText()).includes("Thinking"));
		gameView.pending_pid = botSeat;
		gameView.pending = { source: "Bot effect", task: { type: "influence", amount: 1 } };
		gameView.turn_pid = botSeat;
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction(() => document.querySelector(".or-player.theirs .or-player-hint")?.textContent.includes("Resolving"));
		check("bot effect resolution stays in the opponent rail", await page.locator(".or-status").count() === 0
			&& (await page.locator(".or-player.theirs .or-player-hint").innerText()).includes("Resolving"));
		gameView.pending_pid = "orbit-harness";
		gameView.turn_pid = "orbit-harness";
		gameView.pending.task = { type: "optional_exile_each", planets: ["venus", "jupiter"], index: 0, reward: "zenithium" };
		gameView.legal_moves = [{ action: "choose", accept: false }];
		const repliesBefore = fixtureReplies.length;
		socket.send(JSON.stringify(fixture));
		await sleep(150);
		check("an empty column advances the sole legal response without a fake choice", await page.locator(".or-decision").count() === 0 && fixtureReplies.slice(repliesBefore).some((r) => r.move?.action === "choose" && r.move.accept === false));
		socket.send(JSON.stringify(fixture));
		await sleep(100);
		check("a duplicate forced-choice frame is submitted only once", fixtureReplies.length === repliesBefore + 1);
		gameView.pending = null;
		gameView.pending_pid = null;
		gameView.legal_moves = [];
		for (const [condition, captured] of [["Absolute", ["mars", "mars", "mars"]], ["Democratic", planetNames.slice(0, 4)], ["Popular", ["mars", "mars", "terra", "terra", "venus"]]]) {
			gameView.phase = "over"; gameView.winner = "orbit-harness"; self.captured = captured;
			socket.send(JSON.stringify(fixture));
			await page.waitForFunction((condition) => document.querySelector(".or-result h1")?.textContent.includes(condition), condition);
			check(`${condition}: result names the actual victory condition`, !(await page.locator(".or-result").innerText()).includes("senate"));
			await page.locator(".or-result").scrollIntoViewIfNeeded();
			if (process.env.ORBIT_SHOTS) await page.screenshot({ path: `test-results/orbit-result-${condition}.png` });
		}
		gameView.winner = opponentId; opponent.captured = ["mars", "mars", "mars"];
		socket.send(JSON.stringify(fixture));
		await page.waitForFunction((name) => document.querySelector(".or-result h1")?.textContent === `${name} wins by Absolute victory`, fixture.room.players[opponentId]);
		check("the losing player sees the opponent named as winner", !(await page.locator(".or-result").innerText()).includes("controls the senate"));
		gameView.phase = "playing"; gameView.winner = null;
		socket.send(JSON.stringify(fixture));
		await page.emulateMedia({ reducedMotion: "reduce" });
		gameView.influence.mercury = 0;
		gameView.players[opponentId].credits -= 2;
		socket.send(JSON.stringify(fixture));
		await page.waitForSelector(".or-resource-delta.spent");
		check("reduced motion preserves the signed resource cue without moving the board", await page.evaluate(() =>
			getComputedStyle(document.querySelector(".or-disc")).transitionDuration === "0s"
			&& document.querySelector(".or-resource-delta.spent").getAnimations().length === 0));
		await page.emulateMedia({ reducedMotion: "no-preference" });
		const oldSocket = socket;
		await socket.close({ code: 1001, reason: "visual reconnect check" });
		await page.waitForSelector(".or-connection.lost");
		const reconnectDeadline = Date.now() + 15000;
		while (socket === oldSocket && Date.now() < reconnectDeadline) await sleep(100);
		check("Orbit retries its dropped connection", socket !== oldSocket);
		gameView.players[opponentId].credits += 9;
		gameView.influence.mercury = 3;
		socket.send(JSON.stringify(fixture));
		await page.waitForSelector(".or-connection:not(.lost)");
		check("the restored snapshot does not animate outage changes as new moves", await page.evaluate(() =>
			document.querySelectorAll(".or-resource-delta").length === 0
			&& document.querySelector(".or-mercury .or-disc").getAnimations().length === 0));
		check("no page errors while playing Orbit", errors.length === 0,
			errors[0]?.slice(0, 200) || "");
		await ctx.close();
	}

	// skat → Hard → beat stay contiguous and in order, preserving the adjacency the
	// comments in those blocks were written against.
	// `ragtagFight` is lane A, and LAST, for a reason that is not lane A's usual
	// one: it arms no worker and measures no timing. It is here for BALANCE.
	// Measured, the two lanes were A 117.9s / B 133.9s -- B was the wall clock
	// even before this game existed, and its longest block (`dissonanceQuartet`,
	// 34.5s) is also its latest, so it runs against lane A's heaviest tail.
	// Adding a block to B made that worse and quartet began failing
	// intermittently. Moved here the lanes read A 127.2 / B 124.6. It goes AFTER
	// `dissonanceBeat` specifically so beat's dwell window is unchanged -- beat
	// still runs at the same point in the run, with the same company, and the new
	// work lands behind it.
	// ─── A finished game leaves Active and joins History right away ──────────
	// The lobby columns render from the localStorage cache first, and that cache
	// was last written the last time the LOBBY was open — before this game
	// started. So without `useFinishedGameSync` the game you just finished is
	// still sitting under Active when you walk back in, and still missing from
	// History, until the lobby's own fetch lands (tens of seconds on a cold
	// backend).
	//
	// Asserted on the CACHE while still on the result screen: that is the copy
	// the lobby paints first, and reading it BEFORE going back is the only thing
	// that tells the fix apart from the on-entry fetch that would mask it. The
	// walk back in is then done with both endpoints dead, so the columns can
	// only be coming from what the finish wrote.
	async function lobbyFinishSync(log) {
		const ctx = await browser.newContext({ viewport: { width: 1280, height: 960 } });
		await ctx.addInitScript(() => localStorage.setItem("spender_user",
			JSON.stringify({ id: "finish-harness", name: "Finny", session_token: "stub" })));
		const page = await ctx.newPage();
		let socket, latestFrame, fixtureMode = false;
		await page.routeWebSocket("**/orbit/ws/**", (ws) => {
			socket = ws;
			const server = ws.connectToServer();
			ws.onMessage((message) => { if (!fixtureMode) server.send(message); });
			server.onMessage((message) => {
				const data = JSON.parse(String(message));
				if (data.room?.game) latestFrame = data;
				if (!fixtureMode) ws.send(message);
			});
		});
		const errors = [];
		page.on("pageerror", (e) => errors.push(String(e)));
		const check = (name, cond, detail = "") => {
			if (cond) log(`  OK   ${name}`);
			else { shell.push(name); log(`  FAIL ${name}  ${detail}`); }
		};

		// A login the shell will not clear: it validates the stored session on
		// load, and a NETWORK error deliberately leaves the user alone where a
		// dead token would log them out. Without it this is a guest, and a guest
		// is short-circuited to an empty History.
		await page.route("**/auth/session*", (r) => r.abort());
		// The server's OWN view once the game is over — gone from Active, in
		// History. This is what the refresh under test has to go and fetch.
		let finishedId = null;
		const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
		await page.route("**/orbit/games/mine*", (r) => r.fulfill(json({ ok: true, games: [] })));
		await page.route("**/orbit/games/history*", (r) => r.fulfill(json({
			ok: true,
			games: finishedId ? [{
				id: finishedId, player1_name: "Finny", player2_name: "Bot",
				you_are_p1: true, outcome: "won", turns: 7, updated_at: 1750000000,
				// The tier this room was actually created at, below — the row the
				// server writes carries it, and the History line is the server's.
				ai_difficulty: "easy",
			}] : [],
		})));

		await page.goto(`http://localhost:${PORT}/orbit`, { waitUntil: "networkidle" });
		await page.waitForSelector(".orbit .lby-create-row", { timeout: 25_000 }).catch(() => {});
		await page.locator(".lby-cta").click({ timeout: 10_000 }).catch(() => {});
		await page.waitForSelector(".cm-panel", { timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-seg-btn", { hasText: "VS AI" }).click({ timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-seg-btn", { hasText: "Easy" }).click({ timeout: 10_000 }).catch(() => {});
		await page.locator(".cm-create").click({ timeout: 10_000 }).catch(() => {});
		await page.waitForSelector(".or-mulligan", { timeout: 30_000 }).catch(() => {});
		await page.locator(".or-mulligan .or-primary").click({ timeout: 10_000 }).catch(() => {});
		const playing = await page.waitForSelector(".or-influence", { timeout: 30_000 })
			.then(() => true).catch(() => false);
		const rid = latestFrame?.room?.room_id;
		check("a real Orbit room is in progress to finish", playing && !!rid, String(rid));
		if (!playing || !rid) { await ctx.close(); return; }

		// The Active row the lobby cached WHILE this game was in progress — the
		// row whose survival is the bug.
		const keys = () => page.evaluate(() => {
			const find = (suffix) => Object.keys(localStorage)
				.find((k) => k.startsWith("lbyc.orbit.") && k.endsWith(suffix)) || null;
			return { mine: find(".mine"), history: find(".history") };
		});
		const cacheKeys = await keys();
		check("the lobby cached its lists under a namespaced key",
			!!cacheKeys.mine && !!cacheKeys.history, JSON.stringify(cacheKeys));
		await page.evaluate(([key, id]) => localStorage.setItem(key, JSON.stringify([{
			id, player1_name: "Finny", player2_name: "Bot", you_are_p1: true,
			your_turn: true, turn: 4, updated_at: 1750000000,
		}])), [cacheKeys.mine, rid]);

		// Finish it.
		finishedId = rid;
		fixtureMode = true;
		const fixture = structuredClone(latestFrame);
		fixture.type = "room_update";
		fixture.room.status = "over";
		fixture.room.game.phase = "over";
		fixture.room.game.winner = Object.keys(fixture.room.game.players)[0];
		socket.send(JSON.stringify(fixture));
		const result = await page.waitForSelector(".or-result", { timeout: 15_000 })
			.then(() => true).catch(() => false);
		check("the finished game shows its result screen", result);

		const read = () => page.evaluate(([mineKey, histKey]) => ({
			mine: JSON.parse(localStorage.getItem(mineKey) || "[]"),
			history: JSON.parse(localStorage.getItem(histKey) || "[]"),
		}), [cacheKeys.mine, cacheKeys.history]);
		await page.waitForFunction(([mineKey, histKey, id]) => {
			const mine = JSON.parse(localStorage.getItem(mineKey) || "[]");
			const hist = JSON.parse(localStorage.getItem(histKey) || "[]");
			return !mine.some((g) => g.id === id) && hist.some((g) => g.id === id);
		}, [cacheKeys.mine, cacheKeys.history, rid], { timeout: 15_000 }).catch(() => {});
		const cached = await read();
		check("finishing drops the game from the cached Active list",
			!cached.mine.some((g) => g.id === rid), JSON.stringify(cached.mine));
		check("...and refreshes History with the server's row for it",
			cached.history.some((g) => g.id === rid), JSON.stringify(cached.history));

		// Back to the lobby with both endpoints DEAD, so the columns can only be
		// coming from what the finish wrote.
		await page.unroute("**/orbit/games/mine*");
		await page.unroute("**/orbit/games/history*");
		await page.route("**/orbit/games/mine*", (r) => r.abort());
		await page.route("**/orbit/games/history*", (r) => r.abort());
		await page.goto(`http://localhost:${PORT}/orbit`, { waitUntil: "networkidle" });
		await page.waitForSelector(".orbit .lby-col-history", { timeout: 25_000 }).catch(() => {});
		const columns = await page.evaluate(() => ({
			active: document.querySelectorAll(".lby-col-active .lby-card").length,
			history: [...document.querySelectorAll(".lby-col-history .lby-card")]
				.map((el) => el.textContent.replace(/\s+/g, " ").trim()),
		}));
		check("the lobby you return to files it under History, not Active",
			columns.active === 0 && columns.history.length === 1
			&& columns.history[0].includes("Won") && columns.history[0].includes("Bot"),
			JSON.stringify(columns));
		// The room was created at Easy and the row says so. It is the same path
		// the `lobbyHistory` block covers for Dontminion, run here against a row
		// that came through the finished-game refresh rather than a page load.
		check("...and the row says which bot it was",
			columns.history[0].includes("Easy AI"), JSON.stringify(columns));
		check("no page errors finishing a game and returning to the lobby",
			errors.length === 0, errors[0] || "");
		await ctx.close();
	}

	const laneA = [offlineSpender, offlineCoc, offlineDuel, offlineDissonance,
		dissonanceSkat, dissonanceHard, dissonanceBeat, ragtagFight];
	// `dissonanceQuartet` is lane B: it plays a whole game but arms NO worker
	// (`client_searchable` is false for four hands), and it asserts settled
	// geometry rather than elapsed time -- both of which are what lane B is for.
	const laneB = [routeMounts, shellNav, authScreen, homeScreen, spenderPlayTurn, spenderWaitingRoom,
		rulesModal, dissonanceScorecard, dmExpansionPicker, dmCardFace, lobbyHistory, dmAdventures,
		dmEmpires, dmRenaissance, dmInfoModal, phoneLobbyColumns, lastDifficulty,
		dissonanceQuartet, orbitPlay, lobbyFinishSync];

	// EVERY BLOCK MUST BE IN A LANE. Before the lanes existed, adding a block meant
	// writing it — it then ran because it was simply the next statement. Now it has
	// to be listed as well, and forgetting compiles, runs, and PASSES: the block just
	// never executes, which is a green tick over coverage that did not happen. That
	// is the same failure the repo's no-conditional-skips rule exists to stop, so it
	// gets the same treatment — derived from the source rather than a hand-kept list,
	// because a hardcoded roster only ever guards the set SHRINKING.
	const declared = [...readFileSync(fileURLToPath(import.meta.url), "utf8")
		.matchAll(/^\tasync function (\w+)\(log\)/gm)].map((m) => m[1]);
	const scheduled = new Set([...laneA, ...laneB].map((f) => f.name));
	const orphans = declared.filter((n) => !scheduled.has(n));
	if (orphans.length) {
		throw new Error(`these blocks are defined but in no lane, so they would never run: `
			+ `${orphans.join(", ")} — add each to laneA or laneB (see the lane comment above).`);
	}

	const allBlocks = [...laneA, ...laneB];
	if (ONLY_BLOCKS.length) {
		const byName = new Map(allBlocks.map((fn) => [fn.name, fn]));
		const unknown = ONLY_BLOCKS.filter((name) => !byName.has(name));
		if (unknown.length) {
			throw new Error(`unknown focused screen block(s): ${unknown.join(", ")}`);
		}
		console.log(`SCREENS FOCUS — ${ONLY_BLOCKS.join(", ")}`);
		await runLane(ONLY_BLOCKS.map((name) => byName.get(name)));
	} else {
		await Promise.all([runLane(laneA), runLane(laneB)]);
	}

	if (failures.length || shell.length) {
		console.error(`\nSCREENS FAIL — ${failures.length} screen(s), ${shell.length} shell interaction(s).`);
		process.exitCode = 1;
	} else {
		console.log(`\nSCREENS PASS — ${SCREENS.length} game screens + shell navigation, against a live backend.`);
	}
} catch (err) {
	console.error("SCREENS ERROR:", err.message);
	process.exitCode = 1;
} finally {
	try { await browser?.close(); } catch {}
	shutdown();
}
