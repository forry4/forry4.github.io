/* Is the backend up yet? — the one place the frontend answers that.
 *
 * The site used to answer it BEFORE it drew anything: the shell pinged `/games`
 * and sat on "Waking the server…" until it got a 200, so a visitor to a sleeping
 * Render instance looked at a progress bar for ~25 seconds before seeing a menu
 * that needs no server at all, and even a warm visit paid ~1s (a 250ms ping that
 * aborts, a second ping, then a fixed 350ms delay). The shell now lands from
 * local state (shared/... see the boot effect in games/spender/Spender.jsx), and
 * the question moves here, to be asked only by what actually needs the answer.
 *
 * THE PROBE HOLDS ITS REQUEST OPEN. Render's free tier spins down when idle and
 * takes ~20-50s to come back; during that window it either HOLDS a request until
 * the process is up or answers 503. A client that aborts after a few seconds is
 * the pattern the keepalive section of CLAUDE.md records as worse than nothing
 * (it disconnects mid-spin-up), so each attempt waits up to 90s, and only a
 * failure (a refused connection, a 503) is retried, with a short backoff. It
 * asks `/health`, which is a `SELECT 1` — `/games` decoded up to twenty saved
 * games to say the same thing.
 *
 * Once awake, it stays awake for the life of the page: a server that later
 * restarts is the sockets' problem (useAutoReconnect), not a reason to put a
 * "waking" notice back over a game in progress.
 *
 * Two consumers:
 *  - `openSocket(url)` — every game's socket. A socket that fails before it ever
 *    opened while the server is still waking is retried once the server answers,
 *    without telling the game, so a table created or joined during the wake just
 *    takes longer instead of hanging on a socket nobody retries.
 *  - `useBackendAwake` / `useOnBackendAwake` in shared/lobby.jsx — the lobby's
 *    "Connecting…" reads "Waking the server…", and each lobby re-fetches its lists
 *    the moment the server answers (a 503'd fetch during the wake would otherwise
 *    leave the cached rows up until a manual refresh).
 *
 * There is deliberately NO site-wide "waking" banner (one existed 2026-11-12/13):
 * a page that paints from its cache has nothing to apologise for, and the places
 * that really do wait — a lobby with no rows yet, a room's connecting screen —
 * already say "Waking the server…" in their own loading state.
 *
 * No React here on purpose: `node --test` imports this file directly
 * (webapp/test/unit/backend.test.mjs), and shared/ has no node_modules of its own.
 */

const WS_URL = (import.meta.env && import.meta.env.VITE_WS_URL) || "ws://localhost:8000/ws";
export const BACKEND_HTTP = WS_URL.replace(/^ws/, "http").replace(/\/ws$/, "");

// Long enough to outlast a cold start (keepalive.py uses 80s for the same reason).
export const PROBE_ATTEMPT_MS = 90_000;
const RETRY_MAX_MS = 8_000;

let awake = false;
let waiters = [];
const listeners = new Set();

export function isBackendAwake() { return awake; }

/** Anything that just got a real answer from the server may say so. */
export function markBackendAwake() {
	if (awake) return;
	awake = true;
	const w = waiters; waiters = [];
	for (const resolve of w) resolve();
	for (const fn of [...listeners]) { try { fn(); } catch { /* a listener must not break the rest */ } }
}

export function whenBackendAwake() {
	return awake ? Promise.resolve() : new Promise((resolve) => waiters.push(resolve));
}

export function subscribeBackend(fn) {
	listeners.add(fn);
	return () => listeners.delete(fn);
}

// ── The probe ───────────────────────────────────────────────────────────────
let probe = null;
let nudge = null;   // cuts a backoff short (tab foregrounded, network back)

/**
 * Start asking `/health` until it answers. Idempotent: every caller gets the one
 * probe. `attemptMs` / `retryMs` exist for the unit test.
 */
