/* THE CLEANUP STEP (art direction §3.1): a generated image in, a game-ready picture
 * out. It is what makes pictures from different generations look like one game —
 * the generator draws, and this enforces the rules every picture shares:
 *
 *   1. the flat background (whatever color it is) is cut away from the edges in;
 *   2. what is left is READ at the generator's own pixel count (one color per block
 *      of its grid — readBlocks), never smeared by an arbitrary shrink, and resized
 *      by whole pixels only when it is well off the shared pixel size;
 *   3. every pixel is fully in or out, and lone specks are dropped;
 *   4. every color is swapped for the nearest one in the shared list that its JOB
 *      allows (art.paletteFor);
 *   5. one outline, the same near-black: the generator's own when it drew one.
 *
 * Pure: it works on { w, h, data } (RGBA bytes, as canvas ImageData), so the gallery
 * runs it on a dropped file and the unit tests run it on made-up pictures. */
import { SLOTS, PALETTE, paletteFor } from "./art.js";

const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
/* OKLab: a color space where distance tracks what the eye sees, so "nearest color"
 * picks the one a person would pick. */
export function oklab(r, g, b) {
	const R = lin(r), G = lin(g), B = lin(b);
	const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
	const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
	const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
	return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
		1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
		0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

export const image = (w, h) => ({ w, h, data: new Uint8ClampedArray(w * h * 4) });
const at = (img, x, y) => (y * img.w + x) * 4;

/* 1. Cut the background away, flooding in from the edges over pixels close to the
 * edge's own color — so a body the same color as a DULL background is kept when it
 * is not touching the edge (a vivid key color goes everywhere; see below). `plain` is false when the edge was not one flat color (a
 * scene behind the subject), which the gallery reports. An image that already has a
 * see-through background is only made fully in-or-out. */
export function removeBackground(img, tol = 0.09) {
	const { w, h, data } = img, out = { w, h, data: new Uint8ClampedArray(data) };
	const border = [];
	for (let x = 0; x < w; x++) border.push(at(img, x, 0), at(img, x, h - 1));
	for (let y = 1; y < h - 1; y++) border.push(at(img, 0, y), at(img, w - 1, y));
	if (border.filter((i) => data[i + 3] < 128).length > border.length / 2) {
		for (let i = 3; i < out.data.length; i += 4) out.data[i] = out.data[i] >= 128 ? 255 : 0;
		return { img: out, plain: true };
	}
	const buckets = new Map();
	for (const i of border) {
		const k = (data[i] >> 4) * 256 + (data[i + 1] >> 4) * 16 + (data[i + 2] >> 4);
		buckets.set(k, (buckets.get(k) || 0) + 1);
	}
	const [top, count] = [...buckets].sort((a, b) => b[1] - a[1])[0];
	const pick = border.filter((i) => (data[i] >> 4) * 256 + (data[i + 1] >> 4) * 16 + (data[i + 2] >> 4) === top);
	const bg = oklab(...[0, 1, 2].map((c) => pick.reduce((s, i) => s + data[i + c], 0) / pick.length));
	const near = (i) => { const q = oklab(data[i], data[i + 1], data[i + 2]); return Math.hypot(q[0] - bg[0], q[1] - bg[1], q[2] - bg[2]) <= tol; };
	const seen = new Uint8Array(w * h), stack = [];
	for (const i of border) { const p = i / 4; if (!seen[p] && near(i)) { seen[p] = 1; stack.push(p); } }
	while (stack.length) {
		const p = stack.pop(), x = p % w, y = (p - x) / w;
		out.data[p * 4 + 3] = 0;
		for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {
			if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
			const q = ny * w + nx;
			if (!seen[q] && near(q * 4)) { seen[q] = 1; stack.push(q); }
		}
	}
	// A vivid key color (the asked-for #00FF00) is nobody's body color, so it goes
	// everywhere: the background seen through a gap (between a bow and its archer)
	// is not touching the edge, and would otherwise stay as green specks.
	if (Math.hypot(bg[1], bg[2]) > 0.15)
		for (let p = 0; p < w * h; p++) if (!seen[p] && near(p * 4)) out.data[p * 4 + 3] = 0;
	for (let i = 3; i < out.data.length; i += 4) out.data[i] = out.data[i] >= 128 ? 255 : 0;
	return { img: out, plain: count >= border.length * 0.6 };
}

/* The separate things in a picture, left to right: runs of columns that hold
 * something, with crumbs (under 2% of the whole) left out. */
export function segments(img) {
	const mass = new Array(img.w).fill(0);
	for (let y = 0; y < img.h; y++) for (let x = 0; x < img.w; x++) if (img.data[at(img, x, y) + 3]) mass[x]++;
	const total = mass.reduce((a, b) => a + b, 0), runs = [];
	let start = -1, sum = 0;
	for (let x = 0; x <= img.w; x++) {
		if (x < img.w && mass[x]) { if (start < 0) { start = x; sum = 0; } sum += mass[x]; }
		else if (start >= 0) { if (sum >= total * 0.02) runs.push({ x0: start, x1: x - 1 }); start = -1; }
	}
	return runs;
}

/* The box round everything opaque between columns x0..x1, or null. */
export function bbox(img, x0 = 0, x1 = img.w - 1) {
	let a = Infinity, b = Infinity, c = -1, d = -1;
	for (let y = 0; y < img.h; y++) for (let x = x0; x <= x1; x++)
		if (img.data[at(img, x, y) + 3]) { if (x < a) a = x; if (x > c) c = x; if (y < b) b = y; if (y > d) d = y; }
	return c < 0 ? null : { x: a, y: b, w: c - a + 1, h: d - b + 1 };
}

/* 2. Shrink the box `r` of `img` to W x H by averaging a grid of samples under each
 * new pixel (see-through samples count toward the pixel being see-through). */
export function shrink(img, r, W, H, n = 6) {
	const out = image(W, H);
	for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
		let R = 0, G = 0, B = 0, A = 0;
		for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
			const sx = Math.min(img.w - 1, Math.floor(r.x + (x + (i + 0.5) / n) * r.w / W));
			const sy = Math.min(img.h - 1, Math.floor(r.y + (y + (j + 0.5) / n) * r.h / H));
			const k = at(img, sx, sy), a = img.data[k + 3] / 255;
			R += img.data[k] * a; G += img.data[k + 1] * a; B += img.data[k + 2] * a; A += a;
		}
		const k = (y * W + x) * 4;
		if (A > 0) { out.data[k] = R / A; out.data[k + 1] = G / A; out.data[k + 2] = B / A; }
		out.data[k + 3] = A / (n * n) >= 0.5 ? 255 : 0;               // 3. in or out
	}
	return out;
}

