/* The Fracture (design §14.4a) in the browser's fight: cracks, the Splitter and its
 * Splinters, the Flicker's blink and the Breach. The fixture is a real dungeon from
 * halcyon/dungeon.py, held to the generator by halcyon/tests/test_sim_fixtures.py. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, fingerprint, doorAt, CRACK, BOSS_HP, TPS, FAULT, SHATTER } from "../../../halcyon/sim.js";

const F = JSON.parse(readFileSync(new URL("./fixtures/halcyon-dungeon-fracture-a.json", import.meta.url)));
const GEAR = [{ base_id: "longbow", tier: 1 }, { base_id: "leather_vest", tier: 1 }, { base_id: "volley_quiver", tier: 1 }];

/* Put the player inside room `i` (sealing it) with nothing else in play. */
function inRoom(st, i, keep = () => false) {
	const r = st.rooms[i];
	st.p.x = (r.x0 + r.x1) / 2; st.p.y = st.doorY + 0.5;
	st.p.hp = st.stats.maxHp = 100000; st.p.low = st.p.hp;
	step(st, {});
	assert.equal(st.sealed, i, "the room sealed");
	for (const e of st.enemies) if (!keep(e)) { e.cd = 1e9; e.scd = 1e9; e.tele = 0; }
	return r;
}

test("the Fracture's boss is the Breach, and Splinters wait out of play", () => {
	const st = createSim(F, GEAR);
	assert.equal(st.dungeonId, "fracture");
	const boss = st.enemies.find((e) => e.type === "boss");
	assert.equal(boss.form, "breach");
	assert.equal(boss.maxHp, BOSS_HP.breach);
	const splinters = st.enemies.filter((e) => e.type === "splinter");
	assert.ok(splinters.length >= 2, "the fixture has a Splitter");
	assert.ok(splinters.every((e) => e.dormant && e.parent));
	assert.ok(st.cracks.length > 0);
});

test("cracks open only while their room is fought, on the cycle, and close again", () => {
	const st = createSim(F, GEAR);
	const c = st.cracks[0], [tx, ty] = c.tiles[0];
	for (let t = 0; t < CRACK.period; t++) step(st, {});
	assert.ok(!st.cracks.some((k) => k.open || k.warn), "nothing moves in a room not entered");
	inRoom(st, c.room);
	st.enemies.forEach((e) => { if (e.room !== c.room) e.active = false; });
	let warned = false, opened = -1, closed = -1;
	for (let t = 0; t < 2 * CRACK.period && closed < 0; t++) {
		step(st, {});
		warned ||= c.warn;
		if (opened < 0 && c.open) { opened = t; assert.ok(warned, "it warns before it opens"); assert.equal(doorAt(st, tx + 0.5, ty + 0.5), "x"); }
		if (opened >= 0 && !c.open) closed = t;
	}
	assert.ok(opened >= 0 && closed > opened, "it opened and closed");
	assert.ok(Math.abs(closed - opened - CRACK.open) <= 1, `open for ${closed - opened} ticks`);
	assert.equal(doorAt(st, tx + 0.5, ty + 0.5), ".", "closed is floor again");
});

test("a crack that opens under the player throws them clear and hurts", () => {
	const st = createSim(F, GEAR);
	const c = st.cracks[0];
	inRoom(st, c.room);
	const [tx, ty] = c.tiles[Math.floor(c.tiles.length / 2)];
	c.t = CRACK.period - CRACK.open - 1;                 // one tick from opening
	st.p.x = tx + 0.5; st.p.y = ty + 0.5;
	const hp = st.p.hp;
	step(st, {});
	assert.ok(c.open);
	assert.ok(hp - st.p.hp >= CRACK.dmg * 0.4, `took ${hp - st.p.hp}`);   // less the armor's defense
	assert.equal(st.lastHit.src, "rift:crack");
	assert.notEqual(doorAt(st, st.p.x, st.p.y), "x", "standing on solid ground");
});

test("a Splitter breaks into its Splinters, and the room waits for them", () => {
	const st = createSim(F, GEAR);
	const sp = st.enemies.find((e) => e.type === "splitter");
	inRoom(st, sp.room);
	const kids = st.enemies.filter((e) => e.parent === sp.id);
	assert.ok(kids.every((k) => k.dormant && !k.active), "not in play before it dies");
	for (const e of st.enemies) if (e.room === sp.room && e !== sp && !kids.includes(e)) { e.hp = 0; st.roomLeft[sp.room]--; }
	sp.hp = 1;
	st.bullets.push({ owner: "p", x: sp.x, y: sp.y, vx: 0, vy: 0, dmg: 5, r: 0.1, life: 5, pierce: 0, hit: [] });
	step(st, {});
	assert.ok(sp.hp <= 0);
	assert.ok(kids.every((k) => !k.dormant && k.active && k.hp > 0), "they come into play");
	assert.equal(st.sealed, sp.room, "still sealed");
	for (const k of kids) { k.hp = 1; st.bullets.push({ owner: "p", x: k.x, y: k.y, vx: 0, vy: 0, dmg: 5, r: 0.1, life: 5, pierce: 0, hit: [] }); }
	step(st, {});
	assert.equal(st.sealed, -1, "open once they fall");
});

test("a Flicker marks where it will land, blinks there and fires a ring", () => {
	const st = createSim(F, GEAR);
	const fl = st.enemies.find((e) => e.type === "flicker");
	inRoom(st, fl.room, (e) => e === fl);
	fl.cd = 0;
	step(st, {});
	assert.ok(fl.tele > 0 && (fl.toX || fl.toY), "a marked destination");
	const to = { x: fl.toX, y: fl.toY };
	while (fl.tele > 0) step(st, {});
	assert.ok(Math.abs(fl.x - to.x) < 1e-9 && Math.abs(fl.y - to.y) < 1e-9, "it landed where it said");
	assert.equal(st.bullets.filter((b) => b.src === "flicker:ring").length, 8, "a ring of eight");
});

