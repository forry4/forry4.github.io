/* The Ashen Breach (owner's design, 2026-11-19) in the browser's fight: the creeping
 * fire, the Cinder, the Kiln, the Smolder and the Pyre, and the nine uniques that set
 * fire of the player's own. The fixture is a real dungeon from halcyon/dungeon.py,
 * held to the generator by halcyon/tests/test_sim_fixtures.py. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, fingerprint, statsFor, creepAt, BOSS_HP, TPS, CREEP, KILN, SMOLDER, PYRE, UNIQUE, EMBER,
	STARFALL_DELAY, MORTAR } from "../../../halcyon/sim.js";
import { createTown, stepTown, setTownGear, POSTS } from "../../../halcyon/town.js";

const F = JSON.parse(readFileSync(new URL("./fixtures/halcyon-dungeon-ashen-a.json", import.meta.url)));
const RANGER = [{ base_id: "longbow", tier: 1 }, { base_id: "leather_vest", tier: 1 }, { base_id: "volley_quiver", tier: 1 }];
const PALADIN = [{ base_id: "mace", tier: 1 }, { base_id: "plate_armor", tier: 1 }, { base_id: "stillness_orb", tier: 1 }];
const shot = (x, y, dmg = 5) => ({ owner: "p", x, y, vx: 0, vy: 0, dmg, r: 0.1, life: 5, pierce: 0, hit: [] });
const enemyShot = (st, dmg) => st.bullets.push({ owner: "e", x: st.p.x, y: st.p.y, vx: 0, vy: 0, dmg, r: 0.1, life: 5, pierce: 0, hit: [] });
const run = (st, n, input = {}) => { for (let i = 0; i < n && st.status === "play"; i++) step(st, input); };

/* Put the player in room `i` (sealing it); everything but what `keep` picks is put to sleep
 * (it still counts, so the room stays sealed). */
function inRoom(st, i, keep = () => false, hp = 100000) {
	const r = st.rooms[i];
	st.p.x = (r.x0 + r.x1) / 2; st.p.y = st.doorY + 0.5;
	st.p.hp = st.stats.maxHp = st.p.low = hp;
	step(st, {});
	assert.equal(st.sealed, i, "the room sealed");
	for (const e of st.enemies) if (!keep(e)) e.active = false;
	return r;
}
const roomWith = (st, type) => st.enemies.find((e) => e.type === type && st.rooms[e.room].kind === "combat").room;

test("the Ashen Breach's boss is the Pyre; its Kilns wait out of play, and the rooms burn", () => {
	const st = createSim(F, RANGER);
	assert.equal(st.dungeonId, "ashen");
	assert.equal(st.hazard, "creep");
	const boss = st.enemies.find((e) => e.type === "boss");
	assert.equal(boss.form, "pyre");
	assert.equal(boss.maxHp, BOSS_HP.pyre);
	const kilns = st.enemies.filter((e) => e.summon === boss.id);
	assert.equal(kilns.length, PYRE.kilns.length);
	assert.ok(kilns.every((k) => k.type === "kiln" && k.dormant && !k.parent));
	for (const t of ["cinder", "kiln", "smolder", "shooter"]) assert.ok(st.enemies.some((e) => e.type === t), `the fixture has a ${t}`);
});

test("fire creeps in from the walls a ring at a time, warns first, stops short of the middle and goes out on a clear", () => {
	const st = createSim(F, RANGER);
	const i = roomWith(st, "smolder"), r = inRoom(st, i);
	const [y0, y1] = st.roomY[i], mid = Math.floor((r.x0 + r.x1) / 2), doorY = st.doorY;
	run(st, CREEP.after - 3);
	assert.equal(st.creep.ring, 0, "nothing burns for the first ten seconds");
	assert.equal(creepAt(st, r.x0, doorY), 1, "the edge warns before it catches");
	run(st, 4);
	assert.equal(st.creep.ring, 1);
	assert.equal(creepAt(st, r.x0, doorY), 2, "the outermost ring burns");
	assert.equal(creepAt(st, r.x0 + 1, doorY), 0, "and only it");
	st.p.x = r.x0 + 0.5; st.p.y = doorY + 0.5;
	const hp = st.p.hp;
	run(st, MORTAR.burnEvery + 1);
	assert.ok(st.p.hp < hp && st.lastHit.src === "rift:fire", "standing in it hurts");
	st.p.x = mid + 0.5;
	run(st, 30 * CREEP.every);
	const max = Math.floor((Math.min(r.x1 - r.x0, y1 - y0 + 1) - CREEP.keep) / 2);
	assert.equal(st.creep.ring, max, "it stops");
	const open = [];
	for (let y = y0; y <= y1; y++) if (creepAt(st, mid, y) === 0) open.push(y);
	assert.ok(open.length >= CREEP.keep, `${open.length} tiles open across the middle`);
	for (const e of st.enemies) if (e.room === i && e.hp > 0) { e.active = true; e.hp = 1; st.bullets.push(shot(e.x, e.y)); }
	run(st, 2);
	assert.equal(st.sealed, -1);
	assert.equal(st.creep, null, "a cleared room stops burning");
});

