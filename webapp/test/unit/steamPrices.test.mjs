// The Steam Filter's price logic (steamfilter/prices.js), plus the shipped price file's shape.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { priceNow, attachPrices, money } from "../../../steamfilter/prices.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const NOW = 1793000000;

test("a full price is just its price", () => {
	assert.deepEqual(priceNow([1499], NOW), { cur: 1499 });
	assert.equal(priceNow(undefined, NOW), null);
});

test("a sale shows only inside its window", () => {
	const sale = [624, 2499, NOW + 3600];
	assert.deepEqual(priceNow(sale, NOW), { cur: 624, reg: 2499, end: NOW + 3600, start: null, off: 75 });
	// Ended: the regular price, never the sale price that is gone.
	assert.deepEqual(priceNow(sale, NOW + 7200), { cur: 2499 });
	// Not started yet (the eShop lists a sale's start).
	assert.deepEqual(priceNow([1274, 1499, NOW + 9e5, NOW + 60], NOW), { cur: 1499 });
	// A Steam discount with no end date runs.
	assert.equal(priceNow([500, 2000], NOW).off, 75);
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
	const ok = (p) => Array.isArray(p) && [1, 2, 3, 4].includes(p.length) && p.every((n) => Number.isInteger(n) && n >= 0)
		&& (p.length === 1 || p[0] < p[1]);
	let steam = 0;
	for (const [id, r] of Object.entries(prices.games)) {
		assert.ok(/^\d+$/.test(id), id);
		if (r.s) { assert.ok(ok(r.s), `${id} s ${JSON.stringify(r.s)}`); steam++; }
		if (r.w) assert.ok(ok(r.w), `${id} w ${JSON.stringify(r.w)}`);
	}
	assert.ok(steam >= 0.95 * games.length, `${steam} of ${games.length} games have a Steam price`);
});
