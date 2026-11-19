/* Halcyon Rift's simulation (halcyon/sim.js): deterministic, and a run played
 * through it produces only events the server's store would accept.
 * The fixtures are real dungeons from halcyon/dungeon.py, held to the generator
 * by halcyon/tests/test_sim_fixtures.py. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, setGear, wallHit, enchantValue, STAT_SCALE, fingerprint, dsin, dcos, recoveryLimit, statsFor, levelFor, xpProgress, PER_LEVEL, WEAPONS, TPS, REACH, SHIELD_DURATION, ABILITY_COST, MORTAR, inSight, SLOW_FACTOR, SLOW_DURATION, SLOW_RADIUS,
	SLOW_PULSE, STARFALL_DELAY, COUNTER_WINDOW, COUNTER_GUARD, ENEMY, POTION_HEAL, POTION_COOLDOWN, RECOVERY_MARGIN } from "../../../halcyon/sim.js";

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
		if (god) st.p.hp = st.p.low = 1e9;           // a level-up mid-fight resets the god HP; put it back
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
	assert.ok(a.prints.length > 250, `ran ${a.prints.length} ticks`);
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
	assert.equal(st.pickups.length, 0, "no heal lies in a room: they drop from enemies");
	const orb = { id: "h-test", kind: "heal", x: st.p.x, y: st.p.y };
	st.pickups.push(orb);
	step(st, {});                                       // walking over it is enough
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
	assert.deepEqual(events.filter((e) => !e.local).map((e) => e.type), ["death"]);
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

test("an item put down lies at the player's feet and only comes back from within reach", () => {
	const st = createSim(A, STARTER);
	step(st, { drop: "item-1" });
	assert.equal(st.floor.length, 1);
	const f = st.floor[0];
	st.p.x = f.x + REACH + 2;
	step(st, { lift: "item-1" });
	assert.equal(st.floor.length, 1, "taken from afar");
	st.p.x = f.x; st.p.y = f.y;
	step(st, { lift: "item-2" });
	assert.equal(st.floor.length, 1, "a key that is not there took something");
	step(st, { lift: "item-1" });
	assert.equal(st.floor.length, 0);
	assert.deepEqual(st.events, [{ type: "lift", key: "item-1", local: true }]);
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
		const boss = events.findIndex((e) => e.type === "kill" && e.enemy === d.boss);
		assert.deepEqual(events[events.findIndex((e) => e.type === "cleared")], { type: "cleared", xp: d.complete_xp, local: true });
		assert.ok(events.findIndex((e) => e.type === "cleared") > boss && boss >= 0, "the clear comes with the boss, not the portal");
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

test("every number a player reads is flat, with one decimal place for regeneration", () => {
	for (let q = 0; q <= 1; q += 0.05)
		for (const id of ["max_hp", "max_mp", "attack", "attack_speed", "defense", "ability_power", "mp_regen", "hp_regen"])
			assert.ok((id.endsWith("regen") ? Math.round(enchantValue(id, q) * 10) === enchantValue(id, q) * 10 : Number.isInteger(enchantValue(id, q)))
				&& enchantValue(id, q) > 0, `${id} @ ${q}`);
	const ench = [{ id: "attack", q: 1 }, { id: "attack_speed", q: 0.5 }, { id: "defense", q: 0.3 }];
	for (const base of ["shortbow", "longbow", "tidecaller"])
		for (const tier of [1, 2, 3, 4, 5]) {
			const s = statsFor([{ base_id: base, tier, enchants: ench }, STARTER[1], STARTER[2]], 3);
			for (const k of ["maxHp", "maxMp", "att", "dex", "def", "dmg", "weaponDmg"])
				assert.ok(Number.isInteger(s[k]), `${base} T${tier}: ${k} = ${s[k]}`);
		}
	assert.equal(statsFor([]).mpRegen, 2.5, "base MP regeneration is deliberately lower");
	// Attack is points, and a point is worth the same share of ANY weapon's damage.
	const bare = statsFor([{ base_id: "longbow", tier: 1 }]);
	const strong = statsFor([{ base_id: "longbow", tier: 1, enchants: [{ id: "attack", q: 1 }] }]);
	assert.equal(strong.att, enchantValue("attack", 1));
	assert.equal(strong.dmg, Math.round(bare.weaponDmg * (1 + strong.att / STAT_SCALE)));
});

const PALADIN = [{ base_id: "mace", tier: 1 }, { base_id: "plate_armor", tier: 1 }, { base_id: "stillness_orb", tier: 1 }];
const DIVINER = [{ base_id: "starstaff", tier: 1 }, { base_id: "seer_robes", tier: 1 }, { base_id: "star_tome", tier: 1 }];
const NINJA = [{ base_id: "shuriken", tier: 1 }, { base_id: "shadow_garb", tier: 1 }, { base_id: "mirror_charm", tier: 1 }];
const withAp = (kit, q) => kit.map((it, i) => (i === 2 && q ? { ...it, enchants: [{ id: "ability_power", q }, { id: "ability_power", q }] } : it));

test("one standard ability per class: field, stars, counter (and the volley)", () => {
	assert.equal(statsFor(PALADIN, 1, "paladin").range, 3);
	assert.equal(statsFor(PALADIN, 1, "paladin").abilityKind, "slow");
	assert.equal(statsFor(DIVINER, 1, "diviner").range, 8);
	assert.equal(statsFor(DIVINER, 1, "diviner").abilityKind, "starfall");
	assert.equal(statsFor(NINJA, 1, "ninja").abilityKind, "counter");
	assert.equal(WEAPONS.shuriken.look, "star");
});

test("an ability has no cooldown (but the counter): MP is its only limit", () => {
	const st = createSim(A, PALADIN, { class_id: "paladin" });
	st.enemies = [];
	const cost = st.stats.abilityCost;
	assert.equal(cost, 35, "a tier 1 ability costs 35 MP");
	st.p.mp = 2 * cost + 1;
	step(st, { ability: true });
	const first = st.slowUntil;
	step(st, { ability: true });
	assert.ok(st.slowUntil > first, "a second cast right away refreshes the field");
	assert.ok(st.p.mp < cost, "and spends its MP");
	step(st, { ability: true });
	assert.equal(st.slowUntil, first + 1, "with too little MP nothing is cast");
});

test("the Paladin's field burns enemies inside it, and only inside it", () => {
	const st = createSim(A, PALADIN, { class_id: "paladin" });
	const [inside, outside] = st.enemies.slice(0, 2);
	assert.ok(inside && outside);
	st.enemies = [inside, outside];
	for (const e of st.enemies) Object.assign(e, { type: "radial", active: true, cd: 1e9, scd: 1e9 });
	Object.assign(inside, { x: st.p.x + 1, y: st.p.y, hp: 500, maxHp: 500 });
	Object.assign(outside, { x: st.p.x + st.stats.slowRadius + 3, y: st.p.y, hp: 500, maxHp: 500 });
	step(st, { ability: true });
	for (let i = 0; i < SLOW_PULSE * 3; i++) step(st, {});
	assert.ok(st.stats.abilityDmg > 0);
	assert.ok(inside.hp <= 500 - 3 * st.stats.abilityDmg, `inside took ${500 - inside.hp}`);
	assert.equal(outside.hp, 500);
	assert.ok(500 - inside.hp < 60, "slight: under a second of weapon fire");
});
test("the Paladin's field slows enemy shots inside it; AP widens it, never lengthens it", () => {
	const st = createSim(A, PALADIN, { class_id: "paladin" });
	st.enemies = [];
	step(st, { ability: true });
	const b = { owner: "e", x: st.p.x - 1, y: st.p.y, vx: 6, vy: 0, dmg: 1, r: 0.1, life: 5, pierce: 0, hit: [] };
	st.bullets.push(b);
	step(st, {});
	assert.equal(b.x, st.p.x - 1 + 6 * (1 / TPS) * SLOW_FACTOR);
	const field = (q) => { const s = createSim(A, withAp(PALADIN, q), { class_id: "paladin" }); step(s, { ability: true }); return [s.slowR, s.slowUntil]; };
	const [r0, t0] = field(0), [r1, t1] = field(1);
	assert.ok(Math.abs(r0 - SLOW_RADIUS * 1.1) < 1e-9, `a tier 1 field is 2.2 tiles: ${r0}`);
	assert.ok(r1 > r0, "AP widens the field");
	assert.equal(t1, t0, "AP does not lengthen it");
});

test("the Diviner's star lands where you aim after a beat and hits everything near it", () => {
	const st = createSim(A, DIVINER, { class_id: "diviner" });
	const [e1, e2] = st.enemies.filter((e) => e.type !== "boss");
	st.enemies = [e1, e2];
	st.p.x = 10; st.p.y = 10;
	e1.x = 14; e1.y = 10; e2.x = 14.6; e2.y = 10.4;
	e1.active = e2.active = true;                              // their room is sealed and awake
	const h1 = e1.hp, h2 = e2.hp;
	step(st, { ability: true, ax: 4, ay: 0 });
	assert.equal(st.starfalls.length, 1);
	for (let i = 0; i < STARFALL_DELAY - 2; i++) step(st, {});
	assert.equal(e1.hp, h1, "nothing yet: the star is still falling");
	for (let i = 0; i < 3; i++) step(st, {});
	assert.equal(st.starfalls.length, 0);
	assert.ok(e1.hp < h1 && e2.hp < h2, "both enemies under it are hit");
	const far = createSim(A, DIVINER, { class_id: "diviner" });
	far.enemies = [];
	step(far, { ability: true, ax: 40, ay: 0 });
	assert.ok(Math.abs(far.starfalls[0].x - far.p.x - 8) < 1e-9, "no farther than its range");
	assert.ok(statsFor(withAp(DIVINER, 1), 1, "diviner").abilityDmg > statsFor(DIVINER, 1, "diviner").abilityDmg, "AP raises its damage");
});

test("the Ninja's counter: a hit in the window is ignored, a short guard, the next shot doubled once", () => {
	const st = createSim(A, NINJA, { class_id: "ninja" });
	st.enemies = [];
	const hp = st.p.hp;
	const hit = () => st.bullets.push({ owner: "e", x: st.p.x, y: st.p.y, vx: 0, vy: 0, dmg: 30, r: 0.1, life: 5, pierce: 0, hit: [] });
	step(st, { ability: true });
	for (let i = 0; i < COUNTER_WINDOW - 5; i++) step(st, {});
	hit(); step(st, {});
	assert.equal(st.p.hp, hp, "the countered hit does nothing");
	assert.equal(st.stats.counterMult, 2.4, "a tier 1 counter is x2.4");
	assert.ok(st.p.empower === st.stats.counterMult);
	hit(); step(st, {});
	assert.equal(st.p.hp, hp, "the guard ignores what follows at once");
	for (let i = 0; i < COUNTER_GUARD; i++) step(st, {});
	hit(); step(st, {});
	assert.ok(st.p.hp < hp, "the guard is over");
	step(st, { fire: true, ax: 1, ay: 0 });
	const shot = st.bullets.find((b) => b.owner === "p");
	assert.equal(shot.dmg, st.stats.dmg * st.stats.counterMult, "the next shot is multiplied");
	for (let i = 0; i < TPS; i++) step(st, {});
	step(st, { fire: true, ax: 1, ay: 0 });
	assert.ok(st.bullets.filter((b) => b.owner === "p").every((b) => b.dmg <= st.stats.dmg * st.stats.counterMult), "only once");
	assert.ok(st.bullets.some((b) => b.owner === "p" && b.dmg === st.stats.dmg));
});

test("countering twice before attacking does not stack; AP raises the damage but not the guard", () => {
	const st = createSim(A, withAp(NINJA, 1), { class_id: "ninja" });
	st.enemies = [];
	const mult = st.stats.counterMult;
	assert.ok(mult > 2, "AP raises the counter's damage");
	const hit = () => st.bullets.push({ owner: "e", x: st.p.x, y: st.p.y, vx: 0, vy: 0, dmg: 30, r: 0.1, life: 5, pierce: 0, hit: [] });
	for (let n = 0; n < 2; n++) {
		st.p.mp = 100;
		step(st, { ability: true });
		hit(); step(st, {});
		assert.ok(st.p.guardUntil - st.tick <= COUNTER_GUARD, "the guard is the same at any AP");
	}
	assert.equal(st.p.empower, mult, "still one empowered shot, not two");
});

test("a counter that catches nothing still costs its MP", () => {
	const st = createSim(A, NINJA, { class_id: "ninja" });
	st.enemies = [];
	const mp = st.p.mp;
	step(st, { ability: true });
	for (let i = 0; i < COUNTER_WINDOW + 2; i++) step(st, {});
	assert.equal(st.p.empower, 0);
	assert.ok(st.p.mp < mp + (COUNTER_WINDOW + 3) * st.stats.mpRegen / TPS);
});

test("the retired shield still works for the class that gets it later", () => {
	const st = createSim(A, [{ base_id: "mace", tier: 1 }, { base_id: "grounding_aegis", tier: 1 }], { class_id: "paladin" });
	st.enemies = [];
	step(st, { ax: 1, ay: 0, ability: true });
	assert.ok(st.shield);
	st.bullets.push({ owner: "e", x: st.shield.x, y: st.shield.y, vx: 0, vy: 0, dmg: 99, r: 0.1, life: 5, pierce: 0, hit: [] });
	const hp = st.p.hp;
	step(st, { ax: 1, ay: 0, fire: true });
	assert.equal(st.shield, null);
	assert.equal(st.p.hp, hp);
	step(st, { ax: 1, ay: 0, ability: true });
	assert.ok(st.shield);
	for (let i = 0; i < SHIELD_DURATION * 2; i++) step(st, {});
	assert.equal(st.shield, null);
});

test("damage taken creates a visible one-decimal damage event, and the rift timer freezes at boss death", () => {
	const st = createSim(A, STARTER);
	st.enemies = [];
	st.bullets.push({ owner: "e", x: st.p.x, y: st.p.y, vx: 0, vy: 0, dmg: 17.3, r: 0.1, life: 5, pierce: 0, hit: [] });
	step(st, {});
	const taken = Math.round(Math.max(17.3 * 0.4, 17.3 - st.stats.def) * 10) / 10;
	assert.equal(st.events.find((e) => e.type === "damage").amount, taken);
	assert.equal(st.damageNumbers.at(-1).amount, taken);
	assert.equal(Math.round(taken * 10), taken * 10);
	const boss = { id: "boss", type: "boss", x: st.p.x + 2, y: st.p.y, xp: 0, r: 1, hp: 1, maxHp: 1,
		active: true, cd: 999, tele: 0, flash: 0, side: 1, phase: 1, mode: 0, modeT: 1, ang: 0, aimX: 0, aimY: 0 };
	st.enemies = [boss];
	st.bullets = [{ owner: "p", x: boss.x, y: boss.y, vx: 0, vy: 0, dmg: 10, r: 0.1, life: 5, pierce: 0, hit: [] }];
	step(st, {});
	assert.equal(st.bossTimeTicks, st.elapsedTicks);
	const stopped = st.elapsedTicks;
	for (let i = 0; i < 30; i++) step(st, {});
	assert.equal(st.elapsedTicks, stopped);
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

/* A player shot placed against an enemy, so a test can hit it without aiming. */
function poke(st, e, dmg = 5) {
	st.bullets.push({ owner: "p", x: e.x - e.r - 0.1, y: e.y, vx: 6, vy: 0, dmg, r: 0.14, life: 6, pierce: 0, bounce: 0, hit: [] });
	step(st, {});
}
const inRoom = (st, i) => st.enemies.filter((e) => e.room === i && e.hp > 0);

