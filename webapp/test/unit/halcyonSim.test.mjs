/* Halcyon Rift's simulation (halcyon/sim.js): deterministic, and a run played
 * through it produces only events the server's store would accept.
 * The fixtures are real dungeons from halcyon/dungeon.py, held to the generator
 * by halcyon/tests/test_sim_fixtures.py. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, fingerprint, dsin, dcos, recoveryLimit, statsFor, TPS, REACH } from "../../../halcyon/sim.js";

const load = (s) => JSON.parse(readFileSync(new URL(`./fixtures/halcyon-dungeon-${s}.json`, import.meta.url)));
const A = load("unit-a"), B = load("unit-b");
const STARTER = [{ base_id: "shortbow", tier: 1 }, { base_id: "leather_vest", tier: 1 }, { base_id: "volley_quiver", tier: 1 }];
const solid = (d, x, y) => "#o~".includes(d.tiles[Math.floor(y)][Math.floor(x)]);

/* A bot that walks the BFS path to the nearest live enemy (then the portal),
 * fires at it, uses the ability, and picks up every bag it reaches. */
function bfsNext(st, fx, fy, tx, ty) {
	const key = (x, y) => y * st.w + x, seen = new Map([[key(fx, fy), -1]]), q = [[fx, fy]];
	while (q.length) {
		const [x, y] = q.shift();
		if (x === tx && y === ty) break;
		for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {
			if (seen.has(key(nx, ny)) || "#o~".includes(st.tiles[ny][nx])) continue;
			seen.set(key(nx, ny), key(x, y));
			q.push([nx, ny]);
		}
	}
	let k = key(tx, ty);
	if (!seen.has(k)) return null;
	while (seen.get(k) !== key(fx, fy) && seen.get(k) !== -1) k = seen.get(k);
	return [k % st.w + 0.5, Math.floor(k / st.w) + 0.5];
}
function bot(st, t) {
	const p = st.p;
	const live = st.enemies.filter((e) => e.hp > 0);
	const bag = st.bags[0];
	const goal = bag || (live.length ? live.reduce((a, e) => (dist(p, e) < dist(p, a) ? e : a)) : st.portal);
	const tgt = live.length ? live.reduce((a, e) => (dist(p, e) < dist(p, a) ? e : a)) : null;
	let mx = 0, my = 0;
	if (goal && dist(p, goal) > 0.6) {
		const nxt = bfsNext(st, Math.floor(p.x), Math.floor(p.y), Math.floor(goal.x), Math.floor(goal.y)) || [goal.x, goal.y];
		mx = Math.abs(nxt[0] - p.x) > 0.08 ? Math.sign(nxt[0] - p.x) : 0;
		my = Math.abs(nxt[1] - p.y) > 0.08 ? Math.sign(nxt[1] - p.y) : 0;
	}
	return { mx, my, ax: tgt ? tgt.x - p.x : 1, ay: tgt ? tgt.y - p.y : 0, fire: !!tgt,
		ability: t % 50 === 0, take: bag && dist(p, bag) < 1 ? bag.drops[0] : null, heal: t % 30 === 0,
		enter: !bag && !live.length };
}
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

function play(dungeon, { god = true, ticks = 60 * TPS, inputs = bot } = {}) {
	const st = createSim(dungeon, STARTER);
	if (god) { st.stats.maxHp = st.p.hp = st.p.low = 1e9; }
	const events = [], prints = [];
	for (let t = 0; t < ticks && st.status === "play"; t++) {
		step(st, inputs(st, t));
		events.push(...st.events);
		prints.push(fingerprint(st));
	}
	return { st, events, prints };
}

test("dsin and dcos match Math.sin and Math.cos to 1e-9 across many turns", () => {
	for (let a = -40; a <= 40; a += 0.0137) {
		assert.ok(Math.abs(dsin(a) - Math.sin(a)) < 1e-9, `sin ${a}`);
		assert.ok(Math.abs(dcos(a) - Math.cos(a)) < 1e-9, `cos ${a}`);
	}
});

test("the same dungeon and the same inputs make the same run, tick for tick", () => {
	const a = play(A, { god: false, ticks: 40 * TPS }), b = play(A, { god: false, ticks: 40 * TPS });
	assert.ok(a.prints.length > 600, `ran ${a.prints.length} ticks`);
	assert.deepEqual(a.prints, b.prints);
	assert.deepEqual(a.events, b.events);
	const c = play(B, { god: false, ticks: 40 * TPS });
	assert.notDeepEqual(a.prints.slice(0, 300), c.prints.slice(0, 300));
});

test("a bot clears a whole dungeon, and every event is one the store accepts", () => {
	for (const d of [A, B]) {
		const { st, events } = play(d, { ticks: 240 * TPS });
		assert.equal(st.status, "complete", `${d.seed}: ended ${st.status} with ${st.enemies.filter((e) => e.hp > 0).length} alive`);
		const killed = new Set(), picked = new Set();
		for (const ev of events) {
			if (ev.type === "kill") { assert.ok(!killed.has(ev.enemy)); assert.ok(ev.enemy in d.enemies); killed.add(ev.enemy); }
			if (ev.type === "pickup") {
				assert.ok(!picked.has(ev.drop) && d.drops[ev.drop], ev.drop);
				assert.ok(killed.has(d.drops[ev.drop].enemy), "a drop is taken only after its enemy died");
				picked.add(ev.drop);
			}
		}
		assert.deepEqual([...killed].sort(), Object.keys(d.enemies).sort());
		assert.deepEqual([...picked].sort(), Object.keys(d.drops).sort());
		assert.equal(events.at(-1).type, "complete");
		assert.equal(events.filter((e) => e.type === "complete").length, 1);
	}
});

