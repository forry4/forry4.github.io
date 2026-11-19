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
 * ones marked `local` (a heal, a level-up: the server keeps no HP and works the
 * level out from the XP it credits itself). The server
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
/* THE HEALING POTION (owner's call, 2026-11-18, design §19.1): never a stock, always
 * a cooldown. It heals and raises the recovery limit like a smaller heal orb. */
export const POTION_HEAL = 30;
export const POTION_COOLDOWN = 20 * TPS;
export const ABILITY_COST = 30;
export const SHIELD_DURATION = 5 * TPS;
export const SLOW_DURATION = 5 * TPS;
export const SLOW_RADIUS = 3;
export const SLOW_FACTOR = 0.45;

/* EVERY ABILITY HAS A COOLDOWN as well as its MP cost (owner's worry, 2026-11-18: with
 * enough MP regeneration a defensive ability could be kept up for good). Regen helps
 * only up to the cooldown. Ticks, from the cast. */
export const ABILITY_COOLDOWN = { volley: 3 * TPS, slow: 10 * TPS, starfall: 4 * TPS, counter: 4 * TPS, shield: 8 * TPS };
// Starfall (the Diviner): a star lands where you aim, after a beat, on everything near it.
export const STARFALL_DELAY = 36;
export const STARFALL_RADIUS = 1.5;
export const STARFALL_RANGE = 8;
// Counter (the Ninja): a hit inside the window is ignored, guards for a moment after,
// and the next shot hits harder. The guard does NOT scale (owner: no late-game
// invincibility); Ability power scales the damage.
export const COUNTER_WINDOW = TPS;
export const COUNTER_GUARD = 30;
export const COUNTER_MULT = 2;

/* One standard ability per class (owner's call, 2026-11-18). The shield is retired
 * with its item, kept in the code for a future class. */
export const CLASS_INFO = {
	ranger: { name: "Ranger", description: "A quick ranged fighter with a volley of arrows.", ability: "volley" },
	paladin: { name: "Paladin", description: "A close-range guardian whose field slows enemy shots around them.", ability: "slow" },
	diviner: { name: "Diviner", description: "A long-range mage who calls stars down on a spot.", ability: "starfall" },
	ninja: { name: "Ninja", description: "A quick thrower who counters a hit and strikes back twice as hard.", ability: "counter" },
};

/* ROOMS LOCK (owner's call, 2026-11-18, design §14.1a): an enemy sleeps — and
 * cannot be hurt — until the player is all the way inside its room; then both of
 * that room's doors seal and everything in it wakes at once. The doors open when
 * the last of them falls. While a room has not been fought, its doorways are a
 * VEIL that stops shots both ways, so nothing is fought through a door. */
export const ENEMY = {
	// A chaser also spits a short shot when it is close (owner's ask, 2026-11-18): a
	// short telegraph, then one slow bolt that dies after `shot.range` tiles.
	chaser: { hp: 55, r: 0.4, speed: 3.4, shot: { range: 3.5, speed: 7, dmg: 9, tele: 14, every: 75 } },
	shooter: { hp: 48, r: 0.38, speed: 2.4 },
	radial: { hp: 95, r: 0.45, speed: 0 },
	boss: { hp: 1150, r: 1.0, speed: 1.2 },
};

/* Each weapon fires its own PATTERN, not just its own numbers (owner's ask,
 * 2026-11-18). `rate` is volleys a second; a volley is `shots` arrows fanned
 * `spread` radians apart, or a `burst` of bolts `gap` ticks apart. `pierce` is how
 * many enemies a shot passes through. Damage is per arrow, scaled by tier.
 * Two STANDARD types per class plus uniques (owner's call, 2026-11-18); ranges in
 * tiles are the owner's: shortbow 5, repeater 6, longbow 7.
 *   shortbow   — twin arrows, fast, short: strong up close, spreads out at range.
 *   longbow    — one heavy arrow, slow, the longest reach, punches through two enemies.
 *   tidecaller — UNIQUE: three arrows in a wide fan that glance off a wall once.
 *   repeater   — UNIQUE: a three-bolt burst, then a reload: front-loaded damage.
 * `bounce` is how many walls a shot glances off before it breaks. */
