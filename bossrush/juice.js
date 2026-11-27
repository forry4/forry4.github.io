// Feel: contrast, light and hit feedback, drawn over a fight. RENDER-ONLY — nothing here
// touches the simulation, so a replay, a film and every co-op seat draw the same frames.
// Everything is computed from the state being drawn (its tick, hurt timers, damage
// numbers), never from Math.random, with one exception kept honest: a boss's death
// burst needs the tick it died on, which the state does not keep, so each canvas
// remembers the ids it last saw alive and starts a burst only when it watched one fall
// (a replay seek forgets, rather than replaying a burst at the wrong moment).
//
// There is no screen shake, on purpose (owner, 2026-11-25).
//
// `calm` (prefers-reduced-motion) turns off every flash and burst; the contrast
// and light stay, since they are not motion.

const TAU = Math.PI * 2;

/* A stable [0, 1) from a few numbers: the same spark flies the same way every frame. */
function hash(a, b = 0, c = 0) {
	let h = Math.imul((a * 73856093) | 0, 0x9e3779b1) ^ Math.imul((b * 19349663) | 0, 0x85ebca6b) ^ Math.imul((c * 83492791) | 0, 0xc2b2ae35);
	h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12;
	return (h >>> 0) / 4294967296;
}

/* ---- contrast: the floor steps back so what can hit you steps forward ---- */

/* Laid over the arena's floor and walls only, before hazards, enemies and shots.
 * The baked arena (render.js) carries it already, painted once into the floor rather
 * than over the whole screen every frame; this is for the arena drawn unbaked. */
export const ARENA_SHADE = "rgba(9,7,16,.18)";
export function shadeArena(g, width, height) {
	g.fillStyle = ARENA_SHADE;
	g.fillRect(0, 0, width, height);
}

/* ---- shadows: what stands on the floor ---- */

/* An oval of shadow built from whole art pixels, so it sits on the same grid as the
 * sprite above it (a smooth oval reads as a blur beside chunky art). `X, Y` is its
 * centre, `rx, ry` its half-size in art pixels, `cell` screen pixels per art pixel.
 * A lighter rim one art pixel out, then the core, so it has an edge and a weight. */
function pixelOval(g, x0, y0, rx, ry, cell) {
	const rows = Math.ceil(ry);
	for (let j = -rows; j < rows; j++) {
		const v = (j + 0.5) / ry, t = 1 - v * v;
		if (t <= 0) continue;
		const half = Math.round(rx * Math.sqrt(t));
		if (half > 0) g.fillRect(x0 - half * cell, y0 + j * cell, half * 2 * cell, cell);
	}
}
export function drawPixelShadow(g, X, Y, rx, ry, cell) {
	const x0 = Math.round(X), y0 = Math.round(Y);
	g.save();
	g.fillStyle = "rgba(4,2,10,.2)";
	pixelOval(g, x0, y0, rx + 1, ry + 0.75, cell);
	g.fillStyle = "rgba(4,2,10,.4)";
	pixelOval(g, x0, y0, rx, ry, cell);
	g.restore();
}

const glows = new WeakMap();
/* A soft round light in one color, baked once per document and color. */
function glowSprite(doc, color) {
	let byColor = glows.get(doc);
	if (!byColor) glows.set(doc, byColor = new Map());
	let canvas = byColor.get(color);
	if (!canvas) {
		canvas = doc.createElement("canvas");
		canvas.width = canvas.height = 64;
		const c = canvas.getContext("2d");
		const grad = c.createRadialGradient(32, 32, 0, 32, 32, 32);
		grad.addColorStop(0, color);
		grad.addColorStop(0.35, color + "88");
		grad.addColorStop(1, color + "00");
		c.fillStyle = grad;
		c.fillRect(0, 0, 64, 64);
		byColor.set(color, canvas);
	}
	return canvas;
}