test("a room seals both ways when you are all the way in, wakes at once, and opens when it is cleared", () => {
	const st = createSim(A, STARTER);
	const room = st.rooms.findIndex((r) => r.kind === "combat"), r = st.rooms[room], y = st.doorY + 0.5;
	for (let t = 0; t < 30; t++) step(st, {});
	assert.ok(st.enemies.every((e) => !e.active), "nobody is awake before a room is entered");
	// Outside, at its door: a shot into the room stops at the veil, and the enemies cannot be hurt.
	st.p.x = r.x0 - 2.5; st.p.y = y;
	step(st, { fire: true, ax: 1, ay: 0 });
	for (let t = 0; t < 20; t++) step(st, {});
	assert.ok(!st.bullets.some((b) => b.owner === "p" && b.x > r.x0), "nothing gets through the veil");
	const e = inRoom(st, room)[0], hp = e.hp;
	poke(st, e);
	assert.equal(e.hp, hp, "a sleeping enemy cannot be hurt");
	assert.equal(st.sealed, -1);
	// In the doorway is not in: still open. All the way in: sealed, everyone awake.
	st.p.x = r.x0 - 0.2; step(st, {});
	assert.equal(st.sealed, -1, "standing in the doorway does not seal it");
	st.p.x = r.x0 + 1; step(st, {});
	assert.equal(st.sealed, room);
	assert.ok(inRoom(st, room).every((x) => x.active) && st.enemies.filter((x) => x.room !== room).every((x) => !x.active));
	assert.ok(st.events.some((ev) => ev.type === "seal" && ev.local));
	// Locked behind: walking back out stops at the wall.
	for (let t = 0; t < 30; t++) { st.p.hp = 1e9; step(st, { mx: -1 }); }
	assert.ok(st.p.x - st.p.r >= r.x0 - 1e-9, `held inside at ${st.p.x}`);
	// Clear it: the doors open.
	for (const x of inRoom(st, room)) { x.hp = 1; x.x = st.p.x + 1.5; x.y = st.p.y; poke(st, x); }
	assert.equal(inRoom(st, room).length, 0);
	assert.equal(st.sealed, -1, "cleared: open");
	st.p.x = r.x0 + 0.5;
	for (let t = 0; t < 30; t++) step(st, { mx: -1 });
	assert.ok(st.p.x < r.x0 - 1, "and the way back is open");
});

