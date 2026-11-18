/* Halcyon Rift — the fight, simulated in the browser (design §18.5).
 *
 * A PURE module: no DOM, no React, no renderer, no clock. `step(state, input)`
 * advances exactly one fixed tick of 1/60 s and is DETERMINISTIC — same dungeon,
 * same loadout, same inputs gives the same run on any browser:
 *   - all randomness comes from the seeded generator below (never Math.random);
 *   - timers are integer TICKS, never wall-clock;
 *   - no Math.sin/cos/atan2/exp: engines may differ in their last bit, so the
 *     module carries its own `dsin`/`dcos` built from + - * / only, which IEEE
 *     754 makes exact everywhere. Math.sqrt/round/floor are exact too.
 *
 * What the server learns of a run comes from `state.events` (kill, pickup,
 * death, recall, complete) — the page queues them (design §18.4), all but the
 * ones marked `local` (a heal: the server keeps no HP). The server
 * never simulates; it checks those claims against the dungeon it generated.
 *
 * GREYBOX: every number below is a placeholder to tune by playing (design §23).
 */

export const TPS = 60;
export const DT = 1 / TPS;
const PI = 3.141592653589793;
const TAU = 6.283185307179586;
const HALF_PI = 1.5707963267948966;

// ── deterministic maths ─────────────────────────────────────────────────────
export function dsin(a) {
	a = a - TAU * Math.round(a / TAU);                 // [-PI, PI]
	if (a > HALF_PI) a = PI - a; else if (a < -HALF_PI) a = -PI - a;
	const a2 = a * a;                                  // Taylor to a^13: < 1e-9 on [-PI/2, PI/2]
	return a * (1 - a2 / 6 * (1 - a2 / 20 * (1 - a2 / 42 * (1 - a2 / 72 * (1 - a2 / 110 * (1 - a2 / 156))))));
}
export const dcos = (a) => dsin(a + HALF_PI);

