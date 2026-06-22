// Smoke test: build the app, serve it, load it in a headless browser, and FAIL if
// the page crashes (empty #root or any uncaught page error) OR if it shifts its
// layout on load past a small budget (Cumulative Layout Shift). Catches two classes
// of bug: (1) the bundle compiles but throws at runtime (e.g. a stray backtick in
// the CSS-in-JS template literal) → blank white page; (2) content/fonts/styles
// arriving after first paint → the "snaps into place" reflow we kept hitting.
//
// Run: `npm run smoke` (from webapp/). Used locally before pushing and in CI.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const webappDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4188;
// Cumulative Layout Shift budget on load. Good CWV is < 0.1; our reflow bugs (font
// swap reflowing the page, a resizing control) blow well past it. Keep it tight so
// regressions are caught; raise only with a documented reason.
const CLS_BUDGET = 0.1;
// Default build base is / (vite.config); preview serves at the root.
const url = `http://localhost:${PORT}/`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function run(cmd, args, env) {
	return new Promise((res, rej) => {
		const p = spawn(cmd, args, { cwd: webappDir, stdio: "inherit", shell: true, env: { ...process.env, ...env } });
		p.on("exit", (c) => (c === 0 ? res() : rej(new Error(`${cmd} ${args.join(" ")} exited ${c}`))));
	});
}

async function waitForServer() {
	for (let i = 0; i < 80; i++) {
		try { const r = await fetch(url); if (r.ok) return true; } catch {}
		await sleep(250);
	}
	return false;
}

async function launchBrowser() {
	// Bundled chromium in CI (after `playwright install chromium`); fall back to the
	// system Edge channel locally so no extra download is needed.
	try { return await chromium.launch(); }
	catch { return await chromium.launch({ channel: "msedge" }); }
}

let code = 1;
let preview;
try {
	// Build with the default base (/); preview serves it at the root. The JS is
	// identical across bases, so a render crash is caught regardless.
	await run("npx", ["vite", "build"], {});
	preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"],
		{ cwd: webappDir, stdio: "ignore", shell: true });

	if (!(await waitForServer())) throw new Error("preview server did not start");

	const browser = await launchBrowser();
	const page = await browser.newPage();
	const pageErrors = [];
	page.on("pageerror", (e) => pageErrors.push(e.message));
	// Accumulate layout-shift BEFORE any page script runs. buffered:true also catches
	// shifts from before the observer attached; hadRecentInput excludes user-driven ones.
	await page.addInitScript(() => {
		window.__cls = 0;
		try {
			new PerformanceObserver((list) => {
				for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value;
			}).observe({ type: "layout-shift", buffered: true });
		} catch {}
	});
	await page.goto(url, { waitUntil: "load", timeout: 30000 });
	await sleep(3000); // let React mount, fonts load, and the first real screen settle
	const rootLen = await page.evaluate(() => document.getElementById("root")?.innerHTML.length ?? 0);
	const cls = await page.evaluate(() => Math.round((window.__cls || 0) * 1000) / 1000);
	await browser.close();

	if (pageErrors.length) {
		console.error("SMOKE FAIL — uncaught page error(s):\n" + pageErrors.join("\n").slice(0, 1000));
	} else if (rootLen < 100) {
		console.error(`SMOKE FAIL — #root did not render (innerHTML length ${rootLen}); app is blank.`);
	} else if (cls > CLS_BUDGET) {
		console.error(`SMOKE FAIL — layout shifted on load (CLS ${cls} > ${CLS_BUDGET}); something resizes/reflows after first paint.`);
	} else {
		console.log(`SMOKE PASS — app rendered (#root length ${rootLen}), CLS ${cls} <= ${CLS_BUDGET}, no uncaught page errors.`);
		code = 0;
	}
} catch (e) {
	console.error("SMOKE FAIL — " + (e?.stack || e?.message || e));
} finally {
	try { preview?.kill(); } catch {}
	process.exit(code);
}
