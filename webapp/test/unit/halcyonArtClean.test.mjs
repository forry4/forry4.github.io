/* THE CLEANUP STEP (halcyon/artClean.js), on made-up "generated" pictures: a figure
 * on a flat green ground comes out the slot's size, on the slot's colors only, in
 * or out, with the one outline round it. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { image, removeBackground, segments, shrink, dropSpecks, snap, outline, cleanFor, splitFor, defaultHeight } from "../../../halcyon/artClean.js";
import { SLOTS, PALETTE, paletteFor } from "../../../halcyon/art.js";

const rgb = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
function fill(img, x0, y0, w, h, [r, g, b], a = 255) {
	for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) { const k = (y * img.w + x) * 4; img.data.set([r, g, b, a], k); }
	return img;
}
const px = (img, x, y) => Array.from(img.data.subarray((y * img.w + x) * 4, (y * img.w + x) * 4 + 4));
const colorsOf = (img) => { const s = new Set(); for (let k = 0; k < img.data.length; k += 4) if (img.data[k + 3]) s.add("#" + [0, 1, 2].map((c) => img.data[k + c].toString(16).padStart(2, "0")).join("")); return s; };
const alphas = (img) => { const s = new Set(); for (let k = 3; k < img.data.length; k += 4) s.add(img.data[k]); return s; };
/* A "generated" figure: dark outline, a red body, a pale face, on flat green. */
function figure(w = 300, h = 300, x = 100, y = 40, bw = 100, bh = 220) {
	const img = fill(image(w, h), 0, 0, w, h, [0, 255, 0]);
	fill(img, x, y, bw, bh, [20, 18, 24]);
	fill(img, x + 8, y + 8, bw - 16, bh - 16, [220, 70, 60]);
	fill(img, x + 30, y + 30, 40, 30, [250, 225, 200]);
	return img;
}

test("the background is cut from the edges in, and a same-colored hole inside is kept", () => {
	const img = figure();
	fill(img, 140, 150, 20, 20, [0, 255, 0]);                  // green INSIDE the body
	const { img: cut, plain } = removeBackground(img);
	assert.equal(plain, true);
	assert.equal(px(cut, 5, 5)[3], 0);
	assert.equal(px(cut, 150, 160)[3], 255, "the inside green is part of the figure");
	assert.equal(px(cut, 150, 100)[3], 255);
});

test("a busy edge is reported, and an already see-through picture is left as it is", () => {
	const img = figure();
	for (let x = 0; x < 300; x++) fill(img, x, 0, 1, 300, [x % 256, (x * 7) % 256, (x * 13) % 256]);
	assert.equal(removeBackground(img).plain, false);
	const clear = fill(image(40, 40), 10, 10, 20, 20, [200, 50, 50]);
	const out = removeBackground(clear);
	assert.equal(out.plain, true);
	assert.deepEqual(px(out.img, 15, 15), [200, 50, 50, 255]);
});

test("separate things are found left to right, crumbs left out", () => {
	const img = image(200, 50);
	fill(img, 10, 10, 30, 30, [255, 0, 0]); fill(img, 80, 10, 30, 30, [255, 0, 0]); fill(img, 150, 10, 30, 30, [255, 0, 0]);
	fill(img, 60, 5, 1, 1, [255, 0, 0]);                       // a crumb
	assert.deepEqual(segments(img).map((s) => [s.x0, s.x1]), [[10, 39], [80, 109], [150, 179]]);
});

test("shrinking averages, and every pixel comes out fully in or out", () => {
	const img = fill(image(40, 40), 0, 0, 20, 40, [255, 255, 255]);
	const out = shrink(img, { x: 0, y: 0, w: 40, h: 40 }, 4, 4);
	assert.deepEqual([...alphas(out)].sort(), [0, 255]);
	assert.equal(px(out, 0, 0)[3], 255);
	assert.equal(px(out, 3, 0)[3], 0);
});

test("specks go, bodies stay", () => {
	const img = fill(fill(image(10, 10), 1, 1, 1, 2, [255, 0, 0]), 5, 5, 3, 3, [255, 0, 0]);
	dropSpecks(img);
	assert.equal(px(img, 1, 1)[3], 0);
	assert.equal(px(img, 6, 6)[3], 255);
});

