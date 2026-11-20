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
import { ART } from "./artManifest.js";

/* ART PIXELS PER TILE — the one density every picture shares. It is not chosen in
 * the abstract: the approved Ranger is kept at the generator's own pixel count, and
 * this is set so the Ranger stands the chosen height (studio: "Character height"),
 * so every later picture is matched to the Ranger rather than the Ranger squeezed
 * into a guessed number. `setArtPx` is the studio's live preview of a new choice. */
export const ART_PX = 16;
let artPxNow = ART.artPx || ART_PX;
export const artPx = () => artPxNow;
export function setArtPx(n) { if (n > 0) artPxNow = n; }
export const FACINGS = ["down", "side", "up"];

/* EVERY picture the renderer can ask for, with the frame size the art plan budgets
 * for it. The gallery shows each one, and the art gate holds MANIFEST to it: a
 * picture for a key that is not here would never be drawn. */
export const RIFT_NAMES = { shallows: "The Shallows", fracture: "The Fracture", ashen: "The Ashen Breach", town: "The town" };
/* `tall` is how tall the thing stands on screen, in tiles (a shot: its length);
 * `foot` how far below its position its feet sit, in tiles. w/h are only the frame
 * a picture with no size of its own would use (a hand-made sheet, a test). */
const CHAR = { w: 24, h: 24, tall: 1.0, foot: 0.3 };
const BOSS = { w: 48, h: 48, tall: 2.4, foot: 0.7 };
const TILE = { w: 16, h: 16, tall: 1, anchor: [0, 0] };
const SHOT = { w: 8, h: 8, tall: 0.45, anchor: [0.5, 0.5], group: "Shots" };
const TOWN_PROP = { w: 32, h: 28, tall: 1.55, anchor: [0.5, 0.5], group: "Town props", rift: "town" };
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
/* DECORATIONS (2026-11-19, after the owner's reference room): four per place, placed
 * by the renderer (render.decorations) — a LIGHT and a HANGING on the walls that face
 * into a room, a GROWTH in its corners, a SCATTER on open floor. Each is one connected
 * object, so a place's four can be drawn in one picture and cut apart. The anchor is
 * the point that sits on the spot the renderer picks: a hanging hangs from its top, a
 * growth stands on its foot. */
