import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { EMPTY_ROW, FP_EVERY, Lockstep, hashText } from "../../../bossrush/lockstep.js";
import { inputOf, recordInput } from "../../../bossrush/replay.js";
import { createSim, fingerprint, step } from "../../../bossrush/sim.js";

test("a tick confirms once both seats' inputs for that exact tick arrive", () => {
	const a = new Lockstep({ seat: 0 });
	assert(!a.ready(0));
	a.local(0, [1, 0, 1, 0, 1, 0, 0, 0]);
	assert(!a.ready(0), "ours is in, theirs is not");
	a.remote(0, [[0, 1, 0, 1, 0, 0, 0, 0]]);
	assert(a.ready(0));
	assert.deepEqual(a.take(0), [[1, 0, 1, 0, 1, 0, 0, 0], [0, 1, 0, 1, 0, 0, 0, 0]], "hero 0's row first, whatever our seat");
	const b = new Lockstep({ seat: 1 });
	b.local(0, [5, 0, 0, 0, 0, 0, 0, 0]);
	b.remote(0, [[7, 0, 0, 0, 0, 0, 0, 0]]);
	assert.deepEqual(b.take(0).map((r) => r[0]), [7, 5], "seat 1's own row is hero 1's");
});

test("flush sends a single input immediately or a contiguous batch", () => {
	const l = new Lockstep({ seat: 0 });
	l.local(0, EMPTY_ROW);
	assert.deepEqual(l.flush(), { from: 0, rows: [EMPTY_ROW] });
	l.local(1, EMPTY_ROW); l.local(2, EMPTY_ROW);
	assert.deepEqual(l.flush(), { from: 1, rows: [EMPTY_ROW, EMPTY_ROW] });
	assert.equal(l.flush(), null);
});

test("fingerprints are compared whichever arrives first", () => {
	const l = new Lockstep({ seat: 0 });
	assert.equal(l.theirPrint(120, 5), false);
	assert.equal(l.ownPrint(120, 5), false, "they agree");
	assert.equal(l.ownPrint(240, 9), false);
	assert.equal(l.theirPrint(240, 8), true, "they disagree");
	assert.equal(l.desync, 240);
	assert.equal(hashText("abc"), hashText("abc"));
	assert.notEqual(hashText("abc"), hashText("abd"));
});

test("late, duplicate and out of window inputs cannot replace or queue a row", () => {
	const l = new Lockstep({ seat: 0 });
	const row = [1, 0, 1, 0, 0, 0, 0, 0];
	l.local(0, EMPTY_ROW);
	l.remote(0, [row]);
	l.remote(0, [EMPTY_ROW]);
	assert.deepEqual(l.take(0), [EMPTY_ROW, row]);
	l.remote(0, [EMPTY_ROW, row]);
	l.remote(1000, [row]);
	assert.deepEqual([...l.rows[1]], [[1, row]]);
});

test("a lost input batch can be restored using the original rows", () => {
	const host = new Lockstep({ seat: 0 });
	const guest = new Lockstep({ seat: 1 });
	const move = [1, 0, 1, 0, 0, 0, 0, 0];
	host.local(0, move);
	host.flush();  // first batch did not reach the other browser
	host.local(1, EMPTY_ROW);
	const next = host.flush();
	guest.remote(next.from, next.rows);
	guest.local(0, EMPTY_ROW);
	assert(!guest.ready(0));
	const repaired = host.resend(0);
	guest.remote(repaired.from, repaired.rows);
	assert(guest.ready(0));
	assert.deepEqual(guest.take(0), [move, EMPTY_ROW]);
});

/* Two browsers in one process: each runs its own sim and only ever learns the other's
 * controls through `remote`, late and in bursts. Their fights must match tick for tick. */
test("two lockstepped fights stay identical over a jittery link", () => {
	const window = 32;
	const dungeon = {
		id: "shallows", boss_kind: "tidewarden", seed: "lockstep", width: 24, height: 17,
		tiles: ["#".repeat(24), ...Array(15).fill("#" + ".".repeat(22) + "#"), "#".repeat(24)],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } }, drops: {}, pickups: [], scale: { dmg: 0.3 },
	};
	const peers = [0, 1].map((seat) => {
		const st = createSim(dungeon, CHARACTERS.ranger.gear, { classId: "ranger" }, { gear: CHARACTERS.simon.gear, classId: "simon" });
		st.enemies[0].active = true;
		return { seat, st, lock: new Lockstep({ seat, window: 2 * window + 30 }), t: 0, sampled: 0, prints: [] };
	});
	const wire = [[], []];                 // messages in flight TO each seat, with when they land
	let seed = 7;
	const rnd = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296);
	const controls = (seat, t) => recordInput({ mx: Math.sign(Math.sin(t / (30 + seat * 7))), my: seat ? 1 : -1, ax: 1 - 2 * seat, ay: 0.25,
		fire: t % 50 < 40, ability: t % (90 + seat * 20) === 0, enter: false }, false);
	for (let now = 0; now < 2400; now++) {
		for (const p of peers) {
			for (const m of wire[p.seat].filter((m) => m.at <= now)) p.lock.remote(m.from, m.rows);
			wire[p.seat] = wire[p.seat].filter((m) => m.at > now);
			// A peer runs a little faster or slower than real time, as browsers do.
			const steps = rnd() < 0.1 ? 0 : rnd() < 0.1 ? 2 : 1;
			for (let k = 0; k < steps && p.sampled - p.t < window; k++) {
				p.lock.local(p.sampled, controls(p.seat, p.sampled));
				p.sampled++;
			}
			while (p.lock.ready(p.t)) {
				const [r0, r1] = p.lock.take(p.t);
				step(p.st, { ...inputOf(r0), co: inputOf(r1) });
				p.t++;
				if (p.t % FP_EVERY === 0) p.prints.push(hashText(fingerprint(p.st)));
			}
			const msg = p.lock.flush();
			if (msg) wire[1 - p.seat].push({ ...msg, at: now + 1 + Math.floor(rnd() * 18) });
		}
	}
	const [x, y] = peers;
	assert(Math.min(x.t, y.t) > 1800, `both fights kept moving (${x.t}, ${y.t})`);
	const n = Math.min(x.prints.length, y.prints.length);
	assert(n >= 15);
	assert.deepEqual(x.prints.slice(0, n), y.prints.slice(0, n), "the two fights never differ");
	assert.notEqual(x.st.enemies[0].hp, x.st.enemies[0].maxHp, "and something happened in them");
});
