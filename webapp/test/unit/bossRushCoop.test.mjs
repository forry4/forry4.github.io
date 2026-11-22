import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { BOSS_HP, COOP_BOSS_HP, createSim, fingerprint, heroView, step } from "../../../bossrush/sim.js";

/* Co-op Boss Rush (owner's ask, 2026-11-22): a second hero, the boss at twice its
 * health, and every attack aimed at "the player" aimed at each living hero. */

function arena(kind, objectives = []) {
	const border = "#".repeat(24);
	return {
		id: kind, boss_kind: kind, seed: "coop-test", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } },
		drops: {}, pickups: [], objectives,
	};
}
const duo = (kind, a = "ranger", b = "paladin", dungeon = arena(kind)) =>
	createSim(dungeon, CHARACTERS[a].gear, { classId: a }, { gear: CHARACTERS[b].gear, classId: b });
const place = (st, i, x, y) => { st.heroes[i].p.x = x; st.heroes[i].p.y = y; };

test("co-op doubles the boss's health; solo is unchanged", () => {
	for (const kind of Object.keys(BOSS_HP)) {
		assert.equal(createSim(arena(kind), CHARACTERS.ranger.gear).enemies[0].maxHp, BOSS_HP[kind]);
		const st = duo(kind);
		assert.equal(st.enemies[0].maxHp, BOSS_HP[kind] * COOP_BOSS_HP);
		assert.equal(st.enemies[0].hp, BOSS_HP[kind] * COOP_BOSS_HP);
	}
	assert.equal(COOP_BOSS_HP, 2);
});

test("each hero has their own class, stats and position, and moves on their own input", () => {
	const st = duo("tidewarden", "ninja", "simon");
	assert.deepEqual(st.heroes.map((h) => h.classId), ["ninja", "simon"]);
	assert.equal(st.p, st.heroes[0].p, "hero 0 is the one on the state between ticks");
	assert.notEqual(st.heroes[0].stats, st.heroes[1].stats);
	const [a, b] = st.heroes.map((h) => ({ x: h.p.x, y: h.p.y }));
	assert(Math.abs(a.y - b.y) > 1, "they start apart");
	st.enemies[0].active = false;
	for (let i = 0; i < 30; i++) step(st, { mx: 1, co: { mx: -1, my: 1 } });
	assert(st.heroes[0].p.x > a.x && Math.abs(st.heroes[0].p.y - a.y) < 1e-9, "hero 0 went right");
	assert(st.heroes[1].p.x < b.x && st.heroes[1].p.y > b.y, "hero 1 went down-left");
	assert.equal(st.p, st.heroes[0].p);
	assert.equal(heroView(st, 1).classId, "simon");
	assert.equal(heroView(st, 1).p, st.heroes[1].p);
});

test("each hero's shots are theirs, and each hero's ability is their own", () => {
	const st = duo("tidewarden", "diviner", "paladin");
	st.enemies[0].active = false;
	step(st, { fire: true, ax: 1, ability: true, co: { fire: true, ax: -1, ability: true } });
	const mine = st.bullets.filter((b) => b.vx > 0), theirs = st.bullets.filter((b) => b.vx < 0);
	assert(mine.length && mine.every((b) => b.pi === 0));
	assert(theirs.length && theirs.every((b) => b.pi === 1));
	assert(st.heroes[0].focusZone && !st.heroes[0].slowUntil, "the Diviner placed a zone");
	assert(st.heroes[1].slowUntil > st.tick && !st.heroes[1].focusZone, "the Paladin raised a field");
	assert(st.heroes[0].p.mp < st.heroes[0].stats.maxMp && st.heroes[1].p.mp < st.heroes[1].stats.maxMp);
});

test("the second hero's ability effects expire even while down", () => {
	const st = duo("tidewarden", "ranger", "diviner");
	step(st, { co: { ability: true, ax: 1 } });
	const partner = st.heroes[1];
	assert(partner.focusZone);
	partner.p.dead = true;
	st.tick = partner.focusZone.until - 1;
	step(st, {});
	assert.equal(partner.focusZone, null);
});

/* Run the fight with both heroes standing still (out of each other's way) until
 * `until`, and return what it saw. */
function run(st, until, ticks = 3000) {
	for (let t = 0; t < ticks && st.status === "play"; t++) {
		step(st, {});
		if (until()) return true;
	}
	return false;
}

test("a targeted shell lands on each living hero (the Tidewarden's mortar)", () => {
	const st = duo("tidewarden");
	st.scale.dmg = 0;
	place(st, 0, 5, 4); place(st, 1, 5, 13);
	st.enemies[0].active = true;
	assert(run(st, () => st.mortars.length >= 2));
	const near = (h) => st.mortars.some((m) => Math.abs(m.x - h.p.x) < 1e-9 && Math.abs(m.y - h.p.y) < 1e-9);
	assert(near(st.heroes[0]) && near(st.heroes[1]), "one shell on each hero");
});

