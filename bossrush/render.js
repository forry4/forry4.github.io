// Boss Rush combat baseline from Halcyon Rift's last greybox (d52d2f57).
// This is a standalone copy for Boss Rush balance changes.
import { recoveryLimit, STARFALL_DELAY, TPS, ABILITY_COST, MORTAR, FAULT,
	BELL_LOCK, CINDERWAKE_BEATS, FULL_DRAW_TICKS, SEAL_TICKS, inFocusZone } from "./sim.js";

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
	cinder: "#ffb347", kiln: "#c8553d", smolder: "#6b5a50", smolderLit: "#ff7a2e", pyre: "#ff6a2a", ash: "#8a7d72", cinderwake: "#f5ad61",
	enemyShot: "#ff5a4a", enemyShotHeavy: "#ff3d8b", tele: "rgba(255,90,74,.55)",
	portal: "#9fe7ff",
	veil: "rgba(214,58,90,.22)", veilEdge: "rgba(255,138,150,.55)", bars: "#2a2f2d", barsLit: "#d63a5a", ward: "#cfe3ff",
	paladin: "#f1c46b", diviner: "#c4a5ff", ninja: "#8fd6a4", shield: "rgba(241,196,107,.72)",
	slow: "rgba(241,196,107,.16)", star: "#ffe9a6", damage: "#ff9b8d",
	hp: "#e2564e", mp: "#5a8de8", hudBack: "rgba(16,18,20,.72)",
};

const SHALLOWS = { floorA: COLORS.sand, floorB: COLORS.sandDark, wall: COLORS.wall, wallTop: COLORS.wallTop };
const FRACTURE = { floorA: "#3d3550", floorB: "#39324b", wall: "#17131f", wallTop: "#2a2338" };
const ASHEN = { floorA: "#3b322d", floorB: "#372e29", wall: "#1a1411", wallTop: "#2c221c" };
const FEN = { floorA: "#354547", floorB: "#303e40", wall: "#171e25", wallTop: "#27323a" };
const SEAL_COURT = { floorA: "#44424a", floorB: "#3c3a43", wall: "#1e1d26", wallTop: "#302d3a" };
const BELL_COURT = { floorA: "#49413a", floorB: "#413a34", wall: "#211c1b", wallTop: "#392e29" };
const PALETTES = { shallows: SHALLOWS, fracture: FRACTURE, ashen: ASHEN, fen: FEN,
	"seal-court": SEAL_COURT, "bell-court": BELL_COURT };

function drawMap(g, st, ox, oy, px, width, height, pal = SHALLOWS) {
	const x0 = Math.max(0, Math.floor(-ox / px)), x1 = Math.min(st.w - 1, Math.floor((width - ox) / px));
	const y0 = Math.max(0, Math.floor(-oy / px)), y1 = Math.min(st.h - 1, Math.floor((height - oy) / px));
	// Whole pixels, one tile wide plus a pixel, so neighbours never leave a seam.
	const P = Math.ceil(px) + 1;
	for (let y = y0; y <= y1; y++) {
		const row = st.tiles[y], below = y + 1 < st.h ? st.tiles[y + 1] : null;
		for (let x = x0; x <= x1; x++) {
			const t = row[x], X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
			if (t === "#") {
				g.fillStyle = pal.wall; g.fillRect(X, Y, P, P);
				// A lit top edge where a wall meets floor below it: light comes from above.
				if (below && below[x] !== "#") { g.fillStyle = pal.wallTop; g.fillRect(X, Y + px * 0.72, P, px * 0.28 + 1); }
			} else if (t === "x") {                       // torn floor: the void under the Rift
				g.fillStyle = COLORS.void; g.fillRect(X, Y, P, P);
				if ((x * 7 + y * 13) % 5 === 0) { g.fillStyle = COLORS.voidSpeck; g.fillRect(X + px * 0.3, Y + px * 0.55, px * 0.08, px * 0.08); }
			} else if (t === "~") {
				g.fillStyle = COLORS.water; g.fillRect(X, Y, P, P);
				g.fillStyle = COLORS.waterLight; g.fillRect(X + px * 0.15, Y + px * 0.3, px * 0.4, px * 0.08);
			} else {
				g.fillStyle = (x + y) % 2 ? pal.floorA : pal.floorB; g.fillRect(X, Y, P, P);
				if (t === "o") {
					g.fillStyle = COLORS.rock; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.84);
					g.fillStyle = COLORS.rockTop; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.22);
				}
			}
		}
	}
}

