/* Halcyon Rift's greybox renderer: colored shapes on a Canvas 2D (design §23,
 * art direction §2.3). It only DRAWS the simulation's state — nothing here may
 * change it, so the fight is the same whatever the frame rate.
 *
 * The color roles are the art doc's, and they are the one part of this file that
 * outlives the greybox: the environment quietest (the Shallows' sand, water and
 * rock), the player cyan/white, every enemy and every enemy shot red/orange/
 * magenta, pickups gold (loot) and green (healing).
 */
import { recoveryLimit, xpProgress, STARFALL_DELAY, TPS } from "./sim.js";

export const COLORS = {
	wall: "#3c4a45", wallTop: "#4a5a54", sand: "#a99e80", sandDark: "#a3987a",
	water: "#5f8f93", waterLight: "#6d9ea1", rock: "#7b7a70", rockTop: "#918f84",
	player: "#7fe3f0", playerCore: "#f4fdff", playerShot: "#c9f6ff",
	chaser: "#e8573f", shooter: "#ef8a3a", radial: "#c8458f", boss: "#d63a5a",
	enemyShot: "#ff5a4a", enemyShotHeavy: "#ff3d8b", tele: "rgba(255,90,74,.55)",
	heal: "#6fd36a", bag: "#e9c25a", portal: "#9fe7ff", dream: "#b9a7ff",
	paladin: "#f1c46b", diviner: "#c4a5ff", ninja: "#8fd6a4", shield: "rgba(241,196,107,.72)",
	slow: "rgba(241,196,107,.16)", star: "#ffe9a6", damage: "#ff9b8d",
	hp: "#e2564e", mp: "#5a8de8", xp: "#9d8ff2", hudBack: "rgba(16,18,20,.72)",
	// The town: cool flagstone, so the safe place never reads like a dungeon floor.
	stone: "#56605c", stoneDark: "#515b57", townWall: "#2e3836", townWallTop: "#3c4845",
	vault: "#6b4a2a", vaultTrim: "#e9c25a", forge: "#4a4f55", forgeFire: "#ef8a3a", realm: "#9d8ff2",
};

