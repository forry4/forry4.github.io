/* Halcyon Rift's greybox renderer: colored shapes on a Canvas 2D (design §23,
 * art direction §2.3). It only DRAWS the simulation's state — nothing here may
 * change it, so the fight is the same whatever the frame rate.
 *
 * The color roles are the art doc's, and they are the one part of this file that
 * outlives the greybox: the environment quietest (the Shallows' sand, water and
 * rock), the player cyan/white, every enemy and every enemy shot red/orange/
 * magenta, pickups gold (loot) and green (healing).
 */
import { recoveryLimit, xpProgress, STARFALL_DELAY, TPS, ABILITY_COST, MORTAR, FAULT, VENT } from "./sim.js";
import { drawSprite, drawTile, artPx, PALETTE, sprite } from "./art.js";

/* ART (art.js): every thing below asks for its picture first and draws its shape
 * only when there is none, so art lands one picture at a time with nothing waiting. */

/* A loot bag wears the color of the best thing in it (design §19.1): a tier color, and
 * a unique's gold with a glow. The tier number in every slot is the non-color cue. */
// Tiers 6-10 (2026-11-19) come only from going deeper: hotter, then pale toward 10.
export const TIER_COLORS = { 0: "#8e8a80", 1: "#c9bfa6", 2: "#6fd36a", 3: "#5aa9ff", 4: "#b77cff", 5: "#ff9f43",
	6: "#ff5f57", 7: "#ff4fae", 8: "#3fe0d0", 9: "#f2ee6b", 10: "#fff7ec" };
export const UNIQUE_COLOR = "#ffd85e";

export const COLORS = {
	wall: "#3c4a45", wallTop: "#4a5a54", sand: "#a99e80", sandDark: "#a3987a",
	water: "#5f8f93", waterLight: "#6d9ea1", rock: "#7b7a70", rockTop: "#918f84",
	player: "#7fe3f0", playerCore: "#f4fdff", playerShot: "#c9f6ff",
	chaser: "#e8573f", shooter: "#ef8a3a", radial: "#c8458f", boss: "#d63a5a",
	// the Fracture's (design §14.4a): violet stone over a black void
	shard: "#7fd4ff", splitter: "#ff7a59", splinter: "#ffb199", flicker: "#e16bff", breach: "#9b6bff",
	void: "#0d0a14", voidSpeck: "#3a2a5c", seam: "rgba(185,150,255,.35)", seamHot: "#e7d8ff",
	// the Ashen Breach's: embers on charcoal. The player's own fire burns pale blue, so it
	// never reads as the enemy's orange.
	cinder: "#ffb347", kiln: "#c8553d", smolder: "#6b5a50", smolderLit: "#ff7a2e", pyre: "#ff6a2a", ash: "#8a7d72",
	enemyShot: "#ff5a4a", enemyShotHeavy: "#ff3d8b", tele: "rgba(255,90,74,.55)",
	heal: "#6fd36a", bag: "#e9c25a", portal: "#9fe7ff", dream: "#b9a7ff", deeper: "#ff9f5a",
	veil: "rgba(214,58,90,.22)", veilEdge: "rgba(255,138,150,.55)", bars: "#2a2f2d", barsLit: "#d63a5a", ward: "#cfe3ff",
	paladin: "#f1c46b", diviner: "#c4a5ff", ninja: "#8fd6a4", shield: "rgba(241,196,107,.72)",
	slow: "rgba(241,196,107,.16)", star: "#ffe9a6", damage: "#ff9b8d",
	hp: "#e2564e", mp: "#5a8de8", xp: "#9d8ff2", hudBack: "rgba(16,18,20,.72)",
	// The town: cool flagstone, so the safe place never reads like a dungeon floor.
	stone: "#56605c", stoneDark: "#515b57", townWall: "#2e3836", townWallTop: "#3c4845",
	vault: "#6b4a2a", vaultTrim: "#e9c25a", forge: "#4a4f55", forgeFire: "#ef8a3a", realm: "#9d8ff2",
};

// `deep` is the dark past the walls: the inside of a wall no floor touches, and the
// world beyond the map, so a room reads as one shape cut out of the dark.
const SHALLOWS = { id: "shallows", floorA: COLORS.sand, floorB: COLORS.sandDark, wall: COLORS.wall, wallTop: COLORS.wallTop, deep: "#1b2220" };
const FRACTURE = { id: "fracture", floorA: "#3d3550", floorB: "#39324b", wall: "#2b2439", wallTop: "#3a3150", deep: "#0f0c16" };
const ASHEN = { id: "ashen", floorA: "#3b322d", floorB: "#372e29", wall: "#2e2520", wallTop: "#40332b", deep: "#120e0c" };
export const PALETTES = { shallows: SHALLOWS, fracture: FRACTURE, ashen: ASHEN };
export const TOWN = { id: "town", floorA: COLORS.stone, floorB: COLORS.stoneDark, wall: COLORS.townWall, wallTop: COLORS.townWallTop, deep: "#151b1a" };

export function formatRiftTime(ticks) {
	const seconds = Math.max(0, Number(ticks) || 0) / 60;
	const minutes = Math.floor(seconds / 60);
	return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

/* The map, drawn tile by tile for ONLY the tiles on screen, every frame — about
 * 250 rectangles. It used to be baked once into one canvas the size of the whole
 * dungeon at screen resolution; on a 150% display that canvas was ~20,500 x 2,800
 * pixels, and copying it every frame halved the frame rate (measured: 33ms frames
 * at 2560x1440@1.5 against 16.7ms at 1080p). */
export function drawMap(g, st, ox, oy, px, width, height, pal = SHALLOWS) {
	const x0 = Math.max(0, Math.floor(-ox / px)), x1 = Math.min(st.w - 1, Math.floor((width - ox) / px));
	const y0 = Math.max(0, Math.floor(-oy / px)), y1 = Math.min(st.h - 1, Math.floor((height - oy) / px));
	// Whole pixels, one tile wide plus a pixel, so neighbours never leave a seam.
	const P = Math.ceil(px) + 1, t0 = `tile.${pal.id}.`;
	for (let y = y0; y <= y1; y++) {
		const row = st.tiles[y], below = y + 1 < st.h ? st.tiles[y + 1] : null;
		const Y = Math.floor(oy + y * px), TH = Math.floor(oy + (y + 1) * px) - Y;
		for (let x = x0; x <= x1; x++) {
			const t = row[x], X = Math.floor(ox + x * px), TW = Math.floor(ox + (x + 1) * px) - X, seed = x * 7 + y * 13;
			if (t === "#") {
				if (deepWall(st, x, y)) { g.fillStyle = pal.deep; g.fillRect(X, Y, P, P); continue; }
				// A lit top edge where a wall meets floor below it: light comes from above.
				const edge = (below && below[x] !== "#") || (pal === FRACTURE && (!below || deepWall(st, x, y + 1)));
				if (edge && drawTile(g, t0 + "wallTop", X, Y, TW, TH, seed)) continue;
				if (!drawTile(g, t0 + "wall", X, Y, TW, TH, seed)) { g.fillStyle = edge ? pal.wallTop : pal.wall; g.fillRect(X, Y, P, P); }
			} else if (t === "x") {                       // torn floor: the void under the Rift
				if (drawTile(g, t0 + "void", X, Y, TW, TH, seed)) continue;
				g.fillStyle = COLORS.void; g.fillRect(X, Y, P, P);
				if (seed % 5 === 0) { g.fillStyle = COLORS.voidSpeck; g.fillRect(X + px * 0.3, Y + px * 0.55, px * 0.08, px * 0.08); }
			} else if (t === "~") {
				if (drawTile(g, t0 + "water", X, Y, TW, TH, seed)) continue;
				g.fillStyle = COLORS.water; g.fillRect(X, Y, P, P);
				g.fillStyle = COLORS.waterLight; g.fillRect(X + px * 0.15, Y + px * 0.3, px * 0.4, px * 0.08);
			} else {
				// The Fracture's broad flagstones span a 2×2 repeat.
				const floorSeed = pal === FRACTURE ? (x % 2) + 2 * (y % 2) : seed;
				if (!drawTile(g, t0 + "floor", X, Y, TW, TH, floorSeed)) { g.fillStyle = (x + y) % 2 ? pal.floorA : pal.floorB; g.fillRect(X, Y, P, P); }
				if (t === "o" && !drawTile(g, t0 + "rock", X, Y, TW, TH, seed)) {
					g.fillStyle = COLORS.rock; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.84);
					g.fillStyle = COLORS.rockTop; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.22);
				}
			}
		}
	}
	drawEdges(g, st, ox, oy, px, { x0, x1, y0, y1 }, pal === FRACTURE && sprite("rift.fracture.buttress"));
	drawDecor(g, st, ox, oy, px, { x0, x1, y0, y1 }, pal);
}