function hashSeed(str) {
	let h = 2166136261 >>> 0;
	for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
	return h;
}
function rand(st) {                                  // mulberry32, its state in the sim state
	st.rng = (st.rng + 0x6D2B79F5) >>> 0;
	let t = st.rng;
	t = Math.imul(t ^ (t >>> 15), t | 1);
	t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

// ── tuning (greybox) ────────────────────────────────────────────────────────
export const PLAYER_R = 0.32;
export const PLAYER_SPEED = 5.6;                     // tiles / s
export const REACH = 1.3;                            // how close E has to be
export const RECOVERY_MARGIN = 40;                   // design §9.2: limit = min(max, lowest + margin)
export const HEAL = 35;                              // a heal pickup: +HP and +limit
export const ABILITY_COST = 30;

export const ENEMY = {
	chaser: { hp: 40, r: 0.4, speed: 3.4, touch: 16 },
	shooter: { hp: 35, r: 0.38, speed: 2.4 },
	radial: { hp: 70, r: 0.45, speed: 0 },
	boss: { hp: 900, r: 1.0, speed: 1.2 },
};

const WEAPONS = {
	shortbow: { dmg: 12, rate: 4.5, range: 7.5 },
	longbow: { dmg: 21, rate: 2.6, range: 10 },
};

/* A character's numbers from what it wears. `gear` is the equipped items as the
 * server lists them ({base_id, tier, enchants: [{id, q}]}). */
export function statsFor(gear = []) {
	const s = { maxHp: 100, maxMp: 100, dmg: 6, rate: 3, range: 6, shotSpeed: 14, def: 0,
		hpRegen: 1.2, mpRegen: 6, ap: 1, arrows: 0, abilityDmg: 0, pierce: 0 };
	for (const it of gear) {
		const t = 1 + 0.2 * ((it.tier || 1) - 1);
		const w = WEAPONS[it.base_id];
		if (w) { s.dmg = w.dmg * t; s.rate = w.rate; s.range = w.range; }
		if (it.base_id === "leather_vest") { s.def += 2 * t; s.maxHp += 10 * ((it.tier || 1) - 1); }
		if (it.base_id === "volley_quiver") { s.arrows = 7; s.abilityDmg = 15 * t; }
		if (it.base_id === "band_of_vigor") s.maxHp += 15 * t;
		if (it.base_id === "band_of_focus") { s.maxMp += 15 * t; s.mpRegen += 1.5; }
		if (it.base_id === "kingfisher_eye") { s.pierce = 1; s.dmg *= 1.1; }
		for (const e of it.enchants || []) {
			const q = e.q;
			if (e.id === "max_hp") s.maxHp += 20 * q;
			else if (e.id === "max_mp") s.maxMp += 20 * q;
			else if (e.id === "attack") s.dmg *= 1 + 0.2 * q;
			else if (e.id === "defense") s.def += 4 * q;
			else if (e.id === "attack_speed") s.rate *= 1 + 0.2 * q;
			else if (e.id === "ability_power") s.ap += 0.25 * q;
			else if (e.id === "mp_regen") s.mpRegen += 3 * q;
			else if (e.id === "hp_regen") s.hpRegen += 1.5 * q;
		}
	}
	s.abilityDmg *= s.ap;
	return s;
}

// ── the map ─────────────────────────────────────────────────────────────────
function tileAt(st, x, y) {
	const ty = Math.floor(y), tx = Math.floor(x);
	if (ty < 0 || ty >= st.h || tx < 0 || tx >= st.w) return "#";
	return st.tiles[ty][tx];
}
const walkSolid = (c) => c === "#" || c === "o" || c === "~";
const shotSolid = (c) => c === "#" || c === "o";

function blocked(st, x, y, r) {
	for (let ty = Math.floor(y - r); ty <= Math.floor(y + r); ty++)
		for (let tx = Math.floor(x - r); tx <= Math.floor(x + r); tx++)
			if (walkSolid(tileAt(st, tx, ty))) return true;
	return false;
}

/* Move a circle (as its bounding square) axis by axis, so it slides along walls. */
function moveBody(st, b, dx, dy) {
	if (dx !== 0 && !blocked(st, b.x + dx, b.y, b.r)) b.x += dx;
	if (dy !== 0 && !blocked(st, b.x, b.y + dy, b.r)) b.y += dy;
}

function roomOf(st, x) {
	for (let i = 0; i < st.rooms.length; i++)
		if (x >= st.rooms[i].x0 - 0.5 && x <= st.rooms[i].x1 + 0.5) return i;
	return -1;
}

// ── state ───────────────────────────────────────────────────────────────────
export function createSim(dungeon, gear = []) {
	const stats = statsFor(gear);
	const enemies = Object.entries(dungeon.enemies)
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))      // a fixed order, never insertion order
		.map(([id, e]) => ({ id, type: e.type, room: e.room, x: e.x, y: e.y,
			r: ENEMY[e.type].r, hp: ENEMY[e.type].hp, maxHp: ENEMY[e.type].hp,
			active: false, cd: 30 + (e.type === "boss" ? 60 : 0), tele: 0, flash: 0,
			side: 1, phase: 1, mode: 0, modeT: e.type === "boss" ? BOSS_CYCLE[0][1] : 0, ang: 0, aimX: 0, aimY: 0 }));
	const dropsBy = {};
	for (const [id, d] of Object.entries(dungeon.drops)) (dropsBy[d.enemy] ||= []).push(id);
	for (const k of Object.keys(dropsBy)) dropsBy[k].sort();
	return {
		tick: 0, rng: hashSeed(String(dungeon.seed)), status: "play",
		w: dungeon.width, h: dungeon.height, tiles: dungeon.tiles, rooms: dungeon.rooms,
		stats,
		p: { x: dungeon.start.x, y: dungeon.start.y, r: PLAYER_R, hp: stats.maxHp, low: stats.maxHp,
			mp: stats.maxMp, fireCd: 0, hurt: 0 },
		enemies, bullets: [], dropsBy,
		pickups: dungeon.pickups.map((p) => ({ ...p })),
		bags: [], portal: null, events: [],
	};
}

export const recoveryLimit = (st) => Math.min(st.stats.maxHp, st.p.low + RECOVERY_MARGIN);

function hurtPlayer(st, dmg) {
	if (st.status !== "play") return;
	const p = st.p;
	const taken = Math.max(dmg * 0.4, dmg - st.stats.def);
	p.hp -= taken;
	p.hurt = 8;
	if (p.hp < p.low) p.low = Math.max(0, p.hp);
	if (p.hp <= 0) {
		p.hp = 0;
		st.status = "dead";
		st.events.push({ type: "death" });
	}
}