test("a Cinder runs at you and leaves fire behind it", () => {
	const st = createSim(F, RANGER);
	const c = st.enemies.find((e) => e.type === "cinder");
	inRoom(st, c.room, (e) => e === c);
	c.x = st.p.x + 5; c.y = st.p.y; c.tele = 0; c.scd = 1e9;
	run(st, 40);
	assert.ok(c.x < st.p.x + 5 - 1, "it closes in");
	assert.ok(st.fires.filter((f) => f.src === "cinder:fire").length >= 3, "a trail");
});

test("a Kiln stands still and lobs a firebomb where you stand, which leaves fire", () => {
	const st = createSim(F, RANGER);
	const k = st.enemies.find((e) => e.type === "kiln" && !e.summon);
	inRoom(st, k.room, (e) => e === k);
	k.cd = 0; k.x = st.p.x + 4; k.y = st.p.y;
	const at = { x: st.p.x, y: st.p.y };
	for (let t = 0; t < KILN.tele + 5 && !st.mortars.length; t++) step(st, {});
	const m = st.mortars.find((x) => x.src === "kiln:bomb");
	assert.ok(m && m.x === at.x && m.y === at.y && m.r === KILN.r && m.at - st.tick === KILN.delay, "aimed where you stood");
	assert.equal(k.x, at.x + 4, "it never moves");
	const hp = st.p.hp;
	run(st, KILN.delay);
	assert.ok(hp - st.p.hp >= KILN.dmg * 0.4 && st.lastHit.src === "kiln:bomb", "the landing hurts");
	assert.ok(st.fires.some((f) => f.src === "kiln:fire"), "and it burns after");
});

test("a Smolder does nothing until it is hit, then flares, charges and bursts into fire", () => {
	const st = createSim(F, RANGER);
	const sm = st.enemies.find((e) => e.type === "smolder");
	inRoom(st, sm.room, (e) => e === sm);
	sm.x = st.p.x + 4; sm.y = st.p.y;
	run(st, 5 * TPS);
	assert.ok(!sm.lit && sm.x === st.p.x + 4 && !st.mortars.length && !st.bullets.length, "harmless while dormant");
	st.bullets.push(shot(sm.x, sm.y));
	step(st, {});
	assert.ok(sm.lit && sm.hp > 0, "a hit lights it");
	run(st, SMOLDER.flare - 1);
	assert.equal(sm.x, st.p.x + 4, "it flares in place first");
	const kills = [];
	for (let t = 0; t < SMOLDER.charge + 5 && sm.hp > 0; t++) { step(st, {}); kills.push(...st.events.filter((e) => e.type === "kill")); }
	assert.ok(sm.hp <= 0 && kills.some((e) => e.enemy === sm.id), "it bursts (and counts as a kill)");
	const m = st.mortars.find((x) => x.src === "smolder:burst");
	assert.ok(m && Math.abs(m.x - st.p.x) < SMOLDER.reach + 0.5, "beside you");
	run(st, SMOLDER.fuse);
	assert.ok(st.fires.some((f) => f.src === "smolder:fire"));
});