/* DECORATIONS (art.js DECO_PARTS): where each goes is worked out once per map, from
 * the map alone, so the same map is always dressed the same way and the sim never
 * knows. Lights and hangings go on the walls that face INTO a room (a run of wall
 * with plain floor below it): a light at each end of the run, hangings between;
 * growth in a room's corners and now and then along a wall; scatter here and there on
 * open floor. All of it is drawn under everything that moves. */
const placed = new WeakMap();
function noise(x, y, k = 0) {
	let h = Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(k, 1442695041) | 0;
	h = Math.imul(h ^ (h >>> 13), 1274126177);
	return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
export function decorations(st) {
	let list = placed.get(st.tiles);
	if (list) return list;
	list = [];
	const at = (x, y) => st.tiles[y]?.[x], wall = (x, y) => isWall(st, x, y);
	const front = new Set();
	for (let y = 0; y < st.h; y++) {
		let start = -1;
		for (let x = 0; x <= st.w; x++) {
			const ok = x < st.w && at(x, y) === "#" && at(x, y + 1) === "." && !deepWall(st, x, y);
			if (ok && start < 0) start = x;
			if (!ok && start >= 0) {
				const L = x - start;
				if (L >= 3) {
					const k = Math.max(2, Math.floor((L - 3) / 3) + 1);
					for (let i = 0; i < k; i++) {
						const p = start + Math.round(1 + i * (L - 3) / (k - 1)), end = i === 0 || i === k - 1;
						if (!end && noise(p, y, 1) > 0.75) continue;
						list.push({ part: end ? "light" : "hang", x: p, y });
						front.add(p + "," + y);
					}
				}
				start = -1;
			}
		}
	}
	for (let y = 0; y < st.h; y++) for (let x = 0; x < st.w; x++) {
		if (at(x, y) !== ".") continue;
		const N = wall(x, y - 1), S = wall(x, y + 1), W = wall(x - 1, y), E = wall(x + 1, y), r = noise(x, y, 2);
		if (N && front.has(x + "," + (y - 1))) continue;           // under a light or hanging
		const corner = (N || S) && (W || E);
		if ((corner && r < (N ? 0.6 : 0.35)) || (!corner && (N || W || E) && r < 0.05))
			list.push({ part: "growth", x, y, dx: W ? 0.3 : E ? 0.7 : 0.25 + 0.5 * noise(x, y, 3) });
		else if (!N && !S && !W && !E && r > 0.965)
			list.push({ part: "scatter", x, y, dx: 0.25 + 0.5 * noise(x, y, 4), dy: 0.25 + 0.5 * noise(x, y, 5) });
	}
	placed.set(st.tiles, list);
	return list;
}
/* A decoration is drawn ONLY from its picture: the stand-in shapes tried first (a
 * yellow block for a torch, a strip for a banner) looked comically bad to the owner
 * (2026-11-19), and a room with nothing on its walls looks better than one with
 * placeholders on them. So a place stays bare until its decorations are made. */
const DECO_Y = { light: 0.55, hang: 0.12, growth: 0.95, scatter: null };   // where on its tile each sits (scatter: its own spot)
function drawDecor(g, st, ox, oy, px, { x0, x1, y0, y1 }, pal) {
	const keys = Object.fromEntries(Object.keys(DECO_Y).map((part) => [part, `deco.${pal.id}.${part}`]));
	if (!Object.values(keys).some(sprite)) return;
	for (const d of decorations(st)) {
		if (d.x < x0 - 1 || d.x > x1 + 1 || d.y < y0 - 1 || d.y > y1 + 1) continue;
		const fy = DECO_Y[d.part];
		const X = ox + (d.x + (d.dx ?? 0.5)) * px, Y = oy + (d.y + (fy ?? d.dy)) * px;
		if (pal === FRACTURE && d.part === "light" && sprite(keys.light)) {
			const step = Math.max(1, Math.round(px / artPx()));
			const x = Math.round(X / step) * step, y = Math.round(Y / step) * step;
			g.fillStyle = "rgba(235,129,48,.10)"; g.fillRect(x - step * 8, y - step * 4, step * 16, step * 15);
			g.fillStyle = "rgba(255,161,61,.12)"; g.fillRect(x - step * 5, y - step * 3, step * 10, step * 10);
		}
		drawSprite(g, keys[d.part], X, Y, px, { seed: d.x * 7 + d.y * 13 });
	}
}

/* THE ROOM'S EDGES, drawn over the tiles on the art's own pixel grid (one art pixel
 * is a tile / artPx): what makes a room read as a SHAPE rather than wallpaper, after
 * the owner's reference room (2026-11-19) — a thick dark outline wherever wall meets
 * floor, and the floor in shadow along its walls (deepest under the wall to the north,
 * since the light comes from above). The inside of a wall no floor touches is drawn
 * as the dark beyond (in drawMap), so every wall is a band one tile thick. */
const isWall = (st, x, y) => x < 0 || y < 0 || x >= st.w || y >= st.h || st.tiles[y][x] === "#";
export function deepWall(st, x, y) {
	for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (!isWall(st, x + dx, y + dy)) return false;
	return true;
}
const OUTLINE = PALETTE.outline[0], SHADE = "20,17,26";
function drawEdges(g, st, ox, oy, px, { x0, x1, y0, y1 }, buttresses) {
	const a = px / (artPx() || 16), n = (k) => Math.max(1, Math.round(k * a));
	const o = n(2);                                         // the outline: two art pixels
	for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
		const X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
		const W = Math.floor(ox + (x + 1) * px) - X, H = Math.floor(oy + (y + 1) * px) - Y;
		const N = isWall(st, x, y - 1), S = isWall(st, x, y + 1), Wl = isWall(st, x - 1, y), E = isWall(st, x + 1, y);
		if (isWall(st, x, y)) {
			if (deepWall(st, x, y)) continue;
			// A wall facing the room below shows its FRONT: the lower part of the tile in
			// shadow under a lit lip, so the wall reads as standing up out of the floor.
			if (!S) {
				const f = n(6);
				g.fillStyle = `rgba(${SHADE},.34)`; g.fillRect(X, Y + H - f, W, f);
				g.fillStyle = "rgba(255,255,255,.16)"; g.fillRect(X, Y + H - f - n(1), W, n(1));
			}
			// The outline: on every side that meets floor, and on the outer side, where
			// the band meets the dark (the reference room has both).
			const out = (dx, dy) => !isWall(st, x + dx, y + dy) || deepWall(st, x + dx, y + dy);
			g.fillStyle = OUTLINE;
			if (out(0, -1)) g.fillRect(X, Y, W, o);
			if (out(0, 1)) g.fillRect(X, Y + H - o, W, o);
			if (out(-1, 0)) g.fillRect(X, Y, o, H);
			if (out(1, 0)) g.fillRect(X + W - o, Y, o, H);
			// an outer corner (floor only on the diagonal) would leave a notch
			if (!out(0, -1) && !out(-1, 0) && out(-1, -1)) g.fillRect(X, Y, o, o);
			if (!out(0, -1) && !out(1, 0) && out(1, -1)) g.fillRect(X + W - o, Y, o, o);
			if (!out(0, 1) && !out(-1, 0) && out(-1, 1)) g.fillRect(X, Y + H - o, o, o);
			if (!out(0, 1) && !out(1, 0) && out(1, 1)) g.fillRect(X + W - o, Y + H - o, o, o);
			if (buttresses) {
				const horizontal = !N || !S, vertical = !Wl || !E;
				const corner = horizontal && vertical;
				// Stone caps mark corners and break up long runs without adding collision.
				if (corner || (horizontal && x % 7 === 3) || (vertical && y % 5 === 2))
					drawTile(g, "rift.fracture.buttress", X, Y, W, H);
			}
			continue;
		}
		// The floor's shadow: two steps under a north wall, one beside a side wall.
		const shade = (alpha, x, y, w, h) => { g.fillStyle = `rgba(${SHADE},${alpha})`; g.fillRect(x, y, w, h); };
		if (N) { shade(0.42, X, Y, W, n(3)); shade(0.22, X, Y + n(3), W, n(4)); }
		if (Wl) { shade(0.30, X, Y, n(2), H); shade(0.14, X + n(2), Y, n(2), H); }
		if (E) { shade(0.30, X + W - n(2), Y, n(2), H); shade(0.14, X + W - n(4), Y, n(2), H); }
		if (S) shade(0.16, X, Y + H - n(1), W, n(1));
		if (!N && !Wl && isWall(st, x - 1, y - 1)) shade(0.30, X, Y, n(2), n(3));
		if (!N && !E && isWall(st, x + 1, y - 1)) shade(0.30, X + W - n(2), Y, n(2), n(3));
		// Water and torn floor sit BELOW the floor: an outline round them, their own
		// shadow under the near (north) lip, and the far lip catching the light.
		const t = st.tiles[y][x];
		if (t === "~" || t === "x") {
			const lip = (dx, dy) => { const c = st.tiles[y + dy]?.[x + dx]; return c !== undefined && c !== t && c !== "#"; };
			g.fillStyle = OUTLINE;
			if (lip(0, -1)) g.fillRect(X, Y, W, n(1));
			if (lip(0, 1)) g.fillRect(X, Y + H - n(1), W, n(1));
			if (lip(-1, 0)) g.fillRect(X, Y, n(1), H);
			if (lip(1, 0)) g.fillRect(X + W - n(1), Y, n(1), H);
			if (lip(0, -1)) shade(0.38, X, Y + n(1), W, n(3));
			if (lip(-1, 0)) shade(0.22, X + n(1), Y, n(2), H);
			if (lip(0, 1)) { g.fillStyle = "rgba(255,255,255,.22)"; g.fillRect(X, Y + H - n(2), W, n(1)); }
		}
	}
}

