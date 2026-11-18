/* Halcyon Rift's simulation (halcyon/sim.js): deterministic, and a run played
 * through it produces only events the server's store would accept.
 * The fixtures are real dungeons from halcyon/dungeon.py, held to the generator
 * by halcyon/tests/test_sim_fixtures.py. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, setGear, wallHit, enchantValue, STAT_SCALE, fingerprint, dsin, dcos, recoveryLimit, statsFor, levelFor, xpProgress, PER_LEVEL, WEAPONS, TPS, REACH } from "../../../halcyon/sim.js";

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

function play(dungeon, { god = true, ticks = 60 * TPS, inputs = bot, hero } = {}) {
	const st = createSim(dungeon, STARTER, hero);
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

// The server's level table (halcyon/content.py LEVEL_XP), as the state route ships it.
const LEVELS = [0, 120, 280, 480, 740, 1080, 1530, 2110, 2860, 3840, 5110, 6760, 8910, 11710, 15340, 20060, 26200, 34180, 44560, 58050];

test("a full clear earns every enemy's XP plus the completion bonus, and levels up on the way", () => {
	for (const d of [A, B]) {
		const { st, events } = play(d, { ticks: 240 * TPS, hero: { level: 1, xp: 0, levels: LEVELS } });
		assert.equal(st.status, "complete");
		const earned = Object.values(d.enemies).reduce((n, e) => n + e.xp, 0) + d.complete_xp;
		assert.equal(st.hero.xp, earned);
		assert.equal(st.hero.level, levelFor(LEVELS, earned));
		assert.equal(st.hero.level, 2, `${d.seed}: a Shallows clear is about one level (${earned} XP)`);
		const ups = events.filter((e) => e.type === "level");
		assert.deepEqual(ups, [{ type: "level", level: 2, local: true }], "a level-up is the page's to show, never sent");
		assert.equal(events.at(-1).type, "complete");
		assert.equal(Math.round(st.stats.maxHp), Math.round(statsFor(STARTER, 2).maxHp));
	}
});

test("a level-up lifts HP, the recovery limit and MP by what it added, at once", () => {
	const st = createSim(A, STARTER, { level: 1, xp: 119, levels: LEVELS });
	st.p.hp = 50; st.p.low = 40; st.p.mp = 10;
	const chaser = st.enemies.find((e) => e.type === "chaser");
	chaser.active = true; chaser.hp = 1;
	st.bullets.push({ owner: "p", x: chaser.x, y: chaser.y, vx: 0, vy: 0, dmg: 5, r: 0.2, life: 5, pierce: 0, hit: [] });
	step(st, {});
	assert.equal(st.hero.level, 2);
	assert.equal(st.p.low, 40 + PER_LEVEL.maxHp);
	assert.ok(Math.abs(st.p.hp - (50 + PER_LEVEL.maxHp)) < 0.1, st.p.hp);
	assert.ok(st.p.mp >= 10 + PER_LEVEL.maxMp);
});

test("levels add a little to the base numbers, and a character keeps its level into the run", () => {
	const one = statsFor(STARTER, 1), five = statsFor(STARTER, 5);
	assert.equal(five.maxHp - one.maxHp, 4 * PER_LEVEL.maxHp);
	assert.equal(five.maxMp - one.maxMp, 4 * PER_LEVEL.maxMp);
	assert.equal(five.att - one.att, 4 * PER_LEVEL.att);
	assert.ok(five.dmg > one.dmg, "Attack points raise the damage per arrow");
	const st = createSim(A, STARTER, { level: 5, xp: 760, levels: LEVELS });
	assert.equal(st.p.hp, five.maxHp);
	assert.deepEqual(xpProgress(LEVELS, 760), { level: 5, into: 20, span: 340 });
	assert.deepEqual(xpProgress(LEVELS, 10 ** 9), { level: 20, into: 0, span: 0 });
});

test("a levelled run is as deterministic as any other", () => {
	const hero = { level: 1, xp: 100, levels: LEVELS };
	assert.deepEqual(play(B, { ticks: 120 * TPS, hero }).prints, play(B, { ticks: 120 * TPS, hero }).prints);
});

/* Fire one weapon at nothing for `ticks` and record every arrow it lets go of. */
function arrows(base, ticks = TPS) {
	const st = createSim(A, [{ base_id: base, tier: 1 }]);
	st.enemies = [];                                       // an empty range
	const out = [];
	for (let t = 0; t < ticks; t++) {
		const before = new Set(st.bullets);
		step(st, { ax: 1, ay: 0, fire: true });
		for (const b of st.bullets) if (!before.has(b) && b.owner === "p") out.push({ t, b: { ...b } });   // as fired
	}
	return out;
}

test("each weapon fires its own pattern, not just its own numbers", () => {
	const short = arrows("shortbow"), long = arrows("longbow"), rep = arrows("repeater");
	// shortbow: pairs of arrows fanned apart, many volleys a second
	const pairs = Object.values(Object.groupBy(short, (a) => a.t));
	assert.ok(pairs.length >= 4 && pairs.every((v) => v.length === 2), `${pairs.length} volleys`);
	assert.ok(Math.abs(pairs[0][0].b.vy - pairs[0][1].b.vy) > 0.5, "the twin arrows diverge");
	// longbow: one arrow, few a second, the farthest, piercing
	assert.ok(long.length <= 2 && long.every((a) => a.b.pierce === WEAPONS.longbow.pierce));
	assert.ok(long[0].b.life * Math.hypot(long[0].b.vx, long[0].b.vy) > short[0].b.life * Math.hypot(short[0].b.vx, short[0].b.vy));
	assert.ok(long[0].b.dmg > 3 * short[0].b.dmg);
	// repeater: bursts of three a few ticks apart, then a pause
	const gaps = rep.slice(1).map((a, i) => a.t - rep[i].t);
	assert.deepEqual(gaps.slice(0, 3), [WEAPONS.repeater.gap, WEAPONS.repeater.gap, Math.round(TPS / WEAPONS.repeater.rate) - 2 * WEAPONS.repeater.gap]);
});