const SHALLOWS = { floorA: COLORS.sand, floorB: COLORS.sandDark, wall: COLORS.wall, wallTop: COLORS.wallTop };
const TOWN = { floorA: COLORS.stone, floorB: COLORS.stoneDark, wall: COLORS.townWall, wallTop: COLORS.townWallTop };

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
export function draw(g, st, { width, height, px, aim, notes = [], at = here }) {
	const p = st.p, pp = at(p);
	const { ox, oy } = camera(st, width, height, px, pp, true);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;

	g.fillStyle = "#1b2220"; g.fillRect(0, 0, width, height);
	drawMap(g, st, ox, oy, px, width, height);
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
	for (const b of st.bags) {                        // loot: gold
		const X = sx(b.x), Y = sy(b.y);
		g.fillStyle = COLORS.bag; g.fillRect(X - px * 0.22, Y - px * 0.18, px * 0.44, px * 0.38);
		g.fillStyle = "#7a5a1c"; g.fillRect(X - px * 0.22, Y - px * 0.06, px * 0.44, px * 0.05);
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

	for (const e of st.enemies) {
		if (e.hp <= 0) continue;
		const ep = at(e), X = sx(ep.x), Y = sy(ep.y), r = e.r * px;
		// Telegraphs: what is about to fire says so, and says where.
		if (e.tele > 0 && e.active) {
			g.strokeStyle = COLORS.tele; g.lineWidth = Math.max(1, px * 0.05);
			if (e.type === "shooter") {
				g.beginPath(); g.moveTo(X, Y); g.lineTo(sx(pp.x), sy(pp.y)); g.stroke();
			} else {
				const grow = e.type === "boss" && e.phase === 0 ? 1.6 : 1 + (1 - e.tele / 50) * 0.8;
				g.beginPath(); g.arc(X, Y, r * grow + px * 0.2, 0, Math.PI * 2); g.stroke();
			}
		}
		const col = e.flash > 0 ? "#fff3ea" : COLORS[e.type];
		if (e.type === "chaser") {
			g.save(); g.translate(X, Y); g.rotate(Math.PI / 4); g.fillStyle = col; g.fillRect(-r * 0.8, -r * 0.8, r * 1.6, r * 1.6); g.restore();
		} else if (e.type === "shooter") {
			g.beginPath(); g.moveTo(X, Y - r); g.lineTo(X + r, Y + r * 0.8); g.lineTo(X - r, Y + r * 0.8); g.closePath(); g.fillStyle = col; g.fill();
		} else if (e.type === "radial") {
			circle(g, X, Y, r, col); circle(g, X, Y, r * 0.45, "#5c1b3f");
		} else {
			circle(g, X, Y, r, e.phase === 0 && st.tick % 10 < 5 ? "#fff3ea" : col);
			circle(g, X, Y, r * 0.55, "#5a1424");
		}
		if (e.active && e.hp < e.maxHp) {
			const w = Math.max(px * 0.8, r * 2);
			g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(X - w / 2, Y - r - px * 0.28, w, px * 0.09);
			g.fillStyle = COLORS.hp; g.fillRect(X - w / 2, Y - r - px * 0.28, w * (e.hp / e.maxHp), px * 0.09);
		}
	}

	drawPlayer(g, p, sx(pp.x), sy(pp.y), px, aim, st.classId);

	drawShots(g, st.bullets, sx, sy, px, at);
	drawDamageNumbers(g, st.damageNumbers || [], sx, sy, px, st.tick);
	drawHud(g, st, { width, height, px, notes });
}

/* What an ability leaves on the ground: the Paladin's field (gold, around the player),
 * a falling star (its spot ringed, filling as it comes) and its blast, and the
 * Ninja's counter — a white ring while it is ready to catch a hit, a solid guard
 * just after, and a gold ring while the next shot is countered. Shared by the town. */
function drawAbilityFx(g, st, sx, sy, px, pp) {
	const p = st.p, lw = Math.max(1, px * 0.05);
	if (st.slowUntil > st.tick) {
		circle(g, sx(pp.x), sy(pp.y), px * (st.slowR || 3), COLORS.slow);
		g.strokeStyle = COLORS.paladin; g.lineWidth = lw;
		g.beginPath(); g.arc(sx(pp.x), sy(pp.y), px * (st.slowR || 3), 0, Math.PI * 2); g.stroke();
	}
	for (const f of st.starfalls || []) {
		const k = Math.min(1, Math.max(0, 1 - (f.at - st.tick) / STARFALL_DELAY));
		g.strokeStyle = COLORS.star; g.lineWidth = lw;
		g.beginPath(); g.arc(sx(f.x), sy(f.y), px * f.r, 0, Math.PI * 2); g.stroke();
		circle(g, sx(f.x), sy(f.y), px * f.r * k, "rgba(255,233,166,.28)");
	}
	for (const b of st.blasts || []) {
		const a = Math.max(0, (b.until - st.tick) / 18);
		circle(g, sx(b.x), sy(b.y), px * b.r * (1.1 - 0.1 * a), `rgba(255,240,190,${(0.75 * a).toFixed(3)})`);
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

function drawShots(g, bullets, sx, sy, px, at) {
	for (const b of bullets) {
		const bp = at(b), X = sx(bp.x), Y = sy(bp.y);
		if (b.owner === "p" && b.power) drawPowerTrail(g, X, Y, b, px);
		if (b.owner === "p" && b.look === "star") {          // a spinning four-point star
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
		} else {
			circle(g, X, Y, b.r * px * 1.15, "rgba(255,240,235,.9)");
			circle(g, X, Y, b.r * px, b.dmg >= 30 ? COLORS.enemyShotHeavy : COLORS.enemyShot);
		}
	}
}

/* The player: cyan body, white core, a tick toward the aim. */
function drawPlayer(g, p, PX, PY, px, aim, classId = "ranger") {
	const pr = p.r * px;
	const body = COLORS[classId] && classId !== "ranger" ? COLORS[classId] : COLORS.player;
	circle(g, PX, PY, pr + px * 0.06, p.hurt > 0 ? "#ffffff" : "#1d5f6a");
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
		const rise = (45 - (f.until - tick)) * 0.018;
		const text = Number.isInteger(f.amount) ? `-${f.amount}` : `-${f.amount.toFixed(1)}`;
		g.fillStyle = "rgba(16,18,20,.8)"; g.fillText(text, sx(f.x) + 1, sy(f.y - 0.55 - rise) + 1.5);
		g.fillStyle = COLORS.damage; g.fillText(text, sx(f.x), sy(f.y - 0.55 - rise));
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
export function drawTown(g, st, { width, height, px, at = here, notes = [], prompt = null, aim = null, dps = () => 0 }) {
	const pp = at(st.p);
	const { ox, oy } = camera(st, width, height, px, pp);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;
	g.fillStyle = "#151b1a"; g.fillRect(0, 0, width, height);
	drawMap(g, st, ox, oy, px, width, height, TOWN);

	for (const s of st.stations) {
		const X = sx(s.x), Y = sy(s.y), lit = st.near === s.id;
		if (s.kind === "portal" || s.kind === "dream") {
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
		label(g, s.label, X, Y - (s.kind === "portal" ? px * 1.25 : s.hh * px + px * 0.42), px,
			lit ? "#ffffff" : "#e6e1f7");
	}

	// The practice posts: a straw target on a stake, and what it is taking a second.
	for (const q of st.posts) {
		const X = sx(q.x), Y = sy(q.y), R = q.r * px;
		g.fillStyle = "#5a4127"; g.fillRect(X - px * 0.07, Y, px * 0.14, R * 1.3);
		circle(g, X, Y, R, "#c9a25e");
		circle(g, X, Y, R * 0.66, "#efe3c4");
		circle(g, X, Y, R * 0.33, "#c0503f");
		const d = dps(q);
		// Below the stake: the hit numbers float up from above the post.
		if (d > 0) label(g, `${d} / s`, X, Y + R * 1.3 + px * 0.38, px, "#e9c25a");
	}
	drawAbilityFx(g, st, sx, sy, px, pp);
	drawPlayer(g, st.p, sx(pp.x), sy(pp.y), px, aim, st.classId);
	drawShots(g, st.bullets, sx, sy, px, at);
	g.font = `bold ${Math.round(Math.max(12, px * 0.4))}px "Crimson Pro", Georgia, serif`;
	g.textAlign = "center"; g.textBaseline = "middle";
	for (const f of st.floats) {
		const rise = (40 - (f.until - st.tick)) * 0.012;
		g.fillStyle = "#fff4d6"; g.fillText(f.text, sx(f.x), sy(f.y - rise));
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
	drawNotes(g, notes, width, height, px);
}

/* What the prompt for a station says, given whether it can be used now. */
export function promptFor(station, ready = true) {
	if (!station) return null;
	if (station.kind === "portal") return ready ? `E — Enter ${station.label}` : "Make a character to enter";
	if (station.kind === "dream") return ready ? `E — ${PROMPT.dream}` : "Make a character to practice";
	return `E — ${PROMPT[station.kind]}`;
}

function drawHud(g, st, { width, height, px, notes }) {
	const p = st.p, s = st.stats;
	const W = Math.min(320, width * 0.42), H = Math.max(10, px * 0.32), X = 16;
	const XH = Math.max(4, Math.round(H * 0.4)), Y = height - 16 - H * 2 - 8 - XH - 8;
	g.fillStyle = COLORS.hudBack; g.fillRect(X - 8, Y - 8, W + 16, H * 2 + XH + 32);
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
	// The ability's cooldown, at the MP bar's right end.
	if (s.abilityKind) {
		const cd = p.abilityCd || 0;
		g.textAlign = "right";
		g.fillStyle = cd > 0 ? "#c9cfd6" : "#9fe7ff";
		g.fillText(cd > 0 ? `${(cd / TPS).toFixed(1)}s` : "Ready", X + W - 6, Y + H * 1.5 + 9);
		g.textAlign = "left";
	}
	// XP inside the level, and the level itself at the bar's right end.
	const xp = xpProgress(st.levels, st.hero.xp), XY = Y + H * 2 + 16;
	g.fillStyle = "rgba(157,143,242,.2)"; g.fillRect(X, XY, W, XH);
	g.fillStyle = COLORS.xp; g.fillRect(X, XY, W * (xp.span ? xp.into / xp.span : 1), XH);
	g.textAlign = "right"; g.fillStyle = "#f4efe4";
	g.fillText(`Lv ${st.hero.level}`, X + W - 6, Y + H / 2 + 1);
	g.textAlign = "left";
	const timer = formatRiftTime(st.bossTimeTicks == null ? st.elapsedTicks : st.bossTimeTicks);
	g.fillStyle = COLORS.hudBack; g.fillRect(width - 154, 16, 138, 30);
	g.fillStyle = "#f4efe4"; g.font = `${Math.round(Math.max(13, px * 0.38))}px "Crimson Pro", Georgia, serif`;
	g.fillText(`${st.practice ? "Dream " : "Rift "}${timer}`, width - 144, 31);

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