const DECO = { w: 16, h: 16, foot: 0 };
export const DECO_PARTS = {
	light: { tall: 0.85, anchor: [0.5, 0.5], label: "Wall light" },
	hang: { tall: 1.0, anchor: [0.5, 0], label: "Wall hanging" },
	growth: { tall: 0.7, anchor: [0.5, 1], label: "Corner growth" },
	scatter: { tall: 0.35, anchor: [0.5, 0.5], label: "Floor scatter" },
};
const DECO_LABEL = {
	shallows: { light: "Lantern", hang: "Kelp", growth: "Reeds", scatter: "Shells" },
	fracture: { light: "Flame sconce", hang: "Torn banner", growth: "Corner ivy", scatter: "Rubble" },
	ashen: { light: "Brazier", hang: "Chains", growth: "Dead thorns", scatter: "Slag" },
	town: { light: "Lantern", hang: "Banner", growth: "Ivy", scatter: "Slate chips" },
};
export const SLOTS = {
	"player.ranger": { ...CHAR, tall: 1.25, label: "Ranger", group: "Classes" },
	"player.paladin": { ...CHAR, tall: 1.25, label: "Paladin", group: "Classes" },
	"player.diviner": { ...CHAR, tall: 1.25, label: "Diviner", group: "Classes" },
	"player.ninja": { ...CHAR, tall: 1.25, label: "Ninja", group: "Classes" },
	"enemy.chaser": { ...CHAR, tall: 0.95, label: "Chaser", group: "The Shallows", rift: "shallows" },
	"enemy.shooter": { ...CHAR, tall: 1.1, label: "Shooter", group: "The Shallows", rift: "shallows" },
	"enemy.radial": { ...CHAR, label: "Spinner", group: "The Shallows", rift: "shallows" },
	"enemy.tidewarden": { ...BOSS, label: "The Tidewarden", group: "The Shallows", rift: "shallows" },
	"enemy.shard": { ...CHAR, label: "Shard", group: "The Fracture", rift: "fracture" },
	"enemy.splitter": { ...CHAR, tall: 1.1, label: "Splitter", group: "The Fracture", rift: "fracture" },
	"enemy.splinter": { ...CHAR, w: 16, h: 16, tall: 0.6, foot: 0.2, label: "Splinter", group: "The Fracture", rift: "fracture" },
	"enemy.flicker": { ...CHAR, label: "Flicker", group: "The Fracture", rift: "fracture" },
	"enemy.breach": { ...BOSS, label: "The Schism", group: "The Fracture", rift: "fracture" },
	"enemy.cinder": { ...CHAR, tall: 0.95, label: "Cinder", group: "The Ashen Breach", rift: "ashen" },
	"enemy.kiln": { ...CHAR, tall: 1.05, label: "Kiln", group: "The Ashen Breach", rift: "ashen" },
	"enemy.smolder": { ...CHAR, tall: 0.95, label: "Smolder", group: "The Ashen Breach", rift: "ashen" },
	"enemy.pyre": { ...BOSS, label: "The Pyre", group: "The Ashen Breach", rift: "ashen" },
	"shot.player": { ...SHOT, tall: 0.75, label: "Arrow" },
	"shot.bolt": { ...SHOT, label: "Magic bolt" },
	"shot.slash": { ...SHOT, tall: 0.9, label: "Melee wave" },
	"shot.star": { ...SHOT, label: "Shuriken" },
	"shot.blade": { ...SHOT, tall: 0.7, label: "Throwing blade" },
	"shot.gale": { ...SHOT, tall: 1.0, label: "Gale arrow" },
	"shot.flare": { ...SHOT, tall: 0.8, label: "Blue flare" },
	"shot.power": { ...SHOT, tall: 0.8, label: "Empowered shot" },
	"shot.enemy": { ...SHOT, label: "Enemy shot" },
	"shot.enemyHeavy": { ...SHOT, tall: 0.6, label: "Heavy enemy shot" },
	"shot.enemyShard": { ...SHOT, tall: 0.75, label: "Shatter shard" },
	"shot.impact": { ...SHOT, label: "Hit spark" },
	"town.vault": { ...TOWN_PROP, w: 40, label: "Vault chest" },
	"town.forge": { ...TOWN_PROP, w: 34, label: "Forge" },
	"town.fountain": { ...TOWN_PROP, w: 24, h: 24, tall: 1.3, anchor: [0.5, 0.68], label: "Fountain centerpiece" },
	"town.target": { ...TOWN_PROP, w: 16, h: 19, tall: 1.05, anchor: [0.5, 0.41], label: "Practice target" },
	"town.bag": { ...TOWN_PROP, w: 9, h: 9, tall: 0.45, label: "Loot sack" },
	"town.shallows": { ...TOWN_PROP, label: "Shallows gate" },
	"town.fracture": { ...TOWN_PROP, label: "Fracture gate" },
	"rift.fracture.buttress": { ...DECO, tall: 1, anchor: [0.5, 0.5], label: "Wall buttress", group: "The Fracture", rift: "fracture" },
	"rift.fracture.crack": { ...DECO, tall: 1, anchor: [0.5, 0.5], label: "Warning fissure", group: "The Fracture", rift: "fracture" },
	"rift.fracture.gate": { ...DECO, tall: 1, anchor: [0.5, 0.5], label: "Iron gate panel", group: "The Fracture", rift: "fracture" },
	"town.ashen": { ...TOWN_PROP, label: "Ashen Breach gate" },
	"town.dream": { ...TOWN_PROP, label: "Dream gate" },
	...Object.fromEntries(Object.entries(TILE_PARTS).flatMap(([rift, parts]) =>
		parts.map((part) => [`tile.${rift}.${part}`,
			{ ...TILE, label: TILE_LABEL[rift][part] || TILE_LABEL.any[part],
				group: rift === "town" ? "Town tiles" : `${RIFT_NAMES[rift]} tiles`, rift }]))),
	...Object.fromEntries(Object.entries(DECO_LABEL).flatMap(([rift, labels]) =>
		Object.entries(DECO_PARTS).map(([part, d]) => [`deco.${rift}.${part}`,
			{ ...DECO, tall: d.tall, anchor: d.anchor, label: labels[part],
				group: rift === "town" ? "Town decorations" : `${RIFT_NAMES[rift]} decorations`, rift }]))),
};

/* THE PICTURES THAT EXIST live in artManifest.js, one line per file in
 * webapp/public/art/halcyon/:
 *   "enemy.chaser": { src: "enemy.chaser.png", v: 1763500000000, frames: 4, fps: 8, facings: 3 },
 * w/h/anchor default to the slot's; give them only to override. `v` changes when the
 * file does, so a browser never keeps the old picture. The gallery's "Use this"
 * writes that file through the dev server; it is plain data so a person can too. */
export const MANIFEST = ART.pictures || {};

/* THE SHARED COLOR LIST (art direction §2.3). Every finished picture's colors are
 * snapped to ONE list of shared values, so pictures from different generations use
 * the very same blues, browns and reds; and a picture may only use the part of the
 * list its JOB allows (`paletteFor`) — the color-role rule made mechanical: an enemy
 * cannot come out the player's cyan or blue, the player cannot wear danger red,
 * a floor is never vivid.
 *
 * The list is built in OKLCH (lightness, chroma = how vivid, hue angle): twelve hues
 * every 30 degrees, eight lightness steps, four strengths, plus grays. (The 0.065
 * strength came 2026-11-19: a muted slate cloak sat halfway between 0.04 and 0.09
 * and its squares flipped between the two.) It is broad
 * on purpose — the first one (40 hand-picked colors) had no navy, and snapped the
 * Ranger's blue hood to violet. */