test("the boss's room seals like any other", () => {
	const st = createSim(A, STARTER);
	const i = st.rooms.findIndex((r) => r.kind === "boss"), r = st.rooms[i];
	st.p.x = r.x0 + 1; st.p.y = st.doorY + 0.5;
	step(st, {});
	assert.equal(st.sealed, i);
	assert.ok(st.enemies.find((e) => e.type === "boss").active);
});

test("Warded: each enemy ignores its first few hits, the boss its first ten", () => {
	const st = createSim({ ...A, scale: { ...A.scale, ward: 3, ward_boss: 10 } }, STARTER);
	const e = st.enemies.find((x) => x.type !== "boss"), boss = st.enemies.find((x) => x.type === "boss");
	assert.equal(e.ward, 3); assert.equal(boss.ward, 10);
	st.enemies = [e]; e.active = true; e.x = st.p.x + 2; e.y = st.p.y;
	const hp = e.hp;
	for (let k = 0; k < 3; k++) poke(st, e);
	assert.equal(e.hp, hp, "three hits shrugged off");
	poke(st, e);
	assert.ok(e.hp < hp, "the fourth lands");
});

test("Volatile rings shots where an enemy falls; Bulky makes enemy shots bigger; Frenzied attacks sooner", () => {
	const st = createSim({ ...A, scale: { ...A.scale, volatile: 1 } }, STARTER);
	const e = st.enemies.find((x) => x.type === "chaser");
	st.enemies = [e]; e.active = true; e.hp = 1; e.x = st.p.x + 2; e.y = st.p.y;
	poke(st, e);
	assert.equal(e.hp, 0);
	assert.equal(st.bullets.filter((b) => b.owner === "e").length, 8, "a ring of eight");
	const fire = (scale) => {
		const s = createSim({ ...A, scale: { ...A.scale, ...scale } }, STARTER);
		const sh = s.enemies.find((x) => x.type === "shooter");
		s.enemies = [sh]; sh.active = true; sh.cd = 0; sh.x = s.p.x + 5; sh.y = s.p.y;
		let shot = null;
		for (let t = 0; t < 60 && !shot; t++) { s.p.x = sh.x - 5; s.p.y = sh.y; step(s, {}); shot = s.bullets.find((b) => b.owner === "e"); }
		return { r: shot.r, cd: sh.cd };
	};
	const plain = fire({}), bulky = fire({ shot: 1.5 }), frenzied = fire({ cadence: 1 / 1.4 });
	assert.ok(Math.abs(bulky.r - plain.r * 1.5) < 1e-9, "50% larger");
	assert.ok(frenzied.cd < plain.cd && frenzied.cd === Math.round(84 / 1.4), `cooldown ${frenzied.cd}`);
});

