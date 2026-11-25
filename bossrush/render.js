// Boss Rush combat baseline from Halcyon Rift's last greybox (d52d2f57).
// This is a standalone copy for Boss Rush balance changes.
import { recoveryLimit, STARFALL_DELAY, TPS, ABILITY_COST, MORTAR, FAULT,
	inFocusZone, inCrack, WARDEN, BELL, FEN, wardenBehind, PYRE, pyreArmAngle, heroView } from "./sim.js";
import { CANTOR_ECHO_RANGE, orreryTracePreview } from "./crypt.js";
import { bossSprite, drawBossSprite, propSprite } from "./bossSprites.js";

export const COLORS = {
	water: "#5f8f93", waterLight: "#6d9ea1", rock: "#7b7a70", rockTop: "#918f84",
	player: "#7fe3f0", playerCore: "#f4fdff", playerShot: "#c9f6ff",
	chaser: "#e8573f", shooter: "#ef8a3a", radial: "#c8458f", boss: "#d63a5a",
	// The Fracture: violet stone, black lava, and the Schism's dark core.
	shard: "#7fd4ff", splitter: "#ff7a59", splinter: "#ffb199", flicker: "#e16bff", breach: "#9b6bff",
	void: "#0d0a14", voidSpeck: "#3a2a5c", seam: "rgba(185,150,255,.35)", seamHot: "#e7d8ff",
	// the Ashen Breach's: embers on charcoal. The player's own fire burns pale blue, so it
	// never reads as the enemy's orange.
	cinder: "#ffb347", kiln: "#c8553d", smolder: "#6b5a50", smolderLit: "#ff7a2e", pyre: "#ff6a2a", ash: "#8a7d72", cinderwake: "#f5ad61",
	enemyShot: "#ff5a4a", enemyShotHeavy: "#ff3d8b", tele: "rgba(255,90,74,.55)",
	ward: "#cfe3ff",
	paladin: "#f1c46b", diviner: "#c4a5ff", ninja: "#8fd6a4", simon: "#ff8fc8", shield: "rgba(241,196,107,.72)",
	slow: "rgba(241,196,107,.16)", star: "#ffe9a6", damage: "#ff9b8d",
	hp: "#e2564e", mp: "#5a8de8", hudBack: "rgba(16,18,20,.72)",
};

const SHALLOWS = { floor: "#2f4348", wall: "#263438", cap: "#60736d" };
const FRACTURE = { floor: "#3d3550", wall: "#252034", cap: "#5b4d70" };
const BLACK_LAVA = { surface: "#101012", crust: "#2a2225", ember: "#58342b", bank: "#362e32", wake: "#936452" };
const FRACTURE_BRIDGE = "#675b73";
const ASHEN = { floor: "#3b322d", wall: "#2b221f", cap: "#805444" };
const FEN_PAL = { floor: "#354547", wall: "#233138", cap: "#566c67" };
const SEAL_COURT = { floor: "#44424a", wall: "#302d37", cap: "#64616c" };
const BELL_COURT = { floor: "#49413a", wall: "#342b29", cap: "#785c4d" };
const CRYPT_COLORS = { orrery: "#76ebc6", glassweaver: "#ffb762", cantor: "#dcb0ff" };
const PALETTES = { shallows: SHALLOWS, fracture: FRACTURE, ashen: ASHEN, fen: FEN_PAL,
	"seal-court": SEAL_COURT, "bell-court": BELL_COURT,
	"orrery-hall": { floor: "#293f39", wall: "#20332e", cap: "#526e62" },
	"prism-court": { floor: "#393248", wall: "#262337", cap: "#635878" },
	"hush-vault": { floor: "#393344", wall: "#2b2332", cap: "#68576f" } };
const MAP_TILE_PIXELS = 32;
const maps = new WeakMap();

function drawArenaMap(g, st, ox, oy, px, width, height, pal) {
	// The map is opaque. Only paint the backdrop where the map does not cover
	// the canvas, with a pixel of overlap at fractional camera positions.
	const x = Math.max(0, ox), y = Math.max(0, oy);
	const right = Math.min(width, ox + st.w * px), bottom = Math.min(height, oy + st.h * px);
	const w = right - x, h = bottom - y;
	if (w <= 0 || h <= 0) {
		g.fillStyle = "#1b2220"; g.fillRect(0, 0, width, height);
		return;
	}
	if (x > 0 || y > 0 || right < width || bottom < height) {
		g.fillStyle = "#1b2220";
		if (y > 0) g.fillRect(0, 0, width, Math.ceil(y));
		if (bottom < height) g.fillRect(0, Math.floor(bottom), width, height - Math.floor(bottom));
		if (x > 0) g.fillRect(0, Math.floor(y), Math.ceil(x), Math.ceil(bottom) - Math.floor(y));
		if (right < width) g.fillRect(Math.floor(right), Math.floor(y), width - Math.floor(right), Math.ceil(bottom) - Math.floor(y));
	}
	const doc = g.canvas?.ownerDocument || (typeof document !== "undefined" ? document : null);
	const canDrawImages = typeof g.drawImage === "function";
	const riftArena = pal === SHALLOWS || pal === FRACTURE || pal === ASHEN;
	const pillar = canDrawImages && riftArena ? propSprite(doc, "rift-pillar") : undefined;
	if (!doc || st.w * st.h > 2048 || !canDrawImages) {
		drawMap(g, st, ox, oy, px, width, height, pal, pillar);
		return;
	}
	let map = maps.get(st.tiles);
	if (!map || map.pal !== pal || map.pillar !== pillar) {
		// The whole Boss Rush arena fits in a small texture at a fixed resolution.
		// Rebake when the pillar art arrives. Panning and density changes reuse it.
		const canvas = doc.createElement("canvas");
		canvas.width = st.w * MAP_TILE_PIXELS;
		canvas.height = st.h * MAP_TILE_PIXELS;
		drawMap(canvas.getContext("2d", { alpha: false }), st, 0, 0, MAP_TILE_PIXELS, canvas.width, canvas.height, pal, pillar);
		map = { canvas, pal, pillar };
		maps.set(st.tiles, map);
	}
	const s = MAP_TILE_PIXELS / px, smoothing = g.imageSmoothingEnabled;
	g.imageSmoothingEnabled = false;
	g.drawImage(map.canvas, (x - ox) * s, (y - oy) * s, w * s, h * s, x, y, w, h);
	g.imageSmoothingEnabled = smoothing;
}

// All stone details are drawn inside the existing 32×32 tile, including wall caps.
function drawFloorTile(g, X, Y, px, x, y) {
	const u = px / MAP_TILE_PIXELS;
	const variant = ((Math.imul(x + 1, 73856093) ^ Math.imul(y + 1, 19349663)) >>> 0) % 7;
	g.fillStyle = "rgba(0,0,0,.13)";
	g.fillRect(X, Y, u, px);
	g.fillRect(X + u, Y, px - u, u);
	g.fillStyle = "rgba(255,255,255,.035)";
	g.fillRect(X + 2 * u, Y + u, 29 * u, u);
	if (variant === 1) {
		g.fillRect(X + 22 * u, Y + 24 * u, 5 * u, 2 * u);
		g.fillRect(X + 25 * u, Y + 22 * u, 3 * u, 2 * u);
	}
	if (variant === 2) {
		g.fillStyle = "rgba(0,0,0,.06)";
		g.fillRect(X + 4 * u, Y + 8 * u, 4 * u, 2 * u);
		g.fillRect(X + 7 * u, Y + 10 * u, 3 * u, 2 * u);
	}
}

function drawWallTile(g, X, Y, px, pal, row, above, below, x) {
	const u = px / MAP_TILE_PIXELS;
	const open = (row, x) => row?.[x] != null && row[x] !== "#";
	g.fillStyle = "rgba(0,0,0,.24)";
	g.fillRect(X, Y, u, px);
	g.fillRect(X + u, Y, px - u, u);
	if (open(below, x)) {
		// Recessed face beneath the cap, ending at the collision boundary.
		g.fillRect(X + 4 * u, Y + 24 * u, 24 * u, 5 * u);
		g.fillRect(X + u, Y + 31 * u, px - u, u);
	}
	// Paint the continuous cap over the mortar, with each half-edge stopping at its turn.
	g.fillStyle = pal.cap;
	for (const [flipY, neighborRow] of [[false, above], [true, below]]) {
		for (const stepX of [-1, 1]) {
			drawWallCapCorner(g, X, Y, u, stepX === 1, flipY,
				open(row, x + stepX), open(neighborRow, x), open(neighborRow, x + stepX));
		}
	}
}

function drawWallCapCorner(g, X, Y, u, flipX, flipY, sideOpen, endOpen, diagonalOpen) {
	const half = MAP_TILE_PIXELS / 2;
	const insetX = 4, insetY = flipY ? 9 : 4, thickness = 6;
	const rect = (x, y, w, h) => g.fillRect(
		X + (flipX ? MAP_TILE_PIXELS - x - w : x) * u,
		Y + (flipY ? MAP_TILE_PIXELS - y - h : y) * u, w * u, h * u);
	if (sideOpen) {
		const start = endOpen ? insetY : 0;
		rect(insetX, start, thickness, half - start);
	}
	if (endOpen) {
		const start = sideOpen ? insetX : 0;
		rect(start, insetY, half - start, thickness);
	}
	if (!sideOpen && !endOpen && diagonalOpen) {
		rect(insetX, 0, thickness, insetY + thickness);
		rect(0, insetY, insetX + thickness, thickness);
	}
}

