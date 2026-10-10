// Box Puzzles — PRACTICE: a random box, made in the browser, with no tile of the
// colours the player excluded. A port of the daily generator (boxpuzzles/daily.py),
// with the SAME filters (see its docstring for why each one exists and what was
// measured): a minimum of 8..15, every colour matters, at most MAX_WAYS shortest lines,
// and no trope. Nothing is posted, saved or ranked, so the box needs no secrecy and the
// minimum is simply never shown.
//
// Two differences from the daily, both because nobody is racing: the drawn depth is a
// PREFERENCE (after TRY_EXACT_MS the closest good box found is taken), and the whole
// search has a budget — past it, `generate` returns null and the page tells the player
// to change the filter (owner's call). Excluding a colour keeps it off the STARTING
// board (and so off the targets, which are always colours the board starts with); a
// rule can still make one mid-play (White makes gray, Red makes black).
import { COLORS, CORNERS, press, cornersMatch } from "./engine.js";

export const MIN_DEPTH = 8, MAX_DEPTH = 15;
export const MAX_WAYS = 200;
export const MAX_TROPE = 0.5;
const STATE_CAP = 40_000;
const TRY_EXACT_MS = 1000;
export const BUDGET_MS = 5000;

const ACTIVE = COLORS.filter((c) => c !== "GY");
const key = (t) => t.join("");

// Target shapes, as the four corner colours clockwise from the top-left.
const SHAPES = [
	(a) => [a, a, a, a],         // one colour
	(a, b) => [a, b, a, b],      // diagonal pairs
	(a, b) => [a, a, b, b],      // top / bottom
	(a, b) => [a, b, b, a],      // left / right
];

// Every board `start` reaches -> its depth (the board kept beside it); null past STATE_CAP.
function explore(start) {
	const depth = new Map([[key(start), [0, start]]]);
	const queue = [start];
	for (let q = 0; q < queue.length; q++) {
		const t = queue[q], d = depth.get(key(t))[0] + 1;
		for (let i = 0; i < 9; i++) {
			const u = press(t, i), k = key(u);
			if (depth.has(k)) continue;
			depth.set(k, [d, u]);
			queue.push(u);
			if (depth.size > STATE_CAP) return null;
		}
	}
	return depth;
}

function reachesWithin(start, target, limit) {
	if (cornersMatch(start, target)) return true;
	const seen = new Set([key(start)]);
	let layer = [start];
	for (let n = 0; n < limit; n++) {
		const next = [];
		for (const t of layer) for (let i = 0; i < 9; i++) {
			const u = press(t, i), k = key(u);
			if (seen.has(k)) continue;
			if (cornersMatch(u, target)) return true;
			seen.add(k);
			next.push(u);
		}
		if (!next.length) return false;
		layer = next;
	}
	return false;
}

// The distinct shortest press sequences that solve the box, up to `cap` of them.
export function shortestLines(start, target, cap = MAX_WAYS + 1) {
	if (cornersMatch(start, target)) return [[]];
	const parents = new Map([[key(start), []]]);
	let layer = [start];
	while (layer.length) {
		const next = new Map();
		for (const t of layer) for (let i = 0; i < 9; i++) {
			const u = press(t, i), k = key(u);
			if (parents.has(k)) continue;
			if (!next.has(k)) next.set(k, { board: u, from: [] });
			next.get(k).from.push([key(t), i]);
		}
		for (const [k, v] of next) parents.set(k, v.from);
		const goals = [...next.values()].filter((v) => cornersMatch(v.board, target)).map((v) => key(v.board));
		if (goals.length) {
			const out = [];
			const back = (k, tail) => {
				if (out.length >= cap) return;
				const from = parents.get(k);
				if (!from.length) { out.push(tail.slice().reverse()); return; }
				for (const [t, i] of from) back(t, [...tail, i]);
			};
			for (const g of goals) back(g, []);
			return out;
		}
		layer = [...next.values()].map((v) => v.board);
	}
	return [];
}