test("the order gear is listed in never changes the numbers", () => {
	const ring = { base_id: "kingfisher_eye", tier: 1, enchants: [{ id: "attack", q: 1 }, { id: "attack_speed", q: 0.5 }] };
	const bow = { base_id: "longbow", tier: 2, enchants: [] };
	assert.deepEqual(statsFor([ring, bow]), statsFor([bow, ring]));
	assert.equal(statsFor([ring, bow]).pierce, WEAPONS.longbow.pierce + 1);
});

test("gear swapped mid-run changes the pattern from that tick on", () => {
	const st = createSim(A, [{ base_id: "shortbow", tier: 1 }]);
	st.enemies = [];
	const fired = [];
	for (let t = 0; t < 2 * TPS; t++) {
		const before = new Set(st.bullets);
		step(st, { ax: 1, ay: 0, fire: true, ...(t === TPS ? { gear: [{ base_id: "longbow", tier: 1 }] } : {}) });
		for (const b of st.bullets) if (!before.has(b) && b.owner === "p") fired.push({ t, pierce: b.pierce, dmg: b.dmg });
	}
	const early = fired.filter((a) => a.t < TPS), late = fired.filter((a) => a.t >= TPS);
	assert.ok(early.length >= 8 && early.every((a) => a.pierce === 0), "the shortbow's twin arrows first");
	assert.ok(late.length >= 1 && late.length <= 2 && late.every((a) => a.pierce === WEAPONS.longbow.pierce), "then the longbow's");
	assert.equal(st.stats.pierce, WEAPONS.longbow.pierce);
});

test("a gear swap never heals: HP, the limit and MP only come down to a smaller maximum", () => {
	const ring = { base_id: "band_of_vigor", tier: 1 };
	const st = createSim(A, [{ base_id: "shortbow", tier: 1 }, ring]);
	const full = st.stats.maxHp;
	st.p.hp = st.p.low = full - 5;
	setGear(st, [{ base_id: "shortbow", tier: 1 }]);
	assert.ok(st.stats.maxHp < full - 5 && st.p.hp === st.stats.maxHp && st.p.low === st.stats.maxHp);
	const was = st.p.hp;
	setGear(st, [{ base_id: "shortbow", tier: 1 }, ring]);
	assert.equal(st.stats.maxHp, full);
	assert.equal(st.p.hp, was, "putting the ring back on gives nothing back");
});

test("a run with gear swaps is as deterministic as any other", () => {
	const swaps = (st, t) => ({ ...bot(st, t), ...(t % 300 === 150 ? { gear: t % 600 === 150 ? [{ base_id: "repeater", tier: 1 }] : STARTER } : {}) });
	assert.deepEqual(play(B, { ticks: 90 * TPS, inputs: swaps }).prints, play(B, { ticks: 90 * TPS, inputs: swaps }).prints);
});

test("every number a player reads is flat: whole points, whole damage, whole enchantments", () => {
	for (let q = 0; q <= 1; q += 0.05)
		for (const id of ["max_hp", "max_mp", "attack", "attack_speed", "defense", "ability_power", "mp_regen", "hp_regen"])
			assert.ok(Number.isInteger(enchantValue(id, q)) && enchantValue(id, q) > 0, `${id} @ ${q}`);
	const ench = [{ id: "attack", q: 1 }, { id: "attack_speed", q: 0.5 }, { id: "defense", q: 0.3 }];
	for (const base of ["shortbow", "longbow", "tidecaller"])
		for (const tier of [1, 2, 3, 4, 5]) {
			const s = statsFor([{ base_id: base, tier, enchants: ench }, STARTER[1], STARTER[2]], 3);
			for (const k of ["maxHp", "maxMp", "att", "dex", "def", "dmg", "weaponDmg", "abilityDmg"])
				assert.ok(Number.isInteger(s[k]), `${base} T${tier}: ${k} = ${s[k]}`);
		}
	// Attack is points, and a point is worth the same share of ANY weapon's damage.
	const bare = statsFor([{ base_id: "longbow", tier: 1 }]);
	const strong = statsFor([{ base_id: "longbow", tier: 1, enchants: [{ id: "attack", q: 1 }] }]);
	assert.equal(strong.att, enchantValue("attack", 1));
	assert.equal(strong.dmg, Math.round(bare.weaponDmg * (1 + strong.att / STAT_SCALE)));
});

test("the Tidecaller fans three arrows, and they glance off a wall once", () => {
	const st = createSim(A, [{ base_id: "tidecaller", tier: 1 }]);
	st.enemies = [];
	step(st, { ax: 1, ay: 0, fire: true });
	const shots = st.bullets.filter((b) => b.owner === "p");
	assert.equal(shots.length, 3);
	assert.ok(shots.every((b) => b.bounce === 1));
	// A wall to the east: the arrow comes back west, and a second wall breaks it.
	const wall = (x) => x >= 5;
	const b = { x: 5.05, y: 2, vx: 10, vy: 0, bounce: 1 };
	assert.equal(wallHit(b, (x) => wall(x)), false);
	assert.ok(b.vx < 0 && b.vy === 0 && b.bounce === 0 && b.x < 5);
	b.x = 5.1;
	assert.equal(wallHit(b, (x) => wall(x)), true);
});