test("an aimed fan fires at each hero (the Bellkeeper's clapper), and only at the living", () => {
	const fanned = (dead) => {
		const st = duo("bellkeeper");
		st.scale.dmg = 0;
		place(st, 0, 12.5, 3); place(st, 1, 12.5, 14);   // straight up and straight down from him
		if (dead) { st.heroes[1].p.dead = true; st.heroes[1].p.hp = 0; }
		st.enemies[0].active = true;
		assert(run(st, () => st.bullets.some((b) => b.owner === "e")));
		const up = st.bullets.filter((b) => b.owner === "e" && b.vy < -1).length;
		const down = st.bullets.filter((b) => b.owner === "e" && b.vy > 1).length;
		return [up, down];
	};
	const [up, down] = fanned(false);
	assert(up >= 5 && down >= 5, `a fan each way (${up} up, ${down} down)`);
	const [up2, down2] = fanned(true);
	assert(up2 >= 5 && down2 === 0, `only at the one standing (${up2} up, ${down2} down)`);
});

test("the Pyre's firebombs and crosses mark each hero", () => {
	const st = duo("pyre");
	st.scale.dmg = 0;
	place(st, 0, 4, 4); place(st, 1, 20, 13);
	st.enemies[0].active = true;
	assert(run(st, () => st.mortars.some((m) => m.src === "boss:flame")));
	const flames = st.mortars.filter((m) => m.src === "boss:flame");
	for (const h of st.heroes) assert(flames.some((m) => m.x === h.p.x && m.y === h.p.y), "a flame on each hero");
});

test("one hero down: the fight goes on, they take nothing more; both down ends it", () => {
	const st = duo("tidewarden");
	st.enemies[0].active = true;
	const events = [];
	let t = 0;
	for (; t < 20000 && st.status === "play"; t++) {
		step(st, {});
		events.push(...st.events);
		if (st.heroes.some((h) => h.p.dead) && !events.some((e) => e.type === "checked")) {
			assert.equal(st.status, "play", "one down is not the end");
			const down = st.heroes.find((h) => h.p.dead);
			assert.equal(down.p.hp, 0);
			events.push({ type: "checked" });
		}
	}
	assert.equal(st.status, "dead", "both fell in the end");
	assert(st.heroes.every((h) => h.p.dead && h.p.hp === 0));
	assert.equal(events.filter((e) => e.type === "down").length, 2);
	assert.equal(events.filter((e) => e.type === "death").length, 1);
	assert(events.filter((e) => e.type === "damage").every((e) => e.hero === 0 || e.hero === 1));
});

test("the doors seal only once every standing hero is inside", () => {
	const border = "#".repeat(30);
	const dungeon = {
		id: "shallows", boss_kind: "tidewarden", seed: "coop-seal", width: 30, height: 9, door_y: 4,
		tiles: [border, ...Array(7).fill("#" + ".".repeat(28) + "#"), border],
		rooms: [{ kind: "entrance", x0: 1, x1: 10 }, { kind: "boss", x0: 11, x1: 29 }], start: { x: 5, y: 4.5 },
		enemies: { boss: { type: "boss", room: 1, x: 20, y: 4.5 } }, drops: {}, pickups: [],
	};
	const st = duo("tidewarden", "ranger", "ninja", dungeon);
	place(st, 0, 14, 4.5);
	step(st, {});
	assert.equal(st.sealed, -1, "one inside, one in the entrance: still open");
	place(st, 1, 14, 3.5);
	step(st, {});
	assert.equal(st.sealed, 1);
});

test("the fight is deterministic: the same two inputs give the same fight", () => {
	const play = (twist) => {
		const st = duo("breach", "simon", "ninja");
		st.scale.dmg = 0.2;
		st.enemies[0].active = true;
		for (let t = 0; t < 1500 && st.status === "play"; t++) {
			const a = { mx: t % 90 < 45 ? 1 : -1, fire: true, ax: 1, ay: 0.2, ability: t % 120 === 0 };
			const b = { my: t % 70 < 35 ? 1 : -1, fire: true, ax: -1, ay: -0.3, ability: t % 150 === 0 };
			if (twist && t === 200) b.mx = 1;
			step(st, { ...a, co: b });
		}
		assert.equal(st.status, "play", "still fighting at the end");
		return fingerprint(st);
	};
	assert.equal(play(false), play(false));
	assert.notEqual(play(false), play(true), "the partner's input is in the fight (and in its fingerprint)");
});
