/* Halcyon Rift's greybox renderer: colored shapes on a Canvas 2D (design §23,
 * art direction §2.3). It only DRAWS the simulation's state — nothing here may
 * change it, so the fight is the same whatever the frame rate.
 *
 * The color roles are the art doc's, and they are the one part of this file that
 * outlives the greybox: the environment quietest (the Shallows' sand, water and
 * rock), the player cyan/white, every enemy and every enemy shot red/orange/
 * magenta, pickups gold (loot) and green (healing).
 */
import { recoveryLimit } from "./sim.js";

export const COLORS = {
	wall: "#3c4a45", wallTop: "#4a5a54", sand: "#a99e80", sandDark: "#a3987a",
	water: "#5f8f93", waterLight: "#6d9ea1", rock: "#7b7a70", rockTop: "#918f84",
	player: "#7fe3f0", playerCore: "#f4fdff", playerShot: "#c9f6ff",
	chaser: "#e8573f", shooter: "#ef8a3a", radial: "#c8458f", boss: "#d63a5a",
	enemyShot: "#ff5a4a", enemyShotHeavy: "#ff3d8b", tele: "rgba(255,90,74,.55)",
	heal: "#6fd36a", bag: "#e9c25a", portal: "#9fe7ff",
	hp: "#e2564e", hpLimit: "#f3e2c0", mp: "#5a8de8", hudBack: "rgba(16,18,20,.72)",
};

/* The map drawn once per dungeon, at `px` pixels a tile. */
export function bakeMap(st, px) {
	const c = document.createElement("canvas");
	c.width = st.w * px; c.height = st.h * px;
	const g = c.getContext("2d");
	for (let y = 0; y < st.h; y++) {
		for (let x = 0; x < st.w; x++) {
			const t = st.tiles[y][x], X = x * px, Y = y * px;
			if (t === "#") {
				g.fillStyle = COLORS.wall; g.fillRect(X, Y, px, px);
				// A lit top edge where a wall meets floor below it: light comes from above.
				if (y + 1 < st.h && st.tiles[y + 1][x] !== "#") { g.fillStyle = COLORS.wallTop; g.fillRect(X, Y + px * 0.72, px, px * 0.28); }
			} else {
				g.fillStyle = (x + y) % 2 ? COLORS.sand : COLORS.sandDark; g.fillRect(X, Y, px, px);
				if (t === "~") {
					g.fillStyle = COLORS.water; g.fillRect(X, Y, px, px);
					g.fillStyle = COLORS.waterLight; g.fillRect(X + px * 0.15, Y + px * 0.3, px * 0.4, px * 0.08);
				} else if (t === "o") {
					g.fillStyle = COLORS.rock; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.84);
					g.fillStyle = COLORS.rockTop; g.fillRect(X + px * 0.06, Y + px * 0.12, px * 0.88, px * 0.22);
				}
			}
		}
	}
	return c;
}

function circle(g, x, y, r, fill) {
	g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = fill; g.fill();
}

/* Where the world sits on the canvas: it follows the player, clamped so the map
 * never scrolls past its edge. The page uses it too, to turn the mouse into aim. */
export function camera(st, width, height, px) {
	const vw = width / px, vh = height / px;
	const cx = st.w < vw ? st.w / 2 : Math.max(vw / 2, Math.min(st.w - vw / 2, st.p.x));
	const cy = st.h < vh ? st.h / 2 : Math.max(vh / 2, Math.min(st.h - vh / 2, st.p.y));
	return { ox: width / 2 - cx * px, oy: height / 2 - cy * px };
}

