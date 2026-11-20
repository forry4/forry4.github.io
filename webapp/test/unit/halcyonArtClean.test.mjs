/* THE CLEANUP STEP (halcyon/artClean.js), on made-up "generated" pictures shaped like
 * what an image generator really draws: pixel art blown up into big blocks on a grid
 * that wobbles, on a flat green ground. The cleanup must read that back at the
 * generator's own pixel count — crisp, not smeared — on the slot's colors, with one
 * outline. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { image, removeBackground, segments, shrink, dropSpecks, snap, outline, fixOutline, cleanFor, splitFor, targetHeight, readBlocks, blockSize, edgeProfile, oklab } from "../../../halcyon/artClean.js";
import { SLOTS, PALETTE, MASTER, paletteFor, isPlayerHue } from "../../../halcyon/art.js";

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
/* Pixel art `art` blown up the way a generator draws it: block widths cycling through
 * `sizes` (a grid that wobbles), placed at (ox, oy) on a `bg` ground. */
function blockArt(art, { sizes = [18, 17, 19], ox = 40, oy = 30, bg = [0, 255, 0], pad = 40 } = {}) {
	const edges = (n, shift) => { const e = [0]; for (let i = 0; i < n; i++) e.push(e[i] + sizes[(i + shift) % sizes.length]); return e; };
	const xs = edges(art.w, 0), ys = edges(art.h, 1);
	const img = fill(image(ox + xs[art.w] + pad, oy + ys[art.h] + pad), 0, 0, ox + xs[art.w] + pad, oy + ys[art.h] + pad, bg);
	for (let j = 0; j < art.h; j++) for (let i = 0; i < art.w; i++) {
		const c = px(art, i, j);
		if (c[3]) fill(img, ox + xs[i], oy + ys[j], xs[i + 1] - xs[i], ys[j + 1] - ys[j], c.slice(0, 3));
	}
	return img;
}
/* A seeded pattern of `colors`, so a test fails the same way every run. */
function noise(w, h, colors, seed = 7) {
	const art = image(w, h);
	for (let k = 0; k < w * h; k++) { seed = (seed * 1103515245 + 12345) & 0x7fffffff; art.data.set([...colors[seed % colors.length], 255], k * 4); }
	return art;
}
/* A little figure in art pixels: a near-black rim, a body, a pale face. */
function sprite(w = 12, h = 20, body = [200, 60, 50]) {
	const art = fill(image(w, h), 0, 0, w, h, [20, 18, 24]);
	fill(art, 1, 1, w - 2, h - 2, body);
	fill(art, 3, 2, w - 6, 4, [245, 220, 195]);
	fill(art, 2, 9, w - 4, 2, [120, 80, 50]);
	return art;
}
const same = (a, b) => a.w === b.w && a.h === b.h && a.data.every((v, i) => v === b.data[i]);

