/* Halcyon Rift's side of the wire (design §18.4): who is asking, and the run's
 * event queue.
 *
 * WHO. An account sends its session (Authorization: Bearer). A guest roster is
 * minted by the server once (POST /halcyon/guest) and kept on this device as
 * { owner, secret }; it is sent as two headers on every request.
 *
 * THE QUEUE. What the fight reports — kill, pickup, death, recall, complete — is
 * numbered per run and kept in localStorage BEFORE it is sent, so a closed tab, a
 * server restart or a cold start loses nothing: the next flush, this visit or the
 * next one, delivers it. Re-sending is always safe (the server skips any number it
 * has applied). A run whose last report never arrives is closed as a recall when
 * its character is next opened — which is what closing the tab means (§13.1a).
 *
 * Every storage access is guarded: private windows and blocked storage throw.
 */
import { BACKEND_HTTP } from "../shared/backend.js";

const GUEST_KEY = "halcyon.guest.v1";
const queueKey = (who) => `halcyon.queue.v1.${who}`;

function read(key) {
	try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
}
function write(key, value) {
	try {
		if (value == null) localStorage.removeItem(key);
		else localStorage.setItem(key, JSON.stringify(value));
	} catch { /* storage unavailable: the run still plays, it just cannot outlive the tab */ }
}

export class HalcyonHttpError extends Error {
	constructor(status, message) { super(message); this.status = status; }
}

/* A client for one identity. `authUser` is the shell's identity: an account
 * (session_token) or a guest (whose roster is this device's, not the site's id). */
export function makeClient(authUser, { base = BACKEND_HTTP, fetchImpl = (...a) => fetch(...a) } = {}) {
	const token = authUser && !authUser.guest ? authUser.session_token : null;
	const who = token ? `u.${authUser.id}` : "guest";
	let guest = token ? null : read(GUEST_KEY);

	async function ensureGuest() {
		if (token || (guest && guest.owner && guest.secret)) return;
		const res = await fetchImpl(base + "/halcyon/guest", { method: "POST" });
		if (!res.ok) throw new HalcyonHttpError(res.status, res.status === 429
			? "Too many new rosters from here. Try again later." : "Could not reach the server.");
		guest = await res.json();
		write(GUEST_KEY, guest);
	}

	async function request(path, body, { keepalive = false } = {}) {
		await ensureGuest();
		const headers = { "Content-Type": "application/json" };
		if (token) headers.Authorization = `Bearer ${token}`;
		else { headers["X-Halcyon-Owner"] = guest.owner; headers["X-Halcyon-Secret"] = guest.secret; }
		const res = await fetchImpl(base + path, { method: body === undefined ? "GET" : "POST", headers,
			body: body === undefined ? undefined : JSON.stringify(body), keepalive });
		if (res.status === 401 && !token) {          // the roster was pruned (24h idle): start a new one
			guest = null; write(GUEST_KEY, null);
		}
		if (!res.ok) {
			let msg = `HTTP ${res.status}`;
			try { const j = await res.json(); if (j && typeof j.detail === "string") msg = j.detail; } catch { /* not JSON */ }
			throw new HalcyonHttpError(res.status, msg);
		}
		return res.json();
	}

	// ── the queue: { run_id, next, pending: [{seq, type, ...}] } ─────────────
	const loadQueue = () => read(queueKey(who));
	const saveQueue = (q) => write(queueKey(who), q);

	function beginRun(runId) {
		saveQueue({ run_id: runId, next: 1, pending: [] });
	}
	function report(ev) {
		const q = loadQueue();
		if (!q) return null;
		const numbered = { ...ev, seq: q.next };
		q.next += 1;
		q.pending.push(numbered);
		saveQueue(q);
		return numbered;
	}
	let inFlight = null;
	/* Send what is pending. Resolves to the server's answer, or null when there is
	 * nothing to send or the server cannot be reached (the queue is kept). */
	function flush({ keepalive = false } = {}) {
		if (inFlight) return inFlight.then(() => flush({ keepalive }));
		const q = loadQueue();
		if (!q || !q.pending.length) return Promise.resolve(null);
		const sent = q.pending.slice(0, 500);
		inFlight = request(`/halcyon/runs/${encodeURIComponent(q.run_id)}/events`, { events: sent }, { keepalive })
			.then((out) => {
				const now = loadQueue();
				if (now && now.run_id === q.run_id) {
					now.pending = now.pending.filter((e) => e.seq > out.last_seq);
					// A closed run takes nothing more; a run that is still open may.
					saveQueue(out.status !== "open" && !now.pending.length ? null : now);
				}
				return out;
			})
			.catch((e) => {
				// The server does not know this run (another device, a pruned guest): nothing
				// in the queue can ever be delivered, so holding it would block the next run.
				if (e instanceof HalcyonHttpError && (e.status === 409 || e.status === 401)) saveQueue(null);
				return null;
			})
			.finally(() => { inFlight = null; });
		return inFlight;
	}

	return {
		who,
		state: () => request("/halcyon/state"),
		createCharacter: (slot, classId = "ranger") => request("/halcyon/characters", { slot, class_id: classId }),
		openCharacter: (charId) => request(`/halcyon/characters/${encodeURIComponent(charId)}/open`, {}),
		leaveTown: (charId) => request(`/halcyon/characters/${encodeURIComponent(charId)}/leave`, {}),
		startRun: (charId, dungeonId = "shallows", practice = false, mods = [], bossRush = false) => request("/halcyon/runs",
			{ char_id: charId, dungeon_id: dungeonId, practice, mods, boss_rush: bossRush }),
		descend: (runId, mod, fromLevel) => request(`/halcyon/runs/${encodeURIComponent(runId)}/descend`,
			{ mod, from_level: fromLevel }),
		move: (itemId, to, version) => request(`/halcyon/items/${encodeURIComponent(itemId)}/move`, { to, version }),
		discard: (itemId, version) => request(`/halcyon/items/${encodeURIComponent(itemId)}/discard`, { version }),
		lock: (itemId, locked) => request(`/halcyon/items/${encodeURIComponent(itemId)}/lock`, { locked }),
		fuse: (a, b) => request("/halcyon/fuse", { a, b }),
		reroll: (itemId, keep, version) => request(`/halcyon/items/${encodeURIComponent(itemId)}/reroll`, { keep, version }),
		salvage: (itemId, version) => request(`/halcyon/items/${encodeURIComponent(itemId)}/salvage`, { version }),
		// A run with nothing left to deliver is not "pending": an open run that reported
		// nothing (the tab closed at once) is the server's to close, not the queue's.
		beginRun, report, flush, pendingRun: () => { const q = loadQueue(); return q && q.pending.length ? q.run_id : null; },
	};
}
