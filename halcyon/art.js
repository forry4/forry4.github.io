/* Halcyon Rift's art: the list of pictures the game knows how to use, and a loader
 * that lets the renderer use each one THE MOMENT IT EXISTS (art asset plan §4-§5).
 *
 * Nothing waits for art. Every thing the renderer draws asks `sprite(key)` first and
 * draws its greybox shape when the answer is null — so a picture that is not in
 * MANIFEST, has not finished loading, or failed to load leaves the game exactly as
 * it was. Art arrives one picture at a time, and each one is a manifest line plus a
 * file in `webapp/public/art/halcyon/`.
 *
 * SIZES ARE ART PIXELS, never screen pixels: a tile is ART_PX (16) art pixels wide,
 * so a picture is drawn at `px / ART_PX` screen pixels per art pixel, whatever the
 * window size. A sheet is laid out as
 *   columns = animation frames (or, for a tile, look-alike variants),
 *   rows    = facings, in FACINGS order (one row = it never turns).
 * Facing left is the side row mirrored, so a class needs three facings, not four
 * (art direction §3).
 *
 * `anchor` is the point of the frame that sits ON the thing's position, as a
 * fraction of the frame: [0.5, 0.5] is the middle, [0.5, 0.8] puts the position near
 * the feet, so a character stands on the spot it occupies.
 */
import { MANIFEST } from "./artManifest.js";

export const ART_PX = 16;
export const FACINGS = ["down", "side", "up"];

/* EVERY picture the renderer can ask for, with the frame size the art plan budgets
 * for it. The gallery shows each one, and the art gate holds MANIFEST to it: a
 * picture for a key that is not here would never be drawn. */
export const RIFT_NAMES = { shallows: "The Shallows", fracture: "The Fracture", ashen: "The Ashen Breach", town: "The town" };
const CHAR = { w: 24, h: 24, anchor: [0.5, 0.7] };
const BOSS = { w: 48, h: 48, anchor: [0.5, 0.62] };
const TILE = { w: 16, h: 16, anchor: [0, 0] };
const SHOT = { w: 8, h: 8, anchor: [0.5, 0.5] };
/* The tile kinds each place really has (dungeon.py's and town.js's maps): the
 * Shallows' water, the Fracture's torn floor (void), the town's planters and fountain. */
export const TILE_PARTS = {
	shallows: ["floor", "wall", "wallTop", "rock", "water"],
	fracture: ["floor", "wall", "wallTop", "rock", "void"],
	ashen: ["floor", "wall", "wallTop", "rock"],
	town: ["floor", "wall", "wallTop", "rock", "water"],
};
const TILE_LABEL = { any: { floor: "Floor", wall: "Wall", wallTop: "Wall edge", rock: "Rock", water: "Water", void: "Torn floor" },
	shallows: {}, fracture: { rock: "Pillar" }, ashen: { rock: "Slag rock" }, town: { rock: "Planter", water: "Fountain" } };
export const SLOTS = {
	"player.ranger": { ...CHAR, label: "Ranger", group: "Classes" },
	"player.paladin": { ...CHAR, label: "Paladin", group: "Classes" },
	"player.diviner": { ...CHAR, label: "Diviner", group: "Classes" },
	"player.ninja": { ...CHAR, label: "Ninja", group: "Classes" },
	"enemy.chaser": { ...CHAR, label: "Chaser", group: "The Shallows", rift: "shallows" },
	"enemy.shooter": { ...CHAR, label: "Shooter", group: "The Shallows", rift: "shallows" },
	"enemy.radial": { ...CHAR, label: "Spinner", group: "The Shallows", rift: "shallows" },
	"enemy.tidewarden": { ...BOSS, label: "The Tidewarden", group: "The Shallows", rift: "shallows" },
	"enemy.shard": { ...CHAR, label: "Shard", group: "The Fracture", rift: "fracture" },
	"enemy.splitter": { ...CHAR, label: "Splitter", group: "The Fracture", rift: "fracture" },
	"enemy.splinter": { ...CHAR, w: 16, h: 16, label: "Splinter", group: "The Fracture", rift: "fracture" },
	"enemy.flicker": { ...CHAR, label: "Flicker", group: "The Fracture", rift: "fracture" },
	"enemy.breach": { ...BOSS, label: "The Schism", group: "The Fracture", rift: "fracture" },
	"enemy.cinder": { ...CHAR, label: "Cinder", group: "The Ashen Breach", rift: "ashen" },
	"enemy.kiln": { ...CHAR, label: "Kiln", group: "The Ashen Breach", rift: "ashen" },
	"enemy.smolder": { ...CHAR, label: "Smolder", group: "The Ashen Breach", rift: "ashen" },
	"enemy.pyre": { ...BOSS, label: "The Pyre", group: "The Ashen Breach", rift: "ashen" },
	"shot.player": { ...SHOT, label: "Your shot", group: "Shots" },
	"shot.enemy": { ...SHOT, label: "Enemy shot", group: "Shots" },
	"shot.enemyHeavy": { ...SHOT, label: "Heavy enemy shot", group: "Shots" },
	...Object.fromEntries(Object.entries(TILE_PARTS).flatMap(([rift, parts]) =>
		parts.map((part) => [`tile.${rift}.${part}`,
			{ ...TILE, label: TILE_LABEL[rift][part] || TILE_LABEL.any[part],
				group: rift === "town" ? "Town tiles" : `${RIFT_NAMES[rift]} tiles`, rift }]))),
};