test("the Pyre: rings of shots, crosses of fire, then a burning arena and its Kilns; they fall with it", () => {
	const st = createSim(F, RANGER);
	const boss = st.enemies.find((e) => e.type === "boss");
	inRoom(st, boss.room, (e) => e === boss);
	boss.cd = 0;
	st.p.x = boss.x - 3;
	run(st, 1);
	const ring = st.bullets.filter((b) => b.src === "boss:ring").length;
	assert.equal(ring, PYRE.ring.n, "a ring of sixteen");
	run(st, 150);
	const cross = st.mortars.filter((m) => m.src === "boss:flame");
	assert.ok(cross.length >= 5, `a cross of ${cross.length} shells`);
	assert.ok(cross.some((m) => Math.abs(m.x - st.p.x) < 1e-9 && Math.abs(m.y - st.p.y) < 1e-9), "centred where you stand");
	assert.equal(st.creep, null, "the arena does not burn in phase 1");
	boss.hp = boss.maxHp / 2;
	run(st, 75);
	assert.equal(boss.phase, 2);
	assert.equal(st.creep.room, boss.room, "phase 2: the arena burns");
	const kilns = st.enemies.filter((e) => e.summon === boss.id);
	assert.ok(kilns.every((k) => !k.dormant && k.active && k.hp > 0), "its Kilns come in");
	const events = [];
	boss.hp = 1; st.bullets.push(shot(boss.x, boss.y));
	step(st, {}); events.push(...st.events);
	assert.ok(kilns.every((k) => k.hp <= 0), "and fall with it");
	for (const k of kilns) assert.ok(events.some((e) => e.type === "kill" && e.enemy === k.id), `${k.id} is credited`);
	assert.equal(st.sealed, -1, "the arena opens");
	assert.equal(st.creep, null);
});

// ── the uniques ─────────────────────────────────────────────────────────────
/* A sim with `gear`, a still target `dx` tiles to the right, and the player's HP as given. */
function range(gear, classId = "ranger", dx = 2, hp = 100000) {
	const st = createSim(F, gear, { class_id: classId });
	const proto = st.enemies.find((e) => e.type === "shooter");
	st.enemies = [{ ...proto, id: "t0", room: null, x: st.p.x + dx, y: st.p.y, hp: 10000, maxHp: 10000, active: true, cd: 1e9, tele: 0, ward: 0 }];
	st.roomLeft = st.rooms.map(() => 0);
	st.p.hp = st.p.low = st.stats.maxHp = hp;
	const home = { x: st.enemies[0].x, y: st.enemies[0].y };
	st.hold = () => { for (const e of st.enemies) { e.x = home.x; e.y = home.y; } };
	return st;
}
const tick = (st, input = {}) => { step(st, input); st.hold?.(); };
const ticks = (st, n, input = {}) => { for (let i = 0; i < n && st.status === "play"; i++) tick(st, input); };
const swap = (gear, slot, base_id) => gear.map((x, i) => (i === slot ? { base_id, tier: 1 } : x));
const fire = { fire: true, ax: 1, ay: 0 };

test("the Phoenix Feather: a killing hit leaves you at 1 HP once a level, guarded a moment, with fire round you", () => {
	const st = range([...RANGER, { base_id: "phoenix_feather", tier: 1 }], "ranger", 1.5, 10);
	const t = st.enemies[0];
	enemyShot(st, 500); tick(st);
	assert.equal(st.status, "play");
	assert.ok(st.p.hp >= 1 && st.p.hp < 1.1, `left at ${st.p.hp}`);
	assert.ok(st.p.phoenixUsed && st.embers.length === 1 && st.embers[0].dmg === statsFor([{ base_id: "phoenix_feather", tier: 1 }]).phoenix);
	assert.ok(t.burnUntil > st.tick, "what is near catches");
	enemyShot(st, 500); tick(st);
	assert.ok(st.p.hp >= 1 && st.p.hp < 1.1, "guarded just after");
	ticks(st, UNIQUE.phoenix.guard);
	enemyShot(st, 500); tick(st);
	assert.equal(st.status, "dead", "and only once");
});

