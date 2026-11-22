/* CO-OP LOCKSTEP (owner's ask, 2026-11-22). Both browsers run the same deterministic
 * fight (sim.js); each sends only its own controls, and a tick is stepped once both
 * seats' controls for it are known — so the two copies never differ.
 *
 * A control pressed while tick t is stepped applies to tick t + `delay`: that head
 * start is the time it has to cross to the other browser (bossrush/coop.py picks it
 * from the round trips). Ticks before `delay` have no controls from anyone and are
 * empty for both. If the other seat's controls are late, the fight WAITS for them
 * rather than guessing: a guess is a fork.
 *
 * Rows are replay.js's (`recordInput`): the same eight numbers a solo replay keeps,
 * so a co-op tick is recorded as hero 0's row followed by hero 1's. */

export const EMPTY_ROW = Object.freeze([0, 0, 0, 0, 0, 0, 0, 0]);
export const FP_EVERY = 120;            // both fights compare fingerprints every 2 s

/* 32-bit FNV-1a of a string: a fingerprint small enough to send. */
export function hashText(text) {
	let h = 2166136261 >>> 0;
	for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
	return h;
}

export class Lockstep {
	constructor({ seat, delay }) {
		this.seat = seat;
		this.delay = delay;
		this.rows = [new Map(), new Map()];
		this.next = 0;              // first tick not simulated yet
		this.outbox = [];           // our rows not sent yet: { tick, row }
		this.mine = new Map();      // our fingerprints by tick
		this.theirs = new Map();    // theirs, until ours for that tick exists
		this.desync = null;         // the first tick the two fights disagreed on
	}

	/* Can tick `t` be stepped: are both seats' controls for it in? */
	ready(t) {
		return t < this.delay || (this.rows[0].has(t) && this.rows[1].has(t));
	}

	/* Our controls, sampled while tick `t` is stepped: they apply to t + delay. */
	local(t, row) {
		const at = t + this.delay;
		this.rows[this.seat].set(at, row);
		this.outbox.push({ tick: at, row });
	}

	/* The other seat's controls for ticks `from`, `from + 1`, … */
	remote(from, rows) {
		const other = this.rows[1 - this.seat];
		rows.forEach((row, i) => {
			const tick = from + i;
			// Even the faster seat can only simulate one buffer ahead of us.
			if (tick >= Math.max(this.delay, this.next) && tick < this.next + 2 * this.delay + 30 && !other.has(tick)) {
				other.set(tick, row);
			}
		});
	}

	/* Both seats' rows for tick `t` (hero 0's first), forgotten once taken. */
	take(t) {
		this.next = t + 1;
		if (t < this.delay) return [EMPTY_ROW, EMPTY_ROW];
		const a = this.rows[0].get(t), b = this.rows[1].get(t);
		this.rows[0].delete(t); this.rows[1].delete(t);
		return [a, b];
	}

	/* What to send now, if anything: the waiting rows as one contiguous message. A
	 * row waits for a second one (half the messages) unless it is `stale`. */
	flush(stale = false) {
		if (!this.outbox.length || (this.outbox.length < 2 && !stale)) return null;
		const batch = this.outbox.splice(0, 30);
		return { from: batch[0].tick, rows: batch.map((b) => b.row) };
	}

	/* A fingerprint of our fight after tick `t`; true if it disagrees with theirs. */
	ownPrint(t, hash) {
		this.mine.set(t, hash);
		if (this.mine.size > 20) this.mine.delete(this.mine.keys().next().value);
		return this.compare(t);
	}
	theirPrint(t, hash) {
		this.theirs.set(t, hash);
		if (this.theirs.size > 20) this.theirs.delete(this.theirs.keys().next().value);
		return this.compare(t);
	}
	compare(t) {
		if (!this.mine.has(t) || !this.theirs.has(t)) return false;
		const bad = this.mine.get(t) !== this.theirs.get(t);
		this.theirs.delete(t);
		if (bad && this.desync == null) this.desync = t;
		return bad;
	}
}
