/* The SITE SHELL: capture the three screens every visitor sees, at a width ladder.
 *
 * NOT A GATE — `npm run screens` decides whether the frontend ships, and its
 * `homeScreen` block already measures the things that can be measured (the content
 * column's width, the accent contrast/hue/luminance, the emblem plates, 14 breakpoint
 * boundaries, the wordmark lockup at two viewports). This exists for the things that
 * cannot: whether the page has a light source, whether seven icons read as one set,
 * whether a gap is breathing room or a missing element. It is the shell's counterpart
 * to `shots.mjs`, which does the same job for Rag Tag.
 *
 * Same convention as that file: it boots NOTHING. Point it at a `vite preview`/`vite
 * dev` on 5173 and a backend on 8000 that are already up, and an iteration costs
 * seconds. (It used to capture a LOADING screen too, by stalling the shell's backend
 * ping; there is none since the boot stopped waiting for the server, 2026-11-12.)
 *
 * Captures are `reducedMotion:"reduce"`, so what you see is the reduced-motion
 * rendering: if that one is right, the other is a superset.
 *
 * READING THE OUTPUT — two artefacts of full-page capture, neither a bug:
 *   - the ambient ground is `position:fixed`, so on a page taller than one viewport it
 *     paints over the first screenful only, and everything below looks flat with a hard
 *     seam at the viewport height. `phone-top`/`phone-bottom` are viewport-only and
 *     show the real thing.
 *   - tall captures sometimes ghost a line of text near the top; that is stitching.
 *
 *   cd webapp && node test/shell-shots.mjs <outDir> [--only=home|auth]
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "shell-shots";
const only = (process.argv.find((a) => a.startsWith("--only=")) || "").split("=")[1];
const PORT = 5173;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const VIEWS = [
	{ tag: "phone-sm", w: 320, h: 640, dsf: 2 },
	{ tag: "phone", w: 390, h: 844, dsf: 2 },
	{ tag: "tablet", w: 834, h: 1112, dsf: 2 },
	{ tag: "laptop", w: 1280, h: 800, dsf: 2 },
	{ tag: "desktop", w: 1920, h: 1080, dsf: 1 },
	{ tag: "wide", w: 2560, h: 1400, dsf: 1 },
];

const GUEST = () => localStorage.setItem("spender_user",
	JSON.stringify({ id: "shell-shots", name: "Harness", guest: true }));

const browser = await chromium.launch().catch(() => chromium.launch({ channel: "msedge" }));
const probes = [];

/** One capture. */
async function shot(name, { view, guest = true, after, probe, fullPage = true } = {}) {
	const ctx = await browser.newContext({
		viewport: { width: view.w, height: view.h }, deviceScaleFactor: view.dsf, reducedMotion: "reduce",
	});
	if (guest) await ctx.addInitScript(GUEST);
	const page = await ctx.newPage();
	const errs = [];
	page.on("pageerror", (e) => errs.push(String(e)));
	page.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text()); });
	await page.goto(`http://localhost:${PORT}/`, { waitUntil: "load", timeout: 30_000 });
	await page.waitForSelector(".home-game-card,.auth-card", { timeout: 25_000 })
		.catch(() => {});
	await sleep(700);
	if (after) await after(page);
	await sleep(350);
	await page.screenshot({ path: path.join(OUT, `${name}.${view.tag}.png`), fullPage });
	if (probe) probes.push({ name, view: view.tag, ...(await page.evaluate(probe)) });
	console.log(`  ${name}.${view.tag}.png${errs.length ? "   PAGE ERRORS: " + errs.join(" | ").slice(0, 240) : ""}`);
	await ctx.close();
}

// Geometry worth having next to the pictures: a shot tells you it looks wrong, this
// tells you by how much.
const homeProbe = () => {
	const cards = [...document.querySelectorAll(".home-game-card")];
	const box = document.querySelector(".home").getBoundingClientRect();
	return {
		docH: document.documentElement.scrollHeight, innerH: window.innerHeight,
		fits: document.documentElement.scrollHeight <= window.innerHeight,
		overflowX: document.documentElement.scrollWidth > window.innerWidth,
		column: Math.round(box.width),
		cardW: [...new Set(cards.slice(0, 6).map((c) => Math.round(c.getBoundingClientRect().width)))],
		cardH: [...new Set(cards.map((c) => Math.round(c.getBoundingClientRect().height)))],
	};
};

try {
	if (!only || only === "home") {
		for (const view of VIEWS) await shot("home", { view, probe: homeProbe });
		// Viewport-only, top and bottom: the fixed ambient ground is only honest here.
		const v = VIEWS[1];
		const ctx = await browser.newContext({ viewport: { width: v.w, height: v.h }, deviceScaleFactor: 2, reducedMotion: "reduce" });
		await ctx.addInitScript(GUEST);
		const page = await ctx.newPage();
		await page.goto(`http://localhost:${PORT}/`, { waitUntil: "load" });
		await page.waitForSelector(".home-game-card", { timeout: 25_000 }).catch(() => {});
		await sleep(700);
		await page.screenshot({ path: path.join(OUT, "phone-top.png") });
		await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
		await sleep(500);
		await page.screenshot({ path: path.join(OUT, "phone-bottom.png") });
		await ctx.close();
		console.log("  phone-top.png / phone-bottom.png");
	}
	if (!only || only === "auth") {
		for (const view of VIEWS) await shot("auth-login", { view, guest: false });
		for (const view of [VIEWS[1], VIEWS[3]]) {
			await shot("auth-register", { view, guest: false, after: (p) => p.locator(".auth-tab").nth(1).click() });
			await shot("auth-guest", { view, guest: false, after: (p) => p.locator(".auth-tab").nth(2).click() });
		}
	}
	if (probes.length) {
		writeFileSync(path.join(OUT, "probe.json"), JSON.stringify(probes, null, 1));
		for (const p of probes) console.log("  probe", p.view, JSON.stringify(p));
	}
	console.log("done ->", OUT);
} finally {
	await browser.close();
}
