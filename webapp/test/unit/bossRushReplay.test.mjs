import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { buildTimeline, cursor, KEYFRAME_EVERY, newRecording, recordInput, stageAt, startStage } from "../../../bossrush/replay.js";
import { createSim, fingerprint, step } from "../../../bossrush/sim.js";

function arena(kind, seed) {
	const border = "#".repeat(24);
	return {
		id: kind, name: kind, boss_kind: kind, boss_name: `The ${kind}`, seed, width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } },
		drops: {}, pickups: [], objectives: [], scale: { dmg: 1 },
	};
}

// Plays a fight the way Encounter does, recording each tick, with made-up controls.
function playRecorded(recording, index, dungeon, ticks, seed) {
	const low = index === 0 ? null : 40;
	const stage = startStage(recording, index, dungeon, low);
	const st = createSim(dungeon, CHARACTERS[recording.character].gear, { classId: recording.character, low });
	let s = seed;
	const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
	for (let t = 0; t < ticks && st.status === "play"; t++) {
		const input = { mx: Math.sign(rnd() - 0.45), my: Math.sign(rnd() - 0.5), ax: rnd() * 6 - 3, ay: rnd() * 6 - 3,
			fire: rnd() < 0.8, ability: rnd() < 0.01, enter: false };
		stage.rows.push(recordInput(input, false));
		step(st, input);
	}
	stage.end = fingerprint(st);
	return st;
}

function recordRun() {
	const recording = newRecording("ranger");
	playRecorded(recording, 0, arena("tidewarden", "a"), 700, 11);
	playRecorded(recording, 1, arena("pyre", "b"), 500, 29);
	return recording;
}

test("a recorded run rebuilds to exactly the fight that was played", () => {
	const timeline = buildTimeline(recordRun());
	assert.equal(timeline.exact, true);
	assert.equal(timeline.stages.length, 2);
	assert.equal(timeline.total, timeline.stages[0].ticks + timeline.stages[1].ticks);
	assert.equal(timeline.stages[1].offset, timeline.stages[0].ticks);
	assert.equal(stageAt(timeline, timeline.stages[1].offset), 1);
	assert.deepEqual(timeline.markers.filter((m) => m.kind === "boss").map((m) => m.at), [0, timeline.stages[0].ticks]);
	assert(timeline.markers.some((m) => m.kind === "hit"), "taking hits leaves markers");
});

test("seeking anywhere lands on the same state as playing through, across fights", () => {
	const timeline = buildTimeline(recordRun());
	const play = cursor(timeline);
	const at = [0, 1, KEYFRAME_EVERY - 1, KEYFRAME_EVERY, 333, timeline.stages[0].ticks - 1, timeline.stages[0].ticks + 5, timeline.total];
	let pos = 0;
	for (const target of at) {
		play.advance(target - pos); pos = target;
		const jump = cursor(timeline).seek(target);
		assert.equal(jump.at, play.at, `position ${target}`);
		assert.equal(fingerprint(jump.st), fingerprint(play.st), `state at ${target}`);
	}
});

test("a replay that does not end as the live fight did says so", () => {
	const recording = recordRun();
	const rows = recording.stages[1].rows;
	for (let t = 10; t < rows.length; t++) rows[t][0] *= -1;   // walked the other way
	assert.equal(buildTimeline(recording).exact, false);
});