function drawLavaTile(g, ox, oy, px, x, y, fissure) {
	const X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
	const w = Math.floor(ox + (x + 1) * px) - X, h = Math.floor(oy + (y + 1) * px) - Y;
	const u = w / MAP_TILE_PIXELS, v = h / MAP_TILE_PIXELS;
	const westBank = x === fissure[0], eastBank = x === fissure[1] - 1;
	const phase = (y * 17) % 7, rippleY = 8 + phase * 2;
	g.fillStyle = BLACK_LAVA.surface;
	g.fillRect(X, Y, w, h);
	g.fillStyle = BLACK_LAVA.crust;
	// The main ripple crosses the center seam, so the lava reads as a channel.
	if (westBank) {
		g.fillRect(X + 5 * u, Y + (rippleY + 4) * v, 7 * u, 3 * v);
		g.fillRect(X + 12 * u, Y + (rippleY + 2) * v, 10 * u, 4 * v);
		g.fillRect(X + 22 * u, Y + rippleY * v, 10 * u, 4 * v);
	} else {
		g.fillRect(X, Y + rippleY * v, 8 * u, 4 * v);
		g.fillRect(X + 8 * u, Y + (rippleY - 2) * v, 12 * u, 4 * v);
		g.fillRect(X + 20 * u, Y + (rippleY - 4) * v, 7 * u, 3 * v);
	}
	g.fillRect(X + (4 + phase * 2) * u, Y + 27 * v, 12 * u, 2 * v);
	g.fillStyle = BLACK_LAVA.ember;
	g.fillRect(X + (westBank ? 16 : 10) * u, Y + (rippleY + (westBank ? 3 : -1)) * v, (5 + phase) * u, v);
	g.fillStyle = BLACK_LAVA.bank;
	if (westBank) g.fillRect(X, Y, 2 * u, h);
	if (eastBank) g.fillRect(X + 30 * u, Y, 2 * u, h);
}

function drawCover(g, tiles, x, y, X, Y, px, pillar) {
	if (pillar) {
		// Select the quadrant of the continuous pillar that covers this solid tile.
		const left = tiles[y][x - 1] === "o" ? x - 1 : x;
		const top = tiles[y - 1]?.[x] === "o" ? y - 1 : y;
		const upper = tiles[top], lower = tiles[top + 1];
		if (upper[left] === "o" && upper[left + 1] === "o" && lower?.[left] === "o" && lower[left + 1] === "o") {
			const u = MAP_TILE_PIXELS, smoothing = g.imageSmoothingEnabled;
			g.imageSmoothingEnabled = false;
			g.drawImage(pillar, (x - left) * u, (y - top) * u, u, u, X, Y, px, px);
			g.imageSmoothingEnabled = smoothing;
			return;
		}
	}
	g.fillStyle = COLORS.rock; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.84);
	g.fillStyle = COLORS.rockTop; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.22);
}

function drawMap(g, st, ox, oy, px, width, height, pal, pillar) {
	const x0 = Math.max(0, Math.floor(-ox / px)), x1 = Math.min(st.w - 1, Math.floor((width - ox) / px));
	const y0 = Math.max(0, Math.floor(-oy / px)), y1 = Math.min(st.h - 1, Math.floor((height - oy) / px));
	// Whole pixels, one tile wide plus a pixel, so neighbours never leave a seam.
	const P = Math.ceil(px) + 1;
	for (let y = y0; y <= y1; y++) {
		const row = st.tiles[y], above = st.tiles[y - 1], below = st.tiles[y + 1];
		for (let x = x0; x <= x1; x++) {
			const t = row[x], X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
			if (t === "#") {
				g.fillStyle = pal.wall; g.fillRect(X, Y, P, P);
				drawWallTile(g, X, Y, px, pal, row, above, below, x);
			} else if (t === "x" && st.fissure) {
				drawLavaTile(g, ox, oy, px, x, y, st.fissure);
			} else if (t === "x") {
				g.fillStyle = COLORS.void; g.fillRect(X, Y, P, P);
				if ((x * 7 + y * 13) % 5 === 0) { g.fillStyle = COLORS.voidSpeck; g.fillRect(X + px * 0.3, Y + px * 0.55, px * 0.08, px * 0.08); }
			} else if (t === "~") {
				g.fillStyle = COLORS.water; g.fillRect(X, Y, P, P);
				g.fillStyle = COLORS.waterLight; g.fillRect(X + px * 0.15, Y + px * 0.3, px * 0.4, px * 0.08);
			} else {
				g.fillStyle = pal.floor; g.fillRect(X, Y, P, P);
				drawFloorTile(g, X, Y, px, x, y);
				if (t === "o") drawCover(g, st.tiles, x, y, X, Y, px, pillar);
			}
		}
	}
}

/* The Schism's stone decks lift the player out of the lava. The warning remains
 * visible on the stone until the deck gives way. */
function drawCracks(g, st, ox, oy, px, calm) {
	if (!st.cracks?.length) return;
	const P = Math.ceil(px) + 1;
	for (const c of st.cracks) {
		for (const [x, y] of c.tiles) {
			const X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
			if (st.fissure) {
				if (c.open) {
					drawLavaTile(g, ox, oy, px, x, y, st.fissure);
				} else {
					g.fillStyle = FRACTURE_BRIDGE;
					g.fillRect(X, Y, Math.floor(ox + (x + 1) * px) - X, Math.floor(oy + (y + 1) * px) - Y);
					drawFloorTile(g, X, Y, px, x, y);
				}
				continue;
			}
			if (c.open) {
				g.fillStyle = COLORS.void; g.fillRect(X, Y, P, P);
				g.fillStyle = "rgba(155,107,255,.35)"; g.fillRect(X, Y, P, Math.max(1, px * 0.08));
			} else if (c.warn) {
				const on = calm || st.tick % 8 < 5;
				g.fillStyle = on ? "rgba(231,216,255,.55)" : "rgba(185,150,255,.3)"; g.fillRect(X, Y, P, P);
				g.fillStyle = COLORS.seamHot; g.fillRect(X + px * 0.15, Y + px * 0.45, px * 0.7, Math.max(1.5, px * 0.1));
			} else {
				g.fillStyle = "rgba(155,107,255,.25)"; g.fillRect(X, Y, P, P);
				g.fillStyle = COLORS.seam; g.fillRect(X, Y + px * 0.47, P, Math.max(1, px * 0.06));
			}
		}
		if (st.fissure && c.warn && !c.open)
			drawBridgeWarning(g, c.tiles, ox, oy, px, st.fissure[0], calm || st.tick % 8 < 5);
	}
}

function drawBridgeWarning(g, tiles, ox, oy, px, west, bright) {
	const steps = [-6, -2, 5, 3, -4, -7, 1];
	const u = px / MAP_TILE_PIXELS, line = Math.max(1, 2 * u);
	g.fillStyle = bright ? COLORS.seamHot : "#ad8ed7";
	const center = ox + (west + 1) * px;
	for (const [x, y] of tiles) {
		if (x !== west) continue;
		const from = Math.floor(center + steps[y % steps.length] * u);
		const to = Math.floor(center + steps[(y + 1) % steps.length] * u);
		const top = Math.floor(oy + y * px), bottom = Math.floor(oy + (y + 1) * px);
		const middle = Math.floor(top + (bottom - top) * (y % 2 ? 0.35 : 0.6));
		g.fillRect(from, top, line, middle - top);
		g.fillRect(Math.min(from, to), middle, Math.abs(to - from) + line, line);
		g.fillRect(to, middle + line, line, Math.max(0, bottom - middle - line));
	}
}

function drawDoors(g, st, ox, oy, px) {
	if (!st.doorCols) return;
	const Y = Math.floor(oy + (st.doorY - 1) * px);
	const unit = px / 16;
	st.doorCols.forEach((room, x) => {
		if (room < 0 || !(st.roomLeft[room] > 0)) return;
		const X = Math.floor(ox + x * px);
		const rect = (u, v, w, h, fill) => {
			const left = Math.round(u * unit), top = Math.round(v * unit);
			g.fillStyle = fill;
			g.fillRect(X + left, Y + top, Math.round((u + w) * unit) - left, Math.round((v + h) * unit) - top);
		};
		for (const end of [0, 40]) {
			rect(1, end, 14, 8, "#232029");
			rect(2, end, 12, 2, "#786778");
			rect(6, end + 3, 4, 3, "#4b4352");
		}
		if (st.sealed === room) {
			rect(1, 8, 14, 32, "#53424e");
			rect(2, 8, 2, 32, "#786676");
			rect(12, 8, 2, 32, "#362c39");
			rect(7, 8, 2, 32, "#211b26");
			for (const latch of [13, 22, 31]) {
				rect(5, latch, 6, 2, "#c05d68");
				rect(7, latch, 2, 2, "#ffa485");
			}
		} else {
			rect(6, 8, 4, 2, "#986574");
			rect(6, 38, 4, 2, "#986574");
		}
	});
}