/* THE PICTURES THAT EXIST live in artManifest.js, one line per file in
 * webapp/public/art/halcyon/:
 *   "enemy.chaser": { src: "enemy.chaser.png", v: 1763500000000, frames: 4, fps: 8, facings: 3 },
 * w/h/anchor default to the slot's; give them only to override. `v` changes when the
 * file does, so a browser never keeps the old picture. The gallery's "Use this"
 * writes that file through the dev server; it is plain data so a person can too. */
export { MANIFEST };

/* THE SHARED COLOR LIST (art direction §2.3): every finished picture uses ONLY these,
 * and only the families its job allows (`paletteFor`). That is what makes pictures
 * from different generations look like one game, and it is the color-role rule made
 * mechanical: an enemy cannot come out cyan, a floor cannot come out enemy-red. */
export const PALETTE = {
	outline: ["#14111a"],
	white: ["#f4f6f8"],
	// cloth, leather, skin, steel: low saturation, for bodies of every kind
	neutral: ["#2b3140", "#414a5c", "#606b7f", "#3b2a22", "#5c4232", "#86644a", "#c58f6e", "#e8b896", "#8f97a3", "#c4cad2"],
	// each class's own clothing, muted so it never competes with a danger color
	cloth: ["#3d2f5c", "#5a4785", "#7b68a8", "#2c4a3a", "#3f6b52", "#5f8a6c", "#4a3a26", "#7a6440", "#a08a5c"],
	// the player's accent, its shots and abilities: cyan, blue, white
	player: ["#123e52", "#1d6f86", "#2fb6d0", "#7fe3f0", "#c9f6ff"],
	// every enemy and everything an enemy fires: red, orange, hot magenta, a hot core
	enemy: ["#3a0f1a", "#5a1424", "#a3262f", "#e8573f", "#c8551d", "#ef8a3a", "#ffb347", "#6e1a4a", "#c8458f", "#ff6ac1", "#fff1c2"],
	// pickups and loot: gold and green, never warm red
	loot: ["#7a5a1e", "#e9c25a", "#ffe9a6", "#2f7a3a", "#6fd36a"],
	// each place's ground: always the quietest thing on screen
	env: {
		// daylit sandbars, gray-green rock, shallow water, a faint seam (design §14.4)
		shallows: ["#5e5747", "#7d7460", "#a3987a", "#bfb491", "#d3c9a6", "#4f6058", "#6e7d70", "#918f84", "#3f6a6e", "#5f8f93", "#82aeb0", "#b8d8d0"],
		// dark violet stone over a black void (design §14.4a)
		fracture: ["#0d0a14", "#17131f", "#1f1830", "#2a2338", "#3d3550", "#564a70", "#7a6b99", "#b9a5e6"],
		// charcoal and ash, embers banked low
		ashen: ["#120e0c", "#1a1411", "#231b17", "#372e29", "#4a3f38", "#6b5a50", "#8a7d72", "#7a3a22"],
		// cool flagstone, timber
		town: ["#1c2322", "#2e3836", "#3c4845", "#515b57", "#6a7570", "#8a948f", "#3e2a18", "#58391f", "#7a5534"],
	},
};
/* Which families a slot's picture may use. */
export function paletteFor(key) {
	const slot = SLOTS[key];
	if (!slot) return [];
	const P = PALETTE, [kind, name] = key.split(".");
	if (kind === "tile") return [...P.env[slot.rift]];
	if (kind === "player") return [...P.outline, ...P.white, ...P.neutral, ...P.cloth, ...P.player];
	if (key === "shot.player") return [...P.outline, ...P.white, ...P.player];
	if (kind === "shot") return [...P.outline, ...P.enemy];
	if (slot.h >= 40) return [...P.outline, ...P.neutral, ...P.cloth, ...P.enemy, ...P.env[slot.rift]];   // a boss: free body, danger attacks
	return [...P.outline, ...P.neutral, ...P.enemy];
}

/* The frame layout of one manifest line, with the slot's defaults filled in. */
export function sheetOf(key, entry = MANIFEST[key]) {
	const slot = SLOTS[key];
	if (!slot || !entry) return null;
	return { w: entry.w || slot.w, h: entry.h || slot.h, anchor: entry.anchor || slot.anchor,
		frames: entry.frames || 1, fps: entry.fps || 8, facings: entry.facings || 1, variants: entry.variants || 1, src: entry.src };
}