/* 3. Drop opaque specks of `max` pixels or fewer (the generator's crumbs). */
export function dropSpecks(img, max = 2) {
	const { w, h, data } = img, seen = new Uint8Array(w * h);
	for (let p = 0; p < w * h; p++) {
		if (seen[p] || !data[p * 4 + 3]) continue;
		const comp = [p], stack = [p];
		seen[p] = 1;
		while (stack.length) {
			const q = stack.pop(), x = q % w, y = (q - x) / w;
			for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]]) {
				if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
				const r = ny * w + nx;
				if (!seen[r] && data[r * 4 + 3]) { seen[r] = 1; stack.push(r); comp.push(r); }
			}
		}
		if (comp.length <= max) for (const q of comp) data[q * 4 + 3] = 0;
	}
	return img;
}

/* 4. Every opaque pixel becomes the nearest color in `colors` (hex strings). */
export function snap(img, colors) {
	const pal = colors.map((c) => { const rgb = hex(c); return { rgb, lab: oklab(...rgb) }; });
	const memo = new Map();
	for (let k = 0; k < img.data.length; k += 4) {
		if (!img.data[k + 3]) continue;
		const key = (img.data[k] << 16) | (img.data[k + 1] << 8) | img.data[k + 2];
		let best = memo.get(key);
		if (!best) {
			const q = oklab(img.data[k], img.data[k + 1], img.data[k + 2]);
			let d = Infinity;
			for (const c of pal) { const e = (c.lab[0] - q[0]) ** 2 + (c.lab[1] - q[1]) ** 2 + (c.lab[2] - q[2]) ** 2; if (e < d) { d = e; best = c.rgb; } }
			memo.set(key, best);
		}
		img.data[k] = best[0]; img.data[k + 1] = best[1]; img.data[k + 2] = best[2];
	}
	return img;
}