/* CRACKS (sim.js): a faint seam while closed, a bright flickering one in the second
 * before it opens, and the void while open. */
function drawCracks(g, st, ox, oy, px, calm) {
	if (!st.cracks?.length) return;
	const step = Math.max(1, Math.round(px / artPx()));
	const open = new Set();
	const isVoid = (x, y) => st.tiles[y]?.[x] === "x" || (x >= 0 && x < st.w && open.has(y * st.w + x));
	for (const c of st.cracks) {
		if (c.open) for (const [x, y] of c.tiles) open.add(y * st.w + x);
	}
	for (const c of st.cracks) {
		const group = new Set(c.tiles.map(([x, y]) => y * st.w + x));
		for (const [x, y] of c.tiles) {
			const X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
			const W = Math.floor(ox + (x + 1) * px) - X, H = Math.floor(oy + (y + 1) * px) - Y;
			if (c.open) {
				if (!drawTile(g, "tile.fracture.void", X, Y, W, H, x * 7 + y * 13)) {
					g.fillStyle = COLORS.void; g.fillRect(X, Y, W, H);
				}
				g.fillStyle = "#211832";
				if (!isVoid(x, y - 1)) g.fillRect(X, Y, W, step);
				if (!isVoid(x - 1, y)) g.fillRect(X, Y, step, H);
				g.fillStyle = "#675481";
				if (!isVoid(x, y + 1)) g.fillRect(X, Y + H - step, W, step);
				if (!isVoid(x + 1, y)) g.fillRect(X + W - step, Y, step, H);
			} else {
				const pulse = calm || st.tick % 8 < 5;
				if (c.warn) {
					g.fillStyle = pulse ? "rgba(205,168,247,.40)" : "rgba(185,150,255,.23)"; g.fillRect(X, Y, W, H);
				}
				const vertical = group.has((y - 1) * st.w + x) || group.has((y + 1) * st.w + x);
				const rot = vertical ? 0 : Math.PI / 2;
				const alpha = c.warn ? (pulse ? 1 : 0.72) : 0.18;
				if (!drawSprite(g, "rift.fracture.crack", X + W / 2, Y + H / 2, px, { rot, alpha })) {
					g.fillStyle = c.warn ? COLORS.seamHot : COLORS.seam;
					g.fillRect(X + px * 0.15, Y + px * 0.45, px * 0.7, Math.max(1, px * (c.warn ? 0.10 : 0.06)));
				}
			}
		}
	}
}

/* The doors of rooms that still hold enemies (sim.js): a faint red veil before the
 * room is entered (shots stop there; you can walk through), iron bars once it is
 * sealed. A cleared room's doorway is plain floor. */
function drawDoors(g, st, ox, oy, px) {
	if (!st.doorCols) return;
	const P = Math.ceil(px) + 1, Y = Math.floor(oy + (st.doorY - 1) * px), H = px * 3;
	const paneled = st.dungeonId === "fracture" && sprite("rift.fracture.gate");
	st.doorCols.forEach((room, x) => {
		if (room < 0 || !(st.roomLeft[room] > 0)) return;
		const X = Math.floor(ox + x * px);
		if (st.sealed === room) {
			if (paneled) {
				const W = Math.floor(ox + (x + 1) * px) - X;
				g.fillStyle = "#281f34"; g.fillRect(X, Y, W, H);
				for (let y = st.doorY - 1; y <= st.doorY + 1; y++) {
					const top = Math.floor(oy + y * px), height = Math.floor(oy + (y + 1) * px) - top;
					drawTile(g, "rift.fracture.gate", X, top, W, height);
				}
				return;
			}
			g.fillStyle = COLORS.bars; g.fillRect(X, Y, P, H);
			g.fillStyle = COLORS.barsLit;
			for (let k = 0; k < 4; k++) g.fillRect(X + px * (0.12 + k * 0.24), Y, Math.max(2, px * 0.08), H);
		} else {
			g.fillStyle = COLORS.veil; g.fillRect(X, Y, P, H);
			g.fillStyle = COLORS.veilEdge; g.fillRect(X + px * 0.45, Y, Math.max(1, px * 0.1), H);
		}
	});
}

function circle(g, x, y, r, fill) {
	g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = fill; g.fill();
}

/* Where the world sits on the canvas: it follows the player (at `at`, the drawn —
 * interpolated — position), clamped so the map never scrolls past its edge. The page
 * uses it too, to turn the mouse into aim. */
/* The dungeon camera FOLLOWS the player everywhere (owner's ask, 2026-11-18: it
 * sat still at the start until you walked off the map's edge); the void past the
 * map is drawn as the background. The town still fits its plaza to the stage. */
export function camera(st, width, height, px, at = st.p, follow = false) {
	if (follow) return { ox: width / 2 - at.x * px, oy: height / 2 - at.y * px };
	const vw = width / px, vh = height / px;
	const cx = st.w < vw ? st.w / 2 : Math.max(vw / 2, Math.min(st.w - vw / 2, at.x));
	const cy = st.h < vh ? st.h / 2 : Math.max(vh / 2, Math.min(st.h - vh / 2, at.y));
	return { ox: width / 2 - cx * px, oy: height / 2 - cy * px };
}

/* One frame, at `px` pixels a tile. `at(obj)` is where to DRAW a moving thing —
 * the page passes its position interpolated between the last two ticks, so motion
 * is smooth at any refresh rate while the simulation stays a fixed 60 Hz. */