function circle(g, x, y, r, fill) {
	g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = fill; g.fill();
}

/* Where the world sits on the canvas: it follows the player (at `at`, the drawn —
 * interpolated — position), clamped so the map never scrolls past its edge. The page
 * uses it too, to turn the mouse into aim. */
export function camera(st, width, height, px, at = st.p) {
	const vw = width / px, vh = height / px;
	const cx = st.w < vw ? st.w / 2 : Math.max(vw / 2, Math.min(st.w - vw / 2, at.x));
	const cy = st.h < vh ? st.h / 2 : Math.max(vh / 2, Math.min(st.h - vh / 2, at.y));
	return { ox: width / 2 - cx * px, oy: height / 2 - cy * px };
}

/* One frame, at `px` pixels a tile. `at(obj)` is where to DRAW a moving thing —
 * the page passes its position interpolated between the last two ticks, so motion
 * is smooth at any refresh rate while the simulation stays a fixed 60 Hz. */
const here = (o) => o;
/* CO-OP: `me` is which hero the camera follows (and whose aim `aim` is), `aims` both
 * heroes' aims (a replay draws both), `names` the players' names, drawn over every
 * hero but `you` — the live page's own hero; a replay has none, so names both.
 * Solo passes none of them. */
export function draw(g, st, { width, height, px, aim, aims, at = here, calm = false, ui = 1, bossName = "The boss",
	auto = false, me = 0, names, you = null, bossBarInset = 0, autoFireInset = 0 }) {
	const views = st.heroes ? st.heroes.map((_, i) => heroView(st, i)) : [st];
	const mine = views[me] || views[0];
	const p = mine.p, pp = at(p);
	const { ox, oy } = camera(st, width, height, px, pp);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;

	// The floor and walls never change in a fight: painted once, copied each frame.
	const pal = PALETTES[st.dungeonId] || SHALLOWS;
	drawArenaMap(g, st, ox, oy, px, width, height, pal);
	drawCracks(g, st, ox, oy, px, calm);
	drawDoors(g, st, ox, oy, px);
	drawHazards(g, st, sx, sy, px, width, height);
	const first = views.findIndex((v) => !v.p.dead);
	views.forEach((v, i) => {
		if (v.p.dead) return;
		drawAbilityFx(g, v, sx, sy, px, at(v.p), i === first);
		if (v.shield) {
			circle(g, sx(v.shield.x), sy(v.shield.y), px * v.shield.r, COLORS.shield);
			g.strokeStyle = "#fff0b7"; g.lineWidth = Math.max(2, px * 0.08);
			g.beginPath(); g.arc(sx(v.shield.x), sy(v.shield.y), px * v.shield.r, 0, Math.PI * 2); g.stroke();
		}
	});
	if (first < 0) drawAbilityFx(g, mine, sx, sy, px, pp, true, false);   // the shared stars and blasts still play out

	if (st.portal) drawPortal(g, sx(st.portal.x), sy(st.portal.y), px, st.tick, calm);
	for (const e of st.enemies) {
		if (e.hp <= 0 || e.dormant) continue;
		const ep = at(e), X = sx(ep.x), Y = sy(ep.y), r = e.r * px;
		const boss = e.type === "boss";
		const transitioning = boss && bossTransitioning(st, e);
		// The Breach's fault lines: dashed, thickening until they tear.
		if (e.faults && e.faultT > 0 && e.active) {
			const k = 1 - e.faultT / FAULT.tele;
			g.strokeStyle = `rgba(255,90,74,${0.3 + 0.55 * k})`; g.lineWidth = Math.max(1, px * (0.05 + 0.22 * k));
			g.setLineDash?.([px * 0.3, px * 0.2]);
			for (const [vx, vy, len] of e.faults) { g.beginPath(); g.moveTo(X, Y); g.lineTo(X + vx * len * px, Y + vy * len * px); g.stroke(); }
			g.setLineDash?.([]);
		}
		// Telegraphs: what is about to fire says so, and says where.
		if (e.tele > 0 && e.active && !transitioning) {
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
				const grow = 1 + (1 - e.tele / 50) * 0.8;
				g.beginPath(); g.arc(X, Y, r * grow + px * 0.2, 0, Math.PI * 2); g.stroke();
			}
		}
		if (e.burnUntil > st.tick) {                      // burning (the Ember Loop): an orange ring
			g.strokeStyle = "#ff8a3c"; g.lineWidth = Math.max(1, px * 0.06);
			g.beginPath(); g.arc(X, Y, r + px * 0.1, 0, Math.PI * 2); g.stroke();
		}
		const col = e.flash > 0 ? (calm ? "#f3b9a8" : "#fff3ea")
			: (COLORS[e.form] ?? (e.type === "smolder" && e.lit ? COLORS.smolderLit : COLORS[e.type]));
		const sprite = boss ? bossSprite(g.canvas?.ownerDocument, e.form) : undefined;
		if (sprite) {
			const tint = e.flash > 0 ? (calm ? 0.25 : 0.7) : 0;
			drawBossSprite(g, sprite, X, Y, r, tint);
			if (CRYPT_COLORS[e.form] && e.phase === 2) circle(g, X, Y, r * 0.12, "#fff8ed");
		} else if (e.type === "chaser") {
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
			g.closePath(); g.fillStyle = col; g.fill();
			circle(g, X, Y, r * 0.5, "#ffd27a");
			circle(g, X, Y, r * 0.26, "#fff7ec");
		} else if (e.form === "cinderwake") {
			circle(g, X, Y, r * 1.25, "rgba(241,152,68,.28)");
			g.save(); g.translate(X, Y); g.rotate(Math.PI / 4 + st.tick * 0.01);
			g.fillStyle = e.flash > 0 && !calm ? "#fff3ea" : col; g.fillRect(-r * 0.66, -r * 0.66, r * 1.32, r * 1.32);
			g.restore();
			circle(g, X, Y, r * 0.42, "#fff4ca");
		} else if (e.form === "warden") {
			const w = st.warden, fx = e.fx ?? 1, fy = e.fy ?? 0, bound = w.chainedUntil > st.tick;
			if (!bound) {                                 // his gaze: what is in front of him
				g.fillStyle = "rgba(196,150,240,.10)";
				g.beginPath(); g.moveTo(X, Y);
				const a = Math.atan2(fy, fx);
				g.arc(X, Y, px * 4.5, a - 0.55, a + 0.55); g.closePath(); g.fill();
			}
			g.save(); g.translate(X, Y); g.rotate(Math.atan2(fy, fx));
			g.fillStyle = e.flash ? "#faf1ff" : bound ? "#7d6a8c" : "#aa78d0";
			g.fillRect(-r * 0.75, -r * 0.75, r * 1.5, r * 1.5);
			g.fillStyle = "#39254e"; g.fillRect(r * 0.2, -r * 0.3, r * 0.45, r * 0.6);   // his face, toward his gaze
			const behind = wardenBehind(st, e);
			g.fillStyle = behind ? "#fff0be" : "rgba(255,240,190,.55)";                    // the weak spot on his back
			g.beginPath(); g.moveTo(-r * 0.95, 0); g.lineTo(-r * 0.7, -r * 0.22); g.lineTo(-r * 0.45, 0); g.lineTo(-r * 0.7, r * 0.22); g.closePath(); g.fill();
			g.restore();
			if (bound) {
				g.fillStyle = "#fff0be"; g.font = `600 ${Math.round(px * 0.42)}px "Crimson Pro", Georgia, serif`;
				g.textAlign = "center"; g.fillText("Chained!", X, Y - r - px * 0.5); g.textAlign = "left";
			}
		} else if (e.form === "bellkeeper") {
			circle(g, X, Y, r, e.flash ? "#fff4bd" : "#cc9755");
			circle(g, X, Y, r * 0.73, "#2a140c");
			circle(g, X, Y, r * 0.5, "#ffb84d"); circle(g, X, Y, r * 0.26, "#fff1c2");
		} else if (CRYPT_COLORS[e.form]) {
			const color = e.phase === 0 ? "#b4c3c8" : CRYPT_COLORS[e.form];
			circle(g, X, Y, r, e.flash ? "#fff8ed" : color);
			circle(g, X, Y, r * 0.78, "#192424");
			g.fillStyle = color;
			g.fillRect(X - r * 0.43, Y - r * 0.43, r * 0.86, r * 0.86);
			if (e.phase === 2) circle(g, X, Y, r * 0.28, "#fff8ed");
		} else if (e.form === "breach") {                   // the Breach: a torn violet star
			const n = 8, spin = st.tick * 0.02;
			g.beginPath();
			for (let k = 0; k < n * 2; k++) { const a = spin + k * Math.PI / n, rr = k % 2 ? r * 0.55 : r * 1.05; g[k ? "lineTo" : "moveTo"](X + Math.cos(a) * rr, Y + Math.sin(a) * rr); }
			g.closePath(); g.fillStyle = e.phase === 0 && !calm && st.tick % 10 < 5 ? "#fff3ea" : col; g.fill();
			circle(g, X, Y, r * 0.38, COLORS.void);
		} else {
			circle(g, X, Y, r, col);
			circle(g, X, Y, r * 0.55, "#5a1424");
		}
		if (transitioning) {
			circle(g, X, Y, r * 1.46, "#83dcff35");
			g.strokeStyle = "#b8f2ff"; g.lineWidth = Math.max(2, px * 0.08);
			g.beginPath(); g.arc(X, Y, r * 1.46, 0, Math.PI * 2); g.stroke();
		}
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

	// Your partner first, so you are drawn on top of them.
	const order = views.map((_, i) => i).sort((a, b) => (a === me) - (b === me));
	for (const i of order) {
		const v = views[i], hp = at(v.p), X = sx(hp.x), Y = sy(hp.y);
		if (v.p.dead) { drawFallen(g, X, Y, px, v.classId); continue; }
		if (st.fissure && inCrack(st, hp)) {
			const u = px / MAP_TILE_PIXELS;
			g.fillStyle = BLACK_LAVA.wake;
			g.fillRect(X - 13 * u, Y + 6 * u, 6 * u, u);
			g.fillRect(X + 7 * u, Y + 6 * u, 6 * u, u);
			g.fillRect(X - 5 * u, Y + 10 * u, 10 * u, u);
		}
		const heroAim = aims ? aims[i] : i === me ? aim : undefined;
		drawPlayer(g, v.p, X, Y, px, heroAim, v.classId, calm);
		if (v.p.hp > 0) drawPlayerBars(g, v, X, Y, px);
		const carrier = st.heroes ? st.cinderwake?.carrier ?? 0 : 0;
		if (st.cinderwake?.carrying && carrier === i) drawLantern(g, X + px * 0.32, Y - px * 0.3, px, st.tick);   // in their hands
	}
	if (st.heroes) for (const i of order) {             // the names over the heroes (never your own)
		if (i === you) continue;
		const v = views[i], hp = at(v.p);
		drawName(g, names?.[i] || "Partner", sx(hp.x), sy(hp.y - v.p.r) - px * 0.1, px, v.p.dead);
		if (i !== me) drawOffscreen(g, sx(hp.x), sy(hp.y), width, height, px, v.classId);
	}

	drawShots(g, st.bullets, views, sx, sy, px, at, width, height);
	if (st.damageNumbers?.length) drawDamageNumbers(g, st.damageNumbers, sx, sy, px, st.tick, width, height);
	drawFlashes(g, st, width, height, calm);
	drawHud(g, st, { height: height - autoFireInset, ui, auto });
	drawBossBar(g, st, { width, ui, name: bossName, top: bossBarInset });
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
function bossTransitioning(st, e) {
	return st.crypt?.transitionUntil != null || (e.phase === 0 && e.tele > 0);
}

function drawBossBar(g, st, { width, ui, name, top }) {
	const b = st.enemies.find((e) => e.type === "boss" && e.active && e.hp > 0);
	if (!b) return;
	const W = Math.min(width * 0.5, 560 * ui), H = Math.max(8, 12 * ui), X = width / 2 - W / 2;
	const Y = top ? top + 5 * ui : 30 * ui;
	const transitioning = bossTransitioning(st, b);
	g.textBaseline = "middle";
	if (!top) { // The touch header already shows the boss name.
		g.font = `600 ${Math.round(14 * ui)}px "Cinzel", Georgia, serif`;
		g.textAlign = "center";
		g.fillStyle = "rgba(10,12,14,.75)"; g.fillText(name, width / 2 + 1, Y - 11 * ui + 1.5);
		g.fillStyle = "#f6c2bc"; g.fillText(name, width / 2, Y - 11 * ui);
	}
	g.textAlign = "left";
	g.fillStyle = "rgba(10,12,14,.78)"; g.fillRect(X - 3, Y - 3, W + 6, H + 6);
	g.fillStyle = "#3a1f24"; g.fillRect(X, Y, W, H);
	g.fillStyle = transitioning ? "#91d9ee" : COLORS.boss;
	g.fillRect(X, Y, W * (b.hp / b.maxHp), H);
	const hint = trioHint(st, b), trio = !!(st.warden || st.bellkeeper || st.cinderwake);
	if (hint) {
		g.font = `600 ${Math.round(15 * ui)}px "Crimson Pro", Georgia, serif`;
		g.textAlign = "center";
		g.fillStyle = "rgba(10,12,14,.85)"; g.fillText(hint, width / 2 + 1, Y + H + 13 * ui + 1);
		g.fillStyle = "#fff4ca"; g.fillText(hint, width / 2, Y + H + 13 * ui);
		g.textAlign = "left";
	}
	if (trio ? b.hp > b.maxHp / 2 : b.phase === 1) { g.fillStyle = "rgba(255,240,235,.8)"; g.fillRect(X + W / 2 - 1, Y - 2, 2, H + 4); }
	if (st.bankSweep) {
		g.font = `600 ${Math.round(15 * ui)}px "Crimson Pro", Georgia, serif`;
		g.textAlign = "center";
		g.fillStyle = "#d8bcfc";
		g.fillText(`${st.bankSweep.north ? "North" : "South"} wall sweep · ${st.bankSweep.west ? "West" : "East"} bank`, width / 2, Y + H + 13 * ui);
		g.textAlign = "left";
	} else if (b.ward > 0) {
		g.font = `${Math.round(11 * ui)}px "Crimson Pro", Georgia, serif`;
		g.fillStyle = COLORS.ward; g.textAlign = "right";
		g.fillText(`Warded ×${b.ward}`, X + W, Y + H + 10 * ui);
		g.textAlign = "left";
	}
}

const secs = (st, until) => `${Math.max(0, (until - st.tick) / TPS).toFixed(1)}s`;
/* Attack and phase cues under the boss health bar. */
function trioHint(st, b) {
	const startsAt = b.startsAt ?? st.crypt?.startsAt;
	if (startsAt > st.tick) return `Get into position · ${secs(st, startsAt)}`;
	if (bossTransitioning(st, b)) return "Phase change · Invulnerable";
	const w = st.warden, bk = st.bellkeeper, c = st.cinderwake;
	if (w) {
		if (w.chainedUntil > st.tick) return `Chained · ${secs(st, w.chainedUntil)} — double damage`;
		if (w.glow) return `Stand in the glowing seal · ${secs(st, w.glow.at)}`;
		return "His back takes extra damage";
	}
	if (bk) {
		const lit = bk.bells.filter((bell) => bell.litUntil > st.tick).length;
		if (lit) return lit > 1 ? "Shoot both glowing bells" : "Shoot the glowing bell";
	}
	if (c) {
		if (c.carrying) return "Walk the lantern into a dark brazier";
		if (c.lantern) return "It dropped a lantern — carry it to a brazier to burn it";
	}
	return null;
}

/* The Pyre's plus sign: each arm a row of shots out to the room's edge, with its gap. */
function outsideView(x, y, radius, width, height) {
	// Leave room for antialiased edges at the canvas boundary.
	const pad = radius + 2;
	return x + pad < 0 || y + pad < 0 || x - pad > width || y - pad > height;
}

function drawPyreArms(g, st, e, sx, sy, px, width, height) {
	const q = PYRE.arms, room = st.rooms[e.room], [top, bottom] = st.roomY[e.room];
	// Before phase 2 they are a WARNING: faint, flashing, harmless, not yet turning.
	const ghost = e.phase === 0;
	const inner = q.w * px, outer = inner * 1.15;
	const shimmer = ghost ? `rgba(255,196,94,${(0.35 + 0.25 * Math.sin(st.tick * 0.35)).toFixed(3)})` : null;
	for (let k = 0; k < q.n; k++) {
		const ang = pyreArmAngle(e, k), ux = Math.cos(ang), uy = Math.sin(ang), gap = e.arms.gaps[k];
		for (let d = e.r + 0.3; d <= q.len; d += q.bead) {
			if (d > gap - 0.1 && d < gap + q.gap + 0.1) continue;
			const x = e.x + ux * d, y = e.y + uy * d;
			if (x < room.x0 || x > room.x1 || y < top || y > bottom + 1) break;
			const X = sx(x), Y = sy(y);
			if (outsideView(X, Y, outer, width, height)) continue;
			if (ghost) { circle(g, X, Y, inner * 0.8, shimmer); continue; }
			circle(g, X, Y, outer, "rgba(255,240,235,.9)");
			circle(g, X, Y, inner, "#ffc45e");
		}
	}
}

/* The boss's mortar: burning ground (a flickering orange pool that fades in its last
 * second), and each shell's landing spot, ringed red and filling as it comes. */
function drawHazards(g, st, sx, sy, px, width, height) {
	drawRaidObjectives(g, st, sx, sy, px);
	if (st.crypt) drawCrypt(g, st, sx, sy, px);
	for (const e of st.enemies) if (e.arms && e.hp > 0) drawPyreArms(g, st, e, sx, sy, px, width, height);
	const sweep = st.bankSweep;
	if (sweep) {
		const { north, x0, x1, top, bottom } = sweep;
		g.fillStyle = "rgba(177,104,241,.23)";
		g.fillRect(sx(x0), sy(top), (x1 - x0) * px, (bottom - top) * px);
		const edge = sy(north ? top + 0.4 : bottom - 0.4);
		g.strokeStyle = "#efcfff"; g.lineWidth = Math.max(2, px * 0.05);
		g.beginPath();
		g.moveTo(sx(x0), edge); g.lineTo(sx(x1), edge);
		g.stroke();
	}
	for (const f of st.embers || []) {                // the player's own fire: pale blue, white at heart
		const x = sx(f.x), y = sy(f.y), r = px * f.r;
		if (outsideView(x, y, r, width, height)) continue;
		const left = f.until - st.tick, fade = Math.min(1, left / TPS);
		const flick = 0.85 + 0.15 * Math.sin((st.tick + f.y * 7) * 0.35);
		circle(g, x, y, r, `rgba(120,214,255,${(0.28 * fade * flick).toFixed(3)})`);
		circle(g, x, y, r * 0.55, `rgba(230,250,255,${(0.2 * fade * flick).toFixed(3)})`);
	}
	for (const f of st.fires || []) {
		const x = sx(f.x), y = sy(f.y), r = px * f.r;
		if (outsideView(x, y, r, width, height)) continue;
		const left = f.until - st.tick, fade = Math.min(1, left / TPS);
		const flick = 0.85 + 0.15 * Math.sin((st.tick + f.x * 7) * 0.35);
		circle(g, x, y, r, `rgba(255,112,40,${(0.34 * fade * flick).toFixed(3)})`);
		circle(g, x, y, r * 0.6, `rgba(255,190,80,${(0.22 * fade * flick).toFixed(3)})`);
	}
	const lw = Math.max(1.5, px * 0.07);
	for (const m of st.mortars || []) {
		const x = sx(m.x), y = sy(m.y), r = px * m.r;
		if (outsideView(x, y, r + lw / 2, width, height)) continue;
		const k = Math.min(1, Math.max(0, 1 - (m.at - st.tick) / (m.d || MORTAR.delay)));
		g.strokeStyle = "#ff5a3c";
		g.lineWidth = lw;
		if (m.square) {
			g.strokeRect(sx(m.x - m.r), sy(m.y - m.r), 2 * m.r * px, 2 * m.r * px);
			g.fillStyle = "rgba(255,90,60,.28)";
			g.fillRect(sx(m.x - m.r * k), sy(m.y - m.r * k), 2 * m.r * k * px, 2 * m.r * k * px);
			continue;
		}
		g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
		circle(g, x, y, r * k, "rgba(255,90,60,.3)");
	}
}

const TOWER_INK = { idle: "#58716a", fan: "#76ebc6", trace: "#ffb762" };
const TOWER_GROUND = { idle: "#172321aa", fan: "#76ebc626", trace: "#ffb76226" };

function drawOrreryTower(g, sprite, x, y, px, mode) {
	circle(g, x, y, px * 0.7, TOWER_GROUND[mode]);
	if (sprite) {
		const u = px / MAP_TILE_PIXELS, side = 36 * u;
		const smoothing = g.imageSmoothingEnabled;
		g.imageSmoothingEnabled = false;
		g.drawImage(sprite, x - side / 2, y - side / 2, side, side);
		g.imageSmoothingEnabled = smoothing;
		g.fillStyle = TOWER_INK[mode];
		if (mode === "fan") {
			for (const dx of [-5.5, -1.5, 2.5]) g.fillRect(x + dx * u, y - 4 * u, 3 * u, 8 * u);
		} else if (mode === "trace") {
			g.fillRect(x - 6 * u, y - 2 * u, 12 * u, 4 * u);
		}
		return;
	}

	g.fillStyle = TOWER_INK[mode];
	g.fillRect(x - px * 0.36, y - px * 0.42, px * 0.72, px * 0.84);
	g.fillStyle = "#162022";
	if (mode === "fan") for (const dx of [-0.21, -0.05, 0.11]) g.fillRect(x + px * dx, y - px * 0.21, px * 0.1, px * 0.42);
	else g.fillRect(x - px * 0.22, y - px * 0.07, px * 0.44, px * 0.14);
}

function drawCrypt(g, st, sx, sy, px) {
	const { towers, bounds, marks } = st.crypt;
	const sprite = towers.length ? propSprite(g.canvas?.ownerDocument, "orrery-tower") : undefined;
	const preview = orreryTracePreview(st.crypt);
	for (let i = 0; i < towers.length; i++) {
		const tower = towers[i];
		const mode = i === preview ? "trace" : preview >= 0 && tower.mode === "trace" ? "idle" : tower.mode;
		drawOrreryTower(g, sprite, sx(tower.x), sy(tower.y), px, mode);
	}
	if (!bounds || !marks.length) return;
	const left = sx(bounds.x0), top = sy(bounds.y0), right = sx(bounds.x1), bottom = sy(bounds.y1);
	g.save();
	g.beginPath(); g.rect(left, top, right - left, bottom - top); g.clip();
	for (const m of marks) {
		const active = st.tick >= m.at;
		const k = Math.min(1, (st.tick - m.from) / (m.at - m.from));
		if (m.kind === "comb") {
			const edge = m.fromSide ? sx(m.edge) : sy(m.edge);
			const r = px * (0.09 + k * 0.11);
			g.fillStyle = m.fromSide ? "#ffa764" : "#f2a0dd";
			g.beginPath();
			for (const u of m.points) {
				const x = m.fromSide ? edge : sx(u), y = m.fromSide ? sy(u) : edge;
				g.moveTo(x + r, y); g.arc(x, y, r, 0, Math.PI * 2);
			}
			g.fill();
			// The two faint stripes frame the opening in the approaching volley.
			g.strokeStyle = m.fromSide ? "#ffa76466" : "#f2a0dd66";
			g.lineWidth = Math.max(1, px * 0.025);
			for (const u of [m.gap - m.half, m.gap + m.half]) {
				g.beginPath();
				if (m.fromSide) { g.moveTo(left, sy(u)); g.lineTo(right, sy(u)); }
				else {
					const far = m.side === "top" ? bounds.y1 : bounds.y0;
					const end = u + (m.drift ?? 0) * Math.abs(far - m.edge);
					g.moveTo(sx(u), edge); g.lineTo(sx(end), sy(far));
				}
				g.stroke();
			}
			continue;
		}
		const x = sx(m.x), y = sy(m.y), edge = Math.max(2, px * 0.055);
		if (m.kind === "echo") {
			const length = CANTOR_ECHO_RANGE * px, dx = m.ux * length, dy = m.uy * length;
			g.strokeStyle = active ? "#ffe3ac" : "#ffc57785";
			g.lineWidth = edge;
			g.beginPath(); g.moveTo(x - dx, y - dy); g.lineTo(x + dx, y + dy); g.stroke();
			const r = px * (0.24 + k * 0.13);
			g.fillStyle = active ? "#fff5db" : "#ffc577";
			g.beginPath(); g.moveTo(x, y - r); g.lineTo(x + r, y);
			g.lineTo(x, y + r); g.lineTo(x - r, y); g.closePath(); g.fill();
		} else if (m.kind === "pocket") { // Archived Cantor films still carry the old circles.
			const radius = m.r * px;
			g.save();
			g.globalAlpha *= active ? Math.max(0, 1 - (st.tick - m.at) / (m.linger ?? 8)) : Math.min(1, (st.tick - m.from + 1) / 10);
			g.fillStyle = active ? "#f476965e" : "#a13d6770";
			g.beginPath();
			g.rect(left, top, right - left, bottom - top);
			g.moveTo(x + radius, y); g.arc(x, y, radius, 0, Math.PI * 2);
			g.fill("evenodd");
			g.strokeStyle = "#9bffe2"; g.lineWidth = edge;
			g.beginPath(); g.arc(x, y, radius, 0, Math.PI * 2); g.stroke();
			if (!active) {
				const gold = "#ffcc68", inner = radius - edge * 2.7;
				g.strokeStyle = gold; g.lineWidth = edge * 1.6;
				g.beginPath(); g.arc(x, y, inner, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - k)); g.stroke();
			}
			g.restore();
		} else if (m.kind === "line") {
			g.lineCap = "round"; g.lineWidth = 2 * m.r * px;
			g.strokeStyle = active ? "#ffc77edb" : "#ffad695e";
			g.beginPath(); g.moveTo(x, y); g.lineTo(sx(m.tx), sy(m.ty)); g.stroke();
			g.lineWidth = edge; g.strokeStyle = "#ffe0a8"; g.stroke();
		} else {
			const r = (m.r || 0.48) * px;
			const color = m.kind === "mine" ? "#ffac86" : "#aaffef";
			g.strokeStyle = color; g.lineWidth = edge;
			g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
			circle(g, x, y, r * k, active ? color : m.kind === "mine" ? "#ff76525e" : "#85dbc45e");
			if (m.tx !== undefined) {
				g.beginPath(); g.moveTo(x, y); g.lineTo(sx(m.tx), sy(m.ty)); g.stroke();
			}
		}
	}
	g.restore();
}

