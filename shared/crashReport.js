// shared/crashReport.js — tell the owner when a page throws in a player's browser.
//
// A render error used to be seen by exactly one person: the player looking at the
// error screen. This posts a short report to the backend's /ops/client-error
// (core/client_errors.py), which raises it as a `client-error` owner alert — the
// Site health panel and the phone push — deduplicated per build, screen and first
// line of the message, so one bug on one page is one alert with a count.
//
// Three ways in: the error boundaries' componentDidCatch (`source: "boundary"`),
// `window` `error` and `unhandledrejection` (installed once by `installCrashReporting`).
//
// It must never be the second bug on the page, so EVERY path is wrapped and the send
// is fire-and-forget. And it stays quiet when it has nothing useful to say:
//   * a local dev build (`__BUILD_ID__ === "dev"`) — the developer has the console;
//   * offline — the POST could not land, and a crash offline is not news;
//   * after MAX_REPORTS in one page load — a crash loop is one report, not a flood;
//   * the same first line twice — a boundary catch and a window error for one throw;
//   * the known non-bugs: a lazy chunk that failed after a deploy (`lazyChunk` in
//     Spender.jsx already retries it and reloads once), `ResizeObserver loop` noise,
//     a cross-origin "Script error." with nothing in it, and a browser extension's
//     own throws.
// What is sent is the build, the PATH (never the query or hash), the message and a
// trimmed stack. No ids, names or tokens; the server scrubs again regardless.

const BUILD_ID = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const ENV = (typeof import.meta !== "undefined" && import.meta.env) || {};
const WS_BASE = ENV.VITE_WS_URL || "ws://localhost:8000/ws";
export const CRASH_ENDPOINT = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "") + "/ops/client-error";

export const MAX_REPORTS = 3;
export const MESSAGE_MAX = 500;
export const STACK_MAX = 1500;
export const STACK_LINES = 12;

const IGNORED = [
	/ResizeObserver loop/i,
	/Failed to fetch dynamically imported module/i,      // Chrome: a stale chunk after a deploy
	/Importing a module script failed/i,                  // Safari: the same
	/error loading dynamically imported module/i,         // Firefox: the same
	/Unable to preload CSS/i,                             // Vite's own preload helper: the same
	/^Script error\.?$/i,                                 // cross-origin, carries nothing
];
const EXTENSION = /(chrome|moz|safari(-web)?)-extension:\/\//i;

// Turn whatever was thrown (an Error, a string, a rejected `undefined`, an object)
// into a message and a stack. Never throws.
export function describe(err) {
	try {
		if (err instanceof Error || (err && typeof err === "object" && "message" in err)) {
			const name = typeof err.name === "string" && err.name ? err.name : "Error";
			const message = err.message ? `${name}: ${err.message}` : name;
			return { message, stack: typeof err.stack === "string" ? err.stack : "" };
		}
		if (typeof err === "string") return { message: err, stack: "" };
		if (err === undefined || err === null) return { message: String(err), stack: "" };
		let text = "";
		try { text = JSON.stringify(err); } catch { text = String(err); }
		return { message: `Non-error thrown: ${text}`, stack: "" };
	} catch {
		return { message: "", stack: "" };
	}
}

export function shouldIgnore(message, stack = "") {
	if (!message || !message.trim()) return true;
	if (IGNORED.some((re) => re.test(message))) return true;
	// Every frame in an extension's script: not our code. A stack with OUR frames that
	// merely passes through an extension is still ours.
	const frames = String(stack).split("\n").filter((l) => /:\d+:\d+\)?\s*$/.test(l));
	return frames.length > 0 && frames.every((l) => EXTENSION.test(l));
}

export function trimStack(stack, message = "") {
	const lines = String(stack || "").split("\n").map((l) => l.trimEnd()).filter((l) => l.trim());
	// V8 repeats "Name: message" as the stack's first line; the message already says it.
	if (lines.length && message && message.startsWith(lines[0].trim())) lines.shift();
	return lines.slice(0, STACK_LINES).join("\n").slice(0, STACK_MAX);
}

function defaultSend(endpoint, payload) {
	try {
		const p = fetch(endpoint, {
			method: "POST", mode: "cors", credentials: "omit", keepalive: true,
			headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
		});
		if (p && typeof p.catch === "function") p.catch(() => {});
	} catch { /* fire and forget */ }
}

function defaultOnline() {
	try { return typeof navigator === "undefined" || navigator.onLine !== false; } catch { return true; }
}

function defaultRoute() {
	try { return window.location.pathname; } catch { return ""; }
}

// The screens harness runs a LOCAL build ("dev") and still has to see a report reach
// the backend, so it sets this before the page loads. Inert in a real deploy, which is
// never "dev" (CI stamps the commit).
function defaultForce() {
	try { return !!globalThis.__FG_CRASH_REPORTS__; } catch { return false; }
}

export function createReporter({
	build = BUILD_ID, endpoint = CRASH_ENDPOINT, send = defaultSend, isOnline = defaultOnline,
	route = defaultRoute, max = MAX_REPORTS, force = defaultForce,
} = {}) {
	let sent = 0;
	const seen = new Set();
	function report(err, source = "error", extraStack = "") {
		try {
			if (build === "dev" && !force()) return false;
			if (sent >= max) return false;
			if (!isOnline()) return false;
			const { message, stack } = describe(err);
			if (shouldIgnore(message, stack)) return false;
			const first = message.split("\n")[0];
			if (seen.has(first)) return false;
			seen.add(first);
			sent += 1;
			const full = [trimStack(stack, message), String(extraStack || "").replace(/^\s*\n/, "").trimEnd()].filter(Boolean).join("\n");
			send(endpoint, {
				build, route: String(route() || "").split(/[?#]/)[0].slice(0, 200), source,
				message: message.slice(0, MESSAGE_MAX), stack: trimStack(full),
			});
			return true;
		} catch {
			return false;
		}
	}
	return { report, get sent() { return sent; } };
}

const reporter = createReporter();

// From an error boundary. `info.componentStack` is appended: in a production build the
// JS stack is minified, and the component names are what say WHICH screen piece threw.
export function reportBoundaryError(err, info) {
	return reporter.report(err, "boundary", info && info.componentStack);
}

export function reportError(err, source = "error") {
	return reporter.report(err, source);
}

let installed = false;
export function installCrashReporting(target = typeof window !== "undefined" ? window : null) {
	if (installed || !target || typeof target.addEventListener !== "function") return;
	installed = true;
	try {
		target.addEventListener("error", (e) => {
			// A failed <img>/<script> load fires `error` on the element, not with an error
			// object; only a script's uncaught throw carries `message`.
			if (!e || (e.error == null && !e.message)) return;
			reporter.report(e.error != null ? e.error : e.message, "error");
		});
		target.addEventListener("unhandledrejection", (e) => {
			reporter.report(e ? e.reason : undefined, "rejection");
		});
	} catch { /* never the second bug */ }
}