/* Additive light under a shot: overlapping shots get brighter, never muddier. */
export function drawGlow(g, X, Y, radius, color, alpha = 1) {
	const doc = g.canvas?.ownerDocument;
	if (!doc || typeof g.drawImage !== "function" || !/^#[0-9a-f]{6}$/i.test(color)) return;
	const op = g.globalCompositeOperation, a = g.globalAlpha;
	g.globalCompositeOperation = "lighter";
	g.globalAlpha = alpha;
	g.drawImage(glowSprite(doc, color), X - radius, Y - radius, radius * 2, radius * 2);
	g.globalCompositeOperation = op;
	g.globalAlpha = a;
}

/* A pool of the boss's own light on the floor around it. Steady (it used to breathe),
 * and 2.6 boss radii across rather than 4.2: at 4.2 it was ~1,100 screen pixels wide on
 * a laptop and the largest single thing drawn each frame (owner's OK, 2026-11-27). */
export function drawBossLight(g, X, Y, r, color) {
	drawGlow(g, X, Y, r * 2.6, color, 0.32);
}

/* ---- impacts, read off the damage numbers the sim already keeps ---- */

const FOE_NUMBER_LIFE = 36, HERO_NUMBER_LIFE = 45;   // sim.js: how long each number stays

export function drawImpacts(g, st, sx, sy, px, calm) {
	if (calm || !st.damageNumbers?.length) return;
	const op = g.globalCompositeOperation;
	g.globalCompositeOperation = "lighter";
	for (const n of st.damageNumbers) {
		const age = st.tick - (n.until - (n.foe ? FOE_NUMBER_LIFE : HERO_NUMBER_LIFE));
		const life = n.foe ? 10 : 16;
		if (age < 0 || age >= life) continue;
		const k = age / life, X = sx(n.x), Y = sy(n.y);
		const sparks = n.foe ? 6 : 10, reach = px * (n.foe ? 0.75 : 1.1);
		const seed = Math.round(n.x * 97 + n.y * 131) + n.until;
		g.fillStyle = n.foe ? `rgba(255,236,196,${(1 - k).toFixed(3)})` : `rgba(255,96,80,${(1 - k).toFixed(3)})`;
		for (let i = 0; i < sparks; i++) {
			const a = hash(seed, i) * TAU, d = reach * (0.35 + 0.65 * hash(seed, i, 7)) * Math.sqrt(k);
			const s = Math.max(1.5, px * 0.075 * (1 - k));
			g.fillRect(X + Math.cos(a) * d - s / 2, Y + Math.sin(a) * d - s / 2, s, s);
		}
		if (age < 4) {                                   // the first frames: a white pop
			g.fillStyle = `rgba(255,250,240,${(0.7 * (1 - age / 4)).toFixed(3)})`;
			g.beginPath(); g.arc(X, Y, px * (n.foe ? 0.22 : 0.4) * (1 + age * 0.4), 0, TAU); g.fill();
		}
	}
	g.globalCompositeOperation = op;
}

/* ---- a boss falling ---- */

const watch = new WeakMap();   // per canvas: which bosses it last saw alive, and who fell

function track(g, st) {
	const key = g.canvas || g;
	let w = watch.get(key);
	const tick = st.tick;
	if (!w || tick < w.tick || tick > w.tick + 30) w = { tick, alive: new Map(), deaths: [] };   // a seek: forget
	for (const e of st.enemies || []) {
		if (e.type !== "boss") continue;
		if (e.hp > 0) w.alive.set(e.id, e);
		else if (w.alive.has(e.id)) {
			w.alive.delete(e.id);
			w.deaths.push({ id: e.id, tick, x: e.x, y: e.y, r: e.r });
		}
	}
	w.deaths = w.deaths.filter((d) => tick - d.tick < 60);
	w.tick = tick;
	watch.set(key, w);
	return w;
}

/* Call once per frame, before drawing: it is what notices a boss go down. */
export function noteFrame(g, st) { track(g, st); }

export function drawDeaths(g, st, sx, sy, px, calm, color = "#ffd6a0") {
	if (calm) return;
	const w = watch.get(g.canvas || g);
	if (!w) return;
	for (const d of w.deaths) {
		const age = st.tick - d.tick, k = age / 60, X = sx(d.x), Y = sy(d.y), r = d.r * px;
		// A widening ring, a flash at its heart, and shards thrown out.
		g.strokeStyle = `rgba(255,240,220,${(0.9 * (1 - k)).toFixed(3)})`;
		g.lineWidth = Math.max(2, px * 0.14 * (1 - k));
		g.beginPath(); g.arc(X, Y, r + px * 6 * Math.sqrt(k), 0, TAU); g.stroke();
		drawGlow(g, X, Y, r * (3 + 4 * k), color, 1 - k);
		const op = g.globalCompositeOperation;
		g.globalCompositeOperation = "lighter";
		g.fillStyle = `rgba(255,226,190,${(1 - k).toFixed(3)})`;
		for (let i = 0; i < 24; i++) {
			const a = hash(d.id, i) * TAU, dist = r + px * 5 * (0.4 + 0.6 * hash(d.id, i, 3)) * Math.sqrt(k);
			const s = Math.max(2, px * 0.13 * (1 - k));
			g.fillRect(X + Math.cos(a) * dist - s / 2, Y + Math.sin(a) * dist - s / 2, s, s);
		}
		g.globalCompositeOperation = op;
	}
}

/* ---- the frame's edges ---- */

const vignettes = new WeakMap();
/* Darker toward the corners, so the eye sits where the fight is; red at the edges when
 * you are hurt, and drained when you are down. */
export function drawVignette(g, width, height, { hurt = 0, down = false, calm = false } = {}) {
	const key = g.canvas || g;
	let v = vignettes.get(key);
	if (!v || v.width !== width || v.height !== height) {
		const r = Math.hypot(width, height) / 2;
		v = { width, height, r, dark: null, red: null };
		vignettes.set(key, v);
	}
	edgeLayer(g, v, "dark", 0.7, "rgba(0,0,0,0)", "rgba(4,2,10,.32)");   // clear to 70% (was 55%): a narrower band to draw
	if (hurt > 0 && !calm) {
		g.globalAlpha = Math.min(1, hurt / 8);
		edgeLayer(g, v, "red", 0.62, "rgba(210,30,30,0)", "rgba(210,30,30,.42)");
		g.globalAlpha = 1;
	}
	if (down) {
		g.fillStyle = "rgba(12,8,16,.45)";
		g.fillRect(0, 0, width, height);
	}
}

/* One vignette ring: a radial gradient that is clear inside `inner` of the half
 * diagonal and darkens toward the corners. Recomputing that gradient over the whole
 * screen every frame was the single largest cost of a frame on integrated graphics
 * (owner's 240 Hz laptop, 2026-11-27: ~5% of frames missed with it, ~0% without), so
 * it is painted ONCE per canvas size into an image, and each frame copies only the
 * band outside the clear middle (the rectangle whose corners touch the clear circle,
 * a pixel inside it). Same gradient, same pixels. */
function edgeLayer(g, v, which, inner, from, to) {
	const { width, height, r } = v;
	let layer = v[which];
	const doc = g.canvas?.ownerDocument;
	if (!layer && doc && typeof g.drawImage === "function") {
		layer = doc.createElement("canvas");
		layer.width = width;
		layer.height = height;
		const c = layer.getContext("2d");
		const grad = c.createRadialGradient(width / 2, height / 2, r * inner, width / 2, height / 2, r);
		grad.addColorStop(0, from);
		grad.addColorStop(1, to);
		c.fillStyle = grad;
		c.fillRect(0, 0, width, height);
		v[which] = layer;
	}
	if (!layer) {                                        // no document (tests): the plain fill
		const grad = g.createRadialGradient(width / 2, height / 2, r * inner, width / 2, height / 2, r);
		grad.addColorStop(0, from);
		grad.addColorStop(1, to);
		g.fillStyle = grad;
		g.fillRect(0, 0, width, height);
		return;
	}
	const x0 = Math.ceil(width / 2 - inner * width / 2) + 1, x1 = Math.floor(width / 2 + inner * width / 2) - 1;
	const y0 = Math.ceil(height / 2 - inner * height / 2) + 1, y1 = Math.floor(height / 2 + inner * height / 2) - 1;
	const part = (x, y, w, h) => { if (w > 0 && h > 0) g.drawImage(layer, x, y, w, h, x, y, w, h); };
	part(0, 0, width, y0);                               // top, bottom, then the two sides between
	part(0, y1, width, height - y1);
	part(0, y0, x0, y1 - y0);
	part(x1, y0, width - x1, y1 - y0);
}