function drawRaidObjectives(g, st, sx, sy, px) {
	const lw = Math.max(2, px * 0.05);
	const w = st.warden;
	if (w) {
		const boss = st.enemies.find((e) => e.form === "warden" && e.hp > 0);
		const bound = w.chainedUntil > st.tick;
		for (const [i, seal] of w.seals.entries()) {
			const x = sx(seal.x), y = sy(seal.y), r = seal.r * px;
			const glowing = w.glow?.seal === i, held = bound && w.last?.seal === i;
			if (glowing) {                                // stand here before the ring closes
				const k = (w.glow.at - st.tick) / (w.glow.at - w.glow.from), pulse = 0.5 + 0.5 * Math.sin(st.tick * 0.25);
				circle(g, x, y, r, `rgba(255,226,150,${(0.22 + 0.12 * pulse).toFixed(3)})`);
				g.strokeStyle = "#ffe7a6"; g.lineWidth = lw * 2;
				g.beginPath(); g.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * k); g.stroke();
			} else {
				circle(g, x, y, r, held ? "rgba(255,226,150,.16)" : "rgba(160,123,208,.12)");
				g.strokeStyle = held ? "#ffe7a6" : "rgba(172,139,198,.55)"; g.lineWidth = lw;
				g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
			}
			if (held && boss) {                           // the chains, seal to Warden
				g.strokeStyle = "rgba(255,236,190,.75)"; g.lineWidth = lw * 1.4;
				g.setLineDash?.([px * 0.25, px * 0.12]);
				g.beginPath(); g.moveTo(x, y); g.lineTo(sx(boss.x), sy(boss.y)); g.stroke();
				g.setLineDash?.([]);
			}
			const last = w.last;
			if (last && last.seal === i && st.tick - last.at < 40) {
				const a = 1 - (st.tick - last.at) / 40;
				g.strokeStyle = last.ok ? `rgba(255,236,170,${a})` : `rgba(200,190,210,${a * 0.6})`; g.lineWidth = lw * 2;
				g.beginPath(); g.arc(x, y, r * (1 + 0.4 * (1 - a)), 0, Math.PI * 2); g.stroke();
			}
		}
	}
	const bk = st.bellkeeper;
	if (bk) {
		for (const bell of bk.bells) {
			const x = sx(bell.x), y = sy(bell.y), r = bell.r * px;
			const lit = bell.litUntil > st.tick, rung = st.tick - bell.rungAt < 14;
			if (lit) {                                    // shoot it before it fades
				const k = (bell.litUntil - st.tick) / BELL.glow, pulse = 0.5 + 0.5 * Math.sin(st.tick * 0.3);
				circle(g, x, y, r * (1.6 + 0.25 * pulse), "rgba(255,214,120,.30)");
				g.strokeStyle = "#ffe08a"; g.lineWidth = lw * 1.5;
				g.beginPath(); g.arc(x, y, r * 1.35, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * k); g.stroke();
			}
			circle(g, x, y, r, rung ? "#fff6d8" : "#87623f");
			circle(g, x, y, r * 0.72, lit ? "#ffe08a" : "#9c7a50");
			circle(g, x, y, r * 0.24, lit ? "#fffbe8" : "#d9bf8a");
		}
		const boss = st.enemies.find((e) => e.form === "bellkeeper" && e.hp > 0);
		const pt = bk.peal ? st.tick - bk.peal.at : 99;
		if (boss && pt < 20) {                            // the peal, rung into him
			const k = 1 - pt / 20, big = bk.peal.chord ? 1.6 : 1;
			g.strokeStyle = `rgba(255,226,140,${k.toFixed(3)})`; g.lineWidth = Math.max(3, px * 0.18 * k * big);
			g.beginPath(); g.moveTo(sx(bk.peal.x), sy(bk.peal.y)); g.lineTo(sx(boss.x), sy(boss.y)); g.stroke();
			for (const d of [0, 0.5]) {
				const t = (pt / 20 + d) % 1;
				g.strokeStyle = `rgba(255,236,170,${(0.6 * (1 - t)).toFixed(3)})`; g.lineWidth = lw;
				g.beginPath(); g.arc(sx(bk.peal.x), sy(bk.peal.y), px * (0.8 + t * 1.4 * big), 0, Math.PI * 2); g.stroke();
			}
		}
	}
	const c = st.cinderwake;
	if (c) {
		for (const bz of c.braziers) {
			const x = sx(bz.x), y = sy(bz.y);
			if (!bz.lit) {                                // dark: drop a lantern in here
				g.strokeStyle = c.carrying ? "rgba(255,210,122,.85)" : "rgba(255,200,140,.4)"; g.lineWidth = lw;
				g.setLineDash?.([px * 0.2, px * 0.15]);
				g.beginPath(); g.arc(x, y, px * FEN.reach, 0, Math.PI * 2); g.stroke();
				g.setLineDash?.([]);
			}
			g.fillStyle = "#3b3330"; g.fillRect(x - px * 0.34, y - px * 0.1, px * 0.68, px * 0.36);
			g.fillStyle = "#57493f"; g.fillRect(x - px * 0.42, y - px * 0.18, px * 0.84, px * 0.12);
			if (bz.lit) {                                 // full: burning down until it takes another
				const f = 0.85 + 0.15 * Math.sin(st.tick * 0.35 + bz.x);
				g.beginPath(); g.moveTo(x, y - px * 0.75 * f); g.quadraticCurveTo(x + px * 0.32, y - px * 0.2, x, y - px * 0.12);
				g.quadraticCurveTo(x - px * 0.32, y - px * 0.2, x, y - px * 0.75 * f); g.fillStyle = "#ffb347"; g.fill();
				circle(g, x, y - px * 0.28, px * 0.1, "#fff1c2");
				g.strokeStyle = "rgba(255,210,122,.6)"; g.lineWidth = lw;
				g.beginPath(); g.arc(x, y, px * 0.7, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0, bz.litUntil - st.tick) / FEN.full); g.stroke();
			}
		}
		const boss = st.enemies.find((e) => e.form === "cinderwake" && e.hp > 0);
		const bt = c.blast ? st.tick - c.blast.at : 99;
		if (boss && bt < 20) {                            // the brazier's fire, flung at it
			const k = 1 - bt / 20;
			g.strokeStyle = `rgba(255,190,90,${k.toFixed(3)})`; g.lineWidth = Math.max(3, px * 0.22 * k);
			g.beginPath(); g.moveTo(sx(c.blast.x), sy(c.blast.y) - px * 0.3); g.lineTo(sx(boss.x), sy(boss.y)); g.stroke();
			circle(g, sx(boss.x), sy(boss.y), px * (0.8 + bt * 0.06), `rgba(255,220,150,${(0.5 * k).toFixed(3)})`);
		}
		if (c.lantern) drawLantern(g, sx(c.lantern.x), sy(c.lantern.y), px, st.tick);
	}
}