test("the boss opens home and, while there are levels left, a portal deeper that only asks", () => {
	const deep = (d) => {
		const st = createSim(d, STARTER);
		const boss = st.enemies.find((e) => e.type === "boss");
		st.enemies = [boss]; boss.active = true; boss.phase = 2; boss.hp = 1; boss.x = st.p.x + 2; boss.y = st.p.y;
		poke(st, boss);
		return st;
	};
	const st = deep(A);
	assert.ok(A.offers.length === 3 && st.portal && st.deeper, "two portals");
	assert.ok(Math.hypot(st.portal.x - st.deeper.x, st.portal.y - st.deeper.y) >= 3, "apart");
	st.p.x = st.deeper.x; st.p.y = st.deeper.y; st.bags = [];
	step(st, { enter: true });
	assert.equal(st.status, "play", "the deeper portal does not end the run");
	assert.ok(st.events.some((ev) => ev.type === "deeper" && ev.local));
	assert.equal(deep({ ...A, level: 5, offers: [] }).deeper, null, "the last level has no way deeper");
});

test("a heal drops where the enemy that carries it dies", () => {
	const carrier = { id: "e1" };
	const st = createSim({ ...A, pickups: [{ id: "h-kill", kind: "heal", enemy: carrier.id }] }, STARTER);
	assert.equal(st.pickups.length, 0, "a carried heal is not on the floor before the kill");
	const eid = carrier.id, e = st.enemies.find((x) => x.id === eid);
	e.hp = 1;
	st.p.x = e.x - 2; st.p.y = e.y;
	for (let t = 0; t < 3 * TPS && e.hp > 0; t++) step(st, { fire: true, ax: 1, ay: 0 });
	assert.ok(e.hp <= 0, "the carrier died");
	const orb = st.pickups.find((h) => h.id === st.healsBy[eid]);
	assert.ok(orb && Math.abs(orb.x - e.x) < 0.01, "its heal lies where it fell");
});