/* 5. One outline: every see-through pixel touching the sprite becomes `color`. */
export function outline(img, color = PALETTE.outline[0]) {
	const [r, g, b] = hex(color), { w, h, data } = img, add = [];
	for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
		if (data[at(img, x, y) + 3]) continue;
		if ([[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]].some(([nx, ny]) => nx >= 0 && ny >= 0 && nx < w && ny < h && data[at(img, nx, ny) + 3])) add.push(at(img, x, y));
	}
	for (const k of add) { data[k] = r; data[k + 1] = g; data[k + 2] = b; data[k + 3] = 255; }
	return img;
}

function blit(dst, src, X, Y) {
	for (let y = 0; y < src.h; y++) for (let x = 0; x < src.w; x++) {
		const s = at(src, x, y);
		if (!src.data[s + 3] || X + x < 0 || Y + y < 0 || X + x >= dst.w || Y + y >= dst.h) continue;
		dst.data.set(src.data.subarray(s, s + 4), at(dst, X + x, Y + y));
	}
}

/* THE GENERATOR'S OWN PIXELS. An image generator asked for pixel art draws big
 * square blocks (18 screen pixels each on the first Ranger), on a grid that wobbles
 * a pixel or two. Shrinking that picture by an arbitrary factor smears neighboring
 * blocks into each other — the first cleanup did, and it came out mush. Instead:
 * find the block size, find each block's edges, and take ONE color per block (the
 * most common one in its middle). What comes back is the generator's picture at its
 * own pixel count, crisp. */

/* How strongly the color changes across each column (dir "x") or row (dir "y"). */
export function edgeProfile(img, box, dir) {
	const n = dir === "x" ? box.w : box.h, E = new Float64Array(n);
	for (let y = box.y; y < box.y + box.h; y++) for (let x = box.x; x < box.x + box.w; x++) {
		const i = dir === "x" ? x - box.x : y - box.y;
		if (i === 0) continue;
		const a = at(img, x, y), b = dir === "x" ? at(img, x - 1, y) : at(img, x, y - 1), d = img.data;
		E[i] += Math.abs(d[a] - d[b]) + Math.abs(d[a + 1] - d[b + 1]) + Math.abs(d[a + 2] - d[b + 2]) + Math.abs(d[a + 3] - d[b + 3]);
	}
	return E;
}
/* Where the color edges are along one profile, with their strength (0-1 of the
 * profile's strongest): the columns (or rows) whose change stands above the quiet
 * inside of a block, one per edge (an edge softened over two columns counts once). */
function edgePeaks(E) {
	const sorted = [...E].sort((a, b) => a - b), max = sorted[sorted.length - 1] || 0;
	const thr = Math.max(max * 0.06, sorted[Math.floor(sorted.length / 2)] * 4);
	const out = [];
	for (let i = 1; i < E.length; i++) {
		if (E[i] <= thr || !(E[i] > 0)) continue;
		let top = true;
		for (let d = -2; d <= 2 && top; d++) {
			const j = i + d;
			if (d && j >= 0 && j < E.length && (d < 0 ? E[j] >= E[i] : E[j] > E[i])) top = false;
		}
		if (top) out.push([i, E[i] / max]);
	}
	return out;
}
/* The block size, from SEVERAL profiles at once (both directions of every figure in
 * one picture: the generator drew them all with one square block). Every gap between
 * two neighboring edges is a whole number of blocks, give or take the grid's wobble,
 * so the block size is the LARGEST size that nearly every gap is a whole number of —
 * a multiple of the block fails on the many one-block gaps, and a fraction of it is
 * smaller. A gap counts by the strength of its weaker edge, squared, so the faint
 * specks a generator leaves inside its blocks hardly count. (Scoring "lines every P
 * pixels" instead picked twice and three times the block on the first Ranger.) The
 * answer is then averaged over the gaps that fit.
 * `ratio` is the share of the gaps that fit (0 to 1); 0 means no grid at all. */