const here = (o) => o;
export function draw(g, st, { width, height, px, aim, notes = [], at = here, bagBest = () => ({ tier: 1 }),
	calm = false, ui = 1, dpr = 1, bossName = "The boss", keys = {}, mods = [], auto = false }) {
	const p = st.p, pp = at(p);
	const { ox, oy } = camera(st, width, height, px, pp, true);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;

	const pal = PALETTES[st.dungeonId] || SHALLOWS;
	g.fillStyle = pal.deep; g.fillRect(0, 0, width, height);
	drawMap(g, st, ox, oy, px, width, height, pal);
	drawCracks(g, st, ox, oy, px, calm);
	drawDoors(g, st, ox, oy, px);
	drawHazards(g, st, sx, sy, px);
	drawAbilityFx(g, st, sx, sy, px, pp);
	if (st.shield) {
		circle(g, sx(st.shield.x), sy(st.shield.y), px * st.shield.r, COLORS.shield);
		g.strokeStyle = "#fff0b7"; g.lineWidth = Math.max(2, px * 0.08);
		g.beginPath(); g.arc(sx(st.shield.x), sy(st.shield.y), px * st.shield.r, 0, Math.PI * 2); g.stroke();
	}

	for (const h of st.pickups) {                     // healing: green, a cross
		const X = sx(h.x), Y = sy(h.y), s = px * 0.16;
		circle(g, X, Y, px * 0.3, "rgba(111,211,106,.28)");
		g.fillStyle = COLORS.heal; g.fillRect(X - s * 1.5, Y - s / 2, s * 3, s); g.fillRect(X - s / 2, Y - s * 1.5, s, s * 3);
	}
	for (const b of st.bags) {                        // loot: the color of its best item
		const X = sx(b.x), Y = sy(b.y), best = bagBest(b);
		const col = best.unique ? UNIQUE_COLOR : TIER_COLORS[best.tier] || COLORS.bag;
		if (best.unique) {
			const pulse = calm ? 0.5 : 0.5 + 0.5 * Math.sin(st.tick / 10);
			circle(g, X, Y, px * (0.48 + 0.08 * pulse), "rgba(255,216,94,.28)");
		} else if (best.tier >= 3) circle(g, X, Y, px * 0.42, col + "33");
		g.fillStyle = col; g.fillRect(X - px * 0.22, Y - px * 0.18, px * 0.44, px * 0.38);
		g.fillStyle = "rgba(20,16,10,.55)"; g.fillRect(X - px * 0.22, Y - px * 0.06, px * 0.44, px * 0.05);
	}
	for (const f of st.floor || []) {                 // what the player put down: pale, a bundle
		const X = sx(f.x), Y = sy(f.y);
		g.fillStyle = "#c9cfd6"; g.fillRect(X - px * 0.18, Y - px * 0.16, px * 0.36, px * 0.32);
		g.fillStyle = "#6c747d"; g.fillRect(X - px * 0.18, Y - px * 0.04, px * 0.36, px * 0.05);
	}
	if (st.portal) {
		const pulse = 0.5 + 0.5 * Math.sin(st.tick / 9);
		circle(g, sx(st.portal.x), sy(st.portal.y), px * (0.55 + 0.1 * pulse), "rgba(159,231,255,.35)");
		circle(g, sx(st.portal.x), sy(st.portal.y), px * 0.32, COLORS.portal);
	}
	if (st.deeper) {                                  // the way deeper: ember orange, a dark heart
		const pulse = 0.5 + 0.5 * Math.sin(st.tick / 7);
		circle(g, sx(st.deeper.x), sy(st.deeper.y), px * (0.58 + 0.12 * pulse), "rgba(255,159,90,.32)");
		circle(g, sx(st.deeper.x), sy(st.deeper.y), px * 0.34, COLORS.deeper);
		circle(g, sx(st.deeper.x), sy(st.deeper.y), px * 0.14, "#3a1a10");
	}

	for (const e of st.enemies) {
		if (e.hp <= 0 || e.dormant) continue;
		const ep = at(e), X = sx(ep.x), Y = sy(ep.y), r = e.r * px;
		// The Breach's fault lines: dashed, thickening until they tear.
		if (e.faults && e.faultT > 0 && e.active) {
			const k = 1 - e.faultT / FAULT.tele;
			g.strokeStyle = `rgba(255,90,74,${0.3 + 0.55 * k})`; g.lineWidth = Math.max(1, px * (0.05 + 0.22 * k));
			g.setLineDash?.([px * 0.3, px * 0.2]);
			for (const [vx, vy, len] of e.faults) { g.beginPath(); g.moveTo(X, Y); g.lineTo(X + vx * len * px, Y + vy * len * px); g.stroke(); }
			g.setLineDash?.([]);
		}
		// Telegraphs: what is about to fire says so, and says where.
		if (e.tele > 0 && e.active) {
			g.strokeStyle = COLORS.tele; g.lineWidth = Math.max(1, px * 0.05);
			if (e.toX || e.toY) {                         // a blink: where it will land
				const k = 1 - e.tele / 40;
				g.strokeStyle = COLORS[e.form || e.type] || COLORS.tele;
				g.setLineDash?.([px * 0.18, px * 0.14]);
				g.beginPath(); g.arc(sx(e.toX), sy(e.toY), r * (1.4 - 0.4 * Math.min(1, k)), 0, Math.PI * 2); g.stroke();
				g.setLineDash?.([]);
			} else if (e.type === "shooter" || e.type === "splitter") {
				g.beginPath(); g.moveTo(X, Y); g.lineTo(sx(pp.x), sy(pp.y)); g.stroke();
			} else {
				const grow = e.type === "boss" && e.phase === 0 ? 1.6 : 1 + (1 - e.tele / 50) * 0.8;
				g.beginPath(); g.arc(X, Y, r * grow + px * 0.2, 0, Math.PI * 2); g.stroke();
			}
		}
		if (e.burnUntil > st.tick) {                      // burning (the Ember Loop): an orange ring
			g.strokeStyle = "#ff8a3c"; g.lineWidth = Math.max(1, px * 0.06);
			g.beginPath(); g.arc(X, Y, r + px * 0.1, 0, Math.PI * 2); g.stroke();
		}
		// Reduced flashing (a setting): a hit tints, and the boss's turn holds still.
		const col = e.flash > 0 ? (calm ? "#f3b9a8" : "#fff3ea")
			: e.form === "breach" || e.form === "pyre" ? COLORS[e.form] : e.type === "smolder" && e.lit ? COLORS.smolderLit : COLORS[e.type];
		drawEnemyBody(g, st, e, X, Y, px, col, calm, { x: pp.x - ep.x, y: pp.y - ep.y });
		if (e.ward > 0) {                                 // Warded: one pip per hit it will still ignore
			const n = e.ward, gap = px * 0.16, w0 = (n - 1) * gap, py = Y + r + px * 0.2;
			for (let k = 0; k < n; k++) circle(g, X - w0 / 2 + k * gap, py, Math.max(1.5, px * 0.055), COLORS.ward);
		}
		if (e.active && e.hp < e.maxHp) {
			const w = Math.max(px * 0.8, r * 2);
			g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(X - w / 2, Y - r - px * 0.28, w, px * 0.09);
			g.fillStyle = COLORS.hp; g.fillRect(X - w / 2, Y - r - px * 0.28, w * (e.hp / e.maxHp), px * 0.09);
		}
	}

	drawPlayer(g, p, sx(pp.x), sy(pp.y), px, aim, st.classId, calm, st.tick);

	drawShots(g, st.bullets, sx, sy, px, at);
	drawDamageNumbers(g, st.damageNumbers || [], sx, sy, px, st.tick);
	drawHud(g, st, { width, height, px, notes, ui, keys, auto });
	drawBossBar(g, st, { width, ui, name: bossName });
	drawMinimap(g, st, { width, ui, dpr, bagBest, mods });
}

/* One enemy's body at (X, Y): its picture, facing the player, when there is one —
 * a hit flashes it brighter — else its greybox shape in `col`. Exported for the art
 * gallery, which draws every enemy on every rift's floor. */
