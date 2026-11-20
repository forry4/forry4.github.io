/* THE CLEANUP STEP (art direction §3.1): a generated image in, a game-ready picture
 * out. It is what makes pictures from different generations look like one game —
 * the generator draws, and this enforces the rules every picture shares:
 *
 *   1. the flat background (whatever color it is) is cut away from the edges in;
 *   2. what is left is cropped and shrunk to the slot's size (characters to a chosen
 *      height), so every picture has the same pixel size;
 *   3. every pixel is fully in or out, and specks of one or two pixels are dropped;
 *   4. every color is swapped for the nearest one its JOB allows (art.paletteFor);
 *   5. one outline, the same near-black, goes round every sprite.
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
 * edge's own color — so a body the same color as the background is kept when it is
 * not touching the edge. `plain` is false when the edge was not one flat color (a
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

/* The default height, in art pixels, of what fills a slot: a character 20 of its
 * 24, a boss twice a character, a shot its whole frame less the outline. */
export function defaultHeight(key, charH = 20) {
	const s = SLOTS[key];
	return s.h <= 8 ? s.h - 2 : s.h >= 40 ? Math.min(s.h - 2, charH * 2) : key === "enemy.splinter" ? Math.min(s.h - 2, Math.round(charH * 0.6)) : Math.min(s.h - 2, charH);
}

/* The whole cleanup for one slot. `img` is the generated picture (background still
 * on unless `keyed`). A class whose picture holds THREE things side by side gets
 * them as its three facings (down, side, up). Returns the finished sheet plus
 * `facings` and the `notes` worth telling the person (a busy background, say). */
export function cleanFor(key, img, { charH = 20, keyed = false } = {}) {
	const slot = SLOTS[key], notes = [];
	if (!slot) throw new Error(`no slot ${key}`);
	const colors = paletteFor(key);
	if (key.startsWith("tile.")) {
		const t = shrink(img, { x: 0, y: 0, w: img.w, h: img.h }, slot.w, slot.h);
		for (let i = 3; i < t.data.length; i += 4) t.data[i] = 255;   // a tile has no holes
		return { sheet: snap(t, colors), facings: 1, notes };
	}
	let src = img;
	if (!keyed) {
		const cut = removeBackground(img);
		src = cut.img;
		if (!cut.plain) notes.push("the background was not one flat color, so some of it may be left — ask for a plain background");
	}
	const segs = segments(src);
	const parts = key.startsWith("player.") && segs.length === 3 ? segs : [{ x0: 0, x1: src.w - 1 }];
	if (key.startsWith("player.") && segs.length !== 3) notes.push(`found ${segs.length} figure${segs.length === 1 ? "" : "s"}, not 3, so this is one facing used every way`);
	const H = defaultHeight(key, charH), sheet = image(slot.w, slot.h * parts.length);
	parts.forEach((seg, k) => {
		const box = bbox(src, seg.x0, seg.x1);
		if (!box) return;
		const sc = Math.min(H / box.h, (slot.w - 2) / box.w);
		const W = Math.max(1, Math.round(box.w * sc)), Hh = Math.max(1, Math.round(box.h * sc));
		const part = snap(dropSpecks(shrink(src, box, W, Hh)), colors);
		const frame = image(slot.w, slot.h);
		const y = key.startsWith("shot.") ? Math.round((slot.h - Hh) / 2) : slot.h - 1 - Hh;
		blit(frame, part, Math.round((slot.w - W) / 2), y);
		blit(sheet, outline(frame), 0, k * slot.h);
	});
	return { sheet, facings: parts.length, notes };
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