test("the portal opens clear of the boss's loot, and only E takes you through it", () => {
	const st = createSim(A, STARTER);
	const boss = st.enemies.find((e) => e.type === "boss");
	boss.active = true; boss.hp = 1; boss.phase = 2;   // past its half-health turn, which is untouchable
	st.p.x = boss.x - 2; st.p.y = boss.y;
	st.bullets.push({ owner: "p", x: boss.x, y: boss.y, vx: 0, vy: 0, dmg: 5, r: 0.1, life: 5, pierce: 0, hit: [] });
	step(st, {});
	assert.ok(st.portal && st.bags.length, "the boss is down, with its loot and an exit");
	const bag = st.bags[0];
	assert.ok(Math.hypot(st.portal.x - bag.x, st.portal.y - bag.y) > 2 * REACH, "E at the bag cannot reach the exit");
	st.p.x = st.portal.x; st.p.y = st.portal.y;
	step(st, {});
	assert.equal(st.status, "play", "standing on the portal is not leaving");
	step(st, { enter: true });
	assert.equal(st.status, "complete");
	assert.deepEqual(st.events, [{ type: "complete" }]);
});

test("nothing ever stands inside a wall, a rock or the water", () => {
	let r = 12345;
	const noise = () => ((r = (Math.imul(r, 1103515245) + 12345) >>> 0) % 3) - 1;
	const st = createSim(A, STARTER);
	st.stats.maxHp = st.p.hp = st.p.low = 1e9;
	let dir = [0, 0];
	for (let t = 0; t < 30 * TPS; t++) {
		if (t % 20 === 0) dir = [noise(), noise()];          // hold each random direction a third of a second
		step(st, { mx: dir[0], my: dir[1], fire: true, ax: 1, ay: 0 });
		for (const b of [st.p, ...st.enemies.filter((e) => e.hp > 0)])
			for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1], [0, 0]])
				assert.ok(!solid(A, b.x + dx * b.r * 0.99, b.y + dy * b.r * 0.99), `tick ${t}: ${b.id || "player"} at ${b.x},${b.y}`);
	}
});

test("health regenerates only to the recovery limit, and a heal raises both", () => {
	const st = createSim(A, STARTER);
	const max = st.stats.maxHp;
	st.p.hp = st.p.low = 20;
	for (let t = 0; t < 120 * TPS; t++) step(st, {});
	assert.equal(recoveryLimit(st), 60);
	assert.equal(st.p.hp, 60, "regen stops at lowest + 40");
	const orb = st.pickups[0];
	st.p.x = orb.x; st.p.y = orb.y;
	step(st, { heal: true });
	assert.equal(st.p.low, 55);
	assert.equal(st.p.hp, 95);
	assert.deepEqual(st.events, [{ type: "heal", local: true }]);
	assert.ok(st.p.hp <= max);
});

test("recall ends the run at once and nothing moves after it", () => {
	const st = createSim(A, STARTER);
	step(st, { mx: 1 });
	step(st, { recall: true });
	assert.equal(st.status, "recalled");
	assert.deepEqual(st.events, [{ type: "recall" }]);
	const before = fingerprint(st);
	step(st, { mx: 1, fire: true });
	assert.equal(fingerprint(st), before);
	assert.deepEqual(st.events, []);
});

test("standing still in front of the boss is lethal", () => {
	const st = createSim(A, STARTER);
	const boss = st.enemies.find((e) => e.type === "boss");
	st.p.x = boss.x - 3; st.p.y = boss.y;
	const events = [];
	for (let t = 0; t < 60 * TPS && st.status === "play"; t++) { step(st, {}); events.push(...st.events); }
	assert.equal(st.status, "dead");
	assert.deepEqual(events.map((e) => e.type), ["death"]);
	assert.equal(st.p.hp, 0);
});

test("a bag cannot be taken from across the room", () => {
	const st = createSim(A, STARTER);
	const [dropId, drop] = Object.entries(A.drops)[0];
	const e = st.enemies.find((x) => x.id === drop.enemy);
	e.active = true; e.hp = 1;
	st.bullets.push({ owner: "p", x: e.x, y: e.y, vx: 0, vy: 0, dmg: 5, r: 0.1, life: 5, pierce: 0, hit: [] });
	st.p.x = A.start.x; st.p.y = A.start.y;
	step(st, { take: dropId });
	assert.ok(st.events.some((v) => v.type === "kill" && v.enemy === e.id));
	assert.ok(!st.events.some((v) => v.type === "pickup"), "picked up from afar");
	st.p.x = st.bags[0].x; st.p.y = st.bags[0].y;
	step(st, { take: dropId });
	assert.deepEqual(st.events.filter((v) => v.type === "pickup"), [{ type: "pickup", drop: dropId }]);
});

test("gear changes the numbers: a longbow hits harder and slower, enchantments scale by quality", () => {
	const short = statsFor([{ base_id: "shortbow", tier: 1 }]), long = statsFor([{ base_id: "longbow", tier: 1 }]);
	assert.ok(long.dmg > short.dmg && long.rate < short.rate && long.range > short.range);
	const lo = statsFor([{ base_id: "band_of_vigor", tier: 1, enchants: [{ id: "max_hp", q: 0 }] }]);
	const hi = statsFor([{ base_id: "band_of_vigor", tier: 1, enchants: [{ id: "max_hp", q: 1 }] }]);
	assert.ok(hi.maxHp > lo.maxHp && lo.maxHp > statsFor([]).maxHp);
});