function shoot(st, owner, x, y, ang, speed, dmg, r, life, pierce = 0) {
	st.bullets.push({ owner, x, y, vx: dcos(ang) * speed, vy: dsin(ang) * speed, dmg, r, life, pierce, hit: [] });
}

function shootAt(st, owner, x, y, tx, ty, speed, dmg, r, life) {
	const dx = tx - x, dy = ty - y, d = Math.sqrt(dx * dx + dy * dy) || 1;
	st.bullets.push({ owner, x, y, vx: dx / d * speed, vy: dy / d * speed, dmg, r, life, pierce: 0, hit: [] });
}

// No atan2 (not deterministic): a pattern that needs an aimed FAN rotates the
// unit aim vector instead of computing its angle.
function rotate(vx, vy, a) {
	const c = dcos(a), s = dsin(a);
	return [vx * c - vy * s, vx * s + vy * c];
}

// ── enemies ─────────────────────────────────────────────────────────────────
function enemyStep(st, e) {
	const p = st.p;
	if (e.flash > 0) e.flash--;
	const dx = p.x - e.x, dy = p.y - e.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
	const ux = dx / d, uy = dy / d;
	const sp = ENEMY[e.type].speed * DT;
	if (e.cd > 0) e.cd--;

	if (e.type === "chaser") {
		moveBody(st, e, ux * sp, uy * sp);
		if (d < e.r + p.r + 0.05 && e.cd === 0) { hurtPlayer(st, ENEMY.chaser.touch); e.cd = 36; }
		return;
	}
	if (e.type === "shooter") {
		if (st.tick % 90 === 0 && rand(st) < 0.5) e.side = -e.side;
		if (d < 4) moveBody(st, e, -ux * sp, -uy * sp);
		else if (d > 6.5) moveBody(st, e, ux * sp, uy * sp);
		else moveBody(st, e, -uy * sp * e.side, ux * sp * e.side);
		if (e.tele > 0) {
			if (--e.tele === 0) { shootAt(st, "e", e.x, e.y, p.x, p.y, 7.5, 14, 0.18, 150); e.cd = 84; }
		} else if (e.cd === 0 && d < 11) e.tele = 21;
		return;
	}
	if (e.type === "radial") {
		if (e.tele > 0) {
			if (--e.tele === 0) {
				e.ang = e.ang === 0 ? TAU / 20 : 0;
				for (let k = 0; k < 10; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / 10, 4.5, 16, 0.2, 200);
				e.cd = 144;
			}
		} else if (e.cd === 0) e.tele = 30;
		return;
	}
	bossStep(st, e, d, ux, uy);
}

/* The boss: two phases. Phase 1 alternates a rotating SPIRAL with aimed FANS.
 * Phase 2 (at half health, after a telegraphed pause) adds the NOVA — two dense
 * rings of heavy shots. Caught in the open, a nova is lethal; behind a rock, or
 * in a gap read early, it is not (design §8.3). */
const BOSS_CYCLE = [["spiral", 150], ["rest", 40], ["fan", 100], ["rest", 40]];
const BOSS_CYCLE_2 = [["spiral", 140], ["rest", 30], ["nova", 80], ["rest", 40], ["fan", 90], ["rest", 30]];