function drawLantern(g, x, y, px, tick) {
	const f = 0.85 + 0.15 * Math.sin(tick * 0.3);
	circle(g, x, y, px * 0.55 * f, "rgba(255,190,90,.25)");
	g.fillStyle = "#5b4630"; g.fillRect(x - px * 0.16, y - px * 0.24, px * 0.32, px * 0.42);
	circle(g, x, y, px * 0.12, "#ffd27a");
	g.strokeStyle = "#5b4630"; g.lineWidth = Math.max(1.5, px * 0.05);
	g.beginPath(); g.arc(x, y - px * 0.26, px * 0.12, Math.PI, 0); g.stroke();
}

/* A big moment, over the whole screen: the Warden chained flashes soft gold. */
function drawFlashes(g, st, width, height, calm) {
	const w = st.warden, t = w?.last?.ok ? st.tick - w.last.at : 99, len = 24;
	if (t >= len) return;
	g.fillStyle = `rgba(255,230,160,${((calm ? 0.12 : 0.28) * (1 - t / len)).toFixed(3)})`;
	g.fillRect(0, 0, width, height);
}

/* What an ability leaves on the ground: the Paladin's field (gold, around the player),
 * a falling star (its spot ringed, filling as it comes) and its blast, and the
 * Ninja's counter — a white ring while it is ready to catch a hit, a solid guard
 * just after, and a gold ring while the next shot is countered. Shared by the town. */