export const WEAPONS = {
	none: { dmg: 6, rate: 3, range: 5, speed: 14, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	shortbow: { dmg: 7, rate: 5, range: 5, speed: 15, shots: 2, spread: 0.12, pierce: 0, burst: 1, gap: 0 },
	longbow: { dmg: 34, rate: 1.5, range: 7, speed: 20, shots: 1, spread: 0, pierce: 2, burst: 1, gap: 0 },
	mace: { dmg: 26, rate: 2.2, range: 3, speed: 15, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	greatsword: { dmg: 42, rate: 1.1, range: 4, speed: 17, shots: 1, spread: 0, pierce: 1, burst: 1, gap: 0 },
	wand: { dmg: 13, rate: 3.2, range: 6, speed: 16, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	starstaff: { dmg: 25, rate: 1.5, range: 8, speed: 20, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	tidecaller: { dmg: 13, rate: 2.5, range: 6, speed: 16, shots: 3, spread: 0.24, pierce: 0, burst: 1, gap: 0, bounce: 1 },
	repeater: { dmg: 14, rate: 1.5, range: 6, speed: 17, shots: 1, spread: 0, pierce: 0, burst: 3, gap: 5 },
	// The Ninja's (2026-11-18): stars spin through one enemy; a kunai is one heavy, fast blade.
	// Slower and harder since 2026-11-18 (owner's ask): at 4.5 a second the doubled
	// countered shot left before the player could aim it.
	shuriken: { dmg: 20, rate: 2.4, range: 5, speed: 15, shots: 1, spread: 0, pierce: 1, burst: 1, gap: 0, look: "star" },
	kunai: { dmg: 42, rate: 1.2, range: 6.5, speed: 22, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, look: "blade" },
};

/* EVERY NUMBER A PLAYER READS IS FLAT (owner's ask, 2026-11-18: "stop with all the
 * percentages"). A character has Attack and Dexterity as plain points; each point
 * is worth 1/STAT_SCALE more damage (Attack) or shots a second (Dexterity), so a
 * weapon's damage is still its own and the points scale every weapon alike. The
 * points themselves and damage are whole numbers; HP/MP regeneration may use one
 * decimal place for finer tuning. */
export const STAT_SCALE = 25;

/* An enchantment's flat value at roll quality q (0-1): [at q=0, at q=1], rounded.
 * The store keeps the QUALITY, so changing a row here re-scales every item. */
export const ENCHANT_FLAT = {
	max_hp: [5, 25], max_mp: [5, 25], attack: [1, 6], attack_speed: [1, 6], defense: [1, 5],
	ability_power: [2, 10], mp_regen: [0.5, 2.5], hp_regen: [0.2, 1.2],
};
export const enchantValue = (id, q) => {
	const r = ENCHANT_FLAT[id];
	if (!r) return 0;
	const precision = id === "mp_regen" || id === "hp_regen" ? 10 : 1;
	return Math.round((r[0] + (r[1] - r[0]) * q) * precision) / precision;
};

/* What each level past the first adds (design §10.1: levels are separate from
 * the per-dungeon stat rewards and their caps). Greybox numbers. */
export const PER_LEVEL = { maxHp: 6, maxMp: 4, att: 1, ap: 1 };

const tierScale = (it) => 1 + 0.2 * ((it.tier || 1) - 1);

/* A character's numbers from its level and what it wears. `gear` is the equipped
 * items as the server lists them ({base_id, tier, enchants: [{id, q}]}). */
export function statsFor(gear = [], level = 1, classId = "ranger") {
	// HP regeneration halved 2026-11-18 (owner: "decrease hp/s regen"); heals are rarer drops now.
	const s = { maxHp: 100, maxMp: 100, att: 0, dex: 0, def: 0, ap: 0, hpRegen: 0.5, mpRegen: 2.5,
		arrows: 0, abilityDmg: 0, abilityKind: null, classId,
		...weaponStats(WEAPONS.none, 1) };
	// Points gather first and apply once the weapon is known, so the order the
	// server lists gear in can never change the numbers.
	let pierce = 0;
	for (const it of gear) {
		const t = tierScale(it), tier = it.tier || 1;
		const w = WEAPONS[it.base_id];
		if (w) Object.assign(s, weaponStats(w, t));
		if (it.base_id === "leather_vest") { s.def += 1 + tier; s.maxHp += 10 * (tier - 1); }
		if (it.base_id === "volley_quiver") { s.arrows = 7; s.abilityDmg += Math.round(8 * t); s.abilityKind = "volley"; }
		if (it.base_id === "plate_armor") { s.def += 3 + tier; s.maxHp += 18 * (tier - 1); }
		if (it.base_id === "grounding_aegis") s.abilityKind = "shield";
		if (it.base_id === "seer_robes") { s.maxMp += 18 * tier; s.mpRegen += 0.5; }
		if (it.base_id === "stillness_orb") s.abilityKind = "slow";
		if (it.base_id === "star_tome") { s.abilityKind = "starfall"; s.abilityDmg += Math.round(45 * t); }
		if (it.base_id === "shadow_garb") { s.def += tier; s.dex += 2 + tier; s.maxHp += 8 * (tier - 1); }
		if (it.base_id === "mirror_charm") s.abilityKind = "counter";
		if (it.base_id === "band_of_vigor") s.maxHp += Math.round(15 * t);
		if (it.base_id === "band_of_focus") { s.maxMp += Math.round(15 * t); s.mpRegen += 2; }
		if (it.base_id === "kingfisher_eye") { pierce += 1; s.att += 5; }
		for (const e of it.enchants || []) {
			const v = enchantValue(e.id, e.q);
			if (e.id === "max_hp") s.maxHp += v;
			else if (e.id === "max_mp") s.maxMp += v;
			else if (e.id === "attack") s.att += v;
			else if (e.id === "attack_speed") s.dex += v;
			else if (e.id === "defense") s.def += v;
			else if (e.id === "ability_power") s.ap += v;
			else if (e.id === "mp_regen") s.mpRegen += v;
			else if (e.id === "hp_regen") s.hpRegen += v;
		}
	}
	const up = Math.max(0, (level | 0) - 1);
	s.maxHp += PER_LEVEL.maxHp * up;
	s.maxMp += PER_LEVEL.maxMp * up;
	s.att += PER_LEVEL.att * up;
	s.ap += PER_LEVEL.ap * up;
	s.pierce += pierce;
	s.weaponDmg = s.dmg;                                   // per arrow, before Attack
	s.dmg = Math.round(s.dmg * (1 + s.att / STAT_SCALE));
	s.rate = s.rate * (1 + s.dex / STAT_SCALE);
	// ABILITY POWER (owner's ask, 2026-11-18) is the ability's own stat, as Attack is
	// the weapon's: each point is 1/STAT_SCALE more of what the ability does — the
	// volley's and the starfall's damage, the slowing field's REACH (not its time),
	// the counter's damage (not its guard).
	s.abilityPower = 1 + s.ap / STAT_SCALE;
	s.abilityDmg = s.abilityKind === "volley" || s.abilityKind === "starfall" ? Math.round(s.abilityDmg * s.abilityPower) : 0;
	s.slowRadius = Math.round(SLOW_RADIUS * s.abilityPower * 100) / 100;
	s.counterMult = Math.round(COUNTER_MULT * s.abilityPower * 100) / 100;
	return s;
}

function weaponStats(w, t) {
	return { dmg: Math.round(w.dmg * t), rate: w.rate, range: w.range, shotSpeed: w.speed, shots: w.shots,
		spread: w.spread, pierce: w.pierce, burst: w.burst, gap: w.gap, bounce: w.bounce || 0, look: w.look || null };
}

// ── the map ─────────────────────────────────────────────────────────────────
/* A doorway of a room that still has enemies in it reads as "=" while the room is
 * sealed (nothing passes) and "|" before it is entered (a veil: shots stop, feet
 * do not). Once the room is cleared it is plain floor again. */
function tileAt(st, x, y) {
	const ty = Math.floor(y), tx = Math.floor(x);
	if (ty < 0 || ty >= st.h || tx < 0 || tx >= st.w) return "#";
	if (st.doorCols && ty >= st.doorY - 1 && ty <= st.doorY + 1) {
		const r = st.doorCols[tx];
		if (r >= 0 && st.roomLeft[r] > 0) return st.sealed === r ? "=" : "|";
	}
	return st.tiles[ty][tx];
}
export const doorAt = (st, x, y) => tileAt(st, x, y);
const walkSolid = (c) => c === "#" || c === "o" || c === "~" || c === "=";
const shotSolid = (c) => c === "#" || c === "o" || c === "=" || c === "|";

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

/* The level `xp` reaches on the server's table (`levels[n]` = the XP to BE
 * level n + 1 — the state route ships it, so the two sides read one table). */
export function levelFor(levels, xp) {
	let level = 1;
	while (level < levels.length && xp >= levels[level]) level++;
	return level;
}

/* Where `xp` sits inside its level: { level, into, span } (span 0 at the top). */
export function xpProgress(levels, xp) {
	const level = levelFor(levels, xp);
	if (level >= levels.length) return { level, into: 0, span: 0 };
	return { level, into: xp - levels[level - 1], span: levels[level] - levels[level - 1] };
}

// ── state ───────────────────────────────────────────────────────────────────
/* `hero` is the character as the server lists it: { level, xp }, plus the
 * server's level table. The XP a run earns is shown and levelled on here, but it
 * is CREDITED by the server from its own dungeon (each enemy's `xp`). */
export function createSim(dungeon, gear = [], hero = {}) {
	const levels = hero.levels || [0];
	const xp = hero.xp || 0, level = Math.max(hero.level || 1, levelFor(levels, xp));
	const classId = hero.class_id || hero.classId || dungeon.class_id || "ranger";
	const stats = statsFor(gear, level, classId);
	const scale = { hp: 1, dmg: 1, speed: 1, shot: 1, cadence: 1, ward: 0, ward_boss: 0, volatile: 0, ...(dungeon.scale || {}) };
	const enemies = Object.entries(dungeon.enemies)
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))      // a fixed order, never insertion order
		.map(([id, e]) => ({ id, type: e.type, room: e.room, x: e.x, y: e.y, xp: e.xp || 0,
			r: ENEMY[e.type].r, hp: Math.round(ENEMY[e.type].hp * scale.hp), maxHp: Math.round(ENEMY[e.type].hp * scale.hp),
			active: false, cd: 30 + (e.type === "boss" ? 60 : 0), tele: 0, scd: 0, flash: 0,
			ward: e.type === "boss" ? scale.ward_boss : scale.ward,
			side: 1, phase: 1, mode: 0, modeT: e.type === "boss" ? BOSS_CYCLE[0][1] : 0, ang: 0, aimX: 0, aimY: 0 }));
	// The doors: each room's left and right doorway columns, on the three rows
	// around the map's middle row (dungeon.py cuts them there).
	const rooms = dungeon.rooms || [];
	const doorY = dungeon.door_y ?? Math.floor(dungeon.height / 2);
	const doorCols = new Array(dungeon.width).fill(-1);
	rooms.forEach((r, i) => { if (i > 0) doorCols[r.x0 - 1] = i; if (i < rooms.length - 1) doorCols[r.x1] = i; });
	const roomLeft = rooms.map((_, i) => enemies.filter((e) => e.room === i).length);
	const dropsBy = {};
	for (const [id, d] of Object.entries(dungeon.drops)) (dropsBy[d.enemy] ||= []).push(id);
	for (const k of Object.keys(dropsBy)) dropsBy[k].sort();
	return {
		tick: 0, elapsedTicks: 0, bossTimeTicks: null, rng: hashSeed(String(dungeon.seed)), status: "play",
		classId, practice: !!hero.practice,
		w: dungeon.width, h: dungeon.height, tiles: dungeon.tiles, rooms,
		doorY, doorCols, roomLeft, sealed: -1, depth: dungeon.level || 1, offers: dungeon.offers || [],
		stats, gear, levels, completeXp: dungeon.complete_xp || 0,
		hero: { level, xp, startLevel: level, startXp: xp },
		p: { x: dungeon.start.x, y: dungeon.start.y, r: PLAYER_R, hp: stats.maxHp, low: stats.maxHp,
			mp: stats.maxMp, fireCd: 0, hurt: 0, burstLeft: 0, burstCd: 0,
			abilityCd: 0, potionCd: 0, counterUntil: 0, guardUntil: 0, empower: 0 },
		enemies, bullets: [], dropsBy, scale,
		// Heal orbs DROP from the enemy that carries one (dungeon.py); one with a
		// position of its own (an older dungeon) lies where it was placed.
		pickups: dungeon.pickups.filter((h) => h.enemy == null).map((h) => ({ ...h })),
		healsBy: Object.fromEntries(dungeon.pickups.filter((h) => h.enemy != null).map((h) => [h.enemy, h.id])),
		bags: [], floor: [], portal: null, deeper: null, shield: null, slowUntil: 0, starfalls: [], blasts: [], damageNumbers: [], events: [],
	};
}

export const recoveryLimit = (st) => Math.min(st.stats.maxHp, st.p.low + RECOVERY_MARGIN);

/* `src` names what hit ("shooter:bolt", "boss:nova", "chaser:touch"…): the last hit
 * that landed is kept in `st.lastHit`, so a death can say what did it. */
function hurtPlayer(st, dmg, src = null) {
	if (st.status !== "play") return;
	dmg *= st.scale ? st.scale.dmg : 1;                     // the Brutal modifier
	const p = st.p;
	if (p.guardUntil > st.tick) return;                      // just countered: nothing lands
	if (p.counterUntil >= st.tick) {                         // the counter catches this hit
		p.counterUntil = 0;
		p.guardUntil = st.tick + COUNTER_GUARD;
		p.empower = st.stats.counterMult;                    // the next shot; a second counter does not stack
		st.events.push({ type: "counter", local: true });
		return;
	}
	const taken = Math.round(Math.max(dmg * 0.4, dmg - st.stats.def) * 10) / 10;
	p.hp -= taken;
	p.hurt = 8;
	st.lastHit = { src, dmg: taken, tick: st.tick };
	if (!st.damageNumbers) st.damageNumbers = [];
	st.damageNumbers.push({ x: p.x, y: p.y, amount: taken, until: st.tick + 45 });
	st.events.push({ type: "damage", amount: taken, local: true });
	if (p.hp < p.low) p.low = Math.max(0, p.hp);
	if (p.hp <= 0) {
		p.hp = 0;
		st.status = "dead";
		st.events.push({ type: "death" });
	}
}

/* An enemy's attack cooldown, shortened by Frenzied. */
const cadence = (st, ticks) => Math.max(1, Math.round(ticks * st.scale.cadence));

function shoot(st, owner, x, y, ang, speed, dmg, r, life, pierce = 0) {
	if (owner === "e") { speed *= st.scale.speed; life = Math.round(life / st.scale.speed); r *= st.scale.shot; }
	st.bullets.push({ owner, x, y, vx: dcos(ang) * speed, vy: dsin(ang) * speed, dmg, r, life, pierce, hit: [],
		...(owner === "e" ? { src: st.src } : {}) });
}

function shootAt(st, owner, x, y, tx, ty, speed, dmg, r, life) {
	if (owner === "e") { speed *= st.scale.speed; life = Math.round(life / st.scale.speed); r *= st.scale.shot; }
	const dx = tx - x, dy = ty - y, d = Math.sqrt(dx * dx + dy * dy) || 1;
	st.bullets.push({ owner, x, y, vx: dx / d * speed, vy: dy / d * speed, dmg, r, life, pierce: 0, hit: [],
		...(owner === "e" ? { src: st.src } : {}) });
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
	const sp = ENEMY[e.type].speed * st.scale.speed * DT;
	if (e.cd > 0) e.cd--;

	if (e.type === "chaser") {
		moveBody(st, e, ux * sp, uy * sp);
		const sh = ENEMY.chaser.shot;
		if (e.scd > 0) e.scd--;
		if (e.tele > 0) {
			if (--e.tele === 0) {
				st.src = "chaser:spit";
				shootAt(st, "e", e.x, e.y, p.x, p.y, sh.speed, sh.dmg, 0.16, Math.round((sh.range / sh.speed) * TPS));
				e.scd = cadence(st, sh.every);
			}
		} else if (!(e.scd > 0) && d < sh.range) e.tele = sh.tele;
		return;
	}
	if (e.type === "shooter") {
		if (st.tick % 90 === 0 && rand(st) < 0.5) e.side = -e.side;
		if (d < 4) moveBody(st, e, -ux * sp, -uy * sp);
		else if (d > 6.5) moveBody(st, e, ux * sp, uy * sp);
		else moveBody(st, e, -uy * sp * e.side, ux * sp * e.side);
		if (e.tele > 0) {
			if (--e.tele === 0) { st.src = "shooter:bolt"; shootAt(st, "e", e.x, e.y, p.x, p.y, 7.5, 14, 0.18, 150); e.cd = cadence(st, 84); }
		} else if (e.cd === 0 && d < 11) e.tele = 21;
		return;
	}
	if (e.type === "radial") {
		if (e.tele > 0) {
			if (--e.tele === 0) {
				e.ang = e.ang === 0 ? TAU / 20 : 0;
				st.src = "radial:ring";
				for (let k = 0; k < 10; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / 10, 4.5, 16, 0.2, 200);
				e.cd = cadence(st, 144);
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
	st.src = `boss:${mode}`;
	if (e.phase === 2 && d > 3) moveBody(st, e, ux * ENEMY.boss.speed * st.scale.speed * DT, uy * ENEMY.boss.speed * st.scale.speed * DT);

	if (mode === "spiral") {
		const every = cadence(st, e.phase === 1 ? 6 : 5), arms = e.phase === 1 ? 3 : 5;
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
				shootAt(st, "e", e.x, e.y, e.x + vx, e.y + vy, 8, 18, 0.22, 180);
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
	if (--e.modeT <= 0) {
		e.mode = (e.mode + 1) % cycle.length;
		e.modeT = cycle[e.mode][0] === "rest" ? cadence(st, cycle[e.mode][1]) : cycle[e.mode][1];
	}
}

// ── one tick ────────────────────────────────────────────────────────────────
/* input: { mx, my: -1|0|1; ax, ay: the aim vector (any length); fire: bool;
 *          ability: bool (this tick only); take: drop id | null;
 *          drop: an item the player put down (an opaque key the page names it by);
 *          lift: the key of an item on the floor to take back; heal: bool (E on
 *          an orb); potion: bool (this tick only); enter: bool (E on the portal); recall: bool;
 *          gear: the whole equipped list, on the tick it changes (else absent) } */
export function step(st, input) {
	st.events = [];
	if (st.status !== "play") return st;
	st.tick++;
	if (st.bossTimeTicks == null) st.elapsedTicks++;
	if (st.shield && st.shield.until <= st.tick) st.shield = null;
	if (st.damageNumbers) st.damageNumbers = st.damageNumbers.filter((f) => f.until > st.tick);
	if (input.gear) setGear(st, input.gear);
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

	playerFire(st, input);

	// the healing potion: only when it would heal, then a cooldown
	if (p.potionCd > 0) p.potionCd--;
	// It heals only up to the recovery limit and never raises it (owner's call,
	// 2026-11-18): a potion tops up what regeneration could reach, faster.
	if (input.potion && !(p.potionCd > 0) && p.hp < limit) {
		p.hp = Math.min(limit, p.hp + POTION_HEAL);
		p.potionCd = POTION_COOLDOWN;
		st.events.push({ type: "potion", local: true });
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
	// The floor: items the PLAYER put down, at their feet. The sim only keeps where
	// they lie; what they are is the page's (it reports drop_item / pickup_item).
	if (input.drop) st.floor.push({ key: input.drop, x: p.x, y: p.y });
	if (input.lift) {
		const i = st.floor.findIndex((f) => f.key === input.lift && near(p, f, REACH));
		if (i >= 0) { st.floor.splice(i, 1); st.events.push({ type: "lift", key: input.lift, local: true }); }
	}
	// Leaving is a choice (E), never a step: walking over the portal to reach the
	// boss's loot must not end the run with that loot still on the floor.
	if (input.enter && st.portal && near(p, st.portal, REACH)) {
		st.status = "complete";
		st.events.push({ type: "complete" });
		return st;
	}
	// The way deeper is a choice the PAGE makes (three modifiers, pick one, and a
	// new level from the server): the sim only says the player asked.
	if (input.enter && st.deeper && near(p, st.deeper, REACH)) st.events.push({ type: "deeper", local: true });

	sealRoom(st);
	for (const e of st.enemies) {
		if (e.hp <= 0 || !e.active) continue;
		enemyStep(st, e);
		if (st.status !== "play") return st;
	}

	// stars landing (the Diviner's ability)
	landStarfalls(st, (f) => {
		for (const e of st.enemies) {
			if (e.hp <= 0 || e.phase === 0 || !e.active) continue;
			const dx = e.x - f.x, dy = e.y - f.y, rr = f.r + e.r;
			if (dx * dx + dy * dy >= rr * rr) continue;
			hurtEnemy(st, e, f.dmg, 6);
		}
	});
	if (st.status !== "play") return st;

	// bullets
	const keep = [];
	for (const b of st.bullets) {
		const dxp = st.p.x - b.x, dyp = st.p.y - b.y;
		const sr = st.slowR || SLOW_RADIUS;
		const slowed = b.owner === "e" && st.slowUntil > st.tick && dxp * dxp + dyp * dyp <= sr * sr;
		const speedScale = slowed ? SLOW_FACTOR : 1;
		b.x += b.vx * DT * speedScale; b.y += b.vy * DT * speedScale;
		if (b.owner === "e" && st.shield) {
			const sx = st.shield.x - b.x, sy = st.shield.y - b.y;
			const rr = st.shield.r + b.r;
			if (sx * sx + sy * sy < rr * rr) { if (--st.shield.hits <= 0) st.shield = null; continue; }
		}
		if (--b.life <= 0 || wallHit(b, (x, y) => shotSolid(tileAt(st, x, y)))) continue;
		let gone = false;
		if (b.owner === "p") {
			for (const e of st.enemies) {
				if (e.hp <= 0 || b.hit.includes(e.id)) continue;
				if (e.phase === 0 || !e.active) continue;        // the boss's turn, and a room not entered
				const dx = e.x - b.x, dy = e.y - b.y, rr = e.r + b.r;
				if (dx * dx + dy * dy < rr * rr) {
					b.hit.push(e.id);
					hurtEnemy(st, e, b.dmg, 4);
					if (b.pierce-- <= 0) { gone = true; break; }
				}
			}
		} else {
			const dx = p.x - b.x, dy = p.y - b.y, rr = p.r + b.r;
			if (dx * dx + dy * dy < rr * rr) { hurtPlayer(st, b.dmg, b.src || null); gone = true; }
		}
		if (!gone) keep.push(b);
		if (st.status !== "play") break;
	}
	st.bullets = st.bossDown ? keep.filter((b) => b.owner === "p") : keep;
	st.bossDown = false;
	if (st.rings?.length) {                            // Volatile: what fell this tick bursts
		for (const r of st.rings) {
			st.src = `${r.type}:burst`;
			for (let k = 0; k < r.n; k++) shoot(st, "e", r.x, r.y, r.a + k * TAU / r.n, 4, 10, 0.18, 110);
		}
		st.rings = [];
	}
	return st;
}

/* The player's weapon and ability for one tick: aim, the fire cooldown, a burst in
 * flight, the volley ability. Shared with the town (town.js), which has a `p`, its
 * `stats` and `bullets` of the same shape, so a weapon fires there exactly as here. */
export function playerFire(st, input) {
	const p = st.p, s = st.stats;
	const ix = input.ax || 0, iy = input.ay || 0, al = Math.sqrt(ix * ix + iy * iy);
	const ax = al > 0 ? ix / al : 1, ay = al > 0 ? iy / al : 0;
	if (p.fireCd > 0) p.fireCd--;
	if (input.fire && p.fireCd === 0) {
		volley(st, ax, ay);
		p.burstLeft = s.burst - 1; p.burstCd = s.gap;
		p.fireCd = Math.max(1, Math.round(TPS / s.rate));
	} else if (p.burstLeft > 0 && --p.burstCd <= 0) {   // a burst finishes once started
		volley(st, ax, ay);
		p.burstLeft--; p.burstCd = s.gap;
	}
	if (p.abilityCd > 0) p.abilityCd--;
	if (input.ability && s.abilityKind && p.mp >= ABILITY_COST && !(p.abilityCd > 0)) {
		p.mp -= ABILITY_COST;
		p.abilityCd = ABILITY_COOLDOWN[s.abilityKind] || 0;
		if (s.abilityKind === "volley") {
			for (let i = 0; i < s.arrows; i++) {
				const [vx, vy] = rotate(ax, ay, (i - (s.arrows - 1) / 2) * 0.14);
				st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: vx * 16, vy: vy * 16, dmg: s.abilityDmg,
					r: 0.16, life: 45, pierce: 1, bounce: 0, hit: [] });
			}
		} else if (s.abilityKind === "shield") {
			st.shield = { x: p.x + ax * 0.95, y: p.y + ay * 0.95, r: 0.72, hits: 1 + Math.floor(s.ap / 8),
				until: st.tick + Math.round(SHIELD_DURATION * s.abilityPower) };
		} else if (s.abilityKind === "slow") {
			st.slowUntil = st.tick + SLOW_DURATION;
			st.slowR = s.slowRadius;
		} else if (s.abilityKind === "starfall") {
			// Where the cursor is, no farther than STARFALL_RANGE.
			const k = al > STARFALL_RANGE ? STARFALL_RANGE / al : 1;
			(st.starfalls ||= []).push({ x: p.x + ix * k, y: p.y + iy * k, r: STARFALL_RADIUS, dmg: s.abilityDmg,
				at: st.tick + STARFALL_DELAY, cast: st.tick });
		} else if (s.abilityKind === "counter") {
			p.counterUntil = st.tick + COUNTER_WINDOW;
		}
	}
}

/* One volley from the player: `shots` arrows fanned around the aim. A counter's
 * empowerment is spent on the whole of the next volley. */
function volley(st, ax, ay) {
	const p = st.p, s = st.stats, life = Math.round(s.range / s.shotSpeed * TPS);
	const mult = p.empower > 0 ? p.empower : 1;
	p.empower = 0;
	for (let i = 0; i < s.shots; i++) {
		const [vx, vy] = s.shots > 1 ? rotate(ax, ay, (i - (s.shots - 1) / 2) * s.spread) : [ax, ay];
		st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: vx * s.shotSpeed, vy: vy * s.shotSpeed,
			dmg: Math.round(s.dmg * mult), r: 0.14, life, pierce: s.pierce, bounce: s.bounce, hit: [],
			...(s.look ? { look: s.look } : {}), ...(mult > 1 ? { power: true } : {}) });
	}
}

/* Stars that are due land now: `hit(star)` deals the damage (enemies in a rift,
 * the practice posts in town). Each leaves a short-lived blast for the renderer. */
export function landStarfalls(st, hit) {
	if (st.blasts?.length) st.blasts = st.blasts.filter((b) => b.until > st.tick);
	if (!st.starfalls?.length) return;
	const due = st.starfalls.filter((f) => f.at <= st.tick);
	if (!due.length) return;
	st.starfalls = st.starfalls.filter((f) => f.at > st.tick);
	for (const f of due) {
		hit(f);
		(st.blasts ||= []).push({ x: f.x, y: f.y, r: f.r, until: st.tick + 18 });
	}
}

/* A shot that has just moved into something solid: true if it breaks there. One
 * with `bounce` left glances off instead — back to where it was, its velocity
 * mirrored on the axis it crossed (both, into a corner). */
export function wallHit(b, solidAt) {
	if (!solidAt(b.x, b.y)) return false;
	if (!(b.bounce > 0)) return true;
	const x0 = b.x - b.vx * DT, y0 = b.y - b.vy * DT;
	const flipX = solidAt(b.x, y0), flipY = solidAt(x0, b.y);
	if (flipX || !flipY) b.vx = -b.vx;
	if (flipY || !flipX) b.vy = -b.vy;
	b.x = x0; b.y = y0; b.bounce--;
	return false;
}

function near(a, b, r) {
	const dx = a.x - b.x, dy = a.y - b.y;
	return dx * dx + dy * dy <= r * r;
}

/* The exit opens a few tiles from where the boss fell — clear of its loot bag, on
 * floor the player can stand on. Where it fell is the fallback (always walkable). */
export const PORTAL_OFFSET = 3;
function portalSpot(st, e, not = null) {
	for (const [dx, dy] of [[0, PORTAL_OFFSET], [0, -PORTAL_OFFSET], [PORTAL_OFFSET, 0], [-PORTAL_OFFSET, 0]]) {
		const x = e.x + dx, y = e.y + dy;
		if (blocked(st, x, y, PLAYER_R) || (not && near({ x, y }, not, PORTAL_OFFSET))) continue;
		return { x, y };
	}
	return { x: e.x, y: e.y };
}

/* The player all the way inside a room that still has enemies: both its doors seal
 * and everything in it wakes. One room at a time; the doors open in `kill`. */
function sealRoom(st) {
	if (st.sealed >= 0 || !st.rooms.length) return;
	const p = st.p;
	for (let i = 0; i < st.rooms.length; i++) {
		const r = st.rooms[i];
		if (st.roomLeft[i] > 0 && p.x - p.r > r.x0 && p.x + p.r < r.x1) {
			st.sealed = i;
			for (const e of st.enemies) if (e.room === i && e.hp > 0) e.active = true;
			st.events.push({ type: "seal", room: i, local: true });
			return;
		}
	}
}

/* A hit on an enemy. Warded: the first few hits (counted per enemy, each one —
 * an arrow, a star — one hit) do nothing but flash. */
function hurtEnemy(st, e, dmg, flash) {
	if (e.ward > 0) { e.ward--; e.flash = 2; return; }
	// What a hit did, floated over the enemy (drawing only: not in the fingerprint).
	(st.damageNumbers ||= []).push({ x: e.x, y: e.y - e.r, amount: Math.round(Math.min(dmg, e.hp) * 10) / 10, until: st.tick + 36, foe: true });
	e.hp -= dmg; e.flash = flash;
	if (e.hp <= 0) kill(st, e);
}

/* Gear changed mid-run (the player moved an item in the side panel). It is an
 * INPUT, applied at the top of a tick, so a replay of the same inputs swaps on the
 * same tick. Nothing is given for free: HP, the recovery limit and MP keep their
 * values and only come DOWN to a smaller maximum — otherwise taking a +HP ring off
 * and putting it back would be a heal. A burst in flight stops. */
export function setGear(st, gear) {
	st.gear = gear;
	st.stats = statsFor(gear, st.hero.level, st.classId);
	const p = st.p, s = st.stats;
	p.hp = Math.min(p.hp, s.maxHp);
	p.low = Math.min(p.low, s.maxHp);
	p.mp = Math.min(p.mp, s.maxMp);
	p.burstLeft = 0; p.burstCd = 0;
	p.empower = 0;
}

/* XP, and a level when it crosses one: the new stats apply at once, and the HP,
 * recovery limit and MP each rise by what the level added to their maximum. */
function gainXp(st, amount) {
	const h = st.hero;
	if (st.practice || amount <= 0) return;
	h.xp += amount;
	const level = levelFor(st.levels, h.xp);
	if (level <= h.level) return;
	const was = st.stats, now = statsFor(st.gear, level, st.classId), p = st.p;
	p.hp += now.maxHp - was.maxHp;
	p.low += now.maxHp - was.maxHp;
	p.mp = Math.min(now.maxMp, p.mp + now.maxMp - was.maxMp);
	st.stats = now;
	h.level = level;
	st.events.push({ type: "level", level, local: true });
}

function kill(st, e) {
	e.hp = 0;
	st.events.push({ type: "kill", enemy: e.id });
	if (st.roomLeft && e.room != null && --st.roomLeft[e.room] === 0 && st.sealed === e.room) {
		st.sealed = -1;
		st.events.push({ type: "unseal", room: e.room, local: true });
	}
	if (st.scale.volatile) (st.rings ||= []).push({ x: e.x, y: e.y, n: e.type === "boss" ? 16 : 8, a: rand(st) * TAU, type: e.type });
	gainXp(st, e.xp);
	const drops = st.practice ? [] : st.dropsBy[e.id];
	if (e.type === "boss") st.bossTimeTicks = st.elapsedTicks;
	if (drops && drops.length) st.bags.push({ enemy: e.id, x: e.x, y: e.y, drops: [...drops] });
	const heal = st.healsBy && st.healsBy[e.id];
	if (heal) st.pickups.push({ id: heal, kind: "heal", x: e.x, y: e.y + (drops && drops.length ? 0.6 : 0) });
	if (e.type === "boss") {
		st.portal = portalSpot(st, e);
		if (st.offers.length && st.depth < 5) st.deeper = portalSpot(st, e, st.portal);
		// The dungeon is CLEARED when its boss falls: the bonus and the news come now,
		// not at the portal (owner's ask, 2026-11-18). The server credits it on the
		// same kill event.
		gainXp(st, st.completeXp);
		st.events.push({ type: "cleared", xp: st.completeXp, local: true });
		st.bossDown = true;                                        // its fire dies with it (below)
	}
}

/* A compact fingerprint of everything that decides the future — for the
 * determinism tests and for comparing a replay against a live run. */
export function fingerprint(st) {
	const r = (v) => Math.round(v * 1e6) / 1e6;
	return JSON.stringify([st.tick, st.elapsedTicks, st.bossTimeTicks, st.rng, st.status, st.classId, st.practice,
		st.hero.level, st.hero.xp, st.p.burstLeft, r(st.p.x), r(st.p.y), r(st.p.hp), r(st.p.low), r(st.p.mp),
		st.enemies.map((e) => [e.id, r(e.x), r(e.y), r(e.hp), e.cd, e.tele, e.scd, e.mode, e.modeT, e.ward, e.active]),
		st.sealed, st.roomLeft,
		st.bullets.length, st.bullets.map((b) => [r(b.x), r(b.y)]).slice(0, 40),
		st.bags.map((b) => b.drops.join(",")), st.pickups.length, st.shield && [r(st.shield.x), r(st.shield.y), st.shield.until], st.slowUntil,
		st.p.abilityCd, st.p.potionCd, st.p.counterUntil, st.p.guardUntil, st.p.empower, (st.starfalls || []).map((f) => [r(f.x), r(f.y), f.at])]);
}