// The largest share of `line` covered by one motif (1-4 presses) repeated 3+ times.
export function motifShare(line) {
	const n = line.length;
	let best = 0;
	for (let k = 1; k <= 4; k++) for (let s = 0; s + k <= n; s++) {
		const motif = line.slice(s, s + k).join();
		let occ = 0;
		for (let i = 0; i + k <= n;) {
			if (line.slice(i, i + k).join() === motif) { occ++; i += k; } else i++;
		}
		if (occ >= 3) best = Math.max(best, (occ * k) / n);
	}
	return best;
}

// Each allowed target this board can make -> its minimum, within MIN..MAX_DEPTH.
function targets(tiles, depth) {
	const first = new Map();
	for (const [d, s] of depth.values()) {
		const k = CORNERS.map((c) => s[c]).join("");
		if (!first.has(k) || d < first.get(k)) first.set(k, d);
	}
	const present = [...new Set(tiles)].filter((c) => c !== "GY").sort();
	const out = [];
	for (const a of present) for (const b of present) SHAPES.forEach((shape, i) => {
		if ((i === 0) !== (a === b)) return;
		const t = shape(a, b), m = first.get(t.join(""));
		if (m !== undefined && m >= MIN_DEPTH && m <= MAX_DEPTH) out.push([t, m]);
	});
	return out;
}

// The box's least repetitive shortest line if it passes every filter, else null.
function good(tiles, target, m) {
	for (const c of new Set(tiles)) {
		if (c === "GY") continue;
		const grayed = tiles.map((x) => (x === c ? "GY" : x));
		if (reachesWithin(grayed, target, m) && !reachesWithin(grayed, target, m - 1)) return null;
	}
	const lines = shortestLines(tiles, target);
	if (lines.length < 1 || lines.length > MAX_WAYS) return null;
	let line = lines[0];
	for (const l of lines) if (motifShare(l) < motifShare(line)) line = l;
	return motifShare(line) <= MAX_TROPE ? line : null;
}

const pick = (rng, xs) => xs[Math.floor(rng() * xs.length)];
function sample(rng, xs, k) {
	const a = xs.slice();
	for (let i = a.length - 1; i > 0; i--) {
		const j = Math.floor(rng() * (i + 1));
		[a[i], a[j]] = [a[j], a[i]];
	}
	return a.slice(0, k);
}

// A random board from the allowed colours: the daily's 3-5 colour mix, gray as the
// usual filler, both clipped to what the filter leaves.
function candidate(rng, active, grayOk) {
	const k = Math.min(pick(rng, [3, 4, 4, 5, 5]), active.length + (grayOk ? 1 : 0));
	const gray = grayOk && rng() < 0.6;
	const cols = sample(rng, active, Math.min(active.length, gray ? k - 1 : k));
	if (gray) cols.push("GY");
	return Array.from({ length: 9 }, () => pick(rng, cols));
}

// -> { tiles, target, minimum, solution } | null (no good box inside the budget).
// `exclude` is a list of colour codes; `now` and `rng` are injectable for tests.
export function generate(exclude = [], { rng = Math.random, budget = BUDGET_MS, now = () => Date.now() } = {}) {
	const out = new Set(exclude);
	const active = ACTIVE.filter((c) => !out.has(c));
	if (!active.length) return null;          // nothing a target could be made of
	const grayOk = !out.has("GY");
	const want = MIN_DEPTH + Math.floor(rng() * (MAX_DEPTH - MIN_DEPTH + 1));
	const start = now();
	let best = null;
	for (;;) {
		const elapsed = now() - start;
		if (best && (best.minimum === want || elapsed > TRY_EXACT_MS)) return best;
		if (elapsed > budget) return null;
		const tiles = candidate(rng, active, grayOk);
		const depth = explore(tiles);
		if (!depth) continue;
		const ranked = targets(tiles, depth)
			.sort((x, y) => Math.abs(x[1] - want) - Math.abs(y[1] - want) || (x[0].join() < y[0].join() ? -1 : 1));
		for (const [target, m] of ranked.slice(0, 3)) {
			if (best && Math.abs(m - want) >= Math.abs(best.minimum - want)) break;
			const line = good(tiles, target, m);
			if (line) { best = { tiles, target, minimum: m, solution: line }; break; }
		}
	}
}
