import { EMPTY_ROW } from "./lockstep.js";
import { inputOf } from "./replay.js";
import { step } from "./sim.js";

const heldInput = (row) => row[5] || row[6] ? [row[0], row[1], row[2], row[3], row[4], 0, 0, row[7]] : row;

export function stepPair(state, a, b) {
	const input = inputOf(a);
	input.co = inputOf(b);
	return step(state, input);
}

/* The rendering sim can run ahead of the recorded fight. The latter only uses
 * agreed inputs, and owns events, clocks, portals and the leaderboard. When real
 * input disagrees with a guess, replay the bounded tail from the agreed state. */
export class FightPrediction {
	constructor(lock) {
		this.lock = lock;
		this.partner = 1 - lock.seat;
		this.used = new Map();
		this.confirmedRemote = EMPTY_ROW;
		this.lastRemote = EMPTY_ROW;
		this.state = null;
		this.next = 0;
		this.dirty = false;
	}

	receive(tick, row) {
		const used = this.used.get(tick);
		if (used && row.slice(0, 7).some((value, i) => value !== used[i])) this.dirty = true;
	}

	confirm(tick, remote) {
		this.confirmedRemote = heldInput(remote);
		this.used.delete(tick);
	}

	view(confirmed, sampled) {
		const start = this.lock.next;
		if (sampled === start) {
			this.state = null;
			this.next = start;
			this.lastRemote = this.confirmedRemote;
			this.dirty = false;
			return confirmed;
		}
		if (!this.state || this.dirty || this.next < start) {
			this.state = structuredClone(confirmed);
			this.state.tiles = confirmed.tiles;  // immutable; keep the canvas map cache warm
			this.next = start;
			this.lastRemote = this.confirmedRemote;
			this.used.clear();
			this.dirty = false;
		}
		for (; this.next < sampled; this.next++) {
			const known = this.lock.rows[this.partner].get(this.next);
			const remote = known || heldInput(this.lastRemote);
			const local = this.lock.rows[this.lock.seat].get(this.next);
			this.used.set(this.next, remote);
			this.lastRemote = remote;
			if (this.partner === 1) stepPair(this.state, local, remote);
			else stepPair(this.state, remote, local);
		}
		return this.state;
	}
}