export function drawEnemyBody(g, st, e, X, Y, px, col, calm = false, facing = null) {
	const r = e.r * px, key = `enemy.${e.form || e.type}`, opt = { facing, tick: st.tick };
	if (drawSprite(g, key, X, Y, px, opt)) {
		if (e.flash > 0) {
			g.save(); g.globalCompositeOperation = "lighter";
			drawSprite(g, key, X, Y, px, { ...opt, alpha: calm ? 0.25 : 0.55 });
			g.restore();
		}
		return;
	}
	if (e.type === "chaser") {
		g.save(); g.translate(X, Y); g.rotate(Math.PI / 4); g.fillStyle = col; g.fillRect(-r * 0.8, -r * 0.8, r * 1.6, r * 1.6); g.restore();
	} else if (e.type === "shooter") {
		g.beginPath(); g.moveTo(X, Y - r); g.lineTo(X + r, Y + r * 0.8); g.lineTo(X - r, Y + r * 0.8); g.closePath(); g.fillStyle = col; g.fill();
	} else if (e.type === "radial") {
		circle(g, X, Y, r, col); circle(g, X, Y, r * 0.45, "#5c1b3f");
	} else if (e.type === "shard") {                    // a crystal: a diamond with a cross
		g.beginPath(); g.moveTo(X, Y - r * 1.2); g.lineTo(X + r, Y); g.lineTo(X, Y + r * 1.2); g.lineTo(X - r, Y); g.closePath();
		g.fillStyle = col; g.fill();
		g.fillStyle = "#1d3a4a"; g.fillRect(X - r * 0.12, Y - r * 0.6, r * 0.24, r * 1.2); g.fillRect(X - r * 0.6, Y - r * 0.12, r * 1.2, r * 0.24);
	} else if (e.type === "splitter" || e.type === "splinter") {   // a split hexagon
		g.beginPath();
		for (let k = 0; k < 6; k++) { const a = Math.PI / 6 + k * Math.PI / 3; g[k ? "lineTo" : "moveTo"](X + Math.cos(a) * r, Y + Math.sin(a) * r); }
		g.closePath(); g.fillStyle = col; g.fill();
		if (e.type === "splitter") { g.fillStyle = "#3a160d"; g.fillRect(X - r * 0.08, Y - r, r * 0.16, r * 2); }
	} else if (e.type === "flicker") {                  // a ring that is not all there
		g.strokeStyle = col; g.lineWidth = Math.max(2, r * 0.45);
		g.beginPath(); g.arc(X, Y, r * 0.75, 0.3, Math.PI * 2 - 0.3); g.stroke();
		circle(g, X, Y, r * 0.25, col);
	} else if (e.type === "cinder") {                   // a flame: a teardrop pointing up
		g.beginPath(); g.moveTo(X, Y - r * 1.3); g.quadraticCurveTo(X + r * 1.1, Y + r * 0.2, X, Y + r);
		g.quadraticCurveTo(X - r * 1.1, Y + r * 0.2, X, Y - r * 1.3); g.fillStyle = col; g.fill();
		circle(g, X, Y + r * 0.3, r * 0.35, "#fff1c2");
	} else if (e.type === "kiln") {                     // a squat oven with a glowing mouth
		g.fillStyle = col; g.fillRect(X - r, Y - r * 0.9, r * 2, r * 1.8);
		g.fillStyle = "#2a1410"; g.fillRect(X - r * 0.55, Y - r * 0.1, r * 1.1, r * 0.7);
		g.fillStyle = e.tele > 0 ? "#ffd27a" : "#ff8a3c"; g.fillRect(X - r * 0.4, Y + r * 0.05, r * 0.8, r * 0.45);
	} else if (e.type === "smolder") {                  // a banked coal: dull until hit, then it glows
		circle(g, X, Y, r, col);
		g.strokeStyle = e.lit ? "#fff1c2" : "#ff7a2e"; g.lineWidth = Math.max(1, px * (e.lit ? 0.07 : 0.04));
		g.beginPath(); g.moveTo(X - r * 0.5, Y - r * 0.2); g.lineTo(X, Y + r * 0.15); g.lineTo(X + r * 0.45, Y - r * 0.35);
		g.moveTo(X, Y + r * 0.15); g.lineTo(X + r * 0.1, Y + r * 0.6); g.stroke();
	} else if (e.form === "pyre") {                     // the Pyre: a ring of flame tongues round a white-hot heart
		const n = 10, spin = st.tick * 0.03;
		g.beginPath();
		for (let k = 0; k < n * 2; k++) { const a = spin + k * Math.PI / n, rr = k % 2 ? r * 0.7 : r * 1.12; g[k ? "lineTo" : "moveTo"](X + Math.cos(a) * rr, Y + Math.sin(a) * rr); }
		g.closePath(); g.fillStyle = e.phase === 0 && !calm && st.tick % 10 < 5 ? "#fff3ea" : col; g.fill();
		circle(g, X, Y, r * 0.5, "#ffd27a");
		circle(g, X, Y, r * 0.26, "#fff7ec");
	} else if (e.form === "breach") {                   // the Breach: a torn violet star
		const n = 8, spin = st.tick * 0.02;
		g.beginPath();
		for (let k = 0; k < n * 2; k++) { const a = spin + k * Math.PI / n, rr = k % 2 ? r * 0.55 : r * 1.05; g[k ? "lineTo" : "moveTo"](X + Math.cos(a) * rr, Y + Math.sin(a) * rr); }
		g.closePath(); g.fillStyle = e.phase === 0 && !calm && st.tick % 10 < 5 ? "#fff3ea" : col; g.fill();
		circle(g, X, Y, r * 0.38, COLORS.void);
	} else {
		circle(g, X, Y, r, e.phase === 0 && !calm && st.tick % 10 < 5 ? "#fff3ea" : col);
		circle(g, X, Y, r * 0.55, "#5a1424");
	}
}

/* "Auto-fire" over the HP box while it is on (it stays on across town and runs, so
 * it must be visible). `bottom` is the top edge of what it sits on. */
function drawAutoTag(g, x, bottom, ui) {
	g.font = `600 ${Math.round(12 * ui)}px "Crimson Pro", Georgia, serif`;
	g.textBaseline = "middle"; g.textAlign = "left";
	const t = "Auto-fire", w = g.measureText(t).width + 14, h = Math.round(20 * ui);
	g.fillStyle = COLORS.hudBack; g.fillRect(x - 8, bottom - h - 6, w, h);
	g.fillStyle = "#e9c25a"; g.fillText(t, x - 1, bottom - h / 2 - 6);
}

/* The boss's health across the top of the stage while it fights (design §19.1),
 * with a mark at half: the phase change. */
