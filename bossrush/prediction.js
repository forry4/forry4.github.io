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

export function stepParty(state, rows) {
	return step(state, inputOf(rows.flat()));
}

/* The rendering sim can run ahead of the recorded fight. The latter only uses
 * agreed inputs, and owns events, clocks, portals and the leaderboard. When real
 * input disagrees with a guess, replay the bounded tail from the agreed state. */
export class FightPrediction {
	constructor(lock) {
		this.lock = lock;
		this.peerSeats = lock.rows.map((_, i) => i).filter(i => i !== lock.seat);
		this.peers = new Map(this.peerSeats.map(seat => [seat, {
			used: new Map(), lastAimUse: -1, lastKnownAim: -1, remoteAim: EMPTY_ROW,
			remoteAimTick: -1, confirmedRemote: EMPTY_ROW, lastRemote: EMPTY_ROW,
		}]));
		this.state = null;
		this.next = 0;
		this.dirty = false;
	}

	get used() { return this.peers.get(this.peerSeats[0]).used; }
	get remoteAim() { return this.aimFor(this.peerSeats[0]); }
	aimFor(seat) { return this.peers.get(seat).remoteAim; }

	receive(tick, row, seat = this.peerSeats[0]) {
		const peer = this.peers.get(seat);
		if (tick > peer.remoteAimTick) {
			peer.remoteAimTick = tick;
			peer.remoteAim = row;
		}
		const used = peer.used.get(tick);
		if (!used) return;
		const aimChanged = row[2] !== used[2] || row[3] !== used[3];
		if (row[0] !== used[0] || row[1] !== used[1] || row[4] !== used[4]
			|| row[5] !== used[5] || row[6] !== used[6] || (aimChanged && tick <= peer.lastAimUse)) {
			this.dirty = true;
		}
		// Keep the newest aim for upcoming shots, even when earlier ticks can stay as-is.
		if (tick > peer.lastKnownAim) {
			peer.lastKnownAim = tick;
			peer.lastRemote = heldInput(row);
		}
	}

	confirm(tick, remote, seat = this.peerSeats[0]) {
		const peer = this.peers.get(seat);
		peer.confirmedRemote = heldInput(remote);
		peer.used.delete(tick);
	}

	view(confirmed, sampled) {
		const start = this.lock.next;
		if (sampled === start) {
			this.state = null;
			this.next = start;
			for (const peer of this.peers.values()) peer.lastRemote = peer.confirmedRemote;
			this.dirty = false;
			return confirmed;
		}
		if (!this.state || this.dirty || this.next < start) {
			this.state = copyFight(confirmed);
			this.next = start;
			for (const peer of this.peers.values()) {
				peer.lastRemote = peer.confirmedRemote;
				peer.used.clear();
				peer.lastAimUse = -1;
				peer.lastKnownAim = start - 1;
			}
			this.dirty = false;
		}
		for (; this.next < sampled; this.next++) {
			const rows = this.lock.rows.map((knownRows, seat) => {
				const known = knownRows.get(this.next), peer = this.peers.get(seat);
				if (!peer) return known;
				const remote = known || heldInput(peer.lastRemote);
				peer.used.set(this.next, remote);
				if (known) peer.lastKnownAim = this.next;
				else {
					// Cooldowns tick before firing. A burst can fire after release.
					const body = this.state.heroes[seat].p;
					if (remote[5] || (remote[4] && body.fireCd <= 1) || (body.burstLeft > 0 && body.burstCd <= 1))
						peer.lastAimUse = this.next;
				}
				peer.lastRemote = remote;
				return remote;
			});
			stepParty(this.state, rows);
		}
		return this.state;
	}
}