export function startBackendProbe({ base = BACKEND_HTTP, attemptMs = PROBE_ATTEMPT_MS, retryMs = 1000 } = {}) {
	if (probe) return probe;
	const kick = () => { if (nudge) nudge(); };
	try {
		document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") kick(); });
		window.addEventListener("online", kick);
	} catch { /* no DOM (unit test) */ }
	probe = (async () => {
		let tries = 0;
		while (!awake) {
			let timer = null;
			try {
				const ctrl = typeof AbortController === "function" ? new AbortController() : null;
				if (ctrl) timer = setTimeout(() => ctrl.abort(), attemptMs);
				const res = await fetch(`${base}/health`, { cache: "no-store", signal: ctrl?.signal });
				if (res.ok) { markBackendAwake(); break; }
			} catch { /* refused / offline / the 90s ceiling: retry below */ }
			finally { if (timer) clearTimeout(timer); }
			if (awake) break;   // something else (a socket, the session check) got there first
			tries += 1;
			const wait = Math.min(retryMs * 2 ** (tries - 1), RETRY_MAX_MS);
			await new Promise((resolve) => {
				const t = setTimeout(done, wait);
				function done() { clearTimeout(t); nudge = null; resolve(); }
				nudge = done;
				// a socket or the session check may wake us mid-backoff
				if (awake) done();
			});
		}
	})();
	return probe;
}

// ── Sockets ─────────────────────────────────────────────────────────────────
// A WebSocket-shaped wrapper used only while the server is still waking. It opens
// the real socket AT ONCE (Render may hold the upgrade and complete it, and a warm
// server must not pay for a probe first), and if that socket dies before it ever
// opened, it waits for the probe and tries once more — reporting CONNECTING the
// whole time, which is the truth, and which is what keeps useAutoReconnect from
// stacking its own retries on top. Only the second failure reaches the game.
const CONNECTING = 0, CLOSED = 3;

class WakeSocket {
	constructor(url, first) {
		this.url = url;
		this.onopen = null; this.onmessage = null; this.onclose = null; this.onerror = null;
		this._retried = false;
		this._waiting = false;
		this._closedByCaller = false;
		this._attach(first);
	}

	_attach(ws) {
		this._ws = ws;
		let opened = false;
		ws.onopen = (e) => {
			if (this._ws !== ws) return;
			opened = true;
			markBackendAwake();
			this.onopen?.(e);
		};
		ws.onmessage = (e) => { if (this._ws === ws) this.onmessage?.(e); };
		ws.onerror = (e) => {
			if (this._ws !== ws) return;
			if (!opened && this._mayRetry()) return;   // the close that follows retries
			this.onerror?.(e);
		};
		ws.onclose = (e) => {
			if (this._ws !== ws) return;
			if (!opened && this._mayRetry()) {
				this._retried = true;
				this._waiting = true;
				whenBackendAwake().then(() => {
					this._waiting = false;
					if (this._closedByCaller) return;
					this._attach(new WebSocket(this.url));
				});
				return;
			}
			this.onclose?.(e);
		};
	}

	_mayRetry() { return !this._retried && !this._closedByCaller; }

	get readyState() {
		if (this._waiting) return this._closedByCaller ? CLOSED : CONNECTING;
		return this._ws.readyState;
	}

	send(data) {
		// A real socket throws on send() while CONNECTING; so does this one.
		if (this._waiting) throw new Error("InvalidStateError: the socket is still connecting");
		this._ws.send(data);
	}

	close(code, reason) {
		this._closedByCaller = true;
		if (this._waiting) {
			// Nothing is open to close, but a real socket closed while CONNECTING
			// still fires onclose, and callers may rely on that.
			setTimeout(() => this.onclose?.({ code: 1006, reason: "", wasClean: false }), 0);
			return;
		}
		try { this._ws.close(code, reason); } catch { /* already closing */ }
	}
}

/**
 * Open a game socket. Use this, never `new WebSocket` directly — enforced by
 * shared/tests/test_backend_wake.py. Once the server is known to be up it IS
 * `new WebSocket(url)`.
 */
export function openSocket(url) {
	const ws = new WebSocket(url);
	return awake ? ws : new WakeSocket(url, ws);
}

// For the unit test: forget everything between cases.
export function _resetBackendForTest() {
	awake = false; waiters = []; listeners.clear(); probe = null; nudge = null;
}
