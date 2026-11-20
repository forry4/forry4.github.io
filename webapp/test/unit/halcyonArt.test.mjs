/* HALCYON'S ART (halcyon/art.js): the slot list covers everything the game draws,
 * the manifest is held to the files on disk, frames are picked right, and a key
 * with no picture leaves the shape in place. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { SLOTS, MANIFEST, sheetOf, frameOf, override, drawSprite, drawTile, checkManifest, sprite } from "../../../halcyon/art.js";
import { ENEMY, BOSS_HP, CLASS_INFO } from "../../../halcyon/sim.js";
import { PALETTES, drawEnemyBody, drawMap } from "../../../halcyon/render.js";

const ART_DIR = new URL("../../public/art/halcyon/", import.meta.url);
/* A PNG's size, off its header; null when there is no such file. */
function pngSize(src) {
	const url = new URL(src, ART_DIR);
	if (!existsSync(url)) return null;
	const b = readFileSync(url);
	assert.equal(b.toString("latin1", 1, 4), "PNG", `${src} is not a PNG`);
	return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

/* A canvas that records what it was asked to do. */
function fakeG() {
	const calls = [];
	const g = new Proxy({ calls }, { get: (t, k) => (k in t ? t[k] : (...a) => calls.push([k, ...a])), set: (t, k, v) => { t[k] = v; return true; } });
	return g;
}

test("every thing the game draws has a slot", () => {
	for (const type of Object.keys(ENEMY)) if (type !== "boss") assert.ok(SLOTS[`enemy.${type}`], `enemy.${type}`);
	for (const kind of Object.keys(BOSS_HP)) assert.ok(SLOTS[`enemy.${kind}`], `enemy.${kind}`);
	for (const c of Object.keys(CLASS_INFO)) assert.ok(SLOTS[`player.${c}`], `player.${c}`);
	for (const rift of [...Object.keys(PALETTES), "town"])
		for (const part of ["floor", "wall", "wallTop", "rock"]) assert.ok(SLOTS[`tile.${rift}.${part}`], `tile.${rift}.${part}`);
	assert.ok(SLOTS["tile.shallows.water"] && SLOTS["tile.town.water"] && SLOTS["tile.fracture.void"]);
	for (const [key, s] of Object.entries(SLOTS)) assert.ok(s.w > 0 && s.h > 0 && s.label && s.group && s.anchor.length === 2, key);
});

test("the manifest matches the files on disk", () => {
	assert.deepEqual(checkManifest(MANIFEST, pngSize), []);
});

test("the manifest check catches a missing file, a wrong size and an unknown slot", () => {
	const sizes = { "a.png": [96, 72], "b.png": [24, 24] };
	const problems = checkManifest({
		"enemy.chaser": { src: "a.png", frames: 4, facings: 3 },     // right: 4x24 by 3x24
		"enemy.kiln": { src: "b.png", frames: 2 },                    // wrong: needs 48 wide
		"enemy.dragon": { src: "b.png" },                             // no such slot
		"shot.enemy": { src: "gone.png" },                            // missing
	}, (src) => sizes[src] || null);
	assert.equal(problems.length, 3, problems.join("\n"));
	assert.match(problems.join("\n"), /enemy\.kiln: b\.png is 24x24, the sheet needs 48x24/);
	assert.match(problems.join("\n"), /enemy\.dragon: no such slot/);
	assert.match(problems.join("\n"), /gone\.png is missing/);
});

test("a sheet's frame: facing picks the row, left mirrors the side row, the clock picks the column", () => {
	const s = sheetOf("enemy.chaser", { src: "x.png", frames: 4, fps: 6, facings: 3 });
	assert.deepEqual([s.w, s.h, s.frames, s.facings], [24, 24, 4, 3]);
	assert.deepEqual(frameOf(s, { facing: { x: 0, y: 1 } }), { sx: 0, sy: 0, flip: false });
	assert.deepEqual(frameOf(s, { facing: { x: 1, y: 0.2 } }), { sx: 0, sy: 24, flip: false });
	assert.deepEqual(frameOf(s, { facing: { x: -1, y: 0.2 } }), { sx: 0, sy: 24, flip: true });
	assert.deepEqual(frameOf(s, { facing: { x: 0.1, y: -1 } }), { sx: 0, sy: 48, flip: false });
	assert.equal(frameOf(s, { tick: 9 }).sx, 0);                      // 6 frames a second: 10 ticks each
	assert.equal(frameOf(s, { tick: 10 }).sx, 24);
	assert.equal(frameOf(s, { tick: 25 }).sx, 48);
	assert.equal(frameOf(s, { tick: 45 }).sx, 0);                     // and round again
	const one = sheetOf("enemy.chaser", { src: "x.png" });
	assert.deepEqual(frameOf(one, { facing: { x: -1, y: 0 }, tick: 99 }), { sx: 0, sy: 0, flip: false });   // a picture that never turns
	const tiles = sheetOf("tile.shallows.floor", { src: "f.png", variants: 3 });
	assert.deepEqual([0, 1, 2, 3, -1].map((seed) => frameOf(tiles, { seed }).sx), [0, 16, 32, 0, 32]);
});

test("no picture, no drawing — and the shape is drawn instead", () => {
	const g = fakeG();
	assert.equal(drawSprite(g, "enemy.chaser", 10, 10, 48), false);
	assert.equal(drawTile(g, "tile.shallows.floor", 0, 0, 48), false);
	assert.equal(g.calls.length, 0);
	drawEnemyBody(g, { tick: 0 }, { type: "chaser", r: ENEMY.chaser.r, flash: 0 }, 50, 50, 48, "#e8573f");
	assert.ok(g.calls.some(([k]) => k === "fillRect"), "the chaser's square");
	assert.ok(!g.calls.some(([k]) => k === "drawImage"));
});

test("a picture in place is drawn at art size, on its anchor, and mirrored facing left", () => {
	const img = { width: 72, height: 72 };
	override("enemy.chaser", img, { frames: 3, facings: 3 });
	try {
		assert.ok(sprite("enemy.chaser"));
		const g = fakeG();
		drawEnemyBody(g, { tick: 0 }, { type: "chaser", r: 0.4, flash: 0 }, 100, 200, 48, "#e8573f", false, { x: -1, y: 0 });
		const draw = g.calls.find(([k]) => k === "drawImage");
		// 48 screen px a tile = 3 per art pixel: a 24-pixel frame is 72 wide, anchor [0.5, 0.7].
		assert.deepEqual(draw.slice(1), [img, 0, 24, 24, 24, -36, -72 * 0.7, 72, 72]);
		assert.ok(g.calls.some(([k, x, y]) => k === "translate" && x === 100 && y === 200));
		assert.ok(g.calls.some(([k, x, y]) => k === "scale" && x === -1 && y === 1), "mirrored");
		assert.ok(!g.calls.some(([k]) => k === "fillRect"), "no shape under the picture");
	} finally { override("enemy.chaser", null); }
	assert.equal(sprite("enemy.chaser"), null);
});

test("the map draws a floor picture in each cell, edge to edge", () => {
	const img = { width: 16, height: 16 };
	override("tile.ashen.floor", img);
	try {
		const g = fakeG(), st = { w: 3, h: 1, tiles: ["..."] };
		drawMap(g, st, 0, 0, 50, 150, 50, PALETTES.ashen);
		const cells = g.calls.filter(([k]) => k === "drawImage").map(([, , , , , , X, , W]) => [X, W]);
		assert.deepEqual(cells, [[0, 50], [50, 50], [100, 50]]);
		const other = fakeG();
		drawMap(other, st, 0, 0, 50, 150, 50, PALETTES.shallows);    // another rift: still its shapes
		assert.ok(!other.calls.some(([k]) => k === "drawImage"));
	} finally { override("tile.ashen.floor", null); }
});

test("every tile a dungeon or the town is built from has a slot", async () => {
	const { readdirSync } = await import("node:fs");
	const { createTown } = await import("../../../halcyon/town.js");
	const PART = { "#": "wall", ".": "floor", o: "rock", "~": "water", x: "void" };
	const dir = new URL("./fixtures/", import.meta.url);
	let seen = 0;
	for (const f of readdirSync(dir).filter((f) => /^halcyon-dungeon-.*\.json$/.test(f))) {
		const d = JSON.parse(readFileSync(new URL(f, dir)));
		const rift = f.includes("fracture") ? "fracture" : f.includes("ashen") ? "ashen" : "shallows";
		for (const row of d.tiles) for (const c of row) {
			assert.ok(PART[c], `${f}: tile ${c}`);
			assert.ok(SLOTS[`tile.${rift}.${PART[c]}`], `${f}: tile.${rift}.${PART[c]}`);
			seen++;
		}
	}
	assert.ok(seen > 1000, "the fixtures were read");
	for (const row of createTown().tiles) for (const c of row) assert.ok(SLOTS[`tile.town.${PART[c]}`], `town: ${c}`);
});

test("every slot is made in exactly one step of the prompt guide, and every prompt carries the style", async () => {
	const { BATCHES, promptFor, STYLE, TILE_STYLE, REFERENCE } = await import("../../../halcyon/artPrompts.js");
	const count = {};
	for (const b of BATCHES) for (const it of b.items) {
		for (const k of it.keys) { assert.ok(SLOTS[k], k); count[k] = (count[k] || 0) + 1; }
		const text = promptFor(it, b);
		assert.ok(text.startsWith(it.tile ? TILE_STYLE : STYLE), it.keys.join());
		assert.equal(text.includes(REFERENCE), !b.anchor && !it.tile, it.keys.join());
		assert.equal(!!it.tile, it.keys.every((k) => k.startsWith("tile.")), it.keys.join());
	}
	assert.deepEqual(Object.keys(SLOTS).filter((k) => count[k] !== 1), []);
});
