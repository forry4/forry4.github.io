import { EMPTY_ROW } from "./lockstep.js";
import { inputOf } from "./replay.js";
import { step } from "./sim.js";

const heldInput = (row) => row[5] || row[6] ? [row[0], row[1], row[2], row[3], row[4], 0, 0, row[7]] : row;

// Arena geometry and encounter definitions are read-only during a fight.
function copyFight(confirmed) {
	const { tiles, rooms, roomY, doorCols, crackAt, dropsBy, healsBy, levels, offers, bullets, ...fight } = confirmed;
	// Projectiles are flat records except for their per-shot list of hit IDs.
	// Copy them directly: they dominate the snapshot during dense patterns.
	const shots = bullets.map((bullet) => ({ ...bullet, hit: bullet.hit.slice() }));
	return { ...structuredClone(fight), tiles, rooms, roomY, doorCols, crackAt, dropsBy, healsBy, levels, offers, bullets: shots };
}

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
		this.lastAimUse = -1;
		this.lastKnownAim = -1;
		this.remoteAim = EMPTY_ROW;
		this.remoteAimTick = -1;
		this.confirmedRemote = EMPTY_ROW;
		this.lastRemote = EMPTY_ROW;
		this.state = null;
		this.next = 0;
		this.dirty = false;
	}

	receive(tick, row) {
		if (tick > this.remoteAimTick) {
			this.remoteAimTick = tick;
			this.remoteAim = row;
		}
		const used = this.used.get(tick);
		if (!used) return;
		const aimChanged = row[2] !== used[2] || row[3] !== used[3];
		if (row[0] !== used[0] || row[1] !== used[1] || row[4] !== used[4]
			|| row[5] !== used[5] || row[6] !== used[6] || (aimChanged && tick <= this.lastAimUse)) {
			this.dirty = true;
		}
		// Keep the newest aim for upcoming shots, even when earlier ticks can stay as-is.
		if (tick > this.lastKnownAim) {
			this.lastKnownAim = tick;
			this.lastRemote = heldInput(row);
		}
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
			this.state = copyFight(confirmed);
			this.next = start;
			this.lastRemote = this.confirmedRemote;
			this.used.clear();
			this.lastAimUse = -1;
			this.lastKnownAim = start - 1;
			this.dirty = false;
		}
		for (; this.next < sampled; this.next++) {
			const known = this.lock.rows[this.partner].get(this.next);
			const remote = known || heldInput(this.lastRemote);
			const local = this.lock.rows[this.lock.seat].get(this.next);
			this.used.set(this.next, remote);
			if (known) {
				this.lastKnownAim = this.next;
			} else {
				// playerFire counts cooldowns down before firing. A burst can fire
				// even after the player releases the trigger.
				const body = this.state.heroes[this.partner].p;
				if (remote[5] || (remote[4] && body.fireCd <= 1) || (body.burstLeft > 0 && body.burstCd <= 1)) {
					this.lastAimUse = this.next;
				}
			}
			this.lastRemote = remote;
			if (this.partner === 1) stepPair(this.state, local, remote);
			else stepPair(this.state, remote, local);
		}
		return this.state;
	}
}