function drawAbilityFx(g, st, sx, sy, px, pp, shared = true, own = true) {
	const p = st.p, lw = Math.max(1, px * 0.05);
	if (!own) { drawSharedFx(g, st, sx, sy, px, lw); return; }
	const zone = st.focusZone;
	if (zone) {
		const x = sx(zone.x), y = sy(zone.y), r = px * zone.r;
		const inside = inFocusZone(st);
		circle(g, x, y, r, inside ? "rgba(196,165,255,.20)" : "rgba(196,165,255,.09)");
		g.strokeStyle = inside ? COLORS.diviner : "rgba(196,165,255,.55)";
		g.lineWidth = lw;
		g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
	}
	if (st.slowUntil > st.tick) {
		const c = st.slowAt || pp;                          // the Anchor Orb's field stays where it was cast
		circle(g, sx(c.x), sy(c.y), px * (st.slowR || 3), COLORS.slow);
		g.strokeStyle = COLORS.paladin; g.lineWidth = lw;
		g.beginPath(); g.arc(sx(c.x), sy(c.y), px * (st.slowR || 3), 0, Math.PI * 2); g.stroke();
	}
	if (shared) drawSharedFx(g, st, sx, sy, px, lw);
	drawHeroRings(g, st, p, sx(pp.x), sy(pp.y), px);
}