test("ability power raises the volley's damage and leaves the bow alone", () => {
	const ap = (q) => [{ base_id: "longbow", tier: 1 }, { base_id: "volley_quiver", tier: 1,
		enchants: q ? [{ id: "ability_power", q }] : [] }];
	const lo = statsFor(ap(0), 1), hi = statsFor(ap(1), 1);
	assert.ok(hi.ap > lo.ap && hi.abilityDmg > lo.abilityDmg, "AP raises volley damage");
	assert.equal(hi.dmg, lo.dmg, "and leaves the bow alone");
});

test("rift modifiers scale enemy health", () => {
	const plain = createSim(A, STARTER);
	const hard = createSim({ ...A, scale: { hp: 1.5 } }, STARTER);
	assert.equal(hard.enemies[0].hp, plain.enemies[0].hp * 1.5);
});

test("a chaser up close telegraphs, then spits one short shot that dies within its range", () => {
	const st = createSim(A, [{ base_id: "shortbow", tier: 1 }]);
	const e = st.enemies.find((x) => x.type === "chaser");
	st.enemies = [e];
	e.x = st.p.x + 2.5; e.y = st.p.y; e.active = true; e.cd = 0;          // the open entrance room
	let shot = null, teleSeen = false;
	for (let i = 0; i < 40 && !shot; i++) {
		step(st, {});
		teleSeen ||= e.tele > 0;
		shot = st.bullets.find((b) => b.owner === "e") || null;
	}
	assert.ok(teleSeen && shot, "a telegraph, then a shot");
	const reach = Math.hypot(shot.vx, shot.vy) * shot.life / TPS;
	assert.ok(reach <= ENEMY.chaser.shot.range + 0.5, `reaches ${reach} tiles`);
	const far = createSim(A, [{ base_id: "shortbow", tier: 1 }]);
	const f = far.enemies.find((x) => x.type === "chaser");
	far.enemies = [f];
	f.x = far.p.x + 8; f.y = far.p.y; f.active = true;
	step(far, {});
	assert.equal(f.tele, 0, "no shot from afar");
});

