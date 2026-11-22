/* A Boss Rush FILM (owner's ask, 2026-11-21): a run saved as what HAPPENED — the
 * state of the fight on every frame — rather than as the controls that made it.
 *
 * A replay (replay.js) re-runs the game rules on recorded controls, so it plays
 * back right only under the rules it was recorded with, and the rules change most
 * days. A film is drawn back, never re-simulated, so a later rule change cannot
 * move it. Leaderboard runs are kept as films for that reason; a player's own
 * replay right after a run stays a replay (the rules cannot have changed between).
 *
 * The film keeps MORE than today's drawing reads — the whole sim state but its
 * generator and its event list — so a visual added later usually finds its data
 * already in older films.
 *
 * ENCODING. Each frame is a patch against the frame before, and every number is
 * PREDICTED to keep moving the way it moved last frame (a shot in a straight line,
 * a timer counting down, the tick): only the error against that guess is stored,
 * in thousandths, and a correct guess stores nothing. Objects in a list (shots,
 * enemies, fires) are followed by identity, so a shot costs its birth and its
 * death and nothing in between. The encoder applies its own patches with the
 * decoder's code, so both sides predict from the same rounded values and the
 * film decodes to exactly what the encoder saw.
 *
 * Patch nodes:   number  -> correction vs the prediction, in thousandths
 *                [v]     -> replace with v (numbers in it rounded to thousandths)
 *                {k: node, "-": [deleted keys]}       -> an object, key by key
 *                {"@": [ids], "+": [[id, v]], "~": [[id, node]]} -> a list of objects
 */
import { cursor, inputOf, simFor } from "./replay.js";
import { step, TPS } from "./sim.js";

export const FILM_VERSION = 1;
export const FILM_EVERY = 1;                 // ticks per frame: every tick, the live game's own rate
export const FILM_KEYFRAME = 60;             // a full frame every second of film, for seeking
const SKIP = new Set(["rng", "events"]);     // the generator and the tick's event list: never drawn

const q = (v) => Math.round(v * 1000);
export const roundedFrame = (v) => rounded(v);
const round = (v) => (typeof v === "number" ? q(v) / 1000 : v);
const isPlain = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const isList = (v) => Array.isArray(v) && v.length > 0 && v.every(isPlain);
const isNum = (v) => typeof v === "number" && Number.isFinite(v);