/* The falling stars and the blasts: the fight's, drawn once whoever cast them. */
function drawSharedFx(g, st, sx, sy, px, lw) {
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
}

/* A hero's own rings: the counter, its guard, Haste, an empowered shot. */
function drawHeroRings(g, st, p, X, Y, px) {
	const R = px * (p.r + 0.22);
	if (p.counterUntil >= st.tick) {
		g.strokeStyle = "rgba(255,255,255,.85)"; g.lineWidth = Math.max(1.5, px * 0.06);
		g.beginPath(); g.arc(X, Y, R, 0, Math.PI * 2); g.stroke();
	}
	if (p.guardUntil > st.tick) circle(g, X, Y, R, "rgba(255,255,255,.35)");
	if (p.hasteUntil > st.tick) {                        // Simon's Haste: a pink ring round the feet
		g.strokeStyle = "rgba(255,143,200,.8)"; g.lineWidth = Math.max(1.5, px * 0.06);
		g.setLineDash([px * 0.12, px * 0.1]);
		g.beginPath(); g.arc(X, Y, R, 0, Math.PI * 2); g.stroke();
		g.setLineDash([]);
	}
	if (p.empower > 0) {                                    // the next shot is countered: gold, as it will be
		circle(g, X, Y, R * 1.2, "rgba(255,196,80,.22)");
		g.strokeStyle = "#ffb43c"; g.lineWidth = Math.max(1.5, px * 0.05);
		g.beginPath(); g.arc(X, Y, R * 1.2, 0, Math.PI * 2); g.stroke();
	}
}

/* Use the Ninja counter's gold trail and halo at the same size for every class. */
const POWER_TRAIL_LENGTH = 1.35; // tiles, the reach of the original 15 tiles/s shuriken trail
const POWER_GLOW_SCALE = 0.8;
const POWER_SHOT_SCALE = 0.8;
function drawPowerTrail(g, X, Y, b, px) {
	const L = px * POWER_TRAIL_LENGTH / (Math.hypot(b.vx, b.vy) || 1);
	const dx = b.vx * L, dy = b.vy * L, pulse = 0.75 + 0.25 * Math.sin((b.x + b.y) * 3);
	g.save();
	g.lineCap = "round";
	g.strokeStyle = "rgba(255,196,80,.35)"; g.lineWidth = Math.max(4, px * 0.42) * POWER_GLOW_SCALE;
	g.beginPath(); g.moveTo(X, Y); g.lineTo(X - dx, Y - dy); g.stroke();
	g.strokeStyle = "rgba(255,240,200,.9)"; g.lineWidth = Math.max(2, px * 0.14);
	g.beginPath(); g.moveTo(X, Y); g.lineTo(X - dx * 0.6, Y - dy * 0.6); g.stroke();
	circle(g, X, Y, px * 0.5 * pulse * POWER_GLOW_SCALE, "rgba(255,206,92,.28)");
	g.restore();
}

const ENEMY_SHOT_COLORS = {
	"boss:sweep": "#d591fa", "crypt:needles": "#76ebc6", "crypt:curtain": "#ffb762",
	"crypt:diagonal": "#f2a0dd", "crypt:echo": "#ffc577", "crypt:spokes": "#dcb0ff",
};
const pixelSprites = new WeakMap();
const PELLET_PIXELS = [
	"...#####...",
	"..#+++++#..",
	".#+++++++#.",
	"#++***++++#",
	"#++****+++#",
	"#++****+++#",
	"#+++**++++#",
	"#+++++++++#",
	".#+++++++#.",
	"..#+++++#..",
	"...#####...",
];
const SHARD_PIXELS = [
	".....#.....",
	"....#+#....",
	"...#+++#...",
	"..#++*++#..",
	".#++***++#.",
	"#++*****++#",
	".#++***++#.",
	"..#++*++#..",
	"...#+++#...",
	"....#+#....",
	".....#.....",
];

const PORTAL_PIXELS = [
	"............h.........",
	"..........lhl.........",
	".........vllhl........",
	".......lbccch.........",
	"......hlccbcll........",
	".....lcccvbcch........",
	"....vlcbddbccll.......",
	"....lbcdddbcclh.......",
	"...hlcddavdcccl.......",
	"...lbcddacdbccvh......",
	"...lcbddacbdcccl......",
	"...vlcddvadbccchl.....",
	"...lbcdbacddcccl......",
	"....hlcbddaddbccv.....",
	"....lbcddavddcch......",
	"....vlcbddddbccl......",
	".....hlcbbddbccv......",
	"......lccbbccclh......",
	"......hlccccccl.......",
	"......lcllvhl.........",
	".......vlhl...........",
	"........h.............",
];
const RIFT_PALETTE = {
	d: "#13102a", b: "#292052", c: "#315384", l: "#60d5f1", h: "#c0faff", v: "#8d83e9", a: "#517ab6",
};
const RIFT_GLOW = { ...RIFT_PALETTE, l: "#7de2f9", a: "#6aa4ce" };

const MIN_ENEMY_SHOT_RADIUS = 4;  // CSS pixels, so tiny shots remain visible when zoomed out.

// Directional sprites point right. The ring's open center stays clear at play size.
const CLASS_SHOTS = {
	ranger: { color: COLORS.playerShot, scale: 2.1, facing: "aim", pixels: [
		"..........#....",
		"##........+#...",
		"#+#.......++#..",
		".#########+++#.",
		"..#+++++++++**#",
		".#########+++#.",
		"#+#.......++#..",
		"##........+#...",
		"..........#....",
	] },
	paladin: { color: COLORS.paladin, scale: 1.7, facing: "aim", pixels: [
		".......####.",
		"......#+**+#",
		"......#++++#",
		"########**+#",
		"#+++++++**+#",
		"########+++#",
		"......#+**+#",
		"......#+**+#",
		".......####.",
	] },
	diviner: { color: COLORS.diviner, scale: 1.7, pixels: [
		"....#....",
		"....+....",
		"....+....",
		"...+*+...",
		"#++***++#",
		"...+*+...",
		"....+....",
		"....+....",
		"....#....",
	] },
	ninja: { color: "#accdc3", scale: 1.55, facing: "spin", pixels: [
		"....###..",
		"....#+...",
		"....++...",
		".#.+**##.",
		"#++*+*++#",
		".##**+.#.",
		"...++....",
		"...+#....",
		"..###....",
	] },
	simon: { color: "#ffa8d5", scale: 1.6, pixels: [
		"..#####..",
		".#*****#.",
		"#+#...#+#",
		"#+.....+#",
		"#+.....+#",
		"#+.....+#",
		"#+#...#+#",
		".#+++++#.",
		"..#####..",
	] },
};

function paintPixelSprite(g, pixels, color, X, Y, unit) {
	const palette = typeof color === "string" ? { "#": "#251722", "+": color, "*": "#fff2e9" } : color;
	for (const [ink, fill] of Object.entries(palette)) {
		g.fillStyle = fill;
		pixels.forEach((row, y) => {
			for (let x = 0; x < row.length; x++) {
				if (row[x] === ink) g.fillRect(X + x * unit, Y + y * unit, unit, unit);
			}
		});
	}
}

function pixelSprite(doc, pixels, color) {
	let sprites = pixelSprites.get(doc);
	if (!sprites) pixelSprites.set(doc, sprites = new Map());
	let colors = sprites.get(pixels);
	if (!colors) sprites.set(pixels, colors = new Map());
	let canvas = colors.get(color);
	if (!canvas) {
		canvas = doc.createElement("canvas");
		canvas.width = pixels[0].length;
		canvas.height = pixels.length;
		paintPixelSprite(canvas.getContext("2d"), pixels, color, 0, 0, 1);
		colors.set(color, canvas);
	}
	return canvas;
}

function drawPixelSprite(g, doc, pixels, color, X, Y, r) {
	const unit = 2 * r / Math.max(pixels[0].length, pixels.length);
	const w = pixels[0].length * unit, h = pixels.length * unit;
	const x = X - w / 2, y = Y - h / 2;
	if (doc && typeof g.drawImage === "function") {
		const smoothing = g.imageSmoothingEnabled;
		g.imageSmoothingEnabled = false;
		g.drawImage(pixelSprite(doc, pixels, color), x, y, w, h);
		g.imageSmoothingEnabled = smoothing;
	} else {
		paintPixelSprite(g, pixels, color, x, y, unit);
	}
}

function drawPortal(g, X, Y, px, tick, calm) {
	const unit = px * 0.105;
	// A low, stepped floor anchor gives the hovering opening a point of entry.
	g.fillStyle = "#141826";
	g.fillRect(X - 5 * unit, Y + unit, 10 * unit, 3 * unit);
	g.fillStyle = "#355872";
	g.fillRect(X - 4 * unit, Y + unit, 8 * unit, unit);
	g.fillStyle = "#68c7e1";
	g.fillRect(X - 2 * unit, Y + unit, 4 * unit, unit);
	const palette = !calm && tick % 36 < 18 ? RIFT_GLOW : RIFT_PALETTE;
	drawPixelSprite(g, g.canvas?.ownerDocument, PORTAL_PIXELS, palette, X, Y - px * 0.54, px * 0.96);
	for (let i = 0; i < 3; i++) {
		const rise = calm ? i * 4 : (Math.floor(tick / 4) + i * 4) % 13;
		g.fillStyle = i === 1 ? "#b8f6ff" : "#729ae2";
		g.fillRect(X + (i * 5 - 6) * unit, Y + (1 - rise) * unit, unit * 0.68, unit * 0.68);
	}
}