test("the Ninja throws slower, harder: shuriken and kunai keep about the same damage a second", () => {
	assert.ok(WEAPONS.shuriken.rate <= 2.5 && WEAPONS.shuriken.dmg >= 18);
	assert.ok(WEAPONS.kunai.rate <= 1.3 && WEAPONS.kunai.dmg >= 40);
});

test("the last hit that landed is kept with what dealt it, for the death screen", () => {
	const shot = createSim(A, STARTER);
	const sh = shot.enemies.find((x) => x.type === "shooter");
	shot.enemies = [sh]; sh.active = true; sh.cd = 0; sh.x = shot.p.x + 4; sh.y = shot.p.y;
	for (let t = 0; t < 120 && !shot.lastHit; t++) step(shot, {});
	assert.equal(shot.lastHit?.src, "shooter:bolt");
	assert.ok(shot.lastHit.dmg > 0 && shot.lastHit.tick > 0);
	// NO CONTACT DAMAGE (owner's call, 2026-11-18): a chaser pressed against the
	// player and never shooting does nothing to them.
	const touch = createSim(A, STARTER);
	const ch = touch.enemies.find((x) => x.type === "chaser");
	touch.enemies = [ch]; ch.active = true; ch.cd = 0; ch.scd = 1e9; ch.x = touch.p.x + 0.5; ch.y = touch.p.y;
	const before = touch.p.hp;
	for (let t = 0; t < 120; t++) { ch.scd = 1e9; ch.tele = 0; step(touch, {}); }
	assert.ok(!touch.lastHit, "touching hurts nothing");
	assert.equal(touch.p.hp, before);
	const ring = createSim({ ...A, scale: { ...A.scale, volatile: 1 } }, STARTER);
	const r = ring.enemies.find((x) => x.type === "radial");
	ring.enemies = [r]; r.active = true; r.hp = 1; r.x = ring.p.x + 1.2; r.y = ring.p.y;
	ring.bullets.push({ owner: "p", x: r.x - r.r - 0.1, y: r.y, vx: 6, vy: 0, dmg: 5, r: 0.14, life: 6, pierce: 0, bounce: 0, hit: [] });
	for (let t = 0; t < 40 && !ring.lastHit; t++) step(ring, {});
	assert.equal(ring.lastHit?.src, "radial:burst", "a Volatile ring names the enemy that burst");
});

test("the healing potion heals only up to the recovery limit, never raising it, then waits out its cooldown", () => {
	const st = createSim(A, STARTER);
	step(st, { potion: true });
	assert.equal(st.p.potionCd, 0, "nothing to heal: not spent");
	st.p.hp = 20; st.p.low = 20;
	step(st, { potion: true });
	assert.equal(st.p.low, 20, "the limit is not raised");
	assert.ok(Math.abs(st.p.hp - Math.min(20 + RECOVERY_MARGIN, 20 + POTION_HEAL)) < 0.1, `hp ${st.p.hp}`);
	assert.ok(st.p.hp <= recoveryLimit(st));
	assert.equal(st.p.potionCd, POTION_COOLDOWN);
	assert.ok(st.events.some((e) => e.type === "potion" && e.local));
	const hp = st.p.hp;
	st.p.hp = 10;
	step(st, { potion: true });
	assert.ok(st.p.hp < hp, "on cooldown: no second heal");
	for (let i = 0; i < POTION_COOLDOWN; i++) step(st, {});
	assert.equal(st.p.potionCd, 0);
	step(st, { potion: true });
	assert.equal(st.p.potionCd, POTION_COOLDOWN, "ready again");
	assert.ok(RECOVERY_MARGIN > 0);
});

