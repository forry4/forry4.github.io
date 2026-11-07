// IMDb Filter's logic (imdbfilter/derive.js): the weighted rating, the filters, the
// three-state genre chips and the cell formats — on a small hand-built payload, and
// then the shipped payload's own invariants.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as D from "../../../imdbfilter/derive.js";

const data = {
	bayes: { m: 25000, c: 7 }, genres: ["Drama", "Crime", "Comedy"], names: ["Frank Darabont", "Tim Robbins", "Bryan Cranston"],
	titles: [
		{ i: 111161, n: "The Shawshank Redemption", k: "f", y: 1994, rt: 142, r: 9.3, v: 3000000, g: [0], d: [0], c: [1] },
		{ i: 903747, n: "Breaking Bad", k: "s", y: 2008, ye: 2013, rt: 45, r: 9.5, v: 2200000, g: [1, 0], c: [2], se: 5, ep: 62 },
		{ i: 12345678, n: "Cult Film", o: "Kultfilm", k: "f", y: 2021, r: 9.6, v: 10000, g: [2] },
	],
};
const rows = D.buildRows(data);
const by = (n) => rows.find((r) => r.n === n);

test("buildRows spells out names and genres, pads ids, and builds the search text", () => {
	const s = by("The Shawshank Redemption");
	assert.equal(s.id, "tt0111161");
	assert.equal(by("Cult Film").id, "tt12345678");     // an eight-digit id is left alone
	assert.deepEqual(s.d, ["Frank Darabont"]);
	assert.deepEqual(by("Breaking Bad").g, ["Crime", "Drama"]);
	assert.equal(D.matches(s, "darabont"), true);
	assert.equal(D.matches(by("Cult Film"), "kultf"), true);   // the original title finds it
	assert.equal(D.matches(s, "cranston"), false);
});

test("weighted: IMDb's Top 250 formula pulls a thinly-voted title to the mean", () => {
	assert.equal(D.weighted(9, 25000, { m: 25000, c: 7 }), 8);
	const cult = by("Cult Film"), shaw = by("The Shawshank Redemption");
	assert.ok(cult.r > shaw.r && cult.w < shaw.w, `${cult.w} vs ${shaw.w}`);
	assert.deepEqual(rows.slice().sort(D.sorter("w", -1)).map((r) => r.n),
		["Breaking Bad", "The Shawshank Redemption", "Cult Film"]);
});

test("passes: kinds, years, votes, rating, runtime, genres in and out", () => {
	const s = by("The Shawshank Redemption"), bb = by("Breaking Bad"), cult = by("Cult Film");
	assert.equal(D.passes(s, { kinds: ["s", "m"] }), false);
	assert.equal(D.passes(bb, { kinds: ["s", "m"] }), true);
	assert.equal(D.passes(s, { yfrom: 1995 }), false);
	assert.equal(D.passes(s, { yto: 1994 }), true);
	assert.equal(D.passes(cult, { votes: 25000 }), false);
	assert.equal(D.passes(s, { rating: 9.4 }), false);
	assert.equal(D.passes(s, { rtmax: 120 }), false);
	assert.equal(D.passes(bb, { rtmax: 120 }), true);
	assert.equal(D.passes(cult, { rtmin: 60 }), false);   // no runtime: a bound fails it
	assert.equal(D.passes(cult, {}), true);               // ...and no bound lets it through
	assert.equal(D.passes(bb, { inc: ["Drama", "Crime"] }), true);
	assert.equal(D.passes(s, { inc: ["Drama", "Crime"] }), false);
	assert.equal(D.passes(bb, { exc: ["Crime"] }), false);
	assert.equal(D.passes(s, { exc: ["Crime"] }), true);
});

test("cycleGenre: off -> required -> excluded -> off", () => {
	let st = { inc: [], exc: [] };
	st = D.cycleGenre(st.inc, st.exc, "Horror"); assert.deepEqual(st, { inc: ["Horror"], exc: [] });
	st = D.cycleGenre(st.inc, st.exc, "Horror"); assert.deepEqual(st, { inc: [], exc: ["Horror"] });
	st = D.cycleGenre(st.inc, st.exc, "Horror"); assert.deepEqual(st, { inc: [], exc: [] });
});

test("cells: years, runtime and a series' length", () => {
	assert.equal(D.years(by("Breaking Bad")), "2008–2013");
	assert.equal(D.years({ k: "s", y: 2019 }), "2019–");          // still running
	assert.equal(D.years({ k: "m", y: 2020, ye: 2020 }), "2020");
	assert.equal(D.years(by("The Shawshank Redemption")), "1994");
	assert.equal(D.runtime(142), "2h 22m");
	assert.equal(D.runtime(45), "45m");
	assert.equal(D.runtime(undefined), "—");
	assert.equal(D.length(by("Breaking Bad")), "5 seasons · 62 episodes");
	assert.equal(D.length(by("The Shawshank Redemption")), "");
});

test("sorter: a missing value sorts last either way", () => {
	const r = [{ n: "a", v: 1, rt: null }, { n: "b", v: 1, rt: 90 }, { n: "c", v: 1, rt: 60 }];
	assert.deepEqual(r.slice().sort(D.sorter("rt", -1)).map((x) => x.n), ["b", "c", "a"]);
	assert.deepEqual(r.slice().sort(D.sorter("rt", 1)).map((x) => x.n), ["c", "b", "a"]);
});

test("the shipped payload: interned, floored, and every title rates", () => {
	const here = path.dirname(fileURLToPath(import.meta.url));
	const j = JSON.parse(fs.readFileSync(path.join(here, "..", "..", "public", "data", "imdb-filter.json"), "utf8"));
	assert.ok(j.titles.length >= 8000, `${j.titles.length} titles`);
	assert.equal(j.count, j.titles.length);
	const rs = D.buildRows(j);
	for (const r of rs) {
		assert.ok(r.n && r.v >= j.floor && r.r > 0, `${r.id} missing a title, under the floor or unrated`);
		assert.ok(D.ALL_KINDS.includes(r.k), `${r.id} kind ${r.k}`);
		assert.ok(r.g.every(Boolean) && r.d.every(Boolean) && r.c.every(Boolean), `${r.id} has a dangling index`);
	}
	for (const [id, n] of [["tt0111161", "The Shawshank Redemption"], ["tt0903747", "Breaking Bad"]]) {
		assert.equal(rs.find((r) => r.id === id)?.n, n, `canary ${n}`);
	}
	assert.ok(new Set(rs.map((r) => r.id)).size === rs.length, "duplicate ids");
});