export function blockSize(profiles, min = 4) {
	const Es = Array.isArray(profiles) ? profiles : [profiles];
	// Gaps between neighboring edges, counted again among only the stronger edges:
	// a faint speck halfway across a block splits one real gap into two half gaps,
	// which made HALF the block fit best on the second Ranger (46 pixels tall, not 23).
	const gaps = [];
	for (const E of Es) {
		const all = edgePeaks(E);
		for (const level of [0, 0.15, 0.3]) {
			const p = all.filter(([, st]) => st >= level);
			for (let i = 1; i < p.length; i++) gaps.push([p[i][0] - p[i - 1][0], Math.min(p[i][1], p[i - 1][1]) ** 2]);
		}
	}
	if (gaps.length < 6) return { P: 1, ratio: 0 };
	const all = gaps.reduce((a, [, w]) => a + w, 0);
	const k = (g, P) => Math.max(1, Math.round(g / P));
	// The wobble allowed is a few pixels, and never a quarter block or more (so a
	// small size cannot fit everything just by having lines everywhere).
	const fit = (P) => gaps.filter(([g]) => Math.abs(g - k(g, P) * P) <= Math.min(3 + 0.04 * g, P / 4));
	const share = (list) => list.reduce((a, [, w]) => a + w, 0) / all;
	const max = Math.min(64, ...Es.map((E) => E.length / 2)), shares = [];
	for (let P = max; P >= min; P -= 0.1) shares.push([P, share(fit(P))]);
	const best = Math.max(...shares.map(([, sh]) => sh));
	if (best < 0.6) return { P: 1, ratio: 0 };
	// The largest size that fits about as well as the best; in its run of neighbors
	// (the wobble lets several fit), the one that fits most, from the middle of a tie.
	const good = (sh) => sh >= best - 0.05;
	let run = null;
	for (const [P, sh] of shares) {
		if (good(sh)) { if (!run || sh > run.sh + 1e-9) run = { sh, lo: P, hi: P }; else if (Math.abs(sh - run.sh) <= 1e-9) run.lo = P; }
		else if (run) break;
	}
	if (!run) return { P: 1, ratio: 0 };
	let P = (run.lo + run.hi) / 2;
	// Then the average over the gaps that fit, and again from there.
	for (let n = 0; n < 3; n++) {
		const ok = fit(P);
		P = ok.reduce((a, [g, w]) => a + g * w, 0) / ok.reduce((a, [g, w]) => a + k(g, P) * w, 0);
	}
	return { P, ratio: share(fit(P)) };
}
/* Where the block edges really are: from the start, step about one block and take
 * the strongest edge near there, so a wobbling grid is followed rather than drifted
 * off. Returns the edges, first and last included. */
export function blockEdges(E, P) {
	const n = E.length, mean = E.reduce((a, b) => a + b, 0) / Math.max(1, n - 1) || 1, out = [0];
	let x = 0;
	while (n - x > P * 1.5) {
		const lo = Math.round(x + P * 0.75), hi = Math.min(n - 1, Math.round(x + P * 1.25));
		let best = -1, at = Math.round(x + P);
		for (let i = lo; i <= hi; i++) if (E[i] > best) { best = E[i]; at = i; }
		if (best < mean * 1.2) at = Math.round(x + P);
		out.push(at);
		x = at;
	}
	out.push(n);
	return out;
}
/* The picture inside `box` read block by block: one pixel per block, the most
 * common color in the block's middle half; a block is see-through when most of
 * its middle is. Returns null when the picture has no block grid to read. */
