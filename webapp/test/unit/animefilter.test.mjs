// Anime Filter's logic (animefilter/derive.js): the re-scoring when a site is switched
// off, the filters, and the season view — on a small hand-built payload, and then the
// shipped payload's own invariants.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as D from "../../../animefilter/derive.js";

const scale = { m: [8, 0.5], a: [8, 0.5], k: [8, 1] };
const show = (o) => ({ id: 1, n: "Show", r: null, y: 2013, f: "TV", c: "JP", dm: "Shounen", g: ["Action"], t: [],
	dub: 2, m: 8.5, a: 8.5, k: 9, mv: 100000, p: [], ...o });

test("combined: the z-scores of the chosen sites, on MAL's scale", () => {
	const r = show({});
	assert.equal(D.combined(r, scale), 8 + 1 * 0.5);            // z = +1 on every site
	assert.equal(D.combined({ m: 8, a: 9, k: null }, scale), 8 + 1 * 0.5); // (0 + 2) / 2
	assert.equal(D.combined({ m: 8, a: 9, k: 9 }, scale, ["m"]), 8);       // only MAL counts
	assert.equal(D.combined({ m: null, a: null, k: null }, scale), null);
});

test("passes: dub levels, format, years, genres AND", () => {
	const part = show({ dub: 1 });
	assert.equal(D.passes(part, { dub: "some" }), true);
	assert.equal(D.passes(part, { dub: "full" }), false);
	assert.equal(D.passes(show({ dub: 0 }), { dub: "some" }), false);
	assert.equal(D.passes(show({ f: "Movie" }), { fmt: "series" }), false);
	assert.equal(D.passes(show({ f: "Movie" }), { fmt: "movie" }), true);
	assert.equal(D.passes(show({}), { yfrom: 2014 }), false);
	assert.equal(D.passes(show({ y: null }), { yto: 2020 }), false);
	assert.equal(D.passes(show({}), { genres: ["Action", "Drama"] }), false);
	assert.equal(D.passes(show({ g: ["Drama", "Action"] }), { genres: ["Action", "Drama"] }), true);
	assert.equal(D.passes(show({ c: "CN" }), { jp: true }), false);
});

test("seasonRows: one row per part, scored on its own sites, filtered by its own dub", () => {
	const s = show({ p: [{ id: 10, n: "S1", y: 2013, f: "TV", m: 8.5, a: 8.5, k: 9, d: 2 },
		{ id: 11, n: "S2", y: 2017, f: "TV", m: 7.5, a: 7.5, k: 7, d: 0 }] });
	const rows = D.rescore(D.seasonRows([s]), scale, D.ALL_SITES);
	assert.deepEqual(rows.map((r) => [r.n, r.y, r.dub]), [["S1", 2013, 2], ["S2", 2017, 0]]);
	assert.equal(rows[1].s, 8 - 1 * 0.5);
	assert.equal(D.matches(rows[1], "show"), true);   // its show's name finds it
	assert.equal(D.showRows([s])[0].seasons, 2);
});

test("sorter: a missing value sorts last either way", () => {
	const rows = [{ n: "a", s: null }, { n: "b", s: 2 }, { n: "c", s: 1 }];
	assert.deepEqual(rows.slice().sort(D.sorter("s", -1)).map((r) => r.n), ["b", "c", "a"]);
	assert.deepEqual(rows.slice().sort(D.sorter("s", 1)).map((r) => r.n), ["c", "b", "a"]);
});

test("the shipped payload: ranked, titled, dated, and every show scores", () => {
	const here = path.dirname(fileURLToPath(import.meta.url));
	const j = JSON.parse(fs.readFileSync(path.join(here, "..", "..", "public", "data", "anime-filter.json"), "utf8"));
	assert.ok(j.shows.length >= 400, `${j.shows.length} shows`);
	const rows = D.rescore(D.showRows(j.shows), j.scale, D.ALL_SITES);
	for (const r of rows) {
		assert.ok(r.n && r.y && r.p.length, `${r.id} missing a title, year or parts`);
		assert.ok(r.s != null, `${r.n} has no score`);
		assert.ok(r.p.every((p) => p.y >= r.y || p.y == null), `${r.n} is dated after one of its seasons`);
	}
	// make_data ranks on unrounded scores and ships them to 3 places, so a near-tie can
	// swap by a rounding error; anything more is a real disagreement.
	for (let i = 1; i < rows.length; i++) assert.ok(rows[i - 1].s >= rows[i].s - 2e-3, `${rows[i].n} out of order`);
	assert.ok(rows.some((r) => r.dub === 2) && rows.some((r) => r.dub === 0), "dub flags all one value");
	assert.ok(j.genres.length >= 10 && j.tags.length >= 20, "genre/tag rosters thin");
});
