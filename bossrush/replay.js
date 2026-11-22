/* A Boss Rush REPLAY (owner's ask, 2026-11-21): the run is rebuilt, not filmed.
 *
 * The sim is deterministic, so a fight is fully described by where it started
 * (the arena, the character, the HP carried in) and the controls fed to `step` on
 * each tick. `Encounter` records exactly that, one row per tick, and nothing else;
 * the replay steps a fresh sim through the same rows. Pauses never reach the record
 * (a paused run takes no ticks), so they are cut for free.
 *
 * Nothing here is sent anywhere or stored: the record lives on the run's page and
 * is gone when the player leaves it. An export is a video the player saves. */
import { CHARACTERS } from "./loadouts.js";
import { createSim, fingerprint, step } from "./sim.js";

// One row per tick: [mx, my, ax, ay, fire, ability, enter, auto]. The aim is kept
// exact — it is a float the sim reads, and rounding it would change the fight.
// A CO-OP tick is two rows end to end (hero 0's, then hero 1's): sixteen numbers.
export function recordInput(input, auto) {
	return [input.mx, input.my, input.ax, input.ay, input.fire ? 1 : 0, input.ability ? 1 : 0, input.enter ? 1 : 0, auto ? 1 : 0];
}
export function inputOf(row) {
	const input = { mx: row[0], my: row[1], ax: row[2], ay: row[3], fire: !!row[4], ability: !!row[5], enter: !!row[6] };
	if (row.length >= 16) input.co = inputOf(row.slice(8, 16));
	return input;
}

/* A fresh record for one run. `stages[i]` is set when fight i starts, by index, so
 * a remount (React's development double effect) replaces rather than appends.
 * `partner` is the second hero's character in co-op; a co-op stage's `low` is then
 * a pair. */
export function newRecording(character, partner = null, names = null) {
	return partner ? { character, partner, names, stages: [] } : { character, stages: [] };
}
export function startStage(recording, index, dungeon, low) {
	recording.stages[index] = { dungeon, low, rows: [], end: null };
	recording.stages.length = index + 1;
	return recording.stages[index];
}

export const KEYFRAME_EVERY = 60;   // a snapshot each second of play: seeking is instant

/* The fight a recorded stage started from: one hero, or (co-op) two. */
export function simFor(recording, stage) {
	const { character, partner } = recording, low = stage.low;
	if (!partner) return createSim(stage.dungeon, CHARACTERS[character].gear, { classId: character, low });
	return createSim(stage.dungeon, CHARACTERS[character].gear, { classId: character, low: low?.[0] },
		{ gear: CHARACTERS[partner].gear, classId: partner, low: low?.[1] });
}
const freshSim = simFor;

/* Re-runs the whole record once: snapshots for seeking, markers for the scrub bar,
 * and a check that each fight ends exactly as it did live (`stage.end` is the
 * live sim's fingerprint). Positions are global ticks across the run; position
 * `offset + t` is a stage's state after its first `t` rows. */
export function buildTimeline(recording) {
	const stages = [], markers = [];
	let offset = 0, exact = true;
	for (const [index, stage] of recording.stages.entries()) {
		if (!stage) continue;
		const st = freshSim(recording, stage);
		const keyframes = [structuredClone(st)];          // tick 0, even for a fight with no ticks
		let lastHit = null;
		markers.push({ at: offset, kind: "boss", stage: stages.length, label: stage.dungeon.boss_name });
		for (let t = 0; t < stage.rows.length; t++) {
			if (t > 0 && t % KEYFRAME_EVERY === 0) keyframes.push(structuredClone(st));
			step(st, inputOf(stage.rows[t]));
			const hit = st.lastHit && st.lastHit.tick;
			if (hit != null && hit !== lastHit) markers.push({ at: offset + t + 1, kind: "hit", stage: stages.length });
			lastHit = hit;
			if (st.events.some((e) => e.type === "cleared")) markers.push({ at: offset + t + 1, kind: "kill", stage: stages.length, label: `${stage.dungeon.boss_name} defeated` });
			if (st.status === "dead") markers.push({ at: offset + t + 1, kind: "death", stage: stages.length, label: "Defeated" });
		}
		if (stage.end && fingerprint(st) !== stage.end) exact = false;
		stages.push({ index, offset, ticks: stage.rows.length, keyframes, stage, name: stage.dungeon.name, bossName: stage.dungeon.boss_name });
		offset += stage.rows.length;
	}
	return { recording, stages, markers, total: offset, exact };
}

/* Which stage a global position falls in (the last stage owns the very end). */
export function stageAt(timeline, at) {
	const { stages } = timeline;
	for (let i = stages.length - 1; i >= 0; i--) if (at >= stages[i].offset) return i;
	return 0;
}

/* A cursor walks the timeline: `seek` jumps anywhere (from the nearest snapshot),
 * `advance` steps forward, crossing into the next fight when one ends. */
export function cursor(timeline) {
	let si = 0, t = 0, st = null;
	const c = {
		get at() { return timeline.stages[si] ? timeline.stages[si].offset + t : 0; },
		get st() { return st; },
		get stage() { return timeline.stages[si]; },
		get stageIndex() { return si; },
		// The controls held on the tick just played: the aim to draw, auto-fire's label.
		get row() { const s = timeline.stages[si]; return s && t > 0 ? s.stage.rows[t - 1] : null; },
		get aim() { const r = c.row; return r ? { x: r[2], y: r[3] } : undefined; },
		get aims() { const r = c.row; return r && r.length >= 16 ? [{ x: r[2], y: r[3] }, { x: r[10], y: r[11] }] : undefined; },
		get auto() { return !!c.row?.[7]; },
		seek(at) {
			at = Math.max(0, Math.min(timeline.total, Math.round(at)));
			si = stageAt(timeline, at);
			const s = timeline.stages[si];
			if (!s) return c;
			const local = at - s.offset;
			const k = Math.min(s.keyframes.length - 1, Math.floor(local / KEYFRAME_EVERY));
			st = structuredClone(s.keyframes[k]);
			t = k * KEYFRAME_EVERY;
			while (t < local) step(st, inputOf(s.stage.rows[t++]));
			return c;
		},
		advance(n = 1) {
			// A fight's last tick IS the next fight's first position (as `seek` reads it),
			// so the handover happens the moment a fight runs out, costing no tick.
			const next = () => {
				if (t >= timeline.stages[si].ticks && si + 1 < timeline.stages.length) {
					si++; t = 0; st = structuredClone(timeline.stages[si].keyframes[0]);
				}
			};
			next();
			while (n-- > 0) {
				const s = timeline.stages[si];
				if (!s || t >= s.ticks) return c;
				step(st, inputOf(s.stage.rows[t++]));
				next();
			}
			return c;
		},
	};
	return c.seek(0);
}

export function formatClock(ticks, tps = 60) {
	const total = Math.max(0, ticks) / tps;
	const m = Math.floor(total / 60), s = total - m * 60;
	return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
