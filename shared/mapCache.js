/* THE MAP, PAINTED ONCE AND COPIED (owner's ask, 2026-11-21). Boss Rush and Halcyon
 * Rift drew every floor and wall tile on screen every frame — a few hundred
 * rectangles or tile pictures, ~60 times a second, for a picture that only changes
 * when the camera moves. This keeps that picture in a canvas of its own and copies it
 * in one `drawImage`.
 *
 * The canvas covers the VIEW plus a margin of tiles, never the whole map. Halcyon
 * once baked its whole dungeon into one canvas at screen resolution; on a 150%
 * display that was ~20,500 x 2,800 pixels — past what a graphics card holds as one
 * picture — and copying it every frame halved the frame rate. Here the canvas is
 * about the size of the screen, it is repainted only when the camera leaves it (or
 * the map, its colors or its art change), and a canvas that would still come out
 * too big is skipped in favor of drawing straight to the screen.
 *
 * `paint(c, ox, oy, px, width, height)` draws the layer into `c` exactly the way it
 * would draw on screen: the map's top-left at (ox, oy), `px` pixels a tile, the view
 * `width` x `height`. It is called with the cache's own context and numbers, or with
 * the screen's own when there is no cache (under node, or a canvas too big). `key` is
 * a list of whatever the picture depends on (the tiles, the colors, the art), compared
 * item by item. */
const layers = new WeakMap();
const MAX_SIDE = 8192, MAX_AREA = 16e6;   // iOS refuses a canvas over ~16.7M pixels

export function cachedLayer(g, key, { cols, rows, ox, oy, px, width, height, margin = 3 }, paint) {
	const m = typeof g.getTransform === "function" ? g.getTransform() : null;
	const doc = g.canvas?.ownerDocument || (typeof document !== "undefined" ? document : null);
	if (!m || m.b || m.c || !doc) { paint(g, ox, oy, px, width, height); return false; }
	const s = m.a, d = px * s;                          // device pixels a tile
	const x0 = Math.max(0, Math.floor(-ox / px)), x1 = Math.min(cols - 1, Math.floor((width - ox) / px));
	const y0 = Math.max(0, Math.floor(-oy / px)), y1 = Math.min(rows - 1, Math.floor((height - oy) / px));
	if (x1 < x0 || y1 < y0) return true;
	let L = layers.get(g);
	const fits = L && L.d === d && x0 >= L.x0 && x1 <= L.x1 && y0 >= L.y0 && y1 <= L.y1
		&& L.key.length === key.length && L.key.every((k, i) => k === key[i]);
	if (!fits) {
		const X0 = Math.max(0, x0 - margin), X1 = Math.min(cols - 1, x1 + margin);
		const Y0 = Math.max(0, y0 - margin), Y1 = Math.min(rows - 1, y1 + margin);
		const w = Math.ceil((X1 - X0 + 1) * d), h = Math.ceil((Y1 - Y0 + 1) * d);
		if (w > MAX_SIDE || h > MAX_SIDE || w * h > MAX_AREA) { paint(g, ox, oy, px, width, height); return false; }
		const canvas = L?.canvas || doc.createElement("canvas");
		if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
		const c = canvas.getContext("2d");
		c.setTransform(1, 0, 0, 1, 0, 0);
		c.clearRect(0, 0, w, h);
		paint(c, -X0 * d, -Y0 * d, d, w, h);
		L = { canvas, key: key.slice(), d, x0: X0, x1: X1, y0: Y0, y1: Y1 };
		layers.set(g, L);
	}
	g.save();
	g.setTransform(1, 0, 0, 1, 0, 0);
	// Whole device pixels: a picture copied at a fraction is smudged across two.
	// Only the part on screen is copied.
	const X = Math.round(m.e + ox * s + L.x0 * d), Y = Math.round(m.f + oy * s + L.y0 * d);
	const sx = Math.max(0, -X), sy = Math.max(0, -Y);
	const sw = Math.min(L.canvas.width - sx, (g.canvas?.width ?? Infinity) - X - sx);
	const sh = Math.min(L.canvas.height - sy, (g.canvas?.height ?? Infinity) - Y - sy);
	if (sw > 0 && sh > 0) g.drawImage(L.canvas, sx, sy, sw, sh, X + sx, Y + sy, sw, sh);
	g.restore();
	return true;
}
