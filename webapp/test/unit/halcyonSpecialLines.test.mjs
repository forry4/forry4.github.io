/* THE SPECIAL LINES (owner's calls, 2026-11-19): the deep-dungeon enchantments —
 * tradeoffs and triggers — driven through the real sim on a real dungeon. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, statsFor, fingerprint, enchantValue, lineLevel, isSpecial, SPECIAL, ENCHANT_FLAT, UNIQUE, TPS } from "../../../halcyon/sim.js";

const A = JSON.parse(readFileSync(new URL("./fixtures/halcyon-dungeon-unit-a.json", import.meta.url)));
const KIT = [{ base_id: "shortbow", tier: 1 }, { base_id: "leather_vest", tier: 1 }, { base_id: "volley_quiver", tier: 1 }];
/* The ranger's kit with one line put on the item at `slot` (0 weapon, 1 armor, 2 ability). */
const withLine = (id, slot, q = 1) => KIT.map((x, i) => (i === slot ? { ...x, enchants: [{ id, q }] } : { ...x }));

function range(gear) {
	const st = createSim(A, gear, { class_id: "ranger" });
	const proto = st.enemies.find((e) => e.type === "chaser");
	st.enemies = [{ ...proto, id: "t0", room: null, x: st.p.x + 2, y: st.p.y, hp: 10000, maxHp: 10000, active: true, cd: 1e9, scd: 1e9, tele: 0, ward: 0 }];
	st.p.hp = st.p.low = st.stats.maxHp = 100000;
	const home = { x: st.enemies[0].x, y: st.enemies[0].y };
	st.hold = () => { for (const e of st.enemies) { e.x = home.x; e.y = home.y; } };   // a still target
	return st;
}
const tick = (st, input = {}) => { step(st, input); st.hold?.(); };
const run = (st, ticks, input = {}) => { for (let i = 0; i < ticks; i++) tick(st, input); };
const fire = { fire: true, ax: 1, ay: 0 };
const enemyShot = (st, dmg = 30) => st.bullets.push({ owner: "e", x: st.p.x, y: st.p.y, vx: 0, vy: 0, dmg, r: 0.1, life: 5, pierce: 0, hit: [] });

test("a line's level is the quarter of its quality", () => {
	assert.deepEqual([0, 0.24, 0.25, 0.5, 0.74, 0.75, 1].map(lineLevel), [1, 1, 2, 3, 3, 4, 4]);
	for (const id of Object.keys(SPECIAL)) assert.ok(isSpecial(id) && ENCHANT_FLAT[id], id);
	assert.ok(!isSpecial("attack"));
});

test("the tradeoffs give their stat and take their cost", () => {
	const base = statsFor(KIT);
	const fury = statsFor(withLine("fury", 0));
	assert.equal(base.def - fury.def, SPECIAL.fury.def);
	assert.ok(fury.dmg > base.dmg);
	const glass = statsFor(withLine("glass_mind", 2));
	assert.equal(glass.ap - base.ap, enchantValue("glass_mind", 1));
	assert.equal(base.maxHp - glass.maxHp, SPECIAL.glass_mind.hp);
	const fleet = statsFor(withLine("fleetfoot", 1));
	assert.equal(fleet.dex - base.dex, enchantValue("fleetfoot", 1));
	assert.equal(base.maxHp - fleet.maxHp, SPECIAL.fleetfoot.hp);
});

test("Kindling: a cast sets the next volleys burning, then it stops", () => {
	const st = range(withLine("kindling", 2));
	assert.equal(st.stats.kindle, enchantValue("kindling", 1));
	run(st, 1, fire);
	assert.ok(!st.bullets.some((b) => b.owner === "p" && b.burn), "no burn before a cast");
	st.bullets = []; st.p.fireCd = 0; st.p.mp = st.stats.maxMp;
	step(st, { ability: true, ax: 1, ay: 0 });
	assert.equal(st.p.kindled, SPECIAL.kindling.shots);
	const burning = [];
	for (let i = 0; i < 400 && burning.length < SPECIAL.kindling.shots + 1; i++) {
		const before = new Set(st.bullets);
		tick(st, fire);
		const fresh = st.bullets.filter((b) => !before.has(b) && b.owner === "p" && b.r === 0.14);
		if (fresh.length) burning.push(fresh.some((b) => b.burn));
	}
	assert.deepEqual(burning, [true, true, true, false]);
});

test("Second Wind: a kill gives MP back, at most once a second", () => {
	const st = range(withLine("second_wind", 1));
	const v = enchantValue("second_wind", 1);
	st.p.mp = 10;
	st.enemies[0].hp = 1;
	while (st.enemies[0].hp > 0) run(st, 1, fire);
	assert.ok(st.p.mp >= 10 + v && st.p.mp < 10 + v + 1, `mp ${st.p.mp}`);
	assert.equal(st.p.windAt - st.tick <= SPECIAL.second_wind.cooldown, true);
});

test("Bulwark: a hit raises Defense for the hits after it, then it wears off", () => {
	const st = range(withLine("bulwark", 1));
	const v = enchantValue("bulwark", 1);
	const hit = () => { const hp = st.p.hp; enemyShot(st, 30); step(st, {}); return hp - st.p.hp; };
	const first = hit();
	const second = hit();
	assert.ok(Math.abs(first - second - v) < 0.11, `${first} then ${second}`);
	run(st, SPECIAL.bulwark.cooldown);
	assert.ok(Math.abs(hit() - first) < 0.11, "back to plain after it wears off");
});

test("special lines keep the sim deterministic", () => {
	const gear = KIT.map((x, i) => ({ ...x, enchants: [[{ id: "fury", q: 0.5 }], [{ id: "bulwark", q: 0.3 }, { id: "second_wind", q: 0.9 }], [{ id: "kindling", q: 0.7 }]][i] }));
	const play = () => {
		const st = createSim(A, gear, { class_id: "ranger" });
		for (let t = 0; t < 900; t++) step(st, { fire: t % 3 !== 0, ability: t % 200 === 5, ax: 1, ay: 0.2, mx: t % 120 < 60 ? 1 : -1 });
		return fingerprint(st);
	};
	assert.equal(play(), play());
});