function bossStep(st, e, d, ux, uy) {
	const p = st.p;
	if (e.phase === 1 && e.hp <= e.maxHp / 2) { e.phase = 0; e.modeT = 70; e.tele = 70; return; }
	if (e.phase === 0) {                              // the transition: telegraphed, harmless
		if (--e.modeT <= 0) { e.phase = 2; e.mode = 0; e.modeT = BOSS_CYCLE_2[0][1]; e.tele = 0; }
		else e.tele = e.modeT;
		return;
	}
	if (e.cd > 0) return;                             // the opening beat after the room wakes it
	const cycle = e.phase === 1 ? BOSS_CYCLE : BOSS_CYCLE_2;
	const [mode] = cycle[e.mode];
	const t = cycle[e.mode][1] - e.modeT;              // ticks into this mode
	if (e.phase === 2 && d > 3) moveBody(st, e, ux * ENEMY.boss.speed * DT, uy * ENEMY.boss.speed * DT);

	if (mode === "spiral") {
		const every = e.phase === 1 ? 6 : 5, arms = e.phase === 1 ? 3 : 5;
		if (t % every === 0) {
			for (let k = 0; k < arms; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / arms, 5, 14, 0.2, 240);
			e.ang += 0.21;
		}
	} else if (mode === "fan") {
		const k = t % 33;
		if (k === 0) { e.aimX = p.x; e.aimY = p.y; e.tele = 18; }
		if (k === 18) {
			const dx = e.aimX - e.x, dy = e.aimY - e.y, n = Math.sqrt(dx * dx + dy * dy) || 1;
			for (let i = -2; i <= 2; i++) {
				const [vx, vy] = rotate(dx / n, dy / n, i * 0.22);
				st.bullets.push({ owner: "e", x: e.x, y: e.y, vx: vx * 8, vy: vy * 8, dmg: 18, r: 0.22, life: 180, pierce: 0, hit: [] });
			}
		}
	} else if (mode === "nova") {
		if (t === 0) e.tele = 48;
		if (t === 48 || t === 60) {
			const off = t === 48 ? 0 : TAU / 56;
			for (let k = 0; k < 28; k++) shoot(st, "e", e.x, e.y, off + k * TAU / 28, 6.5, 34, 0.26, 260);
		}
	}
	if (e.tele > 0) e.tele--;
	if (--e.modeT <= 0) { e.mode = (e.mode + 1) % cycle.length; e.modeT = cycle[e.mode][1]; }
}

// ── one tick ────────────────────────────────────────────────────────────────
/* input: { mx, my: -1|0|1; ax, ay: the aim vector (any length); fire: bool;
 *          ability: bool (this tick only); take: drop id | null; heal: bool (E on
 *          an orb); enter: bool (E on the portal); recall: bool } */