test("a hit on an enemy floats what it did over that enemy (a ward's hit floats nothing)", () => {
	const st = createSim({ ...A, scale: { ward: 1 } }, STARTER);
	const e = st.enemies.find((x) => x.type === "chaser");
	e.active = true;
	st.bullets.push({ owner: "p", x: e.x, y: e.y, vx: 0, vy: 0, dmg: 7, r: 0.14, life: 5, pierce: 0, hit: [] });
	step(st, {});
	assert.equal((st.damageNumbers || []).filter((f) => f.foe).length, 0, "the ward took it");
	st.bullets.push({ owner: "p", x: e.x, y: e.y, vx: 0, vy: 0, dmg: 7, r: 0.14, life: 5, pierce: 0, hit: [] });
	step(st, {});
	const f = st.damageNumbers.filter((n) => n.foe);
	assert.equal(f.length, 1);
	assert.equal(f[0].amount, 7);
});

/* THE MORTAR (2026-11-19): the boss shells a player who stays out of its sight. */
function bossFight() {
	const st = createSim(A, STARTER);
	const boss = st.enemies.find((e) => e.type === "boss");
	const i = st.rooms.findIndex((r) => r.kind === "boss");
	st.sealed = i;
	boss.active = true; boss.cd = 0;
	st.p.hp = 100000; st.stats.def = 0;
	return { st, boss };
}
function hiddenSpot(st, boss) {
	for (let y = 0.5; y < st.h; y += 0.5) for (let x = 0.5; x < st.w; x += 0.5) {
		if (st.tiles[Math.floor(y)][Math.floor(x)] !== "." || Math.hypot(x - boss.x, y - boss.y) > 8) continue;
		const ok = [[-0.4, 0], [0.4, 0], [0, -0.4], [0, 0.4]].every(([dx, dy]) => st.tiles[Math.floor(y + dy)][Math.floor(x + dx)] === ".");
		if (ok && !inSight(st, boss, { x, y })) return { x, y };
	}
	return null;
}

test("in the boss's sight, no mortar is lobbed", () => {
	const { st, boss } = bossFight();
	st.p.x = boss.x - 3; st.p.y = boss.y;
	assert.ok(inSight(st, boss, st.p));
	let most = 0;
	for (let t = 0; t < MORTAR.after + 3 * MORTAR.every; t++) { step(st, {}); most = Math.max(most, st.mortars.length); }
	assert.equal(most, 0);
	assert.equal(st.fires.length, 0);
});

test("hiding behind cover draws a mortar after a grace, and it leaves burning ground", () => {
	const { st, boss } = bossFight();
	const spot = hiddenSpot(st, boss);
	assert.ok(spot, "the boss room has cover to hide behind");
	Object.assign(st.p, spot);
	for (let t = 0; t < MORTAR.after - 2; t++) step(st, {});
	assert.equal(st.mortars.length, 0, "a moment behind cover is free");
	for (let t = 0; t < 4; t++) step(st, {});
	assert.equal(st.mortars.length, 1, "staying is not");
	const [m] = st.mortars;
	assert.ok(Math.hypot(m.x - spot.x, m.y - spot.y) < 1e-9, "aimed where the player stood");
	const hp = st.p.hp;
	while (st.mortars.some((x) => x === m)) step(st, {});
	assert.ok(hp - st.p.hp >= MORTAR.dmg - 1e-9, `the shell landed for ${hp - st.p.hp}`);
	assert.equal(st.fires.length, 1);
	assert.equal(st.lastHit.src, "boss:mortar");
	const hp2 = st.p.hp;
	for (let t = 0; t < MORTAR.burnEvery * 3; t++) step(st, {});
	assert.ok(hp2 - st.p.hp >= MORTAR.burnDmg * 2, "the ground burns");
	assert.ok(st.fires.length >= 1);
	// stepping out of the fire, in sight again: the burning stops and no more shells come
	st.p.x = boss.x - 3; st.p.y = boss.y;
	step(st, {});
	const before = st.mortars.length;
	for (let t = 0; t < MORTAR.burn + MORTAR.delay + 2; t++) step(st, {});
	assert.ok(st.mortars.length <= before);
	assert.equal(st.fires.length, 0, "the fires burn out");
});

test("the boss's fall puts out its shells and fires", () => {
	const { st, boss } = bossFight();
	Object.assign(st.p, hiddenSpot(st, boss));
	for (let t = 0; t < MORTAR.after + MORTAR.delay + 4; t++) step(st, {});
	assert.ok(st.fires.length + st.mortars.length > 0);
	boss.hp = 1; boss.phase = 2;
	st.bullets.push({ owner: "p", x: boss.x, y: boss.y, vx: 0, vy: 0, dmg: 5, r: 0.1, life: 5, pierce: 0, hit: [] });
	step(st, {});
	assert.equal(boss.hp <= 0, true);
	assert.equal(st.mortars.length + st.fires.length, 0);
});