function drawBossBar(g, st, { width, ui, name }) {
	const b = st.enemies.find((e) => e.type === "boss" && e.active && e.hp > 0);
	if (!b) return;
	const W = Math.min(width * 0.44, 520 * ui), H = Math.max(8, 12 * ui), X = width / 2 - W / 2, Y = 30 * ui;
	g.font = `600 ${Math.round(14 * ui)}px "Cinzel", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	g.fillStyle = "rgba(10,12,14,.75)"; g.fillText(name, width / 2 + 1, Y - 11 * ui + 1.5);
	g.fillStyle = "#f6c2bc"; g.fillText(name, width / 2, Y - 11 * ui);
	g.textAlign = "left";
	g.fillStyle = "rgba(10,12,14,.78)"; g.fillRect(X - 3, Y - 3, W + 6, H + 6);
	g.fillStyle = "#3a1f24"; g.fillRect(X, Y, W, H);
	g.fillStyle = COLORS.boss; g.fillRect(X, Y, W * (b.hp / b.maxHp), H);
	if (b.phase === 1) { g.fillStyle = "rgba(255,240,235,.8)"; g.fillRect(X + W / 2 - 1, Y - 2, 2, H + 4); }
	if (b.ward > 0) {
		g.font = `${Math.round(11 * ui)}px "Crimson Pro", Georgia, serif`;
		g.fillStyle = COLORS.ward; g.textAlign = "right";
		g.fillText(`Warded ×${b.ward}`, X + W, Y + H + 10 * ui);
		g.textAlign = "left";
	}
}

/* The minimap, top right under the timer (design §19.1: it replaces off-screen
 * arrows). The dungeon is one line of rooms, so the whole map fits a strip: a
 * room still to fight is dark, the sealed one red, a cleared one green-gray; the
 * player, the portals and the loot bags are dots on it. */
const MINI = { open: "#5c645f", ahead: "#2f3437", sealed: "#a5443f", cleared: "#4f7262", boss: "#4a2a33" };
function drawMinimap(g, st, { width, ui, dpr, bagBest, mods = [] }) {
	if (!st.rooms?.length) return;
	const W = Math.min(width * 0.3, 240 * ui * dpr), m = W / st.w, H = st.h * m;
	const X = width - 16 - W, Y = 90 * dpr;                         // under the timer and the Menu button
	g.fillStyle = "rgba(10,12,14,.66)"; g.fillRect(X - 5, Y - 5, W + 10, H + 10);
	const roomOf = new Array(st.w).fill(-1);
	st.rooms.forEach((r, i) => { for (let x = r.x0; x < r.x1; x++) roomOf[x] = i; });
	const colorAt = (x) => {
		const i = roomOf[x];
		if (i < 0) return MINI.open;
		if (st.sealed === i) return MINI.sealed;
		if (st.roomLeft[i] > 0) return st.rooms[i].kind === "boss" ? MINI.boss : MINI.ahead;
		return st.rooms[i].kind === "entrance" ? MINI.open : MINI.cleared;
	};
	for (let y = 0; y < st.h; y++) {                          // floor, in runs of one color
		const row = st.tiles[y];
		let x = 0;
		while (x < st.w) {
			if (row[x] === "#") { x++; continue; }
			const c = colorAt(x);
			let e = x + 1;
			while (e < st.w && row[e] !== "#" && colorAt(e) === c) e++;
			g.fillStyle = c; g.fillRect(X + x * m, Y + y * m, (e - x) * m + 0.5, m + 0.5);
			x = e;
		}
	}
	const dot = (o, r, c) => circle(g, X + o.x * m, Y + o.y * m, Math.max(1.5, r * ui * dpr), c);
	for (const b of st.bags) { const best = bagBest(b); dot(b, 2, best.unique ? UNIQUE_COLOR : TIER_COLORS[best.tier] || COLORS.bag); }
	if (st.portal) dot(st.portal, 2.6, COLORS.portal);
	if (st.deeper) dot(st.deeper, 2.6, COLORS.deeper);
	dot(st.p, 2.8, "#ffffff");
	// THE RUN'S MODIFIERS, under the map (owner's ask, 2026-11-18: viewable in a run).
	if (mods.length) {
		const fs = Math.round(12 * ui * dpr), lh = fs + 4 * dpr;
		g.font = `${fs}px "Crimson Pro", Georgia, serif`;
		g.textAlign = "right"; g.textBaseline = "middle";
		const w = Math.max(...mods.map((t) => g.measureText(t).width)) + 16;
		const top = Y + H + 10;
		g.fillStyle = "rgba(10,12,14,.66)"; g.fillRect(X + W + 5 - w, top, w, mods.length * lh + 8);
		mods.forEach((t, i) => { g.fillStyle = "#f6c2bc"; g.fillText(t, X + W - 3, top + 4 + lh * i + lh / 2); });
		g.textAlign = "left";
	}
}

/* The boss's mortar: burning ground (a flickering orange pool that fades in its last
 * second), and each shell's landing spot, ringed red and filling as it comes. */
function drawHazards(g, st, sx, sy, px) {
	for (const f of st.embers || []) {                // the player's own fire: pale blue, white at heart
		const left = f.until - st.tick, fade = Math.min(1, left / TPS);
		const flick = 0.85 + 0.15 * Math.sin((st.tick + f.y * 7) * 0.35);
		circle(g, sx(f.x), sy(f.y), px * f.r, `rgba(120,214,255,${(0.28 * fade * flick).toFixed(3)})`);
		circle(g, sx(f.x), sy(f.y), px * f.r * 0.55, `rgba(230,250,255,${(0.2 * fade * flick).toFixed(3)})`);
	}
	for (const f of st.fires || []) {
		const left = f.until - st.tick, fade = Math.min(1, left / TPS);
		const flick = 0.85 + 0.15 * Math.sin((st.tick + f.x * 7) * 0.35);
		circle(g, sx(f.x), sy(f.y), px * f.r, `rgba(255,112,40,${(0.34 * fade * flick).toFixed(3)})`);
		circle(g, sx(f.x), sy(f.y), px * f.r * 0.6, `rgba(255,190,80,${(0.22 * fade * flick).toFixed(3)})`);
	}
	const lw = Math.max(1.5, px * 0.07);
	for (const m of st.mortars || []) {
		const k = Math.min(1, Math.max(0, 1 - (m.at - st.tick) / (m.d || MORTAR.delay)));
		const vent = m.src === VENT.impact;
		g.strokeStyle = vent ? "#ffc261" : "#ff5a3c"; g.lineWidth = lw;
		g.beginPath(); g.arc(sx(m.x), sy(m.y), px * m.r, 0, Math.PI * 2); g.stroke();
		circle(g, sx(m.x), sy(m.y), px * m.r * k, vent ? "rgba(255,164,58,.32)" : "rgba(255,90,60,.3)");
	}
}

/* What an ability leaves on the ground: the Paladin's field (gold, around the player),
 * a falling star (its spot ringed, filling as it comes) and its blast, and the
 * Ninja's counter — a white ring while it is ready to catch a hit, a solid guard
 * just after, and a gold ring while the next shot is countered. Shared by the town. */
function drawAbilityFx(g, st, sx, sy, px, pp) {
	const p = st.p, lw = Math.max(1, px * 0.05);
	if (st.slowUntil > st.tick) {
		const c = st.slowAt || pp;                          // the Anchor Orb's field stays where it was cast
		circle(g, sx(c.x), sy(c.y), px * (st.slowR || 3), COLORS.slow);
		g.strokeStyle = COLORS.paladin; g.lineWidth = lw;
		g.beginPath(); g.arc(sx(c.x), sy(c.y), px * (st.slowR || 3), 0, Math.PI * 2); g.stroke();
	}
	for (const f of st.starfalls || []) {
		const k = Math.min(1, Math.max(0, 1 - (f.at - st.tick) / STARFALL_DELAY));
		g.strokeStyle = COLORS.star; g.lineWidth = lw;
		g.beginPath(); g.arc(sx(f.x), sy(f.y), px * f.r, 0, Math.PI * 2); g.stroke();
		circle(g, sx(f.x), sy(f.y), px * f.r * k, "rgba(255,233,166,.28)");
	}
	for (const b of st.blasts || []) {
		const a = Math.max(0, (b.until - st.tick) / 18);
		circle(g, sx(b.x), sy(b.y), px * b.r * (1.1 - 0.1 * a), b.hot ? `rgba(255,140,70,${(0.75 * a).toFixed(3)})` : `rgba(255,240,190,${(0.75 * a).toFixed(3)})`);
	}
	const X = sx(pp.x), Y = sy(pp.y), R = px * (p.r + 0.22);
	if (p.counterUntil >= st.tick) {
		g.strokeStyle = "rgba(255,255,255,.85)"; g.lineWidth = Math.max(1.5, px * 0.06);
		g.beginPath(); g.arc(X, Y, R, 0, Math.PI * 2); g.stroke();
	}
	if (p.guardUntil > st.tick) circle(g, X, Y, R, "rgba(255,255,255,.35)");
	if (p.empower > 0) {                                    // the next shot is countered: gold, as it will be
		circle(g, X, Y, R * 1.2, "rgba(255,196,80,.22)");
		g.strokeStyle = "#ffb43c"; g.lineWidth = Math.max(1.5, px * 0.05);
		g.beginPath(); g.arc(X, Y, R * 1.2, 0, Math.PI * 2); g.stroke();
	}
}

/* A countered (empowered) shot is drawn as its own thing (owner's ask, 2026-11-18):
 * a gold-white core twice the size, a pulsing halo and a long gold trail, so the
 * one doubled shot is unmistakable in a crowd of ordinary ones. */
function drawPowerTrail(g, X, Y, b, px) {
	const L = px * 0.09, pulse = 0.75 + 0.25 * Math.sin((b.x + b.y) * 3);
	g.lineCap = "round";
	g.strokeStyle = "rgba(255,196,80,.35)"; g.lineWidth = Math.max(4, px * 0.42);
	g.beginPath(); g.moveTo(X, Y); g.lineTo(X - b.vx * L, Y - b.vy * L); g.stroke();
	g.strokeStyle = "rgba(255,240,200,.9)"; g.lineWidth = Math.max(2, px * 0.14);
	g.beginPath(); g.moveTo(X, Y); g.lineTo(X - b.vx * L * 0.6, Y - b.vy * L * 0.6); g.stroke();
	g.lineCap = "butt";
	circle(g, X, Y, px * 0.5 * pulse, "rgba(255,206,92,.28)");
}

const PLAYER_SHOTS = { bolt: "bolt", slash: "slash", star: "star", blade: "blade", gale: "gale", flare: "flare" };

/* Keep the hostile core the size of the collision circle. Each projectile PNG has
 * a one-pixel transparent border; friendly trails and empowered shots are cosmetic. */
function shotSprite(g, b, X, Y, px) {
	const friendly = b.owner === "p";
	const type = friendly
		? (b.power ? "power" : b.shard ? "blade" : PLAYER_SHOTS[b.look] || "player")
		: (b.shard ? "enemyShard" : b.dmg >= 30 ? "enemyHeavy" : "enemy");
	const key = "shot." + type, rec = sprite(key);
	if (!rec) return false;
	const size = friendly ? 1 : 2 * b.r * artPx() / Math.max(1, rec.sheet.h - 2);
	const rot = type === "star" ? (b.life || 0) * 0.35 : Math.atan2(b.vy, b.vx);
	return drawSprite(g, key, X, Y, px, { rot, size });
}
export function drawShots(g, bullets, sx, sy, px, at) {
	for (const b of bullets) {
		const bp = at(b), X = sx(bp.x), Y = sy(bp.y);
		if (b.owner === "p" && b.power) drawPowerTrail(g, X, Y, b, px);
		if (shotSprite(g, b, X, Y, px)) continue;
		if (b.owner === "p" && b.look === "flare") {         // the Flare Bow's flare: a bright ball of fire
			circle(g, X, Y, px * 0.24, "rgba(120,214,255,.45)");
			circle(g, X, Y, px * 0.14, "#e6faff");
		} else if (b.owner === "p" && b.look === "star") {   // a spinning four-point star
			const r = px * 0.2 * (b.power ? 2 : 1), a = (b.x + b.y) * 2.4;
			g.fillStyle = b.power ? "#fff1c2" : "#dfe7ea";
			g.beginPath();
			for (let i = 0; i < 8; i++) {
				const rr = i % 2 ? r * 0.38 : r, t = a + (i * Math.PI) / 4;
				g.lineTo(X + Math.cos(t) * rr, Y + Math.sin(t) * rr);
			}
			g.closePath(); g.fill();
			if (b.power) { g.strokeStyle = "#ffb43c"; g.lineWidth = Math.max(1.5, px * 0.05); g.stroke(); }
		} else if (b.owner === "p") {
			g.strokeStyle = b.power ? "#fff1c2" : COLORS.playerShot;
			g.lineWidth = Math.max(2, b.r * px * (b.power ? 2 : 0.9));
			const tail = b.look === "blade" ? 0.022 : 0.03;
			g.beginPath(); g.moveTo(X, Y); g.lineTo(X - b.vx * tail * px, Y - b.vy * tail * px); g.stroke();
		} else if (b.shard) {                                 // a shatter shard: a crystal that will burst
			const r = b.r * px * 1.2;
			g.beginPath(); g.moveTo(X, Y - r); g.lineTo(X + r * 0.7, Y); g.lineTo(X, Y + r); g.lineTo(X - r * 0.7, Y); g.closePath();
			g.fillStyle = COLORS.enemyShotHeavy; g.fill();
			g.strokeStyle = "rgba(255,240,235,.9)"; g.lineWidth = Math.max(1, px * 0.05); g.stroke();
		} else {
			circle(g, X, Y, b.r * px * 1.15, "rgba(255,240,235,.9)");
			circle(g, X, Y, b.r * px, b.dmg >= 30 ? COLORS.enemyShotHeavy : COLORS.enemyShot);
		}
	}
}

/* The player: cyan body, white core, a tick toward the aim — or the class's picture,
 * facing the aim. A hit flashes it brighter. */
export function drawPlayer(g, p, PX, PY, px, aim, classId = "ranger", calm = false, tick = 0) {
	const key = `player.${classId}`, opt = { facing: aim, tick };
	if (drawSprite(g, key, PX, PY, px, opt)) {
		if (p.hurt > 0) {
			g.save(); g.globalCompositeOperation = "lighter";
			drawSprite(g, key, PX, PY, px, { ...opt, alpha: calm ? 0.25 : 0.55 });
			g.restore();
		}
		return;
	}
	const pr = p.r * px;
	const body = COLORS[classId] && classId !== "ranger" ? COLORS[classId] : COLORS.player;
	circle(g, PX, PY, pr + px * 0.06, p.hurt > 0 ? (calm ? "#e2564e" : "#ffffff") : "#1d5f6a");
	circle(g, PX, PY, pr, body);
	circle(g, PX, PY, pr * 0.42, COLORS.playerCore);
	if (aim) {
		const l = Math.hypot(aim.x, aim.y) || 1;
		g.strokeStyle = COLORS.playerCore; g.lineWidth = Math.max(1.5, px * 0.06);
		g.beginPath(); g.moveTo(PX + aim.x / l * pr * 1.2, PY + aim.y / l * pr * 1.2);
		g.lineTo(PX + aim.x / l * pr * 1.9, PY + aim.y / l * pr * 1.9); g.stroke();
	}
}

function drawDamageNumbers(g, numbers, sx, sy, px, tick) {
	g.font = `bold ${Math.round(Math.max(13, px * 0.38))}px "Crimson Pro", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	for (const f of numbers) {
		// Yours: red, "-7", over the player. What you dealt: pale gold, "7", over the enemy.
		const rise = ((f.foe ? 36 : 45) - (f.until - tick)) * 0.018;
		const n = Number.isInteger(f.amount) ? String(f.amount) : f.amount.toFixed(1);
		const text = f.foe ? n : `-${n}`, y = sy(f.y - (f.foe ? 0.25 : 0.55) - rise);
		if (f.foe && rise < 0.10) drawSprite(g, "shot.impact", sx(f.x), sy(f.y), px, { alpha: 1 - rise / 0.10 });
		g.fillStyle = "rgba(16,18,20,.8)"; g.fillText(text, sx(f.x) + 1, y + 1.5);
		g.fillStyle = f.foe ? "#ffe9a6" : COLORS.damage; g.fillText(text, sx(f.x), y);
	}
	g.textAlign = "left";
}

