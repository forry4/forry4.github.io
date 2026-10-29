// The Steam Filter's price logic (steamfilter/prices.js), plus the shipped price file's shape.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { priceNow, attachPrices, startedWithin, money, span } from "../../../steamfilter/prices.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const NOW = 1793000000;

test("a full price is just its price", () => {
	assert.deepEqual(priceNow([1499], NOW), { cur: 1499 });
	assert.equal(priceNow(undefined, NOW), null);
});

test("a sale shows only inside its window", () => {
	const sale = [624, 2499, NOW + 3600];
	assert.deepEqual(priceNow(sale, NOW), { cur: 624, reg: 2499, end: NOW + 3600, start: null, before: null, off: 75 });
	// Ended: the regular price, never the sale price that is gone.
	assert.deepEqual(priceNow(sale, NOW + 7200), { cur: 2499 });
	// Not started yet (the eShop lists a sale's start).
	assert.deepEqual(priceNow([1274, 1499, NOW + 9e5, NOW + 60], NOW), { cur: 1499 });
	// A Steam discount with no end date runs.
	assert.equal(priceNow([500, 2000], NOW).off, 75);
});

test("a Steam start at or before tracked_since is 'on or before', not a date", () => {
	const since = NOW - 5 * 86400;
	assert.equal(priceNow([500, 2000, NOW + 9, since], NOW, since).start, null);
	assert.equal(priceNow([500, 2000, NOW + 9, since], NOW, since).before, since);
	assert.equal(priceNow([500, 2000, NOW + 9, since + 60], NOW, since).start, since + 60);
	// an end of 0 is a discount with no end: it runs
	assert.equal(priceNow([500, 2000, 0, NOW - 60], NOW, since).off, 75);
});

test("startedWithin reads the store asked for, and an unknown start is never recent", () => {
	const since = NOW - 10 * 86400;
	const g = {};
	attachPrices([Object.assign(g, { id: 1 })], {
		1: { s: [500, 2000, NOW + 99, NOW - 2 * 86400], w: [900, 1000, NOW + 99, NOW - 6 * 86400] } }, NOW, since);
	assert.equal(startedWithin(g, "steam", NOW, 3), true);
	assert.equal(startedWithin(g, "switch", NOW, 3), false);
	assert.equal(startedWithin(g, "switch", NOW, 7), true);
	assert.equal(startedWithin(g, "either", NOW, 3), true);
	const old = { id: 2 };
	attachPrices([old], { 2: { s: [500, 2000, NOW + 99, since] } }, NOW, since);
	assert.equal(startedWithin(old, "steam", NOW, 14), false);
	const full = { id: 3 };
	attachPrices([full], { 3: { s: [999] } }, NOW, since);
	assert.equal(startedWithin(full, "either", NOW, 14), false);
});

test("span", () => {
	const t = (iso) => Date.parse(iso) / 1000;
	assert.equal(span(t("2026-10-26T20:00:00"), t("2026-10-31T20:00:00")), "Oct 26–31");
	assert.equal(span(t("2026-10-26T20:00:00"), t("2026-11-01T20:00:00")), "Oct 26–Nov 1");
});

test("attachPrices fills both stores and leaves missing ones null", () => {
	const games = [{ id: 1 }, { id: 2 }];
	attachPrices(games, { 1: { s: [999], w: [624, 2499, NOW + 1], w2: 1 } }, NOW);
	assert.equal(games[0].sp, 999);
	assert.equal(games[0].wp, 624);
	assert.equal(games[0].w2, 1);
	assert.deepEqual([games[1].sp, games[1].wp, games[1].w2], [null, null, 0]);
	attachPrices(games, null, NOW);   // the price file never loaded
	assert.equal(games[0].sp, null);
});

test("money", () => {
	assert.equal(money(0), "Free");
	assert.equal(money(624), "$6.24");
	assert.equal(money(2500), "$25.00");
});

test("the shipped price file covers the payload and holds well-formed entries", () => {
	const prices = JSON.parse(readFileSync(path.join(root, "webapp", "public", "data", "steam-prices.json"), "utf8"));
	const games = JSON.parse(readFileSync(path.join(root, "webapp", "public", "data", "steam-filter.json"), "utf8")).games;
	assert.match(prices.priced, /^\d{4}-\d\d-\d\dT\d\d:\d\dZ$/);
	assert.ok(Number.isInteger(prices.tracked_since) && prices.tracked_since > 1.7e9, String(prices.tracked_since));
	const ok = (p) => Array.isArray(p) && [1, 2, 3, 4].includes(p.length) && p.every((n) => Number.isInteger(n) && n >= 0)
		&& (p.length === 1 || p[0] < p[1]);
	let steam = 0;
	for (const [id, r] of Object.entries(prices.games)) {
		assert.ok(/^\d+$/.test(id), id);
		if (r.s) { assert.ok(ok(r.s), `${id} s ${JSON.stringify(r.s)}`); steam++; }
		// every Steam sale carries a start, no earlier than tracking began
		if (r.s && r.s.length > 1) assert.ok(r.s.length === 4 && r.s[3] >= prices.tracked_since, `${id} s ${JSON.stringify(r.s)}`);
		if (r.w) assert.ok(ok(r.w), `${id} w ${JSON.stringify(r.w)}`);
	}
	assert.ok(steam >= 0.95 * games.length, `${steam} of ${games.length} games have a Steam price`);
});