const toHex = (r, g, b) => "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, "0")).join("");
const gam = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
/* OKLCH to sRGB, lowering the chroma until the color exists on a screen. */
export function oklchHex(L, C, hDeg) {
	for (let c = C; c >= 0; c -= 0.005) {
		const a = c * Math.cos(hDeg * Math.PI / 180), b = c * Math.sin(hDeg * Math.PI / 180);
		const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
		const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
		if (rgb.every((v) => v >= -0.001 && v <= 1.001)) return toHex(...rgb.map(gam));
	}
	return toHex(L, L, L);
}
const LIGHT = [0.2, 0.29, 0.38, 0.48, 0.58, 0.68, 0.79, 0.9];
export const MASTER = [...new Map([
	...[0.13, 0.24, 0.35, 0.47, 0.6, 0.73, 0.86, 0.97].map((L) => ({ L, C: 0, h: 0 })),
	...[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].flatMap((h) =>
		LIGHT.flatMap((L) => [0.04, 0.065, 0.09, 0.15].map((C) => ({ L, C, h })))),
].map((c) => { const hex = oklchHex(c.L, c.C, c.h); return [hex, { hex, ...c }]; })).values()];

export const PALETTE = {
	outline: ["#14111a"],
	// each place's own ground colors, beside the quiet part of the shared list
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
/* The hue families that carry a meaning (OKLCH hue angles, vivid only). */
const vivid = (c) => c.C >= 0.09;
export const isDanger = (c) => vivid(c) && (c.h <= 60 || c.h >= 330);       // red, orange, magenta
export const isPlayerHue = (c) => vivid(c) && c.h >= 180 && c.h <= 270;     // cyan, blue
/* What the player may NOT wear: only the strongest reds and oranges. The middle
 * strength of a warm hue is wood, leather and skin — the Ranger's bow and hands —
 * and forbidding it snapped them to yellow-tan (2026-11-19). */
export const isHotDanger = (c) => isDanger(c) && c.C >= 0.15;
/* Which part of the shared list a slot's picture may use. */
export function paletteFor(key) {
	const slot = SLOTS[key];
	if (!slot) return [];
	const kind = key.split(".")[0], hex = (list) => list.map((c) => c.hex);
	if (kind === "tile") return [...hex(MASTER.filter((c) => c.C <= 0.04)), ...PALETTE.env[slot.rift]];
	// A decoration may glow warm (a torch's flame), but never the enemies' hottest reds
	// and never the player's blues.
	if (kind === "deco") return [...PALETTE.outline, ...hex(MASTER.filter((c) => !isPlayerHue(c) && !isHotDanger(c)))];
	if (kind === "player" || kind === "town") return [...PALETTE.outline, ...hex(MASTER.filter((c) => !isHotDanger(c)))];
	if (kind === "shot") {
		const warm = key.startsWith("shot.enemy") || key === "shot.power" || key === "shot.impact";
		const colors = warm
			? MASTER.filter((c) => isDanger(c) || (c.h >= 30 && c.h <= 90) || (c.C === 0 && c.L > 0.6))
			: MASTER.filter((c) => isPlayerHue(c) || c.C <= 0.04 || (key === "shot.player" && c.h >= 30 && c.h <= 90 && c.L <= 0.68));
		return [...PALETTE.outline, ...hex(colors)];
	}
	return [...PALETTE.outline, ...hex(MASTER.filter((c) => !isPlayerHue(c)))];   // enemies and bosses
}

/* The frame layout of one manifest line, with the slot's defaults filled in. */
export function sheetOf(key, entry = MANIFEST[key]) {
	const slot = SLOTS[key];
	if (!slot || !entry) return null;
	const h = entry.h || slot.h;
	/* A character's feet sit `foot` tiles below its position; the picture's bottom row
	 * is its feet (the cleanup leaves one row under them for the outline). */
	const anchor = entry.anchor || slot.anchor || [0.5, Math.max(0, 1 - (1 + slot.foot * artPx()) / h)];
	return { w: entry.w || slot.w, h, anchor,
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
		const rec = { img, entry, sheet: sheetOf(key, entry), ready: false };
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
	const e = { src: "(preview)", ...entry };
	loaded.set(key, { img: image, entry: e, sheet: sheetOf(key, e), ready: true });
}

/* Draw `key` with its anchor on (X, Y), at `px` screen pixels a tile. Returns false
 * (and draws nothing) when the picture is not there, so the caller draws its shape.
 * `rot` turns it (a shot along its flight); `size` scales it (a big enemy). */
export function drawSprite(g, key, X, Y, px, { facing = null, tick = 0, seed = 0, rot = 0, size = 1, alpha = 1 } = {}) {
	const rec = sprite(key);
	if (!rec) return false;
	// The anchor is worked out per draw, so a new density in the studio moves the feet too.
	const s = sheetOf(key, rec.entry), k = (px / artPx()) * size, f = frameOf(s, { facing, tick, seed });
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