function label(g, text, X, Y, px, color = "#f4efe4") {
	g.font = `600 ${Math.round(Math.max(12, px * 0.36))}px "Cinzel", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	g.fillStyle = "rgba(10,12,14,.75)"; g.fillText(text, X + 1, Y + 1.5);
	g.fillStyle = color; g.fillText(text, X, Y);
	g.textAlign = "left";
}

/* The town (town.js): flagstones, the vault, the forge, a portal per realm. The
 * station in reach glows, and the prompt for it sits at the bottom of the view. */
const PROMPT = { vault: "Open the vault", forge: "Use the forge", dream: "Practice a rift", portal: "Enter" };
export function drawTown(g, st, { width, height, px, at = here, notes = [], prompt = null, aim = null, dps = () => 0, auto = false, ui = 1 }) {
	const pp = at(st.p);
	const { ox, oy } = camera(st, width, height, px, pp);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;
	g.fillStyle = TOWN.deep; g.fillRect(0, 0, width, height);
	drawMap(g, st, ox, oy, px, width, height, TOWN);
	if (st.fountain) drawSprite(g, "town.fountain", sx(st.fountain.x), sy(st.fountain.y), px);

	for (const s of st.stations) {
		const X = sx(s.x), Y = sy(s.y), lit = st.near === s.id;
		const gate = s.kind === "portal" || s.kind === "dream";
		const key = "town." + (s.kind === "portal" ? s.realm : s.kind);
		if (sprite(key)) {
			if (lit) circle(g, X, Y + px * 0.28, px * (gate ? 0.94 : 1.15), "rgba(205,198,251,.30)");
			drawSprite(g, key, X, Y, px);
		} else if (gate) {
			const pulse = 0.5 + 0.5 * Math.sin(st.tick / 14);
			const core = s.kind === "dream" ? COLORS.dream : COLORS.realm;
			circle(g, X, Y, px * (0.95 + 0.12 * pulse), lit ? "rgba(205,198,251,.45)" : "rgba(157,143,242,.28)");
			circle(g, X, Y, px * 0.7, core);
			circle(g, X, Y, px * 0.48, "#2a2350");
			circle(g, X, Y, px * (0.2 + 0.06 * pulse), COLORS.portal);
		} else {
			const W = s.hw * 2 * px, H = s.hh * 2 * px;
			if (lit) { g.fillStyle = "rgba(205,198,251,.35)"; g.fillRect(X - W / 2 - px * 0.14, Y - H / 2 - px * 0.14, W + px * 0.28, H + px * 0.28); }
			if (s.kind === "vault") {                    // a chest: wood, a gold band and lock
				g.fillStyle = COLORS.vault; g.fillRect(X - W / 2, Y - H / 2, W, H);
				g.fillStyle = "#58391f"; g.fillRect(X - W / 2, Y - H / 2, W, H * 0.38);
				g.fillStyle = COLORS.vaultTrim; g.fillRect(X - W / 2, Y - H * 0.14, W, H * 0.1);
				g.fillRect(X - px * 0.13, Y - H * 0.2, px * 0.26, px * 0.34);
			} else {                                    // a forge: stone hearth, the fire showing
				g.fillStyle = COLORS.forge; g.fillRect(X - W / 2, Y - H / 2, W, H);
				const glow = 0.75 + 0.25 * Math.sin(st.tick / 7);
				circle(g, X, Y + H * 0.08, px * 0.5 * glow, "rgba(239,138,58,.4)");
				circle(g, X, Y + H * 0.08, px * 0.3, COLORS.forgeFire);
				g.fillStyle = "#33373c"; g.fillRect(X - W / 2, Y - H / 2, W, H * 0.22);
			}
		}
		label(g, s.label, X, Y - (gate ? px * 1.25 : s.hh * px + px * 0.42), px,
			lit ? "#ffffff" : "#e6e1f7");
	}

	// What the player put down here: a small bag in its color, ringed while in reach.
	for (const f of st.floor || []) {
		const X = sx(f.x), Y = sy(f.y);
		if (st.nearFloor === f.key) circle(g, X, Y, px * 0.38, "rgba(255,255,255,.28)");
		if (f.color) circle(g, X, Y, px * 0.32, f.color + "99");
		if (!drawSprite(g, "town.bag", X, Y, px)) {
			circle(g, X, Y, px * 0.24, "#2b2418");
			circle(g, X, Y, px * 0.18, f.color || COLORS.bag);
		}
	}

	// The practice posts: a straw target on a stake, and what it is taking a second.
	for (const q of st.posts) {
		const X = sx(q.x), Y = sy(q.y), R = q.r * px;
		if (!drawSprite(g, "town.target", X, Y, px, { size: q.r / 0.45 })) {
			g.fillStyle = "#5a4127"; g.fillRect(X - px * 0.07, Y, px * 0.14, R * 1.3);
			circle(g, X, Y, R, "#c9a25e");
			circle(g, X, Y, R * 0.66, "#efe3c4");
			circle(g, X, Y, R * 0.33, "#c0503f");
		}
		const d = dps(q);
		// Below the stake: the hit numbers float up from above the post.
		if (d > 0) label(g, `${d} / s`, X, Y + R * 1.3 + px * 0.38, px, "#e9c25a");
	}
	drawHazards(g, st, sx, sy, px);                    // the player's own fire (the town has no other)
	drawAbilityFx(g, st, sx, sy, px, pp);
	drawPlayer(g, st.p, sx(pp.x), sy(pp.y), px, aim, st.classId, false, st.tick);
	drawShots(g, st.bullets, sx, sy, px, at);
	g.font = `bold ${Math.round(Math.max(12, px * 0.4))}px "Crimson Pro", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	for (const f of st.floats) {
		const age = 40 - (f.until - st.tick);
		if (age < 6) drawSprite(g, "shot.impact", sx(f.x), sy(f.y + 0.55), px, { alpha: (6 - age) / 6 });
		g.fillStyle = "#fff4d6"; g.fillText(f.text, sx(f.x), sy(f.y - age * 0.012));
	}
	g.textAlign = "left";

	if (prompt) {
		g.font = `${Math.round(Math.max(14, px * 0.42))}px "Crimson Pro", Georgia, serif`;
		const w = g.measureText(prompt).width + 32, Y = height - Math.max(28, px * 0.9);
		g.fillStyle = "rgba(16,18,20,.78)"; g.fillRect(width / 2 - w / 2, Y - 17, w, 34);
		g.fillStyle = "#f4efe4"; g.textAlign = "center"; g.textBaseline = "middle";
		g.fillText(prompt, width / 2, Y + 1);
		g.textAlign = "left";
	}
	if (auto) drawAutoTag(g, 24, height - 16, ui);
	drawNotes(g, notes, width, height, px);
}

