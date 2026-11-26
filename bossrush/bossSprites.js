// A boss frame is square with the boss core at its center and an 80% visible
// footprint. The frames are CHUNKY pixel art in the RotMG / Darza manner: 32 px, a few
// flat colors and a black outline, rebuilt from the 80 px art in bossrush/art/sprites80/
// by bossrush/tools/chunky_art.py (run it after changing a source sprite). They are drawn
// unsmoothed, at a whole number of screen pixels per art pixel where that stays within
// 12% of the true size, standing on a soft shadow. Art over 120 px would be drawn
// smoothly. The original artwork is in bossrush/art/.
//
// The heroes are 12 px sprites in the same manner, one per class, facing right
// (hero-<class>.png, drawn by bossrush/tools/hero_art.py; a retouched one is its own source).
import { drawPixelShadow } from "./juice.js";

const FORMS = new Set(["tidewarden", "breach", "pyre", "orrery", "glassweaver", "cantor"]);
const PROPS = new Set(["orrery-tower", "rift-pillar"]);
const HEROES = new Set(["ranger", "paladin", "diviner", "ninja", "simon"]);

/* The sprite with every pixel one color: a hit's flash, a fallen hero's ghost. */
function recolor(doc, image, fill) {
	const canvas = doc.createElement("canvas");
	canvas.width = image.naturalWidth;
	canvas.height = image.naturalHeight;
	const ctx = canvas.getContext("2d");
	ctx.drawImage(image, 0, 0);
	ctx.globalCompositeOperation = "source-atop";
	ctx.fillStyle = fill;
	ctx.fillRect(0, 0, canvas.width, canvas.height);
	return canvas;
}
const ART_BASE = `${import.meta.env?.BASE_URL || "/"}art/bossrush/`;
const loaded = new WeakMap();

function spriteSet(doc) {
	let set = loaded.get(doc);
	if (set) return set;
	const sprites = new Map();
	const files = [...FORMS, ...PROPS, ...[...HEROES].map((c) => `hero-${c}`)];
	const ready = Promise.all(files.map((form) => new Promise((resolve) => {
		const image = doc.createElement("img");
		image.onload = () => {
			const sprite = { image };
			if (FORMS.has(form)) sprite.tint = recolor(doc, image, "#fff3ea");
			if (form.startsWith("hero-")) {
				sprite.tint = recolor(doc, image, "#ffffff");
				sprite.ghost = recolor(doc, image, "rgba(120,114,138,.82)");
			}
			sprites.set(form, sprite);
			resolve();
		};
		// An unavailable sprite leaves the fallback drawing in place.
		image.onerror = () => resolve();
		image.src = `${ART_BASE}${form}.png`;
	})));
	set = { sprites, ready };
	loaded.set(doc, set);
	return set;
}

/* Which boss each arena holds, by the arena key a boss set lists (dungeon.py's BOSSES). */
const ARENA_FORMS = { shallows: "tidewarden", fracture: "breach", ashen: "pyre",
	"orrery-hall": "orrery", "prism-court": "glassweaver", "hush-vault": "cantor" };

/* Where an arena's boss sprite is served, or undefined for a boss with no art yet. */
export function bossArtUrl(arenaKey) {
	const form = ARENA_FORMS[arenaKey];
	return form ? `${ART_BASE}${form}.png` : undefined;
}

/* Where a class's hero sprite is served, for the pages that show it as an <img>. */
export function heroArtUrl(classId) {
	return HEROES.has(classId) ? `${ART_BASE}hero-${classId}.png` : undefined;
}

export function preloadArenaSprites(doc) {
	return spriteSet(doc).ready;
}

export function bossSprite(doc, form) {
	return doc && FORMS.has(form) ? spriteSet(doc).sprites.get(form) : undefined;
}

export function heroSprite(doc, classId) {
	return doc && HEROES.has(classId) ? spriteSet(doc).sprites.get(`hero-${classId}`) : undefined;
}

export function propSprite(doc, name) {
	return doc && PROPS.has(name) ? spriteSet(doc).sprites.get(name)?.image : undefined;
}

export function drawBossSprite(g, sprite, X, Y, r, tintOpacity) {
	const w = sprite.image.naturalWidth;
	let side = r * 2.5;                                   // the frame: 40/32 of the radius, each way
	const smooth = w > 120;
	if (!smooth) {
		// Every art pixel the same width: on a big screen 32 px over ~200 draws at exactly 6.
		const k = Math.round(side / w);
		if (k >= 1 && Math.abs(k * w - side) <= side * 0.12) side = k * w;
		X = Math.round(X - side / 2) + side / 2;
		Y = Math.round(Y - side / 2) + side / 2;
	}
	const half = side / 2;
	// The shadow it stands on: on the sprite's own pixel grid, or smooth under smooth art.
	if (!smooth) drawPixelShadow(g, X, Y - half + Math.round(w * 0.86) * (side / w), w * 0.31, w * 0.085, side / w);
	g.save();
	if (smooth) {
		g.fillStyle = "rgba(4,2,10,.38)";
		g.beginPath(); g.ellipse(X, Y + half * 0.72, half * 0.62, half * 0.17, 0, 0, Math.PI * 2); g.fill();
	}
	g.imageSmoothingEnabled = smooth;
	g.imageSmoothingQuality = "high";
	g.drawImage(sprite.image, X - half, Y - half, side, side);
	if (tintOpacity > 0) {
		g.globalAlpha *= tintOpacity;
		g.drawImage(sprite.tint, X - half, Y - half, side, side);
	}
	g.restore();
}
