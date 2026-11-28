/* REJOINING A CO-OP FIGHT (2026-11-28). A browser that reconnects mid-run gets every
 * input row the server relayed (coop.py `resume`): `[stage, seat, from, rows]` chunks,
 * contiguous from tick 0 per stage and seat. The fight is deterministic, so those rows
 * ARE the run: replaying them rebuilds the recording of each boss already beaten (and
 * so the HP each hero carried into the next), and the current boss up to the last tick
 * every seat's row reached. `restoreRun` does the first part; the encounter preloads
 * `rows` for the second and steps them as confirmed ticks. */
import { fingerprint, TPS } from "./sim.js";
import { newRecording, simFor, startStage } from "./replay.js";
import { stepParty } from "./prediction.js";

/* chunks -> byStage[stage][seat] = rows by tick (contiguous from 0). */
export function rowsByStage(chunks, seats) {
	const byStage = [];
	for (const [stage, seat, from, rows] of chunks) {
		const forStage = (byStage[stage] ||= Array.from({ length: seats }, () => []));
		const list = forStage[seat];
		if (!list || from > list.length) continue;          // the server keeps them contiguous
		rows.forEach((row, i) => { if (from + i >= list.length) list.push(row); });
	}
	return byStage;
}

/* How a confirmed tick ends a stage (as CoopEncounter.confirm reads it). */
export function terminalOf(st, final) {
	if (st.status === "dead") return "dead";
	if (st.status === "complete") return "advance";
	if (final && st.events.some((e) => e.type === "cleared")) return "won";
	return null;
}

/* Replay the bosses before `resume.stage`. Returns the recording with those stages in
 * place, the HP each hero carries into the current boss, the time the earlier fights
 * took (by ticks, from each room's seal to its portal), and the current stage's rows —
 * or `{ error }` when the rows do not reach the end of an earlier fight. */
export function restoreRun(run, resume) {
	const seats = run.characters.length;
	const byStage = rowsByStage(resume.chunks || [], seats);
	const recording = newRecording(run.characters[0], run.characters.slice(1), run.names);
	let low = null, elapsedMs = 0;
	for (let stage = 0; stage < resume.stage; stage++) {
		const rows = byStage[stage] || [];
		const record = startStage(recording, stage, run.stages[stage], low ? [...low] : null);
		const st = simFor(recording, record);
		let sealed = null, end = null;
		for (let t = 0; rows.every((list) => list && t < list.length); t++) {
			const tick = rows.map((list) => list[t]);
			record.rows.push(tick.flat());
			stepParty(st, tick);
			if (sealed === null && st.events.some((e) => e.type === "seal")) sealed = t + 1;
			if ((end = terminalOf(st, stage === run.stages.length - 1))) break;
		}
		if (end !== "advance") return { error: `Could not rebuild boss ${stage + 1} of the run.` };
		record.end = fingerprint(st);
		low = st.heroes.map((h) => h.p.low);
		elapsedMs += Math.max(0, record.rows.length - (sealed ?? 0)) * 1000 / TPS;
	}
	recording.stages.length = resume.stage;
	return { recording, low, elapsedMs, stage: resume.stage,
		rows: byStage[resume.stage] || Array.from({ length: seats }, () => []) };
}