export function step(st, input) {
	st.events = [];
	if (st.status !== "play") return st;
	st.tick++;
	const p = st.p, s = st.stats;

	if (input.recall) { st.status = "recalled"; st.events.push({ type: "recall" }); return st; }

	// movement
	let mx = input.mx || 0, my = input.my || 0;
	if (mx && my) { mx *= 0.7071067811865476; my *= 0.7071067811865476; }
	moveBody(st, p, mx * PLAYER_SPEED * DT, my * PLAYER_SPEED * DT);

	// regeneration, never past the recovery limit (design §9.3)
	const limit = recoveryLimit(st);
	if (p.hp < limit) p.hp = Math.min(limit, p.hp + s.hpRegen * DT);
	p.mp = Math.min(s.maxMp, p.mp + s.mpRegen * DT);
	if (p.hurt > 0) p.hurt--;

	// aim
	const ix = input.ax || 0, iy = input.ay || 0, al = Math.sqrt(ix * ix + iy * iy);
	const ax = al > 0 ? ix / al : 1, ay = al > 0 ? iy / al : 0;
	if (p.fireCd > 0) p.fireCd--;
	if (input.fire && p.fireCd === 0) {
		st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: ax * s.shotSpeed, vy: ay * s.shotSpeed,
			dmg: s.dmg, r: 0.14, life: Math.round(s.range / s.shotSpeed * TPS), pierce: s.pierce, hit: [] });
		p.fireCd = Math.max(1, Math.round(TPS / s.rate));
	}
	if (input.ability && s.arrows > 0 && p.mp >= ABILITY_COST) {
		p.mp -= ABILITY_COST;
		for (let i = 0; i < s.arrows; i++) {
			const [vx, vy] = rotate(ax, ay, (i - (s.arrows - 1) / 2) * 0.14);
			st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: vx * 16, vy: vy * 16, dmg: s.abilityDmg,
				r: 0.16, life: 45, pierce: 1, hit: [] });
		}
	}

	// manual pickups (design §11.6, §9.4)
	if (input.heal) {
		const i = st.pickups.findIndex((h) => near(p, h, REACH));
		if (i >= 0) {
			st.pickups.splice(i, 1);
			p.low = Math.min(s.maxHp, p.low + HEAL);
			p.hp = Math.min(recoveryLimit(st), p.hp + HEAL);
			st.events.push({ type: "heal", local: true });   // the server keeps no HP
		}
	}
	if (input.take) {
		const bag = st.bags.find((b) => b.drops.includes(input.take) && near(p, b, REACH));
		if (bag) {
			bag.drops = bag.drops.filter((d) => d !== input.take);
			st.events.push({ type: "pickup", drop: input.take });
		}
		st.bags = st.bags.filter((b) => b.drops.length);
	}
	// Leaving is a choice (E), never a step: walking over the portal to reach the
	// boss's loot must not end the run with that loot still on the floor.
	if (input.enter && st.portal && near(p, st.portal, REACH)) {
		st.status = "complete";
		st.events.push({ type: "complete" });
		return st;
	}

	// enemies wake when the player enters their room
	const room = roomOf(st, p.x);
	for (const e of st.enemies) {
		if (e.hp <= 0) continue;
		if (!e.active && e.room === room) e.active = true;
		if (e.active) enemyStep(st, e);
		if (st.status !== "play") return st;
	}

	// bullets
	const keep = [];
	for (const b of st.bullets) {
		b.x += b.vx * DT; b.y += b.vy * DT;
		if (--b.life <= 0 || shotSolid(tileAt(st, b.x, b.y))) continue;
		let gone = false;
		if (b.owner === "p") {
			for (const e of st.enemies) {
				if (e.hp <= 0 || !e.active || b.hit.includes(e.id)) continue;
				if (e.phase === 0) continue;                     // the boss's transition is untouchable
				const dx = e.x - b.x, dy = e.y - b.y, rr = e.r + b.r;
				if (dx * dx + dy * dy < rr * rr) {
					e.hp -= b.dmg; e.flash = 4; b.hit.push(e.id);
					if (e.hp <= 0) kill(st, e);
					if (b.pierce-- <= 0) { gone = true; break; }
				}
			}
		} else {
			const dx = p.x - b.x, dy = p.y - b.y, rr = p.r + b.r;
			if (dx * dx + dy * dy < rr * rr) { hurtPlayer(st, b.dmg); gone = true; }
		}
		if (!gone) keep.push(b);
		if (st.status !== "play") break;
	}
	st.bullets = st.bossDown ? keep.filter((b) => b.owner === "p") : keep;
	st.bossDown = false;
	return st;
}

function near(a, b, r) {
	const dx = a.x - b.x, dy = a.y - b.y;
	return dx * dx + dy * dy <= r * r;
}

/* The exit opens a few tiles from where the boss fell — clear of its loot bag, on
 * floor the player can stand on. Where it fell is the fallback (always walkable). */
export const PORTAL_OFFSET = 3;
function portalSpot(st, e) {
	for (const [dx, dy] of [[0, PORTAL_OFFSET], [0, -PORTAL_OFFSET], [PORTAL_OFFSET, 0], [-PORTAL_OFFSET, 0]]) {
		const x = e.x + dx, y = e.y + dy;
		if (!blocked(st, x, y, PLAYER_R)) return { x, y };
	}
	return { x: e.x, y: e.y };
}

function kill(st, e) {
	e.hp = 0;
	st.events.push({ type: "kill", enemy: e.id });
	const drops = st.dropsBy[e.id];
	if (drops && drops.length) st.bags.push({ enemy: e.id, x: e.x, y: e.y, drops: [...drops] });
	if (e.type === "boss") {
		st.portal = portalSpot(st, e);

		st.bossDown = true;                                        // its fire dies with it (below)
	}
}

/* A compact fingerprint of everything that decides the future — for the
 * determinism tests and for comparing a replay against a live run. */
export function fingerprint(st) {
	const r = (v) => Math.round(v * 1e6) / 1e6;
	return JSON.stringify([st.tick, st.rng, st.status, r(st.p.x), r(st.p.y), r(st.p.hp), r(st.p.low), r(st.p.mp),
		st.enemies.map((e) => [e.id, r(e.x), r(e.y), r(e.hp), e.cd, e.tele, e.mode, e.modeT]),
		st.bullets.length, st.bullets.map((b) => [r(b.x), r(b.y)]).slice(0, 40),
		st.bags.map((b) => b.drops.join(",")), st.pickups.length]);
}