/* CRACKS (sim.js): a faint seam while closed, a bright flickering one in the second
 * before it opens, and the void while open. */
function drawCracks(g, st, ox, oy, px, calm) {
	if (!st.cracks?.length) return;
	const P = Math.ceil(px) + 1;
	for (const c of st.cracks) {
		for (const [x, y] of c.tiles) {
			const X = Math.floor(ox + x * px), Y = Math.floor(oy + y * px);
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
	}
}

function drawDoors(g, st, ox, oy, px) {
	if (!st.doorCols) return;
	const P = Math.ceil(px) + 1, Y = Math.floor(oy + (st.doorY - 1) * px), H = px * 3;
	st.doorCols.forEach((room, x) => {
		if (room < 0 || !(st.roomLeft[room] > 0)) return;
		const X = Math.floor(ox + x * px);
		if (st.sealed === room) {
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
export function draw(g, st, { width, height, px, aim, at = here, calm = false, ui = 1, bossName = "The boss", auto = false }) {
	const p = st.p, pp = at(p);
	const { ox, oy } = camera(st, width, height, px, pp);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;

	g.fillStyle = "#1b2220"; g.fillRect(0, 0, width, height);
	drawMap(g, st, ox, oy, px, width, height, PALETTES[st.dungeonId] || SHALLOWS);
	drawCracks(g, st, ox, oy, px, calm);
	drawDoors(g, st, ox, oy, px);
	drawHazards(g, st, sx, sy, px);
	drawAbilityFx(g, st, sx, sy, px, pp);
	if (st.shield) {
		circle(g, sx(st.shield.x), sy(st.shield.y), px * st.shield.r, COLORS.shield);
		g.strokeStyle = "#fff0b7"; g.lineWidth = Math.max(2, px * 0.08);
		g.beginPath(); g.arc(sx(st.shield.x), sy(st.shield.y), px * st.shield.r, 0, Math.PI * 2); g.stroke();
	}

	if (st.portal) {
		const pulse = 0.5 + 0.5 * Math.sin(st.tick / 9);
		circle(g, sx(st.portal.x), sy(st.portal.y), px * (0.55 + 0.1 * pulse), "rgba(159,231,255,.35)");
		circle(g, sx(st.portal.x), sy(st.portal.y), px * 0.32, COLORS.portal);
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
			: (COLORS[e.form] ?? (e.type === "smolder" && e.lit ? COLORS.smolderLit : COLORS[e.type]));
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
		} else if (e.form === "cinderwake") {
			circle(g, X, Y, r * 1.08, "rgba(241,152,68,.24)");
			g.save();
			g.translate(X, Y); g.rotate(Math.PI / 4);
			g.fillStyle = col; g.fillRect(-r * 0.61, -r * 0.61, r * 1.22, r * 1.22);
			g.restore();
			circle(g, X, Y, r * 0.38, st.cinderwake.lantern ? "#c5d8e8" : "#fff4ca");
		} else if (e.form === "warden") {
			g.fillStyle = e.flash ? "#faf1ff" : "#aa78d0";
			g.fillRect(X - r * 0.75, Y - r * 0.75, r * 1.5, r * 1.5);
			circle(g, X, Y, r * 0.36, "#39254e");
		} else if (e.form === "bellkeeper") {
			const stunned = st.bellkeeper.mode === "stunned";
			circle(g, X, Y, r, stunned ? (e.flash ? "#fff4bd" : "#cc9755") : "#a88666");
			circle(g, X, Y, r * 0.73, stunned ? "#6e412d" : "#55453d");
			circle(g, X, Y, r * 0.25, stunned ? "#ffda89" : "#988373");
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

	drawPlayer(g, p, sx(pp.x), sy(pp.y), px, aim, st.classId, calm);

	drawShots(g, st.bullets, sx, sy, px, at);
	drawDamageNumbers(g, st.damageNumbers || [], sx, sy, px, st.tick);
	drawHud(g, st, { width, height, px, ui, auto });
	drawBossBar(g, st, { width, ui, name: bossName });
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
	const cue = b.form === "cinderwake" ? st.cinderwake : null;
	const beat = cue && CINDERWAKE_BEATS[cue.index];
	const W = Math.min(width * (beat ? 0.64 : 0.44), 520 * ui), H = Math.max(8, 12 * ui), X = width / 2 - W / 2, Y = 30 * ui;
	g.font = `600 ${Math.round(14 * ui)}px "Cinzel", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	g.fillStyle = "rgba(10,12,14,.75)"; g.fillText(name, width / 2 + 1, Y - 11 * ui + 1.5);
	g.fillStyle = "#f6c2bc"; g.fillText(name, width / 2, Y - 11 * ui);
	g.textAlign = "left";
	g.fillStyle = "rgba(10,12,14,.78)"; g.fillRect(X - 3, Y - 3, W + 6, H + 6);
	g.fillStyle = "#3a1f24"; g.fillRect(X, Y, W, H);
	g.fillStyle = beat ? (beat.damage ? COLORS.cinderwake : "#8dddc8") : COLORS.boss;
	const filled = beat ? Math.min(1, cue.progress / beat.goal) : b.hp / b.maxHp;
	g.fillRect(X, Y, W * filled, H);
	const bellkeeper = st.bellkeeper;
	let hint;
	if (beat) hint = `${cue.index + 1}/${CINDERWAKE_BEATS.length} · ${beat.name} · ${beat.damage ? "Land hits" : "Stay with the lantern"}`;
	else if (b.form === "warden") {
		const used = st.seals.filter((seal) => seal.progress === SEAL_TICKS).length;
		hint = used < st.seals.length ? `${used}/${st.seals.length} seals · Hold a seal to deal 300 damage` : "All seals captured";
	} else if (bellkeeper) {
		hint = bellkeeper.mode === "stunned" ?
			`Stunned · ${Math.ceil((bellkeeper.until - st.tick) / TPS)}s to attack` : "Lure the charge into a bell";
	}
	if (hint) {
		g.font = `600 ${Math.round(15 * ui)}px "Crimson Pro", Georgia, serif`;
		g.textAlign = "center";
		g.fillStyle = "rgba(10,12,14,.85)"; g.fillText(hint, width / 2 + 1, Y + H + 13 * ui + 1);
		g.fillStyle = "#fff4ca"; g.fillText(hint, width / 2, Y + H + 13 * ui);
		g.textAlign = "left";
	}
	if (!beat && b.phase === 1) { g.fillStyle = "rgba(255,240,235,.8)"; g.fillRect(X + W / 2 - 1, Y - 2, 2, H + 4); }
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

/* The boss's mortar: burning ground (a flickering orange pool that fades in its last
 * second), and each shell's landing spot, ringed red and filling as it comes. */
function drawHazards(g, st, sx, sy, px) {
	drawRaidObjectives(g, st, sx, sy, px);
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
	const lantern = st.cinderwake?.lantern;
	if (lantern) {
		const x = sx(lantern.x), y = sy(lantern.y);
		circle(g, x, y, px * lantern.r, lantern.lit ? "rgba(146,255,213,.30)" : "rgba(250,207,114,.17)");
		g.strokeStyle = lantern.lit ? "#b4ffe2" : "#f9cb72";
		g.lineWidth = Math.max(2, px * 0.04);
		g.beginPath(); g.arc(x, y, px * lantern.r, 0, Math.PI * 2); g.stroke();
		circle(g, x, y, px * 0.23, "#ffbd52");
		circle(g, x, y, px * 0.11, "#fff8cb");
	}
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
		g.strokeStyle = "#ff5a3c";
		g.lineWidth = lw;
		g.beginPath(); g.arc(sx(m.x), sy(m.y), px * m.r, 0, Math.PI * 2); g.stroke();
		circle(g, sx(m.x), sy(m.y), px * m.r * k, "rgba(255,90,60,.3)");
	}
}

function drawRaidObjectives(g, st, sx, sy, px) {
	for (const seal of st.seals) {
		const x = sx(seal.x), y = sy(seal.y), r = seal.r * px;
		const used = seal.progress === SEAL_TICKS;
		circle(g, x, y, r, used ? "rgba(134,167,152,.11)" : "rgba(160,123,208,.18)");
		g.strokeStyle = used ? "#658a7c" : "#ac8bc6"; g.lineWidth = Math.max(2, px * 0.05);
		g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
		if (seal.progress && !used) {
			g.strokeStyle = seal.occupied ? "#fff0be" : "#d0a6ef"; g.lineWidth *= 2;
			g.beginPath(); g.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * seal.progress / SEAL_TICKS); g.stroke();
		}
		if (seal.volley) {
			const from = sy(seal.volley.y), to = sy(seal.volley.endY);
			g.fillStyle = "rgba(238,123,180,.30)";
			g.fillRect(x - px * 0.89, Math.min(from, to), px * 1.78, Math.abs(from - to));
		}
	}
	const state = st.bellkeeper;
	if (!state) return;
	const boss = st.enemies.find((e) => e.form === "bellkeeper" && e.active && e.hp > 0);
	if (boss && (state.mode === "windup" || state.mode === "charge")) {
		const x = sx(boss.x), y = sy(boss.y);
		const tracking = state.mode === "windup" && state.until - st.tick > BELL_LOCK;
		g.strokeStyle = tracking ? "rgba(250,208,146,.40)" : "rgba(255,124,98,.78)";
		g.lineWidth = Math.max(2, px * (tracking ? 0.10 : 0.18));
		g.beginPath(); g.moveTo(x, y); g.lineTo(x + state.dx * px * 20, y + state.dy * px * 20); g.stroke();
	}
	for (const bell of state.bells) {
		const x = sx(bell.x), y = sy(bell.y), r = bell.r * px;
		const ready = bell.readyAt <= st.tick;
		circle(g, x, y, r, ready ? "#87623f" : "#51463e");
		circle(g, x, y, r * 0.72, ready ? "#efbc67" : "#7e6d53");
		circle(g, x, y, r * 0.24, ready ? "#ffe8a4" : "#b29370");
		if (boss && bell.pulseAt > st.tick && bell.pulseAt - st.tick <= 34) {
			g.strokeStyle = "#ffb067"; g.lineWidth = Math.max(2, px * 0.08);
			g.beginPath(); g.arc(x, y, r * 2, 0, Math.PI * 2); g.stroke();
		}
	}
}

/* What an ability leaves on the ground: the Paladin's field (gold, around the player),
 * a falling star (its spot ringed, filling as it comes) and its blast, and the
 * Ninja's counter — a white ring while it is ready to catch a hit, a solid guard
 * just after, and a gold ring while the next shot is countered. Shared by the town. */
function drawAbilityFx(g, st, sx, sy, px, pp) {
	const p = st.p, lw = Math.max(1, px * 0.05);
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

/* Empowered shots have a gold-white core, a pulsing halo and a gold trail. */
function drawPowerTrail(g, X, Y, b, px, scale) {
	const L = px * 0.09 * scale, pulse = 0.75 + 0.25 * Math.sin((b.x + b.y) * 3);
	g.lineCap = "round";
	g.strokeStyle = "rgba(255,196,80,.35)"; g.lineWidth = Math.max(4, px * 0.42) * scale;
	g.beginPath(); g.moveTo(X, Y); g.lineTo(X - b.vx * L, Y - b.vy * L); g.stroke();
	g.strokeStyle = "rgba(255,240,200,.9)"; g.lineWidth = Math.max(2, px * 0.14) * scale;
	g.beginPath(); g.moveTo(X, Y); g.lineTo(X - b.vx * L * 0.6, Y - b.vy * L * 0.6); g.stroke();
	g.lineCap = "butt";
	circle(g, X, Y, px * 0.5 * pulse * scale, "rgba(255,206,92,.28)");
}

function drawShots(g, bullets, sx, sy, px, at) {
	for (const b of bullets) {
		const bp = at(b), X = sx(bp.x), Y = sy(bp.y);
		const powerScale = b.focused ? 0.5 : 1;
		if (b.owner === "p" && b.power) drawPowerTrail(g, X, Y, b, px, powerScale);
		if (b.owner === "p" && b.look === "flare") {         // the Flare Bow's flare: a bright ball of fire
			circle(g, X, Y, px * 0.24, "rgba(120,214,255,.45)");
			circle(g, X, Y, px * 0.14, "#e6faff");
		} else if (b.owner === "p" && b.look === "star") {   // a spinning four-point star
			const r = px * 0.2 * (b.power ? 2 * powerScale : 1), a = (b.x + b.y) * 2.4;
			g.fillStyle = b.power ? "#fff1c2" : "#dfe7ea";
			g.beginPath();
			for (let i = 0; i < 8; i++) {
				const rr = i % 2 ? r * 0.38 : r, t = a + (i * Math.PI) / 4;
				g.lineTo(X + Math.cos(t) * rr, Y + Math.sin(t) * rr);
			}
			g.closePath(); g.fill();
			if (b.power) { g.strokeStyle = "#ffb43c"; g.lineWidth = Math.max(1.5, px * 0.05) * powerScale; g.stroke(); }
		} else if (b.owner === "p") {
			g.strokeStyle = b.power ? "#fff1c2" : COLORS.playerShot;
			g.lineWidth = b.power ? Math.max(2, b.r * px * 2) * powerScale : Math.max(2, b.r * px * 0.9);
			const tail = b.look === "blade" ? 0.022 : 0.03;
			const length = tail * px * powerScale;
			g.beginPath(); g.moveTo(X, Y); g.lineTo(X - b.vx * length, Y - b.vy * length); g.stroke();
		} else if (b.shard) {                                 // a shatter shard: a crystal that will burst
			const r = b.r * px * 1.2;
			g.beginPath(); g.moveTo(X, Y - r); g.lineTo(X + r * 0.7, Y); g.lineTo(X, Y + r); g.lineTo(X - r * 0.7, Y); g.closePath();
			g.fillStyle = COLORS.enemyShotHeavy; g.fill();
			g.strokeStyle = "rgba(255,240,235,.9)"; g.lineWidth = Math.max(1, px * 0.05); g.stroke();
		} else {
			circle(g, X, Y, b.r * px * 1.15, "rgba(255,240,235,.9)");
			const color = b.src === "boss:lane-spiral" ? "#ffc45e" : b.src === "boss:sweep" ? "#d591fa"
				: b.dmg >= 30 ? COLORS.enemyShotHeavy : COLORS.enemyShot;
			circle(g, X, Y, b.r * px, color);
		}
	}
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

function drawDamageNumbers(g, numbers, sx, sy, px, tick) {
	g.font = `bold ${Math.round(Math.max(13, px * 0.38))}px "Crimson Pro", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	for (const f of numbers) {
		// Yours: red, "-7", over the player. What you dealt: pale gold, "7", over the enemy.
		const rise = ((f.foe ? 36 : 45) - (f.until - tick)) * 0.018;
		const n = Number.isInteger(f.amount) ? String(f.amount) : f.amount.toFixed(1);
		const text = f.foe ? n : `-${n}`, y = sy(f.y - (f.foe ? 0.25 : 0.55) - rise);
		g.fillStyle = "rgba(16,18,20,.8)"; g.fillText(text, sx(f.x) + 1, y + 1.5);
		g.fillStyle = f.foe ? "#ffe9a6" : COLORS.damage; g.fillText(text, sx(f.x), y);
	}
	g.textAlign = "left";
}

function drawHud(g, st, { width, height, px, ui = 1, auto = false }) {
	const p = st.p, s = st.stats;
	const W = Math.min(320 * ui, width * 0.42), H = Math.max(10, px * 0.32) * ui, X = 16;
	const Y = height - 24 - H * 2;
	g.fillStyle = COLORS.hudBack; g.fillRect(X - 8, Y - 8, W + 16, H * 2 + 24);
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
		const draw = p.drawUntil ? Math.round((1 - (p.drawUntil - st.tick) / FULL_DRAW_TICKS) * 100) : null;
		const label = draw !== null ? `Full Draw ${draw}%` : ok ? "Ready" : cd ? `${Math.ceil(p.abilityCd / TPS)}s` : `${cost} MP`;
		g.fillText(label, X + W - 6, Y + H * 1.5 + 9);
		g.textAlign = "left";
	}
}
