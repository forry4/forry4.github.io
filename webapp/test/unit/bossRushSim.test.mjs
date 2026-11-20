import assert from "node:assert/strict";
import test from "node:test";
import { CINDERWAKE_BEATS, createSim, step } from "../../../bossrush/sim.js";

test("Cinderwake alternates damage and lantern phases and opens a portal after the finale", () => {
	const border = "#".repeat(24);
	const dungeon = {
		id: "fen", boss_kind: "cinderwake", seed: "lantern-test", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } },
		drops: {}, pickups: [], scale: { dmg: 0 },
	};
	const st = createSim(dungeon, [{ base_id: "longbow", tier: 3 }]);
	const cue = st.cinderwake;
	const boss = st.enemies[0];
	const fire = () => ({ fire: true, ax: boss.x - st.p.x, ay: boss.y - st.p.y });
	const advance = (until, input = () => ({})) => {
		for (let tick = 0; tick < 2000 && !until(); tick++) step(st, input());
		assert(until(), "the encounter advanced");
	};

	advance(() => cue.age >= 75, fire);
	assert(boss.x < boss.homeX, "the opening boss closes distance");
	assert(cue.progress > cue.age, "shots speed up the damage window");
	assert.equal(boss.hp, boss.maxHp, "the phase meter tracks progress");

	for (const [index, beat] of CINDERWAKE_BEATS.entries()) {
		assert.equal(cue.index, index);
		assert.equal(Boolean(beat.damage), index % 2 === 0);
		if (!beat.damage) {
			st.p.x = 3; st.p.y = 3;
			advance(() => cue.age >= 40);
			assert(st.bullets.some((b) => b.owner === "e"), "the lantern phase fires projectile patterns");
			assert.equal(cue.progress, cue.age, "moving away from the lantern slows progress");
			st.p.x = cue.lantern.x; st.p.y = cue.lantern.y;
			const progress = cue.progress;
			step(st, {});
			assert(cue.lantern.lit && cue.progress - progress > 1);
		}
		advance(() => cue.index > index || !!st.portal);
	}
	assert.equal(boss.hp, 0);
	assert(st.portal);
	assert(!st.bullets.some((b) => b.owner === "e"));
});