export function readBlocks(img, box, grid) {
	const ex = edgeProfile(img, box, "x"), ey = edgeProfile(img, box, "y");
	const g = grid || blockSize([ex, ey]);
	if (!g.ratio) return null;
	const xs = blockEdges(ex, g.P), ys = blockEdges(ey, g.P);
	const out = image(xs.length - 1, ys.length - 1);
	for (let j = 0; j < ys.length - 1; j++) for (let i = 0; i < xs.length - 1; i++) {
		const x0 = box.x + xs[i], x1 = box.x + xs[i + 1], y0 = box.y + ys[j], y1 = box.y + ys[j + 1];
		const mx = Math.floor((x1 - x0) / 4), my = Math.floor((y1 - y0) / 4);
		const counts = new Map();
		let solid = 0, all = 0;
		for (let y = y0 + my; y < Math.max(y0 + my + 1, y1 - my); y++) for (let x = x0 + mx; x < Math.max(x0 + mx + 1, x1 - mx); x++) {
			const k = at(img, x, y), d = img.data;
			all++;
			if (!d[k + 3]) continue;
			solid++;
			const q = ((d[k] >> 3) << 10) | ((d[k + 1] >> 3) << 5) | (d[k + 2] >> 3);
			const c = counts.get(q) || [0, 0, 0, 0];
			c[0]++; c[1] += d[k]; c[2] += d[k + 1]; c[3] += d[k + 2];
			counts.set(q, c);
		}
		if (solid * 2 <= all) continue;
		let best = null;
		for (const c of counts.values()) if (!best || c[0] > best[0]) best = c;
		out.data.set([best[1] / best[0], best[2] / best[0], best[3] / best[0], 255], (j * out.w + i) * 4);
	}
	return { img: out, block: g.P };
}

/* Pixel art resized by whole pixels: each new pixel takes the old pixel under its
 * middle. Used only when a picture's pixel count is well off the size it must be. */
export function nearest(img, W, H) {
	const out = image(W, H);
	for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
		const s = at(img, Math.min(img.w - 1, Math.floor((x + 0.5) * img.w / W)), Math.min(img.h - 1, Math.floor((y + 0.5) * img.h / H)));
		out.data.set(img.data.subarray(s, s + 4), (y * W + x) * 4);
	}
	return out;
}
function crop(img, b) {
	const out = image(b.w, b.h);
	for (let y = 0; y < b.h; y++) for (let x = 0; x < b.w; x++) { const s = at(img, b.x + x, b.y + y); out.data.set(img.data.subarray(s, s + 4), (y * b.w + x) * 4); }
	return out;
}
const lum = (d, k) => oklab(d[k], d[k + 1], d[k + 2])[0];
/* 5. THE OUTLINE, once. A generator usually draws its own dark outline already;
 * adding a second ring made the sprite fat. So: if most of the sprite's edge is
 * already dark, those dark edge pixels just take the shared outline color; if not,
 * a ring is added round it. */
export function fixOutline(img, color = PALETTE.outline[0]) {
	const { w, h, data } = img, rgb = hex(color), edge = [];
	const open = (x, y) => x < 0 || y < 0 || x >= w || y >= h || !data[at(img, x, y) + 3];
	for (let y = 0; y < h; y++) for (let x = 0; x < w; x++)
		if (!open(x, y) && (open(x + 1, y) || open(x - 1, y) || open(x, y + 1) || open(x, y - 1))) edge.push(at(img, x, y));
	const dark = edge.filter((k) => lum(data, k) < 0.32);
	if (edge.length && dark.length >= edge.length * 0.6) {
		for (const k of dark) data.set(rgb, k);
		return { img, added: false };
	}
	return { img: outline(img, color), added: true };
}

/* The default on-screen height of a slot in ART pixels at density `px`. */
export const targetHeight = (key, px) => Math.max(2, Math.round(SLOTS[key].tall * px));

/* The whole cleanup for one slot. `img` is the generated picture (background still
 * on unless `keyed`); `artPx` the shared density. Returns the finished `sheet` (its
 * own size: the picture plus one see-through pixel all round), `facings`, the
 * `native` height the generator drew (what sets the density, for the Ranger) and
 * the `notes` worth telling the person.
 *   - read at the generator's own pixel count (readBlocks), or — for a picture with
 *     no block grid — shrunk to the size it must be;
 *   - kept at that count when it is within 15% of the size it must be, otherwise
 *     resized by whole pixels (`exact` keeps it as drawn: the Ranger SETS the size);
 *   - a class picture with THREE figures side by side becomes its three facings. */