/* What the prompt for a station says, given whether it can be used now. */
export function promptFor(station, ready = true) {
	if (!station) return null;
	if (station.kind === "portal") return ready ? `E — Enter ${station.label}` : "Make a character to enter";
	if (station.kind === "dream") return ready ? `E — ${PROMPT.dream}` : "Make a character to practice";
	return `E — ${PROMPT[station.kind]}`;
}

function drawHud(g, st, { width, height, px, notes, ui = 1, keys = {}, auto = false }) {
	const p = st.p, s = st.stats;
	const W = Math.min(320 * ui, width * 0.42), H = Math.max(10, px * 0.32) * ui, X = 16;
	const XH = Math.max(4, Math.round(H * 0.4)), Y = height - 16 - H * 2 - 8 - XH - 8;
	g.fillStyle = COLORS.hudBack; g.fillRect(X - 8, Y - 8, W + 16, H * 2 + XH + 32);
	if (auto) drawAutoTag(g, X, Y - 8, ui);
	// HP in three parts, as in the side panel: red what you have, light gray what
	// regeneration can bring back (to the recovery limit), dark gray what only a heal can.
	g.fillStyle = "#34383d"; g.fillRect(X, Y, W, H);
	g.fillStyle = "#8d9298"; g.fillRect(X, Y, W * (recoveryLimit(st) / s.maxHp), H);
	g.fillStyle = "#d5453b"; g.fillRect(X, Y, W * (p.hp / s.maxHp), H);
	g.fillStyle = "#1a2238"; g.fillRect(X, Y + H + 8, W, H);
	g.fillStyle = COLORS.mp; g.fillRect(X, Y + H + 8, W * (p.mp / s.maxMp), H);
	g.fillStyle = "#f4efe4"; g.font = `${Math.round(H * 0.85)}px "Crimson Pro", Georgia, serif`;
	g.textBaseline = "middle";
	g.fillText(`${Math.ceil(p.hp)} / ${Math.round(s.maxHp)}`, X + 6, Y + H / 2 + 1);
	g.fillText(`${Math.floor(p.mp)} / ${Math.round(s.maxMp)}`, X + 6, Y + H * 1.5 + 9);
	// Whether the ability can be cast, at the MP bar's right end: MP is its only limit.
	if (s.abilityKind) {
		const cost = s.abilityCost ?? ABILITY_COST, cd = p.abilityCd > 0, ok = p.mp >= cost && !cd;
		g.textAlign = "right";
		g.fillStyle = ok ? "#9fe7ff" : "#c9cfd6";
		g.fillText(ok ? "Ready" : cd ? `${Math.ceil(p.abilityCd / TPS)}s` : `${cost} MP`, X + W - 6, Y + H * 1.5 + 9);
		g.textAlign = "left";
	}
	// XP inside the level, and the level itself at the bar's right end.
	const xp = xpProgress(st.levels, st.hero.xp), XY = Y + H * 2 + 16;
	g.fillStyle = "rgba(157,143,242,.2)"; g.fillRect(X, XY, W, XH);
	g.fillStyle = COLORS.xp; g.fillRect(X, XY, W * (xp.span ? xp.into / xp.span : 1), XH);
	// The potion's cooldown at the HP bar's right end, then the level.
	const pcd = p.potionCd || 0, pk = keys.potion || "R";
	g.textAlign = "right";
	g.fillStyle = pcd > 0 ? "#c9cfd6" : "#9ff0a0";
	const ptxt = pcd > 0 ? `${pk} ${Math.ceil(pcd / TPS)}s` : `${pk} potion`;
	g.fillText(ptxt, X + W - 6, Y + H / 2 + 1);
	const pw = g.measureText(ptxt).width;
	g.fillStyle = "#f4efe4";
	g.fillText(`Lv ${st.hero.level}`, X + W - 18 - pw, Y + H / 2 + 1);
	g.textAlign = "left";
	const timer = formatRiftTime(st.bossTimeTicks == null ? st.elapsedTicks : st.bossTimeTicks);
	// The box fits its words: a level deeper adds "L2 " to the label.
	const label = `${st.practice ? "Dream " : "Rift "}${st.depth > 1 ? `L${st.depth} ` : ""}${timer}`;
	g.font = `${Math.round(Math.max(13, px * 0.38) * ui)}px "Crimson Pro", Georgia, serif`;
	const tw = Math.max(138, Math.ceil(g.measureText(label).width) + 22);
	g.fillStyle = COLORS.hudBack; g.fillRect(width - 16 - tw, 16, tw, 30);
	g.fillStyle = "#f4efe4";
	g.fillText(label, width - 16 - tw + 10, 31);

	drawNotes(g, notes, width, height, px);
}

/* Notes (what was picked up, what is under you) — newest last, bottom right. */
function drawNotes(g, notes, width, height, px) {
	g.textBaseline = "middle";
	g.textAlign = "right";
	g.font = `${Math.round(Math.max(13, px * 0.36))}px "Crimson Pro", Georgia, serif`;
	notes.slice(-4).forEach((n, i, arr) => {
		const y = height - 20 - (arr.length - 1 - i) * Math.max(18, px * 0.48);
		g.fillStyle = "rgba(16,18,20,.6)";
		const w = g.measureText(n.text).width;
		g.fillRect(width - 24 - w, y - 11, w + 16, 22);
		g.fillStyle = n.color || "#f4efe4"; g.fillText(n.text, width - 16, y);
	});
	g.textAlign = "left";
}
