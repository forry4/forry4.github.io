// The 80 px game frames contain a 64 px visible footprint and put the boss
// core at (40, 40). The original artwork is in bossrush/art/.
const FORMS = new Set(["tidewarden", "breach", "pyre", "orrery", "glassweaver", "cantor"]);
const ART_BASE = `${import.meta.env?.BASE_URL || "/"}art/bossrush/`;
const loaded = new WeakMap();

function spriteSet(doc) {
	let set = loaded.get(doc);
	if (set) return set;
	const sprites = new Map();
	const ready = Promise.all([...FORMS].map((form) => new Promise((resolve) => {
		const image = doc.createElement("img");
		image.onload = () => {
			const tint = doc.createElement("canvas");
			tint.width = image.naturalWidth;
			tint.height = image.naturalHeight;
			const ctx = tint.getContext("2d");
			ctx.drawImage(image, 0, 0);
			ctx.globalCompositeOperation = "source-in";
			ctx.fillStyle = "#fff3ea";
			ctx.fillRect(0, 0, tint.width, tint.height);
			sprites.set(form, { image, tint });
			resolve();
		};
		// An unavailable sprite leaves the existing boss drawing in place.
		image.onerror = resolve;
		image.src = `${ART_BASE}${form}.png`;
	})));
	set = { sprites, ready };
	loaded.set(doc, set);
	return set;
}

export function preloadBossSprites(doc) {
	return spriteSet(doc).ready;
}

export function bossSprite(doc, form) {
	return doc && FORMS.has(form) ? spriteSet(doc).sprites.get(form) : undefined;
}

export function drawBossSprite(g, sprite, X, Y, r, tintOpacity) {
	const half = r * (40 / 32);
	g.save();
	g.imageSmoothingEnabled = false;
	g.drawImage(sprite.image, X - half, Y - half, 2 * half, 2 * half);
	if (tintOpacity > 0) {
		g.globalAlpha *= tintOpacity;
		g.drawImage(sprite.tint, X - half, Y - half, 2 * half, 2 * half);
	}
	g.restore();
}