export function cleanFor(key, img, { artPx = 16, keyed = false, exact = false } = {}) {
	const slot = SLOTS[key], notes = [];
	if (!slot) throw new Error(`no slot ${key}`);
	const colors = paletteFor(key);
	if (key.startsWith("tile.")) {
		const all = { x: 0, y: 0, w: img.w, h: img.h };
		const read = readBlocks(img, all);
		const t = read ? nearest(read.img, artPx, artPx) : shrink(img, all, artPx, artPx);
		for (let i = 3; i < t.data.length; i += 4) t.data[i] = 255;   // a tile has no holes
		return { sheet: snap(t, colors), facings: 1, notes, native: read ? read.img.h : null, w: artPx, h: artPx };
	}
	let src = img;
	if (!keyed) {
		const cut = removeBackground(img);
		src = cut.img;
		if (!cut.plain) notes.push("the background was not one flat color, so some of it may be left — ask for a plain background");
	}
	const segs = segments(src);
	const many = key.startsWith("player.") && segs.length === 3;
	const parts = many ? segs : [{ x0: 0, x1: src.w - 1 }];
	if (key.startsWith("player.") && !many) notes.push(`found ${segs.length} figure${segs.length === 1 ? "" : "s"}, not 3, so this is one facing used every way`);
	const want = targetHeight(key, artPx);
	let native = 0, blurry = false, resized = false;
	const boxes = parts.map((seg) => bbox(src, seg.x0, seg.x1)).filter(Boolean);
	// One block size for the whole picture, from every figure in it.
	const grid = blockSize(boxes.flatMap((b) => [edgeProfile(src, b, "x"), edgeProfile(src, b, "y")]));
	const frames = boxes.map((box) => {
		const read = readBlocks(src, box, grid);
		let part;
		if (read) {
			const b = bbox(read.img);
			part = crop(read.img, b);
		} else {
			blurry = true;
			const H = want - 2, W = Math.max(1, Math.round(box.w * H / box.h));
			part = shrink(src, box, W, H);
		}
		native = Math.max(native, part.h);
		return part;
	}).filter(Boolean);
	// One size for every facing: the tallest sets it.
	const H = exact || blurry || Math.abs(native - want) <= want * 0.15 ? native : want;
	if (H !== native) resized = true;
	const scaled = frames.map((f) => (H === native ? f : nearest(f, Math.max(1, Math.round(f.w * H / native)), Math.max(1, Math.round(f.h * H / native)))));
	const done = scaled.map((f) => {
		const pad = image(f.w + 2, f.h + 2);
		blit(pad, f, 1, 1);
		const { added } = fixOutline(snap(dropSpecks(pad, 1), colors));
		return { img: pad, added };
	});
	const W = Math.max(...done.map((d) => d.img.w)), Hf = Math.max(...done.map((d) => d.img.h));
	const sheet = image(W, Hf * done.length);
	done.forEach((d, k) => blit(sheet, d.img, Math.floor((W - d.img.w) / 2), k * Hf + (key.startsWith("shot.") ? Math.floor((Hf - d.img.h) / 2) : Hf - d.img.h)));
	if (blurry) notes.push("no clear pixel grid was found, so it was shrunk instead — it may look soft; ask for chunkier pixel art");
	if (resized) notes.push(`drawn ${native} pixels tall; resized to ${H} to match the Ranger's pixel size`);
	return { sheet, facings: done.length, notes, native, w: W, h: Hf };
}

/* One generated picture holding SEVERAL slots side by side (a rift's enemies drawn
 * together, so they match): cut it into its things, left to right, one per key. */
export function splitFor(keys, img) {
	const { img: keyed, plain } = removeBackground(img);
	const segs = segments(keyed);
	if (segs.length !== keys.length) return { error: `found ${segs.length} separate things, expected ${keys.length} — ask for them in one row with space between` };
	return {
		parts: keys.map((key, i) => {
			const b = bbox(keyed, segs[i].x0, segs[i].x1), part = image(b.w + 2, b.h + 2);
			for (let y = 0; y < b.h; y++) for (let x = 0; x < b.w; x++) {
				const s = at(keyed, b.x + x, b.y + y);
				part.data.set(keyed.data.subarray(s, s + 4), at(part, x + 1, y + 1));
			}
			return [key, part];
		}),
		plain,
	};
}
