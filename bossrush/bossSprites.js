// A boss frame is square with the boss core at its center and about an 80% visible
// footprint. The frames are hi-bit pixel art, 96 px, DRAWN by bossrush/tools/hibit_art.py
// (run it after changing a boss; it writes webapp/public/art/bossrush/). They are drawn
// unsmoothed, in whole screen pixels per art pixel where that stays close to the true
// size, so every art pixel is the same width. Art over 120 px would be drawn smoothly.
// The original artwork they were redrawn from is in bossrush/art/.
const FORMS = new Set(["tidewarden", "breach", "pyre", "orrery", "glassweaver", "cantor"]);
const PROPS = new Set(["orrery-tower", "rift-pillar"]);
const ART_BASE = `${import.meta.env?.BASE_URL || "/"}art/bossrush/`;
const loaded = new WeakMap();

function spriteSet(doc) {
	let set = loaded.get(doc);
	if (set) return set;
	const sprites = new Map();
	const ready = Promise.all([...FORMS, ...PROPS].map((form) => new Promise((resolve) => {
		const image = doc.createElement("img");
		image.onload = () => {
			const sprite = { image };
			if (FORMS.has(form)) {
				const tint = doc.createElement("canvas");
				tint.width = image.naturalWidth;
				tint.height = image.naturalHeight;
				const ctx = tint.getContext("2d");
				ctx.drawImage(image, 0, 0);
				ctx.globalCompositeOperation = "source-in";
				ctx.fillStyle = "#fff3ea";
				ctx.fillRect(0, 0, tint.width, tint.height);
				sprite.tint = tint;
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

export function preloadArenaSprites(doc) {
	return spriteSet(doc).ready;
}

export function bossSprite(doc, form) {
	return doc && FORMS.has(form) ? spriteSet(doc).sprites.get(form) : undefined;
}

export function propSprite(doc, name) {
	return doc && PROPS.has(name) ? spriteSet(doc).sprites.get(name)?.image : undefined;
}

export function drawBossSprite(g, sprite, X, Y, r, tintOpacity) {
	const w = sprite.image.naturalWidth;
	let side = r * 2.5;                                   // the frame: 40/32 of the radius, each way
	const smooth = w > 120;
	if (!smooth) {
		// Whole screen pixels per art pixel, when that is within 12% of the true size: on a
		// big screen 96 px of art over ~200 px draws at exactly 2 a pixel, not 2.08.
		const k = Math.round(side / w);
		if (k >= 1 && Math.abs(k * w - side) <= side * 0.12) side = k * w;
		X = Math.round(X - side / 2) + side / 2;
		Y = Math.round(Y - side / 2) + side / 2;
	}
	const half = side / 2;
	g.save();
	g.imageSmoothingEnabled = smooth;
	g.imageSmoothingQuality = "high";
	g.drawImage(sprite.image, X - half, Y - half, side, side);
	if (tintOpacity > 0) {
		g.globalAlpha *= tintOpacity;
		g.drawImage(sprite.tint, X - half, Y - half, side, side);
	}
	g.restore();
}