/* One frame, at `px` pixels a tile. */
export function draw(g, st, map, { width, height, px, aim, notes = [] }) {
	const p = st.p;
	const { ox, oy } = camera(st, width, height, px);
	const sx = (x) => ox + x * px, sy = (y) => oy + y * px;

	g.fillStyle = "#1b2220"; g.fillRect(0, 0, width, height);
	g.drawImage(map, Math.round(ox), Math.round(oy));

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
	if (st.portal) {
		const pulse = 0.5 + 0.5 * Math.sin(st.tick / 9);
		circle(g, sx(st.portal.x), sy(st.portal.y), px * (0.55 + 0.1 * pulse), "rgba(159,231,255,.35)");
		circle(g, sx(st.portal.x), sy(st.portal.y), px * 0.32, COLORS.portal);
	}

	for (const e of st.enemies) {
		if (e.hp <= 0) continue;
		const X = sx(e.x), Y = sy(e.y), r = e.r * px;
		// Telegraphs: what is about to fire says so, and says where.
		if (e.tele > 0 && e.active) {
			g.strokeStyle = COLORS.tele; g.lineWidth = Math.max(1, px * 0.05);
			if (e.type === "shooter") {
				g.beginPath(); g.moveTo(X, Y); g.lineTo(sx(p.x), sy(p.y)); g.stroke();
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

	// The player: cyan body, white core, a tick toward the aim.
	const pr = p.r * px, PX = sx(p.x), PY = sy(p.y);
	circle(g, PX, PY, pr + px * 0.06, p.hurt > 0 ? "#ffffff" : "#1d5f6a");
	circle(g, PX, PY, pr, COLORS.player);
	circle(g, PX, PY, pr * 0.42, COLORS.playerCore);
	if (aim) {
		const l = Math.hypot(aim.x, aim.y) || 1;
		g.strokeStyle = COLORS.playerCore; g.lineWidth = Math.max(1.5, px * 0.06);
		g.beginPath(); g.moveTo(PX + aim.x / l * pr * 1.2, PY + aim.y / l * pr * 1.2);
		g.lineTo(PX + aim.x / l * pr * 1.9, PY + aim.y / l * pr * 1.9); g.stroke();
	}

	for (const b of st.bullets) {
		if (b.owner === "p") {
			g.strokeStyle = COLORS.playerShot; g.lineWidth = Math.max(2, b.r * px * 0.9);
			g.beginPath(); g.moveTo(sx(b.x), sy(b.y)); g.lineTo(sx(b.x - b.vx * 0.03), sy(b.y - b.vy * 0.03)); g.stroke();
		} else {
			circle(g, sx(b.x), sy(b.y), b.r * px * 1.15, "rgba(255,240,235,.9)");
			circle(g, sx(b.x), sy(b.y), b.r * px, b.dmg >= 30 ? COLORS.enemyShotHeavy : COLORS.enemyShot);
		}
	}

	drawHud(g, st, { width, height, px, notes });
}

function drawHud(g, st, { width, height, px, notes }) {
	const p = st.p, s = st.stats;
	const W = Math.min(320, width * 0.42), H = Math.max(10, px * 0.32), X = 16, Y = height - 16 - H * 2 - 8;
	g.fillStyle = COLORS.hudBack; g.fillRect(X - 8, Y - 8, W + 16, H * 2 + 24);
	// HP, with the recovery limit drawn as a pale cap: regeneration stops there.
	g.fillStyle = "#3a1c1a"; g.fillRect(X, Y, W, H);
	g.fillStyle = "rgba(243,226,192,.18)"; g.fillRect(X, Y, W * (recoveryLimit(st) / s.maxHp), H);
	g.fillStyle = COLORS.hp; g.fillRect(X, Y, W * (p.hp / s.maxHp), H);
	g.fillStyle = COLORS.hpLimit; g.fillRect(X + W * (recoveryLimit(st) / s.maxHp) - 1.5, Y - 2, 3, H + 4);
	g.fillStyle = "#1a2238"; g.fillRect(X, Y + H + 8, W, H);
	g.fillStyle = COLORS.mp; g.fillRect(X, Y + H + 8, W * (p.mp / s.maxMp), H);
	g.fillStyle = "#f4efe4"; g.font = `${Math.round(H * 0.85)}px "Crimson Pro", Georgia, serif`;
	g.textBaseline = "middle";
	g.fillText(`${Math.ceil(p.hp)} / ${Math.round(s.maxHp)}`, X + 6, Y + H / 2 + 1);
	g.fillText(`${Math.floor(p.mp)} / ${Math.round(s.maxMp)}`, X + 6, Y + H * 1.5 + 9);

	// Notes (what was picked up, what is under you) — newest last, bottom right.
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
