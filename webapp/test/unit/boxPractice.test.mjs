import { test } from "node:test";
import assert from "node:assert/strict";
import { COLORS, CORNERS, press, cornersMatch } from "../../../boxpuzzles/engine.js";
import { generate, shortestLines, motifShare, MIN_DEPTH, MAX_DEPTH, MAX_WAYS, MAX_TROPE }
	from "../../../boxpuzzles/practice.js";

// A seeded PRNG (mulberry32), so a failure here is reproducible.
const seeded = (seed) => () => {
	seed = (seed + 0x6d2b79f5) | 0;
	let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

// The true minimum, by a plain BFS that shares nothing with the generator but press().
function minimum(tiles, target) {
	const seen = new Set([tiles.join()]);
	let layer = [tiles];
	for (let d = 0; layer.length; d++) {
		if (layer.some((t) => cornersMatch(t, target))) return d;
		const next = [];
		for (const t of layer) for (let i = 0; i < 9; i++) {
			const u = press(t, i);
			if (!seen.has(u.join())) { seen.add(u.join()); next.push(u); }
		}
		layer = next;
	}
	return -1;
}

const FILTERS = [[], ["GY"], ["WH", "RD"], ["GY", "BU", "PI"], ["PU", "YE", "GN", "OR"]];

test("a practice box has none of the excluded colours and passes the daily's filters", () => {
	FILTERS.forEach((exclude, n) => {
		const box = generate(exclude, { rng: seeded(n + 1), budget: 20_000 });
		assert.ok(box, `no box for ${exclude}`);
		for (const c of box.tiles) assert.ok(!exclude.includes(c), `${c} on a board excluding ${exclude}`);
		for (const c of box.target) assert.ok(box.tiles.includes(c) && c !== "GY", `target ${c} not on the board`);
		const m = minimum(box.tiles, box.target);
		assert.equal(m, box.minimum);
		assert.ok(m >= MIN_DEPTH && m <= MAX_DEPTH, `minimum ${m}`);
		assert.equal(box.solution.length, m);
		assert.ok(cornersMatch(box.solution.reduce(press, box.tiles), box.target));
		const ways = shortestLines(box.tiles, box.target).length;
		assert.ok(ways >= 1 && ways <= MAX_WAYS, `${ways} shortest lines`);
		assert.ok(motifShare(box.solution) <= MAX_TROPE);
		// every colour matters: graying one out changes the minimum
		for (const c of new Set(box.tiles)) {
			if (c === "GY") continue;
			assert.notEqual(minimum(box.tiles.map((x) => (x === c ? "GY" : x)), box.target), m, `${c} is decoration`);
		}
	});
});

test("a filter that leaves nothing to build a target from fails at once", () => {
	const t0 = Date.now();
	assert.equal(generate(COLORS.slice()), null);
	assert.equal(generate(COLORS.filter((c) => c !== "GY")), null);
	assert.ok(Date.now() - t0 < 100);
});

test("a filter no box can pass gives up at the budget instead of searching forever", () => {
	let clock = 0;
	const box = generate(COLORS.filter((c) => c !== "RD"), { rng: seeded(7), budget: 50, now: () => (clock += 1) });
	assert.equal(box, null);
});

test("motifShare counts one repeated run of presses", () => {
	assert.equal(motifShare([4, 4, 4, 1, 2, 3]), 0.5);
	assert.equal(motifShare([1, 2, 3, 4, 5, 6]), 0);
	assert.equal(motifShare([0, 1, 0, 1, 0, 1]), 1);
	assert.deepEqual(CORNERS, [0, 2, 8, 6]);
});