test("the Ash Sigil: an enemy that dies burning explodes onto those beside it", () => {
	const blast = (burning) => {
		const st = range([...RANGER, { base_id: "ash_sigil", tier: 1 }]);
		const a = st.enemies[0], b = { ...a, id: "t1", x: a.x + 1, hp: 1000, maxHp: 1000 };
		st.enemies.push(b); st.hold = null;
		a.hp = 1;
		if (burning) { a.burnUntil = st.tick + 100; a.burnDmg = 1; }
		st.bullets.push(shot(a.x, a.y)); step(st, {});
		assert.ok(a.hp <= 0);
		return 1000 - b.hp;
	};
	assert.equal(blast(true), statsFor([{ base_id: "ash_sigil", tier: 1 }]).ashSigil);
	assert.equal(blast(false), 0, "not burning, no blast");
});

test("Banked Coal: your shots hit harder the longer you go unhit, and a hit starts it over", () => {
	const st = range([...RANGER, { base_id: "banked_coal", tier: 1 }], "ranger", 6);
	const cap = st.stats.coalCap;
	const volleyDmg = () => {
		st.p.fireCd = 0; const before = new Set(st.bullets);
		tick(st, fire);
		return st.bullets.find((b) => !before.has(b) && b.owner === "p").dmg;
	};
	const plain = st.stats.dmg;
	ticks(st, UNIQUE.coal.every * (cap + 3));
	const full = volleyDmg();
	assert.equal(full, Math.round(plain * (1 + cap / 25)), `${plain} -> ${full} at +${cap}`);
	enemyShot(st, 5); tick(st);
	assert.equal(volleyDmg(), plain, "back to plain after a hit");
});

test("the Emberweave leaves fire where you walk, and it burns enemies", () => {
	const st = range(swap(RANGER, 1, "emberweave"), "ranger", -1);
	const t = st.enemies[0], hp = t.hp;
	ticks(st, 60, { mx: 1 });
	assert.ok(st.embers.length >= 4, `${st.embers.length} embers`);
	t.x = st.embers[0].x; t.y = st.embers[0].y; st.hold = null;
	ticks(st, EMBER.every + 1);
	assert.ok(t.hp < hp, "the trail burns it");
	const town = createTown(); setTownGear(town, swap(RANGER, 1, "emberweave"));
	for (let i = 0; i < 30; i++) stepTown(town, { mx: 1 });
	assert.ok(town.embers.length >= 2, "in town too");
});

test("Cinderguard: burning ground does not hurt you, and you take less from hits while in it", () => {
	const gear = swap(PALADIN, 1, "cinderguard");
	const st = range(gear, "paladin", 6);
	st.fires.push({ x: st.p.x, y: st.p.y, r: 1, until: st.tick + 1000 });
	const hp = st.p.hp;
	ticks(st, 3 * MORTAR.burnEvery);
	assert.equal(st.p.hp, hp, "fireproof");
	assert.ok(st.p.inFire);
	const take = () => { const h = st.p.hp; enemyShot(st, 40); tick(st); return h - st.p.hp; };
	const inFire = take();
	st.fires = []; tick(st);
	const outOf = take();
	assert.ok(Math.abs(outOf - inFire - st.stats.cinderDef) < 0.11, `${outOf} out, ${inFire} in`);
});

test("the Flare Bow: every fourth shot is a flare that leaves the ground burning where it hits", () => {
	const st = range(swap(RANGER, 0, "flare_bow"), "ranger", 3);
	const seen = [];
	for (let i = 0; i < 400 && seen.length < 8; i++) {
		const before = new Set(st.bullets);
		tick(st, fire);
		for (const b of st.bullets) if (!before.has(b) && b.owner === "p") seen.push(!!b.flare);
	}
	assert.deepEqual(seen, [false, false, false, true, false, false, false, true]);
	ticks(st, 30);
	// (the target steps a little inside each tick before it is pinned back)
	assert.ok(st.embers.some((f) => Math.abs(f.x - st.enemies[0].x) < 0.2 && f.r === UNIQUE.flare.r), "fire where it hit");
});

