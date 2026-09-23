// Smoke test: build the app, serve it, load it in a headless browser, and FAIL if
// the page crashes (empty #root or any uncaught page error) OR if it shifts its
// layout on load past a small budget (Cumulative Layout Shift). Catches two classes
// of bug: (1) the bundle compiles but throws at runtime (e.g. a stray backtick in
// the CSS-in-JS template literal) → blank white page; (2) content/fonts/styles
// arriving after first paint → the "snaps into place" reflow we kept hitting.
//
// Run: `npm run smoke` (from webapp/). Used locally before pushing and in CI.
import { spawn } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const webappDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(webappDir, "..");

// ── Static guard: NO backtick inside a `const css = ` ... `;` template literal ──
// The runtime blank-page check (below) does NOT reliably catch this: a stray backtick
// pair parses as a valid tagged template `(str).cls`...`` that throws at module load —
// but esbuild's build output made it benign in the local build while the deployed build
// blanked the page (build-env-dependent), so the render check greenlit a blank deploy
// TWICE. The css literals are hand-authored and must contain no backtick but their two
// delimiters (documented footgun in every game's jsx). Enforce it at the SOURCE so it
// cannot depend on the bundler at all.
function checkCssBackticks() {
	const jsxFiles = [];
	const walk = (dir) => {
		for (const name of readdirSync(dir)) {
			if (name === "node_modules" || name === "dist" || name.startsWith(".")) continue;
			const full = path.join(dir, name);
			if (statSync(full).isDirectory()) walk(full);
			else if (name.endsWith(".jsx")) jsxFiles.push(full);
		}
	};
	for (const d of ["games", "books", "notes", "shared", "webapp"]) {
		try { walk(path.join(repoRoot, d)); } catch {}
	}
	const bad = [];
	for (const file of jsxFiles) {
		const src = readFileSync(file, "utf8");
		// find each css-named template literal opening: `const <...css...> = [prefix]` then `
		const re = /const\s+(\w*[cC]ss\w*)\s*=\s*[^`\n]*`/g;
		let m;
		while ((m = re.exec(src))) {
			const open = m.index + m[0].length;   // first char INSIDE the literal
			// walk to the TRUE close (first top-level backtick), honoring \escape + ${ } interp
			let i = open, depth = 0;
			for (; i < src.length; i++) {
				const c = src[i];
				if (c === "\\") { i++; continue; }
				if (c === "$" && src[i + 1] === "{") { depth++; i++; continue; }
				if (depth > 0) { if (c === "}") depth--; continue; }
				if (c === "`") break;              // top-level close
			}
			// A well-formed literal is followed by a statement continuation (; + , ) ] } or EOF).
			// A STRAY backtick makes the literal "close" early, followed by e.g. `.coc\`...` —
			// which does NOT match, so it's flagged. (This is the whole bug: `(str).coc\`...\`.)
			if (!/^\s*([;+,)\]}]|$)/.test(src.slice(i + 1))) {
				const line = src.slice(0, i).split("\n").length;
				bad.push(`${path.relative(repoRoot, file)}:${line}: "${m[1]}" template literal closes with a STRAY backtick (content follows the closing \`: ${JSON.stringify(src.slice(i + 1, i + 10))}) — this blanks the page. No backtick may appear inside a css template literal.`);
			}
			re.lastIndex = i + 1;
		}
	}
	if (bad.length) throw new Error("CSS BACKTICK GUARD failed:\n  " + bad.join("\n  "));
	console.log("css-backtick guard: OK (no stray backticks in any css template literal)");
}