function drawBolt(g, X, Y, b, px, sizeScale) {
	const focusScale = b.focused ? 0.5 : 1;
	const width = b.power ? Math.max(2, b.r * px * 2) * focusScale : Math.max(2, b.r * px * 0.9);
	const head = Math.max(2, width * 1.4);
	const trail = Math.hypot(b.vx, b.vy) * px * (b.look === "blade" ? 0.022 : 0.03) * focusScale;
	g.save();
	g.translate(X, Y);
	g.rotate(Math.atan2(b.vy, b.vx));
	g.scale(sizeScale, sizeScale);
	g.fillStyle = b.power ? "#d39651" : "#569eaf";
	g.fillRect(-trail, -width / 4, trail, width / 2);
	g.fillStyle = b.power ? "#fff1c2" : COLORS.playerShot;
	g.fillRect(-head / 2, -width / 2, head, width);
	g.fillStyle = "#fffdf4";
	g.fillRect(0, -width / 4, head / 2, width / 2);
	g.restore();
}

function drawPlayerShot(g, doc, b, classId, X, Y, px) {
	const sizeScale = b.power ? POWER_SHOT_SCALE : 1;
	if (b.power) drawPowerTrail(g, X, Y, b, px);
	const r = b.r * px * sizeScale;
	if (b.look === "flare") {
		drawPixelSprite(g, doc, PELLET_PIXELS, "#78d6ff", X, Y, r);
		return;
	}
	if (b.look === "blade") {
		drawBolt(g, X, Y, b, px, sizeScale);
		return;
	}
	const art = b.look === "star" ? CLASS_SHOTS.ninja : CLASS_SHOTS[classId] || CLASS_SHOTS.ranger;
	const size = r * art.scale * (b.power && !b.focused ? 1.25 : 1);
	if (!art.facing) {
		drawPixelSprite(g, doc, art.pixels, art.color, X, Y, size);
		return;
	}
	g.save();
	g.translate(X, Y);
	g.rotate(art.facing === "spin" ? (b.x + b.y) * 2.4 : Math.atan2(b.vy, b.vx));
	drawPixelSprite(g, doc, art.pixels, art.color, 0, 0, size);
	g.restore();
}

function drawShots(g, bullets, views, sx, sy, px, at, width, height) {
	const doc = g.canvas?.ownerDocument || (typeof document !== "undefined" ? document : null);
	for (const b of bullets) {
		const bp = at(b), X = sx(bp.x), Y = sy(bp.y);
		const r = b.r * px;
		const enemySize = Math.max(r, MIN_ENEMY_SHOT_RADIUS);
		const trail = b.power ? POWER_TRAIL_LENGTH : Math.max(Math.abs(b.vx), Math.abs(b.vy)) * 0.03;
		const pad = b.owner === "p" ? Math.max(px * 0.5, r) + trail * px : enemySize;
		if (X + pad < 0 || Y + pad < 0 || X - pad > width || Y - pad > height) continue;
		if (b.owner === "p") {
			drawPlayerShot(g, doc, b, (views[b.pi ?? 0] || views[0]).classId, X, Y, px);
		} else if (b.shard) {                                 // a shatter shard: a crystal that will burst
			drawPixelSprite(g, doc, SHARD_PIXELS, COLORS.enemyShotHeavy, X, Y, enemySize);
		} else {
			const color = ENEMY_SHOT_COLORS[b.src] ?? (b.dmg >= 30 ? COLORS.enemyShotHeavy : COLORS.enemyShot);
			drawPixelSprite(g, doc, PELLET_PIXELS, color, X, Y, enemySize);
		}
	}
}

/* Co-op: a hero who is down — a dim ring where they fell, in their color. */
function drawFallen(g, X, Y, px, classId) {
	const body = COLORS[classId] && classId !== "ranger" ? COLORS[classId] : COLORS.player;
	g.globalAlpha = 0.35;
	circle(g, X, Y, 0.32 * px, body);
	g.globalAlpha = 1;
	g.strokeStyle = "rgba(240,236,228,.7)"; g.lineWidth = Math.max(1.5, px * 0.05);
	const r = px * 0.16;
	g.beginPath(); g.moveTo(X - r, Y - r); g.lineTo(X + r, Y + r); g.moveTo(X + r, Y - r); g.lineTo(X - r, Y + r); g.stroke();
}

/* Co-op: a name over a hero. */
function drawName(g, text, X, Y, px, dim) {
	g.font = `600 ${Math.round(Math.max(11, px * 0.26))}px "Crimson Pro", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "bottom";
	g.fillStyle = "rgba(16,18,20,.75)"; g.fillText(text, X + 1, Y + 1);
	g.fillStyle = dim ? "rgba(240,236,228,.55)" : "#f0ece4"; g.fillText(text, X, Y);
	g.textAlign = "left"; g.textBaseline = "alphabetic";
}

/* Co-op: your partner off the edge of your screen — an arrow at the edge, toward them. */
function drawOffscreen(g, X, Y, width, height, px, classId) {
	const m = px * 0.5;
	if (X >= 0 && X <= width && Y >= 0 && Y <= height) return;
	const cx = Math.max(m, Math.min(width - m, X)), cy = Math.max(m, Math.min(height - m, Y));
	const a = Math.atan2(Y - cy, X - cx);
	g.save(); g.translate(cx, cy); g.rotate(a);
	g.beginPath(); g.moveTo(m * 0.8, 0); g.lineTo(-m * 0.4, -m * 0.45); g.lineTo(-m * 0.4, m * 0.45); g.closePath();
	g.fillStyle = COLORS[classId] && classId !== "ranger" ? COLORS[classId] : COLORS.player; g.fill();
	g.restore();
}

/* The player: cyan body, white core, a tick toward the aim. */
function drawPlayer(g, p, PX, PY, px, aim, classId = "ranger", calm = false) {
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

function drawDamageNumbers(g, numbers, sx, sy, px, tick, width, height) {
	g.font = `bold ${Math.round(Math.max(13, px * 0.38))}px "Crimson Pro", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	for (const f of numbers) {
		// Yours: red, "-7", over the player. What you dealt: pale gold, "7", over the enemy.
		const rise = ((f.foe ? 36 : 45) - (f.until - tick)) * 0.018;
		const x = sx(f.x), y = sy(f.y - (f.foe ? 0.25 : 0.55) - rise);
		if (x < -px || x > width + px || y < -px || y > height + px) continue;
		const n = Number.isInteger(f.amount) ? String(f.amount) : f.amount.toFixed(1);
		const text = f.foe ? n : `-${n}`;
		g.fillStyle = "rgba(16,18,20,.8)"; g.fillText(text, x + 1, y + 1.5);
		g.fillStyle = f.foe ? "#ffe9a6" : COLORS.damage; g.fillText(text, x, y);
	}
	g.textAlign = "left";
}

function drawHud(g, st, { height, ui = 1, auto = false }) {
	if (auto) drawAutoTag(g, 16, height - 10, ui);
}

/* HP and MP as two thin bars under the hero, as in Halcyon Rift (owner, 2026-11-21).
 * HP in three parts: green what you have, light gray what regeneration can bring
 * back (to the recovery limit), dark gray what only a heal can. MP carries a tick at
 * the ability's cost and is bright only while the ability can be cast. */
function drawPlayerBars(g, st, x, y, px) {
	const p = st.p, s = st.stats;
	const w = Math.max(14, Math.round(px * 0.9)), h = Math.max(3, Math.round(px * 0.1));
	const left = Math.round(x - w / 2), top = Math.round(y + px * 0.47), gap = 2;
	const fill = (v) => Math.round(w * Math.max(0, Math.min(1, v)));
	g.fillStyle = "#14111a"; g.fillRect(left - 1, top - 1, w + 2, h * 2 + gap + 2);
	g.fillStyle = "#34383d"; g.fillRect(left, top, w, h);
	g.fillStyle = "#8d9298"; g.fillRect(left, top, fill(recoveryLimit(st) / s.maxHp), h);
	g.fillStyle = "#83dc78"; g.fillRect(left, top, fill(p.hp / s.maxHp), h);
	const my = top + h + gap;
	g.fillStyle = "#1a2238"; g.fillRect(left, my, w, h);
	const cost = s.abilityKind ? (s.abilityCost ?? ABILITY_COST) : 0;
	const ready = s.abilityKind && p.mp >= cost && !(p.abilityCd > 0);
	g.fillStyle = ready ? "#6fd0ff" : "#3f6fa8"; g.fillRect(left, my, fill(p.mp / s.maxMp), h);
	if (cost && cost < s.maxMp) { g.fillStyle = "#f4efe4"; g.fillRect(left + fill(cost / s.maxMp) - 1, my - 1, 2, h + 2); }
}
