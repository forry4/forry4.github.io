import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { MORTAR, TPS, createSim, step } from "../../../bossrush/sim.js";

// WHOLE NUMBERS (owner, 2026-11-28): every hit, taken or dealt, is a whole number.
function fight(kind, cls) {
	const border = "#".repeat(24);
	return createSim({
		id: kind, boss_kind: kind, seed: "whole", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 7, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 15, y: 8.5 } },
		drops: {}, pickups: [], objectives: [],
	}, CHARACTERS[cls].gear, { classId: cls });
}

test("a fire tick on the Paladin is a whole 3, not 2.8", () => {
	const st = fight("tidewarden", "paladin");
	assert.equal(st.stats.def, 6, "the Paladin's armor still gives 6");
	step(st, {});
	st.fires.push({ x: st.p.x, y: st.p.y, r: 1, until: st.tick + TPS });
	while (st.tick % MORTAR.burnEvery !== MORTAR.burnEvery - 1) step(st, {});
	const hp = st.p.hp;
	step(st, {});
	assert.equal(Math.round((hp - st.p.hp) * 100) / 100, 3, "7 under 6 Defense floors at 40%, rounded");   // regen is a sliver per tick
});

test("every number a fight shows is whole, for every class", () => {
	let total = 0;
	for (const cls of Object.keys(CHARACTERS)) for (const kind of ["tidewarden", "pyre", "cantor", "warden"]) {
		const st = fight(kind, cls), seen = new WeakSet(), shown = [];
		for (let t = 0; t < TPS * 40 && st.status === "play"; t++) {
			const b = st.enemies.find((e) => e.type === "boss");
			step(st, { fire: true, ability: t % 45 === 0, ax: b.x - st.p.x, ay: b.y - st.p.y, my: Math.sin(t / 40) > 0 ? 0.6 : -0.6 });
			for (const n of st.damageNumbers || []) if (!seen.has(n)) { seen.add(n); shown.push(n.amount); }
		}
		assert(shown.length > 0, `${cls} vs ${kind}: the fight showed numbers`);
		total += shown.length;
		const bad = shown.filter((v) => !Number.isInteger(v));
		assert.deepEqual(bad, [], `${cls} vs ${kind} showed ${bad.join(", ")}`);
	}
	assert(total > 300, `only ${total} numbers in twenty fights`);
});
