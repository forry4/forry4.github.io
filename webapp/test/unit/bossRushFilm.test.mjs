import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { decodeFrame, filmCursor, filmRun, filmTimeline, roundedFrame } from "../../../bossrush/film.js";
import { buildTimeline, cursor, inputOf, newRecording, recordInput, simFor, startStage } from "../../../bossrush/replay.js";
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

test("a four-player replay and film keep each hero's controls and aim", async () => {
	const names = ["Ash", "Birch", "Cedar", "Dune"];
	const rec = newRecording("ranger", ["paladin", "diviner", "simon"], names);
	const stage = startStage(rec, 0, arena("cantor", "four"), null);
	const start = simFor(rec, stage);
	const rows = [[0.8, 0.6, 1, 0], [0, 1, 0, 1], [-1, 0, -1, 0], [0, -1, 0, -1]]
		.flatMap(row => [...row, 0, 0, 0, 0]);
	const straight = simFor(rec, stage);
	for (let i = 0; i < 8; i++) {
		stage.rows.push(rows);
		step(straight, inputOf([1, 0, ...rows.slice(2)]));
	}
	const replay = cursor(buildTimeline(rec)).seek(8);
	const initial = start.p, moved = replay.st.p;
	const dx = moved.x - initial.x, dy = moved.y - initial.y;
	assert(Math.abs(dy / dx - 0.75) < 1e-10, "replay preserves the analog angle");
	assert(Math.abs(Math.hypot(dx, dy) - (straight.p.x - initial.x)) < 1e-10, "analog and keyboard travel at the same speed");
	const film = await filmRun(rec);
	const playback = filmCursor(filmTimeline(film)).seek(8);
	assert.deepEqual(film.names, names);
	assert.deepEqual(film.characters, rec.characters);
	assert.equal(playback.st.heroes.length, 4);
	assert.equal(playback.st.enemies[0].maxHp, 15680);
	assert.deepEqual(playback.aims, replay.aims);
	for (let i = 0; i < 4; i++) {
		const p = playback.st.heroes[i].p, initial = start.heroes[i].p;
		assert(Math.abs(p.x - replay.st.heroes[i].p.x) < 0.001);
		assert.equal(Math.sign(p.x - initial.x), Math.sign(rows[i * 8]));
		assert.equal(Math.sign(p.y - initial.y), Math.sign(rows[i * 8 + 1]));
	}
});

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

test("A video's setup block is rebuilt from the first frame, not Firefox's broken copy", async () => {
	const { avcSetupFrom } = await import("../../../bossrush/replayExport.js");
	// Firefox's first keyframe, measured: an access delimiter, the SPS, the PPS, then the picture.
	const units = ["09 10", "67 64 00 1f ac 2c ac 05 00 5b a1 00 00 03 00 01 00 00 03 00 3c 0d a0 88 45 38", "68 ce 3c 30", "65 88 80 40"]
		.map((h) => Uint8Array.from(h.split(" ").map((x) => parseInt(x, 16))));
	const frame = new Uint8Array(units.reduce((n, u) => n + 4 + u.length, 0));
	let o = 0;
	for (const u of units) { new DataView(frame.buffer).setUint32(o, u.length); frame.set(u, o + 4); o += 4 + u.length; }
	const hex = (a) => Array.from(a, (x) => x.toString(16).padStart(2, "0")).join(" ");
	// What Windows decodes (checked with its own transcoder): one SPS and one PPS, each
	// exactly as the frame carries it, and the High profile's 4:2:0 8-bit tail.
	assert.equal(hex(avcSetupFrom(frame)),
		"01 64 00 1f ff e1 00 1a 67 64 00 1f ac 2c ac 05 00 5b a1 00 00 03 00 01 00 00 03 00 3c 0d a0 88 45 38 01 00 04 68 ce 3c 30 fd f8 f8 00");
	assert.equal(avcSetupFrom(frame.subarray(0, 6 + 4 + 26)), null, "no PPS: keep the encoder's own block");
});