// ── Static guard: EVERY @font-face file is preloaded in index.html ─────────────
// font-display:optional drops a face that isn't ready within its ~100ms block
// period for the WHOLE page load — it does not swap the font in when it lands.
// So an un-preloaded face renders in the metric-matched Georgia fallback (same
// widths, visibly heavier) until a reload warms the cache, and NO runtime check
// sees it: CLS stays 0 by design, and the page has no errors. That shipped for
// months on the Crimson Pro ITALIC face, which is used by every hint, empty
// state and log line on the site. Adding a font means adding its preload.
function checkFontPreloads() {
	const css = readFileSync(path.join(repoRoot, "shared", "theme.base-css.css"), "utf8");
	const html = readFileSync(path.join(webappDir, "index.html"), "utf8");
	// only real webfont files — the `local()` fallback faces have nothing to fetch
	const faces = [...css.matchAll(/url\(([^)]*?\.woff2)\)/g)].map((m) => m[1].split("/").pop());
	const preloaded = new Set([...html.matchAll(/rel=["']preload["'][^>]*?href=["']([^"']+)["']/g)]
		.map((m) => m[1].split("/").pop()));
	const missing = [...new Set(faces)].filter((f) => !preloaded.has(f));
	if (missing.length) {
		throw new Error("FONT PRELOAD GUARD failed:\n  " + missing.map((f) =>
			`${f} is an @font-face src but has no <link rel="preload"> in index.html — with ` +
			`font-display:optional it will render as the heavier Georgia fallback until reload`
		).join("\n  "));
	}
	console.log(`font-preload guard: OK (all ${faces.length} @font-face files preloaded)`);
}
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

// Bundled chromium in CI (after `playwright install chromium`); fall back to the
// system Edge channel locally so no extra download is needed.
//
// `PLAYWRIGHT_CHROMIUM_PATH` is the same escape hatch `screens.mjs` already has,
// and for the same reason: a box with a preinstalled Chromium that Playwright's
// pin does not name (a container image where the pin moved 1194 -> 1228) can run
// neither of the first two branches, and the gate stops being runnable at all.
// The two gates are always run together, so having it on only one of them meant
// the pair failed anyway.
async function launchBrowser() {
	const exe = process.env.PLAYWRIGHT_CHROMIUM_PATH;
	if (exe) return await chromium.launch({ executablePath: exe });
	try { return await chromium.launch(); }
	catch { return await chromium.launch({ channel: "msedge" }); }
}

// Load one path and return its health. checkCls only applies on "/" (the deep-link
// paths may legitimately transition screens when a local backend is running, and their
// point is the ROUTER: render + no crash + the URL survives — pathPrefix catches both a
// router parse crash and an accidental normalize-to-"/").
async function checkPage(browser, pagePath, { checkCls = false, pathPrefix = null } = {}) {
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
	await page.goto(`http://localhost:${PORT}${pagePath}`, { waitUntil: "load", timeout: 30000 });
	// SETTLE. The CLS path keeps the full fixed window: a layout shift is by
	// definition something that happens LATE, so waiting only until the page looks
	// ready is precisely the wrong test — it would stop measuring at the moment the
	// shift is most likely to arrive. That budget is the gate, so it stays.
	//
	// The other three paths assert something entirely different (render + no crash +
	// the URL survived), all of which are true as soon as #root has content. They
	// were paying the same 3s for no coverage: 9 of smoke's ~16s spent waiting for a
	// measurement nobody reads. Wait for the condition instead, with the old sleep
	// as the ceiling so a genuinely slow mount still gets its full window.
	if (checkCls) {
		await sleep(3000); // let React mount, fonts load, and the first real screen settle
	} else {
		await page.waitForFunction(
			() => (document.getElementById("root")?.innerHTML.length ?? 0) >= 100,
			null, { timeout: 3000 },
		).catch(() => {});
	}
	const rootLen = await page.evaluate(() => document.getElementById("root")?.innerHTML.length ?? 0);
	const cls = await page.evaluate(() => Math.round((window.__cls || 0) * 1000) / 1000);
	const pathname = await page.evaluate(() => window.location.pathname);
	await page.close();

	if (pageErrors.length) return `uncaught page error(s):\n` + pageErrors.join("\n").slice(0, 1000);
	if (rootLen < 100) return `#root did not render (innerHTML length ${rootLen}); app is blank.`;
	if (checkCls && cls > CLS_BUDGET) return `layout shifted on load (CLS ${cls} > ${CLS_BUDGET}); something resizes/reflows after first paint.`;
	if (pathPrefix && !pathname.startsWith(pathPrefix)) return `URL not preserved (pathname ${pathname}, expected ${pathPrefix}...); the router normalized/crashed.`;
	console.log(`  ${pagePath} OK — #root length ${rootLen}, CLS ${cls}, pathname ${pathname}`);
	return null;
}

let code = 1;
let preview;
try {
	// Build with the default base (/); preview serves it at the root. The JS is
	// identical across bases, so a render crash is caught regardless. Note vite preview
	// serves index.html for unknown paths (SPA-style), so the deep-link checks exercise
	// the ROUTER, not the Pages 404.html fallback (that's prod-only; see deploy-pages.yml).
	checkCssBackticks();   // source-level guard for the stray-css-backtick blank-page bug
	checkFontPreloads();   // source-level guard for the un-preloaded-face fallback bug
	await run("npx", ["vite", "build"], {});
	preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"],
		{ cwd: webappDir, stdio: "ignore", shell: true });

	if (!(await waitForServer())) throw new Error("preview server did not start");

	const browser = await launchBrowser();
	const checks = [
		["/", { checkCls: true }],                        // the original blank-page + CLS gate
		["/duel", { pathPrefix: "/duel" }],               // mode deep link survives + renders
		["/dontminion", { pathPrefix: "/dontminion" }],   // 5th game's mode deep link
		["/spender/ABCDEF", { pathPrefix: "/spender" }],  // room-segment parse (Layer B may normalize to /spender)
	];
	const failures = [];
	for (const [p, opts] of checks) {
		const err = await checkPage(browser, p, opts);
		if (err) failures.push(`${p}: ${err}`);
	}
	await browser.close();

	if (failures.length) {
		console.error("SMOKE FAIL —\n" + failures.join("\n"));
	} else {
		console.log(`SMOKE PASS — all ${checks.length} paths rendered, CLS within ${CLS_BUDGET}, no uncaught page errors.`);
		code = 0;
	}
} catch (e) {
	console.error("SMOKE FAIL — " + (e?.stack || e?.message || e));
} finally {
	try { preview?.kill(); } catch {}
	process.exit(code);
}
