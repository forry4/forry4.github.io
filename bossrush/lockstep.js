/* Both browsers confirm a tick once they have both seats' inputs. Co-op sends
 * undelayed inputs and can render ahead via prediction.js. Only confirmed rows
 * go into the replay, as hero 0's eight numbers followed by hero 1's. */

export const EMPTY_ROW = Object.freeze([0, 0, 0, 0, 0, 0, 0, 0]);
export const FP_EVERY = 120;            // both fights compare fingerprints every 2 s
const MAX_BATCH = 30;
const HISTORY_TICKS = 180;

/* 32-bit FNV-1a of a string: a fingerprint small enough to send. */
export function hashText(text) {
	let h = 2166136261 >>> 0;
	for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
	return h;
}

export class Lockstep {
	constructor({ seat, count = 2, window = 60 }) {
		this.seat = seat;
		this.window = window;
		this.rows = Array.from({ length: count }, () => new Map());
		this.next = 0;              // first tick not simulated yet
		this.outbox = [];           // our rows not sent yet: { tick, row }
		this.sent = new Map();      // recently sent rows, in case our partner reports a gap
		this.mine = new Map();      // our fingerprints by tick
		this.theirs = new Map();    // theirs, until ours for that tick exists
		this.desync = null;         // the first tick the two fights disagreed on
	}

	/* Can tick `t` be stepped: are both seats' controls for it in? */
	ready(t) {
		return this.rows.every((rows) => rows.has(t));
	}

	/* The input we sampled for tick t is the input we confirm for tick t. */
	local(t, row) {
		this.rows[this.seat].set(t, row);
		this.outbox.push({ tick: t, row });
	}

	/* The other seat's controls for ticks `from`, `from + 1`, … */
	remote(from, rows, onRow, seat = 1 - this.seat) {
		const other = this.rows[seat];
		if (!other || seat === this.seat) return;
		rows.forEach((row, i) => {
			const tick = from + i;
			if (tick >= this.next && tick < this.next + this.window && !other.has(tick)) {
				other.set(tick, row);
				onRow?.(tick, row);
			}
		});
	}

	/* Both seats' rows for tick `t` (hero 0's first), forgotten once taken. */
	take(t) {
		this.next = t + 1;
		return this.rows.map((rows) => {
			const row = rows.get(t);
			rows.delete(t);
			return row;
		});
	}

	/* Flush at the end of each frame. Slow frames can batch multiple ticks. */
	flush() {
		if (!this.outbox.length) return null;
		const batch = this.outbox.splice(0, MAX_BATCH);
		for (const { tick, row } of batch) {
			this.sent.set(tick, row);
			this.sent.delete(tick - HISTORY_TICKS);
		}
		return { from: batch[0].tick, rows: batch.map((b) => b.row) };
	}

	/* Replay exactly the rows we sent before. Never resample a missing input. */
	resend(from) {
		const rows = [];
		for (let tick = from; rows.length < MAX_BATCH && this.sent.has(tick); tick++) {
			rows.push(this.sent.get(tick));
		}
		return rows.length ? { from, rows } : null;
	}

	/* A fingerprint of our fight after tick `t`; true if it disagrees with theirs. */
	ownPrint(t, hash) {
		this.mine.set(t, hash);
		if (this.mine.size > 20) this.mine.delete(this.mine.keys().next().value);
		return this.compare(t);
	}
	theirPrint(t, hash) {
		if (this.theirs.has(t) && this.theirs.get(t) !== hash) {
			this.desync ??= t;
			return true;
		}
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