test("a Flicker never picks a crack to land on, and a crack that opens there moves it clear", () => {
	const st = createSim(F, GEAR);
	const fl = st.enemies.find((e) => e.type === "flicker");
	inRoom(st, fl.room, (e) => e === fl);
	const onCrack = (x, y) => st.crackAt[Math.floor(y) * st.w + Math.floor(x)] !== undefined;
	for (let n = 0; n < 40; n++) {                     // forty blinks, none marked on a crack
		fl.cd = 0;
		step(st, {});
		if (fl.toX || fl.toY) assert.ok(!onCrack(fl.toX, fl.toY), `marked ${fl.toX},${fl.toY}`);
		while (fl.tele > 0) step(st, {});
	}
	const c = st.cracks.find((k) => k.room === fl.room);
	assert.ok(c, "the Flicker's room has a crack");
	fl.cd = 0;
	step(st, {});
	const [tx, ty] = c.tiles[0];
	fl.toX = tx + 0.5; fl.toY = ty + 0.5;             // as if it marked a spot that then tore open
	for (const k of st.cracks) if (k.room === fl.room) k.t = CRACK.period - CRACK.open;
	while (fl.tele > 0) step(st, {});
	assert.notEqual(doorAt(st, fl.x, fl.y), "x", "landed on solid ground");
});

test("the Breach marks fault lines, then they tear into a still wall that a pillar stops", () => {
	const st = createSim(F, GEAR);
	const boss = st.enemies.find((e) => e.type === "boss");
	inRoom(st, boss.room, (e) => e === boss);
	st.p.x = boss.x - 6; st.p.y = boss.y;              // straight west of it
	boss.cd = 0;
	step(st, {});
	assert.equal(boss.faults.length, 3, "a Y in phase 1");
	const [vx, vy] = boss.faults[0];
	assert.ok(vx < -0.99 && Math.abs(vy) < 0.01, "the first line points at the player");
	const marks = boss.faults.map((f) => f.slice());
	assert.ok(!st.bullets.some((b) => b.src === "boss:fault"), "nothing yet: only marks");
	for (let t = 0; t < FAULT.tele; t++) step(st, {});
	const wall = st.bullets.filter((b) => b.src === "boss:fault");
	assert.ok(wall.length > 10 && wall.every((b) => b.vx === 0 && b.vy === 0), `a still wall of ${wall.length}`);
	for (const [mx, my, len] of marks) {                // every shot on a marked line, inside its length
		assert.ok(len < FAULT.reach + 1e-9);
	}
	for (const b of wall) assert.ok(marks.some(([mx, my, len]) => {
		const s = (b.x - boss.x) * mx + (b.y - boss.y) * my, off = Math.abs((b.x - boss.x) * my - (b.y - boss.y) * mx);
		return off < 1e-6 && s > 0.5 && s <= len + 1e-6;
	}), "on a mark");
	assert.ok(marks.some(([, , len]) => len < FAULT.reach - 1), "a pillar or wall cut one short");
	for (let t = 0; t < FAULT.life + 2; t++) { st.p.hp = 100000; step(st, {}); }
	assert.ok(!st.bullets.some((b) => b.src === "boss:fault" && b.vx === 0 && wall.includes(b)), "and the tear closes");
});

test("the Breach's shatter shards burst into rings", () => {
	const st = createSim(F, GEAR);
	const boss = st.enemies.find((e) => e.type === "boss");
	inRoom(st, boss.room, (e) => e === boss);
	st.p.x = boss.x; st.p.y = boss.y + 6;
	boss.cd = 0; boss.mode = 2; boss.modeT = 66;     // the shatter
	for (let t = 0; t < 21; t++) step(st, {});
	const shards = st.bullets.filter((b) => b.shard);
	assert.equal(shards.length, 3, "three shards");
	for (let t = 0; t < SHATTER.fuse; t++) step(st, {});
	assert.ok(st.bullets.filter((b) => b.src === "boss:shatter" && !b.shard).length >= 2 * SHATTER.n, "each burst into a ring");
});

test("the Breach, at half health, speeds its cracks and blinks between anchors", () => {
	const st = createSim(F, GEAR);
	const boss = st.enemies.find((e) => e.type === "boss");
	inRoom(st, boss.room, (e) => e === boss);
	boss.cd = 0;
	for (let t = 0; t < 120; t++) step(st, {});
	assert.ok(st.bullets.some((b) => b.src === "boss:fault"), "phase 1 tears fault lines");
	boss.hp = boss.maxHp / 2;
	for (let t = 0; t < 80; t++) step(st, {});
	assert.equal(boss.phase, 2);
	assert.equal(st.fastRoom, boss.room, "its cracks run fast");
	const home = { x: boss.homeX, y: boss.homeY };
	let moved = false;
	for (let t = 0; t < 600; t++) { step(st, {}); moved ||= Math.abs(boss.x - home.x) > 2; }
	assert.ok(moved, "it blinked away from where it started");
});

test("the Fracture plays the same twice from the same inputs", () => {
	const run = () => {
		const st = createSim(F, GEAR);
		for (let t = 0; t < 40 * TPS && st.status === "play"; t++)
			step(st, { mx: t % 400 < 300 ? 1 : 0, my: t % 120 < 60 ? 1 : -1, fire: true, ax: 1, ay: 0 });
		return fingerprint(st);
	};
	assert.equal(run(), run());
});
