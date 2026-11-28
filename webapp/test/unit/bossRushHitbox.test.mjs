import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { HIT_DY, HIT_R } from "../../../bossrush/hitbox.js";
import { PLAYER_R, createSim, step } from "../../../bossrush/sim.js";

// THE HERO'S HITBOX (owner's pick, 2026-11-28): a 0.22 circle 0.10 below the hero's
// position, for every attack. A Null Cantor mine that only crossed the top of the hat
// used to hit, because the whole body (0.32, centred) counted.
function fight(kind) {
	const border = "#".repeat(24);
	const st = createSim({
		id: kind, boss_kind: kind, seed: "hitbox", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 6, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 18, y: 8.5 } },
		drops: {}, pickups: [], objectives: [],
	}, CHARACTERS.ranger.gear, { classId: "ranger" });
	step(st, {});                                   // the seal
	const boss = st.enemies.find((e) => e.type === "boss");
	while (st.tick < boss.startsAt) step(st, {});   // the boss's schedule (and the crypt's marks) start a second later
	return st;
}

// Each attack lands with its edge `gap` tiles ABOVE the hitbox's top (negative: inside it).
const top = (st) => st.p.y + HIT_DY - HIT_R;
const attacks = {
	mine: ["cantor", (st, gap) => st.crypt.marks.push({ kind: "mine", from: st.tick, at: st.tick + 1, x: st.p.x, y: top(st) - gap - 1, r: 1, dmg: 20 })],
	beam: ["cantor", (st, gap) => { const y = top(st) - gap - 0.5;
		st.crypt.marks.push({ kind: "line", from: st.tick, at: st.tick + 1, x: st.p.x - 3, y, tx: st.p.x + 3, ty: y, r: 0.5, dmg: 20 }); }],
	mortar: ["tidewarden", (st, gap) => st.mortars.push({ x: st.p.x, y: top(st) - gap - 1.4, r: 1.4, at: st.tick + 1, d: 1, dmg: 22, burn: 0 })],
	shot: ["tidewarden", (st, gap) => st.bullets.push({ owner: "e", x: st.p.x, y: top(st) - gap - 0.18, vx: 0, vy: 0, dmg: 10, r: 0.18, life: 5, pierce: 0, hit: [] })],
};

test("every attack hits the hitbox and nothing outside it", () => {
	for (const [name, [kind, place]] of Object.entries(attacks)) {
		for (const [gap, hit] of [[-0.04, true], [0.04, false]]) {
			const st = fight(kind), hp = st.p.hp;
			place(st, gap);
			step(st, {}); step(st, {});
			assert.equal(st.p.hp < hp, hit, `${name}, edge ${gap > 0 ? "just above" : "just inside"} the hitbox: ${hit ? "hit" : "safe"}`);
		}
	}
});

test("the hat no longer counts, and the feet still do", () => {
	// An edge 0.25 tiles above the hero's position: inside the old body, outside the hitbox.
	const hat = PLAYER_R - 0.07, st = fight("cantor"), hp = st.p.hp;
	assert(hat < PLAYER_R && hat > HIT_R - HIT_DY, "the case sits between the old body and the new hitbox");
	st.crypt.marks.push({ kind: "mine", from: st.tick, at: st.tick + 1, x: st.p.x, y: st.p.y - hat - 1, r: 1, dmg: 20 });
	step(st, {}); step(st, {});
	assert.equal(st.p.hp, hp, "a mine over the hat misses");
	// The hitbox reaches as low as the old body did: the boots are still the hero.
	assert.equal(HIT_DY + HIT_R, PLAYER_R);
});