test("the background is cut from the edges in: a dull one keeps a same-colored patch inside, the green key goes everywhere", () => {
	const dull = figure();
	fill(dull, 0, 0, 300, 40, [120, 120, 120]); fill(dull, 0, 260, 300, 40, [120, 120, 120]);
	fill(dull, 0, 0, 100, 300, [120, 120, 120]); fill(dull, 200, 0, 100, 300, [120, 120, 120]);
	fill(dull, 140, 150, 20, 20, [120, 120, 120]);              // gray INSIDE the body
	const a = removeBackground(dull);
	assert.equal(a.plain, true);
	assert.equal(px(a.img, 5, 5)[3], 0);
	assert.equal(px(a.img, 150, 160)[3], 255, "the inside gray is part of the figure");
	const keyed = figure();
	fill(keyed, 140, 150, 20, 20, [0, 255, 0]);                // green seen through a gap
	const b = removeBackground(keyed);
	assert.equal(px(b.img, 5, 5)[3], 0);
	assert.equal(px(b.img, 150, 160)[3], 0, "the key color is background wherever it is");
	assert.equal(px(b.img, 150, 100)[3], 255);
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

test("a generator's blocks are read back one pixel each, exactly, though its grid wobbles", () => {
	const art = noise(20, 26, [[200, 60, 50], [40, 50, 120], [245, 220, 195], [20, 18, 24], [90, 140, 80]]);
	const img = blockArt(art, { bg: [0, 0, 0] });
	const read = readBlocks(img, { x: 40, y: 30, w: img.w - 80, h: img.h - 70 });
	assert.ok(read, "a grid was found");
	assert.ok(read.block > 17 && read.block < 19, `block ${read.block}`);
	assert.ok(same(read.img, art), "every block came back as its own color");
});

test("the block size is the block, not a multiple of it", () => {
	// Columns drawn in PAIRS for most rows (the first Ranger's cloak): read alone, the
	// columns land on edges best every TWO blocks — the bug that squashed two facings.
	const art = noise(20, 26, [[200, 60, 50], [40, 50, 120], [245, 220, 195], [90, 140, 80]]);
	for (let j = 0; j < 26; j++) if (j % 4) for (let i = 1; i < 20; i += 2) art.data.set(px(art, i - 1, j), (j * 20 + i) * 4);
	const img = blockArt(art, { bg: [0, 0, 0] });
	const box = { x: 40, y: 30, w: img.w - 80, h: img.h - 70 };
	const { P } = blockSize([edgeProfile(img, box, "x"), edgeProfile(img, box, "y")]);
	assert.ok(P > 16.5 && P < 19.5, `block ${P}`);
	assert.ok(same(readBlocks(img, box).img, art));
});

test("no block grid (a smooth picture) is reported, not misread", () => {
	const img = image(200, 200);
	for (let y = 0; y < 200; y++) for (let x = 0; x < 200; x++) img.data.set([x, y, (x + y) >> 1, 255], (y * 200 + x) * 4);
	assert.equal(readBlocks(img, { x: 0, y: 0, w: 200, h: 200 }), null);
});

test("snapping picks the nearest allowed color: an enemy cannot come out cyan, the hero keeps his navy", () => {
	const hue = (hexc) => MASTER.find((c) => c.hex === hexc);
	for (const [color, kind] of [[[40, 200, 230], "cyan"], [[40, 50, 120], "navy"]]) {
		const img = fill(image(1, 1), 0, 0, 1, 1, color);
		const asPlayer = [...colorsOf(snap({ ...img, data: new Uint8ClampedArray(img.data) }, paletteFor("player.ranger")))][0];
		const asEnemy = [...colorsOf(snap({ ...img, data: new Uint8ClampedArray(img.data) }, paletteFor("enemy.chaser")))][0];
		const [, a, b] = oklab(...rgb(asPlayer)), h = (Math.atan2(b, a) * 180 / Math.PI + 360) % 360;
		assert.ok(h > 180 && h < 300 && Math.hypot(a, b) > 0.05, `${kind} as the player came out ${asPlayer} (hue ${h.toFixed(0)})`);
		assert.ok(!isPlayerHue(hue(asEnemy) || { C: 0 }), `${kind} as an enemy came out ${asEnemy}`);
	}
});

test("the outline goes round the outside, once", () => {
	const img = outline(fill(image(5, 5), 2, 2, 1, 1, [255, 0, 0]));
	assert.deepEqual(px(img, 2, 1).slice(0, 3), rgb(PALETTE.outline[0]));
	assert.deepEqual(px(img, 1, 2).slice(0, 3), rgb(PALETTE.outline[0]));
	assert.equal(px(img, 1, 1)[3], 0, "corners stay open");
	assert.deepEqual(px(img, 2, 2), [255, 0, 0, 255]);
});

test("a figure that already has a dark outline keeps its size, the outline just recolored", () => {
	const pad = (art) => { const p = image(art.w + 2, art.h + 2); for (let y = 0; y < art.h; y++) for (let x = 0; x < art.w; x++) p.data.set(px(art, x, y), ((y + 1) * p.w + x + 1) * 4); return p; };
	const drawn = pad(sprite());
	const { img, added } = fixOutline(drawn);
	assert.equal(added, false);
	assert.deepEqual(px(img, 1, 1).slice(0, 3), rgb(PALETTE.outline[0]));
	assert.equal(px(img, 0, 5)[3], 0, "no second ring");
	const bare = pad(fill(image(6, 6), 0, 0, 6, 6, [200, 60, 50]));
	const out = fixOutline(bare);
	assert.equal(out.added, true);
	assert.deepEqual(px(out.img, 0, 3).slice(0, 3), rgb(PALETTE.outline[0]));
});

test("a character keeps the generator's pixels, standing on its frame, on its job's colors", () => {
	const art = sprite();
	const img = blockArt(art);
	const want = targetHeight("enemy.chaser", 20);                     // 19 — and the art is 20 tall: close enough to keep
	const { sheet, facings, native } = cleanFor("enemy.chaser", img, { artPx: 20 });
	assert.equal(facings, 1);
	assert.equal(native, 20);
	assert.ok(Math.abs(native - want) <= want * 0.15);
	assert.deepEqual([sheet.w, sheet.h], [art.w + 2, art.h + 2], "its own size plus one see-through pixel all round");
	let bottom = -1;
	for (let y = 0; y < sheet.h; y++) for (let x = 0; x < sheet.w; x++) if (px(sheet, x, y)[3]) bottom = Math.max(bottom, y);
	assert.equal(bottom, sheet.h - 2, "feet on the row above the frame's last");
	const allowed = new Set(paletteFor("enemy.chaser"));
	for (const c of colorsOf(sheet)) assert.ok(allowed.has(c), c);
	assert.deepEqual([...alphas(sheet)].sort(), [0, 255]);
	// Far off the size it must be: resized by whole pixels, and said so.
	const small = cleanFor("enemy.chaser", img, { artPx: 12 });
	assert.equal(small.sheet.h, targetHeight("enemy.chaser", 12) + 2);
	assert.match(small.notes.join(), /resized to 11/);
});

test("three figures side by side become a class's three facings, and the Ranger keeps its own size", () => {
	const art = image(56, 20);
	for (const [k, body] of [[60, 70, 140], [50, 60, 130], [40, 50, 120]].entries()) {
		const one = sprite(12, 20, body);
		for (let y = 0; y < 20; y++) for (let x = 0; x < 12; x++) art.data.set(px(one, x, y), (y * 56 + k * 22 + x) * 4);
	}
	const { sheet, facings, notes, native } = cleanFor("player.ranger", blockArt(art), { artPx: 40, exact: true });
	assert.equal(facings, 3);
	assert.equal(native, 20, "exact: the Ranger SETS the size, it is never resized");
	assert.deepEqual([sheet.w, sheet.h], [14, 66]);
	assert.deepEqual(notes, []);
	const one = cleanFor("player.ranger", blockArt(sprite()), { exact: true });
	assert.match(one.notes.join(), /found 1 figure, not 3/);
});

test("a tile fills its square at the density, with no holes, on its own rift's colors", () => {
	const art = noise(16, 16, [[170, 155, 120], [190, 180, 145], [80, 140, 150]]);
	const { sheet } = cleanFor("tile.shallows.floor", blockArt(art, { ox: 0, oy: 0, pad: 0 }), { artPx: 16 });
	assert.deepEqual([sheet.w, sheet.h], [16, 16]);
	assert.deepEqual([...alphas(sheet)], [255]);
	const allowed = new Set(paletteFor("tile.shallows.floor"));
	for (const c of colorsOf(sheet)) assert.ok(allowed.has(c), c);
});

test("one picture of several things splits into one per slot, in order", () => {
	const img = fill(image(900, 300), 0, 0, 900, 300, [0, 255, 0]);
	[[220, 70, 60], [240, 140, 60], [200, 70, 140]].forEach((c, k) => fill(img, k * 300 + 100, 60 + k * 10, 100, 180, c));
	const keys = ["enemy.chaser", "enemy.shooter", "enemy.radial"];
	const { parts, plain } = splitFor(keys, img);
	assert.equal(plain, true);
	assert.deepEqual(parts.map(([k]) => k), keys);
	for (const [key, part] of parts) {
		const { sheet, facings } = cleanFor(key, part, { keyed: true });
		assert.equal(facings, 1);
		assert.ok(sheet.w > 2 && sheet.h > 2, key);
	}
	assert.match(splitFor(["enemy.chaser", "enemy.shooter"], img).error, /found 3 separate things, expected 2/);
});

test("the size each thing must be: its height in tiles times the density", () => {
	assert.equal(targetHeight("enemy.chaser", 20), 19);
	assert.equal(targetHeight("enemy.tidewarden", 20), 48);
	assert.equal(targetHeight("player.ranger", 16), 20);
});