test("snapping picks the nearest allowed color: an enemy cannot come out cyan", () => {
	const img = fill(image(2, 1), 0, 0, 1, 1, [40, 200, 230]);
	fill(img, 1, 0, 1, 1, [40, 200, 230]);
	const asPlayer = snap({ ...img, data: new Uint8ClampedArray(img.data) }, paletteFor("player.ranger"));
	const asEnemy = snap({ ...img, data: new Uint8ClampedArray(img.data) }, paletteFor("enemy.chaser"));
	assert.ok(PALETTE.player.includes([...colorsOf(asPlayer)][0]), [...colorsOf(asPlayer)][0]);
	assert.ok(!PALETTE.player.includes([...colorsOf(asEnemy)][0]), [...colorsOf(asEnemy)][0]);
});

test("the outline goes round the outside, once", () => {
	const img = outline(fill(image(5, 5), 2, 2, 1, 1, [255, 0, 0]));
	assert.deepEqual(px(img, 2, 1).slice(0, 3), rgb(PALETTE.outline[0]));
	assert.deepEqual(px(img, 1, 2).slice(0, 3), rgb(PALETTE.outline[0]));
	assert.equal(px(img, 1, 1)[3], 0, "corners stay open");
	assert.deepEqual(px(img, 2, 2), [255, 0, 0, 255]);
});

test("a character comes out the slot's size, its height, standing on the frame, on its job's colors", () => {
	for (const key of ["enemy.chaser", "player.ranger"]) {
		const { sheet, facings, notes } = cleanFor(key, figure(), { charH: 18 });
		const slot = SLOTS[key];
		assert.equal(facings, 1);
		assert.deepEqual([sheet.w, sheet.h], [slot.w, slot.h]);
		let top = Infinity, bottom = -1;
		for (let y = 0; y < sheet.h; y++) for (let x = 0; x < sheet.w; x++) if (px(sheet, x, y)[3]) { top = Math.min(top, y); bottom = Math.max(bottom, y); }
		assert.equal(bottom - top + 1, 18 + 2, "18 tall plus the outline above and below");
		assert.equal(bottom, slot.h - 1, "its feet on the frame's bottom row");
		const allowed = new Set(paletteFor(key));
		for (const c of colorsOf(sheet)) assert.ok(allowed.has(c), `${key}: ${c}`);
		assert.deepEqual([...alphas(sheet)].sort(), [0, 255]);
		if (key === "player.ranger") assert.match(notes.join(), /found 1 figure, not 3/);
	}
});

test("three figures side by side become a class's three facings", () => {
	const img = fill(image(900, 300), 0, 0, 900, 300, [0, 255, 0]);
	for (let k = 0; k < 3; k++) { fill(img, k * 300 + 100, 40, 100, 220, [20, 18, 24]); fill(img, k * 300 + 108, 48, 84, 204, [60, 180, 210]); }
	const { sheet, facings, notes } = cleanFor("player.ranger", img);
	assert.equal(facings, 3);
	assert.deepEqual([sheet.w, sheet.h], [24, 72]);
	assert.deepEqual(notes, []);
});

test("a tile fills its square, with no holes, on its own rift's colors", () => {
	const img = fill(fill(image(64, 64), 0, 0, 64, 64, [170, 155, 120]), 0, 0, 32, 32, [80, 140, 150]);
	const { sheet } = cleanFor("tile.shallows.floor", img);
	assert.deepEqual([sheet.w, sheet.h], [16, 16]);
	assert.deepEqual([...alphas(sheet)], [255]);
	for (const c of colorsOf(sheet)) assert.ok(PALETTE.env.shallows.includes(c), c);
});

test("one picture of several things splits into one per slot, in order", () => {
	const img = fill(image(900, 300), 0, 0, 900, 300, [0, 255, 0]);
	[[220, 70, 60], [240, 140, 60], [200, 70, 140]].forEach((c, k) => fill(img, k * 300 + 100, 60 + k * 10, 100, 180, c));
	const keys = ["enemy.chaser", "enemy.shooter", "enemy.radial"];
	const { parts, plain } = splitFor(keys, img);
	assert.equal(plain, true);
	assert.deepEqual(parts.map(([k]) => k), keys);
	for (const [key, part] of parts) {
		const { sheet } = cleanFor(key, part, { keyed: true });
		assert.deepEqual([sheet.w, sheet.h], [SLOTS[key].w, SLOTS[key].h]);
	}
	assert.match(splitFor(["enemy.chaser", "enemy.shooter"], img).error, /found 3 separate things, expected 2/);
});

test("default heights: a character its choice, a boss twice that, a shot its frame", () => {
	assert.equal(defaultHeight("enemy.chaser", 18), 18);
	assert.equal(defaultHeight("enemy.tidewarden", 18), 36);
	assert.equal(defaultHeight("shot.enemy"), 6);
	assert.ok(defaultHeight("enemy.splinter", 20) <= SLOTS["enemy.splinter"].h - 2);
});