/* A deep copy with every number rounded the way the film stores it. */
function rounded(v) {
	if (isNum(v)) return round(v);
	if (Array.isArray(v)) return v.map(rounded);
	if (isPlain(v)) { const o = {}; for (const k in v) if (v[k] !== undefined) o[k] = rounded(v[k]); return o; }
	return v;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const predict = (a, b) => (isNum(b) ? 2 * q(a) - q(b) : q(a));

/* ── decoding: one patch applied to the two frames before it ───────────────── */
/* A new object (or one that was something else last frame) is a patch against {},
 * so its own lists still carry ids. Both sides pick the base by the same rule. */
const baseOf = (a) => (isPlain(a) ? a : {});
/* What a part of the state left out of a patch is: everything in it kept moving as
 * predicted (numbers on their last step, the rest unchanged). */
function predictNode(a, b, ids) {
	if (isNum(a)) return predict(a, b) / 1000;
	if (isList(a)) {
		const older = new Map();
		for (const o of Array.isArray(b) ? b : []) older.set(ids.get(o), o);
		return a.map((o) => { const id = ids.get(o), n = predictNode(o, older.get(id), ids); ids.set(n, id); return n; });
	}
	if (isPlain(a)) {
		const out = {}, older = isPlain(b) ? b : null;
		for (const k in a) out[k] = predictNode(a[k], older?.[k], ids);
		return out;
	}
	return a;
}
function applyNode(node, a, b, ids) {
	if (isNum(node)) return (predict(a, b) + node) / 1000;
	if (Array.isArray(node)) return rounded(node[0]);
	if ("@" in node || "+" in node || "~" in node) return applyList(node, a, b, ids);
	const base = baseOf(a), older = isPlain(a) ? b : null;
	const out = {};
	const gone = new Set(node["-"] || []);
	for (const k in base) {                                // the old keys keep their order
		if (gone.has(k)) continue;
		out[k] = k in node ? applyNode(node[k], base[k], older?.[k], ids) : predictNode(base[k], older?.[k], ids);
	}
	for (const k in node) if (k !== "-" && !(k in base)) out[k] = applyNode(node[k], undefined, undefined, ids);
	return out;
}
function applyList(node, a, b, ids) {
	const prev = new Map(), older = new Map();
	for (const o of Array.isArray(a) ? a : []) prev.set(ids.get(o), o);
	for (const o of Array.isArray(b) ? b : []) older.set(ids.get(o), o);
	const born = new Map((node["+"] || []).map(([id, n]) => [id, n]));
	const changed = new Map((node["~"] || []).map(([id, n]) => [id, n]));
	const order = node["@"] || (Array.isArray(a) ? a.map((o) => ids.get(o)) : []);
	return order.map((id) => {
		let o;
		if (born.has(id)) o = applyNode(born.get(id), {}, null, ids);
		else if (changed.has(id)) o = applyNode(changed.get(id), prev.get(id), older.get(id), ids);
		else o = predictNode(prev.get(id), older.get(id), ids);
		ids.set(o, id);
		return o;
	});
}

/* ── encoding: what has to be stored to get from frame a to the state now ───── */
function encodeNode(cur, a, b, ids, live) {
	if (isNum(cur) && isNum(a)) { const d = q(cur) - predict(a, b); return d === 0 ? undefined : d; }
	if (isList(cur)) return encodeList(cur, Array.isArray(a) ? a : [], b, ids, live);
	if (isPlain(cur)) {
		const base = baseOf(a), older = isPlain(a) ? b : null;
		const out = {}, gone = [];
		for (const k in base) if (cur[k] === undefined) gone.push(k);
		for (const k in cur) {
			if (cur[k] === undefined) continue;
			const n = encodeNode(cur[k], base[k], older?.[k], ids, live);
			if (n !== undefined) out[k] = n;
		}
		if (gone.length) out["-"] = gone;
		if (!isPlain(a)) return out;                        // a new object, even an empty one
		return Object.keys(out).length ? out : undefined;
	}
	if (isNum(cur)) return [round(cur)];
	return a !== undefined && same(rounded(cur), a) ? undefined : [rounded(cur)];   // a copy: the sim mutates its arrays in place
}
function encodeList(cur, a, b, ids, live) {
	const prev = new Map(), older = new Map();
	for (const o of a) prev.set(ids.get(o), o);
	for (const o of Array.isArray(b) ? b : []) older.set(ids.get(o), o);
	const order = cur.map((o) => { if (!live.has(o)) live.set(o, live.next++); return live.get(o); });
	const node = {};
	if (!same(order, a.map((o) => ids.get(o)))) node["@"] = order;
	cur.forEach((o, i) => {
		const id = order[i];
		if (!prev.has(id)) (node["+"] ||= []).push([id, encodeNode(o, {}, null, ids, live)]);
		else { const n = encodeNode(o, prev.get(id), older.get(id), ids, live); if (n !== undefined) (node["~"] ||= []).push([id, n]); }
	});
	if (!Array.isArray(a) || (a.length === 0 && !node["@"])) node["@"] = order;
	return Object.keys(node).length ? node : undefined;
}

/* What a frame keeps of the sim state: all of it but SKIP, plus the aim and the
 * auto-fire flag the page draws from the controls. */
function frameOf(st, row) {
	const f = {};
	for (const k in st) if (!SKIP.has(k)) f[k] = st[k];
	f.aim = row ? { x: row[2], y: row[3] } : null;
	if (row && row.length >= 16) f.aim2 = { x: row[10], y: row[11] };   // co-op: the second hero's
	f.auto = row?.[7] ? 1 : 0;
	return f;
}

/* A film from a replay recording (replay.js): re-runs each fight once, now, under
 * the rules it was played with. Every `yieldEvery` ticks it awaits a macrotask so a
 * long run does not freeze the page. Every FILM_KEYFRAME-th frame is whole (a
 * patch against nothing), so playback can seek without decoding from the start. */
export async function filmRun(recording, { yieldEvery = 600, every = FILM_EVERY, keyframe = FILM_KEYFRAME } = {}) {
	const stages = [], markers = [];
	let offset = 0, ticks = 0;
	const live = new WeakMap(); live.next = 1;
	for (const stage of recording.stages) {
		if (!stage) continue;
		const st = simFor(recording, stage);
		const ids = new WeakMap();
		const frames = [];
		let a = null, b = null, lastHit = null;
		const shoot = (row) => {
			const cur = frameOf(st, row);
			const whole = frames.length % keyframe === 0;
			const node = (whole ? encodeNode(cur, {}, null, ids, live) : encodeNode(cur, a, b, ids, live)) ?? {};
			frames.push(node);
			const decoded = whole ? applyNode(node, {}, null, ids) : applyNode(node, a, b, ids);
			b = whole ? null : a; a = decoded;
		};
		markers.push({ at: offset, kind: "boss", stage: stages.length, label: stage.dungeon.boss_name });
		shoot(null);
		for (let t = 0; t < stage.rows.length; t++) {
			step(st, inputOf(stage.rows[t]));
			const hit = st.lastHit && st.lastHit.tick;
			if (hit != null && hit !== lastHit) markers.push({ at: offset + t + 1, kind: "hit", stage: stages.length });
			lastHit = hit;
			if (st.events.some((e) => e.type === "cleared")) markers.push({ at: offset + t + 1, kind: "kill", stage: stages.length, label: `${stage.dungeon.boss_name} defeated` });
			if (st.status === "dead") markers.push({ at: offset + t + 1, kind: "death", stage: stages.length, label: "Defeated" });
			if ((t + 1) % every === 0 || t + 1 === stage.rows.length) shoot(stage.rows[t]);
			if (++ticks % yieldEvery === 0) await new Promise((r) => setTimeout(r, 0));
		}
		stages.push({ ticks: stage.rows.length, name: stage.dungeon.name, bossName: stage.dungeon.boss_name, frames });
		offset += stage.rows.length;
	}
	return { v: FILM_VERSION, character: recording.character, ...(recording.partner ? { characters: [recording.character, recording.partner], names: recording.names || null } : {}),
		every, keyframe, stages, markers, total: offset };
}

/* ── playback: the same shape replay.js's timeline and cursor have ─────────── */
export function filmTimeline(film) {
	const stages = [];
	let offset = 0;
	film.stages.forEach((s, index) => {
		stages.push({ index, offset, ticks: s.ticks, name: s.name, bossName: s.bossName, film: s });
		offset += s.ticks;
	});
	const recording = film.characters ? { character: film.characters[0], partner: film.characters[1], names: film.names || null } : { character: film.character };
	return { film, recording, stages, markers: film.markers, total: film.total, exact: true };
}

/* Frame `upto` of a stage: from its keyframe forward, reusing the last decode when
 * playback only moved ahead. */
export function decodeFrame(film, s, upto, cache = new Map()) {
	const k = Math.floor(upto / film.keyframe) * film.keyframe;
	let e = cache.get(s);
	if (!e || e.k !== k || e.i > upto) {
		const ids = new WeakMap();
		e = { k, i: k, a: applyNode(s.frames[k], {}, null, ids), b: null, ids };
		cache.set(s, e);
	}
	while (e.i < upto) {
		e.i++;
		const next = applyNode(s.frames[e.i], e.a, e.b, e.ids);
		e.b = e.a; e.a = next;
	}
	return e.a;
}

export function filmCursor(timeline) {
	const cache = new Map();
	const film = timeline.film;
	let si = 0, t = 0, st = null;
	const frameAt = () => {
		const s = timeline.stages[si];
		const i = Math.min(s.film.frames.length - 1, Math.round(t / film.every));
		st = decodeFrame(film, s.film, i, cache);
	};
	const c = {
		get at() { return timeline.stages[si] ? timeline.stages[si].offset + t : 0; },
		get st() { return st; },
		get stage() { return timeline.stages[si]; },
		get stageIndex() { return si; },
		get aim() { return st?.aim || undefined; },
		get aims() { return st?.aim2 ? [st.aim || undefined, st.aim2] : undefined; },
		get auto() { return !!st?.auto; },
		seek(at) {
			at = Math.max(0, Math.min(timeline.total, Math.round(at)));
			for (si = timeline.stages.length - 1; si > 0 && at < timeline.stages[si].offset; si--);
			if (!timeline.stages[si]) return c;
			t = at - timeline.stages[si].offset;
			frameAt();
			return c;
		},
		advance(n = 1) {
			while (n-- > 0) {
				const s = timeline.stages[si];
				if (!s) return c;
				if (t >= s.ticks) { if (si + 1 >= timeline.stages.length) break; si++; t = 0; continue; }
				t++;
				if (t >= s.ticks && si + 1 < timeline.stages.length) { si++; t = 0; }
			}
			frameAt();
			return c;
		},
	};
	return c.seek(0);
}

export const filmSeconds = (film) => film.total / TPS;

/* The right cursor for either kind of timeline (a replay's or a film's). */
export const openCursor = (timeline) => (timeline.film ? filmCursor(timeline) : cursor(timeline));

/* A film is stored and sent gzipped: ~0.1 MB a minute of play. */
export async function packFilm(film) {
	const stream = new Blob([JSON.stringify(film)]).stream().pipeThrough(new CompressionStream("gzip"));
	return new Response(stream).blob();
}
export async function unpackFilm(bytes) {
	const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
	return JSON.parse(await new Response(stream).text());
}
export const canPackFilms = () => typeof CompressionStream !== "undefined" && typeof DecompressionStream !== "undefined";