/* Which frame to show: `facing` is a direction vector (or null), `tick` the sim's
 * clock (60 a second), `seed` picks a tile's variant. Pure, so it is unit-tested. */
export function frameOf(sheet, { facing = null, tick = 0, seed = 0 } = {}) {
	let row = 0, flip = false;
	if (sheet.facings >= 3 && facing && (facing.x || facing.y)) {
		if (Math.abs(facing.x) > Math.abs(facing.y)) { row = 1; flip = facing.x < 0; }
		else row = facing.y < 0 ? 2 : 0;
	}
	const cols = Math.max(sheet.frames, sheet.variants);
	const col = sheet.variants > 1 ? ((seed % cols) + cols) % cols
		: sheet.frames > 1 ? Math.floor(tick * sheet.fps / 60) % sheet.frames : 0;
	return { sx: col * sheet.w, sy: row * sheet.h, flip };
}

/* THE LOADER. `loadArt()` starts every picture in MANIFEST loading (in a browser —
 * under node there is no Image, and nothing loads); `sprite(key)` is the loaded
 * picture and its layout, or null. `override(key, canvas)` puts a picture in place
 * without a file — the gallery uses it to preview a dropped image in the real game. */
const loaded = new Map();
let base = null;
function artBase() {
	if (base === null) base = `${(typeof import.meta !== "undefined" && import.meta.env && import.meta.env.BASE_URL) || "/"}art/halcyon/`;
	return base;
}
export function loadArt(manifest = MANIFEST) {
	if (typeof Image === "undefined") return;
	for (const [key, entry] of Object.entries(manifest)) {
		if (loaded.has(key) || !SLOTS[key]) continue;
		const img = new Image();
		const rec = { img, sheet: sheetOf(key, entry), ready: false };
		img.onload = () => { rec.ready = true; };
		img.src = artBase() + entry.src + (entry.v ? `?v=${entry.v}` : "");
		loaded.set(key, rec);
	}
}
export function sprite(key) {
	const rec = loaded.get(key);
	return rec && rec.ready ? rec : null;
}
export function override(key, image, entry = {}) {
	if (!SLOTS[key]) return;
	if (!image) { loaded.delete(key); return; }
	loaded.set(key, { img: image, sheet: sheetOf(key, { src: "(preview)", ...entry }), ready: true });
}

/* Draw `key` with its anchor on (X, Y), at `px` screen pixels a tile. Returns false
 * (and draws nothing) when the picture is not there, so the caller draws its shape.
 * `rot` turns it (a shot along its flight); `size` scales it (a big enemy). */
export function drawSprite(g, key, X, Y, px, { facing = null, tick = 0, seed = 0, rot = 0, size = 1, alpha = 1 } = {}) {
	const rec = sprite(key);
	if (!rec) return false;
	const s = rec.sheet, k = (px / ART_PX) * size, f = frameOf(s, { facing, tick, seed });
	const W = s.w * k, H = s.h * k;
	g.save();
	g.imageSmoothingEnabled = false;
	if (alpha !== 1) g.globalAlpha *= alpha;
	g.translate(Math.round(X), Math.round(Y));
	if (rot) g.rotate(rot);
	if (f.flip) g.scale(-1, 1);
	g.drawImage(rec.img, f.sx, f.sy, s.w, s.h, -s.anchor[0] * W, -s.anchor[1] * H, W, H);
	g.restore();
	return true;
}

/* A tile picture filling one map cell (anchor ignored: a tile is its cell). */
export function drawTile(g, key, X, Y, W, H = W, seed = 0) {
	const rec = sprite(key);
	if (!rec) return false;
	const s = rec.sheet, f = frameOf(s, { seed });
	g.imageSmoothingEnabled = false;
	g.drawImage(rec.img, f.sx, f.sy, s.w, s.h, X, Y, W, H);
	return true;
}

/* THE ART GATE's rule, kept pure so the unit test can hold the real manifest to it
 * and prove it on made-up ones: every line names a known slot and a file, and the
 * file is exactly its frames wide and its facings tall. `sizeOf(src)` is the file's
 * [width, height], or null when it is missing. */
export function checkManifest(manifest, sizeOf) {
	const problems = [];
	for (const [key, entry] of Object.entries(manifest)) {
		if (!SLOTS[key]) { problems.push(`${key}: no such slot`); continue; }
		if (!entry.src) { problems.push(`${key}: no src`); continue; }
		const size = sizeOf(entry.src);
		if (!size) { problems.push(`${key}: ${entry.src} is missing`); continue; }
		const s = sheetOf(key, entry), want = [s.w * Math.max(s.frames, s.variants), s.h * s.facings];
		if (size[0] !== want[0] || size[1] !== want[1])
			problems.push(`${key}: ${entry.src} is ${size[0]}x${size[1]}, the sheet needs ${want[0]}x${want[1]}`);
	}
	return problems;
}