test("the Censer burns twice as hard as a Stillness Orb but slows shots less", () => {
	const orb = statsFor(PALADIN, 1, "paladin"), censer = statsFor(swap(PALADIN, 2, "censer"), 1, "paladin");
	assert.ok(Math.abs(censer.abilityDmg - orb.abilityDmg * UNIQUE.censer.burn) < 1e-9);
	assert.equal(censer.slowRadius, orb.slowRadius);
	const st = range(swap(PALADIN, 2, "censer"), "paladin");
	step(st, { ability: true });
	assert.equal(st.slowF, UNIQUE.censer.slow);
	const b = { owner: "e", x: st.p.x + 1, y: st.p.y, vx: 6, vy: 0, dmg: 1, r: 0.1, life: 50, pierce: 0, hit: [] };
	st.bullets.push(b); const x0 = b.x; step(st, {});
	assert.ok(Math.abs((b.x - x0) - 6 / TPS * UNIQUE.censer.slow) < 1e-9, "75% speed in the field");
});

test("the Meteor Tome's star leaves a burning crater", () => {
	const gear = [{ base_id: "wand", tier: 1 }, { base_id: "leather_vest", tier: 1 }, { base_id: "meteor_tome", tier: 1 }];
	const st = range(gear, "diviner", 3);
	const t = st.enemies[0];
	step(st, { ability: true, ax: 3, ay: 0 });
	ticks(st, STARFALL_DELAY);
	const crater = st.embers.find((f) => f.r > 1);
	assert.ok(crater && Math.abs(crater.x - t.x) < 1e-9, "where it fell");
	assert.equal(crater.until - st.tick, UNIQUE.meteor.last, "for three seconds");
	const hp = t.hp;
	ticks(st, EMBER.every + 1);
	assert.ok(t.hp < hp, "it burns");
});

test("the Ember Kunai sticks and bursts a second later for more", () => {
	const gear = [{ base_id: "ember_kunai", tier: 1 }, { base_id: "plate_armor", tier: 1 }, { base_id: "mirror_charm", tier: 1 }];
	const st = range(gear, "ninja", 2);
	const t = st.enemies[0], hp0 = t.hp;
	tick(st, fire);
	let hitAt = -1;
	for (let i = 0; i < 40 && hitAt < 0; i++) { tick(st); if (t.hp < hp0) hitAt = st.tick; }
	const first = hp0 - t.hp;
	assert.equal(first, st.stats.dmg);
	assert.equal(st.stuck.length, 1);
	ticks(st, UNIQUE.kunai.delay - 1);
	assert.equal(hp0 - t.hp, first, "not yet");
	tick(st);
	assert.equal(hp0 - t.hp - first, Math.round(first * UNIQUE.kunai.share), "the burst");
	// and on the town's posts
	const town = createTown({ x: POSTS[0].x - 2.5, y: POSTS[0].y }, "ninja"); setTownGear(town, gear, 1, "ninja");
	for (let i = 0; i < 3 * TPS; i++) stepTown(town, { fire: true, ax: 1, ay: 0 });
	assert.ok(town.posts[0].hits.some((h) => h.dmg === Math.round(first * UNIQUE.kunai.share)), "it bursts on a post too");
});

test("an Ashen run with every fire unique plays the same twice", () => {
	const kits = {
		ranger: [{ base_id: "flare_bow", tier: 3 }, { base_id: "emberweave", tier: 2 }, { base_id: "volley_quiver", tier: 2 },
			{ base_id: "phoenix_feather", tier: 1 }, { base_id: "ash_sigil", tier: 2 }],
		ninja: [{ base_id: "ember_kunai", tier: 3 }, { base_id: "cinderguard", tier: 2 }, { base_id: "mirror_charm", tier: 1 },
			{ base_id: "banked_coal", tier: 2 }, { base_id: "ash_sigil", tier: 1 }],
		diviner: [{ base_id: "wand", tier: 2 }, { base_id: "emberweave", tier: 1 }, { base_id: "meteor_tome", tier: 2 }],
		paladin: [{ base_id: "mace", tier: 2 }, { base_id: "cinderguard", tier: 1 }, { base_id: "censer", tier: 2 }],
	};
	for (const [cls, gear] of Object.entries(kits)) {
		const go = () => {
			const st = createSim(F, gear, { class_id: cls });
			for (let t = 0; t < 40 * TPS && st.status === "play"; t++)
				step(st, { mx: t % 400 < 300 ? 1 : 0, my: t % 90 < 45 ? 1 : -1, fire: true, ax: 1, ay: 0.1, ability: t % 150 === 0 });
			return fingerprint(st);
		};
		assert.equal(go(), go(), cls);
	}
});
