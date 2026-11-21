import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { CINDERWAKE_BEATS, FULL_DRAW_TICKS, SEAL_TICKS, TPS, createSim, step } from "../../../bossrush/sim.js";

function encounter(kind, objectives = [], gear = CHARACTERS.ranger.gear) {
	const border = "#".repeat(24);
	const dungeon = {
		id: kind, boss_kind: kind, seed: "lantern-test", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } },
		drops: {}, pickups: [], objectives, scale: { dmg: 0 },
	};
	return createSim(dungeon, gear);
}

function advance(st, until, input = () => ({})) {
	for (let tick = 0; tick < 2000 && !until(); tick++) step(st, input());
	assert(until(), "the encounter advanced");
}

const aimAt = (st, boss) => ({ fire: true, ax: boss.x - st.p.x, ay: boss.y - st.p.y });

test("Cinderwake requires active damage and lantern uptime to finish every beat", () => {
	const st = encounter("cinderwake");
	const cue = st.cinderwake;
	const boss = st.enemies[0];
	const edge = () => { st.p.x = 2; st.p.y = 2; };

	for (const [index, beat] of CINDERWAKE_BEATS.entries()) {
		assert.equal(cue.index, index);
		assert.equal(Boolean(beat.damage), index % 2 === 0);
		edge();
		advance(st, () => cue.age >= 1_100);
		assert.equal(cue.progress, 0);
		assert.equal(cue.index, index);
		assert.equal(st.portal, null);
		if (!beat.damage) assert(st.mortars.length || st.fires.length, "neglecting the lantern draws flares");
		advance(st, () => cue.index > index || !!st.portal, () => {
			if (beat.damage) {
				st.p.x = boss.x > 4 ? boss.x - 2 : boss.x + 2;
				st.p.y = boss.y;
				return aimAt(st, boss);
			}
			st.p.x = cue.lantern.x;
			st.p.y = cue.lantern.y;
			return {};
		});
	}
	assert.equal(boss.hp, 0);
	assert(st.portal);
	assert(!st.bullets.some((b) => b.owner === "e"));
});

test("Full Draw can be canceled free and uses the aim when the arrow releases", () => {
	const st = encounter("warden");
	step(st, { ability: true });
	assert.equal(st.p.drawUntil, st.tick + FULL_DRAW_TICKS);
	step(st, { mx: 1 });
	assert.equal(st.p.drawUntil, 0);
	assert.equal(st.p.mp, 120);
	step(st, { ability: true, fire: true, ax: 1 });
	advance(st, () => st.tick === st.p.drawUntil - 1, () => ({ fire: true, ax: 1 }));
	assert.equal(st.bullets.length, 0);
	assert.equal(st.p.mp, 120);
	step(st, { fire: true, ay: 1 });
	assert.equal(st.p.mp, 75);
	assert.equal(st.p.drawUntil, 0);
	const [arrow] = st.bullets;
	assert.equal(arrow.dmg, 240);
	assert(Math.abs(arrow.vx) < 0.001 && arrow.vy > 0);
});

test("the Warden's seals warn as they start, retain progress, and deal damage once each", () => {
	const st = encounter("warden", [{ x: 8, y: 8.5 }, { x: 17, y: 5 }, { x: 17, y: 12 }]);
	const [boss] = st.enemies;
	const [first, second, third] = st.seals;
	advance(st, () => first.progress === 1);
	assert(first.volley);
	st.p.y = 11;
	advance(st, () => st.bullets.some((b) => b.src === "boss:seal-volley"));
	assert.equal(first.progress, 1);
	st.p.y = first.y;
	advance(st, () => first.progress === SEAL_TICKS);
	assert.equal(boss.hp, 2700);
	for (const seal of [second, third]) {
		st.p.x = seal.x;
		st.p.y = seal.y;
		advance(st, () => seal.progress === SEAL_TICKS);
	}
	assert.equal(boss.hp, 2100);
	advance(st, () => st.tick > 900);
	assert.equal(boss.hp, 2100);
	st.p.x = 8;
	st.p.y = boss.y;
	advance(st, () => !!st.portal, () => aimAt(st, boss));
});

test("the Bellkeeper's charge can be baited into a bell, opening a seven-second damage window", () => {
	const st = encounter("bellkeeper", [{ x: 5, y: 8.5 }, { x: 19, y: 5.5 }, { x: 19, y: 11.5 }]);
	const [boss] = st.enemies;
	const state = st.bellkeeper;
	st.p.x = 9;
	advance(st, () => state.mode === "windup" && state.until - st.tick === 41, () => aimAt(st, boss));
	assert.equal(boss.hp, 3000, "arrows hit armor before the stun");
	assert.equal(state.dx, -1);
	st.p.y += 2;
	advance(st, () => state.mode === "stunned");
	assert.equal(state.until - st.tick, 7 * TPS);
	assert(state.bells[0].readyAt > state.until);
	advance(st, () => boss.hp < 3000, () => aimAt(st, boss));
	advance(st, () => state.mode === "stalk");
	boss.hp = 1300;
	st.p.x = boss.x;
	st.p.y = 3;
	advance(st, () => state.retry);
	assert.equal(state.mode, "windup");
});
