import assert from "node:assert/strict";
import test from "node:test";
import { fingerprint } from "../../../bossrush/sim.js";
import { newRecording, recordInput, simFor, startStage } from "../../../bossrush/replay.js";
import { stepParty } from "../../../bossrush/prediction.js";
import { restoreRun, rowsByStage, terminalOf } from "../../../bossrush/resume.js";

/* A browser that rejoins a co-op fight rebuilds it from the input rows the server kept
 * (coop.py `resume`). The rows ARE the run, so the rebuild must match the live fight
 * exactly: the recording of each boss already beaten, the HP carried forward, and the
 * current boss up to the cut. */

function arena(kind, seed) {
	const border = "#".repeat(24);
	return {
		id: kind, name: kind, boss_name: kind, boss_kind: kind, seed, width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } },
		drops: {}, pickups: [], scale: { hp: 0.01, dmg: 0.05 },
	};
}
const RUN = {
	characters: ["ninja", "paladin"], names: ["Ash", "Birch"],
	stages: [arena("tidewarden", "r1"), arena("pyre", "r2"), arena("breach", "r3")],
};

/* Each hero shoots the boss, then walks to the portal and hero 0 takes it. */
function controls(st, seat) {
	const p = st.heroes[seat].p, boss = st.enemies.find((e) => e.type === "boss" && e.hp > 0);
	if (boss) {                                        // close to two tiles (above / below it), firing
		const dx = boss.x - p.x, dy = boss.y + (seat ? 2 : -2) - p.y;
		return recordInput({ mx: Math.abs(dx) > 0.4 ? Math.sign(dx) : 0, my: Math.abs(dy) > 0.4 ? Math.sign(dy) : 0,
			ax: boss.x - p.x, ay: boss.y - p.y, fire: true, ability: st.tick % 90 === 0 }, false);
	}
	if (!st.portal || seat) return recordInput({ mx: 0, my: 0, ax: 1, ay: 0 }, false);
	const dx = st.portal.x - p.x, dy = st.portal.y - p.y;
	return recordInput({ mx: Math.abs(dx) > 0.3 ? Math.sign(dx) : 0, my: Math.abs(dy) > 0.3 ? Math.sign(dy) : 0,
		ax: 1, ay: 0, enter: Math.hypot(dx, dy) < 1 }, false);
}

/* Play the run live, as a browser would, stopping `cut` ticks into stage `upto`; and
 * the chunks the server would have kept, in uneven message-sized pieces. */
function playLive(upto, cut) {
	const recording = newRecording(RUN.characters[0], RUN.characters.slice(1), RUN.names);
	const chunks = [];
	let low = null, st = null;
	for (let stage = 0; stage <= upto; stage++) {
		const record = startStage(recording, stage, RUN.stages[stage], low ? [...low] : null);
		st = simFor(recording, record);
		const sent = [[], []];
		for (let t = 0; t < 20000; t++) {
			if (stage === upto && t === cut) break;
			const rows = [0, 1].map((seat) => controls(st, seat));
			rows.forEach((row, seat) => sent[seat].push(row));
			record.rows.push(rows.flat());
			stepParty(st, rows);
			if (terminalOf(st, stage === 2)) break;
		}
		assert(stage === upto || st.status === "complete", `stage ${stage} reached its portal (${st.status})`);
		record.end = fingerprint(st);
		low = st.heroes.map((h) => h.p.low);
		// Rows a browser sent past the end of a fight (it samples ahead) are kept too.
		sent.forEach((rows, seat) => rows.push(...[0, 1, 2].map(() => controls(st, seat))));
		sent.forEach((rows, seat) => {
			for (let from = 0, n = 3 + seat; from < rows.length; from += n, n = (n % 7) + 1)
				chunks.push([stage, seat, from, rows.slice(from, from + n)]);
		});
	}
	return { recording, chunks, st, low };
}

test("the rows a rejoining browser is sent rebuild every beaten boss and the current one exactly", () => {
	const live = playLive(1, 100);   // mid-fight on the second boss
	const restored = restoreRun(RUN, { stage: 1, chunks: live.chunks });
	assert(!restored.error, restored.error);
	assert.equal(restored.stage, 1);
	const was = live.recording.stages[0], now = restored.recording.stages[0];
	assert.deepEqual(now.rows, was.rows, "the beaten boss's recording, tick for tick");
	assert.equal(now.end, was.end, "and it ends in the same state");
	assert.deepEqual(restored.low, live.recording.stages[1].low, "the HP carried into the next boss");
	assert(restored.elapsedMs > 0);
	// The current boss: step the kept rows as confirmed ticks, up to the cut.
	const record = startStage(restored.recording, 1, RUN.stages[1], restored.low);
	const st = simFor(restored.recording, record);
	for (let t = 0; t < 100; t++) stepParty(st, restored.rows.map((rows) => rows[t]));
	assert.equal(fingerprint(st), fingerprint(live.st), "the fight on screen is the one the others are in");
	assert.equal(live.st.status, "play");
	assert.equal(restored.rows[0].length, 103, "our own rows continue from the first one never sent");
});

test("chunks are stitched by tick, overlaps and all; a gap is not papered over", () => {
	const by = rowsByStage([[0, 0, 0, [[1], [2]]], [0, 0, 1, [[9], [3]]], [0, 1, 0, [[5]]], [0, 1, 2, [[7]]]], 2);
	assert.deepEqual(by[0][0], [[1], [2], [3]], "an overlap keeps the row already there");
	assert.deepEqual(by[0][1], [[5]], "a chunk past a gap is dropped");
});

test("rows that stop short of an earlier boss's portal are refused, not guessed", () => {
	const live = playLive(1, 10);
	const cut = live.chunks.filter(([stage, , from]) => stage > 0 || from < 40);
	assert.match(restoreRun(RUN, { stage: 1, chunks: cut }).error, /Could not rebuild boss 1/);
});
