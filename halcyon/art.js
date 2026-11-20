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
	...Object.fromEntries(["shallows", "fracture", "ashen", "town"].flatMap((rift) =>
		["floor", "wall", "wallTop", "rock", "water"].map((part) => [`tile.${rift}.${part}`,
			{ ...TILE, label: part === "wallTop" ? "Wall edge" : part[0].toUpperCase() + part.slice(1),
				group: rift === "town" ? "Town tiles" : `${RIFT_NAMES[rift]} tiles`, rift }]))),
};

/* THE PICTURES THAT EXIST. One line per file in webapp/public/art/halcyon/:
 *   "enemy.chaser": { src: "chaser.png", frames: 4, fps: 8, facings: 3 },
 * w/h/anchor default to the slot's; give them only to override. Empty on purpose
 * until the first approved picture lands — every key draws its shape until then. */
export const MANIFEST = {};

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
		img.src = artBase() + entry.src;
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
