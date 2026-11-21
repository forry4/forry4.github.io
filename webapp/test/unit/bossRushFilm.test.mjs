import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { decodeFrame, filmCursor, filmRun, filmTimeline, roundedFrame } from "../../../bossrush/film.js";
import { cursor, inputOf, newRecording, recordInput, startStage } from "../../../bossrush/replay.js";
import { createSim, step } from "../../../bossrush/sim.js";

function arena(kind, seed) {
	const border = "#".repeat(24);
	return {
		id: kind, boss_kind: kind, boss_name: `The ${kind}`, name: kind, seed, width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 15.5, y: 8.5 } },
		drops: {}, pickups: [], objectives: [], scale: { dmg: 1 },
	};
}

/* A recording the way the page makes one: a scripted player circling and firing. */
function recordRun(character, ticks = 900) {
	const rec = newRecording(character);
	["tidewarden", "pyre", "tidewarden"].forEach((kind, i) => {
		const dungeon = arena(kind, `film-test-${i}`);
		const st = createSim(dungeon, CHARACTERS[character].gear, { classId: character, low: 100 });
		const stage = startStage(rec, i, dungeon, 100);
		for (let t = 0; t < ticks && st.status === "play"; t++) {
			const b = st.enemies[0];
			const turn = Math.floor(t / 120) % 4;
			const input = { mx: [1, 0, -1, 0][turn], my: [0, 1, 0, -1][turn], ax: b.x - st.p.x, ay: b.y - st.p.y,
				fire: true, ability: t % 75 === 0, enter: false };
			stage.rows.push(recordInput(input, t % 300 < 150));
			step(st, inputOf(stage.rows[t]));
		}
	});
	return rec;
}

const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x)
	? Object.fromEntries(Object.keys(x).sort().map((y) => [y, x[y]])) : x));

test("A film decodes to exactly the fight it was made from, every frame, after a trip through JSON", async () => {
	for (const character of Object.keys(CHARACTERS)) {
		const rec = recordRun(character);
		const film = JSON.parse(JSON.stringify(await filmRun(rec, { yieldEvery: 1e9 })));
		let frames = 0;
		rec.stages.forEach((stage, si) => {
			const st = createSim(stage.dungeon, CHARACTERS[character].gear, { classId: character, low: stage.low });
			const cache = new Map();
			const check = (i, row) => {
				const want = { ...st, aim: row ? { x: row[2], y: row[3] } : null, auto: row?.[7] ? 1 : 0 };
				delete want.rng; delete want.events;
				const got = decodeFrame(film, film.stages[si], i, cache);
				assert.equal(canon(got), canon(roundedFrame(JSON.parse(JSON.stringify(want)))), `${character}: fight ${si + 1}, frame ${i}`);
				frames++;
			};
			check(0, null);
			stage.rows.forEach((row, t) => { step(st, inputOf(row)); check(t + 1, row); });
		});
		assert(frames > 600, `${character}: ${frames} frames checked`);
		assert(film.stages.every((s) => s.frames.length === s.ticks + 1));
	}
});

test("A film plays like the replay it came from: same length, markers, positions and seeks", async () => {
	const rec = recordRun("ranger");
	const film = await filmRun(rec, { yieldEvery: 1e9 });
	const tl = filmTimeline(film);
	const { buildTimeline } = await import("../../../bossrush/replay.js");
	const live = buildTimeline(rec);
	assert.equal(tl.total, live.total);
	assert.deepEqual(tl.markers, live.markers);
	assert.deepEqual(tl.stages.map((s) => [s.offset, s.ticks, s.bossName]), live.stages.map((s) => [s.offset, s.ticks, s.bossName]));
	const a = filmCursor(tl), b = cursor(live);
	const near = (x, y) => Math.abs(x - y) < 0.002;
	for (const at of [0, 1, 59, 60, 61, 400, tl.stages[1].offset - 1, tl.stages[1].offset, tl.stages[2].offset + 7, tl.total]) {
		a.seek(at); b.seek(at);
		assert.equal(a.stageIndex, b.stageIndex, `stage at ${at}`);
		assert(near(a.st.p.x, b.st.p.x) && near(a.st.p.y, b.st.p.y), `hero at ${at}`);
		assert.equal(a.st.bullets.length, b.st.bullets.length, `shots at ${at}`);
		assert.equal(a.st.tick, b.st.tick, `tick at ${at}`);
		if (at > 0 && b.aim) assert(near(a.aim.x, b.aim.x) && a.auto === b.auto, `aim at ${at}`);
	}
	a.seek(0); b.seek(0);
	for (let i = 0; i < tl.total; i += 7) {
		a.advance(7); b.advance(7);
		assert.equal(a.at, b.at);
		assert(near(a.st.p.x, b.st.p.x), `hero after advancing to ${a.at}`);
	}
});

test("A film stores only what it could not predict", async () => {
	const rec = recordRun("ranger");
	const film = await filmRun(rec, { yieldEvery: 1e9 });
	let whole = 0;                                     // every frame's full state, for comparison
	for (const stage of rec.stages) {
		const st = createSim(stage.dungeon, CHARACTERS.ranger.gear, { classId: "ranger", low: stage.low });
		for (const row of stage.rows) { step(st, inputOf(row)); whole += JSON.stringify(st).length; }
	}
	const ratio = JSON.stringify(film).length / whole;
	assert(ratio < 0.1, `the film is ${(ratio * 100).toFixed(1)}% of every full state`);
});