test("a heal orb is taken by walking over it, and left alone at full health", () => {
	const st = createSim(A, STARTER);
	st.enemies = [];
	const orb = { id: "h-walk", kind: "heal", x: st.p.x + 2, y: st.p.y };
	st.pickups.push(orb);
	let crossed = false;
	for (let t = 0; t < 2 * TPS; t++) { step(st, { mx: 1 }); crossed ||= Math.abs(st.p.x - orb.x) < 0.1; }
	assert.ok(crossed, "the walk went over it");
	assert.equal(st.pickups.length, 1, "at full health, walking over it leaves it");
	st.p.hp = st.p.low = 30;
	st.p.x = orb.x; st.p.y = orb.y;
	step(st, {});
	assert.equal(st.pickups.length, 0, "hurt, standing on it takes it");
	assert.ok(st.p.hp > 30);
});

test("tier 0 starter gear is weaker than tier 1 and never takes away max HP", () => {
	const t0 = statsFor([{ base_id: "longbow", tier: 0 }, { base_id: "leather_vest", tier: 0 }]);
	const t1 = statsFor([{ base_id: "longbow", tier: 1 }, { base_id: "leather_vest", tier: 1 }]);
	assert.ok(t0.dmg < t1.dmg && t0.def < t1.def);
	assert.equal(t0.maxHp, t1.maxHp);
});

test("the Mirror Charm's tier raises its counter", () => {
	const m = (tier) => statsFor([{ base_id: "mirror_charm", tier }], 1, "ninja").counterMult;
	assert.ok(m(1) < m(2) && m(2) < m(5), `${m(1)} ${m(2)} ${m(5)}`);
});

test("every standard item is stronger at a higher tier, abilities included", () => {
	const at = (base_id, tier) => statsFor([{ base_id, tier }], 1);
	const power = {
		weapon: (s) => s.dmg,
		armor: (s) => s.def + s.maxHp + s.maxMp + s.dex,
		ring: (s) => s.maxHp + s.maxMp,
		volley_quiver: (s) => s.abilityDmg, star_tome: (s) => s.abilityDmg,
		stillness_orb: (s) => s.abilityDmg + s.slowRadius, mirror_charm: (s) => s.counterMult,
		grounding_aegis: (s) => s.shieldTime,
	};
	const kinds = { leather_vest: "armor", plate_armor: "armor", seer_robes: "armor", shadow_garb: "armor",
		band_of_vigor: "ring", band_of_focus: "ring" };
	const ids = [...Object.keys(WEAPONS).filter((w) => w !== "none" && !["repeater", "tidecaller"].includes(w)),
		...Object.keys(kinds), "volley_quiver", "star_tome", "stillness_orb", "mirror_charm", "grounding_aegis"];
	for (const id of ids) {
		const f = power[id] || power[kinds[id]] || power.weapon;
		const p = Array.from({ length: 11 }, (_, t) => f(at(id, t)));     // T0 to T10
		for (let t = 1; t < p.length; t++) assert.ok(p[t] > p[t - 1], `${id}: T${t} (${p[t]}) is not above T${t - 1} (${p[t - 1]})`);
	}
});

test("the ability table: 30 MP and 5 more a tier, effects that are never worse per MP", () => {
	const at = (base_id, tier) => statsFor([{ base_id, tier }], 1);
	const per = {
		volley_quiver: (s) => s.abilityDmg * s.arrows, star_tome: (s) => s.abilityDmg,
		stillness_orb: (s) => s.abilityDmg * s.slowRadius ** 2, mirror_charm: (s) => s.counterMult,
	};
	const want = { volley_quiver: [55, 155], star_tome: [45, 145], mirror_charm: [2, 6] };
	for (const [id, f] of Object.entries(per)) {
		let last = 0;
		for (let t = 0; t <= 10; t++) {
			const s = at(id, t);
			assert.equal(s.abilityCost, 30 + 5 * t, `${id} T${t} cost`);
			const v = f(s) / s.abilityCost;
			assert.ok(v >= last - 1e-9, `${id} T${t} is worse per MP (${v} < ${last})`);
			last = v;
		}
		if (want[id]) {
			assert.ok(Math.abs(f(at(id, 0)) - want[id][0]) < 1e-9 && Math.abs(f(at(id, 10)) - want[id][1]) < 1e-9, id);
		}
	}
	assert.ok(Math.abs(at("stillness_orb", 0).slowRadius - 2) < 1e-9 && Math.abs(at("stillness_orb", 10).slowRadius - 4) < 1e-9);
});

test("the counter alone has a cooldown: six seconds, whatever the MP", () => {
	const st = createSim(A, NINJA, { class_id: "ninja" });
	st.enemies = [];
	st.p.mp = st.stats.maxMp = 1000;
	step(st, { ability: true });
	const mp = st.p.mp;
	assert.ok(st.p.counterUntil > st.tick, "cast");
	for (let i = 0; i < 6 * TPS - 2; i++) step(st, { ability: true });
	assert.ok(st.p.mp >= mp, "nothing more was spent during the cooldown");
	for (let i = 0; i < 3; i++) step(st, { ability: true });
	assert.ok(st.p.mp < mp, "and it casts again once it is over");
});
